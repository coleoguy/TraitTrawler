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

Point TraitTrawler at a taxon and a trait. It searches PubMed, OpenAlex, bioRxiv, and Crossref; retrieves full-text PDFs (including paywalled papers through your library proxy); extracts structured records from prose, tables, and catalogues; resolves taxonomy against GBIF; and writes validated, provenance-tagged rows to a CSV — session after session, picking up exactly where it left off. No API keys. No Python environment. No setup scripts.

The skill is fully taxon- and trait-agnostic: the same agent that builds a Coleoptera karyotype database works for avian body mass, plant phenology, or parasite host ranges.

---

## What it does that other tools don't

| Capability | TraitTrawler | Elicit / Consensus | Manual curation |
|:-----------|:------------:|:------------------:|:---------------:|
| Full-text extraction into structured fields | ✓ | — | ✓ |
| Paywalled PDF retrieval via proxy | ✓ | — | ✓ |
| Schema-enforced writes with validation rules | ✓ | — | — |
| Bidirectional citation chaining | ✓ | partial | — |
| GBIF taxonomy resolution + synonym collapse | ✓ | — | sometimes |
| **Self-improving domain knowledge** | ✓ | — | — |
| **Adaptive triage learning** | ✓ | — | — |
| Statistical QC (Chao1, Grubbs, calibration) | ✓ | — | — |
| Parallel subagent processing | ✓ | — | — |
| Darwin Core Archive export (GBIF-ready) | ✓ | — | — |
| Full provenance on every record | ✓ | — | — |

---

## Adaptive learning

TraitTrawler improves as it works. Three independent learning systems run continuously in the background:

### 1. Self-improving domain knowledge

Every session, the agent logs notation variants, new taxa, ambiguity patterns, and validation gaps it encounters to `state/discoveries.jsonl`. At session end it proposes specific, diff-formatted amendments to `guide.md`:

```
Discovery: "2n=46+B" notation (B chromosomes) not covered by current guide.
Proposed amendment to guide.md §3.1:
+ B chromosomes (supernumerary): record as diploid_number=46, note="B chromosomes present (46+B)".
  Seen in: Smith 2019, Kozlov 2021, Ferreira 2023.
Accept? [y/n/edit]
```

The user approves or rejects each change. Over multiple sessions, `guide.md` grows into a collaboratively curated knowledge base that encodes everything the literature actually says about notation, edge cases, and taxonomic scope — far exceeding what any researcher could anticipate at setup time. All amendments are logged for full reproducibility.

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

Each session the agent:

1. **Searches** the next unrun queries from `config.py` across PubMed, OpenAlex, bioRxiv, and Crossref, with automatic fallback to public APIs if MCPs are unavailable. Once keyword searches are exhausted, it can optionally chain through references of high-confidence papers bidirectionally to find additional sources.
2. **Triages** each paper as likely, uncertain, or unlikely using rules in `collector_config.yaml` and domain knowledge from `guide.md`. Unlikely papers are skipped; likely and uncertain papers proceed to fetch.
3. **Retrieves** full text through a cascade: Unpaywall → OpenAlex → Europe PMC → Semantic Scholar → CORE → your institutional proxy (via Chrome). Scanned PDFs are read via Claude's native PDF vision. Large PDFs (100+ pages) are chunked across sessions. Papers that can't be obtained are logged in `leads.csv`.
4. **Extracts** records in parallel — up to 3 papers concurrently via subagents for ~3× throughput. Table-heavy papers use a two-pass strategy: enumerate every species, extract each row, then verify row count matches. Catalogue entries are chunked and processed the same way.
5. **Resolves taxonomy** against the GBIF Backbone Taxonomy. Synonyms are updated to accepted names (originals preserved in notes), higher taxonomy is auto-filled, and results are cached locally.
6. **Validates** each record using schema rules from `collector_config.yaml` before writing — required fields, type checks, numeric ranges, allowed values, and cross-field consistency. Records failing hard rules are dropped; soft failures are flagged for review.
7. **Appends** validated records to `results.csv` with atomic writes (write-to-temp + rename). All state files use the same pattern — a mid-session crash loses nothing.

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
3. **Say "let's collect some data."** The setup wizard asks about your target taxa, trait, keywords, institution, and output fields, then generates all config files. For any question, you can say "you figure it out" and the agent researches the answer using OpenAlex and PubMed.

After setup, the agent runs a calibration phase: it processes 3–5 seed papers to learn real notation conventions and table formats for your trait, then seeds the queue from those papers' citations. The first real session starts with battle-tested domain knowledge instead of a cold start.

### Authenticating your library proxy

