#!/usr/bin/env python3
"""
Session lifecycle manager for TraitTrawler.

Consolidates all startup and teardown logic into a single CLI. The Manager
calls this instead of executing dozens of inline code blocks.

Usage:
    # Start a session (all startup tasks):
    python3 scripts/session_manager.py start \
        --project-root . \
        --skill-dir /path/to/skill \
        --session-id 20260328T142904 \
        --target 20 --extractors 5

    # End a session (all teardown tasks):
    python3 scripts/session_manager.py end \
        --project-root . \
        --session-id 20260328T142904 \
        --papers-processed 20 --records-written 147
"""

import argparse
import ast
import csv
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from state_utils import (
    safe_read_json, safe_write_json, append_jsonl, check_state_integrity,
    load_doi_routing, now_iso,
)


SKILL_VERSION = "4.4.0"

# Changelog: brief notes per version so the Manager (an LLM) understands
# what changed when upgrading an existing project. Keyed by version string.
# Only include entries that affect Manager behavior or project state.
CHANGELOG = {
    "4.4.0": [
        "Dedup guard: dispatch.py now skips papers whose DOI is already in "
        "processed.json or results.csv — prevents re-extraction of known papers.",
        "Compact logging: dispatch blocks are 1-line, return blocks are 1-line, "
        "throughput every 10 papers (3 lines). Do NOT print verbose blocks.",
        "Auto-normalization: process_agent_output.py auto-fixes paper_authors "
        "(list→string), confidence (word→float), source_page (int→string) in "
        "finds/ before the Writer sees them.",
        "source_page is now soft-required in finds validation — missing values "
        "produce a warning, not a rejection.",
        "Manager boundary hardened: MUST NOT search, extract, fetch, create "
        "hybrid agents, or manually fix agent output. See 'When the Pipeline "
        "Stalls' section in SKILL.md.",
        "Triage: config-driven exclusion keywords (triage_exclude_keywords in "
        "collector_config.yaml). 30% false positive target.",
        "Queue re-triage: run 'dispatch.py retriage' to re-evaluate stale "
        "queue entries against current triage rules and guide.md.",
        "PDF storage: PDFs now saved to source/ with standardized names "
        "(Lastname-Year-Word-index.pdf). pdf_path column added to CSV. "
        "Add 'pdf_path' to output_fields in collector_config.yaml if not "
        "already present.",
    ],
}


# ---------------------------------------------------------------------------
# Startup tasks
# ---------------------------------------------------------------------------

def ensure_dependencies():
    """Check and install required Python packages."""
    deps = [
        ("pdfplumber", "pdfplumber"),
        ("yaml", "pyyaml"),
        ("scipy", "scipy matplotlib"),
        ("sklearn", "scikit-learn"),
    ]
    installed = []
    for module, package in deps:
        try:
            __import__(module)
        except ImportError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install"]
                + package.split()
                + ["--break-system-packages", "-q"],
                capture_output=True,
            )
            installed.append(package)
    return installed


