#!/usr/bin/env python3
"""Rebuild results.csv ↔ pdfs/ linkage by SHA256.

Use case 1: you imported a v5 results.csv that has `pdf_filename` but
no `sha256` column — v6 requires sha256 for every row. This script
adds the column by re-pairing each row to the PDF on disk.

Use case 2: PDFs got moved or renamed since the last run. manifest.sqlite
still has the SHA256 → canonical_path map, but some canonical_paths no
longer exist. This script re-scans pdfs/ and updates the manifest with
the new paths (content hash hasn't changed, so rows still link).

Use case 3: you want a health report on linkage integrity before
extraction runs — how many rows have valid sha256, how many don't,
what pairing strategy worked.

This script is RUN AT ANY TIME and is safe to re-run. It only adds
columns; it never mutates existing values unless --force is passed.

Usage:
    # Report only (no changes)
    python repair_linkage.py --root <project> --csv results.csv

    # Repair in place (writes new sha256 column, updates manifest)
    python repair_linkage.py --root <project> --csv results.csv --repair

    # Full re-scan after moving PDFs
    python repair_linkage.py --root <project> --csv results.csv \
      --repair --rescan-pdfs <new_pdfs_dir>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rescan_pdfs(pdfs_dir: Path, db: Path) -> dict:
    """Hash every PDF in pdfs_dir and update manifest.sqlite's canonical_path
    where the content hash matches. New PDFs are inserted."""
    con = sqlite3.connect(db)
    stats = Counter()
    try:
        existing = {row[0]: row[1] for row in con.execute(
            "SELECT sha256, canonical_path FROM pdfs").fetchall()}
        seen: set[str] = set()
        for p in sorted(pdfs_dir.rglob("*.pdf")):
            if p.stat().st_size == 0:
                stats["skipped_empty"] += 1
                continue
            sha = sha256_of(p)
            seen.add(sha)
            if sha in existing:
                if existing[sha] != str(p):
                    con.execute(
                        "UPDATE pdfs SET canonical_path=? WHERE sha256=?",
                        (str(p), sha))
                    stats["updated_path"] += 1
                else:
                    stats["unchanged"] += 1
            else:
                con.execute(
                    """INSERT INTO pdfs (sha256, canonical_path, original_filename,
                                          bytes, added_utc, fetch_status)
                       VALUES (?, ?, ?, ?, ?, 'repair_scan')""",
                    (sha, str(p), p.name, p.stat().st_size, iso()))
                stats["newly_registered"] += 1
        # Stale entries — still in manifest but no longer on disk
        for sha, path in existing.items():
            if sha not in seen and not Path(path).exists():
                stats["stale_in_manifest"] += 1
        con.commit()
    finally:
        con.close()
    return dict(stats)


def load_manifest_index(db: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (sha256_to_path, stem_to_sha) from manifest.sqlite."""
    con = sqlite3.connect(db)
    try:
        sha_to_path: dict[str, str] = {}
        stem_to_sha: dict[str, str] = {}
        for sha, path in con.execute("SELECT sha256, canonical_path FROM pdfs"):
            sha_to_path[sha] = path
            stem_to_sha[Path(path).stem.lower()] = sha
        return sha_to_path, stem_to_sha
    finally:
        con.close()


