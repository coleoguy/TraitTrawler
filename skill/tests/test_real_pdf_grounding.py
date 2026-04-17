#!/usr/bin/env python3
"""End-to-end PDF grounding test with REAL PDF files.

Creates three synthetic PDFs with known text content, hashes them into
manifest.sqlite via pdf_ingest.py, then runs verify_quote.py against a
set of crafted claims:

  - good claim: quote really is on the page        → must VERIFY
  - good claim: quote on page 2, not page 1        → must VERIFY
  - bad claim: quote fabricated (not in PDF)       → must FAIL
  - bad claim: quote exists, but on a DIFFERENT page → must FAIL
  - bad claim: references a sha256 not in manifest → must FAIL

This is the critical grounding infrastructure. If verify_quote.py
cannot distinguish real from fabricated quotes on real PDF bytes, the
entire v6 "grounding is a protocol invariant" claim collapses.

Requires: pdfplumber (prod dep) + fpdf2 (dev dep).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("SKIP: fpdf2 not installed. pip install fpdf2", file=sys.stderr)
    sys.exit(0)

try:
    import pdfplumber  # noqa: F401
except ImportError:
    print("SKIP: pdfplumber not installed.", file=sys.stderr)
    sys.exit(0)

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def make_pdf(path: Path, pages: list[str]) -> None:
    """Create a minimal multi-page PDF with the given text per page."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        # Use explicit page width minus margins; fpdf2 needs non-zero w
        # when text contains long tokens.
        usable_w = pdf.w - pdf.l_margin - pdf.r_margin
        for line in text.split("\n"):
            pdf.multi_cell(w=usable_w, h=8, text=line)
    pdf.output(str(path))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def test_pipeline(tmp_root: Path) -> None:
    # 1. Set up project
    run([
        sys.executable, str(SCRIPTS / "setup_project.py"),
        "--root", str(tmp_root),
        "--trait", "chromosome number",
        "--taxa", "insects",
    ])

    # 2. Build three synthetic PDFs
    pdf_dir = tmp_root / "pdfs"
    pdf_a = pdf_dir / "smith2019.pdf"
    pdf_b = pdf_dir / "jones2020.pdf"
    pdf_c = pdf_dir / "lee2021.pdf"
    make_pdf(pdf_a, pages=[
        "Smith et al. 2019. Karyotype of Chrysolina americana.",
        "Methods: conventional Giemsa staining.\nResults: Chrysolina americana exhibited 2n = 22 with an XY sex chromosome system.",
        "Discussion: the observed count matches prior reports.",
    ])
    make_pdf(pdf_b, pages=[
        "Jones 2020. Comparative cytogenetics of Coleoptera.",
        "We found that Galerucella calmariensis has 2n = 34 in all examined populations.",
    ])
    make_pdf(pdf_c, pages=[
        "Lee et al. 2021. Complex sex chromosomes in Blaps gigas.",
        "The karyotype of Blaps gigas comprised 2n = 18 with an X1X2Y multiple sex chromosome system.",
    ])

    # 3. Ingest (hash into manifest.sqlite)
    r = run([
        sys.executable, str(SCRIPTS / "pdf_ingest.py"),
        "--scan",
        "--project-root", str(tmp_root),
    ])
    scan_out = json.loads(r.stdout)
    assert scan_out["count"] == 3, scan_out
    # Every file ingested or duplicate; collect the sha256 we can trust
    sha_a = sha256_of(pdf_a)
    sha_b = sha256_of(pdf_b)
    sha_c = sha256_of(pdf_c)

    # 4. Craft five claims
    claims = [
        # (1) TRUE: quote is on page 2 of pdf_a
        {
            "claim_id": "good_a",
            "sha256": sha_a,
            "page": 2,
            "verbatim_quote": "Chrysolina americana exhibited 2n = 22 with an XY sex chromosome system.",
            "species_hint": "Chrysolina americana",
            "trait_fields": {"diploid_2n": 22, "sex_system": "XY"},
        },
        # (2) TRUE: quote is on page 2 of pdf_b
        {
            "claim_id": "good_b",
            "sha256": sha_b,
            "page": 2,
            "verbatim_quote": "Galerucella calmariensis has 2n = 34 in all examined populations.",
            "species_hint": "Galerucella calmariensis",
            "trait_fields": {"diploid_2n": 34},
        },
        # (3) FAIL: quote fabricated (species not in pdf_c)
        {
            "claim_id": "bad_fabricated",
            "sha256": sha_c,
            "page": 2,
            "verbatim_quote": "Tribolium castaneum was found to have 2n = 20 diploid chromosomes.",
            "species_hint": "Tribolium castaneum",
            "trait_fields": {"diploid_2n": 20},
        },
        # (4) FAIL: quote is correct text, but wrong page number claimed
        {
            "claim_id": "bad_wrong_page",
            "sha256": sha_a,
            "page": 1,  # actual text is on page 2
            "verbatim_quote": "Chrysolina americana exhibited 2n = 22 with an XY sex chromosome system.",
            "species_hint": "Chrysolina americana",
            "trait_fields": {"diploid_2n": 22},
        },
        # (5) FAIL: sha256 not in manifest
        {
            "claim_id": "bad_unknown_pdf",
            "sha256": "f" * 64,
            "page": 1,
            "verbatim_quote": "This PDF does not exist in the manifest.",
            "species_hint": "Mystery species",
            "trait_fields": {},
        },
    ]
    claims_path = tmp_root / "state" / "claims" / "e2e.jsonl"
    claims_path.parent.mkdir(parents=True, exist_ok=True)
    claims_path.write_text("\n".join(json.dumps(c) for c in claims) + "\n")

    # 5. Run verify_quote.py
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify_quote.py"),
         "--claims", str(claims_path),
         "--project-root", str(tmp_root)],
        capture_output=True, text=True,
    )
    # exit 0 = success, 1 = >50% failed; we expect 2/5 pass = 40% = exit 1
    # That's fine; we care about per-claim verdicts, not the global rc.
    report = json.loads(result.stdout)
    assert report["total_claims"] == 5, report
    assert report["verified"] == 2, f"expected 2 verified (good_a, good_b); got {report}"
    assert report["failed"] == 3, f"expected 3 failed; got {report}"

    # 6. Inspect the verified and failed JSONL files
    verified = [json.loads(l) for l in
                Path(report["verified_path"]).read_text().splitlines() if l.strip()]
    failed = [json.loads(l) for l in
              Path(report["failed_path"]).read_text().splitlines() if l.strip()]

    verified_ids = {c["claim_id"] for c in verified}
    failed_ids = {c["claim_id"] for c in failed}
    assert verified_ids == {"good_a", "good_b"}, verified_ids
    assert failed_ids == {"bad_fabricated", "bad_wrong_page", "bad_unknown_pdf"}, failed_ids

    # 7. Each failure has a specific, useful reason
    reasons_by_id = {c["claim_id"]: c["grounding_failure_reason"] for c in failed}
    assert "not found" in reasons_by_id["bad_fabricated"].lower() or \
           "not present" in reasons_by_id["bad_fabricated"].lower() or \
           "not in" in reasons_by_id["bad_fabricated"].lower(), \
           f"fabricated-quote reason should say 'not found': {reasons_by_id['bad_fabricated']}"
    assert "not found" in reasons_by_id["bad_wrong_page"].lower(), \
           f"wrong-page reason: {reasons_by_id['bad_wrong_page']}"
    assert ("not found on disk" in reasons_by_id["bad_unknown_pdf"].lower()
            or "pdf for sha256" in reasons_by_id["bad_unknown_pdf"].lower()), \
           f"unknown-pdf reason: {reasons_by_id['bad_unknown_pdf']}"

    # 8. Each verified claim carries grounding_verified=True
    for c in verified:
        assert c.get("grounding_verified") is True
    for c in failed:
        assert c.get("grounding_verified") is False


