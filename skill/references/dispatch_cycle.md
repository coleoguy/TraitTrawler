# Dispatch Cycle — Detailed Agent Operations

This reference contains the full agent spawn templates, return validation
procedures, progress reporting formats, failure handling, and context
management guidelines. The Manager loads this at session start and after
context compaction if needed.

---

## Decision Logging Formats

**Print your dispatch reasoning to the conversation window** so the user can
see exactly what you're deciding and why. Before every dispatch cycle, output
a brief decision block like this:

```
── dispatch ──────────────────────────────────
state: queue=42 | ready=3 | finds=1 | leads=5
agents: searcher=idle | fetcher=running | dealers=2/3 | writer=idle
action: spawn dealer (handoff: 10.1234/example)
action: spawn writer (3 finds files ready, no dealers finishing)
reason: fetcher still running, searcher exhausted, 3 finds accumulated
──────────────────────────────────────────────
```

After each agent returns, print what happened **including duration**:

```
── fetcher returned (95s) ────────────────────
result: 2/3 fetched, 1 lead (paywall, browser attempted: yes)
source_stats check: browser attempts=3, successes=2
validation: PASS (browser_used=yes, source_stats_updated=yes, yield=67%)
ready_for_extraction: 5 files now
next: spawn 2 dealers + re-spawn fetcher
──────────────────────────────────────────────
```

Every 5 papers (or every 10 minutes), print a throughput summary:

```
── throughput ────────────────────────────────
session: 12 papers in 48 min (15.0 papers/hr)
records: 87 written (7.3 per paper avg)
fetch yield: 67% (20 fetched, 10 leads)
avg durations: searcher=142s fetcher=95s dealer=210s writer=15s
bottleneck: fetcher (queue backing up, 30 papers waiting)
──────────────────────────────────────────────
```

This is not optional. Always print these blocks — they are the primary way
the user monitors pipeline health and debugs agent misbehavior.

---

## Agent Spawn Templates

### Searcher (background, continuous)

Read `${CLAUDE_SKILL_DIR}/agents/searcher.md`. Spawn with `run_in_background=true`.

```
Agent(model=sonnet, run_in_background=true, prompt="{searcher.md content}\n\nSEARCH QUERIES:\n{next 20 from config.py}\n\nALREADY SEEN DOIs:\n{doi list from processed.json via one-liner}\n\nPROJECT ROOT:\n{cwd}")
```

**Batch size: 20 queries per Searcher.** The slim spec (97 lines) leaves
ample context for processing more queries per spawn.

Pass the already-seen DOI list as a simple text list (one per line), NOT
the full processed.json. Generate it:
```bash
python3 -c "import json; [print(k) for k in json.load(open('state/processed.json')).keys()]"
```

**On return**: Process output via script (never read agent files into context):
```bash
python3 scripts/process_agent_output.py --action search_results --project-root .
```
This returns a JSON summary: `{files, queries, new_to_queue, rejected, source_counts, sources_hit, validation}`.
Use the summary for your decision log block and run_log event. The script
handles all state updates (queue.json, search_log.json, processed.json,
source_stats.json) and deletes the processed files.

**Exhaustion**: Stop re-spawning when all queries in config.py have been run.

### Fetcher (background, dual-track)

Read `${CLAUDE_SKILL_DIR}/agents/fetcher.md`. The Fetcher runs in two
parallel tracks — **API** (fast, for OA papers) and **Browser** (slower,
for paywalled papers). Both can run simultaneously.

**DOI prefix routing** — classify papers using `dispatch.py`:
```bash
python3 scripts/dispatch.py route-fetch --project-root . \
    --api-batch-size 8 --browser-batch-size 3
```
Returns JSON with `api_batch` and `browser_batch` arrays, classified by
DOI prefix (OA-likely vs paywalled publishers).

**Spawn two Fetchers in parallel** (both background):
```
# API Fetcher — 5-8 OA-likely papers, no browser needed
Agent(model=sonnet, run_in_background=true, prompt="{fetcher.md}\n\nFETCH MODE: api\n\nPAPERS TO FETCH:\n{api_batch}\n\nCONTACT EMAIL: {contact_email}\n\nPROJECT ROOT:\n{cwd}")

# Browser Fetcher — 3 paywalled papers, uses Claude in Chrome
Agent(model=sonnet, run_in_background=true, prompt="{fetcher.md}\n\nFETCH MODE: browser\n\nPAPERS TO FETCH:\n{browser_batch}\n\nPROJECT ROOT:\n{cwd}")
```

