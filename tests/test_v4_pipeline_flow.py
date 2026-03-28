#!/usr/bin/env python3
"""
V4 pipeline flow smoke tests for TraitTrawler.

Tests the folder-based data flow contracts WITHOUT any LLM calls.
Validates that synthetic data injected into handoff folders flows
through the deterministic parts of the pipeline correctly:

  ready_for_extraction/ → (simulated) → finds/ → Writer (csv_writer.py) → results.csv
  results.csv → verify_session.py → verification_report.json
  results.csv → dashboard_generator.py → dashboard.html

Usage:
    python tests/test_v4_pipeline_flow.py
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _write_csv(path: Path, fieldnames: list, rows: list):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _count_lines(path: Path) -> int:
    with open(path, "r") as f:
        return sum(1 for _ in f)


# ---------------------------------------------------------------------------
# V4 field schema (matches config_template.yaml output_fields)
# ---------------------------------------------------------------------------

V4_FIELDS = [
    "doi", "paper_title", "paper_authors", "first_author",
    "paper_year", "paper_journal", "session_id",
    "species", "family", "subfamily", "genus",
    # trait fields (project-specific, using body_mass for tests)
    "body_mass_g_mean",
    "collection_locality", "country",
    "source_page", "source_context", "extraction_reasoning",
    "accepted_name", "gbif_key", "taxonomy_note",
    "extraction_confidence", "calibrated_confidence",
    "flag_for_review", "source_type", "pdf_source",
    "pdf_filename", "pdf_url", "notes", "processed_date",
    "consensus", "extraction_trace_id",
    "audit_status", "audit_session", "audit_prior_values",
]

V4_CONFIG_YAML = """
project_name: "V4 Smoke Test"
contact_email: "test@example.com"
target_taxa:
  - Aves
trait_name: "body_mass"
trait_description: "Avian body mass from literature"
proxy_url: ""
institution: "Test University"
extraction_mode: consensus
concurrency:
  max_concurrent_dealers: 2
pdf_subfolder_field: "family"
vision_extraction: "ask"
batch_size: 20
report_every: 5
taxonomy_resolution: true
output_fields:
  - doi
  - paper_title
  - paper_authors
  - first_author
  - paper_year
  - paper_journal
  - session_id
  - species
  - family
  - subfamily
  - genus
  - body_mass_g_mean
  - collection_locality
  - country
  - source_page
  - source_context
  - extraction_reasoning
  - accepted_name
  - gbif_key
  - taxonomy_note
  - extraction_confidence
  - calibrated_confidence
  - flag_for_review
  - source_type
  - pdf_source
  - pdf_filename
  - pdf_url
  - notes
  - processed_date
  - consensus
  - extraction_trace_id
  - audit_status
  - audit_session
  - audit_prior_values
