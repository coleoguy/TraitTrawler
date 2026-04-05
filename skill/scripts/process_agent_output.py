#!/usr/bin/env python3
"""
Process agent output folders and update state files.

The Manager calls these functions instead of reading agent output files
into its context window. Each function reads the transient files, updates
state, and deletes the processed files.

Usage from Manager (via python3 one-liners):
    python3 scripts/process_agent_output.py --action search_results
    python3 scripts/process_agent_output.py --action fetch_failures
    python3 scripts/process_agent_output.py --action extractor_results
    python3 scripts/process_agent_output.py --action writer_results
"""

import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from state_utils import (
    add_to_queue,
    update_processed,
    log_event,
    safe_read_json,
    safe_write_json,
    append_jsonl,
    FileLock,
)


def _archive_file(path):
    """Move a processed file to a deprecated/ subfolder in its parent dir.

    The glob('*.json') pattern naturally skips subdirectories, so archived
    files won't be re-processed. This works even in sandboxed filesystems
    where os.remove() is blocked, because rename is a directory-entry
    operation, not a file deletion.
    """
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
            pass  # Last resort: file stays but won't match glob if
                  # we add tracker fallback later


def _handle_corrupt_file(f, error, project_root):
    """Log corrupt file to run_log.jsonl and move to state/corrupt/."""
    print(f"WARNING: corrupt file {f}: {error}", file=sys.stderr)
    corrupt_dir = os.path.join(project_root, "state", "corrupt")
    os.makedirs(corrupt_dir, exist_ok=True)
    log_path = os.path.join(project_root, "state", "run_log.jsonl")
    append_jsonl(log_path, {
        "event": "corrupt_file",
        "file": os.path.basename(f),
        "folder": os.path.basename(os.path.dirname(f)),
        "error": str(error),
    })
    try:
        dest = os.path.join(corrupt_dir, os.path.basename(f))
        os.rename(f, dest)
    except OSError:
        pass


def process_search_results(project_root):
    """Read search_results/*.json, update queue + search_log + processed, delete files."""
    folder = os.path.join(project_root, "search_results")
    state_dir = os.path.join(project_root, "state")
    files = sorted(glob.glob(os.path.join(folder, "*.json")))
    if not files:
        print(json.dumps({"files": 0, "new_to_queue": 0, "rejected": 0}))
        return

    total_new = 0
    total_rejected = 0
    queries_processed = []
    source_counts = {"pubmed": 0, "openalex": 0, "biorxiv": 0, "medrxiv": 0, "crossref": 0}

    # Read search_log for update
    search_log_path = os.path.join(state_dir, "search_log.json")
    search_log = safe_read_json(search_log_path, default={})

    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            _handle_corrupt_file(f, e, project_root)
            continue

        query = data.get("query", os.path.basename(f))

        # Add papers to queue
        papers = data.get("papers", [])
        if papers:
            added = add_to_queue(state_dir, papers)
            total_new += added

        # Mark rejected papers
        for r in data.get("rejected", []):
            doi = r.get("doi")
            if doi:
                update_processed(state_dir, doi, {
                    "outcome": "triage_rejected",
                    "triage": "unlikely",
                    "reason": r.get("reason", ""),
                    "source_query": query,
                })
                total_rejected += 1

        # Update search_log
        log_entry = {"query": query, "date": data.get("date", "")}
        for key in ["pubmed_results", "openalex_results", "biorxiv_results",
                     "crossref_results", "new_to_queue", "duplicates_skipped"]:
            log_entry[key] = data.get(key, 0)
        search_log[query] = log_entry
        queries_processed.append(query)

        # Accumulate source counts
        for src in source_counts:
            source_counts[src] += data.get(f"{src}_results", 0)

        # Delete processed file
        _archive_file(f)

    # Write search_log
    safe_write_json(search_log_path, search_log)

    # Update source_stats
    stats_path = os.path.join(state_dir, "source_stats.json")
    stats = safe_read_json(stats_path, default={})
    search_sources = stats.get("search_sources", {})
    for src, count in source_counts.items():
        if src not in search_sources:
            search_sources[src] = {"total_found": 0}
        search_sources[src]["total_found"] += count
    stats["search_sources"] = search_sources
    safe_write_json(stats_path, stats)

    # Compute source diversity for validation
    sources_hit = sum(1 for s, c in source_counts.items() if c > 0)

    result = {
        "files": len(files),
        "queries": queries_processed,
        "new_to_queue": total_new,
        "rejected": total_rejected,
        "source_counts": source_counts,
        "sources_hit": sources_hit,
        "validation": {
            "multi_source": sources_hit >= 2,
            "has_papers": total_new > 0,
        }
    }
    print(json.dumps(result))


