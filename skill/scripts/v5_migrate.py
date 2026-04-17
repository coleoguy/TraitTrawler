#!/usr/bin/env python3
"""Classify and clean up a v5 TraitTrawler project directory.

When you point v6 at an existing v5 project, the directory is typically
cluttered with v5-specific state files, intermediate result folders,
deprecated scripts, and session logs. This script:

  1. Detects v5 markers to confirm it IS a v5 project.
  2. Classifies every top-level file/directory into one of four buckets:
     - KEEP      — used by v6 (results.csv, pdfs/, …)
     - MIGRATE   — valuable input to v6 bootstrap (guide.md, ill_list.csv,
                    processed.json, extraction_examples.md)
     - DEPRECATE — move to deprecated/ (v5 state, scripts, intermediates)
     - UNKNOWN   — ask the user
  3. Writes `state/bootstrap/v5_cleanup_plan.md` + `.json` for review.
  4. On --execute, MOVES (not deletes) DEPRECATE items into a
     timestamped `deprecated/<iso>/` directory. Everything is
     reversible with `mv deprecated/<iso>/* .`.
  5. Writes `state/bootstrap/v5_manifest.json` recording exactly what
     was moved so you can always audit or roll back.

NOTHING is ever deleted. The script is strictly reorganizational.

Usage:
    python v5_migrate.py --root <project_root> --source <v5_folder>
    python v5_migrate.py --root <project_root> --source <v5_folder> --execute
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# ------------------------------------------------------------------
# v5 detection and classification
# ------------------------------------------------------------------

V5_MARKERS = {
    "pipeline_state.json", "processed.json", "calibration_data.jsonl",
    "coverage_tracker.json", "triage_stats.json", "search_log.json",
    "run_log.jsonl", "discoveries.jsonl",
    "dashboard_generator.py", "verify_session.py", "export_dwc.py",
    "guide.md", "extraction_examples.md",
}

V5_DIRS = {
    "finds", "audit_results", "audit_manifests", "adjudication",
    "adjudication_results", "dealer_results", "writer_results",
    "ready_for_extraction", "search_results", "fetch_failures",
    "lead_files", "learning", "perfection_finds", "provided_pdfs",
}

# Classification per entry name (file or dir).
# KEEP: v6 uses it directly as-is.
# MIGRATE: v6 treats it as a bootstrap input (or renames it).
# DEPRECATE: move to deprecated/.
# UNKNOWN: ask the user.

CLASSIFICATION: dict[str, str] = {
    # v6 infra (keep)
    "results.csv": "KEEP",
    "pdfs": "KEEP",
    "config.yaml": "KEEP",
    "state": "KEEP",
    "reports": "KEEP",
    "candidates.jsonl": "KEEP",
    "legacy_rejected.csv": "KEEP",

    # v5 artifacts that carry real value into v6 bootstrap
    "guide.md": "MIGRATE",
    "extraction_examples.md": "MIGRATE",
    "ill_list.csv": "MIGRATE",          # → papers_needed
    "leads.csv": "MIGRATE",             # → papers_needed candidates
    "processed.json": "MIGRATE",        # dedup hint
    "calibration_data.jsonl": "MIGRATE",  # historical confidence reference

    # v5 state files (deprecate)
    "pipeline_state.json": "DEPRECATE",
    "coverage_tracker.json": "DEPRECATE",
    "triage_stats.json": "DEPRECATE",
    "search_log.json": "DEPRECATE",
    "run_log.jsonl": "DEPRECATE",
    "discoveries.jsonl": "DEPRECATE",
    "collector_config.yaml": "DEPRECATE",
    "config.py": "DEPRECATE",
    "context.md": "DEPRECATE",
    "dashboard.html": "DEPRECATE",
    "processed_backup.json": "DEPRECATE",

    # v5 scripts (deprecate)
    "dashboard_generator.py": "DEPRECATE",
    "verify_session.py": "DEPRECATE",
    "export_dwc.py": "DEPRECATE",
}

# Any dir matching V5_DIRS becomes DEPRECATE unless specifically listed.
for d in V5_DIRS:
    CLASSIFICATION.setdefault(d, "DEPRECATE")


def detect_v5(source: Path) -> tuple[bool, list[str]]:
    """Returns (is_v5, found_markers)."""
    markers = []
    for m in V5_MARKERS:
        if (source / m).exists():
            markers.append(m)
    for d in V5_DIRS:
        if (source / d).is_dir():
            markers.append(f"{d}/")
    return (len(markers) >= 2), markers  # 2+ markers => confident v5


def classify_entry(path: Path, source: Path) -> str:
    rel = path.relative_to(source).parts[0]
    if rel in CLASSIFICATION:
        return CLASSIFICATION[rel]
    # Unlisted dotfiles/backups follow a pattern
    if rel.startswith(".") or rel.endswith(".bak") or rel.endswith(".tmp"):
        return "KEEP"  # preserve hidden files; user's call
    # Backup files
    if "backup" in rel.lower() or "_bak" in rel.lower() or rel.endswith("~"):
        return "DEPRECATE"
    # Everything else unknown — user decides
    return "UNKNOWN"


def build_plan(source: Path) -> dict:
    is_v5, markers = detect_v5(source)
    entries: list[dict] = []
    for p in sorted(source.iterdir()):
        if p.name in (".git", ".DS_Store", "deprecated"):
            continue
        cls = classify_entry(p, source)
        entries.append({
            "path": str(p.relative_to(source)),
            "type": "dir" if p.is_dir() else "file",
            "classification": cls,
            "size_bytes": _dir_size(p) if p.is_dir() else p.stat().st_size,
        })
    return {
        "source": str(source),
        "is_v5": is_v5,
        "v5_markers_found": markers,
        "entries": entries,
        "counts": {
            "KEEP": sum(1 for e in entries if e["classification"] == "KEEP"),
            "MIGRATE": sum(1 for e in entries if e["classification"] == "MIGRATE"),
            "DEPRECATE": sum(1 for e in entries if e["classification"] == "DEPRECATE"),
            "UNKNOWN": sum(1 for e in entries if e["classification"] == "UNKNOWN"),
        },
    }


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def render_plan_markdown(plan: dict) -> str:
    lines = [
        "# v5 Cleanup Plan",
        "",
        f"Source: `{plan['source']}`",
        f"Detected as v5: **{plan['is_v5']}**  (markers: {plan['v5_markers_found']})",
        "",
        "Every DEPRECATE item will be MOVED (not deleted) into a timestamped",
        "`deprecated/<iso>/` directory under the source. Nothing is destroyed;",
        "you can roll back with `mv deprecated/<iso>/* .`.",
        "",
        "## Counts",
    ]
    for bucket, n in plan["counts"].items():
        lines.append(f"- {bucket}: {n}")

    for bucket in ("KEEP", "MIGRATE", "DEPRECATE", "UNKNOWN"):
        items = [e for e in plan["entries"] if e["classification"] == bucket]
        if not items:
            continue
        lines.append(f"\n## {bucket}\n")
        for e in items:
            size_mb = e["size_bytes"] / 1024 / 1024
            size_s = f"{size_mb:.1f} MB" if size_mb >= 0.1 else f"{e['size_bytes']} B"
            lines.append(f"- `{e['path']}` ({e['type']}, {size_s})")
    lines += [
        "",
        "## What MIGRATE items become",
        "",
        "- `guide.md` → trait_learner uses as additional seed knowledge",
        "- `extraction_examples.md` → trait_learner uses as notation examples",
        "- `ill_list.csv`, `leads.csv` → fed to bootstrap as `--papers-needed`",
        "- `processed.json` → hint for dedup (marks DOIs already handled)",
        "- `calibration_data.jsonl` → historical reference (not used at extraction)",
        "",
        "## To execute",
        "",
        "Review the plan. On approval, re-run with `--execute`.",
        "UNKNOWN items stay in place; you decide what to do with each.",
        "",
    ]
    return "\n".join(lines)


def execute(plan: dict, source: Path, dest_root: Path | None = None) -> dict:
    """Move every DEPRECATE entry into deprecated/<iso>/."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dep_dir = (dest_root or source) / "deprecated" / stamp
    dep_dir.mkdir(parents=True, exist_ok=True)
    moved: list[dict] = []
    for entry in plan["entries"]:
        if entry["classification"] != "DEPRECATE":
            continue
        src = source / entry["path"]
        if not src.exists():
            continue
        dst = dep_dir / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append({
            "from": str(src),
            "to": str(dst),
            "type": entry["type"],
            "size_bytes": entry["size_bytes"],
        })
    manifest = {
        "executed_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "deprecated_dir": str(dep_dir),
        "moved": moved,
        "rollback_command": f"mv {dep_dir}/* {source}/",
    }
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True,
                    help="v6 project root (must have state/)")
    ap.add_argument("--source", type=Path, required=True,
                    help="v5 folder to clean up. May equal --root for "
                         "in-place cleanup.")
    ap.add_argument("--execute", action="store_true",
                    help="Actually move DEPRECATE items. Without this flag, "
                         "only the plan is written.")
    args = ap.parse_args()

    root = args.root.resolve()
    source = args.source.resolve()
    if not source.exists():
        print(f"source not found: {source}", file=sys.stderr)
        return 2

    bootstrap_dir = root / "state" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    plan = build_plan(source)
    (bootstrap_dir / "v5_cleanup_plan.json").write_text(
        json.dumps(plan, indent=2, default=str))
    (bootstrap_dir / "v5_cleanup_plan.md").write_text(
        render_plan_markdown(plan))

    if not args.execute:
        print(json.dumps({
            "mode": "plan-only",
            "is_v5": plan["is_v5"],
            "counts": plan["counts"],
            "plan_md": str(bootstrap_dir / "v5_cleanup_plan.md"),
            "next_step": "Review the plan then re-run with --execute"
                         if plan["is_v5"] else
                         "No strong v5 signal; nothing to clean up unless you "
                         "override",
        }, indent=2))
        return 0

    manifest = execute(plan, source)
    (bootstrap_dir / "v5_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str))
    print(json.dumps({
        "mode": "executed",
        "moved_count": len(manifest["moved"]),
        "deprecated_dir": manifest["deprecated_dir"],
        "rollback": manifest["rollback_command"],
        "manifest": str(bootstrap_dir / "v5_manifest.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