def copy_utility_scripts(project_root, skill_dir):
    """Copy/update utility scripts from skill directory.

    Always overwrites existing scripts so that upgraded skill versions
    deploy their fixes. Scripts are deterministic utilities — user
    customizations belong in collector_config.yaml and guide.md, not
    in the scripts themselves.
    """
    if not skill_dir:
        return 0

    copied = 0
    skipped = 0

    def _safe_copy(src, dest):
        """Copy file, handling sandbox/read-only filesystem gracefully."""
        nonlocal copied, skipped
        try:
            shutil.copy2(src, dest)
            copied += 1
        except (OSError, PermissionError):
            # Sandbox won't allow overwrite — file from prior session is fine
            if os.path.exists(dest):
                skipped += 1
            else:
                print(f"WARNING: Cannot copy {src} to {dest}",
                      file=sys.stderr)

    # Root-level scripts
    for script in ["dashboard_generator.py", "verify_session.py",
                    "export_dwc.py"]:
        dest = os.path.join(project_root, script)
        src = os.path.join(skill_dir, script)
        if os.path.exists(src):
            _safe_copy(src, dest)

    # scripts/ directory
    scripts_dir = os.path.join(project_root, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    skill_scripts = os.path.join(skill_dir, "scripts")
    if os.path.isdir(skill_scripts):
        for script in os.listdir(skill_scripts):
            if script.endswith(".py"):
                dest = os.path.join(scripts_dir, script)
                src = os.path.join(skill_scripts, script)
                _safe_copy(src, dest)

    # .claude/hooks/ — copy from repo if available
    repo_hooks = os.path.join(os.path.dirname(skill_dir), ".claude", "hooks")
    if os.path.isdir(repo_hooks):
        proj_hooks = os.path.join(project_root, ".claude", "hooks")
        os.makedirs(proj_hooks, exist_ok=True)
        for hook in os.listdir(repo_hooks):
            if hook.endswith(".sh"):
                src = os.path.join(repo_hooks, hook)
                dest = os.path.join(proj_hooks, hook)
                _safe_copy(src, dest)
                try:
                    os.chmod(dest, 0o755)
                except (OSError, PermissionError):
                    pass

    # .claude/settings.json — copy if not present (don't overwrite user edits)
    repo_settings = os.path.join(os.path.dirname(skill_dir), ".claude",
                                 "settings.json")
    if os.path.exists(repo_settings):
        proj_settings = os.path.join(project_root, ".claude", "settings.json")
        os.makedirs(os.path.dirname(proj_settings), exist_ok=True)
        if not os.path.exists(proj_settings):
            _safe_copy(repo_settings, proj_settings)

    if skipped:
        print(f"Note: {skipped} file(s) already exist and could not be "
              f"overwritten (sandbox filesystem)", file=sys.stderr)
    return copied


def hash_pdf(path):
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_provided_pdf_hash(project_root, pdf_path):
    """Return True if this PDF's content hash is already registered."""
    registry_path = os.path.join(project_root, "state", "processed_pdfs.json")
    registry = safe_read_json(registry_path, default={})
    digest = hash_pdf(pdf_path)
    return digest in registry


def register_provided_pdf(project_root, pdf_path, session_id):
    """Record a provided PDF's content hash so it won't be re-processed."""
    registry_path = os.path.join(project_root, "state", "processed_pdfs.json")
    registry = safe_read_json(registry_path, default={})
    digest = hash_pdf(pdf_path)
    registry[digest] = {
        "filename": os.path.basename(pdf_path),
        "session_id": session_id,
        "processed_at": now_iso(),
    }
    safe_write_json(registry_path, registry)


def ensure_directories(project_root):
    """Create all required project directories."""
    dirs = [
        "state/extraction_traces", "state/snapshots", "state/dealt",
        "state/session_reports",
        "backups",
        "finds", "ready_for_extraction", "search_results",
        "fetch_failures", "extractor_results", "writer_results", "lead_files",
        "learning", "provided_pdfs", "provided_pdfs/done",
    ]
    for d in dirs:
        os.makedirs(os.path.join(project_root, d), exist_ok=True)


def backup_state(project_root, session_id):
    """Create timestamped backups of critical state files.

    Two backup locations:
    - state/snapshots/ — rolling window of 10 (for quick recovery)
    - backups/ — permanent archive of results.csv at each session start
    """
    snapshots = os.path.join(project_root, "state", "snapshots")
    os.makedirs(snapshots, exist_ok=True)

    ts = session_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    backed_up = []

    for filename in ["results.csv", "state/processed.json"]:
        src = os.path.join(project_root, filename)
        if os.path.exists(src):
            base = os.path.basename(filename).replace(".", f"_{ts}.")
            dst = os.path.join(snapshots, base)
            shutil.copy2(src, dst)
            backed_up.append(filename)

    # Prune old snapshots — keep 10 most recent
    all_snaps = sorted(glob.glob(os.path.join(snapshots, "*")),
                       key=os.path.getmtime, reverse=True)
    for old in all_snaps[10:]:
        try:
            os.remove(old)
        except OSError:
            pass

    # Permanent backup of results.csv in backups/ (never pruned)
    backup_dir = os.path.join(project_root, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    results_src = os.path.join(project_root, "results.csv")
    if os.path.exists(results_src):
        backup_dst = os.path.join(backup_dir, f"results_{ts}.csv")
        shutil.copy2(results_src, backup_dst)
        backed_up.append(f"backups/results_{ts}.csv")

    return backed_up


def sync_processed_json(project_root):
    """Backfill processed.json with DOIs from results.csv."""
    csv_path = os.path.join(project_root, "results.csv")
    proc_path = os.path.join(project_root, "state", "processed.json")

    if not os.path.exists(csv_path):
        return 0

    doi_counts = Counter()
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            doi = (row.get("doi") or "").strip()
            if doi:
                doi_counts[doi] += 1

    proc = safe_read_json(proc_path, default={})
    added = 0
    now = now_iso()

    for doi, count in doi_counts.items():
        if doi not in proc:
            proc[doi] = {
                "outcome": "imported",
                "records": count,
                "date": now,
                "session_id": "backfill",
                "source": "csv_sync",
            }
            added += 1

    if added:
        safe_write_json(proc_path, proc)

    return added


def ensure_standard_fields(project_root):
    """Ensure standard fields like pdf_path are in collector_config.yaml.

    Called during startup to inject fields the skill requires but the user
    may not have added manually. Only adds fields that are genuinely
    missing — never reorders or removes existing fields.

    Returns list of field names added (empty if none needed).
    """
    config_path = os.path.join(project_root, "collector_config.yaml")
    if not os.path.exists(config_path):
        return []

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except (ImportError, Exception):
        return []

    fields = config.get("output_fields", [])
    if not fields:
        return []

    # Standard fields that must exist in every project
    required_standard = ["pdf_path"]
    added = []
    for field in required_standard:
        if field not in fields:
            # Insert pdf_path after pdf_source if it exists, else append
            if field == "pdf_path" and "pdf_source" in fields:
                idx = fields.index("pdf_source") + 1
                fields.insert(idx, field)
            else:
                fields.append(field)
            added.append(field)

    if added:
        config["output_fields"] = fields
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False,
                          sort_keys=False, allow_unicode=True)
        except Exception:
            return []

    return added


def validate_output_fields(project_root):
    """Validate that output_fields in collector_config.yaml is well-formed.

    Checks:
    1. output_fields exists and is non-empty
    2. All required_fields are present in output_fields
    3. Core provenance fields (species, doi, extraction_confidence, pdf_path)
       are present
    4. No duplicate field names
    5. If results.csv exists, its columns match output_fields (warns on drift)

    Returns dict with:
        ok: bool - all checks passed
        warnings: list of str - non-fatal issues
        errors: list of str - fatal issues that should block startup
    """
    config_path = os.path.join(project_root, "collector_config.yaml")
    result = {"ok": True, "warnings": [], "errors": []}

    if not os.path.exists(config_path):
        result["warnings"].append("No collector_config.yaml found")
        return result

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except (ImportError, Exception) as e:
        result["errors"].append(f"Cannot parse collector_config.yaml: {e}")
        result["ok"] = False
        return result

    output_fields = config.get("output_fields", [])
    if not output_fields:
        result["errors"].append(
            "output_fields is empty or missing in collector_config.yaml")
        result["ok"] = False
        return result

    # Check for duplicates
    seen = set()
    duplicates = []
    for field in output_fields:
        if field in seen:
            duplicates.append(field)
        seen.add(field)
    if duplicates:
        result["warnings"].append(
            f"Duplicate fields in output_fields: {duplicates}")

    # Check required_fields are in output_fields
    required = config.get("required_fields", [])
    for field in required:
        if field not in output_fields:
            result["errors"].append(
                f"Required field '{field}' is in required_fields but "
                f"missing from output_fields — records will fail validation")
            result["ok"] = False

    # Check core provenance fields are present
    core_fields = ["species", "doi", "extraction_confidence", "pdf_path",
                   "paper_title", "paper_year"]
    missing_core = [f for f in core_fields if f not in output_fields]
    if missing_core:
        result["warnings"].append(
            f"Recommended core fields missing from output_fields: "
            f"{missing_core}")

    # Check results.csv column consistency
    csv_path = os.path.join(project_root, "results.csv")
    if os.path.exists(csv_path):
        try:
            import csv
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                csv_header = next(reader, [])
            if csv_header:
                config_set = set(output_fields)
                csv_set = set(csv_header)
                in_csv_not_config = csv_set - config_set
                in_config_not_csv = config_set - csv_set
                if in_csv_not_config:
                    result["warnings"].append(
                        f"Columns in results.csv but not in output_fields: "
                        f"{sorted(in_csv_not_config)}")
                if in_config_not_csv:
                    result["warnings"].append(
                        f"Fields in output_fields but not in results.csv "
                        f"(will be added): {sorted(in_config_not_csv)}")
        except Exception:
            pass

    return result


def migrate_csv_columns(project_root):
    """Add missing columns from collector_config.yaml to results.csv.

    When a skill upgrade adds new output_fields, existing results.csv files
    won't have those columns. This reads the current header, compares it to
    the config, and rewrites the header + all rows with the new columns
    appended (empty for existing rows).

    Returns list of column names added (empty if none needed).
    """
    csv_path = os.path.join(project_root, "results.csv")
    config_path = os.path.join(project_root, "collector_config.yaml")

    if not os.path.exists(csv_path) or not os.path.exists(config_path):
        return []

    # Load configured output_fields
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        config_fields = config.get("output_fields", [])
    except (ImportError, Exception):
        return []

    if not config_fields:
        return []

    # Read existing CSV header
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_fields = list(reader.fieldnames) if reader.fieldnames else []

    if not existing_fields:
        return []

    # Find new columns (preserve order: existing first, then new)
    existing_set = set(existing_fields)
    new_columns = [f for f in config_fields if f not in existing_set]

    if not new_columns:
        return []

    # Rewrite CSV with new columns appended
    merged_fields = existing_fields + new_columns
    tmp_path = csv_path + ".migration.tmp"

    with open(csv_path, "r", encoding="utf-8") as fin, \
         open(tmp_path, "w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=merged_fields,
                                extrasaction="ignore")
        writer.writeheader()
        for row in reader:
            writer.writerow(row)

    os.replace(tmp_path, csv_path)
    return new_columns


def stamp_skill_version(project_root):
    """Write current skill version into collector_config.yaml.

    Allows future sessions to detect which version created or last
    touched the project. Only updates if the version has changed.

    Returns the previous version (or None if not set).
    """
    config_path = os.path.join(project_root, "collector_config.yaml")
    if not os.path.exists(config_path):
        return None

    try:
        import yaml
    except ImportError:
        return None

    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
        config = yaml.safe_load(raw) or {}

    previous = config.get("skill_version")
    current = SKILL_VERSION

    if previous == current:
        return previous

    config["skill_version"] = current

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True)

    return previous


