---
name: trait-trawler
model: sonnet
effort: high
description: >
  Autonomous scientific literature mining agent that builds structured trait
  databases (karyotype, morphometric, life-history, any phenotype) from the
  primary literature. Searches PubMed, OpenAlex, bioRxiv, and Crossref;
  retrieves full-text PDFs via open-access cascades and institutional proxies;
  extracts structured data from prose, tables, and catalogues; resolves
  taxonomy against GBIF; validates and writes to CSV with full provenance.
  Includes statistical QC (Chao1, Grubbs), citation chaining, self-improving
  domain knowledge, confidence calibration, multi-agent consensus extraction,
  and formal reproducibility. Use when the user wants to: collect trait data,
  mine the literature, run a session, build a trait database, process papers,
  extract data, run QC, audit the database, or continue collecting. Do NOT use
  for casual literature review (use deepscholar), simple data exploration, or
  one-off paper summaries.
allowed-tools: >
  Bash(python3:*) Bash(pip:*) Bash(cp:*) Bash(mkdir:*) Bash(wc:*) Bash(ls:*)
  Bash(open:*) Bash(pkill:*) Bash(sleep:*)
  Read Write Edit Glob Grep Agent WebFetch WebSearch
argument-hint: "[session-target or command, e.g. '20 papers', 'run QC', 'audit']"
compatibility: >
  Requires Python 3.9+, pyyaml, pdfplumber, scipy (optional, QC plots),
  matplotlib (optional, QC plots), scikit-learn (optional, calibration).
  Network access required for PubMed, OpenAlex, bioRxiv, Crossref,
  Unpaywall, and GBIF APIs. Claude in Chrome MCP enables institutional
  proxy PDF retrieval; without it degrades gracefully to open-access papers
  and abstracts only. PubMed and bioRxiv MCPs are optional (falls back to
  public APIs).
metadata:
  author: Heath Blackmon
  version: 3.0.0
---

# TraitTrawler

Searches the scientific literature, retrieves full-text papers, and extracts
structured data records into a CSV. Everything about *what* to collect lives in
three project files: `collector_config.yaml` (taxa, trait, fields), `config.py`
(search queries), and `guide.md` (domain knowledge for extraction). The skill
itself is taxon- and trait-agnostic.

Run until the user stops, `session_target` is reached, or the search queue is
exhausted. Pick up exactly where the previous session ended.

**Skill directory**: `${CLAUDE_SKILL_DIR}`
**Project root**: the folder Cowork has open (the current working directory).

## Pipeline stages (detail in reference files)

| Stage | Section | Reference file | When to load |
|---|---|---|---|
| Calibration (first run) | §0b | [calibration.md](references/calibration.md) | First run only, after setup wizard |
| Search & Triage | §3–4 | [search_and_triage.md](references/search_and_triage.md) | Every search cycle |
| Fetch, Extract, Validate, Write | §5–8 | [extraction_and_validation.md](references/extraction_and_validation.md) | Every extraction cycle |
| State, Reporting, Dashboard | §9–13 | [session_management.md](references/session_management.md) | Session start and end |
| Model routing | §2 | [model_routing.md](references/model_routing.md) | Session start (reference) |
| Self-improving knowledge | §14 | [knowledge_evolution.md](references/knowledge_evolution.md) | Session end, if discoveries logged |
| Taxonomic intelligence | §16 | [taxonomy.md](references/taxonomy.md) | During extraction (after records, before write) |
| Statistical QC | §17 | [statistical_qc.md](references/statistical_qc.md) | Session end or on-demand ("run QC") |
| Campaign planning | §18 | [campaign_planning.md](references/campaign_planning.md) | On-demand after 3+ sessions |
| Audit mode | §15 | [audit_mode.md](references/audit_mode.md) | On-demand ("audit the database") |
| Confidence calibration | §19 | [confidence_calibration.md](references/confidence_calibration.md) | Session end, if calibration data exists |
| Extraction benchmarking | §20 | [benchmarking.md](references/benchmarking.md) | During calibration + on-demand |
| Consensus extraction | §21 | [consensus_extraction.md](references/consensus_extraction.md) | Auto on low-confidence papers |
| Advanced features | §22–28 | [advanced_features.md](references/advanced_features.md) | Traces, active learning, adaptive tools, transfer, KG export, streaming, reproducibility |
| Troubleshooting | — | [troubleshooting.md](references/troubleshooting.md) | When something goes wrong |

