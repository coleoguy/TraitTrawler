#!/usr/bin/env python3
"""
End-to-end Writer pipeline for TraitTrawler.

Processes finds/ JSON files through: parse → taxonomy resolution →
confidence calibration → field stripping → validation + dedup + write
(via csv_writer.py) → verify → cleanup → summary.

Replaces the prose instructions in writer.md with deterministic logic.
The Writer agent calls this script instead of re-implementing the
pipeline each spawn.

Usage:
    python3 scripts/write_finds.py --project-root . --session-id 20260328T142904

Output: JSON summary to stdout. Also writes summary to
    writer_results/{timestamp}.json
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# Add scripts/ to path so we can import csv_writer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from csv_writer import SchemaEnforcedWriter
from validate_finds_json import validate_file


def now_iso():
    """Canonical UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Fields that are internal to the consensus process — strip before CSV write
INTERNAL_FIELDS = {"agent_values", "enumeration_inventory_size"}


def load_config(project_root):
    """Load relevant config settings."""
    config_path = os.path.join(project_root, "collector_config.yaml")
    config = {}
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except (ImportError, FileNotFoundError):
        pass
    return config


def resolve_taxonomy(project_root, species_names):
    """Call taxonomy_resolver.py for a batch of species names.

    Returns dict mapping original_name → resolution result.
    """
    if not species_names:
        return {}

    cache_path = os.path.join(project_root, "state", "taxonomy_cache.json")
    config = load_config(project_root)
    kingdom = config.get("kingdom", "Animalia")

    cmd = [
        sys.executable, os.path.join(project_root, "scripts",
                                     "taxonomy_resolver.py"),
        "--species",
    ] + list(species_names) + [
        "--cache", cache_path,
        "--kingdom", kingdom,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=60)
        if result.returncode != 0:
            # GBIF may be down — retry in offline mode
            print(f"WARNING: taxonomy_resolver.py failed, retrying offline: "
                  f"{result.stderr}", file=sys.stderr)
            return _resolve_offline(cmd)
        data = json.loads(result.stdout)
        lookup = {}
        for r in data.get("results", []):
            lookup[r.get("query", "")] = r
        return lookup
    except subprocess.TimeoutExpired:
        print("WARNING: Taxonomy resolution timed out, using offline mode",
              file=sys.stderr)
        return _resolve_offline(cmd)
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: taxonomy resolution error: {e}", file=sys.stderr)
        return {}


