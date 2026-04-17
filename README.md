<p align="center">
  <img src="docs/traittrawler_logo.svg" alt="TraitTrawler" width="520">
</p>

<h3 align="center">Autonomous AI agent for building structured trait databases from the scientific literature</h3>

<p align="center">
  <a href="https://github.com/coleoguy/TraitTrawler/actions/workflows/ci.yml"><img src="https://github.com/coleoguy/TraitTrawler/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://doi.org/ZENODO_DOI_HERE"><img src="https://img.shields.io/badge/DOI-10.5281%2Fzenodo.XXXXXXX-blue" alt="DOI"></a>
  <a href="https://claude.ai"><img src="https://img.shields.io/badge/platform-Claude_Code-7C3AED" alt="Claude Code"></a>
  <a href="CITATION.cff"><img src="https://img.shields.io/badge/cite-CFF-green" alt="Citation"></a>
</p>

<p align="center">
  <b>Version 6.1</b> — Opus 4.7 · trait-agnostic · citation-grounded · hook-gated · bootstrap-capable
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> &bull;
  <a href="#the-core-claim">Core claim</a> &bull;
  <a href="#how-it-works">How it works</a> &bull;
  <a href="#bootstrap">Bootstrap</a> &bull;
  <a href="#hooks-as-learnable-domain-logic">Hooks</a> &bull;
  <a href="#whats-new-in-v61">What's new</a> &bull;
  <a href="#generalizing-beyond-traits">Generalizing</a> &bull;
  <a href="#citation">Citation</a>
</p>

---

Point TraitTrawler at a taxon and a trait. It optionally ingests an existing curated dataset you already have, learns how that trait is reported in the literature, proposes an output schema **and a set of domain-specific validation hooks** for you to approve, then autonomously searches, fetches, and extracts structured records into a verified CSV — with a cryptographically-linked audit ledger behind every row.

The skill is fully **taxon- and trait-agnostic**: no chromosome-specific, species-specific, or discipline-specific logic lives in the core. The same agent that builds a Coleoptera karyotype database works for avian body mass, plant phenology, clinical-trial outcomes, or materials-science properties. The trait knowledge lives in a per-project `trait_profile.md` that the skill writes from 5–10 seed papers (plus any curated data you provide), and the validation rules live in per-project hook files that you approve one at a time.

---

## The core claim

> **No row reaches `results.csv` unless a deterministic Python script has already confirmed that a verbatim quote from the extracted value literally appears in the SHA256-hashed source PDF on the cited page, AND the row has passed every one of the user-approved domain-specific validators.**

Grounding is a protocol invariant, not a best-effort field. Domain logic is in code, not in an agent prompt. Every row's provenance — source PDF hash, page, verbatim quote, model versions, hook verdicts, adjudication ruling — is preserved in `state/ledger.jsonl` as a publishable audit trail.

---

## Quickstart

```bash
git clone https://github.com/coleoguy/TraitTrawler.git
cd TraitTrawler
python3 -m pip install pdfplumber fpdf2   # test deps

# Verify the skill scaffolding:
cd skill && python3 tests/test_smoke.py
```

Inside Claude Code, with the TraitTrawler skill installed, just say:

> "Start a new TraitTrawler project for diploid chromosome numbers in Coleoptera. I have an existing curated CSV at ~/hbdat.csv and the paired PDFs in ~/coleopdfs/."

The Manager greets you, collects five inputs (trait, taxonomic scope, optional seed DOIs, optional curated CSV + PDF directory, project root), then walks you through:

1. **Bootstrap** (if you gave it curated data) — ingests your rows as human-validated ground truth.
2. **Learning** — reads 5–10 seed papers and summarizes how this trait is reported in the literature.
3. **Schema + hook approval** — proposes output columns and candidate validators for you to approve one at a time.
4. **Autonomous batch processing** — searches, fetches, extracts, with narrated progress.

It narrates every batch and pauses at four declared checkpoints. Autonomous runs between pause points.

---

## How it works

TraitTrawler v6.1 is an **8-phase state machine** where an LLM Manager orchestrates specialist subagents running on different Claude models, but every write to `results.csv` passes through deterministic Python gates.

