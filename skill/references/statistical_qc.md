# Statistical QC

TraitTrawler includes a Python-based statistical quality control system that
generates diagnostic plots and summary statistics for the growing dataset.
This replaces ad-hoc "eyeballing" with reproducible, publication-quality
diagnostics that help the user decide when to stop collecting, where errors
lurk, and whether the data is ready for analysis.

## 17a. Triggers

- **Automatic**: Run at session end (after the session summary, before
  the knowledge review). Generate a brief summary; save full report.
- **On-demand**: User says "run QC", "check data quality", "how's the data
  looking", "diagnostic plots", "rarefaction curve", "outlier check".

## 17b. The statistical_qc.py script

Located at `${CLAUDE_SKILL_DIR}/scripts/statistical_qc.py`, copied to
`scripts/statistical_qc.py` in the project root at session start (§1e).

```bash
python3 scripts/statistical_qc.py --project-root . [--full]
```

- Without `--full`: generates `qc_summary.json` only (fast, <5 seconds)
- With `--full`: generates `qc_report.html` with all plots (~15 seconds)

At session end, run without `--full` and print the summary. On explicit
user request, run with `--full` and mention the HTML report.

## 17c. Analyses included

### 1. Species accumulation curve with Chao1 estimator

The species accumulation curve plots cumulative unique species against
cumulative papers processed (ordered chronologically by session). This is
the collector's curve biologists use to assess sampling completeness.

**Chao1 estimator**: estimates the true species pool size from the observed
data. Formula: S_est = S_obs + (f1² / 2*f2), where f1 = singletons (species
found in exactly 1 paper) and f2 = doubletons (species in exactly 2 papers).

The plot shows:
- Solid line: observed cumulative species
- Dashed line: Chao1 estimated total
- Shaded region: 95% confidence interval
- Annotation: "Estimated {X}% of species pool sampled"

**Interpretation for user**: If the curve is flattening, you're approaching
saturation and additional sessions will yield diminishing returns. If it's
still climbing steeply, there's substantial undiscovered diversity.

### 2. Confidence distribution

Histogram of `extraction_confidence` values across all records, with
overlays for:
- Session-specific distribution (current session in a different color)
- Threshold lines at 0.5 (low), 0.75 (flag threshold), 0.9 (high)
- Mean and median annotations

**Interpretation**: A left-skewed distribution suggests the guide.md needs
refinement or the trait is inherently ambiguous. Right-skewed is healthy.

### 3. Outlier detection

**Continuous numeric fields** (detected automatically: all-numeric values
with > 20 unique values): Grubbs' test for outliers at α = 0.05, stratified
by the grouping field (default: `family`). Uses scipy.stats for the test.

**Discrete numeric fields** (all-integer values, < 30% unique): Modal
frequency method per audit_mode.md — flag singletons in groups where the
mode accounts for > 50% of records.

**Categorical fields**: Flag singleton values in groups with 10+ records
where the majority share a different value.

Output: table of flagged records with field, value, group, reason, and
a recommendation (review, likely error, likely real variation).

### 4. Source-type breakdown

Doughnut chart showing records by `pdf_source`: unpaywall, openalex,
europepmc, semantic_scholar, proxy, abstract_only, local_pdf. Useful for
understanding how dependent the project is on institutional proxy access.

### 5. Taxonomic coverage heatmap

Grid showing families (rows) × trait completeness (columns). Each cell
colored by: green (>10 records), yellow (1–10), red (0). Families sorted
by expected diversity (from GBIF via taxonomy cache).

### 6. Session efficiency trend

Line chart of records/paper and tokens/record across sessions (from
`run_log.jsonl`). Shows whether the agent is getting more efficient as
guide.md improves.

### 8. Confidence calibration reliability diagram (§19)

When generating the full QC report (`--full`), include the reliability
diagram from the calibration module. This plots predicted confidence
(X-axis) against observed accuracy (Y-axis) — perfect calibration is
the diagonal line.

Run `scripts/calibration.py --project-root . --full` to generate the
reliability plot. If calibration data exists (>10 observations from
benchmarks, audits, and corrections), the plot shows:
- Bar chart of observed accuracy per confidence bin
- Diagonal line for perfect calibration reference
- ECE annotation

If calibration data is insufficient, skip this plot and note:
"Calibration reliability diagram requires >10 benchmark observations."

### 9. Cross-paper conflict summary (§26)

Include a summary of cross-paper conflicts detected by
`scripts/knowledge_graph_export.py`:
- Total species with data from multiple papers
- Number of concordant vs. conflicted observations
- Top conflicts with confidence-weighted resolution

### 7. Duplicate and near-duplicate detection

Scan for records with the same species and very similar (but not identical)
trait values. E.g., same species, 2n=20 in one record and 2n=20 in another
but different sex chromosome systems. These may indicate genuine biological
variation or data entry inconsistency — flag for user attention.

## 17d. Output files

- **`qc_summary.json`**: Machine-readable summary with key metrics:
  ```json
  {
    "total_records": 1336,
    "unique_species": 892,
    "chao1_estimate": 1450,
    "pct_sampled": 61.5,
    "mean_confidence": 0.82,
    "outliers_detected": 7,
    "flagged_for_review": 23,
    "sessions_completed": 8,
    "records_per_paper_mean": 4.7,
    "singletons": 234,
    "doubletons": 156
  }
  ```

- **`qc_report.html`**: Self-contained HTML with all charts (Chart.js),
  styled to match the dashboard aesthetic. Can be opened alongside
  `dashboard.html` for a complete project overview.

## 17e. Session-end summary (printed to conversation)

```
── QC Summary ─────────────────────
 Species sampled    : 892 / ~1,450 est. (Chao1: 61.5%)
 Mean confidence    : 0.82
 Calibrated ECE     : 0.042 (well-calibrated)
 Outliers detected  : 7 (3 likely errors, 4 possible variation)
 Cross-paper conflicts: 3 species with conflicting values
 Accumulation slope : 12.3 new spp/paper (still climbing)
 Recommendation     : Continue collecting — curve not yet saturating
────────────────────────────────────
```

## 17f. Dependencies

The script uses only Python standard library plus:
- `scipy.stats` — Grubbs' test, confidence intervals
- `matplotlib` — plot generation (saved as base64 PNGs embedded in HTML)

Both are installed at session start (§1a). If scipy is unavailable, the
script falls back to simpler Z-score outlier detection and skips the
Grubbs' test. If matplotlib is unavailable, skip plots and generate
text-only report.
