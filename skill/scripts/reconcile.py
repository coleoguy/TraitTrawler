#!/usr/bin/env python3
"""
Reconciliation engine for TraitTrawler v5.

Mechanically compares Extractor output (finds/) against Auditor output
(audit_results/) for the same paper. Produces:
  1. Reconciled finds/ files with agreement-based confidence
  2. Disputes file for Opus adjudication (if any disagreements)
  3. Calibration observations for calibration_data.jsonl

The Manager runs this after the Auditor returns, before scrub.py.

Usage:
    python3 scripts/reconcile.py --project-root . --finds-file finds/example.json

Output: JSON summary to stdout.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(project_root):
    """Load output_fields and identify trait fields."""
    config_path = os.path.join(project_root, "collector_config.yaml")
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except (ImportError, FileNotFoundError):
        config = {}

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

    output_fields = []
    for f in config.get("output_fields", []):
        name = f["name"] if isinstance(f, dict) else f
        output_fields.append(name)

    trait_fields = [f for f in output_fields if f not in METADATA_FIELDS]
    return output_fields, trait_fields


def normalize_for_comparison(value):
    """Normalize a value for fuzzy comparison."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s)
    return s


def values_match(v1, v2):
    """Check if two extracted values are equivalent."""
    n1 = normalize_for_comparison(v1)
    n2 = normalize_for_comparison(v2)
    if n1 == n2:
        return True

    # Numeric comparison: 22 == 22.0
    try:
        f1, f2 = float(n1), float(n2)
        if abs(f1 - f2) < 0.001:
            return True
    except (ValueError, TypeError):
        pass

    return False


