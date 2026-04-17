#!/usr/bin/env python3
"""SHA256-hash PDFs into manifest.sqlite. Idempotent.

Modes:
  --file <path>             : hash one file, insert/update manifest
  --scan                    : scan pdfs/ directory, hash any new files
  --dedupe                  : identify and report duplicate PDFs (same sha256)

Exit code 0 on success, non-zero on fatal error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BLOCKSIZE = 1 << 20  # 1 MiB


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(BLOCKSIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_page_count(path: Path) -> int | None:
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def project_root_from_cwd() -> Path:
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        if (cur / "state" / "manifest.sqlite").exists():
            return cur
        cur = cur.parent
    raise RuntimeError("No project root found (no state/manifest.sqlite above cwd)")


def ingest_one(con: sqlite3.Connection, path: Path) -> dict:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    sha = sha256_file(path)
    row = con.execute(
        "SELECT sha256, canonical_path FROM pdfs WHERE sha256 = ?", (sha,)
    ).fetchone()
    if row:
        return {"status": "duplicate", "sha256": sha,
                "canonical_path": row[1], "this_path": str(path)}
    pages = pdf_page_count(path)
    con.execute(
        """INSERT INTO pdfs (sha256, canonical_path, original_filename,
                              pages, bytes, added_utc)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (sha, str(path), path.name, pages, path.stat().st_size,
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    return {"status": "ingested", "sha256": sha, "path": str(path), "pages": pages}


def scan_directory(con: sqlite3.Connection, pdfs_dir: Path) -> list[dict]:
    results = []
    for p in sorted(pdfs_dir.rglob("*.pdf")):
        results.append(ingest_one(con, p))
    return results


def report_duplicates(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        """SELECT sha256, GROUP_CONCAT(canonical_path, '|') as paths, COUNT(*) as n
           FROM pdfs GROUP BY sha256 HAVING n > 1"""
    ).fetchall()
    return [{"sha256": r[0], "paths": r[1].split("|"), "count": r[2]} for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--project-root", type=Path)
    args = ap.parse_args()

    root = (args.project_root or project_root_from_cwd()).resolve()
    db = root / "state" / "manifest.sqlite"
    if not db.exists():
        print(f"manifest not found at {db}", file=sys.stderr)
        return 2
    con = sqlite3.connect(db)

    out: dict = {"project_root": str(root)}
    try:
        if args.file:
            out["result"] = ingest_one(con, args.file.resolve())
        elif args.scan:
            out["results"] = scan_directory(con, root / "pdfs")
            out["count"] = len(out["results"])
        elif args.dedupe:
            out["duplicates"] = report_duplicates(con)
        else:
            print("one of --file, --scan, --dedupe required", file=sys.stderr)
            return 2
    finally:
        con.close()

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
