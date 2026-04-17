#!/usr/bin/env python3
"""Append a one-line batch summary to state/manager_log.md.

The Manager calls this at every batch close. The log is a running
narrative that survives context compaction — if the Manager's
in-context memory of batches 1-37 is lost, it can tail this file to
restore narrative continuity before dispatching batch 38.

Keep each entry to ~80 chars on one line so tailing ~50 lines gives
a compact readable history. Surprises and anomalies go here too.

Usage:
  python session_log.py --root <root> \
    --batch 7 --rows-written 14 --to-review 3 \
    --adjudicated 1 --interesting "Smith 2013 contradicts Jones 1998"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def iso_short() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--rows-written", type=int, default=0)
    ap.add_argument("--to-review", type=int, default=0)
    ap.add_argument("--adjudicated", type=int, default=0)
    ap.add_argument("--papers-in-batch", type=int, default=0)
    ap.add_argument("--interesting", default="")
    ap.add_argument("--cost-estimate", type=float, default=None)
    args = ap.parse_args()

    root = args.root.resolve()
    log = root / "state" / "manager_log.md"
    first = not log.exists()
    line = (f"- [{iso_short()}] batch {args.batch} ({args.papers_in_batch}p): "
            f"{args.rows_written} rows, {args.to_review} review, "
            f"{args.adjudicated} adj")
    if args.cost_estimate is not None:
        line += f", ~${args.cost_estimate:.2f}"
    if args.interesting:
        line += f" — {args.interesting[:100]}"
    line += "\n"

    with log.open("a") as f:
        if first:
            f.write("# Manager Session Log\n\n")
            f.write("One line per batch close. Tail the last ~50 lines to "
                    "re-establish narrative continuity after compaction.\n\n")
        f.write(line)
    print(line.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
