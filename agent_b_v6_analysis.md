# TraitTrawler v6 Analysis: Real Challenges and Concrete Improvements

**Author**: Agent analysis (independent review)  
**Date**: April 2026  
**Scope**: Evaluation against current Anthropic best practices, latest Claude capabilities, and autonomous runtime constraints.

---

## CRITICAL PREAMBLE

The prior v6 design notes contain **one material misunderstanding** that must be corrected here:

**Compilation tables are not a problem.** Heath is right: they're 99% as good as primary data. The -0.15 penalty is excessive and should be removed entirely or reduced to -0.05. Compilation tables sourced from methods-heavy reviews are often *more* reliable than isolated primary papers because they're already subject to expert filtering and comparative error-checking. The real issue isn't the confidence penalty—it's the missing *original source citation* link. Solve that at extraction time (capture the cited reference), not by downweighting the record.

---

## I. REAL CHALLENGES (What's Actually Broken)

### 1. **Manager lacks deterministic audit trail for dispatch decisions**

**The problem**: `dispatch.py recommend` makes all pipeline routing decisions, but the Manager logs only the action list, not the _reasoning_. When dispatch recommends spawning 3 Extractors + verify_and_write, but you later find a critical bug in the Extractor, you have no persistent record of _why_ that dispatch happened (queue depth? coverage threshold? exhaustion condition?).

**Impact**: Medium. Post-hoc debugging and model upgrade validation is harder. For papers-in-flight, you can't reconstruct the decision context without re-running dispatch. For research reproducibility, a future reader can't audit whether the dispatch logic was sound.

**Why it matters for v6**: If you add optional features (e.g., quality-based prioritization, learned dispatch weights), you need to log the inputs to dispatch.recommend as well as the output. Currently you only log the output.

### 2. **Auditor verification doesn't persist verification logic—only the conclusion**

**The problem**: When the Auditor corrects a value or marks it ambiguous, the JSON stores the new value and status label, but not the _why_. Example: Auditor sees "2n = 24, 25" on the page but Extractor reported "24". The audit_results.json says `"status": "corrected", "corrected_value": "24, 25"` but there's no structured field capturing that this is polymorphism, not an error. Downstream users see "this was corrected" but not the semantic reason.

**Impact**: High for manual review workflows. When a human QA person looks at a corrected record, they can't tell whether it's a genuine error fix or a re-interpretation of the data (e.g., extracting all individuals vs. the "typical" value). This blocks semi-automated review strategies.

**Why it matters for v6**: If you want to feed review decisions back into guide.md improvements or build patterns in what gets corrected, you need to classify the correction type (transcription error, misinterpretation, polymorphism, OCR artifact, etc.). Currently absent.

### 3. **Confidence calibration doesn't account for source_type / source_context heterogeneity**

**The problem**: Isotonic regression fits confidence(X) → accuracy across _all_ records pooled. But a record from a table is not the same kind of uncertainty as one inferred from prose. Calibration is fitting one curve to data from multiple noise sources. A confidence of 0.82 from a table-extracted record is not the same as 0.82 from a prose-inferred record—the underlying error distribution differs.

**Impact**: Medium. Downstream analyses that filter by confidence threshold (e.g., "keep records with confidence > 0.80") are conflating different types of uncertainty. You'll either over-filter clean table data or under-filter noisy inferences.

**Why it matters for v6**: If you move toward structured uncertainty (Challenge A in the prior notes), this becomes easier. But even now, keeping separate calibration models per source_type would be straightforward and more principled.

### 4. **Learning system doesn't feed corrections back into guide.md amendments**

**The problem**: The Auditor corrects values. These corrections are logged. At session end, the learning system proposes amendments to guide.md based on discoveries (new notation, new journals). But the Auditor's corrections are _never_ analyzed to propose guide.md fixes. Example: if 20% of records for field X are corrected because extractors misunderstood the notation, the learning system should propose a guide.md clarification—but it doesn't.

**Impact**: Medium. The pipeline learns slowly. The same notation ambiguity that the Auditor catches on day 1 may recur on day 2 because guide.md wasn't updated. In a long session, this is wasted Auditor effort.

**Why it matters for v6**: The learning loop is incomplete. Closing it is a KISS improvement: analyze audit_results/ for systematic correction patterns and propose guide.md diffs.

