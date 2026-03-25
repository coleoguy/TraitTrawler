# Audit Mode — Self-Cleaning Data

## 15a. Audit queue construction

Build the audit queue by scanning `results.csv` for records matching any of
three criteria, in priority order:

**Priority 1 — Low confidence:**
Records where `extraction_confidence < audit_config.confidence_threshold`
(default: 0.6). These are the most likely to improve on re-extraction.

**Priority 2 — Guide-drift candidates:**
Records extracted under an older version of `guide.md`. Compare each record's
`session_id` against `state/run_log.jsonl` to find the `guide_md5` at that
session. If it differs from the current `guide.md` hash, the record was
extracted before a domain knowledge update — it may benefit from re-extraction
with the improved rules.

**Priority 3 — Statistical outliers:**
After 100+ records exist, flag values that are statistical outliers within
their taxonomic group. The detection method depends on the data type:

- **Continuous numeric fields** (body mass, wing length): values > N SD from
  the group mean, where N = `audit_config.outlier_sd_threshold` (default: 3).
- **Discrete numeric fields** (chromosome counts): SD-based detection is
  inappropriate because these distributions are often multimodal (e.g.,
  2n=20 and 2n=40 in the same family due to polyploidy). Instead, use
  **modal frequency**: flag a value if it appears only once in a group where
  the mode accounts for > 50% of records. This catches genuine errors (a
  typo giving 2n=21 in a family that's always 2n=20) without flagging real
  biological variation (2n=20 and 2n=24 both common).
  Detect discrete vs. continuous automatically: if all values in a field are
  integers and the unique count is < 30% of total records, treat as discrete.
- **Categorical fields** (sex chromosome system, staining method): flag values
  that appear only once in a group with `audit_config.outlier_min_group_size`+
  records (default: 10), where the majority (> 50%) share a different value.
  This catches "XY" in a family that's otherwise "Xyp" without flagging
  legitimately diverse groups.

Cap the audit queue at `audit_config.max_records` (default: 50) per session.
Report the queue composition:

```
🔍 Audit Queue — {N} records to review
   Low confidence (<0.6):     {n1}
   Guide-drift (old rules):   {n2}
   Statistical outliers:      {n3}
```

---

## 15b. Audit re-extraction

For each record in the audit queue:

1. **Locate the source.** Use the record's `doi` to find the cached PDF in
   `pdfs/`. Use `source_page` to go directly to the relevant page(s) —
   no need to re-read the entire paper.

2. **Re-extract with current knowledge.** Read `guide.md` (current version)
   and the relevant page(s). Extract the same fields independently, as if
   seeing the data for the first time. Do NOT look at the original record
   values during re-extraction — this prevents anchoring bias.

3. **Compare.** Diff the original record against the re-extracted record.
   Classify the result:
   - **match**: All trait fields agree. Mark `audit_status: confirmed`.
   - **minor_diff**: Non-trait fields differ (notes, source_context) or
     confidence changed. Auto-accept the higher-confidence version.
   - **correction**: One or more trait fields differ. Present to user:

```
🔍 Audit: Record {n}/{total}
   Paper: Smith et al. 2003 (10.1234/example.5678)
   Species: Cicindela campestris

   ┌─────────────────┬──────────────┬──────────────┐
   │ Field           │ Original     │ Re-extracted  │
   ├─────────────────┼──────────────┼──────────────┤
   │ 2n              │ 22           │ 22            │
   │ sex_chr_system  │ XY           │ Xyp           │  ← CHANGED
   │ confidence      │ 0.45         │ 0.88          │
   │ source_page     │ 14           │ 14            │
   └─────────────────┴──────────────┴──────────────┘

   Source text (p.14): "The karyotype formula was 10+Xyp..."

   Accept correction? [y/n/skip]
```

4. **If the PDF is missing** (not cached), check whether the paper is still
   available via the OA fetch cascade (§5b). If not, skip and log.

---

## 15c. Model routing for audits

Audit re-extraction uses the model routing from §2:
- Default: `sonnet` (targeted page re-reads are simpler than full-paper extraction)
- Escalate to `opus` if the re-extraction disagrees with the original AND
  confidence is < 0.7 on both versions (genuine ambiguity — worth the cost)
- Use `haiku` for queue construction and statistical outlier detection

---

## 15d. Audit state tracking

Add audit fields to each reviewed record in `results.csv`:
- `audit_status`: one of `unaudited`, `confirmed`, `corrected`, `skipped`
- `audit_session`: session_id of the audit that reviewed this record
- `audit_prior_values`: JSON string of original values before correction
  (empty if confirmed/unaudited)

Log every audit action to `state/run_log.jsonl`:
```json
{"timestamp": "...", "session_id": "...", "event": "audit_record", "doi": "...", "species": "...", "result": "corrected", "changed_fields": ["sex_chr_system"], "old_values": {"sex_chr_system": "XY"}, "new_values": {"sex_chr_system": "Xyp"}}
```

---

## 15e. Audit summary

After the audit pass completes, print:
```
══════════════════════════════════
 Audit Complete
══════════════════════════════════
 Records audited        : 47
 Confirmed (no change)  : 31  (66%)
 Corrected              : 12  (26%)
 Skipped (no PDF)       : 4   (8%)
 Mean confidence before : 0.52
 Mean confidence after  : 0.81
 Guide-drift fixes      : 8
══════════════════════════════════
```

This summary quantifies how much the self-auditing system improves data
quality over time — essential for the manuscript and for scientific
reproducibility.

---

## 15f. Audit never modifies records silently

Same principle as §14e: the agent proposes corrections, the human approves.
For `minor_diff` results (non-trait field changes), auto-accept is allowed
because no scientific data changes. For any trait field change, the user
must explicitly approve.
