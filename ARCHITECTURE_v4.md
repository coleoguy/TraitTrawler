# TraitTrawler v4 — Multi-Agent Architecture Specification

## Purpose of this document

This is the complete architectural specification for rebuilding TraitTrawler as a
true multi-agent system. It replaces the current monolithic SKILL.md with a
constellation of dedicated agents that communicate via the filesystem. Claude Code
should use this document to implement the rebuild.

---

## 1. Design Principles

1. **One agent, one job.** Each agent has a single responsibility and writes to a
   single output location. No agent does search AND extraction AND CSV writing.

2. **Consensus by default (user-configurable).** Every paper gets 3 independent
   extraction passes with majority-rule voting. This is the standard pipeline.
   The cost is ~3x extraction tokens per paper; the payoff is dramatically higher
   accuracy for scientific data where errors compound. At session start the Manager
   asks the user to choose an extraction mode:
   - **Consensus (default)**: 3 agents per paper, majority-rule voting. Best accuracy.
   - **Fast**: 1 agent per paper, no voting. ~3x faster, lower token cost. Use for
     exploratory runs, well-understood traits, or when budget is tight.
   The choice is stored in `collector_config.yaml` → `extraction_mode` and can be
   changed at any session start. The Dealer respects this setting when spawning
   Extractors.

   `max_concurrent_dealers` (default: 2) controls how many papers are extracted in
   parallel. Set in `collector_config.yaml` → `concurrency`. Increase to 3–4 if
   the pipeline is bottlenecked on extraction; decrease to 1 for debugging.

3. **File-based inter-agent communication.** Agents communicate by writing files to
   well-defined folders with well-defined naming conventions. No shared mutable JSON
   state passed between agents. Each folder is a queue. This eliminates the entire
   class of concurrent-write bugs (CSV corruption, state desync, column shift) that
   plagued v2–v3.

4. **Opus thinks, Sonnet works.** The Opus-Manager coordinates and talks to the
   user. Sonnet sub-processes do all the actual work (search, fetch, extract, write).
   Opus is never in the extraction hot path — it stays available for decisions.

5. **On-demand vs sub-process.** Sub-processes (SP) run as part of the continuous
   pipeline loop. On-demand agents (OD) are user-triggered or condition-triggered.
   The prefixes are for human readability only — both are implemented as Agent
   subagent calls from the Manager.

---

## 2. Agent Roster

### Opus-Manager (the SKILL.md entry point)

- **Model**: opus (or session default — this is the main agent)
- **Role**: Coordinator. Interacts with the user. Reads project state. Decides what
  to do next. Spawns sub-processes. Never does extraction, search, or CSV writing
  itself.
- **Reads**: All config files, state files, context.md
- **Writes**: Only `state/run_log.jsonl` (session events), user-facing messages
- **Spawns**: All other agents via the Agent tool

### SP: Sonnet-Searcher

- **Model**: sonnet
- **Role**: Searches for papers and builds a queue of paper leads.
- **Inputs**: `config.py` (search terms), `guide.md` (triage knowledge),
  `collector_config.yaml` (triage_rules, triage_keywords),
  `state/search_log.json`, `state/processed.json`
- **Outputs**: Writes new paper leads to `state/queue.json`. Updates
  `state/search_log.json` with completed queries.
- **Writes to**: `state/queue.json`, `state/search_log.json`,
  `state/triage_outcomes.jsonl`
- **Never writes to**: `results.csv`, `leads.csv`, any folder in `pdfs/`, `finds/`
- **Behavior**:
  1. Pull the next N unrun queries from `config.py` (batch: 5–10 per invocation)
  2. Search PubMed, OpenAlex, bioRxiv, Crossref for each query
  3. Deduplicate against `processed.json` (by DOI, fallback to normalized title)
  4. Triage each paper: likely / uncertain / unlikely
  5. Add likely + uncertain papers to `queue.json` with metadata (doi, title,
     authors, year, journal, abstract, triage, triage_confidence, source, added_date)
  6. Mark unlikely papers directly in `processed.json` with `"triage": "unlikely"`
  7. Log completed queries to `search_log.json`
  8. Return summary JSON to Manager: `{"queries_run": N, "papers_found": N,
     "new_to_queue": N, "queue_depth": N}`

### SP: Sonnet-PDF Fetcher

- **Model**: sonnet
- **Role**: Acquires PDFs for papers in the queue. Names them uniquely for extraction.
- **Inputs**: `state/queue.json` (papers to fetch), `collector_config.yaml`
  (proxy_url, contact_email, vision_extraction setting)
- **Outputs**: PDF files saved to `pdfs/{family}/` with standardized names.
  Metadata written to `ready_for_extraction/` folder.
- **Writes to**: `pdfs/` subdirectories, `ready_for_extraction/` folder,
  `leads.csv` (when PDF unavailable), `state/processed.json` (for lead entries)
