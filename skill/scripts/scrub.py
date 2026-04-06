#!/usr/bin/env python3
"""
Deterministic finds/ JSON normalization for TraitTrawler v5.

Replaces the LLM-based Scrubber agent with pure Python — all operations
are mechanical string transformations. Normalizes finds/*.json files
before write_finds.py processes them: fixes field names, backfills
metadata, normalizes values, so the write pipeline gets clean input.

Usage:
    python3 scripts/scrub.py --project-root . --dir finds/
    python3 scripts/scrub.py --project-root . --file finds/example.json

Output: JSON summary to stdout:
    {"files_scrubbed": 3, "repairs": {...}, "errors": []}
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_WORDS = {"high": 0.85, "medium": 0.65, "low": 0.40}

# Sex chromosome normalization map (lowercase key -> canonical value)
SEX_CHROM_MAP = {
    "xyp": "Xyp", "xyr": "Xyp",
    "xo":  "X0",  "x0":  "X0",
    "neo-xy": "NeoXY", "neoxy":  "NeoXY",
    "neo-x0": "NeoX0", "neo-xo": "NeoX0", "neox0": "NeoX0", "neoxo": "NeoX0",
    "x-y parachute": "Xyp", "xy parachute": "Xyp",
}

# Field name aliases: alias -> canonical name
FIELD_ALIASES = {
    "sex_chrom":        "sex_chromosome_system",
    "sex_chromosome":   "sex_chromosome_system",
    "sex_chrom_system": "sex_chromosome_system",
    "2n":               "diploid_2n_male",
    "2n_male":          "diploid_2n_male",
    "diploid_number":   "diploid_2n_male",
    "chromosome_number": "diploid_2n_male",
    "authors":          "paper_authors",
    "year":             "paper_year",
    "journal":          "paper_journal",
    "title":            "paper_title",
    "confidence":       "extraction_confidence",
    "page":             "source_page",
    "pages":            "source_page",
    "context":          "source_context",
    "source":           "source_context",
    "tau":              "tau_mean_hours",
    "period":           "tau_mean_hours",
    "tau_hours":        "tau_mean_hours",
    "tau_sd":           "tau_sd_hours",
    "sd":               "tau_sd_hours",
    "tau_sem":          "tau_sem_hours",
    "sem":              "tau_sem_hours",
}

# Fields that should be integers
INTEGER_FIELDS = {"paper_year", "diploid_2n_male", "diploid_2n_female",
                  "n_autosomes", "sample_size"}

# Fields that should be floats
FLOAT_FIELDS = {"tau_mean_hours", "tau_sd_hours", "tau_sem_hours"}

# Regex: author citation after binomial  ("Genus epithet Author, 1990")
_AUTHOR_CITATION_RE = re.compile(
    r'^([A-Z][a-z]+\s+[a-z][a-z-]+)\s+[A-Z].*$'
)

# Regex: numeric prefix junk ("2n=", "~", "n=")
_NUMERIC_PREFIX_RE = re.compile(r'^[~\u2248]?(?:2?n\s*=\s*)?')

# Regex: trailing unit on floats ("23.8 h", "1.5 hours")
_FLOAT_UNIT_RE = re.compile(
    r'^([0-9]+\.?[0-9]*)\s*(?:h|hrs?|hours?)?\s*$', re.I)

# Regex: range values ("12-14", "12--14", "12\u201314")
_RANGE_RE = re.compile(r'^\d+\s*[\u2013\u2014\-]+\s*\d+$')

# Regex: multi-X chromosomes with spaces ("X1 X2 Y")
_MULTI_X_RE = re.compile(r'^[XYZWxyzw0-9]+(?:\s+[XYZWxyzw0-9]+)+$')


# ---------------------------------------------------------------------------
# Repair helpers
# ---------------------------------------------------------------------------

def _null_to_empty(data):
    """Recursively convert None values to empty strings."""
    if isinstance(data, dict):
        return {k: _null_to_empty(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_null_to_empty(v) for v in data]
    if data is None:
        return ""
    return data


def _apply_field_aliases(record, repairs):
    """Rename aliased field names when the canonical name is empty/missing."""
    for alias, canonical in FIELD_ALIASES.items():
        if alias not in record:
            continue
        existing = str(record.get(canonical, "")).strip()
        if not existing:
            record[canonical] = record[alias]
            repairs["fields_aliased"] += 1
            if alias == "chromosome_number":
                record.setdefault("scrub_notes", [])
                record["scrub_notes"].append(
                    "chromosome_number mapped to diploid_2n_male")
        del record[alias]


def _normalize_confidence(record, repairs):
    """Normalize extraction_confidence to a float in [0.0, 1.0]."""
    val = record.get("extraction_confidence", "")
    if val == "" or val is None:
        return
    if isinstance(val, str):
        low = val.strip().lower()
        if low in CONFIDENCE_WORDS:
            record["extraction_confidence"] = CONFIDENCE_WORDS[low]
            repairs["confidence_normalized"] += 1
            return
        try:
            val = float(low)
        except ValueError:
            return
    if isinstance(val, (int, float)):
        record["extraction_confidence"] = max(0.0, min(1.0, float(val)))
        repairs["confidence_normalized"] += 1


def _normalize_sex_chrom(record, repairs, unresolved=None):
    """Normalize sex_chromosome_system values.

    If *unresolved* is a list, append details when a non-empty value
    cannot be mapped to a canonical form.
    """
    val = record.get("sex_chromosome_system", "")
    if not isinstance(val, str) or not val.strip():
        return
    raw = val.strip()
    low = raw.lower()

    # Direct map lookup
    if low in SEX_CHROM_MAP:
        record["sex_chromosome_system"] = SEX_CHROM_MAP[low]
        repairs["sex_chrom_normalized"] += 1
        return

    # Multi-X/Y with spaces: "X1 X2 Y" -> "X1X2Y"
    if _MULTI_X_RE.match(raw):
        record["sex_chromosome_system"] = raw.replace(" ", "")
        repairs["sex_chrom_normalized"] += 1
        return

    # Value is non-empty but unrecognized — report it
    if unresolved is not None:
        unresolved.append({
            "field": "sex_chromosome_system",
            "raw_value": raw,
            "species": record.get("species", ""),
        })


def _normalize_species(record, repairs):
    """Strip whitespace and author citations from species names."""
    val = record.get("species", "")
    if not isinstance(val, str) or not val.strip():
        return
    original = val
    cleaned = val.strip()
    m = _AUTHOR_CITATION_RE.match(cleaned)
    if m:
        cleaned = m.group(1)
        repairs["species_cleaned"] += 1
    elif cleaned != original:
        # Only whitespace was stripped
        repairs["species_cleaned"] += 1
    record["species"] = cleaned


def _normalize_integer(record, field, repairs):
    """Normalize an integer field: strip prefixes like '2n=24' -> 24."""
    val = record.get(field, "")
    if val == "" or val is None:
        return
    s = str(val).strip()
    if not s:
        return

    # Check for range values first — leave as-is, add note
    if _RANGE_RE.match(s):
        record.setdefault("scrub_notes", [])
        record["scrub_notes"].append(f"{field} is a range: {s}")
        return

    cleaned = _NUMERIC_PREFIX_RE.sub("", s)
    try:
        record[field] = int(float(cleaned))
        repairs["numerics_fixed"] += 1
    except (ValueError, TypeError):
        pass


def _normalize_float(record, field, repairs):
    """Normalize a float field: strip units like '23.8 h' -> 23.8."""
    val = record.get(field, "")
    if val == "" or val is None:
        return
    s = str(val).strip()
    if not s:
        return

    # Check for range values first — leave as-is, add note
    if _RANGE_RE.match(s):
        record.setdefault("scrub_notes", [])
        record["scrub_notes"].append(f"{field} is a range: {s}")
        return

    m = _FLOAT_UNIT_RE.match(s)
    if m:
        try:
            record[field] = float(m.group(1))
            repairs["numerics_fixed"] += 1
        except (ValueError, TypeError):
            pass


# ---------------------------------------------------------------------------
# Core scrubbing logic
# ---------------------------------------------------------------------------

def scrub_file(fpath, repairs, normalization_failures=None, project_root=None):
    """Scrub a single finds/ JSON file in-place. Returns (ok, error_msg)."""
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, str(e)

    if not isinstance(data, dict):
        return False, "top-level JSON is not an object"

    # --- Null cleanup (whole tree) ---
    data = _null_to_empty(data)

    # --- 1. Structural fixes (top-level) ---

    # extraction_timestamp
    if not data.get("extraction_timestamp"):
        try:
            mtime = os.path.getmtime(fpath)
            ts = datetime.fromtimestamp(mtime, tz=timezone.utc)
            data["extraction_timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            data["extraction_timestamp"] = (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        repairs["metadata_backfilled"] += 1

    # Rename variant record keys to canonical "records"
    if "records" not in data or not data["records"]:
        for alt_key in ("consensus_records", "extracted_records", "results"):
            if alt_key in data and data[alt_key]:
                data["records"] = data.pop(alt_key)
                repairs["records_key_fixed"] += 1
                break

    # Ensure doi or title is non-empty (check paper_metadata fallback)
    pm = data.get("paper_metadata", {}) or {}
    if not str(data.get("doi", "")).strip():
        if pm.get("doi"):
            data["doi"] = pm["doi"]
            repairs["metadata_backfilled"] += 1
    if not str(data.get("title", "")).strip():
        if pm.get("title"):
            data["title"] = pm["title"]
            repairs["metadata_backfilled"] += 1

    records = data.get("records", [])
    if not isinstance(records, list):
        return False, "'records' is not a list"

    extraction_mode = str(data.get("extraction_mode", "")).strip().lower()

    # Track fields that couldn't be normalized for this file
    unresolved = []

    # --- Per-record processing ---
    for rec in records:
        if not isinstance(rec, dict):
            continue

        # 8. Field name aliasing (do first so later steps see canonical names)
        _apply_field_aliases(rec, repairs)

        # 2. Metadata backfill from top-level into each record
        _backfill = {
            "paper_title":   data.get("title", ""),
            "paper_authors": "",
            "first_author":  pm.get("first_author", ""),
            "paper_year":    pm.get("year", ""),
            "paper_journal": pm.get("journal", ""),
            "doi":           data.get("doi", ""),
            "pdf_path":      data.get("pdf_path", ""),
            "pdf_source":    data.get("pdf_source", ""),
            "source_type":   data.get("source_type", "full_text"),
        }
        # Build authors string from list or pass through string
        authors_raw = pm.get("authors", "")
        if isinstance(authors_raw, list):
            _backfill["paper_authors"] = "; ".join(
                str(a) for a in authors_raw if a)
        elif isinstance(authors_raw, str):
            _backfill["paper_authors"] = authors_raw

        for field, fallback in _backfill.items():
            if not str(rec.get(field, "")).strip() and str(fallback).strip():
                rec[field] = fallback
                repairs["metadata_backfilled"] += 1

        # 3. pdf_path file-exists check
        pdf_val = str(rec.get("pdf_path", "")).strip()
        if pdf_val and project_root:
            abs_pdf = os.path.join(project_root, pdf_val)
            if not os.path.isfile(abs_pdf):
                if unresolved is not None:
                    unresolved.append({
                        "field": "pdf_path",
                        "raw_value": pdf_val,
                        "species": rec.get("species", ""),
                    })

        # 4. Confidence normalization
        _normalize_confidence(rec, repairs)

        # 5. Sex chromosome normalization
        _normalize_sex_chrom(rec, repairs, unresolved)

        # 6. Species cleanup
        _normalize_species(rec, repairs)

        # 7. Numeric field normalization
        for field in INTEGER_FIELDS:
            _normalize_integer(rec, field, repairs)
        for field in FLOAT_FIELDS:
            _normalize_float(rec, field, repairs)

        # 8. flag_for_review: coerce to boolean string
        ffr = rec.get("flag_for_review")
        if ffr is not None and not isinstance(ffr, bool) and ffr not in (
                "True", "False", "true", "false", "", "0", "1"):
            # Integer or garbage value leaked in — coerce to False
            rec["flag_for_review"] = "False"
            repairs["flag_for_review_coerced"] = (
                repairs.get("flag_for_review_coerced", 0) + 1)

        # 9. None/null -> empty string (catch any stragglers in records)
        for k, v in list(rec.items()):
            if v is None:
                rec[k] = ""

    data["records"] = records

    # Report normalization failures for this file
    if unresolved and normalization_failures is not None:
        doi = data.get("doi", os.path.basename(fpath))
        normalization_failures.append({
            "file": os.path.basename(fpath),
            "doi": doi,
            "unresolved": unresolved,
        })

    # --- Write back in-place ---
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        return False, f"write failed: {e}"

    return True, ""


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def scrub_finds(project_root, target_dir=None, target_file=None):
    """Scrub finds/ JSON files. Returns summary dict."""
    repairs = {
        "metadata_backfilled": 0,
        "confidence_normalized": 0,
        "sex_chrom_normalized": 0,
        "species_cleaned": 0,
        "numerics_fixed": 0,
        "fields_aliased": 0,
        "records_key_fixed": 0,
    }
    errors = []

    # Collect target files
    if target_file:
        path = os.path.join(project_root, target_file)
        files = [path] if os.path.isfile(path) else []
        if not files:
            errors.append({"file": target_file, "error": "file not found"})
    elif target_dir:
        pattern = os.path.join(project_root, target_dir, "*.json")
        files = sorted(glob.glob(pattern))
    else:
        pattern = os.path.join(project_root, "finds", "*.json")
        files = sorted(glob.glob(pattern))

    normalization_failures = []
    files_scrubbed = 0
    for fpath in files:
        ok, err = scrub_file(fpath, repairs, normalization_failures,
                             project_root=project_root)
        if ok:
            files_scrubbed += 1
        else:
            errors.append({
                "file": os.path.basename(fpath),
                "error": err,
            })

    summary = {
        "files_scrubbed": files_scrubbed,
        "repairs": repairs,
        "errors": errors,
    }
    if normalization_failures:
        summary["normalization_failures"] = normalization_failures
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Deterministic finds/ JSON normalization for TraitTrawler"
    )
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--dir", default=None,
                        help="Directory of JSON files to scrub (relative "
                             "to project root)")
    parser.add_argument("--file", default=None,
                        help="Single JSON file to scrub (relative to "
                             "project root)")
    args = parser.parse_args()

    summary = scrub_finds(args.project_root,
                          target_dir=args.dir,
                          target_file=args.file)
    json.dump(summary, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
