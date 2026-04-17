#!/usr/bin/env python3
"""Structured review queue with resolution states.

- Adds items from state/disputes.jsonl (after adjudicator routing) to
  state/review_queue.jsonl with resolution_state=pending.
- Emits an HTML bundle for batch human review.
- Applies a decisions CSV back into results.csv / legacy_rejected.csv
  and updates active-learning counters.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ISO = lambda: datetime.now(timezone.utc).isoformat()


def enqueue(disputes_path: Path, queue_path: Path) -> int:
    """Move disputes to review queue with pending state."""
    if not disputes_path.exists():
        return 0
    added = 0
    with disputes_path.open() as f, queue_path.open("a") as qf:
        for line in f:
            line = line.strip()
            if not line:
                continue
            dispute = json.loads(line)
            item = {
                "review_id": f"rv_{uuid.uuid4().hex[:12]}",
                "created_utc": ISO(),
                "dispute_id": dispute.get("dispute_id"),
                "row": dispute.get("row"),
                "failure_reasons": dispute.get("failure_reasons", []),
                "verbatim_quote": dispute.get("verbatim_quote"),
                "page": dispute.get("row", {}).get("page"),
                "sha256": dispute.get("row", {}).get("sha256"),
                "adjudicator_verdict": dispute.get("adjudicator_verdict"),
                "adjudicator_reasoning": dispute.get("adjudicator_reasoning"),
                "resolution_state": "pending",
                "resolution": None,
                "resolved_by": None,
                "resolved_utc": None,
            }
            qf.write(json.dumps(item) + "\n")
            added += 1
    # truncate disputes file once enqueued
    disputes_path.write_text("")
    return added


def emit_html(queue_path: Path, out_path: Path, top: int = 20) -> int:
    items: list[dict] = []
    if queue_path.exists():
        with queue_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if item.get("resolution_state") == "pending":
                    items.append(item)
                if len(items) >= top:
                    break

    rows_html = []
    for item in items:
        rid = html.escape(item["review_id"])
        q = html.escape(item.get("verbatim_quote") or "")
        reasons = "".join(
            f"<li>{html.escape(r)}</li>" for r in item.get("failure_reasons", [])
        )
        row = item.get("row") or {}
        row_summary = "; ".join(
            f"<b>{html.escape(k)}</b>={html.escape(str(v))}"
            for k, v in row.items()
            if k in ("canonical_species", "diploid_2n", "sex_system",
                     "haploid_autosome_count", "page")
        )
        rows_html.append(f"""
<div class="item" data-id="{rid}">
  <div class="hd">
    <code>{rid}</code> — page {item.get('page')} —
    sha256 <small>{html.escape((item.get('sha256') or '')[:12])}…</small>
  </div>
  <div class="row">{row_summary}</div>
  <div class="quote">“{q}”</div>
  <ul class="reasons">{reasons}</ul>
  <div class="controls">
    <label><input type="radio" name="{rid}" value="confirm"> confirm</label>
    <label><input type="radio" name="{rid}" value="correct"> correct</label>
    <label><input type="radio" name="{rid}" value="reject"> reject</label>
    <label><input type="radio" name="{rid}" value="defer"> defer</label>
    <input type="text" class="comment" placeholder="optional comment"/>
  </div>
</div>""")

    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8"/><title>TraitTrawler Review</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;max-width:900px;margin:2em auto;padding:0 1em}}
.item{{border:1px solid #ccc;border-radius:6px;padding:1em;margin-bottom:1.5em}}
.hd{{color:#555;font-size:.9em;margin-bottom:.5em}}
.quote{{background:#ffc;padding:.6em;border-left:3px solid #c90;margin:.5em 0;font-style:italic}}
.reasons{{color:#a30;margin:.5em 0}}
.controls label{{margin-right:1em}}
.controls input[type=text]{{width:100%;margin-top:.4em}}
button{{background:#036;color:#fff;padding:.6em 1.2em;border:0;border-radius:4px;font-size:1em}}
</style></head><body>
<h1>TraitTrawler Review — {len(items)} pending</h1>
<p>Pick confirm / correct / reject / defer for each item, then click Save.</p>
<form id="f">{''.join(rows_html)}
<button type="button" onclick="save()">Save decisions CSV</button>
</form>
<script>
function save(){{
 const items=document.querySelectorAll('.item');
 let csv='review_id,decision,comment\\n';
 items.forEach(it=>{{
   const id=it.dataset.id;
   const picked=it.querySelector('input[type=radio]:checked');
   const comment=it.querySelector('.comment').value.replaceAll('"','""');
   if(picked)csv+=`${{id}},${{picked.value}},"${{comment}}"\\n`;
 }});
 const blob=new Blob([csv],{{type:'text/csv'}});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);
 a.download='review_decisions.csv';a.click();
}}
</script></body></html>"""
    out_path.write_text(html_doc)
    return len(items)


