# TraitTrawler v6: Analysis and Recommendations

**For**: Heath Blackmon, Texas A&M University  
**Date**: April 2026  
**Scope**: Real challenges, concrete improvements, context-aware constraints

---

## Executive Summary

TraitTrawler v5 is architecturally sound—the four-agent pipeline with extract+verify is clean, the dispatch loop is deterministic, and context consumption is tightly controlled. The system has real gaps, but they're not in the core loop. The main issues are:

1. **Weak evidence linkage**: Records carry provenance metadata but not visual/spatial evidence, making verification slow
2. **Opaque confidence**: A single float hides multiple orthogonal uncertainty dimensions
3. **Broken compilation table tracking**: Original source citations aren't reliably captured
4. **Dead human queue**: No structured workflow to resolve flagged records or feed corrections back
5. **Limited autonomy on figures**: Cytogenetics papers with karyotype images are systematically under-extracted

The v6 roadmap should focus on *making existing data actionable* rather than expanding extraction scope. Don't add heavyweight per-record processing or context bloat.

---

## Part 1: Real Challenges

### 1. Verification is a bottleneck (provenance is documented but not verifiable)

**Problem**: Every record has `source_page`, `source_context` (200-char quote), `extraction_reasoning`, but verifying a record still requires:
- Opening the PDF
- Navigating to the page
- Finding the exact table cell or sentence
- Mentally matching the 200-char quote to the surrounding context

For a database with 5,000+ records (coleoweekend scale), this is a multi-hour task. The 200-char context is often too small to disambiguate which table or paragraph the value came from, especially in compilations or dense methods sections.

**Why it matters**: A downstream user or reviewer cannot efficiently audit the database. Confidence in the collection drops. Published datasets with this problem face skepticism because spot-checking is expensive.

**Current status**: `source_context` is working as designed, but the design itself is insufficient for large-scale curation.

### 2. Confidence is a compression artifact

**Problem**: Calibrated confidence is a single [0, 1] float. A record with confidence 0.82 could be:
- High-clarity value from a table, but from a compilation table (-0.15 penalty)
- Medium-clarity value from prose, confirmed by Auditor
- Low-clarity notation (ambiguous sexing symbols) but from a good source
- Value from a low-quality PDF, confirmed across multiple fields

These are qualitatively different uncertainty modes. The single number compresses them all. A downstream user cannot ask "show me only records from original primary data with high-clarity values" because that information is lost.

**Why it matters**: Users cannot stratify analyses by data quality. Meta-analyses can't weight records appropriately. The confidence metric becomes decorative rather than actionable.

**Current status**: Calibration is well-implemented technically, but the loss-of-information problem is fundamental to the design.

### 3. Compilation table sources are not reliably original-cited

**Problem**: Compilation tables have a reference column (e.g., "Author/Year" or "Genus/Species/Source"). The Extractor is supposed to capture this as `source_reference` or similar, but currently:
- The field is not required in the schema
- The Extractor's instructions don't emphasize it
- No post-hoc verification that the original reference was captured
- Many compilation records cite the review paper as their source, not the primary source

Example from coleoweekend: A compilation table from Smith et al. (2020) citing data from Johnson et al. (1995) gets recorded as "source: Smith 2020" instead of "source: Johnson 1995; cited in Smith 2020."

**Why it matters**: Records are provenance-corrupted. A downstream user cannot deduplicate across compilation tables and direct extractions of the same primary papers. A meta-analysis might double-count data without knowing it.

**Current status**: Partial blame on Extractor instructions (could be stricter), partial on schema (could require the field).

### 4. Human review queue is a dead end

**Problem**: Records flagged for review go to `human_review_queue.csv`. In the coleoweekend trial, this queue ballooned to 6,960 rows (1,084 unique, post-dedup fix). But:
- There is no mechanism to mark items as "reviewed"
- Corrections cannot be fed back into results.csv
- The queue never shrinks
- Users have no visibility into resolution status or priority

