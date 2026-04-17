#!/usr/bin/env python3
"""Manager checkpoint: compact on-disk summary that survives compaction.

The Manager's context fills up over a long run. Claude Code will
eventually auto-compact. When that happens, everything the Manager
"remembered" about which papers went how is at risk — unless that
memory lived on disk.

This script writes `state/manager_checkpoint.md` — a compact,
chronological, plain-markdown summary of the session so far. The
Manager writes a new checkpoint every N batches (default 10) and
reads it as the FIRST thing it does after any session break or
suspected compaction.

The checkpoint answers the four questions a post-compaction Manager
needs to resume coherently:
  1. Where are we in the phase state machine?
  2. What has been written so far (counts)?
  3. What surprising / interesting findings deserve follow-up?
  4. What pauses / user input are outstanding?

Usage:
  python checkpoint.py --project-root <root>            # write new
  python checkpoint.py --project-root <root> --show     # print current
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gather_state(root: Path) -> dict:
    session_path = root / "state" / "session.json"
    ledger_path = root / "state" / "ledger.jsonl"
    review_path = root / "state" / "review_queue.jsonl"
    results_path = root / "results.csv"
    rejected_path = root / "legacy_rejected.csv"
    candidates_path = root / "candidates.jsonl"

    session = {}
    if session_path.exists():
        session = json.loads(session_path.read_text())

    # Ledger tally
    ledger_count = 0
    source_type_counter: Counter = Counter()
    hook_fail_counter: Counter = Counter()
    last_timestamps: list[str] = []
    if ledger_path.exists():
        with ledger_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ledger_count += 1
                source_type_counter[entry.get("source_type") or "unknown"] += 1
                for hr in entry.get("hook_results", []) or []:
                    if hr.get("verdict") == "fail":
                        hook_fail_counter[hr.get("hook") or "unknown"] += 1
                ts = entry.get("timestamp_utc")
                if ts:
                    last_timestamps.append(ts)
    last_timestamps.sort()

    # Review queue by state
    review_counter: Counter = Counter()
    if review_path.exists():
        with review_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                review_counter[entry.get("resolution_state") or "unknown"] += 1

    # CSV row counts
    rows_ok = 0
    if results_path.exists() and results_path.stat().st_size > 0:
        with results_path.open() as f:
            rows_ok = max(0, sum(1 for _ in csv.reader(f)) - 1)
    rows_rej = 0
    if rejected_path.exists() and rejected_path.stat().st_size > 0:
        with rejected_path.open() as f:
            rows_rej = max(0, sum(1 for _ in csv.reader(f)) - 1)

    # Candidate count
    candidates_count = 0
    if candidates_path.exists():
        with candidates_path.open() as f:
            candidates_count = sum(1 for line in f if line.strip())

    return {
        "session": session,
        "ledger_count": ledger_count,
        "source_type_counter": dict(source_type_counter),
        "hook_fail_counter": dict(hook_fail_counter.most_common(10)),
        "review_counter": dict(review_counter),
        "rows_ok": rows_ok,
        "rows_rej": rows_rej,
        "candidates_count": candidates_count,
        "last_ledger_timestamp": last_timestamps[-1] if last_timestamps else None,
    }


def render_checkpoint(root: Path, state: dict) -> str:
    sess = state["session"]
    lines = [
        "# Manager Checkpoint",
        f"_Written: {iso()}_",
        "",
        "Read this file at the start of every Manager turn to re-establish",
        "context without depending on in-session memory. If this conflicts",
        "with your in-context memory, this file wins (it is the source of",
        "truth along with session.json).",
        "",
        "## Current phase",
        f"- **Phase**: `{sess.get('phase')}`",
        f"- Session ID: `{sess.get('session_id')}`",
        f"- Created: {sess.get('created_utc')}",
        f"- Last updated: {sess.get('updated_utc')}",
        f"- Batch cursor: {sess.get('batch_cursor', 0)}",
        f"- Papers processed: {sess.get('papers_processed', 0)}",
        "",
        "## Output counts",
        f"- Ledger entries: **{state['ledger_count']}**",
        f"- Rows in `results.csv`: **{state['rows_ok']}**",
        f"- Rows in `legacy_rejected.csv`: {state['rows_rej']}",
        f"- Candidates queued: {state['candidates_count']}",
        f"- Review queue by state:",
    ]
    for st, n in sorted(state["review_counter"].items()):
        lines.append(f"  - {st}: {n}")

    lines += ["", "## Source-type mix"]
    for st, n in sorted(state["source_type_counter"].items(),
                         key=lambda kv: -kv[1]):
        lines.append(f"- {st}: {n}")

    lines += ["", "## Top hook failures (last-10 firing)"]
    for h, n in state["hook_fail_counter"].items():
        lines.append(f"- {h}: {n}")

    lines += [
        "",
        "## Resume instructions",
        "",
        "Read `state/session.json` for authoritative phase state, then",
        "proceed with the Phase state machine as documented in SKILL.md.",
        "If `state/manager_log.md` exists, tail the last ~50 lines to",
        "restore narrative continuity. Do NOT try to recall earlier",
        "batches from memory.",
        "",
        f"Last ledger timestamp: {state['last_ledger_timestamp']}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    root = args.project_root.resolve()
    ckpt = root / "state" / "manager_checkpoint.md"

    if args.show:
        if ckpt.exists():
            print(ckpt.read_text())
        else:
            print("(no checkpoint yet)")
        return 0

    state = gather_state(root)
    text = render_checkpoint(root, state)
    ckpt.write_text(text)
    print(json.dumps({
        "written": str(ckpt),
        "ledger_count": state["ledger_count"],
        "rows_ok": state["rows_ok"],
        "phase": state["session"].get("phase"),
        "batch_cursor": state["session"].get("batch_cursor"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
