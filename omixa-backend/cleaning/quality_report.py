"""
Data Quality Report

Read-only diagnostics run on the *uploaded* file, before any cleaning
rule touches it. Nothing here mutates the dataframe — this only
describes what's wrong and what the matching rule (if any) would do
about it, so the user can decide before they click "Clean my data".

Severity levels:
    critical -> auto-fix would be unsafe/impossible; needs a human
    warning  -> auto-fixable but worth knowing about (or not covered
                by V1 rules yet)
    info     -> minor / cosmetic, or a heads-up with no rule attached
"""

from __future__ import annotations
import pandas as pd

from cleaning import detectors

HIGH_MISSING_THRESHOLD = 70
CONSTANT_COLUMN_MAX_ROWS = 1  # nunique <= this (ignoring NaN) => constant


def _missing_findings(df: pd.DataFrame, total_rows: int) -> list[dict]:
    findings = []
    for col in df.columns:
        missing = int(df[col].isna().sum())
        if not missing:
            continue
        pct = round((missing / total_rows) * 100, 2) if total_rows else 0.0
        numeric = pd.api.types.is_numeric_dtype(df[col])

        if pct > HIGH_MISSING_THRESHOLD:
            findings.append({
                "column": col, "issue": "high_missingness", "severity": "critical",
                "detail": f"{pct}% missing ({missing} of {total_rows} rows).",
                "suggestion": "Too sparse to fill reliably — this column is left "
                              "untouched and flagged for manual review rather than auto-filled.",
            })
        else:
            fill = "the column median" if numeric else '"Unknown"'
            findings.append({
                "column": col, "issue": "missing_values",
                "severity": "warning" if pct > 20 else "info",
                "detail": f"{pct}% missing ({missing} rows).",
                "suggestion": f"The 'Fill gaps' rule will fill these with {fill}.",
            })
    return findings


def _duplicate_findings(df: pd.DataFrame, total_rows: int) -> list[dict]:
    dup_count = int(df.duplicated(keep="first").sum())
    if not dup_count:
        return []
    pct = round((dup_count / total_rows) * 100, 2) if total_rows else 0.0
    severity = "critical" if pct > 25 else ("warning" if pct > 5 else "info")
    return [{
        "column": None, "issue": "duplicate_rows", "severity": severity,
        "detail": f"{dup_count} exact duplicate rows ({pct}% of the file).",
        "suggestion": "The 'Remove duplicates' rule will drop these, keeping the first occurrence.",
    }]


def _formatting_findings(df: pd.DataFrame) -> list[dict]:
    findings = []
    for col in df.select_dtypes(include=["object", "string"]).columns:
        original = df[col].astype("string")
        cleaned = original.str.strip().str.replace(r"\s+", " ", regex=True)
        diff = int(((original != cleaned) & original.notna()).sum())
        if diff:
            findings.append({
                "column": col, "issue": "whitespace", "severity": "info",
                "detail": f"{diff} values have extra or trailing whitespace.",
                "suggestion": "The 'Fix formatting' rule will trim and collapse this automatically.",
            })
    return findings


def _outlier_findings(df: pd.DataFrame) -> list[dict]:
    findings = []
    for col in df.select_dtypes(include="number").columns:
        series = df[col].dropna()
        if len(series) < 10:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = int(((series < lo) | (series > hi)).sum())
        if outliers:
            findings.append({
                "column": col, "issue": "potential_outliers", "severity": "info",
                "detail": f"{outliers} values fall outside the typical range "
                          f"({round(lo, 2)} to {round(hi, 2)}).",
                "suggestion": "Not auto-fixed — worth a manual look before trusting "
                              "averages or totals on this column.",
            })
    return findings


def _inconsistent_category_findings(df: pd.DataFrame, total_rows: int) -> list[dict]:
    findings = []
    for col in df.select_dtypes(include=["object", "string"]).columns:
        values = df[col].dropna().astype(str)
        nunique = values.nunique()
        if nunique < 2 or nunique > 50 or nunique > total_rows * 0.5:
            continue
        groups: dict[str, set] = {}
        for v in values.unique():
            key = " ".join(v.split()).lower()
            groups.setdefault(key, set()).add(v)
        variants = [g for g in groups.values() if len(g) > 1]
        if variants:
            examples = ", ".join(sorted(next(iter(variants)))[:3])
            findings.append({
                "column": col, "issue": "inconsistent_categories", "severity": "warning",
                "detail": f"{len(variants)} value(s) appear under multiple spellings/casings, "
                          f"e.g. {examples}.",
                "suggestion": "Not covered by a V1 rule — standardize manually, or flag it "
                              "if a category-normalization rule would help.",
            })
    return findings


def _constant_column_findings(df: pd.DataFrame) -> list[dict]:
    findings = []
    for col in df.columns:
        non_null = df[col].dropna()
        if len(non_null) and non_null.nunique() <= CONSTANT_COLUMN_MAX_ROWS:
            findings.append({
                "column": col, "issue": "constant_column", "severity": "info",
                "detail": f'Every non-empty value is "{non_null.iloc[0]}".',
                "suggestion": "Not auto-fixed — this column may not be worth keeping.",
            })
    return findings


def _email_validation_findings(df: pd.DataFrame) -> list[dict]:
    """Detect-only: flags values in an email-shaped column that don't
    look like valid emails. Never rewrites or guesses a corrected
    address — a malformed email could be missing a character anywhere,
    so only a human can safely fix it."""
    findings = []
    for col in df.select_dtypes(include=["object", "string"]).columns:
        series = df[col]
        if not detectors.is_email_column(str(col), series):
            continue
        values = series.dropna().astype(str)
        if values.empty:
            continue
        invalid = int((~values.str.match(detectors.EMAIL_RE)).sum())
        if invalid:
            findings.append({
                "column": col, "issue": "invalid_email_format", "severity": "warning",
                "detail": f"{invalid} value(s) don't look like valid email addresses.",
                "suggestion": "Not auto-fixed — verify and correct these manually.",
            })
    return findings


