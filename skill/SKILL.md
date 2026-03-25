---
name: traittrawler
model: sonnet
effort: high
description: >
  Autonomous scientific literature mining agent. Searches PubMed, OpenAlex,
  bioRxiv, and Crossref, retrieves full-text PDFs through open-access sources
  and institutional proxies, extracts structured phenotypic data from prose,
  tables, and catalogues, and writes validated records to CSV. Taxon- and
  trait-agnostic: adapts to any system via project configuration files. Triggers
  on: collect trait data, run the agent, work on the database, gather papers,
  literature mining, build a trait database, let's collect some data, process
  papers, fetch PDFs, add records, process these PDFs, extract from these,
  I have some papers to process.
compatibility: "Requires Bash, Read, Write, WebFetch, Claude in Chrome MCP, PubMed MCP, bioRxiv MCP, OpenAlex MCP, Crossref MCP"
---

# TraitTrawler

Searches the scientific literature, retrieves full-text papers, and extracts
structured data records into a CSV. Everything about *what* to collect lives in
three project files: `collector_config.yaml` (taxa, trait, fields), `config.py`
(search queries), and `guide.md` (domain knowledge for extraction). The skill
itself is taxon- and trait-agnostic.

Run until the user stops, `batch_size` is reached, or the search queue is
exhausted. Pick up exactly where the previous session ended.

**Project root**: the folder Cowork has open (the current working directory).

## Pipeline stages (detail in reference files)

| Stage | Section | Reference file |
|---|---|---|
| Calibration (first run) | §0b | [calibration.md](references/calibration.md) |
| Search & Triage | §3–4 | [search_and_triage.md](references/search_and_triage.md) |
| Fetch, Extract, Validate, Write | §5–8 | [extraction_and_validation.md](references/extraction_and_validation.md) |
| State, Reporting, Dashboard | §9–13 | [session_management.md](references/session_management.md) |
| Self-improving knowledge | §14 | Below |
| Audit mode | §15 | [audit_mode.md](references/audit_mode.md) |

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
to research the answer using the taxon and trait from Q1–Q2. See
[calibration.md](references/calibration.md) §0a for specific research
strategies per question. Always present researched answers for user approval
before writing config files.

### Create project files

- Locate the skill directory:
  ```bash
  SKILL_DIR="$(dirname "$(find /sessions -path '*/skills/traittrawler/SKILL.md' -print -quit 2>/dev/null)")"
  ```
- Create `collector_config.yaml` from answers using the template in
  `$SKILL_DIR/references/config_template.yaml`. Populate `{TRAIT_FIELDS}` with
  trait-specific field names using these conventions:
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
  `discoveries.jsonl` (empty)
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
real session. The agent processes 3–5 seed papers to learn notation, table
formats, and terminology from real examples — then uses their citations to
warm-start the search queue. Full details in
[calibration.md](references/calibration.md).

Summary: ask for seed DOIs (or find them automatically) → extract with
aggressive §14 discovery logging → immediate knowledge review to update
`guide.md` → citation-seed the queue → auto-generate `extraction_examples.md`
from worked examples. The first real session starts with a battle-tested
`guide.md` and a warm queue instead of cold keyword searches.

**If `collector_config.yaml` exists → skip to §1.**

---

## 1. Startup

### 1a. Locate the skill directory and check dependencies

```bash
SKILL_DIR="$(dirname "$(find /sessions -path '*/skills/traittrawler/SKILL.md' -print -quit 2>/dev/null)")"
```

**Check Python dependencies** (run once per session):
```bash
python3 -c "import pdfplumber" 2>/dev/null || pip install pdfplumber --break-system-packages -q
python3 -c "import yaml" 2>/dev/null || pip install pyyaml --break-system-packages -q
```

If either install fails, warn the user but continue — fall back to Read tool
for PDFs and regex for YAML.

**Check MCP availability** — try each, degrade gracefully:
- PubMed MCP (`search_articles`): fallback → E-utilities API via WebFetch
- OpenAlex MCP (`search_works`): fallback → OpenAlex REST API via WebFetch
- bioRxiv MCP (`search_preprints`): fallback → Crossref API for preprints
- Crossref MCP (`search_crossref`): fallback → Crossref REST API via WebFetch
- Claude in Chrome: if unavailable, warn and skip proxy fetch (OA only)

Do not fail hard on any missing MCP.

### 1b. Read files in order

