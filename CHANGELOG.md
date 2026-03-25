# Changelog

All notable changes to TraitTrawler will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.0.0] — 2026-03-25

### Added
- **GBIF Taxonomic Intelligence (§16)**: Automatic species name validation against GBIF Backbone Taxonomy. Resolves synonyms to accepted names, auto-fills higher taxonomy, preserves original names in `notes`. Runs before deduplication to prevent synonym-induced phantom diversity. New fields: `accepted_name`, `gbif_key`, `taxonomy_note`. Configurable via `taxonomy_resolution` in `collector_config.yaml`.
- **Statistical QC (§17)**: Species accumulation curves with Chao1 estimator and 95% CI, Grubbs' test outlier detection for continuous traits, modal frequency detection for discrete traits, confidence distribution analysis, near-duplicate detection, session efficiency trends. Standalone script `scripts/statistical_qc.py` generates JSON summary and self-contained HTML report.
- **Campaign Planning (§18)**: Coverage analysis against GBIF family-level species counts, strategic recommendations (obtain leads, focus queries, citation chain, deprioritize low-yield families, trigger audit), session-remaining estimates. Output to `campaign_report.md`.
- **Bidirectional Smart Citation Chaining (§3b)**: Forward references + cited-by via OpenAlex with priority scoring (seed confidence, journal match, author overlap, recency, keyword density, abstract relevance). Yield tracking per source with coverage estimation.
- **Adaptive Triage Learning (§4b)**: Computes triage accuracy every 50 papers and suggests rule adjustments when false-negative or false-positive rates exceed threshold.
- **Standalone scripts directory**: `scripts/taxonomy_resolver.py` (GBIF API resolver with caching, batch processing, rate limiting) and `scripts/statistical_qc.py` (full QC pipeline).
- New reference files: `taxonomy.md`, `statistical_qc.md`, `campaign_planning.md`, `model_routing.md`, `knowledge_evolution.md`.
- `scipy` and `matplotlib` added to `requirements.txt`.

### Changed
- **Cross-paper deduplication**: Dedup key changed from `(doi, species, trait_fields)` to `(species, trait_fields)`. Same species with identical trait values across different papers are now deduplicated. Different trait values for the same species are kept as independent observations.
- **SKILL.md reduced to 351 lines**: Extracted §14 knowledge evolution (160 lines) to `references/knowledge_evolution.md` and §2 model routing detail to `references/model_routing.md` for better progressive disclosure.
- **Platform compliance**: Replaced `find /sessions -path` hack with `${CLAUDE_SKILL_DIR}` variable throughout. Pipeline now includes Taxonomy Check step between extraction and validation.
- `search_and_triage.md` expanded from 72 → 142 lines with smart chaining and adaptive triage.
- `extraction_and_validation.md` updated with §7g Taxonomy Check and revised dedup logic.
- `session_management.md` session-end sequence updated with statistical QC and campaign reporting.
- `csv_schema.md` updated with taxonomy intelligence fields.
- `config_template.yaml` updated with taxonomy fields and settings.
- `dashboard_generator.py` core fields exclusion set updated for new fields.

## [1.1.0] — 2026-03-24

### Added
- **Self-improving domain knowledge system (§14)**: Agent logs notation variants, new taxa, ambiguity patterns, and validation gaps to `state/discoveries.jsonl` during extraction, then proposes diff-formatted amendments to `guide.md` at session end for human approval. Full change history in `state/run_log.jsonl`.
- **Evaluation suite** (`evals/`): Five structured JSON test cases — setup wizard, triage accuracy, table extraction, session resume, and near-miss triage — following Anthropic's recommended eval format.
- **Post-batch verification script** (`skill/verify_session.py`): Deterministic checks for duplicates, schema compliance, confidence anomalies, required fields, cross-field consistency, and controlled vocabularies. Outputs JSON report to `state/verification_report.json`.
- **Darwin Core Archive export** (`skill/export_dwc.py`): Converts `results.csv` to DwC-A format (occurrence.txt, meta.xml, eml.xml) for GBIF/iDigBio interoperability. Supports `--zip` for `.dwca` archive output.
- **Provenance chain**: New fields `source_page`, `source_context`, and `extraction_reasoning` added to `csv_schema.md`, `config_template.yaml`, and both example configs for full record auditability.
- `session_id` field added to output schema and both example configs.
- **Multi-model routing (§2)**: Configurable model selection per pipeline stage — haiku for search/triage/state, sonnet for extraction/validation, opus as escalation-only fallback. Escalation triggers on low confidence, row-count mismatch, or OCR artifacts. Logged to `run_log.jsonl`.
- **Audit mode (§15)**: Self-cleaning data system that re-examines low-confidence records, guide-drift candidates, and statistical outliers by re-reading cached PDFs with current domain knowledge. Presents diffs for human approval. Tracks audit status per record (`audit_status`, `audit_session`, `audit_prior_values`). Can run on-demand or automatically every N sessions.
- **PDF-first mode (§3a)**: Detects unprocessed PDFs in `pdfs/` at startup and offers to extract from them directly, skipping search and triage. Supports user-supplied PDFs alongside the standard search pipeline.
- **Calibration phase (§0b)**: First-run learning from 3–5 seed papers before the first real session. Processes seed papers with aggressive §14 discovery logging, immediately updates `guide.md`, auto-generates `extraction_examples.md` with worked examples, and seeds the search queue via citation chaining. Optional but strongly recommended.

- **Session duration control (§1g, §9d)**: Agent asks user how long to run at session start. Accepts paper counts, time estimates, or presets. Long sessions checkpoint every 10 papers.
- **Context management (§9b-2)**: Explicit strategy to prevent context exhaustion — subagent delegation, checkpoint files, context-safe file reads, progressive re-reading of reference files after compaction.
- **Wizard self-research**: Setup wizard can research answers when user delegates questions — finds keywords, taxonomic groups, journals, and reporting conventions via OpenAlex/PubMed.
- `model: sonnet` and `effort: high` added to SKILL.md frontmatter.
- `session_id` added to `config_template.yaml` output_fields (was missing, present in examples).

### Changed
- **SKILL.md split for Anthropic compliance**: Monolithic 885-line spec reduced to 327-line core file with three reference files (`search_and_triage.md`, `extraction_and_validation.md`, `session_management.md`) following Anthropic's progressive disclosure pattern.
- **Skill description rewritten**: Third-person, comprehensive trigger terms, under Anthropic's recommended format.
- `sample_results.csv`: Confidence values changed from strings ("high"/"medium") to numeric floats (0.0–1.0).
- README updated with self-improving knowledge section, revised repo structure, build-from-source instructions.

### Fixed
- Removed phantom `validation/` directory from README repo structure.
- Removed references to deleted `agent/` and `traittrawler_skill_fixed/` directories.

## [1.0.0] — 2026-03-24

Initial public release accompanying the manuscript submission.

### Added
- Core autonomous agent: search → triage → retrieve → extract → validate → write pipeline
- 1,669 search queries covering 148 Coleoptera families × 11 cytogenetics keywords
- PDF retrieval cascade: Unpaywall → OpenAlex → Europe PMC → Semantic Scholar → institutional proxy
- 22 cross-field validation rules for karyotype data
- Leads tracking for papers needing manual PDF retrieval
- Self-contained HTML dashboard generator (Chart.js)
- Avian body mass example configuration in `examples/`
- Validation study: 5,339 records benchmarked against 4,959-record human-curated database
- GBIF taxonomy validation at session end
- Domain knowledge guide (`guide.md`) with Coleoptera karyotype notation conventions
