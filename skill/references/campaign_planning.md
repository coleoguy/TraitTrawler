# Campaign Planning

After 3+ sessions, the agent can generate a strategic campaign report that
transforms it from a blind query executor into a research partner that
understands where the gaps are and how to fill them efficiently.

## 18a. Triggers

The user says: "plan the campaign", "coverage report", "how much is left",
"what should I focus on next", "strategic report", "estimate remaining work".

Also offered automatically at session end after every 5th session
(configurable via `campaign_planning.auto_report_interval` in config).

## 18b. Data sources

The campaign report synthesizes data from:
- `results.csv` — what we have (species, families, record counts)
- `state/processed.json` — papers processed (yield per paper)
- `state/search_log.json` — queries run and their yield
- `state/run_log.jsonl` — session history, efficiency trends
- `state/taxonomy_cache.json` — taxonomic hierarchy from GBIF
- `config.py` — total query space remaining
- `leads.csv` — papers we know about but couldn't get

## 18c. Coverage analysis

### Taxonomic coverage vs. known diversity

For each family in `results.csv`, query GBIF for the known species count:

```
GET https://api.gbif.org/v1/species/search?rank=FAMILY&q={family}&limit=1
→ get numDescendants for rank=SPECIES
```

Build a coverage table:

```
📊 Taxonomic Coverage Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Family            │ Records │ Species │ GBIF Known │ Coverage
──────────────────┼─────────┼─────────┼────────────┼──────────
Carabidae         │     342 │     218 │     40,000 │    0.5%
Cerambycidae      │     156 │     102 │     35,000 │    0.3%
Chrysomelidae     │      89 │      67 │     32,000 │    0.2%
Scarabaeidae      │      45 │      31 │     27,000 │    0.1%
Coccinellidae     │      12 │       9 │      6,000 │    0.2%
... (top 20 families by record count)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Totals            │   1,336 │     892 │   390,000+ │    0.2%

⚠ Families with 0 records but likely data in literature:
  Staphylinidae (63,000 spp), Curculionidae (51,000 spp)
```

Note: coverage fractions will be small for large taxa — this is expected.
The value is relative comparison across families, not absolute percentage.

### Search efficiency analysis

```
📈 Search Efficiency
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Queries completed     : 122 / 1,669 (7.3%)
Papers processed      : 287
Records extracted     : 1,336
Records / paper       : 4.7 (mean)
Records / query       : 11.0 (mean)

Top-yielding query patterns:
  "Carabidae karyotype"       → 89 records (12 papers)
  "Chrysomelidae chromosome"  → 67 records (8 papers)
  "Cerambycidae cytogenetics" → 45 records (6 papers)

Low-yield patterns (< 1 record/query):
  "{family} DNA content" → 2 records across 15 queries
  Consider deprioritizing or removing these query patterns.

Citation chaining yield:
  From 23 seed papers → 156 new papers found → 412 records
  Citation chaining is {2.3x / 0.8x} more efficient than keyword search
```

### Leads pipeline

```
📋 Leads Pipeline
━━━━━━━━━━━━━━━━
Total leads        : 18
  Paywall blocked  : 12  (worth obtaining: estimated {N} records)
  PDF failed       : 4
  Scanned skipped  : 2

If all paywall leads were resolved, estimated records: ~{N}
(based on {records/paper} average for likely-triaged papers)
```

## 18d. Strategic recommendations

Based on the analysis, generate prioritized recommendations:

```
🎯 Recommended Next Actions (prioritized)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. OBTAIN LEADS — 12 paywalled papers are likely-triaged and waiting.
   Estimated yield: ~56 records. This is the highest-ROI action.

2. FOCUS QUERIES — Switch to Staphylinidae and Curculionidae queries.
   These large families have 0 records but likely published data.
   Estimated: 3–5 sessions to establish baseline coverage.

3. CITATION CHAIN — 47 high-confidence papers haven't been citation-
   chained yet. Based on current yield (2.3x vs keyword), this would
   add ~200 records in 2 sessions.

4. DEPRIORITIZE — "DNA content" queries yield <1 record/query. Consider
   removing from config.py to save session time.

5. AUDIT — 23 records are low-confidence and could benefit from
   re-extraction with the current (improved) guide.md.
```

## 18e. Session estimate

```
⏱ Effort Estimate
━━━━━━━━━━━━━━━━━
To process remaining keyword queries : ~{N} sessions ({M} hours)
To reach 50% family coverage         : ~{N} additional sessions
To exhaust all leads + queries       : ~{N} sessions total

(Estimates based on current rate of {papers/session} papers/session
 and {records/paper} records/paper)
```

## 18f. Output

The campaign report is printed to the conversation and also saved to
`campaign_report.md` in the project root for reference. Include a
timestamp header so the user can track how recommendations evolve.

## 18g. Implementation notes

- Use GBIF API for family-level species counts (cache in taxonomy_cache)
- Read `run_log.jsonl` for session-over-session trends
- Use Python for any calculations (records/query, yield estimates)
- The report should be generated in under 60 seconds
- Do not modify any config files based on the report — recommendations
  are advisory. The user decides what to act on.
