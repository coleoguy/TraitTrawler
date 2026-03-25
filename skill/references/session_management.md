# Session Management

## 9. State Management

### 9a. State file schemas

**`processed.json`** — object keyed by DOI (or normalized title if no DOI):
```json
{
  "10.1234/example.1111": {
    "title": "Title of a relevant paper",
    "triage": "likely",
    "outcome": "extracted",
    "records": 3,
    "date": "2026-03-20"
  },
  "10.1234/example.2222": {
    "title": "Title of an irrelevant paper",
    "triage": "unlikely",
    "outcome": "skipped",
    "records": 0,
    "date": "2026-03-20"
  }
}
```

**`queue.json`** — array of paper objects awaiting fetch/extraction:
```json
[
  {
    "doi": "10.1234/example.3333",
    "title": "A paper awaiting processing",
    "authors": "Smith et al.",
    "year": 2021,
    "journal": "Journal Name",
    "abstract": "Abstract text...",
    "triage": "likely",
    "source": "pubmed",
    "added_date": "2026-03-20"
  }
]
```

**`search_log.json`** — object keyed by query string:
```json
{
  "Taxon keyword": {
    "date": "2026-03-20",
    "pubmed_results": 23,
    "biorxiv_results": 1,
    "new_to_queue": 8
  }
}
```

**`run_log.jsonl`** — newline-delimited JSON, one event per line:
```json
{"timestamp": "2026-03-24T14:30:00Z", "session_id": "2026-03-24T14:30:00Z", "event": "session_start", "guide_md5": "abc123...", "config_py_md5": "def456..."}
{"timestamp": "2026-03-24T14:35:12Z", "session_id": "2026-03-24T14:30:00Z", "event": "paper_processed", "doi": "10.1234/ex.1111", "records": 3}
{"timestamp": "2026-03-24T14:45:00Z", "session_id": "2026-03-24T14:30:00Z", "event": "batch_complete", "papers_processed": 12, "records_added": 45}
{"timestamp": "2026-03-24T14:45:30Z", "session_id": "2026-03-24T14:30:00Z", "event": "session_end", "total_papers": 12, "total_records": 45}
```

### 9b. Update procedure

After every paper (success or failure):
- Add DOI (or normalized title) to `processed.json`
- Remove from `queue.json`
- If full text was unavailable and triage was likely/uncertain → append to `leads.csv` (see §5g)
- Append event to `state/run_log.jsonl`
- Write all files immediately — session can end anytime without data loss

Use atomic writes (write to `.tmp` then `os.rename`) to avoid corruption.

### 9b-2. Context management (critical for long sessions)

Long collection sessions can exhaust the context window, causing the agent
to lose track of the pipeline state, skip papers, or stop unexpectedly.
Use these strategies to prevent this:

**1. Delegate to subagents aggressively.** Every subagent (search/triage
on haiku, extraction on sonnet per §2) runs in an isolated context that
is discarded when it returns. This means PDF text, extraction reasoning,
and intermediate data do NOT accumulate in the main agent's context. The
main agent only sees the returned results (records, classifications).

**2. Avoid reading large files into context.** Never `Read` the entirety
of `results.csv`, `processed.json`, or `queue.json` into context when
they grow large. Instead:
- Count records: `wc -l results.csv` via Bash
- Check if a DOI is processed: `grep -c "doi_string" state/processed.json`
- Get queue depth: `python3 -c "import json; print(len(json.load(open('state/queue.json'))))"`

**3. Checkpoint every 10 papers.** After every 10 papers processed, write
a brief status checkpoint to `state/session_checkpoint.json`:
```json
{
  "session_id": "2026-03-24T14:30:00Z",
  "papers_processed": 10,
  "records_added": 37,
  "last_doi": "10.1234/example",
  "queue_remaining": 22,
  "queries_completed": 45,
  "next_action": "continue_queue"
}
```
If the session crashes or the context compacts, re-read this checkpoint
at the start of the next session to resume exactly where you left off.

**4. Don't hold PDF text.** After extracting records from a paper, do NOT
retain the PDF text in conversation. The subagent architecture handles
this naturally — the extraction subagent holds the PDF text, returns
records, and its context is released. If processing directly (no subagent),
summarize findings as records and move on.

**5. Re-read SKILL.md reference files if context compacts.** If you notice
you've lost track of the pipeline rules (e.g., after a long session), re-read
the relevant reference file. The progressive disclosure architecture means
re-reading is cheap — the files are small.

### 9d. Session duration control

At startup (§1g), present this prompt:

```
How long should I run?
  1. Quick pass — ~10 papers (good for testing or short sessions)
  2. Standard batch — {batch_size} papers (from config, default 20)
  3. Long session — 50+ papers (I'll checkpoint every 20 and ask to continue)
  4. Until I run out — process everything in the queue
  5. A specific number: ___
```

**Time-to-paper conversion**: If the user gives a time estimate, convert
using ~3–5 minutes per full-text paper, ~1 minute per abstract-only:
- "30 minutes" → ~8 papers
- "1 hour" → ~15 papers
- "a couple hours" → ~30 papers
- "let it run all day" → unlimited, checkpoint every 20

