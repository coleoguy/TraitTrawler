# Dispatch Cycle Reference (v5)

Loaded when Manager needs agent spawn details or error recovery guidance.
NEVER paste agent .md contents into prompts -- sub-agents read their own
spec from disk. Pass ONLY task-specific parameters.

---

## Agent Spawn Templates

### Searcher (background)
```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Searcher agent.
Read your full instructions from the searcher.md file in the skill agents directory.
SEARCH QUERIES:\n{next 20 from config.py}\nALREADY SEEN DOIs:\n{doi list}\nPROJECT ROOT: {cwd}")
```
Batch size: 20 queries. Generate DOI list:
`python3 -c "import json; [print(k) for k in json.load(open('state/processed.json')).keys()]"`

### Fetcher (background, dual-track)
Route DOIs then spawn two Fetchers in parallel (both background):
```bash
python3 scripts/dispatch.py route-fetch --project-root . --api-batch-size 8 --browser-batch-size 3
```
```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Fetcher agent.
Read your full instructions from the fetcher.md file in the skill agents directory.
FETCH MODE: {api|browser}\nPAPERS TO FETCH:\n{batch}\nCONTACT EMAIL: {contact_email}\nPROJECT ROOT: {cwd}")
```
API Fetcher includes CONTACT EMAIL; Browser Fetcher omits it. Route API failures to next browser batch.

### Extractor (background, up to max_concurrent_extractors)
Register then spawn:
```bash
AGENT_ID=$(python3 scripts/dispatch.py start --project-root . \
    --session-id $SESSION_ID --agent-type extractor \
    --payload '{"handoff_file": "FILENAME.json"}')
```
```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Extractor agent.
Read your full instructions from the extractor.md file in the skill agents directory.
PROJECT ROOT: {cwd}\nHANDOFF FILE: {handoff_file}")
```

### Auditor (foreground, mandatory verification)
Runs on ALL records from finds/ files. No sampling, no skip.
```
Agent(model=sonnet, prompt="You are a TraitTrawler Auditor agent.
Read your full instructions from the auditor.md file in the skill agents directory.
PROJECT ROOT: {cwd}\nFILES TO VERIFY: {finds_file_list}")
```

### verify_and_write Pipeline (foreground, blocking)
Four-step pipeline run after Extractors produce finds/ files:

1. **Auditor** (foreground): spawn Auditor on all finds/ files
2. **Scrub**: `python3 scripts/scrub.py --project-root . --dir finds/`
3. **Write**: `python3 scripts/write_finds.py --project-root . --session-id $SESSION_ID`
4. **Process**: `python3 scripts/process_agent_output.py --action writer_results --project-root .`

When to run: after every 2-3 Extractor returns, when an Extractor
returns with none in-flight, or before session end.

---

## Agent Return Processing

Process output via script after each return (never read agent files into
Manager context). All commands take `--project-root .`.

| Agent            | Command                                              |
|------------------|------------------------------------------------------|
| Searcher         | `process_agent_output.py --action search_results`    |
| Fetcher          | `process_agent_output.py --action fetch_failures`    |
| Extractor        | `process_agent_output.py --action extractor_results` |
| verify_and_write | `process_agent_output.py --action writer_results`    |

---

## Validation Checks

Each action returns a `validation` object. Key fields per stage:

**Searcher** -- `has_papers` (false = empty, retry once), `multi_source`
(false = single source, log warning).

**Fetcher** -- `browser_used` (false = re-route failures to browser),
`yield_pct` (success rate), `low_yield` (true when < 20% and n >= 3).

**Extractor** -- `produced_output` (false = handoff stays for retry),
`all_failed`, `has_records` (false = finds with 0 records),
`empty_papers` (DOI list).

**verify_and_write** -- `has_writes` (false = nothing written),
`has_errors`, `high_reject_rate` (more rejected than accepted).

---

## Failure Handling

### Per-agent policy

**Searcher**: Retry once. Second failure: mark `"outcome": "agent_error"`
in search_log.json, skip those queries.

**Fetcher**: Papers stay in queue.json on failure. After 2 consecutive
failures for same paper: route to leads.csv, remove from queue.

**Extractor**: Handoff stays in ready_for_extraction/ on failure. Retry
once. After 2 failures: move to state/dealt/ with `"outcome":
"agent_error"` in processed.json.

**Auditor**: If Auditor fails, skip to scrub step (scrub and write have
their own validation).

**write_finds.py**: finds/ preserved on failure. Retry once. Second
failure: report to user.

### General policy
- Max 1 automatic retry per agent call
- 3+ errors in a session: warn user, ask whether to continue
- All errors logged to `state/run_log.jsonl`

### Exhaustion conditions
- **Searcher**: stop when all config.py queries have run
- **Fetcher**: stop when queue.json empty AND no Searcher running
- **Extractor**: stop when ready_for_extraction/ empty AND no Fetcher running
- **Session complete**: target reached, user stops, or all streams exhausted
  (no agents in-flight + all directories empty)

---

## Directory Layout

```
collector_config.yaml     -- master config
config.py                 -- search terms
guide.md                  -- domain knowledge
results.csv               -- the database (append-only)
leads.csv                 -- papers needing full-text
dashboard.html            -- auto-generated dashboard
scripts/                  -- utility Python scripts
state/                    -- JSON state files (Manager-owned)
  dealt/                  -- processed handoff files
  session_reports/        -- session report output
  snapshots/              -- state snapshots
pdfs/                     -- all PDFs (Lastname-Year-Word-index.pdf)
finds/                    -- extraction results awaiting verify_and_write
extractor_results/        -- Extractor no-data and error reports
ready_for_extraction/     -- handoff files (Fetcher writes, Extractor reads)
search_results/           -- Searcher output
fetch_failures/           -- Fetcher failure reports
lead_files/               -- individual lead JSONs (consolidated at session end)
writer_results/           -- write_finds.py summaries
learning/                 -- session discoveries awaiting review
provided_pdfs/            -- user-supplied PDFs awaiting processing
```

Agents must NEVER create files outside this layout. No ad-hoc scripts,
temp folders, report files, or status files in the project root. Use
Python `tempfile` for scratch space, `state/run_log.jsonl` for logging.
