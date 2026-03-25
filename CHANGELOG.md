# Changelog

All notable changes to TraitTrawler will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

Initial public release accompanying the MEE manuscript submission.

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
