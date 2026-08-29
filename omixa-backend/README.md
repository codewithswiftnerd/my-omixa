# Omixa Backend (V1 scaffold)

No database. No persistent storage. Every request is one job, backed
by a temp folder that gets deleted after download (or after 30 min
if abandoned).

## Structure

```
omixa-backend/
├── app.py              entry point, registers routes
├── config.py           temp dir, upload limits, allowed file types
├── routes/
│   ├── upload.py        POST /api/upload         -> job_id
│   ├── process.py       POST /api/process/<id>    -> runs cleaning
│   └── download.py      GET  /api/download/<id>   -> cleaned file
├── processing/
│   └── pipeline.py      read -> clean -> export orchestration
├── cleaning/
│   ├── rules.py          auto-fix cleaning rules (see below)
│   ├── quality_report.py read-only diagnostics report (detect-only findings)
│   └── detectors.py      shared heuristics (email/phone/date/etc. detection)
├── export/
│   └── exporter.py      writes cleaned df back to csv/xlsx
└── utils/
    └── file_handler.py  job folders, save/find/delete temp files
```

## Flow

```
POST /api/upload            -> { job_id }
POST /api/process/<job_id>  -> { status, summary }
GET  /api/download/<job_id> -> cleaned file, then temp data is deleted
```

## Run locally

```
pip install -r requirements.txt
python app.py
```

Server starts on `http://localhost:5000`. `GET /api/health` for a
quick check it's alive.

## Cleaning rules

`cleaning/rules.py` runs an ordered pipeline of auto-fix rules
(`cleaning.rules.DEFAULT_RULES`), each safe enough to apply without
asking first:

1. **column_names** — tidy headers into consistent `snake_case`
2. **formatting** — trim/collapse whitespace
3. **missing_token_normalization** — treat `"N/A"`, `"null"`, `"-"`, blanks, etc. as real missing values
4. **numeric_text_cleaning** — strip `$`, `,`, `%` from numbers stored as text and convert dtype (whole-column-safe only)
5. **boolean_standardization** — `Yes/No`, `True/False`, `Y/N` → real booleans (never touches `1`/`0`)
6. **categorical_standardization** — merges case/whitespace-only variants (`Male`/`MALE`/`male`)
7. **email_cleaning** — trims + lowercases email-shaped columns
8. **phone_cleaning** — collapses accidental repeated punctuation only, in phone-shaped columns
9. **date_standardization** — normalizes dates to `YYYY-MM-DD`, but only when day-first vs month-first parsing agree (unambiguous)
10. **missing_values** — median (or mode, for booleans) for numbers, `"Unknown"` for text
11. **duplicates** — drops exact duplicate rows, keeping the first

Anything too ambiguous to fix safely (mismatched date formats,
inconsistent categories that aren't just case variants, outliers,
constant columns, malformed emails/phones, likely near-duplicate
records, mixed-type columns) is never silently changed — it's
surfaced instead via `cleaning/quality_report.py`, both before
cleaning (`GET /api/report/<job_id>`) and after
(`summary.quality_report` from `POST /api/process/<job_id>`), so the
user can decide what to do about it themselves.

Both the fixer and the detector share the same "is this an email
column? a phone column? a date column?" heuristics from
`cleaning/detectors.py`, so the report never promises a fix the rules
don't actually perform.