For long sessions (>20 papers), use the checkpoint strategy from §9b-2:
checkpoint every 10 papers, ask to continue every 20. This prevents both
context exhaustion and runaway cost.

### 9c. Pause triggers

After extracting each paper, check `pause_triggers` from `collector_config.yaml`
(optional). If any condition is met, pause and show the user the relevant records:

Example `pause_triggers`:
```yaml
pause_triggers:
  - field: extraction_confidence
    operator: less_than
    value: 0.5
    action: show_records
  - field: records_added_this_session
    operator: greater_than
    value: 100
    action: ask_continue
```

Supported operators: `less_than`, `greater_than`, `equals`, `not_equals`.
Actions: `show_records` (display and continue), `ask_continue` (show and ask user).

---

## 10. Progress Reporting

The cadence is configurable via `report_every` in `collector_config.yaml`
(default: 5 papers). After every N papers, print a rolling update:

```
📄 [15/45 queued] "Smith et al. 2003 — Paper title"
   → 8 records | source: proxy 🌐 | pdfs/Family/Smith_2003_Journal_9504.pdf
   → Session: +34 records | Database total: 1,281
```

Zero-record papers:
```
📄 [16/45] "Jones 1998 — Paper title"
   → 0 records (no target trait data — marked processed)
```

Large PDF progress:
```
📚 [large PDF, pages 51-100/380] "Author 1975 — Book title"
   → 142 records this batch | resuming next session from page 101
```

---

## 11. Session End

Print a summary when the user stops, `batch_size` is reached, or searches are exhausted.

**If user interrupts mid-paper**: finish the current paper completely before
stopping — never leave half-extracted records. Commit the full paper to
results.csv and state files before exiting.

Session summary format:

```
══════════════════════════════════════
 Session Complete
══════════════════════════════════════
 Session ID                    : {session_id}
 Papers processed this session : 23
 Records added                 : 89
 Via proxy (browser)           : 7
 Via open access               : 11
 Abstract-only                 : 5
 Leads added (need full text)  : 3
 Flagged for review            : 2
 Large PDFs in progress        : 1 (resuming p.101)
 Database total                : 1,336
 Leads total                   : 18
 Queue remaining               : 4
 Queries remaining             : 608 / 730
 Discoveries this session      : {N} (see state/discoveries.jsonl)
══════════════════════════════════════
```

At session end, also:
1. Run `verify_session.py` and report any issues found.
2. Run the domain knowledge review (§14) if discoveries were logged.
3. Regenerate the dashboard.
4. Check whether an audit is due: if `audit_config.auto_audit` is `true` and
   the session count (from `run_log.jsonl`) is a multiple of
   `audit_config.auto_audit_interval` (default: 5), offer:
   `🔍 Audit due — {N} records are candidates for re-examination. Run audit? [y/n]`

Append session-end entry to `state/run_log.jsonl`:
```json
{"timestamp": "2026-03-24T14:45:30Z", "session_id": "2026-03-24T14:30:00Z", "event": "session_end", "papers_processed": 23, "records_added": 89, "flagged_for_review": 2, "discoveries": 3}
```

---

## 12. Error Handling

- **Rate limits (429)**: back off 30s, retry once; if still failing, skip source.
- **PDF download timeout**: skip after 60s; note URL for retry next session.
- **Malformed state file JSON**: warn user, show raw content, do not overwrite.
- **results.csv write failure**: stop immediately — never silently drop records.
- **Chrome navigation fails**: mark `pdf_source: browser_failed`, fall through to abstract.
- **Proxy returns wrong content-type**: don't save as PDF; log and continue.

---

## 13. Dashboard

The skill includes a self-contained HTML dashboard that visualizes collection
progress and summary statistics. It lives at `{project_root}/dashboard.html`.

### When to update

Regenerate the dashboard at these points:
1. **Session start** (§1e) — after reading state files, before the first batch
2. **Every 10 papers processed** — alongside the rolling progress update (§10)
3. **Session end** (§11) — as part of the session summary

### How to update

The dashboard generator is copied to the project root at session start (§1e).
Regenerate the dashboard anytime with:

```bash
python3 "{project_root}/dashboard_generator.py" --project-root "{project_root}"
```

**Only re-copy if missing** — do not overwrite on every session start.

The script reads `results.csv`, `leads.csv`, `state/processed.json`,
`state/search_log.json`, and `config.py` and writes a single
self-contained `dashboard.html` with Chart.js visualizations.

### What the dashboard shows

**KPI cards** (top row): Total records, unique species, papers processed,
leads (need full text), flagged for review.

**Search progress bar**: queries completed vs. total from `config.py`

**Charts** (auto-generated based on available data): cumulative records over
time, records by taxonomic group (top 20), records by publication year,
full-text source breakdown, extraction confidence distribution, records by
country (top 15), lead failure reasons, lead status breakdown, and
additional trait-specific charts if recognized fields are present.

### Dashboard output location

The dashboard is always written to `{project_root}/dashboard.html`.
After generation at session start and session end, mention it to the user:

```
📊 Dashboard updated → dashboard.html
```

Do NOT open it in Chrome or ask the user to view it — just note that it exists.