def _resolve_offline(base_cmd):
    """Re-run taxonomy_resolver.py with --offline flag."""
    try:
        result = subprocess.run(base_cmd + ["--offline"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {r.get("query", ""): r
                    for r in data.get("results", [])}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return {}


def apply_taxonomy(record, resolution):
    """Apply a single taxonomy resolution to a record."""
    if not resolution:
        return 0
    action = resolution.get("action", "")
    resolved = 0

    if action == "accepted":
        # Fill empty family/genus from GBIF
        if not record.get("family") and resolution.get("family"):
            record["family"] = resolution["family"]
            resolved = 1
        if not record.get("genus") and resolution.get("genus"):
            record["genus"] = resolution["genus"]
            resolved = 1
        if resolution.get("gbif_key"):
            record["gbif_key"] = str(resolution["gbif_key"])
            record["accepted_name"] = resolution.get("accepted_name", "")

    elif action == "synonym_resolved":
        original = record.get("species", "")
        record["species"] = resolution.get("accepted_name", original)
        record["taxonomy_note"] = f"Synonym of {original}"
        if not record.get("family") and resolution.get("family"):
            record["family"] = resolution["family"]
        if not record.get("genus") and resolution.get("genus"):
            record["genus"] = resolution["genus"]
        if resolution.get("gbif_key"):
            record["gbif_key"] = str(resolution["gbif_key"])
            record["accepted_name"] = resolution.get("accepted_name", "")
        resolved = 1

    elif action == "fuzzy_high_confidence":
        # Fuzzy match >= 90% — accept with note
        record["taxonomy_note"] = (
            f"Fuzzy match ({resolution.get('confidence', 0)}%): "
            f"{resolution.get('accepted_name', '')}"
        )
        if not record.get("family") and resolution.get("family"):
            record["family"] = resolution["family"]
        if not record.get("genus") and resolution.get("genus"):
            record["genus"] = resolution["genus"]
        if resolution.get("gbif_key"):
            record["gbif_key"] = str(resolution["gbif_key"])
            record["accepted_name"] = resolution.get("accepted_name", "")
        resolved = 1

    elif action == "fuzzy_low_confidence":
        # Fuzzy match < 90% — flag
        record["flag_for_review"] = True
        record["taxonomy_note"] = (
            f"Low-confidence fuzzy match ({resolution.get('confidence', 0)}%): "
            f"{resolution.get('accepted_name', '')}"
        )

    elif action == "deferred_offline":
        # GBIF was unavailable — extract genus from binomial, flag for later
        if not record.get("genus") and resolution.get("genus"):
            record["genus"] = resolution["genus"]
        record["taxonomy_note"] = "GBIF unavailable; resolve in next session"
        record["flag_for_review"] = True

    elif action in ("flag_not_found", "flag_higher_rank"):
        record["taxonomy_note"] = resolution.get("notes", f"GBIF: {action}")

    return resolved


def apply_calibration(record, calibration_model):
    """Apply isotonic calibration to extraction_confidence."""
    if not calibration_model:
        return
    if calibration_model.get("status") != "calibrated":
        return

    raw = record.get("extraction_confidence")
    if raw is None:
        return
    try:
        raw_f = float(raw)
    except (ValueError, TypeError):
        return

    global_model = calibration_model.get("global_model", {})
    method = global_model.get("method", "")

    if method == "isotonic_regression":
        x_pts = global_model.get("thresholds_x", [])
        y_pts = global_model.get("thresholds_y", [])
        if x_pts and y_pts:
            # Linear interpolation between thresholds
            if raw_f <= x_pts[0]:
                calibrated = y_pts[0]
            elif raw_f >= x_pts[-1]:
                calibrated = y_pts[-1]
            else:
                for j in range(len(x_pts) - 1):
                    if x_pts[j] <= raw_f <= x_pts[j + 1]:
                        t = ((raw_f - x_pts[j]) /
                             (x_pts[j + 1] - x_pts[j]))
                        calibrated = y_pts[j] + t * (y_pts[j + 1] - y_pts[j])
                        break
                else:
                    calibrated = raw_f
            record["calibrated_confidence"] = round(calibrated, 4)

    elif method == "binned_calibration":
        bins = global_model.get("bins", {})
        for bin_range, bin_data in bins.items():
            lo, hi = bin_range.split("-")
            if float(lo) <= raw_f < float(hi) or (
                    float(hi) == 1.0 and raw_f == 1.0):
                record["calibrated_confidence"] = round(
                    bin_data.get("calibrated", raw_f), 4)
                break


def process_finds(project_root, session_id):
    """Process all finds/ files through the full Writer pipeline."""
    finds_dir = os.path.join(project_root, "finds")
    results_dir = os.path.join(project_root, "writer_results")
    os.makedirs(results_dir, exist_ok=True)

    # Collect finds files, oldest first
    pattern = os.path.join(finds_dir, "*.json")
    files = sorted(glob.glob(pattern))

    if not files:
        summary = {
            "files_processed": 0,
            "records_written": 0,
            "records_rejected": 0,
            "records_flagged": 0,
            "records_duplicate": 0,
            "taxonomy_resolved": 0,
            "errors": [],
        }
        json.dump(summary, sys.stdout, indent=2)
        print()
        return summary

    # Load config
    config = load_config(project_root)
    do_taxonomy = config.get("taxonomy_resolution", True)

    # Load calibration model if available
    cal_path = os.path.join(project_root, "state", "calibration_model.json")
    calibration_model = None
    if os.path.exists(cal_path):
        try:
            with open(cal_path, "r", encoding="utf-8") as f:
                cal_data = json.load(f)
            n_obs = cal_data.get("n_observations", 0)
            if n_obs >= 10 and cal_data.get("status") == "calibrated":
                calibration_model = cal_data
        except (json.JSONDecodeError, OSError):
            pass

    # Initialize the schema-enforced writer
    writer = SchemaEnforcedWriter(project_root)

    total_written = 0
    total_rejected = 0
    total_flagged = 0
    total_duplicate = 0
    total_taxonomy = 0
    errors = []
    files_processed = 0

    for fpath in files:
        fname = os.path.basename(fpath)

        # Step 1: Validate structure
        ok, validation_errors = validate_file(fpath)
        if not ok:
            errors.append({
                "file": fname,
                "stage": "validation",
                "details": validation_errors,
            })
            # Don't delete — leave for manual inspection
            continue

        # Step 2: Parse
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            errors.append({
                "file": fname,
                "stage": "parse",
                "details": str(e),
            })
            continue

        records = data.get("records", [])
        if not records:
            # Valid file but no records — clean up
            files_processed += 1
            try:
                os.remove(fpath)
            except OSError:
                pass
            continue

        # Step 3: Taxonomy resolution
        if do_taxonomy:
            unique_species = set()
            for rec in records:
                sp = rec.get("species", "").strip()
                if sp:
                    unique_species.add(sp)

            if unique_species:
                tax_lookup = resolve_taxonomy(project_root, unique_species)
                for rec in records:
                    sp = rec.get("species", "").strip()
                    if sp and sp in tax_lookup:
                        total_taxonomy += apply_taxonomy(rec, tax_lookup[sp])

        # Step 4: Confidence calibration
        if calibration_model:
            for rec in records:
                apply_calibration(rec, calibration_model)

        # Step 5: Strip internal fields
        for rec in records:
            for field in INTERNAL_FIELDS:
                rec.pop(field, None)

        # Step 6: Add session metadata
        processed_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for rec in records:
            if session_id:
                rec["session_id"] = session_id
            rec["processed_date"] = processed_date
            # Carry forward paper-level fields
            if not rec.get("doi"):
                rec["doi"] = data.get("doi", "")
            if not rec.get("paper_title"):
                rec["paper_title"] = data.get("title", "")
            pm = data.get("paper_metadata", {})
            if pm:
                if not rec.get("paper_year") and pm.get("year"):
                    rec["paper_year"] = pm["year"]
                if not rec.get("paper_journal") and pm.get("journal"):
                    rec["paper_journal"] = pm["journal"]
                if not rec.get("first_author") and pm.get("first_author"):
                    rec["first_author"] = pm["first_author"]
            if not rec.get("pdf_source"):
                rec["pdf_source"] = data.get("pdf_source", "")
            if not rec.get("pdf_path"):
                rec["pdf_path"] = data.get("pdf_path", "")

        # Step 7: Write via SchemaEnforcedWriter (handles validation,
        # dedup, atomic write, post-write verification)
        try:
            report = writer.append_records(records, session_id=session_id)
            total_written += report.accepted
            total_rejected += report.rejected
            total_flagged += report.flagged
            total_duplicate += report.duplicates

            if report.errors:
                for idx, err in report.errors:
                    errors.append({
                        "file": fname,
                        "stage": "write",
                        "record_index": idx,
                        "details": str(err),
                    })

        except RuntimeError as e:
            errors.append({
                "file": fname,
                "stage": "write",
                "details": str(e),
            })
            # Don't delete on write failure
            continue

        # Step 8: Cleanup on success
        files_processed += 1
        try:
            os.remove(fpath)
        except OSError as e:
            errors.append({
                "file": fname,
                "stage": "cleanup",
                "details": f"Could not delete: {e}",
            })

    # Write summary
    summary = {
        "files_processed": files_processed,
        "records_written": total_written,
        "records_rejected": total_rejected,
        "records_flagged": total_flagged,
        "records_duplicate": total_duplicate,
        "taxonomy_resolved": total_taxonomy,
        "errors": errors,
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    summary_path = os.path.join(results_dir, f"{timestamp}.json")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    except OSError as e:
        print(f"WARNING: Could not write summary: {e}", file=sys.stderr)

    json.dump(summary, sys.stdout, indent=2)
    print()
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Process finds/ files through the Writer pipeline"
    )
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--session-id", default="",
                        help="Session identifier")
    args = parser.parse_args()

    process_finds(args.project_root, args.session_id)


if __name__ == "__main__":
    main()