Log into your institution's library portal in Chrome before starting a session. The agent uses your active browser session to access paywalled papers. If you skip this, it still works but is limited to open-access papers and abstracts.

---

## Running a session

When you start a session, the agent reads all project files, checks dependencies, and prints a status report showing records collected, papers processed, queue depth, and search progress. It then enters the main loop and prints rolling updates every 5 papers.

Stop anytime by telling the agent to stop. All state is saved after every paper — nothing is lost. You can also set `batch_size` in `collector_config.yaml` (default: 20) to have the agent pause automatically after processing that many papers.

**The dashboard.** The agent generates `dashboard.html`, updated at session start, every 2 papers, and session end. Double-click it to open in any browser — it auto-refreshes every 60 seconds. The dashboard is fully self-contained (no CDN, no server) with an interactive column picker, sortable data table, and auto-detected trait-specific charts. It includes an activity panel showing what the agent is currently processing.

**Session length.** At the start of each session, the agent asks how long to run. You can give a paper count ("do 30 papers"), a time estimate ("I have an hour"), or a preset ("quick pass" for ~10, "long session" for 50+, "until done" for unlimited).

**Processing local PDFs.** Drop PDFs into `pdfs/` and the agent detects them automatically at session start, offering to process them before continuing with search mode.

---

## Understanding the output

### results.csv

One row per species per paper. Fields are defined by your `collector_config.yaml`. Every record carries `extraction_confidence` (0.0–1.0), `flag_for_review`, `doi`, `source_page`, `source_context` (verbatim text the record came from), and `extraction_reasoning`. Records below confidence 0.75 are automatically flagged.

### leads.csv

Papers identified as relevant but without obtainable full text. Each row includes DOI, title, failure reason, and whether abstract extraction succeeded. Resolve by dropping the PDF into `pdfs/` and running again.

### state/

Session state that enables resumption across sessions: `processed.json`, `queue.json`, `search_log.json`, `large_pdf_progress.json`, `discoveries.jsonl`, `triage_outcomes.jsonl`, `source_stats.json`, `taxonomy_cache.json`. You should never need to edit these directly.

### Statistical QC

At session end, `scripts/statistical_qc.py` generates:
- **Species accumulation curves** with Chao1 richness estimates (how close are you to completeness?)
- **Outlier detection** via Grubbs' test (continuous traits) and modal-frequency analysis (discrete)
- **Confidence distribution** analysis and near-duplicate flagging

Results are saved as `qc_report.html` and `qc_summary.json`. Ask "run QC" or "how's the data looking" at any time.

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

**`collector_config.yaml`** is the master configuration. It defines target taxa, trait name, triage rules, proxy URL, output fields, and validation rules (cross-field checks enforced before each write).

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
│   ├── SKILL.md                  # Core agent specification
│   ├── dashboard_generator.py    # Generates dashboard.html
│   ├── verify_session.py         # Post-batch deterministic verification
│   ├── export_dwc.py             # Darwin Core Archive export
│   ├── scripts/
│   │   ├── csv_writer.py         # Schema-enforced CSV writes (atomic)
│   │   ├── api_utils.py          # Retry/backoff + per-API rate limiting
│   │   ├── state_utils.py        # Atomic state file management
│   │   ├── statistical_qc.py     # Chao1, Grubbs outlier detection, QC plots
│   │   ├── taxonomy_resolver.py  # GBIF Backbone Taxonomy API resolver
│   │   ├── calibration.py        # Isotonic regression confidence calibration
│   │   ├── benchmark.py          # Precision/recall/F1 per field
│   │   ├── knowledge_graph_export.py  # JSON-LD provenance export
│   │   ├── reproduce.py          # Reproducibility verification
│   │   ├── pdf_utils.py          # PDF path construction + misplaced-PDF detection
│   │   ├── test_harness.py       # Synthetic data generator for testing
│   │   └── dashboard_server.py   # Optional live dashboard with SSE updates
│   └── references/               # 16 reference files loaded on-demand
│       ├── search_and_triage.md
│       ├── extraction_and_validation.md
│       ├── session_management.md
│       ├── knowledge_evolution.md  # Self-improving domain knowledge
│       ├── advanced_features.md    # Adaptive triage, source ordering, transfer
│       └── ...
│
├── tests/
│   └── test_verify_and_export.py
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

## Building the skill from source

```bash
cd skill && zip -r ../traittrawler.skill SKILL.md dashboard_generator.py verify_session.py export_dwc.py references/ scripts/ && cd ..
```

Pre-built `.skill` files are attached to each [GitHub Release](https://github.com/coleoguy/TraitTrawler/releases).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports, new taxon configurations, and validation studies for other trait systems are welcome.

## License

[MIT](LICENSE). Use it, modify it, share it.
