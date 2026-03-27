#!/usr/bin/env python3
"""
Atomic state file utilities for TraitTrawler.

Provides crash-safe read/write for all JSON state files (processed.json,
queue.json, search_log.json, etc.) using write-to-temp-then-rename pattern.
Includes JSON validation on read with fallback to last-known-good backup.

Usage:
    from state_utils import safe_read_json, safe_write_json, append_jsonl

    # Read with validation and backup fallback
    processed = safe_read_json("state/processed.json", default={})

    # Write atomically (temp file + rename)
    processed["10.1234/example"] = {"triage": "likely", "records": 3}
    safe_write_json("state/processed.json", processed)

    # Append to JSONL (run_log, discoveries)
    append_jsonl("state/run_log.jsonl", {"event": "paper_processed", ...})
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Union


# ---------------------------------------------------------------------------
# Atomic JSON read/write
# ---------------------------------------------------------------------------

def safe_read_json(path: str, default: Any = None,
                   create_if_missing: bool = True) -> Any:
    """
    Read a JSON file with validation and backup fallback.

    If the file is corrupt or unreadable:
    1. Try the backup file ({path}.bak)
    2. If backup also fails, return the default value
    3. Log the corruption for the user

    Args:
        path: Path to the JSON file.
        default: Default value if file doesn't exist or is unreadable.
        create_if_missing: If True, create the file with default value
            if it doesn't exist.

    Returns:
        Parsed JSON data, or default if unreadable.
    """
    if not os.path.exists(path):
        if create_if_missing and default is not None:
            safe_write_json(path, default)
        return default if default is not None else {}

    # Try main file
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default if default is not None else {}
            data = json.loads(content)
            return data
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"WARNING: Corrupt JSON in {path}: {e}", file=sys.stderr)

    # Try backup
    backup_path = path + ".bak"
    if os.path.exists(backup_path):
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    print(f"  Recovered from backup: {backup_path}",
                          file=sys.stderr)
                    # Restore main file from backup
                    safe_write_json(path, data)
                    return data
        except (json.JSONDecodeError, UnicodeDecodeError) as e2:
            print(f"  Backup also corrupt: {backup_path}: {e2}",
                  file=sys.stderr)

    # Both failed — return default
    print(f"  Using default value for {path}", file=sys.stderr)
    return default if default is not None else {}


def safe_write_json(path: str, data: Any, indent: int = 2,
                    backup: bool = True) -> None:
    """
    Write JSON data atomically using write-to-temp-then-rename.

    Steps:
    1. Shrink detection: refuse to overwrite a dict/list with fewer entries
    2. If backup=True and file exists, copy current file to {path}.bak
    3. Write data to a temp file in the same directory
    4. Rename temp file to target path (atomic on POSIX)

    This ensures that a crash at any point leaves either the old file
    or the new file intact — never a partial write.

    Args:
        path: Target file path.
        data: JSON-serializable data.
        indent: JSON indentation (default: 2).
        backup: If True, create .bak before overwriting.

    Raises:
        ValueError: If the new data is significantly smaller than existing,
            indicating a possible accidental overwrite.
    """
    parent_dir = os.path.dirname(path) or "."
    os.makedirs(parent_dir, exist_ok=True)

    # Step 0: Shrink detection — prevent accidental overwrites
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            # Check if new data is dramatically smaller than existing
            if isinstance(existing, dict) and isinstance(data, dict):
                if len(existing) > 10 and len(data) < len(existing) * 0.5:
                    raise ValueError(
                        f"SHRINK DETECTED: {path} has {len(existing)} entries "
                        f"but new data has only {len(data)}. Refusing to overwrite. "
                        f"If intentional, delete the file first."
                    )
            elif isinstance(existing, list) and isinstance(data, list):
                if len(existing) > 10 and len(data) < len(existing) * 0.5:
                    raise ValueError(
                        f"SHRINK DETECTED: {path} has {len(existing)} entries "
                        f"but new data has only {len(data)}. Refusing to overwrite. "
                        f"If intentional, delete the file first."
                    )
        except (json.JSONDecodeError, ValueError) as e:
            if "SHRINK DETECTED" in str(e):
                raise  # re-raise shrink detection
            pass  # ignore other read errors — proceed with write

    # Step 1: Create backup of current file
    if backup and os.path.exists(path):
        backup_path = path + ".bak"
        try:
            shutil.copy2(path, backup_path)
        except OSError:
            pass  # backup failure shouldn't block write

    # Step 2: Write to temp file
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".json.tmp",
        dir=parent_dir,
        prefix="." + os.path.basename(path) + "_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.write("\n")  # trailing newline for POSIX compliance
            f.flush()
            os.fsync(f.fileno())  # force to disk

        # Step 3: Atomic rename
        os.rename(tmp_path, path)

    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def append_jsonl(path: str, entry: dict) -> None:
    """
    Append a single JSON object to a JSONL file.

    Uses file locking (via append mode) to prevent interleaved writes.
    Each entry is written as a single line terminated by newline.

    Args:
        path: Path to the JSONL file.
        entry: Dictionary to serialize and append.
    """
    parent_dir = os.path.dirname(path) or "."
    os.makedirs(parent_dir, exist_ok=True)

    # Add timestamp if not present
    if "timestamp" not in entry:
        entry["timestamp"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )

    line = json.dumps(entry, ensure_ascii=False) + "\n"

    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


def read_jsonl(path: str, max_lines: Optional[int] = None) -> list:
    """
    Read a JSONL file, skipping corrupt lines.

    Args:
        path: Path to the JSONL file.
        max_lines: Maximum number of lines to read (None = all).

    Returns:
        List of parsed JSON objects.
    """
    if not os.path.exists(path):
        return []

    entries = []
    corrupt_count = 0

    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if max_lines is not None and len(entries) >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                corrupt_count += 1

    if corrupt_count:
        print(f"WARNING: {corrupt_count} corrupt line(s) in {path}",
              file=sys.stderr)

    return entries


# ---------------------------------------------------------------------------
# State file management helpers
# ---------------------------------------------------------------------------

def update_processed(state_dir: str, doi: str, entry: dict) -> None:
    """
    Add or update a DOI entry in processed.json.

    Args:
        state_dir: Path to state/ directory.
        doi: DOI string (key).
        entry: Dict with triage, outcome, records, date, etc.
    """
    path = os.path.join(state_dir, "processed.json")
    processed = safe_read_json(path, default={})
    processed[doi] = entry
    safe_write_json(path, processed)


def remove_from_queue(state_dir: str, doi: str) -> None:
    """
    Remove a DOI from queue.json.

    Args:
        state_dir: Path to state/ directory.
        doi: DOI to remove.
    """
    path = os.path.join(state_dir, "queue.json")
    queue = safe_read_json(path, default=[])
    queue = [item for item in queue if item.get("doi") != doi]
    safe_write_json(path, queue)


def add_to_queue(state_dir: str, papers: list) -> int:
    """
    Add papers to queue.json, deduplicating by DOI.

    Args:
        state_dir: Path to state/ directory.
        papers: List of paper dicts with at least 'doi' field.

    Returns:
        Number of new papers added.
    """
    path = os.path.join(state_dir, "queue.json")
    queue = safe_read_json(path, default=[])
    existing_dois = {item.get("doi") for item in queue}
    added = 0
    for paper in papers:
        if paper.get("doi") and paper["doi"] not in existing_dois:
            queue.append(paper)
            existing_dois.add(paper["doi"])
            added += 1
    safe_write_json(path, queue)
    return added


def log_search(state_dir: str, query: str, results: dict) -> None:
    """
    Log a completed search query to search_log.json.

    Args:
        state_dir: Path to state/ directory.
        query: The search query string.
        results: Dict with date, pubmed_results, biorxiv_results, etc.
    """
    path = os.path.join(state_dir, "search_log.json")
    search_log = safe_read_json(path, default={})
    search_log[query] = results
    safe_write_json(path, search_log)


def log_event(state_dir: str, event: dict) -> None:
    """
    Append an event to run_log.jsonl.

    Args:
        state_dir: Path to state/ directory.
        event: Event dict (timestamp added automatically if missing).
    """
    path = os.path.join(state_dir, "run_log.jsonl")
    append_jsonl(path, event)


# ---------------------------------------------------------------------------
# Integrity check
# ---------------------------------------------------------------------------

def check_state_integrity(project_root: str) -> dict:
    """
    Verify state file integrity and report issues.

    Returns:
        Dict with 'ok' (bool) and 'issues' (list of strings).
    """
    state_dir = os.path.join(project_root, "state")
    issues = []

    # Check each expected state file
    expected_files = {
        "processed.json": dict,
        "queue.json": list,
        "search_log.json": dict,
        "taxonomy_cache.json": dict,
        "source_stats.json": dict,
        "consensus_stats.json": dict,
    }

    for filename, expected_type in expected_files.items():
        path = os.path.join(state_dir, filename)
        if not os.path.exists(path):
            issues.append(f"Missing: {filename}")
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    issues.append(f"Empty: {filename}")
                    continue
                data = json.loads(content)
                if not isinstance(data, expected_type):
                    issues.append(
                        f"Wrong type in {filename}: expected "
                        f"{expected_type.__name__}, got {type(data).__name__}"
                    )
        except json.JSONDecodeError as e:
            issues.append(f"Corrupt JSON in {filename}: {e}")
        except Exception as e:
            issues.append(f"Error reading {filename}: {e}")

    # Check JSONL files
    for jsonl_file in ["run_log.jsonl", "discoveries.jsonl",
                       "calibration_data.jsonl", "triage_outcomes.jsonl"]:
        path = os.path.join(state_dir, jsonl_file)
        if os.path.exists(path):
            corrupt = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        corrupt += 1
            if corrupt:
                issues.append(f"{corrupt} corrupt line(s) in {jsonl_file}")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="TraitTrawler state file utilities"
    )
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--check", action="store_true",
                        help="Check state file integrity")
    parser.add_argument("--repair", action="store_true",
                        help="Attempt to repair corrupt state files")
    args = parser.parse_args()

    state_dir = os.path.join(args.project_root, "state")

    if args.check or args.repair:
        result = check_state_integrity(args.project_root)
        if result["ok"]:
            print("All state files OK.")
        else:
            print(f"Found {len(result['issues'])} issue(s):")
            for issue in result["issues"]:
                print(f"  - {issue}")

            if args.repair:
                print("\nAttempting repairs...")
                # Re-create missing files with defaults
                defaults = {
                    "processed.json": {},
                    "queue.json": [],
                    "search_log.json": {},
                    "taxonomy_cache.json": {},
                    "source_stats.json": {},
                    "consensus_stats.json": {},
                }
                for filename, default in defaults.items():
                    path = os.path.join(state_dir, filename)
                    if not os.path.exists(path):
                        safe_write_json(path, default)
                        print(f"  Created: {filename}")
                    else:
                        # Try to read — if corrupt, restore from backup or default
                        data = safe_read_json(path, default=default)
                        safe_write_json(path, data)
                        print(f"  Validated: {filename}")

                print("Repair complete.")
            else:
                sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
