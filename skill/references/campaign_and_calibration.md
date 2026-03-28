# Campaign Planning & Confidence Calibration — On-Demand Reference

Load this file when the user triggers: "plan the campaign", "coverage report",
"how much is left", "calibrate", "check calibration", "reliability diagram".

---

## Campaign Planning

Available after 3+ collection sessions.

### Data Sources
- `results.csv` — current database
- `state/processed.json` — all papers seen
- `state/search_log.json` — queries completed
- `state/run_log.jsonl` — session history
- `state/taxonomy_cache.json` — known families
- `config.py` — total query count
- `leads.csv` — papers needing full text

### Coverage Analysis

1. **Query GBIF** for known species count per family in the target taxon:
   `https://api.gbif.org/v1/species/search?rank=FAMILY&higherTaxonKey={taxon_key}&limit=100`
   For each family, get species count from occurrence facets.

2. **Build coverage table**:
   ```
   Family          | Records | Species | GBIF Known | Coverage %
   Carabidae       | 234     | 89      | 40,000     | 0.2%
   Cicindelidae    | 45      | 22      | 2,700      | 0.8%
   ```
   Note: small percentages are normal for large taxa — report them without alarm.

3. **Identify gaps**: families with 0 records but likely data in literature.

### Search Efficiency Analysis

- Queries completed / total from config.py
- Papers processed, records extracted
- Records/paper mean (higher = more productive papers)
- Records/query mean (higher = better-targeted queries)
- Top-yielding query patterns (rank by records extracted)
- Low-yield patterns (< 1 record/query) — candidates for removal
- Citation chaining yield vs keyword search yield

### Data Quality Section (if calibration exists)

- Calibrated confidence mean
- Records above 0.9 confidence, below 0.6
- Per-field accuracy from benchmark data
- Recommendations for low-scoring fields

### Cross-Paper Concordance

- Species with data from multiple papers
- Concordant observations (%)
- Conflicting observations (%) with specific conflicts listed

### Leads Pipeline

- Total leads, breakdown by reason (paywall, no_oa, timeout)
- Estimated records if all leads were obtained (based on current yield rate)

### Strategic Recommendations

Prioritized actionable list:
1. Obtain high-value leads (estimated records × triage confidence)
2. Focus remaining queries on underrepresented families
3. Citation chain from unused high-confidence papers
4. Deprioritize low-yield query patterns
5. Audit low-confidence records from early sessions

### Effort Estimate

- Sessions to exhaust remaining queries (at current papers/session rate)
- Sessions to reach 50% family coverage (extrapolating current rate)
- Sessions to exhaust all leads + queries

### Output

Print to conversation AND save to `campaign_report.md` with timestamp.
Generation should take < 60 seconds. Advisory only — never modify config
files automatically.

---

## Confidence Calibration

### Why Calibrate

LLMs are systematically overconfident. A record tagged 0.9 confidence might
actually be correct only 75% of the time. Calibration closes this gap by
fitting a monotone function that maps heuristic scores to empirical
accuracy rates.

### Data Source

`state/calibration_data.jsonl` — entries with `(predicted_confidence, correct)`
pairs from:
- Benchmark papers (calibration holdouts where user verified every field)
- Audit outcomes (confirmed = correct, corrected = incorrect)
- User corrections (mid-session correction = incorrect for old value)

### Method: Isotonic Regression

```python
from sklearn.isotonic import IsotonicRegression
ir = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
ir.fit(predicted_confidences, actual_correct_flags)
calibrated = ir.predict(new_confidences)
```

**Fallback** (if sklearn unavailable): binned calibration — divide [0,1]
into 10 bins, compute accuracy per bin, use bin accuracy as calibrated value.

### Model Output

Save to `state/calibration_model.json`:
```json
{
  "method": "isotonic",
  "n_observations": 156,
  "date": "2026-03-27",
  "global": {"X_thresholds": [...], "y_thresholds": [...]},
  "per_field": {
    "chromosome_number_2n": {"X_thresholds": [...], "y_thresholds": [...], "n": 42}
  }
}
```

### Per-Field Calibration

When >= 30 observations exist for a specific field, create a per-field model.
Per-field models take precedence over the global model when available.

### ECE (Expected Calibration Error)

ECE = sum over bins of (|bin_count| / N) * |accuracy(bin) - confidence(bin)|

Interpretation:
- ECE < 0.05: well-calibrated
- ECE 0.05-0.15: moderate, usable
- ECE > 0.15: unreliable — need more calibration data

### Application

The Writer agent applies calibration automatically (see `writer.md` Step 3).
- Raw score stays in `extraction_confidence`
- Calibrated score goes in `calibrated_confidence`
- Skip if < 10 calibration observations

### Recalibration Triggers

Re-fit the model when:
- 20+ new observations added since last fit
- Session end (if new calibration data exists)
- User requests ("calibrate", "recalibrate")

### Session Summary Block

```
Calibration: {n_observations} observations | ECE {ece:.3f} |
  Worst field: {field_name} (ECE {field_ece:.3f})
  Recommendation: {advice}
```