def detect_stuck_handoffs(project_root, threshold_hours=2.0):
    """Find handoff files older than threshold."""
    stuck = []
    now = time.time()
    for folder in ["finds", "ready_for_extraction"]:
        folder_path = os.path.join(project_root, folder)
        if not os.path.isdir(folder_path):
            continue
        for f in os.listdir(folder_path):
            filepath = os.path.join(folder_path, f)
            if os.path.isfile(filepath):
                age_hours = (now - os.path.getmtime(filepath)) / 3600
                if age_hours > threshold_hours:
                    stuck.append({
                        "folder": folder,
                        "file": f,
                        "age_hours": round(age_hours, 1),
                    })
    return stuck


def prioritize_queue(project_root):
    """Sort queue by OA likelihood — OA papers first, paywalled last."""
    queue_path = os.path.join(project_root, "state", "queue.json")
    queue = safe_read_json(queue_path, default=[])
    if not queue:
        return {"oa_likely": 0, "unknown": 0, "paywalled": 0, "total": 0}

    oa_prefixes, pw_prefixes = load_doi_routing(project_root)

    def priority(paper):
        doi = paper.get("doi", "")
        if any(doi.startswith(p) for p in oa_prefixes):
            return 0
        if any(doi.startswith(p) for p in pw_prefixes):
            return 2
        return 1

    queue.sort(key=priority)
    safe_write_json(queue_path, queue)

    counts = Counter(priority(p) for p in queue)
    return {
        "oa_likely": counts.get(0, 0),
        "unknown": counts.get(1, 0),
        "paywalled": counts.get(2, 0),
        "total": len(queue),
    }


