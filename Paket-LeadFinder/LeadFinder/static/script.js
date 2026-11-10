const form = document.getElementById("search-form");
const urlInput = document.getElementById("url-input");
const searchButton = document.getElementById("btn-cari");
const resultBody = document.getElementById("result-body");
const resultCount = document.getElementById("result-count");
const statusMessage = document.getElementById("status-message");
const preview = document.getElementById("site-preview");
const previewDomain = document.getElementById("preview-domain");
const previewHint = document.getElementById("preview-hint");
const openSite = document.getElementById("open-site");
const openInstagram = document.getElementById("open-instagram");

function updateInstagramLink(value) {
    if (!value) {
        openInstagram.hidden = true;
        openInstagram.removeAttribute("href");
        return;
    }
    try {
        const candidate = /^https?:\/\//i.test(value) ? value : `https://${value}`;
        const parsed = new URL(candidate);
        if (parsed.protocol !== "https:" || !(parsed.hostname === "instagram.com" || parsed.hostname.endsWith(".instagram.com"))) {
            openInstagram.hidden = true;
            return;
        }
        openInstagram.href = parsed.href;
        openInstagram.hidden = false;
    } catch {
        openInstagram.hidden = true;
    }
}

function updatePreview(rawUrl) {
    const candidate = /^https?:\/\//i.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
    try {
        const parsed = new URL(candidate);
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error("URL tidak valid");
        preview.src = parsed.href;
        openSite.href = parsed.href;
        openSite.hidden = false;
        previewDomain.textContent = parsed.hostname;
        previewHint.textContent = "Halaman ditampilkan langsung. Jika situs menolak panel ini, buka website di browser.";
        if (parsed.hostname === "instagram.com" || parsed.hostname.endsWith(".instagram.com")) {
            updateInstagramLink(parsed.href);
        } else {
            updateInstagramLink(null);
        }
    } catch {
        previewDomain.textContent = "URL tidak valid";
    }
}

function renderResults(results) {
    resultBody.replaceChildren();
    const lead = results[0];
    if (lead && lead.telepon && lead.telepon !== "-") {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.textContent = lead.telepon;
        row.appendChild(cell);
        resultBody.appendChild(row);
    }
    resultCount.textContent = resultBody.children.length ? "1 hasil" : "0 hasil";
    return lead;
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = urlInput.value.trim();
    if (!url) {
        statusMessage.textContent = "Silakan masukkan URL website.";
        urlInput.focus();
        return;
    }
    updatePreview(url);
    urlInput.blur();
    statusMessage.focus({ preventScroll: true });
    searchButton.disabled = true;
    searchButton.textContent = "Mencari...";
    statusMessage.textContent = "Sedang memeriksa website. Mohon tunggu.";
    resultBody.replaceChildren();
    resultCount.textContent = "—";
    try {
        const response = await fetch("/scrape", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Server gagal memproses URL.");
        if (!Array.isArray(payload)) throw new Error("Format hasil dari server tidak valid.");
        const lead = renderResults(payload);
        if (lead && lead.instagram) updateInstagramLink(lead.instagram);
        statusMessage.textContent = lead ? lead.status_whatsapp || "Pencarian selesai." : "Tidak ada data yang ditemukan.";
    } catch (error) {
        statusMessage.textContent = error.message || "Terjadi kesalahan saat mencari data.";
        resultCount.textContent = "0 hasil";
    } finally {
        searchButton.disabled = false;
        searchButton.textContent = "Cari data";
        statusMessage.focus({ preventScroll: true });
    }
});
async function copyPhoneNumber() {
    const cell = resultBody.querySelector("td");
    const phone = cell?.textContent?.trim();
    if (!phone) {
        statusMessage.textContent = "Belum ada nomor untuk disalin.";
        return;
    }
    try {
        await navigator.clipboard.writeText(phone);
    } catch {
        const helper = document.createElement("textarea");
        helper.value = phone;
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        const copied = document.execCommand("copy");
        helper.remove();
        if (!copied) {
            statusMessage.textContent = "Gagal menyalin nomor. Silakan salin manual.";
            return;
        }
    }
    statusMessage.textContent = `Nomor ${phone} disalin.`;
}

document.addEventListener("keydown", (event) => {
    if (event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || target.closest("input, textarea, select, [contenteditable='true']"))) return;

    const key = event.key.toLowerCase();
    if (!["i", "o", "c"].includes(key)) return;
    event.preventDefault();

    if (key === "i") {
        if (!openInstagram.hidden) openInstagram.click();
        else statusMessage.textContent = "Tautan Instagram belum ditemukan.";
    } else if (key === "o") {
        if (!openSite.hidden) openSite.click();
        else statusMessage.textContent = "Masukkan URL website terlebih dahulu.";
    } else {
        copyPhoneNumber();
    }
});
