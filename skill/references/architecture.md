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

## The 7 phases

```
0. SETUP     → project_init subagent collects trait, taxa, seed DOIs
1. LEARN     → trait_learner reads 5-10 seeds, writes trait_profile.md
2. SCHEMA    → propose_columns generates schema; user approves
3. SEARCH    → searcher queries all four APIs
4. FETCH     → fetcher downloads PDFs, manifest.sqlite records hashes
5. PROCESS   → batch loop: triage → extract → verify → structure → hook → adjudicate
6. REVIEW    → user resolves review-queue items
7. REPORT    → session_report summarizes coverage & accuracy
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
