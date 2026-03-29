# Changelog

All notable changes to TraitTrawler will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [4.3.0] — 2026-03-29

### Added
- **Shared extractor reference file** (`references/extractor_common.md`): Extracted 84 lines of shared rules (Universal Rules, Output Format, Compilation Tables, Constraints) from extractors A/B/C into a single reference file. Consensus orchestrator inlines it into each sub-agent prompt. Reduces per-extractor prompt by ~168 tokens (504 total per paper).
- **Dispatch `recommend` command**: Deterministic dispatch decision engine in `dispatch.py` returns JSON action list. Replaces ~500 tokens of Manager reasoning per dispatch cycle.
- **Dispatch `cleanup-stale` command**: Removes agent entries older than 30 minutes from `dispatch_state.json`, preventing pipeline deadlocks from crashed agents. Stale agents also flagged in `status` output.
- **Corrupt file handling**: `process_agent_output.py` now logs corrupt JSON files to `run_log.jsonl` and moves them to `state/corrupt/` instead of silently skipping.
- **Snapshot cleanup**: `session_manager.py` keeps only the 10 most recent state snapshots, deleting older ones automatically.
- **Learning file pruning**: At session start, keeps 20 most recent learning files and archives older ones to `state/learning_archive/`.
- **Canonical timestamp helper** (`state_utils.now_iso()`): Single source of truth for ISO 8601 UTC timestamps, eliminating 3 different format variants across scripts.
- **Shared DOI routing constants** (`state_utils.load_doi_routing()`): `DEFAULT_OA_LIKELY` and `DEFAULT_PAYWALLED` prefix sets consolidated from duplicate definitions in `dispatch.py` and `session_manager.py`.
- **Configurable confidence word map**: `csv_writer.py` reads `confidence_word_map` from `collector_config.yaml` with fallback to defaults (`high: 0.85, medium: 0.65, low: 0.4`).
- **Configurable taxonomy cache TTL**: `taxonomy_resolver.py` reads `taxonomy_cache_ttl_days` from config (default 90 days).

### Changed
- **Extractor agent prompts trimmed**: Each extractor (A/B/C) reduced to strategy-specific content only (~45-65 lines each, down from ~135). Shared rules loaded from `extractor_common.md` by the consensus orchestrator.
- **Writer taxonomy resolution**: Changed from inline GBIF WebFetch calls to subprocess invocation of `taxonomy_resolver.py` CLI. Maintains agent isolation (no Python imports of shared utilities).
- **Fetcher PDF validation strengthened**: Now checks page count > 0 and extracted text > 200 chars (via pdfplumber) in addition to magic byte check. Catches single-page paywall/placeholder PDFs.
- **Searcher bioRxiv clarification**: Explicit instruction that the bioRxiv MCP tool only supports date/category filters, not keyword search. Agent sets `biorxiv_results: 0` and moves on.
- **Dashboard regeneration frequency**: Changed from every 2 papers to every 10 papers (or session end).
- **Session report streaming**: `session_report.py` filters by `session_id` during JSONL read instead of loading entire file then filtering.
- **Version bumped to 4.3.0**.

### Fixed
- **File handle leaks**: 10+ bare `open()` calls across `dispatch.py`, `session_manager.py`, and `process_agent_output.py` replaced with `with` statements.
- **Security: exec() in session_manager.py**: `exec(open(config).read())` replaced with `ast.parse()` + `ast.literal_eval()` for safe config parsing.
- **Agent isolation: Dealer MUST NOT list**: Added prohibition on modifying `guide.md`, `extraction_examples.md`, `collector_config.yaml`, and `learning/` files. Dealer reads these but cannot write to them.
- **Agent isolation: Extractor sub-agent file access**: Fixed extractor prompts that told sub-agents to "read references/extractor_common.md first" (impossible — sub-agents can only access inlined content). Changed to "prepended above by the consensus orchestrator".
- **Timestamp format inconsistency**: Unified all scripts to use `state_utils.now_iso()` (canonical `%Y-%m-%dT%H:%M:%SZ`).

## [4.2.0] — 2026-03-28

### Added
- **Manager MUST NOT section**: Explicit prohibition list preventing the Manager from writing to `results.csv`, extracting data, searching for papers, fetching PDFs, reading large files into context, or creating root-level files. Addresses observed behavior where the Manager attempted CSV writes directly instead of delegating to the Writer agent.
- **Agent failure handling**: Per-agent retry/skip/report logic for all agent types (Searcher, Fetcher, Dealer, Writer). Max 1 automatic retry, 3+ errors triggers user prompt. All failures logged to `state/run_log.jsonl`.
- **Consensus vote tracking**: New `consensus_vote` field on every record (`1_1_0_NA` = Agent A agreed, B agreed, C disagreed, Opus not used). Tracks per-agent agreement through the full pipeline to `results.csv`.
- **Rejected record preservation**: Records that fail validation in `csv_writer.py` are now saved to `state/needs_attention.csv` with rejection reasons, instead of being silently dropped.
- **Processed.json sync check at startup**: Every session compares DOIs in `results.csv` against `processed.json` and backfills missing entries. Prevents the Searcher from re-finding papers already in the database after CSV bootstrap or manual edits.
- **State-driven autonomous dispatch**: Manager uses a dispatch table to keep Searcher, Fetcher, and Dealer streams running continuously in the background. Users no longer need to say "now search" or "now fetch" — the pipeline runs autonomously after session configuration.
- **Smart session config parsing**: Manager parses the user's invocation message for mode, target, and concurrency before asking questions. Only asks what's missing.
- **Project directory layout enforcement**: Explicit allowlist of permitted files/folders in the project root. All agents have MUST NOT rules prohibiting creation of ad-hoc files (reports, status files, temp folders) in the root.
- **Self-loading subagent inputs**: All subagents (Searcher, Fetcher, Dealer) read their own config files from the project root. Manager passes only the agent spec, task parameters, and project root path — never guide.md, config sections, or DOI lists inline.
- **File locking for concurrent state access**: `FileLock` class in `state_utils.py` using `fcntl.flock()` prevents race conditions between Searcher (adds to queue) and Fetcher (removes from queue) running concurrently. Wraps `add_to_queue()`, `remove_from_queue()`, and `update_processed()`.
- **Shrink detection in `safe_write_json()`**: Refuses to overwrite a state file if the new data has <50% of the existing entries, preventing accidental data loss.
- **PDF magic-number validation in Fetcher**: Fetcher now validates every download before saving — checks for `%PDF-` header, rejects HTML paywall pages, JavaScript-required landing pages, and undersized files. Prevents downstream Dealer/Extractor cycles from being wasted on garbage.
- **Finds JSON schema validation in Extractor Consensus**: Validates output structure before writing to `finds/` — checks for required keys (`doi`, `records` array, `extraction_timestamp`), per-record required fields (`species`, `extraction_confidence`, `consensus`, `consensus_vote`, `source_page`), and rejects prose or non-standard schemas (e.g., `consensus_records`, `consensus_results`, flat dicts). Normalizes agent output to the canonical schema.
- **End-to-end per-query yield tracking**: `source_query` field flows from Searcher → queue → Fetcher handoff → Dealer → `processed.json`. At session end, Manager reports top queries by records and lowest-yield queries, enabling intelligent prioritization of remaining queries.

