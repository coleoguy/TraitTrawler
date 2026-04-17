# TraitTrawler v6 Architecture

This document is the authoritative explanation of how v6 works. Read it
before proposing changes to any other file. The Manager reads it on
demand, not on every turn.

## One-sentence summary

TraitTrawler v6 is a trait-agnostic literature-mining pipeline where the
LLM Manager orchestrates specialist subagents, but every bit of data
written to the final CSV has already passed a deterministic Python gate
that verifies a verbatim quote appears on the cited page of a SHA256-
identified PDF.

## Design goals, in priority order

1. **Accuracy over coverage.** A dropped record is cheap; a silently-
   wrong record is expensive. Every design decision reflects this.
2. **Grounding as invariant, not field.** A row without a verified
   verbatim quote on a hashed PDF cannot exist.
3. **Trait and clade agnostic.** No domain knowledge is hardcoded. The
   `trait_profile.md` learned at project start is the only domain
   input downstream agents receive.
4. **User approves the schema.** The user is never surprised by a
   column showing up in their CSV.
5. **Main-context discipline.** The Manager delegates to subagents so
   it can run long sessions without context compaction mangling the
   orchestration state.
6. **Talkative autonomy.** The user always knows where the pipeline is
   and what it just decided. Autonomous runs between narrated pause
   points.
7. **Generalizable.** The same architecture works for any scientific
   extraction task. This is the reference implementation for "AI
   does the whole scientific process."

## The 8 phases

```
0. SETUP         → project_init collects trait, taxa, seed DOIs, optional curated data
0.5. BOOTSTRAP   → (optional) bootstrap subagent ingests curated CSV + paired PDFs
1. LEARN         → trait_learner reads seeds + bootstrap rows; writes trait_profile.md AND proposed hooks
2. SCHEMA+HOOKS  → propose_columns generates schema; user approves schema AND each proposed hook
3. SEARCH        → searcher queries all four APIs
4. FETCH         → fetcher downloads PDFs, manifest.sqlite records hashes
5. PROCESS       → batch loop: triage → extract → verify → structure → hook → adjudicate
6. REVIEW        → user resolves review-queue items
7. REPORT        → session_report summarizes coverage & accuracy
```

## The batch loop (phase 5)

The Manager issues a single assistant message with N parallel Task
calls (one per paper in the batch). Each extractor subagent runs this
chain inside its own turn:

```
                  Paper in pdfs/ (sha256 known)
                            │
                            ▼
                    [triage subagent]
                            │
                            ▼
               relevant? ──no──> log + skip
                            │
                           yes
                            ▼
               [extractor: read pages_of_interest]
                            │
                            ▼
                    Claims JSON (one per value)
                    each carries: species_hint,
                    trait_fields, verbatim_quote,
                    page, preceding/following 10w
                            │
                            ▼
               [verify_quote.py] ← DETERMINISTIC
                    drop any claim whose quote is
                    not a substring of the PDF page
                            │
                            ▼
                [semantic_verifier subagent]
                    reads ONLY the quote + context
                    verdict: pass | fail | adjust
                            │
                            ▼
                  [structurer subagent]
                    claims → schema-valid rows
                            │
                            ▼
                     [hooks.py] ← DETERMINISTIC
                    6+ validators: range, arithmetic,
                    regex, dedup, gbif, cited-in-quote
                            │
                            ▼
                  pass? ──yes──> write results.csv + ledger.jsonl
                            │
                           no
                            ▼
                    state/disputes.jsonl
                            │
                            ▼
                   [adjudicator subagent]
                    Opus xhigh, ~5% of rows
                    accept | amend | reject
                            │
                            ▼
                    final write: results.csv or
                    legacy_rejected.csv + ledger
```

## The ledger

`state/ledger.jsonl` is the publishable audit artifact. Every row in
`results.csv` has exactly one ledger entry with the same `ledger_id`.
A ledger entry captures everything needed to reproduce or contest the
row:

```json
{
  "ledger_id": "uuid",
  "row_hash": "sha256-of-canonical-row-json",
  "sha256": "sha256-of-pdf",
  "pdf_path": "pdfs/xyz.pdf",
  "page": 4,
  "verbatim_quote": "...",
  "quote_preceding_10w": "...",
  "quote_following_10w": "...",
  "claim_id": "uuid",
  "extractor_model": "claude-opus-4-7-20260416",
  "semantic_verifier_model": "claude-sonnet-4-6-20260401",
  "adjudicator_model": null,
  "skill_version": "6.0.0",
  "trait_profile_hash": "md5-of-trait-profile-md",
  "schema_hash": "md5-of-schema-json",
  "session_id": "...",
  "timestamp_utc": "2026-04-16T...",
  "uncertainty": {"value_clarity": 0.95, ...},
  "hook_results": [{"hook": "hook_2n_range", "verdict": "pass"}, ...],
  "adjudication": null | {"verdict": "...", "reasoning": "..."}
}
```