def find_audit_file(project_root, doi):
    """Find the audit_results file for a given DOI."""
    audit_dir = os.path.join(project_root, "audit_results")
    if not os.path.isdir(audit_dir):
        return None

    doi_safe = re.sub(r'[^\w\-]', '_', doi or "")
    for fname in os.listdir(audit_dir):
        if not fname.endswith(".json"):
            continue
        if doi_safe and doi_safe in fname:
            return os.path.join(audit_dir, fname)

    # Fallback: check DOI inside the file
    for fname in os.listdir(audit_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(audit_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("doi") == doi:
                return fpath
        except (json.JSONDecodeError, OSError):
            continue
    return None


def match_records(extractor_records, auditor_records):
    """Match Extractor and Auditor records by species + source_page.

    Returns list of (extractor_record, auditor_record) tuples.
    Unmatched records returned as (record, None) or (None, record).
    """
    matched = []
    used_auditor = set()

    for ext_rec in extractor_records:
        ext_sp = normalize_for_comparison(ext_rec.get("species", ""))
        ext_pg = str(ext_rec.get("source_page", "")).strip()
        best_match = None
        best_idx = None

        for i, aud_rec in enumerate(auditor_records):
            if i in used_auditor:
                continue
            aud_sp = normalize_for_comparison(aud_rec.get("species", ""))
            aud_pg = str(aud_rec.get("source_page", "")).strip()

            # Exact species match
            if ext_sp == aud_sp:
                # Prefer same page, but accept any page match
                if ext_pg == aud_pg:
                    best_match = aud_rec
                    best_idx = i
                    break
                elif best_match is None:
                    best_match = aud_rec
                    best_idx = i

        if best_match is not None:
            matched.append((ext_rec, best_match))
            used_auditor.add(best_idx)
        else:
            matched.append((ext_rec, None))

    # Auditor-only records (Extractor missed them)
    for i, aud_rec in enumerate(auditor_records):
        if i not in used_auditor:
            status = aud_rec.get("status", "")
            matched.append((None, aud_rec))

    return matched


def reconcile_pair(ext_rec, aud_rec, trait_fields):
    """Reconcile a matched pair of records.

    Returns (reconciled_record, disputes, calibration_obs).
    """
    disputes = []
    calibration_obs = []

    if ext_rec is None:
        # Auditor found a record the Extractor missed
        rec = dict(aud_rec)
        rec["verification"] = "auditor_added"
        rec["extraction_confidence"] = min(
            float(aud_rec.get("extraction_confidence", 0.7)), 0.75
        )
        rec["verification_notes"] = "Record found by Auditor but missed by Extractor"
        return rec, [], []

    if aud_rec is None:
        # Extractor found a record the Auditor couldn't verify
        # (species_not_found or page mismatch)
        rec = dict(ext_rec)
        rec["verification"] = "unverified"
        rec["extraction_confidence"] = min(
            float(ext_rec.get("extraction_confidence", 0.5)), 0.60
        )
        rec["verification_notes"] = "Auditor could not locate this record on cited page"
        rec["flag_for_review"] = True
        return rec, [], []

    # Both extracted — compare trait fields
    rec = dict(ext_rec)
    agreements = 0
    disagreements = 0
    total_fields = 0

    for field in trait_fields:
        ext_val = ext_rec.get(field, "")
        aud_val = aud_rec.get(field, "")

        # Skip if both empty
        if normalize_for_comparison(ext_val) == "" and \
           normalize_for_comparison(aud_val) == "":
            continue

        total_fields += 1

        if values_match(ext_val, aud_val):
            agreements += 1
            calibration_obs.append({
                "field": field,
                "predicted_confidence": float(
                    ext_rec.get("extraction_confidence", 0.5)),
                "correct": True,
                "source": "auditor_agreement",
            })
        else:
            disagreements += 1
            disputes.append({
                "field": field,
                "extractor_value": str(ext_val),
                "auditor_value": str(aud_val),
                "source_page": str(ext_rec.get("source_page", "")),
            })
            calibration_obs.append({
                "field": field,
                "predicted_confidence": float(
                    ext_rec.get("extraction_confidence", 0.5)),
                "correct": False,
                "source": "auditor_disagreement",
            })

    # Agreement-based confidence scoring
    if total_fields == 0:
        # No trait fields to compare (unusual)
        agreement_rate = 1.0
    else:
        agreement_rate = agreements / total_fields

    if agreement_rate == 1.0:
        # Full agreement: high confidence
        # Use the higher of the two raw scores, boosted
        ext_conf = float(ext_rec.get("extraction_confidence", 0.5))
        aud_conf = float(aud_rec.get("extraction_confidence", 0.5))
        confidence = min(max(ext_conf, aud_conf) + 0.05, 0.99)
        rec["verification"] = "confirmed"
        rec["verification_notes"] = (
            f"Full agreement on {agreements}/{total_fields} trait fields"
        )
    elif disagreements <= 1 and agreements >= 3:
        # Mostly agree, minor disagreement — don't resolve here,
        # route the disputed field(s) to adjudication
        confidence = 0.70
        rec["verification"] = "partial_agreement"
        rec["verification_notes"] = (
            f"Agreement on {agreements}/{total_fields} fields; "
            f"{disagreements} disputed"
        )
    else:
        # Significant disagreement — route all fields to adjudication
        confidence = 0.50
        rec["verification"] = "disputed"
        rec["verification_notes"] = (
            f"Disagreement on {disagreements}/{total_fields} fields"
        )
        rec["flag_for_review"] = True

    rec["extraction_confidence"] = round(confidence, 2)

    return rec, disputes, calibration_obs


def reconcile_file(project_root, finds_path, trait_fields):
    """Reconcile a single finds file against its audit result.

    Returns (reconciled_records, all_disputes, all_calibration, summary).
    """
    with open(finds_path, "r", encoding="utf-8") as f:
        finds_data = json.load(f)

    doi = finds_data.get("doi", "")
    document_type = finds_data.get("document_type", "unknown")
    ext_records = finds_data.get("records", [])

    audit_path = find_audit_file(project_root, doi)

    if audit_path is None:
        # No audit result — Auditor failed or didn't run for this file.
        # Deflate all confidence scores since unverified.
        for rec in ext_records:
            raw = float(rec.get("extraction_confidence", 0.5))
            rec["extraction_confidence"] = round(min(raw, 0.60), 2)
            rec["verification"] = "unaudited"
            rec["verification_notes"] = "No audit result available"
            rec["flag_for_review"] = True

        summary = {
            "doi": doi,
            "status": "no_audit",
            "records": len(ext_records),
            "confirmed": 0,
            "disputed": 0,
            "auditor_added": 0,
        }
        return ext_records, [], [], summary

    with open(audit_path, "r", encoding="utf-8") as f:
        audit_data = json.load(f)

    aud_records = [r for r in audit_data.get("records", [])
                   if r.get("status") != "species_not_found"]

    matched = match_records(ext_records, aud_records)

    reconciled = []
    all_disputes = []
    all_calibration = []
    confirmed = 0
    disputed = 0
    auditor_added = 0

    for ext_rec, aud_rec in matched:
        rec, disputes, cal_obs = reconcile_pair(ext_rec, aud_rec, trait_fields)

        # Attach DOI/species/document_type to calibration observations
        species = rec.get("species", "")
        for obs in cal_obs:
            obs["doi"] = doi
            obs["species"] = species
            obs["document_type"] = document_type

        reconciled.append(rec)
        all_calibration.extend(cal_obs)

        if disputes:
            all_disputes.append({
                "species": species,
                "source_page": rec.get("source_page", ""),
                "disputes": disputes,
            })
            disputed += 1
        elif ext_rec is None:
            auditor_added += 1
        elif rec.get("verification") == "confirmed":
            confirmed += 1

    # Update the finds file with reconciled records
    finds_data["records"] = reconciled
    finds_data["reconciliation_timestamp"] = now_iso()
    with open(finds_path, "w", encoding="utf-8") as f:
        json.dump(finds_data, f, indent=2, ensure_ascii=False)

    # Write disputes file if any
    if all_disputes:
        adj_dir = os.path.join(project_root, "adjudication")
        os.makedirs(adj_dir, exist_ok=True)
        doi_safe = re.sub(r'[^\w\-]', '_', doi or "unknown")
        disputes_path = os.path.join(
            adj_dir, f"{doi_safe}_{now_iso().replace(':', '')}.json")
        with open(disputes_path, "w", encoding="utf-8") as f:
            json.dump({
                "doi": doi,
                "pdf_path": finds_data.get("pdf_path", ""),
                "finds_file": os.path.basename(finds_path),
                "disputes": all_disputes,
                "timestamp": now_iso(),
            }, f, indent=2, ensure_ascii=False)

    # Clean up audit file (move to state/dealt/)
    dealt_dir = os.path.join(project_root, "state", "dealt")
    os.makedirs(dealt_dir, exist_ok=True)
    try:
        os.rename(audit_path, os.path.join(
            dealt_dir, os.path.basename(audit_path)))
    except OSError:
        pass

    summary = {
        "doi": doi,
        "status": "reconciled",
        "records": len(reconciled),
        "confirmed": confirmed,
        "disputed": disputed,
        "auditor_added": auditor_added,
        "agreement_rate": round(
            confirmed / max(len(matched), 1), 2),
    }
    return reconciled, all_disputes, all_calibration, summary


def append_calibration(project_root, observations, session_id):
    """Append calibration observations to calibration_data.jsonl."""
    if not observations:
        return
    cal_path = os.path.join(project_root, "state", "calibration_data.jsonl")
    os.makedirs(os.path.dirname(cal_path), exist_ok=True)
    with open(cal_path, "a", encoding="utf-8") as f:
        for obs in observations:
            obs["session_id"] = session_id
            obs["timestamp"] = now_iso()
            f.write(json.dumps(obs, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile Extractor vs Auditor extractions")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--finds-file", default=None,
                        help="Single finds file to reconcile")
    parser.add_argument("--session-id", default="unknown")
    args = parser.parse_args()

    project_root = args.project_root
    output_fields, trait_fields = load_config(project_root)

    if args.finds_file:
        files = [os.path.join(project_root, args.finds_file)
                 if not os.path.isabs(args.finds_file)
                 else args.finds_file]
    else:
        finds_dir = os.path.join(project_root, "finds")
        files = sorted(glob.glob(os.path.join(finds_dir, "*.json")))

    total_summary = {
        "files_reconciled": 0,
        "total_records": 0,
        "confirmed": 0,
        "disputed": 0,
        "auditor_added": 0,
        "unaudited": 0,
        "has_disputes": False,
        "per_file": [],
    }

    all_calibration = []

    for fpath in files:
        if not os.path.isfile(fpath):
            continue
        reconciled, disputes, cal_obs, summary = reconcile_file(
            project_root, fpath, trait_fields)
        all_calibration.extend(cal_obs)

        total_summary["files_reconciled"] += 1
        total_summary["total_records"] += summary["records"]
        total_summary["confirmed"] += summary["confirmed"]
        total_summary["disputed"] += summary["disputed"]
        total_summary["auditor_added"] += summary["auditor_added"]
        if summary["status"] == "no_audit":
            total_summary["unaudited"] += summary["records"]
        if disputes:
            total_summary["has_disputes"] = True
        total_summary["per_file"].append(summary)

    # Write calibration data
    append_calibration(project_root, all_calibration, args.session_id)

    # Print summary
    print(json.dumps(total_summary, indent=2))


if __name__ == "__main__":
    main()