**Project files** (in project root):
1. `collector_config.yaml` — master config
2. `config.py` — search term list
3. `guide.md` — domain knowledge (inject into all triage and extraction)
4. `state/processed.json`, `state/queue.json`, `state/search_log.json`
5. `results.csv` — count existing records
6. `leads.csv` — count for status report
7. `state/discoveries.jsonl` — review any pending discoveries from prior sessions

**Skill reference files** (in `SKILL_DIR/references/`):
8. `csv_schema.md` — generic field definitions and confidence guidelines

**Project-specific** (optional):
9. `extraction_examples.md` — notation rules and worked examples

### 1c. Generate session_id and compute file hashes

Generate `session_id` as ISO timestamp (e.g., "2026-03-24T14:30:00Z").
Compute MD5 hashes of `guide.md` and `config.py` for change tracking.

### 1d. Check for flagged-for-review records

If `results.csv` has records with `flag_for_review == True`, report count
and offer to review before continuing.

### 1e. Dashboard initialization

Copy dashboard generator from `SKILL_DIR` if not present:
```bash
if [ ! -f "dashboard_generator.py" ]; then
  cp "$SKILL_DIR/dashboard_generator.py" "dashboard_generator.py"
fi
```
Then regenerate the dashboard (see [session_management.md](references/session_management.md) §13).

### 1f. Copy utility scripts

Copy utility scripts from `SKILL_DIR` if not present:
```bash
for script in verify_session.py export_dwc.py; do
  [ ! -f "$script" ] && cp "$SKILL_DIR/$script" "$script" 2>/dev/null || true
done
```

### 1g. Ask how long to run

Ask the user how long this session should run. Accept paper counts ("do 30
papers"), time estimates ("I have an hour" → ~15–20 papers at ~3–5 min
each), or presets ("quick pass" = 10, "long session" = 50+, "until done" =
unlimited). See [session_management.md](references/session_management.md)
§9d for the full prompt and conversion rules. If the user says "just go",
use `batch_size` from config. Set `session_target` for the rest of the run.

### 1h. Startup state log entry

Append to `state/run_log.jsonl`:
```json
{"timestamp": "...", "session_id": "...", "event": "session_start", "guide_md5": "...", "config_py_md5": "...", "session_target": 20}
```

### 1i. Print startup status

Print a status block: project name, session_id, records in database, papers
processed, leads count, flagged for review, session target, queue depth,
queries run (n/total), next query. Use box-drawing characters for formatting.

---

## 2. Model Routing

TraitTrawler uses cheaper, faster models for routine tasks and reserves
expensive models for tasks requiring deep reasoning. The Agent tool's `model`
parameter controls this. Configure defaults in `collector_config.yaml` →
`model_routing` (see config template), or accept these defaults:

| Task | Default model | Escalation trigger |
|---|---|---|
| Search (API calls, dedup) | `haiku` | — |
| Triage (abstract classification) | `haiku` | — |
| State updates, reporting, leads | `haiku` | — |
| Prose extraction | `sonnet` | → opus if confidence < 0.5 on retry |
| Table extraction (pass 1: enumerate) | `sonnet` | — |
| Table extraction (pass 2: extract) | `sonnet` | → opus if row-count mismatch > 10% |
| Catalogue/dense extraction | `sonnet` | → opus if > 50 taxa per page |
| Scanned PDF (vision) | `sonnet` | → opus if OCR artifacts detected |
| Validation & verification | `sonnet` | — |
| Knowledge review (§14 proposals) | `sonnet` | — |

### Escalation protocol

When a task escalates to a more expensive model:
1. Log the escalation to `state/run_log.jsonl`:
   ```json
   {"timestamp": "...", "session_id": "...", "event": "model_escalation", "doi": "...", "from": "sonnet", "to": "opus", "reason": "row_count_mismatch_23pct"}
   ```
2. Report to the user at the next progress update:
   `⬆ Escalated "{title}" to opus (reason: {reason})`
3. After the escalated task completes, return to the default model for the
   next paper. Escalation is per-paper, never sticky.

### Override

The user can say "use opus for everything" or "use sonnet for triage too" at
any time. Respect the override for the rest of the session but do not persist
it to config. Log overrides to `run_log.jsonl`.

### Implementation

Use the Agent tool with the `model` parameter to dispatch subtasks:
- Spawn a haiku subagent for search/triage batches
- The main agent (whatever model the session runs on) handles extraction
- Spawn an opus subagent only when escalation is triggered

