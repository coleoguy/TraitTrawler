# Advanced Features

This file covers six features that enhance TraitTrawler's agent
sophistication: chain-of-thought traces, adaptive tool selection, active
learning for triage, cross-project transfer learning, knowledge graph
provenance export, streaming/interruptible execution, and formal
reproducibility.

---

## 22. Chain-of-Thought Extraction Traces

### 22a. Purpose

Every extracted record gets a full reasoning trace stored on disk. This
enables: (a) human verification of WHY a value was extracted, not just
WHAT was extracted; (b) disagreement analysis when audit mode produces
different results; (c) systematic debugging of extraction errors.

### 22b. Trace storage

Create `state/extraction_traces/` directory at project initialization.
Each paper gets a JSON file:

```
state/extraction_traces/{doi_hash}_{first_author}_{year}.json
```

Where `doi_hash` is the last 8 characters of the DOI's MD5 hash (for
filesystem-safe naming).

### 22c. Trace format

```json
{
  "doi": "10.1234/example.5678",
  "paper_title": "Karyotype of Cicindela campestris",
  "extraction_date": "2026-03-24T15:12:00Z",
  "session_id": "2026-03-24T14:30:00Z",
  "document_type": "table-heavy",
  "model_used": "sonnet",
  "records": [
    {
      "trace_id": "tr_abc123",
      "species": "Cicindela campestris",
      "source_passage": "Table 2, row 3: C. campestris, 2n=22, 10+Xyp, conventional staining",
      "reasoning_chain": [
        "1. Identified species as Cicindela campestris from Table 2 header",
        "2. Row 3 lists '2n=22' — explicit diploid count, high confidence",
        "3. Karyotype formula '10+Xyp' — 10 autosome pairs + X and y(p) sex chromosomes",
        "4. Sex system interpretation: Xyp notation indicates parachute association, distinct from standard XY",
        "5. Staining method: 'conventional' stated in Methods section (p.8)"
      ],
      "alternatives_considered": [
        "Considered whether '10+Xyp' could mean n=10 + sex pair, but context confirms 2n=22 total"
      ],
      "extracted_values": {
        "chromosome_number_2n": "22",
        "sex_chr_system": "Xyp",
        "karyotype_formula": "10+Xyp",
        "staining_method": "conventional"
      },
      "confidence_rationale": "Full text, explicit values in table, methods section describes technique → 0.92"
    }
  ],
  "consensus_traces": null
}
```

### 22d. Integration with extraction subagents

When spawning a sonnet subagent for extraction (§7), include in the prompt:

```
For each record you extract, also return a reasoning trace in this format:
{
  "trace_id": "tr_{random_8_chars}",
  "source_passage": "<verbatim text/table row, max 300 chars>",
  "reasoning_chain": ["step 1...", "step 2...", ...],
  "alternatives_considered": ["alternative 1...", ...],
  "confidence_rationale": "<one sentence explaining the confidence score>"
}
```

The subagent returns records + traces together. The main agent writes
traces to disk and links them to CSV records via `extraction_trace_id`.

### 22e. New CSV field

- `extraction_trace_id`: string, e.g. `"tr_abc123"`. Links the CSV
  record to its full reasoning trace in `state/extraction_traces/`.

### 22f. Verification interface

When a record is flagged for review, the agent can present the trace:

```
🔍 Review: Cicindela campestris (10.1234/example.5678)
   Trace ID: tr_abc123

   Source: "Table 2, row 3: C. campestris, 2n=22, 10+Xyp..."

   Reasoning:
   1. Identified species from Table 2 header
   2. Row 3: '2n=22' — explicit diploid count
   3. '10+Xyp' — parachute association, distinct from XY
   4. Staining: 'conventional' from Methods (p.8)

   Alternatives considered:
   - Could '10+Xyp' mean n=10 + sex pair? No — 2n=22 confirms total

   Accept record? [y/n/edit]
```

### 22g. Disagreement analysis for audits

When audit mode (§15) re-extracts a record and gets a different result,
load both traces and present a side-by-side comparison:

```
🔍 Audit Disagreement Analysis
   Species: Cicindela campestris

   Original reasoning (session 2026-03-20):
   → "10+Xyp interpreted as standard XY system"

   Re-extraction reasoning (current session):
   → "10+Xyp interpreted as parachute association (Xyp ≠ XY per guide.md §3.2)"

   Root cause: guide.md was updated to distinguish Xyp from XY after
   session 2026-03-22. The original extraction used outdated rules.
```