def prune_learning(project_root, max_files=20):
    """Keep the most recent learning files, archive older ones."""
    learning_dir = os.path.join(project_root, "learning")
    if not os.path.isdir(learning_dir):
        return 0

    files = sorted(glob.glob(os.path.join(learning_dir, "*.json")),
                   key=os.path.getmtime, reverse=True)

    if len(files) <= max_files:
        return 0

    archive_dir = os.path.join(project_root, "state", "learning_archive")
    os.makedirs(archive_dir, exist_ok=True)

    archived = 0
    for old_file in files[max_files:]:
        try:
            dest = os.path.join(archive_dir, os.path.basename(old_file))
            shutil.move(old_file, dest)
            archived += 1
        except OSError:
            pass
    return archived


def read_project_state(project_root):
    """Read lightweight project state summary (no large files in memory)."""
    state = {}

    # Record count
    csv_path = os.path.join(project_root, "results.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r") as f:
            state["records"] = sum(1 for _ in f) - 1
    else:
        state["records"] = 0

    # Leads count
    leads_path = os.path.join(project_root, "leads.csv")
    if os.path.exists(leads_path):
        with open(leads_path, "r") as f:
            state["leads"] = max(0, sum(1 for _ in f) - 1)
    else:
        state["leads"] = 0

    # Processed papers
    proc_path = os.path.join(project_root, "state", "processed.json")
    proc = safe_read_json(proc_path, default={})
    state["papers_processed"] = len(proc)

    # Queue depth
    queue_path = os.path.join(project_root, "state", "queue.json")
    queue = safe_read_json(queue_path, default=[])
    state["queue_depth"] = len(queue)

    # Queries completed
    slog_path = os.path.join(project_root, "state", "search_log.json")
    slog = safe_read_json(slog_path, default={})
    state["queries_completed"] = len(slog)

    # Queries remaining (needs config.py)
    try:
        config_path = os.path.join(project_root, "config.py")
        if os.path.exists(config_path):
            with open(config_path) as fh:
                source = fh.read()
            tree = ast.parse(source)
            total_queries = 0
            for node in ast.walk(tree):
                if (isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "SEARCH_TERMS"
                                for t in node.targets)):
                    total_queries = len(ast.literal_eval(node.value))
                    break
            state["queries_remaining"] = max(
                0, total_queries - state["queries_completed"])
            state["queries_total"] = total_queries
        else:
            state["queries_remaining"] = -1
            state["queries_total"] = -1
    except Exception:
        state["queries_remaining"] = -1
        state["queries_total"] = -1

    # Pending discoveries
    disc_path = os.path.join(project_root, "state", "discoveries.jsonl")
    if os.path.exists(disc_path):
        with open(disc_path) as f:
            state["pending_discoveries"] = sum(1 for line in f if line.strip())
    else:
        state["pending_discoveries"] = 0

    # File hashes for change tracking
    for name in ["guide.md", "config.py"]:
        fpath = os.path.join(project_root, name)
        if os.path.exists(fpath):
            with open(fpath, "rb") as fh:
                h = hashlib.md5(fh.read()).hexdigest()[:8]
            state[f"{name.replace('.', '_')}_md5"] = h

    # Pipeline folder counts
    for folder in ["finds", "ready_for_extraction", "search_results",
                    "fetch_failures", "extractor_results", "provided_pdfs"]:
        pattern = os.path.join(project_root, folder, "*")
        state[f"{folder}_pending"] = len(glob.glob(pattern))

    return state


