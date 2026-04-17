# Hooks Reference

Hooks are the deterministic Python gates that run on every proposed Row
before it reaches `results.csv`. They are the concrete expression of
"domain logic as code, not prompt."

There are two tiers of hooks and a strict boundary between them:

1. **Agnostic hooks** live in `scripts/hooks.py` and run on every
   project regardless of trait. They enforce grounding, schema,
   deduplication, and taxonomy invariants. This tier never changes
   when you start a new project.

2. **Project-specific hooks** live in `state/hooks/*.py` inside the
   project root. They are proposed by the `trait_learner` subagent,
   validated by `scripts/hook_sandbox.py`, and approved by the user
   before they ever execute. The core skill contains **zero** trait-
   specific hook code.

## Hook signature

```python
def hook_name(row: dict, ctx) -> "HookResult":
    """One-line docstring explaining what this hook enforces."""
    ...
    return Pass("hook_name")
    # or
    return Fail("reason", "hook_name", severity="hard")
```

- `row` is the proposed Row dict.
- `ctx` is a `HookContext` with `schema`, `ledger_path`, `written_keys`.
- Return `Pass()` or `Fail(reason, hook, severity)`. Hard failures send
  the row to `state/disputes.jsonl` for the Adjudicator. Soft failures
  write a note to the ledger but allow the write.

## Agnostic hooks (always on)

- **`hook_has_sha256_and_page`** — Row must carry a non-null `sha256`
  and an integer `page`.
- **`hook_has_verbatim_quote`** — Row must carry a non-empty
  `verbatim_quote`.
- **`hook_quote_verified`** — `verify_quote.py` must have marked the
  claim as verified (bootstrap rows are exempt — they are human-
  validated ground truth).
- **`hook_cited_value_in_quote`** — For columns flagged
  `cited_value_required: true` in the schema, the literal numeric
  value must appear in `verbatim_quote`. Opt-in per column.
- **`hook_schema_valid`** — Row passes JSON-Schema-like validation
  against `state/schema.json` (types, enums, required fields).
- **`hook_doi_composite_unique`** — `(doi, canonical_species,
  trait_key)` is not already written this session.
- **`hook_gbif_resolved`** — `canonical_species` resolved to a valid
  GBIF backbone key. Soft failure (warn) — some legitimate species
  are not yet in the backbone.

## Project-specific hook lifecycle

### 1. Proposal

The `trait_learner` subagent writes candidate hooks during phases
1.LEARN and 5.PROCESS (every 10 batches). Each proposal is a single
Python file at `state/hooks/proposed/<name>.py` with a sibling
`<name>.rationale.txt` explaining: what pattern motivated the hook,
which seed papers exemplify it, and what false-positive risks exist.

### 2. Sandbox validation

Before a proposed hook is even shown to the user, the Manager runs
`python scripts/hook_sandbox.py <path>`. This is a static AST-based
linter that rejects:

- Imports outside the allowlist (`re`, `math`, `statistics`, `json`,
  `typing`, `dataclasses`, `collections`, `itertools`, `functools`,
  `decimal`, `fractions`, `enum`)
- Calls to `exec`, `eval`, `__import__`, `open`, `input`, `print`,
  `compile`, `globals`, `locals`, `vars`, `dir`, `breakpoint`
- `with` blocks, async functions, `global`/`nonlocal`/`del`
- Dunder attribute access except `__name__`, `__doc__`, `__qualname__`
- Any syntax error

A hook that fails sandbox validation is deleted before the user sees it,
and the trait_learner logs why. This is defense in depth — the loader
in `scripts/hooks.py` re-validates at load time.

### 3. User approval

The Manager surfaces each sandbox-passing proposed hook during phase
`2.SCHEMA + HOOKS` via AskUserQuestion with four options:

- **approve** — hook moves to `state/hooks/` and is registered in
  `state/schema.json.trait_hooks`.
- **edit** — user is invited to edit the .py file directly, then
  re-approve. The sandbox check re-runs after edit.
- **reject** — file is deleted from `proposed/`; the rejection is
  logged so the trait_learner knows not to re-propose the same.
