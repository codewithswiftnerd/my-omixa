from flask import Blueprint, request, jsonify

from utils.file_handler import find_source_file, job_dir_path
from processing.pipeline import run_pipeline

process_bp = Blueprint("process", __name__)


@process_bp.post("/<job_id>")
def process_file(job_id):
    """
    Frontend contract:

    Request:  POST /api/process/<job_id>
              optional JSON body: { "rules": ["missing_values", "duplicates", "formatting"] }
    Response: { "job_id": "...", "status": "completed", "summary": {...} }
              or { "status": "failed", "error": "..." }, 422
    """
    if not job_dir_path(job_id) or not find_source_file(job_id):
        return jsonify({"error": "Unknown job_id or no uploaded file found"}), 404

    rules = (request.get_json(silent=True) or {}).get("rules")

    try:
        summary = run_pipeline(job_id, rules=rules)
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 422

    return jsonify({
        "job_id": job_id,
        "status": "completed",
        "summary": summary,
    }), 200
