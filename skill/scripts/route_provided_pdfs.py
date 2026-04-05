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


def _crossref_lookup(doi):
    """Query Crossref for clean metadata given a DOI. Returns dict or None."""
    import urllib.request
    import urllib.error
    try:
        url = f"https://api.crossref.org/works/{urllib.request.quote(doi, safe='')}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "TraitTrawler/5.0 (mailto:traittrawler@example.com)"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        item = data.get("message", {})
        meta = {"doi": doi}
        # Title
        titles = item.get("title", [])
        if titles:
            meta["title"] = titles[0]
        # Authors
        authors = item.get("author", [])
        if authors:
            parts = []
            for a in authors:
                family = a.get("family", "")
                given = a.get("given", "")
                if family:
                    parts.append(f"{family}, {given}" if given else family)
            meta["authors"] = "; ".join(parts)
        # Year
        for date_field in ("published-print", "published-online",
                           "issued", "created"):
            dp = item.get(date_field, {}).get("date-parts", [[]])
            if dp and dp[0] and dp[0][0]:
                meta["year"] = str(dp[0][0])
                break
        # Journal
        containers = item.get("container-title", [])
        if containers:
            meta["journal"] = containers[0]
        return meta
    except Exception:
        return None


def _extract_meta_from_filename(filename):
    """Try to extract author and year from the original filename.

    Common patterns: smith1951.pdf, dutrillaux2013.pdf, angus2020.pdf,
    cabral-de-mello2011.pdf, Galian-1995-Heredity.pdf
    """
    stem = os.path.splitext(filename)[0]
    # Remove common prefixes/suffixes
    stem = re.sub(r'\s*\(\d+\)\s*$', '', stem)  # " (1)" duplicates
    stem = re.sub(r'^[\d._]+', '', stem)  # leading DOI-like numbers

    meta = {}

    # Pattern: name followed by 4-digit year
    m = re.match(r'^([a-zA-Z][a-zA-Z_-]+?)\s*[-_]?\s*((?:19|20)\d{2})', stem)
    if m:
        author_part = m.group(1).strip('-_ ')
        meta["authors"] = author_part.replace('_', ' ').replace('-', ' ').title()
        meta["year"] = m.group(2)
        return meta

    # Pattern: Year-Author or Author-Year-Journal
    parts = re.split(r'[-_]', stem)
    for p in parts:
        if re.match(r'^(19|20)\d{2}$', p):
            meta["year"] = p
        elif re.match(r'^[A-Z][a-z]{2,}$', p) and "authors" not in meta:
            meta["authors"] = p

    return meta if meta else {}


def _extract_doi_from_pdf(pdf_path):
    """Extract DOI and metadata from a PDF.

    Strategy:
    1. Scan PDF text for DOI
    2. If DOI found → query Crossref for clean metadata (preferred)
    3. If Crossref fails or no DOI → try filename-based extraction
    4. Last resort → parse PDF text (unreliable)
    """
    try:
        import pdfplumber
    except ImportError:
        return None, _extract_meta_from_filename(os.path.basename(pdf_path))

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = ""
            for page in pdf.pages[:2]:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception:
        return None, _extract_meta_from_filename(os.path.basename(pdf_path))

    if not text.strip():
        return None, _extract_meta_from_filename(os.path.basename(pdf_path))

    meta = {}

    # Step 1: Find DOI in PDF text
    doi_match = re.search(
        r"(?:doi[:\s]*|https?://doi\.org/)(10\.\d{4,5}/[^\s,;\"']+)",
        text[:5000], re.IGNORECASE)
    if doi_match:
        doi = doi_match.group(1).rstrip(".")
        meta["doi"] = doi

        # Step 2: Crossref lookup (clean, reliable metadata)
        cr = _crossref_lookup(doi)
        if cr:
            meta.update(cr)
            return doi, meta

    # Step 3: Try filename-based extraction
    fn_meta = _extract_meta_from_filename(os.path.basename(pdf_path))
    if fn_meta:
        for k, v in fn_meta.items():
            if k not in meta:
                meta[k] = v

    # Step 4: PDF text fallback (only for fields still missing)
    if "year" not in meta:
        year_match = re.search(r"\b(19\d{2}|20[0-2]\d)\b", text[:2000])
        if year_match:
            meta["year"] = year_match.group(1)

    # Only try PDF text for title/authors if we have nothing else
    if "title" not in meta and "authors" not in meta:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        # Title: skip short lines, headers, dates, URLs
        for line in lines[:8]:
            if (len(line) > 20 and not line.startswith("http")
                    and not re.match(r'^(Received|Accepted|Published|Vol\.|©)',
                                     line, re.IGNORECASE)
                    and not re.match(r'^\d', line)):
                meta["title"] = line[:200]
                break

    return meta.get("doi"), meta


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
        return {"found": 0, "skipped_hash": 0, "skipped_processed": 0,
                "linked": 0, "queued": 0, "skipped_existing": 0}

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

    # Load processed.json for pre-extraction dedup
    processed = safe_read_json(str(state_dir / "processed.json"), default={})

    skipped_hash = 0
    skipped_processed = 0
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

        # 2b. Check processed.json BEFORE extraction (catches papers
        #     already extracted in prior sessions, including no-data)
        already_done = False
        if doi and doi in processed:
            prior = processed[doi]
            if isinstance(prior, dict) and prior.get("outcome") in (
                    "extracted", "no_data", "imported", "triage_rejected",
                    "lead_needs_fulltext"):
                already_done = True
        if not already_done:
            title = (meta.get("title", "") or "").strip()
            if title:
                title_key = f"title:{title[:120]}"
                if title_key in processed:
                    prior = processed[title_key]
                    if isinstance(prior, dict) and prior.get("outcome") in (
                            "extracted", "no_data", "imported",
                            "triage_rejected"):
                        already_done = True

        # 3. Build standardized path
        abs_path, rel_path = build_source_path(
            project_root,
            authors=meta.get("authors", ""),
            year=meta.get("year", ""),
            title=meta.get("title", ""),
            doi=doi,
        )

        # 4. Move PDF to pdfs/ (always — even if skipping extraction,
        #    the user's PDF should be in the standardized library)
        shutil.move(str(pdf), abs_path)

        # 4b. If already processed, register hash and skip handoff
        if already_done:
            skipped_processed += 1
            registry[digest] = {
                "filename": pdf.name,
                "standardized": rel_path,
                "doi": doi or "",
                "outcome": "skipped_already_processed",
                "session_id": session_id or "",
                "processed_at": now_iso(),
            }
            append_jsonl(str(log_path), {
                "event": "provided_pdf_routed",
                "original": pdf.name,
                "standardized": rel_path,
                "doi": doi or "",
                "outcome": "skipped_already_processed",
                "timestamp": now_iso(),
            })
            continue

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
        "skipped_processed": skipped_processed,
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
