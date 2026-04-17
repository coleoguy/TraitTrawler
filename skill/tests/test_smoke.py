#!/usr/bin/env python3
"""Smoke tests for TraitTrawler v6 core scripts.

These tests do not exercise the LLM subagents; they verify the
deterministic Python pipeline (setup, ingest, hooks, ledger, review)
works end-to-end with synthetic inputs.

Run:
    cd skill && python -m pytest tests/ -v
or:
    cd skill && python tests/test_smoke.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=cwd)


def test_setup_and_ingest_and_hooks(tmp_root: Path) -> None:
    # 1. Initialize project
    run([
        sys.executable, str(SCRIPTS / "setup_project.py"),
        "--root", str(tmp_root),
        "--trait", "diploid chromosome number",
        "--taxa", "Coleoptera",
    ])
    assert (tmp_root / "state" / "session.json").exists()
    assert (tmp_root / "state" / "manifest.sqlite").exists()
    assert (tmp_root / "config.yaml").exists()

    sess = json.loads((tmp_root / "state" / "session.json").read_text())
    assert sess["phase"] == "1.LEARN"

    # 2. Write a minimal schema that enables karyotype hooks
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
        "trait_hooks": ["hook_2n_range", "hook_hac_consistency",
                        "hook_sex_system_regex"],
    }
    (tmp_root / "state" / "schema.json").write_text(json.dumps(schema))

    # 3. Write two rows: one clean, one with a 2n/HAC swap
    good_row = {
        "sha256": "a" * 64,
        "page": 4,
        "verbatim_quote": "Chrysolina americana has 2n = 22 with XY sex chromosomes.",
        "canonical_species": "Chrysolina americana",
        "diploid_2n": 22,
        "haploid_autosome_count": 10,
        "sex_chrom_count": 2,
        "sex_system": "XY",
        "doi": "10.0000/good",
        "grounding_verified": True,
        "taxonomy_status": "resolved",
    }
    swap_row = {
        "sha256": "b" * 64,
        "page": 2,
        "verbatim_quote": "Galerucella calmariensis exhibits 2n = 34.",
        "canonical_species": "Galerucella calmariensis",
        # Deliberately WRONG: HAC reported as 2n value
        "diploid_2n": 34,
        "haploid_autosome_count": 34,  # wrong; should be ~16
        "sex_chrom_count": 2,
        "sex_system": "XY",
        "doi": "10.0000/swap",
        "grounding_verified": True,
        "taxonomy_status": "resolved",
    }
    complex_row = {
        "sha256": "c" * 64,
        "page": 3,
        "verbatim_quote": "Blaps gigas has 2n = 15 + X1X2Y3 system, see Fig. 1.",
        "canonical_species": "Blaps gigas",
        "diploid_2n": 18,
        "sex_system": "XY",  # Wrong: quote says X1X2Y3
        "doi": "10.0000/complex",
        "grounding_verified": True,
        "taxonomy_status": "resolved",
    }
    rows_path = tmp_root / "state" / "rows" / "smoke.jsonl"
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    rows_path.write_text("\n".join(json.dumps(r) for r in (good_row, swap_row, complex_row)) + "\n")

    # 4. Run hook gate
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
    assert stats["passed"] == 1, f"expected 1 pass (good_row only); got {stats}"
    assert stats["disputed"] == 2, f"expected 2 disputes (swap + complex); got {stats}"

    # 5. Verify ledger entries and disputes captured the hook names
    ledger_lines = (tmp_root / "state" / "ledger.jsonl").read_text().splitlines()
    assert len(ledger_lines) == 1, "one ledger entry per passing row"
    entry = json.loads(ledger_lines[0])
    hook_names = {r["hook"] for r in entry["hook_results"]}
    assert "hook_has_sha256_and_page" in hook_names
    assert "hook_hac_consistency" in hook_names

    disputes = [json.loads(l) for l in
                (tmp_root / "state" / "disputes.jsonl").read_text().splitlines() if l.strip()]
    assert len(disputes) == 2
    all_reasons = " ".join(" ".join(d.get("failure_reasons", [])) for d in disputes)
    assert "hook_hac_consistency" in all_reasons, all_reasons
    assert "hook_sex_system_regex" in all_reasons, all_reasons


def test_review_queue_roundtrip(tmp_root: Path) -> None:
    # setup + schema + hooks produce disputes
    test_setup_and_ingest_and_hooks(tmp_root)
    disputes_path = tmp_root / "state" / "disputes.jsonl"
    assert disputes_path.stat().st_size > 0

    # enqueue -> expect 2 pending items
    r = run([
        sys.executable, str(SCRIPTS / "review_queue.py"),
        "--project-root", str(tmp_root),
        "enqueue",
    ])
    assert '"enqueued": 2' in r.stdout, r.stdout

    # emit HTML -> file exists and contains 2 item divs
    out_html = tmp_root / "reports" / "r.html"
    out_html.parent.mkdir(exist_ok=True)
    r = run([
        sys.executable, str(SCRIPTS / "review_queue.py"),
        "--project-root", str(tmp_root),
        "emit-html",
        "--out", str(out_html),
    ])
    body = out_html.read_text()
    assert body.count('class="item"') == 2
    assert 'X1X2Y' in body or 'sex_system_regex' in body

    # write a decisions CSV: confirm one, reject one
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
    # results.csv should now have 2 rows (1 original pass + 1 confirmed)
    results_lines = (tmp_root / "results.csv").read_text().splitlines()
    assert len(results_lines) >= 3  # header + original pass + confirmed
    # legacy_rejected.csv should have 1 row
    rej_lines = (tmp_root / "legacy_rejected.csv").read_text().splitlines()
    assert len(rej_lines) >= 2


def test_dispatch_state_machine(tmp_root: Path) -> None:
    run([sys.executable, str(SCRIPTS / "setup_project.py"),
         "--root", str(tmp_root), "--trait", "x", "--taxa", "y"])
    for _ in range(3):
        run([sys.executable, str(SCRIPTS / "dispatch.py"),
             "--project-root", str(tmp_root), "advance"])
    r = run([sys.executable, str(SCRIPTS / "dispatch.py"),
             "--project-root", str(tmp_root), "phase"])
    assert r.stdout.strip() == "4.FETCH", r.stdout


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "proj_hooks"
        test_setup_and_ingest_and_hooks(root)
        print("OK: setup + ingest + hooks")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "proj_review"
        test_review_queue_roundtrip(root)
        print("OK: review queue roundtrip")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "proj_dispatch"
        test_dispatch_state_machine(root)
        print("OK: dispatch state machine")
    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
