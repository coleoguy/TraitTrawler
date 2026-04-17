#!/usr/bin/env python3
"""
End-to-end Writer pipeline for TraitTrawler.

Processes finds/ JSON files through: parse → taxonomy resolution →
confidence calibration → field stripping → validation + dedup + write
(via csv_writer.py) → verify → cleanup → summary.

The Manager calls this script directly (no agent spawn needed).

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
import urllib.request
import urllib.error
from datetime import datetime, timezone

# Add scripts/ to path so we can import csv_writer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from csv_writer import SchemaEnforcedWriter
from validate_finds_json import validate_file


def now_iso():
    """Canonical UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _archive_file(path):
    """Move a processed file to deprecated/ in its parent directory."""
    parent = os.path.dirname(path)
    dep_dir = os.path.join(parent, "deprecated")
    os.makedirs(dep_dir, exist_ok=True)
    dest = os.path.join(dep_dir, os.path.basename(path))
    try:
        os.rename(path, dest)
    except OSError:
        try:
            import shutil
            shutil.move(path, dest)
        except (OSError, PermissionError):
            pass


# Internal fields — strip before CSV write
INTERNAL_FIELDS = {"agent_values", "enumeration_inventory_size"}

# Metadata fields that Crossref can backfill
_METADATA_FIELDS = {"paper_authors", "paper_title", "paper_year",
                     "first_author", "paper_journal"}

_CROSSREF_CACHE = {}  # doi → metadata dict (per-run cache)


def _crossref_lookup(doi):
    """Fetch metadata for a single DOI from Crossref. Returns dict or None."""
    if doi in _CROSSREF_CACHE:
        return _CROSSREF_CACHE[doi]

    url = f"https://api.crossref.org/works/{urllib.request.quote(doi, safe='')}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "TraitTrawler/4.4 (mailto:coleoguy@gmail.com)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("message", {})
        authors_raw = msg.get("author", [])
        authors = []
        first = ""
        for a in authors_raw:
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                authors.append(name)
                if not first:
                    first = a.get("family", name)

        title_list = msg.get("title", [])
        title = title_list[0] if title_list else ""

        year = None
        for date_field in ("published-print", "published-online",
                           "issued", "created"):
            parts = (msg.get(date_field, {}).get("date-parts") or [[]])[0]
            if parts and parts[0]:
                year = parts[0]
                break

        journal_list = msg.get("container-title", [])
        journal = journal_list[0] if journal_list else ""

        result = {
            "paper_authors": "; ".join(authors) if authors else "",
            "first_author": first,
            "paper_title": title,
            "paper_year": year,
            "paper_journal": journal,
        }
        _CROSSREF_CACHE[doi] = result
        return result
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError, KeyError):
        _CROSSREF_CACHE[doi] = None
        return None


def backfill_metadata(records):
    """Backfill missing paper metadata from Crossref for records with DOIs.

    Only queries Crossref for DOIs where at least one metadata field is empty.
    Returns count of records updated.
    """
    updated = 0
    dois_needing_lookup = set()

    for rec in records:
        doi = str(rec.get("doi", "")).strip()
        if not doi:
            continue
        missing = [f for f in _METADATA_FIELDS
                   if not str(rec.get(f, "")).strip()]
        if missing:
            dois_needing_lookup.add(doi)

    if not dois_needing_lookup:
        return 0

    # Batch lookup (one HTTP call per unique DOI)
    lookup = {}
    for doi in dois_needing_lookup:
        result = _crossref_lookup(doi)
        if result:
            lookup[doi] = result

    # Apply to records
    for rec in records:
        doi = str(rec.get("doi", "")).strip()
        if doi not in lookup:
            continue
        meta = lookup[doi]
        filled = False
        for field in _METADATA_FIELDS:
            if not str(rec.get(field, "")).strip() and meta.get(field):
                rec[field] = meta[field]
                filled = True
        if filled:
            updated += 1

    return updated


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


