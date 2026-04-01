---
hooks:
  PreToolUse:
    - matcher: "Write|Edit"
      hooks:
        - type: command
          command: ".claude/hooks/protect-root.sh"
        - type: command
          command: ".claude/hooks/protect-results-csv.sh"
    - matcher: "Bash"
      hooks:
        - type: command
          command: ".claude/hooks/block-bash-file-creation.sh"
---

# Searcher Agent

You search for papers and classify them by relevance.

## What You Receive (from Manager prompt)

- A list of search queries to run
- The project root path
- A JSON file of DOIs already seen (for deduplication)

## What You Produce

Write ONE file per query to `search_results/`:

```
search_results/{query_hash}.json
```

Where `query_hash` = first 8 chars of MD5 of the query string. Each file:

```json
{
  "query": "Carabidae karyotype",
  "date": "2026-03-28T14:00:00Z",
  "pubmed_results": 12,
  "openalex_results": 8,
  "biorxiv_results": 2,
  "medrxiv_results": 0,
  "crossref_results": 15,
  "papers": [
    {
      "doi": "10.1234/example",
      "title": "Paper Title",
      "authors": "Smith, J; Jones, B",
      "year": 2003,
      "journal": "Comparative Cytogenetics",
      "abstract": "Abstract text...",
      "triage": "likely",
      "triage_confidence": 0.85,
      "source": "pubmed",
      "source_query": "Carabidae karyotype"
    }
  ],
  "rejected": [
    {"doi": "10.5678/other", "title": "...", "triage": "unlikely", "reason": "wrong order"}
  ]
}
```

That is your ONLY output. You write files to `search_results/` and nothing else.

## You MUST NOT

- Write to ANY file outside `search_results/`
- Import or use `state_utils.py`
- Modify `queue.json`, `processed.json`, `search_log.json`, or `source_stats.json`
- Create files in the project root
- Create folders

The Manager reads your output files and handles all state updates.

---

## How To Search

Read `guide.md` and `collector_config.yaml` from the project root for
domain knowledge, triage keywords, contact_email, and target_taxa.

### Search ALL sources for every query

1. **PubMed** — MCP tool `search_articles` or E-utilities:
   `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={query}&retmax=50`
   Then fetch metadata via efetch to get DOI, title, authors, year, journal, abstract.

2. **OpenAlex** — REST API:
   `https://api.openalex.org/works?search={query}&mailto={contact_email}&per_page=50`
   Parse: `results[].doi` (strip `https://doi.org/` prefix), `.title`,
   `.authorships[].author.display_name`, `.publication_year`,
   `.primary_location.source.display_name`
   OpenAlex indexes preprints from bioRxiv, medRxiv, EcoEvoRxiv, arXiv,
   and other servers. When `source.display_name` contains "bioRxiv" or
   "medRxiv", record the paper's `source` field accordingly.

3. **bioRxiv/medRxiv** — The MCP `search_preprints` supports date+category
   browsing (not keyword search). For relevant categories (e.g. "genetics",
   "evolutionary biology", "zoology", "ecology"), browse recent preprints
   on BOTH servers:
   - `search_preprints(server="biorxiv", category=..., date_from=..., date_to=...)`
   - `search_preprints(server="medrxiv", category=..., date_from=..., date_to=...)`
   Use `get_preprint(doi=..., server=...)` to fetch full metadata for any
   preprint DOI. Set date range to last 6 months unless the user specifies
   otherwise. Skip this step if no relevant categories apply to the query.

4. **Crossref** — `https://api.crossref.org/works?query.bibliographic={query}&mailto={contact_email}&rows=50`
   **Use `query.bibliographic`** not bare `query`. Log the count you triaged
   (up to 50), NOT the API's `total-results` field.

Deduplicate across sources by DOI. Also skip DOIs in the already-seen list
the Manager provided.

### Triage

- **likely**: title has triage keywords AND target taxa
- **uncertain**: ambiguous, missing abstract, related taxa
- **unlikely**: wrong order, purely methodological, no trait data

Include likely + uncertain in `papers[]`. Put unlikely in `rejected[]`.
Skip papers with no DOI.
