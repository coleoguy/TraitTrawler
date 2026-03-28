# Knowledge Evolution & Cross-Project Transfer — On-Demand Reference

Load this file at session end for knowledge review, or during setup wizard
for cross-project transfer.

---

## Session-End Knowledge Review

### Step 1: Gather Discoveries

Read all files in `learning/` from this session. Also check
`state/discoveries.jsonl` for any pending discoveries from prior sessions
that weren't reviewed.

### Step 2: Group by Type

Discovery types:
- `notation_variant`: new way of writing a known value (e.g., subscript sex chromosomes)
- `new_taxon`: species/genus/family not in GBIF or not previously seen
- `ambiguity_pattern`: recurring ambiguous notation (e.g., "2n=20+B")
- `validation_gap`: value that passes validation but seems wrong
- `extraction_pattern`: structural pattern in papers (e.g., "this journal always puts data in Table 1")
- `terminology`: domain term not in guide.md

### Step 3: Classify Each Discovery

- **Routine**: notation variant, new taxon, terminology → propose a specific
  one-line addition to guide.md
- **Structural**: validation gap, extraction pattern, ambiguity requiring
  rule change → draft a multi-line amendment, flag for careful review

### Step 4: Propose Amendments

Present each proposal in diff format:
```
guide.md amendment (routine):
  Section: Notation Rules
+ "2n=20+B" means 20 autosomes plus B chromosomes. Record as 2n=20, note B
+ chromosomes in notes field. Do not add B chromosomes to the count.
  Discovered in: Smith 2003 (doi: 10.1234/...)
  Accept? [y/n]
```

For structural amendments:
```
guide.md amendment (STRUCTURAL — review carefully):
  Section: Validation Rules
+ Add validation rule: if sex_chromosome_system contains a digit > 5,
+ flag_for_review = true (likely a multi-sex-chromosome system that
+ needs manual verification)
  Discovered in: 3 papers this session
  Rationale: {explanation from Extractor's lesson learned}
  Accept? [y/n]
```

### Step 5: Apply Approved Changes

For each approved amendment:
1. Apply via Edit tool to `guide.md`
2. Mark discovery as `applied: true` in `state/discoveries.jsonl`
3. Log to `run_log.jsonl`: `{"event": "guide_amended", "type": "routine|structural", "section": "...", "summary": "..."}`

For rejected:
- Mark `applied: false, reason: "{user's reason}"` in `state/discoveries.jsonl`

### Cumulative Knowledge Report

Every 5 sessions, print:
```
Knowledge Growth (all sessions):
  Guide.md amendments accepted : 23
  Guide.md amendments rejected : 4
  Notation variants discovered : 12
  New taxa encountered         : 8
  Validation rules added       : 3
```

---

## Mid-Session Correction

**Triggers**: "that's wrong", "you're miscoding", "that field should be",
"correction:", or user identifies a systematic extraction error.

### Procedure

1. **Stop** the extraction pipeline immediately
2. **Identify** the specific error (which field, which values, why it's wrong)
3. **Draft** a guide.md amendment that fixes the root cause
4. **Present** the amendment to the user for approval
5. **Apply** the approved change to guide.md
6. **Offer warm re-extraction**: "I've updated the guide. Want me to re-extract
   this session's papers with the corrected rule? I'll show you a diff of
   old vs new values for each."
7. If yes:
   a. Find all papers from this session in `state/processed.json`
   b. For each, spawn Dealer → Extractor with updated guide.md
   c. Compare old record vs new record field by field
   d. Present diff:
      ```
      Re-extraction diff: Cicindela campestris (Smith 2003)
        sex_chromosome_system: Xyp -> XY  (CHANGED)
        chromosome_number_2n:  22  -> 22  (same)
        confidence:            0.65 -> 0.90 (improved)
      Accept? [y/all/n/skip]
      ```
   e. "all" = accept remaining without asking
   f. Update results.csv for approved changes
   g. Log correction to `run_log.jsonl`
8. Resume normal extraction with corrected guide

---

## Cross-Project Transfer Learning

### Shared Knowledge Directory

`~/.claude/traittrawler_shared/` contains knowledge transferable across
TraitTrawler projects:

```
~/.claude/traittrawler_shared/
├── journal_patterns.jsonl     # Journal-specific extraction patterns
├── notation_variants.jsonl    # Notation conventions across fields
├── publisher_quirks.jsonl     # Publisher-specific PDF quirks
└── source_effectiveness.json  # API success rates by publisher
```

### What Transfers

Only discoveries that are NOT trait-specific:
- `extraction_pattern` (e.g., "Comparative Cytogenetics always has data in Table 1")
- `terminology` (e.g., "2n" always means diploid number)
- `notation_variant` that applies across traits (e.g., subscript notation)

Trait-specific discoveries (e.g., "Xyp means X-autosome fusion") do NOT transfer.

### When to Write

At session end, after knowledge review:
1. Filter this session's approved discoveries for transferable types
2. Write each to the appropriate `.jsonl` file with provenance:
   ```json
   {"description": "...", "source_project": "coleoptera-karyotypes",
    "source_doi": "10.1234/...", "date": "2026-03-27", "type": "extraction_pattern"}
   ```

### When to Read

During the setup wizard (section 0), after generating `guide.md`:
1. Check if `~/.claude/traittrawler_shared/` exists
2. If yes, load relevant entries and incorporate into guide.md
3. Tell user: "Loaded {N} patterns from previous TraitTrawler projects."

### Privacy

Shared knowledge contains only extraction patterns and notation rules —
never actual data values, species names, or paper content.
