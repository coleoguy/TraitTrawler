#!/usr/bin/env python3
"""Smoke tests for TraitTrawler v6 core scripts.

Exercises the deterministic pipeline end-to-end using synthetic inputs
and project-local hooks (matching the v6.1 trait-agnostic redesign).

Run:
    cd skill && python3 tests/test_smoke.py
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=cwd)


# Project-local karyotype hooks used only by this test.
# Mirrors what a real user's state/hooks/*.py would look like.

KARYOTYPE_HOOK_HAC = '''"""Enforce HAC == (2n - sex_chrom_count) / 2."""
from typing import Any

def hook_hac_consistency(row: dict, ctx: Any):
    d = row.get("diploid_2n")
    h = row.get("haploid_autosome_count")
    s = row.get("sex_chrom_count")
    if d in (None, "") or h in (None, "") or s in (None, ""):
        return Pass("hook_hac_consistency")
    try:
        d, h, s = int(d), int(h), int(s)
    except (TypeError, ValueError):
        return Fail("HAC inputs not integers", "hook_hac_consistency")
    expected = (d - s) / 2
    if expected != h:
        return Fail(
            f"HAC inconsistent: (2n - sex)/2 = {expected}, reported HAC = {h}",
            "hook_hac_consistency",
        )
    return Pass("hook_hac_consistency")
'''

KARYOTYPE_HOOK_SEX = '''"""Flag simple XY when quote indicates X1X2Y, neoXY, or multiple."""
import re
from typing import Any

COMPLEX = re.compile(r"X[_\\s]?[1-9]|neo[\\s\\-]?XY|multiple\\s+sex\\s+chrom", re.I)

def hook_sex_system_regex(row: dict, ctx: Any):
    quote = row.get("verbatim_quote") or ""
    sys_val = (row.get("sex_system") or "").upper()
    if COMPLEX.search(quote) and sys_val in ("XY", "XX"):
        return Fail(
            "quote indicates complex sex system but row says simple XY",
            "hook_sex_system_regex",
        )
    return Pass("hook_sex_system_regex")
'''


def _setup_karyotype_project(tmp_root: Path) -> None:
    """Create a v6 project with karyotype hooks installed as project-local."""
    run([
        sys.executable, str(SCRIPTS / "setup_project.py"),
        "--root", str(tmp_root),
        "--trait", "diploid chromosome number",
        "--taxa", "Coleoptera",
    ])
    # Sandbox-validate the karyotype hooks before installing.
    hooks_dir = tmp_root / "state" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "hac_consistency.py").write_text(KARYOTYPE_HOOK_HAC)
    (hooks_dir / "sex_system_regex.py").write_text(KARYOTYPE_HOOK_SEX)
    # Run the sandbox on each
    for f in ("hac_consistency.py", "sex_system_regex.py"):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "hook_sandbox.py"),
             str(hooks_dir / f)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, \
            f"sandbox rejected {f}: {result.stderr}"

    schema = {
        "trait_name": "karyotype",
        "primary_trait_key": "karyotype",
        "columns": {
            "sha256":              {"type": "string", "required": True},
            "page":                {"type": "int",    "required": True},
            "verbatim_quote":      {"type": "string", "required": True},
            "canonical_species":   {"type": "string", "required": False},
            "diploid_2n":          {"type": "int",    "required": False},
            "haploid_autosome_count": {"type": "int", "required": False},
            "sex_chrom_count":     {"type": "int",    "required": False},
            "sex_system":          {"type": "enum",   "required": False,
                                    "values": ["XY", "XX", "X0", "ZW",
                                               "X1X2Y", "neoXY", "multiple",
                                               "unknown"]},
        },
        "trait_hooks": [
            "state/hooks/hac_consistency.py",
            "state/hooks/sex_system_regex.py",
        ],
    }
    (tmp_root / "state" / "schema.json").write_text(json.dumps(schema))


def test_setup_and_project_hooks(tmp_root: Path) -> None:
    _setup_karyotype_project(tmp_root)

    good_row = {
        "sha256": "a" * 64, "page": 4,
        "verbatim_quote": "Chrysolina americana has 2n = 22 with XY sex chromosomes.",
        "canonical_species": "Chrysolina americana",
        "diploid_2n": 22, "haploid_autosome_count": 10, "sex_chrom_count": 2,
        "sex_system": "XY", "doi": "10.0000/good",
        "grounding_verified": True, "taxonomy_status": "resolved",
    }
    swap_row = {
        "sha256": "b" * 64, "page": 2,
        "verbatim_quote": "Galerucella calmariensis exhibits 2n = 34.",
        "canonical_species": "Galerucella calmariensis",
        "diploid_2n": 34, "haploid_autosome_count": 34,  # bogus HAC
        "sex_chrom_count": 2, "sex_system": "XY", "doi": "10.0000/swap",
        "grounding_verified": True, "taxonomy_status": "resolved",
    }
    complex_row = {
        "sha256": "c" * 64, "page": 3,
        "verbatim_quote": "Blaps gigas has 2n = 15 + X1X2Y3 system.",
        "canonical_species": "Blaps gigas", "diploid_2n": 18,
        "sex_system": "XY",  # wrong: quote says X1X2Y3
        "doi": "10.0000/complex",
        "grounding_verified": True, "taxonomy_status": "resolved",
    }
    rows_path = tmp_root / "state" / "rows" / "smoke.jsonl"
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    rows_path.write_text("\n".join(
        json.dumps(r) for r in (good_row, swap_row, complex_row)
    ) + "\n")

    result = run([
        sys.executable, str(SCRIPTS / "hooks.py"),
        "--rows", str(rows_path),
        "--schema", str(tmp_root / "state" / "schema.json"),
        "--ledger", str(tmp_root / "state" / "ledger.jsonl"),
        "--csv", str(tmp_root / "results.csv"),
        "--disputes", str(tmp_root / "state" / "disputes.jsonl"),
        "--session-id", "test",
    ])
    stats = json.loads(result.stdout)
    assert stats["total"] == 3, stats
    assert stats["passed"] == 1, f"expected 1 pass; got {stats}"
    assert stats["disputed"] == 2, f"expected 2 disputed; got {stats}"
    assert stats["project_hooks"] == 2, stats  # hac_consistency + sex_system_regex

    ledger_lines = (tmp_root / "state" / "ledger.jsonl").read_text().splitlines()
    assert len(ledger_lines) == 1
    entry = json.loads(ledger_lines[0])
    hook_names = {r["hook"] for r in entry["hook_results"]}
    assert "hook_hac_consistency" in hook_names
    assert "hook_sex_system_regex" in hook_names

    disputes = [json.loads(l) for l in
                (tmp_root / "state" / "disputes.jsonl").read_text().splitlines() if l.strip()]
    reasons = " ".join(" ".join(d.get("failure_reasons", [])) for d in disputes)
    assert "hook_hac_consistency" in reasons
    assert "hook_sex_system_regex" in reasons


def test_sandbox_blocks_unsafe_hooks(tmp_root: Path) -> None:
    """Sandbox must reject hooks that do I/O, import disallowed modules,
    or reference banned builtins."""
    run([
        sys.executable, str(SCRIPTS / "setup_project.py"),
        "--root", str(tmp_root),
        "--trait", "x", "--taxa", "y",
    ])

    UNSAFE_CASES = [
        ("import_os", 'import os\ndef hook_x(row, ctx):\n    return Pass("x")'),
        ("subprocess", 'import subprocess\ndef hook_x(row, ctx):\n    return Pass("x")'),
        ("open_file", 'def hook_x(row, ctx):\n    open("/tmp/x")\n    return Pass("x")'),
        ("exec_call", 'def hook_x(row, ctx):\n    exec("x=1")\n    return Pass("x")'),
        ("dunder", 'def hook_x(row, ctx):\n    row.__class__\n    return Pass("x")'),
        ("print", 'def hook_x(row, ctx):\n    print("sneaky")\n    return Pass("x")'),
    ]
    SAFE_CASES = [
        ("plain", 'def hook_x(row, ctx):\n    return Pass("x")'),
        ("regex", 'import re\nRX = re.compile(r"x")\ndef hook_x(row, ctx):\n    if RX.search(row.get("verbatim_quote", "")):\n        return Fail("bad", "hook_x")\n    return Pass("hook_x")'),
        ("math", 'import math\ndef hook_x(row, ctx):\n    if math.sqrt(4) != 2.0:\n        return Fail("math broken", "hook_x")\n    return Pass("hook_x")'),
    ]

    scratch = tmp_root / "state" / "hooks" / "test"
    scratch.mkdir(parents=True, exist_ok=True)

    for name, src in UNSAFE_CASES:
        p = scratch / f"{name}.py"
        p.write_text(src)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "hook_sandbox.py"), str(p)],
            capture_output=True, text=True,
        )
        assert r.returncode == 2, f"sandbox should have rejected {name}: {r.stdout} {r.stderr}"

    for name, src in SAFE_CASES:
        p = scratch / f"{name}.py"
        p.write_text(src)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "hook_sandbox.py"), str(p)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"sandbox should have accepted {name}: {r.stderr}"


def test_review_queue_roundtrip(tmp_root: Path) -> None:
    test_setup_and_project_hooks(tmp_root)
    disputes_path = tmp_root / "state" / "disputes.jsonl"
    assert disputes_path.stat().st_size > 0

    r = run([
        sys.executable, str(SCRIPTS / "review_queue.py"),
        "--project-root", str(tmp_root),
        "enqueue",
    ])
    assert '"enqueued": 2' in r.stdout

    out_html = tmp_root / "reports" / "r.html"
    out_html.parent.mkdir(exist_ok=True)
    run([
        sys.executable, str(SCRIPTS / "review_queue.py"),
        "--project-root", str(tmp_root),
        "emit-html",
        "--out", str(out_html),
    ])
    body = out_html.read_text()
    assert body.count('class="item"') == 2

    queue_lines = (tmp_root / "state" / "review_queue.jsonl").read_text().splitlines()
    ids = [json.loads(l)["review_id"] for l in queue_lines]
    dec = tmp_root / "dec.csv"
    dec.write_text("review_id,decision,comment\n"
                   f"{ids[0]},confirm,hook was wrong\n"
                   f"{ids[1]},reject,definitely wrong\n")
    r = run([
        sys.executable, str(SCRIPTS / "review_queue.py"),
        "--project-root", str(tmp_root),
        "apply",
        "--decisions", str(dec),
    ])
    stats = json.loads(r.stdout)
    assert stats["confirmed"] == 1
    assert stats["rejected"] == 1


def test_dispatch_state_machine(tmp_root: Path) -> None:
    run([sys.executable, str(SCRIPTS / "setup_project.py"),
         "--root", str(tmp_root), "--trait", "x", "--taxa", "y"])
    for _ in range(3):
        run([sys.executable, str(SCRIPTS / "dispatch.py"),
             "--project-root", str(tmp_root), "advance"])
    r = run([sys.executable, str(SCRIPTS / "dispatch.py"),
             "--project-root", str(tmp_root), "phase"])
    assert r.stdout.strip() == "4.FETCH", r.stdout


def test_bootstrap_ingests_curated_csv(tmp_root: Path) -> None:
    """End-to-end bootstrap: CSV → ledger + exemplars + derived hooks."""
    run([sys.executable, str(SCRIPTS / "setup_project.py"),
         "--root", str(tmp_root), "--trait", "karyotype",
         "--taxa", "Coleoptera"])

    csv_path = tmp_root / "curated.csv"
    # Write a synthetic curated CSV mimicking Heath's real dataset
    lines = ["species,doi,trait_key,trait_value,diploid_2n,sex_system,verbatim_quote,notation_style\n"]
    species_rows = [
        ("Chrysolina americana", "10.1/a", 22, "XY", "2n = 22, XY"),
        ("Chrysolina menthastri", "10.1/b", 24, "XY", "2n = 24, XY"),
        ("Galerucella calmariensis", "10.1/c", 34, "XY", "2n = 34"),
        ("Galerucella pusilla", "10.1/d", 34, "XY", "2n = 34"),
        ("Blaps gigas", "10.1/e", 18, "X1X2Y", "2n = 15 + X1X2Y"),
        ("Tribolium castaneum", "10.1/f", 20, "XY", "2n = 20"),
        ("Tribolium confusum", "10.1/g", 18, "XY", "2n = 18"),
        ("Leptinotarsa decemlineata", "10.1/h", 36, "XY", "2n = 36"),
        ("Otiorhynchus sulcatus", "10.1/i", 22, "X0", "2n = 22, X0"),
        ("Pyrrhalta viburni", "10.1/j", 38, "XY", "2n = 38"),
        ("Carabus granulatus", "10.1/k", 28, "XY", "2n = 28"),
        ("Carabus nemoralis", "10.1/l", 28, "XY", "2n = 28"),
    ]
    for sp, doi, d2n, sys_v, quote in species_rows:
        lines.append(f'"{sp}",{doi},"diploid_2n",{d2n},{d2n},{sys_v},"{quote}",inline_prose\n')
    csv_path.write_text("".join(lines))

    r = run([
        sys.executable, str(SCRIPTS / "bootstrap.py"),
        "--root", str(tmp_root),
        "--csv", str(csv_path),
        "--skip-gbif",  # no network
    ])
    summary = json.loads(r.stdout)
    assert summary["imported"] == 12, summary
    assert summary["exemplars"] >= 1
    assert (tmp_root / "state" / "bootstrap" / "imported.jsonl").exists()
    assert (tmp_root / "state" / "bootstrap" / "exemplars.jsonl").exists()

    # Ledger got 12 human-curated entries
    ledger = [json.loads(l) for l in
              (tmp_root / "state" / "ledger.jsonl").read_text().splitlines() if l.strip()]
    assert len(ledger) == 12
    assert all(e["source_type"] == "human_curated_bootstrap" for e in ledger)
    assert all(e["dwc_identificationVerificationStatus"] == "ValidatedByHuman"
               for e in ledger)

    # Derive hooks
    r2 = run([
        sys.executable, str(SCRIPTS / "derive_hooks.py"),
        "--project-root", str(tmp_root),
    ])
    derived = json.loads(r2.stdout)
    assert derived["proposed"] >= 1, derived
    proposed_dir = tmp_root / "state" / "hooks" / "proposed"
    assert any(p.suffix == ".py" for p in proposed_dir.iterdir())

    # All proposed hooks pass the sandbox (important — we generated them)
    for p in proposed_dir.glob("*.py"):
        r3 = subprocess.run(
            [sys.executable, str(SCRIPTS / "hook_sandbox.py"), str(p)],
            capture_output=True, text=True,
        )
        assert r3.returncode == 0, f"derived hook {p.name} failed sandbox: {r3.stderr}"


def test_messy_migration(tmp_root: Path) -> None:
    """End-to-end messy migration: a source folder with multiple CSVs,
    auxiliary files, weird column names, and PDFs whose filenames don't
    exactly match the CSV's pdf_filename column.

    Exercises: migration_preflight.py (classification + fuzzy column
    mapping), pair_pdfs.py (fuzzy pairing across 4 strategies),
    bootstrap.py (--dry-run + --column-map + --suspect-csv +
    --papers-needed), migration_report.md generation.
    """
    # 1. Set up project
    run([sys.executable, str(SCRIPTS / "setup_project.py"),
         "--root", str(tmp_root),
         "--trait", "arbitrary trait for testing",
         "--taxa", "any"])

    # 2. Build a messy source folder
    source = tmp_root.parent / "messy_source"
    source.mkdir(exist_ok=True)
    pdfs_dir = source / "pdfs"
    pdfs_dir.mkdir(exist_ok=True)

    # 2a. Main dataset with weird column names (not pre-aliased)
    main_csv = source / "myproj_dataset_2024.csv"
    main_csv.write_text(
        "Sp_Name,DOI,Ref,MyValue,Notes,pdf_file\n"
        '"Alpha beta",10.1/paper-a,Smith 2020,42,"field notes",smith2020.pdf\n'
        '"Gamma delta",10.1/paper-b,Jones 2019,18,,jones_et_al_2019.pdf\n'
        '"Epsilon zeta",,Brown 2021,33,"compilation entry",\n'
        '"Eta theta",10.1/paper-d,Lee 2018,27,,lee-2018-a.pdf\n'
    )

    # 2b. "Suspect records" auxiliary
    suspect_csv = source / "suspect records.csv"
    suspect_csv.write_text(
        "Sp_Name,MyValue,reason\n"
        '"Iota kappa",99,"2n seems high for this genus"\n'
        '"Lambda mu",0,"zero is implausible"\n'
    )

    # 2c. "Papers needed" auxiliary (newline-delimited DOIs)
    papers_needed = source / "papers_needed.txt"
    papers_needed.write_text(
        "# List of papers to fetch\n"
        "10.1/needed-a\n"
        "10.1/needed-b\n"
        "A paper titled without a DOI\n"
    )

    # 2d. PDFs with various naming conventions. Each file gets unique
    # content so SHA256 hashes differ — otherwise content-dedup would
    # collapse them and we could not detect orphans.
    for name in [
        "smith2020.pdf",              # EXACT_STEM match
        "jones_et_al_2019.pdf",       # EXACT_STEM
        "10.1-paper-d_lee-2018.pdf",  # DOI_IN_NAME
        "random_orphan.pdf",          # Orphan
        "another_orphan.pdf",         # Orphan
    ]:
        (pdfs_dir / name).write_bytes(
            b"%PDF-1.4\n%fake for test " + name.encode() + b"\n%%EOF\n"
        )

    # 3. Run migration_preflight.py WITHOUT user aliases
    r = run([sys.executable, str(SCRIPTS / "migration_preflight.py"),
             "--root", str(tmp_root),
             "--source", str(source)])
    summary = json.loads(r.stdout)
    assert summary["pdf_count"] == 5, summary
    # Core aliases should map Sp_Name -> canonical_species, DOI -> doi, etc.
    plan_json = json.loads(
        (tmp_root / "state" / "bootstrap" / "migration_plan.json").read_text()
    )
    main_file = plan_json["main_dataset"]
    mapping = main_file["proposed_mapping"]
    assert mapping.get("Sp_Name") == "canonical_species", mapping
    assert mapping.get("DOI") == "doi", mapping
    assert mapping.get("pdf_file") == "pdf_filename", mapping
    # Ref could map to original_citation (fuzzy) OR pass through
    # Trait-specific columns like MyValue should NOT auto-map (core
    # skill is trait-agnostic; MyValue has to come via user aliases
    # or dialogue)
    assert "MyValue" in main_file.get("unmapped_headers", []), \
        "MyValue should be unmapped in the core skill"
    # Classification: auxiliary files
    roles = plan_json["roles"]
    assert any("suspect records.csv" in p for p in roles.get("review_queue", [])), roles
    assert any("papers_needed.txt" in p for p in roles.get("papers_needed", [])), roles
    assert any("myproj_dataset_2024.csv" in p for p in roles.get("main_dataset", [])), roles

    # 4. Run migration_preflight.py WITH user-supplied aliases
    user_aliases = tmp_root / "column_aliases.json"
    user_aliases.write_text(json.dumps({
        "my_trait_value": ["MyValue", "value_num"],
    }))
    r2 = run([sys.executable, str(SCRIPTS / "migration_preflight.py"),
              "--root", str(tmp_root),
              "--source", str(source),
              "--user-aliases", str(user_aliases)])
    plan2 = json.loads(
        (tmp_root / "state" / "bootstrap" / "migration_plan.json").read_text()
    )
    main2 = plan2["main_dataset"]
    assert main2["proposed_mapping"].get("MyValue") == "my_trait_value", \
        f"user alias should map MyValue: {main2['proposed_mapping']}"
    assert "MyValue" not in main2.get("unmapped_headers", [])

    # 5. Build column_map.json (what the subagent would write after dialogue)
    col_map = tmp_root / "state" / "bootstrap" / "column_map.json"
    col_map.write_text(json.dumps({
        "Sp_Name": "canonical_species",
        "DOI": "doi",
        "Ref": "original_citation",
        "MyValue": "my_trait_value",
        "pdf_file": "pdf_filename",
    }))

    # 6. Run pair_pdfs.py
    r3 = run([sys.executable, str(SCRIPTS / "pair_pdfs.py"),
              "--root", str(tmp_root),
              "--csv", str(main_csv),
              "--pdfs", str(pdfs_dir),
              "--column-map", str(col_map),
              "--no-title-peek"])
    pair_summary = json.loads(r3.stdout)
    assert pair_summary["rows"] == 4, pair_summary
    # smith2020.pdf and jones_et_al_2019.pdf match by EXACT_STEM;
    # 10.1-paper-d_lee-2018.pdf matches by DOI_IN_NAME
    strat = pair_summary["strategy_counts"]
    assert strat.get("EXACT_STEM", 0) >= 2, strat
    assert pair_summary["paired_pdfs_unique"] >= 2, pair_summary
    # Orphans: random_orphan.pdf, another_orphan.pdf
    assert pair_summary["orphan_pdf_count"] >= 2, pair_summary

    # 7. bootstrap.py --dry-run
    r4 = run([sys.executable, str(SCRIPTS / "bootstrap.py"),
              "--root", str(tmp_root),
              "--csv", str(main_csv),
              "--pdfs", str(pdfs_dir),
              "--pairing-report", str(tmp_root / "state" / "bootstrap" / "pairing_report.json"),
              "--column-map", str(col_map),
              "--suspect-csv", str(suspect_csv),
              "--papers-needed", str(papers_needed),
              "--dry-run",
              "--skip-gbif"])
    boot_sum = json.loads(r4.stdout)
    assert boot_sum["dry_run"] is True, boot_sum
    assert boot_sum["imported"] == 4, boot_sum
    assert boot_sum["paired_to_pdf"] >= 2, boot_sum
    assert boot_sum["orphan_pdfs"] >= 2, boot_sum
    assert boot_sum["suspect_records_added"] == 2, boot_sum
    assert boot_sum["papers_needed_added"] == 3, boot_sum

    # Migration report exists
    report = (tmp_root / "state" / "bootstrap" / "migration_report.md").read_text()
    assert "Migration Report" in report
    assert "DRY RUN" in report
    assert "EXACT_STEM" in report

    # 8. Ledger should be EMPTY after dry-run (key correctness check)
    ledger_size = (tmp_root / "state" / "ledger.jsonl").stat().st_size
    assert ledger_size == 0, "dry-run must not write ledger entries"

    # 9. Real commit
    r5 = run([sys.executable, str(SCRIPTS / "bootstrap.py"),
              "--root", str(tmp_root),
              "--csv", str(main_csv),
              "--pdfs", str(pdfs_dir),
              "--pairing-report", str(tmp_root / "state" / "bootstrap" / "pairing_report.json"),
              "--column-map", str(col_map),
              "--suspect-csv", str(suspect_csv),
              "--papers-needed", str(papers_needed),
              "--skip-gbif"])
    boot_sum2 = json.loads(r5.stdout)
    assert boot_sum2["dry_run"] is False, boot_sum2
    # Ledger should now have 4 entries
    ledger_lines = (tmp_root / "state" / "ledger.jsonl").read_text().splitlines()
    assert len(ledger_lines) == 4, f"expected 4 ledger lines, got {len(ledger_lines)}"
    for l in ledger_lines:
        entry = json.loads(l)
        assert entry["source_type"] == "human_curated_bootstrap"
        assert entry["dwc_identificationVerificationStatus"] == "ValidatedByHuman"

    # Review queue should have 2 suspect items with pending state
    rq_lines = (tmp_root / "state" / "review_queue.jsonl").read_text().splitlines()
    assert len(rq_lines) == 2
    for l in rq_lines:
        item = json.loads(l)
        assert item["resolution_state"] == "pending"
        assert item["source"] == "bootstrap_suspect_csv"

    # candidates.jsonl should have 3 papers-needed entries
    cand_lines = (tmp_root / "candidates.jsonl").read_text().splitlines()
    cands = [json.loads(l) for l in cand_lines if l.strip()]
    assert len(cands) == 3
    for c in cands:
        assert c["source_api"] == "bootstrap_papers_needed"


def test_checkpoint_and_session_log(tmp_root: Path) -> None:
    """checkpoint.py + session_log.py: compaction-safe state recovery."""
    test_setup_and_project_hooks(tmp_root)  # gives us a ledger + disputes
    # Write a couple of session_log entries
    run([sys.executable, str(SCRIPTS / "session_log.py"),
         "--root", str(tmp_root),
         "--batch", "1", "--papers-in-batch", "10",
         "--rows-written", "8", "--to-review", "2", "--adjudicated", "0",
         "--interesting", "Smith 2013 contradicts Jones 1998"])
    run([sys.executable, str(SCRIPTS / "session_log.py"),
         "--root", str(tmp_root),
         "--batch", "2", "--papers-in-batch", "10",
         "--rows-written", "12", "--to-review", "1", "--adjudicated", "0"])
    log_text = (tmp_root / "state" / "manager_log.md").read_text()
    assert "Manager Session Log" in log_text
    assert "batch 1" in log_text and "batch 2" in log_text
    assert "Smith 2013" in log_text

    # Write a checkpoint
    r = run([sys.executable, str(SCRIPTS / "checkpoint.py"),
             "--project-root", str(tmp_root)])
    summary = json.loads(r.stdout)
    assert summary["ledger_count"] >= 1
    ckpt_path = tmp_root / "state" / "manager_checkpoint.md"
    assert ckpt_path.exists()
    ckpt_text = ckpt_path.read_text()
    assert "Manager Checkpoint" in ckpt_text
    assert "Current phase" in ckpt_text
    assert "Output counts" in ckpt_text
    assert "Resume instructions" in ckpt_text
    # `checkpoint --show` reads it back
    r2 = run([sys.executable, str(SCRIPTS / "checkpoint.py"),
              "--project-root", str(tmp_root), "--show"])
    assert "Manager Checkpoint" in r2.stdout


def test_v5_migrate_and_linkage_repair(tmp_root: Path) -> None:
    """v5_migrate classifies + moves cruft; repair_linkage adds sha256."""
    run([sys.executable, str(SCRIPTS / "setup_project.py"),
         "--root", str(tmp_root),
         "--trait", "anything", "--taxa", "any"])

    # Synthetic v5 directory inside the project root
    v5 = tmp_root / "legacy_v5"
    v5.mkdir()
    # v5 markers
    (v5 / "pipeline_state.json").write_text("{}")
    (v5 / "processed.json").write_text("{}")
    (v5 / "dashboard_generator.py").write_text("# v5 dashboard")
    (v5 / "verify_session.py").write_text("# v5 verifier")
    (v5 / "guide.md").write_text("# v5 domain guide")
    (v5 / "ill_list.csv").write_text("doi,title\n10.1/a,Needed A\n")
    (v5 / "results.csv").write_text("species,doi,diploid_2n\nAlpha beta,10.1/x,22\n")
    (v5 / "pdfs").mkdir()
    (v5 / "pdfs" / "paper_10_1_x.pdf").write_bytes(
        b"%PDF-1.4\n%fake content\n%%EOF\n")
    (v5 / "finds").mkdir()
    (v5 / "finds" / "smith.json").write_text("{}")
    (v5 / "audit_results").mkdir()
    (v5 / "audit_results" / "a.json").write_text("{}")

    # Plan-only pass
    r = run([sys.executable, str(SCRIPTS / "v5_migrate.py"),
             "--root", str(tmp_root),
             "--source", str(v5)])
    summary = json.loads(r.stdout)
    assert summary["mode"] == "plan-only"
    assert summary["is_v5"] is True, summary
    assert summary["counts"]["DEPRECATE"] >= 4, summary
    assert summary["counts"]["MIGRATE"] >= 2, summary  # guide.md + ill_list.csv
    assert summary["counts"]["KEEP"] >= 2, summary  # results.csv + pdfs/

    # Confirm plan files exist
    assert (tmp_root / "state" / "bootstrap" / "v5_cleanup_plan.json").exists()
    assert (tmp_root / "state" / "bootstrap" / "v5_cleanup_plan.md").exists()

    # Execute pass — moves DEPRECATE items
    r2 = run([sys.executable, str(SCRIPTS / "v5_migrate.py"),
              "--root", str(tmp_root),
              "--source", str(v5),
              "--execute"])
    s2 = json.loads(r2.stdout)
    assert s2["mode"] == "executed"
    assert s2["moved_count"] >= 4
    # Originally-deprecated items should no longer exist at source
    assert not (v5 / "pipeline_state.json").exists()
    assert not (v5 / "finds").exists()
    assert not (v5 / "dashboard_generator.py").exists()
    # Migrate items stay in place
    assert (v5 / "guide.md").exists()
    assert (v5 / "ill_list.csv").exists()
    # Keep items stay in place
    assert (v5 / "results.csv").exists()
    assert (v5 / "pdfs").exists()
    # deprecated/ dir now exists
    deprecated_root = v5 / "deprecated"
    assert deprecated_root.exists()
    # And it has the moved items
    subdirs = list(deprecated_root.iterdir())
    assert len(subdirs) == 1
    stamp_dir = subdirs[0]
    assert (stamp_dir / "pipeline_state.json").exists()

    # Manifest written
    manifest = json.loads(
        (tmp_root / "state" / "bootstrap" / "v5_manifest.json").read_text()
    )
    assert "rollback_command" in manifest
    assert len(manifest["moved"]) >= 4

    # === repair_linkage ===
    # Hash the surviving PDF into manifest.sqlite
    run([sys.executable, str(SCRIPTS / "pdf_ingest.py"),
         "--scan",
         "--project-root", str(tmp_root)])  # won't find anything in v5/pdfs/
    # Also ingest explicitly from v5/pdfs
    run([sys.executable, str(SCRIPTS / "pdf_ingest.py"),
         "--file", str(v5 / "pdfs" / "paper_10_1_x.pdf"),
         "--project-root", str(tmp_root)])

    # Run report-only repair pass on the v5 results.csv
    r3 = run([sys.executable, str(SCRIPTS / "repair_linkage.py"),
              "--root", str(tmp_root),
              "--csv", str(v5 / "results.csv")])
    rep = json.loads(r3.stdout)
    assert rep["total_rows"] == 1
    # Strategy should be DOI_IN_STEM (10.1/x → paper_10_1_x.pdf) or UNPAIRED
    # depending on how the stem normalizes
    strategies = rep["strategies"]
    assert any(k in strategies for k in ("DOI_IN_STEM", "FILENAME", "UNPAIRED")), strategies

    # Actually repair: rewrites the CSV with sha256 column
    r4 = run([sys.executable, str(SCRIPTS / "repair_linkage.py"),
              "--root", str(tmp_root),
              "--csv", str(v5 / "results.csv"),
              "--repair"])
    rep2 = json.loads(r4.stdout)
    assert "backup" in rep2
    # Backup was created
    assert Path(rep2["backup"]).exists()
    # The repaired CSV has a sha256 column
    with (v5 / "results.csv").open() as f:
        reader = csv.reader(f)
        header = next(reader)
        assert "sha256" in header, header


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        test_setup_and_project_hooks(Path(d) / "proj_hooks")
        print("OK: project-local karyotype hooks end-to-end")
    with tempfile.TemporaryDirectory() as d:
        test_sandbox_blocks_unsafe_hooks(Path(d) / "proj_sandbox")
        print("OK: hook sandbox blocks unsafe code, accepts safe code")
    with tempfile.TemporaryDirectory() as d:
        test_review_queue_roundtrip(Path(d) / "proj_review")
        print("OK: review queue roundtrip")
    with tempfile.TemporaryDirectory() as d:
        test_dispatch_state_machine(Path(d) / "proj_dispatch")
        print("OK: dispatch state machine")
    with tempfile.TemporaryDirectory() as d:
        test_bootstrap_ingests_curated_csv(Path(d) / "proj_boot")
        print("OK: bootstrap ingests curated CSV + derives hooks")
    with tempfile.TemporaryDirectory() as d:
        test_messy_migration(Path(d) / "proj_messy")
        print("OK: messy migration (preflight + fuzzy pairing + aux files + dry-run)")
    with tempfile.TemporaryDirectory() as d:
        test_checkpoint_and_session_log(Path(d) / "proj_ckpt")
        print("OK: checkpoint + session log (compaction-safe state recovery)")
    with tempfile.TemporaryDirectory() as d:
        test_v5_migrate_and_linkage_repair(Path(d) / "proj_v5")
        print("OK: v5 cleanup + linkage repair (deprecate dir + sha256 backfill)")
    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
