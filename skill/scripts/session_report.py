#!/usr/bin/env python3
"""
TraitTrawler Session Performance Report.

Reads run_log.jsonl, source_stats.json, processed.json, search_log.json,
and leads.csv to produce a comprehensive performance profile of a session.

Usage:
    python3 scripts/session_report.py --project-root .
    python3 scripts/session_report.py --project-root . --session 20260328T142904
    python3 scripts/session_report.py --project-root . --json  # machine-readable
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def read_jsonl(path, session_id=None):
    """Read JSONL file, skip corrupt lines. Optionally filter by session_id."""
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if session_id and entry.get("session_id") != session_id:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                pass
    return entries


def read_json(path, default=None):
    """Read JSON file safely."""
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return default if default is not None else {}


def count_csv_rows(path):
    """Count data rows in a CSV file."""
    if not os.path.exists(path):
        return 0
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header:
            for row in reader:
                if row:
                    count += 1
    return count


def parse_timestamp(ts_str):
    """Parse ISO timestamp. Canonical format is %Y-%m-%dT%H:%M:%SZ."""
    if not ts_str:
        return None
    # Strip trailing Z or +00:00 for uniform parsing
    clean = ts_str.replace("Z", "").replace("+00:00", "")
    # Try with and without fractional seconds
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


def generate_report(project_root, session_id=None, as_json=False):
    """Generate a comprehensive session performance report."""
    state_dir = os.path.join(project_root, "state")

    # Load all data — filter run_log during read for large files
    run_log = read_jsonl(os.path.join(state_dir, "run_log.jsonl"),
                         session_id=session_id)
    search_log = read_json(os.path.join(state_dir, "search_log.json"), {})
    processed = read_json(os.path.join(state_dir, "processed.json"), {})
    source_stats = read_json(os.path.join(state_dir, "source_stats.json"), {})
    results_rows = count_csv_rows(os.path.join(project_root, "results.csv"))
    leads_rows = count_csv_rows(os.path.join(project_root, "leads.csv"))

    # --- Session Timeline ---
    session_starts = [e for e in run_log if e.get("event") == "session_start"]
    session_ends = [e for e in run_log if e.get("event") == "session_end"]

    first_ts = None
    last_ts = None
    for entry in run_log:
        ts = parse_timestamp(entry.get("timestamp"))
        if ts:
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

    session_duration = (last_ts - first_ts) if (first_ts and last_ts) else None

    # --- Agent Performance ---
    dispatched = [e for e in run_log if e.get("event") == "agent_dispatched"]
    returned = [e for e in run_log if e.get("event") == "agent_returned"]
    validations_failed = [e for e in run_log if e.get("event") == "validation_failed"]

    agent_durations = defaultdict(list)
    agent_counts = defaultdict(int)
    agent_successes = defaultdict(int)
    for entry in returned:
        agent_type = entry.get("agent_type", "unknown")
        agent_counts[agent_type] += 1
        if entry.get("success"):
            agent_successes[agent_type] += 1
        dur = entry.get("duration_seconds")
        if dur is not None:
            agent_durations[agent_type].append(dur)

    # --- Search Analysis ---
    search_sources = defaultdict(int)
    queries_with_single_source = 0
    total_new_to_queue = 0
    for query, data in search_log.items():
        sources_hit = 0
        for key in ["pubmed_results", "openalex_results", "biorxiv_results",
                     "crossref_results"]:
            val = data.get(key, 0)
            if val and val > 0:
                sources_hit += 1
                search_sources[key.replace("_results", "")] += val
        if sources_hit <= 1:
            queries_with_single_source += 1
        total_new_to_queue += data.get("new_to_queue", 0)

    # --- Fetch Analysis ---
    # Handle both structured {"browser": {"attempts": N, "successes": N}}
    # and malformed narrative entries from non-compliant Fetchers
    raw_fetch = source_stats.get("fetch_sources", {})
    fetch_sources = {}
    for k, v in raw_fetch.items():
        if isinstance(v, dict) and "attempts" in v and "successes" in v:
            fetch_sources[k] = v
    fetch_total_attempts = sum(v.get("attempts", 0) for v in fetch_sources.values())
    fetch_total_successes = sum(v.get("successes", 0) for v in fetch_sources.values())
    proxy_stats = fetch_sources.get("browser", fetch_sources.get("proxy", {}))

    # --- Extraction Analysis ---
    extraction_events = [e for e in run_log
                         if e.get("event") == "agent_returned"
                         and e.get("agent_type") == "dealer"]
    total_records_extracted = 0
    consensus_types = defaultdict(int)
    no_data_count = 0
    for entry in extraction_events:
        summary = entry.get("result_summary", {})
        outcome = summary.get("outcome", "")
        if outcome == "extracted":
            total_records_extracted += summary.get("records", 0)
        elif outcome == "no_data":
            no_data_count += 1
        ct = summary.get("consensus_type")
        if ct:
            consensus_types[ct] += 1

    # --- Processed.json Analysis ---
    outcome_counts = defaultdict(int)
    for doi, data in processed.items():
        if isinstance(data, dict):
            outcome_counts[data.get("outcome", "unknown")] += 1
        else:
            outcome_counts["malformed_entry"] += 1

    # --- Throughput ---
    papers_extracted = agent_counts.get("dealer", 0)
    duration_hours = session_duration.total_seconds() / 3600 if session_duration else 0
    papers_per_hour = papers_extracted / duration_hours if duration_hours > 0 else 0
    records_per_hour = total_records_extracted / duration_hours if duration_hours > 0 else 0

    # --- Build Report ---
    report = {
        "session": {
            "id": session_id or (session_starts[0].get("session_id") if session_starts else "unknown"),
            "duration_minutes": round(session_duration.total_seconds() / 60, 1) if session_duration else None,
            "start": first_ts.isoformat() if first_ts else None,
            "end": last_ts.isoformat() if last_ts else None,
        },
        "throughput": {
            "papers_processed": papers_extracted,
            "records_extracted": total_records_extracted,
            "records_per_paper": round(total_records_extracted / papers_extracted, 1) if papers_extracted else 0,
            "papers_per_hour": round(papers_per_hour, 1),
            "records_per_hour": round(records_per_hour, 1),
        },
        "search": {
            "queries_completed": len(search_log),
            "papers_queued": total_new_to_queue,
            "queries_single_source": queries_with_single_source,
            "source_contribution": dict(search_sources),
        },
        "fetch": {
            "total_attempts": fetch_total_attempts,
            "total_successes": fetch_total_successes,
            "yield_pct": round(100 * fetch_total_successes / fetch_total_attempts, 1) if fetch_total_attempts else 0,
            "browser_attempts": proxy_stats.get("attempts", 0),
            "browser_successes": proxy_stats.get("successes", 0),
            "leads_total": leads_rows,
            "source_breakdown": {k: v for k, v in fetch_sources.items()},
        },
        "extraction": {
            "papers_with_data": papers_extracted - no_data_count,
            "papers_no_data": no_data_count,
            "total_records": total_records_extracted,
            "consensus_types": dict(consensus_types),
        },
        "agent_performance": {},
        "validation_failures": len(validations_failed),
        "validation_details": [
            {"agent": e.get("agent_type"), "check": e.get("check"),
             "details": e.get("details")}
            for e in validations_failed
        ],
        "outcomes": dict(outcome_counts),
        "database": {
            "results_csv_rows": results_rows,
            "leads_csv_rows": leads_rows,
            "processed_dois": len(processed),
        },
    }

    # Agent duration stats
    for agent_type in ["searcher", "fetcher", "dealer", "writer"]:
        durations = agent_durations.get(agent_type, [])
        total = agent_counts.get(agent_type, 0)
        successes = agent_successes.get(agent_type, 0)
        report["agent_performance"][agent_type] = {
            "calls": total,
            "successes": successes,
            "failure_rate_pct": round(100 * (total - successes) / total, 1) if total else 0,
            "avg_duration_s": round(sum(durations) / len(durations), 1) if durations else None,
            "min_duration_s": round(min(durations), 1) if durations else None,
            "max_duration_s": round(max(durations), 1) if durations else None,
            "total_time_s": round(sum(durations), 1) if durations else None,
        }

    if as_json:
        return report

    # --- Pretty Print ---
    lines = []
    s = report["session"]
    lines.append(f"{'='*60}")
    lines.append(f"  TraitTrawler Session Report")
    lines.append(f"{'='*60}")
    lines.append(f"  Session:   {s['id']}")
    lines.append(f"  Duration:  {s['duration_minutes']} min" if s['duration_minutes'] else "  Duration:  unknown")
    lines.append(f"  Period:    {s['start']} → {s['end']}")
    lines.append("")

    t = report["throughput"]
    lines.append(f"── Throughput ─────────────────────────────────")
    lines.append(f"  Papers processed:    {t['papers_processed']}")
    lines.append(f"  Records extracted:   {t['records_extracted']} ({t['records_per_paper']} per paper)")
    lines.append(f"  Papers/hour:         {t['papers_per_hour']}")
    lines.append(f"  Records/hour:        {t['records_per_hour']}")
    lines.append("")

    sr = report["search"]
    lines.append(f"── Search ─────────────────────────────────────")
    lines.append(f"  Queries completed:   {sr['queries_completed']}")
    lines.append(f"  Papers queued:       {sr['papers_queued']}")
    lines.append(f"  Single-source queries: {sr['queries_single_source']}"
                 + (" ⚠️" if sr['queries_single_source'] > 0 else ""))
    if sr["source_contribution"]:
        lines.append(f"  Source contribution:")
        for src, count in sorted(sr["source_contribution"].items(),
                                  key=lambda x: -x[1]):
            lines.append(f"    {src:12s} {count:>6d} papers")
    lines.append("")

    f = report["fetch"]
    lines.append(f"── Fetch ──────────────────────────────────────")
    lines.append(f"  Attempts:            {f['total_attempts']}")
    lines.append(f"  Successes:           {f['total_successes']} ({f['yield_pct']}%)")
    lines.append(f"  Browser attempts:      {f['browser_attempts']}"
                 + (" ⚠️ BROWSER NOT USED" if f['browser_attempts'] == 0 and f['total_attempts'] > 0 else ""))
    lines.append(f"  Browser successes:     {f['browser_successes']}")
    lines.append(f"  Leads (unfetched):   {f['leads_total']}")
    if f["source_breakdown"]:
        lines.append(f"  Source breakdown:")
        for src, stats in sorted(f["source_breakdown"].items(),
                                  key=lambda x: -x[1].get("successes", 0)):
            att = stats.get("attempts", 0)
            suc = stats.get("successes", 0)
            pct = round(100 * suc / att, 0) if att else 0
            lines.append(f"    {src:18s} {suc:>4d}/{att:<4d} ({pct:.0f}%)")
    lines.append("")

    e = report["extraction"]
    lines.append(f"── Extraction ─────────────────────────────────")
    lines.append(f"  Papers with data:    {e['papers_with_data']}")
    lines.append(f"  Papers no data:      {e['papers_no_data']}")
    lines.append(f"  Total records:       {e['total_records']}")
    if e["consensus_types"]:
        lines.append(f"  Consensus breakdown:")
        for ct, count in sorted(e["consensus_types"].items(), key=lambda x: -x[1]):
            lines.append(f"    {ct:18s} {count:>4d}")
    lines.append("")

    lines.append(f"── Agent Performance ──────────────────────────")
    for agent_type in ["searcher", "fetcher", "dealer", "writer"]:
        ap = report["agent_performance"][agent_type]
        if ap["calls"] == 0:
            continue
        dur_str = f"avg={ap['avg_duration_s']}s" if ap['avg_duration_s'] else "no timing"
        lines.append(f"  {agent_type:10s}  {ap['calls']:>3d} calls  "
                     f"{ap['failure_rate_pct']:>5.1f}% fail  {dur_str}"
                     f"  (min={ap['min_duration_s']}s max={ap['max_duration_s']}s)"
                     if ap['avg_duration_s'] else
                     f"  {agent_type:10s}  {ap['calls']:>3d} calls  "
                     f"{ap['failure_rate_pct']:>5.1f}% fail  {dur_str}")
    lines.append("")

    vf = report["validation_failures"]
    if vf > 0:
        lines.append(f"── Validation Failures ({vf}) ──────────────────")
        for detail in report["validation_details"][:10]:
            lines.append(f"  [{detail['agent']}] {detail['check']}: {detail['details']}")
        lines.append("")

    oc = report["outcomes"]
    if oc:
        lines.append(f"── Outcome Distribution ────────────────────────")
        for outcome, count in sorted(oc.items(), key=lambda x: -x[1]):
            lines.append(f"  {outcome:25s} {count:>5d}")
        lines.append("")

    db = report["database"]
    lines.append(f"── Database ───────────────────────────────────")
    lines.append(f"  results.csv rows:    {db['results_csv_rows']}")
    lines.append(f"  leads.csv rows:      {db['leads_csv_rows']}")
    lines.append(f"  processed DOIs:      {db['processed_dois']}")
    lines.append(f"{'='*60}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="TraitTrawler session performance report"
    )
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--session", default=None,
                        help="Filter to specific session ID")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON instead of formatted text")
    args = parser.parse_args()

    result = generate_report(args.project_root, args.session, args.json)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result)


if __name__ == "__main__":
    main()