```
0. SETUP         project_init collects trait, taxa, seed DOIs, optional curated data
0.5. BOOTSTRAP   (optional) bootstrap subagent ingests curated CSV + paired PDFs
1. LEARN         trait_learner reads seeds + bootstrap rows; writes trait_profile.md
                 AND proposes candidate validation hooks as sandbox-safe Python
2. SCHEMA+HOOKS  propose_columns generates schema; user approves schema AND
                 each proposed hook individually
3. SEARCH        searcher queries PubMed / bioRxiv / OpenAlex / Crossref
4. FETCH         fetcher downloads PDFs; manifest.sqlite records SHA256 hashes
5. PROCESS       batch loop: triage → extract → verify → structure → hook → adjudicate
6. REVIEW        user resolves review-queue items via HTML batch bundle
7. REPORT        session_report summarizes coverage + accuracy + hook-failure patterns
```

The per-paper extraction chain inside Phase 5:

```
triage (Haiku 4.5)       → relevant? if no, skip with logged reason
      │
      ▼
extractor (Opus 4.7,     → Claims with verbatim_quote + page
   thinking=xhigh,          PDF pages rendered at 2576px for table/figure pages
   text+image)
      │
      ▼
verify_quote.py          → drop any claim whose quote is not literally on the
(deterministic)             cited page of the hashed PDF
      │
      ▼
semantic_verifier        → reads the quote + context, verdict pass/fail/adjust
(Sonnet 4.6,                Escalates ambiguous claims to the advisor subagent
   with advisor               (Opus 4.7) emulating Anthropic's Advisor Tool pattern
   escalation)
      │
      ▼
structurer (Sonnet 4.6)  → schema-valid Row JSON
      │
      ▼
hooks.py                 → agnostic gates (grounding, schema, dedup, GBIF)
(deterministic)             + approved project-local hooks from state/hooks/*.py
      │
      ▼
adjudicator (Opus 4.7,   → only ~5% of rows; accept / amend / reject
   thinking=xhigh)
      │
      ▼
results.csv + state/ledger.jsonl
```

See [skill/references/architecture.md](skill/references/architecture.md) for the full diagram, data-flow narrative, and model-lineup table.

---

## Bootstrap

Heath (or any user) typically arrives with an existing curated dataset — often years of manual work. TraitTrawler v6.1 treats that as a first-class input rather than asking you to start over.

When you supply `curated.csv` (and optionally a paired PDF directory), the `bootstrap` subagent:

1. **Validates** the CSV structurally and canonicalizes species via GBIF's `/species/match` endpoint (which handles fuzzy matches like *Otiorhynchus* ↔ *Otiorrhynchus* with a confidence score).
2. **SHA256-hashes** any paired PDFs into `manifest.sqlite`, giving content-addressed linkage that survives file moves and renames.
3. **Writes ledger entries** for every imported row with `source_type: "human_curated_bootstrap"` and Darwin Core `identificationVerificationStatus: "ValidatedByHuman"`. These entries are treated as ground truth by the dedup hook — the AI extractor will not re-extract them unless you explicitly set `config.challenge_mode: true`.
4. **Selects exemplars** — a stratified representative sample (default 50 rows) used as in-context anchors for notation conventions in every subsequent extraction call.
5. **Derives soft hooks** via `scripts/derive_hooks.py` — Deequ-style range and enum validators generated from the observed numeric and categorical distributions in your curated data, with 20% padding so novel-but-correct values are flagged rather than rejected.

Every derived hook is a pure-Python file that passes `scripts/hook_sandbox.py` (AST-based static safety linter) and is shown to you for approval individually, with a sibling `.rationale.txt` explaining which curated rows motivated it.

See [skill/references/bootstrap.md](skill/references/bootstrap.md) for full workflow documentation.

---

## Hooks as learnable domain logic

This is the architectural move that makes the skill genuinely trait-agnostic:

> **The core skill contains zero trait-specific logic. Every domain rule lives in a per-project Python file that was either (a) proposed by the `trait_learner` subagent after reading seed papers, (b) derived from your curated data by `derive_hooks.py`, or (c) hand-written by you — and approved individually before it runs.**

There are **two tiers** of hooks:

- **Agnostic hooks** (in `scripts/hooks.py`): grounding, schema validity, DOI composite dedup, GBIF taxonomy, value-appears-in-quote. These run on every project. They never change when you start a new project.
- **Project-specific hooks** (in `state/hooks/*.py`): trait-specific range checks, arithmetic consistency rules, regex-based notation checks. Proposed, validated, approved, then loaded dynamically.

