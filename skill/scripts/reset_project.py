#!/usr/bin/env python3
"""
Reset a TraitTrawler project for a fresh start while preserving:
- collector_config.yaml, config.py, guide.md (project configuration)
- pdfs/ (already-downloaded papers)
- state/benchmark_gold.jsonl (gold standard for validation)
- Benchmark DOIs in processed.json (keeps the model blind to holdout papers)
- leads.csv (papers needing full text)

Everything else is backed up to pre_reset/ and then cleared.

Usage:
    python3 scripts/reset_project.py --project-root .
    python3 scripts/reset_project.py --project-root . --execute
"""

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


def get_benchmark_dois(project_root):
    """Extract unique DOIs from benchmark_gold.jsonl."""
    gold_path = os.path.join(project_root, "state", "benchmark_gold.jsonl")
    dois = set()
    if not os.path.exists(gold_path):
        return dois
    with open(gold_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                doi = entry.get("doi", "")
                if doi:
                    dois.add(doi)
            except json.JSONDecodeError:
                continue
    return dois


def plan_reset(project_root):
    """Show what will be reset and what will be preserved."""
    root = Path(project_root)

    benchmark_dois = get_benchmark_dois(project_root)
    print(f"Project: {root.resolve()}")
    print()

    # Count current state
    results_path = root / "results.csv"
    if results_path.exists():
        with open(results_path) as f:
            n_records = sum(1 for _ in f) - 1
        print(f"Current results.csv: {n_records} records")

    processed_path = root / "state" / "processed.json"
    if processed_path.exists():
        with open(processed_path) as f:
            processed = json.load(f)
        print(f"Current processed.json: {len(processed)} entries")

    print(f"Benchmark DOIs to preserve: {len(benchmark_dois)}")
    for d in sorted(benchmark_dois):
        print(f"  {d}")

    # Count PDFs
    pdfs_dir = root / "pdfs"
    if pdfs_dir.exists():
        n_pdfs = sum(1 for _ in pdfs_dir.rglob("*.pdf"))
        print(f"PDFs preserved: {n_pdfs}")

    # Stray files in root
    stray = [f.name for f in root.iterdir()
             if f.is_file() and f.suffix in (".txt", ".md", ".json", ".html")
             and f.name not in ("collector_config.yaml", "config.py", "guide.md",
                                "results.csv", "leads.csv", "context.md",
                                "extraction_examples.md", "dashboard.html",
                                "requirements.txt")]
    if stray:
        print(f"\nStray files to remove ({len(stray)}):")
        for s in sorted(stray):
            print(f"  {s}")

    print()
    print("WILL PRESERVE:")
    print("  collector_config.yaml, config.py, guide.md")
    print("  extraction_examples.md (if exists)")
    print("  pdfs/ (all downloaded papers)")
    print("  state/benchmark_gold.jsonl")
    print("  state/calibration_complete.json")
    print(f"  {len(benchmark_dois)} benchmark DOIs in processed.json")
    print("  leads.csv")
    print()
    print("WILL RESET (backed up to pre_reset/):")
    print("  results.csv → header-only")
    print("  state/processed.json → benchmark DOIs only")
    print("  state/queue.json → []")
    print("  state/search_log.json → {}")
    print("  state/run_log.jsonl → empty")
    print("  state/discoveries.jsonl → empty")
    print("  state/triage_outcomes.jsonl → empty")
    print("  state/source_stats.json → {}")
    print("  state/consensus_stats.json → {}")
    print("  state/taxonomy_cache.json → preserved (reusable)")
    print("  Stray files in project root → deleted")
    print()
    print("Run with --execute to perform the reset.")


def execute_reset(project_root):
    """Perform the reset."""
    root = Path(project_root)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_dir = root / f"pre_reset_{ts}"
    backup_dir.mkdir(exist_ok=True)

    benchmark_dois = get_benchmark_dois(project_root)

    # Back up everything first
    print(f"Backing up to {backup_dir}/")
    for f in ["results.csv", "leads.csv", "context.md"]:
        src = root / f
        if src.exists():
            shutil.copy2(src, backup_dir / f)

    state_backup = backup_dir / "state"
    state_backup.mkdir(exist_ok=True)
    state_dir = root / "state"
    if state_dir.exists():
        for f in state_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, state_backup / f.name)

    # Reset results.csv — get header from existing file or config
    results_path = root / "results.csv"
    if results_path.exists():
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
        with open(results_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        print(f"  results.csv → header only ({len(fieldnames)} columns)")

    # Reset processed.json — keep only benchmark DOIs
    processed_path = root / "state" / "processed.json"
    benchmark_processed = {}
    if processed_path.exists():
        with open(processed_path) as f:
            old = json.load(f)
        # Keep benchmark DOIs
        for doi in benchmark_dois:
            if doi in old:
                benchmark_processed[doi] = old[doi]
            else:
                benchmark_processed[doi] = {
                    "triage": "benchmark_holdout",
                    "outcome": "benchmark_holdout",
                    "records": 0,
                    "date": ts,
                }
        # Also check for pdf-filename-style keys that might be benchmark papers
        for key, val in old.items():
            if any(d in key for d in benchmark_dois):
                benchmark_processed[key] = val
    else:
        for doi in benchmark_dois:
            benchmark_processed[doi] = {
                "triage": "benchmark_holdout",
                "outcome": "benchmark_holdout",
                "records": 0,
                "date": ts,
            }

    with open(processed_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_processed, f, indent=2)
    print(f"  processed.json → {len(benchmark_processed)} benchmark entries only")

    # Reset other state files
    resets = {
        "state/queue.json": "[]",
        "state/search_log.json": "{}",
        "state/source_stats.json": "{}",
        "state/consensus_stats.json": "{}",
        "state/large_pdf_progress.json": "{}",
    }
    for path, content in resets.items():
        full_path = root / path
        with open(full_path, "w") as f:
            f.write(content + "\n")
        print(f"  {path} → reset")

    # Clear JSONL files (empty)
    for jl in ["state/run_log.jsonl", "state/discoveries.jsonl",
               "state/triage_outcomes.jsonl", "state/calibration_data.jsonl"]:
        full_path = root / jl
        with open(full_path, "w") as f:
            pass
        print(f"  {jl} → cleared")

    # Remove stray files from project root
    stray_exts = {".txt", ".json"}
    stray_keep = {"collector_config.yaml", "config.py", "guide.md",
                  "results.csv", "leads.csv", "context.md",
                  "extraction_examples.md", "dashboard.html",
                  "requirements.txt"}
    removed = 0
    for f in root.iterdir():
        if f.is_file() and f.suffix in stray_exts and f.name not in stray_keep:
            shutil.move(str(f), str(backup_dir / f.name))
            removed += 1
    # Also move stray .md files that aren't config
    for f in root.iterdir():
        if (f.is_file() and f.suffix == ".md"
                and f.name not in stray_keep
                and f.name not in ("README.md", "CHANGELOG.md")):
            shutil.move(str(f), str(backup_dir / f.name))
            removed += 1
    if removed:
        print(f"  Moved {removed} stray files to backup")

    # Preserve taxonomy_cache (saves GBIF lookups)
    print("  state/taxonomy_cache.json → preserved (reusable)")
    # Preserve calibration_complete.json (skips re-calibration)
    print("  state/calibration_complete.json → preserved")
    # Preserve benchmark_gold.jsonl
    print("  state/benchmark_gold.jsonl → preserved")

    print()
    print(f"Reset complete. Backup at: {backup_dir}/")
    print(f"Benchmark DOIs preserved: {len(benchmark_processed)}")
    print("Start a new session to begin fresh collection.")


def main():
    parser = argparse.ArgumentParser(
        description="Reset a TraitTrawler project while preserving config and benchmarks")
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--execute", action="store_true",
                        help="Actually perform the reset (default: dry run)")
    args = parser.parse_args()

    if not os.path.exists(os.path.join(args.project_root, "collector_config.yaml")):
        print(f"Error: {args.project_root} doesn't look like a TraitTrawler project "
              f"(no collector_config.yaml)", file=sys.stderr)
        sys.exit(1)

    if args.execute:
        execute_reset(args.project_root)
    else:
        plan_reset(args.project_root)


if __name__ == "__main__":
    main()
