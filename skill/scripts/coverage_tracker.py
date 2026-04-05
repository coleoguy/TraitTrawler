#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 scripts/coverage_tracker.py --project-root /path/to/project
# OUTPUT: coverage_tracker.json in state/ AND JSON to stdout
"""
TraitTrawler Coverage Tracker
==============================
Tracks species accumulation and estimates taxonomic coverage using the
Chao1 nonparametric richness estimator.

Usage:
    python3 scripts/coverage_tracker.py --project-root /path/to/project

Reads results.csv and writes state/coverage_tracker.json with:
  - s_obs, singletons, doubletons, chao1, completeness
  - accumulation slope (new species per paper over last 10 papers)
  - total_records, total_papers, updated_at
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Import state_utils from sibling scripts directory
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from state_utils import safe_write_json


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------

def safe_read_csv(path):
    """Read a CSV file, returning a list of dicts. Returns [] if missing."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Chao1 richness estimator
# ---------------------------------------------------------------------------

def compute_chao1(species_counts):
    """
    Compute the Chao1 nonparametric species richness estimator.

    Args:
        species_counts: Counter mapping species -> observation count.

    Returns:
        (s_obs, f1, f2, chao1_estimate)
    """
    s_obs = len(species_counts)
    if s_obs == 0:
        return 0, 0, 0, 0.0

    f1 = sum(1 for c in species_counts.values() if c == 1)  # singletons
    f2 = sum(1 for c in species_counts.values() if c == 2)  # doubletons

    if f2 == 0:
        # Bias-corrected form when no doubletons observed
        chao1_est = s_obs + (f1 * (f1 - 1)) / 2 if f1 > 1 else float(s_obs)
    else:
        chao1_est = s_obs + (f1 ** 2) / (2 * f2)

    return s_obs, f1, f2, chao1_est


# ---------------------------------------------------------------------------
# Accumulation curve and slope
# ---------------------------------------------------------------------------

def accumulation_slope(records):
    """
    Build a species accumulation curve and compute the discovery slope
    over the last 10 papers.

    Records are sorted by processed_date (then doi for stability).
    A "paper" boundary is defined by a change in doi.

    Returns:
        (slope, total_papers)
        slope = new_species_in_last_10_papers / 10
        total_papers = number of distinct papers (by doi)
    """
    if not records:
        return 0.0, 0

    sorted_recs = sorted(
        records,
        key=lambda r: (r.get("processed_date", ""), r.get("doi", ""))
    )

    seen_species = set()
    paper_cumulative = []  # list of (paper_index, cumulative_species_count)
    current_doi = None
    paper_idx = 0

    for rec in sorted_recs:
        doi = rec.get("doi", "")
        if doi != current_doi:
            paper_idx += 1
            current_doi = doi
        sp = rec.get("species", "").strip()
        if sp:
            seen_species.add(sp)

        # Record the running total at each row; deduplicate to per-paper below
        paper_cumulative.append((paper_idx, len(seen_species)))

    # Keep only the last entry per paper (the final cumulative count)
    per_paper = {}
    for idx, count in paper_cumulative:
        per_paper[idx] = count
    curve = sorted(per_paper.items())  # [(paper_idx, cum_species), ...]

    total_papers = len(curve)
    if total_papers == 0:
        return 0.0, 0

    # Slope over the last 10 papers (or fewer if < 10 exist)
    window = min(10, total_papers)
    if window < 2:
        slope = 0.0
    else:
        tail = curve[-window:]
        new_in_window = tail[-1][1] - tail[0][1]
        slope = round(new_in_window / window, 2)

    return slope, total_papers


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(project_root):
    """
    Read results.csv, compute Chao1 coverage statistics, and return a
    summary dict ready for JSON serialisation.
    """
    results_path = os.path.join(project_root, "results.csv")
    records = safe_read_csv(results_path)

    # Extract species names (skip blank entries)
    species_list = [
        r.get("species", "").strip()
        for r in records
        if r.get("species", "").strip()
    ]

    species_counts = Counter(species_list)
    s_obs, f1, f2, chao1_est = compute_chao1(species_counts)

    # Completeness ratio
    completeness = round(s_obs / chao1_est, 3) if chao1_est > 0 else 1.0

    # Accumulation slope
    slope, total_papers = accumulation_slope(records)

    summary = {
        "s_obs": s_obs,
        "singletons": f1,
        "doubletons": f2,
        "chao1": round(chao1_est, 1),
        "completeness": completeness,
        "slope": slope,
        "total_records": len(records),
        "total_papers": total_papers,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TraitTrawler Coverage Tracker (Chao1 richness estimation)"
    )
    parser.add_argument(
        "--project-root", default=".",
        help="Project root directory (default: current directory)"
    )
    args = parser.parse_args()
    project_root = args.project_root

    summary = analyze(project_root)

    # Write to state/coverage_tracker.json
    out_path = os.path.join(project_root, "state", "coverage_tracker.json")
    safe_write_json(out_path, summary, backup=False)
    print(f"Coverage tracker written to {out_path}", file=sys.stderr)

    # Print JSON to stdout for the calling agent
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