Every proposed hook passes `scripts/hook_sandbox.py` before the user ever sees it. The sandbox is an AST-based static linter that rejects:

- Imports outside an allowlist (`re`, `math`, `statistics`, `json`, `typing`, `dataclasses`, `collections`, `itertools`, `functools`, `decimal`, `fractions`, `enum`)
- Calls to `exec`, `eval`, `__import__`, `open`, `input`, `print`, `compile`, `globals`, `locals`, etc.
- Dunder attribute access, `with` blocks, async functions, `global`/`nonlocal`/`del`
- Any syntax error

This is defense in depth — the loader in `hooks.py` re-validates at load time so even a file that somehow bypassed the approval workflow cannot execute unsafe code.

See [skill/references/hooks_reference.md](skill/references/hooks_reference.md) for the full hook lifecycle and example project-local hooks (for reference — they are NOT part of the core skill).

---

## Opus 4.7 (launched 2026-04-16)

TraitTrawler v6.1 launched the same day as Opus 4.7 and takes advantage of specific 4.7 capabilities:

| Feature | 4.6 | 4.7 | How TraitTrawler uses it |
|---|---|---|---|
| Max image resolution | 1568px | **2576px** | Extractor renders table/figure pages via `pdf_render.py` at 2576px. CharXiv Reasoning jumped 69.1% → 82.1% no-tools. |
| Thinking control | `budget_tokens: N` | `effort: high \| xhigh \| max` | Extractor runs at `xhigh`; adjudicator at `xhigh`; verifier at `high`. |
| Literal instruction following | Loose | **Stricter** | Stripped all 4.6-era "double-check / verify carefully" scaffolding per the migration guide. |
| Prompt caching | Manual | **Auto-managed (Feb 2026)** | System prompts with `trait_profile.md` + `schema.json` cached with 5-min TTL across batches (90% discount on reads). |
| Advisor Tool (beta) | — | **Available** | `semantic_verifier` (Sonnet 4.6) escalates uncertain claims to the `advisor` subagent (Opus 4.7) — +2.7pp on SWE-bench Multilingual with 11.9% cost reduction per Anthropic's benchmarks, adapted to the Claude Code skill harness via subagent dispatch. |

Breaking-change compliance: no `temperature`, `top_p`, `top_k`, assistant-prefill, `budget_tokens`, or the deprecated beta headers (`effort-2025-11-24`, `interleaved-thinking-2025-05-14`, `fine-grained-tool-streaming-2025-05-14`) appear anywhere in the skill.

Token-inflation countermeasure: the 4.7 tokenizer produces 1.0–1.35× as many tokens for the same input, so the skill leans hard on prompt caching (`state/trait_profile.md` + `state/schema.json` cached across all extractions in a batch) and routes non-interactive passes through the Batch API for 50% off.

---

## Standards-compliant provenance

Every row written to `results.csv` carries full Darwin Core + PAV + PROV-O + Dublin Core provenance:

| Field | Standard | Value |
|---|---|---|
| `dwc_basisOfRecord` | Darwin Core | `MachineObservation` (AI row) or `HumanObservation` (bootstrap row) |
| `dwc_identificationVerificationStatus` | Darwin Core | `PredictedByMachine` or `ValidatedByHuman` |
| `dwc_recordedBy` | Darwin Core | Curator name or `TraitTrawler v6.1` |
| `pav_authoredBy` | PAV | ORCID of the source paper author |
| `pav_curatedBy` | PAV | ORCID of the human curator (null for pure AI rows) |
| `pav_createdBy` | PAV | Tool that produced the row |
| `prov_wasDerivedFrom` | PROV-O | SHA256 of source PDF |
| `prov_wasGeneratedBy` | PROV-O | ledger entry URI |
| `dcterms_created` | Dublin Core | ISO-8601 timestamp |

This is the W3C/TDWG standard for biodiversity data provenance and satisfies FAIR principle R1.2 ("detailed provenance"). Downstream analyses can filter on `dwc_identificationVerificationStatus` to separate machine-predicted rows from human-validated ones — exactly the distinction reviewers and Darwin Core Archive consumers need.

---

