#!/usr/bin/env python3
"""Fuzzy row ↔ PDF pairing with confidence tiers.

Real-world curated CSVs rarely have filename columns that exactly match
the PDF stems on disk. This module tries multiple strategies in
decreasing confidence and reports per-row outcome:

Strategies (in order):
  1. EXACT_STEM      — filename column stem matches a PDF stem literally
  2. DOI_IN_NAME     — DOI suffix appears in a PDF stem (common publisher pattern)
  3. DOI_NORMALIZED  — DOI with slashes replaced matches a PDF stem
  4. AUTHOR_YEAR     — "Smith2019" or "Smith_2019" or "Smith et al 2019" present
  5. TITLE_PEEK      — pdfplumber reads first page of each PDF, fuzzy matches
                       title column against first-page text

Strategies 1–4 are cheap (no PDF reads). Strategy 5 reads each unpaired
PDF once and caches; skipped entirely if `--no-title-peek` is passed.

Output: state/bootstrap/pairing_report.json — per-row verdict with
confidence; also writes orphan_pdfs.json for PDFs that paired to nothing.

Usage:
    python pair_pdfs.py --root <root> --csv <csv> --pdfs <dir>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


CONF_EXACT_STEM = 1.00
CONF_DOI_IN_NAME = 0.95
CONF_DOI_NORMALIZED = 0.92
CONF_AUTHOR_YEAR = 0.85
CONF_TITLE_PEEK_BASE = 0.70  # scaled by similarity


def normalize_stem(s: str) -> str:
    return re.sub(r"\W+", "_", s.lower()).strip("_")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def index_pdfs(pdfs_dir: Path) -> list[dict]:
    """One record per PDF: path, stem, normalized_stem, size."""
    out: list[dict] = []
    for p in sorted(pdfs_dir.rglob("*.pdf")):
        if p.stat().st_size == 0:
            continue
        out.append({
            "path": p,
            "stem": p.stem,
            "normalized_stem": normalize_stem(p.stem),
        })
    return out


def _first_page_text(path: Path, char_limit: int = 2000) -> str:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return ""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return ""
            text = pdf.pages[0].extract_text() or ""
            return text[:char_limit]
    except Exception:
        return ""


AUTHOR_YEAR_RX = re.compile(r"(?i)([A-Z][a-z]+)[\s_\-,]*(?:et\s*al\.?)?[\s_\-,]*([0-9]{4})")


def try_pair(row: dict, pdfs: list[dict],
             title_text_cache: dict[Path, str] | None) -> dict:
    """Try strategies 1-5; return the best match or unpaired."""
    # 1. EXACT_STEM
    filename_cols = (
        "pdf_filename", "pdf_file", "filename", "file", "pdf_name",
        "pdf_path", "pdf",
    )
    filename_val = ""
    for c in filename_cols:
        v = row.get(c)
        if v:
            filename_val = str(v).strip()
            break
    if filename_val:
        stem = Path(filename_val).stem
        norm = normalize_stem(stem)
        for pdf in pdfs:
            if pdf["normalized_stem"] == norm or pdf["stem"] == stem:
                return {"pdf_path": str(pdf["path"]), "strategy": "EXACT_STEM",
                        "confidence": CONF_EXACT_STEM}

    # 2 & 3. DOI
    doi = (row.get("doi") or row.get("DOI") or "").strip()
    if doi:
        suffix = doi.split("/")[-1].lower()
        normalized = re.sub(r"[^a-z0-9]", "", doi.lower())
        for pdf in pdfs:
            ns = pdf["normalized_stem"]
            if suffix and suffix in ns:
                return {"pdf_path": str(pdf["path"]), "strategy": "DOI_IN_NAME",
                        "confidence": CONF_DOI_IN_NAME}
            if normalized and normalized in re.sub(r"[^a-z0-9]", "", pdf["stem"].lower()):
                return {"pdf_path": str(pdf["path"]),
                        "strategy": "DOI_NORMALIZED",
                        "confidence": CONF_DOI_NORMALIZED}

    # 4. AUTHOR_YEAR
    author = (row.get("first_author") or row.get("author") or
              row.get("authors") or "").strip()
    year = (row.get("year") or row.get("publication_year") or
            row.get("paper_year") or "").strip()
    if author and year:
        # Extract just the surname — many CSVs have "Smith, J. D." or
        # "Smith et al."
        last = re.split(r"[,\s&]", author)[0].strip().lower()
        if last:
            pattern = f"{last}{year}"
            pattern_norm = normalize_stem(pattern)
            for pdf in pdfs:
                if pattern_norm in pdf["normalized_stem"] or \
                   f"{last}_{year}" in pdf["normalized_stem"]:
                    return {"pdf_path": str(pdf["path"]),
                            "strategy": "AUTHOR_YEAR",
                            "confidence": CONF_AUTHOR_YEAR}

    # 5. TITLE_PEEK
    if title_text_cache is not None:
        title = (row.get("title") or row.get("paper_title") or "").strip()
        if title and len(title) > 20:
            title_lc = title.lower()
            best_score = 0.0
            best_pdf = None
            for pdf in pdfs:
                text = title_text_cache.get(pdf["path"])
                if text is None:
                    text = _first_page_text(pdf["path"])
                    title_text_cache[pdf["path"]] = text
                if not text:
                    continue
                text_lc = text.lower()
                # Fast substring test first
                if title_lc[:50] in text_lc:
                    score = 0.95
                else:
                    # Fall back to fuzzy ratio on the first 300 chars of
                    # the page vs the title
                    score = SequenceMatcher(None, title_lc,
                                             text_lc[:300]).ratio()
                if score > best_score:
                    best_score = score
                    best_pdf = pdf
            if best_pdf and best_score >= 0.70:
                return {"pdf_path": str(best_pdf["path"]),
                        "strategy": "TITLE_PEEK",
                        "confidence": min(0.95, CONF_TITLE_PEEK_BASE + 0.25 * best_score)}

    return {"pdf_path": None, "strategy": "UNPAIRED", "confidence": 0.0}


def register_sha256s(project_root: Path, pdf_paths: set[Path]) -> dict[Path, str]:
    """Ensure each PDF is in manifest.sqlite; return a path->sha map."""
    db = project_root / "state" / "manifest.sqlite"
    out: dict[Path, str] = {}
    if not pdf_paths:
        return out
    con = sqlite3.connect(db)
    try:
        for p in pdf_paths:
            sha = sha256_of(p)
            out[p] = sha
            existing = con.execute(
                "SELECT 1 FROM pdfs WHERE sha256 = ?", (sha,)
            ).fetchone()
            if existing:
                continue
            con.execute(
                """INSERT INTO pdfs (sha256, canonical_path, original_filename,
                                      bytes, added_utc, fetch_status)
                   VALUES (?, ?, ?, ?, datetime('now'), 'bootstrap')""",
                (sha, str(p), p.name, p.stat().st_size),
            )
        con.commit()
    finally:
        con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True,
                    help="Project root")
    ap.add_argument("--csv", type=Path, required=True,
                    help="Main curated CSV")
    ap.add_argument("--pdfs", type=Path, required=True,
                    help="Directory of PDFs")
    ap.add_argument("--column-map", type=Path, default=None,
                    help="JSON file mapping {user_col: canonical_col} to apply to CSV headers")
    ap.add_argument("--no-title-peek", action="store_true",
                    help="Skip the slow first-page title-extraction pass")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--delimiter", default=None)
    ap.add_argument("--encoding", default="utf-8")
    args = ap.parse_args()

    root = args.root.resolve()
    bootstrap_dir = root / "state" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    out = args.out or (bootstrap_dir / "pairing_report.json")

    col_map: dict[str, str] = {}
    if args.column_map and args.column_map.exists():
        col_map = json.loads(args.column_map.read_text())

    pdfs = index_pdfs(args.pdfs)

    # Detect delimiter if not given
    delimiter = args.delimiter
    if not delimiter:
        from migration_preflight import sniff_csv  # sibling
        sniff = sniff_csv(args.csv)
        delimiter = sniff["delimiter"]

    title_cache: dict[Path, str] | None = None if args.no_title_peek else {}

    # Pair every row
    results: list[dict] = []
    strategy_counter: Counter = Counter()
    paired_pdf_paths: set[Path] = set()

    with args.csv.open("r", encoding=args.encoding, errors="replace",
                        newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for i, raw in enumerate(reader):
            # Apply column remapping
            row = {}
            for k, v in raw.items():
                if k in col_map:
                    row[col_map[k]] = v
                row[k] = v  # keep original too
            verdict = try_pair(row, pdfs, title_cache)
            verdict["row_index"] = i
            verdict["doi"] = row.get("doi") or row.get("DOI") or None
            verdict["species"] = (row.get("canonical_species") or
                                   row.get("species") or
                                   row.get("species_name"))
            results.append(verdict)
            strategy_counter[verdict["strategy"]] += 1
            if verdict["pdf_path"]:
                paired_pdf_paths.add(Path(verdict["pdf_path"]))

    # Register hashes for all paired PDFs
    sha_map = register_sha256s(root, paired_pdf_paths)
    for r in results:
        if r["pdf_path"]:
            r["sha256"] = sha_map.get(Path(r["pdf_path"]))

    # Orphans = PDFs never paired
    all_pdf_paths = {p["path"] for p in pdfs}
    orphans = [str(p) for p in sorted(all_pdf_paths - paired_pdf_paths)]

    report = {
        "csv_path": str(args.csv),
        "pdfs_dir": str(args.pdfs),
        "rows": len(results),
        "strategy_counts": dict(strategy_counter),
        "paired_pdfs_unique": len(paired_pdf_paths),
        "orphan_pdf_count": len(orphans),
        "orphan_pdfs_sample": orphans[:25],
        "title_peek_performed": not args.no_title_peek,
        "per_row": results,
    }
    out.write_text(json.dumps(report, indent=2, default=str))

    # Short summary for stdout (the Manager reads this)
    summary = {k: v for k, v in report.items() if k != "per_row"}
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
