# Bootstrap Workflow

If the user has existing curated trait data, TraitTrawler can ingest
it as ground truth rather than re-extracting everything from scratch.
Real-world curated folders are messy — main CSV plus auxiliary files,
PDFs whose names don't match the CSV's filename column, column-name
typos, partial coverage. This workflow is explicitly designed to make
that kind of migration work well.

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

You point the skill at a folder. The skill figures out the rest.

The folder might contain, in any combination:
- One main curated CSV/TSV
- Auxiliary files like `suspect records.csv` (rows flagged for review),
  `papers needed.txt` or `.bib`/`.ris` (papers the user wants PDFs for),
  `adjudication_decisions.csv` (pre-made dispute resolutions)
- A `pdfs/` subdirectory (or any directory of PDFs)

The filenames do not need to follow a specific convention. The skill
classifies them by matching keywords (`suspect|review|flag|pending|
uncertain|queue` → review queue; `papers_needed|wanted|to_get|ill_list|
wishlist` → fetch candidates; `adjudic|resolution|decided|dispute` →
adjudication log; `result|dataset|data|main|master|curated|records` →
main dataset; everything else → unknown).

Minimum CSV columns in the main dataset (the script accepts aliases
and fuzzy-matches column names):
- species: `canonical_species`, `species`, `Sp_Name`, `species_name`, `taxon`, etc.
- trait: `trait_key`, `trait`, or a specific numeric column like `2n`
- value: `trait_value` or a specific numeric column

### Core aliases (trait-agnostic)

The preflight script carries **only** infrastructure and provenance
aliases — the fields every scientific extraction project needs
regardless of trait. No trait-specific alias is hardcoded in the
core skill.

| Canonical | Known aliases |
|---|---|
| `canonical_species` | species, sp, sp_name, speciesname, taxon, binomial, scientificname, organism |
| `doi` | DOI, paper_doi, article_doi, identifier |
| `pdf_filename` | pdf_file, pdf, filename, file, paper_pdf, pdf_name |
| `pdf_path` | pdf_location, file_path, path |
| `first_author` | firstauthor, author, authors, auth |
| `year` | paper_year, pub_year, publication_year, yr, date |
| `trait_key` | trait, trait_name, field, character, variable |
| `trait_value` | value, measurement, result |
| `verbatim_quote` | quote, source_context, context, evidence, excerpt, source_text |
| `page` | page_number, pg, page_num, source_page |
| `notation_style` | notation, style, format |
| `is_compilation` | compilation, review_table, from_review |
| `original_citation` | orig_cite, primary_source, source |
| `title` | paper_title, article_title |
| `curator` | curatedby, curated_by, recordedby, recorded_by |

### Project-specific aliases (where your trait vocabulary lives)

Everything trait-specific comes from one of three places:

1. **An interactive dialogue** with the `bootstrap` subagent during
   Stage 1. The subagent asks: "I don't recognize the column `chrnum`
   — what does it represent? The first value is `20`." You answer.
   Your answer is saved to `state/bootstrap/column_map.json`.
2. **A pre-supplied `<project_root>/column_aliases.json`** that you
   populate before starting (or let the subagent save for you after
   Stage 1 so future migrations skip the dialogue):
   ```json
   {
     "diploid_2n": ["chrnum", "2n", "chromosome_count"],
     "sex_system": ["Sys", "sex_chr_system"],
     "haploid_autosome_count": ["HAC", "n_autosomes"]
   }
   ```
3. **The trait_learner output** from phase 1.LEARN — §11 Proposed
   Columns includes the canonical names, and you can set them as
   aliases for future bootstrap runs.

Unmapped columns pass through as-is to the ledger; nothing is lost.
Pass `--user-aliases <path>` to `migration_preflight.py` to merge
your project-specific aliases into the preflight's proposals.

## The three-stage workflow

### Stage 1: Pre-flight

`scripts/migration_preflight.py` scans the source folder and writes
`state/bootstrap/migration_plan.md` + `.json`. Classifies every file,
sniffs CSV dialect and encoding, proposes column mappings, counts
PDFs, and flags warnings (zero-byte PDFs, no main dataset detected,
multiple main-dataset candidates, unmapped headers).

The user reviews the plan via `AskUserQuestion` with four options:
approve / edit mapping / reclassify a file / abort.

### Stage 2: Dry-run pairing + ingestion

`scripts/pair_pdfs.py` tries five strategies in decreasing
confidence:

