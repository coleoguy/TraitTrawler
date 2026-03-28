# Setup Wizard & Calibration — First-Run Reference

Load this file when `collector_config.yaml` does not exist in the project root.

---

## Path A: Fresh Start (no CSV provided)

Ask these questions one at a time (wait for each answer):

1. "What taxa are you collecting data for? (e.g. Coleoptera, Aves, Mammalia)"
2. "What trait or data type are you collecting? (e.g. karyotype, body size, mating system)"
3. "Is this **among-species** data (one value per species across many species)
   or **within-species** data (multiple observations for one or few species,
   keyed by population, locality, individual, etc.)?"
   - **Among-species**: add `species` to `required_fields`, enable
     `taxonomy_resolution: true`, include `species`, `family`, `genus` in output_fields
   - **Within-species**: do NOT require `species`, set `taxonomy_resolution: false`,
     ask what the key field is (e.g., `population`, `locality`, `individual_id`)
     and add that as a required field instead
4. "What keywords in a paper title make it clearly relevant even without an abstract?"
5. "What is your contact email? (used for API polite-pool access)"
6. "What institution do you use for library access? (for the proxy URL)"
   — For Texas A&M: proxy is `http://proxy.library.tamu.edu/login?url=`

For any question the user delegates ("you figure it out"), spawn a **sonnet
subagent** to research and return a proposed answer.

### Generate Project Files

From answers, create:
- `collector_config.yaml` from template in `${CLAUDE_SKILL_DIR}/references/config_template.yaml`
  - Add `extraction_mode: consensus` (default) and `concurrency: {max_concurrent_dealers: 2}`
  - Populate `{TRAIT_FIELDS}` with trait-specific field names:
    - snake_case, include unit when applicable (e.g. `body_mass_g_mean`)
    - Include `_mean`, `_sd`, `_min`, `_max` for continuous measurements
    - Include `sex`, `sample_size`, `age_class` when trait is per-individual
    - **Always include provenance fields**: `source_page`, `source_context`, `extraction_reasoning`
    - Show the user the field list and ask if they want changes
  - Set `required_fields` based on among/within-species answer
  - Set `dedup_key` based on the key field + trait fields:
    - Among-species: `[species, doi, {trait_fields}]`
    - Within-species: `[{key_field}, doi, {trait_fields}]`
    - Show the user: "A record is considered a duplicate when these fields
      all match an existing record: {dedup_key}. Correct?"
- `config.py` with cross-product of taxonomic groups x trait keywords
- `guide.md` with domain knowledge structure
- `results.csv` with header row only
- `leads.csv` (empty)
- All folders: `state/`, `finds/`, `ready_for_extraction/`, `learning/`,
  `provided_pdfs/`, `pdfs/`, `state/dealt/`, `state/extraction_traces/`,
  `state/snapshots/`
- Empty state files: `processed.json` (`{}`), `queue.json` (`[]`),
  `search_log.json` (`{}`), `run_log.jsonl` (empty), `discoveries.jsonl` (empty),
  `taxonomy_cache.json` (`{}`), `calibration_data.jsonl` (empty),
  `triage_outcomes.jsonl` (empty), `source_stats.json` (`{}`),
  `consensus_stats.json` (`{}`)

Then ask:
7. "What are the major taxonomic groups I should search?"
8. "Any specific journals or author names that are especially relevant?"
9. "What should I know about how this trait is reported in the literature?"

Generate `config.py` with cross-product. Generate `guide.md` with sections
for: Units/notation, What to extract, What to skip, Common pitfalls,
Taxonomy notes.

---

## Path B: Bootstrap from Existing CSV

Before asking wizard questions, check for any `.csv` in the project root
(other than `leads.csv`). If found, ask:

```
Found {filename} ({N} columns, {M} data rows). Use this as the project template?
  1. Yes -- infer my schema and settings from this file
  2. No -- start fresh with the setup wizard
```

If yes:
1. **Infer output_fields** from column headers:
   - All-numeric values → `number`
   - Only "True"/"False" → `boolean`
   - Everything else → `string`
   - Recognize standard TraitTrawler columns automatically:
     `species`, `family`, `genus`, `doi`, `paper_title`, `paper_year`,
     `first_author`, `paper_journal`, `extraction_confidence`, `flag_for_review`,
     `session_id`, `source_page`, `source_context`, `extraction_reasoning`,
     `consensus`, `accepted_name`, `gbif_key`, `taxonomy_note`, `pdf_source`,
     `source_type`, `notes`
2. **Ask only what can't be inferred** (taxon, trait name, email, proxy)
3. **Import data**: copy CSV to `results.csv`, populate `processed.json` from DOIs
4. **Skip calibration** if 20+ records exist
5. **Generate `extraction_examples.md`** from 3-5 high-confidence records

---

## Calibration Phase (both paths)

After config files are ready:

1. Ask for 2-5 seed papers (user-provided DOIs or auto-found via search)
2. Process seeds through the full pipeline (Fetcher → Dealer → Extractor → Writer)
3. Designate 2-3 as benchmark holdouts (user verifies every field)
4. Review discoveries immediately (run knowledge review, don't wait for session end)
5. Citation-seed the queue from seed papers' references
6. Auto-generate `extraction_examples.md` with 2-3 worked examples

Write `state/calibration_complete.json`:
```json
{"completed": true, "date": "...", "seed_papers": N, "records": N,
 "benchmark_holdouts": N}
```

Tell the user:
```
Calibration complete — config files, guide.md, and extraction examples are
ready. Start a new conversation and say "continue collecting" or "run a
session" to begin the first collection batch with a fresh context window.
```

**Do NOT proceed to section 1 in the same invocation.** Wizard + calibration
consumes most of the context window. A fresh session gets the full budget
for actual collection.
