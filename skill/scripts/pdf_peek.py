#!/usr/bin/env python3
"""Quick PDF text peek for triage.

Given a sha256, returns text from a page range. Much cheaper than
reading the full PDF into a subagent's context.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

try:
    import pdfplumber  # type: ignore
except ImportError:
    print("pdfplumber required", file=sys.stderr)
    sys.exit(3)


def parse_range(s: str) -> list[int]:
    """Accept '1', '1-3', '1,3,5'."""
    pages: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        elif part:
            pages.append(int(part))
    return pages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha256")
    ap.add_argument("--path", type=Path, help="direct PDF path")
    ap.add_argument("--pages", required=True, help="e.g. '1-2' or '1,3,5'")
    ap.add_argument("--project-root", type=Path)
    ap.add_argument("--max-chars", type=int, default=8000)
    args = ap.parse_args()

    pdf_path: Path
    if args.path:
        pdf_path = args.path.resolve()
    else:
        if not args.sha256 or not args.project_root:
            print("--sha256 + --project-root or --path required", file=sys.stderr)
            return 2
        db = (args.project_root / "state" / "manifest.sqlite").resolve()
        con = sqlite3.connect(db)
        try:
            row = con.execute(
                "SELECT canonical_path FROM pdfs WHERE sha256 = ?",
                (args.sha256,),
            ).fetchone()
        finally:
            con.close()
        if not row:
            print(f"sha256 not found: {args.sha256}", file=sys.stderr)
            return 2
        pdf_path = Path(row[0]).resolve()

    pages = parse_range(args.pages)
    out: dict = {"pdf_path": str(pdf_path), "pages": {}}
    with pdfplumber.open(pdf_path) as pdf:
        npages = len(pdf.pages)
        for p in pages:
            if 1 <= p <= npages:
                text = pdf.pages[p - 1].extract_text() or ""
                out["pages"][p] = text[: args.max_chars]
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