Anything upstream of the ledger can be reconstructed from the ledger
plus the PDF plus the schema. That is the reproducibility guarantee.

## Model lineup (2026-04-16)

| Stage | Model | Thinking | Cost per Mtok | Why |
|---|---|---|---|---|
| project_init, bootstrap | Sonnet 4.6 | default | $3/$15 | Lightweight setup. |
| trait_learner | Sonnet 4.6 | adaptive, `effort: high` | $3/$15 | Careful synthesis of seeds + bootstrap. |
| searcher | Haiku 4.5 | default | $1/$5 | Cached system prompt; cheap at scale. |
| fetcher | Haiku 4.5 | default | $1/$5 | URL cascade logic. |
| triage | Haiku 4.5 | default | $1/$5 | Relevance gate for ~60% early-exit. |
| extractor | **Opus 4.7** | adaptive, `effort: xhigh` | $15/$75 | Careful reading + vision @ 2576px. |
| semantic_verifier | Sonnet 4.6 | adaptive, `effort: high` | $3/$15 | Escalates to advisor on uncertainty. |
| advisor (optional) | Opus 4.7 | adaptive, `effort: xhigh` | $15/$75 | Called by semantic_verifier when uncertain. |
| structurer | Sonnet 4.6 | default | $3/$15 | Schema conversion. |
| adjudicator | Opus 4.7 | adaptive, `effort: xhigh` | $15/$75 | Disputes only (~5% of rows). |

## Opus 4.7 considerations

**Vision.** 4.7's max image resolution jumped 1568px → 2576px. CharXiv
Reasoning no-tools went from 69.1% → 82.1%. For table- and figure-
heavy trait papers, the `extractor` should render triage-flagged pages
via `scripts/pdf_render.py` at 2576px and pass image + text to the
extractor. Prose-dominant pages stay text-only to save tokens.

**Adaptive thinking.** Manual `budget_tokens` is a 400 error on 4.7.
Use `thinking: adaptive` + `effort: high|xhigh|max`. Start extraction
at `xhigh`; only drop to `high` if latency gates the pipeline. `max`
has documented "overthinking" risk; do not use as default.

**Strip scaffolding.** 4.7 follows instructions more literally than
4.6. Do NOT add "double-check", "verify carefully", or "think through
this step by step" boilerplate. The migration guide says strip and
re-measure. Added back only targeted, specific guidance.

**Breaking changes.** Omit `temperature`, `top_p`, `top_k`, assistant-
message prefill, and the old beta headers (`effort-2025-11-24`,
`interleaved-thinking-2025-05-14`, `fine-grained-tool-streaming-
2025-05-14`). All produce 400 on 4.7.

**Token inflation.** 4.7's tokenizer counts 1.0–1.35× as many tokens
for the same input. Counter via prompt caching (`cache_control` on
the outer content block for `state/trait_profile.md` +
`state/schema.json`) and routing cold non-interactive passes (backfill,
re-scoring) through the Batch API for 50% off.

**Advisor Tool (beta).** The Sonnet-executor + Opus-advisor pattern
gained +2.7pp SWE-bench Multilingual while cutting cost 11.9%. Our
semantic_verifier uses this pattern: it's a Sonnet call that
escalates to an `advisor` subagent on Opus when uncertain, rather
than making every verification step run on Opus.

## Parallelism and scale

Where the pipeline runs things in parallel, and how to tune it for
large corpora (thousands of PDFs).

### LLM-level parallelism

The Manager processes papers in **batches** of `batch_size` (config.yaml,
default 5). At the start of each batch, the Manager issues ALL
`extractor` Task calls for that batch in a single assistant message,
and they execute in parallel.

Each `extractor` subagent internally chains through deterministic
scripts AND spawns additional subagents:
- Each extractor spawns one `semantic_verifier` via Task.
- The semantic_verifier spawns an `advisor` on ~5–10% of claims.
- The extractor spawns the `adjudicator` only when hook failures occur
  (~5% of rows).

So for a batch of 10 papers, peak concurrent model contexts:

