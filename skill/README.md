# TraitTrawler v6.1 — Skill README

This directory is the Claude Code skill that implements TraitTrawler
v6.1. The top-level [README.md](../README.md) covers the project
broadly; this file is for skill developers and contributors.

## Directory layout

```
skill/
├── SKILL.md                          Manager orchestrator (8 phases)
├── agents/                           10 subagent specs
│   ├── project_init.md
│   ├── bootstrap.md                  ingests curated CSV, derives hooks
│   ├── trait_learner.md              writes trait_profile.md + proposed hooks
│   ├── searcher.md
│   ├── fetcher.md
│   ├── triage.md
│   ├── extractor.md                  Opus 4.7 xhigh + 2576px vision
│   ├── semantic_verifier.md          Sonnet 4.6 + advisor escalation
│   ├── advisor.md                    Opus 4.7 (Advisor Tool pattern)
│   ├── structurer.md
│   └── adjudicator.md
├── references/                       7 narrative docs loaded on demand
│   ├── architecture.md               full pipeline + model table
│   ├── trait_profile_schema.md       11 sections incl. §11 Proposed Columns
│   ├── hooks_reference.md            agnostic vs project-local tiers
│   ├── bootstrap.md                  curated-data ingestion workflow
│   ├── talkative_style.md            narration templates
│   ├── review_workflow.md            resolution states + active learning
│   └── generalizing_beyond_traits.md template instantiations
├── scripts/                          15 deterministic Python modules
│   ├── setup_project.py              init a new project
│   ├── pdf_ingest.py                 SHA256 + manifest.sqlite
│   ├── pdf_render.py                 2576px page rendering for 4.7 vision
│   ├── pdf_peek.py                   quick text extraction
│   ├── verify_quote.py               THE critical grounding gate
│   ├── hooks.py                      agnostic hooks + per-project loader
│   ├── hook_sandbox.py               AST-based safety linter
│   ├── bootstrap.py                  curated CSV ingestion
│   ├── derive_hooks.py               Deequ-style profile → soft hooks
│   ├── propose_columns.py            schema generator + DwC/PAV/PROV-O
│   ├── taxonomy_resolver.py          GBIF lookup with cache
│   ├── ledger.py                     append-only audit log
│   ├── review_queue.py               resolution workflow + HTML review
│   ├── apply_adjudications.py
│   ├── session_report.py
│   ├── dispatch.py                   state-machine CLI
│   └── narrate.py                    styled status-line helper
└── tests/
    ├── test_smoke.py                 5 scenarios, no LLM calls
    └── test_real_pdf_grounding.py    real PDFs via fpdf2
```

## Architecture one-liner

The Manager subagent orchestrates specialist subagents through an
eight-phase state machine. No row reaches `results.csv` without a
deterministic grounding check (verbatim quote found in the cited PDF
page via `verify_quote.py`) AND a hook-gate (domain-agnostic hooks in
`scripts/hooks.py` plus user-approved project-local hooks in
`state/hooks/*.py`). Read
[references/architecture.md](references/architecture.md) for the full
story.

## Quick start

```bash
# Inside Claude Code, with this skill installed, ask Claude:
"Start a new TraitTrawler project for diploid chromosome numbers in
Coleoptera. I have curated data at ~/hbdat.csv."
```

The Manager handles the rest: collects your inputs, runs bootstrap if
you gave it curated data, runs the learning phase on seed papers, asks
you to approve the proposed schema AND each proposed hook, then runs
autonomously until the review queue needs attention.

## Running the smoke tests

```bash
cd skill
python3 tests/test_smoke.py              # 5 scenarios
python3 tests/test_real_pdf_grounding.py # real-PDF E2E
```

The smoke tests exercise the deterministic pipeline (setup → ingest
→ hooks → sandbox → review queue → bootstrap → state machine) using
synthetic data. The real-PDF grounding test creates real PDF fixtures
with fpdf2 and confirms `verify_quote.py` correctly accepts true
quotes, rejects fabricated ones, wrong-page claims, and unknown-sha256
claims. No network, no LLM calls.

## Dependencies

Production:
- Python 3.10+ (3.9 works for scripts but type hints may not)
- `pdfplumber` (PDF text extraction)
- Standard library (sqlite3, csv, json, uuid, hashlib, ast)

