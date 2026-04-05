#!/usr/bin/env python3
"""
Bootstrap v5 learning state from an existing results.csv + state/ directory.

Derives calibration seeds, coverage baselines, processed.json sync,
guide.md scaffold, extraction examples, triage intelligence, search log,
ILL list, and pipeline state for TraitTrawler v5 upgrades.

Usage:
    # Auto mode (called by session_manager.py start):
    python3 scripts/bootstrap.py --project-root . --auto

    # Manual mode:
    python3 scripts/bootstrap.py --project-root . --results results.csv --pdfs pdfs/
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from state_utils import safe_read_json, safe_write_json, append_jsonl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso():
    """Return current UTC timestamp in canonical ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_results_csv(csv_path):
    """Read results.csv into a list of dicts. Returns [] if missing."""
    if not os.path.exists(csv_path):
        return []
    rows = []
    with open(csv_path, "r", newline="", encoding="utf-8",
              errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def run_script(project_root, script_name, extra_args=None):
    """Run a sibling script via subprocess. Returns (success, stdout, stderr)."""
    script_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), script_name
    )
    if not os.path.exists(script_path):
        return False, "", f"Script not found: {script_path}"
    cmd = [sys.executable, script_path, "--project-root", project_root]
    if extra_args:
        cmd.extend(extra_args)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        return proc.returncode == 0, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout running {script_name}"
    except Exception as e:
        return False, "", str(e)


# ---------------------------------------------------------------------------
# Step 1: Calibration seed
# ---------------------------------------------------------------------------

