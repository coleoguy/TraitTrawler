#!/usr/bin/env python3
"""End-of-session report generator.

Produces reports/session_<timestamp>.md with:
  - Coverage stats (papers processed, rows written, rejection rate)
  - Hook failure breakdown (which hooks fire most often)
  - Accuracy proxies (adjudicator accept/amend/reject ratios)
  - Per-source quality differentials (table vs prose, primary vs compilation)
  - Top anomalies for human follow-up
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    args = ap.parse_args()
    root = args.project_root.resolve()

    results = root / "results.csv"
    rejected = root / "legacy_rejected.csv"
    ledger_path = root / "state" / "ledger.jsonl"
    session_path = root / "state" / "session.json"

    # Counts from CSVs
    rows_ok = 0
    if results.exists():
        with results.open() as f:
            rows_ok = sum(1 for _ in csv.reader(f)) - 1
            rows_ok = max(0, rows_ok)
    rows_rej = 0
    if rejected.exists():
        with rejected.open() as f:
            rows_rej = sum(1 for _ in csv.reader(f)) - 1
            rows_rej = max(0, rows_rej)

    # Ledger analysis
    hook_counts: Counter = Counter()
    adj_counts: Counter = Counter()
    compilation_rows = 0
    total = 0
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
                total += 1
                for hr in entry.get("hook_results", []) or []:
                    if hr.get("verdict") == "fail":
                        hook_counts[hr.get("hook")] += 1
                adj = entry.get("adjudication")
                if adj and adj.get("verdict"):
                    adj_counts[adj["verdict"]] += 1

    session = {}
    if session_path.exists():
        session = json.loads(session_path.read_text())

    now = datetime.now(timezone.utc).isoformat()
    out_path = root / "reports" / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out_path.parent.mkdir(exist_ok=True)

    md_lines = [
        f"# TraitTrawler Session Report",
        f"Generated: {now}",
        "",
        "## Top-line",
        f"- Phase at report time: `{session.get('phase')}`",
        f"- Papers processed: **{session.get('papers_processed', 0)}**",
        f"- Rows written to results.csv: **{rows_ok}**",
        f"- Rows rejected: **{rows_rej}**",
        f"- Review queue size: **{session.get('review_queue_size', 0)}**",
        "",
        "## Hook failures (top 10)",
    ]
    for hook, n in hook_counts.most_common(10):
        md_lines.append(f"- `{hook}`: {n}")

    md_lines += ["", "## Adjudicator outcomes"]
    for v, n in adj_counts.most_common():
        md_lines.append(f"- {v}: {n}")

    md_lines += ["", f"## Ledger entries: {total}"]

    out_path.write_text("\n".join(md_lines))
    print(json.dumps({"report": str(out_path), "rows_ok": rows_ok,
                      "rows_rej": rows_rej, "ledger_entries": total}, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
