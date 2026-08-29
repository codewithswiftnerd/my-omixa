"""
Shared, read-only heuristics.

Both cleaning/rules.py (auto-fix) and cleaning/quality_report.py
(detect-only diagnostics) need to answer the same questions — "is
this an email column?", "is this a boolean-looking column?", "is
this string actually a placeholder for missing data?" — and they
need to answer them the *same way*, or the report would end up
promising a fix that the rules don't actually perform (or vice
versa). This module is the single source of truth for those
questions. Nothing in here mutates a dataframe.
"""

from __future__ import annotations
import re
from typing import Optional
import pandas as pd

# Common placeholder strings people use for "no value" that pandas'
# own NA detection doesn't catch (those are usually only caught when
# the *whole* column is empty, not a single stray cell). Matched
# case-insensitively against the trimmed cell value. Deliberately
# does NOT include ambiguous words like "unknown" or "missing" —
# those can be legitimate category labels (e.g. a survey answer),
# so they're left alone rather than guessed at.
MISSING_TOKENS = {
    "", "na", "n/a", "n.a.", "n\\a", "null", "none", "nan",
    "-", "--", "?", "#n/a", "nil",
}

# Restricted to unambiguous words on purpose. "1"/"0" are excluded:
# plenty of real columns use 1/0 as numeric codes rather than
# booleans, and we'd rather leave those as numbers than guess.
TRUE_WORDS = {"yes", "y", "true", "t"}
FALSE_WORDS = {"no", "n", "false", "f"}
BOOLEAN_WORDS = TRUE_WORDS | FALSE_WORDS

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Characters that are purely visual/formatting noise on an otherwise
# numeric value: currency symbols, thousands separators, percent
# signs, stray whitespace.
_NUMERIC_NOISE_RE = re.compile(r"[,\s$€£¥%]")
_PAREN_NEGATIVE_RE = re.compile(r"^\((.*)\)$")


def is_missing_token(value: str) -> bool:
    return value.strip().lower() in MISSING_TOKENS


def is_email_column(name: str, series: pd.Series) -> bool:
    """Name hint first (cheap, explicit); falls back to checking
    whether most non-null values actually look like an email."""
    lname = name.lower()
    if "email" in lname or "e-mail" in lname or "e_mail" in lname:
        return True
    values = series.dropna().astype(str)
    if len(values) < 3:
        return False
    matches = values.str.match(EMAIL_RE)
    return bool(matches.mean() >= 0.8)


def is_phone_column(name: str) -> bool:
    lname = name.lower()
    return any(k in lname for k in (
        "phone", "mobile", "contact_no", "contact no", "contactnumber",
        "contact_number", "telephone", "tel_no", "whatsapp", "fax",
    )) or lname.strip() in ("tel", "cell")


def is_probable_date_column(name: str, series: pd.Series) -> bool:
    """Name hint, or a sample of values that mostly parse as dates
    and mostly contain date-shaped separators (so we don't flag a
    plain numeric ID column as a date just because pandas can
    technically parse '20230101' as one)."""
    lname = name.lower()
    if any(k in lname for k in ("date", "dob", "birthday")):
        return True

    values = series.dropna().astype(str)
    if len(values) < 3:
        return False
    shaped = values.str.match(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}$")
    if shaped.mean() < 0.8:
        return False
    parsed = pd.to_datetime(values, errors="coerce", format="mixed")
    return bool(parsed.notna().mean() >= 0.8)


def unambiguous_date_parse(values: pd.Series) -> Optional[pd.Series]:
    """
    Tries to parse a column of date-like strings safely.

    Returns the parsed datetime Series only if the result is the
    SAME regardless of whether day-first or month-first parsing is
    assumed (e.g. every value is already ISO, or every day-of-month
    happens to be >12), so there's no real ambiguity to guess at.
    Returns None if the two interpretations disagree anywhere, or if
    too many values fail to parse at all — in either case the column
    is left untouched and the report flags it for manual review
    instead.
    """
    non_null = values.dropna().astype(str)
    if non_null.empty:
        return None

    day_first = pd.to_datetime(non_null, errors="coerce", dayfirst=True, format="mixed")
    month_first = pd.to_datetime(non_null, errors="coerce", dayfirst=False, format="mixed")

    if day_first.isna().mean() > 0.05 and month_first.isna().mean() > 0.05:
        return None  # too many unparseable values either way

    # Prefer whichever interpretation parsed more successfully; if
    # they parsed the same values but disagree on the actual dates,
    # that's the ambiguous case we bail out on.
    candidate = day_first if day_first.isna().sum() <= month_first.isna().sum() else month_first
    other = month_first if candidate is day_first else day_first

    both_parsed = candidate.notna() & other.notna()
    if both_parsed.any() and not (candidate[both_parsed] == other[both_parsed]).all():
        return None

    if candidate.isna().mean() > 0.05:
        return None

    full = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    full.loc[non_null.index] = candidate.values
    return full


def strip_numeric_noise(value: str) -> str:
    s = _NUMERIC_NOISE_RE.sub("", value.strip())
    m = _PAREN_NEGATIVE_RE.match(s)
    if m:
        s = "-" + m.group(1)
    return s


def try_parse_float(cleaned: str) -> Optional[float]:
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
