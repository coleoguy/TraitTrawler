# Model Routing

TraitTrawler uses cheaper, faster models for routine tasks and reserves
expensive models for tasks requiring deep reasoning. The Agent tool's `model`
parameter controls this. Configure defaults in `collector_config.yaml` →
`model_routing` (see config template), or accept these defaults:

| Task | Default model | Escalation trigger |
|---|---|---|
| Search (API calls, dedup) | `haiku` | — |
| Triage (abstract classification) | `haiku` | — |
| State updates, reporting, leads | `haiku` | — |
| Prose extraction | `sonnet` | → opus if confidence < 0.5 on retry |
| Table extraction (pass 1: enumerate) | `sonnet` | — |
| Table extraction (pass 2: extract) | `sonnet` | → opus if row-count mismatch > 10% |
| Catalogue/dense extraction | `sonnet` | → opus if > 50 taxa per page |
| Scanned PDF (vision) | `sonnet` | → opus if OCR artifacts detected |
| Validation & verification | `sonnet` | — |
| Knowledge review (§14 proposals) | `sonnet` | → opus for structural amendments |
| Taxonomy resolution (§16) | `haiku` | — |
| Statistical QC (§17) | `haiku` | — |
| Campaign planning (§18) | `sonnet` | — |

## Escalation protocol

When a task escalates to a more expensive model:
1. Log the escalation to `state/run_log.jsonl`:
   ```json
   {"timestamp": "...", "session_id": "...", "event": "model_escalation", "doi": "...", "from": "sonnet", "to": "opus", "reason": "row_count_mismatch_23pct"}
   ```
2. Report to the user at the next progress update:
   `⬆ Escalated "{title}" to opus (reason: {reason})`
3. After the escalated task completes, return to the default model for the
   next paper. Escalation is per-paper, never sticky.

## Override

The user can say "use opus for everything" or "use sonnet for triage too" at
any time. Respect the override for the rest of the session but do not persist
it to config. Log overrides to `run_log.jsonl`.

## Implementation

Use the Agent tool with the `model` parameter to dispatch subtasks:
- Spawn a haiku subagent for search/triage batches
- The main agent (whatever model the session runs on) handles extraction
- Spawn an opus subagent only when escalation is triggered

When the session model is already haiku or sonnet, skip spawning a subagent
for tasks at that level — just do them directly.

**Batch subagent calls to amortize overhead.** Spawning a subagent has fixed
context-setup cost, so batch work rather than spawning per-paper:
- **Search**: Send 5–10 queries per haiku subagent call. Include the search
  terms, API instructions, and `processed.json` DOI list for dedup. The
  subagent returns new papers as JSON.
- **Triage**: Send 10–20 abstracts per haiku subagent call. Include
  `guide.md` content and triage rules. The subagent returns classifications.
- **Extraction**: Do NOT batch across papers — each paper needs full context.
  Run one paper per sonnet call (or do it directly if already on sonnet).
- **Audit queue construction**: One haiku subagent call to scan all of
  `results.csv` and return the prioritized queue.

Pass all needed context (guide.md, triage rules, config excerpts) in the
Agent prompt — subagents do not inherit the parent's conversation history.
