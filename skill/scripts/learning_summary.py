#!/usr/bin/env python3
"""
Learning and knowledge evolution summary for TraitTrawler.

Reads run_log.jsonl, discoveries.jsonl, learning/ files, and guide.md
history to produce a summary of what the system has learned across sessions.

Usage:
    python3 scripts/learning_summary.py --project-root /path/to/project
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


def read_jsonl(path):
    """Read a JSONL file, returning list of dicts."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def read_json_dir(dirpath):
    """Read all JSON files in a directory."""
    entries = []
    if not os.path.exists(dirpath):
        return entries
    for f in sorted(Path(dirpath).glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                data["_source_file"] = f.name
                entries.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return entries


def summarize_sessions(run_log):
    """Summarize session activity from run_log.jsonl."""
    sessions = defaultdict(lambda: {
        "start": None, "end": None, "agents_dispatched": 0,
        "agents_returned": 0, "papers_processed": 0,
        "events": Counter()
    })

    for entry in run_log:
        event = entry.get("event", "")
        sid = entry.get("session_id", "unknown")
        ts = entry.get("timestamp", "")

        sessions[sid]["events"][event] += 1

        if event == "session_start":
            sessions[sid]["start"] = ts
        elif event == "session_end":
            sessions[sid]["end"] = ts
        elif event == "agent_dispatched":
            sessions[sid]["agents_dispatched"] += 1
        elif event == "agent_returned":
            sessions[sid]["agents_returned"] += 1
            # Count papers from dealer returns
            agent_type = entry.get("agent_type", "")
            if agent_type == "dealer":
                sessions[sid]["papers_processed"] += 1
        elif event in ("guide_updated", "mid_session_correction",
                       "discovery_applied"):
            sessions[sid]["events"][event] += 1

    return dict(sessions)


def summarize_discoveries(discoveries):
    """Summarize discovery types and outcomes."""
    types = Counter()
    applied = 0
    rejected = 0
    pending = 0

    for d in discoveries:
        types[d.get("type", "unknown")] += 1
        status = d.get("applied")
        if status is True:
            applied += 1
        elif status is False:
            rejected += 1
        else:
            pending += 1

    return {
        "total": len(discoveries),
        "by_type": dict(types),
        "applied": applied,
        "rejected": rejected,
        "pending": pending,
    }


def check_guide_growth(project_root):
    """Check guide.md for signs of evolution."""
    guide_path = os.path.join(project_root, "guide.md")
    if not os.path.exists(guide_path):
        return {"exists": False}

    with open(guide_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    sections = [ln for ln in lines if ln.startswith("## ")]

    return {
        "exists": True,
        "lines": len(lines),
        "sections": len(sections),
        "section_names": [s.strip("# ").strip() for s in sections],
        "has_triage_optimization": "triage" in content.lower()
                                  and "optimization" in content.lower(),
        "has_learned_patterns": any(w in content.lower() for w in
                                    ["learned from", "high-yield",
                                     "low-yield", "pipeline efficiency"]),
    }


def generate_summary(project_root):
    """Generate complete learning summary."""
    root = Path(project_root).resolve()

    # Read data sources
    run_log = read_jsonl(root / "state" / "run_log.jsonl")
    discoveries = read_jsonl(root / "state" / "discoveries.jsonl")
    learning_files = read_json_dir(root / "learning")

    # Summarize
    sessions = summarize_sessions(run_log)
    discovery_summary = summarize_discoveries(discoveries)
    guide_info = check_guide_growth(project_root)

    # Count agent types dispatched across all sessions
    agent_types = Counter()
    for entry in run_log:
        if entry.get("event") == "agent_dispatched":
            agent_types[entry.get("agent_type", "unknown")] += 1

    # Knowledge events
    knowledge_events = [e for e in run_log
                        if e.get("event") in ("guide_updated",
                                               "mid_session_correction",
                                               "discovery_applied",
                                               "discovery_rejected")]

    # Print report
    print("=" * 60)
    print("TRAITTRAWLER LEARNING & KNOWLEDGE SUMMARY")
    print("=" * 60)
    print(f"Project: {root}")
    print(f"Run log entries: {len(run_log)}")
    print(f"Sessions: {len(sessions)}")
    print()

    # Session overview
    print("SESSION HISTORY")
    print("-" * 40)
    for sid in sorted(sessions.keys()):
        s = sessions[sid]
        agents = s["agents_dispatched"]
        papers = s["papers_processed"]
        events = dict(s["events"])
        print(f"  {sid}: {agents} agents, {papers} papers extracted")
        knowledge = {k: v for k, v in events.items()
                     if k in ("guide_updated", "mid_session_correction",
                              "discovery_applied")}
        if knowledge:
            print(f"    Knowledge events: {knowledge}")
    print()

    # Agent activity
    print("AGENT DISPATCH TOTALS")
    print("-" * 40)
    for agent_type, count in agent_types.most_common():
        print(f"  {agent_type}: {count}")
    print()

    # Discovery tracking
    print("DISCOVERY TRACKING")
    print("-" * 40)
    print(f"  Learning files (learning/): {len(learning_files)}")
    print(f"  Archived discoveries: {discovery_summary['total']}")
    if discovery_summary["total"] > 0:
        print(f"    Applied: {discovery_summary['applied']}")
        print(f"    Rejected: {discovery_summary['rejected']}")
        print(f"    Pending: {discovery_summary['pending']}")
        print(f"    By type: {discovery_summary['by_type']}")
    print(f"  Knowledge events in run log: {len(knowledge_events)}")
    if not learning_files and not discoveries and not knowledge_events:
        print("  ** NO LEARNING ACTIVITY DETECTED **")
        print("  The learning pipeline (extractor → reviewer → guide.md)")
        print("  has not produced any discoveries. This is normal for")
        print("  early sessions or well-understood traits.")
    print()

    # Guide evolution
    print("GUIDE.MD STATUS")
    print("-" * 40)
    if guide_info["exists"]:
        print(f"  Lines: {guide_info['lines']}")
        print(f"  Sections: {guide_info['sections']}")
        for s in guide_info["section_names"]:
            print(f"    - {s}")
        if guide_info["has_triage_optimization"]:
            print("  [+] Has triage optimization (learned patterns)")
        if guide_info["has_learned_patterns"]:
            print("  [+] Contains learned extraction patterns")
    else:
        print("  guide.md not found")
    print()

    # Recommendations
    print("RECOMMENDATIONS")
    print("-" * 40)
    if not learning_files:
        print("  - Extractors are not writing discovery files to learning/")
        print("    This means mid-session learning injection is inactive.")
    if not knowledge_events:
        print("  - No guide.md amendments have been logged.")
        print("    The Reviewer agent may not be getting spawned at session end.")
    if discovery_summary["pending"] > 0:
        print(f"  - {discovery_summary['pending']} discoveries pending review")

    return {
        "sessions": len(sessions),
        "run_log_entries": len(run_log),
        "learning_files": len(learning_files),
        "discoveries": discovery_summary,
        "knowledge_events": len(knowledge_events),
        "guide": guide_info,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Learning and knowledge evolution summary"
    )
    parser.add_argument("--project-root", required=True,
                        help="Path to project root")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON instead of text")
    args = parser.parse_args()

    result = generate_summary(args.project_root)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