```
10 (extractors)
  + 10 (semantic_verifiers, one per extractor, running concurrently)
  + ~1-2 (advisors, for uncertain claims)
  + ~0-2 (adjudicators, for disputed rows)
= ~22-24 concurrent contexts at peak
```

Each context runs on a different model (Opus 4.7 for extraction +
adjudication, Sonnet 4.6 for verification + structuring, Haiku 4.5 for
triage), so they do NOT compete for the same rate-limit bucket.

### Tuning `batch_size`

| Corpus size | Suggested batch_size | Why |
|---|---|---|
| <100 papers | 5 (default) | Fast enough; keeps main context small. |
| 100–500 | 8 | Good balance of speed and rate-limit headroom. |
| 500–2,500 | 10–12 | Overnight run feasible at this scale. |
| 2,500–10,000 | 12–15 | Approaching Anthropic rate-limit ceilings; monitor. |
| >10,000 | 15 + Batch API | For cold bulk passes, route through Batch API for 50% off. |

Edit `config.yaml`:
```yaml
batch_size: 10
```

### Deterministic Python parallelism

IO-bound tasks inside the Python scripts are parallelized via
`ThreadPoolExecutor`:

| Script | Parallel operation | Default workers | Flag |
|---|---|---|---|
| `pair_pdfs.py` | pdfplumber first-page reads for title-peek | 8 | `--title-peek-workers` |
| `bootstrap.py` | GBIF species-match HTTP calls | 8 | `--gbif-workers` |
| `pdf_ingest.py` | SHA256 hashing | 1 (serial) | — (CPU-bound, fast) |
| `verify_quote.py` | PDF text extraction | 1 per paper | — (already parallel at subagent level) |
| `hooks.py` | Hook evaluation per row | 1 per paper | — (already parallel at subagent level) |

Both `pair_pdfs` and `bootstrap` use threads (not processes) because
the bottlenecks are IO, not CPU — the GIL is not the limiter. For a
2,500-PDF corpus with 2,500 unique species:

- `pair_pdfs.py --title-peek-workers 8`: ~45s instead of ~5min serial
- `bootstrap.py --gbif-workers 8`: ~45s instead of ~8min serial

Don't push `--gbif-workers` above 16 — GBIF's API is public and we
shouldn't hammer it. Their docs don't publish a hard rate limit but
running ~8 concurrent connections is polite.

### Back-pressure and failure modes

- **Anthropic rate limits.** If the extractor returns 429s, the
  Manager should pause for 30s and resume with `batch_size - 2`. This
  is a resilience pattern documented in SKILL.md's golden rules; not
  yet automated — watch for it on the first large run.
- **GBIF flakes.** The `taxonomy_resolver` HTTP call has a 10s timeout.
  Failed lookups mark the row as `taxonomy_status: "unresolved"` (soft
  fail, row still writes but `hook_gbif_resolved` flags it). No
  retries — one shot per unique species per bootstrap.
- **pdfplumber errors on corrupt PDFs.** The thread pool catches
  exceptions per PDF and marks its title as empty. Title-peek fails
  gracefully back to filename-only strategies.

### What does NOT parallelize (intentionally)

- **Adjudication.** Disputes are rare (~5% of rows); running Opus
  xhigh concurrently burns tokens faster than it saves wall time.
  Serialize adjudications within a batch.
- **Across batches.** The Manager processes one batch at a time so
  its narration and pause-points stay comprehensible. The speed win
  is within a batch, not across them.
- **Trait_learner update mode.** Runs once per 10 batches, consumes
  the tail of the ledger (last ~2000 entries only), writes a new
  profile. Fast enough serial.

## Context budget across a long run

Each component's context budget per invocation, and the cumulative
Manager growth over a multi-batch run.

### Per-subagent context (each is a forked context — does NOT bleed into Manager)

| Subagent | Typical input tokens | Why |
|---|---|---|
| triage | ~2–5k | abstract + first 2 pages via pdf_peek |
| extractor (text-only pages) | ~10–30k | agent spec + trait_profile + schema + exemplars + 2–5 pages of PDF text |
| extractor (image + text pages) | ~25–55k | adds ~4.8k tokens per rendered 2576px page image |
| semantic_verifier | ~5–10k | quote + context + row, per claim |
| structurer | ~5–8k | verified claims + schema |
| advisor (when called) | ~3–6k | one claim's worth of context |
| adjudicator | ~5–10k | disputed row + quote + hook failures |
| trait_learner (bootstrap) | ~50–80k | 5–10 seed PDFs read in sequence |
| trait_learner (update) | ~10–20k | tail of ledger (last ~2000 entries) |

