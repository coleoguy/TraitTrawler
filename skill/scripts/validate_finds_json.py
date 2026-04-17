#!/usr/bin/env python3
"""
Validate finds/ JSON files against the canonical schema.

Called by write_finds.py before processing. Catches structural problems
before they waste downstream Writer cycles.

Usage:
    python3 scripts/validate_finds_json.py --file finds/10_1234_example_2026-03-28T140500Z.json
    python3 scripts/validate_finds_json.py --dir finds/

Output: JSON to stdout with pass/fail per file and details.
"""

import argparse
import glob
import json
import os
import sys

REQUIRED_TOP_KEYS = {"records", "extraction_timestamp"}
# doi is strongly recommended but not required — pre-DOI papers
# (pre-2000 literature) may not have one. Papers without DOI must
# have a title for identification.
RECOMMENDED_TOP_KEYS = {"doi"}
REQUIRED_RECORD_KEYS = {"species", "extraction_confidence"}
# Soft-required: recommended but scrub.py auto-fills these before write.
# Missing values trigger a warning, not a validation failure.
SOFT_REQUIRED_RECORD_KEYS = {"source_page"}


def _load_required_fields(config_path):
    """Load required_fields from collector_config.yaml if available."""
    if not config_path or not os.path.exists(config_path):
        return []
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("required_fields", [])
    except Exception:
        return []


def validate_file(path, config_path=None):
    """Validate a single finds JSON file. Returns (ok, errors) tuple."""
    errors = []
    project_required = _load_required_fields(config_path)

    # Parse JSON
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]
    except OSError as e:
        return False, [f"Cannot read file: {e}"]

    if not isinstance(data, dict):
        return False, ["Top-level must be a JSON object, got "
                       f"{type(data).__name__}"]

    # Check required top-level keys
    for key in REQUIRED_TOP_KEYS:
        if key not in data:
            errors.append(f"Missing required top-level key: '{key}'")

    # Soft-check: doi recommended but not required (pre-DOI papers)
    for key in RECOMMENDED_TOP_KEYS:
        if key not in data or not data.get(key):
            print(f"WARNING: '{key}' is empty (recommended for provenance)",
                  file=sys.stderr)

    # Must have doi OR title for paper identification
    has_doi = bool(data.get("doi", ""))
    has_title = bool(data.get("title", ""))
    if not has_doi and not has_title:
        errors.append("Must have either 'doi' or 'title' for paper identification")

    # records must be a list
    records = data.get("records")
    if records is None:
        errors.append("'records' key is missing")
        return len(errors) == 0, errors
    if not isinstance(records, list):
        errors.append(f"'records' must be an array, got {type(records).__name__}")
        return False, errors

    # Check for common schema variants that indicate agent non-compliance
    for bad_key in ("consensus_records", "consensus_results", "extracted_records"):
        if bad_key in data:
            errors.append(f"Non-standard key '{bad_key}' found — "
                          f"agent used wrong schema")

    # paper_metadata check
    pm = data.get("paper_metadata")
    if pm is not None:
        if not isinstance(pm, dict):
            errors.append(f"'paper_metadata' must be a dict, got "
                          f"{type(pm).__name__}")
        else:
            for mk in ("year", "journal", "first_author"):
                if mk not in pm:
                    errors.append(f"paper_metadata missing '{mk}'")

    # Per-record validation
    for i, rec in enumerate(records):
        prefix = f"records[{i}]"
        if not isinstance(rec, dict):
            errors.append(f"{prefix}: must be a dict, got "
                          f"{type(rec).__name__}")
            continue

        # Required fields (hard — blocks validation)
        for key in REQUIRED_RECORD_KEYS:
            val = rec.get(key)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"{prefix}: missing or empty '{key}'")

        # Soft-required fields (warning only — does NOT block validation)
        for key in SOFT_REQUIRED_RECORD_KEYS:
            val = rec.get(key)
            if val is None or (isinstance(val, str) and not val.strip()):
                # Log warning but don't append to errors
                print(f"WARNING: {prefix}: '{key}' is empty (recommended "
                      f"but not required)", file=sys.stderr)

        # Project-specific required fields from collector_config.yaml
        for key in project_required:
            val = rec.get(key)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"{prefix}: missing project-required field "
                              f"'{key}' (from collector_config.yaml)")

        # extraction_confidence must be float in [0, 1]
        ec = rec.get("extraction_confidence")
        if ec is not None:
            try:
                ecf = float(ec)
                if ecf < 0.0 or ecf > 1.0:
                    errors.append(f"{prefix}: extraction_confidence={ecf} "
                                  f"outside [0.0, 1.0]")
            except (ValueError, TypeError):
                errors.append(f"{prefix}: extraction_confidence='{ec}' "
                              f"is not numeric")

        # Detect prose in fields that should be flat values
        species = rec.get("species", "")
        if isinstance(species, str) and len(species) > 200:
            errors.append(f"{prefix}: 'species' looks like prose "
                          f"({len(species)} chars)")

        # Soft-check: source_context should contain at least one trait value
        src_ctx = str(rec.get("source_context", "")).strip().lower()
        if src_ctx and len(src_ctx) > 10:
            # Check if any non-metadata field value appears in source_context
            found_grounding = False
            for key, val in rec.items():
                if key in REQUIRED_RECORD_KEYS | SOFT_REQUIRED_RECORD_KEYS:
                    continue
                if key in ("species", "source_context",
                           "extraction_reasoning", "notes",
                           "flag_for_review", "source_type"):
                    continue
                sval = str(val or "").strip()
                if sval and len(sval) >= 1 and sval.lower() in src_ctx:
                    found_grounding = True
                    break
            if not found_grounding:
                print(f"WARNING: {prefix}: no trait values found in "
                      f"source_context (possible hallucination)",
                      file=sys.stderr)

    return len(errors) == 0, errors


def main():
    parser = argparse.ArgumentParser(
        description="Validate finds/ JSON files against canonical schema"
    )
    parser.add_argument("--file", help="Single file to validate")
    parser.add_argument("--dir", help="Directory of files to validate")
    parser.add_argument("--config", help="Path to collector_config.yaml "
                        "(enables project-specific required_fields check)")
    args = parser.parse_args()

    files = []
    if args.file:
        files.append(args.file)
    elif args.dir:
        files = sorted(glob.glob(os.path.join(args.dir, "*.json")))
    else:
        parser.error("Provide --file or --dir")

    results = []
    all_ok = True
    for fpath in files:
        ok, errs = validate_file(fpath, config_path=args.config)
        if not ok:
            all_ok = False
        results.append({
            "file": os.path.basename(fpath),
            "valid": ok,
            "errors": errs,
        })

    output = {
        "files_checked": len(results),
        "all_valid": all_ok,
        "results": results,
    }
    json.dump(output, sys.stdout, indent=2)
    print()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
