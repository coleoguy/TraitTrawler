# Knowledge Atom Schemas

This file defines the JSON structures for all knowledge types extracted by
Reader agents. The Orchestrator assigns IDs; Readers return raw objects.

---

## Claims

A claim is an atomic assertion extracted from a paper — one finding, one
conclusion, one result. Granularity matters: "Species X has 2n=20 and an XY
system" is TWO claims, not one. Err toward splitting.

```json
{
  "claim_id": "c_00142",
  "paper_doi": "10.1234/example",
  "claim_text": "Sex chromosome-autosome fusions fix at higher rates in species with male-biased mutation",
  "claim_type": "finding | hypothesis_test | method_conclusion | review_synthesis | replication | null_result",
  "evidence_type": "empirical | theoretical | simulation | meta_analysis | review | case_study",
  "evidence_strength": "strong | moderate | weak | anecdotal",
  "quantitative_support": {
    "effect_size": "OR = 2.3 (or Cohen's d, r, etc. — whatever the paper reports)",
    "p_value": "< 0.001 (or Bayes factor, posterior probability)",
    "sample_size": "n = 47 species (or individuals, populations, etc.)",
    "confidence_interval": "1.4–3.8",
    "test_used": "phylogenetic logistic regression"
  },
  "taxa_scope": ["Mammalia"],
  "methods": ["phylogenetic logistic regression", "dated phylogeny"],
  "caveats": [
    "Limited to mammals; beetles may differ due to Xyp system",
    "Tree topology from a single source"
  ],
  "research_questions": ["rq_01", "rq_02"],
  "extraction_confidence": 0.9,
  "verbatim_quote": "We found that fusion fixation probability was significantly elevated in lineages with higher male mutation bias (OR = 2.3, 95% CI: 1.4–3.8, P < 0.001)",
  "page_or_section": "Results, p. 1247",
  "notes": ""
}
```

### Field rules

- **claim_text**: One sentence summarizing the finding. Write it as a standalone
  assertion that makes sense without reading the paper.
- **claim_type**:
  - `finding`: a new empirical result
  - `hypothesis_test`: the paper explicitly tested a stated hypothesis
  - `method_conclusion`: a finding about a method's performance
  - `review_synthesis`: a conclusion drawn from surveying multiple papers
  - `replication`: confirms/disconfirms a previous finding
  - `null_result`: explicitly tested something and found no effect (valuable!)
- **evidence_strength**:
  - `strong`: large sample, rigorous methods, clear effect
  - `moderate`: decent sample/methods but some limitations
  - `weak`: small sample, exploratory, or methods have known issues
  - `anecdotal`: single case, informal observation, or "we noticed that..."
- **quantitative_support**: Fill in whatever the paper reports. Use `null` for
  fields not reported. If the paper gives no numbers at all, set the whole
  object to `null`.
- **extraction_confidence**: Your confidence that you extracted this correctly
  (0.0-1.0). Lower if from abstract-only, ambiguous text, or scanned PDF.
- **verbatim_quote**: Copy the key sentence(s) from the paper. This is the
  evidence chain — it lets anyone verify the claim against the source.

---

## Hypotheses

A hypothesis is a proposed explanation that may or may not have been tested.

```json
{
  "hyp_id": "h_012",
  "hypothesis": "Meiotic drive favors sex chromosome-autosome fusions in taxa with achiasmate meiosis",
  "first_proposed_by": "10.1234/example",
  "year_proposed": 2015,
  "status": "untested | supported | contested | refuted | well_supported",
  "supporting_claims": ["c_00142", "c_00145"],
  "contradicting_claims": ["c_00056"],
  "test_requirements": "Need comparative dataset of fusion rates + meiotic system across Coleoptera",
  "research_questions": ["rq_02", "rq_05"],
  "taxa_scope": ["Insecta"],
  "notes": "No one has tested this in beetles specifically"
}
```

### Status rules

- **untested**: proposed but no empirical test exists in the knowledge base
- **supported**: at least one claim supports it, none contradict
- **well_supported**: multiple independent claims from different groups support it
- **contested**: claims exist on both sides
- **refuted**: strong evidence against, no surviving support

The Synthesizer updates status as the knowledge base grows. Readers set initial
status based on what the paper reports.

---

## Untested Ideas

These are speculative suggestions from Discussion/Conclusion sections that the
paper itself did NOT address. This is the most valuable extraction target for
finding new projects.