def step_calibration_seed(project_root, rows, errors):
    """Seed calibration_data.jsonl from results.csv, then fit model."""
    cal_path = os.path.join(project_root, "state", "calibration_data.jsonl")
    n_records = len(rows)

    # Skip if already bootstrapped (more entries than results rows)
    if os.path.exists(cal_path):
        line_count = 0
        with open(cal_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    line_count += 1
        if line_count >= n_records:
            return line_count

    # Write calibration observations from results.csv
    os.makedirs(os.path.dirname(cal_path), exist_ok=True)
    written = 0
    with open(cal_path, "a", encoding="utf-8") as f:
        for row in rows:
            conf = row.get("extraction_confidence", "")
            try:
                raw_conf = float(conf) if conf else 0.7
            except (ValueError, TypeError):
                raw_conf = 0.7
            entry = {
                "predicted_confidence": raw_conf,
                "correct": True,
                "source": "bootstrap",
                "field": "all",
                "timestamp": now_iso(),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1

    # Fit the calibration model via subprocess
    ok, stdout, stderr = run_script(project_root, "calibration.py")
    if not ok:
        errors.append(f"calibration.py failed: {stderr[:200]}")

    return written


# ---------------------------------------------------------------------------
# Step 2: Coverage baseline
# ---------------------------------------------------------------------------

def step_coverage_baseline(project_root, errors):
    """Run coverage_tracker.py to compute Chao1 and completeness."""
    ok, stdout, stderr = run_script(project_root, "coverage_tracker.py")
    if not ok:
        errors.append(f"coverage_tracker.py failed: {stderr[:200]}")
        return {}

    coverage_path = os.path.join(
        project_root, "state", "coverage_tracker.json"
    )
    if os.path.exists(coverage_path):
        return safe_read_json(coverage_path, default={})
    return {}


# ---------------------------------------------------------------------------
# Step 3: Processed.json sync
# ---------------------------------------------------------------------------

def step_sync_processed(project_root, rows, errors):
    """Backfill processed.json with DOIs and titles from results.csv."""
    proc_path = os.path.join(project_root, "state", "processed.json")
    proc = safe_read_json(proc_path, default={})
    now = now_iso()

    # Count records per DOI for enrichment
    doi_counts = Counter()
    for row in rows:
        doi = (row.get("doi") or "").strip()
        if doi:
            doi_counts[doi] += 1

    added = 0
    for row in rows:
        doi = (row.get("doi") or "").strip()
        title = (row.get("paper_title") or "").strip()

        if doi and doi not in proc:
            proc[doi] = {
                "outcome": "imported",
                "records": doi_counts.get(doi, 1),
                "date": now,
                "source": "bootstrap",
            }
            added += 1

        # Title-based key for papers without DOIs
        if not doi and title:
            title_key = f"title:{title[:120]}"
            if title_key not in proc:
                proc[title_key] = {
                    "outcome": "imported",
                    "records": 1,
                    "date": now,
                    "source": "bootstrap",
                }
                added += 1

    if added:
        safe_write_json(proc_path, proc)

    return len(proc)


# ---------------------------------------------------------------------------
# Step 4: Guide.md scaffold
# ---------------------------------------------------------------------------

def step_scaffold_guide(project_root, rows, errors):
    """Generate a scaffold guide.md from patterns in results.csv."""
    guide_path = os.path.join(project_root, "guide.md")
    if os.path.exists(guide_path):
        return False  # already exists

    if not rows:
        return False

    # Collect unique values
    families = set()
    genera = set()
    systems = set()
    journals = Counter()
    authors = Counter()
    numeric_ranges = defaultdict(lambda: {"min": float("inf"),
                                          "max": float("-inf")})

    # Detect numeric-looking fields
    skip_fields = {"doi", "species", "paper_title", "paper_authors",
                   "first_author", "paper_journal", "paper_year",
                   "source_page", "source_context", "extraction_confidence",
                   "pdf_path", "pdf_source", "family", "genus",
                   "sex_chromosome_system", "source_query"}

    for row in rows:
        fam = (row.get("family") or "").strip()
        if fam:
            families.add(fam)

        gen = (row.get("genus") or "").strip()
        if gen:
            genera.add(gen)

        sys_val = (row.get("sex_chromosome_system") or "").strip()
        if sys_val:
            systems.add(sys_val)

        journal = (row.get("paper_journal") or "").strip()
        if journal:
            journals[journal] += 1

        author = (row.get("first_author") or "").strip()
        if author:
            authors[author] += 1

        # Detect numeric trait fields
        for key, val in row.items():
            if key in skip_fields or not val:
                continue
            val = val.strip()
            try:
                num = float(val)
                if numeric_ranges[key]["min"] > num:
                    numeric_ranges[key]["min"] = num
                if numeric_ranges[key]["max"] < num:
                    numeric_ranges[key]["max"] = num
            except (ValueError, TypeError):
                pass

    # Build guide
    lines = ["# Extraction Guide\n"]
    lines.append("*Auto-generated scaffold from bootstrap. "
                 "Edit to refine extraction rules.*\n")

    # Taxonomy
    lines.append("## Taxonomy\n")
    if families:
        sorted_fam = sorted(families)
        lines.append(f"**Families** ({len(sorted_fam)}): "
                     + ", ".join(sorted_fam[:30]))
        if len(sorted_fam) > 30:
            lines.append(f" ... and {len(sorted_fam) - 30} more")
        lines.append("\n")
    if genera:
        sorted_gen = sorted(genera)
        lines.append(f"**Genera** ({len(sorted_gen)}): "
                     + ", ".join(sorted_gen[:30]))
        if len(sorted_gen) > 30:
            lines.append(f" ... and {len(sorted_gen) - 30} more")
        lines.append("\n")

    # Notation
    if systems:
        lines.append("## Notation Variants\n")
        lines.append(", ".join(sorted(systems)))
        lines.append("\n")

    # Value ranges
    if numeric_ranges:
        lines.append("## Value Ranges\n")
        lines.append("| Field | Min | Max |")
        lines.append("|-------|-----|-----|")
        for field in sorted(numeric_ranges.keys()):
            r = numeric_ranges[field]
            if r["min"] != float("inf"):
                lines.append(f"| {field} | {r['min']} | {r['max']} |")
        lines.append("")

    # Journals
    if journals:
        lines.append("## Top Journals\n")
        for journal, count in journals.most_common(10):
            lines.append(f"- {journal} ({count} records)")
        lines.append("")

    # Authors
    if authors:
        lines.append("## Top Authors\n")
        for author, count in authors.most_common(10):
            lines.append(f"- {author} ({count} records)")
        lines.append("")

    with open(guide_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return True


# ---------------------------------------------------------------------------
# Step 5: Extraction examples
# ---------------------------------------------------------------------------

def step_extraction_examples(project_root, rows, errors):
    """Write top-5 high-confidence records as extraction examples."""
    examples_path = os.path.join(project_root, "extraction_examples.md")
    if os.path.exists(examples_path):
        return 0

    if not rows:
        return 0

    # Sort by extraction_confidence descending
    def conf_key(row):
        try:
            return float(row.get("extraction_confidence") or 0)
        except (ValueError, TypeError):
            return 0

    sorted_rows = sorted(rows, key=conf_key, reverse=True)
    top = sorted_rows[:5]

    # Identify trait fields (not metadata)
    meta_fields = {"doi", "paper_title", "paper_authors", "first_author",
                   "paper_journal", "paper_year", "source_page",
                   "source_context", "extraction_confidence", "pdf_path",
                   "pdf_source", "source_query"}

    trait_fields = []
    if top:
        trait_fields = [k for k in top[0].keys() if k not in meta_fields]

    lines = ["# Extraction Examples\n"]
    lines.append("*Top 5 highest-confidence extractions from bootstrap.*\n")

    # Header
    header_cols = ["species"] + trait_fields[:6] + ["doi", "source_page"]
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

    for row in top:
        vals = []
        for col in header_cols:
            v = (row.get(col) or "").strip()
            # Truncate long values for table readability
            if len(v) > 40:
                v = v[:37] + "..."
            vals.append(v)
        lines.append("| " + " | ".join(vals) + " |")

    lines.append("")

    # Source context snippets
    lines.append("## Source Context Snippets\n")
    for i, row in enumerate(top, 1):
        sp = (row.get("species") or "unknown").strip()
        ctx = (row.get("source_context") or "").strip()
        if ctx:
            # Truncate to first 200 chars
            if len(ctx) > 200:
                ctx = ctx[:197] + "..."
            lines.append(f"**{i}. {sp}**: {ctx}\n")

    with open(examples_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return len(top)


# ---------------------------------------------------------------------------
# Step 6: Triage intelligence
# ---------------------------------------------------------------------------

def step_triage_intelligence(project_root, rows, errors):
    """Compute journal yield statistics for triage."""
    triage_path = os.path.join(project_root, "state", "triage_stats.json")

    # Group records by journal
    journal_papers = defaultdict(set)   # journal -> set of DOIs
    journal_records = defaultdict(int)   # journal -> record count

    for row in rows:
        journal = (row.get("paper_journal") or "").strip()
        doi = (row.get("doi") or "").strip()
        if journal:
            if doi:
                journal_papers[journal].add(doi)
            journal_records[journal] += 1

    journals = {}
    for journal in journal_records:
        n_papers = len(journal_papers[journal]) or 1
        n_records = journal_records[journal]
        journals[journal] = {
            "papers": n_papers,
            "records": n_records,
            "yield": round(n_records / n_papers, 2),
        }

    # Query stats (if source_query field exists)
    query_stats = {}
    for row in rows:
        sq = (row.get("source_query") or "").strip()
        if sq:
            if sq not in query_stats:
                query_stats[sq] = {"records": 0, "dois": set()}
            query_stats[sq]["records"] += 1
            doi = (row.get("doi") or "").strip()
            if doi:
                query_stats[sq]["dois"].add(doi)

    # Convert sets to counts for JSON serialization
    query_out = {}
    for sq, info in query_stats.items():
        query_out[sq] = {
            "records": info["records"],
            "papers": len(info["dois"]),
        }

    triage = {
        "journals": journals,
        "queries": query_out,
        "updated_at": now_iso(),
    }
    safe_write_json(triage_path, triage)

    # Count high-yield journals (yield >= 3 records per paper)
    high_yield = sum(1 for j in journals.values() if j["yield"] >= 3)
    return {"high_yield_journals": high_yield}


# ---------------------------------------------------------------------------
# Step 7: Search log seed
# ---------------------------------------------------------------------------

def step_search_log_seed(project_root, errors):
    """Ensure search_log.json exists."""
    log_path = os.path.join(project_root, "state", "search_log.json")
    if os.path.exists(log_path):
        return True  # already has query history
    safe_write_json(log_path, {})
    return True


# ---------------------------------------------------------------------------
# Step 8: ILL list seed
# ---------------------------------------------------------------------------

def step_ill_list(project_root, rows, pdfs_dir, errors):
    """Generate ill_list.csv for papers missing PDFs."""
    ill_path = os.path.join(project_root, "ill_list.csv")
    if os.path.exists(ill_path):
        return 0

    if not rows:
        return 0

    # Group by DOI — find papers where pdf_path is empty or file missing
    missing = defaultdict(lambda: {
        "title": "", "authors": "", "year": "",
        "journal": "", "records": 0
    })

    for row in rows:
        doi = (row.get("doi") or "").strip()
        if not doi:
            continue

        pdf_path = (row.get("pdf_path") or "").strip()
        has_pdf = False
        if pdf_path:
            # Check absolute path first, then relative to project
            if os.path.isabs(pdf_path):
                has_pdf = os.path.exists(pdf_path)
            else:
                has_pdf = os.path.exists(
                    os.path.join(project_root, pdf_path)
                )
        # Also check pdfs/ directory
        if not has_pdf and pdfs_dir:
            # Look for any PDF that might correspond to this DOI
            safe_doi = doi.replace("/", "_").replace(":", "_")
            candidate = os.path.join(pdfs_dir, safe_doi + ".pdf")
            if os.path.exists(candidate):
                has_pdf = True

        if not has_pdf:
            entry = missing[doi]
            entry["title"] = (row.get("paper_title") or entry["title"]
                              or "").strip()
            entry["authors"] = (row.get("paper_authors") or entry["authors"]
                                or "").strip()
            entry["year"] = (row.get("paper_year") or entry["year"]
                             or "").strip()
            entry["journal"] = (row.get("paper_journal") or entry["journal"]
                                or "").strip()
            entry["records"] += 1

    if not missing:
        return 0

    # Write CSV sorted by record count (highest priority first)
    sorted_missing = sorted(missing.items(),
                            key=lambda x: x[1]["records"], reverse=True)

    with open(ill_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["doi", "title", "authors", "year", "journal",
                         "reason", "priority", "status"])
        for doi, info in sorted_missing:
            writer.writerow([
                doi,
                info["title"],
                info["authors"],
                info["year"],
                info["journal"],
                "pdf_missing",
                info["records"],
                "pending",
            ])

    return len(sorted_missing)


# ---------------------------------------------------------------------------
# Step 9: Pipeline state
# ---------------------------------------------------------------------------

def step_pipeline_state(project_root, rows, coverage, errors):
    """Create the v5 pipeline state file."""
    ps_path = os.path.join(project_root, "state", "pipeline_state.json")

    pipeline = {
        "session_id": None,
        "session_target": None,
        "papers_processed": 0,
        "records_written": len(rows),
        "searcher_exhausted": False,
        "coverage": {
            "s_obs": coverage.get("s_obs", 0),
            "chao1": coverage.get("chao1", 0),
            "completeness": coverage.get("completeness", 0),
        },
        "audit_queue_depth": 0,
        "human_review_depth": 0,
        "bootstrapped_at": now_iso(),
        "bootstrapped_from": "v4",
    }
    safe_write_json(ps_path, pipeline)
    return pipeline


# ---------------------------------------------------------------------------
# Auto-detection check
# ---------------------------------------------------------------------------

def already_bootstrapped(project_root):
    """Check if bootstrap has already been run."""
    ps_path = os.path.join(project_root, "state", "pipeline_state.json")
    if not os.path.exists(ps_path):
        return False
    data = safe_read_json(ps_path, default={})
    return bool(data.get("bootstrapped_at"))


# ---------------------------------------------------------------------------
# Main bootstrap orchestrator
# ---------------------------------------------------------------------------

def bootstrap(project_root, results_path=None, pdfs_dir=None, auto=False):
    """Run all bootstrap steps. Returns JSON-serializable result dict."""
    # Auto-detection: skip if already bootstrapped
    if auto and already_bootstrapped(project_root):
        return {
            "bootstrapped": False,
            "reason": "already bootstrapped",
        }

    # Resolve paths
    if results_path is None:
        results_path = os.path.join(project_root, "results.csv")
    elif not os.path.isabs(results_path):
        results_path = os.path.join(project_root, results_path)

    if pdfs_dir is None:
        # Try common PDF directory names
        for candidate in ["pdfs", "source", "pdf"]:
            p = os.path.join(project_root, candidate)
            if os.path.isdir(p):
                pdfs_dir = p
                break
    elif not os.path.isabs(pdfs_dir):
        pdfs_dir = os.path.join(project_root, pdfs_dir)

    # Ensure state directory exists
    os.makedirs(os.path.join(project_root, "state"), exist_ok=True)

    # Read results.csv once — all steps share this data
    rows = read_results_csv(results_path)
    errors = []

    result = {
        "bootstrapped": True,
        "processed_papers": 0,
        "calibration_records": 0,
        "coverage": {},
        "taxonomy_cached": 0,
        "guide_scaffolded": False,
        "examples_generated": 0,
        "triage_stats": {},
        "search_log_imported": False,
        "ill_list_generated": 0,
        "errors": errors,
    }

    if not rows:
        errors.append(f"No records found in {results_path}")
        # Still continue with steps that don't need rows

    # -- Step 1: Calibration seed --
    try:
        cal_count = step_calibration_seed(project_root, rows, errors)
        result["calibration_records"] = cal_count
    except Exception as e:
        errors.append(f"Step 1 (calibration seed): {e}")

    # -- Step 2: Coverage baseline --
    coverage = {}
    try:
        coverage = step_coverage_baseline(project_root, errors)
        result["coverage"] = {
            "s_obs": coverage.get("s_obs", 0),
            "chao1": coverage.get("chao1", 0),
            "completeness": coverage.get("completeness", 0),
        }
    except Exception as e:
        errors.append(f"Step 2 (coverage baseline): {e}")

    # -- Step 3: Processed.json sync --
    try:
        proc_total = step_sync_processed(project_root, rows, errors)
        result["processed_papers"] = proc_total
    except Exception as e:
        errors.append(f"Step 3 (processed.json sync): {e}")

    # -- Step 4: Guide.md scaffold --
    try:
        scaffolded = step_scaffold_guide(project_root, rows, errors)
        result["guide_scaffolded"] = scaffolded
    except Exception as e:
        errors.append(f"Step 4 (guide.md scaffold): {e}")

    # -- Step 5: Extraction examples --
    try:
        n_examples = step_extraction_examples(project_root, rows, errors)
        result["examples_generated"] = n_examples
    except Exception as e:
        errors.append(f"Step 5 (extraction examples): {e}")

    # -- Step 6: Triage intelligence --
    try:
        triage = step_triage_intelligence(project_root, rows, errors)
        result["triage_stats"] = triage
    except Exception as e:
        errors.append(f"Step 6 (triage intelligence): {e}")

    # -- Step 7: Search log seed --
    try:
        imported = step_search_log_seed(project_root, errors)
        result["search_log_imported"] = imported
    except Exception as e:
        errors.append(f"Step 7 (search log seed): {e}")

    # -- Step 8: ILL list seed --
    try:
        n_ill = step_ill_list(project_root, rows, pdfs_dir, errors)
        result["ill_list_generated"] = n_ill
    except Exception as e:
        errors.append(f"Step 8 (ILL list): {e}")

    # -- Step 9: Pipeline state --
    try:
        step_pipeline_state(project_root, rows, coverage, errors)
    except Exception as e:
        errors.append(f"Step 9 (pipeline state): {e}")

    # Taxonomy count: species in coverage data
    result["taxonomy_cached"] = coverage.get("s_obs", 0)

    # Log the bootstrap event
    try:
        append_jsonl(
            os.path.join(project_root, "state", "run_log.jsonl"),
            {
                "event": "bootstrap_complete",
                "records": len(rows),
                "processed_papers": result["processed_papers"],
                "errors": len(errors),
                "timestamp": now_iso(),
            },
        )
    except Exception:
        pass  # logging failure is non-fatal

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap TraitTrawler v5 learning state"
    )
    parser.add_argument(
        "--project-root", required=True,
        help="Project root directory",
    )
    parser.add_argument(
        "--results", default=None,
        help="Path to results.csv (default: <project-root>/results.csv)",
    )
    parser.add_argument(
        "--pdfs", default=None,
        help="Path to PDFs directory (default: auto-detect)",
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Auto mode: skip if already bootstrapped",
    )

    args = parser.parse_args()

    result = bootstrap(
        project_root=args.project_root,
        results_path=args.results,
        pdfs_dir=args.pdfs,
        auto=args.auto,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
