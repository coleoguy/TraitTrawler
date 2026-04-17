#!/usr/bin/env python3
"""Deterministic hook gate.

Hooks validate a proposed Row against both domain-agnostic invariants
(grounding, schema, dedup, taxonomy) and project-specific rules that
live in `state/hooks/*.py`. Each project-specific hook is a pure Python
function that was auto-proposed by the trait_learner or hand-written by
the user, passed through `scripts/hook_sandbox.py` for safety, and
approved via AskUserQuestion before being enabled.

The core skill carries ZERO trait-specific logic. No karyotype hooks,
no chromosome range checks, no sex-system regex lives in this file.
All of that is project-local.

CLI usage:
  python hooks.py --rows state/rows/<sha>.jsonl \
                  --schema state/schema.json \
                  --ledger state/ledger.jsonl \
                  --csv results.csv \
                  --disputes state/disputes.jsonl

Exit code 0 always (partial failures are routed to disputes, not errors).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# ------------------------------------------------------------------
# Hook result types
# ------------------------------------------------------------------


@dataclass
class HookResult:
    verdict: str  # "pass" or "fail"
    reason: str = ""
    hook: str = ""
    severity: str = "hard"  # "hard" -> dispute, "soft" -> warn but write


def Pass(hook: str = "") -> HookResult:
    return HookResult("pass", "", hook)


def Fail(reason: str, hook: str = "", severity: str = "hard") -> HookResult:
    return HookResult("fail", reason, hook, severity)


@dataclass
class HookContext:
    schema: dict
    ledger_path: Path
    written_keys: set  # DOI composite keys already seen


# ------------------------------------------------------------------
# Domain-agnostic hooks (ALWAYS ON, regardless of trait)
# ------------------------------------------------------------------


def hook_has_sha256_and_page(row: dict, ctx: HookContext) -> HookResult:
    if not row.get("sha256"):
        return Fail("missing sha256", "hook_has_sha256_and_page")
    if not isinstance(row.get("page"), int):
        return Fail("page must be an int", "hook_has_sha256_and_page")
    return Pass("hook_has_sha256_and_page")


def hook_has_verbatim_quote(row: dict, ctx: HookContext) -> HookResult:
    q = row.get("verbatim_quote")
    if not q or not isinstance(q, str) or len(q.strip()) < 5:
        return Fail("verbatim_quote empty or too short", "hook_has_verbatim_quote")
    return Pass("hook_has_verbatim_quote")


def hook_quote_verified(row: dict, ctx: HookContext) -> HookResult:
    # Bootstrap rows are human-curated and marked as such — they don't need
    # grounding verification (the curator already did it).
    if row.get("source_type") == "human_curated_bootstrap":
        return Pass("hook_quote_verified")
    if not row.get("grounding_verified"):
        return Fail("claim did not pass verify_quote.py", "hook_quote_verified")
    return Pass("hook_quote_verified")


def hook_cited_value_in_quote(row: dict, ctx: HookContext) -> HookResult:
    """For columns flagged `cited_value_required: true`, the literal numeric
    value must appear in verbatim_quote. Opt-in per column."""
    quote = row.get("verbatim_quote") or ""
    for col, cfg in ctx.schema.get("columns", {}).items():
        if not cfg.get("cited_value_required"):
            continue
        if cfg.get("type") not in ("int", "float"):
            continue
        val = row.get(col)
        if val is None or val == "":
            continue
        if str(val) not in quote:
            return Fail(
                f"column {col}={val} not present in verbatim_quote",
                "hook_cited_value_in_quote",
            )
    return Pass("hook_cited_value_in_quote")


def hook_schema_valid(row: dict, ctx: HookContext) -> HookResult:
    cols = ctx.schema.get("columns", {})
    for name, cfg in cols.items():
        required = cfg.get("required", False)
        value = row.get(name)
        if required and (value is None or value == ""):
            return Fail(f"required column {name} is empty", "hook_schema_valid")
        if value is None or value == "":
            continue
        t = cfg.get("type")
        try:
            if t == "int" and not isinstance(value, int):
                return Fail(f"{name} expected int, got {type(value).__name__}",
                            "hook_schema_valid")
            if t == "float" and not isinstance(value, (int, float)):
                return Fail(f"{name} expected float", "hook_schema_valid")
            if t == "enum":
                if value not in cfg.get("values", []):
                    return Fail(
                        f"{name}={value!r} not in enum {cfg.get('values')}",
                        "hook_schema_valid",
                    )
        except Exception as e:
            return Fail(f"{name} validation error: {e}", "hook_schema_valid")
    return Pass("hook_schema_valid")


def hook_doi_composite_unique(row: dict, ctx: HookContext) -> HookResult:
    doi = row.get("doi") or row.get("sha256")
    species = row.get("canonical_species") or row.get("species")
    trait = row.get("trait_key") or ctx.schema.get("primary_trait_key", "value")
    key = (doi, species, trait)
    if key in ctx.written_keys:
        return Fail(f"duplicate (doi, species, trait): {key}",
                    "hook_doi_composite_unique")
    ctx.written_keys.add(key)
    return Pass("hook_doi_composite_unique")


def hook_gbif_resolved(row: dict, ctx: HookContext) -> HookResult:
    status = row.get("taxonomy_status")
    if status == "unresolved":
        return Fail("canonical_species did not resolve in GBIF backbone",
                    "hook_gbif_resolved", severity="soft")
    return Pass("hook_gbif_resolved")


AGNOSTIC_HOOKS: list[Callable] = [
    hook_has_sha256_and_page,
    hook_has_verbatim_quote,
    hook_quote_verified,
    hook_cited_value_in_quote,
    hook_schema_valid,
    hook_doi_composite_unique,
    hook_gbif_resolved,
]


# ------------------------------------------------------------------
# Per-project hook loader
# ------------------------------------------------------------------


def load_project_hooks(schema: dict, schema_path: Path) -> list[Callable]:
    """Load project-specific hooks listed in schema.json.trait_hooks.

    Each entry in `trait_hooks` is a path (absolute or relative to the
    project root) pointing to a Python file that defines one or more
    functions matching the hook signature. The file MUST have already
    been validated by scripts/hook_sandbox.py; this loader enforces the
    same safety subset at load time as a defense in depth.

    Convention: the module may define any number of top-level functions
    named `hook_*`. Every such function is registered.
    """
    loaded: list[Callable] = []
    trait_hooks = schema.get("trait_hooks", [])
    if not trait_hooks:
        return loaded

    # Import the sandbox linter (sibling module). Fail loudly if missing —
    # we refuse to load project-specific hooks without sandbox validation.
    try:
        from hook_sandbox import validate_hook_source, HookSandboxError
    except ImportError:
        here = Path(__file__).resolve().parent
        sys.path.insert(0, str(here))
        from hook_sandbox import validate_hook_source, HookSandboxError  # type: ignore

    # Project root is the parent of schema.json
    project_root = schema_path.resolve().parent.parent  # state/schema.json -> project_root

    for entry in trait_hooks:
        p = Path(entry)
        if not p.is_absolute():
            p = (project_root / entry).resolve()
        if not p.exists():
            print(f"WARN: project hook missing on disk: {p}", file=sys.stderr)
            continue
        try:
            validate_hook_source(p.read_text())
        except HookSandboxError as e:
            print(f"REJECTED unsafe hook {p}: {e}", file=sys.stderr)
            continue
        # Load the module
        spec = importlib.util.spec_from_file_location(
            f"project_hooks_{p.stem}", p
        )
        if not spec or not spec.loader:
            continue
        mod = importlib.util.module_from_spec(spec)
        # Inject the Pass/Fail helpers into the module's globals so
        # hook files can call them without importing anything. This
        # matches the ergonomic contract documented in
        # references/hooks_reference.md.
        mod.Pass = Pass  # type: ignore[attr-defined]
        mod.Fail = Fail  # type: ignore[attr-defined]
        mod.HookResult = HookResult  # type: ignore[attr-defined]
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            print(f"WARN: could not exec {p}: {e}", file=sys.stderr)
            continue
        # Re-inject after exec_module in case the module body shadowed
        # them (it shouldn't, but be defensive).
        mod.Pass = Pass  # type: ignore[attr-defined]
        mod.Fail = Fail  # type: ignore[attr-defined]
        mod.HookResult = HookResult  # type: ignore[attr-defined]
        for name in dir(mod):
            if not name.startswith("hook_"):
                continue
            fn = getattr(mod, name)
            if callable(fn):
                loaded.append(fn)
    return loaded


# ------------------------------------------------------------------
# Ledger dedup key helpers
# ------------------------------------------------------------------


def load_written_keys(ledger_path: Path) -> set:
    keys: set = set()
    if not ledger_path.exists():
        return keys
    with ledger_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            keys.add((
                entry.get("doi"),
                entry.get("canonical_species"),
                entry.get("trait_key"),
            ))
    return keys


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, type=Path)
    ap.add_argument("--schema", required=True, type=Path)
    ap.add_argument("--ledger", required=True, type=Path)
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--disputes", required=True, type=Path)
    ap.add_argument("--session-id", default="unknown")
    ap.add_argument("--extractor-model", default="claude-opus-4-7")
    ap.add_argument("--verifier-model", default="claude-sonnet-4-6")
    ap.add_argument("--trait-profile", type=Path)
    args = ap.parse_args()

    schema = json.loads(args.schema.read_text())
    project_hooks = load_project_hooks(schema, args.schema)
    all_hooks = AGNOSTIC_HOOKS + project_hooks
    ctx = HookContext(
        schema=schema,
        ledger_path=args.ledger,
        written_keys=load_written_keys(args.ledger),
    )

    # Local import to avoid hard dependency when hooks.py is used as a lib
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from ledger import append_entry  # type: ignore

    columns = list(schema.get("columns", {}).keys())
    write_header = not args.csv.exists() or args.csv.stat().st_size == 0
    csv_f = args.csv.open("a", newline="")
    dispute_f = args.disputes.open("a")
    writer = csv.DictWriter(
        csv_f,
        fieldnames=columns + ["ledger_id", "sha256", "page", "verbatim_quote"],
        extrasaction="ignore",
    )
    if write_header:
        writer.writeheader()

    stats = {"total": 0, "passed": 0, "disputed": 0,
             "agnostic_hooks": len(AGNOSTIC_HOOKS),
             "project_hooks": len(project_hooks)}
    try:
        with args.rows.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("type") == "structuring_error":
                    stats["disputed"] += 1
                    stats["total"] += 1
                    dispute_f.write(json.dumps({
                        "dispute_id": f"dsp_{stats['total']}",
                        "row": row,
                        "failure_reasons": [f"structuring_error: {row.get('reason')}"],
                    }) + "\n")
                    continue
                stats["total"] += 1
                results = [h(row, ctx) for h in all_hooks]
                hard_failures = [r for r in results
                                 if r.verdict == "fail" and r.severity == "hard"]
                hook_results_for_ledger = [
                    {"hook": r.hook, "verdict": r.verdict, "reason": r.reason,
                     "severity": r.severity}
                    for r in results
                ]
                if hard_failures:
                    stats["disputed"] += 1
                    dispute_f.write(json.dumps({
                        "dispute_id": f"dsp_{stats['total']}",
                        "row": row,
                        "failure_reasons": [
                            f"{r.hook}: {r.reason}" for r in hard_failures
                        ],
                        "hook_results": hook_results_for_ledger,
                        "verbatim_quote": row.get("verbatim_quote"),
                        "quote_preceding_10w": row.get("quote_preceding_10w"),
                        "quote_following_10w": row.get("quote_following_10w"),
                    }) + "\n")
                else:
                    ledger_id = append_entry(
                        args.ledger,
                        row=row,
                        claim=row,
                        hook_results=hook_results_for_ledger,
                        session_id=args.session_id,
                        extractor_model=args.extractor_model,
                        semantic_verifier_model=args.verifier_model,
                        trait_profile_path=args.trait_profile,
                        schema_path=args.schema,
                    )
                    row["ledger_id"] = ledger_id
                    writer.writerow(row)
                    stats["passed"] += 1
    finally:
        csv_f.close()
        dispute_f.close()

    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