- **Never writes to**: `results.csv`, `finds/`
- **Behavior**:
  1. Pull the next paper from `queue.json`
  2. Run OA cascade: Unpaywall → OpenAlex → EuropePMC → Semantic Scholar → CORE
  3. If all OA fail and proxy configured: use Claude in Chrome for proxy fetch
  4. If PDF obtained:
     - Save to `pdfs/{family}/{FirstAuthor}_{Year}_{JournalAbbrev}_{ShortDOI}.pdf`
       using `scripts/pdf_utils.py`
     - Extract text via pdfplumber (or vision for scanned PDFs)
     - Write a handoff file to `ready_for_extraction/`:
       ```
       ready_for_extraction/{doi_safe}.json
       ```
       Contents:
       ```json
       {
         "doi": "10.1234/example",
         "title": "Paper Title",
         "authors": "Smith et al.",
         "year": 2003,
         "journal": "Journal Name",
         "pdf_path": "pdfs/Carabidae/Smith_2003_CompCytogen_9504.pdf",
         "pdf_source": "unpaywall",
         "text_pages": 24,
         "has_tables": true,
         "document_type": "table-heavy",
         "fetched_at": "2026-03-27T14:00:00Z"
       }
       ```
  5. If PDF NOT obtained:
     - Write paper to `leads.csv` with reason (needs_fulltext, paywall, etc.)
     - Mark in `processed.json` with `"outcome": "lead_needs_fulltext"`
  6. Remove paper from `queue.json`
  7. Return summary to Manager: `{"doi": "...", "outcome": "fetched|lead",
     "pdf_path": "...", "pdf_source": "..."}`

### SP: Sonnet-Dealer

- **Model**: sonnet
- **Role**: Takes a PDF ready for extraction, sends it to the Sonnet-Extractor
  (which runs 3 parallel sub-agents), evaluates the result, and files the PDF
  as processed or failed.
- **Inputs**: Handoff files from `ready_for_extraction/`, `guide.md`,
  `collector_config.yaml`, `extraction_examples.md`
- **Outputs**: Moves processed handoff files to `state/dealt/`. Reports outcome
  to Manager.
- **Writes to**: `state/dealt/` (processed handoff files), `state/processed.json`,
  `state/run_log.jsonl`
- **Never writes to**: `results.csv`, `finds/`, `leads.csv`
- **Behavior**:
  1. Pick up the next file from `ready_for_extraction/`
  2. Read the PDF text (from the path in the handoff file)
  3. Check `collector_config.yaml` → `extraction_mode`:
     - **`consensus`** (default): Spawn a **Sonnet-Extractor** agent (which runs
       3 sub-agents with majority voting)
     - **`fast`**: Spawn a single Sonnet extraction sub-agent directly (Agent A
       Standard prompt only, no voting). Write the result to `finds/` with
       `consensus: "single_pass"` on all records.
  4. In either mode, pass the Extractor/sub-agent:
     - The full PDF text (or path for vision extraction)
     - Paper metadata (doi, title, year, journal)
     - `guide.md` content
     - `collector_config.yaml` output_fields, validation_rules
     - `extraction_examples.md` content (if exists)
  5. Receive back the Extractor's result (success with records, no data, or
     no consensus)
  6. On **success**: move handoff file from `ready_for_extraction/` to `state/dealt/`
     with outcome. Mark paper in `processed.json` as `"outcome": "extracted"`.
  7. On **no data** (paper had no extractable trait data): mark in `processed.json`
     as `"outcome": "no_data"`. Move handoff to `state/dealt/`.
  8. On **no consensus** (extractors disagreed, no majority): mark in
     `processed.json` as `"outcome": "consensus_failed"`. Move handoff to
     `state/dealt/`. Write paper to `state/needs_attention.csv` for human review.
  9. Return summary to Manager: `{"doi": "...", "outcome": "...",
     "records_extracted": N, "consensus_type": "full|partial|none"}`

### Sonnet-Extractor (spawned by Dealer)

- **Model**: sonnet
- **Role**: Spins up 3 Sonnet sub-agents. Each is given the same PDF and all
  tools/knowledge to extract the trait of interest independently. Applies
  majority-rule voting on non-string values. Writes accepted records to
  the `finds/` folder.
- **Inputs**: PDF text, paper metadata, guide.md, output_fields, validation_rules,
  extraction_examples.md
- **Outputs**: Temp result file in `finds/` folder. Lesson learned file in
  `learning/` folder (optional).
- **Writes to**: `finds/{unique_name}.json`, `learning/{unique_name}.json`
  (optional), `state/extraction_traces/` (reasoning traces)
