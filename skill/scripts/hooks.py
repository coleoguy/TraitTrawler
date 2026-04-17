#!/usr/bin/env python3
"""Deterministic hook gate.

Hooks are pure Python functions that validate a proposed Row against
both domain-agnostic invariants (grounding, schema, dedup) and trait-
specific rules (range, arithmetic, regex). Each hook returns Pass() or
Fail(reason).

CLI usage:
  python hooks.py --rows state/rows/<sha>.jsonl \
                  --schema state/schema.json \
                  --ledger state/ledger.jsonl \
                  --csv results.csv \
                  --disputes state/disputes.jsonl

Exit code 0 always (partial failures are routed to disputes, not an
error).
"""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import re
import sqlite3
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
    severity: str = "hard"  # "hard" -> dispute, "soft" -> log only


def Pass(hook: str = "") -> HookResult:
    return HookResult("pass", "", hook)


def Fail(reason: str, hook: str = "", severity: str = "hard") -> HookResult:
    return HookResult("fail", reason, hook, severity)


# ------------------------------------------------------------------
# Context passed to each hook
# ------------------------------------------------------------------


@dataclass
class HookContext:
    schema: dict
    ledger_path: Path
    written_keys: set  # DOI composite keys already seen this session


# ------------------------------------------------------------------
# Domain-agnostic hooks (ALWAYS ON)
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
    if not row.get("grounding_verified"):
        return Fail("claim did not pass verify_quote.py", "hook_quote_verified")
    return Pass("hook_quote_verified")


