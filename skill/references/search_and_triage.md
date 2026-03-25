# Search and Triage

## 3. Search

Pull the next unrun query from the search term list in `config.py`.

Run each query against multiple sources to maximize coverage. Different databases
index different journals — PubMed is biomedical-biased, OpenAlex covers the long
tail of taxonomy and ecology journals, Crossref catches regional publications.

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

### 3b. Citation chaining

When all keyword searches from `config.py` are exhausted and the queue is empty,
offer to check references from high-confidence papers using OpenAlex:

```
All {N} keyword searches complete. Want me to check references from
high-confidence papers for additional leads? [y/n]
```

If yes, use `get_work_references` from OpenAlex to fetch the reference lists
of papers with `extraction_confidence >= 0.8`. For each reference, triage based
on title and abstract (if available) and add likely/uncertain papers to the queue.

Log each citation-chain search as a special entry in `search_log.json`:
```json
{
  "citation_chain_from_doi_10.1234/example.5678": {
    "date": "2026-03-24",
    "source_paper": "Smith et al. 2021",
    "references_found": 87,
    "new_to_queue": 12
  }
}
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