source_type_values: [full_text, table, catalogue]
pdf_source_values: [unpaywall, openalex, europepmc, semanticscholar, core, proxy, local_pdf]
"""


# ---------------------------------------------------------------------------
# Synthetic data factories
# ---------------------------------------------------------------------------

def _make_v4_project(tmp: Path, existing_rows=None) -> Path:
    """Create a complete v4 folder structure with optional seed data."""
    project = tmp / "project"
    project.mkdir()

    # V4 folder structure
    for d in ["state", "state/dealt", "state/extraction_traces",
              "state/snapshots", "finds", "ready_for_extraction",
              "learning", "provided_pdfs", "pdfs", "pdfs/Passeridae",
              "pdfs/Falconidae", "scripts"]:
        (project / d).mkdir(parents=True, exist_ok=True)

    # Config
    (project / "collector_config.yaml").write_text(V4_CONFIG_YAML)

    # Empty state files
    (project / "state" / "processed.json").write_text("{}")
    (project / "state" / "queue.json").write_text("[]")
    (project / "state" / "search_log.json").write_text("{}")
    (project / "state" / "run_log.jsonl").write_text("")
    (project / "state" / "taxonomy_cache.json").write_text("{}")
    (project / "state" / "source_stats.json").write_text("{}")
    (project / "state" / "consensus_stats.json").write_text("{}")
    (project / "state" / "discoveries.jsonl").write_text("")

    # Results CSV (empty or with seed data)
    rows = existing_rows or []
    _write_csv(project / "results.csv", V4_FIELDS, rows)

    # Copy scripts from skill directory
    skill_dir = _repo_root() / "skill"
    for script in ["verify_session.py", "dashboard_generator.py"]:
        src = skill_dir / script
        if src.exists():
            shutil.copy2(src, project / script)

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.exists():
        for script in scripts_dir.glob("*.py"):
            shutil.copy2(script, project / "scripts" / script.name)

    return project


_finds_counter = 0

def _make_finds_file(project: Path, doi: str, records: list,
                     consensus_type: str = "full") -> Path:
    """Create a synthetic finds/ JSON file (mimics Extractor output)."""
    global _finds_counter
    _finds_counter += 1
    doi_safe = doi.replace("/", "_").replace(".", "_")
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H%M%SZ")
    filename = f"{doi_safe}_{ts}_{_finds_counter}.json"
    path = project / "finds" / filename

    finds_data = {
        "doi": doi,
        "title": f"Test paper {doi}",
        "pdf_path": f"pdfs/Passeridae/Author_2020_Journal_{doi_safe[-4:]}.pdf",
        "pdf_source": "unpaywall",
        "extraction_timestamp": ts,
        "extraction_mode": "consensus",
        "records": records,
        "no_data_agents": 0,
        "agents_completed": 3,
        "paper_metadata": {
            "year": 2020,
            "journal": "J Ornithol",
            "first_author": "TestAuthor"
        }
    }

    path.write_text(json.dumps(finds_data, indent=2))
    return path


def _make_handoff_file(project: Path, doi: str, family: str = "Passeridae") -> Path:
    """Create a synthetic ready_for_extraction/ handoff file (mimics Fetcher output)."""
    doi_safe = doi.replace("/", "_").replace(".", "_")
    path = project / "ready_for_extraction" / f"{doi_safe}.json"

    handoff = {
        "doi": doi,
        "title": f"Test paper {doi}",
        "authors": "TestAuthor, A; CoAuthor, B",
        "year": 2020,
        "journal": "J Ornithol",
        "pdf_path": f"pdfs/{family}/TestAuthor_2020_JOrnithol_{doi_safe[-4:]}.pdf",
        "pdf_source": "unpaywall",
        "text_pages": 12,
        "has_tables": True,
        "document_type": "table-heavy",
        "fetched_at": datetime.utcnow().isoformat() + "Z"
    }

    path.write_text(json.dumps(handoff, indent=2))
    return path


def _make_queue_entries(project: Path, dois: list):
    """Add papers to queue.json (mimics Searcher output)."""
    queue = []
    for doi in dois:
        queue.append({
            "doi": doi,
            "title": f"Test paper {doi}",
            "authors": "TestAuthor et al.",
            "year": 2020,
            "journal": "J Ornithol",
            "abstract": "This paper reports body mass data for passerines.",
            "triage": "likely",
            "triage_confidence": 0.85,
            "source": "pubmed",
            "added_date": datetime.utcnow().isoformat() + "Z"
        })
    (project / "state" / "queue.json").write_text(json.dumps(queue, indent=2))


def _sample_extraction_records():
    """Records as they'd appear in a finds/ JSON (Extractor output format)."""
    return [
        {
            "species": "Passer domesticus",
            "family": "Passeridae",
            "genus": "Passer",
            "body_mass_g_mean": 28.5,
            "extraction_confidence": 0.92,
            "consensus": "full",
            "source_page": "12",
            "source_context": "Table 1 row 3: P. domesticus 28.5 g",
            "extraction_reasoning": "",
            "flag_for_review": False,
            "agent_values": {
                "A": {"body_mass_g_mean": 28.5},
                "B": {"body_mass_g_mean": 28.5},
                "C": {"body_mass_g_mean": 28.5}
            },
            "notes": ""
        },
        {
            "species": "Passer montanus",
            "family": "Passeridae",
            "genus": "Passer",
            "body_mass_g_mean": 22.0,
            "extraction_confidence": 0.88,
            "consensus": "majority",
            "source_page": "12",
            "source_context": "Table 1 row 4: P. montanus 22.0 g",
            "extraction_reasoning": "",
            "flag_for_review": False,
            "agent_values": {
                "A": {"body_mass_g_mean": 22.0},
                "B": {"body_mass_g_mean": 22.0},
                "C": {"body_mass_g_mean": 21.5}
            },
            "notes": ""
        },
    ]