## What's new in v6.1

Changes since v5:

| v5 | v6.1 |
|---|---|
| `source_context` missing 38.5% of rows | `verbatim_quote` is a protocol-required field; `verify_quote.py` confirms it appears in the PDF before anything downstream sees it |
| Auditor blind — misses wrong-row-in-table silent errors | Semantic Verifier reads the Extractor's actual quote; escalates uncertain cases to an Opus advisor subagent |
| Domain logic in agent prose ("Step 3b: verify every value…") | Domain logic in per-project `state/hooks/*.py` — sandboxed, user-approved Python that blocks bad writes |
| **Trait-specific logic hardcoded in skill code** | **Zero trait-specific logic in core. Karyotype, body mass, thermal conductivity — all live as per-project hooks the user approves.** |
| No bootstrap path for existing curated data | `bootstrap` subagent ingests curated CSV + paired PDFs, preserves rows as ValidatedByHuman ground truth, derives soft hooks from observed distributions |
| PDF linkage by filename (breaks on moves/renames) | PDF linkage by SHA256 in `manifest.sqlite` |
| Single confidence float compresses many axes | Structured `uncertainty` JSON (`value_clarity`, `notation_ambiguity`, `pdf_quality`, …) |
| Review queue is a flat CSV that grows unbounded | `review_queue.jsonl` with resolution states + HTML batch review UX + active-learning feedback into `trait_profile.md` |
| Trait knowledge hardcoded in `references/*.md` | Trait knowledge learned into `state/trait_profile.md` per project; §11 machine-parseable Proposed Columns drives schema generation |
| Manager reads PDFs inline; context fills; compaction corrupts state | Manager delegates to forked subagents; main context stays lean across 500-paper runs |
| Per-record provenance inconsistent; filename-based linkage | Full Darwin Core + PAV + PROV-O + Dublin Core on every row; content-addressed PDFs; publishable ledger |
| Opus 4.5 / Sonnet 4 | Opus 4.7 / Sonnet 4.6 / Haiku 4.5 with adaptive thinking, 2576px vision, prompt caching |
| Generic verifier on every claim | Sonnet verifier escalates ambiguous cases to Opus advisor (Advisor Tool pattern) |

---

## Generalizing beyond traits

The same 8-phase architecture — `setup → bootstrap → learn → schema+hooks → search → fetch → extract → verify → gate` — is a general template for autonomous AI-driven scientific data collection. See [skill/references/generalizing_beyond_traits.md](skill/references/generalizing_beyond_traits.md) for concrete template instantiations:

- **Clinical-trial outcome harvesting** — columns: `trial_id`, `primary_outcome`, `effect_size`, CI bounds, N. Project-local hooks: CI consistency, N positivity, p-value range.
- **Materials-science property extraction** — columns: `compound`, `temperature`, `measured_value`, `method`. Project-local hooks: unit plausibility, method enum.
- **Ecology field-observation mining** — columns: `species`, `coords`, `density`, `survey_method`. Project-local hooks: coord bounds, method enum.
- **Drug dosing from case reports** — columns: `drug`, `age`, `weight`, `dose`. Project-local hooks: plausible-range ICD-10 resolution.

The contribution is the architecture, not the karyotype data it first produced. Spinning up a new scientific-extraction domain on v6.1 requires: (1) 5–10 seed papers, (2) optionally a curated CSV, (3) approving the schema and a handful of proposed hooks. Zero code changes to the pipeline.

---

## Design principles

1. **Accuracy beats coverage.** A dropped record is cheap; a silently wrong record is expensive.
2. **Grounding is an invariant, not a field.**
3. **Trait and clade agnostic — enforced architecturally.** No domain logic anywhere in the core.
4. **User approves everything project-specific** before any extraction runs.
5. **Main-context discipline.** Manager orchestrates; subagents do the work.
6. **Talkative autonomy.** Narrated pause points, autonomous in between.
7. **Trust 4.7's literalism.** Strip 4.6-era self-verification scaffolding; add back only targeted guidance that measurably helps.
8. **Defense in depth for user-approved code.** Sandbox at propose time, re-validate at load time.
9. **Publishable ledger.** Every row reproducible from SHA256 + page + quote + schema hash + model versions.
10. **Generalizable.** Same architecture for any scientific extraction task.

---

