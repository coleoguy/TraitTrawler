# Search and Triage

## 3. Search

Pull the next unrun query from the search term list in `config.py`.

Run each query against multiple sources to maximize coverage. Different databases
index different journals — PubMed is biomedical-biased, OpenAlex covers the long
tail of taxonomy and ecology journals, Crossref catches regional publications.

**Rate limiting**: All API calls are rate-limited by `scripts/api_utils.py`.
When using MCP tools, the tools handle their own rate limiting. When falling
back to direct API calls via WebFetch or Python, use the `resilient_fetch()`
function which enforces per-API rate limits automatically:

| API | Requests/sec | Pool access |
|-----|-------------|-------------|
| PubMed | 3/s (with key) / 1/s (without) | Add `api_key` to E-utilities URL |
| OpenAlex | 10/s (polite) / 1/s (default) | Add `mailto={contact_email}` |
| Crossref | 50/s (polite) / 1/s (default) | Add `mailto:{contact_email}` header |
| bioRxiv | via MCP or Crossref API | N/A |

**Always use the `contact_email` from `collector_config.yaml`** in API calls
to access polite/priority pools. This is the difference between 1 req/s and
10+ req/s on most APIs.

**PubMed** (primary): Use the PubMed MCP `search_articles`. For each result,
call `get_article_metadata` to get DOI, abstract, journal.

**OpenAlex** (primary): Use the OpenAlex MCP `search_works` with the same query.
OpenAlex indexes 250M+ works including many taxonomy, ecology, and regional
natural history journals absent from PubMed. For each result, extract DOI,
title, abstract, journal from the work object.

**bioRxiv/medRxiv** (secondary): Use `search_preprints` — covers recent work not
yet in PubMed. Call `get_preprint` for metadata.

**Crossref** (tertiary): Use the Crossref MCP `search_crossref` for additional
coverage, especially for older publications and non-English journals.

Deduplicate results across all sources against `processed.json` (by DOI; fall
back to normalized title). Add new papers to `queue.json`. Log query text and
timestamp to `search_log.json`. Skip queries already in `search_log.json`.

---

## 3b. Smart Citation Chaining

When all keyword searches from `config.py` are exhausted and the queue is empty,
or when the user requests it ("chain citations", "follow references"), offer:

```
All {N} keyword searches complete. Want me to follow citations from
high-confidence papers for additional leads? [y/n]
```

### Bidirectional chaining

For each seed paper (extraction_confidence >= 0.8):

1. **Forward references**: Use OpenAlex `get_work_references` to get papers
   this seed cites. These are often foundational or methodological papers.

2. **Backward citations** (cited-by): Use OpenAlex `get_work_cited_by` to
   get papers that cite this seed. These are often newer work building on it.

For each discovered paper, triage based on title and abstract (if available)
and add likely/uncertain papers to the queue.

### Priority scoring

Not all citation-discovered papers are equal. Score each by:

| Factor | Points | Rationale |
|---|---|---|
| Seed paper confidence >= 0.9 | +2 | Higher-quality seeds produce better leads |
| Same journal as a high-yield paper | +2 | Journals cluster by topic |
| Author overlap with known high-yield authors | +1 | Specialists publish multiple relevant papers |
| Publication year within 10 years of seed | +1 | Temporal relevance |
| Title contains triage_keywords | +3 | Direct keyword match |
| Abstract available and mentions trait | +2 | Confirmed relevance |

Sort the queue by priority score (descending) so the most promising
citation-discovered papers are processed first.

### Yield tracking

Track yield per source to inform future priority:

```json
{
  "citation_chain_from_doi_10.1234/example.5678": {
    "date": "2026-03-24",
    "source_paper": "Smith et al. 2021",
    "direction": "both",
    "references_found": 87,
    "cited_by_found": 34,
    "new_to_queue": 18,
    "priority_scores": {"mean": 4.2, "max": 8}
  }
}
```

### Coverage estimation

After citation chaining, estimate remaining discoverable papers:

```
📊 Citation Chain Results
   Seed papers used     : 47
   Total refs examined  : 2,340
   New papers found     : 156 (6.7% hit rate)
   Already processed    : 89
   Queue additions      : 67

   Estimated uncovered  : ~{N} papers (based on {X}% new-discovery rate
   declining across chains — suggesting approaching saturation)
```

---

## 4. Triage

Classify each paper yourself using the `triage_rules` in `collector_config.yaml`
and the domain knowledge in `guide.md`. No external API call needed.

The three categories are always:
- **likely**: paper almost certainly contains the target trait data for the target taxa
- **uncertain**: abstract absent/ambiguous, or title implies relevance but can't confirm.
  Err strongly toward uncertain — false negatives are permanent data loss.
- **unlikely**: clearly irrelevant to the trait and/or taxa

**Rule**: If the abstract is missing but title contains any of the `triage_keywords`
from `collector_config.yaml` → classify as "likely".

Move likely/uncertain to fetch. Mark unlikely as processed immediately
(`processed.json` with `"triage": "unlikely"`).

### 4b. Adaptive triage learning

After every 50 papers processed, compute triage accuracy metrics:

```python
# From processed.json, count:
# - Papers triaged "likely" that yielded 0 records (false positives)
# - Papers triaged "uncertain" that yielded records (could have been "likely")
```

Report these at the session end:
```
📊 Triage Accuracy (last 50 papers)
   Likely → records:     34/38 (89%)
   Uncertain → records:  8/12  (67%)
   False positive rate:  4/50  (8%)
```

If the false positive rate exceeds 20%, suggest tightening triage_keywords.
If uncertain→records rate exceeds 50%, suggest loosening triage rules.

### 4c. Active learning for triage (§23)

After 100+ papers processed, shift from static keyword matching to
learned triage with uncertainty sampling. See
[advanced_features.md](references/advanced_features.md) §23 for details.

**Summary**:
- Record triage→outcome pairs in `state/triage_outcomes.jsonl` (after
  each paper: triage classification, records found, abstract keywords)
- After 100+ pairs: compute word-level precision (which abstract words
  predict yield) and suggest keyword additions/removals
- Reorder queue by expected information value: prioritize papers where
  triage confidence is lowest (most informative for learning)
- Track triage precision/recall over time as a learning curve

### 4d. Adaptive source ordering (§24)

Track search source effectiveness in `state/source_stats.json`. After
20+ queries per source, route queries to the most productive API:

- If OpenAlex yields 2x more papers than PubMed for this project's taxa,
  query OpenAlex first
- If bioRxiv yields <1 paper per 10 queries, reduce search frequency
- Dynamically reorder the OA cascade (§5b) by observed PDF retrieval
  success rate (except proxy, which always goes last)

See [advanced_features.md](references/advanced_features.md) §24 for
the full adaptive tool selection protocol.
