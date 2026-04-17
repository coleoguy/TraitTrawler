#!/usr/bin/env python3
"""
Merge Opus Adjudicator results back into finds/ files.

Reads adjudication_results/*.json produced by the Adjudicator agent and
applies the resolved values to the corresponding finds/ file, updating
the field value and adjusting confidence based on the adjudicator's
certainty.

Usage:
    python3 scripts/merge_adjudication.py --project-root .

Output: JSON summary to stdout.
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize(v):
    return str(v or "").strip().lower()


def apply_resolution(finds_data, resolution):
    """Apply one adjudication resolution to a finds file.

    resolution has: species, source_page, field, resolved_value,
    confidence, reasoning.
    """
    species_key = normalize(resolution.get("species", ""))
    page_key = str(resolution.get("source_page", "")).strip()
    field = resolution.get("field", "")
    value = resolution.get("resolved_value", "")
    conf = resolution.get("confidence", 0.75)
    reasoning = resolution.get("reasoning", "")

    for rec in finds_data.get("records", []):
        if normalize(rec.get("species", "")) != species_key:
            continue
        if page_key and str(rec.get("source_page", "")).strip() != page_key:
            continue
        # Match — apply
        rec[field] = value
        # Use the higher of adjudicator confidence vs existing
        existing = float(rec.get("extraction_confidence", 0.5))
        rec["extraction_confidence"] = round(max(existing, float(conf)), 2)
        # Track adjudication in verification_notes
        existing_notes = rec.get("verification_notes", "")
        new_note = f"Adjudicated {field}: {reasoning}"
        if existing_notes:
            rec["verification_notes"] = f"{existing_notes}; {new_note}"
        else:
            rec["verification_notes"] = new_note
        # Upgrade verification status
        if rec.get("verification") in ("disputed", "partial_agreement"):
            rec["verification"] = "adjudicated"
        return True
    return False


def merge_adjudication_file(project_root, adj_path, finds_dir="finds"):
    """Merge one adjudication_results file back into its finds file.

    Returns (applied_count, finds_file_name).
    """
    with open(adj_path, "r", encoding="utf-8") as f:
        adj_data = json.load(f)

    finds_filename = adj_data.get("finds_file", "")
    resolutions = adj_data.get("resolutions", [])

    if not finds_filename or not resolutions:
        return 0, finds_filename

    finds_path = os.path.join(project_root, finds_dir, finds_filename)
    if not os.path.isfile(finds_path):
        return 0, finds_filename

    with open(finds_path, "r", encoding="utf-8") as f:
        finds_data = json.load(f)

    applied = 0
    for res in resolutions:
        if apply_resolution(finds_data, res):
            applied += 1

    # Write back
    finds_data["adjudication_timestamp"] = now_iso()
    with open(finds_path, "w", encoding="utf-8") as f:
        json.dump(finds_data, f, indent=2, ensure_ascii=False)

    # Move adjudication result to state/dealt/
    dealt_dir = os.path.join(project_root, "state", "dealt")
    os.makedirs(dealt_dir, exist_ok=True)
    try:
        os.rename(adj_path, os.path.join(
            dealt_dir, os.path.basename(adj_path)))
    except OSError:
        pass

    return applied, finds_filename


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--finds-dir", default="finds",
                        help="Directory containing finds files (default: finds)")
    args = parser.parse_args()

    adj_dir = os.path.join(args.project_root, "adjudication_results")
    if not os.path.isdir(adj_dir):
        print(json.dumps({"files_merged": 0, "resolutions_applied": 0}))
        return

    files = sorted(glob.glob(os.path.join(adj_dir, "*.json")))

    total_applied = 0
    per_file = []
    for fpath in files:
        applied, finds_name = merge_adjudication_file(
            args.project_root, fpath, finds_dir=args.finds_dir)
        total_applied += applied
        per_file.append({
            "adjudication_file": os.path.basename(fpath),
            "finds_file": finds_name,
            "applied": applied,
        })

    # Clean up stale disputes files (whose adjudication is now merged)
    disputes_dir = os.path.join(args.project_root, "adjudication")
    if os.path.isdir(disputes_dir):
        dealt_dir = os.path.join(args.project_root, "state", "dealt")
        os.makedirs(dealt_dir, exist_ok=True)
        for f in glob.glob(os.path.join(disputes_dir, "*.json")):
            try:
                os.rename(f, os.path.join(dealt_dir, os.path.basename(f)))
            except OSError:
                pass

    print(json.dumps({
        "files_merged": len(files),
        "resolutions_applied": total_applied,
        "per_file": per_file,
    }, indent=2))


if __name__ == "__main__":
    main()