Contrast: systematic review software (DistillerSR, Covidence) has a multi-step workflow: assigned → reviewed → consensus → resolved → archived.

**Why it matters**: The pipeline doesn't close the loop. Work accumulates without resolution. Users cannot tell if a flag is an actionable problem or a false positive that will never be addressed.

**Current status**: `inline_qc.py` writes the queue correctly, but there's no follow-up mechanism.

### 5. Per-record extraction context is incomplete

**Problem**: Each record has `session_id` and `processed_date`, but not:
- `skill_version` (which TraitTrawler version was used)
- `guide_md_hash` (state of domain knowledge at extraction time)
- `config_hash` (state of collector_config at extraction time)
- `extractor_model` string (was it Sonnet 4.5 or 4.6?)
- `auditor_model` string

If guide.md evolves mid-session, two records from the same session were extracted under different domain knowledge. If the skill is upgraded, there's no way to know which records were extracted with the old vs. new logic. A post-hoc analysis that asks "did accuracy improve after we fixed the sex-chromosome notation rule?" cannot be answered.

**Why it matters**: Reproducibility and post-hoc analysis are impossible. Cannot correlate accuracy with guide version, model version, or config state.

**Current status**: Partial information is captured (session_id, processed_date, extraction_trace_id sometimes), but not comprehensively or per-record.

### 6. Cross-paper deduplication is blind to original sources

**Problem**: Current dedup key is `(species, trait_fields)` with DOI scoping. Two records for the same species with identical trait values from different papers are deduplicated if the values match exactly. But:
- If both are from the *same* primary source, this is correct dedup
- If they're from different primary sources via different compilations, this is *incorrect* dedup (legitimate biological variation was hidden)

Example: Beetle species X has 2n=24 in Smith (2000) and 2n=24 in Johnson (1995). If TraitTrawler extracts both via compilations, and both reach results.csv with value 24, the dedup logic sees them as redundant. But they're independent observations from different primary sources and should both be kept.

**Why it matters**: For trait datasets, especially in organisms with polymorphism or population structure, diversity is legitimately lost. The database becomes artificially homogenized.

**Current status**: The dedup mechanism is well-designed for exact duplicates (same paper cited twice), but it cannot distinguish "same source cited twice" from "independent observations of the same value."

### 7. PDF linkage is filesystem-fragile

**Problem**: Records link to PDFs via `pdf_path` (filesystem path) and `pdf_filename` (filename). If:
- PDFs are moved to a new directory
- The project is shared across systems
- Files are synced to cloud storage with renamed paths

The links break. There's no content-based identifier (e.g., SHA-256 hash) connecting a record to a specific PDF file immutably.

**Why it matters**: A record that says "see page 4 of the PDF" becomes unhelpful if the PDF path is stale. Reproducibility breaks. The only fix is manual relinking.

**Current status**: Works within a single session on a single machine, but fragile under the conditions that distributed research teams face.

### 8. Figure/image data is invisible to the pipeline

**Problem**: Karyotype images, idiograms, phylogenies, and morphometric plots are ignored. The Extractor reads PDFs with pdfplumber (text only) and has no facility to:
- Detect figures
- Extract data from images
- Cross-reference text statements against figure data

For cytogenetics, this is a major omission: metaphase plate idiograms often contain arm ratios, heterochromatin distributions, and B-chromosome presence that aren't stated in the text.

**Why it matters**: Systematic under-extraction of certain trait types. Cytogenetics papers will consistently miss data visible in figures. The database is biased toward text-extractable traits.

**Current status**: Acknowledged in the methods (images not extracted), but no mechanism even to log which papers have extractable figures. Users don't know what was missed.

### 9. Dispute resolution and Adjudicator feedback is minimal