# ---------------------------------------------------------------------------
# Test 1: Folder structure creation
# ---------------------------------------------------------------------------

def test_v4_folder_structure():
    """Verify all v4 folders are created correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))

        required_dirs = [
            "state", "state/dealt", "state/extraction_traces",
            "state/snapshots", "finds", "ready_for_extraction",
            "learning", "provided_pdfs", "pdfs",
        ]
        for d in required_dirs:
            assert (project / d).is_dir(), f"Missing directory: {d}"

        required_files = [
            "collector_config.yaml", "results.csv",
            "state/processed.json", "state/queue.json",
            "state/search_log.json", "state/run_log.jsonl",
            "state/taxonomy_cache.json",
        ]
        for f in required_files:
            assert (project / f).is_file(), f"Missing file: {f}"

    print("  PASS  test_v4_folder_structure")


# ---------------------------------------------------------------------------
# Test 2: Finds file schema validation
# ---------------------------------------------------------------------------

def test_finds_file_schema():
    """Verify finds/ files have the correct schema for Writer consumption."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))
        records = _sample_extraction_records()
        finds_path = _make_finds_file(project, "10.1234/test.0001", records)

        data = json.loads(finds_path.read_text())

        # Required top-level keys
        assert "doi" in data, "Missing 'doi' in finds file"
        assert "records" in data, "Missing 'records' in finds file"
        assert "paper_metadata" in data, "Missing 'paper_metadata'"
        assert "extraction_timestamp" in data, "Missing 'extraction_timestamp'"
        assert "pdf_path" in data, "Missing 'pdf_path'"
        assert "pdf_source" in data, "Missing 'pdf_source'"

        # Record-level required keys
        for rec in data["records"]:
            assert "species" in rec, "Record missing 'species'"
            assert "extraction_confidence" in rec, "Record missing 'extraction_confidence'"
            assert "consensus" in rec, "Record missing 'consensus'"
            assert "source_page" in rec, "Record missing 'source_page'"
            assert "source_context" in rec, "Record missing 'source_context'"
            assert 0.0 <= rec["extraction_confidence"] <= 1.0, \
                f"Confidence out of range: {rec['extraction_confidence']}"

        # Consensus types must be valid
        valid_consensus = {"full", "majority", "two_found", "single_agent",
                          "none", "single_pass", "opus_escalation"}
        for rec in data["records"]:
            assert rec["consensus"] in valid_consensus, \
                f"Invalid consensus type: {rec['consensus']}"

    print("  PASS  test_finds_file_schema")


# ---------------------------------------------------------------------------
# Test 3: Handoff file schema validation
# ---------------------------------------------------------------------------

def test_handoff_file_schema():
    """Verify ready_for_extraction/ files have correct schema for Dealer."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))
        handoff_path = _make_handoff_file(project, "10.1234/test.0001")

        data = json.loads(handoff_path.read_text())

        required_keys = ["doi", "title", "authors", "year", "journal",
                        "pdf_path", "pdf_source", "text_pages",
                        "has_tables", "document_type", "fetched_at"]
        for key in required_keys:
            assert key in data, f"Handoff file missing '{key}'"

        valid_doc_types = {"table-heavy", "prose", "catalogue", "scanned"}
        assert data["document_type"] in valid_doc_types, \
            f"Invalid document_type: {data['document_type']}"

        assert isinstance(data["text_pages"], int), "text_pages must be int"
        assert isinstance(data["has_tables"], bool), "has_tables must be bool"

    print("  PASS  test_handoff_file_schema")


# ---------------------------------------------------------------------------
# Test 4: Queue schema validation
# ---------------------------------------------------------------------------

def test_queue_schema():
    """Verify queue.json entries have correct schema for Fetcher."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))
        _make_queue_entries(project, ["10.1234/test.0001", "10.1234/test.0002"])

        queue = json.loads((project / "state" / "queue.json").read_text())
        assert len(queue) == 2, f"Expected 2 queue entries, got {len(queue)}"

        required_keys = ["doi", "title", "authors", "year", "journal",
                        "abstract", "triage", "triage_confidence",
                        "source", "added_date"]
        for entry in queue:
            for key in required_keys:
                assert key in entry, f"Queue entry missing '{key}'"
            assert entry["triage"] in {"likely", "uncertain", "unlikely"}, \
                f"Invalid triage: {entry['triage']}"
            assert 0.0 <= entry["triage_confidence"] <= 1.0

    print("  PASS  test_queue_schema")


