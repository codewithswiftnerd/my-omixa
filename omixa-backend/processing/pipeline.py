"""
Orchestrates: Read -> Clean -> Export

This file doesn't know the details of any single cleaning rule —
that lives in cleaning/rules.py, which is Misumi's spec turned into
code. This file just wires the steps together in order.
"""

import os
from typing import Optional, List
import pandas as pd

from utils.file_handler import find_source_file, cleaned_file_path
from cleaning.rules import apply_rules
from cleaning.quality_report import generate_report
from export.exporter import export_dataframe


def read_source(path: str) -> pd.DataFrame:
    ext = path.rsplit(".", 1)[1].lower()
    if ext == "csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def run_pipeline(job_id: str, rules: Optional[List[str]] = None) -> dict:
    """
    Returns a summary dict the frontend can display, e.g.:
        {
          "rows_in": 1000,
          "rows_out": 940,
          "rules_applied": ["missing_values", "duplicates"],
          "changes": {"duplicates_removed": 40, "missing_values_fixed": 20}
        }
    """
    source_path = find_source_file(job_id)
    if not source_path:
        raise FileNotFoundError("No source file found for this job")

    df = read_source(source_path)
    rows_in = len(df)

    cleaned_df, change_log = apply_rules(df, rules=rules)

    rows_out = len(cleaned_df)

    ext = source_path.rsplit(".", 1)[1].lower()
    out_path = cleaned_file_path(job_id, ext)
    export_dataframe(cleaned_df, out_path, ext=ext)

    # Re-run the same read-only quality checks against the cleaned data
    # so the frontend can show a before/after score, not just a list of
    # "N cells changed" counts.
    post_report = generate_report(cleaned_df)

    return {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rules_applied": change_log["rules_applied"],
        "changes": change_log["changes"],
        "details": change_log.get("details", {}),
        "quality_report": post_report,
    }