Read the appropriate reference file when entering that pipeline stage.
**During the setup wizard (§0) and calibration (§0b), only read
`calibration.md` and `config_template.yaml`.** Do not pre-load
extraction_and_validation.md, session_management.md, or other reference
files — they are not needed until §1+ and loading them wastes context.

---

## 0. First-Run Detection

Check whether `collector_config.yaml` exists in the current working directory.

**If it does NOT exist → run setup wizard:**

Ask these questions one at a time (wait for each answer):

1. "What taxa are you collecting data for? (e.g. Coleoptera, Aves, Mammalia)"
2. "What trait or data type are you collecting? (e.g. karyotype, body size, mating system)"
3. "What keywords in a paper title make it clearly relevant even without an abstract?"
4. "What is your contact email? (used for API polite-pool access)"
5. "What institution do you use for library access? (for the proxy URL)"
   — For Texas A&M: proxy is `http://proxy.library.tamu.edu/login?url=`
   — For others: offer to look it up or ask them to paste it

### Researching answers the user delegates

For any wizard question, the user may say "you figure it out", "look it up",
or "research it." **Spawn a haiku subagent** to do the research — pass it
the taxon, trait, and the specific question. The subagent does the API
calls, reads abstracts, and returns a concise answer (proposed keyword list,
proxy URL, taxonomic group list, etc.). Present the subagent's findings to
the user for approval. This keeps search results, abstracts, and intermediate
reasoning out of the main context.

See [calibration.md](references/calibration.md) §0a for the research
strategy per question — include these instructions in the subagent prompt.

### Create project files

- Create `collector_config.yaml` from answers using the template in
  `${CLAUDE_SKILL_DIR}/references/config_template.yaml`. Populate
  `{TRAIT_FIELDS}` with trait-specific field names using these conventions:
  - snake_case, include unit when applicable (e.g. `body_mass_g_mean`)
  - Include `_mean`, `_sd`, `_min`, `_max` for continuous measurements
  - Include `sex`, `sample_size`, `age_class` when trait is per-individual
  - Include method/technique fields when relevant
  - **Always include provenance fields**: `source_page`, `source_context`,
    `extraction_reasoning`
  - Show the user the field list and ask if they want changes
- Create `state/` folder with empty state files:
  `processed.json` (`{}`), `queue.json` (`[]`), `search_log.json` (`{}`),
  `large_pdf_progress.json` (`{}`), `run_log.jsonl` (empty),
  `discoveries.jsonl` (empty), `taxonomy_cache.json` (`{}`),
  `calibration_data.jsonl` (empty), `benchmark_gold.jsonl` (empty),
  `triage_outcomes.jsonl` (empty), `source_stats.json` (`{}`),
  `consensus_stats.json` (`{}`)
- Create `state/extraction_traces/` and `state/snapshots/` directories
- Create `pdfs/` folder
- Create `results.csv` with just the header row

**Generate `config.py`** if it doesn't exist — ask:
7. "What are the major taxonomic groups I should search?"
8. "Any specific journals or author names that are especially relevant?"

Generate cross-product of taxonomic groups × trait keywords. File MUST define
`SEARCH_TERMS` as a list. Tell the user the query count.

**Generate `guide.md`** if it doesn't exist — ask:
9. "What should I know about how this trait is reported in the literature?"

Generate structured guide with sections for: Units/notation, What to extract,
What to skip, Common pitfalls, Taxonomy notes. Tell user they can edit anytime.

### 0b. Calibration phase

After generating config files, run a calibration phase before the first
real session. Full details in [calibration.md](references/calibration.md).

Summary: ask for seed DOIs (or find automatically) → extract with aggressive
discovery logging → immediate knowledge review → citation-seed the queue →
auto-generate `extraction_examples.md`. The first real session starts with
battle-tested domain knowledge and a warm queue.

**After calibration completes**, write a checkpoint flag to
`state/calibration_complete.json` (keys: `completed`, `date`, `seed_papers`,
`records`). Then tell the user:

```
Calibration complete — config files, guide.md, and extraction examples are
ready. Start a new conversation and say "continue collecting" or "run a
session" to begin the first collection batch with a fresh context window.
```

**Do NOT proceed to §1 in the same invocation.** The wizard + calibration
consumes most of the context window. Starting §1 → §3 here risks context
exhaustion mid-session, causing state desync, skipped papers, or silent
failures. A fresh session gets the full context budget for actual collection.

**If `collector_config.yaml` exists → skip to §1.**

---

## 1. Startup

If `state/calibration_complete.json` exists and this is the first session
after calibration, acknowledge it briefly:
```
Calibration data loaded — {N} records from {M} seed papers, queue has {Q} papers.
```
Then proceed normally with §1a–§1f.

### 1a. Check dependencies

**Check Python dependencies** (run once per session):
```bash
python3 -c "import pdfplumber" 2>/dev/null || pip install pdfplumber --break-system-packages -q
python3 -c "import yaml" 2>/dev/null || pip install pyyaml --break-system-packages -q
python3 -c "import scipy" 2>/dev/null || pip install scipy matplotlib --break-system-packages -q
python3 -c "import sklearn" 2>/dev/null || pip install scikit-learn --break-system-packages -q
```

If any install fails, warn but continue — fall back gracefully.

**Check MCP availability** — attempt one lightweight call to each; degrade
gracefully if unavailable. MCP tool names vary by environment (e.g.,
`mcp__<uuid>__search_articles`); match by the **suffix** after the last `__`:
- PubMed MCP (suffix `search_articles`): fallback → E-utilities API via WebFetch
- OpenAlex MCP (suffix `search_works`): fallback → OpenAlex REST API via WebFetch
- bioRxiv MCP (suffix `search_preprints`): fallback → Crossref API for preprints
- Crossref MCP (suffix `search_crossref`): fallback → Crossref REST API via WebFetch
- Claude in Chrome (suffix `navigate`): if unavailable, warn and skip proxy fetch (OA only)

Do not fail hard on any missing MCP.

### 1b. Read files in order

**Project files** (in project root):
1. `collector_config.yaml` — master config
2. `config.py` — search term list
3. `guide.md` — domain knowledge (inject into all triage and extraction)
4. `state/processed.json`, `state/queue.json`, `state/search_log.json`
5. `results.csv` — count existing records
6. `leads.csv` — count for status report
7. `state/discoveries.jsonl` — review pending discoveries from prior sessions

**Skill reference files** (in `${CLAUDE_SKILL_DIR}/references/`):
8. `csv_schema.md` — generic field definitions and confidence guidelines

**Project-specific** (optional):
9. `extraction_examples.md` — notation rules and worked examples

### 1c. Generate session_id and compute file hashes

Generate `session_id` as ISO timestamp (e.g., "2026-03-24T14:30:00Z").
Compute MD5 hashes of `guide.md` and `config.py` for change tracking.

### 1d. Check for flagged-for-review records

If `results.csv` has records with `flag_for_review == True`, report count
and offer to review before continuing.

### 1e. Copy utility scripts from skill directory if not present

```bash
for script in dashboard_generator.py verify_session.py export_dwc.py; do
  [ ! -f "$script" ] && cp "${CLAUDE_SKILL_DIR}/$script" "$script" 2>/dev/null || true
done
mkdir -p scripts
for script in statistical_qc.py taxonomy_resolver.py calibration.py benchmark.py knowledge_graph_export.py reproduce.py dashboard_server.py csv_writer.py api_utils.py state_utils.py pdf_utils.py test_harness.py; do
  [ ! -f "scripts/$script" ] && cp "${CLAUDE_SKILL_DIR}/scripts/$script" "scripts/$script" 2>/dev/null || true
done
mkdir -p state/extraction_traces state/snapshots
```

**Pre-session backup** — run BEFORE any extraction work:
```bash
mkdir -p state/snapshots
BACKUP_TS=$(date +%Y%m%dT%H%M%S)
[ -f results.csv ] && cp results.csv "state/snapshots/results_${BACKUP_TS}.csv"
[ -f state/processed.json ] && cp state/processed.json "state/snapshots/processed_${BACKUP_TS}.json"
[ -f state/search_log.json ] && cp state/search_log.json "state/snapshots/search_log_${BACKUP_TS}.json"
echo "Backup created: state/snapshots/*_${BACKUP_TS}.*"
```