**Problem**: The Adjudicator (Opus) resolves Extractor/Auditor disputes and writes to `adjudication_results/`, which are then merged back into finds/ via `merge_adjudication.py`. But:
- The Adjudicator's reasoning is not stored persistently (only the final value)
- No post-session analysis of dispute patterns (e.g., "60% of disputes were notation-related")
- No feedback loop to improve the Extractor's domain knowledge

**Why it matters**: The pipeline doesn't learn from disputes. If the same notation ambiguity causes disputes in 10 papers, the guide.md isn't updated to disambiguate it. The learning system catches some cases, but not the ones that cause disputes.

**Current status**: The Adjudicator mechanism works, but it's a dead-end sink for conflict resolution.

---

## Part 2: Assessment of Prior Analysis

The `traittrawler_v6_design_notes.md` document proposes 10 suggestions (A–J). Here's my evaluation:

### What's right

**A (Per-record evidence bundles)**: **SOLID**. This directly addresses challenge #1. Visual evidence + cropped screenshots would cut verification time by 90%. But execution matters: don't store PNGs in the JSON (context bloat). Instead: store bounding box coordinates or a reference pointer that the dashboard can render.

**C (Original citation extraction for compilations)**: **YES, do this**. This directly addresses challenge #3. Add a required `original_source_doi` or `original_authors_year` field to the schema when `source_type: "compilation"`. The Extractor reads it from the table. A lookup to Crossref/OpenAlex resolves it to a DOI if available.

