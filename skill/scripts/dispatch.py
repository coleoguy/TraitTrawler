#!/usr/bin/env python3
"""
Agent dispatch tracker for TraitTrawler.

Tracks active agents, computes durations, and logs every dispatch/return
to run_log.jsonl automatically. The Manager calls this instead of manually
tracking timestamps and writing log entries.

Usage:
    # Register a new agent dispatch (returns agent_id, logs to run_log):
    python3 scripts/dispatch.py start --project-root . \
        --session-id 20260328T142904 --agent-type fetcher \
        --payload '{"papers": 5, "mode": "api"}'

    # Mark agent complete (computes duration, logs to run_log):
    python3 scripts/dispatch.py complete --project-root . \
        --agent-id fetcher_001 --success \
        --summary '{"fetched": 3, "leads": 2}'

    # Get pipeline state (active agents + folder counts):
    python3 scripts/dispatch.py status --project-root .

    # Route papers for fetch (classify OA vs paywalled):
    python3 scripts/dispatch.py route-fetch --project-root . \
        --api-batch-size 8 --browser-batch-size 3
"""

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from state_utils import (
    safe_read_json, safe_write_json, append_jsonl, FileLock,
    load_doi_routing, now_iso,
)


# ---------------------------------------------------------------------------
# Dispatch state management
# ---------------------------------------------------------------------------

def _state_path(project_root):
    return os.path.join(project_root, "state", "dispatch_state.json")


def _log_path(project_root):
    return os.path.join(project_root, "state", "run_log.jsonl")


def dispatch_start(project_root, session_id, agent_type, payload=None):
    """Register a new agent dispatch. Returns the agent_id."""
    path = _state_path(project_root)
    with FileLock(path):
        state = safe_read_json(path, default={
            "active_agents": {},
            "session_counts": {},
        })

        # Generate sequential ID
        counts = state.get("session_counts", {})
        n = counts.get(agent_type, 0) + 1
        counts[agent_type] = n
        state["session_counts"] = counts

        agent_id = f"{agent_type}_{n:03d}"
        now = now_iso()

        state.setdefault("active_agents", {})[agent_id] = {
            "type": agent_type,
            "dispatched_at": now,
            "session_id": session_id,
            "payload": payload or {},
        }
        safe_write_json(path, state)

    # Log dispatch event
    append_jsonl(_log_path(project_root), {
        "event": "agent_dispatched",
        "agent_type": agent_type,
        "agent_id": agent_id,
        "session_id": session_id,
        "timestamp": now,
        "payload_summary": payload or {},
    })

    return agent_id


def dispatch_complete(project_root, agent_id, success=True, summary=None):
    """Mark an agent as complete. Computes duration, logs to run_log."""
    path = _state_path(project_root)
    now = now_iso()
    duration = 0
    agent_type = "unknown"
    session_id = ""

    with FileLock(path):
        state = safe_read_json(path, default={"active_agents": {}})
        active = state.get("active_agents", {})

        if agent_id in active:
            entry = active.pop(agent_id)
            agent_type = entry.get("type", "unknown")
            session_id = entry.get("session_id", "")
            dispatched_at = entry.get("dispatched_at", "")
            if dispatched_at:
                try:
                    t0 = datetime.fromisoformat(
                        dispatched_at.replace("Z", "+00:00"))
                    t1 = datetime.now(timezone.utc)
                    duration = int((t1 - t0).total_seconds())
                except (ValueError, TypeError):
                    pass
            state["active_agents"] = active
            safe_write_json(path, state)

    # Log return event
    append_jsonl(_log_path(project_root), {
        "event": "agent_returned",
        "agent_type": agent_type,
        "agent_id": agent_id,
        "session_id": session_id,
        "timestamp": now,
        "duration_seconds": duration,
        "success": success,
        "result_summary": summary or {},
    })

    return {"agent_id": agent_id, "duration_seconds": duration}