def apply_decisions(
    queue_path: Path,
    decisions_csv: Path,
    results_csv: Path,
    rejected_csv: Path,
) -> dict:
    decisions: dict[str, tuple[str, str]] = {}
    with decisions_csv.open() as f:
        for row in csv.DictReader(f):
            decisions[row["review_id"]] = (row["decision"], row.get("comment", ""))

    stats = {"confirmed": 0, "corrected": 0, "rejected": 0, "deferred": 0,
             "unknown": 0}
    new_queue_lines: list[str] = []

    with queue_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            rid = item["review_id"]
            if rid not in decisions:
                new_queue_lines.append(json.dumps(item))
                continue
            decision, comment = decisions[rid]
            item["resolved_utc"] = ISO()
            item["resolved_by"] = "human"
            item["resolution"] = {"decision": decision, "comment": comment}
            if decision == "confirm":
                item["resolution_state"] = "confirmed"
                _append_csv_row(results_csv, item.get("row") or {})
                stats["confirmed"] += 1
            elif decision == "correct":
                item["resolution_state"] = "corrected"
                # corrected rows assume the human hand-edited a sidecar CSV
                # and will be merged separately; for now write as-is with flag
                corrected = dict(item.get("row") or {})
                corrected["human_corrected"] = True
                corrected["human_comment"] = comment
                _append_csv_row(results_csv, corrected)
                stats["corrected"] += 1
            elif decision == "reject":
                item["resolution_state"] = "rejected"
                rej = dict(item.get("row") or {})
                rej["rejection_reason"] = comment or "human_rejected"
                _append_csv_row(rejected_csv, rej)
                stats["rejected"] += 1
            elif decision == "defer":
                item["resolution_state"] = "deferred"
                stats["deferred"] += 1
                new_queue_lines.append(json.dumps(item))
            else:
                stats["unknown"] += 1
                new_queue_lines.append(json.dumps(item))

    queue_path.write_text("\n".join(new_queue_lines) + ("\n" if new_queue_lines else ""))
    return stats


def _append_csv_row(csv_path: Path, row: dict) -> None:
    """Append a single dict as a CSV row, inferring header from the file."""
    existing_header: list[str] = []
    if csv_path.exists() and csv_path.stat().st_size > 0:
        with csv_path.open() as f:
            reader = csv.reader(f)
            existing_header = next(reader, [])
    header = existing_header or list(row.keys())
    write_header = not existing_header
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("enqueue")
    hp = sub.add_parser("emit-html")
    hp.add_argument("--top", type=int, default=20)
    hp.add_argument("--out", type=Path)
    ap_apply = sub.add_parser("apply")
    ap_apply.add_argument("--decisions", type=Path, required=True)

    args = ap.parse_args()
    root = args.project_root.resolve()
    queue = root / "state" / "review_queue.jsonl"
    disputes = root / "state" / "disputes.jsonl"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.touch(exist_ok=True)

    if args.cmd == "enqueue":
        n = enqueue(disputes, queue)
        print(json.dumps({"enqueued": n}))
    elif args.cmd == "emit-html":
        out = args.out or (root / "reports" / f"review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        n = emit_html(queue, out, top=args.top)
        print(json.dumps({"html": str(out), "items": n}))
    elif args.cmd == "apply":
        stats = apply_decisions(
            queue,
            args.decisions,
            root / "results.csv",
            root / "legacy_rejected.csv",
        )
        print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