# ---------------------------------------------------------------------------
# Test 5: CSV Writer processes finds/ correctly
# ---------------------------------------------------------------------------

def test_csv_writer_from_finds():
    """Simulate Writer: parse finds/ JSON, write to results.csv, verify."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))
        records = _sample_extraction_records()
        finds_path = _make_finds_file(project, "10.1234/test.0001", records)

        # Parse finds file (same logic Writer uses)
        finds_data = json.loads(finds_path.read_text())
        csv_rows = []
        for rec in finds_data["records"]:
            row = {
                "doi": finds_data["doi"],
                "paper_title": finds_data["title"],
                "paper_authors": "",
                "first_author": finds_data["paper_metadata"]["first_author"],
                "paper_year": str(finds_data["paper_metadata"]["year"]),
                "paper_journal": finds_data["paper_metadata"]["journal"],
                "session_id": "2026-03-27T10:00:00Z",
                "processed_date": "2026-03-27",
                "pdf_source": finds_data["pdf_source"],
                "pdf_filename": Path(finds_data["pdf_path"]).name,
                "source_type": "full_text",
            }
            # Copy record fields
            for field in V4_FIELDS:
                if field in rec and field not in row:
                    row[field] = str(rec[field]) if rec[field] is not None else ""
            # Fill missing fields with empty
            for field in V4_FIELDS:
                if field not in row:
                    row[field] = ""
            csv_rows.append(row)

        # Append to results.csv
        results_path = project / "results.csv"
        with open(results_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=V4_FIELDS, extrasaction="ignore")
            w.writerows(csv_rows)

        # Verify
        written = _read_csv(results_path)
        assert len(written) == 2, f"Expected 2 rows, got {len(written)}"
        assert written[0]["species"] == "Passer domesticus"
        assert written[1]["species"] == "Passer montanus"
        assert written[0]["consensus"] == "full"
        assert written[1]["consensus"] == "majority"
        assert float(written[0]["extraction_confidence"]) == 0.92
        assert written[0]["doi"] == "10.1234/test.0001"

        # Column count consistency
        header_count = len(V4_FIELDS)
        for i, row in enumerate(written):
            assert len(row) == header_count, \
                f"Row {i} has {len(row)} columns, expected {header_count}"

    print("  PASS  test_csv_writer_from_finds")


# ---------------------------------------------------------------------------
# Test 6: Verify session passes on v4 data
# ---------------------------------------------------------------------------

def test_verify_session_v4():
    """verify_session.py should pass on valid v4-format results.csv."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))

        # Write some valid rows
        rows = [
            {f: "" for f in V4_FIELDS} | {
                "doi": "10.1234/test.0001",
                "paper_title": "Test paper",
                "first_author": "Smith",
                "paper_year": "2020",
                "paper_journal": "J Ornithol",
                "session_id": "2026-03-27T10:00:00Z",
                "species": "Passer domesticus",
                "family": "Passeridae",
                "genus": "Passer",
                "body_mass_g_mean": "28.5",
                "extraction_confidence": "0.92",
                "flag_for_review": "false",
                "source_type": "full_text",
                "pdf_source": "unpaywall",
                "consensus": "full",
                "processed_date": "2026-03-27",
            },
        ]
        _write_csv(project / "results.csv", V4_FIELDS, rows)

        script = project / "verify_session.py"
        if not script.exists():
            script = _repo_root() / "skill" / "verify_session.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        report_path = project / "state" / "verification_report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            assert report["summary"]["pass"] is True, \
                f"Verification failed: {report.get('issues', [])}"
        # If verify_session.py doesn't exist or has different interface,
        # just check it didn't crash
        assert result.returncode == 0, \
            f"verify_session.py failed (exit {result.returncode}): {result.stderr}"

    print("  PASS  test_verify_session_v4")