def dispatch_status(project_root):
    """Return current pipeline state as a dict."""
    path = _state_path(project_root)
    state = safe_read_json(path, default={"active_agents": {}})
    active = state.get("active_agents", {})

    # Count active agents by type
    type_counts = {}
    for entry in active.values():
        t = entry.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    # Count files in pipeline folders
    def count_files(folder):
        pattern = os.path.join(project_root, folder, "*.json")
        return len(glob.glob(pattern))

    queue_depth = 0
    queue_path = os.path.join(project_root, "state", "queue.json")
    if os.path.exists(queue_path):
        try:
            with open(queue_path) as fh:
                q = json.load(fh)
            queue_depth = len(q) if isinstance(q, list) else 0
        except Exception:
            pass

    # Claimed handoff files (active dealer payloads)
    claimed = {
        entry.get("payload", {}).get("handoff_file", "")
        for entry in active.values()
        if entry.get("type") == "dealer"
    } - {""}

    result = {
        "searcher_active": type_counts.get("searcher", 0) > 0,
        "api_fetcher_active": type_counts.get("api_fetcher", 0) > 0
                              or type_counts.get("fetcher", 0) > 0,
        "browser_fetcher_active": type_counts.get("browser_fetcher", 0) > 0,
        "dealers_active": type_counts.get("dealer", 0),
        "writer_active": type_counts.get("writer", 0) > 0,
        "queue": queue_depth,
        "ready": count_files("ready_for_extraction"),
        "finds": count_files("finds"),
        "fetch_failures": count_files("fetch_failures"),
        "search_results": count_files("search_results"),
        "active_agents": {k: v.get("type") for k, v in active.items()},
        "claimed_handoffs": list(claimed),
        "stale_agents": [
            k for k, v in active.items()
            if _agent_age_minutes(v) > 20
        ],
        "session_counts": state.get("session_counts", {}),
        "manager_checkpoint": state.get("manager_checkpoint", {}),
    }
    return result


def _agent_age_minutes(entry):
    """Compute age of an agent entry in minutes."""
    from datetime import datetime, timezone
    dispatched_at = entry.get("dispatched_at", "")
    if not dispatched_at:
        return 999
    try:
        t0 = datetime.fromisoformat(dispatched_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t0).total_seconds() / 60
    except (ValueError, TypeError):
        return 999


def cleanup_stale(project_root, max_age_minutes=30):
    """Remove stale agent entries older than max_age_minutes."""
    from datetime import datetime, timezone
    path = _state_path(project_root)
    removed = []
    cutoff = datetime.now(timezone.utc)

    with FileLock(path):
        state = safe_read_json(path, default={"active_agents": {}})
        active = state.get("active_agents", {})
        to_remove = []

        for agent_id, entry in active.items():
            dispatched_at = entry.get("dispatched_at", "")
            if not dispatched_at:
                to_remove.append(agent_id)
                continue
            try:
                t0 = datetime.fromisoformat(
                    dispatched_at.replace("Z", "+00:00"))
                age_minutes = (cutoff - t0).total_seconds() / 60
                if age_minutes > max_age_minutes:
                    to_remove.append(agent_id)
            except (ValueError, TypeError):
                to_remove.append(agent_id)

        for agent_id in to_remove:
            entry = active.pop(agent_id)
            removed.append({
                "agent_id": agent_id,
                "type": entry.get("type", "unknown"),
                "dispatched_at": entry.get("dispatched_at", ""),
            })

        if removed:
            state["active_agents"] = active
            safe_write_json(path, state)

    # Log removals
    for r in removed:
        append_jsonl(_log_path(project_root), {
            "event": "stale_agent_removed",
            "agent_id": r["agent_id"],
            "agent_type": r["type"],
            "dispatched_at": r["dispatched_at"],
            "timestamp": now_iso(),
        })

    return {"removed": removed, "count": len(removed)}


def claimed_files(project_root):
    """Return set of handoff filenames currently assigned to active dealers."""
    state = safe_read_json(_state_path(project_root),
                           default={"active_agents": {}})
    return {
        entry.get("payload", {}).get("handoff_file", "")
        for entry in state.get("active_agents", {}).values()
        if entry.get("type") == "dealer"
    } - {""}


