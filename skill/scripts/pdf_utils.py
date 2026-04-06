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


def _extract_representative_word(title):
    """Pick one taxonomically informative word from a paper title.

    Prefers genus/family-like words (capitalized, Latin-ish).
    Falls back to the longest content word.
    """
    if not title:
        return "paper"
    # Remove parenthetical content and punctuation
    clean = re.sub(r"\([^)]*\)", "", title)
    clean = re.sub(r"[^A-Za-z\s]", "", clean)
    words = clean.split()
    if not words:
        return "paper"

    # Skip very common words
    stop = {"the", "a", "an", "of", "in", "and", "for", "from", "with",
            "on", "to", "by", "new", "data", "study", "analysis", "review",
            "notes", "some", "two", "three", "first", "species", "genus",
            "family", "order", "class", "chromosome", "chromosomes",
            "karyotype", "karyotypes", "number", "numbers", "cytogenetic",
            "cytogenetics", "description", "records", "report", "results"}

    # Prefer capitalized words that look taxonomic (often genus/family names)
    # Sort by length descending — longer taxonomic names are more informative
    taxonomic = [w for w in words
                 if w[0].isupper() and len(w) >= 4 and w.lower() not in stop]
    if taxonomic:
        taxonomic.sort(key=len, reverse=True)
        return _sanitize(taxonomic[0], max_len=20)

    # Fall back to longest non-stop word (minimum 3 chars)
    content = [w for w in words if w.lower() not in stop and len(w) >= 3]
    if content:
        content.sort(key=len, reverse=True)
        return _sanitize(content[0], max_len=20)

    # Last resort: longest word of any kind
    words.sort(key=len, reverse=True)
    return _sanitize(words[0], max_len=20) if words[0] and len(words[0]) >= 2 else "paper"


def _extract_last_name(authors_str):
    """Extract first author's last name from an authors string.

    Handles formats: "Smith, J; Jones, B" or "Smith J, Jones B"
    or "J. Smith" or "Smith" or ["Smith, J", "Jones, B"].
    """
    if not authors_str:
        return "unknown"
    if isinstance(authors_str, list):
        authors_str = authors_str[0] if authors_str else "unknown"
    # Take first author (before first ; or second ,)
    first = authors_str.split(";")[0].strip()
    # "Smith, J" → "Smith"
    if "," in first:
        return _sanitize(first.split(",")[0].strip(), max_len=20)
    # "J. Smith" or "J Smith" → "Smith" (last token)
    parts = first.split()
    if len(parts) >= 2:
        # If first part is initials, take last part
        if len(parts[0]) <= 2 or parts[0].endswith("."):
            return _sanitize(parts[-1], max_len=20)
    return _sanitize(parts[0] if parts else "unknown", max_len=20)


def build_source_path(project_root, first_author=None, authors=None,
                      year=None, title=None, doi=None):
    """Construct the standardized PDF path in source/.

    Naming: Lastname-Year-RepresentativeWord-a.pdf
    The index letter (a, b, c...) avoids collisions.

    Returns (absolute_path, relative_path) tuple.
    Example: ("/.../pdfs/Smith-2003-Chrysolina-a.pdf",
              "pdfs/Smith-2003-Chrysolina-a.pdf")
    """
    root = Path(project_root).resolve()
    pdfs_dir = root / "pdfs"
    pdfs_dir.mkdir(exist_ok=True)

    # Extract components
    if first_author:
        lastname = _sanitize(first_author, max_len=20)
    elif authors:
        lastname = _extract_last_name(authors)
    else:
        lastname = "unknown"

    yr = str(year) if year else "noYear"
    word = _extract_representative_word(title)

    # Find next available index letter
    base = f"{lastname}-{yr}-{word}"
    for letter in "abcdefghijklmnopqrstuvwxyz":
        candidate = f"{base}-{letter}.pdf"
        full = pdfs_dir / candidate
        if not full.exists():
            rel = Path("pdfs") / candidate
            return str(full), str(rel)

    # Exhausted letters — use DOI hash as tiebreaker
    import hashlib
    h = hashlib.md5((doi or title or "").encode()).hexdigest()[:6]
    candidate = f"{base}-{h}.pdf"
    rel = Path("pdfs") / candidate
    full = pdfs_dir / candidate
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
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                results.append((str(src), str(dst), True))
            except OSError as e:
                print(f"WARNING: Failed to move {src} -> {dst}: {e}",
                      file=sys.stderr)
                results.append((str(src), str(dst), False))

    return results