Test-only:
- `fpdf2` — synthesizes test PDFs for `test_real_pdf_grounding.py`

Optional:
- `pygbif` — falls back to HTTP lookup against GBIF's species/match API
- `pdf2image` + poppler — fallback for `pdf_render.py` on platforms
  where pdfplumber's `page.to_image()` misbehaves

## How to add a new trait domain

1. Start a new project — the Manager walks you through it.
2. Bootstrap if you have curated data; skip if not.
3. The `trait_learner` subagent reads your seed papers (and bootstrap
   rows if present) and writes `state/trait_profile.md` including §11
   Proposed Columns.
4. `propose_columns.py` generates the schema. You edit/approve.
5. The `trait_learner` also writes `state/hooks/proposed/*.py` —
   candidate validators for your domain. You approve each one
   individually.
6. Autonomous extraction begins. No code changes to the pipeline are
   required. If they ARE required, that's a generality regression;
   refactor the domain logic back into hooks / schema / profile.

See
[references/generalizing_beyond_traits.md](references/generalizing_beyond_traits.md)
for template instantiations in clinical trials, materials science,
ecology, and drug dosing.

## Model lineup (as of 2026-04-16)

| Subagent | Model | Effort |
|---|---|---|
| project_init, bootstrap | Sonnet 4.6 | default |
| trait_learner | Sonnet 4.6 | high |
| searcher, fetcher, triage | Haiku 4.5 | default |
| extractor | **Opus 4.7** | **xhigh** |
| semantic_verifier | Sonnet 4.6 | high (escalates to advisor) |
| advisor | Opus 4.7 | xhigh |
| structurer | Sonnet 4.6 | default |
| adjudicator | Opus 4.7 | xhigh |

## What v6.1 changes vs v5

| v5 | v6.1 |
|---|---|
| `source_context` missing 38.5% of rows | `verbatim_quote` required; verified against PDF bytes before downstream |
| Auditor blind to the Extractor's quote | Semantic Verifier reads the quote + escalates to Opus advisor when uncertain |
| Domain logic in prose Step 3b | Domain logic in sandboxed, user-approved `state/hooks/*.py` |
| **Trait-specific code hardcoded in skill** | **Zero trait-specific code in core; per-project hooks only** |
| No curated-data ingest path | `bootstrap` subagent + `derive_hooks.py` |
| PDF linkage by filename | PDF linkage by SHA256 |
| Single confidence float | Structured uncertainty JSON |
| Review queue unbounded flat CSV | JSONL with resolution states + HTML batch review + active learning |
| Trait knowledge in `references/*.md` | Learned into `state/trait_profile.md` per project |
| Manager reads PDFs inline | Manager delegates; main context stays lean |
| Filename-based provenance | Full DwC + PAV + PROV-O + Dublin Core on every row |
| Opus 4.5 / Sonnet 4 | Opus 4.7 / Sonnet 4.6 / Haiku 4.5 with adaptive thinking + 2576px vision |

## Design principles

1. Accuracy beats coverage.
2. Grounding is a protocol invariant, not a field.
3. Trait and clade agnostic — enforced architecturally.
4. User approves everything project-specific.
5. Main-context discipline (Manager orchestrates; subagents work).
6. Talkative autonomy (narrated pause points, autonomous in between).
7. Trust 4.7's literalism; strip 4.6-era verification scaffolding.
8. Defense in depth for user-approved code (sandbox at propose time
   AND at load time).
9. Publishable ledger (reproducible from hash + page + quote + schema
   + model versions).
10. Generalizable to the whole scientific extraction process.

## References

- [SKILL.md](SKILL.md) — the Manager spec with model lineup and golden rules
- [references/architecture.md](references/architecture.md) — full pipeline, model table, 4.7 notes
- [references/hooks_reference.md](references/hooks_reference.md) — agnostic vs project-local, lifecycle, sandbox
- [references/bootstrap.md](references/bootstrap.md) — curated-data ingestion
- [references/trait_profile_schema.md](references/trait_profile_schema.md) — 11-section profile format
- [references/talkative_style.md](references/talkative_style.md) — narration templates
- [references/review_workflow.md](references/review_workflow.md) — resolution states
- [references/generalizing_beyond_traits.md](references/generalizing_beyond_traits.md) — the north star
