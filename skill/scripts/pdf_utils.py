#!/usr/bin/env python3
"""
PDF path utilities for TraitTrawler.

Provides canonical path construction, misplaced-PDF detection, and relocation.

Usage:
    python3 scripts/pdf_utils.py --project-root . --check
    python3 scripts/pdf_utils.py --project-root . --fix
"""

import argparse
import csv
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path


def _sanitize(text, max_len=12):
    """Remove non-ASCII, spaces, and punctuation; truncate."""
    if not text:
        return "unknown"
    # Normalize unicode to ASCII approximations
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]", "", text)
    return text[:max_len] if text else "unknown"


def _short_doi(doi):
    """Extract short identifier from DOI for filename use."""
    if not doi:
        return "noDOI"
    # Take last segment after final / or .
    parts = re.split(r"[/.]", doi)
    short = parts[-1] if parts else "noDOI"
    short = re.sub(r"[^A-Za-z0-9]", "", short)
    return short[:10] if short else "noDOI"


def build_pdf_path(project_root, first_author, year, journal, doi,
                   subfolder_value, subfolder_field="family"):
    """Construct the canonical PDF save path and ensure directory exists.

    Returns (absolute_path, relative_path) tuple.
    Example: ("/abs/pdfs/Carabidae/Smith_2003_CompCytogen_9504.pdf",
              "pdfs/Carabidae/Smith_2003_CompCytogen_9504.pdf")
    """
    root = Path(project_root).resolve()
    subfolder = _sanitize(subfolder_value, max_len=50) if subfolder_value else "unknown"
    author = _sanitize(first_author, max_len=20)
    yr = str(year) if year else "noYear"
    jrnl = _sanitize(journal, max_len=12)
    sdoi = _short_doi(doi)

    filename = f"{author}_{yr}_{jrnl}_{sdoi}.pdf"
    rel = Path("pdfs") / subfolder / filename
    full = root / rel

    # Ensure directory exists
    full.parent.mkdir(parents=True, exist_ok=True)
    return str(full), str(rel)


def check_misplaced_pdfs(project_root):
    """Find PDF files in project root that should be in pdfs/ subfolder.

    Returns list of dicts: {"path": str, "suggestion": str | None}
    """
    root = Path(project_root).resolve()
    pdfs_dir = root / "pdfs"
    misplaced = []

    for f in root.iterdir():
        if f.suffix.lower() == ".pdf" and f.is_file():
            # Try to match against results.csv for a better destination
            suggestion = _suggest_destination(root, f.name)
            misplaced.append({
                "path": str(f),
                "name": f.name,
                "suggestion": suggestion,
            })
    return misplaced


def _suggest_destination(root, pdf_name):
    """Try to find the correct pdfs/{family}/ destination from results.csv."""
    results_path = root / "results.csv"
    if not results_path.exists():
        return None

    try:
        with open(results_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if row.get("pdf_filename", "") == pdf_name:
                    family = row.get("family", "unknown") or "unknown"
                    return str(Path("pdfs") / _sanitize(family, 50) / pdf_name)
    except Exception:
        pass
    return None


def relocate_misplaced_pdfs(project_root, dry_run=True):
    """Move misplaced PDFs to their correct locations.

    Returns list of (src, dst, moved) tuples.
    """
    misplaced = check_misplaced_pdfs(project_root)
    root = Path(project_root).resolve()
    results = []

    for item in misplaced:
        src = Path(item["path"])
        if item["suggestion"]:
            dst = root / item["suggestion"]
        else:
            dst = root / "pdfs" / "unknown" / item["name"]

        if dry_run:
            results.append((str(src), str(dst), False))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            results.append((str(src), str(dst), True))

    return results


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler PDF path utilities")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--check", action="store_true", help="Check for misplaced PDFs")
    parser.add_argument("--fix", action="store_true", help="Move misplaced PDFs to correct locations")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not root.exists():
        print(f"Error: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    if args.check or args.fix:
        misplaced = check_misplaced_pdfs(root)
        if not misplaced:
            print("No misplaced PDFs found in project root.")
            sys.exit(0)

        print(f"Found {len(misplaced)} PDF(s) in project root:")
        for item in misplaced:
            dest = item["suggestion"] or f"pdfs/unknown/{item['name']}"
            print(f"  {item['name']} -> {dest}")

        if args.fix:
            results = relocate_misplaced_pdfs(root, dry_run=False)
            moved = sum(1 for _, _, m in results if m)
            print(f"\nMoved {moved} file(s).")
        else:
            print("\nRun with --fix to move them.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
