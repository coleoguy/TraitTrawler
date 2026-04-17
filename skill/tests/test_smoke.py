#!/usr/bin/env python3
"""Smoke tests for TraitTrawler v6 core scripts.

Exercises the deterministic pipeline end-to-end using synthetic inputs
and project-local hooks (matching the v6.1 trait-agnostic redesign).

Run:
    cd skill && python3 tests/test_smoke.py
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
    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