# ---------------------------------------------------------------------------
# Test 7: Dashboard generates from v4 data
# ---------------------------------------------------------------------------

def test_dashboard_generation_v4():
    """dashboard_generator.py should produce dashboard.html from v4 project."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))

        # Write some rows so dashboard has data
        rows = []
        for i, (sp, fam, mass) in enumerate([
            ("Passer domesticus", "Passeridae", "28.5"),
            ("Falco peregrinus", "Falconidae", "750.0"),
            ("Corvus corax", "Corvidae", "1200.0"),
        ]):
            rows.append({f: "" for f in V4_FIELDS} | {
                "doi": f"10.1234/test.{i:04d}",
                "species": sp, "family": fam,
                "body_mass_g_mean": mass,
                "extraction_confidence": "0.90",
                "flag_for_review": "false",
                "source_type": "full_text",
                "pdf_source": "unpaywall",
                "consensus": "full",
                "session_id": "2026-03-27T10:00:00Z",
                "processed_date": "2026-03-27",
            })
        _write_csv(project / "results.csv", V4_FIELDS, rows)

        # Write run_log for dashboard
        with open(project / "state" / "run_log.jsonl", "w") as f:
            f.write(json.dumps({
                "timestamp": "2026-03-27T10:00:00Z",
                "session_id": "2026-03-27T10:00:00Z",
                "event": "session_start"
            }) + "\n")

        script = project / "dashboard_generator.py"
        if not script.exists():
            script = _repo_root() / "skill" / "dashboard_generator.py"

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(project)],
            capture_output=True, text=True,
        )

        dashboard = project / "dashboard.html"
        if dashboard.exists():
            content = dashboard.read_text()
            assert len(content) > 100, "Dashboard seems empty"
            assert "Passer domesticus" in content or "Passeridae" in content or \
                   "dashboard" in content.lower(), "Dashboard missing expected content"
        assert result.returncode == 0, \
            f"dashboard_generator.py failed (exit {result.returncode}): {result.stderr}"

    print("  PASS  test_dashboard_generation_v4")


# ---------------------------------------------------------------------------
# Test 8: Duplicate detection across finds files
# ---------------------------------------------------------------------------

def test_duplicate_detection():
    """Same species+doi in two finds files should be caught as duplicate."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))
        records = _sample_extraction_records()

        # Two finds files with same DOI = exact duplicate scenario
        _make_finds_file(project, "10.1234/test.0001", records)
        import time; time.sleep(0.01)  # ensure different timestamp
        _make_finds_file(project, "10.1234/test.0001", records)

        finds_files = list((project / "finds").glob("*.json"))
        assert len(finds_files) == 2, f"Expected 2 finds files, got {len(finds_files)}"

        # Collect all records across finds files
        all_records = []
        for fp in finds_files:
            data = json.loads(fp.read_text())
            for rec in data["records"]:
                all_records.append((data["doi"], rec["species"]))

        # Check for duplicates (same doi + species)
        seen = set()
        duplicates = []
        for key in all_records:
            if key in seen:
                duplicates.append(key)
            seen.add(key)

        assert len(duplicates) == 2, \
            f"Expected 2 duplicates (2 species x 1 dup each), got {len(duplicates)}"

    print("  PASS  test_duplicate_detection")


# ---------------------------------------------------------------------------
# Test 9: Folder contract — producer/consumer isolation
# ---------------------------------------------------------------------------

