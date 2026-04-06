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
  <a href="#quickstart">Quickstart</a> &bull;
  <a href="#how-it-works">How it works</a> &bull;
  <a href="#adaptive-learning">Adaptive learning</a> &bull;
  <a href="#running-a-session">Running a session</a> &bull;
  <a href="#understanding-the-output">Output</a> &bull;
  <a href="#validation-study">Validation</a> &bull;
  <a href="#citation">Citation</a>
</p>

---

Point TraitTrawler at a taxon and a trait. It searches PubMed, OpenAlex, bioRxiv, and Crossref; retrieves full-text PDFs (including paywalled papers through your library proxy); extracts structured records; spot-checks every record against cited source pages; resolves taxonomy against GBIF; and writes validated, provenance-tagged rows to a CSV — session after session, picking up exactly where it left off. No API keys. No Python environment. No setup scripts.

The skill is fully taxon- and trait-agnostic: the same agent that builds a Coleoptera karyotype database works for avian body mass, plant phenology, or parasite host ranges. It handles both among-species data (one value per species across many species) and within-species data (population-level observations for a single species).

---

## What it does that other tools don't

| Capability | TraitTrawler | Elicit / Consensus | Manual curation |
|:-----------|:------------:|:------------------:|:---------------:|
| Full-text extraction into structured fields | ✓ | — | ✓ |
| **Extract + independent Auditor spot-check** | ✓ | — | — |
| Paywalled PDF retrieval via proxy | ✓ | — | ✓ |
| Schema-enforced writes with validation rules | ✓ | — | — |
| Three-phase search (keywords → citations → authors) | ✓ | partial | — |
| GBIF taxonomy resolution + synonym collapse | ✓ | — | sometimes |
| **Self-improving domain knowledge** | ✓ | — | — |
| **Adaptive triage learning** | ✓ | — | — |
| Inline QC (Chao1, Grubbs, calibration) | ✓ | — | — |
| Multi-agent pipeline with concurrent extraction | ✓ | — | — |
| **Automatic bootstrap from existing data** | ✓ | — | — |
| Compilation table handling (attributed extraction) | ✓ | — | sometimes |
| Darwin Core Archive export (GBIF-ready) | ✓ | — | — |
| Full provenance on every record | ✓ | — | — |

---

## How it works

<p align="center">
  <img src="docs/traittrawler_pipeline.png" alt="TraitTrawler pipeline" width="900">
</p>

TraitTrawler uses a **4-agent pipeline** where a Manager (Opus) coordinates dedicated sub-agents (Sonnet). Agents communicate via filesystem folders — nothing is deleted until the downstream consumer verifies its work. All shared state files use file locking (`fcntl.flock`) for safe concurrent access. The Manager delegates scheduling decisions to `dispatch.py`, which tracks pipeline state and recommends next actions.

Each session the pipeline:

1. **Searches** (Searcher) — three-phase search. Phase 1: runs keyword queries from `config.py` across PubMed, OpenAlex, bioRxiv, and Crossref, triaging each paper as likely, uncertain, or unlikely. Phase 2: once keywords are exhausted, chains bidirectionally through citations of high-yield papers via OpenAlex. Phase 3: searches prolific authors' publication lists. Each phase triggers automatically when the previous one is exhausted.
2. **Fetches** (Fetcher) — retrieves full text through a cascade: Unpaywall → OpenAlex → Europe PMC → Semantic Scholar → CORE → your institutional proxy (via Chrome). Writes a handoff file to `ready_for_extraction/` for each acquired PDF. Papers without obtainable full text go to `leads.csv`.
3. **Extracts** (Extractor) — reads the paper, extracts all structured records, self-validates against the JSON schema, and writes to `finds/`. One agent per paper, up to 5 concurrent. Each record includes confidence scoring and source-page citation.
4. **Spot-checks** (Auditor) — independent verification of extracted records. The Auditor reads only the cited source pages (not the full paper) and confirms, corrects, or flags each value. Confirmed records get boosted confidence; corrections are logged with explanations; genuinely ambiguous cases route to a human review queue.
5. **Writes** — a deterministic script pipeline (`scrub.py` → `write_finds.py` → `inline_qc.py`) normalizes field values, validates against schema rules, deduplicates, resolves taxonomy against GBIF, and appends to `results.csv` with atomic writes. Records with normalization failures (e.g., unrecognized field values, missing PDFs) are routed back for re-extraction with formatting instructions rather than silently dropped.

