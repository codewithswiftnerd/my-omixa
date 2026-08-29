from flask import Blueprint, jsonify

from utils.file_handler import find_source_file
from processing.pipeline import read_source
from cleaning.quality_report import generate_report

report_bp = Blueprint("report", __name__)


@report_bp.get("/<job_id>")
def get_report(job_id):
    """
    Frontend contract:

    Request:  GET /api/report/<job_id>
    Response: { "job_id": "...", "report": {...} }
              or { "error": "..." }, 404

    Read-only: analyzes the uploaded file as-is. Does not run any
    cleaning rule and does not write anything to the job folder.
    """
    source_path = find_source_file(job_id)
    if not source_path:
        return jsonify({"error": "Unknown job_id or no uploaded file found"}), 404

    try:
        df = read_source(source_path)
    except Exception as e:
        return jsonify({"error": f"Could not read file: {e}"}), 422

    return jsonify({
        "job_id": job_id,
        "report": generate_report(df),
    }), 200
