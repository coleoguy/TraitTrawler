# Review Workflow

The review queue is where records that failed hooks (and an adjudicator
ruling of `reject` or `defer`) wait for a human decision. v5's review
queue had no resolution workflow and ballooned to thousands of rows. v6
fixes this with structured resolution states and a feedback loop that
teaches the trait_learner.

## Queue storage

`state/review_queue.jsonl` — one JSON per line:

```json
{
  "review_id": "uuid",
  "created_utc": "...",
  "dispute_id": "uuid",
  "row": { ... },
  "failure_reasons": ["hook_hac_consistency: ..."],
  "verbatim_quote": "...",
  "page": 4,
  "sha256": "...",
  "adjudicator_verdict": "reject|defer|amend",
  "adjudicator_reasoning": "...",
  "resolution_state": "pending",
  "resolution": null,
  "resolved_by": null,
  "resolved_utc": null
}
```

## Resolution states

- **`pending`** — newly queued, awaiting human review.
- **`confirmed`** — human approved the original Row (hook was wrong).
  Row is written to `results.csv`. Hook false-positive is recorded
  for active-learning.
- **`corrected`** — human edited the Row and approved the edit. Edited
  Row goes to `results.csv`. The edit is recorded to the ledger as
  `adjudication: {verdict: "human_amend", diff: {...}}`.
- **`rejected`** — human confirms the Row is wrong. Goes to
  `legacy_rejected.csv` with reason code.
- **`deferred`** — human is unsure, wants to revisit. Stays in queue
  with a bump timestamp.

## Batch review UX

The Manager generates an HTML review bundle on demand:

```
scripts/review_queue.py --emit-html --top 20
```

The HTML groups items by source paper (so the user can review ~all
items from one PDF in one sitting without tab-switching), shows the
verbatim quote highlighted in context, lists failure reasons in plain
English, and has four radio buttons per item (confirm / correct /
reject / defer) with an optional comment field. Clicking "Save" writes
a decisions CSV.

The user then runs:

```
scripts/review_queue.py --apply decisions.csv
```

which moves resolved items out of the queue, feeds them back into
results.csv or legacy_rejected.csv, writes ledger entries for each,
and updates active-learning counters.

## Active learning feedback

Every resolution feeds counters:

- **Hook false-positive rate** — if `hook_foo` has been `confirmed`
  more than 3× and `rejected` less than 1×, flag it for review by
  the maintainer; the hook may be over-strict.
- **Hook true-positive rate** — hooks that consistently produce
  `rejected` resolutions are doing their job.
- **Adjudicator accuracy** — when the human overturns an adjudicator
  amend, that amendment pattern is recorded.

Counters live in `state/active_learning.json` and are consulted by
the `trait_learner` during update mode, which may add clarifying
notes to `trait_profile.md`.

## Throughput targets

A healthy session has:
- Review queue size trending down between sessions.
- Median item age under 48 hours.
- Per-item resolution time under 60 seconds (the HTML bundle makes
  this achievable because the quote is highlighted and the failure
  reason is concrete).

If queue grows faster than resolution rate, the Manager narrates the
imbalance at the end of each batch — this is the active-throttle
signal.
