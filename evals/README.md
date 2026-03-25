# TraitTrawler Evaluation Suite

This directory contains evaluations for the `trait-trawler` skill organized into the three categories recommended by Anthropic: triggering tests, functional tests, and performance comparisons.

## Test Categories

### 1. Triggering Tests (`trigger_tests.json`)

Tests whether the skill activates on the right prompts and stays silent on the wrong ones.

**Should trigger (7 cases):**
- Explicit data collection requests ("collect trait data", "run a session")
- PDF-first mode ("extract data from these PDFs")
- Campaign planning ("plan the campaign", "coverage report")
- Audit mode ("audit the database")

**Should NOT trigger (5 cases):**
- Literature review questions (deepscholar territory)
- One-off paper summaries
- "Collect some thoughts" (non-data use of "collect")
- Data visualization requests
- Manuscript writing

### 2. Functional Tests (`functional_tests.json`)

Tests core skill behaviors with synthetic data and expected outcomes.

| Test | What it validates |
|:-----|:-----------------|
| Setup wizard | Config detection, interactive Q&A, file generation |
| Triage accuracy | Keyword-based classification of 5 abstracts |
| Table extraction | Two-pass extraction of 5-row karyotype table |
| Session resume | State file reading, skip-already-processed, correct status |
| Near-miss triage | Rejects plausible-but-irrelevant abstracts |
| Model routing | Haiku for search/triage, sonnet for extraction, opus escalation |

### 3. Performance Tests (`performance_tests.json`)

Compares skill-equipped agent vs. bare Claude on the same tasks. These are designed for A/B evaluation — run each test with and without the skill and compare metrics.

| Test | Key metric |
|:-----|:----------|
| Extraction accuracy | Records correct, notation handling, provenance fields |
| Triage precision | False positive rate on near-miss abstracts |
| Session efficiency | Dedup, state tracking, schema consistency over 10 papers |
| Taxonomy resolution | Synonym detection, GBIF integration, no phantom diversity |

### Legacy Tests (`eval_*.json`)

The original eval files remain for backward compatibility. They follow the per-test JSON format:

```json
{
  "skills": ["trait-trawler"],
  "query": "User request to the agent",
  "files": [{"name": "file.json", "content": "..."}],
  "expected_behavior": ["Condition 1", "Condition 2"]
}
```

## Running Tests

### Manual
1. Install the skill in Cowork
2. Prepare any mock files from the `files` array
3. Submit the `query` to the agent
4. Verify all `expected_behavior` conditions are met

### Automated
```bash
claude eval evals/trigger_tests.json
claude eval evals/functional_tests.json
claude eval evals/performance_tests.json
```

## Interpreting Results

**Pass:** All expected behaviors observed
**Fail:** One or more expected behaviors not observed
**Needs Investigation:** Behaviors partially met or edge cases

For triggering tests, the key metric is zero false triggers on should-not-trigger cases. For functional tests, check each expected_behavior line. For performance tests, the skill should match or exceed bare-model accuracy while adding provenance, confidence, and validation that the bare model omits.
