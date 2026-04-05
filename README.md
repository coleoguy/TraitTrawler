<p align="center">
  <img src="docs/traittrawler_logo.svg" alt="TraitTrawler" width="520">
</p>

<h3 align="center">Autonomous AI agent for building structured trait databases from the scientific literature</h3>

<p align="center">
  <a href="https://github.com/coleoguy/TraitTrawler/actions/workflows/ci.yml"><img src="https://github.com/coleoguy/TraitTrawler/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://doi.org/ZENODO_DOI_HERE"><img src="https://img.shields.io/badge/DOI-10.5281%2Fzenodo.XXXXXXX-blue" alt="DOI"></a>
  <a href="https://claude.ai"><img src="https://img.shields.io/badge/platform-Claude_Cowork-7C3AED" alt="Claude Cowork"></a>
  <a href="CITATION.cff"><img src="https://img.shields.io/badge/cite-CFF-green" alt="Citation"></a>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> &bull;
  <a href="#how-it-works">How it works</a> &bull;
  <a href="#adaptive-learning">Adaptive learning</a> &bull;
  <a href="#running-a-session">Running a session</a> &bull;
  <a href="#understanding-the-output">Output</a> &bull;
  <a href="#validation-study">Validation</a> &bull;
  <a href="#citation">Citation</a>
</p>

---

Point TraitTrawler at a taxon and a trait. It searches PubMed, OpenAlex, bioRxiv, and Crossref; retrieves full-text PDFs (including paywalled papers through your library proxy); extracts structured records with mandatory double-entry verification; resolves taxonomy against GBIF; and writes validated, provenance-tagged rows to a CSV — session after session, picking up exactly where it left off. No API keys. No Python environment. No setup scripts.

The skill is fully taxon- and trait-agnostic: the same agent that builds a Coleoptera karyotype database works for avian body mass, plant phenology, or parasite host ranges. It handles both among-species data (one value per species across many species) and within-species data (population-level observations for a single species).

---

## What it does that other tools don't

| Capability | TraitTrawler | Elicit / Consensus | Manual curation |
|:-----------|:------------:|:------------------:|:---------------:|
| Full-text extraction into structured fields | ✓ | — | ✓ |
| **Extract + mandatory Auditor verification** | ✓ | — | — |
| Paywalled PDF retrieval via proxy | ✓ | — | ✓ |
| Schema-enforced writes with validation rules | ✓ | — | — |
| Bidirectional citation chaining | ✓ | partial | — |
| GBIF taxonomy resolution + synonym collapse | ✓ | — | sometimes |
| **Self-improving domain knowledge** | ✓ | — | — |
| **Adaptive triage learning** | ✓ | — | — |
| Inline 3-tier QC (Chao1, Grubbs, calibration) | ✓ | — | — |
| Multi-agent pipeline with concurrent extraction | ✓ | — | — |
| **Automatic bootstrap from existing data** | ✓ | — | — |
| Compilation table handling (attributed extraction) | ✓ | — | sometimes |
| Darwin Core Archive export (GBIF-ready) | ✓ | — | — |
| Full provenance on every record | ✓ | — | — |

---

## Adaptive learning

TraitTrawler improves as it works. Three independent learning systems run continuously in the background:

### 1. Self-improving domain knowledge

Every session, agents log notation variants, new taxa, ambiguity patterns, and validation gaps to `learning/`. The `review_discoveries.py` script classifies each discovery as routine or structural. Routine discoveries (new notation variants, new journals, prolific authors) are auto-applied to `guide.md` immediately — no human approval needed. Structural discoveries (new extraction rules, taxonomic revisions) are queued for human review at session end.

Over multiple sessions, `guide.md` grows into a collaboratively curated knowledge base that encodes everything the literature actually says about notation, edge cases, and taxonomic scope — far exceeding what any researcher could anticipate at setup time. All amendments are logged for full reproducibility.

### 2. Adaptive triage

After 100+ papers, the agent shifts from static keyword matching to learned triage. It records triage-to-outcome pairs in `state/triage_outcomes.jsonl` and computes word-level precision (which abstract keywords actually predict data yield). High-information-value papers — those where the model is most uncertain — are promoted to the front of the queue, maximizing what is learned per paper processed.

Every 50 papers, the agent reports triage accuracy and flags drift:

```
Triage Accuracy (last 50 papers)
   Likely → records:     34/38 (89%)
   Uncertain → records:   8/12 (67%)
   False positive rate:   4/50  (8%)
```

If the false-positive rate exceeds 20%, it recommends tightening `triage_keywords`. If uncertain papers yield records at >50%, it recommends relaxing the rules.

