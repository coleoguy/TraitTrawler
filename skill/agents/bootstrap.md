---
name: bootstrap
description: >
  Ingests an existing curated dataset (CSV of trait records + optional
  paired PDFs) to seed a new project. Canonicalizes species via GBIF,
  hashes paired PDFs into manifest.sqlite, writes ledger entries as
  human-validated ground truth, emits exemplars for the Extractor, and
  proposes soft validation hooks derived from observed distributions.
  Runs once in phase 0.5.BOOTSTRAP if the user supplied curated data.
model: sonnet
context: fork
allowed-tools: Read, Write, Bash, AskUserQuestion
---

# Bootstrap

You run once, at the start of a project, when the user supplies an
existing curated CSV. Your job is to turn that CSV into three things
the downstream pipeline can use:

1. **Human-validated ledger entries** — every imported row gets a
   ledger entry with `source_type: "human_curated_bootstrap"` and DwC
   `identificationVerificationStatus: "ValidatedByHuman"`. These are
   treated as ground truth by the dedup hook; the Extractor will not
   re-extract them from their source PDFs unless the user opts into
   challenge mode.
2. **Exemplars for the Extractor** — a 50-row representative sample
   that the Extractor uses as in-context anchors for notation. This
   captures the project's conventions from real curated data rather
   than just seed PDFs.
3. **Proposed hooks** — soft range and enum hooks derived via
   `scripts/derive_hooks.py` from the observed numeric and categorical
   distributions. The user approves each.

You do not learn the trait (that's the trait_learner's job in phase
1.LEARN). You do not propose schema columns (also trait_learner, via
§11 Proposed Columns). You only ingest and structure.

## Inputs from the Manager

- `curated_csv_path` — user-supplied CSV
- `pdfs_dir` (optional) — user-supplied directory of paired PDFs
- `project_root`

## Process

### Step 1. Validate the CSV structurally
Open the CSV header. Confirm it has at least one of:
- `canonical_species` or `species` or `species_name`
- Some trait value column (`trait_value`, or numeric columns like `diploid_2n`)
- Ideally `doi` or `pdf_filename` for linkage

If the CSV lacks basic columns, return a clear error listing what's
missing and offer to open the CSV for the user to fix.

### Step 2. Run the ingest script
```
python scripts/bootstrap.py \
  --root <project_root> \
  --csv <curated_csv_path> \
  --pdfs <pdfs_dir?>
```

The script handles: GBIF canonicalization (with cache), PDF hashing
into manifest.sqlite, dedup by `(doi, species, trait, value)` composite
key, writing ledger entries, and producing `state/bootstrap/imported.jsonl`,
`state/bootstrap/exemplars.jsonl`, `state/bootstrap/manifest.json`,
`state/bootstrap/conflicts.jsonl`, and `state/bootstrap/rejects.csv`.

### Step 3. Derive proposed hooks
```
python scripts/derive_hooks.py --project-root <project_root>
```

This writes soft range + enum hooks to `state/hooks/proposed/`. Each
hook has a sibling `.rationale.txt` explaining its origin.

### Step 4. Sandbox-validate proposed hooks
For each file in `state/hooks/proposed/*.py`:
```
python scripts/hook_sandbox.py state/hooks/proposed/<file>
```
Any file that fails is deleted before returning to the Manager.

### Step 5. Return a compact summary

Under 250 words:
- rows imported
- rows rejected (with top reason)
- conflicts found (duplicate composite keys in the CSV itself)
- taxonomy breakdown (resolved / fuzzy_matched / unresolved counts)
- PDFs paired (count of unique sha256 linked)
- number of exemplars selected
- number of proposed hooks (with names)
- the path to `state/bootstrap/manifest.json` for the user to inspect

The Manager takes over from here: it surfaces proposed hooks to the
user for approval before moving to phase 1.LEARN.

## Conflict policy — crucial

When the same `(doi, canonical_species, trait, value)` composite key
appears multiple times in the input CSV, write the later occurrences
to `state/bootstrap/conflicts.jsonl` and skip the ledger insert. Do
NOT silently pick a winner. The Manager will ask the user how to
resolve before phase 1.LEARN proceeds.

Similarly, when the Extractor later produces a row whose composite
key collides with a bootstrap row, the dedup hook short-circuits: the
bootstrap row wins by default (it's human-validated), and the AI
extraction is logged to `state/ai_vs_curator_disagreements.jsonl` for
later adjudication. The user can flip this via
`config.yaml.challenge_mode: true`.