---

## 23. Active Learning for Triage

### 23a. Uncertainty sampling

Instead of processing papers in queue order (FIFO), prioritize papers
where the triage model is LEAST confident — these are the papers where
human feedback is most informative.

After triage (§4), assign a triage_confidence score (0.0-1.0):
- 1.0: strong keyword match + clear abstract → definitively likely/unlikely
- 0.5: ambiguous abstract, borderline keywords → uncertain

### 23b. Learning from outcomes

After each paper is processed, record the triage→outcome pair in
`state/triage_outcomes.jsonl`:

```json
{
  "doi": "10.1234/example",
  "triage": "likely",
  "triage_confidence": 0.85,
  "outcome": "extracted",
  "records_found": 5,
  "abstract_words": ["karyotype", "chromosome", "Carabidae", "diploid"],
  "session_id": "2026-03-24T14:30:00Z"
}
```

### 23c. Adaptive triage thresholds

After 100+ triage→outcome pairs accumulate, compute learned thresholds:

```python
import json
from collections import Counter

outcomes = []
with open("state/triage_outcomes.jsonl") as f:
    for line in f:
        outcomes.append(json.loads(line))

# Compute yield by triage category
likely_yield = [o for o in outcomes if o["triage"] == "likely" and o["records_found"] > 0]
unlikely_yield = [o for o in outcomes if o["triage"] == "unlikely" and o["records_found"] > 0]

# Word frequency analysis: which words predict yield?
positive_words = Counter()
negative_words = Counter()
for o in outcomes:
    if o["records_found"] > 0:
        for w in o.get("abstract_words", []):
            positive_words[w] += 1
    else:
        for w in o.get("abstract_words", []):
            negative_words[w] += 1

# Compute word-level precision: P(yield | word present)
# Use these to refine triage_keywords dynamically
```

### 23d. Triage learning curve

Track triage precision/recall over time (sliding window of 50 papers):

```
── Triage Learning ────────────────
 Window: last 50 papers
 Likely → yield    : 92% (was 84% at session 1)
 Uncertain → yield : 45% (was 67% — good, uncertains are being resolved)
 False positive rate: 6% (was 12% — improving)
 Suggested keywords to ADD: "banding", "C-banding"
 Suggested keywords to DROP: "DNA content" (0% yield)
────────────────────────────────────
```

### 23e. Priority queue reordering

After active learning analysis, reorder `queue.json` by expected
information value:

1. **Highest priority**: uncertain-triaged papers with high triage_confidence
   uncertainty (most informative for learning)
2. **High priority**: likely-triaged papers (most likely to yield records)
3. **Low priority**: uncertain papers with low expected yield

---

## 24. Adaptive Tool Selection

### 24a. Source statistics tracking

Track success rates for each data source in `state/source_stats.json`:

```json
{
  "pdf_sources": {
    "unpaywall": {"attempts": 45, "successes": 32, "success_rate": 0.71},
    "openalex": {"attempts": 45, "successes": 28, "success_rate": 0.62},
    "europepmc": {"attempts": 40, "successes": 15, "success_rate": 0.38},
    "semantic_scholar": {"attempts": 35, "successes": 8, "success_rate": 0.23},
    "core": {"attempts": 30, "successes": 5, "success_rate": 0.17},
    "proxy": {"attempts": 20, "successes": 18, "success_rate": 0.90}
  },
  "search_sources": {
    "pubmed": {"queries": 50, "papers_found": 120, "records_yielded": 340, "yield_per_query": 6.8},
    "openalex": {"queries": 50, "papers_found": 180, "records_yielded": 290, "yield_per_query": 5.8},
    "biorxiv": {"queries": 50, "papers_found": 12, "records_yielded": 45, "yield_per_query": 0.9},
    "crossref": {"queries": 50, "papers_found": 95, "records_yielded": 110, "yield_per_query": 2.2}
  },
  "last_updated": "2026-03-24T14:30:00Z"
}
```

### 24b. Dynamic cascade reordering

After 20+ fetch attempts, reorder the OA cascade by success rate:

```python
# Instead of fixed order: unpaywall → openalex → europepmc → semantic_scholar → core
# Use dynamic order based on observed success rates:
sources = sorted(source_stats["pdf_sources"].items(),
                 key=lambda x: x[1]["success_rate"], reverse=True)
# Result might be: proxy → unpaywall → openalex → europepmc → core → semantic_scholar
```

**Exception**: proxy always goes last regardless of success rate (it
requires browser interaction and is slower).

### 24c. Search source routing

After 20+ queries per source, route queries to the most productive
search API:

- If OpenAlex yields 2x more papers per query than PubMed for this
  project's taxa, query OpenAlex first and skip PubMed for low-priority
  queries.
- If bioRxiv yields <1 paper per 10 queries, reduce bioRxiv search
  frequency (every 5th query instead of every query).

### 24d. Session-end reflection

At session end, generate a brief tool effectiveness analysis:

```
── Tool Effectiveness ─────────────
 Best PDF source     : Unpaywall (71% success)
 Worst PDF source    : CORE (17% success — consider dropping)
 Best search source  : OpenAlex (6.8 records/query)
 Cascade order       : Unpaywall → OpenAlex → EuropePMC → S.Scholar → CORE
 Recommendation      : Skip CORE (saves ~3s/paper, 17% success not worth latency)
────────────────────────────────────
```

---

## 25. Cross-Project Transfer Learning

### 25a. Shared knowledge directory

Create `~/.claude/traittrawler_shared/` (user-level, cross-project):

```
~/.claude/traittrawler_shared/
  ├── journal_patterns.jsonl    # Journal-specific extraction patterns
  ├── notation_variants.jsonl   # Cross-trait notation knowledge
  ├── publisher_quirks.jsonl    # Publisher PDF formatting quirks
  └── source_effectiveness.json # Cross-project source stats
```

### 25b. What transfers

| Knowledge type | Example | How it helps |
|---------------|---------|-------------|
| Journal patterns | "Comparative Cytogenetics puts data in Table 1" | Skip to relevant section faster |
| Notation variants | "±" means standard deviation across biology | Avoid rediscovering common conventions |
| Publisher quirks | "Springer tables have merged header cells" | Better table parsing |
| Source effectiveness | "EuropePMC is great for taxonomy journals" | Better cascade ordering for new projects |

### 25c. When to write

At session end, during the knowledge review (§14c), check if any
discoveries have cross-project value:

```python
# Discovery types that transfer:
transferable_types = ["extraction_pattern", "terminology"]
# Plus notation_variants that are NOT trait-specific
```

Write transferable discoveries to the shared directory with provenance:

```json
{
  "source_project": "coleoptera-karyotypes",
  "discovery_type": "extraction_pattern",
  "journal": "Comparative Cytogenetics",
  "pattern": "Trait data consistently in Table 1 or 2; methods in section 2.1",
  "confidence": 0.9,
  "n_papers_observed": 15,
  "date": "2026-03-24"
}
```

### 25d. When to read

During setup wizard (§0) or calibration (§0b), if the shared knowledge
directory exists, load relevant entries:

```python
# At project start, inject relevant shared knowledge into guide.md
# Filter by: journals likely to appear for this taxon/trait combination
# Present to user for approval before injecting
```

### 25e. Privacy

Shared knowledge contains only structural observations about journals
and notation — never species data, trait values, or paper content. It
is safe to share across projects even if the projects have different
collaborators.

---

## 26. Knowledge Graph Provenance Export

### 26a. Cross-paper concordance

Before export, scan results.csv for concordance patterns:

```python
# Group by species + trait field
# For each group with >1 record from different papers:
#   If values agree → concordant (strengthens confidence)
#   If values disagree → conflicted (needs investigation)

concordance = {}
for species in unique_species:
    records = [r for r in results if r["species"] == species]
    if len(set(r["doi"] for r in records)) > 1:
        # Multiple papers report data for this species
        for field in trait_fields:
            values = [r[field] for r in records if r[field]]
            if len(set(values)) > 1:
                concordance.setdefault(species, {})[field] = {
                    "values": list(set(values)),
                    "sources": [r["doi"] for r in records],
                    "status": "conflicted"
                }
```

Report conflicts at session end:

```
── Cross-Paper Conflicts ──────────
 Cicindela campestris:
   sex_chr_system: "XY" (Smith 2003) vs "Xyp" (Jones 2010)
   → Confidence-weighted resolution: Xyp (0.92 vs 0.65)
 3 species with conflicting values across 7 papers
────────────────────────────────────
```