def try_attach_sha(row: dict, sha_to_path: dict[str, str],
                    stem_to_sha: dict[str, str]) -> tuple[str | None, str]:
    """Try to find a sha256 for this row. Returns (sha or None, strategy)."""
    # 1. row already has sha256 and it's in manifest
    existing = (row.get("sha256") or "").strip().lower()
    if existing and existing in sha_to_path:
        return existing, "ALREADY_LINKED"
    # 2. pdf_filename column
    for col in ("pdf_filename", "pdf_file", "pdf", "filename", "file"):
        v = (row.get(col) or "").strip()
        if not v:
            continue
        stem = Path(v).stem.lower()
        if stem in stem_to_sha:
            return stem_to_sha[stem], "FILENAME"
    # 3. DOI-in-stem
    doi = (row.get("doi") or row.get("DOI") or "").strip()
    if doi:
        suffix = doi.split("/")[-1].lower()
        for stem, sha in stem_to_sha.items():
            if suffix and suffix in stem:
                return sha, "DOI_IN_STEM"
    # 4. author + year
    author = (row.get("first_author") or row.get("author")
              or row.get("authors") or "").strip()
    year = str(row.get("year") or row.get("publication_year") or "").strip()
    if author and year:
        import re as _re
        last = _re.split(r"[,\s&]", author)[0].strip().lower()
        for stem, sha in stem_to_sha.items():
            if last and year and last in stem and year in stem:
                return sha, "AUTHOR_YEAR"
    return None, "UNPAIRED"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True,
                    help="The CSV file to analyze / repair (typically "
                         "results.csv or an imported v5 CSV).")
    ap.add_argument("--repair", action="store_true",
                    help="Rewrite the CSV with a sha256 column. Original "
                         "backed up to <csv>.pre_repair.<iso>.bak.")
    ap.add_argument("--rescan-pdfs", type=Path, default=None,
                    help="Before repairing, re-hash every PDF in this dir "
                         "and update manifest canonical_paths.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing sha256 values if they disagree "
                         "with a better match. Default: keep existing.")
    args = ap.parse_args()

    root = args.root.resolve()
    db = root / "state" / "manifest.sqlite"
    if not db.exists():
        print(f"no manifest at {db}", file=sys.stderr)
        return 2

    rescan_stats: dict = {}
    if args.rescan_pdfs:
        if not args.rescan_pdfs.exists():
            print(f"rescan dir not found: {args.rescan_pdfs}", file=sys.stderr)
            return 2
        print(f"re-scanning {args.rescan_pdfs}…", file=sys.stderr)
        rescan_stats = rescan_pdfs(args.rescan_pdfs.resolve(), db)

    sha_to_path, stem_to_sha = load_manifest_index(db)

    # Read the target CSV
    if not args.csv.exists():
        print(f"csv not found: {args.csv}", file=sys.stderr)
        return 2
    rows: list[dict] = []
    fieldnames: list[str] = []
    with args.csv.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for r in reader:
            rows.append(dict(r))

    # Classify each row
    strategy_counter: Counter = Counter()
    unpaired_samples: list[dict] = []
    for r in rows:
        sha, strat = try_attach_sha(r, sha_to_path, stem_to_sha)
        r["_new_sha256"] = sha
        r["_sha_strategy"] = strat
        strategy_counter[strat] += 1
        if strat == "UNPAIRED" and len(unpaired_samples) < 10:
            unpaired_samples.append({
                "doi": r.get("doi") or r.get("DOI"),
                "species": r.get("canonical_species") or r.get("species"),
                "pdf_filename": r.get("pdf_filename") or r.get("pdf_file"),
            })

    report = {
        "csv": str(args.csv),
        "total_rows": len(rows),
        "strategies": dict(strategy_counter),
        "unpaired_samples": unpaired_samples,
        "rescan_stats": rescan_stats,
        "manifest_pdf_count": len(sha_to_path),
    }

    if not args.repair:
        print(json.dumps(report, indent=2))
        return 0

    # Repair: write back with sha256 column populated. Back up original.
    backup = args.csv.with_suffix(args.csv.suffix +
                                    f".pre_repair.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
    shutil.copy2(args.csv, backup)
    if "sha256" not in fieldnames:
        fieldnames = list(fieldnames) + ["sha256"]
    updated = 0
    kept = 0
    with args.csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            new_sha = r.get("_new_sha256")
            existing = (r.get("sha256") or "").strip()
            if new_sha:
                if existing and existing != new_sha and not args.force:
                    kept += 1
                else:
                    r["sha256"] = new_sha
                    updated += 1
            # else: leave sha256 blank
            # Strip scratch fields
            r.pop("_new_sha256", None)
            r.pop("_sha_strategy", None)
            writer.writerow(r)

    report["backup"] = str(backup)
    report["rows_updated"] = updated
    report["rows_kept_existing_sha"] = kept
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