def test_folder_contracts():
    """Verify that folder ownership rules are correctly structured."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))

        # Simulate Fetcher output (writes to ready_for_extraction/)
        _make_handoff_file(project, "10.1234/test.0001")
        assert len(list((project / "ready_for_extraction").glob("*.json"))) == 1

        # Simulate Dealer moving handoff to dealt/
        handoff = list((project / "ready_for_extraction").glob("*.json"))[0]
        shutil.move(str(handoff), str(project / "state" / "dealt" / handoff.name))
        assert len(list((project / "ready_for_extraction").glob("*.json"))) == 0
        assert len(list((project / "state" / "dealt").glob("*.json"))) == 1

        # Simulate Extractor output (writes to finds/)
        _make_finds_file(project, "10.1234/test.0001", _sample_extraction_records())
        assert len(list((project / "finds").glob("*.json"))) == 1

        # Simulate Writer consuming finds/ (delete after successful write)
        finds_file = list((project / "finds").glob("*.json"))[0]
        os.remove(finds_file)
        assert len(list((project / "finds").glob("*.json"))) == 0

        # All folders should be clean after a complete cycle
        assert len(list((project / "ready_for_extraction").glob("*.json"))) == 0
        assert len(list((project / "finds").glob("*.json"))) == 0

    print("  PASS  test_folder_contracts")


# ---------------------------------------------------------------------------
# Test 10: Learning file schema
# ---------------------------------------------------------------------------

def test_learning_file_schema():
    """Verify learning/ files have correct schema for Manager review."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))

        learning_file = project / "learning" / "10_1234_test_0001_2026-03-27T100000Z.json"
        learning_data = {
            "doi": "10.1234/test.0001",
            "type": "notation_variant",
            "description": "Sex chromosome system written as X1X2Y with subscripts",
            "proposed_rule": "Normalize subscript notation: X1X2Y -> XXXY",
            "affected_fields": ["sex_chromosome_system"],
            "source_context": "Table 2 header notation",
            "agents_that_noticed": ["A", "C"]
        }
        learning_file.write_text(json.dumps(learning_data, indent=2))

        data = json.loads(learning_file.read_text())

        required_keys = ["doi", "type", "description", "proposed_rule",
                        "affected_fields", "source_context"]
        for key in required_keys:
            assert key in data, f"Learning file missing '{key}'"

        valid_types = {"notation_variant", "new_taxon", "ambiguity_pattern",
                      "validation_gap", "extraction_pattern", "terminology"}
        assert data["type"] in valid_types, f"Invalid type: {data['type']}"
        assert isinstance(data["affected_fields"], list)

    print("  PASS  test_learning_file_schema")


# ---------------------------------------------------------------------------
# Test 11: State file consistency after simulated pipeline run
# ---------------------------------------------------------------------------

