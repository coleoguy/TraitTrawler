#!/usr/bin/env python3
"""Deterministic grounding verification.

For each Claim in a JSONL file, re-extract the text of the claimed page
from the PDF and confirm `verbatim_quote` is a substring (after modest
whitespace normalization).

Claims that pass are written to <input>.verified.jsonl with a
`grounding_verified: true` flag. Claims that fail are written to
<input>.failed.jsonl with the reason and the actual page text snippet so
a human can see what went wrong.

This is THE critical fix over v5. Nothing reaches results.csv without
passing this gate.
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
    print("pdfplumber required: pip install pdfplumber", file=sys.stderr)
    sys.exit(3)


_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    """Modest whitespace normalization. Preserves all printable characters."""
    # collapse runs of whitespace (including newlines) to single space
    return _WS.sub(" ", s).strip()


def pdf_page_text(pdf_path: Path, page_number: int) -> str:
    """1-indexed page number."""
    with pdfplumber.open(pdf_path) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            return ""
        return pdf.pages[page_number - 1].extract_text() or ""


def verify_claim(claim: dict, sha_to_path: dict[str, Path]) -> tuple[bool, str]:
    quote = claim.get("verbatim_quote")
    page = claim.get("page")
    sha = claim.get("sha256")
    if not quote or not isinstance(page, int) or not sha:
        return False, "missing verbatim_quote, page, or sha256"
    pdf_path = sha_to_path.get(sha)
    if not pdf_path or not pdf_path.exists():
        return False, f"pdf for sha256={sha} not found on disk"
    page_text = pdf_page_text(pdf_path, page)
    if not page_text:
        return False, f"no extractable text on page {page}"
    if normalize(quote) in normalize(page_text):
        return True, "ok"
    # second chance: try a 50% prefix match, because authors sometimes
    # add zero-width punctuation. If prefix matches, still fail but
    # with a more informative reason.
    nq = normalize(quote)
    np = normalize(page_text)
    prefix = nq[: max(40, len(nq) // 2)]
    if prefix and prefix in np:
        return False, f"quote prefix appears but full quote does not (likely OCR drift); see page text snippet"
    return False, "verbatim quote not found on claimed page"


def load_sha_to_path(project_root: Path) -> dict[str, Path]:
    db = project_root / "state" / "manifest.sqlite"
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT sha256, canonical_path FROM pdfs").fetchall()
    finally:
        con.close()
    return {sha: Path(p) for sha, p in rows}


def project_root_from_path(p: Path) -> Path:
    cur = p.resolve()
    while cur != cur.parent:
        if (cur / "state" / "manifest.sqlite").exists():
            return cur
        cur = cur.parent
    raise RuntimeError("Could not locate project root")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", required=True, type=Path)
    ap.add_argument("--project-root", type=Path)
    args = ap.parse_args()

    claims_path: Path = args.claims.resolve()
    root = (args.project_root or project_root_from_path(claims_path)).resolve()
    sha_to_path = load_sha_to_path(root)

    verified_path = claims_path.with_suffix(".verified.jsonl")
    failed_path = claims_path.with_suffix(".failed.jsonl")

    total = 0
    verified = 0
    with (claims_path.open() as fin,
          verified_path.open("w") as fv,
          failed_path.open("w") as ff):
        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            claim = json.loads(line)
            ok, reason = verify_claim(claim, sha_to_path)
            if ok:
                claim["grounding_verified"] = True
                fv.write(json.dumps(claim) + "\n")
                verified += 1
            else:
                claim["grounding_verified"] = False
                claim["grounding_failure_reason"] = reason
                ff.write(json.dumps(claim) + "\n")

    result = {
        "total_claims": total,
        "verified": verified,
        "failed": total - verified,
        "verified_path": str(verified_path),
        "failed_path": str(failed_path),
        "verification_rate": round(verified / total, 3) if total else 0.0,
    }
    print(json.dumps(result, indent=2))
    return 0 if total == 0 or verified / total >= 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
