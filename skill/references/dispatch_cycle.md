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

**Exhaustion**: Stop keyword Searcher when all queries in config.py have run.
Then activate Phase 2.

### Searcher Phase 2: Citation Chaining (background)

Trigger when keyword searches are exhausted (all queries run, <5% yield on
last 20). No user prompt needed — just spawn it.

Pick seed DOIs — top 10 papers by record count from processed.json:
```bash
python3 -c "
import json
proc = json.load(open('state/processed.json'))
ranked = sorted(proc.items(), key=lambda x: x[1].get('records',0), reverse=True)
for doi, v in ranked[:10]:
    print(doi)
"
```

```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Searcher agent.
Read your full instructions from the searcher.md file in the skill agents directory.
MODE: citation_chain\nSEED DOIS:\n{seed_dois}\nALREADY SEEN DOIs:\n{doi list}\nPROJECT ROOT: {cwd}")
```

Process return the same way as keyword Searcher. Re-spawn with next 10
seeds if the first batch finds new papers. Stop when yield < 5%.

### Searcher Phase 3: Author Search (background)

Trigger when citation chaining yield drops below 5%, OR guide.md has a
"Prolific Authors" section.

Extract author list from guide.md (one grep, not a full file read):
```bash
python3 -c "
import re
with open('guide.md') as f: text = f.read()
m = re.search(r'Prolific Authors\n\n(.+)', text)
if m: print(m.group(1))
"
```

```
Agent(model=sonnet, run_in_background=true, prompt="You are a TraitTrawler Searcher agent.
Read your full instructions from the searcher.md file in the skill agents directory.
MODE: author_search\nAUTHOR NAMES:\n{author_list}\nALREADY SEEN DOIs:\n{doi list}\nPROJECT ROOT: {cwd}")
```

Process return the same way. Spawn once per session (don't re-spawn).

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

### Auditor (foreground, blind re-extraction)
Runs on ALL finds/ files. For each finds file, build a manifest of
`(species, source_page)` pairs WITHOUT the trait values — the Auditor
must not see what the Extractor found. The Auditor independently
re-extracts from the cited pages. Results go to `audit_results/`.

Build the manifest per finds file:
```bash
python3 scripts/build_audit_manifest.py --project-root . \
    --finds-file finds/FILENAME.json
```

Then spawn the Auditor (one per finds file, or batched):
```
Agent(model=sonnet, prompt="You are a TraitTrawler Auditor agent.
Read your full instructions from the auditor.md file in the skill agents directory.
PROJECT ROOT: {cwd}\nMANIFEST FILE: audit_manifests/FILENAME_manifest.json")
```

### Opus Adjudicator (foreground, disputes only)
When reconcile.py produces files in `adjudication/`, disputed fields
need a tiebreak. Spawn one Opus agent per disputes file:

```
Agent(model=opus, prompt="You are a TraitTrawler Adjudicator agent.
Read your full instructions from the adjudicator.md file in the skill agents directory.
PROJECT ROOT: {cwd}\nDISPUTES FILE: adjudication/FILENAME.json")
```

The Adjudicator reads only the cited source page(s) and the disputed
fields (both candidate values), picks the correct value with reasoning,
and writes `adjudication_results/FILENAME.json`. reconcile.py merges
these back into the finds/ files on the next pass.

### verify_and_write Pipeline (foreground, blocking)
Seven-step pipeline run after Extractors produce finds/ files:

1. **Build audit manifests**: `python3 scripts/build_audit_manifest.py --project-root . --dir finds/`
2. **Auditor** (foreground): spawn Auditor agents, one per manifest.
   Each writes to `audit_results/`.
3. **Reconcile**: `python3 scripts/reconcile.py --project-root . --session-id $SESSION_ID`
   - Mechanically diffs Extractor vs Auditor per record per trait field
   - Writes agreement-based confidence into finds/ files
   - Creates `adjudication/*.json` for disputed fields
   - Appends agreement observations to `state/calibration_data.jsonl`
4. **Adjudicate** (if `adjudication/` has files): spawn Opus Adjudicator
   agents. Merge results back into finds/ files via
   `python3 scripts/merge_adjudication.py --project-root .`
5. **Scrub**: `python3 scripts/scrub.py --project-root . --dir finds/`
6. **Re-extraction routing**: If scrub output contains `normalization_failures`,
   those records have field values that couldn't be auto-fixed. For each
   affected file: create a new handoff in `ready_for_extraction/` with the
   original `pdf_path` and an `extraction_instructions` field listing the
   specific field, bad value, and valid formats. Remove the affected file
   from `finds/` so it doesn't write bad data.
7. **Write**: `python3 scripts/write_finds.py --project-root . --session-id $SESSION_ID`
   then `python3 scripts/process_agent_output.py --action writer_results --project-root .`

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
dashboard.html            -- on-demand dashboard
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
