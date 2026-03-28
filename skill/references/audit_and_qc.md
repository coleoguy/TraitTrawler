# Audit Mode & Data QC — On-Demand Reference

Load this file when the user triggers: "run QC", "audit the database",
"check data quality", "clean the data", "check low-confidence records",
"how's the data looking".

---

## Audit Queue Construction

Build the audit queue with three priority tiers:

### Priority 1: Low Confidence (highest priority)
Records where `extraction_confidence < confidence_threshold` (default 0.6
from `audit_config` in `collector_config.yaml`).

### Priority 2: Guide-Drift
Records extracted under an older `guide.md` (compare `session_id` dates
against the guide.md modification date). These may have used outdated
notation rules or missed patterns discovered later.

### Priority 3: Statistical Outliers
Records flagged by `scripts/statistical_qc.py`:

**Continuous fields** (floats): Grubbs' test at alpha = 0.05, applied per
taxonomic group. A value is an outlier if it exceeds the critical value
for the group size. Only test groups with >= `outlier_min_group_size`
(default 10) records.

**Discrete fields** (integers with < 30% unique values): Modal frequency
rule. Within each group, if the modal value accounts for > 50% of records,
flag singletons (values appearing only once). This catches typos in
chromosome counts (e.g., 2n=23 when all others are 2n=22 or 2n=24).

**Categorical fields**: Flag singletons in groups with 10+ records where
the majority differs. Example: one record says "XO" when all other records
in the family say "XY".

Cap at `audit_config.max_records` (default 50) per audit session.

---

## Re-Extraction Procedure

For each record in the audit queue:

1. **Locate the cached PDF** using `pdf_path` from the record
2. **Go directly to `source_page`** — don't re-read the entire paper
3. **Re-extract WITHOUT seeing the original values** — this prevents
   anchoring bias. The Dealer/Extractor agents receive only the PDF text
   and guide.md, not the existing record.
4. **Compare re-extraction result against original**:

   - **match**: All trait fields agree → mark `audit_status: "confirmed"`,
     boost confidence by +0.05
   - **minor_diff**: Non-trait differences only (metadata, notes) →
     auto-accept the higher-confidence version, mark `audit_status: "confirmed"`
   - **correction**: Trait fields differ → show both versions to user:
     ```
     Record: Cicindela campestris (doi: 10.1234/...)
       Original:     2n=22, sex_chrom=Xyp, confidence=0.65
       Re-extracted:  2n=20, sex_chrom=XY,  confidence=0.88
     Accept correction? [y/n/skip]
     ```
     On approval: update results.csv, store old values in `audit_prior_values`
     (JSON string), mark `audit_status: "corrected"`, log to `run_log.jsonl`
     On rejection: mark `audit_status: "confirmed"` (user says original is right)
     On skip: mark `audit_status: "skipped"`

5. **Model routing for re-extraction**: Default sonnet. If re-extraction
   disagrees with original AND both have confidence < 0.7 → escalate to
   opus for adjudication.

---

## Audit State Tracking

Add these fields to re-examined records in results.csv:
- `audit_status`: unaudited / confirmed / corrected / skipped
- `audit_session`: session_id of the audit
- `audit_prior_values`: JSON string of original values (only if corrected)

---

## Audit Summary

Print at the end of an audit session:
```
Audit Complete
  Records examined  : 42
  Confirmed         : 28 (67%)
  Corrected         : 8 (19%)
  Skipped           : 6 (14%)
  Confidence before : 0.62 avg
  Confidence after  : 0.78 avg
  Guide-drift fixes : 3
  Outlier fixes     : 2
```

---

## Statistical QC Report

When running QC (not audit), the script `statistical_qc.py --full` generates:

1. **Species accumulation curve** with Chao1 richness estimator:
   - Chao1 = S_obs + (f1^2 / 2*f2) where f1 = singletons, f2 = doubletons
   - Interpretation: if Chao1 >> S_obs, many species remain undiscovered
   - Accumulation slope: if still steep, more collecting is productive

2. **Confidence distribution**: histogram of extraction_confidence values.
   Report mean, SD, count below 0.75.

3. **Outlier detection**: Grubbs' test (continuous) + modal frequency (discrete)
   as described above. Report count and list specific records.

4. **Near-duplicate detection**: records with same species + similar trait
   values from different DOIs that may be the same observation reported
   in multiple papers.

5. **Session efficiency trends**: records/paper and records/query over time.

Output: `qc_report.html` (self-contained with plots) and `qc_summary.json`.

QC summary block for session end:
```
QC: {S_obs} species ({Chao1:.0f} estimated) | confidence {mean:.2f} avg |
    {N_outliers} outliers | {N_conflicts} cross-paper conflicts |
    accumulation slope {slope:.2f}
```
