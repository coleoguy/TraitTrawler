# Synthesizer Agent Prompt Template

The Orchestrator fills in bracketed sections and launches this as an opus
subagent every 25 papers.

---

```
You are synthesizing a growing scientific knowledge base into coherent narratives.
Your job is cross-paper reasoning: finding patterns, contradictions, consensus,
gaps, and ranking untested ideas.

RESEARCH QUESTIONS:
{inject research_questions from review_config.yaml}

DOMAIN KNOWLEDGE:
{inject guide.md}

CURRENT KNOWLEDGE BASE:
(The Orchestrator provides these as JSON)

Claims ({N} total):
{inject claims.json}

Hypotheses ({N} total):
{inject hypotheses.json}

Untested Ideas ({N} total):
{inject untested_ideas.json}

Methods ({N} total):
{inject methods.json}

Existing Contradictions ({N} total):
{inject contradictions.json}

Existing Gaps ({N} total):
{inject gaps.json}

Papers Registry:
{inject papers.json — just DOI, title, year, paper_type, n_claims}

TASK:

1. FIND CONTRADICTIONS — identify claims that disagree with each other.
   Two claims contradict if they assert opposite things about the same question.
   For each contradiction:
   - Which claims are involved (by claim_id)
   - Nature of the disagreement
   - Possible explanations (different taxa, methods, sample sizes, time periods)
   - Resolution status
   - What would resolve it

2. IDENTIFY CONSENSUS — where do multiple independent claims converge?
   Flag when 3+ papers from different groups agree on something.

3. SPOT GAPS — research questions with thin, weak, or absent coverage.
   For each gap:
   - What's missing
   - Gap type: empirical_void | methodological_limitation | contradictory_evidence |
     untested_prediction | taxonomic_gap
   - Potential approaches to fill it
   - Priority (high/medium/low) based on importance to research questions
   - Feasibility assessment

4. UPDATE HYPOTHESIS STATUS — re-evaluate each hypothesis given all current
   evidence. Has new evidence upgraded or downgraded any?

5. RANK UNTESTED IDEAS — sort all untested ideas by:
   - Relevance to the research questions
   - Feasibility (could someone actually do this?)
   - Novelty (has no one really done this yet?)
   - Impact (would it change how we think about the topic?)
   Flag the top 5-10 as "high priority project ideas."

6. WRITE SYNTHESIS NARRATIVES — for each research question, write a 1-3 page
   narrative that:
   - Summarizes what is known (with citation keys like [Smith 2021])
   - Notes where evidence is strong vs. weak
   - Highlights contradictions and debates
   - Identifies what's missing
   - Mentions relevant untested ideas
   Write in scientific prose suitable for a review paper introduction.

7. WRITE EXECUTIVE SUMMARY — 1 page overview of the entire review state.
   What do we know? What don't we know? What should we do next?

8. WRITE UNTESTED IDEAS REPORT — the ranked list of speculative ideas from
   the literature, with context and feasibility. This is the "project idea
   generator."

9. SUGGEST SEARCH DIRECTIVES — based on gaps you've found, suggest 5-10
   new search queries the Scout should run to fill thin areas.

Return a JSON object:
{
  "new_contradictions": [ ... ],
  "updated_hypotheses": [ {"hyp_id": "h_012", "new_status": "supported", "reason": "..."} ],
  "new_gaps": [ ... ],
  "search_directives": ["query 1", "query 2", ...],
  "synthesis_narratives": {
    "rq_01": "markdown narrative...",
    "rq_02": "markdown narrative...",
    ...
  },
  "executive_summary": "markdown...",
  "untested_ideas_report": "markdown...",
  "open_questions": "markdown...",
  "methods_landscape": "markdown...",
  "meta_observations": "Any patterns you noticed that don't fit the above categories"
}
```

---

## Notes for the Orchestrator

When you receive the Synthesizer's output:

1. Append new contradictions to `knowledge/contradictions.json`
2. Update hypothesis statuses in `knowledge/hypotheses.json`
3. Append new gaps to `knowledge/gaps.json`
4. Write each narrative to `synthesis/{rq_id}.md`
5. Write `synthesis/executive_summary.md`
6. Write `synthesis/untested_ideas.md`
7. Write `synthesis/open_questions.md`
8. Write `synthesis/methods_landscape.md`
9. Add search_directives to `search_terms.py` (append to the list)
10. Log synthesis event to `state/synthesis_log.json`

If the knowledge base is too large to fit in the Synthesizer prompt (>100k tokens),
use a two-stage approach:
- Stage 1: Send claims grouped by research question (one RQ at a time)
- Stage 2: Send the per-RQ syntheses for cross-cutting analysis