```json
{
  "idea_id": "u_034",
  "paper_doi": "10.1234/example",
  "idea_text": "It remains to be tested whether the elevated fusion rate in Coleoptera reflects meiotic drive acting through the Xyp system",
  "verbatim_quote": "One intriguing possibility is that the parachute configuration of the Xyp system in Coleoptera creates a meiotic environment that favors fusion fixation, though this remains untested.",
  "context": "Authors found elevated fusion rates in beetles vs other insects but could not explain why",
  "idea_type": "future_experiment | alternative_explanation | methodological_suggestion | taxonomic_extension | theoretical_prediction",
  "testability": "Could test with ChromePlus data: compare fusion rates between Xyp and XY beetle lineages using phylogenetic logistic regression",
  "feasibility": "high | medium | low | unknown",
  "research_questions": ["rq_02"],
  "taxa_mentioned": ["Coleoptera"],
  "has_been_tested_elsewhere": false,
  "notes": ""
}
```

### What counts as an untested idea

YES — extract these:
- "We hypothesize that..." (when they don't test it in the paper)
- "One possible explanation is..."
- "Future studies should investigate..."
- "It remains to be tested whether..."
- "An alternative interpretation is..."
- "This raises the possibility that..."
- "An important next step would be..."
- "Whether this pattern extends to [other taxa] is unknown"

NO — do NOT extract these:
- Hypotheses that the paper actually tested (those go in hypotheses)
- Generic statements like "more research is needed"
- Requests for more data without a specific testable idea
- Caveats about the current study (those go in claim caveats)

### idea_type

- `future_experiment`: a specific experiment or analysis someone should do
- `alternative_explanation`: a different interpretation of the data
- `methodological_suggestion`: a better way to analyze something
- `taxonomic_extension`: "does this pattern hold in group X?"
- `theoretical_prediction`: a model predicts something untested

### feasibility

Your rough assessment of how doable this is with existing tools/data:
- `high`: could be done now with available data (e.g., existing databases, ChromePlus)
- `medium`: would need new data collection but nothing exotic
- `low`: would require major new technology, decades of fieldwork, etc.
- `unknown`: can't tell from context

---

## Methods

```json
{
  "method_id": "m_008",
  "name": "Phylogenetic logistic regression (Ives & Garland 2010)",
  "category": "comparative | experimental | observational | computational | statistical",
  "used_in": ["10.1234/a", "10.1234/b"],
  "description": "Logistic regression on a phylogeny for binary traits",
  "strengths": ["Handles binary traits", "Accounts for branch lengths"],
  "limitations": ["Sensitive to tree topology", "Convergence issues with <50 tips"],
  "alternatives": ["Bayesian threshold model", "BayesTraits multistate"],
  "key_reference": "10.1086/650729",
  "notes": ""
}
```

Methods accumulate: if a method already exists in methods.json, the Reader
should note the DOI in `used_in` rather than creating a duplicate. The
Orchestrator handles deduplication by method name.

---

## Key References (for citation chasing)

The Reader also returns a list of references to follow up:

```json
{
  "doi": "10.xxxx/yyyy",
  "title": "...",
  "authors": "...",
  "year": 2018,
  "why_important": "Foundational dataset for sex chromosome evolution in beetles",
  "cited_by": "10.1234/example",
  "research_questions": ["rq_01"]
}
```

These go into `state/citation_queue.json`. The Scout processes them in
subsequent runs — looks up metadata, triages, adds to leads.csv if relevant.

---

## Papers Registry

The Orchestrator maintains `knowledge/papers.json`:

```json
{
  "10.1234/example": {
    "doi": "10.1234/example",
    "title": "Sex chromosome fusions in mammals",
    "authors": ["Smith, J.", "Jones, K."],
    "first_author": "Smith",
    "year": 2021,
    "journal": "Evolution",
    "abstract": "...",
    "paper_type": "empirical",
    "taxa_studied": ["Mammalia"],
    "methods_used": ["phylogenetic logistic regression"],
    "pdf_path": "pdfs/Smith_2021_Evolution.pdf",
    "pdf_source": "open_access",
    "read_depth": "full_text",
    "date_processed": "2026-03-21",
    "n_claims": 7,
    "n_hypotheses": 2,
    "n_untested_ideas": 1,
    "n_refs_queued": 3,
    "research_questions_addressed": ["rq_01", "rq_02"],
    "extraction_quality_score": 0.87,
    "last_reextraction": null,
    "qc_category": null
  }
}
```

### QC tracking fields

**`extraction_quality_score`** — computed by the Orchestrator after each Reader
returns. Formula: mean of `extraction_confidence` across all claims for this paper.
Range 0.0–1.0. Abstract-only papers are capped at ≤ 0.5 regardless of per-claim
scores (abstract extraction is inherently uncertain). Set to `null` if no claims
were extracted.

**`last_reextraction`** — ISO date string of the most recent QC re-extraction,
or `null` if the paper has been processed only once. Updated by the QC loop
(SKILL.md §4b step 4) after each re-extraction completes.

**`qc_category`** — the QC category from the most recent audit: `"A"` (abstract-only),
`"B"` (low-confidence), `"C"` (stale), or `null` if not currently flagged. Updated
at startup when the Orchestrator computes QC candidate counts. Cleared to `null`
after a successful re-extraction that brings the paper above threshold.
