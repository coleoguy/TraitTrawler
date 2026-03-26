# results.csv Field Schema

All fields use null (empty cell) when not reported. Append-only — never modify
existing rows.

## Core fields (present in every project)

### Paper metadata
| Field | Type | Notes |
|---|---|---|
| `doi` | string | Full DOI, e.g. `10.3897/compcytogen.v10i3.9504` |
| `paper_title` | string | Full title as published |
| `paper_authors` | string | Full author list as published |
| `first_author` | string | Last name of first author only, ASCII |
| `paper_year` | integer | 4-digit year |
| `paper_journal` | string | Journal name as published |
| `session_id` | string | ISO timestamp of the session that created this record, e.g. `2026-03-24T14:30:00` |
| `processed_date` | string | ISO date this record was added, e.g. `2026-03-20` |

### Taxonomy
| Field | Type | Notes |
|---|---|---|
| `species` | string | Binomial, e.g. `Dynastes hercules` |
| `genus` | string | Genus name |
| `family` | string | Taxonomic family |
| `subfamily` | string | Subfamily if reported or inferable |

### Data quality
| Field | Type | Notes |
|---|---|---|
| `extraction_confidence` | float | 0.0–1.0. Lower if ambiguous, inferred, or from catalogue only |
| `flag_for_review` | boolean | true if confidence < 0.75 |
| `source_type` | string | `full_text`, `table`, `catalogue`, or `abstract_only` |
| `pdf_source` | string | How full text was obtained: `unpaywall`, `openalex`, `europepmc`, `semantic_scholar`, `proxy`, `abstract_only`, `local_pdf` |
| `pdf_filename` | string | Human-readable filename, e.g. `Smith_2003_Genetica_9504.pdf` |
| `pdf_url` | string | URL the PDF was downloaded from (if applicable) |
| `notes` | string | Caveats, ambiguities, verbatim source text if applicable |

### Provenance
| Field | Type | Notes |
|---|---|---|
| `source_page` | string | Page number(s) where data was found, e.g. `12` or `45-47` |
| `source_context` | string | Verbatim text passage or table row (≤200 chars) the record was extracted from |
| `extraction_reasoning` | string | One-sentence note when ambiguity existed; blank when unambiguous |

### Taxonomy intelligence (added by §16)
| Field | Type | Notes |
|---|---|---|
| `accepted_name` | string | GBIF accepted name if different from `species`; empty if species is already accepted or GBIF lookup failed |
| `gbif_key` | integer | GBIF Backbone Taxonomy usageKey for this species |
| `taxonomy_note` | string | Details of any taxonomy resolution: synonym resolution, fuzzy match, not found in GBIF |

### Audit tracking (added by audit mode §15)
| Field | Type | Notes |
|---|---|---|
| `audit_status` | string | `unaudited` (default), `confirmed`, `corrected`, or `skipped` |
| `audit_session` | string | Session ID of the audit that reviewed this record |
| `audit_prior_values` | string | JSON of original values before correction; empty if confirmed/unaudited |

### Calibrated confidence (added by §19)
| Field | Type | Notes |
|---|---|---|
| `calibrated_confidence` | float | Post-hoc calibrated probability (0.0–1.0) using isotonic regression on benchmark data. Empty when calibration model not yet available (<10 observations). Unlike `extraction_confidence` (heuristic), this is empirically validated: a value of 0.85 means records at this level are correct ~85% of the time. |

### Consensus extraction (added by §21)
| Field | Type | Notes |
|---|---|---|
| `consensus_agreement` | string | Result of multi-agent consensus extraction: `full` (all passes agree), `partial` (some fields differ, resolved by voting), `disputed` (major disagreement, flagged for review), `pass2_only` (record found only by enumeration pass). Empty if consensus not triggered. |

### Chain-of-thought trace (added by §22)
| Field | Type | Notes |
|---|---|---|
| `extraction_trace_id` | string | Links to full reasoning trace in `state/extraction_traces/{doi_hash}_{author}_{year}.json`. Contains step-by-step reasoning chain, source passage, alternatives considered, and confidence rationale for every extracted value. |

## Trait-specific fields

Defined per project in `collector_config.yaml` → `output_fields`.
The setup wizard (§0) populates these based on the user's trait.
Examples:

- **Karyotype project**: `chromosome_number_2n`, `n_haploid`, `sex_chr_system`,
  `karyotype_formula`, `staining_method`, etc.
- **Body mass project**: `body_mass_g_mean`, `body_mass_g_sd`, `sex`,
  `sample_size`, `measurement_method`, etc.

The skill reads the active field list from `collector_config.yaml` at startup
and uses only those fields when writing to CSV.

## Confidence guidelines
| Situation | Confidence |
|---|---|
| Full text, explicit values, methods described | 0.90–1.00 |
| Full text, values present, no methods section | 0.80–0.89 |
| Catalogue or reference book entry | 0.80–0.85 |
| Catalogue entry marked uncertain (* or ?) | 0.60–0.65 |
| Comparative table (not focal species of paper) | 0.80–0.85 |
| Abstract only | 0.40–0.55 |
| Inferred or ambiguous | ≤ 0.65 |

---

## leads.csv — papers needing manual full-text retrieval

Populated by §5g when a likely/uncertain paper's full text cannot be obtained.
The user can review this file, manually obtain PDFs, drop them in `pdfs/`,
and re-run. The agent will detect the local PDF on the next pass.

| Field | Type | Notes |
|---|---|---|
| `doi` | string | Full DOI |
| `paper_title` | string | Full title |
| `first_author` | string | Last name of first author |
| `paper_year` | integer | Publication year |
| `paper_journal` | string | Journal name |
| `triage` | string | `likely` or `uncertain` |
| `reason` | string | Why full text failed: `paywall_no_proxy_auth`, `pdf_download_failed`, `pdf_timeout`, `scanned_skipped`, `browser_failed`, `no_oa_source` |
| `abstract_extracted` | boolean | `true` if abstract-only extraction was done |
| `records_from_abstract` | integer | Records extracted from abstract (0 if none) |
| `date_added` | string | ISO date the lead was logged |
| `status` | string | `new` on creation; user sets `obtained` or `skip` |

## leads.csv field order
```
doi, paper_title, first_author, paper_year, paper_journal,
triage, reason, abstract_extracted, records_from_abstract,
date_added, status
```