None of these is close to Opus 4.7's 200k base context limit. Image-
heavy extraction on a 10-page paper would still land under 100k.

### Manager context (your main Claude Code session — THE risk)

Per batch, the Manager accumulates:
- ~1k tokens of narration output
- Task invocations: ~500 tokens × batch_size
- Summaries returned: ~300 tokens × batch_size (spec-capped at 250 words)
- Occasional reference-doc read (one-off)

→ **~5–10k tokens per batch** accumulated in Manager context.

| Papers | Batches (at batch_size=10) | Manager context used | Action |
|---|---|---|---|
| 100 | 10 | ~100k tokens | fine |
| 500 | 50 | ~500k tokens | fine on Sonnet 4.6 (1M) |
| 1,000 | 100 | ~1M tokens | near limit; checkpoint often |
| 2,500 | 250 | ~2.5M tokens | **requires session breaks** |

### The checkpoint protocol

Everything important lives on disk:
- `state/session.json` — authoritative phase state
- `state/ledger.jsonl` — every row written, including provenance
- `state/manager_checkpoint.md` — compact session summary (rewritten every 10 batches by `scripts/checkpoint.py`)
- `state/manager_log.md` — per-batch one-liner log (appended by `scripts/session_log.py`)
- `state/review_queue.jsonl`, `results.csv`, `legacy_rejected.csv` — outputs

If the Manager's in-context memory is lost to compaction or session
restart, it re-hydrates by reading session.json + manager_checkpoint.md
+ tail of manager_log.md. No batch is re-processed; the ledger is the
source of truth for what has been written.

The Manager proactively suggests a session break every 50 batches
(~500 papers). Heath can `/clear` and re-invoke the skill, and work
resumes seamlessly.

## Prompt caching strategy

Each extractor Task call is structured as:

```
system_prompt:
  # extraction rules (cacheable — rarely changes)
  # <state/trait_profile.md>
  # <state/schema.json>
  # <exemplars from state/bootstrap/exemplars.jsonl>

user_message:
  # <this paper's sha256, pages_of_interest, maybe 2576px images>
```

Mark the system prompt with `cache_control: {type: "ephemeral"}` (5-min
TTL, 1.25× write cost but 0.1× read cost) so subsequent extractions on
the same project hit cache. The 1-hour TTL variant is an option for
large nightly batches. See the migration notes in SKILL.md for token
budgeting details.

## What makes v6 different from v5

| v5 | v6 |
|---|---|
| Source_context is a 200-char field the Extractor decides to fill. Missing 38.5% of the time. | `verbatim_quote` is a protocol-required field. A deterministic script proves it appears in the PDF. Missing rate: 0%. |
| PDF linked to records by file path. User manually re-links when files move. | PDF linked by SHA256 in `manifest.sqlite`. Moves are harmless. |
| Auditor is blind — re-extracts from page without seeing Extractor's quote. Misses wrong-row-in-table errors. | Semantic Verifier reads the Extractor's actual quote. Catches species-mismatch, value-not-in-quote, and qualifier errors. |
| Domain logic lives in `extractor.md` prose ("Step 3b: verify every value…"). No enforcement. | Domain logic lives in `scripts/hooks.py` as deterministic Python functions. Write is blocked on failure. |
| Confidence is a float. Compresses many uncertainty sources into one scalar. | `uncertainty` is a structured JSON (value_clarity, notation_ambiguity, pdf_quality, …). Users can filter on any axis. |
| Compilation tables get a penalty; original citation is mostly ignored. | Extractor must emit `original_citation` for compilation rows; hook fails if missing. Compilation rows are first-class. |
| Review queue is a flat CSV. Items accumulate with no resolution workflow. | `state/review_queue.jsonl` has resolution states; `review_queue.py` feeds resolutions back into results.csv and tracks rate. |
| Per-record provenance (model version, guide hash) inconsistent. | Ledger captures model versions, trait_profile hash, schema hash, session id for every row. |
| Trait knowledge hardcoded in references/*.md. Any new trait is a refactor. | Trait knowledge lives in `state/trait_profile.md`, built by `trait_learner` from seed papers. Any trait works. |
| Main agent reads PDFs and extracts inline. Context fills; compaction corrupts state. | Main agent only orchestrates. Extraction happens in forked subagent contexts. Main context stays small all session. |
