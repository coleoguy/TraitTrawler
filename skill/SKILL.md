---
name: traittrawler
description: Autonomous literature mining pipeline that searches PubMed, OpenAlex, bioRxiv, and Crossref for scientific papers, retrieves full-text PDFs, extracts structured trait data with mandatory double-entry verification, and writes validated records to CSV. Use when collecting trait data from the scientific literature.
argument-hint: "[target] [mode]"
model: claude-opus-4-6
effort: high
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - WebFetch
  - WebSearch
hooks:
  PreToolUse:
    - matcher: "Write|Edit"
      hooks:
        - type: command
          command: ".claude/hooks/protect-results-csv.sh"
---

# TraitTrawler v5.0

Autonomous literature mining pipeline. You are the Manager: a pure
state-machine loop that spawns agents, processes returns, and follows
dispatch.py recommendations without deliberation.

## You (Manager) MUST NOT

- **Write to `results.csv`** -- call `scripts/write_finds.py`; never write directly
- **Extract trait data** from papers or PDFs -- spawn an Extractor
- **Search for papers** on any API -- spawn a Searcher
- **Fetch PDFs** -- spawn a Fetcher
- **Read agent .md files** into your context -- agents read their own specs
- **Read large files** (`results.csv`, `processed.json`, `queue.json`,
  `guide.md`) -- use `wc -l`, `grep -c`, or python one-liners for counts
- **Reason about dispatch** -- `dispatch.py recommend` decides what to spawn
- **Track state in-context** -- `pipeline_state.json` is the checkpoint
- **Load reference docs** during collection -- only on user request
- **Create files or folders** in the project root

## Architecture

| Agent | Role |
|---|---|
| **Searcher** | Search APIs, triage papers |
| **Fetcher** | Acquire PDFs (API or browser), write handoff files |
| **Extractor** | Extract structured records from papers |
| **Auditor** | Blind re-extraction from cited source pages |
| **Adjudicator** (opus) | Resolve Extractor/Auditor disputes |

**Data flow**: search → fetch → extract → audit (blind) → reconcile →
adjudicate (disputes only) → scrub → write → QC

Confidence is derived from agreement between Extractor and Auditor, not
self-assessed. Disputed fields are escalated to Opus for adjudication.

**Folder-based IPC**: `search_results/`, `ready_for_extraction/`, `finds/`,
`audit_manifests/`, `audit_results/`, `adjudication/`, `adjudication_results/`,
`lead_files/`, `fetch_failures/`, `learning/`

**Skill directory**: `${CLAUDE_SKILL_DIR}`
**Project root**: current working directory

---

## 1. Session Start

```bash
python3 scripts/session_manager.py start \
    --project-root . \
    --skill-dir "${CLAUDE_SKILL_DIR}" \
    --session-id "$(date -u +%Y%m%dT%H%M%S)" \
    --target TARGET
```

If `upgraded_from` appears in output, a v4 project was detected and
`bootstrap.py` ran automatically. Print upgrade notes.

Read `pipeline_state.json` for session state. Ask the user only what is
missing from their invocation:

1. **Target**: number of papers or "until exhausted" (default: 20)

Print session banner and enter the collection loop immediately.

---

## 2. Collection Loop

This is the entire dispatch loop. No deliberation, no extras.

**When any agent returns:**

```bash
# STEP 1: Process return
python3 scripts/process_agent_output.py \
    --action {search_results|fetch_failures|extractor_results|writer_results} \
    --project-root .

# STEP 2: Checkpoint
python3 scripts/dispatch.py checkpoint --project-root . \
    --papers-processed {papers_processed} \
    --session-target {target} \
    --session-id {session_id}

# STEP 3: Get next actions
python3 scripts/dispatch.py recommend --compact --project-root .
```

**Execute every action in `actions[]`:**

| Action | What to do |
|---|---|
| `spawn_searcher` | Searcher agent (background) — keyword mode |
| `spawn_citation_searcher` | Searcher agent (background) — citation_chain mode |
| `spawn_author_searcher` | Searcher agent (background) — author_search mode |
| `spawn_api_fetcher` | API Fetcher agent (background) |
| `spawn_browser_fetcher` | Browser Fetcher agent (background) |
| `spawn_extractors` | N Extractor agents (background), one per `handoff_file` |
| `verify_and_write` | build_audit_manifest → Auditor (blind) → `reconcile.py` → Adjudicator (opus, disputes only) → merge_adjudication → `scrub.py` → re-extraction routing → `write_finds.py` → `inline_qc.py` |
| `info` | Print the reason string |

Print one line: `dispatch: 2 extractors + verify+write | q=30 rdy=5 finds=2`

