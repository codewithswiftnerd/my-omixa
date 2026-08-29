from flask import Blueprint, request, jsonify

from utils.file_handler import allowed_file, create_job_dir, save_upload

upload_bp = Blueprint("upload", __name__)


@upload_bp.post("/")
def upload_file():
    """
    Frontend contract:

    Request:  multipart/form-data, field name "file"
    Response: { "job_id": "...", "filename": "patients.xlsx", "status": "uploaded" }
              or { "error": "..." }, 400
    """
    if "file" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type. Use CSV or Excel."}), 400

    job_id = create_job_dir()
    save_upload(file, job_id)

    return jsonify({
        "job_id": job_id,
        "filename": file.filename,
        "status": "uploaded",
    }), 201
