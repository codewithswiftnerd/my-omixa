import os
import mimetypes
from io import BytesIO
from flask import Blueprint, send_file, jsonify

from utils.file_handler import job_dir_path, delete_job

download_bp = Blueprint("download", __name__)


@download_bp.get("/<job_id>")
def download_file(job_id):
    """
    Frontend contract:

    Request:  GET /api/download/<job_id>
    Response: the cleaned file as an attachment, then the job's
              temp data is discarded (no database, no persistence).
    """
    d = job_dir_path(job_id)
    dir_exists = os.path.isdir(d)
    listing = os.listdir(d) if dir_exists else []

    # Debug trace — prints to the terminal running `python app.py` so a
    # failed download is diagnosable from the server side, not just a
    # generic error in the browser. Safe to remove once this is stable.
    print(f"[download] job_id={job_id} dir={d} exists={dir_exists} contents={listing}")

    cleaned = None
    for name in listing:
        if name.startswith("cleaned."):
            cleaned = os.path.join(d, name)
            break

    if not cleaned:
        reason = (
            "job folder does not exist (wrong/expired job_id, or the server "
            "restarted and this id is from a previous run)"
            if not dir_exists
            else f"job folder exists but has no cleaned.* file — contents: {listing}"
        )
        return jsonify({"error": "No cleaned file ready for this job", "detail": reason}), 404

    filename = os.path.basename(cleaned)
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # Read the file into memory BEFORE deleting the job folder. Deleting
    # it while send_file still holds the path open used to blow up with
    # a 500 on Windows ("file in use by another process") — os.remove()
    # can't touch a file another process/handle still has open there,
    # unlike POSIX where an unlinked-but-open file keeps working fine.
    # Reading it into a BytesIO first means the bytes are already ours
    # by the time delete_job() runs, so there's nothing left to race.
    with open(cleaned, "rb") as f:
        data = f.read()

    # Discard temp data now that the file is safely in memory.
    delete_job(job_id)

    return send_file(
        BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype=mimetype,
    )
