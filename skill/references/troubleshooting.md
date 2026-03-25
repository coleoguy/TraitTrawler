# Troubleshooting

Common failure modes and recovery strategies. The agent handles most of
these automatically, but this reference helps when diagnosing issues or
when the user reports unexpected behavior.

---

## PDF retrieval failures

### Proxy returns login page instead of PDF

**Symptom:** Browser navigates to proxy URL but lands on an SSO/login page.
Records show `pdf_source: browser_failed` for paywalled papers.

**Fix:** Open Chrome manually and log into your institution's library portal.
The agent uses your active browser session — it cannot authenticate for you.
After logging in, tell the agent to continue. It will retry proxy fetches.

### Unpaywall / OpenAlex return no PDF URL

**Symptom:** Papers with valid DOIs show `pdf_source: abstract_only` even
though they should be open access.

**Cause:** OA metadata lags behind publisher release. Some papers take weeks
to appear in Unpaywall's database after publication.

**Fix:** Drop the PDF into `pdfs/` manually and run another session. The
agent detects unprocessed local PDFs automatically.

### PDF download times out

**Symptom:** Agent reports timeout after 60 seconds on a specific paper.

**Cause:** Publisher CDN is slow or blocking automated downloads.

**Fix:** The agent logs the URL and moves on. The paper appears in
`leads.csv`. Obtain the PDF manually and place in `pdfs/`.

### Scanned PDF returns empty text

**Symptom:** pdfplumber extracts zero characters from a valid PDF.

**Cause:** The PDF contains page images, not embedded text (common for
older publications scanned from print).

**Fix:** Controlled by `vision_extraction` in `collector_config.yaml`:
- `ask` (default): agent asks before using vision extraction per document
- `always`: automatically use Claude's native PDF reading (slower but works)
- `never`: skip scanned PDFs entirely, log to leads.csv

---

## API rate limits

### PubMed 429 (Too Many Requests)

**Symptom:** PubMed searches fail with HTTP 429 or "API rate limit exceeded."

**Cause:** NCBI E-utilities allow 3 requests/second without an API key,
10/second with one. The agent backs off 30 seconds and retries once.

**Fix:** If persistent, add your NCBI API key to `collector_config.yaml`:
```yaml
ncbi_api_key: "your_key_here"
```
Request a free key at https://www.ncbi.nlm.nih.gov/account/settings/

### OpenAlex rate limiting

**Symptom:** OpenAlex returns 429 or empty results intermittently.

**Cause:** OpenAlex's polite pool allows higher throughput when you provide
a `mailto` parameter. The agent uses `contact_email` from your config.

**Fix:** Ensure `contact_email` is set to a valid institutional email.
OpenAlex deprioritizes requests without a `mailto` parameter.

### Crossref rate limiting

**Symptom:** Crossref API calls fail intermittently.

**Fix:** Same as OpenAlex — the `contact_email` field enables polite-pool
access. Crossref also respects the `mailto` parameter.

---

## State file issues

### Corrupted JSON in state files

**Symptom:** Agent reports "Malformed state file JSON" at startup.

**Cause:** A previous session crashed mid-write (power loss, forced quit).

**Fix:** The agent warns you and shows the raw content. Options:
1. If the file is mostly intact, fix the JSON manually (usually a truncated
   closing brace).
2. If unrecoverable, delete the file. The agent recreates it:
   - `processed.json` → loses dedup history (may re-process some papers)
   - `queue.json` → loses pending queue (agent rebuilds from search)
   - `search_log.json` → loses query progress (may re-run some queries)
   - `run_log.jsonl` → loses session history (non-critical)

### results.csv write failure

**Symptom:** Agent stops with "results.csv write failure" error.

**Cause:** File is locked by another process (Excel, another editor) or
disk is full.

**Fix:** Close any programs that have results.csv open. Check disk space.
The agent stops immediately on write failure to prevent data loss — no
records are silently dropped.

---

## Dashboard issues

### Dashboard shows no charts

**Symptom:** dashboard.html opens but shows empty chart areas.

**Cause:** results.csv is empty or has only a header row.

**Fix:** Run at least one collection session. The dashboard needs data
to generate charts.

### Dashboard doesn't auto-refresh

**Symptom:** Charts don't update while the agent is running.

**Cause:** Browser security may block auto-refresh for local files.

**Fix:** Manually refresh the page, or open it via a local HTTP server:
```bash
python3 -m http.server 8080
# Then open http://localhost:8080/dashboard.html
```

---

## Extraction quality issues

### Many records flagged for review

**Symptom:** High proportion of records have `flag_for_review = True`.

**Possible causes:**
1. `guide.md` lacks specificity for this trait's notation conventions.
   Solution: review flagged records, identify patterns, update guide.md.
2. Papers are in a language the agent handles less reliably.
   Solution: add language-specific notation examples to guide.md.
3. The trait is inherently ambiguous in how it's reported.
   Solution: add worked examples to `extraction_examples.md`.

### Low extraction confidence across the board

**Symptom:** Mean confidence is below 0.7 for a session.

**Fix:** Run calibration (§0b) if you haven't already. The calibration
phase processes seed papers and builds `extraction_examples.md`, which
substantially improves subsequent extraction quality.

### Table extraction misses rows

**Symptom:** Two-pass table extraction reports fewer records than visible
rows in the original table.

**Cause:** Complex table layouts (merged cells, multi-line rows, footnote
symbols) can cause the enumeration pass to undercount.

**Fix:** The agent automatically escalates to opus when row-count mismatch
exceeds 10%. If the problem persists, obtain the PDF and process it in
PDF-first mode, which lets you review extraction interactively.

---

## MCP / dependency issues

### "PubMed MCP not available" warning

**Symptom:** Agent reports MCP unavailable at startup and falls back to
E-utilities API.

**Cause:** The PubMed MCP server is not installed or not connected.

**Fix:** This is non-critical — the agent works fine with the API fallback.
If you want MCP access, install the PubMed MCP in Cowork settings.

### pdfplumber install fails

**Symptom:** `pip install pdfplumber` fails at session start.

**Cause:** Network restrictions or pip configuration issues in the
Cowork environment.

**Fix:** Non-critical. The agent falls back to the Read tool for PDF
text extraction. Vision extraction for scanned PDFs still works.

### pyyaml install fails

**Symptom:** `pip install pyyaml` fails at session start.

**Cause:** Same as above.

**Fix:** Non-critical. The agent falls back to regex-based YAML parsing,
which handles the standard collector_config.yaml format.

---

## Performance issues

### Sessions running slowly

**Symptom:** Agent processes fewer than 3 papers per hour.

**Possible causes:**
1. Most papers require proxy retrieval (browser navigation is slow).
   Solution: focus on open-access queries first; use `pdf_source` stats
   in the dashboard to see the retrieval mix.
2. Papers are very large (100+ pages).
   Solution: expected — large PDFs process in 50-page batches across
   sessions. Check `state/large_pdf_progress.json` for active batches.
3. Many model escalations to opus.
   Solution: review `state/run_log.jsonl` for escalation events. If the
   trait is consistently triggering escalation, the guide.md may need
   more detailed rules to help sonnet handle it directly.

### Context window exhaustion

**Symptom:** Agent loses track of pipeline state, skips papers, or stops
unexpectedly mid-session.

**Cause:** Long sessions accumulate context. The agent's context management
(§9b-2) mitigates this but very long sessions (50+ papers) can still hit
limits.

**Fix:** Use shorter sessions (20-30 papers). The checkpoint system
(§9b-2) ensures perfect resumption across sessions. If this happens
mid-session, restart — the agent picks up from the last checkpoint.
