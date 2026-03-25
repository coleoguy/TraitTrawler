---
name: deepscholar
description: >
  Autonomous deep literature review agent. Invoke this skill when the user wants
  to build a comprehensive literature review on any scientific topic, collect and
  synthesize papers, find knowledge gaps, track hypotheses, mine untested ideas
  from Discussion sections, or query an existing knowledge base. Triggers on
  phrases like "literature review", "survey the literature", "what's known about",
  "find papers on", "run deepscholar", "review the literature", "collect papers",
  "what are the open questions", "untested hypotheses", or any request to
  systematically read and synthesize scientific literature. Also triggers when
  the user wants to query an existing review ("what do we know about X", "what are
  the gaps", "draft an introduction") or improve extraction quality ("recheck
  papers", "improve extractions", "qc mode", "re-extract low confidence papers",
  "retry abstract-only papers"). The skill picks up exactly where the previous
  session ended. Supports three modes: COLLECT (find and read papers), QC (review
  and re-extract poor-quality items), and QUERY (answer questions from the
  knowledge base).
argument-hint: "[collect | qc | <question about the literature>]"
model: claude-opus-4-6
effort: high
allowed-tools: Read, Write, Edit, Bash(python *), Bash(python3 *), WebFetch, Agent
compatibility: >
  Requires PubMed MCP, bioRxiv MCP, OpenAlex MCP (scholarly-apis plugin).
  Chrome MCP optional for institutional proxy access.
metadata:
  version: "2.0.0"
  changelog: "v2.0 — added QC mode, mode dispatch via $ARGUMENTS, extraction_quality_score tracking"
---

# DeepScholar

An autonomous literature review agent that builds a persistent, structured
knowledge base from scientific papers. It extracts claims, hypotheses, methods,
untested ideas, contradictions, and gaps — then synthesizes them into queryable
narratives that improve with every session.

**Three operating modes** share the same project folder and state files:
- **COLLECT** — run the pipeline, discover and read new papers
- **QC** — surface and re-extract low-quality or stale items
- **QUERY** — answer questions directly from the knowledge base

**Project root**: read from `review_config.yaml` → `project_root`.
All paths below are relative to that root.

---

## Mode Dispatch

Check `$ARGUMENTS` before anything else to skip the menu when the user is direct:

| `$ARGUMENTS` value | Action |
|---|---|
| empty | Run startup, then show mode menu (§2) |
| `collect` | Run startup, go directly to COLLECT (§3) |
| `qc` | Run startup, go directly to QC (§4) |
| any other text | Run startup, treat as a query → QUERY mode (§5) |

---

## 0. First-Run Detection

Check whether `review_config.yaml` exists in the current working directory or
any parent/mounted folder.

**If it does NOT exist → run setup wizard:**

Use AskUserQuestion for the first question, then follow up conversationally:

1. "What topic do you want to review? (1-3 sentences describing scope)"
2. "What are your 2-5 core research questions this review should answer?"
3. "What taxa or systems are in scope?"
4. "What keywords should I start with? I'll generate more."
5. "Any domain-specific gotchas, key debates, or terminology traps I should know?"
6. "Where should I create the project folder?"
7. "Your contact email? (for API polite-pool access)"
8. "Institution for library access?" — TAMU proxy: `http://proxy.library.tamu.edu/login?url=`

Then create:
- `review_config.yaml` using `${CLAUDE_SKILL_DIR}/references/config_template.yaml`
- `state/` folder: `processed.json` ({}), `queue.json` ([]), `search_log.json` ([]),
  `citation_queue.json` ([]), `synthesis_log.json` ([])
- `knowledge/` folder: `papers.json` ({}), `claims.json` ([]), `hypotheses.json` ([]),
  `untested_ideas.json` ([]), `methods.json` ([]), `gaps.json` ([]),
  `contradictions.json` ([])
