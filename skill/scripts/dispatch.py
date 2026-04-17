#!/usr/bin/env python3
"""Session state-machine helper.

Thin CLI wrapper around state/session.json so subagents (and the
Manager) can read and advance phase without loading YAML or SQLite.

Commands:
  phase        Print current phase
  advance      Advance to the next phase
  set          Set a specific phase
  bump         Increment batch_cursor and papers_processed
  status       Dump the whole session.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PHASE_ORDER = [
    "0.SETUP", "1.LEARN", "2.SCHEMA", "3.SEARCH",
    "4.FETCH", "5.PROCESS", "6.REVIEW", "7.REPORT",
]


def session_path(root: Path) -> Path:
    return root / "state" / "session.json"


def load(root: Path) -> dict:
    p = session_path(root)
    if not p.exists():
        raise SystemExit(f"no session.json at {p}")
    return json.loads(p.read_text())


def save(root: Path, session: dict) -> None:
    session["updated_utc"] = datetime.now(timezone.utc).isoformat()
    session_path(root).write_text(json.dumps(session, indent=2))


def cli() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("phase")
    sub.add_parser("advance")
    s = sub.add_parser("set")
    s.add_argument("--to", required=True, choices=PHASE_ORDER)
    b = sub.add_parser("bump")
    b.add_argument("--papers", type=int, default=0)
    b.add_argument("--rows", type=int, default=0)
    b.add_argument("--review-delta", type=int, default=0)
    sub.add_parser("status")
    args = ap.parse_args()

    root = args.project_root.resolve()
    sess = load(root)

    if args.cmd == "phase":
        print(sess["phase"])
    elif args.cmd == "advance":
        i = PHASE_ORDER.index(sess["phase"])
        if i + 1 < len(PHASE_ORDER):
            sess["phase"] = PHASE_ORDER[i + 1]
            save(root, sess)
        print(sess["phase"])
    elif args.cmd == "set":
        sess["phase"] = args.to
        save(root, sess)
        print(sess["phase"])
    elif args.cmd == "bump":
        sess["batch_cursor"] = sess.get("batch_cursor", 0) + 1
        sess["papers_processed"] = sess.get("papers_processed", 0) + args.papers
        sess["rows_written"] = sess.get("rows_written", 0) + args.rows
        sess["review_queue_size"] = sess.get("review_queue_size", 0) + args.review_delta
        save(root, sess)
        print(json.dumps(sess, indent=2))
    elif args.cmd == "status":
        print(json.dumps(sess, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