### Changed
- **Manager context management**: Section 1b rewritten to use lightweight one-liners (`wc -l`, `grep -c`, `python3 -c`) for all state file checks. Manager never reads `guide.md`, `processed.json`, `queue.json`, or `search_log.json` into context.
- **Agent spawn prompts**: All four spawn prompts (Searcher, Fetcher, Dealer, Writer) rewritten to pass only agent spec + project root, not inline content.
- **Dealer no longer reads PDFs**: Dealer passes `pdf_path`, `document_type`, and `text_pages` to the Extractor. The Extractor Consensus agent reads the PDF once and distributes text to its 3 sub-agents.
- **Session config asks 3 questions**: Mode, target, and concurrency (was 2 — concurrency was previously skipped).
- **Continuous background streams**: Searcher, Fetcher, and Dealer all run with `run_in_background=true` and re-spawn immediately on return until exhausted.
- **Version bumped to 4.2.0**.

### Fixed
- **Manager writing to results.csv**: Added explicit MUST NOT prohibition. Only the Writer agent may touch results.csv, via SchemaEnforcedWriter.
- **Queue.json race condition**: Searcher (background, adds papers) and Fetcher (concurrent, removes papers) doing unsynchronized read-modify-write. Fixed with `FileLock` in `state_utils.py`.
- **Silent record loss**: `csv_writer.py` rejected records were `continue`d past with no preservation. Now saved to `state/needs_attention.csv`.
- **Hot start deduplication gap**: CSV bootstrap path populated results.csv but not processed.json, causing the Searcher to re-find every imported paper. Fixed in both setup_wizard.md (bootstrap script) and SKILL.md (startup sync check).
- **Project root clutter**: Agents creating ad-hoc report/status/temp files in the project root. Added directory layout allowlist and MUST NOT rules to all agent specs.

## [2.0.1] — 2026-03-28

### Fixed
- **Dead confidence anomaly check**: `check_confidence_anomaly()` in `verify_session.py` had a self-referential comparison (`mean < mean - 2*stdev`) that could never trigger. Now correctly flags batches where >30% of records fall below the 2-SD threshold, plus an absolute check for session means below 0.5.
- **Non-atomic CSV append**: `csv_writer.py` append path used separate read/write operations with no locking. Replaced with `fcntl.flock()` exclusive lock + `fsync()` for true atomic appends.
- **GBIF rate limiting missing**: `gbif_match()` and `gbif_family_species_count()` in `taxonomy_resolver.py` called the GBIF API without any delay between requests, risking IP bans. Added `time.sleep(RATE_LIMIT_DELAY)` before each call.
- **Dedup key inconsistency**: `build_dedup_keys()` and `make_dedup_key()` in `csv_writer.py` each defined their own `core_fields` set independently. Extracted shared `_CORE_FIELDS` constant and `_get_trait_fields()` helper to guarantee consistency.
- **JSON decode crash in `resilient_fetch()`**: `api_utils.py` did not handle non-JSON responses (HTML error pages, empty bodies) from APIs returning HTTP 200. Now catches `json.JSONDecodeError` and raises a descriptive `APIError`.
- **Retry-After header parsing**: `api_utils.py` only parsed `Retry-After` as seconds. Now handles both seconds and HTTP-date formats per RFC 7231.
- **Cross-filesystem rename failure**: `state_utils.py` used `os.rename()` which fails across filesystems. Replaced with `os.replace()`.
- **Silent PDF relocation failures**: `relocate_misplaced_pdfs()` in `pdf_utils.py` crashed on `OSError` from `shutil.move()`. Now catches errors, logs to stderr, and continues.
- **Silent logging failures**: `_log_retry()` in `api_utils.py` swallowed all exceptions. Now logs to stderr so disk/permission issues are visible.

### Added
- **GBIF rank validation**: `taxonomy_resolver.py` now rejects matches at ranks above SPECIES (GENUS, FAMILY, etc.) and flags them as `flag_higher_rank` instead of silently accepting family-level data as species-level.
- **Taxonomy cache TTL**: Cache entries in `taxonomy_resolver.py` now expire after 90 days (`CACHE_TTL_DAYS`). Stale entries are refreshed from GBIF on next access.

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