- `synthesis/` folder (empty — populated after first batch)
- `leads.csv` and `needs_attention.csv` with header rows
- `pdfs/` folder
- `guide.md` with the domain knowledge the user provided (note to user: edit to expand)
- `search_terms.py` — 50-200 systematic queries based on topic, research questions,
  and keywords. Use systematic variations: keyword combinations, taxon-specific terms,
  method-specific terms, key author names if known.

**If `review_config.yaml` exists → proceed to §1.**

---

## 1. Startup

Read these files in order before doing anything else:

1. `review_config.yaml` — topic, RQs, scope, proxy, email, QC settings
2. `search_terms.py`
3. `guide.md` — inject into all triage and extraction
4. `state/processed.json` — DOIs already handled
5. `state/queue.json` — papers fetched but not yet read
6. `state/search_log.json` — queries already run
7. `state/citation_queue.json` — references flagged for follow-up
8. `state/synthesis_log.json` — when syntheses last ran
9. `leads.csv` — count by status
10. Count records in `knowledge/claims.json`, `hypotheses.json`,
    `untested_ideas.json`, `gaps.json`, `contradictions.json`
11. Compute QC candidate counts from `knowledge/papers.json` (see §4a)

### 1b. Connectivity check

Run in parallel:
- **Chrome + Proxy**: call `mcp__Claude_in_Chrome__tabs_context_mcp`
  (createIfEmpty: true); if available, navigate to a known OA paper via proxy.
- **APIs**: test OpenAlex MCP via WebFetch and PubMed MCP.

Print the startup dashboard:

```
═══════════════════════════════════════════════════════════
 {project_name} — DeepScholar v2.0
═══════════════════════════════════════════════════════════
 Papers processed     : 147     | QC candidates : 12
 Claims extracted     : 892     |   abstract-only: 5
 Hypotheses tracked   : 23      |   low-confidence: 7
 Untested ideas       : 56      |   stale (>90d) : 3
 Gaps identified      : 31 (8 high priority)
 Contradictions       : 9 (5 unresolved)
 Queries run          : 45 / 200
 Citation queue       : 34 papers
 Last synthesis       : 12 papers ago
───────────────────────────────────────────────────────────
 Connectivity:
   PubMed API     : ✅      OpenAlex API : ✅
   TAMU Proxy     : ✅ authenticated
   Chrome browser : ✅
═══════════════════════════════════════════════════════════
```

---

## 2. Mode Selection

If `$ARGUMENTS` did not specify a mode, use AskUserQuestion to present the menu:

```
What would you like to do?
  [c] COLLECT  — continue the pipeline, read new papers
  [q] QC       — review and improve extraction quality (12 candidates)
  [ask]        — type a question about the knowledge base
  [s]          — save and end session
```

This same menu is offered at every 25-paper batch checkpoint, making it easy to
pivot between modes mid-session without losing any work.

---

## 3. COLLECT Mode — Multi-Agent Pipeline

### Agent roles

| Role | Model | Does |
|---|---|---|
| **Orchestrator** (you) | opus | Coordinates everything, writes knowledge base |
| **Scout** | sonnet | Searches APIs, triages, appends leads.csv |
| **Reader** (×3-5 parallel) | sonnet | Reads papers, extracts knowledge atoms |
| **Synthesizer** | opus | Cross-paper synthesis every 25 papers |

### Pipeline flow

```
Scout (sonnet)         Orchestrator (opus)            Readers (sonnet ×3-5)
──────────────         ──────────────────             ────────────────────
Search APIs
Triage abstracts
Append leads.csv  →    Claim new leads
                       Fetch full text
                       Launch Readers ─────────────→  Extract knowledge atoms
                       Collect results  ←───────────  Return JSON
                       Validate + store
                       Every 25 papers ──────────────────────→  Synthesizer (opus)
                                                                 Cross-paper analysis
                                                                 Update gaps/contradictions
                                                                 Write synthesis/ narratives
                       Report + mode menu  ←──────────────────
                       Loop ↑
```

### 3a. Orchestrator loop

Repeat until the user stops or all search queries are exhausted:

