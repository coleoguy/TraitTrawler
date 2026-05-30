# Example: Coleoptera Karyotypes

A worked TraitTrawler **v6** project. It collects diploid chromosome numbers
(2n), sex chromosome systems, karyotype formulas, and cytogenetic method
details for beetles. This is the configuration behind the TraitTrawler
validation study (Blackmon 2026).

## How a v6 project is configured

`config.yaml` is the whole configuration: a **trait**, a **taxon**, optional
**seed DOIs**, and runtime/model defaults. You no longer hand-author search
queries or output columns. From a handful of seed papers the skill *learns*:

- the output schema (which columns to extract) → `state/trait_profile.md` §11
- triage rules and query synonyms → `state/trait_profile.md`
- validation hooks (range/notation checks) → `state/hooks/` (you approve each)

The reference docs below show the domain knowledge a mature karyotype project
converges on. In v6 you don't write them up front — the skill learns equivalent
knowledge as it reads papers. They're kept here as a worked illustration and a
sanity check on what the skill should rediscover.

## Files

| File | Role | Purpose |
|------|------|---------|
| `config.yaml` | **configuration** | Trait, taxa, seed DOIs, runtime/model defaults — the v6 entry point |
| `guide.md` | reference | Sex-chromosome notation, family-specific rules, validation checks, staining conventions |
| `extraction_examples.md` | reference | Worked examples: catalogue entries, dense tables, OCR artifacts |
| `csv_schema.md` | reference | The 40+-field output schema this study converged on |
| `db_scanner.py` | reference | A standalone CSV anomaly scanner from the study (22 cleanup passes). In v6 this role is filled by learned validation hooks. |

## To run

1. Copy this folder somewhere (e.g. `~/coleoptera-karyotypes/`).
2. Open it in Claude Cowork with the TraitTrawler skill installed.
3. Say **"let's collect some data."** A short setup wizard confirms the trait
   and taxon for the project (recorded in `config.yaml` for reference),
   optionally takes seed DOIs, then initializes the project and begins learning
   from seed papers. The trait/taxa values to confirm:
   - **trait:** `karyotype (diploid chromosome number 2n, sex chromosome system)`
   - **taxa:** `Coleoptera (beetles)`
4. The skill proposes an output schema and validation hooks for your approval,
   then starts searching, fetching, and extracting in batches.

Institutional PDF access is automatic in v6 via the bundled `pdfgetter`
(a multi-source cascade) — there is no proxy URL to configure.

See the main [README](../../README.md) for the full pipeline.
