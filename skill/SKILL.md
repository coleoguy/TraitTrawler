---
name: trait-trawler
model: sonnet
effort: high
description: >
  Autonomous scientific literature mining agent that builds structured trait
  databases (karyotype, morphometric, life-history, any phenotype) from the
  primary literature. Searches PubMed, OpenAlex, bioRxiv, and Crossref;
  retrieves full-text PDFs via open-access cascades and institutional proxies
  (Chrome); extracts structured data from prose, tables, and catalogues;
  resolves taxonomy against GBIF; validates and writes to CSV with full
  provenance. Includes statistical QC (Chao1, Grubbs outlier detection),
  bidirectional citation chaining, self-improving domain knowledge, and
  multi-session campaign planning. Use when the user wants to: collect trait
  data, mine the literature, run a session, trawl for data, build a trait
  database, process papers, extract data from papers, add records, fetch PDFs,
  run QC, plan the campaign, audit the database, or continue collecting. Do
  NOT use for casual literature review (use deepscholar), simple data
  exploration, or one-off paper summaries.
allowed-tools: >
  Bash(python3:*) Bash(pip:*) Bash(cp:*) Bash(mkdir:*) Bash(wc:*) Bash(ls:*)
  Read Write Edit Glob Grep Agent WebFetch WebSearch
argument-hint: "[session-target or command, e.g. '20 papers', 'run QC', 'audit']"
compatibility: >
  Requires Python 3.9+, pyyaml, pdfplumber, scipy (optional, for Grubbs
  outlier detection), matplotlib (optional, for QC report plots). Network
  access required for PubMed, OpenAlex, bioRxiv, Crossref, Unpaywall, and
  GBIF APIs. Claude in Chrome MCP enables institutional proxy PDF retrieval;
  without it the skill degrades gracefully to open-access papers and abstracts
  only. PubMed and bioRxiv MCPs are optional (falls back to public APIs).
metadata:
  author: Heath Blackmon
  version: 2.0.0
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
| Troubleshooting | — | [troubleshooting.md](references/troubleshooting.md) | When something goes wrong |

Read the appropriate reference file when entering that pipeline stage.

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
6. "What should I call the output CSV file? (default: results.csv)"

### Researching answers the user delegates

For any wizard question, the user may say "you figure it out", "look it up",
or "research it." When this happens, use OpenAlex, PubMed, and web search
to research the answer. See [calibration.md](references/calibration.md) §0a
for specific research strategies per question. Always present researched
answers for user approval before writing config files.

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
  `discoveries.jsonl` (empty), `taxonomy_cache.json` (`{}`)
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

**After calibration completes**, proceed directly to §1 (Startup). Calibration
and the first collection session happen in the same invocation — the agent
runs §0 → §0b → §1 → §3 without stopping. §1f (session duration) still
applies to the first real batch after calibration.

**If `collector_config.yaml` exists → skip to §1.**

---

## 1. Startup

### 1a. Check dependencies

**Check Python dependencies** (run once per session):
```bash
python3 -c "import pdfplumber" 2>/dev/null || pip install pdfplumber --break-system-packages -q
python3 -c "import yaml" 2>/dev/null || pip install pyyaml --break-system-packages -q
python3 -c "import scipy" 2>/dev/null || pip install scipy matplotlib --break-system-packages -q
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
for script in statistical_qc.py taxonomy_resolver.py; do
  [ ! -f "scripts/$script" ] && cp "${CLAUDE_SKILL_DIR}/scripts/$script" "scripts/$script" 2>/dev/null || true
done
```

**Script usage** — execute all of these via Bash. Do NOT read them into context:

| Script | Purpose | Invocation |
|---|---|---|
| `dashboard_generator.py` | Generates `dashboard.html` from project data | `python3 dashboard_generator.py --project-root .` |
| `verify_session.py` | Post-batch CSV validation (schema, dupes, ranges) | `python3 verify_session.py --project-root .` |
| `export_dwc.py` | Exports results.csv as Darwin Core Archive | `python3 export_dwc.py --project-root . --output-dir dwc_export` |
| `scripts/statistical_qc.py` | Outlier detection, Chao1 estimator, QC plots | `python3 scripts/statistical_qc.py --project-root .` |
| `scripts/taxonomy_resolver.py` | Batch GBIF taxonomy lookups with caching | `python3 scripts/taxonomy_resolver.py --csv results.csv --species-column species --cache state/taxonomy_cache.json` |

Then regenerate the dashboard (see [session_management.md](references/session_management.md) §13).

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

**→ Search → Triage → Fetch → Extract → Taxonomy Check → Validate → Write → Update state → Report → repeat**

For each stage, read the relevant reference file and use the model per §2:
- **Search & Triage** (haiku): [search_and_triage.md](references/search_and_triage.md)
- **Fetch, Extract, Validate, Write** (sonnet): [extraction_and_validation.md](references/extraction_and_validation.md)
- **Taxonomy check** (inline): [taxonomy.md](references/taxonomy.md)
- **State & Reporting** (haiku): [session_management.md](references/session_management.md)

Aim to fully process 5–10 papers per reporting cycle.

**When `session_target` is reached**, print session summary and ask:
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

## Stop Conditions

The agent stops when any of these are met:
- User says stop
- `session_target` papers processed this session (collection mode)
- `audit_config.max_records` reviewed this session (audit mode)
- 10,000 total records in results.csv
- 15 consecutive empty searches (no new papers found)
- All queries in `config.py` exhausted (offer smart citation chaining first)