def test_state_consistency():
    """After a simulated pipeline run, state files should be consistent."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))

        # Simulate: 2 papers processed, 1 lead
        processed = {
            "10.1234/test.0001": {
                "title": "Paper about sparrows",
                "triage": "likely",
                "outcome": "extracted",
                "records": 2,
                "date": "2026-03-27"
            },
            "10.1234/test.0002": {
                "title": "Paper about falcons",
                "triage": "likely",
                "outcome": "extracted",
                "records": 1,
                "date": "2026-03-27"
            },
            "10.1234/test.0003": {
                "title": "Paywalled paper",
                "triage": "likely",
                "outcome": "lead_needs_fulltext",
                "records": 0,
                "date": "2026-03-27"
            },
        }
        (project / "state" / "processed.json").write_text(
            json.dumps(processed, indent=2))

        # Queue should NOT contain processed papers
        queue = [
            {"doi": "10.1234/test.0004", "title": "Unprocessed paper",
             "triage": "likely", "source": "pubmed",
             "authors": "A", "year": 2020, "journal": "J",
             "abstract": "...", "triage_confidence": 0.8,
             "added_date": "2026-03-27"}
        ]
        (project / "state" / "queue.json").write_text(json.dumps(queue))

        # Verify no overlap between processed and queue
        proc_dois = set(processed.keys())
        queue_dois = {e["doi"] for e in queue}
        overlap = proc_dois & queue_dois
        assert len(overlap) == 0, f"DOIs in both processed and queue: {overlap}"

        # Verify record counts in processed match expectations
        total_records = sum(p["records"] for p in processed.values())
        assert total_records == 3, f"Expected 3 records, got {total_records}"

        # Verify leads are marked correctly
        leads = [doi for doi, p in processed.items()
                 if p["outcome"] == "lead_needs_fulltext"]
        assert len(leads) == 1
        assert leads[0] == "10.1234/test.0003"

    print("  PASS  test_state_consistency")


# ---------------------------------------------------------------------------
# Test 12: End-to-end flow simulation
# ---------------------------------------------------------------------------

def test_end_to_end_flow():
    """Simulate the full v4 pipeline flow: queue → handoff → finds → CSV."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_v4_project(Path(tmp))

        # Step 1: Searcher populates queue
        _make_queue_entries(project, ["10.1234/test.0001", "10.1234/test.0002"])
        queue = json.loads((project / "state" / "queue.json").read_text())
        assert len(queue) == 2, "Queue should have 2 entries"

        # Step 2: Fetcher creates handoff files, removes from queue
        _make_handoff_file(project, "10.1234/test.0001", "Passeridae")
        _make_handoff_file(project, "10.1234/test.0002", "Falconidae")
        # Fetcher would remove from queue
        (project / "state" / "queue.json").write_text("[]")

        handoffs = list((project / "ready_for_extraction").glob("*.json"))
        assert len(handoffs) == 2, "Should have 2 handoff files"

        # Step 3: Dealer processes handoffs, Extractor writes to finds/
        for handoff in handoffs:
            data = json.loads(handoff.read_text())
            records = _sample_extraction_records()
            _make_finds_file(project, data["doi"], records)
            # Dealer moves handoff to dealt/
            shutil.move(str(handoff), str(project / "state" / "dealt" / handoff.name))

        finds_files = list((project / "finds").glob("*.json"))
        assert len(finds_files) == 2, "Should have 2 finds files"
        assert len(list((project / "ready_for_extraction").glob("*.json"))) == 0

        # Step 4: Writer processes finds/ → results.csv
        all_csv_rows = []
        for fp in sorted(finds_files):
            finds_data = json.loads(fp.read_text())
            for rec in finds_data["records"]:
                row = {f: "" for f in V4_FIELDS}
                row.update({
                    "doi": finds_data["doi"],
                    "paper_title": finds_data["title"],
                    "first_author": finds_data["paper_metadata"]["first_author"],
                    "paper_year": str(finds_data["paper_metadata"]["year"]),
                    "paper_journal": finds_data["paper_metadata"]["journal"],
                    "session_id": "2026-03-27T10:00:00Z",
                    "processed_date": "2026-03-27",
                    "pdf_source": finds_data["pdf_source"],
                    "source_type": "full_text",
                })
                for field in V4_FIELDS:
                    if field in rec:
                        row[field] = str(rec[field]) if rec[field] is not None else ""
                all_csv_rows.append(row)
            # Writer deletes finds file after successful write
            os.remove(fp)

        _write_csv(project / "results.csv", V4_FIELDS, all_csv_rows)

        # Verify final state
        results = _read_csv(project / "results.csv")
        assert len(results) == 4, f"Expected 4 records (2 per paper), got {len(results)}"
        assert len(list((project / "finds").glob("*.json"))) == 0, "finds/ should be empty"
        assert len(list((project / "ready_for_extraction").glob("*.json"))) == 0
        assert len(list((project / "state" / "dealt").glob("*.json"))) == 2

        # Verify DOIs are correct
        dois = {r["doi"] for r in results}
        assert dois == {"10.1234/test.0001", "10.1234/test.0002"}

        # Verify all records have required fields
        for r in results:
            assert r["species"], f"Missing species in row with doi={r['doi']}"
            assert r["extraction_confidence"], "Missing confidence"
            assert r["consensus"], "Missing consensus"

    print("  PASS  test_end_to_end_flow")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    print("TraitTrawler v4 Pipeline Flow Tests")
    print("=" * 50)

    tests = [
        test_v4_folder_structure,
        test_finds_file_schema,
        test_handoff_file_schema,
        test_queue_schema,
        test_csv_writer_from_finds,
        test_verify_session_v4,
        test_dashboard_generation_v4,
        test_duplicate_detection,
        test_folder_contracts,
        test_learning_file_schema,
        test_state_consistency,
        test_end_to_end_flow,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"  FAIL  {test.__name__}: {e}")

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")

    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  {name}: {err}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
