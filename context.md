# TraitTrawler — Project Context

## What this is
TraitTrawler is a taxon- and trait-agnostic autonomous literature-mining agent that runs as a Claude Cowork skill. It searches PubMed, bioRxiv, OpenAlex, and Crossref, retrieves PDFs, extracts structured trait data, and writes validated records to CSV. The skill itself contains no taxon-specific content — all project configuration lives in the user's project folder.

## Current state (2026-03-24)
- **Version:** 1.1.0 (all Anthropic compliance and enhancement work complete)
- **Manuscript target:** Methods in Ecology and Evolution (Blackmon 2026)
- **Validation study:** complete — 5,339 AI records benchmarked against 4,959 human-curated Coleoptera karyotype records
- **Repo status:** public-ready; needs Zenodo DOI before advertising

## Architecture
The skill is fully generic. Project-specific configuration lives in the user's working folder:
- `collector_config.yaml` — taxa, trait, output fields, proxy URL, batch_size, pause triggers, validation rules
- `config.py` — search queries (taxon × keyword cross-product)
- `guide.md` — domain knowledge for extraction
- `extraction_examples.md` — optional worked examples for the trait

The skill bundle contains:
- `SKILL.md` — agent behavior spec (327 lines, under Anthropic's 500-line limit)
- `dashboard_generator.py` — HTML dashboard generator (auto-detects trait-specific columns)
- `verify_session.py` — post-batch deterministic verification script
- `export_dwc.py` — Darwin Core Archive export
- `references/csv_schema.md` — generic field docs (paper metadata, quality, leads, provenance)
- `references/config_template.yaml` — blank project template
- `references/search_and_triage.md` — §3–4: Search and triage logic
- `references/extraction_and_validation.md` — §5–8: Fetch, extract, validate, write
- `references/session_management.md` — §9–13: State, reporting, dashboard
- `references/audit_mode.md` — §15: Self-cleaning data audit system

## Key files
| File | Role |
|:-----|:-----|
| `skill/SKILL.md` | Core agent spec (~490 lines) with §0 setup/calibration, §1 startup, §2 model routing, §3 main loop, §14 self-improving knowledge, §15 audit mode, stop conditions |
| `skill/references/` | Progressive disclosure: search_and_triage.md, extraction_and_validation.md, session_management.md, csv_schema.md, config_template.yaml |
| `skill/verify_session.py` | Post-batch verification: duplicates, schema, confidence anomalies, cross-field checks |
| `skill/export_dwc.py` | Darwin Core Archive export for GBIF/iDigBio interoperability |
| `evals/` | 5 structured JSON test cases (setup wizard, triage accuracy, table extraction, session resume, near-miss triage) |
| `examples/coleoptera-karyotypes/` | Complete Coleoptera karyotype config + detailed schema + db_scanner.py |
| `examples/avian-body-mass/` | Complete avian body mass config (demonstration) |
| `examples/sample_results.csv` | Example output showing CSV schema (numeric confidence, session_id) |
| `TraitTrawler_Review_and_Recommendations.docx` | Anthropic submission review document |

## v1.1.0 changes (2026-03-24)
All items from the Anthropic review recommendations have been implemented:
- [x] Split SKILL.md from 885 → 327 lines with 3 reference files (progressive disclosure)
- [x] Rewrote skill description (third-person, comprehensive triggers)
- [x] Created evaluation suite (5 JSON test cases in evals/)
- [x] Created verify_session.py (deterministic post-batch verification)
- [x] Added provenance chain (source_page, source_context, extraction_reasoning)
- [x] Implemented self-improving domain knowledge system (§14 with discoveries.jsonl)
- [x] Created Darwin Core Archive export (export_dwc.py)
- [x] Updated all example configs with session_id and provenance fields
- [x] Fixed sample_results.csv (numeric confidence, session_id)
- [x] Updated README (repo structure, self-improving knowledge section, build instructions)
- [x] Updated CHANGELOG with v1.1.0 entry
- [x] Added multi-model routing (§2): haiku for search/triage, sonnet for extraction, opus escalation-only
- [x] Added audit mode (§15): self-cleaning data via re-extraction of low-confidence, guide-drift, and outlier records
- [x] Fixed outlier detection for discrete numeric data (modal frequency instead of SD for chromosome counts)
- [x] Added subagent batching guidance to §2 implementation
- [x] Created model routing validation eval (eval_model_routing.json — 4 test cases)
- [x] Added calibration phase (§0b): seed paper learning, citation queue seeding, auto-generated extraction_examples.md
- [x] Added PDF-first mode (§3a): direct extraction from user-supplied PDFs
- [x] Added wizard self-research: agent researches answers when user delegates questions
- [x] Added model:sonnet and effort:high to SKILL.md frontmatter
- [x] Added context management strategy (§9b-2): subagent delegation, checkpointing, context-safe file reads
- [x] Added session duration control (§1g/§9d): user sets paper count, time estimate, or preset
- [x] Fixed missing session_id in config_template.yaml output_fields
- [x] Updated README with current repo structure, calibration docs, session control docs

## Strategic context
This repo is part of Heath Blackmon's research program at TAMU Biology. It supports:
- The **OpenClaw** manuscript (autonomous AI as lead investigator)
- The **Google.org AI for Science** grant application (deadline April 17, 2026)
- The broader **AI-Native Biology** initiative at TAMU

## Next actions
- [ ] Register Zenodo DOI (flip GitHub integration on, tag v1.1.0 release)
- [ ] Rebuild .skill archive and attach to GitHub Release
- [ ] Submit MEE manuscript
- [ ] Send to Anthropic with review document

## Second-project workflow
Each project = one folder. To start a new project:
1. Create a new folder
2. Open it in Cowork with TraitTrawler installed
3. The setup wizard (§0) generates all config files from user answers
4. Or copy an example from `examples/` and edit
