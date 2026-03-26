# Multi-Agent Consensus Extraction

When a standard extraction produces low-confidence results, TraitTrawler
can run multiple independent extraction passes with different prompting
strategies and use consensus voting to improve accuracy. This mirrors
the dual-reviewer pattern in systematic reviews (otto-SR achieves 96.7%
sensitivity with dual workflows) and Anthropic's multi-agent research
architecture.

## 21a. When to trigger

Consensus extraction activates when ALL of these conditions are met:

1. A paper's initial extraction produces records where the **mean
   confidence < consensus_config.trigger_threshold** (default: 0.7)
2. The paper has **full text available** (not abstract-only — consensus
   on abstracts wastes tokens for minimal gain)
3. **consensus_config.enabled** is true (default: true)
4. The project has processed **>20 papers** (consensus is expensive —
   skip during early calibration when guide.md is still evolving)

Additionally, the user can force consensus on any paper: "run consensus
on this paper", "double-check this extraction", "verify extraction".

## 21b. The three passes

Each pass uses a **different prompting strategy** to avoid correlated
errors. All passes receive the same PDF text and guide.md, but frame the
extraction task differently:

### Pass 1: Standard extraction (already completed)
The normal extraction per §7. This is the baseline.

### Pass 2: Enumeration-first extraction
Prompt strategy: "First, list every species mentioned anywhere in this
paper. For each species, list every table, figure, or text passage that
contains trait data. Then extract one record per species-observation pair."

This catches species missed by the standard pass (which may skim
non-results sections) and ensures table rows aren't skipped.

### Pass 3: Adversarial verification
Prompt strategy: "Given the following proposed extraction [pass 1 results],
find evidence in the paper that CONTRADICTS any of these values. For each
record, verify that the extracted value matches the source text exactly.
Report any discrepancies."

This is NOT a third independent extraction — it's a targeted check that
uses pass 1 as a starting point and tries to disprove it. This catches
transcription errors, notation misinterpretations, and table-row misalignment.

## 21c. Consensus resolution

After all three passes complete, resolve each record:

### Field-level voting
For each field in each record:

| Pass 1 | Pass 2 | Pass 3 | Resolution |
|--------|--------|--------|------------|
| A | A | agrees | Accept A, boost confidence by +0.1 |
| A | A | flags discrepancy | Accept A, note discrepancy, keep confidence |
| A | B | agrees with A | Accept A, note disagreement |
| A | B | agrees with B | Accept B (2/3 majority), note change |
| A | B | flags both | Flag for human review |
| A | B | C (different) | Flag for human review |

### Record-level consensus
- **Full agreement**: all passes found the same species with same values →
  mark `consensus_agreement: "full"`, boost confidence +0.1 (capped at 1.0)
- **Partial agreement**: species match, some fields differ → resolve per
  field-level voting above, mark `consensus_agreement: "partial"`
- **Disagreement**: passes found different species or fundamentally
  different records → mark `consensus_agreement: "disputed"`, flag for review
- **Pass 2 found extra records**: records present in pass 2 but not pass 1
  → add them with `consensus_agreement: "pass2_only"`, lower confidence by -0.1

## 21d. Consensus statistics

Track consensus outcomes in `state/consensus_stats.json`:

```json
{
  "total_consensus_papers": 15,
  "full_agreement_pct": 67.3,
  "partial_agreement_pct": 24.1,
  "disputed_pct": 8.6,
  "extra_records_found": 12,
  "corrections_from_consensus": 8,
  "field_disagreement_rates": {
    "chromosome_number_2n": 0.03,
    "sex_chr_system": 0.11,
    "karyotype_formula": 0.18
  },
  "tokens_spent_on_consensus": 145000
}
```

Report at session end:
```
── Consensus Extraction ────────────
 Papers sent to consensus  : 3
 Full agreement            : 2 (67%)
 Corrections found         : 1 (in karyotype_formula)
 Extra records discovered  : 2
 Tokens spent on consensus : ~45,000
────────────────────────────────────
```

## 21e. Model routing for consensus

- **Pass 2 (enumeration)**: Same model as standard extraction (sonnet)
- **Pass 3 (adversarial)**: Same model as standard extraction (sonnet)
- If pass 3 flags a discrepancy AND confidence is still < 0.6 after
  resolution → escalate to opus for a final adjudication pass

**Cost control**: Consensus roughly triples extraction cost for triggered
papers. The trigger threshold (default: 0.7) should be tuned to balance
accuracy improvement against token budget. Track `tokens_spent_on_consensus`
and report the marginal cost.

## 21f. Integration with other features

- **Calibration data** (§19): Consensus outcomes (confirmed/corrected)
  feed into `state/calibration_data.jsonl` as calibration observations
- **Benchmark** (§20): Consensus corrections on benchmark papers update
  the gold standard
- **Chain-of-thought traces** (§22): Each consensus pass stores its own
  trace, enabling disagreement analysis
- **Discovery logging** (§14): If passes disagree on notation, log as
  `ambiguity_pattern` discovery

## 21g. New CSV field

- `consensus_agreement`: string, one of `"full"`, `"partial"`,
  `"disputed"`, `"pass2_only"`, or empty (consensus not triggered).
  Added to `output_fields` in the config template.

## 21h. Configuration

```yaml
# In collector_config.yaml:
consensus_config:
  enabled: true
  trigger_threshold: 0.7       # Mean confidence below this triggers consensus
  min_papers_before_active: 20 # Don't run consensus until guide.md is stable
  max_consensus_per_session: 5 # Cap to control token spend
```

## 21i. User-triggered consensus

The user can say:
- "run consensus on this paper" — triggers consensus on the current paper
- "consensus mode" — lower trigger_threshold to 0.9 (consensus on everything)
- "verify last extraction" — run passes 2+3 on the most recently extracted paper
