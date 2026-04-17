#!/usr/bin/env python3
"""Code-execution pre-filter for triage.

Anthropic's 'Code Execution with MCP' engineering post demonstrates
~98% token reduction by running deterministic code BEFORE sending data
to Claude. For TraitTrawler's triage stage: instead of sending a full
PDF (~20-80k tokens) to Haiku so it can decide which pages matter, we
run a keyword/regex filter here and return only the matching pages
plus surrounding context. Haiku then reads ~2-5k tokens per paper
instead of ~20-80k.

Filter sources:
  1. Trait vocabulary from state/trait_profile.md (synonyms, canonical
     names, notation strings, common units). Built at project init by
     the trait_learner.
  2. Optional user-supplied keywords via --keywords "word1,word2".
  3. Always-on structural signals: presence of "Table", "Figure",
     "Results" section headers, species-binomial-looking tokens.

Output per paper:
  - pages_with_hits: list of 1-indexed pages that contain trait signal
  - hit_summary: per-page count of different signal types
  - confidence: heuristic 0-1 score on whether this paper has
    extractable data (low means likely not relevant; skip extractor)
  - context_snippet: 100 chars around each hit for the triage agent to
    read (total across all hits, capped at ~4000 chars per paper)

Usage:
  python triage_prefilter.py --sha256 <sha> --project-root <root>
  python triage_prefilter.py --path <pdf> --keywords "karyotype,2n,chromosome"
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

try:
    import pdfplumber  # type: ignore
except ImportError:
    print("pdfplumber required", file=sys.stderr)
    sys.exit(3)


# ------------------------------------------------------------------
# Extract trait vocabulary from trait_profile.md
# ------------------------------------------------------------------


def extract_vocab_from_profile(profile_md: str) -> list[str]:
    """Pull keyword candidates from sections 1, 2, 4 of trait_profile.md.

    §1 = Canonical Name and Synonyms (all synonyms become keywords)
    §2 = Notation Conventions (literal notation strings)
    §4 = Valid Biological Ranges (unit strings)

    Conservative: only adds strings that are reasonably specific
    (3+ chars, not common English stopwords).
    """
    STOPWORDS = {"the", "and", "for", "per", "with", "from", "into",
                 "over", "under", "also", "are", "was", "were", "has",
                 "have", "had", "this", "that", "these", "those",
                 "observed", "reported", "described"}
    vocab: set[str] = set()
    # Look for bullet lines in section headers
    current_section = None
    for line in profile_md.splitlines():
        m = re.match(r"^##\s+(\d+)\.\s+", line)
        if m:
            current_section = m.group(1)
            continue
        if current_section not in ("1", "2", "4"):
            continue
        # Match backtick-quoted strings (notation)
        for quoted in re.findall(r"`([^`]+)`", line):
            if 3 <= len(quoted) <= 40:
                vocab.add(quoted.lower())
        # Bullet items
        bullet = re.match(r"^\s*-\s+(.+)$", line)
        if bullet:
            for token in re.split(r"[,;|]\s*", bullet.group(1)):
                token = token.strip().strip("`\"'")
                if 3 <= len(token) <= 40 and token.lower() not in STOPWORDS:
                    # keep if it's alnum/dash/space
                    if re.match(r"^[\w\-\s\+\=]+$", token):
                        vocab.add(token.lower())
    return sorted(vocab)


def load_profile_vocab(project_root: Path) -> list[str]:
    path = project_root / "state" / "trait_profile.md"
    if not path.exists():
        return []
    return extract_vocab_from_profile(path.read_text())


# ------------------------------------------------------------------
# Always-on structural signals
# ------------------------------------------------------------------


STRUCTURAL_PATTERNS = [
    (r"\bTable\s*\d+", "table_header"),
    (r"\bFigure\s*\d+", "figure_header"),
    (r"\b(?:Results|Methods|Discussion|Abstract)\b", "section_header"),
    # Species binomial: capitalized genus + lowercase species, 3+ chars each
    (r"\b[A-Z][a-z]{2,}\s+[a-z]{3,}\b", "binomial"),
]


def scan_page(text: str, vocab: list[str]) -> dict:
    """Return hit counts per signal type for this page's text."""
    counts = {"vocab": 0, "binomial": 0, "table_header": 0,
              "figure_header": 0, "section_header": 0}
    hits: list[tuple[int, int, str]] = []  # (start, end, signal_type)

    # Vocab hits (case-insensitive whole-word, with modest boundary)
    text_lc = text.lower()
    for term in vocab:
        for m in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", text_lc):
            counts["vocab"] += 1
            hits.append((m.start(), m.end(), "vocab"))

    # Structural hits
    for pattern, signal in STRUCTURAL_PATTERNS:
        for m in re.finditer(pattern, text):
            counts[signal] = counts.get(signal, 0) + 1
            hits.append((m.start(), m.end(), signal))

    # Collect short context snippets around the first ~8 hits, deduped
    hits.sort()
    snippets: list[str] = []
    seen_ranges: list[tuple[int, int]] = []
    for start, end, sig in hits[:20]:
        # Expand 60 chars each side
        ctx_start = max(0, start - 60)
        ctx_end = min(len(text), end + 60)
        # Dedup overlapping snippets
        overlap = any(s <= ctx_start < e or s < ctx_end <= e
                      for s, e in seen_ranges)
        if overlap:
            continue
        seen_ranges.append((ctx_start, ctx_end))
        snippet = text[ctx_start:ctx_end].replace("\n", " ").strip()
        snippets.append(f"[{sig}] …{snippet}…")
        if len(snippets) >= 8:
            break
    return {"counts": counts, "snippets": snippets,
            "total_hits": sum(counts.values())}