Duplicate papers are caught at two levels: at routing time (checked against `processed.json` before extraction begins) and at write time (CSV deduplication). Results.csv is snapshotted before every write for instant rollback. Session state is continuously checkpointed to `pipeline_state.json`, so context compaction or crashes lose zero progress.

---

## Adaptive learning

TraitTrawler improves as it works. Three learning systems run during collection:

### 1. Self-improving domain knowledge

Extractors log recurring notation gaps, systematic ambiguities, validation rule gaps, and source structure patterns to `learning/`. At session end, the Manager reviews each discovery, classifies it as routine or structural, applies routine amendments to `guide.md`, and queues structural changes for human review. All amendments are logged to `discoveries.jsonl` for reproducibility.

Over multiple sessions, `guide.md` grows into a collaboratively curated knowledge base that encodes what the literature actually says about notation, edge cases, and taxonomic scope — far exceeding what a researcher could anticipate at setup time.

### 2. Adaptive triage

After 100+ papers, the agent shifts from static keyword matching to learned triage. It records triage-to-outcome pairs in `state/triage_outcomes.jsonl` and computes which abstract keywords actually predict data yield. Every 50 papers, the agent reports triage accuracy and flags drift.

### 3. Adaptive source ordering

The agent tracks search yield per API in `state/source_stats.json`. After 20+ queries per source, it routes future queries to the most productive database first. The OA retrieval cascade reorders dynamically by observed PDF retrieval success rate.

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

## Quickstart

