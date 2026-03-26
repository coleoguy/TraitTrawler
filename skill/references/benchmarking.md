# Extraction Benchmarking

TraitTrawler includes built-in benchmarking infrastructure to measure
extraction accuracy against gold-standard data. This transforms confidence
scores from heuristic guesses into empirically validated metrics, and
enables systematic tracking of extraction quality over time.

## 20a. Why benchmark

Without benchmarking, there is no way to know if the system is extracting
data correctly. A confidence score of 0.9 means nothing unless you have
verified that 0.9-confidence records are actually correct ~90% of the time.
PaperQA2 benchmarks against LitQA2; Elicit reports ~92% precision; otto-SR
achieves 96.7% sensitivity. TraitTrawler needs equivalent rigor.

## 20b. Gold-standard creation (during calibration)

During the calibration phase (§0b), after the user provides seed papers:

1. **Hold out 2-3 papers as benchmark papers.** These are NOT used for
   guide.md learning — they are reserved for blind evaluation.
2. **Process benchmark papers normally** through the extraction pipeline.
3. **Present extracted records to the user** for field-by-field verification:

```
🎯 Benchmark Verification — Paper 1/3
   Smith et al. 2003 (10.1234/example.5678)

   Record 1/8: Cicindela campestris
   ┌─────────────────────┬──────────────┬──────────┐
   │ Field               │ Extracted    │ Correct? │
   ├─────────────────────┼──────────────┼──────────┤
   │ chromosome_number_2n│ 22           │ [y/n/fix]│
   │ sex_chr_system      │ Xyp          │ [y/n/fix]│
   │ karyotype_formula   │ 10+Xyp       │ [y/n/fix]│
   │ staining_method     │ conventional │ [y/n/fix]│
   └─────────────────────┴──────────────┴──────────┘
```

4. **Record verification results** to `state/benchmark_gold.jsonl`:

```json
{
  "doi": "10.1234/example.5678",
  "species": "Cicindela campestris",
  "field": "chromosome_number_2n",
  "extracted_value": "22",
  "gold_value": "22",
  "correct": true,
  "predicted_confidence": 0.92,
  "session_id": "2026-03-24T14:30:00Z",
  "paper_type": "benchmark"
}
```

5. **Also record missed records** (species in the paper that the agent
   did NOT extract — these are false negatives):

```json
{
  "doi": "10.1234/example.5678",
  "species": "Cicindela hybrida",
  "field": "_record_level",
  "extracted_value": null,
  "gold_value": "present",
  "correct": false,
  "predicted_confidence": null,
  "session_id": "2026-03-24T14:30:00Z",
  "paper_type": "benchmark",
  "error_type": "false_negative"
}
```

## 20c. Ongoing benchmark accumulation

Benchmark data accumulates from three sources:

1. **Calibration holdout papers** (§20b): initial gold standard
2. **Audit confirmations/corrections** (§15): every audit record that is
   confirmed or corrected generates calibration data
3. **User corrections** (§14f): mid-session corrections provide verified
   correct/incorrect pairs
4. **Manual benchmark additions**: user can say "benchmark this paper" at
   any time — agent extracts and then presents for field-by-field verification

All data flows into `state/calibration_data.jsonl` (shared with §19
confidence calibration) and `state/benchmark_gold.jsonl` (gold-standard
specific).

## 20d. Metrics computed

The benchmark script (`scripts/benchmark.py`) computes:

### Per-field metrics
| Metric | Formula | What it measures |
|--------|---------|-----------------|
| Precision | TP / (TP + FP) | Of records extracted, how many are correct |
| Recall | TP / (TP + FN) | Of records that exist, how many were found |
| F1 | 2 × P × R / (P + R) | Harmonic mean of precision and recall |
| Accuracy | (TP + TN) / total | Overall correctness rate |

### Record-level metrics
| Metric | What it measures |
|--------|-----------------|
| Record precision | Papers with data → records extracted correctly |
| Record recall | Species in papers → species captured |
| False positive rate | Records extracted that shouldn't be (wrong species, wrong values) |
| False negative rate | Records missed entirely |

### Calibration metrics (fed to §19)
| Metric | What it measures |
|--------|-----------------|
| ECE | Expected Calibration Error (see §19e) |
| MCE | Maximum Calibration Error (worst bin) |
| Brier score | Mean squared difference between confidence and correctness |

## 20e. Benchmark report

Generated at session end if new benchmark data was added this session:

```
── Benchmark Report ───────────────────
 Gold-standard observations : {N} fields across {M} records
 Per-field accuracy:
   chromosome_number_2n     : 96.2% (P=0.97, R=0.95, F1=0.96)
   sex_chr_system           : 89.4% (P=0.91, R=0.88, F1=0.89)
   karyotype_formula        : 78.3% (P=0.82, R=0.75, F1=0.78)
 Record-level:
   Precision                : 94.1%
   Recall                   : 91.7%
   F1                       : 92.9%
 Brier score               : 0.067
 Recommendation            : karyotype_formula needs more guide.md examples
────────────────────────────────────────
```

## 20f. Benchmark tracking over time

Store session-level benchmark snapshots in `state/benchmark_log.json`:

```json
[
  {
    "session_id": "2026-03-24T14:30:00Z",
    "n_observations": 45,
    "overall_f1": 0.929,
    "per_field": {
      "chromosome_number_2n": {"precision": 0.97, "recall": 0.95, "f1": 0.96},
      "sex_chr_system": {"precision": 0.91, "recall": 0.88, "f1": 0.89}
    },
    "ece": 0.042,
    "brier_score": 0.067
  }
]
```

This enables plotting accuracy trends over sessions — does guide.md
improvement actually translate into measurable extraction quality gains?

## 20g. The benchmark.py script

Located at `${CLAUDE_SKILL_DIR}/scripts/benchmark.py`, copied to
`scripts/benchmark.py` in the project root at session start (§1e).

```bash
python3 scripts/benchmark.py --project-root . [--full]
```

- Without `--full`: prints summary metrics to stdout
- With `--full`: generates `benchmark_report.html` with per-field
  breakdown, confusion matrices, and trend plots

Dependencies: numpy (standard with scipy). No additional installs needed.

## 20h. Integration with calibration

Benchmark data is the primary input for confidence calibration (§19).
Every verified field-value pair becomes an observation in
`state/calibration_data.jsonl` with `correct: true/false` and
`predicted_confidence`. The calibration system (§19) uses these to fit
the isotonic regression model that transforms raw confidence into
calibrated probability.

## 20i. Trigger

- **Automatic during calibration**: §0b holds out benchmark papers
- **On-demand**: "benchmark this paper", "run benchmark", "check accuracy"
- **At session end**: if audit or corrections generated new data, recompute
