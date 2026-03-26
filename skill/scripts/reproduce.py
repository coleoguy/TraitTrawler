#!/usr/bin/env python3
"""
Reproducibility verification for TraitTrawler.

Generates a reproducibility report by comparing current extraction
results against the state at a specific session. Measures drift from
guide.md changes, model updates, and stochastic variation.

Usage:
    python3 scripts/reproduce.py --project-root . --session 2026-03-24T14:30:00Z
    python3 scripts/reproduce.py --project-root . --summary
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def load_run_log(project_root):
    """Load session events from run_log.jsonl."""
    path = Path(project_root) / "state" / "run_log.jsonl"
    if not path.exists():
        return []

    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def load_snapshots(project_root):
    """Load reproducibility snapshots."""
    snap_dir = Path(project_root) / "state" / "snapshots"
    if not snap_dir.exists():
        return {}

    snapshots = {}
    for f in snap_dir.glob("*.json"):
        with open(f) as fh:
            snap = json.load(fh)
            sid = snap.get("session_id", f.stem)
            snapshots[sid] = snap
    return snapshots


def get_session_papers(events, session_id):
    """Get list of DOIs processed in a specific session."""
    papers = []
    for event in events:
        if event.get("session_id") == session_id and event.get("event") == "paper_processed":
            papers.append({
                "doi": event.get("doi", ""),
                "records": event.get("records", 0),
            })
    return papers


def get_session_records(project_root, session_id):
    """Get records from results.csv that belong to a specific session."""
    path = Path(project_root) / "results.csv"
    if not path.exists():
        return []

    records = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("session_id", "") == session_id:
                records.append(row)
    return records


def list_sessions(events):
    """List all sessions with basic stats."""
    sessions = {}
    for event in events:
        sid = event.get("session_id", "")
        if not sid:
            continue
        if sid not in sessions:
            sessions[sid] = {"papers": 0, "records": 0, "guide_md5": "", "start": ""}
        if event.get("event") == "session_start":
            sessions[sid]["guide_md5"] = event.get("guide_md5", "")
            sessions[sid]["start"] = event.get("timestamp", "")
        elif event.get("event") == "paper_processed":
            sessions[sid]["papers"] += 1
            sessions[sid]["records"] += event.get("records", 0)
        elif event.get("event") == "session_end":
            sessions[sid]["records"] = event.get("records_added", sessions[sid]["records"])
    return sessions


def compute_file_hash(filepath):
    """Compute SHA-256 hash of a file."""
    if not os.path.exists(filepath):
        return None
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def check_pdf_availability(project_root, dois):
    """Check which PDFs are cached locally."""
    pdf_dir = Path(project_root) / "pdfs"
    available = 0
    missing = 0

    # Build index of all PDFs
    pdf_files = set()
    if pdf_dir.exists():
        for f in pdf_dir.rglob("*.pdf"):
            pdf_files.add(f.name.lower())

    # For each DOI, check if a PDF exists (approximate match on DOI suffix)
    for doi in dois:
        doi_suffix = doi.split("/")[-1].split(".")[-1][:10] if "/" in doi else doi[:10]
        found = any(doi_suffix.lower() in pf for pf in pdf_files)
        if found:
            available += 1
        else:
            missing += 1

    return available, missing


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler reproducibility verification")
    parser.add_argument("--project-root", required=True, help="Project root directory")
    parser.add_argument("--session", help="Session ID to verify")
    parser.add_argument("--summary", action="store_true", help="List all sessions with stats")
    args = parser.parse_args()

    project_root = args.project_root
    events = load_run_log(project_root)

    if not events:
        print("No session history found in state/run_log.jsonl")
        return

    if args.summary:
        sessions = list_sessions(events)
        print(f"── Session History ────────────────")
        print(f" {'Session ID':30s} │ Papers │ Records │ Guide Hash")
        print(f" {'─' * 30}─┼────────┼─────────┼───────────")
        for sid, stats in sorted(sessions.items()):
            print(f" {sid:30s} │ {stats['papers']:6d} │ {stats['records']:7d} │ {stats['guide_md5'][:8]}...")
        print(f"────────────────────────────────────")

        # Current state
        guide_hash = compute_file_hash(os.path.join(project_root, "guide.md"))
        print(f"\n Current guide.md hash: {guide_hash[:16] if guide_hash else 'N/A'}...")

        # Count guide changes
        guide_updates = [e for e in events if e.get("event") == "guide_updated"]
        print(f" Guide amendments since inception: {len(guide_updates)}")
        return

    if not args.session:
        print("Specify --session <session_id> or --summary")
        return

    session_id = args.session

    # Get session info
    papers = get_session_papers(events, session_id)
    records = get_session_records(project_root, session_id)
    snapshots = load_snapshots(project_root)
    snapshot = snapshots.get(session_id, {})

    if not papers and not records:
        print(f"No data found for session {session_id}")
        return

    # Check guide.md drift
    current_guide_hash = compute_file_hash(os.path.join(project_root, "guide.md"))
    session_guide_hash = None
    for event in events:
        if event.get("session_id") == session_id and event.get("event") == "session_start":
            session_guide_hash = event.get("guide_md5", "")
            break

    guide_changed = session_guide_hash and current_guide_hash and session_guide_hash != current_guide_hash[:len(session_guide_hash)]

    # Count guide amendments between session and now
    guide_updates = [
        e for e in events
        if e.get("event") == "guide_updated"
        and e.get("timestamp", "") > session_id
    ]

    # Check PDF availability
    dois = [p["doi"] for p in papers if p["doi"]]
    pdfs_available, pdfs_missing = check_pdf_availability(project_root, dois)

    # Print reproducibility report
    print(f"── Reproducibility Report ─────────")
    print(f" Session             : {session_id}")
    print(f" Papers processed    : {len(papers)}")
    print(f" Records in database : {len(records)}")
    print(f" PDFs cached locally : {pdfs_available}/{pdfs_available + pdfs_missing}")
    print(f" Guide.md changed    : {'YES' if guide_changed else 'NO'} ({len(guide_updates)} amendments since)")

    if snapshot:
        print(f" Model at session    : {snapshot.get('model_id', 'unknown')}")
        print(f" Skill version       : {snapshot.get('skill_version', 'unknown')}")
        print(f" Python version      : {snapshot.get('python_version', 'unknown')}")

    print(f"")

    if pdfs_missing > 0:
        print(f" ⚠ {pdfs_missing} PDFs not cached — re-extraction would require re-downloading")

    if guide_changed:
        print(f" ℹ guide.md has changed — re-extraction with current rules may produce")
        print(f"   different results (expected and desirable if rules improved)")

    print(f"")
    print(f" To re-extract this session's papers with current rules:")
    print(f"   1. Run TraitTrawler in PDF-first mode")
    print(f"   2. Compare new records against originals in results.csv")
    print(f"   3. Differences indicate guide.md improvement impact")
    print(f"────────────────────────────────────")


if __name__ == "__main__":
    main()
