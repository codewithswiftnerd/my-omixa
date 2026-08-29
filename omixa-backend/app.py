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

    # CORS is still enabled for the case where the frontend is served
    # from somewhere else (e.g. the real product frontend on another
    # origin during dev). It's a no-op when the console below is
    # loaded from this same Flask app, since same-origin requests
    # don't need CORS at all.
    CORS(app)

    app.register_blueprint(upload_bp, url_prefix="/api/upload")
    app.register_blueprint(process_bp, url_prefix="/api/process")
    app.register_blueprint(download_bp, url_prefix="/api/download")
    app.register_blueprint(report_bp, url_prefix="/api/report")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "omixa-backend"}

    # Serves static/index.html (the engine test console) at the root
    # URL, so `python app.py` + open http://localhost:5000/ gives you
    # a working frontend and backend from one process, one folder.
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