### 26b. JSON-LD export

Export provenance as linked data for interoperability with biodiversity
knowledge graphs:

```json
{
  "@context": {
    "dwc": "http://rs.tdwg.org/dwc/terms/",
    "schema": "http://schema.org/",
    "prov": "http://www.w3.org/ns/prov#",
    "tt": "http://traittrawler.org/terms/"
  },
  "@graph": [
    {
      "@id": "record:tr_abc123",
      "@type": "dwc:MeasurementOrFact",
      "dwc:scientificName": "Cicindela campestris",
      "dwc:measurementType": "chromosome_number_2n",
      "dwc:measurementValue": "22",
      "prov:wasGeneratedBy": {
        "@type": "prov:Activity",
        "prov:used": {"@id": "doi:10.1234/example.5678"},
        "tt:sourcePage": "14",
        "tt:sourceContext": "Table 2, row 3...",
        "tt:extractionConfidence": 0.92,
        "tt:calibratedConfidence": 0.89,
        "tt:extractionTraceId": "tr_abc123"
      }
    }
  ]
}
```

### 26c. Script

`scripts/knowledge_graph_export.py`:

```bash
python3 scripts/knowledge_graph_export.py --project-root . --format jsonld --output provenance.jsonld
python3 scripts/knowledge_graph_export.py --project-root . --format conflicts --output conflicts.json
```

---

## 27. Streaming Progress & Interruptible Execution

### 27a. Progressive dashboard updates

Reduce dashboard regeneration interval from every 10 papers to every
5 papers. Additionally, after each paper, append a single line to
`state/live_progress.jsonl`:

```json
{"timestamp": "2026-03-24T15:12:00Z", "paper": "Smith et al. 2003", "records": 3, "total_records": 1339, "queue_remaining": 22}
```

The dashboard can poll this file for near-real-time updates without
full regeneration.

### 27b. Interruptible extraction

Between each paper in the main loop (§3b), check for user input signals:

- "skip" or "next" → skip the current paper, mark as processed with
  `"outcome": "user_skipped"`
- "redo" or "redo last" → re-extract the previous paper
- "pause" → stop after the current paper, don't end the session
- "show trace" → display the chain-of-thought trace for the last record
- "consensus on last" → trigger consensus extraction for the last paper

### 27c. Live confidence updates

After each paper, print a one-line status showing confidence trend:

```
📊 Confidence: 0.87 avg (↑ from 0.84) | 3 records | total: 1,339
```

---

## 28. Formal Reproducibility Package

### 28a. Session snapshots

At session start, save a reproducibility snapshot to
`state/snapshots/{session_id}.json`:

```json
{
  "session_id": "2026-03-24T14:30:00Z",
  "guide_md5": "abc123...",
  "guide_content_hash": "sha256:def456...",
  "config_py_md5": "ghi789...",
  "config_yaml_hash": "sha256:jkl012...",
  "model_id": "claude-sonnet-4-6",
  "skill_version": "3.0.0",
  "python_version": "3.11.4",
  "pdfplumber_version": "0.10.3",
  "dependencies": {"pyyaml": "6.0.1", "scipy": "1.12.0"}
}
```

### 28b. reproduce.py script

```bash
python3 scripts/reproduce.py --project-root . --session 2026-03-24T14:30:00Z
```

What it does:
1. Loads the session snapshot to identify which model and config were used
2. For each paper processed in that session (from run_log.jsonl):
   a. Locates the cached PDF in `pdfs/`
   b. Re-extracts using the CURRENT guide.md (not the snapshot — this
      shows how much guide.md improvement affects results)
   c. Diffs re-extracted records against originals in results.csv
3. Generates a reproducibility report:

```
── Reproducibility Report ─────────
 Session: 2026-03-24T14:30:00Z
 Papers re-extracted: 23
 Records compared: 89
 Exact match: 82 (92.1%)
 Minor differences: 5 (5.6%)
 Major differences: 2 (2.2%)
 Guide.md has changed since this session: YES (3 amendments)
 Expected divergence from guide changes: 2 records
────────────────────────────────────
```

### 28c. Reproducibility limitations

Note in the report:
- LLM extraction is inherently stochastic — exact reproduction is not
  guaranteed even with identical inputs
- Model version changes between sessions may affect results
- The value of reproduce.py is measuring DRIFT, not achieving exact match