When the session model is already haiku or sonnet, skip spawning a subagent
for tasks at that level — just do them directly.

**Batch subagent calls to amortize overhead.** Spawning a subagent has fixed
context-setup cost, so batch work rather than spawning per-paper:
- **Search**: Send 5–10 queries per haiku subagent call. Include the search
  terms, API instructions, and `processed.json` DOI list for dedup. The
  subagent returns new papers as JSON.
- **Triage**: Send 10–20 abstracts per haiku subagent call. Include
  `guide.md` content and triage rules. The subagent returns classifications.
- **Extraction**: Do NOT batch across papers — each paper needs full context.
  Run one paper per sonnet call (or do it directly if already on sonnet).
- **Audit queue construction**: One haiku subagent call to scan all of
  `results.csv` and return the prioritized queue.

Pass all needed context (guide.md, triage rules, config excerpts) in the
Agent prompt — subagents do not inherit the parent's conversation history.

---

## 3. Main Loop

### 3a. Detect operating mode

At startup, after reading state files, check for unprocessed local PDFs:

```bash
# Find PDFs in pdfs/ not yet in processed.json
```

Compare the list of PDF files in `pdfs/` against DOIs/titles in
`processed.json`. If there are unprocessed local PDFs, ask the user:

```
Found {N} unprocessed PDFs in pdfs/. How should I proceed?
  1. Process these PDFs first, then continue with search queue
  2. Search mode only (ignore local PDFs for now)
  3. PDF-only mode (process local PDFs, skip search)
```

Also enter PDF-first mode if the user says any of:
```
"process these PDFs", "I have some papers", "extract from these",
"I dropped some PDFs in", "just process what's in the folder"
```

**PDF-first mode** skips search and triage entirely. For each unprocessed
PDF in `pdfs/`:
1. Extract metadata (title, authors, year, DOI) from the first page
2. Check against `processed.json` to avoid reprocessing
3. Go straight to extraction (§7) — the paper is assumed relevant since
   the user supplied it
4. Set `pdf_source: local_pdf` and `source_type: full_text`
5. Validate and write per normal pipeline (§7f, §8)
6. Mark processed in `processed.json` with `"triage": "user_supplied"`

After all local PDFs are processed, offer to continue with search mode
or stop.

### 3b. Search mode (default)

Repeat until the user stops, `batch_size` is reached, or searches are exhausted:

**→ Search → Triage → Fetch → Extract → Validate → Write → Update state → Report → repeat**

For each stage, read the relevant reference file and use the model specified in §2:
- **Search & Triage** (haiku): See [search_and_triage.md](references/search_and_triage.md)
- **Fetch, Extract, Validate, Write** (sonnet, escalate per §2): See [extraction_and_validation.md](references/extraction_and_validation.md)
- **State updates & Reporting** (haiku): See [session_management.md](references/session_management.md)

Aim to fully process 5–10 papers per reporting cycle.

**When `batch_size` is reached**, print session summary and ask:
```
Batch complete ({N} papers). Continue with another batch? [y/n]
```

---

## 14. Self-Improving Domain Knowledge

This is the agent's learning system. As you process papers, you encounter
patterns, edge cases, and notation variants that aren't covered in `guide.md`.
Rather than silently adapting, capture these discoveries so the project's
domain knowledge improves over time.

### 14a. When to log a discovery

After extracting records from each paper, check whether you encountered any of:
- A notation variant not in `guide.md` or `extraction_examples.md`
- A new taxonomic name (family, subfamily) not previously seen in results.csv
- A field value that required interpretation not covered by existing rules
- A recurring low-confidence pattern (same type of ambiguity across papers)
- A journal or source type with unusual formatting worth noting
- A validation rule that should exist but doesn't

If so, append an entry to `state/discoveries.jsonl`:

```json
{
  "session_id": "2026-03-24T14:30:00Z",
  "timestamp": "2026-03-24T15:12:00Z",
  "type": "notation_variant",
  "source_doi": "10.1234/example.5678",
  "description": "Sex chromosome system written as 'X1X2X3Y' — not in normalization table. Wrote as XXXY per existing rule but the subscript notation suggests this may be a distinct system in Cicindelidae.",
  "proposed_rule": "Add to sex_chr_system normalization: X₁X₂X₃Y → XXXY. Add note in guide.md §Sex Chromosome Systems that numbered notation is equivalent.",
  "affected_fields": ["sex_chr_system"],
  "confidence": 0.85,
  "guide_section": "Sex Chromosome Systems"
}
```

