#!/usr/bin/env python3
"""
PDF OCR quality assessment for TraitTrawler.

Checks whether a PDF has usable extracted text by analyzing the first
few pages with pdfplumber. Returns a quality classification that the
Extractor uses to decide extraction strategy.

Usage:
    python3 scripts/ocr_quality_check.py --pdf pdfs/Author-2020-Paper-1.pdf

Output: JSON to stdout.
"""

import argparse
import json
import os
import re
import sys


def check_ocr_quality(pdf_path, max_pages=3):
    """Assess OCR/text quality of a PDF.

    Returns dict with:
      ocr_quality: "good" | "degraded" | "unusable"
      char_count: total characters across sampled pages
      non_ascii_ratio: fraction of non-ASCII characters
      avg_word_length: average word length
      pages_checked: number of pages analyzed
    """
    try:
        import pdfplumber
    except ImportError:
        # If pdfplumber isn't available, assume good and let Extractor
        # use the Read tool for native PDF reading
        return {
            "ocr_quality": "good",
            "reason": "pdfplumber not available, assuming good",
            "char_count": -1,
            "non_ascii_ratio": 0.0,
            "avg_word_length": 0.0,
            "pages_checked": 0,
        }

    if not os.path.isfile(pdf_path):
        return {
            "ocr_quality": "unusable",
            "reason": f"file not found: {pdf_path}",
            "char_count": 0,
            "non_ascii_ratio": 0.0,
            "avg_word_length": 0.0,
            "pages_checked": 0,
        }

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as e:
        return {
            "ocr_quality": "unusable",
            "reason": f"cannot open PDF: {e}",
            "char_count": 0,
            "non_ascii_ratio": 0.0,
            "avg_word_length": 0.0,
            "pages_checked": 0,
        }

    total_chars = 0
    total_non_ascii = 0
    total_words = 0
    total_word_len = 0
    pages_checked = 0

    try:
        for i, page in enumerate(pdf.pages[:max_pages]):
            text = page.extract_text() or ""
            total_chars += len(text)

            # Count non-ASCII characters (OCR artifacts often produce these)
            non_ascii = sum(1 for c in text if ord(c) > 127)
            total_non_ascii += non_ascii

            # Word statistics
            words = re.findall(r'[a-zA-Z]+', text)
            total_words += len(words)
            total_word_len += sum(len(w) for w in words)
            pages_checked += 1
    finally:
        pdf.close()

    if pages_checked == 0:
        return {
            "ocr_quality": "unusable",
            "reason": "no pages in PDF",
            "char_count": 0,
            "non_ascii_ratio": 0.0,
            "avg_word_length": 0.0,
            "pages_checked": 0,
        }

    chars_per_page = total_chars / pages_checked
    non_ascii_ratio = total_non_ascii / max(total_chars, 1)
    avg_word_length = total_word_len / max(total_words, 1)

    # Classification
    reasons = []
    if chars_per_page < 100:
        quality = "unusable"
        reasons.append(f"only {chars_per_page:.0f} chars/page")
    elif non_ascii_ratio > 0.40:
        quality = "unusable"
        reasons.append(f"non-ASCII ratio {non_ascii_ratio:.2f}")
    elif non_ascii_ratio > 0.15 or avg_word_length < 3.0:
        quality = "degraded"
        if non_ascii_ratio > 0.15:
            reasons.append(f"non-ASCII ratio {non_ascii_ratio:.2f}")
        if avg_word_length < 3.0:
            reasons.append(f"avg word length {avg_word_length:.1f}")
    else:
        quality = "good"

    return {
        "ocr_quality": quality,
        "reason": "; ".join(reasons) if reasons else "text quality acceptable",
        "char_count": total_chars,
        "non_ascii_ratio": round(non_ascii_ratio, 3),
        "avg_word_length": round(avg_word_length, 1),
        "pages_checked": pages_checked,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Check PDF OCR/text quality")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--max-pages", type=int, default=3,
                        help="Number of pages to check (default: 3)")
    args = parser.parse_args()

    result = check_ocr_quality(args.pdf, args.max_pages)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
