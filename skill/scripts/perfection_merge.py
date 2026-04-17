#!/usr/bin/env python3
"""
Merge perfection pass results back into results.csv.

After the verify_and_write pipeline runs on perfection_finds/, this script
takes the reconciled, adjudicated, scrubbed finds files and updates the
original CSV rows in-place — preserving full audit trail.

Usage:
    python3 scripts/perfection_merge.py --project-root . \
        --session-id "perfection_20260411T120000"

Output: JSON summary to stdout.
"""

import argparse
import csv
import glob
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from state_utils import safe_read_json, safe_write_json, append_jsonl


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_read_csv(path):
    """Read a CSV file into a list of dicts. Returns [] if missing."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def atomic_rewrite_csv(csv_path, rows, fieldnames):
    """Rewrite a CSV file atomically using temp-file-then-rename."""
    parent_dir = os.path.dirname(csv_path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".csv", dir=parent_dir, prefix=".results_perf_")
    try:
        with os.fdopen(tmp_fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, csv_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _load_trait_fields(project_root):
    """Load trait field names from collector_config.yaml."""
    config_path = os.path.join(project_root, "collector_config.yaml")
    METADATA_FIELDS = {
        "doi", "paper_title", "paper_authors", "first_author", "paper_year",
        "paper_journal", "session_id", "processed_date", "family", "subfamily",
        "genus", "species", "extraction_confidence", "flag_for_review",
        "source_type", "pdf_source", "pdf_path", "pdf_filename", "pdf_url",
        "notes", "calibrated_confidence", "extraction_trace_id",
        "audit_status", "audit_session", "audit_prior_values",
        "accepted_name", "gbif_key", "taxonomy_note",
        "source_page", "source_context", "extraction_reasoning",
        "verification", "verification_notes",
    }
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        output_fields = []
        for f in config.get("output_fields", []):
            name = f["name"] if isinstance(f, dict) else f
            output_fields.append(name)
        return [f for f in output_fields if f not in METADATA_FIELDS]
    except (ImportError, FileNotFoundError):
        return []


def _normalize(val):
    """Normalize a value for comparison."""
    import re
    s = str(val or "").strip().lower()
    s = re.sub(r'\s+', ' ', s)
    return s


def _values_match(v1, v2):
    """Check if two extracted values are equivalent."""
    n1, n2 = _normalize(v1), _normalize(v2)
    if n1 == n2:
        return True
    try:
        if abs(float(n1) - float(n2)) < 0.001:
            return True
    except (ValueError, TypeError):
        pass
    return False


def merge_one_file(finds_path, csv_rows, trait_fields, session_id):
    """Merge one perfection finds file back into CSV rows.

    Returns (confirmed, corrected, unresolved, errors).
    """
    with open(finds_path, "r", encoding="utf-8") as f:
        finds_data = json.load(f)

    row_indices = finds_data.get("original_row_indices", [])
    records = finds_data.get("records", [])

    if len(row_indices) != len(records):
        return 0, 0, 0, [f"row_indices/records length mismatch in "
                         f"{os.path.basename(finds_path)}"]

    confirmed = 0
    corrected = 0
    unresolved = 0
    errors = []

    for i, rec in enumerate(records):
        row_idx = row_indices[i]
        if row_idx < 0 or row_idx >= len(csv_rows):
            errors.append(f"row_idx {row_idx} out of range")
            continue

        csv_row = csv_rows[row_idx]
        verification = (rec.get("verification") or "").strip().lower()

        # Unresolved: auditor couldn't find or still disputed
        if verification in ("unverified", "unaudited", "disputed"):
            csv_row["audit_status"] = "needs_human_review"
            csv_row["audit_session"] = session_id
            csv_row["flag_for_review"] = "true"
            unresolved += 1
            continue

        # Compare trait fields to detect corrections
        changed_fields = {}
        for tf in trait_fields:
            rec_val = (rec.get(tf) or "").strip()
            csv_val = (csv_row.get(tf) or "").strip()
            if rec_val and csv_val and not _values_match(rec_val, csv_val):
                changed_fields[tf] = csv_val  # store the ORIGINAL value

        if changed_fields:
            # Corrected: store originals, apply new values
            csv_row["audit_status"] = "corrected"
            csv_row["audit_session"] = session_id
            csv_row["audit_prior_values"] = json.dumps(
                changed_fields, ensure_ascii=False)
            # Apply corrected values
            for tf in changed_fields:
                new_val = (rec.get(tf) or "").strip()
                if new_val:
                    csv_row[tf] = new_val
            corrected += 1
        else:
            # Confirmed: all trait fields match
            csv_row["audit_status"] = "confirmed"
            csv_row["audit_session"] = session_id
            confirmed += 1

        # Update confidence and verification from reconciled record
        if rec.get("extraction_confidence") is not None:
            csv_row["extraction_confidence"] = str(
                round(float(rec["extraction_confidence"]), 2))
        if rec.get("verification"):
            csv_row["verification"] = rec["verification"]
        if rec.get("verification_notes"):
            csv_row["verification_notes"] = rec["verification_notes"]
        # Clear flag_for_review on confirmed records
        if csv_row["audit_status"] == "confirmed":
            csv_row["flag_for_review"] = ""

    return confirmed, corrected, unresolved, errors


def main():
    parser = argparse.ArgumentParser(
        description="Merge perfection pass results into results.csv")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root

    # Load manifest
    manifest_path = os.path.join(project_root, "state",
                                 "perfection_manifest.json")
    manifest = safe_read_json(manifest_path, default={})
    if not manifest:
        print(json.dumps({"error": "No perfection manifest found"}))
        sys.exit(1)

    if manifest.get("session_id") != args.session_id:
        print(json.dumps({
            "error": "Session ID mismatch",
            "manifest_session": manifest.get("session_id"),
            "requested_session": args.session_id,
        }))
        sys.exit(1)

    # Safety: check results.csv hasn't been modified since selection
    csv_path = os.path.join(project_root, "results.csv")
    if not os.path.exists(csv_path):
        print(json.dumps({"error": "results.csv not found"}))
        sys.exit(1)

    current_mtime = os.path.getmtime(csv_path)
    saved_mtime = manifest.get("csv_mtime", 0)
    if abs(current_mtime - saved_mtime) > 1.0:
        print(json.dumps({
            "error": "results.csv modified since perfection_select ran",
            "hint": "Re-run perfection_select.py to refresh row indices",
            "saved_mtime": saved_mtime,
            "current_mtime": current_mtime,
        }, indent=2))
        sys.exit(1)

    # Snapshot results.csv before modifying
    snapshot_dir = os.path.join(project_root, "state", "snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)
    ts = now_iso().replace(":", "").replace("-", "")
    snapshot_path = os.path.join(
        snapshot_dir, f"results_pre_perfection_{ts}.csv")
    shutil.copy2(csv_path, snapshot_path)

    # Load CSV and trait fields
    csv_rows = safe_read_csv(csv_path)
    if not csv_rows:
        print(json.dumps({"error": "results.csv is empty"}))
        sys.exit(1)

    trait_fields = _load_trait_fields(project_root)
    fieldnames = list(csv_rows[0].keys())

    # Ensure audit fields exist in fieldnames
    for af in ("audit_status", "audit_session", "audit_prior_values"):
        if af not in fieldnames:
            fieldnames.append(af)
            for row in csv_rows:
                row.setdefault(af, "")

    # Find perfection finds files
    output_dir = manifest.get("output_dir", "perfection_finds")
    finds_dir = os.path.join(project_root, output_dir)
    finds_files = sorted(glob.glob(os.path.join(finds_dir, "*.json")))

    # Filter to only perfection files (not deprecated/)
    finds_files = [f for f in finds_files
                   if os.path.basename(f).startswith("perfection_")]

    total_confirmed = 0
    total_corrected = 0
    total_unresolved = 0
    all_errors = []
    conf_before = []
    conf_after = []

    for fpath in finds_files:
        # Collect pre-merge confidence for reporting
        with open(fpath, "r", encoding="utf-8") as f:
            fdata = json.load(f)
        for i, rec in enumerate(fdata.get("records", [])):
            indices = fdata.get("original_row_indices", [])
            if i < len(indices) and indices[i] < len(csv_rows):
                try:
                    conf_before.append(float(
                        csv_rows[indices[i]].get(
                            "extraction_confidence", 0.5)))
                except (ValueError, TypeError):
                    pass

        confirmed, corrected, unresolved, errors = merge_one_file(
            fpath, csv_rows, trait_fields, args.session_id)
        total_confirmed += confirmed
        total_corrected += corrected
        total_unresolved += unresolved
        all_errors.extend(errors)

    # Collect post-merge confidence
    for fpath in finds_files:
        with open(fpath, "r", encoding="utf-8") as f:
            fdata = json.load(f)
        for i, rec in enumerate(fdata.get("records", [])):
            indices = fdata.get("original_row_indices", [])
            if i < len(indices) and indices[i] < len(csv_rows):
                try:
                    conf_after.append(float(
                        csv_rows[indices[i]].get(
                            "extraction_confidence", 0.5)))
                except (ValueError, TypeError):
                    pass

    avg_before = (sum(conf_before) / len(conf_before)) if conf_before else 0
    avg_after = (sum(conf_after) / len(conf_after)) if conf_after else 0

    # Write updated CSV
    if not args.dry_run and (total_confirmed + total_corrected + total_unresolved) > 0:
        atomic_rewrite_csv(csv_path, csv_rows, fieldnames)

        # Archive processed perfection finds
        dep_dir = os.path.join(finds_dir, "deprecated")
        os.makedirs(dep_dir, exist_ok=True)
        for fpath in finds_files:
            try:
                os.rename(fpath, os.path.join(
                    dep_dir, os.path.basename(fpath)))
            except OSError:
                pass

        # Update manifest
        manifest["status"] = "merged"
        manifest["merge_timestamp"] = now_iso()
        manifest["confirmed"] = total_confirmed
        manifest["corrected"] = total_corrected
        manifest["needs_human_review"] = total_unresolved
        manifest["confidence_before_avg"] = round(avg_before, 3)
        manifest["confidence_after_avg"] = round(avg_after, 3)
        manifest["snapshot"] = os.path.relpath(snapshot_path, project_root)
        safe_write_json(manifest_path, manifest)

        # Log event
        append_jsonl(
            os.path.join(project_root, "state", "run_log.jsonl"),
            {
                "event": "perfection_merge",
                "session_id": args.session_id,
                "timestamp": now_iso(),
                "confirmed": total_confirmed,
                "corrected": total_corrected,
                "needs_human_review": total_unresolved,
                "confidence_before_avg": round(avg_before, 3),
                "confidence_after_avg": round(avg_after, 3),
            })

    summary = {
        "records_examined": total_confirmed + total_corrected + total_unresolved,
        "confirmed": total_confirmed,
        "corrected": total_corrected,
        "needs_human_review": total_unresolved,
        "errors": all_errors,
        "confidence_before_avg": round(avg_before, 3),
        "confidence_after_avg": round(avg_after, 3),
        "snapshot": os.path.relpath(snapshot_path, project_root),
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
