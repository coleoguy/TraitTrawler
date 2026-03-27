# Session Management

## Contents

- [§9. State Management](#9-state-management) — file schemas, update procedure, context management, session duration, pause triggers
- [§10. Progress Reporting](#10-progress-reporting) — rolling update format, zero-record papers, large PDF progress
- [§10b. Usage Tracking](#10b-usage-tracking) — token estimation, per-tier tracking, efficiency metrics
- [§11. Session End](#11-session-end) — summary format, verification, QC, knowledge review, dashboard
- [§12. Error Handling](#12-error-handling) — rate limits, timeouts, malformed state, write failures
- [§13. Dashboard](#13-dashboard) — when/how to regenerate, what it shows

---

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

**Use `scripts/state_utils.py` for ALL state file operations.** This module
provides atomic writes (write-to-temp + rename), JSON validation on read,
and automatic backup/recovery:

```python
import sys
sys.path.insert(0, "scripts")
from state_utils import (
    update_processed, remove_from_queue, log_event,
    safe_read_json, safe_write_json, append_jsonl
)

# After processing a paper:
update_processed("state", doi, {
    "title": paper_title,
    "triage": "likely",
    "outcome": "extracted",
    "records": 3,
    "date": "2026-03-24"
})
remove_from_queue("state", doi)
log_event("state", {
    "session_id": session_id,
    "event": "paper_processed",
    "doi": doi,
    "records": 3
})
```

Every write creates a `.bak` backup before overwriting. If a state file is
corrupt on read, the utility automatically falls back to the backup. If both
are corrupt, it returns a safe default and warns the user.

**At session start**, run an integrity check:
```python
from state_utils import check_state_integrity
result = check_state_integrity(".")
if not result["ok"]:
    for issue in result["issues"]:
        print(f"  ⚠ {issue}")
```

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

**3. Checkpoint every 2 papers.** After every 2 papers processed, write
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
Also regenerate the dashboard at each checkpoint so the browser auto-refresh
picks up current data:
```bash
python3 "{project_root}/dashboard_generator.py" --project-root "{project_root}"
```

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
checkpoint every 2 papers, ask to continue every 20. This prevents both
context exhaustion and runaway cost.

### 9e. Streaming progress & interruptible execution (§27)

Regenerate the dashboard every 2 papers. After each paper, append a line
to `state/live_progress.jsonl`:
```json
{"timestamp": "...", "paper": "Smith et al. 2003", "records": 3, "total_records": 1339, "queue_remaining": 22}
```

Between each paper in the main loop, check for user input signals:
- "skip" or "next" → skip current paper, mark `"outcome": "user_skipped"`
- "redo" or "redo last" → re-extract previous paper
- "pause" → stop after current paper without ending session
- "show trace" → display chain-of-thought trace for last record (§22)
- "consensus on last" → trigger consensus extraction for last paper (§21)

After each paper, print a one-line confidence trend:
```
📊 Confidence: 0.87 avg (↑ from 0.84) | 3 records | total: 1,339
```

See [advanced_features.md](references/advanced_features.md) §27.

### 9f. Adaptive tool statistics (§24)

After each PDF fetch attempt and each search query, update
`state/source_stats.json` with success/failure counts per source. At
session end, generate a tool effectiveness analysis showing best/worst
PDF sources and search sources with success rates.

See [advanced_features.md](references/advanced_features.md) §24.

### 9g. Reproducibility snapshots (§28)

At session start, save a reproducibility snapshot to
`state/snapshots/{session_id}.json` containing: guide.md hash, config
hashes, model ID, skill version, Python version, and dependency versions.

This enables `scripts/reproduce.py` to identify exactly what configuration
was used for each session and measure extraction drift over time.

See [advanced_features.md](references/advanced_features.md) §28.

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

**Dashboard update:** Every 2 papers processed, regenerate the dashboard
so that the browser auto-refresh picks up new data (see §13):
```bash
python3 "{project_root}/dashboard_generator.py" --project-root "{project_root}"
```

---

## 10b. Usage Tracking

Track model usage per session to enable cost estimation and cross-study
comparisons. **Tokens** are the universal unit of LLM compute — all
major providers (Anthropic, OpenAI, Google) use byte-pair encoding where
1 token ≈ 4 characters ≈ 0.75 English words. Token counts are comparable
(within ~5%) across providers even though dollar-per-token prices differ
by provider, model tier, and subscription type.

TraitTrawler tracks **token volumes by model tier** — the numbers that
are stable and comparable — rather than dollar amounts, which change
frequently. Users apply their own provider's published rates to estimate
cost.

### What to track

Maintain a running tally for the current session:

```python
usage = {
    "haiku_calls": 0,           # subagent calls at haiku tier
    "sonnet_calls": 0,          # subagent calls or direct work at sonnet tier
    "opus_calls": 0,            # escalation calls at opus tier
    "pages_processed": 0,       # total PDF pages read
    "records_written": 0,       # records added to results.csv
    "est_input_tokens": 0,      # estimated total input tokens (all tiers)
    "est_output_tokens": 0,     # estimated total output tokens (all tiers)
    "est_input_tokens_by_tier": {   # breakdown for cost estimation
        "haiku": 0,
        "sonnet": 0,
        "opus": 0
    },
    "est_output_tokens_by_tier": {
        "haiku": 0,
        "sonnet": 0,
        "opus": 0
    }
}
```

### Estimating tokens per call

The agent cannot measure exact token usage, but can estimate reliably
from document size. Use these conversion factors:

| Input type | Tokens per unit | How to measure |
|---|---|---|
| PDF page (text) | ~800 tokens/page | `pages_processed` from pdfplumber |
| PDF page (vision/scanned) | ~1,600 tokens/page | Higher due to image encoding |
| Abstract (text) | ~300 tokens | Fixed estimate |
| Search query batch | ~200 tokens | Fixed estimate |
| Guide.md + config context | ~2,000 tokens | Injected per extraction call |
| Agent output (triage) | ~100 tokens/paper | Classification + reasoning |
| Agent output (extraction) | ~500 tokens/paper | Records as structured data |

**After each call, estimate and accumulate tokens:**

- **Haiku search batch** (5–10 queries): ~200 input + ~3,000 output
- **Haiku triage batch** (15 abstracts): ~(300 × 15 + 2,000) = ~6,500
  input + ~1,500 output
- **Sonnet extraction** (1 paper): ~(800 × pages + 2,000) input +
  ~(500 × records_from_paper) output
- **Opus escalation** (1 paper): same formula as sonnet, different tier

### Session summary line

Add a usage block to the session summary (§11):

```
── Usage ──────────────────────────
 Model calls   : haiku ×{N}  sonnet ×{N}  opus ×{N}
 Pages read    : {N}
 Est. tokens   : {est_input_tokens:,} in / {est_output_tokens:,} out
 Records/call  : {records_written / (sonnet_calls + opus_calls):.1f}
 Tokens/record : {(est_input_tokens + est_output_tokens) / records_written:,.0f}
```

**Key efficiency metrics:**
- `Records/call` — how many validated records per extraction-tier call.
  Higher is better (table-heavy papers score high).
- `Tokens/record` — total tokens per validated record. Lower is better.
  This is the number most comparable across studies and providers.

### Logging

Append usage to the session-end entry in `state/run_log.jsonl`:

```json
{
  "event": "session_end",
  "usage": {
    "haiku_calls": 14,
    "sonnet_calls": 23,
    "opus_calls": 2,
    "pages_processed": 487,
    "records_written": 89,
    "est_input_tokens": 892000,
    "est_output_tokens": 156000,
    "est_input_tokens_by_tier": {"haiku": 112000, "sonnet": 740000, "opus": 40000},
    "est_output_tokens_by_tier": {"haiku": 36000, "sonnet": 108000, "opus": 12000}
  }
}
```

### Cumulative usage report

The dashboard generator reads `run_log.jsonl` session-end entries and
shows cumulative usage across all sessions:

```
── Cumulative Usage (all sessions) ──
 Total tokens  : {N:,} in / {N:,} out
   haiku       : {N:,} in / {N:,} out
   sonnet      : {N:,} in / {N:,} out
   opus        : {N:,} in / {N:,} out
 Total records : {N}
 Tokens/record : {N:,} (lifetime average)
```

### Why tokens, not dollars

Token counts are the stable, provider-neutral measure of compute. Dollar
costs change frequently (trending downward), vary across providers,
and depend on whether you are on API pricing (pay-per-token) or a
subscription plan (flat monthly fee, marginal cost ≈ $0). By logging
tokens, TraitTrawler's efficiency numbers remain valid and comparable
regardless of when, where, or how the agent is run. Anyone can multiply
tokens × their provider's current $/million-token rate to get a cost
estimate.

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
── Usage ──────────────────────────
 Model calls                   : haiku ×{N}  sonnet ×{N}  opus ×{N}
 Pages read                    : {N}
 Est. tokens                   : {N} in / {N} out
 Records / extraction call     : {N}
 Tokens / record               : {N}
══════════════════════════════════════
```

At session end, also:
1. Run `verify_session.py` and report any issues found.
2. Run `scripts/statistical_qc.py --project-root .` and print the QC summary
   (species sampled / Chao1 estimate, mean confidence, outliers, accumulation
   slope). See [statistical_qc.md](references/statistical_qc.md) §17e.
3. Run `scripts/calibration.py --project-root .` if calibration data exists.
   Print calibration summary (ECE, worst field). See
   [confidence_calibration.md](references/confidence_calibration.md) §19j.
4. Run `scripts/benchmark.py --project-root .` if benchmark data exists.
   Print benchmark summary (per-field F1, record-level precision/recall).
   See [benchmarking.md](references/benchmarking.md) §20e.
5. Run the domain knowledge review (§14) if discoveries were logged.
   See [knowledge_evolution.md](references/knowledge_evolution.md).
6. Print consensus extraction summary if consensus was triggered this session.
   See [consensus_extraction.md](references/consensus_extraction.md) §21d.
7. Print tool effectiveness analysis from source_stats.json.
   See [advanced_features.md](references/advanced_features.md) §24d.
8. Run cross-paper conflict detection:
   `python3 scripts/knowledge_graph_export.py --project-root . --format conflicts`
   See [advanced_features.md](references/advanced_features.md) §26a.
9. Regenerate the dashboard.
10. Check for misplaced PDFs: `python3 scripts/pdf_utils.py --project-root . --check`.
    If any found, report to user and offer to run `--fix`.
11. Check whether an audit is due: if `audit_config.auto_audit` is `true` and
    the session count (from `run_log.jsonl`) is a multiple of
    `audit_config.auto_audit_interval` (default: 5), offer:
    `🔍 Audit due — {N} records are candidates for re-examination. Run audit? [y/n]`
11. Check whether a campaign report is due: if session count is a multiple of
    `campaign_planning.auto_report_interval` (default: 5) and >= 3 sessions,
    offer: `📊 Campaign report available. Generate? [y/n]`
    See [campaign_planning.md](references/campaign_planning.md).

Append session-end entry to `state/run_log.jsonl`:
```json
{"timestamp": "2026-03-24T14:45:30Z", "session_id": "2026-03-24T14:30:00Z", "event": "session_end", "papers_processed": 23, "records_added": 89, "flagged_for_review": 2, "discoveries": 3, "usage": {"haiku_calls": 14, "sonnet_calls": 23, "opus_calls": 2, "pages_processed": 487, "records_written": 89, "est_input_tokens": 892000, "est_output_tokens": 156000, "est_input_tokens_by_tier": {"haiku": 112000, "sonnet": 740000, "opus": 40000}, "est_output_tokens_by_tier": {"haiku": 36000, "sonnet": 108000, "opus": 12000}}}
```

---

## 12. Error Handling

**Use `scripts/api_utils.py` for ALL external API calls.** The module
provides automatic retry with exponential backoff and per-API rate limiting:

```python
import sys
sys.path.insert(0, "scripts")
from api_utils import resilient_fetch, fetch_unpaywall, fetch_openalex_work, APIError

# Automatic retry (3 attempts, exponential backoff 1s→2s→4s)
try:
    data = resilient_fetch(
        f"https://api.openalex.org/works/doi:{doi}?mailto={email}",
        api_name="openalex",
        log_file="state/run_log.jsonl"
    )
except APIError as e:
    print(f"API failed after {e.attempts} attempts: {e}")
    # Fall through to next source

# Convenience wrappers with built-in rate limiting:
data = fetch_unpaywall(doi, email, log_file="state/run_log.jsonl")
data = fetch_openalex_work(doi, email, log_file="state/run_log.jsonl")
```

**Rate limits enforced per API** (see `api_utils.py` → `RATE_LIMITS`):

| API | Requests/sec | Notes |
|-----|-------------|-------|
| PubMed (with key) | 3/s | NCBI E-utilities policy |
| PubMed (no key) | 1/s | Throttled without api_key |
| OpenAlex (polite) | 10/s | With mailto parameter |
| Crossref (polite) | 50/s | With mailto parameter |
| GBIF | 3/s | Empirically safe |
| Unpaywall | 1/s | Rate-limited by email param |
| Europe PMC | 3/s | Conservative estimate |
| Semantic Scholar | 1/s | Without API key |
| CORE | 1/s | Conservative estimate |

**Error handling rules:**
- **Rate limits (429)**: automatic retry with exponential backoff + Retry-After header
- **Server errors (500-504)**: automatic retry up to 3 attempts
- **PDF download timeout**: skip after 60s; note URL for retry next session
- **Malformed state file JSON**: `state_utils.py` auto-recovers from `.bak` backup
- **results.csv write failure**: `csv_writer.py` raises RuntimeError — stop immediately
- **Chrome navigation fails**: mark `pdf_source: browser_failed`, fall through to abstract
- **Proxy returns wrong content-type**: don't save as PDF; log and continue

---

## 13. Dashboard

The skill includes a self-contained HTML dashboard that visualizes collection
progress and summary statistics. It lives at `{project_root}/dashboard.html`.

### Dashboard

The dashboard is a **self-contained HTML file** (`dashboard.html`) with pure
CSS/SVG charts. No CDN, no external dependencies. Users open it by
double-clicking the file — works on `file://` protocol. It auto-refreshes
every 60 seconds.

Features:
- KPI cards (records, species, families, papers, leads, mean confidence, flagged)
- Activity panel (last 5 papers processed, queue remaining)
- Charts: cumulative timeline, family breakdown, confidence distribution, source type
- Auto-detected trait-specific charts
- Interactive column picker (persists selections via localStorage)
- Sortable data table (last 200 records)

### When to regenerate

1. **Session start** (§1e) — after reading state files
2. **Every 2 papers processed** — alongside the rolling progress update (§10)
3. **Session end** (§11) — as part of the session summary

```bash
python3 dashboard_generator.py --project-root .
```

Tell the user: **"Dashboard updated — refresh dashboard.html."**

### Live dashboard server (optional)

The `scripts/dashboard_server.py` SSE server is available but **not started
by default**. Only start it if the user explicitly requests a live server:
```bash
python3 scripts/dashboard_server.py --project-root . --port 8347 &
```

### Command input (live dashboard only)

The live dashboard has a command input at the bottom. When the user types
a command and hits Send, it writes to `state/user_commands.txt`. The agent
checks this file between papers (see §9e):

```python
import os
cmd_path = os.path.join(project_root, "state", "user_commands.txt")
if os.path.exists(cmd_path):
    with open(cmd_path) as f:
        lines = f.readlines()
    if lines:
        last_cmd = lines[-1].strip().split(" ", 1)[-1]  # strip timestamp
        # Process command: skip, pause, redo, show trace, run QC, stop, etc.
        # After processing, truncate the file:
        open(cmd_path, "w").close()
```

Supported commands: `skip`, `pause`, `redo last`, `show trace`,
`run QC`, `consensus on last`, `stop`.

### What the static dashboard shows

**KPI cards** (top row): Total records, unique species, papers processed,
leads (need full text), flagged for review.

**Search progress bar**: queries completed vs. total from `config.py`

**Charts** (auto-generated based on available data): cumulative records over
time, records by taxonomic group (top 20), records by publication year,
full-text source breakdown, extraction confidence distribution, records by
country (top 15), lead failure reasons, lead status breakdown, and
additional trait-specific charts if recognized fields are present.

### Stopping the live server

At session end, stop the server:
```bash
pkill -f "dashboard_server.py" 2>/dev/null
```

Or leave it running — it's lightweight and the user can keep monitoring
between sessions.
