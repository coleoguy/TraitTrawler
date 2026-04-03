#!/usr/bin/env python3
"""
Project directory cleanup for TraitTrawler.

Removes stale files that accumulate across sessions: empty report placeholders,
lock files, backup files, temp files, and optionally old script variants.

Usage:
    python3 scripts/project_cleanup.py --project-root /path/to/project --dry-run
    python3 scripts/project_cleanup.py --project-root /path/to/project --apply
"""

import argparse
import os
import sys
from pathlib import Path


def find_empty_files(root):
    """Find 0-byte files in root directory (report placeholders)."""
    results = []
    for f in root.iterdir():
        if f.is_file() and f.stat().st_size == 0:
            results.append(f)
    return results


def find_lock_files(root):
    """Find stale .lock files anywhere in the project."""
    return list(root.rglob("*.lock"))


def find_bak_files(root):
    """Find .bak backup files anywhere in the project."""
    return list(root.rglob("*.bak"))


def find_tmp_files(root):
    """Find .tmp and temp files anywhere in the project."""
    results = list(root.rglob("*.tmp"))
    results.extend(root.rglob(".results_new_*"))
    results.extend(root.rglob("*.json.tmp"))
    return results


def find_junk_files(root):
    """Find known junk files."""
    junk_names = {".DS_Store", "cookies.txt", "stdout", ".Rhistory",
                  "Thumbs.db", ".FETCHER_COMPLETE"}
    results = []
    for f in root.iterdir():
        if f.is_file() and f.name in junk_names:
            results.append(f)
    # Also check subdirectories for .DS_Store
    for f in root.rglob(".DS_Store"):
        if f not in results:
            results.append(f)
    return results


def find_duplicate_results(root):
    """Find duplicate/backup copies of results.csv."""
    results = []
    for f in root.iterdir():
        if not f.is_file():
            continue
        name = f.name.lower()
        if name == "results.csv":
            continue  # keep the real one
        if "results" in name and name.endswith(".csv"):
            results.append(f)
    return results


def find_script_variants(root):
    """Find duplicate script variants (v2, v3, final, enhanced, etc.)."""
    scripts_dir = root / "scripts"
    if not scripts_dir.exists():
        # Check root for scripts
        scripts_dir = root

    variant_suffixes = ["_v2", "_v3", "_v4", "_final", "_final_v2",
                        "_enhanced", "_robust", "_complete", "_extended",
                        "_advanced", "_comprehensive", "_clean",
                        "_aggressive", "_simple", "_base"]

    results = []
    for f in scripts_dir.iterdir():
        if not f.is_file() or f.suffix not in (".py", ".sh"):
            continue
        stem = f.stem.lower()
        for suffix in variant_suffixes:
            if stem.endswith(suffix):
                results.append(f)
                break
    return results


def scan_project(root):
    """Scan project for all cleanup candidates."""
    root = Path(root).resolve()

    categories = {
        "empty_files": find_empty_files(root),
        "lock_files": find_lock_files(root),
        "bak_files": find_bak_files(root),
        "tmp_files": find_tmp_files(root),
        "junk_files": find_junk_files(root),
        "duplicate_results": find_duplicate_results(root),
        "script_variants": find_script_variants(root),
    }

    return categories


def print_report(categories, root):
    """Print a summary of cleanup candidates."""
    root = Path(root).resolve()
    total = 0
    total_bytes = 0

    for cat_name, files in categories.items():
        if not files:
            continue
        cat_bytes = sum(f.stat().st_size for f in files if f.exists())
        total += len(files)
        total_bytes += cat_bytes
        label = cat_name.replace("_", " ").title()
        print(f"\n{label} ({len(files)} files, {cat_bytes / 1024:.1f} KB):")
        # Show up to 10 files per category
        for f in sorted(files)[:10]:
            rel = f.relative_to(root) if f.is_relative_to(root) else f
            size = f.stat().st_size if f.exists() else 0
            print(f"  {rel} ({size:,} bytes)")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")

    print(f"\n{'='*50}")
    print(f"Total: {total} files, {total_bytes / 1024:.1f} KB")
    return total


def apply_cleanup(categories, root, skip_scripts=True):
    """Delete cleanup candidates."""
    root = Path(root).resolve()
    deleted = 0
    errors = 0

    for cat_name, files in categories.items():
        if cat_name == "script_variants" and skip_scripts:
            continue  # Don't auto-delete scripts without explicit flag
        for f in files:
            try:
                if f.exists():
                    os.remove(f)
                    deleted += 1
            except OSError as e:
                print(f"  ERROR: Could not delete {f}: {e}", file=sys.stderr)
                errors += 1

    return deleted, errors


def main():
    parser = argparse.ArgumentParser(
        description="Clean up stale files in a TraitTrawler project"
    )
    parser.add_argument("--project-root", required=True,
                        help="Path to project root")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Show what would be deleted")
    group.add_argument("--apply", action="store_true",
                       help="Delete cleanup candidates")
    parser.add_argument("--include-scripts", action="store_true",
                        help="Also delete script variant files")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"Error: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    categories = scan_project(root)

    if args.dry_run:
        print("PROJECT CLEANUP - DRY RUN")
        print(f"Scanning: {root}")
        total = print_report(categories, root)
        if total == 0:
            print("\nProject is clean!")
        else:
            print("\nRun with --apply to delete these files.")
            if not args.include_scripts:
                n_scripts = len(categories.get("script_variants", []))
                if n_scripts:
                    print(f"(Script variants [{n_scripts}] excluded — "
                          f"use --include-scripts to include)")
    else:
        print("PROJECT CLEANUP - APPLYING")
        print(f"Scanning: {root}")
        print_report(categories, root)
        print()
        deleted, errors = apply_cleanup(
            categories, root, skip_scripts=not args.include_scripts)
        print(f"Deleted {deleted} files ({errors} errors)")


if __name__ == "__main__":
    main()