def write_snapshot(project_root, session_id, mode, target, extractors,
                   guide_md5, config_md5):
    """Write reproducibility snapshot."""
    snapshot_dir = os.path.join(project_root, "state", "snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)
    snapshot = {
        "session_id": session_id,
        "guide_md5": guide_md5,
        "config_py_md5": config_md5,
        "skill_version": SKILL_VERSION,
        "extraction_mode": mode,
        "max_concurrent_extractors": extractors,
        "target": target,
        "started_at": now_iso(),
    }
    path = os.path.join(snapshot_dir, f"{session_id}.json")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)


# ---------------------------------------------------------------------------
# Teardown tasks
# ---------------------------------------------------------------------------

def run_teardown_scripts(project_root, session_id):
    """Run all session-end scripts and collect their output."""
    results = {}

    scripts = [
        ("verify", ["python3", "verify_session.py", "--project-root", "."]),
        ("qc", ["python3", "scripts/statistical_qc.py", "--project-root", "."]),
        ("calibration", ["python3", "scripts/calibration.py",
                         "--project-root", "."]),
        ("session_report", ["python3", "scripts/session_report.py",
                            "--project-root", ".",
                            "--session", session_id, "--json"]),
        ("dashboard", ["python3", "dashboard_generator.py",
                       "--project-root", "."]),
    ]

    for name, cmd in scripts:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, cwd=project_root,
                timeout=120,
            )
            output = r.stdout.strip()
            try:
                results[name] = json.loads(output)
            except (json.JSONDecodeError, ValueError):
                results[name] = {"output": output[:500],
                                 "returncode": r.returncode}
            if r.returncode != 0 and r.stderr:
                results[name]["stderr"] = r.stderr[:300]
        except FileNotFoundError:
            results[name] = {"skipped": True, "reason": "script not found"}
        except subprocess.TimeoutExpired:
            results[name] = {"skipped": True, "reason": "timeout"}

    return results


