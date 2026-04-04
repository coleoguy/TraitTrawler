# Dispatch Cycle — Detailed Agent Operations

This reference contains the full agent spawn templates, return validation
procedures, progress reporting formats, failure handling, and context
management guidelines. The Manager loads this at session start and after
context compaction if needed.

---

## Decision Logging Formats

**Print compact dispatch logs to the conversation window** so the user can
monitor pipeline health. Keep these SHORT — every line consumes Manager
context that can't be recovered. Use the compact formats below.

**IMPORTANT — context conservation**: The Manager's context window is the
pipeline's lifespan. Every unnecessary line printed shortens the session.
Use the shortest format that conveys the essential information. Never
print raw JSON output from scripts — extract the 2-3 key numbers and
report those.

Before a dispatch cycle, print ONE line:

```
dispatch: q=42 rdy=3 finds=1 → spawn dealer(10.1234/example) + writer
```

After each agent returns, print ONE line:

```
dealer_003 (95s): EXTRACTED 8 records | fetcher_001 (120s): 5/8 fetched
```

For no-data results, batch them:

```
dealers 004-008: 2 extracted (12 records), 3 no-data (ecology, microbiome, genomics)
```

Every 10 papers, print a 3-line throughput block:

```
── 10/20 papers | 48 min | 87 records (+7.3/paper) ──
yield: 70% data | fetch: 67% | queue: 30 | confidence: 0.87 avg
bottleneck: fetcher (queue backing up)
```

**Do NOT print**:
- Full JSON output from `process_agent_output.py` — extract key numbers only
- Validation detail blocks (PASS/FAIL per field) — only report failures
- Source stats breakdowns — only report if yield is abnormally low
- Agent spawn template details — you already know the templates
- File contents from finds/, dealer_results/, or writer_results/

**Do NOT read agent output files into Manager context.** Always use the
processing scripts and only capture their summary numbers. The scripts
handle all state updates — the Manager only needs counts for dispatch
decisions and user reporting.

---

## Agent Spawn Templates

**CRITICAL — context conservation**: NEVER paste agent .md file contents
into Agent() prompts. Sub-agents have Read tool access and read their own
spec from disk. The Manager passes ONLY the task-specific parameters
(project root, handoff file, mode, etc.). This saves thousands of tokens
per spawn and dramatically extends session lifespan.

### Searcher (background, continuous)

```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Searcher agent.\nRead your full instructions from: scripts/../agents/searcher.md (use Read tool on the CLAUDE_SKILL_DIR path, or find it via: python3 -c \"import os; print(os.path.join(os.environ.get('CLAUDE_SKILL_DIR','skill'), 'agents', 'searcher.md'))\")\n\nSEARCH QUERIES:\n{next 20 from config.py}\n\nALREADY SEEN DOIs:\n{doi list}\n\nPROJECT ROOT: {cwd}")
```

**Batch size: 20 queries per Searcher.**

Pass the already-seen DOI list as a simple text list (one per line), NOT
the full processed.json. Generate it:
```bash
python3 -c "import json; [print(k) for k in json.load(open('state/processed.json')).keys()]"
```

**On return**: Process output via script (never read agent files into context):
```bash
python3 scripts/process_agent_output.py --action search_results --project-root .
```
Returns: `{files, queries, new_to_queue, rejected, source_counts, sources_hit, validation}`.

**Exhaustion**: Stop re-spawning when all queries in config.py have been run.

### Fetcher (background, dual-track)

Two parallel tracks — **API** (fast, OA) and **Browser** (slower, paywalled).

**DOI prefix routing**:
```bash
python3 scripts/dispatch.py route-fetch --project-root . \
    --api-batch-size 8 --browser-batch-size 3
```

