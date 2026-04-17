#!/usr/bin/env python3
"""
Select suspect records from results.csv for re-verification.

Reads results.csv, selects records matching configurable quality criteria,
groups them by DOI, and writes synthetic finds/ JSON files that the existing
verify_and_write pipeline (build_audit_manifest -> Auditor -> reconcile ->
Adjudicator -> scrub) can process.

Usage:
    python3 scripts/perfection_select.py --project-root . \
        --session-id "perfection_20260411T120000" \
        --criteria low_confidence,unverified,unaudited \
        --confidence-threshold 0.70 \
        --output-dir perfection_finds/

Output: JSON summary to stdout + state/perfection_manifest.json.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
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


def _truthy(val):
    """Check if a CSV string value is truthy."""
    v = str(val or "").strip().lower()
    return v not in ("", "0", "false", "no", "none")


def _matches_criteria(row, criteria, opts):
    """Check if a row matches any of the specified criteria (OR logic)."""
    for criterion in criteria:
        if criterion == "low_confidence":
            try:
                conf = float(row.get("extraction_confidence", 1.0))
            except (ValueError, TypeError):
                conf = 0.0
            if conf < opts["confidence_threshold"]:
                return True, "low_confidence"

        elif criterion == "unverified":
            v = (row.get("verification") or "").strip().lower()
            if v in ("", "unaudited", "unverified"):
                return True, "unverified"

        elif criterion == "unaudited":
            a = (row.get("audit_status") or "").strip().lower()
            if a in ("", "unaudited"):
                return True, "unaudited"

        elif criterion == "flagged":
            if _truthy(row.get("flag_for_review")):
                return True, "flagged"

        elif criterion == "conflicts":
            species = (row.get("species") or "").strip()
            if species in opts.get("conflict_species", set()):
                return True, "conflict"

        elif criterion == "stale":
            sid = (row.get("session_id") or "").strip()
            if opts.get("session_before") and sid and sid < opts["session_before"]:
                return True, "stale"
            if opts.get("session_ids") and sid in opts["session_ids"]:
                return True, "stale"

    return False, ""


def _load_conflict_species(project_root):
    """Load species with cross-paper conflicts from audit_queue.json."""
    aq_path = os.path.join(project_root, "state", "audit_queue.json")
    queue = safe_read_json(aq_path, default=[])
    species = set()
    for entry in queue:
        if entry.get("reason", "") == "cross_paper_conflict":
            sp = (entry.get("species") or "").strip()
            if sp:
                species.add(sp)
    return species


def _doi_safe(doi):
    """Convert a DOI to a filesystem-safe string."""
    return re.sub(r'[^\w\-]', '_', doi or "unknown")


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


def build_synthetic_finds(doi, rows_with_indices, project_root, output_dir,
                          session_id, trait_fields):
    """Build a synthetic finds JSON file for one DOI group.

    Returns the output file path, or None if no valid records.
    """
    first = rows_with_indices[0][1]
    pdf_path = (first.get("pdf_path") or "").strip()

    # Verify PDF exists
    if pdf_path:
        abs_pdf = os.path.join(project_root, pdf_path)
        if not os.path.isfile(abs_pdf):
            pdf_path = ""

    if not pdf_path:
        return None

    records = []
    row_indices = []
    for idx, row in rows_with_indices:
        rec = {"species": (row.get("species") or "").strip()}
        rec["source_page"] = (row.get("source_page") or "").strip()
        rec["source_context"] = (row.get("source_context") or "").strip()
        try:
            rec["extraction_confidence"] = float(
                row.get("extraction_confidence", 0.5))
        except (ValueError, TypeError):
            rec["extraction_confidence"] = 0.5
        rec["extraction_reasoning"] = (
            row.get("extraction_reasoning") or "").strip()
        rec["flag_for_review"] = _truthy(row.get("flag_for_review"))
        rec["notes"] = (row.get("notes") or "").strip()
        rec["source_type"] = (row.get("source_type") or "").strip()

        # Copy all trait fields
        for tf in trait_fields:
            rec[tf] = (row.get(tf) or "").strip()

        records.append(rec)
        row_indices.append(idx)

    if not records:
        return None

    finds = {
        "doi": doi,
        "title": (first.get("paper_title") or "").strip(),
        "pdf_path": pdf_path,
        "pdf_source": "perfection_pass",
        "extraction_timestamp": now_iso(),
        "extraction_mode": "perfection_pass",
        "source_query": "perfection_pass",
        "perfection_session": session_id,
        "original_row_indices": row_indices,
        "records": records,
        "paper_metadata": {
            "year": first.get("paper_year", ""),
            "journal": (first.get("paper_journal") or "").strip(),
            "first_author": (first.get("first_author") or "").strip(),
            "paper_authors": (first.get("paper_authors") or "").strip(),
        },
    }

    os.makedirs(output_dir, exist_ok=True)
    ts = now_iso().replace(":", "").replace("-", "")
    fname = f"perfection_{_doi_safe(doi)}_{ts}.json"
    fpath = os.path.join(output_dir, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(finds, f, indent=2, ensure_ascii=False)
    return fpath


def main():
    parser = argparse.ArgumentParser(
        description="Select suspect records for re-verification")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--session-id", required=True,
                        help="Perfection pass session ID")
    parser.add_argument("--criteria",
                        default="low_confidence,unverified,unaudited",
                        help="Comma-separated selection criteria")
    parser.add_argument("--confidence-threshold", type=float, default=0.70)
    parser.add_argument("--session-before", default=None,
                        help="Select records from sessions before this ID")
    parser.add_argument("--session-ids", default=None,
                        help="Comma-separated session IDs to re-verify")
    parser.add_argument("--doi", default=None,
                        help="Limit to specific DOI")
    parser.add_argument("--all-for-doi", action="store_true",
                        help="Include ALL records for matching DOIs")
    parser.add_argument("--max-records", type=int, default=None,
                        help="Maximum records to select")
    parser.add_argument("--output-dir", default="perfection_finds")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be selected without writing")
    args = parser.parse_args()

    project_root = args.project_root
    criteria = [c.strip() for c in args.criteria.split(",") if c.strip()]

    # Check for existing in-progress perfection pass
    manifest_path = os.path.join(project_root, "state",
                                 "perfection_manifest.json")
    existing = safe_read_json(manifest_path, default={})
    if existing.get("status") in ("selected", "verifying"):
        print(json.dumps({
            "error": "Existing perfection pass in progress",
            "existing_session": existing.get("session_id", ""),
            "status": existing.get("status", ""),
            "hint": "Complete or delete state/perfection_manifest.json first",
        }, indent=2))
        sys.exit(1)

    # Load CSV
    csv_path = os.path.join(project_root, "results.csv")
    rows = safe_read_csv(csv_path)
    if not rows:
        print(json.dumps({"error": "results.csv is empty or missing"}))
        sys.exit(1)

    # Build options for criteria matching
    opts = {
        "confidence_threshold": args.confidence_threshold,
        "session_before": args.session_before,
        "session_ids": (set(args.session_ids.split(","))
                        if args.session_ids else set()),
        "conflict_species": (_load_conflict_species(project_root)
                             if "conflicts" in criteria else set()),
    }

    trait_fields = _load_trait_fields(project_root)

    # Select matching records
    selected = []  # (row_index, row, reason)
    for idx, row in enumerate(rows):
        if args.doi:
            row_doi = (row.get("doi") or "").strip()
            if row_doi != args.doi:
                continue
        matched, reason = _matches_criteria(row, criteria, opts)
        if matched:
            selected.append((idx, row, reason))

    # If --all-for-doi, expand to all records sharing DOIs with selected
    if args.all_for_doi and selected:
        selected_dois = {(r.get("doi") or "").strip()
                         for _, r, _ in selected} - {""}
        selected_indices = {idx for idx, _, _ in selected}
        for idx, row in enumerate(rows):
            if idx in selected_indices:
                continue
            if (row.get("doi") or "").strip() in selected_dois:
                selected.append((idx, row, "all_for_doi"))

    # Apply max-records limit
    if args.max_records and len(selected) > args.max_records:
        selected = selected[:args.max_records]

    # Group by DOI
    by_doi = defaultdict(list)
    for idx, row, reason in selected:
        doi = (row.get("doi") or "").strip() or f"no_doi_{idx}"
        by_doi[doi].append((idx, row))

    # Build synthetic finds files
    output_dir = os.path.join(project_root, args.output_dir)
    finds_files = []
    skipped_no_pdf = []
    records_by_doi = {}

    for doi, rows_with_indices in by_doi.items():
        if args.dry_run:
            finds_files.append(
                f"(dry-run) {doi}: {len(rows_with_indices)} records")
            records_by_doi[doi] = [idx for idx, _ in rows_with_indices]
            continue

        fpath = build_synthetic_finds(
            doi, rows_with_indices, project_root, output_dir,
            args.session_id, trait_fields)
        if fpath:
            rel = os.path.relpath(fpath, project_root)
            finds_files.append(rel)
            records_by_doi[doi] = [idx for idx, _ in rows_with_indices]
        else:
            for idx, row in rows_with_indices:
                skipped_no_pdf.append({
                    "row_id": idx,
                    "doi": doi,
                    "species": (row.get("species") or "").strip(),
                    "reason": "no_usable_pdf",
                })

    reason_counts = defaultdict(int)
    for _, _, reason in selected:
        reason_counts[reason] += 1

    total_selected = sum(len(v) for v in records_by_doi.values())

    if not args.dry_run:
        csv_mtime = os.path.getmtime(csv_path)
        manifest = {
            "session_id": args.session_id,
            "started": now_iso(),
            "criteria": criteria,
            "confidence_threshold": args.confidence_threshold,
            "total_selected": total_selected,
            "total_skipped_no_pdf": len(skipped_no_pdf),
            "dois_selected": len(records_by_doi),
            "finds_files": finds_files,
            "status": "selected",
            "records_by_doi": records_by_doi,
            "csv_mtime": csv_mtime,
            "output_dir": args.output_dir,
        }
        os.makedirs(os.path.join(project_root, "state"), exist_ok=True)
        safe_write_json(manifest_path, manifest)

        if skipped_no_pdf:
            skip_path = os.path.join(project_root, "state",
                                     "perfection_skipped.json")
            safe_write_json(skip_path, skipped_no_pdf)

        append_jsonl(
            os.path.join(project_root, "state", "run_log.jsonl"),
            {
                "event": "perfection_select",
                "session_id": args.session_id,
                "timestamp": now_iso(),
                "criteria": criteria,
                "total_selected": total_selected,
                "dois": len(records_by_doi),
                "skipped_no_pdf": len(skipped_no_pdf),
            })

    summary = {
        "total_in_csv": len(rows),
        "total_selected": total_selected,
        "total_skipped_no_pdf": len(skipped_no_pdf),
        "dois_selected": len(records_by_doi),
        "finds_files": len(finds_files),
        "reason_counts": dict(reason_counts),
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
