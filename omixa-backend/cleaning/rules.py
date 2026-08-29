"""
Cleaning Rules

Started from the V1 locked spec (missing values, exact duplicates,
formatting/whitespace) and grown with a second wave of rules that
follow the same philosophy: auto-fix only when the correction is
unambiguous, otherwise leave the data untouched and let
cleaning/quality_report.py flag it for a human to look at. Every
rule keeps the signature the pipeline already expects:

    (df: pd.DataFrame) -> (pd.DataFrame, int)   # cleaned df, count changed

so the pipeline can log exactly what happened for the summary the
frontend shows the user ("Removed 40 duplicate rows", etc).

Anything the spec says should be "flagged for review" instead of
auto-fixed is deliberately left untouched in the data (so it's still
visible/inspectable) and reported separately via LAST_RUN_DETAILS
rather than silently changed — see each function's docstring.
"""

from __future__ import annotations
from typing import Optional, List, Tuple
import re
import pandas as pd

from cleaning import detectors

# Order matters. Formatting runs first so that " Delhi" and "Delhi"
# are the same string before anything else compares them. Column
# names are cleaned up front since nothing downstream depends on the
# original header spelling. Missing-token normalization and numeric/
# boolean/categorical/email/phone/date standardization all run
# *before* missing_values, so the fill step sees the real shape of
# the data (e.g. a numeric-looking text column becomes numeric
# before deciding whether to median-impute or "Unknown"-impute it).
# duplicates runs last so standardized values are compared, not raw
# ones — otherwise "Male"/"MALE" or " x " vs "x" would hide real
# duplicate rows.
DEFAULT_RULES = [
    "column_names",
    "formatting",
    "missing_token_normalization",
    "numeric_text_cleaning",
    "boolean_standardization",
    "categorical_standardization",
    "email_cleaning",
    "phone_cleaning",
    "date_standardization",
    "missing_values",
    "duplicates",
]

# High-missingness threshold (MV-004): above this %, a column is
# flagged for manual review instead of auto-imputed.
HIGH_MISSING_THRESHOLD = 70

# Populated by each handle_* call with anything beyond a bare count
# (e.g. which columns got flagged, how each was cleaned). Read by
# apply_rules() right after the call and merged into the summary.
LAST_RUN_DETAILS: dict = {}


