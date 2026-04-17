# TraitTrawler v6 — Skill README

This directory is the Claude Code skill that implements TraitTrawler
v6. The top-level [README.md](../README.md) covers the project broadly;
this file is for skill developers and contributors.

## Directory layout

```
skill/
├── SKILL.md                 # Manager orchestrator
├── agents/                  # Subagent specs (one Task target per file)
│   ├── project_init.md
│   ├── trait_learner.md
│   ├── searcher.md
│   ├── fetcher.md
│   ├── triage.md
│   ├── extractor.md
│   ├── semantic_verifier.md
│   ├── structurer.md
│   └── adjudicator.md
├── references/              # Narrative docs loaded on demand
│   ├── architecture.md
│   ├── trait_profile_schema.md
│   ├── hooks_reference.md
│   ├── talkative_style.md
│   ├── review_workflow.md
│   └── generalizing_beyond_traits.md
├── scripts/                 # Deterministic Python
│   ├── setup_project.py
│   ├── pdf_ingest.py
│   ├── verify_quote.py      # the critical grounding gate
│   ├── hooks.py             # deterministic write validators
│   ├── ledger.py            # append-only audit log
│   ├── propose_columns.py
│   ├── review_queue.py
│   ├── apply_adjudications.py
│   ├── session_report.py
│   ├── pdf_peek.py
│   ├── taxonomy_resolver.py
│   ├── dispatch.py
│   └── narrate.py
└── tests/
    └── test_smoke.py        # pipeline smoke tests (no LLM calls)
```

## Architecture one-liner

The Manager subagent orchestrates specialist subagents through a seven-
phase state machine. No row reaches `results.csv` without a
deterministic grounding check (verbatim quote found in the cited PDF
page) and a hook-gate (domain-specific Python validators). Read
[references/architecture.md](references/architecture.md) for the full
story.

## Quick start

```bash
# Inside Claude Code, with this skill installed, ask Claude:
"Start a new TraitTrawler project. I want to collect
diploid chromosome numbers (2n) for Coleoptera."
```

The Manager handles the rest: collects your inputs, runs the learning
phase on seed papers, asks you to approve the proposed schema, then
runs autonomously until the review queue needs attention.

## Running the smoke tests

```bash
cd skill
python3 tests/test_smoke.py
# or, with pytest:
python3 -m pytest tests/ -v
```

The tests exercise the deterministic pipeline (setup → ingest → hooks
→ review) using synthetic rows — no network, no LLM calls. They are a
fast sanity check that the Python scaffolding works.

## Dependencies

- Python 3.10+
- `pdfplumber` (for PDF text extraction)
- Standard library (sqlite3, csv, json, uuid, hashlib)
- `pygbif` is optional; the taxonomy resolver falls back to an HTTP
  call against the GBIF match endpoint.

## How to add a new trait domain

1. Start a new project (the Manager walks you through it).
2. The `trait_learner` subagent reads your seed papers and writes
   `state/trait_profile.md`.
3. `propose_columns.py` generates a schema. You edit/approve.
4. If the trait needs new validators beyond the generic ones, add
   them to `scripts/hooks.py` following the existing pattern and
   register their names in `state/schema.json`'s `trait_hooks`
   array.
5. That's it. No changes to `SKILL.md` or any agent spec should be
   needed. If they are, that is a generality regression — refactor
   the trait-specific logic back into hooks / schema / profile.

See [references/generalizing_beyond_traits.md](references/generalizing_beyond_traits.md)
for template instantiations (clinical outcomes, materials science,
ecology, drug dosing).

## What v6 fixes vs v5

| v5 | v6 |
|---|---|
| source_context missing 38.5% of rows | verbatim_quote is a required field, verified against PDF bytes by `verify_quote.py` before anything downstream sees it |
| Auditor blind — re-extracts from page without the Extractor's quote; misses wrong-row-in-table silent errors | Semantic Verifier reads the Extractor's actual quote; catches species mismatch and value-not-supported |
| Domain logic in prose ("Step 3b: verify every value…") | Domain logic in `scripts/hooks.py` as deterministic Python that can block a write |
| PDF linkage by filename (breaks on moves) | PDF linkage by SHA256 in `manifest.sqlite` |
| Single confidence float | Structured `uncertainty` JSON (value_clarity, notation_ambiguity, pdf_quality, ...) |
| Review queue is flat CSV that grows unbounded | `review_queue.jsonl` with resolution states + HTML batch review UX + active-learning feedback |
| Trait knowledge hardcoded in references/*.md | Trait knowledge learned into `state/trait_profile.md` per project |
| Manager reads PDFs inline; context fills | Manager delegates to forked subagents; main context stays lean |

## Design principles

1. Accuracy beats coverage.
2. Grounding is a protocol invariant, not a field.
3. Trait and clade agnostic.
4. User approves the schema.
5. Main-context discipline (Manager orchestrates, subagents do the work).
6. Talkative autonomy (narrated pause points, autonomous in between).
7. Generalizable to the whole scientific extraction process.

## References

- [SKILL.md](SKILL.md) — the Manager spec
- [references/architecture.md](references/architecture.md) — full pipeline
- [references/hooks_reference.md](references/hooks_reference.md) — all hooks
- [references/talkative_style.md](references/talkative_style.md) — narration templates
- [references/review_workflow.md](references/review_workflow.md) — review UX
- [references/generalizing_beyond_traits.md](references/generalizing_beyond_traits.md) — the north star