### 5. **Human review queue is a CSV dead-end**

**The problem**: Records flagged for review go to human_review_queue.csv. The queue accumulates. There's no mechanism for a human to mark items as reviewed, add notes, or feed corrections back. In coleoweekend, the queue bloated to 6,960 rows. Even if a human reviewer worked through 100 items, there's no way to update results.csv with the validated values or mark them as reviewed.

**Impact**: High. Human review is blocked. The entire point of building a review pipeline is to close the loop, but the infrastructure stops at generating the queue.

**Why it matters for v6**: The prior analysis suggests "structured human review workflow" with resolution states. This is necessary but currently unimplemented. Without it, human review is theater.

### 6. **Context consumption is still ~150-200 tokens per dispatch cycle but could be tightened**

**The problem**: Each dispatch cycle: process agent output (~50 tokens), checkpoint (~20 tokens), recommend (~30 tokens), execute action list (~20 tokens), print progress (~20 tokens) = ~140 tokens. This is already tight, but it doesn't include:
- Re-reading pipeline_state.json after compaction (should be cached)
- Re-reading agent specs if an agent spawns (shouldn't happen but sometimes does)
- Inline documentation or example printouts

For a 500-paper session, you're looking at ~70K tokens of overhead alone, which is 35% of a usable 200K context window. Any session past ~200 papers risks hitting context limits.

**Impact**: Medium. Sessions longer than 4-6 hours are risky. The skill is designed for autonomy, but long sessions might hit context walls.

**Why it matters for v6**: If you're going to extend sessions or add features, context consumption needs to stay flat or decrease. Currently, every new feature (improved dispatch logging, verification metadata, etc.) risks pushing the overhead per cycle from 140 → 180 tokens.

### 7. **No per-record reproducibility metadata**

**The problem**: Records lack: skill_version, guide_md_hash, extractor_model, auditor_model. If guide.md evolves mid-session, two records from the same session may have been extracted under different domain knowledge. If the model defaults change (sonnet-4.5 → sonnet-4.6), you have no way to know which records used which model.

**Impact**: Low for immediate use, high for long-term research credibility. For a published dataset, reviewers will ask "which model version extracted this data?" and you can't answer.

**Why it matters for v6**: Adding these fields is cheap (4-8 bytes per record) and high-value for scientific credibility. v6 should include them.

### 8. **PDF validation is content-agnostic; doesn't check for OCR quality or image-heavy papers**

**The problem**: Fetcher validates PDFs by: file size, %PDF- header, text extraction > 200 chars. But:
- A scanned PDF with poor OCR can pass (has extractable text) but yield garbage extractions.
- An image-heavy paper (e.g., karyotype cytogenetics with 50 figures) may have sparse text but high data density in images.
- No signal reaches the Manager to trigger vision-based extraction for these cases.

**Impact**: Medium. Scanned papers with OCR artifacts cause low-confidence extractions. Image-heavy papers are under-extracted (figures ignored). The Extractor sees a PDF labeled "table-heavy" but that's only based on metadata, not actual visual inspection.

**Why it matters for v6**: The current setup documents an optional vision_extraction config knob but the pipeline doesn't automatically route based on PDF characteristics. A simple fix: add a PDF classification step in Fetcher (or Extractor Step 0) that detects heavy image content and signals Extractor to trigger vision-based extraction.

---

## II. SUGGESTIONS FOR v6 (Concrete, Implementable)

### A. **Feed Auditor corrections into guide.md amendments (KISS fix)**

**What**: After each verify_and_write, analyze audit_results/ for systematic patterns:
- Group corrections by field + correction_type (e.g., `field="2n", type="polymorphism"`)
- If a field has >3 corrections of the same type in one batch, log it as a discovery
- Example: "Field `sex_chromosome_system` had 5 records corrected from `XY` to `XY+B`; recommend guide.md clarification: 'B-chromosome polymorphism is common in Diabrotica; extract range (e.g., XY or XY+B) not single value.'"

**Implementation**: ~30 lines in a new `analyze_audit_corrections.py` script. Called at session end or every 50 records. Output goes to learning/*.json as usual.

**Why KISS**: Doesn't require new fields or new agent logic. Uses existing audit output. Closes a gap in the learning loop without context overhead.

**Context cost**: Zero per dispatch cycle (runs only at session end or batched). One-time ~100 tokens.

---

### B. **Separate calibration models by source_type**

**What**: Instead of one isotonic regression fit across all records, maintain separate models for:
- `source_type: "table"` (high-precision, narrow confidence range)
- `source_type: "prose"` (wider uncertainty)
- `source_type: "compilation"` (validated elsewhere, use as-is or with tiny adjustment)

**Implementation**: Change `calibration.py` to check source_type before fitting. Maintain separate `state/calibration_data_{source_type}.jsonl` files. When writing records, use the appropriate model for that source_type.

**Why KISS**: Doesn't change the schema or agent behavior. Pure post-processing improvement. Users benefit immediately with better-calibrated confidence scores.

**Context cost**: ~5 tokens per dispatch (reading which calibration model to use). Negligible.

**Impact**: Confidence scores become more informative. A 0.82 from a table is genuinely more trustworthy than a 0.82 from prose.

---

### C. **Log dispatch.py inputs + outputs (not just outputs)**

**What**: When recommend() is called, also log:
- Queue depths (queue.json line count, ready_for_extraction/ file count, finds/ count, etc.)
- Coverage metrics (Chao1, species_count)
- Exhaustion flags (all_searches_done, api_fetcher_stale, etc.)
- Spawn limits (max_concurrent_extractors)

Current log: `{"action": "spawn_extractors", "count": 3, "timestamp": "..."}`  
Enhanced log: `{"action": "spawn_extractors", "count": 3, "inputs": {"queue_depth": 45, "max_concurrent": 5, "active_extractors": 1, "chao1": 0.68, "reason": "active < max AND queue > threshold"}, "timestamp": "..."}`

**Implementation**: 20 lines in dispatch.py around the recommend() call.

**Why KISS**: Debugging and validation becomes trivial. No new file structures, no agent changes.

**Context cost**: ~10 tokens per dispatch cycle (logging inputs). Acceptable.

**Impact**: Future model upgrades or rule changes to dispatch logic can be audited. You can answer "why did the pipeline spawn 3 extractors here?"

---

### D. **Add extraction_model and guide_hash to every record (cheap provenance)**

**What**: When write_finds.py processes records, add two fields:
- `extractor_model`: read from env or config (e.g., "claude-sonnet-4-6-20260401")
- `guide_md_hash`: MD5(guide.md) at extraction time (Extractor computes, stores in finds/ JSON)

CSV schema adds two string columns (negligible size).

**Implementation**: 5 lines in Extractor (compute hash after reading guide.md, store in finds JSON). 3 lines in write_finds.py (copy from metadata to record).

**Why KISS**: Two tiny fields, massive credibility gain. Reviewers can now ask "which model?" and you answer with a single field lookup.

**Context cost**: Zero. Fields are copied from metadata, not recomputed.

**Impact**: Dataset becomes publishable-grade. Long-term reproducibility improves.

---

### E. **Implement structured human review resolution states (necessary but non-urgent)**

**What**: Replace human_review_queue.csv with a two-file system:
1. `state/human_review_queue.jsonl`: queue items with unique ID, creation_date, reason_code, original_value, species, field
2. `state/human_review_resolutions.jsonl`: resolution entries with queue_id, reviewer_action (confirmed/corrected/deferred), new_value, notes, reviewed_date

After review, the Manager can feed resolutions back into results.csv via a new script `apply_review_resolutions.py`.

**Implementation**: ~80 lines total (new queue schema + apply script).

**Why KISS**: Doesn't change extraction or verification. Pure bookkeeping. But it unblocks human workflows.

**Context cost**: ~5 tokens per verify_and_write to append resolutions. Negligible.

**Impact**: Human review becomes actionable. Corrections flow back into the database.

---

### F. **Auto-detect OCR / image-heavy PDFs and route to vision extraction**

**What**: Add a lightweight PDF classification in Fetcher or Extractor Step 0:
- If PDF has > 50% images (by page) or OCR confidence < 0.80 (if available), tag as `pdf_quality: "scanned"` or `pdf_content_type: "image_heavy"`
- Pass this to Extractor; if set, Extractor tries vision-based extraction before text-based

**Implementation**: 20 lines in PDF validation (image detection via PIL/pdfplumber statistics). Extractor already has vision fallback in Step 2; just needs a signal to trigger it earlier.

**Why KISS**: Doesn't require new agents. Uses existing vision capability. Just makes it automatic instead of manual.

**Context cost**: ~10 tokens per PDF processed (classification metadata). Minimal.

**Impact**: Scanned papers no longer yield garbage extractions. Image-heavy papers get better coverage.

---

### G. **Add structured correction classification to audit_results JSON**

**What**: When Auditor corrects a value, add a `correction_type` field:
- `"type": "transcription_error"` — Extractor misread the text
- `"type": "misinterpretation"` — Extractor chose wrong value from ambiguous text
- `"type": "polymorphism"` — Both Extractor and cited source were valid; Auditor is noting range
- `"type": "ocr_artifact"` — PDF text was corrupted
- `"type": "incompleteness"` — Extractor missed a value present on page
- `"type": "unit_mismatch"` — Extractor got value but wrong units

**Implementation**: 5 lines in Auditor spec (add the field to JSON output). Auditor already has the logic; this just formalizes it.

**Why KISS**: No schema change, no new validation. Purely semantic enrichment of existing data.

**Context cost**: ~2 tokens per correction (field name + type string). Negligible.

**Impact**: Enables analysis of error patterns (e.g., "unit_mismatch is 20% of corrections; guide.md needs unit clarity"). Feeds into the learning system.

---

### H. **Reduce Manager context overhead per dispatch cycle: inline quick-status caching**

**What**: Currently, the Manager calls recommend() with `--compact` flag, but dispatch.py re-reads multiple state files each time. Cache the last `pipeline_state.json` read in a session variable so that if no writes happened since last checkpoint, the cached version is used.

Also: only print full progress every 10 papers; between updates, use a single-line "still running" message.

**Implementation**: 10 lines in dispatch.py (session cache). 5 lines in SKILL.md Manager loop (conditional progress printing).

**Why KISS**: Saves 20-30 tokens per cycle by reducing file I/O and logging.

**Context cost**: ~10 tokens saved per cycle. Compounds over long sessions.

**Impact**: Sessions can extend from ~450 papers to ~500+ papers before context limits. Marginal but real.

---

### I. **Document (don't implement yet) the structured evidence bundle vision**

**What**: The prior notes suggest "evidence bundles" with page crops and bounding boxes. This is _not_ a v6 change because:
1. Requires vision API to extract bounding boxes, which adds token cost to Extractor
2. Requires new JSON schema and CSV columns
3. Needs a viewer UI to display evidence (outside skill scope)

**BUT**: For v6 design clarity, document the target architecture:
- Each record optionally carries `evidence.bbox` (page, x0, y0, x1, y1) + `evidence.page_image_b64` (base64-encoded 200x200 px crop) + `evidence.full_context` (full sentence/cell, not truncated)
- Future versions (v7+) can add this incrementally without breaking the pipeline
- Today's records can have empty evidence fields; tomorrow's can populate them

**Implementation**: 20 lines of documentation in a new section of the SKILL.md or references/. Zero code.

**Why KISS**: No production cost. Establishes a forward path for evidence richness without disrupting v6.

**Context cost**: Zero (pure documentation).

---

## III. WHAT NOT TO DO IN v6 (Resist These)

### Don't: Remove compilation table penalty entirely

The -0.15 penalty is wrong, but removing it entirely is also wrong. A compilation table from a 2020 review is not the same as primary data from 1985. Reduce the penalty to -0.05 (or make it configurable). But don't zero it out.

### Don't: Add per-record evidence bundles

Too much complexity. Defer to v7. Document the target schema; don't implement yet.

### Don't: Add differential quality metrics per journal/decade

Attractive but requires post-hoc analysis outside the collection pipeline. Suggestion I leaves this to post-collection analysis scripts, not the pipeline itself.

### Don't: Implement active learning for review prioritization

Requires machine learning on accumulated review data. Out of scope for KISS. Do this in v7 when you have historical review data.

### Don't: Increase Extractor or Auditor context window

The whole design goal is to keep agents lightweight and context-efficient. Don't balloon the spec with "nice-to-have" details about footnotes, appendix structure, or edge cases. Keep them focused.

---

## IV. LATEST ANTHROPIC BEST PRACTICES (What v6 should follow)

Based on current Anthropic Claude Code documentation and agent SDK release notes:

### 1. **Hooks and SDK callbacks are mature — use them**

v5 removed sub-agent hooks to save tokens. But PreToolUse hooks on the Manager are still valuable for guardrails:
- Your current hook (protect-results.csv.sh) prevents accidental writes. Keep it.
- Consider adding a PostToolUse hook to validate dispatch.py output (ensure actions are from a known set, no typos)

Cost: ~20 tokens at session start (hook registration). No per-dispatch cost.

### 2. **MCP tool schemas are fetched on-demand, not pre-loaded**

The WebFetch, WebSearch, Grep, Read, etc. tools are now loaded lazily. Your skill declares them in frontmatter; Claude fetches schemas only when they're first used. This saves ~500 tokens on startup if you're using 10+ MCPs.

v5 already uses this implicitly. v6 should make sure the frontmatter lists all tools you might use (already done) and trust that Claude handles the lazy loading.

### 3. **Agent isolation and skill delegation are the gold standard**

Your design (Manager delegates all decisions to dispatch.py, Searcher/Fetcher/Extractor are isolated agents) is exactly what Anthropic recommends in 2026. Keep this architecture. Don't be tempted to merge agents or put logic in the Manager.

### 4. **Progressive disclosure via reference files is still best practice**

You have reference/ files for dispatch, extraction, audit, campaign planning. Load them only on request. This is correct and matches Anthropic's guidance.

### 5. **Skill version management + frontmatter are essential**

Your SKILL.md frontmatter (name, model, effort, allowed-tools) is exactly right. The version field in CHANGELOG is good. For v6, ensure version bumps are tied to schema changes, not just bug fixes.

---

## V. NEW CLAUDE CAPABILITIES TO LEVERAGE (April 2026)

### 1. **Defer permission decisions in PreToolUse hooks (v2.1.89+)**

If a skill needs user approval to write a file or execute a destructive action, hooks can now "defer" the decision:
```
hook returns {"defer": true, "message": "Approve write to results.csv?"}
```

Claude pauses; user can approve/reject; session resumes. v5 doesn't use this. Consider it for v6 if you want stronger write protection.

### 2. **PermissionDenied hook for auto-mode recovery**

When Claude's auto-mode classifier denies a tool call, a PermissionDenied hook fires. Return `{"retry": true}` to let Claude re-evaluate the tool use. Useful for recovery from transient denials. Optional; probably overkill for TraitTrawler.

### 3. **Streamable HTTP transport for remote MCP servers**

If you ever want to connect to a remote MCP server (not local stdio), April 2026 Claude Code supports it. Not relevant today, but good to know for future scalability.

---

## VI. SUMMARY: PRIORITY ROADMAP FOR v6

**Must have** (close a real gap, minimal context cost):
1. Feed Auditor corrections into guide.md amendments (A)
2. Separate calibration models by source_type (B)
3. Log dispatch.py inputs + outputs (C)
4. Add extractor_model + guide_md_hash to records (D)

**Should have** (unblocks workflows, moderate implementation cost):
5. Structured human review resolutions (E)
6. Auto-detect OCR/image-heavy PDFs (F)

**Nice to have** (enrichment, deferred cost):
7. Structured correction classification (G)
8. Manager context caching (H)
9. Documentation for future evidence bundles (I)

**Don't do yet**:
- Remove compilation table penalty entirely
- Add evidence bundles
- Implement ML-based review prioritization
- Increase agent context windows

---

## VII. FINAL NOTES

**On compilation tables**: The -0.15 penalty is not the real problem. The real problem is missing original-source attribution. Extractor should extract and store the cited reference column (if present) as a structured field. This is a simple change to the extraction spec, worth more than tweaking the confidence number. The original citation link is what matters for downstream deduplication and audit trails.

**On context consumption**: Current ~140 tokens per dispatch cycle is good. The design scales to ~500 papers in a 200K context window. If you add the suggestions above carefully (logging inputs, structured corrections, calibration split), you'll stay within 150-160 tokens per cycle. Don't exceed 180.

**On autonomous runtime**: The pipeline is already autonomously runnable for 4-6 hours. v6 changes should preserve this. All suggestions above are designed to add capabilities without bloating the dispatch loop.

**On KISS**: Resist feature creep. Every suggestion here pays for itself in either accuracy, reproducibility, or closed-loop learning. Don't add a feature just because it's theoretically nice.