- **Never writes to**: `results.csv`, `state/processed.json`, `leads.csv`
- **Behavior**:
  1. **Spawn 3 independent extraction sub-agents** (all sonnet), each with:
     - The same PDF text
     - The same guide.md, output_fields, validation_rules, examples
     - A different extraction strategy prompt:
       - **Agent A (Standard)**: "Extract all trait records from this paper.
         For each record, provide species, all trait fields, confidence, and
         provenance (source_page, source_context, extraction_reasoning)."
       - **Agent B (Enumeration-first)**: "First, list every species mentioned
         anywhere in this paper. For each species, list every table/figure/text
         passage with trait data. Then extract one record per species-observation."
       - **Agent C (Skeptical)**: "Extract trait records, but for each value
         you extract, note the strongest reason it could be WRONG. Only include
         values where the evidence clearly outweighs the doubt. Assign lower
         confidence when evidence is indirect."
  2. **Collect results** from all 3 agents
  3. **Align records** across agents by species name (fuzzy match on genus+epithet)
  4. **Apply majority-rule voting** for each field in each record:
     - **String fields** (species, family, genus, journal, sex, notes):
       accept any non-empty value that appears in at least 2 of 3 agents.
       If all 3 differ, take Agent A's value and flag for review.
     - **Numeric fields** (2n, confidence, sample_size, etc.):
       - If all 3 agree: accept, set `consensus: "full"`
       - If 2 of 3 agree: accept majority value, set `consensus: "majority"`
       - If all 3 differ: do NOT return a value for this field. Set
         `consensus: "none"`, flag the entire record for human review.
     - **Confidence**: take the MEDIAN of the 3 agents' confidence scores.
       Boost by +0.1 if full consensus. Lower by -0.1 if no consensus on
       any field.
  5. **Records found by only 1 or 2 agents** (not all 3):
     - Found by 2 agents: include with `consensus: "two_found"`, normal confidence
     - Found by 1 agent only: include with `consensus: "single_agent"`,
       confidence reduced by -0.15, flag_for_review = True
  6. **Write result file** to `finds/` with a unique name:
     ```
     finds/{doi_safe}_{timestamp}.json
     ```
     Contents:
     ```json
     {
       "doi": "10.1234/example",
       "title": "Paper Title",
       "pdf_path": "pdfs/Carabidae/Smith_2003_CompCytogen_9504.pdf",
       "pdf_source": "unpaywall",
       "extraction_timestamp": "2026-03-27T14:05:00Z",
       "records": [
         {
           "species": "Cicindela campestris",
           "family": "Cicindelidae",
           "chromosome_number_2n": 22,
           "sex_chromosome_system": "Xyp",
           "extraction_confidence": 0.92,
           "consensus": "full",
           "source_page": "14",
           "source_context": "Table 2, row 3: C. campestris, 2n=22, 10+Xyp",
           "extraction_reasoning": "Explicit values in table",
           "flag_for_review": false,
           "agent_values": {
             "A": {"chromosome_number_2n": 22, "sex_chromosome_system": "Xyp"},
             "B": {"chromosome_number_2n": 22, "sex_chromosome_system": "Xyp"},
             "C": {"chromosome_number_2n": 22, "sex_chromosome_system": "Xyp"}
           }
         }
       ],
       "no_data_agents": 0,
       "paper_metadata": {
         "year": 2003,
         "journal": "Comparative Cytogenetics",
         "first_author": "Smith"
       }
     }
     ```
  7. **Lesson learned** (optional): If any agent encountered a notation variant,
     ambiguous value, or pattern worth noting, write to `learning/`:
     ```
     learning/{doi_safe}_{timestamp}.json
     ```
     ```json
     {
       "doi": "10.1234/example",
       "type": "notation_variant",
       "description": "Sex chromosome system written as 'X1X2X3Y' with subscript
         notation. All 3 agents normalized to XXXY but Agent C flagged uncertainty.",
       "proposed_rule": "Add subscript-numbered notation as equivalent",
       "affected_fields": ["sex_chromosome_system"],
       "source_context": "Table 2 header notation"
     }
     ```
  8. **Return summary** to Dealer:
     - `"success"` + record count if any records extracted with consensus
     - `"no_data"` if all 3 agents found zero records
     - `"no_consensus"` if records were found but majority rule failed on
       key numeric fields for ALL records

### SP: Sonnet-Writer

- **Model**: sonnet
- **Role**: CSV file maintenance. Watches the `finds/` folder for new result
  files. For each file: validates records, runs taxonomy resolution, writes to
  `results.csv`, verifies its own work, then deletes the original file from
  `finds/`.
- **Inputs**: Files in `finds/` folder, `collector_config.yaml` (validation_rules),
  `state/taxonomy_cache.json`
- **Outputs**: Appended rows in `results.csv`. Updated `state/taxonomy_cache.json`.
- **Writes to**: `results.csv` (via SchemaEnforcedWriter), `state/taxonomy_cache.json`,
  `state/needs_attention.csv` (for flagged records)
- **Never writes to**: `finds/` (only deletes after successful write), `queue.json`,
  `pdfs/`, `leads.csv`
- **Behavior**:
  1. List all `.json` files in `finds/`
  2. For each file (oldest first, by timestamp in filename):
     a. Parse the JSON
     b. **Taxonomy resolution**: For each unique species in the records:
        - Check `state/taxonomy_cache.json`
        - If not cached, query GBIF via `scripts/taxonomy_resolver.py`
        - Apply: synonyms → accepted name, auto-fill family/genus if empty
        - Store original name in notes
     c. **Validation**: Apply universal checks (required fields, confidence
        range, no duplicates vs existing results.csv) and project-specific
        validation_rules from config
     d. **Deduplication**: Check against existing results.csv by
        (species + trait fields). Keep independent observations from different
        papers. Flag exact duplicates.
     e. **Write**: Use `scripts/csv_writer.py` SchemaEnforcedWriter to append
        records atomically. Add session_id and processed_date.
     f. **Verify**: Read back the last N rows of results.csv. Confirm:
        - Row count increased by expected amount
        - No column shift (field count matches header)
        - Written values match what was in the finds file
     g. **On success**: Delete the finds file. Log write event to
        `state/run_log.jsonl`.
     h. **On failure**: Do NOT delete the finds file. Write error to
        `state/needs_attention.csv`. Report to Manager.
  3. Return summary to Manager: `{"files_processed": N, "records_written": N,
     "records_rejected": N, "records_flagged": N}`

### OD: Opus-Setup Wizard

- **Model**: opus (runs as the Manager itself, not a subagent)
- **Role**: Runs on first invocation when `collector_config.yaml` does not exist.
  Walks the user through project setup. Generates all config files.
- **Trigger**: Absence of `collector_config.yaml` in project root

#### Path A: Fresh start (no CSV provided)

Same as current §0 setup wizard flow. Ask questions one at a time,
generate `collector_config.yaml`, `config.py`, `guide.md`, create `state/`
directory structure, create empty `results.csv` with headers, create `finds/`,
`ready_for_extraction/`, `learning/`, `state/dealt/` directories.

After completion: run calibration phase (spawn Sonnet sub-processes to
process 3–5 seed papers), then checkpoint and tell user to start a new
conversation.

#### Path B: Bootstrap from existing CSV ("go-by CSV")

The user can short-circuit setup by providing a CSV file — either empty (headers
only) or populated with existing data. This handles two use cases:
1. **Headers-only CSV**: The user already knows their schema. The column names
   define `output_fields` directly — no need to negotiate field names.