**Run verification** before dispatching any extraction subagents:
```bash
python3 verify_session.py --project-root .
```
If verification finds errors, report them to the user before continuing.

**Script usage** — execute all of these via Bash. Do NOT read them into context:

| Script | Purpose | Invocation |
|---|---|---|
| `dashboard_generator.py` | Generates `dashboard.html` from project data | `python3 dashboard_generator.py --project-root .` |
| `verify_session.py` | Post-batch CSV validation (schema, dupes, ranges) | `python3 verify_session.py --project-root .` |
| `export_dwc.py` | Exports results.csv as Darwin Core Archive | `python3 export_dwc.py --project-root . --output-dir dwc_export` |
| `scripts/statistical_qc.py` | Outlier detection, Chao1 estimator, QC plots | `python3 scripts/statistical_qc.py --project-root .` |
| `scripts/taxonomy_resolver.py` | Batch GBIF taxonomy lookups with caching | `python3 scripts/taxonomy_resolver.py --csv results.csv --species-column species --cache state/taxonomy_cache.json` |
| `scripts/calibration.py` | Confidence calibration, ECE, reliability diagrams | `python3 scripts/calibration.py --project-root .` |
| `scripts/benchmark.py` | Gold-standard accuracy metrics (precision/recall/F1) | `python3 scripts/benchmark.py --project-root .` |
| `scripts/knowledge_graph_export.py` | JSON-LD provenance export, cross-paper conflict detection | `python3 scripts/knowledge_graph_export.py --project-root . --format both` |
| `scripts/reproduce.py` | Reproducibility verification and session drift analysis | `python3 scripts/reproduce.py --project-root . --summary` |
| `scripts/dashboard_server.py` | *(Optional)* Live dashboard with SSE updates | `python3 scripts/dashboard_server.py --project-root . &` — only if user requests live server |
| `scripts/csv_writer.py` | Schema-enforced CSV writes with atomic operations | Used as library; standalone: `python3 scripts/csv_writer.py --project-root .` |
| `scripts/api_utils.py` | Retry/backoff and rate limiting for all APIs | Used as library; info: `python3 scripts/api_utils.py --rate-limits` |
| `scripts/state_utils.py` | Atomic state file reads/writes with backup recovery | Standalone: `python3 scripts/state_utils.py --project-root . --check` |
| `scripts/pdf_utils.py` | PDF path construction, misplaced-PDF detection and fix | `python3 scripts/pdf_utils.py --project-root . --check` (or `--fix`) |
| `scripts/test_harness.py` | Generate synthetic project data for testing | `python3 scripts/test_harness.py --output-dir /tmp/test --records 200` |

Then regenerate the dashboard:

```bash
python3 dashboard_generator.py --project-root .
```

Tell the user: **"Dashboard updated — open dashboard.html in your browser
(double-click the file) to see progress. It auto-refreshes every 60 seconds."**

The dashboard is a self-contained HTML file with no external dependencies.
It works via `file://` protocol (double-click). Regenerate it every 2 papers
during collection so the auto-refresh picks up near-real-time data.

### 1f. Ask how long to run

