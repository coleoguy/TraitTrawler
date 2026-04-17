#!/usr/bin/env python3
"""Initialize a fresh TraitTrawler v6 project.

Creates the directory tree, initial config.yaml, and session.json
in phase 1.LEARN. Non-destructive: refuses to run if target root
already contains state/.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_VERSION = "6.0.0"

CONFIG_TEMPLATE = """\
# TraitTrawler v6 project config
skill_version: {version}
trait: {trait!r}
taxa: {taxa!r}
seed_dois: {seed_dois}

# Batch processing
batch_size: 5
review_queue_max: 50

# Model selection (override per-subagent if needed)
models:
  triage: haiku
  extractor: opus
  semantic_verifier: sonnet
  structurer: sonnet
  adjudicator: opus

# Search sources (order = priority)
search_sources: [pubmed, biorxiv, openalex, crossref]

# Throttling
http_rate_limit_per_host_per_second: 1
"""

SESSION_TEMPLATE = {
    "phase": "1.LEARN",
    "created_utc": None,
    "updated_utc": None,
    "batch_cursor": 0,
    "papers_processed": 0,
    "rows_written": 0,
    "review_queue_size": 0,
    "session_id": None,
}


def iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize a TraitTrawler v6 project")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--trait", required=True)
    ap.add_argument("--taxa", required=True)
    ap.add_argument("--seed-dois", default="", help="Comma-separated DOIs")
    args = ap.parse_args()

    root: Path = args.root.expanduser().resolve()
    state_dir = root / "state"
    if state_dir.exists():
        print(f"REFUSING: {state_dir} already exists. Use --root on an empty/new dir.",
              file=sys.stderr)
        return 2

    # Build directory tree
    for sub in ("state", "pdfs", "reports", "state/claims", "state/rows",
                "state/triage", "state/adjudications"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    # Write config.yaml
    seed_dois = [s.strip() for s in args.seed_dois.split(",") if s.strip()]
    cfg = CONFIG_TEMPLATE.format(
        version=SKILL_VERSION,
        trait=args.trait,
        taxa=args.taxa,
        seed_dois=json.dumps(seed_dois),
    )
    (root / "config.yaml").write_text(cfg)

    # Write session.json
    session = dict(SESSION_TEMPLATE)
    now = iso_utc()
    session["created_utc"] = now
    session["updated_utc"] = now
    session["session_id"] = f"sess_{now.replace(':', '').replace('-', '')}"
    (state_dir / "session.json").write_text(json.dumps(session, indent=2))

    # Touch append-only files so downstream code can open in append mode
    for f in ("ledger.jsonl", "review_queue.jsonl", "disputes.jsonl"):
        (state_dir / f).touch()
    (root / "candidates.jsonl").touch()
    (root / "results.csv").touch()
    (root / "legacy_rejected.csv").touch()

    # Initial empty manifest
    from_manifest_path = root / "state" / "manifest.sqlite"
    import sqlite3
    con = sqlite3.connect(from_manifest_path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS pdfs (
            sha256 TEXT PRIMARY KEY,
            canonical_path TEXT NOT NULL,
            original_filename TEXT,
            pages INTEGER,
            bytes INTEGER,
            added_utc TEXT NOT NULL,
            doi TEXT,
            fetch_status TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_doi ON pdfs(doi);
        CREATE TABLE IF NOT EXISTS candidates_link (
            candidate_id TEXT PRIMARY KEY,
            sha256 TEXT REFERENCES pdfs(sha256)
        );
    """)
    con.commit()
    con.close()

    print(json.dumps({
        "status": "ok",
        "root": str(root),
        "phase": "1.LEARN",
        "seed_dois_queued": seed_dois,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