**On return** (either Fetcher): Process output via scripts:
```bash
python3 scripts/process_agent_output.py --action fetch_failures --project-root .
python3 -c "import json,glob,sys; sys.path.insert(0,'scripts'); from state_utils import remove_from_queue; [remove_from_queue('state', json.load(open(f)).get('doi','')) for f in glob.glob('ready_for_extraction/*.json')]"
python3 scripts/process_agent_output.py --action fetch_successes --project-root .
```

If the API Fetcher produced failure files, **route those papers to the next
browser batch** (they failed OA but may work via institutional access).

**Exhaustion**: Stop re-spawning when queue.json is empty AND no Searcher running.

### Dealer (background, up to max_concurrent_dealers)

Read `${CLAUDE_SKILL_DIR}/agents/dealer.md`. Spawn for each handoff file.
Use the `handoff_files` list from `recommend` output to pick which files
to dispatch — this prevents double-dispatching the same file.

**Always register the handoff filename** in the dispatch payload:
```bash
AGENT_ID=$(python3 scripts/dispatch.py start --project-root . \
    --session-id $SESSION_ID --agent-type dealer \
    --payload '{"handoff_file": "FILENAME.json"}')
```

```
Agent(model=sonnet, run_in_background=true, prompt="{dealer.md content}\n\nHANDOFF FILE PATH:\nready_for_extraction/{filename}\n\nPROJECT ROOT:\n{cwd}\n\nEXTRACTION MODE: {consensus|fast}")
```

**On return**: Process output via scripts (never read agent files into context):
```bash
# Process no-data/failed results → processed.json
python3 scripts/process_agent_output.py --action dealer_results --project-root .
# Count and register extracted papers (doesn't delete finds — Writer does that)
python3 scripts/process_agent_output.py --action finds --project-root .
```
The dealer_results script returns: `{files, no_data, failed, invalid, validation: {produced_output, all_failed}}`.
The finds script returns: `{files, total_records, papers: [{doi, records, file}], validation: {has_records, empty_papers}}`.

**Exhaustion**: Stop re-spawning when ready_for_extraction/ is empty AND
no Fetcher running.

### Writer (foreground, serialized)

Read `${CLAUDE_SKILL_DIR}/agents/writer.md`. Spawn whenever finds/ has files.
Run in foreground — **never spawn concurrent Writers**.

```
Agent(model=sonnet, prompt="{writer.md content}\n\nPROJECT ROOT:\n{current working directory}\n\nSESSION ID: {session_id}")
```

Spawn the Writer:
- After every 2-3 Dealer returns (batch up finds for efficiency)
- When a Dealer returns and no other Dealers are in-flight
- Before session end (flush all remaining finds)

**On return**: Process output via script:
```bash
python3 scripts/process_agent_output.py --action writer_results --project-root .
```
Returns: `{files, records_written, records_rejected, records_flagged, records_duplicate, errors, validation: {has_writes, has_errors, high_reject_rate}}`.

---

## Agent Return Validation

All `process_agent_output.py` actions return a `validation` object in their
JSON output. The Manager checks these fields instead of running manual shell
commands:

**After Searcher** (`process_search_results`):
- `validation.has_papers` — false means Searcher produced nothing. Retry once.
- `validation.multi_source` — false means only 1 source returned results. Log warning.

**After Fetcher** (`process_fetch_failures` + `process_fetch_successes`):
- `validation.browser_used` — false means some failures didn't try browser.
  Re-spawn those papers with explicit browser instruction.
- `validation.yield_pct` — fetch success rate.
- `validation.low_yield` — true when yield < 20% and sample >= 3. Flag to user.

**After Dealer** (`process_dealer_results` + `process_finds`):
- `validation.produced_output` — false means Dealer produced nothing.
  Handoff stays in ready_for_extraction/ for retry.
- `validation.all_failed` — true means every dealer result was a failure.
- `validation.has_records` — false means finds exist but contain no records.
- `validation.empty_papers` — list of DOIs with 0 records extracted.

**After Writer** (`process_writer_results`):
- `validation.has_writes` — false means Writer wrote nothing.
- `validation.has_errors` — true means write errors occurred.
- `validation.high_reject_rate` — true means more records rejected than accepted.