def handle_missing_values(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Rules MV-001 -> MV-004.

      - Numeric column, missing %  <= 70  -> fill with column median
        (robust to outliers, unlike mean).
      - Text/categorical column, missing % <= 70 -> fill with "Unknown"
        (keeps the fact that the value was absent, doesn't guess).
      - Any column with missing % > 70 -> left untouched and flagged
        for review; auto-filling that much of a column would mostly
        be inventing data.

    Returns the number of individual cells that were actually filled.
    """
    changed = 0
    per_column = {}
    flagged = []
    total_rows = len(df)

    for col in df.columns:
        missing_count = int(df[col].isna().sum())
        if missing_count == 0:
            continue

        missing_pct = round((missing_count / total_rows) * 100, 2) if total_rows else 0.0

        if missing_pct > HIGH_MISSING_THRESHOLD:
            flagged.append({"column": col, "missing_percentage": missing_pct})
            per_column[col] = {"action": "review_required", "missing_percentage": missing_pct}
            continue

        if pd.api.types.is_bool_dtype(df[col]):
            # Booleans (e.g. from the boolean-standardization rule)
            # aren't well served by either median or "Unknown" — fill
            # with whichever value (True/False) is more common.
            mode = df[col].mode(dropna=True)
            fill_value = bool(mode.iloc[0]) if not mode.empty else False
            action = "mode_imputation"
        elif pd.api.types.is_numeric_dtype(df[col]):
            fill_value = df[col].median()
            action = "median_imputation"
        else:
            fill_value = "Unknown"
            action = "unknown_category"

        df[col] = df[col].fillna(fill_value)
        changed += missing_count
        per_column[col] = {
            "action": action,
            "missing_percentage": missing_pct,
            "filled": missing_count,
        }

    LAST_RUN_DETAILS["missing_values"] = {
        "per_column": per_column,
        "flagged_for_review": flagged,
    }
    return df, changed


def handle_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Rules DP-001 / DP-002 (exact duplicates only for V1).

    A row is only treated as a duplicate if every column matches
    another row exactly. The first occurrence is kept, later ones are
    removed. Same-key-different-data cases (e.g. same customer_id,
    different city) are NOT touched here — that's a review case, not
    an auto-delete, so it's out of scope for this default rule.
    """
    before = len(df)
    duplicate_count = int(df.duplicated(keep="first").sum())
    df = df.drop_duplicates(keep="first").reset_index(drop=True)
    removed = before - len(df)

    LAST_RUN_DETAILS["duplicates"] = {
        "duplicate_rows_found": duplicate_count,
        "removed": removed,
        "kept": "first",
    }
    return df, removed


def handle_formatting(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Rules FM-001 / FM-002 (the safe, always-on defaults).

      - Strip leading/trailing whitespace on every text column.
      - Collapse repeated internal whitespace to a single space.

    Case normalization (FM-003/004) and category/date standardization
    (FM-005/006) are deliberately NOT auto-applied here — the spec
    marks those "configurable"/"review", since blindly lowercasing a
    name column or remapping an unrecognized category can silently
    corrupt data. Those belong behind an explicit column-level config
    once that's defined, not in the default V1 pipeline.
    """
    changed = 0
    per_column = {}
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        original = df[col].astype("string")
        cleaned = original.str.strip().str.replace(r"\s+", " ", regex=True)
        diff = int(((original != cleaned) & original.notna()).sum())
        if diff:
            df[col] = cleaned
            changed += diff
            per_column[col] = diff

    LAST_RUN_DETAILS["formatting"] = {"per_column_cells_changed": per_column}
    return df, changed


def handle_column_names(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Cleans up column headers: strips stray whitespace, collapses
    runs of non-alphanumeric characters (spaces, dashes, dots, etc.)
    to a single underscore, and lowercases the result — so
    " First Name", "first-name" and "FirstName " all become the
    predictable "first_name". This only touches header labels, never
    the data itself, so there's no risk of corrupting a cell value.

    If cleaning would make two columns collide (e.g. "Name" and
    "name"), the later one gets a numeric suffix instead of silently
    overwriting the first — nothing is ever dropped.
    """
    seen: dict[str, int] = {}
    renamed = {}
    new_columns = []

    for col in df.columns:
        cleaned = re.sub(r"[^\w]+", "_", str(col).strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
        if not cleaned:
            cleaned = "column"

        if cleaned in seen:
            seen[cleaned] += 1
            unique = f"{cleaned}_{seen[cleaned]}"
        else:
            seen[cleaned] = 1
            unique = cleaned

        new_columns.append(unique)
        if unique != col:
            renamed[str(col)] = unique

    df.columns = new_columns
    LAST_RUN_DETAILS["column_names"] = {"renamed": renamed}
    return df, len(renamed)


def handle_missing_token_normalization(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Recognizes common stand-ins for "no value" — blank strings,
    "N/A", "null", "None", "-", "?", etc. — and converts them to a
    real missing value (NaN), so the 'Fill gaps' rule and the
    quality report both see them as missing instead of as a
    legitimate text category. Deliberately excludes ambiguous words
    like "unknown" or "missing", since those can be genuine survey/
    category answers rather than placeholders — those are left as-is.
    """
    changed = 0
    per_column = {}
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        series = df[col]
        is_token = series.apply(lambda v: isinstance(v, str) and detectors.is_missing_token(v))
        count = int(is_token.sum())
        if count:
            df.loc[is_token, col] = pd.NA
            changed += count
            per_column[col] = count

    LAST_RUN_DETAILS["missing_token_normalization"] = {"per_column": per_column}
    return df, changed


def handle_numeric_text_cleaning(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Some numeric columns get read in as text because of formatting
    noise — currency symbols, thousands separators, percent signs,
    accounting-style parentheses for negatives ("$1,200.50", "(45)").
    This strips that noise and converts the column to a real numeric
    dtype, but only when EVERY non-null value in the column converts
    cleanly — a single genuinely non-numeric value (e.g. a real word)
    aborts the conversion for that column entirely, since a partial
    conversion could silently misrepresent mixed data. Columns that
    don't fully convert are left untouched (they may surface in the
    quality report as a mixed-type column instead).
    """
    changed = 0
    per_column = {}
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        series = df[col]
        non_null = series.dropna().astype(str)
        if len(non_null) < 2:
            continue

        cleaned_strs = non_null.map(detectors.strip_numeric_noise)
        parsed = cleaned_strs.map(detectors.try_parse_float)
        if parsed.isna().any():
            continue  # not every value converts cleanly -> leave column alone

        # Require at least one value to have actually had noise
        # stripped or a decimal point/sign, otherwise this is just a
        # column of bare integers already and there's nothing to do.
        diff_mask = non_null != cleaned_strs
        if not diff_mask.any():
            continue

        full_values = pd.Series(pd.NA, index=series.index, dtype="object")
        full_values.loc[non_null.index] = parsed.values
        df[col] = pd.to_numeric(full_values, errors="coerce")

        count = int(diff_mask.sum())
        changed += count
        per_column[col] = count

    LAST_RUN_DETAILS["numeric_text_cleaning"] = {"per_column": per_column}
    return df, changed


def handle_boolean_standardization(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Standardizes columns whose only non-null values are textual
    yes/no-style words (Yes/No, Y/N, True/False, T/F, in any casing)
    into real booleans. Deliberately does NOT touch 1/0-style columns
    — those are common as legitimate numeric codes, not just
    booleans, so guessing there would be unsafe.
    """
    changed = 0
    per_column = {}
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        series = df[col]
        non_null = series.dropna().astype(str).str.strip()
        if non_null.empty:
            continue
        lowered = non_null.str.lower()
        unique_vals = set(lowered.unique())
        if not unique_vals or not unique_vals.issubset(detectors.BOOLEAN_WORDS):
            continue

        mapped = lowered.map(lambda v: True if v in detectors.TRUE_WORDS else False)
        new_series = pd.Series(pd.NA, index=series.index, dtype="object")
        new_series.loc[non_null.index] = mapped.values
        df[col] = new_series.astype("boolean")

        count = len(non_null)
        changed += count
        per_column[col] = {
            "changed": count,
            "true_words_seen": sorted(unique_vals & detectors.TRUE_WORDS),
            "false_words_seen": sorted(unique_vals & detectors.FALSE_WORDS),
        }

    LAST_RUN_DETAILS["boolean_standardization"] = {"per_column": per_column}
    return df, changed


def handle_categorical_standardization(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Merges values that are the SAME category spelled differently only
    by case or whitespace — "Male" / "MALE" / "male" all become one
    value. The canonical spelling chosen is whichever variant already
    appears most often in the data (ties broken alphabetically), so
    nothing is invented — it's just consolidation. Only considered for
    columns that look categorical (a small, repeated set of values,
    not free text or near-unique IDs), so it never touches something
    like a names or addresses column. Genuinely different labels for
    the same idea (e.g. "NY" vs "New York") are NOT merged — that
    requires judgement a rule shouldn't make, and is left for the
    quality report's "inconsistent categories" finding instead.
    """
    changed = 0
    per_column = {}
    total_rows = len(df)
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        series = df[col]
        non_null = series.dropna().astype(str)
        nunique = non_null.nunique()
        if nunique < 2 or nunique > 50 or (total_rows and nunique > total_rows * 0.5):
            continue

        groups: dict[str, list[str]] = {}
        for v in non_null.unique():
            key = " ".join(v.split()).lower()
            groups.setdefault(key, []).append(v)

        variant_groups = {k: v for k, v in groups.items() if len(v) > 1}
        if not variant_groups:
            continue

        value_counts = non_null.value_counts()
        remap = {}
        for variants in variant_groups.values():
            canonical = sorted(variants, key=lambda v: (-value_counts[v], v))[0]
            for v in variants:
                if v != canonical:
                    remap[v] = canonical

        if not remap:
            continue

        mask = non_null.isin(remap.keys())
        df.loc[non_null.index[mask], col] = non_null[mask].map(remap)
        count = int(mask.sum())
        changed += count
        per_column[col] = {"changed": count, "groups_merged": len(variant_groups)}

    LAST_RUN_DETAILS["categorical_standardization"] = {"per_column": per_column}
    return df, changed


def handle_email_cleaning(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    For columns that look like email addresses (by column name, or
    because most of the values match an email shape), trims stray
    whitespace and lowercases the address. Lowercasing is a common,
    low-risk normalization for emails since domains are case-
    insensitive and almost all real-world mailboxes treat the local
    part the same way — but it IS an assumption, so it's scoped
    tightly to columns that are confidently email columns. Validity
    (is this actually a well-formed email?) is not judged here — see
    the quality report's email-validation finding for that.
    """
    changed = 0
    per_column = {}
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        series = df[col]
        if not detectors.is_email_column(str(col), series):
            continue

        original = series.astype("string")
        cleaned = original.str.strip().str.lower()
        diff = (original != cleaned) & original.notna()
        count = int(diff.sum())
        if count:
            df[col] = cleaned
            changed += count
            per_column[col] = count

    LAST_RUN_DETAILS["email_cleaning"] = {"per_column": per_column}
    return df, changed


def handle_phone_cleaning(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    For columns that look like phone numbers (by column name only —
    phone formats vary too much by country to detect reliably from
    values alone), collapses accidental repeated punctuation
    ("12--34" -> "12-34") left over from messy data entry. Does NOT
    strip digits, re-group numbers, add/remove country codes, or
    reformat parentheses/dashes — that would require knowing the
    number's country and could easily produce a number that looks
    plausible but is wrong. Whitespace trimming/collapsing is already
    handled by the formatting rule.
    """
    changed = 0
    per_column = {}
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        if not detectors.is_phone_column(str(col)):
            continue

        original = df[col].astype("string")
        cleaned = (
            original
            .str.replace(r"-{2,}", "-", regex=True)
            .str.replace(r"\.{2,}", ".", regex=True)
            .str.strip(" -")
        )
        diff = (original != cleaned) & original.notna()
        count = int(diff.sum())
        if count:
            df[col] = cleaned
            changed += count
            per_column[col] = count

    LAST_RUN_DETAILS["phone_cleaning"] = {"per_column": per_column}
    return df, changed


def handle_date_standardization(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    For columns that look like dates, converts them to a single ISO
    format (YYYY-MM-DD) — but ONLY when the format is unambiguous,
    i.e. day-first and month-first parsing agree on every value
    (which is always true for already-ISO dates, and also true
    whenever every day-of-month happens to be >12). If the column
    could reasonably mean two different dates depending on
    convention (e.g. "03/04/2024" — 3rd April or March 4th?), it is
    left completely untouched; the quality report flags it for a
    human to confirm instead of guessing.
    """
    changed = 0
    per_column = {}
    skipped = []
    text_columns = df.select_dtypes(include=["object", "string"]).columns

    for col in text_columns:
        series = df[col]
        if not detectors.is_probable_date_column(str(col), series):
            continue

        parsed = detectors.unambiguous_date_parse(series)
        if parsed is None:
            skipped.append(col)
            continue

        formatted = parsed.dt.strftime("%Y-%m-%d")
        original = series.astype("string")
        new_values = pd.Series(pd.NA, index=series.index, dtype="string")
        has_value = parsed.notna()
        new_values.loc[has_value] = formatted[has_value]
        # Leave any value that failed to parse exactly as it was,
        # rather than blanking it out.
        new_values.loc[~has_value & original.notna()] = original[~has_value & original.notna()]

        diff = (original != new_values) & original.notna()
        count = int(diff.sum())
        if count:
            df[col] = new_values
            changed += count
            per_column[col] = {"changed": count, "format": "YYYY-MM-DD"}

    LAST_RUN_DETAILS["date_standardization"] = {"per_column": per_column, "skipped_ambiguous": skipped}
    return df, changed


RULE_DISPATCH = {
    "missing_values": handle_missing_values,
    "duplicates": handle_duplicates,
    "formatting": handle_formatting,
    "column_names": handle_column_names,
    "missing_token_normalization": handle_missing_token_normalization,
    "numeric_text_cleaning": handle_numeric_text_cleaning,
    "boolean_standardization": handle_boolean_standardization,
    "categorical_standardization": handle_categorical_standardization,
    "email_cleaning": handle_email_cleaning,
    "phone_cleaning": handle_phone_cleaning,
    "date_standardization": handle_date_standardization,
}


def apply_rules(df: pd.DataFrame, rules: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    rules = rules or DEFAULT_RULES
    changes = {}
    details = {}
    LAST_RUN_DETAILS.clear()

    for rule_name in rules:
        fn = RULE_DISPATCH.get(rule_name)
        if not fn:
            continue
        df, count = fn(df)
        changes[f"{rule_name}_changed"] = count
        if rule_name in LAST_RUN_DETAILS:
            details[rule_name] = LAST_RUN_DETAILS[rule_name]

    return df, {"rules_applied": rules, "changes": changes, "details": details}