def compute_query_yield(project_root):
    """Compute per-query extraction yield for session summary."""
    proc_path = os.path.join(project_root, "state", "processed.json")
    proc = safe_read_json(proc_path, default={})

    query_yield = defaultdict(
        lambda: {"papers": 0, "extracted": 0, "records": 0, "no_data": 0})

    for doi, p in proc.items():
        if not isinstance(p, dict):
            continue
        q = p.get("source_query", "unknown")
        query_yield[q]["papers"] += 1
        if p.get("outcome") in ("extracted", "imported"):
            query_yield[q]["extracted"] += 1
            query_yield[q]["records"] += p.get("records", 0)
        elif p.get("outcome") == "no_data":
            query_yield[q]["no_data"] += 1

    # Top 10 by records, bottom 10 by yield rate
    by_records = sorted(
        query_yield.items(),
        key=lambda x: x[1]["records"], reverse=True,
    )[:10]
    by_waste = sorted(
        [(q, v) for q, v in query_yield.items() if v["papers"] >= 3],
        key=lambda x: x[1]["extracted"] / max(x[1]["papers"], 1),
    )[:10]

    return {
        "top_queries": [
            {"query": q, **v} for q, v in by_records
        ],
        "lowest_yield": [
            {"query": q, "yield_pct": round(
                v["extracted"] / max(v["papers"], 1) * 100), **v}
            for q, v in by_waste
        ],
    }


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------

def cmd_start(args):
    """Execute all session startup tasks."""
    root = args.project_root
    result = {"session_id": args.session_id}

    # Idempotency guard: if this session was already started, return
    # current state without re-clearing dispatch tracking or re-logging.
    snapshot_path = os.path.join(
        root, "state", "snapshots", f"{args.session_id}.json")
    if os.path.exists(snapshot_path) and not getattr(args, "force", False):
        state = read_project_state(root)
        result["already_started"] = True
        result.update(state)
        print(json.dumps(result, indent=2))
        return

    # 1. Dependencies
    installed = ensure_dependencies()
    if installed:
        result["dependencies_installed"] = installed

    # 2. Copy scripts
    copied = copy_utility_scripts(root, args.skill_dir)
    result["scripts_copied"] = copied

    # 3. Ensure directories
    ensure_directories(root)

    # 4. Backup
    backed_up = backup_state(root, args.session_id)
    result["backed_up"] = backed_up

    # 5. Integrity check
    integrity = check_state_integrity(root)
    result["integrity"] = "OK" if integrity["ok"] else integrity["issues"]

    # 6. Sync processed.json
    backfilled = sync_processed_json(root)
    result["backfilled_dois"] = backfilled

    # 6b. Ensure standard fields in config (e.g. pdf_path)
    injected_fields = ensure_standard_fields(root)
    if injected_fields:
        result["config_fields_added"] = injected_fields

    # 6c. Validate output_fields configuration
    field_validation = validate_output_fields(root)
    if not field_validation["ok"]:
        result["config_errors"] = field_validation["errors"]
    if field_validation["warnings"]:
        result["config_warnings"] = field_validation["warnings"]

    # 6d. Migrate CSV columns (add new output_fields to existing results.csv)
    new_columns = migrate_csv_columns(root)
    if new_columns:
        result["csv_columns_added"] = new_columns

    # 6c. Stamp skill version in config
    previous_version = stamp_skill_version(root)
    if previous_version and previous_version != SKILL_VERSION:
        result["upgraded_from"] = previous_version
        # Collect changelog entries for all versions after the previous one
        changes = []
        for ver, entries in CHANGELOG.items():
            if ver > previous_version:
                changes.extend(entries)
        if changes:
            result["upgrade_notes"] = changes
    result["skill_version"] = SKILL_VERSION

    # 7. Stuck handoffs
    stuck = detect_stuck_handoffs(root)
    result["stuck_handoffs"] = stuck

    # 8. Prune old learning files
    archived = prune_learning(root)
    if archived:
        result["learning_archived"] = archived

    # 9. Queue prioritization
    queue_info = prioritize_queue(root)
    result["queue"] = queue_info

    # 10. Read project state
    state = read_project_state(root)
    result.update(state)

    # 11. Write snapshot
    guide_md5 = state.get("guide_md5", "")
    config_md5 = state.get("config_py_md5", "")
    write_snapshot(
        root, args.session_id, args.mode, args.target,
        args.extractors, guide_md5, config_md5,
    )

    # 12. Clear dispatch state for new session
    dispatch_path = os.path.join(root, "state", "dispatch_state.json")
    safe_write_json(dispatch_path, {
        "active_agents": {},
        "session_counts": {},
    })

    # 13. Log session_start to run_log.jsonl
    append_jsonl(os.path.join(root, "state", "run_log.jsonl"), {
        "event": "session_start",
        "session_id": args.session_id,
        "extraction_mode": args.mode,
        "target": args.target,
        "max_concurrent_extractors": args.extractors,
        "records_at_start": state.get("records", 0),
        "queue_depth": queue_info.get("total", 0),
        "guide_md5": guide_md5,
        "config_md5": config_md5,
    })

    print(json.dumps(result, indent=2))


