# TraitTrawler — Project Context

## What this is
TraitTrawler is a taxon- and trait-agnostic autonomous literature-mining agent that runs as a Claude Cowork skill. It searches PubMed/bioRxiv, retrieves PDFs, extracts structured trait data, and writes validated records to CSV. The skill itself contains no taxon-specific content — all project configuration lives in the user's project folder.

## Current state (2026-03-24)
- **Version:** 1.0.0, preparing for initial public release alongside MEE submission
- **Manuscript target:** Methods in Ecology and Evolution (Blackmon 2026)
- **Validation study:** complete — 5,339 AI records benchmarked against 4,959 human-curated Coleoptera karyotype records
- **Repo status:** public-ready; needs Zenodo DOI before advertising

## Architecture
The skill is fully generic. Project-specific configuration lives in the user's working folder:
- `collector_config.yaml` — taxa, trait, output fields, proxy URL
- `config.py` — search queries (taxon × keyword cross-product)
- `guide.md` — domain knowledge for extraction
- `extraction_examples.md` — optional worked examples for the trait

The skill bundle contains only:
- `SKILL.md` — agent behavior spec
- `dashboard_generator.py` — HTML dashboard generator
- `references/config_template.yaml` — blank project template
- `references/csv_schema.md` — generic field docs (paper metadata, quality, leads)

## Key files
| File | Role |
|:-----|:-----|
| `traittrawler_skill_fixed/` | Updated skill files ready to install |
| `examples/coleoptera-karyotypes/` | Complete Coleoptera karyotype config (validation study) |
| `examples/avian-body-mass/` | Complete avian body mass config (demonstration) |
| `examples/sample_results.csv` | Example output showing CSV schema |
| `validation/` | MEE validation study (data, R scripts, manuscript, figures) |

## Strategic context
This repo is part of Heath Blackmon's research program at TAMU Biology. It supports:
- The **OpenClaw** manuscript (autonomous AI as lead investigator)
- The **Google.org AI for Science** grant application (deadline April 17, 2026)
- The broader **AI-Native Biology** initiative at TAMU

## Next actions
- [ ] Register Zenodo DOI (flip GitHub integration on, tag v1.0.0 release)
- [ ] Attach `.skill` file to GitHub Release as downloadable asset
- [ ] Copy `traittrawler_skill_fixed/` into installed skill location (`.claude/skills/traittrawler/`)
- [ ] Genericize `dashboard_generator.py` (currently has some hardcoded karyotype chart types)
- [ ] Submit MEE manuscript

## Second-project workflow
Each project = one folder. To start a new project:
1. Create a new folder
2. Open it in Cowork with TraitTrawler installed
3. The setup wizard (§0) generates all config files from user answers
4. Or copy an example from `examples/` and edit
