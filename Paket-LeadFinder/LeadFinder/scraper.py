import io
import json
import logging
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)
INDONESIAN_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?62|0)(?:[\s().-]*\d){7,13}(?!\d)")
PHONE_LABEL_PATTERN = re.compile(
    r"(?:kontak(?:\s+whatsapp)?|contact(?:\s+us)?|hubungi(?:\s+kami)?|"
    r"telepon|telp|phone(?:\s+number)?|whatsapp|wa)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
CONTACT_KEYWORDS = ("contact", "kontak", "about", "tentang", "hubungi")
FALLBACK_CONTACT_PATHS = ("/contact", "/kontak", "/about", "/contact-us")
WHATSAPP_HOSTS = {"wa.me", "api.whatsapp.com", "web.whatsapp.com", "www.whatsapp.com", "whatsapp.com"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGES_PER_PAGE = 4


class WebsiteAccessDeniedError(Exception):
    pass


class LeadScraper:
    def __init__(self, timeout=8):
        self.timeout = min(float(timeout), 8.0)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; LeadFinder/1.0)",
            "Accept": "text/html,application/xhtml+xml,image/*;q=0.8",
            "Accept-Language": "id,en;q=0.8",
        })

    def _get_soup(self, url, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, url
        timeout = min(self.timeout, remaining)
        try:
            response = self.session.get(url, timeout=(min(3.0, timeout), timeout), allow_redirects=True)
            if response.status_code in (401, 403):
                server = response.headers.get("Server", "").lower()
                challenge = "cloudflare" in server or "just a moment" in response.text[:2000].lower() or "cf-chl-" in response.text[:5000].lower()
                detail = "dilindungi challenge anti-bot" if challenge else f"menolak permintaan (HTTP {response.status_code})"
                raise WebsiteAccessDeniedError(
                    f"Website {detail}. Scraper tidak dapat mengambil data tanpa izin atau akses resmi dari pemilik website."
                )
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser"), response.url
        except WebsiteAccessDeniedError:
            raise
        except requests.RequestException as error:
            LOGGER.warning("Tidak dapat mengambil halaman %s: %s", url, error)
            return None, url

    @staticmethod
    def normalize_url(url):
        value = url.strip()
        if not value:
            raise ValueError("URL tidak boleh kosong.")
        explicit_scheme = re.match(r"^[a-z][a-z0-9+.-]*://", value, re.IGNORECASE)
        if explicit_scheme and not value.lower().startswith(("http://", "https://")):
            raise ValueError("Masukkan URL website dengan protokol HTTP atau HTTPS.")
        if not explicit_scheme:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise ValueError("Masukkan URL website dengan protokol HTTP atau HTTPS.")
        try:
            parsed.port
        except ValueError as error:
            raise ValueError("Port pada URL tidak valid.") from error
        return urlunparse(parsed._replace(scheme=parsed.scheme.lower()))

    @staticmethod
    def _clean_phone(value):
        digits = re.sub(r"\D", "", value)
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        if not 10 <= len(digits) <= 15 or not digits.startswith("62"):
            return None
        return digits

    @classmethod
    def _whatsapp_link_numbers(cls, href):
        absolute = urljoin("https://placeholder.invalid/", href)
        parsed = urlparse(absolute)
        host = (parsed.hostname or "").lower()
        is_whatsapp = host in WHATSAPP_HOSTS or host.endswith(".whatsapp.com")
        if not is_whatsapp:
            return []
        values = parse_qs(parsed.query).get("phone", [])
        if host == "wa.me":
            first_path = parsed.path.strip("/").split("/", 1)[0]
            if first_path and first_path.lower() not in {"message", ""}:
                values.insert(0, first_path)
        results = []
        for value in values:
            phone = cls._clean_phone(value)
            if phone and phone not in results:
                results.append(phone)
        return results

    def extract_phone_candidates(self, soup, text):
        candidates = {}
        for match in INDONESIAN_PHONE_PATTERN.finditer(text):
            phone = self._clean_phone(match.group())
            if not phone:
                continue
            before = text[max(0, match.start() - 80):match.start()]
            label_match = PHONE_LABEL_PATTERN.search(before)
            priority = 1 if label_match and ("whatsapp" in label_match.group(0).lower() or "wa" in label_match.group(0).lower()) else (2 if label_match else 4)
            candidates[phone] = min(candidates.get(phone, 99), priority)

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            linked_numbers = self._whatsapp_link_numbers(href)
            if not linked_numbers:
                continue
            label = " ".join((anchor.get_text(" ", strip=True), str(anchor.get("aria-label", "")), str(anchor.get("title", "")))).lower()
            priority = 0 if any(word in label for word in ("whatsapp", "hubungi", "chat", "wa")) else 1
            for phone in linked_numbers:
                candidates[phone] = min(candidates.get(phone, 99), priority)

        phone_fields = {"telephone", "phone", "mobile", "whatsapp", "whatsappnumber", "contactnumber"}
        def collect_structured_phones(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key.lower() in phone_fields:
                        values = value if isinstance(value, list) else [value]
                        for item in values:
                            if isinstance(item, str):
                                for match in INDONESIAN_PHONE_PATTERN.finditer(item):
                                    phone = self._clean_phone(match.group())
                                    if phone:
                                        candidates[phone] = min(candidates.get(phone, 99), 2)
                    else:
                        collect_structured_phones(value)
            elif isinstance(node, list):
                for item in node:
                    collect_structured_phones(item)

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                collect_structured_phones(json.loads(script.string or script.get_text()))
            except (json.JSONDecodeError, TypeError):
                continue

        return sorted(((priority, phone) for phone, priority in candidates.items()), key=lambda item: item[0])
    def _ocr_phone_candidates(self, soup, page_url, deadline):
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            LOGGER.info("OCR tidak tersedia; pasang Pillow dan pytesseract untuk membaca nomor pada gambar.")
            return []

        page_host = (urlparse(page_url).hostname or "").lower()
        found = []
        for image in soup.find_all("img", src=True)[:MAX_IMAGES_PER_PAGE]:
            image_url = urljoin(page_url, image["src"])
            parsed = urlparse(image_url)
            if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() != page_host:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                with self.session.get(image_url, stream=True, timeout=(2, min(3, remaining))) as response:
                    if not response.ok or not response.headers.get("Content-Type", "").lower().startswith("image/"):
                        continue
                    length = response.headers.get("Content-Length")
                    if length and int(length) > MAX_IMAGE_BYTES:
                        continue
                    data = bytearray()
                    for chunk in response.iter_content(16384):
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE_BYTES:
                            break
                    if not data or len(data) > MAX_IMAGE_BYTES:
                        continue
                text = pytesseract.image_to_string(Image.open(io.BytesIO(data)), lang="eng")
                for match in INDONESIAN_PHONE_PATTERN.finditer(text):
                    phone = self._clean_phone(match.group())
                    if phone and phone not in [number for _, number in found]:
                        found.append((3, phone))
            except Exception as error:
                LOGGER.debug("OCR gambar dilewati (%s): %s", image_url, error)
        return found

    @staticmethod
    def _is_instagram_url(url):
        host = (urlparse(url).hostname or "").lower()
        return host == "instagram.com" or host.endswith(".instagram.com")

    @classmethod
    def extract_instagram_link(cls, soup, page_url):
        ignored_paths = {"accounts", "about", "direct", "explore", "p", "reel", "reels", "share", "stories"}
        for anchor in soup.find_all("a", href=True):
            candidate = urljoin(page_url, anchor["href"].strip())
            parsed = urlparse(candidate)
            if not cls._is_instagram_url(candidate) or not parsed.path.strip("/"):
                continue
            first_part = parsed.path.strip("/").split("/", 1)[0].lower()
            if first_part in ignored_paths:
                continue
            return urlunparse(parsed._replace(scheme="https", fragment=""))
        return None
    @staticmethod
    def extract_company_name(soup, fallback_url):
        for selector in ("h1", "title"):
            element = soup.find(selector)
            if element:
                name = element.get_text(" ", strip=True)
                if name:
                    return name
        return urlparse(fallback_url).hostname or "-"

    @staticmethod
    def _same_host(url, base_url):
        candidate, base = urlparse(url), urlparse(base_url)
        return candidate.scheme.lower() in ("http", "https") and candidate.hostname and candidate.hostname.lower() == (base.hostname or "").lower()

    def find_contact_pages(self, base_url, soup):
        pages, seen = [], {base_url.split("#", 1)[0]}
        for anchor in soup.find_all("a", href=True):
            href, label = anchor["href"].strip(), anchor.get_text(" ", strip=True).lower()
            if not any(word in href.lower() or word in label for word in CONTACT_KEYWORDS):
                continue
            page_url = urljoin(base_url, href).split("#", 1)[0]
            if self._same_host(page_url, base_url) and page_url not in seen:
                seen.add(page_url)
                pages.append(page_url)
                if len(pages) == 2:
                    return pages
        for path in FALLBACK_CONTACT_PATHS:
            page_url = urljoin(base_url, path)
            if page_url not in seen:
                seen.add(page_url)
                pages.append(page_url)
                if len(pages) == 2:
                    break
        return pages

    def scrape_lead(self, target_url):
        normalized_url = self.normalize_url(target_url)
        deadline = time.monotonic() + self.timeout
        homepage, homepage_url = self._get_soup(normalized_url, deadline)
        if homepage is None:
            return {"nama": "Website tidak dapat diakses", "telepon": "-", "status_whatsapp": "Nomor WhatsApp tidak ditemukan.", "instagram": normalized_url if self._is_instagram_url(normalized_url) else None}

        name = self.extract_company_name(homepage, homepage_url)
        candidates = {}
        instagram_url = self.extract_instagram_link(homepage, homepage_url)
        if not instagram_url and self._is_instagram_url(normalized_url):
            instagram_url = normalized_url
        pages_to_scan = [(homepage, homepage_url)]
        for page_url in self.find_contact_pages(homepage_url, homepage):
            if time.monotonic() >= deadline:
                break
            try:
                page, final_url = self._get_soup(page_url, deadline)
            except WebsiteAccessDeniedError as error:
                LOGGER.warning("Halaman kontak %s tidak dapat diakses: %s", page_url, error)
                continue
            if page is not None:
                if not instagram_url:
                    instagram_url = self.extract_instagram_link(page, final_url)
                pages_to_scan.append((page, final_url))

        for page, page_url in pages_to_scan:
            page_text = page.get_text(" ", strip=True)
            for priority, phone in self.extract_phone_candidates(page, page_text):
                candidates[phone] = min(candidates.get(phone, 99), priority)
            for priority, phone in self._ocr_phone_candidates(page, page_url, deadline):
                candidates[phone] = min(candidates.get(phone, 99), priority)

        if not candidates:
            return {"nama": name, "telepon": "-", "status_whatsapp": "Nomor WhatsApp tidak ditemukan di halaman, tautan, atau gambar yang terbaca.", "instagram": instagram_url}
        phone, priority = min(candidates.items(), key=lambda item: item[1])
        source = "tautan WhatsApp" if priority <= 1 else ("teks halaman" if priority <= 2 else "gambar (OCR)")
        status = f"Ditemukan dari {source}. Status aktif akun tidak dapat dipastikan dari website."
        return {"nama": name, "telepon": "+" + phone, "status_whatsapp": status, "instagram": instagram_url}


def scrape_website(url):
    return LeadScraper().scrape_lead(url)