**Spawn two Fetchers in parallel** (both background):
```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Fetcher agent.\nRead your full instructions from the fetcher.md file in the skill agents directory.\n\nFETCH MODE: api\nPAPERS TO FETCH:\n{api_batch}\nCONTACT EMAIL: {contact_email}\nPROJECT ROOT: {cwd}")

Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Fetcher agent.\nRead your full instructions from the fetcher.md file in the skill agents directory.\n\nFETCH MODE: browser\nPAPERS TO FETCH:\n{browser_batch}\nPROJECT ROOT: {cwd}")
```

**On return**: Process output via scripts:
```bash
python3 scripts/process_agent_output.py --action fetch_failures --project-root .
python3 -c "import json,glob,sys; sys.path.insert(0,'scripts'); from state_utils import remove_from_queue; [remove_from_queue('state', json.load(open(f)).get('doi','')) for f in glob.glob('ready_for_extraction/*.json')]"
python3 scripts/process_agent_output.py --action fetch_successes --project-root .
```

Route API failures to next browser batch.

**Exhaustion**: Stop re-spawning when queue.json is empty AND no Searcher running.

### Dealer (background, up to max_concurrent_dealers)

Use the `handoff_files` list from `recommend` to pick files.

**Register the handoff filename**:
```bash
AGENT_ID=$(python3 scripts/dispatch.py start --project-root . \
    --session-id $SESSION_ID --agent-type dealer \
    --payload '{"handoff_file": "FILENAME.json"}')
```

```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Dealer agent.\nRead your full instructions from the dealer.md file in the skill agents directory.\n\nHANDOFF FILE PATH: ready_for_extraction/{filename}\nPROJECT ROOT: {cwd}\nEXTRACTION MODE: {consensus|fast}")
```

**On return**: Process output via scripts:
```bash
python3 scripts/process_agent_output.py --action dealer_results --project-root .
python3 scripts/process_agent_output.py --action finds --project-root .
```

**Exhaustion**: Stop re-spawning when ready_for_extraction/ is empty AND
no Fetcher running.

### Writer (foreground, serialized)

Spawn whenever finds/ has files. **Never spawn concurrent Writers.**

```
Agent(model=sonnet, prompt="You are a TraitTrawler Writer agent.\nRead your full instructions from the writer.md file in the skill agents directory.\n\nPROJECT ROOT: {cwd}\nSESSION ID: {session_id}")
```

Spawn the Writer:
- After every 2-3 Dealer returns (batch up finds for efficiency)
- When a Dealer returns and no other Dealers are in-flight
- Before session end (flush all remaining finds)

**On return**: Process output via script:
```bash
python3 scripts/process_agent_output.py --action writer_results --project-root .
```

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

1. **Do NOT track or print token estimates.** Token counting wastes
   Manager context and produces nothing actionable. The session will
   naturally end when context fills or the target is reached.

2. **Do NOT print per-paper progress lines.** The throughput block every
   10 papers (above) is sufficient. Per-paper lines waste context.

3. **Regenerate dashboard** every 10 papers (or at session end):
   ```bash
   python3 dashboard_generator.py --project-root .
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
   - "pause" → stop spawning new agents after current wave finishes
   - "status" → run `dispatch.py status`, print pipeline state
   - "explore [question]" → query the collected data (see SKILL.md §4b)

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
- Track failure count mentally (do NOT maintain a usage dict)
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
pdfs/                    — all PDFs, standardized names (Lastname-Year-Word-index.pdf)
pdfs/                    — legacy PDF location (pre-v4.4.0), organized by {family}/
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

4. **Never read agent .md files** into Manager context. Sub-agents have
   Read tool access and load their own specs from disk. The Manager only
   passes task-specific parameters (handoff file, project root, mode).

5. **Folder-based self-checkpointing**: files in `finds/`,
   `ready_for_extraction/`, `learning/` persist across sessions and context
   compactions. Resume by processing backlogs at startup (section 1a–1e).
   No explicit checkpoint file needed — the folders ARE the checkpoint.

6. **For long sessions (>20 papers)**: ask to continue every 20 papers.
   This gives the user a natural exit point and keeps sessions manageable.