---

## Phase E: Progress Update & Controls

After each Dealer+Writer cycle:

1. **Update usage tracker**: For each agent call that returned, estimate tokens:

   | Call type | Est. input tokens | Est. output tokens |
   |---|---|---|
   | Searcher (5-10 queries) | ~3,000 | ~1,500 |
   | Fetcher (1 paper) | ~500 | ~300 |
   | Dealer+Extractor consensus (1 paper) | ~(800 × pages + 2,000) × 3 | ~(500 × records) × 3 |
   | Dealer+Extractor fast/Opus (1 paper) | ~(800 × pages + 2,000) | ~(500 × records) |
   | Opus escalation from consensus (1 paper) | ~(800 × pages + 2,000) | ~(500 × records) |
   | Writer (N finds files) | ~2,000 | ~500 |

   Accumulate into `usage` and the appropriate tier in `est_*_by_tier`.

2. **Print one-line confidence trend** after each paper:
   ```
   Confidence: 0.87 avg (up from 0.84) | 3 records | total: 1,339
   ```

3. **Print rolling progress** every `report_every` papers (default 5):
   ```
   [15/45 queued] "Smith et al. 2003 -- Paper title"
     -> 8 records | source: unpaywall | consensus: full
     -> Session: +34 records | Database total: 1,281
   ```

4. **Regenerate dashboard** every 10 papers (or at session end):
   ```bash
   python3 dashboard_generator.py --project-root .
   ```

5. **Append to live_progress.jsonl**:
   ```json
   {"timestamp": "...", "paper": "Smith et al. 2003", "records": 3, "total_records": 1339, "queue_remaining": 22}
   ```

6. **Check pause triggers** from `collector_config.yaml` (if configured):
   ```yaml
   pause_triggers:
     - field: extraction_confidence
       operator: less_than     # less_than, greater_than, equals, not_equals
       value: 0.5
       action: show_records    # show_records, ask_continue
   ```
   If any trigger fires: show the relevant records and either continue
   (`show_records`) or ask the user (`ask_continue`).

7. **Handle user commands** (if the user sends a message mid-session):
   Do NOT pause to solicit commands — keep dispatching. Only react if the
   user actively sends one of these:
   - "skip" / "next" → skip current paper, mark `"outcome": "user_skipped"`
   - "redo last" → re-extract previous paper through Dealer
   - "pause" → stop after current paper without ending session
   - "show trace" → display chain-of-thought trace for last extraction
   - "consensus on last" → trigger consensus re-extraction for last paper

8. **Check stop conditions**: target reached, user stops, or **all streams
   exhausted** (Searcher done + queue empty + ready_for_extraction/ empty +
   finds/ empty + no agents in-flight).

9. **For long sessions (>20 papers)**: ask to continue every 20 papers.

---

## Agent Failure Handling

If any Agent() call returns an error, times out, or crashes:

**Searcher failure**: Log to `state/run_log.jsonl`:
`{"event": "agent_error", "agent": "searcher", "error": "..."}`.
Retry once with the same queries. If it fails again, skip those queries
(mark `"outcome": "agent_error"` in search_log.json) and continue. The
session proceeds with whatever is already queued.

**Fetcher failure**: Log the error. Papers remain in queue.json (Fetcher
removes them only on success) — they will be retried on the next Fetcher
spawn. After 2 consecutive failures for the same paper, route it to
leads.csv with `reason: "fetch_agent_error"` and remove from queue.

**Dealer failure** (includes Extractor/Consensus failures): Log the error.
The handoff file remains in `ready_for_extraction/` (Dealer moves it to
`state/dealt/` only on success). Retry once. After 2 failures for the same
handoff, move it to `state/dealt/` with `"outcome": "agent_error"` in
processed.json. Never leave handoffs stuck in ready_for_extraction/
indefinitely.

**Writer failure**: Log the error. finds/ files are preserved (Writer deletes
only after verified write). Retry once. If the retry also fails, report to
the user: "Writer failed — finds/ files preserved. Run 'process finds' to
retry." NEVER spawn a second Writer concurrently as a "retry" — wait for the
first to fully complete or fail before retrying.

**General retry policy**:
- Maximum 1 automatic retry per agent call
- Track failures in session usage: `usage["agent_errors"] += 1`
- If 3+ agent errors occur in a session, warn the user and ask whether
  to continue