def test_triage_prefilter(tmp_root: Path) -> None:
    """triage_prefilter.py identifies trait-bearing pages via regex+keyword."""
    # 1. Set up project
    subprocess.run([
        sys.executable, str(SCRIPTS / "setup_project.py"),
        "--root", str(tmp_root),
        "--trait", "chromosome number", "--taxa", "insects",
    ], check=True, capture_output=True)

    # 2. Write a trait_profile.md with a couple of sections so the
    #    vocab-extraction logic has something to pull from.
    (tmp_root / "state" / "trait_profile.md").write_text("""\
---
trait: chromosome number
---

## 1. Canonical Name and Synonyms
- chromosome number
- 2n
- diploid number

## 2. Notation Conventions
- Notation: `2n = N`
- Example: `2n = 22, XY`

## 4. Valid Biological Ranges
- chromosomes

## 11. Proposed Columns
### diploid_2n
- type: int
""")

    # 3. Build two PDFs: one with strong trait signal, one without
    hit_pdf = tmp_root / "pdfs" / "good.pdf"
    noise_pdf = tmp_root / "pdfs" / "irrelevant.pdf"
    hit_pdf.parent.mkdir(exist_ok=True)
    make_pdf(hit_pdf, pages=[
        "Smith et al. 2020. Karyotype survey.",
        "Methods: conventional Giemsa staining on meiotic preparations.",
        "Results: Table 2. Chrysolina americana exhibited 2n = 22, XY. "
        "Galerucella calmariensis exhibited 2n = 34.",
        "Figure 1. Idiogram of Chrysolina americana.",
    ])
    make_pdf(noise_pdf, pages=[
        "Thompson 2021. A general review of ecology.",
        "This paper discusses population dynamics and community structure "
        "in tropical forests. No karyotype data reported.",
    ])

    # 4. Ingest hashes
    subprocess.run([
        sys.executable, str(SCRIPTS / "pdf_ingest.py"),
        "--scan", "--project-root", str(tmp_root),
    ], check=True, capture_output=True)

    sha_hit = sha256_of(hit_pdf)
    sha_noise = sha256_of(noise_pdf)

    # 5. Run pre-filter on each
    r1 = subprocess.run([
        sys.executable, str(SCRIPTS / "triage_prefilter.py"),
        "--sha256", sha_hit, "--project-root", str(tmp_root),
    ], check=True, capture_output=True, text=True)
    hit_report = json.loads(r1.stdout)

    r2 = subprocess.run([
        sys.executable, str(SCRIPTS / "triage_prefilter.py"),
        "--sha256", sha_noise, "--project-root", str(tmp_root),
    ], check=True, capture_output=True, text=True)
    noise_report = json.loads(r2.stdout)

    # 6. Assertions
    # Hit paper should have HIGH confidence + multiple pages flagged
    assert hit_report["paper_confidence"] >= 0.35, hit_report
    assert hit_report["recommendation"] in ("READ_HIT_PAGES", "READ_ABSTRACT_ONLY"), \
        hit_report
    assert len(hit_report["pages_with_hits"]) >= 1
    # One of the hit pages should be page 3 (where the Table 2 data is)
    assert 3 in hit_report["pages_with_hits"], hit_report

    # Noise paper should have LOW confidence
    assert noise_report["paper_confidence"] < hit_report["paper_confidence"], \
        (noise_report, hit_report)

    # Vocab should have been extracted from the profile
    assert hit_report["vocab_size"] >= 1, hit_report


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        test_pipeline(Path(d) / "e2e_proj")
        print("OK: real-PDF grounding (5 claims, 2 verified, 3 failed correctly)")
    with tempfile.TemporaryDirectory() as d:
        test_triage_prefilter(Path(d) / "prefilter_proj")
        print("OK: triage pre-filter identifies trait-bearing pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