Ask the user how long this session should run. Accept paper counts ("do 30
papers"), time estimates ("I have an hour" → ~15–20 papers), or presets
("quick pass" = 10, "long session" = 50+, "until done" = unlimited). See
[session_management.md](references/session_management.md) §9d for conversion
rules. Set `session_target` for the rest of the run.

### 1g. Startup state log and status

Append session_start to `state/run_log.jsonl`:
```json
{"timestamp": "...", "session_id": "...", "event": "session_start", "guide_md5": "...", "config_py_md5": "...", "session_target": 20}
```

Print a status block: project name, session_id, records in database, papers
processed, leads count, flagged for review, session target, queue depth,
queries run (n/total), taxonomic coverage summary (families with records /
known families), next query. Use box-drawing characters.

---

## 2. Model Routing

TraitTrawler uses cheaper models for routine tasks and reserves expensive
models for deep reasoning. Full routing table, escalation protocol, batch
strategies, and override rules in
[model_routing.md](references/model_routing.md).

**Summary**: haiku for search/triage/state, sonnet for extraction/validation,
opus only on escalation (low confidence, row-count mismatch, OCR artifacts,
structural guide amendments).

---

## 3. Main Loop

### 3a. Detect operating mode

Check for unprocessed local PDFs in `pdfs/`. Compare PDF filenames against
`processed.json`. If unprocessed PDFs found, ask:

```
Found {N} unprocessed PDFs in pdfs/. How should I proceed?
  1. Process these PDFs first, then continue with search queue
  2. Search mode only (ignore local PDFs for now)
  3. PDF-only mode (process local PDFs, skip search)
```

Also enter PDF-first mode on: "process these PDFs", "I have some papers",
"extract from these", "I dropped some PDFs in", "just process what's in
the folder".

**PDF-first mode** skips search/triage. For each unprocessed PDF: extract
metadata → check processed.json → extract (§7) → taxonomy check (§16) →
validate/write (§7f, §8) → mark processed with `"triage": "user_supplied"`.
After all local PDFs, offer to continue with search mode or stop.

### 3b. Search mode (default)

Repeat until user stops, session_target reached, or searches exhausted:

**→ Search → Triage → Queue → Extract → Update state → Report → repeat**

**Hard separation of search and extraction**: Search agents ONLY populate
`state/queue.json`. They must NEVER attempt extraction. Extraction agents
ONLY process papers already in the queue. Never combine search + extraction
in a single subagent.

For each stage, read the relevant reference file and use the model per §2:
- **Search & Triage** (haiku): [search_and_triage.md](references/search_and_triage.md)
  - Search agents write ONLY to: `state/queue.json`, `state/search_log.json`,
    `state/triage_outcomes.jsonl`. No other file writes permitted.
- **Fetch, Extract, Validate, Write** (sonnet): [extraction_and_validation.md](references/extraction_and_validation.md)
  - Extraction agents write ONLY to: `results.csv` (via SchemaEnforcedWriter),
    `state/processed.json`, `leads.csv`, `state/run_log.jsonl`.
- **Taxonomy check** (inline): [taxonomy.md](references/taxonomy.md)
- **State & Reporting** (haiku): [session_management.md](references/session_management.md)

### 3c. Parallel paper processing

After triage, dispatch **up to 3 papers concurrently** to parallel sonnet
subagents. Each runs the full pipeline (fetch → extract → taxonomy → validate
→ write) independently for ~3x throughput. Full coordinator pattern, subagent
prompt template, error handling, and fallback rules in
[extraction_and_validation.md](references/extraction_and_validation.md) §3c.

**Critical rules for subagents:**
- **Back up results.csv** before dispatching any batch.
- Subagents must use `scripts/csv_writer.py` for all writes — never raw
  `csv.DictWriter` or `open("results.csv", "w")`.
- **No abstract-only extraction** — if full text unavailable, route to
  leads.csv and return immediately.
- **Verify record count** after each batch. If it decreased, restore backup.
- If any subagent fails, fall back to serial processing for the rest of
  the session.

**Every 2 papers processed**, regenerate the dashboard:
```bash
python3 dashboard_generator.py --project-root .
```

**When `session_target` is reached**, run post-session checks and print summary:
```bash
python3 scripts/pdf_utils.py --project-root . --check
python3 dashboard_generator.py --project-root .
```

If `pdf_utils.py --check` finds misplaced PDFs, report them to the user and
offer to run `--fix` to move them to the correct `pdfs/{Family}/` locations.

Then ask:
```
Session target reached ({N} papers). Continue with another batch? [y/n]
```

---

## 14. Self-Improving Domain Knowledge

As the agent processes papers, it captures notation variants, new taxa,
ambiguity patterns, and validation gaps in `state/discoveries.jsonl`. At
session end, it proposes diff-formatted amendments to `guide.md` for user
approval. Full discovery types, review protocol, mid-session correction
pathway, and cumulative knowledge reports in
[knowledge_evolution.md](references/knowledge_evolution.md).

**Core principle**: The agent proposes; the human decides. Never silently
edit `guide.md`, `extraction_examples.md`, or `collector_config.yaml`.

---

## 15. Audit Mode — Self-Cleaning Data

Re-examines low-confidence, statistically anomalous, and guide-drift records
by re-extracting from cached PDFs with current domain knowledge. Full logic
in [audit_mode.md](references/audit_mode.md).

**Triggers**: "audit the database", "check low-confidence records",
"clean the data", "re-check flagged records", "run an audit".

**Three criteria** (priority): low confidence → guide-drift → statistical outliers.
**Core method**: re-extract from cached PDF using `source_page` with current
`guide.md`, without seeing original values (prevents anchoring).

---

## 16. Taxonomic Intelligence

Every extracted species name is validated against the GBIF Backbone Taxonomy.
The agent resolves synonyms to accepted names, auto-fills higher taxonomy
when missing, and flags nomenclatural issues. When a name is updated to an
accepted synonym, the original extracted name is preserved in the `notes`
field (e.g., "Original name: Cicindela sylvatica, resolved to accepted name
via GBIF"). Full integration spec in [taxonomy.md](references/taxonomy.md).

**Script**: `scripts/taxonomy_resolver.py` handles batch GBIF lookups with
caching to `state/taxonomy_cache.json` to avoid redundant API calls.

---

## 17. Statistical QC

At session end and on-demand ("run QC", "check data quality", "how's the
data looking"), the agent runs `scripts/statistical_qc.py` to generate
diagnostic plots and a quality report. Includes: outlier detection (Grubbs
test for continuous data, modal-frequency for discrete), species accumulation
curves with Chao1 estimator, confidence distribution analysis, taxonomic
coverage vs. GBIF known diversity, and session-over-session efficiency
trends. Full spec in [statistical_qc.md](references/statistical_qc.md).

Output: `qc_report.html` (self-contained with plots) and `qc_summary.json`.

---

## 18. Campaign Planning

After 3+ sessions, the agent can generate a strategic campaign report
analyzing: taxonomic coverage gaps (families with known diversity but few
or no records), search efficiency trends (records/paper by query type),
estimated sessions to reach target coverage, and recommended search strategy
adjustments (which queries to prioritize, when to switch to citation
chaining). Full spec in [campaign_planning.md](references/campaign_planning.md).

**Triggers**: "plan the campaign", "coverage report", "how much is left",
"what should I focus on next", "strategic report".

---

## 19. Confidence Calibration

Transforms heuristic confidence scores into calibrated probabilities via
isotonic regression. `scripts/calibration.py` computes ECE, fits per-field
models, generates reliability diagrams. Full spec in
[confidence_calibration.md](references/confidence_calibration.md).

**Triggers**: automatic at session end if calibration data exists;
"calibrate", "check calibration", "reliability diagram".

---

## 20. Extraction Benchmarking

Built-in accuracy measurement against gold-standard data. During
calibration (§0b), 2-3 seed papers are held out as benchmark papers —
the user verifies every extracted field, creating ground truth for
precision/recall/F1 per field. Benchmark data also accumulates from
audit outcomes (§15) and user corrections (§14f).

**Script**: `scripts/benchmark.py` computes per-field and record-level
metrics, Brier score, and tracks accuracy trends over sessions. Full spec
in [benchmarking.md](references/benchmarking.md).

**Triggers**: automatic during calibration; on-demand via "benchmark this
paper", "run benchmark", "check accuracy".

---

## 21. Multi-Agent Consensus Extraction

When mean confidence < 0.7, run 2 additional independent passes
(enumeration-first, adversarial) and resolve by field-level 2/3 vote; ties
flagged for human review. Triples cost per triggered paper — configurable
threshold and per-session cap. Full spec in
[consensus_extraction.md](references/consensus_extraction.md).

**Triggers**: automatic on low confidence; "run consensus", "verify extraction",
"double-check this paper".

---

## 22–28. Advanced Features

Chain-of-thought traces, active learning for triage, adaptive tool selection,
cross-project transfer learning, knowledge graph provenance export, streaming
progress, and formal reproducibility. Full spec in
[advanced_features.md](references/advanced_features.md).

---

## Stop Conditions

The agent stops when any of these are met:
- User says stop
- `session_target` papers processed this session (collection mode)
- `audit_config.max_records` reviewed this session (audit mode)
- 10,000 total records in results.csv
- 15 consecutive empty searches (no new papers found)
- All queries in `config.py` exhausted (offer smart citation chaining first)