- **defer** — stays in `proposed/` with a bumped timestamp.

### 4. Execution

`scripts/hooks.py` iterates all agnostic hooks plus every project hook
listed in `state/schema.json.trait_hooks` (as relative or absolute
paths). Each hook's verdict is captured in the row's ledger entry.

## How to add a hook manually

If you know what you want and don't want to wait for the trait_learner
to propose it:

```bash
# Write state/hooks/my_check.py with a hook_* function
# The sandbox is re-checked on load; if it passes, register:
python -c "
import json
from pathlib import Path
schema = json.loads(Path('state/schema.json').read_text())
schema.setdefault('trait_hooks', []).append('state/hooks/my_check.py')
Path('state/schema.json').write_text(json.dumps(schema, indent=2))
"
```

Next run of `hooks.py` will pick it up automatically.

## Example: the karyotype project's hooks (for reference)

These are the hooks Heath's Coleoptera karyotype project approved in
a specific project — they do NOT ship with the core skill. They are
reproduced here as a concrete example of what a well-formed project-
local hook library looks like.

**`state/hooks/2n_range.py`**:
```python
"""Block 2n values outside the biological range [2, 500]."""
from typing import Any

def hook_2n_range(row: dict, ctx: Any):
    v = row.get("diploid_2n")
    if v is None or v == "":
        return Pass("hook_2n_range")
    try:
        v = int(v)
    except (TypeError, ValueError):
        return Fail(f"diploid_2n not an int: {v!r}", "hook_2n_range")
    if not 2 <= v <= 500:
        return Fail(f"diploid_2n={v} outside biological range",
                    "hook_2n_range")
    return Pass("hook_2n_range")
```

**`state/hooks/hac_consistency.py`**:
```python
"""Enforce HAC == (2n - sex_chrom_count) / 2. Catches 2n/HAC swap."""
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
            f"HAC inconsistent: (2n - sex)/2 = {expected}, reported HAC = {h} (likely 2n/HAC swap)",
            "hook_hac_consistency",
        )
    return Pass("hook_hac_consistency")
```

**`state/hooks/sex_system_regex.py`**:
```python
"""Flag rows claiming simple XY when the quote indicates X1X2Y, neoXY, or multiple."""
import re
from typing import Any

COMPLEX = re.compile(r"X[\u2080\u2081\u2082_\s]?[0-9]|neo[\s\-]?XY|multiple\s+sex\s+chrom", re.I)

def hook_sex_system_regex(row: dict, ctx: Any):
    quote = row.get("verbatim_quote") or ""
    sys_val = (row.get("sex_system") or "").upper()
    if COMPLEX.search(quote) and sys_val in ("XY", "XX"):
        return Fail(
            "quote indicates complex sex system but row says simple XY",
            "hook_sex_system_regex",
        )
    return Pass("hook_sex_system_regex")
```

Each of these was proposed by the trait_learner after reading a
handful of Coleoptera karyotype seed papers, sandbox-approved, and
user-approved. They live in that project's `state/hooks/` directory
and nowhere else.

## Auto-derived hooks from curated data

When a project bootstraps with an existing curated CSV, the `bootstrap`
subagent runs a Deequ-style column profiler
(`scripts/derive_hooks.py`) and proposes **soft** range/enum/allow-list
hooks derived from the observed distributions. These are soft by
default because the curated set may not span the full legitimate
range; novel-but-correct extractions should flag, not reject.

## Ledger integration

Every hook result is recorded on the row's ledger entry:

```json
"hook_results": [
  {"hook": "hook_has_sha256_and_page", "verdict": "pass", "severity": "hard"},
  {"hook": "hook_hac_consistency", "verdict": "fail",
   "reason": "HAC inconsistent...", "severity": "hard"}
]
```

Downstream analysis can ask: which hooks fire most often? which are
over-strict (high confirm rate on human review)? which are under-strict
(high reject rate)? Those counters feed back into the active-learning
loop in `scripts/review_queue.py` and the trait_learner's update mode.