def apply_calibration(record, calibration_model, document_type=None):
    """Apply isotonic calibration to extraction_confidence.

    Checks per-source-type model first (if document_type known),
    falls back to global model.
    """
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

    # Try per-source-type model first
    global_model = calibration_model.get("global_model", {})
    if document_type and document_type != "unknown":
        type_model = (calibration_model.get("per_source_type", {})
                      .get(document_type, {}).get("model"))
        if type_model:
            global_model = type_model
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

    # Collect finds files, oldest first.
    # Glob('*.json') naturally skips the deprecated/ subdirectory.
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
            "metadata_backfilled": 0,
            "errors": [],
        }
        json.dump(summary, sys.stdout, indent=2)
        print()
        return summary

    # Load config
    config = load_config(project_root)
    do_taxonomy = config.get("taxonomy_resolution", True)

    # Load pipeline state for reproducibility metadata
    ps_path = os.path.join(project_root, "state", "pipeline_state.json")
    ps_data = {}
    if os.path.exists(ps_path):
        try:
            with open(ps_path, "r", encoding="utf-8") as f:
                ps_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

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

    # Snapshot results.csv before writing (rolling window of 3)
    results_csv = os.path.join(project_root, "results.csv")
    if os.path.exists(results_csv) and os.path.getsize(results_csv) > 0:
        snap_dir = os.path.join(project_root, "state", "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        snap_path = os.path.join(snap_dir, f"results_prewrite_{ts}.csv")
        try:
            import shutil
            shutil.copy2(results_csv, snap_path)
            # Keep only last 3 pre-write snapshots
            prewrite_snaps = sorted(glob.glob(
                os.path.join(snap_dir, "results_prewrite_*.csv")))
            for old in prewrite_snaps[:-3]:
                os.remove(old)
        except OSError:
            pass

    # Initialize the schema-enforced writer
    writer = SchemaEnforcedWriter(project_root)

    total_written = 0
    total_rejected = 0
    total_flagged = 0
    total_duplicate = 0
    total_taxonomy = 0
    total_backfilled = 0
    errors = []
    files_processed = 0

    for fpath in files:
        fname = os.path.basename(fpath)

        # Step 1: Validate structure
        config_path = os.path.join(project_root, "collector_config.yaml")
        ok, validation_errors = validate_file(fpath, config_path=config_path)
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
            # Valid file but no records — archive
            files_processed += 1
            _archive_file(fpath)
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

        # Step 4: Confidence calibration (source-type-aware)
        doc_type = data.get("document_type", "unknown")
        if calibration_model:
            for rec in records:
                apply_calibration(rec, calibration_model,
                                  document_type=doc_type)

        # Step 5: Strip internal fields
        for rec in records:
            for field in INTERNAL_FIELDS:
                rec.pop(field, None)

        # Step 6: Add session metadata + reproducibility fields
        processed_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for rec in records:
            if session_id:
                rec["session_id"] = session_id
            rec["processed_date"] = processed_date
            # Reproducibility metadata from pipeline_state.json
            if ps_data:
                rec.setdefault("skill_version", ps_data.get(
                    "skill_version", ""))
                rec.setdefault("guide_md_hash", ps_data.get(
                    "guide_md_hash", ""))
            # Document-level metadata from finds JSON
            rec.setdefault("document_type", doc_type)
            rec.setdefault("extraction_model", data.get(
                "extraction_model", ""))
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
            # pdf_path backfill is handled by scrub.py; just warn if still empty
            if not rec.get("pdf_path"):
                print(f"WARNING: Record for '{rec.get('species', '?')}' in "
                      f"{fname} has no pdf_path — provenance broken",
                      file=sys.stderr)

        # Step 6b: Backfill missing metadata from Crossref
        backfilled = backfill_metadata(records)
        total_backfilled += backfilled

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

        # Step 8: Archive on success
        files_processed += 1
        _archive_file(fpath)

    # Write summary
    summary = {
        "files_processed": files_processed,
        "records_written": total_written,
        "records_rejected": total_rejected,
        "records_flagged": total_flagged,
        "records_duplicate": total_duplicate,
        "taxonomy_resolved": total_taxonomy,
        "metadata_backfilled": total_backfilled,
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

    # v5: Run inline QC after writing (auto-fix, audit queue, human queue)
    if total_written > 0:
        inline_qc_script = os.path.join(project_root, "scripts",
                                         "inline_qc.py")
        if os.path.exists(inline_qc_script):
            try:
                subprocess.run(
                    [sys.executable, inline_qc_script,
                     "--project-root", project_root,
                     "--session-id", session_id or ""],
                    timeout=120, capture_output=True, text=True,
                )
            except (subprocess.TimeoutExpired, OSError) as e:
                print(f"WARNING: inline_qc.py failed: {e}",
                      file=sys.stderr)

        # v5: Auto-calibration trigger (every 20 records)
        cal_meta_path = os.path.join(project_root, "state",
                                      "calibration_meta.json")
        try:
            if os.path.exists(cal_meta_path):
                with open(cal_meta_path, "r") as f:
                    cal_meta = json.load(f)
            else:
                cal_meta = {"records_since_last": 0}
            cal_meta["records_since_last"] = (
                cal_meta.get("records_since_last", 0) + total_written)
            if cal_meta["records_since_last"] >= 20:
                cal_script = os.path.join(project_root, "scripts",
                                           "calibration.py")
                if os.path.exists(cal_script):
                    subprocess.run(
                        [sys.executable, cal_script,
                         "--project-root", project_root],
                        timeout=60, capture_output=True, text=True,
                    )
                    cal_meta["records_since_last"] = 0
                    cal_meta["last_calibration"] = now_iso()
            with open(cal_meta_path, "w") as f:
                json.dump(cal_meta, f, indent=2)
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: calibration trigger failed: {e}",
                  file=sys.stderr)

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
