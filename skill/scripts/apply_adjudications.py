#!/usr/bin/env python3
"""Apply adjudicator rulings atomically.

Reads state/adjudications/*.json, merges rulings into results.csv /
legacy_rejected.csv / state/ledger.jsonl, and moves processed
adjudication files to state/adjudications/_applied/.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_row(csv_path: Path, row: dict) -> None:
    existing: list[str] = []
    if csv_path.exists() and csv_path.stat().st_size > 0:
        with csv_path.open() as f:
            existing = next(csv.reader(f), [])
    header = existing or list(row.keys())
    write_header = not existing
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    args = ap.parse_args()
    root = args.project_root.resolve()
    adj_dir = root / "state" / "adjudications"
    applied_dir = adj_dir / "_applied"
    applied_dir.mkdir(exist_ok=True)
    results = root / "results.csv"
    rejected = root / "legacy_rejected.csv"
    ledger = root / "state" / "ledger.jsonl"

    stats = {"accept": 0, "amend": 0, "reject": 0, "defer": 0}
    for jf in sorted(adj_dir.glob("*.json")):
        ruling = json.loads(jf.read_text())
        verdict = ruling.get("verdict")
        row = ruling.get("row") or {}
        if verdict == "accept":
            append_row(results, row)
            stats["accept"] += 1
        elif verdict == "amend":
            amended = {**row, **(ruling.get("amendments") or {})}
            append_row(results, amended)
            stats["amend"] += 1
        elif verdict == "reject":
            rej = {**row, "rejection_reason": ruling.get("reason") or "adjudicator_rejected"}
            append_row(rejected, rej)
            stats["reject"] += 1
        elif verdict == "defer":
            stats["defer"] += 1
            continue
        with ledger.open("a") as f:
            f.write(json.dumps({
                "adjudication_id": ruling.get("dispute_id"),
                "verdict": verdict,
                "reason": ruling.get("reason"),
                "amendments": ruling.get("amendments"),
                "timestamp_utc": iso(),
            }) + "\n")
        shutil.move(str(jf), applied_dir / jf.name)

    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