1. **EXACT_STEM** (confidence 1.00) — filename column stem matches a
   PDF stem literally.
2. **DOI_IN_NAME** (0.95) — DOI suffix appears in a PDF stem.
3. **DOI_NORMALIZED** (0.92) — DOI with slashes replaced matches a PDF stem.
4. **AUTHOR_YEAR** (0.85) — surname-year pattern in a PDF stem.
5. **TITLE_PEEK** (up to 0.95) — `pdfplumber` reads first page of
   each unpaired PDF, fuzzy-matches against the title column.

Outputs `state/bootstrap/pairing_report.json` with per-row verdict.
Orphan PDFs (on disk but paired to nothing) are reported separately.

Then `scripts/bootstrap.py --dry-run` runs every step **without**
writing ledger entries — produces the migration report so the user
can see what would happen.

### Stage 3: Commit

Same commands without `--dry-run`. Ledger entries are written,
exemplars selected, then `scripts/derive_hooks.py` produces soft
validation hooks from observed distributions.

## Example

Heath's Coleoptera karyotype folder contains:
- `hbdat.csv` (4,102 rows, main dataset)
- `suspect_records.csv` (127 rows flagged for review)
- `papers_needed.txt` (300 DOIs of papers he wants)
- `pdfs/` (2,547 PDFs)

Running bootstrap (trait-agnostic: the exact same commands work for
karyotype data, avian body mass, clinical outcomes, materials
conductivity, or any other trait):

```bash
# Stage 1: pre-flight (the subagent will dialogue about unmapped columns)
python scripts/migration_preflight.py \
  --root ~/my-project --source ~/my-curated-folder/
# → auto-maps infrastructure columns (species, DOI, pdf_filename, ...)
# → lists the trait-specific columns it does NOT recognize
# → bootstrap subagent asks the user what each one represents

# Optional: supply project-specific aliases up front to skip the dialogue
cat > ~/my-project/column_aliases.json <<EOF
{
  "<your_canonical_col>": ["alias_as_it_appears_in_your_csv", ...]
}
EOF
python scripts/migration_preflight.py \
  --root ~/my-project --source ~/my-curated-folder/ \
  --user-aliases ~/my-project/column_aliases.json

# Stage 2: fuzzy pairing + dry-run ingest
python scripts/pair_pdfs.py --root ~/my-project \
  --csv ~/my-curated-folder/<main_csv> \
  --pdfs ~/my-curated-folder/pdfs/ \
  --column-map state/bootstrap/column_map.json

python scripts/bootstrap.py --root ~/my-project \
  --csv ~/my-curated-folder/<main_csv> \
  --pdfs ~/my-curated-folder/pdfs/ \
  --pairing-report state/bootstrap/pairing_report.json \
  --column-map state/bootstrap/column_map.json \
  --suspect-csv ~/my-curated-folder/<suspect_csv?> \
  --papers-needed ~/my-curated-folder/<papers_needed?> \
  --dry-run

# The Manager narrates the dry-run result and asks "commit?" before
# anything is written to state/ledger.jsonl.

# Stage 3: commit (same command minus --dry-run)
python scripts/bootstrap.py ... (no --dry-run)
# → N ledger lines written with ValidatedByHuman; M review-queue
#   items loaded; K candidates queued for the fetcher; exemplars
#   selected; migration_report.md produced

python scripts/derive_hooks.py --project-root ~/my-project
# → soft hooks proposed from the observed distributions
#   (names are derived from YOUR column names, not baked in)
```

Then in phase 2.SCHEMA+HOOKS, the user approves each proposed hook
individually. Any derived hook they reject or edit never runs.

## Concrete example from a karyotype project

To make this concrete: when Heath runs bootstrap on his Coleoptera
data, his `column_aliases.json` might look like:

```json
{
  "diploid_2n": ["chrnum", "2n", "chromosome_count"],
  "haploid_autosome_count": ["HAC", "n_autosomes"],
  "sex_chrom_count": ["sex_chr", "n_sex_chr"],
  "sex_system": ["Sys", "sex_chr_system"]
}
```

The derived hooks produced for his project would include names like
`hook_range_diploid_2n` and `hook_enum_sex_system`. None of those
names lives in the core skill — they are derived at runtime from the
column names in his data. A clinical-outcome project's derived hooks
would be named `hook_range_effect_size`, `hook_enum_outcome_type`,
and so on, entirely by analogy.

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
