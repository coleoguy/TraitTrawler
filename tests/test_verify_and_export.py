#!/usr/bin/env python3
"""
Runnable tests for TraitTrawler's verify_session.py and export_dwc.py.

Creates synthetic project data, runs both scripts, and asserts expected
outcomes. No external dependencies beyond Python stdlib + pyyaml (optional).

Usage:
    python tests/test_verify_and_export.py
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the repository root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


def _write_csv(path: Path, fieldnames: list, rows: list):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _write_yaml(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def _make_project(tmp: Path, rows: list, extra_yaml: str = "") -> Path:
    """Create a minimal TraitTrawler project directory with results.csv."""
    project = tmp / "project"
    project.mkdir()
    (project / "state").mkdir()

    fieldnames = [
        "doi", "paper_title", "paper_authors", "first_author",
        "paper_year", "paper_journal", "session_id",
        "species", "family", "subfamily", "genus",
        "body_mass_g_mean",
        "collection_locality", "country",
        "source_page", "source_context", "extraction_reasoning",
        "extraction_confidence", "flag_for_review",
        "source_type", "pdf_source", "pdf_filename", "pdf_url",
        "notes", "processed_date",
    ]

    _write_csv(project / "results.csv", fieldnames, rows)

    yaml_text = f"""
project_name: "Test Project"
contact_email: "test@example.com"
target_taxa:
  - Aves
trait_name: "body_mass"
trait_description: "Avian body mass from literature"
proxy_url: ""
institution: "Test University"
output_csv: "results.csv"
output_fields:
  - doi
  - paper_title
  - species
  - family
  - genus
  - body_mass_g_mean
  - extraction_confidence
  - flag_for_review
  - source_type
  - pdf_source
  - processed_date
  - session_id
source_type_values: [full_text, table, catalogue, abstract_only]
pdf_source_values: [unpaywall, openalex, europepmc, semanticscholar, core, proxy, local_pdf, browser_failed, scanned_skipped]
{extra_yaml}
"""
    _write_yaml(project / "collector_config.yaml", yaml_text)
    return project


# ---------------------------------------------------------------------------
# Good synthetic records
# ---------------------------------------------------------------------------

_GOOD_ROWS = [
    {
        "doi": "10.1234/test.0001",
        "paper_title": "Body mass of passerines",
        "paper_authors": "Smith, J.; Jones, A.",
        "first_author": "Smith",
        "paper_year": "2020",
        "paper_journal": "J Ornithol",
        "session_id": "2026-03-25T10:00:00Z",
        "species": "Passer domesticus",
        "family": "Passeridae",
        "subfamily": "",
        "genus": "Passer",
        "body_mass_g_mean": "28.5",
        "collection_locality": "London, UK",
        "country": "United Kingdom",
        "source_page": "12",
        "source_context": "Table 1 row 3: P. domesticus 28.5 g",
        "extraction_reasoning": "",
        "extraction_confidence": "0.92",
        "flag_for_review": "false",
        "source_type": "full_text",
        "pdf_source": "unpaywall",
        "pdf_filename": "Smith_2020_JOrnithol_0001.pdf",
        "pdf_url": "https://example.com/pdf",
        "notes": "",
        "processed_date": "2026-03-25",
    },
    {
        "doi": "10.1234/test.0002",
        "paper_title": "Raptor morphometrics",
        "paper_authors": "Lee, B.",
        "first_author": "Lee",
        "paper_year": "2019",
        "paper_journal": "Ibis",
        "session_id": "2026-03-25T10:00:00Z",
        "species": "Falco peregrinus",
        "family": "Falconidae",
        "subfamily": "",
        "genus": "Falco",
        "body_mass_g_mean": "750.0",
        "collection_locality": "Berlin, Germany",
        "country": "Germany",
        "source_page": "5-6",
        "source_context": "Results section: F. peregrinus mean mass 750 g",
        "extraction_reasoning": "",
        "extraction_confidence": "0.88",
        "flag_for_review": "false",
        "source_type": "full_text",
        "pdf_source": "openalex",
        "pdf_filename": "Lee_2019_Ibis_0002.pdf",
        "pdf_url": "https://example.com/pdf2",
        "notes": "",
        "processed_date": "2026-03-25",
    },
]


# ---------------------------------------------------------------------------
# Test: verify_session.py on clean data → exit 0
# ---------------------------------------------------------------------------

def test_verify_clean():
    """verify_session.py should pass on valid, non-duplicate records."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp), _GOOD_ROWS)
        script = _repo_root() / "skill" / "verify_session.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        report_path = project / "state" / "verification_report.json"
        assert report_path.exists(), "verification_report.json not created"

        report = json.loads(report_path.read_text())
        assert report["summary"]["pass"] is True, (
            f"Expected PASS, got errors: {report['issues']}"
        )
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
    print("  PASS  test_verify_clean")


