# Confidence Calibration

TraitTrawler's extraction confidence scores are initially heuristic-based
(see csv_schema.md). This module transforms them into calibrated
probabilities — when the system reports 0.85 confidence, records are
actually correct 85% of the time. Calibration requires benchmark data
(see benchmarking.md) and improves automatically as more gold-standard
comparisons accumulate.

## 19a. Why calibrate

LLMs are systematically overconfident. Research shows that raw confidence
heuristics from extraction systems correlate with accuracy but are not
well-calibrated — a 0.9 heuristic confidence might correspond to 0.75
actual accuracy. Calibration closes this gap using post-hoc statistical
correction, making confidence scores actionable for downstream analysis.

**Practical value:**
- Users can set meaningful thresholds ("keep only records with >90%
  estimated accuracy")
- Audit mode (§15) can prioritize records where calibrated confidence
  diverges most from raw confidence
- Campaign planning (§18) can estimate database quality, not just size

## 19b. Calibration data source

Calibration requires paired (predicted_confidence, actual_correctness)
observations. These come from:

1. **Benchmark papers** (§20): gold-standard records from calibration
   seed papers where the user verified every extraction
2. **Audit outcomes** (§15): records that were re-extracted and either
   confirmed or corrected
3. **User corrections**: mid-session corrections (§14f) that changed
   trait field values

All calibration data is stored in `state/calibration_data.jsonl`:

```json
{"doi": "10.1234/example", "species": "Cicindela campestris", "field": "chromosome_number_2n", "predicted_confidence": 0.88, "correct": true, "source": "benchmark", "session_id": "2026-03-24T14:30:00Z"}
{"doi": "10.1234/example", "species": "Cicindela campestris", "field": "sex_chr_system", "predicted_confidence": 0.88, "correct": false, "source": "audit_correction", "session_id": "2026-03-25T10:00:00Z"}
```

## 19c. Calibration method: isotonic regression

Use isotonic regression (monotone non-decreasing function fit) to map
raw confidence → calibrated probability. This is the standard post-hoc
calibration method (Platt scaling is for binary classifiers; isotonic
regression is more flexible and requires no distributional assumptions).

```python
from sklearn.isotonic import IsotonicRegression
import json, numpy as np

# Load calibration data
data = []
with open("state/calibration_data.jsonl") as f:
    for line in f:
        data.append(json.loads(line))

if len(data) < 20:
    print("Insufficient calibration data (<20 observations). Using raw confidence.")
    # Fall back to identity mapping
else:
    predicted = np.array([d["predicted_confidence"] for d in data])
    actual = np.array([1.0 if d["correct"] else 0.0 for d in data])

    ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    ir.fit(predicted, actual)

    # Save the calibration model
    calibration = {
        "method": "isotonic_regression",
        "n_observations": len(data),
        "date": "2026-03-25",
        "bins": list(zip(ir.X_thresholds_.tolist(), ir.y_thresholds_.tolist()))
    }
    with open("state/calibration_model.json", "w") as f:
        json.dump(calibration, f, indent=2)
```

**When sklearn is unavailable**, use a simple binned calibration fallback:

```python
# Bin predicted confidence into 10 bins, compute actual accuracy per bin
bins = np.linspace(0, 1, 11)
bin_indices = np.digitize(predicted, bins) - 1
calibration_map = {}
for i in range(10):
    mask = bin_indices == i
    if mask.sum() > 0:
        bin_center = (bins[i] + bins[i+1]) / 2
        actual_acc = actual[mask].mean()
        calibration_map[f"{bins[i]:.1f}-{bins[i+1]:.1f}"] = {
            "n": int(mask.sum()),
            "predicted_mean": float(predicted[mask].mean()),
            "actual_accuracy": float(actual_acc)
        }
```

## 19d. Per-field calibration

Different fields have different extraction difficulty. `chromosome_number_2n`
(a single integer usually explicit in text) is more reliably extracted than
`karyotype_formula` (complex notation with many variants). Calibrate
per-field when sufficient data exists (>30 observations per field).

Store per-field calibration models in `state/calibration_model.json`:

```json
{
  "global": { "method": "isotonic_regression", "n_observations": 150, ... },
  "per_field": {
    "chromosome_number_2n": { "n_observations": 140, "ece": 0.03, ... },
    "sex_chr_system": { "n_observations": 120, "ece": 0.08, ... },
    "karyotype_formula": { "n_observations": 85, "ece": 0.12, ... }
  }
}
```

## 19e. Expected Calibration Error (ECE)

The primary metric for calibration quality. ECE measures the average gap
between predicted confidence and observed accuracy across bins:

```
ECE = Σ (|bin_count| / N) × |accuracy(bin) - confidence(bin)|
```

Lower is better. ECE < 0.05 is well-calibrated. ECE > 0.15 means
confidence scores are unreliable.

Report ECE in:
- Session-end QC summary (§17e)
- The QC report HTML (§17d)
- Campaign planning reports (§18)

## 19f. Reliability diagram

A visual diagnostic: X-axis = predicted confidence (binned), Y-axis =
observed accuracy. Perfect calibration = diagonal line. Add to
`qc_report.html` when generated with `--full`:

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(1, 1, figsize=(6, 6))
ax.plot([0, 1], [0, 1], 'k--', label='Perfect calibration')
ax.bar(bin_centers, actual_accuracies, width=0.08, alpha=0.7,
       label=f'TraitTrawler (ECE={ece:.3f})')
ax.set_xlabel('Predicted confidence')
ax.set_ylabel('Observed accuracy')
ax.set_title('Confidence Calibration (Reliability Diagram)')
ax.legend()
```

## 19g. Applying calibrated confidence

After extraction, before writing to CSV, apply the calibration model to
transform raw confidence into calibrated confidence:

1. Read `state/calibration_model.json`
2. If sufficient data and model exists:
   - Use per-field calibration if available for the specific field
   - Otherwise use global calibration
   - Store raw confidence in `extraction_confidence` (unchanged)
   - Add `calibrated_confidence` field to the record
3. If no calibration model exists (too few observations), skip — the raw
   confidence is the best available estimate

**New CSV field**: `calibrated_confidence` (float, 0.0–1.0). Added to
`output_fields` in the config template. Empty when calibration model is
not yet available.

## 19h. Triggering recalibration

Recalibrate automatically when:
- 20+ new calibration observations have accumulated since last calibration
- At session end, if benchmark or audit data was generated this session

Recalibration takes < 1 second and is fully automatic.

## 19i. Dependencies

- `scikit-learn` (optional, for isotonic regression): `pip install scikit-learn`
- Falls back to binned calibration if unavailable
- `matplotlib` (optional, for reliability diagram)

Install at session start alongside scipy:
```bash
python3 -c "import sklearn" 2>/dev/null || pip install scikit-learn --break-system-packages -q
```

## 19j. Session-end calibration summary

Add to the QC summary block (§17e):

```
── Calibration ────────────────────
 Calibration data  : {N} observations ({M} fields)
 Global ECE        : 0.042 (well-calibrated)
 Worst field ECE   : karyotype_formula (0.12)
 Recommendation    : More benchmark data for karyotype_formula
────────────────────────────────────
```
