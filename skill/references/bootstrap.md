# Bootstrap Workflow

If the user has existing curated trait data, TraitTrawler can ingest
it as ground truth rather than re-extracting everything from scratch.
This doc describes the feature end-to-end. The Manager reads it on
demand in phase 0.5.BOOTSTRAP.

## What bootstrap does

- **Ingests** a curated CSV of trait records into the project ledger
  with a clear `source_type: "human_curated_bootstrap"` marker and DwC
  `identificationVerificationStatus: "ValidatedByHuman"`.
- **Hashes** any paired PDFs into `state/manifest.sqlite` keyed by
  SHA256 so the content-based linkage survives filename changes.
- **Dedupes** on a composite key `(doi, canonical_species, trait,
  value)` so the Extractor does not re-extract curated rows unless
  explicitly told to.
- **Selects exemplars** — a representative subset (default 50 rows)
  that the Extractor uses as in-context anchors for notation
  conventions.
- **Proposes soft hooks** via `scripts/derive_hooks.py` — range and
  enum validators derived from the observed numeric and categorical
  distributions.

## What bootstrap does NOT do

- It does not learn the trait. That's the trait_learner in phase 1.
  The trait_learner does read `state/bootstrap/imported.jsonl` as an
  additional signal, but the structured learning and §11 Proposed
  Columns still come from it.
- It does not propose output schema columns directly. The schema is
  produced by `propose_columns.py` reading §11 from the
  trait_learner's output.

## User input

One CSV file, one optional PDF directory. That's it.

Minimum CSV columns (the script accepts common aliases):
- species: `canonical_species` or `species` or `species_name`
- trait: `trait_key` or `trait` or `trait_name`
- value: `trait_value` or `value` or a specific numeric column
- (optional) `doi`, `pdf_filename`, `pdf_path`, `curator`, `verbatim_quote`,
  `notation_style`, `is_compilation`

Any additional columns pass through to `state/bootstrap/imported.jsonl`
and can be referenced by later schema-proposal steps.

## Example

Heath's Coleoptera karyotype project has a ~4,000-row curated CSV
accumulated over years of manual work. To bootstrap a v6 project from
it:

```
traittrawler new
> trait: diploid chromosome number
> taxa: Coleoptera
> curated CSV: /path/to/hbdat.csv
> paired PDFs: /path/to/pdfs/
> project root: ~/trait-projects/coleo-v6
```

Bootstrap:
1. Canonicalizes 4,000 species names via GBIF (flags fuzzy matches).
2. Hashes ~2,500 paired PDFs into manifest.sqlite.
3. Writes 4,000 ledger entries with ValidatedByHuman.
4. Selects 50 exemplars stratified over notation_style × compilation
   status × trait_key.
5. Derives ~15 soft hooks (e.g. `hook_range_diploid_2n`,
   `hook_enum_sex_system`).

Then in phase 2.SCHEMA+HOOKS, Heath approves each proposed hook
individually. Any derived hook he rejects or edits never runs. The
ones he approves move from `state/hooks/proposed/` to `state/hooks/`
and are registered in `state/schema.json.trait_hooks`.

## Conflict handling

### Same paper, curator vs AI disagree

When the Extractor later produces a row whose composite key collides
with a bootstrap row, the dedup hook short-circuits: bootstrap wins
(human-validated), the AI extraction is logged to
`state/ai_vs_curator_disagreements.jsonl` for later review. Set
`config.yaml.challenge_mode: true` to flip this — useful when
validating the Extractor against known-good curator data.

### Duplicate composite keys within the input CSV

Written to `state/bootstrap/conflicts.jsonl`. The Manager pauses and
asks the user how to resolve (keep first / keep latest / merge /
manual review).

## Provenance standards

Every imported row carries Darwin Core + PAV + PROV-O + Dublin Core
fields. Downstream analyses can filter on
`dwc_identificationVerificationStatus` to separate ValidatedByHuman
from PredictedByMachine rows. This is the W3C/TDWG standard for
biodiversity data lineage and is a published approach for exactly
this kind of mixed human-AI curation workflow (see FAIR²,
Frontiers 2025).

## When to skip bootstrap

If the user has no curated data, bootstrap is skipped entirely and
the project goes straight to phase 1.LEARN with just seed PDFs. The
trait_learner handles both cases — it just has more evidence when
bootstrap ran.
