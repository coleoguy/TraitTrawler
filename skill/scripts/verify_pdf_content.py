#!/usr/bin/env python3
"""
PDF content verification for TraitTrawler.

Checks whether a downloaded PDF matches expected metadata (title, authors, DOI)
by extracting text from the first 2 pages and comparing against known values.
Catches wrong-PDF delivery from sources like CORE (~5% mismatch rate).

Usage:
    python3 scripts/verify_pdf_content.py --pdf path/to/file.pdf --title "Expected Title" [--authors "Smith, J"] [--doi "10.1234/example"]

Output: JSON to stdout with match result.
"""

import argparse
import json
import re
import sys


def _extract_text_from_pdf(pdf_path, max_pages=2):
    """Extract text from the first N pages of a PDF."""
    try:
        import pdfplumber
    except ImportError:
        return ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            for page in pdf.pages[:max_pages]:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        return text
    except Exception:
        return ""


def _extract_doi_from_text(text):
    """Find a DOI embedded in PDF text."""
    match = re.search(
        r"(?:doi[:\s]*|https?://doi\.org/)(10\.\d{4,5}/[^\s,;\"']+)",
        text[:5000], re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".")
    return ""


def _normalize_words(text):
    """Extract content words from text, lowercased, de-punctuated."""
    if not text:
        return set()
    clean = re.sub(r"[^A-Za-z0-9\s]", " ", text.lower())
    stop = {"the", "a", "an", "of", "in", "and", "for", "from", "with",
            "on", "to", "by", "is", "are", "was", "were", "this", "that",
            "its", "it", "be", "as", "at", "or", "not", "but", "we", "our",
            "has", "have", "been", "may", "can", "do", "does", "will",
            "no", "between", "during", "after", "before", "under", "over",
            "new", "using", "based", "role", "effect", "effects", "study"}
    words = {w for w in clean.split() if len(w) >= 3 and w not in stop}
    return words


def verify_pdf(pdf_path, expected_title=None, expected_authors=None,
               expected_doi=None):
    """Verify PDF content matches expected metadata.

    Returns dict with:
        match: bool - whether the PDF likely matches
        overlap_score: int - number of overlapping content words
        extracted_title_snippet: str - first substantial line from PDF
        extracted_doi: str - DOI found in PDF text (if any)
        reason: str - explanation of match/mismatch
    """
    text = _extract_text_from_pdf(pdf_path)

    if not text or len(text.strip()) < 100:
        return {
            "match": False,
            "overlap_score": 0,
            "extracted_title_snippet": "",
            "extracted_doi": "",
            "reason": "PDF has insufficient extractable text"
        }

    result = {
        "match": False,
        "overlap_score": 0,
        "extracted_title_snippet": "",
        "extracted_doi": "",
        "reason": ""
    }

    # Extract DOI from PDF text
    pdf_doi = _extract_doi_from_text(text)
    result["extracted_doi"] = pdf_doi

    # Extract first substantial line as title snippet
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for line in lines[:8]:
        if len(line) > 15 and not line.startswith("http"):
            result["extracted_title_snippet"] = line[:200]
            break

    # Strategy 1: DOI match (strongest signal)
    if expected_doi and pdf_doi:
        norm_expected = expected_doi.lower().strip().rstrip(".")
        norm_pdf = pdf_doi.lower().strip().rstrip(".")
        if norm_expected == norm_pdf:
            result["match"] = True
            result["reason"] = "DOI match"
            result["overlap_score"] = 100
            return result

    # Strategy 2: Title word overlap
    if expected_title:
        expected_words = _normalize_words(expected_title)
        # Search in first 3000 chars of PDF (covers title, abstract, header)
        pdf_header_words = _normalize_words(text[:3000])

        overlap = expected_words & pdf_header_words
        result["overlap_score"] = len(overlap)

        # Require at least 3 content words or 40% of title words to match
        min_required = max(2, int(len(expected_words) * 0.4))

        if len(overlap) >= min_required:
            result["match"] = True
            result["reason"] = (f"Title word overlap: {len(overlap)} of "
                                f"{len(expected_words)} content words match")
            return result

    # Strategy 3: Author name match (weaker signal, supplements title)
    if expected_authors:
        author_names = set()
        for part in re.split(r"[;,&]", expected_authors):
            tokens = part.strip().split()
            for token in tokens:
                clean = re.sub(r"[^A-Za-z]", "", token)
                if len(clean) >= 3 and clean[0].isupper():
                    author_names.add(clean.lower())

        if author_names:
            pdf_first_page = _normalize_words(text[:2000])
            author_overlap = author_names & pdf_first_page
            if len(author_overlap) >= 1 and result["overlap_score"] >= 1:
                result["match"] = True
                result["reason"] = (f"Author+title partial match: "
                                    f"{len(author_overlap)} author names + "
                                    f"{result['overlap_score']} title words")
                return result

    # No match found
    expected_words = _normalize_words(expected_title or "")
    min_needed = max(2, int(len(expected_words) * 0.4))
    result["match"] = False
    result["reason"] = (f"Insufficient match: {result['overlap_score']} title "
                        f"word(s) overlap (need {min_needed})")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Verify PDF content matches expected metadata"
    )
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--title", default="", help="Expected paper title")
    parser.add_argument("--authors", default="", help="Expected authors")
    parser.add_argument("--doi", default="", help="Expected DOI")
    args = parser.parse_args()

    result = verify_pdf(args.pdf, args.title, args.authors, args.doi)
    json.dump(result, sys.stdout, indent=2)
    print()
    sys.exit(0 if result["match"] else 1)


if __name__ == "__main__":
    main()