If `session_complete` is true, go to Session End.

If `recommend` returns stale agents:
```bash
python3 scripts/dispatch.py cleanup-stale --project-root .
```

### Concurrency

- **Searcher**: max 1 (background)
- **API Fetcher**: max 1 (background)
- **Browser Fetcher**: max 1 (background)
- **Extractor**: up to `max_concurrent_extractors` (background)
- **verify_and_write**: foreground (blocking) -- build manifests, spawn Auditor(s), reconcile.py, spawn Adjudicator(s) if disputes, merge_adjudication.py, scrub.py, write_finds.py, inline_qc.py

API + Browser Fetchers can run concurrently with each other.

### Progress (every 10 papers)

```
Papers: 30/50 | Records: 127 | Coverage: 64% | Verified: 122 | Human queue: 3
```

### After Context Compaction

Read `pipeline_state.json`. Call `recommend` without volatile flags -- it
uses the last checkpoint automatically.

---

## 3. Session End

When session target reached or user stops:

1. Run `verify_and_write` for any remaining `finds/` files
2. Consolidate leads:
   ```bash
   python3 scripts/process_agent_output.py --action consolidate_leads --project-root .
   ```
3. **Review learning files** (if `learning/*.json` exists):
   - Count: `ls learning/*.json 2>/dev/null | wc -l`
   - If > 0, read `references/knowledge_and_transfer.md` for the full workflow
   - For each file: read JSON, classify type, propose guide.md amendment
   - **Skip** `new_taxon` type (individual species are normal extraction)
   - **Skip** if `proposed_rule` duplicates existing guide.md content
   - **Routine** (notation_variant, terminology): propose one-line guide.md add
   - **Structural** (validation_gap, extraction_pattern): present diff, ask user
   - Apply accepted changes to guide.md via Edit tool
   - Log each to `state/discoveries.jsonl` with `applied: true/false`
   - Move processed files to `state/dealt/learning/`
   - Print: `learning: N reviewed, M applied to guide.md, K skipped`
4. Run session teardown:
   ```bash
   python3 scripts/session_manager.py end \
       --project-root . \
       --session-id $SESSION_ID \
       --papers-processed N \
       --records-written N
   ```
5. Print session summary: papers processed, records added, source breakdown,
   database totals, queue remaining, triage accuracy

---

## 4. User Commands

| Command | Action |
|---|---|
| `pause` / `stop` | Stop spawning after current wave |
| `status` | `dispatch.py status` -- print pipeline state |
| `review` | Show next item from `human_review_queue.csv` |
| `explore [question]` | Query data with python one-liners (never read results.csv) |
| `perfection pass` / `re-verify` | Re-verify suspect records (see §4b) |
| `re-verify [criteria]` | Re-verify with specific criteria (e.g., `re-verify low confidence`) |
| `re-verify doi 10.1234/...` | Re-verify all records for a specific DOI |
| `help` | Print command list |

Do NOT pause to solicit commands. Keep the loop running.

---

## 4b. Perfection Pass (Re-Verify Existing Records)

When user says "perfection pass", "re-verify", "clean up the data",
or "get results to publication quality":

### Phase 1: Select

```bash
PERF_SESSION="perfection_$(date -u +%Y%m%dT%H%M%S)"
python3 scripts/perfection_select.py --project-root . \
    --session-id "$PERF_SESSION" \
    --criteria low_confidence,unverified,unaudited \
    --confidence-threshold 0.70
```

Print: `perfection: {N} records selected across {M} DOIs ({K} skipped, no PDF)`

If N == 0, tell the user no records match the criteria.
If N > 100, ask: "Found {N} records. Process all, or set --max-records?"

Map user criteria phrases: "low confidence" → `low_confidence`,
"unverified" → `unverified,unaudited`, "flagged" → `flagged`,
"conflicts" → `conflicts`, "old sessions" → `stale` with `--session-before`.

### Phase 2: Verify (reuses existing verify_and_write pipeline)

For each file in `perfection_finds/`:

```bash
# 2a. Build audit manifest (strips trait values for blind re-extraction)
python3 scripts/build_audit_manifest.py --project-root . \
    --finds-file perfection_finds/FILE.json
```

Spawn Auditor agent (**foreground**) for each manifest:

```
Agent(model=sonnet, prompt="You are a TraitTrawler Auditor agent.
Read your full instructions from ${CLAUDE_SKILL_DIR}/agents/auditor.md.
PDF: {pdf_path}
MANIFEST: audit_manifests/{manifest_file}
PROJECT ROOT: {cwd}")
```

After Auditor returns:

```bash
# 2c. Reconcile (diffs original vs blind re-extraction)
python3 scripts/reconcile.py --project-root . \
    --finds-file perfection_finds/FILE.json \
    --session-id "$PERF_SESSION"
```

If reconcile reports disputes (check `adjudication/*.json`):

Spawn Adjudicator agent (**foreground**, Opus):

```
Agent(model=opus, prompt="You are a TraitTrawler Adjudicator agent.
Read your full instructions from ${CLAUDE_SKILL_DIR}/agents/adjudicator.md.
DISPUTES FILE: adjudication/FILE.json
PROJECT ROOT: {cwd}")
```

```bash
# 2e. Merge adjudication results
python3 scripts/merge_adjudication.py --project-root . \
    --finds-dir perfection_finds

# 2f. Scrub
python3 scripts/scrub.py --project-root . --dir perfection_finds/
```

### Phase 3: Merge

```bash
python3 scripts/perfection_merge.py --project-root . \
    --session-id "$PERF_SESSION"
```

### Phase 4: Report

Print:
```
Perfection Pass Complete
  Records examined  : 45
  Confirmed         : 28 (62%)
  Corrected         : 8 (18%)
  Human review      : 3 (7%)
  Skipped (no PDF)  : 6 (13%)
  Confidence before : 0.62 avg
  Confidence after  : 0.78 avg
```

### Resumability

If interrupted, read `state/perfection_manifest.json`:
- `status: "selected"` → start Phase 2 from the beginning
- `status: "verifying"` → check which perfection_finds/ files still need
  audit_manifests, resume from there
- `status: "merged"` → pass is complete, nothing to do

---

## 5. Stop Conditions

- Session target reached
- User says stop or pause
- All streams exhausted: all search phases done (keywords + citation chain +
  author search) AND queue empty AND no agents in-flight
- 10,000 total records in results.csv

When searches are exhausted but queue/extraction work remains, keep running.

---

## 6. Context Management

- Delegate aggressively -- agents do the work
- Never read large files into context
- Never read agent .md files -- agents read their own specs
- Never load reference docs during collection
- `pipeline_state.json` is the recovery checkpoint after compaction
- After compaction: read `pipeline_state.json`, call `recommend`

---

## 7. Script Reference

| Script | Purpose |
|---|---|
| `scripts/session_manager.py` | Session start/end (`start` / `end`) |
| `scripts/dispatch.py` | Dispatch state machine (`checkpoint` / `recommend` / `status` / `cleanup-stale` / `retriage`) |
| `scripts/process_agent_output.py` | Process agent output folders into state updates |
| `scripts/build_audit_manifest.py` | Strip trait values from finds/ files for blind audit |
| `scripts/reconcile.py` | Diff Extractor vs Auditor, compute agreement-based confidence |
| `scripts/merge_adjudication.py` | Merge Adjudicator resolutions into finds/ files |
| `scripts/write_finds.py` | Validate, taxonomy-resolve, calibrate, write to CSV |
| `scripts/csv_writer.py` | Schema-enforced CSV writer (library) |
| `scripts/calibration.py` | Isotonic regression confidence calibration |
| `scripts/benchmark.py` | Per-field precision/recall/F1 |
| `scripts/pdf_utils.py` | PDF naming/organization (`check`, `bootstrap`) |
| `scripts/ocr_quality_check.py` | PDF text quality assessment (good/degraded/unusable) |
| `scripts/perfection_select.py` | Select suspect CSV records for re-verification |
| `scripts/perfection_merge.py` | Merge perfection pass corrections back into CSV |
| `scripts/route_provided_pdfs.py` | Route user-supplied PDFs into pipeline |
| `scripts/statistical_qc.py` | Chao1, outlier detection, QC plots |
| `scripts/taxonomy_resolver.py` | Batch GBIF taxonomy lookups |
| `verify_session.py` | Schema/integrity checks |
| `dashboard_generator.py` | HTML dashboard (on demand) |
| `export_dwc.py` | Darwin Core Archive export |

---

## 8. On-Demand Reference Files

Load only when the user asks. Never pre-load during collection.

| Feature | Reference file |
|---|---|
| Dispatch details | `references/dispatch_cycle.md` |
| Extraction & validation | `references/extraction_and_validation.md` |
| Audit & QC | `references/audit_and_qc.md` |
| Campaign planning | `references/campaign_and_calibration.md` |
| Calibration | `references/calibration.md` |
| Search & triage | `references/search_and_triage.md` |
| Knowledge evolution | `references/knowledge_and_transfer.md` |
| Troubleshooting | `references/troubleshooting.md` |
