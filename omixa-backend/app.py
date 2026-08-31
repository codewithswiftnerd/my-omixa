"""
Omixa V1 Backend — Entry Point

Pipeline:
    Upload -> Read -> Clean -> Export -> Download -> Discard

No database. No persistent storage. Everything lives in TEMP_DIR
for the lifetime of a single job, then gets deleted.
"""

from flask import Flask, send_from_directory
from flask_cors import CORS

from config import Config
from routes.upload import upload_bp
from routes.process import process_bp
from routes.download import download_bp
from routes.report import report_bp


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config.from_object(Config)

    CORS(app, expose_headers=["Content-Disposition"])

    app.register_blueprint(upload_bp, url_prefix="/api/upload")
    app.register_blueprint(process_bp, url_prefix="/api/process")
    app.register_blueprint(download_bp, url_prefix="/api/download")
    app.register_blueprint(report_bp, url_prefix="/api/report")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "omixa-backend"}

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