def score_page(page_report: dict) -> float:
    """0-1 confidence that this page contains extractable trait data."""
    c = page_report["counts"]
    # Heuristic weights
    score = 0.0
    score += min(1.0, c.get("vocab", 0) / 3.0) * 0.5
    score += min(1.0, c.get("binomial", 0) / 2.0) * 0.3
    score += 0.15 if c.get("table_header", 0) > 0 else 0.0
    score += 0.05 if c.get("section_header", 0) > 0 else 0.0
    return min(1.0, score)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha256")
    ap.add_argument("--path", type=Path,
                    help="Direct PDF path (bypasses manifest lookup)")
    ap.add_argument("--project-root", type=Path)
    ap.add_argument("--keywords", default="",
                    help="Comma-separated extra trait keywords to match")
    ap.add_argument("--min-page-score", type=float, default=0.15,
                    help="Pages below this score are filtered out")
    ap.add_argument("--max-pages-out", type=int, default=10,
                    help="Cap on pages_with_hits returned (top-scored first)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    # Resolve PDF path
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
                (args.sha256,)).fetchone()
        finally:
            con.close()
        if not row:
            print(f"sha256 not in manifest: {args.sha256}", file=sys.stderr)
            return 2
        pdf_path = Path(row[0]).resolve()

    # Assemble vocab
    vocab: list[str] = []
    if args.project_root:
        vocab.extend(load_profile_vocab(args.project_root.resolve()))
    vocab.extend([k.strip().lower() for k in args.keywords.split(",") if k.strip()])
    vocab = sorted(set(vocab))

    # Scan every page
    page_reports: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            report = scan_page(text, vocab)
            report["page"] = i
            report["score"] = score_page(report)
            page_reports.append(report)

    # Filter + sort
    hit_pages = [r for r in page_reports if r["score"] >= args.min_page_score]
    hit_pages.sort(key=lambda r: -r["score"])
    hit_pages = hit_pages[:args.max_pages_out]

    # Paper-level confidence: max page score, boosted if multiple hit pages
    if page_reports:
        max_score = max(r["score"] for r in page_reports)
        paper_conf = min(1.0,
                          max_score + 0.05 * min(5, len(hit_pages)))
    else:
        paper_conf = 0.0

    output = {
        "pdf_path": str(pdf_path),
        "sha256": args.sha256,
        "total_pages": n_pages,
        "pages_with_hits": sorted(r["page"] for r in hit_pages),
        "paper_confidence": round(paper_conf, 3),
        "vocab_size": len(vocab),
        "hit_summary": [
            {"page": r["page"], "score": round(r["score"], 3),
             "counts": r["counts"],
             "snippets": r["snippets"]}
            for r in hit_pages
        ],
        "recommendation": (
            "SKIP_NO_SIGNAL" if paper_conf < 0.15 else
            "READ_ABSTRACT_ONLY" if paper_conf < 0.35 else
            "READ_HIT_PAGES"
        ),
    }

    if args.out:
        args.out.write_text(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