def hook_cited_value_in_quote(row: dict, ctx: HookContext) -> HookResult:
    """For columns flagged `cited_value_required: true` in the schema, the
    literal numeric value must appear in the verbatim_quote. Opt-in per
    column because derived fields (computed counts, page numbers) need not
    appear in the quote.
    """
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
                return Fail(f"{name} expected int, got {type(value).__name__}", "hook_schema_valid")
            if t == "float" and not isinstance(value, (int, float)):
                return Fail(f"{name} expected float", "hook_schema_valid")
            if t == "enum":
                if value not in cfg.get("values", []):
                    return Fail(
                        f"{name}={value!r} not in allowed enum {cfg.get('values')}",
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
        return Fail(f"duplicate (doi, species, trait) key: {key}",
                    "hook_doi_composite_unique")
    ctx.written_keys.add(key)
    return Pass("hook_doi_composite_unique")


def hook_gbif_resolved(row: dict, ctx: HookContext) -> HookResult:
    status = row.get("taxonomy_status")
    if status == "unresolved":
        return Fail("canonical_species did not resolve in GBIF backbone",
                    "hook_gbif_resolved", severity="soft")
    return Pass("hook_gbif_resolved")


# ------------------------------------------------------------------
# Trait-specific hooks for karyotype projects (registered by schema)
# ------------------------------------------------------------------


def hook_2n_range(row: dict, ctx: HookContext) -> HookResult:
    v = row.get("diploid_2n")
    if v is None or v == "":
        return Pass("hook_2n_range")
    try:
        v = int(v)
    except (TypeError, ValueError):
        return Fail(f"diploid_2n not an int: {v!r}", "hook_2n_range")
    if not 2 <= v <= 500:
        return Fail(f"diploid_2n={v} outside biological range", "hook_2n_range")
    return Pass("hook_2n_range")


def hook_hac_consistency(row: dict, ctx: HookContext) -> HookResult:
    d = row.get("diploid_2n")
    h = row.get("haploid_autosome_count")
    s = row.get("sex_chrom_count")
    if d in (None, "") or h in (None, "") or s in (None, ""):
        return Pass("hook_hac_consistency")
    try:
        d, h, s = int(d), int(h), int(s)
    except (TypeError, ValueError):
        return Fail("HAC consistency inputs not integers", "hook_hac_consistency")
    expected = (d - s) / 2
    if expected != h:
        return Fail(
            f"HAC inconsistent: (2n - sex_chrom_count)/2 = {expected}, "
            f"but haploid_autosome_count = {h} (likely 2n/HAC swap)",
            "hook_hac_consistency",
        )
    return Pass("hook_hac_consistency")


COMPLEX_SEX_REGEX = re.compile(
    r"X[\u2080\u2081\u2082_\s]?[0-9]|neo[\s\-]?XY|multiple\s+sex\s+chrom", re.IGNORECASE
)


def hook_sex_system_regex(row: dict, ctx: HookContext) -> HookResult:
    quote = row.get("verbatim_quote") or ""
    sys_val = (row.get("sex_system") or "").upper()
    if COMPLEX_SEX_REGEX.search(quote) and sys_val in ("XY", "XX"):
        return Fail(
            "quote indicates complex sex system (e.g. X1X2Y, neoXY) but row says simple XY",
            "hook_sex_system_regex",
        )
    return Pass("hook_sex_system_regex")


# ------------------------------------------------------------------
# Hook registry
# ------------------------------------------------------------------


AGNOSTIC_HOOKS: list[Callable] = [
    hook_has_sha256_and_page,
    hook_has_verbatim_quote,
    hook_quote_verified,
    hook_cited_value_in_quote,
    hook_schema_valid,
    hook_doi_composite_unique,
    hook_gbif_resolved,
]

# Trait-specific hook registry: schema declares which ones to load.
TRAIT_HOOK_TABLE: dict[str, Callable] = {
    "hook_2n_range": hook_2n_range,
    "hook_hac_consistency": hook_hac_consistency,
    "hook_sex_system_regex": hook_sex_system_regex,
}


def resolve_trait_hooks(schema: dict) -> list[Callable]:
    names = schema.get("trait_hooks", [])
    out: list[Callable] = []
    for n in names:
        if n in TRAIT_HOOK_TABLE:
            out.append(TRAIT_HOOK_TABLE[n])
        else:
            # Allow custom hooks declared in an external module
            try:
                mod_name, fn_name = n.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                out.append(getattr(mod, fn_name))
            except Exception as e:
                print(f"WARN: could not resolve hook {n}: {e}", file=sys.stderr)
    return out


def load_written_keys(ledger_path: Path) -> set:
    keys = set()
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
            # Derive the composite key from the entry if stored
            # (best-effort; worst case dedup hook is slightly leaky
            # across sessions and can be rebuilt from results.csv).
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
    ap.add_argument("--rows", required=True, type=Path,
                    help="JSONL file of proposed rows from structurer")
    ap.add_argument("--schema", required=True, type=Path)
    ap.add_argument("--ledger", required=True, type=Path)
    ap.add_argument("--csv", required=True, type=Path,
                    help="results.csv to append passes to")
    ap.add_argument("--disputes", required=True, type=Path,
                    help="state/disputes.jsonl to append failures to")
    ap.add_argument("--session-id", default="unknown")
    ap.add_argument("--extractor-model", default="claude-opus-4-7")
    ap.add_argument("--verifier-model", default="claude-sonnet-4-6")
    ap.add_argument("--trait-profile", type=Path)
    args = ap.parse_args()

    schema = json.loads(args.schema.read_text())
    trait_hooks = resolve_trait_hooks(schema)
    all_hooks = AGNOSTIC_HOOKS + trait_hooks
    ctx = HookContext(
        schema=schema,
        ledger_path=args.ledger,
        written_keys=load_written_keys(args.ledger),
    )

    from ledger import append_entry  # type: ignore

    columns = list(schema.get("columns", {}).keys())
    # Ensure csv has a header
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

    stats = {"total": 0, "passed": 0, "disputed": 0}
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
                    # Append ledger entry, then CSV row with the ledger_id
                    ledger_id = append_entry(
                        args.ledger,
                        row=row,
                        claim=row,  # row carries forward claim_id, uncertainty
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