def cmd_end(args):
    """Execute all session teardown tasks."""
    root = args.project_root
    result = {"session_id": args.session_id}

    # Run teardown scripts
    script_results = run_teardown_scripts(root, args.session_id)
    result["scripts"] = script_results

    # Query yield analysis
    yield_info = compute_query_yield(root)
    result["query_yield"] = yield_info

    # Final state
    state = read_project_state(root)
    result["final_state"] = state

    # Count learning files produced this session
    learning_dir = os.path.join(root, "learning")
    learning_count = len(glob.glob(os.path.join(learning_dir, "*.json"))) if os.path.isdir(learning_dir) else 0
    result["learning_files"] = learning_count

    # Clean up stale files (lock files, empty placeholders, tmp files)
    try:
        from project_cleanup import scan_project, apply_cleanup
        categories = scan_project(root)
        # Auto-clean everything except script variants and duplicate results
        safe_categories = {k: v for k, v in categories.items()
                          if k not in ("script_variants", "duplicate_results")}
        deleted, _ = apply_cleanup(safe_categories, root)
        if deleted > 0:
            result["cleanup"] = {"files_removed": deleted}
    except (ImportError, Exception):
        pass  # Cleanup is best-effort

    # Count needs_attention records
    na_path = os.path.join(root, "state", "needs_attention.csv")
    needs_attention_count = 0
    if os.path.exists(na_path):
        with open(na_path, "r") as f:
            needs_attention_count = max(0, sum(1 for _ in f) - 1)
    if needs_attention_count > 0:
        result["needs_attention"] = needs_attention_count

    # Log session_end to run_log.jsonl
    append_jsonl(os.path.join(root, "state", "run_log.jsonl"), {
        "event": "session_end",
        "session_id": args.session_id,
        "papers_processed": args.papers_processed,
        "records_written": args.records_written,
        "records_at_end": state.get("records", 0),
        "queue_remaining": state.get("queue_depth", 0),
        "learning_files": learning_count,
        "needs_attention": needs_attention_count,
    })

    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="TraitTrawler session lifecycle manager"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Initialize a new session")
    p_start.add_argument("--project-root", default=".")
    p_start.add_argument("--skill-dir", default="",
                         help="Path to skill directory (for copying scripts)")
    p_start.add_argument("--session-id", required=True)
    p_start.add_argument("--mode", default="extract_verify",
                         help="Extraction mode (v5: always extract_verify)")
    p_start.add_argument("--target", default="20")
    p_start.add_argument("--extractors", type=int, default=5)
    p_start.add_argument("--force", action="store_true",
                         help="Force re-initialization even if session exists")

    # end
    p_end = sub.add_parser("end", help="Finalize a session")
    p_end.add_argument("--project-root", default=".")
    p_end.add_argument("--session-id", required=True)
    p_end.add_argument("--papers-processed", type=int, default=0)
    p_end.add_argument("--records-written", type=int, default=0)

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "end":
        cmd_end(args)


if __name__ == "__main__":
    main()
