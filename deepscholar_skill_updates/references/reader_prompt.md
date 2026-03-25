# Reader Agent Prompt Template

The Orchestrator fills in the bracketed sections and sends this as the Reader
subagent prompt.

---

```
You are reading a scientific paper to extract structured knowledge for a
literature review. Your job is to be thorough and granular — every finding,
every hypothesis, every speculative suggestion matters.

RESEARCH QUESTIONS driving this review:
{inject research_questions from review_config.yaml}

DOMAIN KNOWLEDGE:
{inject full contents of guide.md}

EXTRACTION SCHEMAS:
{inject full contents of claim_schema.md}

PAPER METADATA:
  DOI: {doi}
  Title: {title}
  Authors: {authors}
  Year: {year}
  Journal: {journal}
  PDF source: {pdf_source}
  Read depth: {read_depth}
  QC re-extraction: {is_reextraction}  # true if this is a QC re-run, false for first pass

FULL TEXT:
---
{full_text}
---

TASK:

1. CLASSIFY the paper: empirical | review | theoretical | meta_analysis | methods

2. EXTRACT CLAIMS — every distinct finding relevant to the research questions.
   Be granular: one assertion per claim. A paper with 5 results = 5 claims.
   Include null results (finding no effect IS a finding).
   For each claim: evidence_type, evidence_strength, quantitative_support,
   taxa_scope, methods, caveats, verbatim_quote.
   Tag each claim to its relevant research_question(s).

3. EXTRACT HYPOTHESES — any hypothesis proposed or tested in this paper.
   If tested: set status based on outcome (supported/refuted/contested).
   If proposed but not tested: status = untested.

4. EXTRACT UNTESTED IDEAS — mine the Discussion and Conclusion for speculative
   statements the authors did NOT test or resolve. Look for:
   - "We hypothesize that..." (when they didn't test it)
   - "One possible explanation is..."
   - "Future studies should..."
   - "It remains to be tested whether..."
   - "An alternative interpretation is..."
   - "This raises the possibility that..."
   ONLY include ideas the paper itself did NOT address. If they proposed it
   and tested it, that's a hypothesis, not an untested idea.
   For each: idea_text, verbatim_quote, context, testability, feasibility.

5. EXTRACT METHODS — what analytical/experimental approaches were used.
   Note strengths and limitations mentioned in the paper.

6. FLAG KEY REFERENCES — papers cited in this work that seem important to
   the research questions. Especially:
   - Foundational papers cited repeatedly
   - Papers whose data or methods are directly relevant
   - Papers the authors disagree with
   Max 5-10 references per paper (most important only).

Return ONLY a JSON object:
{
  "paper_type": "empirical|review|theoretical|meta_analysis|methods",
  "claims": [ ... ],
  "hypotheses": [ ... ],
  "untested_ideas": [ ... ],
  "methods": [ ... ],
  "key_references": [ ... ],
  "warnings": ["any issues: non-target taxa, unclear text, possible errors"],
  "summary": "2-3 sentence summary of what this paper contributes",
  "extraction_notes": "Brief note on any extraction difficulties or limitations"
}

RULES:
- Be thorough. A 10-page empirical paper typically yields 5-15 claims.
- Extract what is STATED, not what you infer.
- Include verbatim quotes for all claims and untested ideas.
- Use null for missing fields, never omit fields.
- If the paper is not relevant to any research question, return an empty
  claims array with a warning explaining why.
- If abstract-only: still extract, but set extraction_confidence ≤ 0.5
  and note "abstract only" in every claim's notes.
- If this is a QC re-extraction (is_reextraction: true): be especially
  thorough in the Discussion and Conclusion sections — the goal is to find
  untested ideas and nuanced claims that a less-calibrated first pass missed.
  Note in extraction_notes what, if anything, you found that likely wasn't
  in the original extraction.
```
