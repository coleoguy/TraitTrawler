#!/usr/bin/env python3
"""
Route user-provided PDFs into the TraitTrawler pipeline.

For each PDF in provided_pdfs/:
1. Hash-check against processed_pdfs.json (skip duplicates)
2. Extract DOI from PDF text (first 2 pages)
3. Generate standardized name via build_source_path()
4. Move to pdfs/ with standardized name
5. Check if DOI already in results.csv:
   - YES with empty pdf_path → update pdf_path (no re-extraction)
   - YES with pdf_path → skip (already linked)
   - NO → create handoff for extraction
6. Register hash

Usage:
    python3 scripts/route_provided_pdfs.py --project-root .
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
from pathlib import Path

# Allow imports from same directory
sys.path.insert(0, os.path.dirname(__file__))
from state_utils import safe_read_json, safe_write_json, now_iso, append_jsonl
from pdf_utils import build_source_path


def _hash_pdf(path):
    """SHA-256 of file contents."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_doi_from_pdf(pdf_path):
    """Read first 2 pages, extract DOI if embedded."""
    try:
        import pdfplumber
    except ImportError:
        return None, {}

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = ""
            for page in pdf.pages[:2]:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        if not text.strip():
            return None, {}

        meta = {}

        # DOI
        doi_match = re.search(
            r"(?:doi[:\s]*|https?://doi\.org/)(10\.\d{4,5}/[^\s,;\"']+)",
            text[:3000], re.IGNORECASE)
        if doi_match:
            meta["doi"] = doi_match.group(1).rstrip(".")

        # Title (first substantial line)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines[:5]:
            if len(line) > 10 and not line.startswith("http"):
                meta["title"] = line
                break

        # Year
        year_match = re.search(r"\b(19\d{2}|20[0-2]\d)\b", text[:2000])
        if year_match:
            meta["year"] = year_match.group(1)

        # Authors
        for line in lines[:8]:
            if re.search(r"[A-Z][a-z]+,?\s+[A-Z]\.?", line):
                meta["authors"] = line
                break

        return meta.get("doi"), meta
    except Exception:
        return None, {}


def route_provided_pdfs(project_root, session_id=None):
    """Route all PDFs in provided_pdfs/ into the pipeline.

    Returns JSON summary.
    """
    root = Path(project_root).resolve()
    provided_dir = root / "provided_pdfs"
    pdfs_dir = root / "pdfs"
    ready_dir = root / "ready_for_extraction"
    state_dir = root / "state"
    log_path = state_dir / "run_log.jsonl"

    pdfs_dir.mkdir(exist_ok=True)
    ready_dir.mkdir(exist_ok=True)

    # Find PDFs (skip done/ subdirectory)
    pdf_files = []
    for f in provided_dir.iterdir():
        if f.suffix.lower() == ".pdf" and f.is_file():
            pdf_files.append(f)

    if not pdf_files:
        return {"found": 0, "skipped_hash": 0, "linked": 0,
                "queued": 0, "skipped_existing": 0}

    # Load hash registry
    registry_path = state_dir / "processed_pdfs.json"
    registry = safe_read_json(str(registry_path), default={})

    # Load results.csv DOI → row indices + pdf_path status
    results_path = root / "results.csv"
    all_rows = []
    fieldnames = []
    doi_rows = {}  # doi → [(index, has_pdf_path)]
    if results_path.exists():
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames) if reader.fieldnames else []
            for i, row in enumerate(reader):
                all_rows.append(dict(row))
                doi = row.get("doi", "").strip()
                if doi:
                    if doi not in doi_rows:
                        doi_rows[doi] = []
                    doi_rows[doi].append((i, bool(row.get("pdf_path", "").strip())))

    # Ensure pdf_path in fieldnames
    if fieldnames and "pdf_path" not in fieldnames:
        if "pdf_source" in fieldnames:
            idx = fieldnames.index("pdf_source") + 1
            fieldnames.insert(idx, "pdf_path")
        else:
            fieldnames.append("pdf_path")

    skipped_hash = 0
    linked = 0
    queued = 0
    skipped_existing = 0
    csv_modified = False

    for pdf in pdf_files:
        # 1. Hash check
        digest = _hash_pdf(str(pdf))
        if digest in registry:
            skipped_hash += 1
            continue

        # 2. Extract DOI from PDF
        doi, meta = _extract_doi_from_pdf(pdf)

        # 3. Build standardized path
        abs_path, rel_path = build_source_path(
            project_root,
            authors=meta.get("authors", ""),
            year=meta.get("year", ""),
            title=meta.get("title", ""),
            doi=doi,
        )

        # 4. Move PDF to pdfs/
        shutil.move(str(pdf), abs_path)

        # 5. Check DOI in results.csv
        outcome = "queued_for_extraction"
        if doi and doi in doi_rows:
            entries = doi_rows[doi]
            has_any_without_pdf = any(not has_pdf for _, has_pdf in entries)
            has_all_with_pdf = all(has_pdf for _, has_pdf in entries)

            if has_all_with_pdf:
                # Already fully linked
                outcome = "pdf_already_linked"
                skipped_existing += 1
            elif has_any_without_pdf:
                # Update pdf_path on rows missing it
                for idx, has_pdf in entries:
                    if not has_pdf:
                        all_rows[idx]["pdf_path"] = rel_path
                outcome = "pdf_linked"
                linked += 1
                csv_modified = True
        else:
            # New paper — create handoff
            doi_safe = re.sub(r"[/.]", "_", doi) if doi else Path(abs_path).stem
            handoff = {
                "doi": doi or "",
                "title": meta.get("title", ""),
                "authors": meta.get("authors", ""),
                "year": meta.get("year", ""),
                "pdf_path": rel_path,
                "pdf_source": "user_provided",
                "source_query": "provided_pdf",
                "fetched_at": now_iso(),
            }
            handoff_path = ready_dir / f"{doi_safe}.json"
            with open(handoff_path, "w", encoding="utf-8") as f:
                json.dump(handoff, f, indent=2)
            outcome = "queued_for_extraction"
            queued += 1

        # 6. Register hash
        registry[digest] = {
            "filename": pdf.name,
            "standardized": rel_path,
            "doi": doi or "",
            "outcome": outcome,
            "session_id": session_id or "",
            "processed_at": now_iso(),
        }

        # Log
        append_jsonl(str(log_path), {
            "event": "provided_pdf_routed",
            "original": pdf.name,
            "standardized": rel_path,
            "doi": doi or "",
            "outcome": outcome,
            "timestamp": now_iso(),
        })

    # Write updated registry
    safe_write_json(str(registry_path), registry)

    # Write updated results.csv if we linked any
    if csv_modified and all_rows and fieldnames:
        tmp = str(results_path) + ".route.tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        os.replace(tmp, str(results_path))

    return {
        "found": len(pdf_files),
        "skipped_hash": skipped_hash,
        "linked": linked,
        "queued": queued,
        "skipped_existing": skipped_existing,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Route provided PDFs into TraitTrawler pipeline")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args()

    result = route_provided_pdfs(args.project_root, args.session_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
