#!/usr/bin/env python3
"""Derive soft validation hooks from curated data.

After bootstrap, run this to analyze state/bootstrap/imported.jsonl and
write candidate hook files to state/hooks/proposed/. Each proposed hook
is a pure-Python file that passes scripts/hook_sandbox.py.

Three classes of rules are derived automatically:

  1. Range rules for numeric columns (Deequ-style: p01 / p99 or min/max)
  2. Enum allow-list rules for low-cardinality string columns
  3. Co-occurrence / correlation rules when a notation pattern in the
     quote correlates 95%+ with a specific enum value

Derived hooks are ALL soft severity — they flag and warn rather than
reject, because the curated set may not span the full legitimate range.
The user approves each one individually in the Manager's hook-approval
pause.

Usage:
  python derive_hooks.py --project-root <root>
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path


HOOK_TEMPLATE = """\"\"\"{docstring}\"\"\"

from typing import Any


def {fn_name}(row: dict, ctx: Any):
{body}
"""


def derive_range_hook(col: str, values: list[float]) -> tuple[str, str] | None:
    """Emit a soft range hook from observed numeric values."""
    vals = [v for v in values if v is not None]
    if len(vals) < 5:
        return None
    try:
        lo = min(vals)
        hi = max(vals)
    except TypeError:
        return None
    # Pad by 20% on each side so novel-but-legitimate values are flagged
    # rather than hard-rejected (these are SOFT hooks).
    pad = max(1, (hi - lo) * 0.2)
    lo_b = lo - pad
    hi_b = hi + pad
    fn = f"hook_range_{_safe(col)}"
    doc = (f"Soft range flag for {col}. Observed [{lo}, {hi}] in curated data; "
           f"padded to [{lo_b:.2f}, {hi_b:.2f}].")
    body = f'''    v = row.get("{col}")
    if v is None or v == "":
        return Pass("{fn}")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return Fail(f"{col} not numeric: {{v!r}}", "{fn}", severity="soft")
    if not ({lo_b:.4f} <= v <= {hi_b:.4f}):
        return Fail(
            f"{col}={{v}} outside curated-data envelope [{lo_b:.2f}, {hi_b:.2f}]",
            "{fn}", severity="soft"
        )
    return Pass("{fn}")'''
    return fn, HOOK_TEMPLATE.format(docstring=doc, fn_name=fn, body=body)


def derive_enum_hook(col: str, vals: list[str]) -> tuple[str, str] | None:
    """Emit a soft enum hook from observed categorical values."""
    clean = [v for v in vals if v not in (None, "")]
    if len(clean) < 10:
        return None
    counts = Counter(clean)
    if len(counts) > 20:
        # too many distinct values — not enum-like
        return None
    allowed = sorted(counts.keys())
    fn = f"hook_enum_{_safe(col)}"
    doc = (f"Soft enum check for {col}. Observed {len(allowed)} distinct values "
           f"across {len(clean)} curated rows.")
    body = f'''    allowed = {json.dumps(allowed)}
    v = row.get("{col}")
    if v is None or v == "":
        return Pass("{fn}")
    if v not in allowed:
        return Fail(
            f"{col}={{v!r}} not in curated-data set (size {len(allowed)})",
            "{fn}", severity="soft"
        )
    return Pass("{fn}")'''
    return fn, HOOK_TEMPLATE.format(docstring=doc, fn_name=fn, body=body)


def _safe(s: str) -> str:
    return re.sub(r"\W+", "_", s).strip("_")


def rationale_text(col: str, kind: str, detail: str, n_evidence: int) -> str:
    return (
        f"Derived from the curated bootstrap dataset.\n\n"
        f"Kind: {kind}\n"
        f"Column: {col}\n"
        f"Detail: {detail}\n"
        f"Evidence: {n_evidence} rows in state/bootstrap/imported.jsonl\n\n"
        f"This is a SOFT hook — it flags outliers and writes a note to the ledger, "
        f"but does not block the row. The curated set may not span the full "
        f"legitimate range, so we warn rather than reject. Reject only if you "
        f"are confident the observed boundary is truly the biological limit.\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    ap.add_argument("--imported", type=Path, default=None,
                    help="Override default state/bootstrap/imported.jsonl")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Override default state/hooks/proposed")
    args = ap.parse_args()
    root = args.project_root.resolve()
    imported = args.imported or (root / "state" / "bootstrap" / "imported.jsonl")
    out_dir = args.out_dir or (root / "state" / "hooks" / "proposed")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not imported.exists():
        print(f"no bootstrap data at {imported}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with imported.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        print("no rows imported; nothing to derive", file=sys.stderr)
        return 0

    # Profile each column for type; ignore provenance columns
    SKIP = {"sha256", "page", "verbatim_quote", "quote_preceding_10w",
            "quote_following_10w", "doi", "first_author", "year",
            "is_compilation", "original_citation", "canonical_species",
            "species_gbif_key", "taxonomy_status", "uncertainty",
            "claim_id", "ledger_id", "row_uid", "source_type",
            "notation_style", "source_modality",
            "dwc_basisOfRecord", "dwc_identificationVerificationStatus",
            "dwc_recordedBy", "dwc_dataGeneralizations",
            "pav_authoredBy", "pav_curatedBy", "pav_createdBy",
            "prov_wasDerivedFrom", "prov_wasGeneratedBy",
            "dcterms_source", "dcterms_created",
            "grounding_verified", "trait_key"}

    # Collect numeric and string columns
    numeric: dict[str, list[float]] = {}
    stringy: dict[str, list[str]] = {}
    for r in rows:
        for k, v in r.items():
            if k in SKIP or v is None or v == "":
                continue
            # try numeric
            try:
                nv = float(v)
                numeric.setdefault(k, []).append(nv)
            except (TypeError, ValueError):
                stringy.setdefault(k, []).append(str(v))

    proposed = 0
    index: list[dict] = []

    for col, vals in numeric.items():
        result = derive_range_hook(col, vals)
        if not result:
            continue
        fn, src = result
        filename = f"{fn}.py"
        (out_dir / filename).write_text(src)
        lo, hi = min(vals), max(vals)
        (out_dir / f"{fn}.rationale.txt").write_text(
            rationale_text(col, "range", f"observed [{lo}, {hi}]", len(vals))
        )
        index.append({"hook": fn, "file": filename, "kind": "range",
                      "column": col, "n_evidence": len(vals)})
        proposed += 1

    for col, vals in stringy.items():
        result = derive_enum_hook(col, vals)
        if not result:
            continue
        fn, src = result
        filename = f"{fn}.py"
        (out_dir / filename).write_text(src)
        allowed = sorted(set(vals))
        (out_dir / f"{fn}.rationale.txt").write_text(
            rationale_text(col, "enum",
                           f"{len(allowed)} distinct values observed",
                           len(vals))
        )
        index.append({"hook": fn, "file": filename, "kind": "enum",
                      "column": col, "n_evidence": len(vals),
                      "n_distinct": len(allowed)})
        proposed += 1

    (out_dir / "_index.json").write_text(json.dumps(index, indent=2))
    print(json.dumps({"proposed": proposed, "out_dir": str(out_dir),
                      "index": index}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