## Directory layout

```
TraitTrawler/
├── README.md                    (this file)
├── skill/                       the Claude Code skill
│   ├── SKILL.md                 Manager orchestrator (8 phases, model lineup, breaking-change checklist)
│   ├── agents/                  10 subagent specs
│   │   ├── project_init.md
│   │   ├── bootstrap.md         NEW v6.1
│   │   ├── trait_learner.md     writes trait_profile.md + proposed hooks
│   │   ├── searcher.md
│   │   ├── fetcher.md
│   │   ├── triage.md
│   │   ├── extractor.md         Opus 4.7 xhigh + 2576px vision
│   │   ├── semantic_verifier.md Sonnet 4.6 with advisor escalation
│   │   ├── advisor.md           NEW v6.1 (Advisor Tool pattern)
│   │   ├── structurer.md
│   │   └── adjudicator.md
│   ├── references/              7 narrative docs
│   │   ├── architecture.md      full pipeline, model table, 4.7 notes, prompt-caching
│   │   ├── trait_profile_schema.md  11-section profile format incl. §11 Proposed Columns
│   │   ├── hooks_reference.md   agnostic-vs-project-local tiers, sandbox, lifecycle
│   │   ├── talkative_style.md   narration templates
│   │   ├── review_workflow.md   resolution states + active learning
│   │   ├── bootstrap.md         NEW v6.1 — full workflow
│   │   └── generalizing_beyond_traits.md  template instantiations
│   ├── scripts/                 15 deterministic Python modules
│   │   ├── setup_project.py
│   │   ├── pdf_ingest.py        SHA256 + manifest.sqlite
│   │   ├── pdf_render.py        NEW v6.1 — 2576px page rendering for Opus 4.7 vision
│   │   ├── pdf_peek.py          quick text extraction for triage
│   │   ├── verify_quote.py      THE critical grounding gate
│   │   ├── hooks.py             agnostic hooks + per-project hook loader
│   │   ├── hook_sandbox.py      NEW v6.1 — AST-based safety linter
│   │   ├── bootstrap.py         NEW v6.1 — curated data ingestion
│   │   ├── derive_hooks.py      NEW v6.1 — Deequ-style profile → soft hooks
│   │   ├── propose_columns.py   schema generator from profile §11 + standards provenance
│   │   ├── taxonomy_resolver.py GBIF lookup with local cache
│   │   ├── ledger.py            append-only audit log
│   │   ├── review_queue.py      resolution workflow + HTML review
│   │   ├── apply_adjudications.py
│   │   ├── session_report.py
│   │   ├── dispatch.py          state machine CLI
│   │   └── narrate.py           styled status-line helper
│   ├── tests/
│   │   ├── test_smoke.py        5 scenarios: project hooks, sandbox, review, dispatch, bootstrap
│   │   └── test_real_pdf_grounding.py  real PDFs via fpdf2, verify_quote E2E
│   └── README.md                skill-level docs
├── docs/                        logos, diagrams
├── evals/                       accuracy evaluation harness
├── examples/                    sample project configs
└── tests/                       top-level tests
```

---

## Running the tests

```bash
cd skill

# Deterministic pipeline tests (no network, no LLM calls)
python3 tests/test_smoke.py
#   OK: project-local karyotype hooks end-to-end
#   OK: hook sandbox blocks unsafe code, accepts safe code (6 unsafe + 3 safe)
#   OK: review queue roundtrip
#   OK: dispatch state machine
#   OK: bootstrap ingests curated CSV + derives hooks (12 rows, DwC provenance)

# Real-PDF grounding end-to-end
python3 tests/test_real_pdf_grounding.py
#   OK: real-PDF grounding (5 claims, 2 verified, 3 failed correctly)
```

The smoke tests exercise the full deterministic Python pipeline (setup → ingest → hooks → sandbox → review queue → bootstrap → state machine) with synthetic data. The real-PDF grounding test creates real PDF fixtures with known text via fpdf2 and confirms `verify_quote.py` correctly accepts true quotes and rejects fabricated ones, wrong-page claims, and unknown-sha256 claims. No LLM calls; no network.

---

## Citation

If you use TraitTrawler, please cite using the metadata in [CITATION.cff](CITATION.cff).

---

## License

MIT. See [LICENSE](LICENSE).
