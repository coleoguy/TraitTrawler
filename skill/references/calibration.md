# Calibration Phase

Run after the setup wizard generates config files, before the first real
collection session. The goal is to learn from real papers so the agent starts
its first session with domain knowledge extracted from actual literature, not
just the user's initial description.

---

## Seed Papers

You need 2-5 seed papers. These may come from:

- **Papers the user mentioned during the setup conversation** — always
  offer to use these first
- **DOIs or titles the user provides** when you ask
- **Papers you find yourself** — if the user says "find some yourself",
  spawn a Sonnet-Searcher with the top 3 highest-specificity queries from
  `config.py`, pick 3-5 papers with the best abstracts. Prefer papers
  from journals known for the target trait.

## Benchmark Holdouts

Before processing, designate 2-3 seed papers as **benchmark holdouts**.
These go through the normal extraction pipeline, but afterward you present
the results to the user for field-by-field verification — creating
gold-standard data for accuracy measurement.

Let the user know what you're doing and why: these verified records let you
measure and improve extraction accuracy over time. Record results to
`state/benchmark_gold.jsonl` and `state/calibration_data.jsonl`.

The remaining seed papers are used for guide.md learning below.

---

## Calibration Extraction

Process each seed paper through the full v4 pipeline:
1. Spawn **Sonnet-Fetcher** to acquire the PDF
2. Spawn **Sonnet-Dealer** to coordinate extraction (use whatever
   `extraction_mode` the user chose — consensus or fast)
3. Spawn **Sonnet-Writer** to validate and write to results.csv

During calibration, instruct the Dealer to be aggressive about discovery
logging:
- Log **every** notation variant, terminology, and extraction pattern to
  `learning/` — even things that seem obvious
- Note document structure: Where does trait data typically appear? Tables?
  Results section? Appendices? Comparative tables?
- The whole point is to populate `guide.md` with real examples before
  collecting at scale

---

## Knowledge Review

Run the knowledge review immediately after calibration extraction (don't
wait for session end). Read `learning/` files, classify each discovery as
routine or structural (see `knowledge_and_transfer.md`), present all
discoveries to the user, and apply approved amendments to `guide.md`.

This is the key payoff: the first real collection session benefits from
domain knowledge extracted from real papers, not just the user's description.

---

## Citation Seeding

For each seed paper, spawn a **Sonnet-Searcher** with
`mode: "citation_chain"` to pull references and citing papers via OpenAlex.
Triage titles and abstracts using the standard triage rules. Add
likely/uncertain papers to `state/queue.json`.

Citation seeding often finds papers more relevant than cold keyword searches,
especially for niche taxa or older literature that uses different terminology.

---

## Extraction Examples

Using the seed papers, auto-generate `extraction_examples.md` with 2-3
worked examples showing:
- The raw text or table row from the paper (verbatim, short excerpt)
- The extracted record (all fields with values)
- Notes on notation choices or ambiguity resolution

Ask the user to review. These examples serve as few-shot prompts during
extraction — particularly valuable for complex notation systems.

---

## Wrapping Up

Report what you accomplished: how many papers processed, records extracted,
guide.md amendments approved, citations found and queued.

Write `state/calibration_complete.json`:
```json
{"completed": true, "date": "...", "seed_papers": N, "records": N,
 "benchmark_holdouts": N}
```

Tell the user to start a new conversation for the first collection session.
**Do NOT proceed to section 1 in this invocation** — wizard + calibration
consumes most of the context budget. A fresh session ensures full context
for collection.

---

## Notes

- Calibration records are written to `results.csv` normally, with
  `session_id` reflecting the calibration session.
- If the user wants to skip calibration ("just start searching"), that's
  fine. It's strongly recommended but not required.
- The entire calibration phase typically takes 10-20 minutes for 3-5 papers.
  It pays for itself in the first batch by reducing low-confidence
  extractions and notation errors.