def dispatch_checkpoint(project_root, papers_processed,
                        searcher_exhausted, session_target):
    """Save volatile Manager state to dispatch_state.json.

    These values normally live in the Manager's LLM context. Checkpointing
    them lets recommend() recover correct state after context compaction.
    """
    path = _state_path(project_root)
    with FileLock(path):
        state = safe_read_json(path, default={
            "active_agents": {},
            "session_counts": {},
        })
        state["manager_checkpoint"] = {
            "papers_processed": papers_processed,
            "searcher_exhausted": searcher_exhausted,
            "session_target": session_target,
            "updated_at": now_iso(),
        }
        safe_write_json(path, state)


def recommend(project_root, searcher_exhausted=None,
              max_concurrent_dealers=5, session_target=None,
              papers_processed=None):
    """Recommend next dispatch actions based on current pipeline state.

    When papers_processed, searcher_exhausted, or session_target are None
    (not passed), falls back to the last checkpoint values. This makes
    recommend() resilient to Manager context compaction.
    """
    status = dispatch_status(project_root)

    # Load checkpoint fallbacks for values the Manager may have lost
    ckpt = status.get("manager_checkpoint", {})
    if papers_processed is None:
        papers_processed = ckpt.get("papers_processed", 0)
    if searcher_exhausted is None:
        searcher_exhausted = ckpt.get("searcher_exhausted", False)
    if session_target is None:
        session_target = ckpt.get("session_target")

    actions = []

    # Searcher
    if (not status["searcher_active"]
            and not searcher_exhausted):
        actions.append({
            "action": "spawn_searcher",
            "reason": "queries remain and searcher not active",
        })

    # API Fetcher
    if not status["api_fetcher_active"] and status["queue"] > 0:
        actions.append({
            "action": "spawn_api_fetcher",
            "reason": f"queue has {status['queue']} papers",
        })

    # Browser Fetcher
    if (not status["browser_fetcher_active"]
            and (status["queue"] > 0 or status["fetch_failures"] > 0)):
        actions.append({
            "action": "spawn_browser_fetcher",
            "reason": "paywalled papers or fetch failures need browser",
        })

    # Dealers — exclude files already claimed by active dealers
    claimed = claimed_files(project_root)
    ready_files = glob.glob(
        os.path.join(project_root, "ready_for_extraction", "*.json"))
    unclaimed = [os.path.basename(f) for f in ready_files
                 if os.path.basename(f) not in claimed]
    dealer_slots = max_concurrent_dealers - status["dealers_active"]
    if dealer_slots > 0 and unclaimed:
        to_spawn = min(dealer_slots, len(unclaimed))
        actions.append({
            "action": "spawn_dealers",
            "count": to_spawn,
            "handoff_files": unclaimed[:to_spawn],
            "reason": (f"{len(unclaimed)} unclaimed papers ready, "
                       f"{dealer_slots} slots open"),
        })

    # Writer
    if (not status["writer_active"] and status["finds"] > 0
            and (status["dealers_active"] == 0 or status["finds"] >= 3)):
        actions.append({
            "action": "spawn_writer",
            "reason": f"{status['finds']} finds ready",
        })

    # Session end check
    all_exhausted = (
        searcher_exhausted
        and status["queue"] == 0
        and len(unclaimed) == 0
        and status["finds"] == 0
        and not status["searcher_active"]
        and not status["api_fetcher_active"]
        and not status["browser_fetcher_active"]
        and status["dealers_active"] == 0
        and not status["writer_active"]
    )

    # Target reached
    target_reached = (session_target is not None
                      and papers_processed >= int(session_target))

    return {
        "actions": actions,
        "session_complete": all_exhausted or target_reached,
        "reason": ("all streams exhausted" if all_exhausted
                   else "target reached" if target_reached
                   else "work remaining"),
        "status": status,
    }