1. **Fill the pipeline** — if leads.csv has fewer than 10 `status=new` rows,
   launch a Scout. Read `${CLAUDE_SKILL_DIR}/references/scout_prompt.md` for the
   template. Pass `citation_queue.json` entries to the Scout for processing too.

2. **Claim a batch** — select 3-5 leads with `status=new`. Set `status=in_progress`.

3. **Fetch full text** — for each lead, run the fetch cascade (§6).

4. **Launch Readers in parallel** — send ALL Reader subagents in a single message
   (parallel, not sequential — sequential runs lose the speedup). Read
   `${CLAUDE_SKILL_DIR}/references/reader_prompt.md` for the template. Each Reader
   gets: paper text + guide.md domain knowledge + claim schema.

5. **Collect and store** — as Reader results arrive:
   - Parse JSON: claims, hypotheses, untested_ideas, methods, key_references
   - Assign IDs: c_NNNNN, h_NNNNN, u_NNNNN, m_NNNNN
   - Append to the appropriate `knowledge/` JSON files using atomic writes (§9)
   - Add key_references to `state/citation_queue.json`
   - Update leads.csv status → `extracted`; update `state/processed.json`
   - Calculate `extraction_quality_score` = mean extraction_confidence across all
     claims for this paper; store in `knowledge/papers.json`
   - Papers with `read_depth: abstract_only` are automatically QC Category A candidates

6. **Check synthesis trigger** — if 25+ papers since last synthesis, launch
   Synthesizer subagent. Read `${CLAUDE_SKILL_DIR}/references/synthesizer_prompt.md`.

7. **Report** — print rolling update after every batch (§10).

8. **Batch checkpoint** — every 25 papers, print session stats and offer the mode
   menu (§2). State is fully written before this prompt, so no work is lost
   regardless of which option the user picks.

9. **Repeat** from step 1.

---

## 4. QC Mode — Quality Review and Re-extraction

The knowledge base improves over time as guide.md matures and full text becomes
accessible for papers that were originally abstract-only. QC mode surfaces papers
worth re-extracting and runs fresh Reader passes against them.

### 4a. QC Audit

Scan `knowledge/papers.json` and categorize candidates. Also compute these counts
during startup (§1 step 11) so the dashboard always shows current QC load.

**Category A — abstract-only**: `read_depth == "abstract_only"`. Highest-value
targets — full-text extraction typically yields 3-5× more claims. Re-try the
fetch cascade before re-running the Reader.

**Category B — low-confidence**: `extraction_quality_score < qc_settings.low_confidence_threshold`
(default 0.65) OR `n_claims == 0` despite `read_depth == "full_text"`. A
well-extracted 10-page empirical paper typically yields 5-15 claims; fewer suggests
the Reader missed content — often because guide.md lacked calibration at the time.

**Category C — stale**: `date_processed` more than `qc_settings.stale_days` (default 90)
days ago AND `extraction_quality_score < 0.80`. Earlier sessions had a less-refined
guide.md; re-extraction with the current guide often recovers missed untested ideas
and hypotheses.

Report to the user before doing any work:

```
QC Audit Results
───────────────────────────────────────────────────────────
 Category A (abstract-only)   :  5 papers — high value, retry fetch first
 Category B (low-confidence)  :  7 papers — avg score 0.48
 Category C (stale >90d)      :  3 papers — processed before current guide.md
 Total candidates              : 15 papers
───────────────────────────────────────────────────────────
Process: [all] [A only] [B only] [C only] [N papers] [cancel]
```

Use AskUserQuestion for this choice.

### 4b. Re-extraction loop

For each selected paper:

1. **Re-fetch** (always for Category A; worthwhile for any paper where
   `read_depth != "full_text"`): run the full fetch cascade (§6). Update
   `read_depth` in papers.json if full text is now available.

2. **Re-run Reader**: launch a Reader subagent with the current `guide.md` and
   claim schema. Use `${CLAUDE_SKILL_DIR}/references/reader_prompt.md`.