def process_fetch_failures(project_root):
    """Read fetch_failures/*.json, move to lead_files/, update processed.json.

    Follows the file-based queue pattern: each lead is an individual JSON file
    dropped in lead_files/. The consolidate_leads action merges them into
    leads.csv at session end or on demand. This eliminates concurrent CSV
    write issues.
    """
    folder = os.path.join(project_root, "fetch_failures")
    lead_dir = os.path.join(project_root, "lead_files")
    state_dir = os.path.join(project_root, "state")
    os.makedirs(lead_dir, exist_ok=True)

    files = sorted(glob.glob(os.path.join(folder, "*.json")))
    if not files:
        print(json.dumps({"files": 0, "leads_added": 0, "browser_missing": 0}))
        return

    leads_added = 0
    browser_missing = 0
    source_attempts = {}

    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            _handle_corrupt_file(f, e, project_root)
            continue

        doi = data.get("doi", "")
        sources_tried = data.get("sources_tried", [])

        # Check browser was attempted
        if "browser" not in sources_tried:
            browser_missing += 1

        # Track source attempts for stats
        for src in sources_tried:
            if src not in source_attempts:
                source_attempts[src] = {"attempts": 0, "successes": 0}
            source_attempts[src]["attempts"] += 1

        # Move to lead_files/ (atomic rename)
        dest = os.path.join(lead_dir, os.path.basename(f))
        try:
            os.replace(f, dest)
        except OSError:
            try:
                import shutil
                shutil.copy2(f, dest)
            except (OSError, PermissionError):
                pass
            _archive_file(f)
        leads_added += 1

        # Mark in processed.json
        if doi:
            update_processed(state_dir, doi, {
                "outcome": "lead_needs_fulltext",
                "reason": data.get("reason", "unknown"),
                "sources_tried": sources_tried,
                "source_query": data.get("source_query", ""),
            })


    # Update fetch source stats
    stats_path = os.path.join(state_dir, "source_stats.json")
    stats = safe_read_json(stats_path, default={})
    fetch_sources = stats.get("fetch_sources", {})
    for src, counts in source_attempts.items():
        if src not in fetch_sources:
            fetch_sources[src] = {"attempts": 0, "successes": 0}
        fetch_sources[src]["attempts"] += counts["attempts"]
    stats["fetch_sources"] = fetch_sources
    safe_write_json(stats_path, stats)

    result = {
        "files": len(files),
        "leads_added": leads_added,
        "browser_missing": browser_missing,
        "source_attempts": source_attempts,
        "validation": {
            "browser_used": browser_missing == 0,
        }
    }
    print(json.dumps(result))