2. **Populated CSV**: Porting an existing project (v2/v3 TraitTrawler, manual
   data, collaborator's dataset). The data is imported and the schema is inferred.

**Detection**: At first-run, before asking wizard questions, check for any `.csv`
file in the project root (other than `leads.csv`). If found, ask:

```
Found {filename} ({N} columns, {M} data rows). Use this as the project template?
  1. Yes — infer my schema and settings from this file
  2. No — start fresh with the setup wizard
```

**If yes — bootstrap procedure**:

1. **Infer output_fields** from column headers. Map to types:
   - Columns with all-numeric values → `number`
   - Columns with only "True"/"False" → `boolean`
   - Everything else → `string`
   - Recognize standard TraitTrawler columns automatically:
     `species`, `family`, `genus`, `doi`, `paper_title`, `paper_year`,
     `first_author`, `paper_journal`, `extraction_confidence`, `flag_for_review`,
     `session_id`, `source_page`, `source_context`, `extraction_reasoning`,
     `consensus`, `accepted_name`, `gbif_key`, `taxonomy_note`, `pdf_source`,
     `source_type`, `notes`
   - Everything else is assumed to be a trait-specific field

2. **Ask only the questions that can't be inferred from the CSV**:
   - Taxon (can sometimes infer from `family`/`genus` columns, but confirm)
   - Trait name (infer from non-standard column names, but confirm)
   - Contact email
   - Proxy URL (or skip)
   - Triage keywords (can bootstrap from existing `paper_title` values)

3. **Generate config files** with inferred + confirmed values:
   - `collector_config.yaml` with `output_fields` matching CSV headers exactly
   - `config.py` with search terms (if user provides taxonomic groups)
   - `guide.md` (if populated CSV exists, analyze trait values for notation
     patterns and draft initial domain rules)

4. **Import data** (if CSV had rows):
   - Copy or rename the CSV to `results.csv`
   - Populate `state/processed.json` from DOIs in the CSV
   - Report: `"Imported {N} records from {filename}. {M} unique DOIs marked
     as already processed."`

5. **Skip calibration** if the imported CSV has 20+ records — the existing data
   serves as the calibration corpus. Generate `extraction_examples.md` from
   3–5 high-confidence records in the imported data.

6. **Create all folders** (same as Path A): `finds/`, `ready_for_extraction/`,
   `learning/`, `provided_pdfs/`, `state/dealt/`, `pdfs/`, etc.

This path means a user with an existing v2/v3 TraitTrawler project can drop their
`results.csv` into a new folder, open it in Cowork, and be collecting within
2 minutes instead of going through the full wizard + calibration.

### OD: Opus-Data QC

- **Model**: opus
- **Role**: On-demand cleanup, formatting, and quality review of the database.
  Flags things for human review.
- **Triggers**: "run QC", "check data quality", "audit the database",
  "clean the data", "check low-confidence records", "how's the data looking"
- **Behavior**:
  1. Run `scripts/statistical_qc.py` for Chao1, Grubbs, accumulation curves
  2. Run `verify_session.py` for schema/integrity checks
  3. Scan results.csv for:
     - Records with consensus == "none" or "single_agent"
     - Records with extraction_confidence < 0.5
     - Statistical outliers flagged by QC script
     - Guide-drift records (extracted under older guide.md rules)
  4. Present findings to user with specific recommended actions
  5. If user approves re-extraction: spawn Dealer → Extractor pipeline for
     affected papers using cached PDFs
  6. Run campaign planning if 3+ sessions exist

### OD: Opus-Handle PDFs

- **Model**: opus (initial detection), then delegates to pipeline
- **Role**: When the user drops PDFs into `provided_pdfs/` folder, routes them
  into the extraction pipeline.
- **Trigger**: User says "process these PDFs", "I have some papers", PDFs
  detected in `provided_pdfs/` at session start
- **Behavior**:
  1. Scan `provided_pdfs/` for PDF files
  2. For each PDF:
     a. Extract metadata (try DOI from first page, or ask user)
     b. Copy to `pdfs/{family}/` with proper naming
     c. Write handoff file to `ready_for_extraction/` (same format as Fetcher)
  3. The normal Dealer → Extractor → Writer pipeline handles the rest
  4. Report: `"Found {N} PDFs in provided_pdfs/. Routing to extraction pipeline."`

---

## 3. Folder Structure (Inter-Agent Communication)

```
project_root/
├── collector_config.yaml          # Project config (user + wizard)
├── config.py                      # Search queries (user + wizard)
├── guide.md                       # Domain knowledge (user + wizard + learning)
├── extraction_examples.md         # Worked examples (calibration + learning)
├── results.csv                    # Final database (Writer only)
├── leads.csv                      # Papers needing full text (Fetcher only)
├── dashboard.html                 # Generated dashboard (Manager triggers)
│
├── finds/                         # ← Extractor writes here
│   └── {doi_safe}_{ts}.json      # ← Writer reads + deletes after processing
│
├── ready_for_extraction/          # ← Fetcher writes here
│   └── {doi_safe}.json           # ← Dealer reads + moves to state/dealt/
│
├── provided_pdfs/                 # ← User drops PDFs here
│   └── *.pdf                     # ← Handle-PDFs agent routes to pipeline
│
├── learning/                      # ← Extractor writes lessons here
│   └── {doi_safe}_{ts}.json     # ← Manager reviews at session end
│
├── pdfs/                          # ← Fetcher writes here
│   ├── Carabidae/                # Organized by family (or primary grouping)
│   ├── Cicindelidae/
│   └── unknown/
│
├── state/
│   ├── processed.json            # All papers seen (Fetcher, Dealer, Searcher)
│   ├── queue.json                # Papers awaiting fetch (Searcher writes, Fetcher reads)
│   ├── search_log.json           # Completed queries (Searcher only)
│   ├── run_log.jsonl             # Event log (all agents append)
│   ├── taxonomy_cache.json       # GBIF cache (Writer only)
│   ├── triage_outcomes.jsonl     # Triage accuracy data (Searcher only)
│   ├── source_stats.json         # API effectiveness (Fetcher, Searcher)
│   ├── discoveries.jsonl         # Domain knowledge discoveries (from learning/)
│   ├── calibration_complete.json # Calibration checkpoint
│   ├── calibration_data.jsonl    # For confidence calibration
│   ├── consensus_stats.json      # Consensus outcomes (Extractor)
│   ├── needs_attention.csv       # Records needing human review
│   ├── dealt/                    # Processed handoff files (Dealer)
│   ├── extraction_traces/        # Full reasoning traces (Extractor)
│   └── snapshots/                # Pre-session backups (Manager)
│
└── scripts/                       # Utility scripts (copied from skill bundle)
    ├── csv_writer.py
    ├── taxonomy_resolver.py
    ├── statistical_qc.py
    ├── pdf_utils.py
    ├── api_utils.py
    ├── state_utils.py
    ├── calibration.py
    ├── benchmark.py
    ├── knowledge_graph_export.py
    ├── reproduce.py
    └── dashboard_server.py
```

### Folder contracts

| Folder | Producer | Consumer | File format | Lifecycle |
|--------|----------|----------|-------------|-----------|
| `finds/` | Extractor | Writer | JSON (records array) | Written by Extractor → Read by Writer → Deleted by Writer after successful CSV write |
| `ready_for_extraction/` | Fetcher | Dealer | JSON (paper metadata + pdf_path) | Written by Fetcher → Read by Dealer → Moved to `state/dealt/` by Dealer |
| `provided_pdfs/` | User | Handle-PDFs agent | Raw PDF files | Dropped by user → Processed by Handle-PDFs → Copied to `pdfs/` and handoff written to `ready_for_extraction/` |
| `learning/` | Extractor | Manager (session-end review) | JSON (lesson learned) | Written by Extractor → Reviewed by Manager → Archived to `state/discoveries.jsonl` |
| `pdfs/` | Fetcher, Handle-PDFs | Dealer/Extractor (read), QC (re-extraction) | PDF files | Permanent cache — never deleted |

### Naming conventions

- `finds/{doi_safe}_{ISO_timestamp}.json` — doi_safe replaces `/` and `.` with `_`
- `ready_for_extraction/{doi_safe}.json` — one file per paper, deduplicated
- `learning/{doi_safe}_{ISO_timestamp}.json` — tied to extraction event
- PDFs: `pdfs/{Family}/{FirstAuthor}_{Year}_{JournalAbbrev}_{ShortDOI}.pdf`

---

## 4. Main Loop (Opus-Manager Orchestration)

The Manager runs this loop. It never does extraction or search work itself.

```
SESSION START
│
├─ §0: Check for collector_config.yaml
│  └─ Missing → Run Setup Wizard (OD) → Calibration → Checkpoint → END SESSION
│
├─ §1: Startup
│  ├─ Install dependencies
│  ├─ Read config files (collector_config.yaml, config.py, guide.md)
│  ├─ Read state files (processed.json, queue.json, search_log.json)
│  ├─ Count results.csv records
│  ├─ Copy utility scripts if missing
│  ├─ Create backups (snapshots/)
│  ├─ Run verify_session.py
│  ├─ Regenerate dashboard
│  ├─ Check for provided_pdfs/ → if found, spawn Handle-PDFs (OD)
│  ├─ Check for files in finds/ → if found, spawn Writer to clear backlog
│  ├─ Check for files in ready_for_extraction/ → if found, process first
│  ├─ Ask user: extraction mode (consensus / fast) — show current setting
│  ├─ Ask user: session target (paper count or time)
│  └─ Print status block (includes extraction mode + max_concurrent_dealers)
│
├─ §2: Main collection loop (repeat until target or stop)
│  │
│  ├─ PHASE A: Fill the queue (if queue < 10 papers)
│  │  └─ Spawn Sonnet-Searcher with next batch of queries
│  │     Returns: new papers added to queue.json
│  │
│  ├─ PHASE B: Fetch PDFs (for queued papers without PDFs)
│  │  └─ Spawn Sonnet-PDF Fetcher for next 3 papers in queue
│  │     Returns: handoff files in ready_for_extraction/ or leads
│  │
│  ├─ PHASE C: Extract (for papers with PDFs ready)
│  │  └─ Spawn Sonnet-Dealer for each file in ready_for_extraction/
│  │     (up to max_concurrent_dealers in parallel; each spawns Extractor
│  │      in consensus mode, or runs single agent in fast mode)
│  │     Returns: result files in finds/ or failure reports
│  │
│  ├─ PHASE D: Write to CSV (for completed extractions)
│  │  └─ Spawn Sonnet-Writer to process all files in finds/
│  │     Returns: records written, rejected, flagged counts
│  │
│  ├─ PHASE E: Progress update
│  │  ├─ Print rolling progress (papers processed, records, confidence)
│  │  ├─ Regenerate dashboard (every 2 papers)
│  │  └─ Check stop conditions
│  │
│  └─ Loop back to PHASE A
│
├─ §3: Session end
│  ├─ Run verify_session.py
│  ├─ Run statistical_qc.py
│  ├─ Review learning/ folder → propose guide.md amendments
│  ├─ Regenerate dashboard
│  ├─ Print session summary
│  └─ Update context.md
│
└─ END SESSION
```

### Concurrency model

The Manager can run phases in parallel when there are no data dependencies:

- **Searcher** can run while **Dealer** processes papers already in the queue
- **Writer** can run while **Fetcher** is acquiring the next PDF
- **N Dealers** can run concurrently (controlled by `max_concurrent_dealers`,
  default 2). Each handles one paper independently. In fast mode, each Dealer
  runs 1 extraction agent; in consensus mode, each runs 3 — so peak concurrent
  extraction agents is `max_concurrent_dealers × 3` in consensus mode.
- **Writer** must NOT run concurrently with itself (single writer to results.csv)

The Manager tracks what's in-flight and sequences accordingly:

```
Time →
  [Searcher: batch 2]  [Searcher: batch 3]
  [Fetcher: paper A]   [Fetcher: paper D]   [Fetcher: paper G]
  [Dealer+Ext: paper B][Dealer+Ext: paper E]
  [Dealer+Ext: paper C][Dealer+Ext: paper F]
                        [Writer: A,B,C]       [Writer: D,E,F]
```

---

## 5. What Each Agent's Prompt Must Include

### Sonnet-Searcher prompt template

```
You are a TraitTrawler search agent. Your ONLY job is to search for papers
and classify them by relevance.

SEARCH QUERIES TO RUN:
{next_N_queries_from_config_py}

TRIAGE RULES:
{triage_rules_from_collector_config}
{triage_keywords_from_collector_config}

DOMAIN KNOWLEDGE (for triage decisions):
{guide_md_content}

ALREADY PROCESSED (skip these DOIs):
{list_of_dois_from_processed_json}

INSTRUCTIONS:
1. Run each query against PubMed, OpenAlex, bioRxiv, Crossref
2. For each paper found, classify as: likely / uncertain / unlikely
3. Deduplicate against the processed list above
4. Return results as JSON

YOU MUST NOT:
- Attempt to fetch or read any PDFs
- Write to results.csv or any file outside state/
- Extract any trait data

RETURN FORMAT:
{
  "queries_completed": [...],
  "papers_found": [
    {"doi": "...", "title": "...", "authors": "...", "year": N,
     "journal": "...", "abstract": "...", "triage": "likely|uncertain|unlikely",
     "triage_confidence": 0.85, "source": "pubmed|openalex|..."}
  ],
  "summary": {"total_found": N, "likely": N, "uncertain": N, "unlikely": N}
}
```

### Sonnet-Extractor sub-agent prompt template (×3 variants)

**Common preamble** (all 3 agents get this):
```
You are a TraitTrawler extraction agent. Extract structured trait data from
this scientific paper.

PAPER: {title} ({year}) DOI: {doi}
PDF TEXT:
{pdf_text}

OUTPUT FIELDS: {output_fields_from_config}
VALIDATION RULES: {validation_rules_from_config}

DOMAIN KNOWLEDGE:
{guide_md_content}

WORKED EXAMPLES:
{extraction_examples_md_content}

NOTATION RULES (STRICT):
{notation_rules_from_guide_md}

UNIVERSAL RULES:
- Extract data EXPLICITLY stated — never infer values not present in the text
- extraction_confidence: ALWAYS a float 0.0–1.0
- For each record, provide: source_page, source_context (verbatim, max 200 chars),
  extraction_reasoning (one sentence for ambiguous cases)
- Return ONLY valid JSON array of record objects
```

**Agent A (Standard)** appends:
```
Extract all trait records from this paper. Work through the text systematically.
For table-heavy papers, process each table row. For prose, extract from Results
and Discussion.
```

**Agent B (Enumeration-first)** appends:
```
STEP 1: List every species mentioned ANYWHERE in this paper (title, abstract,
introduction, methods, results, discussion, tables, figures, appendices).
STEP 2: For each species, list every location where trait data appears
(table + row, figure, text passage with page number).
STEP 3: Extract one record per species-observation pair from your enumeration.

This two-step approach ensures no species or data point is missed.
```

**Agent C (Skeptical)** appends:
```
For each value you extract, note the strongest reason it could be WRONG:
- Could the number be from a different species in the same table?
- Could the notation mean something different in this context?
- Is the value for the right sex/population/subspecies?

Only include values where the evidence clearly outweighs the doubt.
Assign LOWER confidence when evidence is indirect or ambiguous.
If genuinely uncertain about a value, leave the field empty rather than guessing.
```

### Sonnet-Writer prompt template

```
You are a TraitTrawler CSV writer agent. Your ONLY job is to take validated
extraction results from the finds/ folder and write them to results.csv.

PROJECT ROOT: .
OUTPUT FIELDS: {output_fields}
VALIDATION RULES: {validation_rules}
CURRENT SESSION ID: {session_id}

INSTRUCTIONS:
1. List all .json files in finds/
2. Process each file (oldest first):
   a. Parse JSON
   b. Run taxonomy resolution (scripts/taxonomy_resolver.py or GBIF API)
   c. Validate each record (required fields, ranges, no duplicates)
   d. Write via scripts/csv_writer.py SchemaEnforcedWriter
   e. Verify: re-read results.csv, confirm row count increased correctly
   f. On success: delete the finds file
   g. On failure: DO NOT delete. Report the error.
3. Return summary JSON

YOU MUST NOT:
- Fetch PDFs or search for papers
- Modify finds files (only delete after successful write)
- Write to results.csv by any means other than SchemaEnforcedWriter
- Use open("results.csv", "w") — this would DESTROY all data

RETURN FORMAT:
{
  "files_processed": N,
  "records_written": N,
  "records_rejected": N,
  "records_flagged": N,
  "errors": [...]
}
```

---

## 6. Features Mapped to New Architecture

| Current Feature | v4 Owner | Notes |
|----------------|----------|-------|
| Setup Wizard (§0) | Opus-Manager directly | Same flow, adds new folders (finds/, ready_for_extraction/, etc.) |
| Calibration (§0b) | Opus-Manager → spawns pipeline | Uses same Fetcher → Dealer → Extractor → Writer pipeline |
| Search (§3) | Sonnet-Searcher | Dedicated agent, cleaner |
| Triage (§4) | Sonnet-Searcher | Integrated with search — triage happens at search time |
| PDF Fetch (§5) | Sonnet-PDF Fetcher | Dedicated agent |
| Extraction (§7) | Sonnet-Extractor (3 sub-agents) | Consensus by default |
| Validation (§7f) | Sonnet-Writer | Moved from extraction to write phase |
| Taxonomy (§7g/§16) | Sonnet-Writer | Runs during write phase, before CSV append |
| CSV Write (§8) | Sonnet-Writer | Dedicated agent, sole writer to results.csv |
| State Management (§9) | Distributed | Each agent manages its own state files |
| Progress Reporting (§10) | Opus-Manager | Aggregates reports from sub-processes |
| Dashboard (§13) | Opus-Manager triggers | `python3 dashboard_generator.py` |
| Knowledge Evolution (§14) | Opus-Manager (session-end) | Reviews learning/ folder |
| Audit Mode (§15) | OD: Opus-Data QC | Re-extraction uses normal pipeline |
| Statistical QC (§17) | OD: Opus-Data QC | Runs scripts, presents to user |
| Campaign Planning (§18) | OD: Opus-Data QC | Runs scripts, presents to user |
| Confidence Calibration (§19) | Sonnet-Writer | Applied during write phase |
| Benchmarking (§20) | OD: Opus-Data QC | Uses calibration pipeline |
| Consensus (§21) | Sonnet-Extractor | Now default, not optional |
| Chain-of-thought Traces (§22) | Sonnet-Extractor | Written to state/extraction_traces/ |
| Active Triage Learning (§23) | Sonnet-Searcher | Uses triage_outcomes.jsonl |
| Adaptive Source Selection (§24) | Sonnet-Fetcher + Searcher | Uses source_stats.json |
| Transfer Learning (§25) | Opus-Manager (session-end) | Reviews learning/ for cross-project value |
| Knowledge Graph Export (§26) | OD: Opus-Data QC | On-demand script |
| Streaming Progress (§27) | Opus-Manager | Prints after each sub-process returns |
| Reproducibility (§28) | OD: Opus-Data QC | On-demand script |
| Mid-session Correction (§14f) | Opus-Manager | Stops pipeline, applies fix, offers re-extraction |
| Handle User PDFs (§3a) | OD: Opus-Handle PDFs | Routes to ready_for_extraction/ |

---

## 7. Implementation Plan for Claude Code

### Phase 1: Folder structure and contracts

1. Create the new folder structure (finds/, ready_for_extraction/, learning/,
   provided_pdfs/, state/dealt/)
2. Update the setup wizard to create these folders
3. Update config_template.yaml with new consensus_config defaults

### Phase 2: Sonnet-Writer (safest to build first)

1. Build the Writer agent that watches finds/ and writes to results.csv
2. Test with manually created finds/ JSON files
3. This is the most critical agent — if it works, the rest of the pipeline
   can be built around it safely

### Phase 3: Sonnet-Extractor (the 3-agent consensus engine)

1. Build the Extractor that spawns 3 sub-agents with different prompts
2. Build the majority-rule voting logic
3. Build the finds/ JSON writer
4. Test with a known paper

### Phase 4: Sonnet-Dealer (thin coordinator)

1. Build the Dealer that reads from ready_for_extraction/, spawns Extractor,
   handles outcomes
2. Test end-to-end: handoff file → Dealer → Extractor → finds/ → Writer → CSV

### Phase 5: Sonnet-PDF Fetcher

1. Port the existing OA cascade logic into a standalone Fetcher agent
2. Build the ready_for_extraction/ handoff file writer
3. Test: queue entry → Fetcher → ready_for_extraction/ file

### Phase 6: Sonnet-Searcher

1. Port the existing search + triage logic into a standalone Searcher agent
2. Test: queries → papers found → queue.json

### Phase 7: Opus-Manager (main loop)

1. Build the orchestration loop (Phase A → B → C → D → E)
2. Wire up concurrency (Searcher while Dealer runs, etc.)
3. Build session start/end logic
4. Build the learning/ review system

### Phase 8: On-demand agents

1. Port setup wizard
2. Port QC/audit
3. Port Handle-PDFs

### Phase 9: SKILL.md rewrite

1. The new SKILL.md is much simpler — it's the Manager's behavior spec
2. Reference files become agent prompt templates
3. Build and test the .skill archive

---

## 8. What to Preserve from v2/v3

These components work well and should be carried forward as-is:

- `scripts/csv_writer.py` — SchemaEnforcedWriter with atomic writes
- `scripts/taxonomy_resolver.py` — GBIF API with caching
- `scripts/statistical_qc.py` — Chao1, Grubbs, accumulation curves
- `scripts/pdf_utils.py` — PDF path construction and naming
- `scripts/state_utils.py` — Atomic state file operations
- `scripts/api_utils.py` — Rate limiting and retry logic
- `dashboard_generator.py` — HTML dashboard
- `verify_session.py` — Post-batch verification
- `export_dwc.py` — Darwin Core Archive export
- All example configs (coleoptera-karyotypes, avian-body-mass)
- The eval suite structure

---

## 9. What to Delete or Replace

- Current SKILL.md (replace with Manager-focused version, ~200 lines)
- `references/extraction_and_validation.md` (replaced by Extractor + Writer prompts)
- `references/search_and_triage.md` (replaced by Searcher prompt)
- `references/model_routing.md` (simplified: Opus manages, Sonnet works)
- `references/consensus_extraction.md` (consensus is now built into Extractor)
- `references/session_management.md` (simplified — Manager handles state)
- The "parallel paper processing §3c" pattern (replaced by Dealer/Extractor)

---

## 10. Key Behavioral Differences from v2/v3

| Behavior | v2/v3 | v4 |
|----------|-------|-----|
| Consensus extraction | Optional, triggered by low confidence | Default (consensus mode) or opt-out (fast mode) — user chooses at session start |
| Project setup | 9-question wizard, no shortcuts | Wizard OR drop a CSV (headers-only or populated) to bootstrap in 2 minutes |
| Model for extraction | Sonnet (escalate to Opus) | Sonnet ×3 in consensus mode, Sonnet ×1 in fast mode. Opus escalation on consensus failure. |
| Model for search/triage | Haiku | Sonnet (better triage accuracy, marginal cost difference) |
| CSV writing | Extraction subagent writes directly | Dedicated Writer agent, sole access to results.csv |
| Inter-agent communication | JSON state files + shared CSV | Folder-based queues (finds/, ready_for_extraction/) |
| Error recovery | Backup/restore results.csv | Writer verifies before deleting source file — bad writes never destroy data |
| Context management | Single agent holds everything | Each agent holds only its job + relevant config |
| Pipeline control | Monolithic main loop | Manager dispatches phases, agents are stateless workers |
| Concurrency | Up to 3 parallel extraction subagents | Configurable max_concurrent_dealers (default 2), each with 1 or 3 extraction agents |
| Porting old projects | Manual reconfiguration | Drop existing results.csv → auto-infer schema, import data, skip calibration |

---

## 11. Per-Agent Reference Files

Rather than embedding prompt templates in this architecture spec, each agent
type has its own `.md` file in `skill/agents/`:

```
skill/agents/
├── searcher.md              # Search APIs, triage classification, citation chaining
├── fetcher.md               # OA cascade, PDF acquisition, handoff file format
├── dealer.md                # Extraction coordination, mode selection, Opus escalation
├── extractor_A.md           # Standard extraction strategy
├── extractor_B.md           # Enumeration-first extraction strategy
├── extractor_C.md           # Skeptical extraction strategy
├── extractor_consensus.md   # Consensus orchestrator: spawns A/B/C, majority voting
└── writer.md                # Taxonomy resolution, validation, CSV writing, verify-then-delete
```

Each file contains **only** what that agent needs:
- Its role and boundaries ("you MUST NOT write to results.csv")
- Its input contract (what files/folders it reads)
- Its output contract (what it writes and where)
- Its return format (JSON schema the Manager expects back)
- Relevant domain rules (confidence scoring, triage criteria, etc.)

The Manager reads the appropriate `.md` file when spawning an agent and
injects it into the prompt alongside dynamic data (queue state, config
values, guide.md content, etc.).

**Advantages**:
- Each file is independently testable and version-controlled
- Editing the Writer's behavior doesn't risk breaking the Searcher
- The Manager doesn't hold all agent specs in context simultaneously
- Same progressive-disclosure pattern as v3's reference files, but scoped
  per-agent instead of per-topic

---

## 12. Opus Escalation on Consensus Failure

When the 3-agent Sonnet consensus fails (no majority on key numeric fields
for ALL records in a paper), the Dealer does NOT immediately route to
`needs_attention.csv`. Instead:

1. The Dealer spawns a single **Opus extraction agent** using the Agent A
   (Standard) prompt from `extractor_A.md` with `model: opus`
2. Opus receives the same PDF text, guide.md, config, and examples
3. If Opus returns results with mean confidence >= 0.7:
   - Records are written to `finds/` with `consensus: "opus_escalation"`
   - Paper marked as `"outcome": "extracted"` in processed.json
4. If Opus is also not confident (mean confidence < 0.7):
   - Paper goes to `state/needs_attention.csv` for human review
   - All extraction attempts (3 Sonnet + 1 Opus) are attached for context

**Rationale**: Consensus improves precision (catches random errors) but
doesn't help with systematic errors where all 3 Sonnet agents share the
same blind spot. Opus handles the cases that require deeper reasoning —
ambiguous notation, complex table layouts, unusual conventions.

**Cost**: Opus escalation fires on ~5-10% of papers (those where Sonnet
consensus fails). This keeps Opus out of the hot path while preserving it
as a safety net for the hardest papers.

---

## 13. Mid-Session Learning

The v3 system reviewed `learning/` discoveries only at session end. In v4,
the Dealer injects recent lessons into Extractor prompts mid-session:

1. Before spawning Extractors, the Dealer checks `learning/` for `.json`
   files created during this session
2. If any exist, their descriptions are appended to the Extractor prompt:
   ```
   RECENT DISCOVERIES (from earlier papers this session):
   - Notation variant: subscript-numbered sex chromosomes (X1X2Y → normalize to XXXY)
   - New taxon: Subfamily Platyninae not in GBIF — flag for review
   ```
3. This allows extraction quality to improve within a session as the system
   encounters new patterns

At session end, the Manager still does the full knowledge review (proposing
guide.md amendments for user approval). The mid-session injection is a
read-only preview — it doesn't modify guide.md.