**Prerequisites:** [Claude Code](https://claude.ai) with a Pro or Max subscription, and the Claude in Chrome extension installed for paywalled PDF access.

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

4. **Add the skill to Claude Code.** Install `traittrawler.skill` from the repository root.

5. **Open the project folder in Claude Code** and say "let's collect some data."

### Option B — Start from scratch

1. **Install the skill** (same as step 4 above).
2. **Create an empty folder** for your project and open it in Claude Code.
3. **Say "let's collect some data."** The setup wizard asks about your target taxa, trait, whether you're collecting among-species or within-species data, keywords, institution, and output fields. For any question, you can say "you figure it out" and the agent researches the answer.

After setup, the agent runs a calibration phase: it processes 3-5 seed papers to learn real notation conventions and table formats for your trait, then seeds the queue from those papers' citations.

### Option C — Bootstrap from existing data

1. **Install the skill** (same as step 4 above).
2. **Drop your existing CSV** (and as much of the `state/` folder and `pdfs/` as you have) into a new folder and open it in Claude Code.
3. **Say "let's collect some data."** The system auto-detects existing data and runs `bootstrap.py` to derive calibration models, coverage baselines, triage intelligence, and domain knowledge from your data. The more you bring, the stronger the bootstrap.

### Authenticating your library proxy

Log into your institution's library portal in Chrome before starting a session. The agent uses your active browser session to access paywalled papers. If you skip this, it still works but is limited to open-access papers.

---

## Running a session

When you start a session, the Manager checks dependencies, copies utility scripts, clears any backlog from prior sessions, syncs state against `results.csv`, and prints a status report. You tell it how many papers to process (or "until exhausted"), and it runs the pipeline autonomously — you never need to say "now search" or "now fetch." Stop anytime by telling the agent to pause or stop. All state is saved continuously. A mid-session crash loses nothing.

**The dashboard.** Say "dashboard" and the agent generates `dashboard.html` — a self-contained HTML file with KPIs, species accumulation curves (with user-selectable grouping), and an interactive data table with a column picker. Open it in any browser. Generated on demand, not automatically.

**Processing local PDFs.** Drop PDFs into `provided_pdfs/` and the agent detects them at session start, routing them into the normal extraction pipeline. PDFs are renamed to a standardized format (`Lastname-Year-Word-a.pdf`) in `pdfs/`. Every record in results.csv links back to its source PDF via the `pdf_path` column.

**Mid-session commands.** "pause" stops after the current wave. "status" shows pipeline state. "explore [question]" queries the data without interrupting collection. "dashboard" generates the HTML dashboard.

---

## Understanding the output

### results.csv

One row per observation per paper. Fields are defined by your `collector_config.yaml`. Every record carries:
- `extraction_confidence` (0.0-1.0, calibrated)
- `verification` (confirmed / corrected / ambiguous — from the Auditor)
- `flag_for_review`, `doi`, `source_page`, `source_context` (verbatim source text)
- `pdf_path` linking to the source PDF

Data from compilation tables is tagged `source_type: "compilation"` with the original reference noted. Records that fail validation are routed for re-extraction with specific formatting instructions, or preserved in `state/needs_attention.csv` — never silently dropped.

### leads.csv

Papers identified as relevant but without obtainable full text. Resolve by dropping the PDF into `provided_pdfs/` and running again.

### state/ and pipeline folders

Session state that enables resumption: `processed.json`, `queue.json`, `search_log.json`, `discoveries.jsonl`, `triage_outcomes.jsonl`, `source_stats.json`. You should never need to edit these directly.

The pipeline uses folder-based queues for inter-agent communication:
- `pdfs/` — standardized PDF library; every record links here via `pdf_path`
- `ready_for_extraction/` — handoff files (Fetcher → Extractor)
- `finds/` — extraction results awaiting spot-check and CSV write
- `learning/` — discoveries from extraction (reviewed at session end)
- `provided_pdfs/` — user-supplied PDFs to process

These folders self-checkpoint: if a session ends mid-pipeline, the next session picks up the backlog automatically.

### Statistical QC

**Inline QC** runs automatically after every write via `inline_qc.py`:
- **Tier 1** — auto-fix: missing taxonomy (GBIF), missing metadata (Crossref), numeric cleanup
- **Tier 2** — audit queue: low confidence, statistical outliers (Grubbs), cross-paper conflicts
- **Tier 3** — human review: genuinely ambiguous cases, large cross-paper discrepancies

Ask "run QC" or "how's the data looking" at any time to run the full statistical QC suite.

---

## Starting a new project

### The three project files

**`collector_config.yaml`** is the master configuration. It defines target taxa, trait name, triage rules, proxy URL, output fields, validation rules, deduplication key, required fields, and compilation table handling.

**`config.py`** contains the search query list as `SEARCH_TERMS`. The Coleoptera example uses a cross-product of 148 family names × 11 keywords (1,669 queries). For a new project, replace the taxa and keywords.

**`guide.md`** is the domain knowledge document. The agent reads it at startup and uses it for every triage and extraction decision. Be specific: notation conventions, worked examples, common pitfalls. The guide grows automatically as the learning system proposes amendments.

### Example configurations

| Example | Description | Queries |
|:--------|:------------|--------:|
| `examples/coleoptera-karyotypes/` | Beetle chromosome data (validation study config) | 1,669 |
| `examples/avian-body-mass/` | Bird body mass from morphometric literature | 91 |

---

## Repository structure

```
TraitTrawler/
│
├── traittrawler.skill            # Install this in Claude Code
│
├── examples/
│   ├── coleoptera-karyotypes/    # Complete config with 1,669 queries
│   ├── avian-body-mass/          # Complete config with 91 queries
│   └── sample_results.csv        # Example output
│
├── skill/                        # Skill source (taxon-agnostic)
│   ├── SKILL.md                  # Manager specification
│   ├── agents/
│   │   ├── searcher.md           # Three-phase search + triage
│   │   ├── fetcher.md            # PDF acquisition, OA cascade
│   │   ├── extractor.md          # Single-pass extraction, self-validation
│   │   └── auditor.md            # Independent spot-check verification
│   ├── dashboard_generator.py    # On-demand HTML dashboard
│   ├── verify_session.py         # Post-batch deterministic verification
│   ├── export_dwc.py             # Darwin Core Archive export
│   ├── scripts/                  # Utility scripts (executed, not read)
│   │   ├── dispatch.py           # Pipeline state machine
│   │   ├── scrub.py              # Finds JSON normalization + validation
│   │   ├── write_finds.py        # Crossref backfill + CSV writing
│   │   ├── csv_writer.py         # Schema-enforced atomic CSV writes
│   │   ├── inline_qc.py          # Post-write QC (auto-fix/audit/human)
│   │   ├── session_manager.py    # Session lifecycle, bootstrap detection
│   │   ├── process_agent_output.py
│   │   ├── pdf_utils.py          # PDF naming, standardization
│   │   ├── bootstrap.py          # Derive state from existing data
│   │   ├── calibration.py        # Isotonic confidence calibration
│   │   ├── taxonomy_resolver.py  # GBIF taxonomy lookups
│   │   ├── statistical_qc.py     # Grubbs outlier detection, QC plots
│   │   └── ...                   # + 8 more utilities
│   └── references/               # On-demand reference docs (22 files)
│       ├── dispatch_cycle.md     # Agent spawn templates, search phases
│       ├── extraction_and_validation.md
│       ├── session_management.md
│       ├── search_and_triage.md
│       ├── knowledge_and_transfer.md
│       └── ...
│
├── .claude/hooks/                # Guardrails (protect results.csv, etc.)
├── tests/
├── evals/
├── docs/
├── CITATION.cff
├── CONTRIBUTING.md
├── CHANGELOG.md
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
