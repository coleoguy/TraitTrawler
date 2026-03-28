# TraitTrawler — Project Context

## What this is
TraitTrawler is a taxon- and trait-agnostic autonomous literature-mining agent that runs as a Claude Cowork skill. It searches PubMed, bioRxiv, OpenAlex, and Crossref, retrieves PDFs, extracts structured trait data, and writes validated records to CSV. The skill itself contains no taxon-specific content — all project configuration lives in the user's project folder.

## Current state (2026-03-25)
- **Version:** 2.0.0 (taxonomic intelligence, statistical QC, campaign planning)
- **Manuscript target:** TBD (Blackmon 2026)
- **Validation study:** complete — 5,339 AI records benchmarked against 4,959 human-curated Coleoptera karyotype records
- **Repo status:** public-ready; needs Zenodo DOI before advertising

## Architecture
The skill is fully generic. Project-specific configuration lives in the user's working folder:
- `collector_config.yaml` — taxa, trait, output fields, proxy URL, batch_size, pause triggers, validation rules
- `config.py` — search queries (taxon × keyword cross-product)
- `guide.md` — domain knowledge for extraction
- `extraction_examples.md` — optional worked examples for the trait

The skill bundle contains:
- `SKILL.md` — agent behavior spec (351 lines, under Anthropic's 500-line limit)
- `dashboard_generator.py` — HTML dashboard generator (auto-detects trait-specific columns)
- `verify_session.py` — post-batch deterministic verification script
- `export_dwc.py` — Darwin Core Archive export
- `scripts/taxonomy_resolver.py` — GBIF Backbone Taxonomy API resolver with caching
- `scripts/statistical_qc.py` — Statistical QC pipeline (Chao1, Grubbs, accumulation curves)
- `references/csv_schema.md` — generic field docs (paper metadata, quality, leads, provenance, taxonomy intelligence)
- `references/config_template.yaml` — blank project template
- `references/search_and_triage.md` — §3–4: Search, smart citation chaining, adaptive triage
- `references/extraction_and_validation.md` — §5–8: Fetch, extract, taxonomy check, validate, write
- `references/session_management.md` — §9–13: State, reporting, dashboard, QC, campaign
- `references/taxonomy.md` — §16: GBIF taxonomic intelligence
- `references/statistical_qc.md` — §17: Statistical QC and rarefaction
- `references/campaign_planning.md` — §18: Coverage analysis and strategic recommendations
- `references/model_routing.md` — §2: Multi-model routing with escalation
- `references/knowledge_evolution.md` — §14: Self-improving domain knowledge
- `references/audit_mode.md` — §15: Self-cleaning data audit system
- `references/troubleshooting.md` — Common failure modes and recovery strategies

## Key files
| File | Role |
|:-----|:-----|
| `skill/SKILL.md` | Core agent spec (~351 lines) with §0 setup/calibration, §1 startup, §2 model routing, §3 main loop, §16 taxonomy, §17 QC, §18 campaign |
| `skill/references/` | Progressive disclosure: 11 reference files covering search, extraction, taxonomy, QC, campaign, model routing, knowledge, audit, troubleshooting |
| `skill/scripts/` | Standalone Python scripts: taxonomy_resolver.py (GBIF API), statistical_qc.py (Chao1, Grubbs, accumulation) |
| `skill/verify_session.py` | Post-batch verification: duplicates, schema, confidence anomalies, cross-field checks |
| `skill/export_dwc.py` | Darwin Core Archive export for GBIF/iDigBio interoperability |
| `evals/` | 5 structured JSON test cases (setup wizard, triage accuracy, table extraction, session resume, near-miss triage) |
| `examples/coleoptera-karyotypes/` | Complete Coleoptera karyotype config + detailed schema + db_scanner.py |
| `examples/avian-body-mass/` | Complete avian body mass config (demonstration) |
| `examples/sample_results.csv` | Example output showing CSV schema (numeric confidence, session_id) |
| `tests/test_verify_and_export.py` | Runnable tests for verify_session.py and export_dwc.py (8 tests) |
| `requirements.txt` | Python dependencies for standalone use |
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

## v1.1.1 changes (2026-03-25)
- [x] Created runnable test suite (`tests/test_verify_and_export.py`) — 8 tests covering verify_session.py and export_dwc.py with synthetic data
- [x] Added `requirements.txt` for standalone Python dependency installation
- [x] Added API rate-limiting guidance to both example config.py files
- [x] Created `skill/references/troubleshooting.md` — common failure modes and recovery (PDF retrieval, API rate limits, state corruption, performance)
- [x] Removed all journal-specific references from repository (CITATION.cff, README, CHANGELOG, context, SKILL.md, evals, examples)
- [x] Rebuilt `traittrawler.skill` archive with all v1.1.0 + v1.1.1 content (was stale)
- [x] Fixed README build command to include verify_session.py and export_dwc.py
- [x] Added troubleshooting.md to SKILL.md pipeline stage table
- [x] Added usage tracking (§10b in session_management.md): model-tier call counts, pages processed, records/call efficiency metric, cumulative logging to run_log.jsonl
- [x] Added mid-session correction pathway (§14f): stop → fix guide.md → offer warm re-extraction of current-session records from cached PDFs → log correction event
- [x] Added opus escalation trigger for structural guide amendments (§14c): new canonical vocab entries, rule conflicts, and category redefinitions escalate to opus
- [x] Added recent records feed to dashboard: scrollable table of last 25 records showing species, family, trait fields, confidence (color-coded), source, and paper reference. Flagged records marked with icon. Most recent on top for live monitoring.
- [x] Fixed pre-existing bug in dashboard_generator.py: None date keys in Counter caused crash on sorted()
- [x] Added session_id, source_page, source_context, extraction_reasoning to _CORE_FIELDS exclusion set (were incorrectly eligible for trait charts)

## v2.0.0 changes (2026-03-25)
Major feature release: taxonomic intelligence, statistical QC, campaign planning, and platform compliance.

### New features
- [x] **GBIF Taxonomic Intelligence (§16)**: Automatic species name validation against GBIF Backbone Taxonomy — synonym resolution, accepted-name normalization, higher taxonomy auto-fill. Original names preserved in `notes`. Runs BEFORE deduplication so synonyms don't create phantom diversity. New fields: `accepted_name`, `gbif_key`, `taxonomy_note`. Full spec in `references/taxonomy.md`.
- [x] **Statistical QC (§17)**: Species accumulation curves with Chao1 estimator, Grubbs' outlier detection for continuous traits, modal frequency for discrete traits, confidence distribution analysis, near-duplicate detection, session efficiency trends. Script: `scripts/statistical_qc.py`. Runs at session end + on-demand. Full spec in `references/statistical_qc.md`.
- [x] **Campaign Planning (§18)**: Coverage analysis against GBIF family-level species counts, strategic recommendations (obtain leads, focus queries, citation chain, deprioritize low-yield, audit), session-remaining estimates. Output: `campaign_report.md`. Full spec in `references/campaign_planning.md`.
- [x] **Bidirectional Smart Citation Chaining (§3b)**: Forward references + cited-by via OpenAlex with priority scoring (seed confidence, journal match, author overlap, recency, keyword density, abstract relevance). Yield tracking per source with coverage estimation.
- [x] **Adaptive Triage Learning (§4b)**: Computes triage accuracy every 50 papers and suggests rule adjustments when false-negative or false-positive rates exceed threshold.
- [x] **Standalone scripts directory**: `scripts/taxonomy_resolver.py` (301 lines) and `scripts/statistical_qc.py` (533 lines) — both executable standalone or called by the agent.

### Changed
- [x] **Cross-paper deduplication**: Dedup key changed from `(doi, species, trait_fields)` to `(species, trait_fields)` — enables dedup across papers. Different trait values for the same species from different papers are kept as independent observations.
- [x] **SKILL.md reduced to 351 lines**: Extracted §14 (knowledge evolution, 160 lines) to `references/knowledge_evolution.md` and §2 detail to `references/model_routing.md`.
- [x] **Platform compliance**: Replaced fragile `find /sessions -path` hack with `${CLAUDE_SKILL_DIR}` variable throughout. Added `scipy` to dependency install. Updated pipeline to include Taxonomy Check step.
- [x] Updated `config_template.yaml` with taxonomy fields and `taxonomy_resolution` setting.
- [x] Updated `csv_schema.md` with taxonomy intelligence fields.
- [x] Updated `dashboard_generator.py` core fields exclusion set for new fields.
- [x] Updated `search_and_triage.md` from 72 → 142 lines with smart chaining + adaptive triage.
- [x] Updated `extraction_and_validation.md` with §7g Taxonomy Check and new dedup logic.
- [x] Updated `session_management.md` session-end sequence with statistical QC and campaign reporting.

### New files
- `skill/scripts/taxonomy_resolver.py` — GBIF API lookup with caching, batch processing, rate limiting
- `skill/scripts/statistical_qc.py` — Full QC pipeline: Chao1, Grubbs, accumulation curves, HTML reports
- `skill/references/taxonomy.md` — §16 GBIF taxonomy integration spec (155 lines)
- `skill/references/statistical_qc.md` — §17 statistical QC spec (149 lines)
- `skill/references/campaign_planning.md` — §18 campaign planning spec (151 lines)
- `skill/references/model_routing.md` — §2 model routing detail (65 lines)
- `skill/references/knowledge_evolution.md` — §14 self-improving knowledge (160 lines)

### Archive
- Rebuilt `traittrawler.skill` — 21 files, 213 KB, includes new `scripts/` directory

## v2.0.1 changes (2026-03-25)
Platform compliance fixes based on external code review.

- [x] Renamed skill from `traittrawler` to `trait-trawler` (kebab-case per Anthropic convention)
- [x] Added `allowed-tools` frontmatter field scoping tool access (Bash, Read, Write, Edit, etc.)
- [x] Added `compatibility` field with Python version, dependencies, and degradation behavior (no Chrome → OA only)
- [x] Added `metadata` block with author and version in frontmatter
- [x] Improved description: added biological specificity (karyotype, morphometric, life-history), negative triggers (not for literature review, data viz, paper summaries), stays under 1,024 chars
- [x] Restructured eval suite into Anthropic's recommended three-category taxonomy: `trigger_tests.json` (7 positive + 5 negative), `functional_tests.json` (6 tests), `performance_tests.json` (4 A/B comparisons). Legacy `eval_*.json` files retained for backward compatibility.
- [x] Updated all eval files: `skills` field changed from `traittrawler` to `trait-trawler`
- [x] SKILL.md: 372 lines, 2,050 words (under both 500-line and 5,000-word limits)
- [x] Rebuilt `traittrawler.skill` archive — 21 files

## v2.0.2 changes (2026-03-25)
Best-practices compliance pass based on review against `claude_skill_best_practices.md`.

- [x] Added execute-vs-read annotation table for all 5 scripts in SKILL.md §1e — prevents agent from reading 500+ line scripts into context
- [x] Added TOC to `references/extraction_and_validation.md` (387 lines, was missing per >300-line rule)
- [x] Added TOC to `references/session_management.md` (446 lines, was missing per >300-line rule)
- [x] Added "When to load" column to pipeline stage table in SKILL.md — each reference file now has explicit load semantics
- [x] Added `argument-hint` frontmatter field to SKILL.md
- [ ] Remove legacy `eval_*.json` files from evals/ (or reference them from SKILL.md)
- [ ] Run description optimization loop via `run_loop.py` (trigger_tests.json exists but not yet benchmarked)
- [ ] Generate baseline comparison data for performance_tests.json evals

## v2.0.3 changes (2026-03-25)
Dry-run simulation fixes: traced full fresh-install execution path through Cowork and fixed all identified failures.

- [x] Fixed `taxonomy_resolver.py` invocation in SKILL.md §1e — was `--project-root .` (nonexistent arg), now `--csv results.csv --species-column species --cache state/taxonomy_cache.json`
- [x] Fixed `export_dwc.py` invocation in SKILL.md §1e — was missing required `--output-dir` arg
- [x] Fixed MCP tool name documentation in SKILL.md §1a — added note that MCP names vary by environment, match by suffix after last `__`
- [x] Fixed `pause_triggers` format in `config_template.yaml` — was flat key-value (`confidence_below: 0.6`), now structured format matching session_management.md §9c (`field`, `operator`, `value`, `action`)
- [x] Fixed `$SKILL_DIR` variable typo in extraction_and_validation.md §8b — replaced with note that script is already in project root from §1e copy step
- [x] Added subagent mandate to calibration.md Step 3 — prevents context pressure from 3–5 rapid seed paper extractions accumulating PDF text in main context
- [x] Added calibration-to-session-1 transition logic in SKILL.md §0b — explicit flow: §0 → §0b → §1 → §3 in same invocation, §1f still applies

## Bug fixes from first production run (2026-03-25)

### 1. Dashboard stopped updating after initial generation
§13 said "every 10 papers — alongside §10" but §10, §9b, and §3b had zero mention of dashboard regeneration. Agent follows those sections during its loop and never re-reads §13. Fix: added `python3 dashboard_generator.py --project-root .` to §10, §9b, and §3b.

### 2. State desync — processed.json vs results.csv
Large batch writes succeeded for CSV but processed.json/search_log.json updates were incomplete. No verification existed. Fix: added §8b state sync check (extraction_and_validation.md) — runs after every batch write, auto-patches missing DOIs.

### 3. Duplicate dict key crash in generated batch write code
Agent improvised scripts setting `flag_for_review` twice (base dict + loop). Fix: added code generation guardrails to §8a requiring use of the template verbatim.

### 4. Context window exhaustion during wizard + calibration
The design mandated §0 → §0b → §1 → §3 all in one invocation (SKILL.md line 139). Wizard (9 Q&A rounds, possible research) + calibration (3-5 seed papers + knowledge review + citation seeding + example generation) + §1 startup (reads all config/state files) + §3 (reads extraction_and_validation.md 453 lines) simply doesn't fit. Three fixes:
- Wizard + calibration now end with a checkpoint flag (`state/calibration_complete.json`) and tell the user to start a new conversation. §1 detects the checkpoint and acknowledges it.
- Delegated wizard research ("you figure it out") now uses haiku subagents — API calls, abstract reads, and intermediate reasoning happen in isolated context that's discarded after returning the answer.
- Added explicit instruction to only read calibration.md during §0/§0b — no pre-loading of extraction or session management reference files.

### 5. CSV column shift mid-session
Template code read `fieldnames` from `collector_config.yaml` on every write. If the agent's YAML parsing varied between writes (different field order, missing field), later rows would have different column positions than the header. `csv.DictReader` silently absorbs this by mapping values to wrong field names, so `verify_session.py` never caught it. Two fixes:
- Template code in §8a now reads fieldnames from the existing CSV header (not config) for all writes after the first. This anchors column order to the header row.
- Added `check_column_count()` to `verify_session.py` — reads raw CSV with `csv.reader`, compares field count per row against header, flags mismatches as errors. Runs first in the check sequence.
- Added explicit instruction to always use `csv.DictWriter`, never string concatenation.

### 6. Agent writing to wrong CSV file after calibration
The wizard asked "What should I call the output CSV file?" (Q6) and stored the answer in `collector_config.yaml` as `output_csv`. The §8 prose said "append to the `output_csv` path from config" while the template code hardcoded `path = "results.csv"`. Calibration followed the template → wrote to `results.csv`. Main collection followed the prose → read `output_csv` from config → wrote to a different file. Dashboard, verify_session.py, state sync, campaign planner, and taxonomy resolver all hardcode `results.csv`, so everything downstream only saw calibration data. Fix: removed wizard Q6 entirely, removed `output_csv` from config_template.yaml, hardcoded `results.csv` in §8 prose. The filename is no longer configurable — 15+ locations depend on it.

### Files changed
- `skill/SKILL.md` — removed wizard Q6; dashboard regen in §3b; broke wizard/calibration into separate session; added reference file loading restriction for §0/§0b; added calibration checkpoint detection to §1
- `skill/references/calibration.md` — updated completion report, session-break instruction, subagent research
- `skill/references/config_template.yaml` — removed `output_csv` field, added comment explaining results.csv is fixed
- `skill/references/session_management.md` — dashboard regen in §10 and §9b
- `skill/references/extraction_and_validation.md` — §8 hardcodes results.csv; §8a reads header from existing CSV; §8b state sync; code generation guardrails; old §8b→§8c
- `skill/references/troubleshooting.md` — state desync + duplicate key entries
- `skill/verify_session.py` — added `check_column_count()` raw-line field count check

## v2.0.4 changes (2026-03-25)
Best-practices compliance audit against `claude_skill_best_practices.md`.

- [x] Added `# PURPOSE: Execute this script. Do not read it into context.` annotation to all 5 Python scripts (§11 requirement: every script must clarify execute vs. read)
- [x] Renamed `expected_behavior` → `expectations` in all eval JSON files to match §15 evals.json schema
- [x] Created canonical `evals/evals.json` with 4 representative test cases per §2 directory architecture requirement
- [x] Expanded trigger_tests.json from 7+5 → 10+10 (§16 recommends 10 should-trigger, 10 should-not-trigger)
- [x] Added 5 near-miss negative trigger tests (single-paper PDF summary, spreadsheet editing, manuscript drafting, statistical analysis, conceptual synthesis) — these are the highest-value tests per §16
- [x] Updated evals/README.md with correct field names and expanded trigger test counts
- [ ] Run description optimization loop via `run_loop.py` (trigger_tests.json ready but not yet benchmarked)
- [ ] Generate baseline comparison data for performance_tests.json evals
- [ ] Clean up repo: remove tracked `traittrawler.skill` and `untitled folder/` from git

### Audit findings — no action needed (already compliant)
- SKILL.md is 413 lines (under 500-line limit) ✓
- Description is 133 words (within 75–200 range) ✓
- Zero ALL-CAPS emphasis markers (ALWAYS/NEVER/CRITICAL/IMPORTANT) in SKILL.md ✓
- All reference files >300 lines have TOCs (extraction_and_validation.md, session_management.md) ✓
- Every reference file is mentioned in SKILL.md with what it contains + when to load ✓
- Progressive disclosure: 11 reference files loaded on-demand, SKILL.md is the navigation layer ✓
- Atomic writes pattern used for all JSON state files ✓
- State written after every unit of work, not just batch end ✓
- Single-item failures never abort pipeline (§12 error handling) ✓
- needs_attention mechanism exists (state/needs_attention.csv) ✓
- Session protocol section present (§11 Session End + Stop Conditions) ✓
- context.md convention used for multi-session calibration data ✓
- `${CLAUDE_SKILL_DIR}` used for all bundled file references ✓
- `disable-model-invocation` not set (correct — this skill should auto-trigger) ✓
- `allowed-tools` follows least-privilege ✓
- Voice is imperative + explanatory throughout ✓
- Negative boundary clause present in description (differentiates from deepscholar) ✓

## v4.0.0 — Multi-Agent Architecture Rebuild (2026-03-27)

The v2/v3 monolithic SKILL.md approach hit a ceiling: context exhaustion, CSV corruption from concurrent writes, state desync, and fragile error recovery. Heath designed a new multi-agent architecture (block diagram) that fundamentally restructures TraitTrawler around dedicated agents with file-based communication.

**Full spec**: `ARCHITECTURE_v4.md`

### Key changes
- **6 dedicated agents**: Opus-Manager (coordinator), Sonnet-Searcher, Sonnet-PDF Fetcher, Sonnet-Dealer, Sonnet-Extractor (3 sub-agents), Sonnet-Writer
- **3 on-demand agents**: Setup Wizard, Data QC, Handle PDFs
- **Consensus by default**: Every paper gets 3 independent extraction passes with majority-rule voting (was optional, low-confidence-only trigger)
- **File-based queues**: `finds/`, `ready_for_extraction/`, `learning/` folders replace shared mutable JSON state
- **Single CSV writer**: Only the Writer agent touches results.csv, eliminating all concurrent-write bugs
- **Simpler model routing**: Opus manages, Sonnet works. No haiku tier.

### Implementation plan (8 phases)
1. Folder structure and contracts
2. Sonnet-Writer (build first — safest, most critical)
3. Sonnet-Extractor (3-agent consensus engine)
4. Sonnet-Dealer (thin coordinator)
5. Sonnet-PDF Fetcher
6. Sonnet-Searcher
7. Opus-Manager (main loop)
8. On-demand agents + SKILL.md rewrite

### What carries forward from v2/v3
All Python scripts (csv_writer.py, taxonomy_resolver.py, statistical_qc.py, pdf_utils.py, etc.), dashboard_generator.py, verify_session.py, export_dwc.py, example configs, eval suite.

## Next actions
- [ ] Implement v4 architecture per ARCHITECTURE_v4.md
- [ ] Register Zenodo DOI (flip GitHub integration on, tag release)
- [ ] Submit manuscript
- [ ] Send to Anthropic with review document

## Second-project workflow
Each project = one folder. To start a new project:
1. Create a new folder
2. Open it in Cowork with TraitTrawler installed
3. The setup wizard (§0) generates all config files from user answers
4. Or copy an example from `examples/` and edit
