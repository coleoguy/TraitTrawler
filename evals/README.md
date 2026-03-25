# TraitTrawler Evaluation Suite

This directory contains a comprehensive evaluation suite for TraitTrawler, an autonomous literature mining agent that searches scientific databases, retrieves PDFs, extracts structured phenotypic data, and writes results to CSV.

## Evaluation Tests

### 1. **eval_setup_wizard.json**
Tests the initial configuration workflow when no `collector_config.yaml` exists.

**What it tests:**
- Detection of missing configuration files
- Proper execution of the setup wizard
- Prompts for target taxa, trait definition, and triage keywords
- Prevents premature search/extraction before configuration

**Success criteria:** Agent detects missing config and guides user through all setup steps without attempting database operations.

---

### 2. **eval_triage_accuracy.json**
Tests the core triage classification system with 10 realistic paper abstracts.

**What it tests:**
- Accuracy of relevance classification (relevant vs. irrelevant)
- Handling of near-miss papers (superficially relevant but not actually useful)
- Consistent application of triage rules across a diverse abstract set

**Test data:**
- 4 clearly relevant karyotype papers (gold standard)
- 3 clearly irrelevant papers (ecology, behavior, molecular phylogenetics)
- 3 near-miss papers (mention chromosomes casually, genome assembly, population genetics)

**Success criteria:** Agent correctly classifies at least 9 of 10 papers with appropriate confidence levels (likely/unlikely/uncertain).

---

### 3. **eval_table_extraction.json**
Tests data extraction from table-heavy papers, which often contain concentrated phenotypic data.

**What it tests:**
- Two-pass extraction strategy (enumerate first, extract second)
- Parsing of structured karyotype data tables
- Accurate field mapping to output CSV columns
- Handling of 8 species records in a single table

**Success criteria:** Agent extracts all 8 species records with correct values for 2n, sex chromosome system, and locality. Uses enumeration phase to identify all rows before extraction.

---

### 4. **eval_session_resume.json**
Tests state management and resumption of long-running collection tasks.

**What it tests:**
- Correct reading of session state files
- Skipping of already-processed papers
- Resumption from correct query index
- Accurate status reporting (queries run, papers processed)

**Test scenario:**
- 5 queries already completed
- 3 papers already extracted
- Expects agent to skip them and continue from query 6

**Success criteria:** Agent correctly identifies processed items, reports accurate status counts, and continues without re-processing.

---

### 5. **eval_near_miss_triage.json**
Targeted test for the "near-miss" triage challenge—papers that appear relevant but should NOT trigger extraction.

**What it tests:**
- Review papers that cite but don't report original data
- Phylogenetics papers mentioning chromosomal changes in non-karyotype context
- Applied/pest management papers with genetic mentions but no phenotypic data
- Papers on chromosomes in off-target taxa
- Methods editorials with no species-specific data

**Success criteria:** Agent classifies all 5 abstracts as unlikely or uncertain (never "likely"). Demonstrates robust understanding that data presence ≠ relevance.

---

## Running the Evaluations

Each test file is a JSON document following a standard structure:

```json
{
  "skills": ["traittrawler"],
  "query": "User request to the agent",
  "files": [{"name": "file.json", "content": "..."}],
  "expected_behavior": [
    "Condition 1",
    "Condition 2"
  ]
}
```

### Manual Testing
To run a test manually:
1. Load the skill with `claude -s traittrawler`
2. Prepare any mock files listed in the `files` array
3. Submit the `query` to the agent
4. Verify that all `expected_behavior` conditions are met

### Automated Testing (Recommended)
Use Anthropic's evaluation framework:
```bash
claude eval evals/eval_setup_wizard.json
claude eval evals/eval_triage_accuracy.json
claude eval evals/eval_table_extraction.json
claude eval evals/eval_session_resume.json
claude eval evals/eval_near_miss_triage.json
```

---

## Test Data Notes

All test data is scientifically realistic:
- Uses real journal names (Genome Biology, Chromosome Research, etc.)
- Includes plausible DOIs with correct format
- Species names follow binomial nomenclature
- Karyotype notation follows standard cytogenetics conventions (2n = diploid number)
- Sex chromosome systems use established abbreviations (XY, ZW, XO, etc.)

---

## Interpreting Results

**Pass:** All expected behaviors observed
**Fail:** One or more expected behaviors not observed
**Needs Investigation:** Behaviors partially met or inconsistent

For failures, examine:
- Error messages in agent logs
- State file contents (if applicable)
- Whether abstraction/generalization rules were correctly applied
