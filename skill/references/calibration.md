# Calibration and Self-Research

## 0a. Researching wizard answers

When the user delegates a setup wizard question ("you figure it out",
"research it", "I don't know"), use the taxon and trait from Q1–Q2 to
find the answer. Always present findings for user approval.

**Q3 (keywords)**: Search OpenAlex for 10–20 recent papers matching the
taxon + trait. Extract the most common title words that co-occur with the
trait. Propose a keyword list.

**Q5 (proxy URL)**: Search the web for "{institution name} library proxy
URL" or "{institution name} ezproxy". Common patterns:
`http://proxy.library.{domain}/login?url=` or
`https://ezproxy.{domain}/login?url=`. Propose and confirm.

**Q7 (taxonomic groups)**: Search OpenAlex for the higher taxonomy of the
target taxon. For an order, list families; for a family, list subfamilies.
Use OpenAlex `search_works` with facets or GBIF taxonomy to identify the
most-studied groups for this trait. Propose a list.

**Q8 (journals/authors)**: Search OpenAlex for the top 10 journals and
top 10 authors publishing on {taxon} + {trait} in the last 20 years.
Propose the lists.

**Q9 (how trait is reported)**: Search for 3–5 open-access papers on the
trait, read the Methods and Results sections, and draft `guide.md` sections
based on what you find. This merges directly into the calibration phase
below — if the user delegates Q9, use the papers you find as seed papers
for calibration and skip straight to Step 3.

---

# Calibration Phase (§0b)

Run this phase after the setup wizard generates config files, before the
first real collection session. The goal is to learn from real papers so the
agent starts its first session with domain knowledge extracted from actual
literature, not just the user's initial description.

---

## Step 1 — Ask for seed papers

```
Before I start searching, can you give me 2–5 DOIs or titles of papers
that are good examples of what I should be finding? These will help me
learn the notation, table formats, and terminology for your trait before
I process hundreds of papers on my own.

(If you don't have any handy, I'll find some myself using your keywords.)
```

---

## Step 2 — Acquire seed papers

**If the user provides DOIs**: fetch via the OA cascade (§5b) or locate in
`pdfs/` if user-supplied.

**If the user says "find some yourself"**: run the top 3 highest-specificity
queries from `config.py` (queries with the most keywords), fetch the top 2
results from each, and pick the 3–5 with the most relevant-looking
abstracts. Prefer papers from journals known for the target trait — e.g.,
Comparative Cytogenetics for karyotypes, or journals with "morphometrics"
in the title for body measurements.

---

## Step 3 — Calibration extraction

Process each seed paper through the full extraction pipeline (§7), but with
extra attention to discovery logging (§14). **Use the same subagent
architecture as normal sessions** (see model_routing.md §2) — spawn a
sonnet subagent for each paper's extraction. This keeps PDF text out of
the main agent's context, which is important because calibration processes
3–5 papers in quick succession and context pressure accumulates fast.

For each paper:
- Extract records as normal (via subagent)
- Log EVERY notation variant, terminology, and extraction pattern to
  `state/discoveries.jsonl` — be aggressive about logging during calibration,
  even for things that seem obvious. The point is to populate `guide.md`
  with real examples before the agent flies solo.
- Note the document structure: Where is trait data typically found? Tables?
  Results section? Appendices? Comparative tables in Introduction?

---

## Step 4 — Immediate knowledge review

Run the §14 session-end knowledge review immediately (don't wait for session
end). Present all discoveries to the user and apply approved amendments to
`guide.md`.

This is the key payoff: the very first real search session benefits from
domain knowledge extracted from real papers, not just the user's description
of how the trait is reported.

---

## Step 5 — Citation seeding

For each seed paper, use OpenAlex `get_work_references` and
`get_work_cited_by` to pull references and citing papers. Triage the titles
and abstracts using the standard triage rules (§4). Add likely/uncertain
papers to `queue.json`.

This seeds the search queue with papers connected to known-good sources —
often more relevant than cold keyword searches, especially for niche taxa
or older literature that uses different terminology.

Report:
```
📚 Calibration complete
   Seed papers processed   : {N}
   Records extracted        : {N}
   guide.md amendments      : {N} approved
   Citations found          : {N}
   Added to search queue    : {N}
   guide.md is now {lines} lines with {sections} sections

Ready to start collecting. The search queue has {N} papers from citations
plus {M} keyword queries. Begin? [y/n]
```

---

## Step 6 — Generate extraction_examples.md

Using the seed papers as source material, auto-generate
`extraction_examples.md` with 2–3 worked examples showing:
- The raw text or table row from the paper (verbatim, short excerpt)
- The extracted record (all fields with values)
- Notes on any notation choices or ambiguity resolution

Ask the user to review and approve. This gives the agent (and future
sessions) concrete worked examples, not just abstract rules. The examples
serve as few-shot prompts during extraction — particularly valuable for
complex notation systems where a rule description alone is insufficient.

---

## Notes

- Calibration records are written to `results.csv` normally, with
  `session_id` reflecting the calibration session.
- If the user skips calibration ("just start searching"), proceed to §1.
  Calibration is strongly recommended but not required.
- The entire calibration phase should take 10–20 minutes for 3–5 papers.
  It's an investment that pays for itself within the first batch by
  reducing low-confidence extractions and notation errors.