- All errors logged to `state/run_log.jsonl`

---

## Directory Layout

**Root files** (user-facing or config):
```
collector_config.yaml    — master config
config.py                — search terms
guide.md                 — domain knowledge
extraction_examples.md   — worked examples (optional)
results.csv              — the database (append-only)
leads.csv                — papers needing full-text
dashboard.html           — auto-generated HTML dashboard
dashboard_generator.py   — copied from skill at startup
verify_session.py        — copied from skill at startup
export_dwc.py            — copied from skill at startup
```

**Root folders** (each has a defined purpose):
```
scripts/                 — utility Python scripts (copied from skill)
state/                   — all JSON state files (Manager-owned, agents never write here)
  state/extraction_traces/
  state/snapshots/
  state/dealt/            — processed handoff files
  state/session_reports/  — session_report.py JSON output
  state/needs_attention.csv
pdfs/                    — downloaded PDFs, organized by {family}/
finds/                   — extraction results awaiting Writer (Dealer writes, Writer reads)
ready_for_extraction/    — handoff files (Fetcher writes, Dealer reads)
search_results/          — Searcher output (Searcher writes, Manager reads + deletes)
fetch_failures/          — Fetcher failure reports (Fetcher writes, Manager processes → lead_files/)
lead_files/              — individual lead JSON files (consolidated to leads.csv at session end)
dealer_results/          — Dealer no-data/failed reports (Dealer writes, Manager reads + deletes)
writer_results/          — Writer summaries (Writer writes, Manager reads + deletes)
learning/                — session discoveries awaiting review
provided_pdfs/           — user-supplied PDFs awaiting processing
```

### Enforcement Rules

Agents must NEVER create files or folders outside the allowed layout.
No report files, no status files, no temp files, no log files, no ad-hoc
folders in the project root. Specifically:
- No `*.txt` report or status files in the root
- No `*_COMPLETE.*`, `*_REPORT.*`, `*_STATUS.*`, `*_SUMMARY.*` files
- No `fetch_*.py`, `pdf_fetch_*.json`, or other ad-hoc scripts
- No `temp/`, `logs/`, `leads_temp/`, `extraction_agents/`, or other
  ad-hoc folders
- No `context.md`, `summary.txt`, or other narrative files

If an agent needs temporary working space, use Python's `tempfile` module
(files in the OS temp directory, auto-cleaned). If an agent needs to log
something, append to `state/run_log.jsonl`. If an agent needs to report
results, return them in its JSON response to the Manager.

---

## Context Management

These strategies prevent context exhaustion in long sessions:

1. **Delegate aggressively**: every sub-agent (Searcher, Fetcher, Dealer,
   Extractor, Writer) runs in an isolated context that is discarded on
   return. PDF text, extraction reasoning, and intermediate data never
   accumulate in the Manager's context.

2. **Never read large files** into Manager context:
   - Count records: `wc -l results.csv`
   - Check if DOI processed: `grep -c "doi_string" state/processed.json`
   - Queue depth: `python3 -c "import json; print(len(json.load(open('state/queue.json'))))"`
   - Query count: `python3 -c "import json; print(len(json.load(open('state/search_log.json'))))"`
   - Never `Read` the entirety of results.csv, processed.json, queue.json,
     or search_log.json.
   - Never read guide.md, config.py, or collector_config.yaml into Manager
     context for the purpose of passing to subagents. Subagents read their
     own inputs from the project root.
   - For collector_config.yaml: extract only Manager-relevant fields via
     python3 one-liners (batch_size, extraction_mode, max_concurrent_dealers).

3. **Don't hold PDF text**: Neither the Manager nor the Dealer holds PDF text.
   The Extractor Consensus agent reads the PDF directly from the file path.
   The Manager only sees the return summary (records count, outcome, confidence).

4. **Re-read agent .md files** when spawning — they're the source of truth.
   If context compacts, re-read the relevant agent spec before the next spawn.

5. **Folder-based self-checkpointing**: files in `finds/`,
   `ready_for_extraction/`, `learning/` persist across sessions and context
   compactions. Resume by processing backlogs at startup (section 1a–1e).
   No explicit checkpoint file needed — the folders ARE the checkpoint.

6. **For long sessions (>20 papers)**: ask to continue every 20 papers.
   This gives the user a natural exit point and keeps sessions manageable.
