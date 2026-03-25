# Taxonomic Intelligence

TraitTrawler validates every extracted species name against the GBIF Backbone
Taxonomy. This catches synonym drift (the same biological species entered
under two different names from different eras of the literature), auto-fills
higher taxonomy, and flags nomenclatural problems before they corrupt the
database.

## When to run

After extracting records from each paper, before writing to results.csv,
run the taxonomy check on every species in the batch. This is a lightweight
HTTP call per unique species, cached to avoid redundant lookups.

## 16a. GBIF Species Lookup

For each unique species name in the extraction batch, check
`state/taxonomy_cache.json` first. If not cached, query GBIF:

```python
# Use scripts/taxonomy_resolver.py or direct API call:
# GET https://api.gbif.org/v1/species/match?name={species}&kingdom=Animalia&strict=false
```

The GBIF match API returns:
- `usageKey`: GBIF taxon ID
- `scientificName`: matched name
- `status`: `ACCEPTED`, `SYNONYM`, `DOUBTFUL`, `MISAPPLIED`
- `acceptedUsageKey` / `accepted`: the accepted name if status is SYNONYM
- `rank`: SPECIES, GENUS, etc.
- `kingdom`, `phylum`, `class`, `order`, `family`, `genus`
- `matchType`: `EXACT`, `FUZZY`, `HIGHERRANK`, `NONE`
- `confidence`: GBIF's match confidence (0–100)

## 16b. Actions by match result

### ACCEPTED (status == "ACCEPTED", matchType == "EXACT")
- No name change needed
- Auto-fill any empty taxonomy fields (`family`, `subfamily`, `genus`)
  from the GBIF response if not already populated from the paper
- Cache the result

### SYNONYM (status == "SYNONYM")
- **Update the species field** to the accepted name from GBIF
- **Preserve the original name** in the `notes` field:
  `"Original name: {extracted_name}, resolved to accepted name via GBIF
  (acceptedUsageKey: {key})"`
- Auto-fill taxonomy from the accepted taxon's hierarchy
- Cache both the original name (pointing to accepted) and accepted name
- Log to `state/run_log.jsonl`:
  ```json
  {"timestamp": "...", "session_id": "...", "event": "taxonomy_synonym_resolved", "original": "Cicindela sylvatica", "accepted": "Cylindera sylvatica", "gbif_key": 12345678, "doi": "..."}
  ```

### FUZZY MATCH (matchType == "FUZZY", confidence >= 90)
- Likely a spelling variant. Present to user for confirmation:
  ```
  🔬 Taxonomy: "{extracted_name}" fuzzy-matched to "{matched_name}"
     (GBIF confidence: {confidence}%). Accept correction? [y/n]
  ```
- If accepted: update species, note original in `notes`
- If rejected: keep original, add `"GBIF fuzzy match rejected"` to notes,
  set `flag_for_review = True`

### FUZZY MATCH (matchType == "FUZZY", confidence < 90)
- Do NOT auto-correct. Flag for review:
  `flag_for_review = True`, add to notes:
  `"GBIF low-confidence fuzzy match: {matched_name} ({confidence}%)"`

### NO MATCH (matchType == "NONE")
- Species not in GBIF backbone. This is common for recently described
  species or regional names. Do NOT flag as an error — many valid species
  are not yet in GBIF.
- Add to notes: `"Species not found in GBIF Backbone Taxonomy"`
- Log as a discovery (type: `new_taxon`) in `state/discoveries.jsonl`
  for the session-end knowledge review

### HIGHERRANK (matchType == "HIGHERRANK")
- GBIF matched to a genus or family, not species. The binomial may be
  malformed or the species epithet is not recognized.
- Flag for review, add to notes:
  `"GBIF matched to higher rank only: {matched_name} (rank: {rank})"`

## 16c. Taxonomy cache

Store results in `state/taxonomy_cache.json` to avoid redundant API calls:

```json
{
  "Cicindela sylvatica": {
    "status": "SYNONYM",
    "accepted_name": "Cylindera sylvatica",
    "gbif_key": 12345678,
    "family": "Cicindelidae",
    "genus": "Cylindera",
    "lookup_date": "2026-03-24"
  },
  "Dynastes hercules": {
    "status": "ACCEPTED",
    "accepted_name": "Dynastes hercules",
    "gbif_key": 87654321,
    "family": "Scarabaeidae",
    "genus": "Dynastes",
    "lookup_date": "2026-03-24"
  }
}
```

The cache is loaded at session start (§1b) and updated after each batch.
Cache entries never expire within a project — GBIF backbone updates are
rare enough that manual cache clearing (`rm state/taxonomy_cache.json`)
suffices when needed.

## 16d. Batch processing

To minimize API calls, collect all unique species names from a paper's
extraction batch and resolve them together. The taxonomy_resolver.py script
handles batching and rate limiting (GBIF allows ~3 requests/second without
authentication).

```bash
python3 scripts/taxonomy_resolver.py \
  --species "Cicindela sylvatica" "Dynastes hercules" "Nebria brevicollis" \
  --cache state/taxonomy_cache.json \
  --kingdom Animalia
```

The script outputs JSON with resolution results for each species. The agent
reads the output and applies the changes per §16b.

If the script is unavailable, the agent can make the GBIF API calls directly
via WebFetch — the script is a convenience, not a hard dependency.

## 16e. Interaction with deduplication

Taxonomy resolution happens BEFORE deduplication (§8). This means that if
Paper A reports "Cicindela sylvatica" and Paper B reports "Cylindera
sylvatica" (the accepted name), after taxonomy resolution both records have
`species: "Cylindera sylvatica"` — and if all trait fields also match, the
second record is correctly identified as a duplicate.

Without taxonomy resolution, these would be treated as different species
and both kept, inflating the database with phantom diversity.

## 16f. Configuration

Taxonomy resolution is enabled by default. To disable:
```yaml
# In collector_config.yaml:
taxonomy_resolution: false
```

When disabled, species names are written exactly as extracted with no
GBIF lookup. This may be appropriate for projects studying nomenclatural
history itself, or for non-animal taxa where GBIF coverage is sparse.