3. **Merge results** — compare new Reader output to existing extractions:
   - New claims not semantically duplicated in claims.json → append with new IDs
   - New untested ideas, hypotheses, key references → append normally
   - Do not delete old claims. Deleting would break claim ID references in
     synthesis narratives; the Synthesizer reconciles overlaps in its next pass.

4. **Update the papers.json record**: set `date_processed` to today, update
   `extraction_quality_score`, `n_claims`, `read_depth`, `n_untested_ideas`,
   and `last_reextraction` to today's date.

5. **Report per paper**:

```
🔧 QC [3/15] "Smith 2021 — Sex chromosomes in Coleoptera"
   abstract-only → full_text retrieved
   +4 new claims | +1 untested idea | confidence: 0.45 → 0.89
```

### 4c. Post-QC synthesis

If QC processed 10 or more papers, offer a Synthesizer pass. New claims from
re-extraction can create new contradictions, upgrade hypothesis statuses, or
fill gaps that previously appeared empty — synthesis consolidates these gains.

After QC completes, return to the mode menu (§2).

---

## 5. QUERY Mode — Knowledge Base Queries

When the user asks about the knowledge base rather than running the pipeline,
load only the relevant subset of files — loading everything wastes context and
slows responses.

| User asks | Load |
|---|---|
| "What do we know about X?" | relevant `synthesis/` narrative + matching claims |
| "What are the untested ideas?" | `untested_ideas.json`, ranked by feasibility |
| "Where does the literature disagree?" | `contradictions.json` |
| "What gaps could I fill?" | `gaps.json` + `methods.json` |
| "Draft an introduction" | `synthesis/` narratives + top claims for cited prose |
| "What are the open questions?" | `synthesis/open_questions.md` |

Answer from the knowledge base with citations (first_author + year). If coverage
is thin on the question, say so and suggest COLLECT mode search targets.

After answering, offer to return to the mode menu.

---

## 6. Full-Text Fetch Cascade

Try sources in order, stop when you have usable text. If all sources fail,
mark `needs_attention.csv` and continue — stalling on one paper kills pipeline
momentum for the entire batch.

**6a. Local cache** — check `pdfs/` first.

**6b. Open-access sources:**
1. OpenAlex MCP: `get_work(identifier="{doi}")` → check pdf_url, oa_url
2. Crossref MCP: `get_work_by_doi(doi="{doi}")` → check pdf_link
3. Europe PMC via WebFetch: fullTextXML endpoint (no PDF needed)
4. Unpaywall: `api.unpaywall.org/v2/{doi}?email={email}`
5. Semantic Scholar via WebFetch: openAccessPdf field

**6c. Institution proxy via Chrome:**
Navigate `{proxy_url}https://doi.org/{doi}` → use `get_page_text`. If a login
page appears, set `proxy_authenticated=false` for this session and skip Chrome
for remaining papers. Report this once, not per paper.

**6d. Abstract fallback:**
Use the abstract. Set `read_depth: abstract_only` and `extraction_quality_score ≤ 0.5`.
Still extract — abstracts contain real claims. The paper is automatically flagged
as a QC Category A candidate for the next session.

---

## 7. Search

The Scout handles search in COLLECT mode.
Read `${CLAUDE_SKILL_DIR}/references/scout_prompt.md` for the full template.

Sources: PubMed (primary), bioRxiv/medRxiv (secondary), OpenAlex (tertiary),
Crossref (older literature). Deduplicate against `processed.json` by DOI, falling
back to normalized title. Log every query to `state/search_log.json`.

---

## 8. Triage

Classify papers using `triage_rules` from `review_config.yaml` plus `guide.md`:

- **likely**: clearly addresses one or more research questions
- **uncertain**: abstract absent or ambiguous, or tangentially related —
  err toward uncertain because missed relevant papers are a permanent knowledge loss
- **unlikely**: clearly irrelevant

Move likely + uncertain to the fetch cascade. Mark unlikely as processed.