### 14b. Discovery types

| Type | When to log |
|---|---|
| `notation_variant` | New way of writing a known value |
| `new_taxon` | Family/subfamily/tribe not previously encountered |
| `ambiguity_pattern` | Same type of unclear data across 2+ papers |
| `validation_gap` | A check that should exist but doesn't |
| `extraction_pattern` | Recurring document structure worth noting |
| `terminology` | Domain term with meaning not in guide.md |

### 14c. Session-end knowledge review

At the end of each session (after the session summary), if any discoveries
were logged during this session:

1. Read `state/discoveries.jsonl` for this session's entries.
2. Group discoveries by `guide_section`.
3. For each group, propose a **specific, diff-formatted amendment** to `guide.md`:

```
🔬 Domain Knowledge Review — {N} discoveries this session
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Discovery 1: New notation variant for sex chromosome systems
  Source: Smith et al. 2003 (10.1234/example.5678)

  Proposed addition to guide.md § Sex Chromosome Systems:
  ┌──────────────────────────────────────────────────┐
  │ + | X₁X₂X₃Y, X1X2X3Y | `XXXY` | Numbered       │
  │ + |   notation equivalent to repeated-letter form  │
  │ + |   Common in Cicindelidae (tiger beetles)       │
  └──────────────────────────────────────────────────┘

  Apply this change? [y/n/edit]
```

4. For each proposed change the user approves:
   - Apply the edit to `guide.md` using the Edit tool
   - Log the change to `state/run_log.jsonl`:
     ```json
     {"timestamp": "...", "session_id": "...", "event": "guide_updated", "section": "Sex Chromosome Systems", "change": "Added X₁X₂X₃Y normalization rule", "source_doi": "10.1234/example.5678"}
     ```
   - Mark the discovery as `"applied": true` in `discoveries.jsonl`

5. For rejected changes, mark as `"applied": false, "reason": "user rejected"`.

### 14d. Cumulative knowledge report

Every 5 sessions (tracked via `run_log.jsonl`), print a brief summary:

```
📚 Knowledge Growth Report
   guide.md: {N} agent-proposed amendments accepted ({M} rejected)
   Notation variants discovered: {N}
   New taxa encountered: {N}
   Validation rules suggested: {N}
```

This creates a transparent record of how the domain knowledge evolves —
essential for the MEE manuscript and for scientific reproducibility.

### 14e. Never modify guide.md without approval

The agent proposes; the human decides. Never silently edit `guide.md`,
`extraction_examples.md`, or `collector_config.yaml`. The user must
explicitly approve every change. This maintains scientific integrity
and keeps the human as the domain authority.

---

## 15. Audit Mode — Self-Cleaning Data

TraitTrawler can audit its own database by re-examining records that are
low-confidence, statistically anomalous, or extracted before domain knowledge
was updated. Full audit logic is in [audit_mode.md](references/audit_mode.md).

**Triggers** — the user says:
```
"audit the database", "check low-confidence records", "clean the data",
"re-check flagged records", "run an audit"
```

Or automatically: if `audit_config.auto_audit` is `true`, the agent offers
an audit every N sessions (default: 5).

**Three audit criteria** (priority order):
1. Low confidence — records below `audit_config.confidence_threshold` (0.6)
2. Guide-drift — records extracted before a `guide.md` update (tracked via
   `guide_md5` in `run_log.jsonl`)
3. Statistical outliers — continuous fields use SD threshold, discrete
   numeric fields (e.g., chromosome counts) use modal frequency to avoid
   flagging real polyploidy, categoricals flag singletons in groups with 10+

**Core principle**: Re-extract from the cached PDF using `source_page`,
with current `guide.md`, without looking at original values (prevents
anchoring). Diff old vs. new. User approves all trait-field corrections.

**Model routing**: haiku for queue construction, sonnet for re-extraction,
opus only when both versions disagree and both have confidence < 0.7.

Read [audit_mode.md](references/audit_mode.md) when entering audit mode.

---

## Stop Conditions

The agent stops when any of these are met:
- User says stop
- `batch_size` papers processed this session (collection mode)
- `audit_config.max_records` reviewed this session (audit mode)
- 10,000 total records in results.csv
- 15 consecutive empty searches (no new papers found)
- All queries in `config.py` exhausted (offer citation chaining first)