### 3. Adaptive source ordering

The agent tracks search yield per API in `state/source_stats.json`. After 20+ queries per source, it routes future queries to the most productive database first. If OpenAlex consistently outperforms PubMed for a project's taxa, it goes first. If bioRxiv yields fewer than 1 paper per 10 queries, search frequency drops. The OA retrieval cascade reorders dynamically by observed PDF retrieval success rate.

---

## Validation study

We validated TraitTrawler against a manually curated Coleoptera karyotype database assembled over two years.

| Metric | Value |
|:-------|------:|
| Records extracted (AI) | 5,339 (3,808 species) |
| Human-curated benchmark | 4,959 records (4,298 species) |
| Autonomous run time | ~15 hours over 3 days |
| Species overlap (Jaccard) | 0.50 |
| HAC accuracy, raw | 94.1% (n = 1,673; r = 0.955) |
| HAC accuracy, post-adjudication | 96.3% |
| Sex chromosome agreement | 92.7% (Cohen's kappa = 0.84) |
| Name spelling errors (GBIF) | AI 10.0% vs. Human 11.0% (p = 0.79) |
| **New species contributed** | **1,116 (+26% beyond the human database)** |
| Approximate LLM cost | ~US $150 |

> **Key finding:** 28% of apparent disagreements between datasets were not errors but genuine intraspecific karyotypic variation documented in different primary sources. Combining independently curated datasets recovers biological variation that either dataset alone misses.

---

## How it works

<p align="center">
  <img src="docs/traittrawler_pipeline.png" alt="TraitTrawler pipeline" width="900">
</p>

TraitTrawler v5 uses a **4-agent pipeline** where an Opus Manager coordinates dedicated Sonnet sub-processes. Agents communicate via filesystem folders — nothing is deleted until the downstream consumer verifies its work. All shared state files use file locking (`fcntl.flock`) for safe concurrent access between background agents. The Manager is a pure state-machine loop (~200 lines) that delegates all decisions to `dispatch.py`.

Each session the pipeline:

1. **Searches** (Sonnet-Searcher) — runs unrun queries from `config.py` across PubMed, OpenAlex, bioRxiv, and Crossref. Triages each paper as likely, uncertain, or unlikely. Once keyword searches are exhausted, it chains through references of high-confidence papers bidirectionally.
2. **Fetches** (Sonnet-Fetcher) — retrieves full text through a cascade: Unpaywall → OpenAlex → Europe PMC → Semantic Scholar → CORE → your institutional proxy (via Chrome). Writes a handoff file to `ready_for_extraction/` for each acquired PDF. Papers that can't be obtained go to `leads.csv`.
3. **Extracts** (Sonnet-Extractor) — reads the paper, extracts all structured records, self-validates, and writes to `finds/`. One agent per paper, with confidence scoring and source-page citation for every record.
4. **Verifies** (Sonnet-Auditor) — mandatory double-entry verification of ALL records. The Auditor reads only the cited source pages (1-2 pages per record, not the entire paper) and confirms, corrects, or flags each value. Records where extraction and verification agree get high confidence; disagreements get lower confidence with explanations; genuinely ambiguous cases route to a human review queue.
5. **Writes** — a deterministic script pipeline (`scrub.py` → `write_finds.py` → `inline_qc.py`) resolves taxonomy against GBIF, applies confidence calibration, validates against schema rules, deduplicates, and appends to `results.csv` with atomic writes. A 3-tier inline QC system auto-fixes ~50% of issues, routes ~40% to the Auditor, and sends <5% to the human review queue.

Duplicate papers are caught at two levels: at routing time (checked against `processed.json` before extraction begins) and at write time (CSV deduplication). Results.csv is snapshotted before every write for instant rollback. The system runs autonomously for hours without human checkpoints. Session state is continuously checkpointed to `pipeline_state.json`, so context compaction or crashes lose zero progress.

---

## Quickstart

**Prerequisites:** A [Claude](https://claude.ai) Pro or Max subscription with Cowork mode enabled, and the Claude in Chrome extension installed.

### Option A — Use an example configuration

1. **Clone the repository.**
   ```bash
   git clone https://github.com/coleoguy/TraitTrawler.git
   ```

2. **Copy an example to a new project folder.**
   ```bash
   cp -r TraitTrawler/examples/coleoptera-karyotypes ~/my-karyotype-project
   ```

3. **Edit the config.** Open `collector_config.yaml` and set your `proxy_url`, `institution`, and `contact_email`.

4. **Install the skill in Cowork.** Open Cowork settings → Plugins → Install from file → select `traittrawler.skill` from the repository root.

5. **Open the project folder in Cowork** and say "let's collect some data."

### Option B — Start from scratch

1. **Install the skill** (same as step 4 above).
2. **Create an empty folder** for your project and open it in Cowork.
3. **Say "let's collect some data."** The setup wizard asks about your target taxa, trait, whether you're collecting among-species or within-species data, keywords, institution, and output fields. For any question, you can say "you figure it out" and the agent researches the answer.

After setup, the agent runs a calibration phase: it processes 3-5 seed papers to learn real notation conventions and table formats for your trait, then seeds the queue from those papers' citations.

### Option C — Bootstrap from existing data

1. **Install the skill** (same as step 4 above).
2. **Drop your existing CSV** (and as much of the `state/` folder and `pdfs/` as you have) into a new folder and open it in Cowork.
3. **Say "let's collect some data."** The system auto-detects existing data and runs `bootstrap.py` to derive calibration models, coverage baselines, triage intelligence, and domain knowledge from your data. The more you bring (results.csv + pdfs/ + state/), the stronger the bootstrap. You're collecting within 2 minutes with calibrated confidence from record one.

### Authenticating your library proxy

Log into your institution's library portal in Chrome before starting a session. The agent uses your active browser session to access paywalled papers. If you skip this, it still works but is limited to open-access papers and abstracts.

---

## Running a session

When you start a session, the Manager checks dependencies, copies utility scripts, clears any backlog from prior sessions, syncs `processed.json` against `results.csv` (so hot-started projects don't re-fetch known papers), and prints a status report. It then confirms three settings (parsing as many as possible from your invocation message):

1. **Session target** — paper count or "until exhausted" (default: 20).
2. **Mode** — `consensus` (extract + verify, best accuracy) or `fast` (single pass). Consensus is the default.

After configuration, the Manager drives the pipeline autonomously — you never need to say "now search" or "now fetch". Say "50 papers" and watch it go. Stop anytime by telling the agent to stop. All state is saved continuously — the folder-based architecture means files in `finds/` and `ready_for_extraction/` persist across sessions. A mid-session crash loses nothing.

**The dashboard.** The agent generates `dashboard.html`, updated at session start, every 2 papers, and session end. Double-click it to open in any browser — it auto-refreshes every 60 seconds. Fully self-contained with no external dependencies.

**Processing local PDFs.** Drop PDFs into `provided_pdfs/` and the agent detects them automatically at session start, routing them into the normal extraction pipeline. PDFs are renamed to a standardized format (`Lastname-Year-Word-a.pdf`) in `pdfs/`. Every record in results.csv links back to its source PDF via the `pdf_path` column.

**Bootstrapping existing PDFs.** If you already have a collection of PDFs, say "link PDFs" and the agent scans your files, extracts citation metadata from each PDF header, fuzzy-matches against records in results.csv, and creates the links automatically.

**Data exploration.** Say "explore" or ask a question about the data ("how many families?", "show me low confidence records") at any time. The agent queries results.csv via lightweight scripts without loading it into context.

**Help.** Say "help" or "commands" to see all available commands grouped by category.

**Mid-session commands.** While collecting, say "pause" to stop after the current wave, "status" to see the pipeline state, or "explore [question]" to query the collected data without interrupting the session.

**Token tracking.** The Manager estimates token usage per model tier and reports efficiency metrics (records/call, tokens/record) at session end.

---

## Understanding the output

### results.csv

One row per observation per paper. For among-species projects, this is typically one row per species per paper; for within-species projects, one row per population or individual per paper. Fields are defined by your `collector_config.yaml`. Every record carries `extraction_confidence` (0.0-1.0, calibrated), `verification` (confirmed/corrected/ambiguous — from the Auditor), `flag_for_review`, `doi`, `source_page`, `source_context` (verbatim text the record came from), and `extraction_reasoning`. Data from compilation tables is tagged `source_type: "compilation"` with the original reference noted. Records that fail validation are preserved in `state/human_review_queue.csv` rather than silently dropped.

### leads.csv

Papers identified as relevant but without obtainable full text. The agent no longer extracts from abstracts — papers without full text go directly to leads.csv with a `needs_fulltext` reason. Resolve by dropping the PDF into `provided_pdfs/` and running again.

### state/ and pipeline folders

Session state that enables resumption across sessions: `processed.json`, `queue.json`, `search_log.json`, `discoveries.jsonl`, `triage_outcomes.jsonl`, `source_stats.json`, `taxonomy_cache.json`. You should never need to edit these directly.

The pipeline uses folder-based queues for inter-agent communication:
- `pdfs/` — standardized PDF library (`Lastname-Year-Word-a.pdf`); every record links here via `pdf_path`
- `ready_for_extraction/` — PDFs waiting for extraction (Fetcher → Extractor)
- `finds/` — extraction results awaiting verification and CSV write (Extractor → Auditor → write pipeline)
- `learning/` — discoveries from extraction (Extractor → review_discoveries.py)
- `provided_pdfs/` — user-supplied PDFs to process

These folders self-checkpoint: if a session ends mid-pipeline, the next session picks up the backlog automatically.

### Statistical QC

**Inline QC** runs automatically after every write via `inline_qc.py`:
- **Tier 1** — auto-fix: missing taxonomy (GBIF), missing metadata (Crossref), numeric cleanup (~50%)
- **Tier 2** — audit queue: low confidence, statistical outliers (Grubbs), cross-paper conflicts (~40%)
- **Tier 3** — human review: genuinely ambiguous cases, large cross-paper discrepancies (<5%)

Cross-paper conflicts use tolerance-based filtering — small numeric differences (±1-2 for chromosome counts) are recognized as expected intraspecific variation and auto-noted rather than queued.

**Statistical QC** at session end via `scripts/statistical_qc.py` generates species accumulation curves with Chao1 richness estimates, outlier detection via Grubbs' test, and confidence distribution analysis. Results saved as `qc_report.html` and `qc_summary.json`. Ask "run QC" or "how's the data looking" at any time.

### Campaign planning

After 3+ sessions, ask "coverage report" or "plan the campaign" and the agent generates strategic recommendations: which families are well-sampled, which queries to prioritize, estimated sessions to completion, and when to switch from keyword search to citation chaining.

---

## Starting a new project

### From an example

```bash
cp -r examples/coleoptera-karyotypes ~/my-project
# Edit collector_config.yaml, config.py, guide.md as needed
```

| Example | Description | Queries |
|:--------|:------------|--------:|
| `examples/coleoptera-karyotypes/` | Beetle chromosome data (validation study config) | 1,669 |
| `examples/avian-body-mass/` | Bird body mass from morphometric literature | 91 |

### The three project files

**`collector_config.yaml`** is the master configuration. It defines target taxa, trait name, triage rules, proxy URL, output fields, validation rules, extraction mode (consensus/fast), deduplication key, required fields, and compilation table handling.

**`config.py`** contains the search query list as `SEARCH_TERMS`. The Coleoptera example uses a cross-product of 148 family names × 11 keywords (1,669 queries). For a new project, replace the taxa and keywords.

**`guide.md`** is the domain knowledge document. The agent reads it at startup and uses it for every triage and extraction decision. Be specific: notation conventions, worked examples, common pitfalls. The guide grows with each session as the adaptive learning system proposes amendments based on patterns found in the literature.

---

## Repository structure

```
TraitTrawler/
│
├── traittrawler.skill            # Install this in Cowork
│
├── examples/
│   ├── coleoptera-karyotypes/    # Complete Coleoptera karyotype config
│   │   ├── collector_config.yaml
│   │   ├── config.py             # 1,669 search queries
│   │   ├── guide.md              # Domain knowledge (notation, validation rules)
│   │   ├── extraction_examples.md
│   │   ├── csv_schema.md
│   │   └── db_scanner.py
│   ├── avian-body-mass/          # Complete avian body mass config
│   │   ├── collector_config.yaml
│   │   ├── config.py             # 91 search queries
│   │   └── guide.md
│   └── sample_results.csv        # Example output (5 records)
│
├── skill/                        # Skill source (taxon-agnostic)
│   ├── SKILL.md                  # Opus Manager specification (v5)
│   ├── agents/                   # Per-agent specs (4-agent pipeline)
│   │   ├── searcher.md           # Search APIs, triage, citation chaining
│   │   ├── fetcher.md            # PDF acquisition, OA cascade
│   │   ├── extractor.md          # Single-pass extraction, self-validation
│   │   └── auditor.md            # Mandatory double-entry verification
│   ├── dashboard_generator.py    # Generates dashboard.html
│   ├── verify_session.py         # Post-batch deterministic verification
│   ├── export_dwc.py             # Darwin Core Archive export
│   ├── scripts/                  # Utility scripts (executed, not read)
│   │   ├── dispatch.py           # State machine: checkpoint, recommend, cleanup
│   │   ├── session_manager.py    # Session lifecycle, bootstrap detection
│   │   ├── process_agent_output.py  # Agent output processing, auto-normalization
│   │   ├── write_finds.py        # Validation, Crossref backfill, CSV writing
│   │   ├── scrub.py              # Deterministic finds/ JSON normalization
│   │   ├── inline_qc.py          # 3-tier post-write QC (auto-fix/audit/human)
│   │   ├── coverage_tracker.py   # Chao1 richness, accumulation curves
│   │   ├── review_discoveries.py # Auto-apply routine discoveries to guide.md
│   │   ├── bootstrap.py          # Derive v5 state from existing data
│   │   ├── csv_writer.py         # Schema-enforced CSV writes (atomic)
│   │   ├── calibration.py        # Isotonic regression confidence calibration
│   │   ├── taxonomy_resolver.py  # GBIF Backbone Taxonomy API resolver
│   │   ├── statistical_qc.py     # Grubbs outlier detection, QC plots
│   │   ├── validate_finds_json.py   # Finds JSON schema validation
│   │   ├── pdf_utils.py          # PDF path construction, standardized naming
│   │   ├── state_utils.py        # Atomic state file management
│   │   ├── api_utils.py          # Retry/backoff + per-API rate limiting
│   │   ├── benchmark.py          # Precision/recall/F1 per field
│   │   ├── knowledge_graph_export.py  # JSON-LD provenance export
│   │   └── dashboard_server.py   # Optional live dashboard with SSE updates
│   └── references/               # On-demand reference files
│       ├── setup_wizard.md       # First-run setup + calibration
│       ├── audit_and_qc.md       # Audit mode, Grubbs, outlier detection
│       ├── campaign_and_calibration.md  # Coverage analysis, isotonic regression
│       ├── knowledge_and_transfer.md    # Knowledge review, cross-project transfer
│       ├── troubleshooting.md    # Error recovery strategies
│       ├── config_template.yaml  # Project config template
│       ├── calibration.md        # Calibration phase details
│       ├── csv_schema.md         # Field definitions
│       ├── dispatch_cycle.md     # Agent spawn templates, failure handling
│       └── knowledge_evolution.md # Discovery types, logging format
│
├── .claude/
│   └── hooks/                   # Claude Code hooks (Manager-only guardrails)
│       ├── protect-results-csv.sh  # Prevents direct writes to results.csv
│       ├── protect-root.sh         # Prevents file creation in project root
│       └── block-bash-file-creation.sh  # Prevents ad-hoc file creation via Bash
│
├── tests/
│   ├── test_verify_and_export.py     # Verification + DwC export tests (8 tests)
│   └── test_v4_pipeline_flow.py      # V4 folder-based pipeline tests (12 tests)
├── evals/                        # Skill evaluation suite
├── ARCHITECTURE_v4.md            # Legacy v4 architecture (historical reference)
├── .github/workflows/ci.yml
├── CHANGELOG.md
├── CITATION.cff
├── CONTRIBUTING.md
└── LICENSE
```

---

## Citation

> Blackmon, H. (2026). TraitTrawler: an autonomous AI agent for large-scale extraction of phenotypic data from the scientific literature. (in prep).

```bibtex
@article{blackmon2026traittrawler,
  author  = {Blackmon, Heath},
  title   = {{TraitTrawler}: an autonomous {AI} agent for large-scale extraction
             of phenotypic data from the scientific literature},
  journal = {},
  year    = {2026},
  note    = {In preparation}
}
```

GitHub's **"Cite this repository"** button (top right) uses [`CITATION.cff`](CITATION.cff).

## Upgrading from v4

If you have an existing v4 project folder:

1. **Rebuild and reinstall the skill** (see below).
2. **Your project data is safe.** Bring your entire project folder — especially `results.csv`, `pdfs/`, and the `state/` directory.
3. **Start a new session.** The system auto-detects the v4 project and runs `bootstrap.py` to migrate all learning state (calibration models, triage intelligence, coverage baselines, taxonomy cache, search history) to v5 format. No manual migration needed.

The more of your v4 state you bring, the better the bootstrap:
- `results.csv` alone → minimal (re-examines no-data papers, no calibration)
- `results.csv` + `pdfs/` → basic (can generate extraction examples)
- Full project folder → complete (all accumulated intelligence preserved)

---

## Building the skill from source

```bash
cd skill && zip -r ../traittrawler.skill SKILL.md agents/ dashboard_generator.py verify_session.py export_dwc.py references/ scripts/ && cd ..
```

Pre-built `.skill` files are attached to each [GitHub Release](https://github.com/coleoguy/TraitTrawler/releases).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports, new taxon configurations, and validation studies for other trait systems are welcome.

## License

[MIT](LICENSE). Use it, modify it, share it.