---

## 9. Knowledge Base Writes

Atomic JSON writes prevent session crashes from corrupting state files. A
half-written JSON file breaks all subsequent reads:

```python
import json, os

def atomic_json_write(path, data):
    """Write to .tmp then rename — crash-safe on all POSIX systems."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.rename(tmp, path)

# Standard pattern: load existing, extend, write back
claims = json.load(open("knowledge/claims.json"))
claims.extend(new_claims)
atomic_json_write("knowledge/claims.json", claims)
```

A write failure should stop execution — silently dropping knowledge atoms
corrupts the knowledge base in ways that are hard to detect later.

Write after every paper, not after every batch. Sessions end unexpectedly, and
any work not persisted before an abrupt end is gone.

---

## 10. Progress Reporting

After every batch of 3-5 papers:

```
📄 [23/40 queued] "Blackmon & Demuth 2015 — Coleoptera sex chromosome evolution"
   → 12 claims | 2 hypotheses | 1 untested idea | 3 refs queued | score: 0.87
   → Session: +67 claims | Knowledge base: 959 total
```

After every 25 papers (synthesis trigger + mode checkpoint):

```
🔬 Synthesis triggered (25 papers since last)
   → 2 new contradictions found
   → 1 hypothesis upgraded: untested → supported
   → 4 new untested ideas ranked
   → 3 new gaps identified
   → Updated: synthesis/rq_01_fixation_prob.md

 What next?
   [c] Continue collecting (next 25)
   [q] Switch to QC mode — 12 candidates identified
   [ask] Ask something about the knowledge base
   [s] Save and end session
```

---

## 11. Session End

```
══════════════════════════════════════════════════════
 Session Complete
══════════════════════════════════════════════════════
 Mode(s) used              : COLLECT → QC
 Papers collected          : 27 new | 8 re-extracted
 Claims added              : 134 new | 23 updated
 Hypotheses tracked        : 5 new (28 total)
 Untested ideas            : 8 new (64 total)
 Gaps identified           : 3 new (34 total)
 Contradictions            : 1 new (10 total)
 Via proxy / open access   : 9 / 13
 Abstract-only this session : 5 (queued as QC Category A)
 Citation queue            : 42 papers
 Queries remaining         : 155 / 200
 QC candidates remaining   : 7
══════════════════════════════════════════════════════
 Next session:  /deepscholar collect
                /deepscholar qc   (7 candidates waiting)
══════════════════════════════════════════════════════
```

---

## 12. Error Handling

The pipeline never stops because a single paper fails. Each error type has a
specific response that keeps the rest of the batch moving:

| Error | Response |
|---|---|
| Rate limit (429) | Back off 30s, retry once, skip source, continue |
| Network / fetch failure | Try next source in cascade; log to needs_attention |
| Malformed input item | Mark needs_attention, continue with next paper |
| State write failure | Stop — never silently drop knowledge atoms |
| Subagent failure | Mark paper needs_attention, continue with batch |
| Auth expired | Set session flag, skip auth-dependent steps, report once |

---

## Reference Files

Load on demand — do not read all at startup:

- `${CLAUDE_SKILL_DIR}/references/config_template.yaml` — project config template.
  Load during the setup wizard (§0).
- `${CLAUDE_SKILL_DIR}/references/claim_schema.md` — JSON schemas for all knowledge
  atom types including the papers registry. Load when briefing Reader subagents.
- `${CLAUDE_SKILL_DIR}/references/scout_prompt.md` — Scout subagent prompt template.
  Load when launching a Scout (§3a step 1).
- `${CLAUDE_SKILL_DIR}/references/reader_prompt.md` — Reader subagent prompt template.
  Load when launching Readers (§3a step 4 and §4b step 2).
- `${CLAUDE_SKILL_DIR}/references/synthesizer_prompt.md` — Synthesizer subagent
  prompt template. Load every 25 papers (§3a step 6) and after large QC runs (§4c).