def route_fetch(project_root, api_batch_size=8, browser_batch_size=3):
    """Classify queued papers into API and browser fetch batches."""
    oa_prefixes, pw_prefixes = load_doi_routing(project_root)

    queue_path = os.path.join(project_root, "state", "queue.json")
    queue = safe_read_json(queue_path, default=[])

    api_batch = []
    browser_batch = []

    for paper in queue:
        if len(api_batch) >= api_batch_size and len(browser_batch) >= browser_batch_size:
            break

        doi = paper.get("doi", "")
        is_paywalled = any(doi.startswith(p) for p in pw_prefixes)
        is_oa = any(doi.startswith(p) for p in oa_prefixes)

        if is_paywalled and len(browser_batch) < browser_batch_size:
            browser_batch.append(paper)
        elif is_oa and len(api_batch) < api_batch_size:
            api_batch.append(paper)
        elif len(api_batch) < api_batch_size:
            api_batch.append(paper)
        elif len(browser_batch) < browser_batch_size:
            browser_batch.append(paper)

    return {
        "api_batch": api_batch,
        "browser_batch": browser_batch,
        "queue_remaining": len(queue) - len(api_batch) - len(browser_batch),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TraitTrawler agent dispatch tracker"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Register an agent dispatch")
    p_start.add_argument("--project-root", default=".")
    p_start.add_argument("--session-id", required=True)
    p_start.add_argument("--agent-type", required=True)
    p_start.add_argument("--payload", default="{}", help="JSON payload summary")

    # complete
    p_complete = sub.add_parser("complete", help="Mark an agent as complete")
    p_complete.add_argument("--project-root", default=".")
    p_complete.add_argument("--agent-id", required=True)
    p_complete.add_argument("--success", action="store_true", default=True)
    p_complete.add_argument("--failed", action="store_true")
    p_complete.add_argument("--summary", default="{}", help="JSON result summary")

    # status
    p_status = sub.add_parser("status", help="Get pipeline state")
    p_status.add_argument("--project-root", default=".")

    # route-fetch
    p_route = sub.add_parser("route-fetch", help="Classify papers for fetch")
    p_route.add_argument("--project-root", default=".")
    p_route.add_argument("--api-batch-size", type=int, default=8)
    p_route.add_argument("--browser-batch-size", type=int, default=3)

    # recommend
    p_rec = sub.add_parser("recommend", help="Recommend next dispatch actions")
    p_rec.add_argument("--project-root", default=".")
    p_rec.add_argument("--searcher-exhausted", action="store_true",
                       default=None)
    p_rec.add_argument("--max-concurrent-dealers", type=int, default=5)
    p_rec.add_argument("--session-target", default=None)
    p_rec.add_argument("--papers-processed", type=int, default=None)

    # checkpoint
    p_ckpt = sub.add_parser("checkpoint",
                            help="Save volatile Manager state")
    p_ckpt.add_argument("--project-root", default=".")
    p_ckpt.add_argument("--papers-processed", type=int, required=True)
    p_ckpt.add_argument("--searcher-exhausted", action="store_true")
    p_ckpt.add_argument("--session-target", default=None)

    # cleanup-stale
    p_cleanup = sub.add_parser("cleanup-stale",
                               help="Remove stale agent entries")
    p_cleanup.add_argument("--project-root", default=".")
    p_cleanup.add_argument("--max-age-minutes", type=int, default=30)

    args = parser.parse_args()

    if args.command == "start":
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {"raw": args.payload}
        agent_id = dispatch_start(
            args.project_root, args.session_id,
            args.agent_type, payload
        )
        # Print just the agent_id so Manager can capture it with $()
        print(agent_id)

    elif args.command == "complete":
        success = not args.failed
        try:
            summary = json.loads(args.summary)
        except json.JSONDecodeError:
            summary = {"raw": args.summary}
        result = dispatch_complete(
            args.project_root, args.agent_id, success, summary
        )
        print(json.dumps(result))

    elif args.command == "status":
        result = dispatch_status(args.project_root)
        print(json.dumps(result, indent=2))

    elif args.command == "route-fetch":
        result = route_fetch(
            args.project_root,
            args.api_batch_size,
            args.browser_batch_size,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "recommend":
        # None means "use checkpoint fallback" — only pass explicit values
        se = args.searcher_exhausted if args.searcher_exhausted else None
        result = recommend(
            args.project_root,
            searcher_exhausted=se,
            max_concurrent_dealers=args.max_concurrent_dealers,
            session_target=args.session_target,
            papers_processed=args.papers_processed,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "checkpoint":
        dispatch_checkpoint(
            args.project_root,
            papers_processed=args.papers_processed,
            searcher_exhausted=args.searcher_exhausted,
            session_target=args.session_target,
        )
        print(json.dumps({"status": "ok"}))

    elif args.command == "cleanup-stale":
        result = cleanup_stale(
            args.project_root,
            args.max_age_minutes,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
