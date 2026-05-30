# Example: Avian Body Mass

A second worked TraitTrawler **v6** project, showing how the same skill adapts to
a different taxon and trait — here, body mass (in grams) for birds.

## How a v6 project is configured

`config.yaml` is the whole configuration: a **trait**, a **taxon**, optional
**seed DOIs**, and runtime/model defaults. From a handful of seed papers the
skill *learns* the output schema, triage rules, query synonyms, and validation
hooks — you don't hand-author them. `guide.md` here is reference material
showing the kind of domain knowledge (units, measurement preferences, pitfalls)
the skill should discover on its own.

## Files

| File | Role | Purpose |
|------|------|---------|
| `config.yaml` | **configuration** | Trait, taxa, seed DOIs, runtime/model defaults — the v6 entry point |
| `guide.md` | reference | Units, which measurement to prefer, summary-statistic rules, common pitfalls |

## To run

1. Copy this folder somewhere (e.g. `~/avian-body-mass/`).
2. Open it in Claude Cowork with the TraitTrawler skill installed.
3. Say **"let's collect some data."** A short setup wizard confirms the trait
   and taxon for the project (recorded in `config.yaml` for reference),
   optionally takes seed DOIs, then initializes the project and begins learning
   from seed papers. The trait/taxa values to confirm:
   - **trait:** `body mass (grams)`
   - **taxa:** `Aves (birds)`
4. The skill proposes an output schema and validation hooks for your approval,
   then starts searching, fetching, and extracting in batches.

## Design note

This example is intentionally simpler than the Coleoptera one. Body mass is a
single numeric trait with few notation conventions, so the learned
`state/trait_profile.md` stays short. For traits with complex notation, multiple
measurement types, or domain-specific validation rules, the Coleoptera example
is the better template to study.

See the main [README](../../README.md) for the full pipeline.
