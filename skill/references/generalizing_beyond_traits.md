# Generalizing Beyond Trait Extraction

TraitTrawler v6's architecture is not specific to phenotype harvesting.
The same seven-phase pattern — `learn → propose schema → search → fetch
→ extract → verify → gate` — is a general template for autonomous AI-
driven scientific data collection.

This document sketches the map so the skill is recognizable to readers
who want to build the equivalent for other scientific tasks.

## What is trait-specific vs what is general

**Trait-specific (localized in 3 files):**
- `state/trait_profile.md` — the learned domain knowledge
- `state/schema.json` — the output columns + trait-specific hook names
- a handful of optional functions in `scripts/hooks.py` registered as
  trait_hooks

**General (everything else):**
- The 7-phase state machine in `SKILL.md`
- The subagent roster (searcher, fetcher, triage, extractor,
  semantic_verifier, structurer, adjudicator)
- `scripts/verify_quote.py` — deterministic grounding
- `scripts/ledger.py` — audit log
- The review workflow
- The talkative style

## Template instantiations

### Clinical trial outcome harvesting
- Trait → "primary outcome measures for condition X"
- Seed papers → 10 registered trials' publications
- Schema columns proposed: `trial_id`, `primary_outcome`,
  `units`, `effect_size`, `ci_low`, `ci_high`, `p_value`, `n`
- Trait-specific hooks: CI consistency, N positivity, p-value range

### Materials science property extraction
- Trait → "thermal conductivity of compound X"
- Seed papers → 5-10 recent ACS/RSC papers
- Schema: `compound`, `temperature_k`, `conductivity_w_mk`,
  `uncertainty`, `measurement_method`
- Trait-specific hooks: temperature positive, conductivity within
  material-class bounds, method enum valid

### Ecology field-observation mining
- Trait → "population density of species X in biome Y"
- Seed papers → 10 field-study publications
- Schema: `species`, `site_coords`, `density_per_ha`, `year`,
  `survey_method`
- Trait-specific hooks: coords valid, density non-negative, method
  enum

### Drug dosing from case reports
- Trait → "on-label vs off-label pediatric dosing"
- Seed papers → 10 case reports
- Schema: `drug`, `age_months`, `weight_kg`, `dose_mg_per_kg`,
  `indication`, `outcome`
- Trait-specific hooks: age plausible, dose within FDA range +/-,
  indication resolves to ICD-10

## The point

When Heath pitches this to peers at Google / Anthropic, the claim is
stronger than "we built a good karyotype extractor." It is "we built
an extraction pipeline where the trait is a plug-in, the grounding is
a protocol invariant, and the entire process is autonomous with
narrated pause points." That pattern — not the karyotype data it first
produced — is the contribution.

For the pipeline to be recognizably general, new projects should:
1. Start from phase 0 of a fresh project with a new `config.yaml`.
2. Add 5–10 seed papers and let the `trait_learner` build a fresh
   `trait_profile.md`.
3. Add any needed trait-specific hooks to `scripts/hooks.py` and
   register them in the generated `schema.json`.
4. That's it. No code in the main pipeline should need to change.

If a new trait requires changes to `SKILL.md` or any subagent spec,
that is a generality regression and should be refactored back into
`trait_profile.md` / schema / hooks.
