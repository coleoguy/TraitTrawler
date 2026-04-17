# Hooks Reference

Hooks are the deterministic Python gates that run on every proposed Row
before it reaches `results.csv`. They are the concrete expression of the
"domain logic as code, not prompt" principle.

All hooks live in `scripts/hooks.py`. Each hook is a function with the
signature:

```python
def hook_name(row: Row, context: HookContext) -> HookResult
```

`HookResult` is either `Pass()` or `Fail(reason: str, severity:
str="hard")`. Hard failures route to the Adjudicator; soft failures
write a note to the ledger but do not block.

## Hook categories

### 1. Grounding hooks (domain-agnostic; ALWAYS ON)

- **`hook_has_sha256_and_page`** — Row must carry a non-null `sha256`
  and integer `page`. The Extractor should always provide these;
  absence is a bug.
- **`hook_has_verbatim_quote`** — Row must carry a non-empty
  `verbatim_quote`.
- **`hook_quote_verified`** — `verify_quote.py` must have already
  marked this claim as verified (flag set in ledger). No backdoor.
- **`hook_cited_value_in_quote`** — For numeric trait fields, the
  literal value (or a canonical string form) must appear in
  `verbatim_quote`. Prevents the "value was inferred not stated"
  failure mode.

### 2. Schema hooks (domain-agnostic; ALWAYS ON)

- **`hook_schema_valid`** — Row passes JSON Schema validation against
  `state/schema.json`.
- **`hook_enums_canonical`** — Enum columns use the canonical label
  from `trait_profile.md`, not a synonym.
- **`hook_no_null_required`** — Every column marked `required: true`
  in the schema has a non-null value.

### 3. Dedup hooks (domain-agnostic; ALWAYS ON)

- **`hook_doi_composite_unique`** — `(doi, canonical_species, trait_key)`
  is not already in the ledger. Catches compilation-table duplication.
- **`hook_sha256_dedup`** — A row with the same `(sha256, page,
  canonical_species, trait_key)` is not already written. Catches
  re-extraction accidents.

### 4. Taxonomy hook (domain-agnostic; ALWAYS ON)

- **`hook_gbif_resolved`** — `canonical_species` resolves to a valid
  GBIF backbone key. If unresolved, fail hard so the user sees it
  rather than silently accepting obsolete names.

### 5. Trait-specific hooks (loaded from `state/schema.json`)

The schema declares trait-specific validators. `hooks.py` picks these
up at startup. Examples for the karyotype domain:

- **`hook_2n_range`** — `diploid_2n` must be in `[2, 500]`.
- **`hook_hac_consistency`** — If `diploid_2n`, `haploid_autosome_count`,
  and `sex_chrom_count` are all present, the arithmetic
  `HAC == (2n - sex_chrom_count) / 2` must hold. Catches the 2n-vs-HAC
  swap that v5 produced ~5% of the time.
- **`hook_sex_system_regex`** — If `verbatim_quote` matches the complex-
  sex-system regex (`X[_\s]?[1-9]` or `neo[_\s-]?XY` or
  `multiple sex chrom`), then `sex_system` cannot be `XY` or `XX`.
  Catches the v5 failure where X₁X₂Y got silently flattened to XY.

### How to add a new trait-specific hook

1. Define the function in `scripts/hooks.py` following the signature
   convention. Return `Pass()` / `Fail(reason)`.
2. Register it in `state/schema.json` under `trait_hooks`:
   ```json
   {
     "trait_hooks": ["hook_my_new_check"]
   }
   ```
3. Add an entry to `trait_profile.md` §10 explaining what the hook
   enforces.
4. The skill auto-loads registered hooks on next Manager turn.

## Hook output into the ledger

Every hook's verdict is recorded in the row's ledger entry under
`hook_results`. This lets downstream analysis answer questions like
"how often does `hook_hac_consistency` fail, and in what kinds of
papers?" — which is the active-learning signal for improving the
pipeline over time.