# ---------------------------------------------------------------------------
# Test: verify_session.py catches duplicates → exit 1
# ---------------------------------------------------------------------------

def test_verify_duplicate():
    """verify_session.py should flag exact duplicate rows."""
    dup_rows = _GOOD_ROWS + [_GOOD_ROWS[0].copy()]  # duplicate first record

    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp), dup_rows)
        script = _repo_root() / "skill" / "verify_session.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        report = json.loads(
            (project / "state" / "verification_report.json").read_text()
        )
        assert report["summary"]["pass"] is False, "Expected FAIL for duplicates"
        dup_issues = [i for i in report["issues"] if i["type"] == "duplicate"]
        assert len(dup_issues) >= 1, "Expected at least one duplicate issue"
    print("  PASS  test_verify_duplicate")


# ---------------------------------------------------------------------------
# Test: verify_session.py catches missing species → exit 1
# ---------------------------------------------------------------------------

def test_verify_missing_species():
    """verify_session.py should flag records with empty species."""
    bad_row = _GOOD_ROWS[0].copy()
    bad_row["species"] = ""
    bad_row["doi"] = "10.1234/test.9999"

    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp), [bad_row])
        script = _repo_root() / "skill" / "verify_session.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        report = json.loads(
            (project / "state" / "verification_report.json").read_text()
        )
        assert report["summary"]["pass"] is False, "Expected FAIL for missing species"
        missing = [i for i in report["issues"] if i["type"] == "missing_required_field"]
        assert len(missing) >= 1, "Expected missing_required_field issue"
    print("  PASS  test_verify_missing_species")


# ---------------------------------------------------------------------------
# Test: verify_session.py catches bad controlled vocabulary → exit 1
# ---------------------------------------------------------------------------

def test_verify_bad_vocabulary():
    """verify_session.py should flag invalid source_type values."""
    bad_row = _GOOD_ROWS[0].copy()
    bad_row["doi"] = "10.1234/test.8888"
    bad_row["source_type"] = "made_up_value"

    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp), [bad_row])
        script = _repo_root() / "skill" / "verify_session.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        report = json.loads(
            (project / "state" / "verification_report.json").read_text()
        )
        vocab_issues = [i for i in report["issues"] if i["type"] == "invalid_vocabulary"]
        assert len(vocab_issues) >= 1, "Expected invalid_vocabulary issue"
    print("  PASS  test_verify_bad_vocabulary")


# ---------------------------------------------------------------------------
# Test: verify_session.py warns on abstract_only + high confidence
# ---------------------------------------------------------------------------

def test_verify_abstract_confidence():
    """Abstract-only records with confidence > 0.55 should generate a warning."""
    bad_row = _GOOD_ROWS[0].copy()
    bad_row["doi"] = "10.1234/test.7777"
    bad_row["source_type"] = "abstract_only"
    bad_row["extraction_confidence"] = "0.85"

    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp), [bad_row])
        script = _repo_root() / "skill" / "verify_session.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        report = json.loads(
            (project / "state" / "verification_report.json").read_text()
        )
        consistency = [i for i in report["issues"] if i["type"] == "consistency_violation"]
        assert len(consistency) >= 1, "Expected consistency_violation warning"
    print("  PASS  test_verify_abstract_confidence")


