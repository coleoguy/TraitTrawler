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
  <b>Version 6.0</b> — citation-grounded, hook-gated, trait-agnostic
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> &bull;
  <a href="#how-it-works">How it works</a> &bull;
  <a href="#whats-new-in-v6">What's new in v6</a> &bull;
  <a href="#generalizing-beyond-traits">Generalizing</a> &bull;
  <a href="#citation">Citation</a>
</p>

---

Point TraitTrawler at a taxon and a trait. It learns how that trait is reported in the literature, proposes an output schema for you to approve, then autonomously searches, fetches, and extracts structured records into a verified CSV — with a cryptographically-linked audit ledger behind every row.

The skill is fully **taxon- and trait-agnostic**: the same agent that builds a Coleoptera karyotype database works for avian body mass, plant phenology, or parasite host ranges. The trait knowledge lives in a per-project `trait_profile.md` that the skill builds from 5–10 seed papers, so adding a new domain requires no code changes to the pipeline.

---

## The core claim

> **No row reaches `results.csv` unless a deterministic Python script has already confirmed that a verbatim quote from the extracted value literally appears in the SHA256-hashed source PDF on the cited page.**

Grounding is a protocol invariant, not a best-effort field. That single architectural move is what makes v6 meaningfully different from earlier iterations.

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

> "Start a new TraitTrawler project for diploid chromosome numbers in Coleoptera."

The Manager greets you, collects four inputs (trait, taxonomic scope, optional seed DOIs, project root), then walks you through learning, schema approval, and autonomous batch processing. It narrates every batch and pauses at three declared checkpoints.

---

## How it works

TraitTrawler v6 is a **7-phase state machine** where an LLM Manager orchestrates specialist subagents, but every write to `results.csv` passes through deterministic Python gates.

```
0. SETUP     project_init collects trait, taxa, seed DOIs, root path
1. LEARN     trait_learner reads 5-10 seeds, writes trait_profile.md
2. SCHEMA    propose_columns generates a schema; user approves
3. SEARCH    searcher queries PubMed / bioRxiv / OpenAlex / Crossref
4. FETCH     fetcher downloads PDFs, manifest.sqlite records SHA256
5. PROCESS   batch loop: triage → extract → verify → structure → hook → adjudicate
6. REVIEW    user resolves review queue via HTML bundle
7. REPORT    session_report summarizes coverage + accuracy
```

The per-paper extraction chain inside Phase 5:

```
triage (Haiku)  →  relevant? if no, skip with logged reason
      │
      ▼
extractor (Opus, thinking=high) → Claims with verbatim_quote + page
      │
      ▼
verify_quote.py (deterministic) → drop any claim whose quote is not
   literally on the cited page of the hashed PDF
      │
      ▼
semantic_verifier (Sonnet) → reads the quote + context, verdict
   pass / fail / adjust per claim
      │
      ▼
structurer (Sonnet) → schema-valid Row JSON
      │
      ▼
hooks.py (deterministic) → six+ validators including
   grounding, 2n/HAC arithmetic, complex-sex-system regex, DOI dedup
      │
      ▼
adjudicator (Opus, xhigh, only ~5% of rows) → accept / amend / reject
      │
      ▼
results.csv + ledger.jsonl
```

See [skill/references/architecture.md](skill/references/architecture.md) for the full diagram and data-flow narrative.

---

## What's new in v6

| v5 | v6 |
|---|---|
| `source_context` missing 38.5% of rows | `verbatim_quote` is a protocol-required field; `verify_quote.py` confirms it appears in the PDF before anything downstream sees it |
| Auditor blind — misses wrong-row-in-table silent errors | Semantic Verifier reads the Extractor's actual quote; catches species mismatch and value-not-supported |
| Domain logic in agent prose ("Step 3b: verify every value…") | Domain logic in `scripts/hooks.py` — deterministic Python that blocks bad writes |
| PDF linkage by filename (breaks on moves/renames) | PDF linkage by SHA256 in `manifest.sqlite` |
| Single confidence float compresses many axes | Structured `uncertainty` JSON (value_clarity, notation_ambiguity, pdf_quality, …) |
| Review queue is a flat CSV that grows unbounded | `review_queue.jsonl` with resolution states + HTML batch review UX + active-learning feedback into `trait_profile.md` |
| Trait knowledge hardcoded in `references/*.md` | Trait knowledge learned into `state/trait_profile.md` per project |
| Manager reads PDFs inline; context fills; compaction corrupts state | Manager delegates to forked subagents; main context stays lean across 500-paper runs |
| Per-record provenance inconsistent | Ledger captures model versions, `trait_profile` hash, `schema` hash, session id for every row |

Full migration notes are in the v6 commit message on branch `v6-rewrite`.

---

## Generalizing beyond traits

The same 7-phase architecture — `learn → schema → search → fetch → extract → verify → gate` — is a general template for autonomous AI-driven scientific data collection. See [skill/references/generalizing_beyond_traits.md](skill/references/generalizing_beyond_traits.md) for concrete template instantiations:

- **Clinical trial outcome harvesting** — columns: trial_id, primary_outcome, effect_size, CI bounds, N; hooks for CI consistency, N positivity, p-value range
- **Materials science property extraction** — columns: compound, temperature, measured value, method; hooks for unit plausibility and method enum
- **Ecology field-observation mining** — columns: species, coords, density, survey method; hooks for coord bounds and method enum
- **Drug dosing from case reports** — columns: drug, age, weight, dose; hooks for plausible ranges and ICD-10 resolution

The contribution is the architecture, not the karyotype data it first produced.

---

## Design principles

1. **Accuracy beats coverage.** A dropped record is cheap; a silently wrong record is expensive.
2. **Grounding is an invariant, not a field.**
3. **Trait and clade agnostic.**
4. **User approves the schema** before any extraction runs.
5. **Main-context discipline.** Manager orchestrates; subagents do the work.
6. **Talkative autonomy.** Narrated pause points, autonomous in between.
7. **Generalizable.** Same architecture for any scientific extraction task.

---

## Directory layout

```
TraitTrawler/
├── README.md                    (this file)
├── skill/                       the Claude Code skill
│   ├── SKILL.md                 Manager orchestrator
│   ├── agents/                  9 subagent specs
│   ├── references/              6 narrative docs
│   ├── scripts/                 13 deterministic Python modules
│   ├── tests/                   smoke tests + real-PDF grounding test
│   └── README.md                skill-level docs
├── docs/                        logos, diagrams
├── evals/                       accuracy evaluation harness
├── examples/                    sample project configs
└── tests/                       top-level tests
```

---

## Running the tests

```bash
# From repo root:
cd skill
python3 tests/test_smoke.py              # deterministic pipeline tests
python3 tests/test_real_pdf_grounding.py # end-to-end with real PDFs
```

The smoke tests exercise the full deterministic Python pipeline
(setup → ingest → hooks → review queue → state machine) with synthetic
data. The real-PDF grounding test creates real PDF fixtures with
known text and confirms `verify_quote.py` correctly accepts true
quotes and rejects fabricated ones. No LLM calls; no network.

---

## Citation

If you use TraitTrawler, please cite using the metadata in [CITATION.cff](CITATION.cff).

---

## License

MIT. See [LICENSE](LICENSE).