**D (Content-addressed PDF storage)**: **YES, cheap and useful**. SHA-256 hash per PDF costs nothing, provides immutable linkage (challenge #7), and enables deduplication. Store it as `pdf_sha256` on every record.

**F (Per-record extraction provenance metadata)**: **CRITICAL**. This addresses challenge #5. Add: `skill_version`, `guide_md_hash`, `config_hash`, `extractor_model`, `auditor_model`. Store these in `state/metadata.jsonl` keyed by doi + timestamp (not in results.csv, which would bloat columns). Merge them back in at export time.

### What's underspecified or risky

**B (Decomposed confidence into structured uncertainty)**: **INTERESTING but RISKY**. The design shows a JSON structure with multiple confidence components. But:
- This adds columns to results.csv, or requires a separate metadata store
- Downstream tools need to understand the new structure
- The overall score still compresses everything
- This is nice-to-have, not essential

*Suggestion*: Move this to v6.1 or a dashboard feature (show the components when hovering over a record). Don't change the CSV schema in v6.

**E (Structured human review workflow)**: **NEEDS DESIGN WORK**. The suggestion is right (challenge #4), but the design is vague. How are corrections fed back? Who can edit? Is there a schema for the resolution? Is this a separate CSV or integrated into results.csv?

*Suggestion*: This is too big for v6.0. Do a proof-of-concept with 50 items in a jupyter notebook first.

**G (Figure and image awareness)**: **LOW PRIORITY**. Logging which figures exist is nice, but not until vision extraction is ready (which requires new LLM capabilities, not available now). For v6.0, note that figures exist and move on.

**H (Exportable evidence reports)**: **GOLD**. An HTML dashboard showing extracted values + source context + Auditor verification + confidence breakdown per paper would be excellent for publication. But this is a post-processing tool, not a pipeline change. Build it after v6.0 ships.

**I (Differential quality metrics by data source)**: **YES, EASY WIN**. Track and report:
- % extracted from tables vs. prose vs. figures
- % from primary vs. compilation
- % from paywalled papers
- Accuracy by decade, journal

This is a dashboard/reporting feature, not a pipeline change. Implement in `statistical_qc.py`.

**J (Active learning for prioritization)**: **TOO COMPLEX for v6.0**. This requires tracking which review decisions changed downstream analyses (impossible to know). Defer to v6.2.

---

## Part 3: Concrete v6 Recommendations

### What to do now (v6.0)

**1. Add required original-source citation for compilation tables**

- Schema: add optional `original_source_doi`, `original_authors_year` fields
- Extractor instruction: "If this is a compilation/review table, the original reference is in [citation column]. Extract it and look it up in Crossref to get the DOI if available."
- `write_finds.py`: when writing, if `source_type: "compilation"` and `original_source_doi` is empty, flag for human review
- No context bloat, no new agents, pure schema + instruction update

**2. Add PDF SHA-256 hash as immutable identifier**

- `pdf_utils.py` or `write_finds.py`: compute SHA-256 hash of every PDF before writing records
- Store as `pdf_sha256` field in results.csv
- Use for deduplication at import time (if a PDF with the same hash is seen, skip it)
- Cleanup: compute hashes retroactively for existing results.csv

**3. Capture extraction metadata per-record (model versions, guide hash, etc.)**

- Create `state/extraction_metadata.jsonl` (one JSON per record: `{doi, timestamp, skill_version, guide_md_hash, config_hash, extractor_model, auditor_model}`)
- At session start: read skill version and record it
- In Extractor: Compute MD5 of guide.md and config at extraction time, log it (costs ~1 second per paper)
- In `write_finds.py`: join metadata into results.csv as a separate export (don't bloat the CSV itself; keep as JSONL for analysis)
- Enable post-hoc queries: "which records were extracted with guide_v3?" or "did accuracy change when we upgraded from Sonnet 4.5 to 4.6?"

**4. Fix compilation table -0.15 confidence penalty assessment**

- You've flagged this correctly: -0.15 is arbitrary and wrong
- Run a benchmark on the coleoptera dataset: separate records from compilations vs. primary, compare their Auditor agreement rates
- Hypothesis: compilation tables from recent reviews (post-2010) are 99% as good as primary, so penalty should be -0.03 or -0.05, not -0.15
- Implement: make the penalty configurable in `collector_config.yaml` with a sensible default (~-0.05)

**5. Add source evidence pointers (not full screenshots, just coordinates)**

- Schema: optional `evidence` JSON object: `{page: int, bbox: [x0, y0, x1, y1], passage: "full verbatim text, not truncated"}`
- Extractor: for table extractions, record the table ID and cell coordinates if available (costs <5 seconds per record with structured extraction)
- Dashboard: render the bbox as a highlighted region in the PDF page image
- No context bloat (100 chars per record), huge verification speedup

**6. Generate per-session quality report in `statistical_qc.py`**

- After each session, output: source breakdown (% tables/prose/figures), quality by source, Auditor agreement rate, dispute rate by field
- This lets users see at a glance whether a session produced high-quality data or needs review
- Already have the data in audit results; just needs aggregation

**Cost analysis**:
- 1–3 adds: ~500 tokens per dispatch cycle (minimal)
- 4: no context cost, one config flag
- 5: ~50 tokens per record (low)
- 6: post-hoc aggregation, zero collection-time cost

All six are KISS. None require new agents, new MCP tools, or context-window explosions.

### What NOT to do (scope boundaries)

- **Don't build a structured human review UI in v6.0**. The CSV queue is fine. Build a Jupyter notebook to manually review items (4 involves fixing dedup and low-confidence routing first).
- **Don't implement figure extraction yet**. The Extractor can log "Figure 2 shows karyotype" but shouldn't try to extract from images until vision capabilities are clearer. v6.1 feature.
- **Don't decompose confidence into multiple fields in the CSV**. Store it as metadata (JSONL) for analysis, keep results.csv clean.
- **Don't add per-record evidence bundles as full images**. Use coordinate pointers instead.

---

## Part 4: Anthropic Best Practices Alignment

Current v5 is well-aligned with Anthropic's skill recommendations:

✓ **Focus on domain-specific expertise**: TraitTrawler's value is in literature search, PDF handling, and trait extraction—not general coding.

✓ **Document common mistakes**: SKILL.md has strong "MUST NOT" sections for the Manager, all agent specs have prohibitions.

✓ **Leverage folder structure**: Uses folders for PDFs, results, reference docs, scripts—not just Markdown.

✓ **Minimize context consumption**: ~200 tokens per dispatch cycle, reference docs loaded on demand only.

**Gaps to address**:

- **Skill versioning**: Add a `skill_version.txt` file or frontmatter that auto-increments. Needed for metadata tracking (recommendation #3).
- **Agent failure recovery**: Current retry logic is per-script, not per-agent. v4.4 added this but could be more explicit in SKILL.md.
- **Pre/PostToolUse hooks**: Currently used only for CSV protection. Could add more validation hooks for finds/ JSON to catch schema errors earlier.

---

## Part 5: Context Window and Autonomous Runtime Analysis

**Current math**:
- Fixed overhead (SKILL.md, agent specs, reference docs): ~7,000 tokens
- Per-dispatch-cycle overhead: ~200 tokens (process_agent_output, dispatch checkpoint, recommend call)
- Agent spawn prompt: ~500 tokens each

**At 200 tokens per cycle and a 200K context limit, the system can run ~1,000 cycles autonomously**, which corresponds to 300–500 papers depending on extraction complexity.

**Coleoweekend trial**: 8–10 hours of runtime, ~200 papers, ~80 cycles. Roughly 2,000 tokens/cycle at peak (extraction + auditor overhead). System handled it fine; no context overflow.

**For v6**: Recommendations #1–6 add:
- Metadata tracking: ~50 tokens per cycle (reading guide hash, config hash)
- Compilation source lookup: ~100 tokens per compilation table (Crossref API call during write)
- PDF hash computation: ~10 tokens per paper (subprocess call)

**Total added**: ~160 tokens per cycle worst-case. **Still well within budget**. A 1,400-cycle session becomes a 1,300-cycle session. No problem.

---

## Part 6: Roadmap Priorities for v6.0, v6.1, v6.2

### v6.0 (ship now)
1. Fix compilation table penalty (config flag)
2. Add original-source citation for compilations (schema + instruction)
3. Add PDF SHA-256 hash (write_finds.py change)
4. Capture extraction metadata (skill version, guide hash, model versions)
5. Add evidence pointers (bbox coordinates in finds/ JSON)
6. Improve quality report (statistical_qc.py aggregation)

**Effort**: ~1 week (mostly config and instruction tweaks).  
**Context cost**: +160 tokens/cycle.  
**Impact**: Verification becomes fast, compilation table provenance is fixed, metadata enables post-hoc analysis.

### v6.1 (3 months out)
1. Dashboard with evidence rendering (highlight bbox in PDF)
2. Decomposed confidence metadata (separate from CSV)
3. Figure detection and logging (not extraction yet)
4. Quality stratification (differential metrics by source)

**Effort**: ~2 weeks.  
**Context cost**: None (dashboard is offline).

### v6.2+ (future)
1. Human review workflow (if data accumulates)
2. Vision-based figure extraction (wait for better model support)
3. Active learning for review prioritization

---

## Conclusion

TraitTrawler v5 has a solid architecture. The challenges are not in the core loop—they're in the gaps between extraction and publication:

- Evidence is documented but not efficiently verifiable
- Confidence is opaque
- Compilation tables lose their original sources
- Metadata is incomplete
- Human review doesn't close the loop

**v6 should focus on closing these gaps**, not expanding capability. All six recommendations are low-cost, high-impact, and KISS. None require new agents, new models, or context-window explosion. Implement them in sequence, test on a subset of coleoweekend data, and ship.

The system will remain fast, simple, and autonomous.

---

## Sources

- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)
- [Claude API Agent Skills Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Claude Agent SDK Overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Claude Code Changelog April 2026](https://code.claude.com/docs/en/changelog)
- [Claude 1M Token Context Beta](https://platform.claude.com/docs/en/release-notes/overview)