def _phone_validation_findings(df: pd.DataFrame) -> list[dict]:
    """Detect-only: flags phone-column values whose digit count is
    outside a broad plausible range (7-15 digits, roughly the E.164
    bounds). Doesn't attempt to fix formatting or add country codes —
    phone conventions vary too much by country to guess safely."""
    findings = []
    for col in df.select_dtypes(include=["object", "string"]).columns:
        if not detectors.is_phone_column(str(col)):
            continue
        values = df[col].dropna().astype(str)
        if values.empty:
            continue
        digit_counts = values.str.replace(r"\D", "", regex=True).str.len()
        suspicious = int(((digit_counts < 7) | (digit_counts > 15)).sum())
        if suspicious:
            findings.append({
                "column": col, "issue": "suspicious_phone_format", "severity": "info",
                "detail": f"{suspicious} value(s) have an unusual number of digits for a phone number.",
                "suggestion": "Not auto-fixed — worth a manual check.",
            })
    return findings


def _mixed_type_column_findings(df: pd.DataFrame) -> list[dict]:
    """Detect-only: a text column where a meaningful chunk of values
    parse as numbers and the rest don't usually means numeric data got
    mixed with free-text notes/codes. Not auto-converted since forcing
    a type would either invent numbers or lose the text values."""
    findings = []
    for col in df.select_dtypes(include=["object", "string"]).columns:
        values = df[col].dropna().astype(str)
        if len(values) < 10:
            continue
        cleaned = values.map(detectors.strip_numeric_noise)
        parses = cleaned.map(detectors.try_parse_float).notna()
        ratio = parses.mean()
        if 0.05 < ratio < 0.95:
            findings.append({
                "column": col, "issue": "mixed_data_types", "severity": "warning",
                "detail": f"{int(parses.sum())} of {len(values)} non-empty values look numeric; "
                          f"the rest look like text.",
                "suggestion": "Not auto-fixed — confirm whether this column should be numeric "
                              "before relying on it for calculations.",
            })
    return findings


def _date_format_review_findings(df: pd.DataFrame) -> list[dict]:
    """Detect-only: a date-shaped column where day-first vs
    month-first parsing genuinely disagree (e.g. '03/04/2024'). The
    'Standardize dates' rule deliberately skips these rather than
    guessing — this finding is what tells the user why."""
    findings = []
    for col in df.select_dtypes(include=["object", "string"]).columns:
        series = df[col]
        if not detectors.is_probable_date_column(str(col), series):
            continue
        if detectors.unambiguous_date_parse(series) is not None:
            continue  # the rule already handles (or will handle) this one safely
        findings.append({
            "column": col, "issue": "ambiguous_date_format", "severity": "warning",
            "detail": "Values look like dates, but it's not possible to tell day-first from "
                      "month-first formatting without guessing.",
            "suggestion": "Not auto-fixed — confirm the intended format before standardizing.",
        })
    return findings


def _possible_duplicate_record_findings(df: pd.DataFrame, total_rows: int) -> list[dict]:
    """Detect-only: rows that are identical across every column
    EXCEPT one are often the same real-world record with one field
    edited, mistyped, or updated — not caught by exact-duplicate
    removal. Reports the single best candidate column rather than
    every possibility, to keep this readable. Skipped for very wide
    or very large files to keep the check cheap."""
    if total_rows < 2 or len(df.columns) < 2 or len(df.columns) > 40 or total_rows > 50000:
        return []

    exact_dupes = df.duplicated(keep=False)
    best_col, best_count = None, 0
    for col in df.columns:
        other_cols = [c for c in df.columns if c != col]
        near_dupes = df.duplicated(subset=other_cols, keep=False)
        candidates = int((near_dupes & ~exact_dupes).sum())
        if candidates > best_count:
            best_col, best_count = col, candidates

    if not best_count:
        return []

    pct = round((best_count / total_rows) * 100, 2) if total_rows else 0.0
    return [{
        "column": best_col, "issue": "possible_duplicate_records",
        "severity": "warning" if pct > 5 else "info",
        "detail": f"{best_count} row(s) match another row on every column except '{best_col}'.",
        "suggestion": "Not auto-fixed — these look like possible duplicate records; review "
                      "before deciding whether to merge or remove them.",
    }]


_SEVERITY_WEIGHT = {"critical": 15, "warning": 6, "info": 2}


def generate_report(df: pd.DataFrame) -> dict:
    total_rows = len(df)
    findings: list[dict] = []
    findings += _missing_findings(df, total_rows)
    findings += _duplicate_findings(df, total_rows)
    findings += _formatting_findings(df)
    findings += _outlier_findings(df)
    findings += _inconsistent_category_findings(df, total_rows)
    findings += _constant_column_findings(df)
    findings += _email_validation_findings(df)
    findings += _phone_validation_findings(df)
    findings += _mixed_type_column_findings(df)
    findings += _date_format_review_findings(df)
    findings += _possible_duplicate_record_findings(df, total_rows)

    counts = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f["severity"]] += 1

    penalty = sum(_SEVERITY_WEIGHT[f["severity"]] for f in findings)
    score = max(0, 100 - penalty)

    return {
        "score": score,
        "row_count": total_rows,
        "column_count": len(df.columns),
        "counts": counts,
        "findings": findings,
    }
