# Shared Extraction Rules

These rules apply to ALL extraction agents (A, B, C). Agent-specific
instructions are in each agent's own file.

---

## Universal Rules

- Extract data **explicitly stated** in the paper — never infer values not
  present in the text
- `extraction_confidence`: ALWAYS a float 0.0-1.0
- For each record, provide:
  - `source_page`: page number where the data appears
  - `source_context`: verbatim quote from the paper, max 200 characters
  - `extraction_reasoning`: one sentence explaining the extraction (required
    for ambiguous cases, blank if the value is unambiguous)
- Return a JSON object with `records` and `traces` arrays (see Output Format)
- If the paper contains NO extractable trait data, return an empty array `[]`

## Compilation / Comparative Tables

Many papers include tables compiling previously published values from other
studies. These have a citation/reference column attributing rows to other sources.

**How to handle** (check `compilation_tables` setting from Dealer):
- `"extract_attributed"` (default): Extract with `source_type: "compilation"`,
  cited reference in `notes`, confidence reduced by -0.15.
- `"skip"`: Do NOT extract. Note: "Skipped Table N (compilation)".
- `"extract_as_leads"`: Return cited references in `"compilation_leads"` array.

**Identification**: caption says "previous/literature/published/comparison",
has a reference column, Methods doesn't describe generating this data.

## You MUST NOT

- Infer values from other papers or general knowledge
- Extract from abstracts alone (if you only have the abstract, return `[]`)
- Fabricate or estimate values not explicitly stated
- Create ANY files in the project root (no .txt, .md, .json, .py reports)
- Create ANY new folders (no temp/, logs/, etc.)
- Write status/report/summary files anywhere — return all results in your
  JSON response only

## Output Format

Return a JSON object with `records` and `traces` arrays:

```json
{
  "records": [
    {
      "species": "Genus epithet",
      "family": "Familyname",
      "genus": "Genus",
      "TRAIT_FIELD_1": "value",
      "TRAIT_FIELD_2": 42,
      "extraction_confidence": 0.92,
      "source_page": "14",
      "source_context": "Table 2, row 3: G. epithet, 2n=42, XY",
      "extraction_reasoning": "",
      "flag_for_review": false,
      "notes": ""
    }
  ],
  "traces": [
    {
      "trace_id": "{doi_hash}_{species_slug}",
      "source_passage": "verbatim text from paper",
      "reasoning_chain": [
        "Step 1: Found species in Table 2 header",
        "Step 2: Row 3 contains chromosome data: 2n=42",
        "Step 3: Sex system column shows XY"
      ],
      "alternatives_considered": "Could be 2n=44 if including B chromosomes, but methods section says B chroms excluded",
      "confidence_rationale": "Explicit table value, methods confirm counting procedure"
    }
  ]
}
```

Replace `TRAIT_FIELD_1`, etc. with the actual field names from `OUTPUT FIELDS`.
All extraction agents use this same output format.
