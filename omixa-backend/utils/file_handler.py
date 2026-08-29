"""
Handles everything to do with temporary, per-job storage.

Omixa V1 has no database, so a "job" is just a folder:

    temp/
    └── <job_id>/
        ├── source.csv        (or .xlsx)
        └── cleaned.csv        (written after processing)

job_id is a uuid4 string. Once the user downloads the cleaned file
(or JOB_TTL_SECONDS passes), the whole folder is deleted.
"""

import os
import time
import uuid
from typing import Optional
from werkzeug.utils import secure_filename

from config import Config


def allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS
    )


def create_job_dir() -> str:
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(Config.TEMP_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    return job_id


def job_dir_path(job_id: str) -> str:
    return os.path.join(Config.TEMP_DIR, job_id)


def save_upload(file_storage, job_id: str) -> str:
    """Saves the incoming file as source.<ext> inside the job dir."""
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    dest = os.path.join(job_dir_path(job_id), f"source.{ext}")
    file_storage.save(dest)
    return dest


def find_source_file(job_id: str) -> Optional[str]:
    d = job_dir_path(job_id)
    if not os.path.isdir(d):
        return None
    for name in os.listdir(d):
        if name.startswith("source."):
            return os.path.join(d, name)
    return None


def cleaned_file_path(job_id: str, ext: str) -> str:
    return os.path.join(job_dir_path(job_id), f"cleaned.{ext}")


def delete_job(job_id: str) -> None:
    """Discards all temp data for a job. Called after download,
    and by the periodic sweep for abandoned jobs."""
    d = job_dir_path(job_id)
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        os.remove(os.path.join(d, name))
    os.rmdir(d)


def sweep_expired_jobs() -> None:
    """Deletes any job folder older than JOB_TTL_SECONDS.
    Call this on a schedule (e.g. APScheduler) or at request time."""
    now = time.time()
    if not os.path.isdir(Config.TEMP_DIR):
        return
    for job_id in os.listdir(Config.TEMP_DIR):
        d = job_dir_path(job_id)
        if os.path.isdir(d) and (now - os.path.getmtime(d)) > Config.JOB_TTL_SECONDS:
            delete_job(job_id)
