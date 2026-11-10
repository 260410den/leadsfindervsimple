import logging

from flask import Flask, jsonify, render_template, request

from scraper import LeadScraper, WebsiteAccessDeniedError

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
logging.basicConfig(level=logging.INFO)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Kirim data JSON yang valid."}), 400

    url = data.get("url")
    if not isinstance(url, str) or not url.strip():
        return jsonify({"error": "URL tidak boleh kosong."}), 400

    try:
        result = LeadScraper().scrape_lead(url)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except WebsiteAccessDeniedError as error:
        return jsonify({"error": str(error)}), 403
    except Exception:
        app.logger.exception("Gagal memproses URL yang diminta.")
        return jsonify({"error": "Terjadi kesalahan saat memproses website."}), 500

    return jsonify([result])


if __name__ == "__main__":
    app.run(debug=False)