def consolidate_leads(project_root):
    """Read lead_files/*.json and append to leads.csv, then delete files.

    Called at session end or on demand. Single-threaded — no concurrency
    concern because this is never called during the hot pipeline path.
    """
    lead_dir = os.path.join(project_root, "lead_files")
    leads_path = os.path.join(project_root, "leads.csv")
    files = sorted(glob.glob(os.path.join(lead_dir, "*.json")))
    if not files:
        print(json.dumps({"files": 0, "leads_written": 0}))
        return

    header = ["doi", "paper_title", "first_author", "paper_year",
              "paper_journal", "reason", "sources_tried", "date_added", "status"]

    file_exists = os.path.exists(leads_path) and os.path.getsize(leads_path) > 0
    leads_written = 0

    with open(leads_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        if not file_exists:
            writer.writeheader()

        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as jfh:
                    data = json.load(jfh)
            except (json.JSONDecodeError, OSError) as e:
                _handle_corrupt_file(f, e, project_root)
                continue

            authors = data.get("authors", "")
            first_author = (authors.split(",")[0].split(";")[0].strip()
                            if authors else "")
            writer.writerow({
                "doi": data.get("doi", ""),
                "paper_title": data.get("title", ""),
                "first_author": first_author,
                "paper_year": data.get("year", ""),
                "paper_journal": data.get("journal", ""),
                "reason": data.get("reason", "unknown"),
                "sources_tried": ",".join(data.get("sources_tried", [])),
                "date_added": data.get("date", ""),
                "status": "pending",
            })
            leads_written += 1
            _archive_file(f)

    result = {
        "files": len(files),
        "leads_written": leads_written,
    }
    print(json.dumps(result))


def process_fetch_successes(project_root):
    """Count new handoff files and update source_stats for successful fetches.

    Unlike failures, successful fetches leave handoff files in
    ready_for_extraction/ which persist until the Dealer picks them up.
    This function updates source_stats.json with success counts.
    """
    folder = os.path.join(project_root, "ready_for_extraction")
    state_dir = os.path.join(project_root, "state")
    files = sorted(glob.glob(os.path.join(folder, "*.json")))

    source_successes = {}
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            _handle_corrupt_file(f, e, project_root)
            continue
        src = data.get("pdf_source", "unknown")
        if src not in source_successes:
            source_successes[src] = 0
        source_successes[src] += 1

    # Update source_stats.json with successful fetch counts
    if source_successes:
        stats_path = os.path.join(state_dir, "source_stats.json")
        stats = safe_read_json(stats_path, default={})
        fetch_sources = stats.get("fetch_sources", {})
        for src, count in source_successes.items():
            if src not in fetch_sources:
                fetch_sources[src] = {"attempts": 0, "successes": 0}
            fetch_sources[src]["successes"] += count
            # Also count as attempts (successes are a subset of attempts)
            fetch_sources[src]["attempts"] += count
        stats["fetch_sources"] = fetch_sources
        safe_write_json(stats_path, stats)

    # Calculate fetch yield (needs failure count from lead_files/)
    lead_dir = os.path.join(project_root, "lead_files")
    recent_leads = len(glob.glob(os.path.join(lead_dir, "*.json")))
    total_fetch = len(files) + recent_leads
    yield_pct = round(len(files) / total_fetch * 100, 1) if total_fetch > 0 else 0

    result = {
        "handoffs_ready": len(files),
        "source_successes": source_successes,
        "validation": {
            "yield_pct": yield_pct,
            "low_yield": yield_pct < 20 and total_fetch >= 3,
        },
    }
    print(json.dumps(result))


def process_extractor_results(project_root):
    """Process Extractor returns: finds/ records and extractor_results/ no-data reports."""
    state_dir = os.path.join(project_root, "state")

    # Part 1: Process finds/ (extracted records)
    # NOTE: finds/ files are NOT archived here — they persist for verify_and_write.
    finds_folder = os.path.join(project_root, "finds")
    finds_files = sorted(glob.glob(os.path.join(finds_folder, "*.json")))

    total_records = 0
    papers = []
    normalized_count = 0

    for f in finds_files:
        if _normalize_finds_file(f):
            normalized_count += 1
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            _handle_corrupt_file(f, e, project_root)
            continue

        doi = data.get("doi", "")
        records = data.get("records", [])
        n = len(records) if isinstance(records, list) else 0
        total_records += n
        papers.append({"doi": doi, "records": n, "file": os.path.basename(f)})

        key = doi
        if not key:
            title = (data.get("title", "") or "").strip()
            if title:
                key = f"title:{title[:120]}"
        if key:
            update_processed(state_dir, key, {
                "outcome": "extracted",
                "records": n,
                "source_query": data.get("source_query", ""),
            })

    # Part 2: Process extractor_results/ (no-data and error reports)
    results_folder = os.path.join(project_root, "extractor_results")
    nodata_files = sorted(glob.glob(os.path.join(results_folder, "*.json")))

    no_data = 0
    failed = 0

    for f in nodata_files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            _handle_corrupt_file(f, e, project_root)
            continue

        doi = data.get("doi", "")
        outcome = data.get("outcome", "unknown")
        if outcome == "no_data":
            no_data += 1
        else:
            failed += 1

        if doi:
            update_processed(state_dir, doi, {
                "outcome": outcome,
                "reason": data.get("reason", ""),
                "source_query": data.get("source_query", ""),
            })
        _archive_file(f)

    # Combined result
    total_files = len(finds_files) + len(nodata_files)
    result = {
        "finds_files": len(finds_files),
        "nodata_files": len(nodata_files),
        "total_records": total_records,
        "no_data": no_data,
        "normalized": normalized_count,
        "papers": papers,
        "validation": {
            "produced_output": len(finds_files) > 0 or len(nodata_files) > 0,
            "all_failed": failed == total_files and total_files > 0,
            "has_records": total_records > 0,
            "empty_papers": [p["doi"] for p in papers if p["records"] == 0],
        },
    }
    print(json.dumps(result))


def _normalize_finds_file(fpath):
    """Auto-fix common agent output format issues in a finds JSON file.

    Fixes applied in-place:
    - paper_authors: list → semicolon-separated string
    - extraction_confidence: word ("high"/"medium"/"low") → float
    - extraction_timestamp: add if missing
    - records: unwrap if wrapped in extra nesting
    - source_page: ensure string type

    Returns True if the file was modified, False if no changes needed.
    """
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    if not isinstance(data, dict):
        return False

    modified = False

    # Fix missing extraction_timestamp
    if "extraction_timestamp" not in data:
        from datetime import datetime, timezone
        data["extraction_timestamp"] = datetime.now(
            timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        modified = True

    # Fix records that are a dict instead of a list
    records = data.get("records")
    if isinstance(records, dict):
        # Agent wrote {species: {...}} instead of [{species: ...}]
        data["records"] = [records]
        records = data["records"]
        modified = True

    if not isinstance(records, list):
        return modified

    conf_word_map = {"high": 0.85, "medium": 0.65, "low": 0.4}

    for rec in records:
        if not isinstance(rec, dict):
            continue

        # Fix paper_authors: list → string
        pa = rec.get("paper_authors")
        if isinstance(pa, list):
            rec["paper_authors"] = "; ".join(str(a) for a in pa)
            modified = True

        # Fix extraction_confidence: word → float
        ec = rec.get("extraction_confidence")
        if isinstance(ec, str) and ec.strip().lower() in conf_word_map:
            rec["extraction_confidence"] = conf_word_map[ec.strip().lower()]
            modified = True

        # Fix source_page: int → string
        sp = rec.get("source_page")
        if isinstance(sp, int):
            rec["source_page"] = str(sp)
            modified = True

    if modified:
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            return False

    return modified


def process_finds(project_root):
    """Alias for process_extractor_results (backward compatibility)."""
    process_extractor_results(project_root)


def process_writer_results(project_root):
    """Read writer_results/*.json, print summary, delete files."""
    folder = os.path.join(project_root, "writer_results")
    files = sorted(glob.glob(os.path.join(folder, "*.json")))
    if not files:
        print(json.dumps({"files": 0}))
        return

    total_written = 0
    total_rejected = 0
    total_flagged = 0
    total_duplicate = 0
    errors = []

    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            _handle_corrupt_file(f, e, project_root)
            continue

        total_written += data.get("records_written", 0)
        total_rejected += data.get("records_rejected", 0)
        total_flagged += data.get("records_flagged", 0)
        total_duplicate += data.get("records_duplicate", 0)
        errors.extend(data.get("errors", []))

        _archive_file(f)

    result = {
        "files": len(files),
        "records_written": total_written,
        "records_rejected": total_rejected,
        "records_flagged": total_flagged,
        "records_duplicate": total_duplicate,
        "errors": errors,
        "validation": {
            "has_writes": total_written > 0,
            "has_errors": len(errors) > 0,
            "high_reject_rate": (total_rejected > total_written
                                 and total_written + total_rejected > 0),
        },
    }
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(
        description="Process TraitTrawler agent output folders"
    )
    parser.add_argument("--action", required=True,
                        choices=["search_results", "fetch_failures",
                                 "fetch_successes", "extractor_results",
                                 "finds", "writer_results",
                                 "consolidate_leads", "all"],
                        help="Which agent output to process")
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    args = parser.parse_args()

    if args.action == "all":
        for action in ["search_results", "fetch_failures", "fetch_successes",
                        "extractor_results", "finds", "writer_results"]:
            print(f"--- {action} ---")
            globals()[f"process_{action}"](args.project_root)
    else:
        fn = globals()[f"process_{args.action}"]
        fn(args.project_root)


if __name__ == "__main__":
    main()
