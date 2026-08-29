import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # Where uploaded/cleaned files live temporarily. Nothing here is
    # meant to survive past a job's lifecycle — see utils/file_handler.py
    TEMP_DIR = os.path.join(BASE_DIR, "temp")

    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB upload cap for V1

    ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls"}

    # How long a job's temp files are allowed to live before cleanup
    # sweeps them, even if the user never hits /download
    JOB_TTL_SECONDS = 60 * 30  # 30 minutes