def bootstrap_pdfs(project_root, dry_run=True):
    """Scan for existing PDFs, rename into source/, and link to results.csv.

    Searches: pdfs/**/*.pdf, provided_pdfs/**/*.pdf, *.pdf in root.
    For each PDF:
    1. Try to match to a results.csv record by DOI (extracted from filename
       or from processed.json metadata)
    2. Copy/rename into source/ with standardized naming
    3. Update the pdf_path column in results.csv for matched records
    4. Mark matched DOIs in processed.json as having a PDF

    Returns JSON summary.
    """
    import json
    root = Path(project_root).resolve()
    pdfs_dir = root / "pdfs"
    pdfs_dir.mkdir(exist_ok=True)

    # Collect all existing PDFs from everywhere
    pdf_files = []
    for search_dir in ["pdfs", "provided_pdfs", "provided_pdfs/done"]:
        d = root / search_dir
        if d.exists():
            pdf_files.extend(d.rglob("*.pdf"))
    # Also check root-level PDFs
    for f in root.iterdir():
        if f.suffix.lower() == ".pdf" and f.is_file():
            pdf_files.append(f)

    if not pdf_files:
        return {"pdfs_found": 0, "linked": 0, "copied": 0, "unmatched": 0}

    # Build DOI → record metadata from results.csv
    results_path = root / "results.csv"
    doi_to_meta = {}  # doi → {first_author, year, title, row_indices}
    all_rows = []
    fieldnames = []
    if results_path.exists():
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames) if reader.fieldnames else []
            for i, row in enumerate(reader):
                all_rows.append(dict(row))
                doi = row.get("doi", "").strip()
                if doi and doi not in doi_to_meta:
                    doi_to_meta[doi] = {
                        "first_author": (row.get("first_author", "") or
                                         row.get("paper_authors", "")),
                        "year": row.get("paper_year", ""),
                        "title": row.get("paper_title", ""),
                        "row_indices": [],
                    }
                if doi:
                    doi_to_meta[doi]["row_indices"].append(i)

    # Build DOI → metadata from processed.json (for PDFs not yet in results)
    proc_path = root / "state" / "processed.json"
    proc_data = {}
    if proc_path.exists():
        try:
            with open(proc_path, "r", encoding="utf-8") as f:
                proc_data = json.load(f)
            if not isinstance(proc_data, dict):
                proc_data = {}
        except (json.JSONDecodeError, OSError):
            pass

    # Build DOI → handoff metadata from ready_for_extraction/ and state/dealt/
    handoff_meta = {}
    for hdir in ["ready_for_extraction", "state/dealt"]:
        hpath = root / hdir
        if hpath.exists():
            for hf in hpath.glob("*.json"):
                try:
                    with open(hf, "r", encoding="utf-8") as f:
                        hdata = json.load(f)
                    hdoi = hdata.get("doi", "").strip()
                    if hdoi:
                        handoff_meta[hdoi] = {
                            "authors": hdata.get("authors", ""),
                            "year": hdata.get("year", ""),
                            "title": hdata.get("title", ""),
                            "pdf_path": hdata.get("pdf_path", ""),
                        }
                except (json.JSONDecodeError, OSError):
                    pass

    # Try to extract DOI from PDF filename patterns
    def _guess_doi_from_filename(name):
        """Try to reverse-engineer DOI from safe-filename patterns."""
        # Pattern: 10_1234_example → 10.1234/example
        m = re.match(r"^(10_\d{4,5})_(.+?)(?:_\d{8}.*)?\.pdf$", name)
        if m:
            prefix = m.group(1).replace("_", ".", 1)
            suffix = m.group(2).replace("_", ".", 1).replace("_", "/", 1)
            return f"{prefix}/{suffix}"
        return None

    def _extract_citation_from_pdf(pdf_path):
        """Read first 2 pages of a PDF and extract author, year, title.

        Returns dict with 'authors', 'year', 'title' (any may be empty).
        """
        try:
            import pdfplumber
        except ImportError:
            return {}
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                text = ""
                for page in pdf.pages[:2]:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
            if not text.strip():
                return {}

            result = {}
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            # Title is usually the first substantial line (>10 chars)
            for line in lines[:5]:
                if len(line) > 10 and not line.startswith("http"):
                    result["title"] = line
                    break

            # Year: find 4-digit number in range 1900-2030
            year_match = re.search(r"\b(19\d{2}|20[0-2]\d)\b", text[:2000])
            if year_match:
                result["year"] = year_match.group(1)

            # DOI embedded in text
            doi_match = re.search(
                r"(?:doi[:\s]*|https?://doi\.org/)(10\.\d{4,5}/[^\s,;\"']+)",
                text[:3000], re.IGNORECASE)
            if doi_match:
                result["doi"] = doi_match.group(1).rstrip(".")

            # Authors: look for patterns like "Lastname, F." or "F. Lastname"
            # in lines before the abstract
            for line in lines[:8]:
                if re.search(r"[A-Z][a-z]+,?\s+[A-Z]\.?", line):
                    result["authors"] = line
                    break

            return result
        except Exception:
            return {}

    def _fuzzy_match_citation(citation, doi_to_meta):
        """Try to match extracted citation to a results.csv record.

        Matches by: year + first-author-lastname substring match +
        species confirmation from PDF text.

        Returns (doi, meta) tuple or (None, None).
        """
        cite_year = str(citation.get("year", ""))
        cite_authors = (citation.get("authors", "") or "").lower()
        cite_title = (citation.get("title", "") or "").lower()

        if not cite_year and not cite_authors:
            return None, None

        candidates = []
        for doi, meta in doi_to_meta.items():
            score = 0
            meta_year = str(meta.get("year", ""))
            meta_author = (meta.get("first_author", "") or "").lower()
            meta_title = (meta.get("title", "") or "").lower()

            # Year match
            if cite_year and meta_year and cite_year == meta_year:
                score += 2

            # Author match (last name appears in citation author line)
            if meta_author and meta_author in cite_authors:
                score += 3
            elif cite_authors:
                # Try first token of cite_authors against meta_author
                first_cite = cite_authors.split(",")[0].split()
                if first_cite:
                    first_word = first_cite[0].strip(".,;")
                    if first_word and first_word in meta_author:
                        score += 2

            # Title word overlap
            if cite_title and meta_title:
                cite_words = set(cite_title.split()) - {"the", "a", "of",
                    "in", "and", "for", "from", "with", "on", "to", "by"}
                meta_words = set(meta_title.split()) - {"the", "a", "of",
                    "in", "and", "for", "from", "with", "on", "to", "by"}
                overlap = cite_words & meta_words
                if len(overlap) >= 3:
                    score += 3
                elif len(overlap) >= 1:
                    score += 1

            if score >= 4:  # Need year + author OR strong title match
                candidates.append((score, doi, meta))

        if not candidates:
            return None, None

        # Return best match
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_doi, best_meta = candidates[0]
        return best_doi, best_meta

    linked = 0
    copied = 0
    unmatched = 0
    unmatched_files = []

    pdfs_dir = root / "pdfs"
    pdfs_dir.mkdir(exist_ok=True)

    # Track which standardized names are already claimed
    _existing_standardized = set()
    for f in pdfs_dir.iterdir():
        if f.suffix.lower() == ".pdf" and re.match(
                r"^[A-Za-z]+-\d{4}-[A-Za-z]+-[a-z]\.pdf$", f.name):
            _existing_standardized.add(str(f))

    for pdf in pdf_files:
        # Skip PDFs already in pdfs/ with standardized names
        if str(pdf) in _existing_standardized:
            continue

        # Strategy 1: Match by DOI from filename
        doi = _guess_doi_from_filename(pdf.name)
        meta = None

        if doi and doi in doi_to_meta:
            meta = doi_to_meta[doi]
        elif doi and doi in handoff_meta:
            meta = handoff_meta[doi]

        # Strategy 2: Read PDF header, extract citation, fuzzy-match
        if not meta:
            citation = _extract_citation_from_pdf(pdf)
            if citation:
                # Check if PDF contains a DOI we can use directly
                if citation.get("doi"):
                    cdoi = citation["doi"]
                    if cdoi in doi_to_meta:
                        doi = cdoi
                        meta = doi_to_meta[cdoi]
                    elif cdoi in handoff_meta:
                        doi = cdoi
                        meta = handoff_meta[cdoi]

                # Fall back to fuzzy citation matching
                if not meta and doi_to_meta:
                    matched_doi, matched_meta = _fuzzy_match_citation(
                        citation, doi_to_meta)
                    if matched_doi:
                        doi = matched_doi
                        meta = matched_meta

                # Even if no match to results.csv, use extracted citation
                # for naming (still copy to source/ for future linking)
                if not meta and citation.get("authors"):
                    meta = {
                        "first_author": citation.get("authors", ""),
                        "year": citation.get("year", ""),
                        "title": citation.get("title", ""),
                    }
                    doi = citation.get("doi", "")

        if meta:
            # Build standardized path in pdfs/
            abs_path, rel_path = build_source_path(
                project_root,
                authors=meta.get("first_author") or meta.get("authors", ""),
                year=meta.get("year"),
                title=meta.get("title"),
                doi=doi,
            )

            if not dry_run:
                # If PDF is already in pdfs/, rename in place; otherwise copy
                if str(pdf.parent) == str(pdfs_dir) or str(pdf).startswith(str(pdfs_dir)):
                    # Already in pdfs/ — rename to standardized name
                    if str(pdf) != abs_path:
                        shutil.copy2(str(pdf), abs_path)
                        # Don't delete original yet — user can clean up later
                else:
                    # Outside pdfs/ — copy in
                    shutil.copy2(str(pdf), abs_path)

                # Update results.csv rows with new pdf_path
                if doi and doi in doi_to_meta:
                    for idx in doi_to_meta[doi]["row_indices"]:
                        all_rows[idx]["pdf_path"] = rel_path
                    linked += 1
                else:
                    copied += 1

                # Mark in processed.json
                if doi and doi in proc_data and isinstance(proc_data[doi], dict):
                    proc_data[doi]["pdf_path"] = rel_path
            else:
                if doi and doi in doi_to_meta:
                    linked += 1
                else:
                    copied += 1
        else:
            unmatched += 1
            unmatched_files.append(str(pdf.relative_to(root)))

    # Write updated results.csv
    if not dry_run and all_rows and fieldnames:
        # Ensure pdf_path is in fieldnames
        if "pdf_path" not in fieldnames:
            # Insert after pdf_source if present
            if "pdf_source" in fieldnames:
                idx = fieldnames.index("pdf_source") + 1
                fieldnames.insert(idx, "pdf_path")
            else:
                fieldnames.append("pdf_path")

        tmp_path = str(results_path) + ".bootstrap.tmp"
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        os.replace(tmp_path, str(results_path))

    # Write updated processed.json
    if not dry_run and proc_data:
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from state_utils import safe_write_json
            safe_write_json(str(proc_path), proc_data)
        except Exception:
            pass

    result = {
        "pdfs_found": len(pdf_files),
        "linked": linked,
        "copied": copied,
        "unmatched": unmatched,
        "dry_run": dry_run,
    }
    if unmatched_files and len(unmatched_files) <= 20:
        result["unmatched_files"] = unmatched_files
    elif unmatched_files:
        result["unmatched_files_sample"] = unmatched_files[:10]
        result["unmatched_files_total"] = len(unmatched_files)

    return result


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler PDF path utilities")
    parser.add_argument("--project-root", default=".", help="Project root directory")

    sub = parser.add_subparsers(dest="command")

    # check (legacy)
    p_check = sub.add_parser("check", help="Check for misplaced PDFs")
    p_check.add_argument("--fix", action="store_true",
                         help="Move misplaced PDFs to correct locations")

    # bootstrap
    p_boot = sub.add_parser("bootstrap",
                            help="Scan existing PDFs, rename into source/, "
                                 "link to results.csv")
    p_boot.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without making changes")

    args = parser.parse_args()
    root = Path(args.project_root).resolve()

    if not root.exists():
        print(f"Error: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    if args.command == "bootstrap":
        import json
        result = bootstrap_pdfs(str(root), dry_run=args.dry_run)
        print(json.dumps(result, indent=2))

    elif args.command == "check":
        misplaced = check_misplaced_pdfs(root)
        if not misplaced:
            print("No misplaced PDFs found in project root.")
            sys.exit(0)
        print(f"Found {len(misplaced)} PDF(s) in project root:")
        for item in misplaced:
            dest = item["suggestion"] or f"pdfs/unknown/{item['name']}"
            print(f"  {item['name']} -> {dest}")
        if getattr(args, 'fix', False):
            results = relocate_misplaced_pdfs(root, dry_run=False)
            moved = sum(1 for _, _, m in results if m)
            print(f"\nMoved {moved} file(s).")
        else:
            print("\nRun with --fix to move them.")
    else:
        # No subcommand — show help
        parser.print_help()


if __name__ == "__main__":
    main()