# ---------------------------------------------------------------------------
# Test: export_dwc.py produces valid DwC-A files
# ---------------------------------------------------------------------------

def test_export_dwc():
    """export_dwc.py should produce occurrence.txt, meta.xml, and eml.xml."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = _make_project(tmp_path, _GOOD_ROWS)
        output_dir = tmp_path / "dwc_output"
        script = _repo_root() / "skill" / "export_dwc.py"

        result = subprocess.run(
            [sys.executable, str(script),
             "--project-root", str(project),
             "--output-dir", str(output_dir)],
            capture_output=True, text=True,
        )

        assert result.returncode == 0, f"export_dwc.py failed: {result.stderr}"

        # Check output files exist
        assert (output_dir / "occurrence.txt").exists(), "occurrence.txt not created"
        assert (output_dir / "meta.xml").exists(), "meta.xml not created"
        assert (output_dir / "eml.xml").exists(), "eml.xml not created"

        # Validate occurrence.txt structure
        with open(output_dir / "occurrence.txt", "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            occ_rows = list(reader)

        assert len(occ_rows) == 2, f"Expected 2 records, got {len(occ_rows)}"

        # Check required DwC fields present
        for row in occ_rows:
            assert row["scientificName"], "scientificName should not be empty"
            assert row["occurrenceID"].startswith("traitrawler_"), "Bad occurrenceID"
            assert row["basisOfRecord"] == "MaterialCitation", "Wrong basisOfRecord"

        # Check dynamicProperties contains trait fields as JSON
        dp = json.loads(occ_rows[0]["dynamicProperties"])
        assert "body_mass_g_mean" in dp, "Trait field missing from dynamicProperties"

        # Check references field has DOI URL
        assert occ_rows[0]["references"].startswith("https://doi.org/"), "Bad DOI URL"

    print("  PASS  test_export_dwc")


# ---------------------------------------------------------------------------
# Test: export_dwc.py --zip produces .dwca archive
# ---------------------------------------------------------------------------

def test_export_dwc_zip():
    """export_dwc.py --zip should produce an archive.dwca file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        project = _make_project(tmp_path, _GOOD_ROWS)
        output_dir = tmp_path / "dwc_output"
        script = _repo_root() / "skill" / "export_dwc.py"

        result = subprocess.run(
            [sys.executable, str(script),
             "--project-root", str(project),
             "--output-dir", str(output_dir),
             "--zip"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0, f"export_dwc.py --zip failed: {result.stderr}"
        assert (output_dir / "archive.dwca").exists(), "archive.dwca not created"

        # Verify it's a valid zip
        import zipfile
        with zipfile.ZipFile(output_dir / "archive.dwca") as zf:
            names = zf.namelist()
            assert "occurrence.txt" in names, "occurrence.txt missing from archive"
            assert "meta.xml" in names, "meta.xml missing from archive"
            assert "eml.xml" in names, "eml.xml missing from archive"

    print("  PASS  test_export_dwc_zip")


# ---------------------------------------------------------------------------
# Test: verify_session.py handles missing results.csv gracefully
# ---------------------------------------------------------------------------

def test_verify_missing_csv():
    """verify_session.py should report error for missing results.csv."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "empty_project"
        project.mkdir()
        (project / "state").mkdir()

        script = _repo_root() / "skill" / "verify_session.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        assert result.returncode == 1, "Expected exit 1 for missing CSV"
    print("  PASS  test_verify_missing_csv")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        test_verify_clean,
        test_verify_duplicate,
        test_verify_missing_species,
        test_verify_bad_vocabulary,
        test_verify_abstract_confidence,
        test_export_dwc,
        test_export_dwc_zip,
        test_verify_missing_csv,
    ]

    print(f"\nRunning {len(tests)} tests...\n")
    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'='*50}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
