# results.csv Field Schema

All fields use null (empty cell) when not reported. Append-only — never modify
existing rows.

## Paper metadata
| Field | Type | Notes |
|---|---|---|
| `doi` | string | Full DOI, e.g. `10.3897/compcytogen.v10i3.9504` |
| `paper_title` | string | Full title as published |
| `paper_authors` | string | Full author list as published |
| `first_author` | string | Last name of first author only, ASCII |
| `paper_year` | integer | 4-digit year |
| `paper_journal` | string | Journal name as published |
| `processed_date` | string | ISO date this record was added, e.g. `2026-03-20` |

## Taxonomy
| Field | Type | Notes |
|---|---|---|
| `species` | string | Binomial, e.g. `Dynastes hercules` |
| `genus` | string | Genus name |
| `family` | string | Beetle family, e.g. `Carabidae` |
| `subfamily` | string | Subfamily if reported or inferable from taxonomic header |

## Core karyotype
| Field | Type | Notes |
|---|---|---|
| `chromosome_number_2n` | integer | Diploid chromosome number |
| `n_haploid` | integer | Haploid number (= 2n/2 for standard diploids) |
| `sex_chr_system` | string | EXACT as written: `XY`, `X0`, `Xyp`, `neo-XY`, `X1X2Y`, etc. Never normalize |
| `sex_of_specimen` | string | `male`, `female`, or `unknown` |
| `karyotype_formula` | string | Full formula verbatim, e.g. `2n=20=8m+10sm+2st` |
| `haploid_autosome_count` | integer | Autosome pairs only. = (2n − sex_chr_count) / 2 |

## Chromosome details
| Field | Type | Notes |
|---|---|---|
| `chromosome_morphology` | string | Free text description of chromosome morphology |
| `ploidy` | string | null if diploid; else `triploid`, `tetraploid`, etc. |
| `b_chromosomes` | string | B chromosome count or description if reported |

## Cytogenetic methods
| Field | Type | Notes |
|---|---|---|
| `staining_method` | string | e.g. `Giemsa`, `C-banding`, `FISH`, `AgNOR`, `DAPI` |
| `NOR_position` | string | Nucleolar organizer region location if reported |
| `heterochromatin_pattern` | string | C-banding or heterochromatin description |

## Collection info
| Field | Type | Notes |
|---|---|---|
| `collection_locality` | string | Free-text locality as reported in paper |
| `country` | string | ISO country name normalized from locality (e.g. `Brazil`, `Japan`) |
| `voucher_info` | string | Voucher specimen identifier if reported |
| `collection_year` | integer | Year specimens were collected |
| `number_of_specimens` | integer | Number of individuals karyotyped |

## Data quality
| Field | Type | Notes |
|---|---|---|
| `extraction_confidence` | float | 0.0–1.0. Lower if ambiguous, inferred, or from catalogue only |
| `flag_for_review` | boolean | true if confidence < 0.75 |
| `source_type` | string | `full_text`, `table`, `catalogue`, or `abstract_only` |
| `pdf_source` | string | How full text was obtained: `unpaywall`, `openalex`, `europepmc`, `semantic_scholar`, `tamu_proxy`, `abstract_only`, `local_pdf` |
| `pdf_filename` | string | Human-readable filename, e.g. `Smith_2003_CompCytogen_9504.pdf` |
| `pdf_url` | string | URL the PDF was downloaded from (if applicable) |
| `notes` | string | Caveats, ambiguities, verbatim catalogue entry if applicable |

## Confidence guidelines
| Situation | Confidence |
|---|---|
| Full text, explicit counts, methods described | 0.90–1.00 |
| Full text, counts present, no methods | 0.80–0.89 |
| Catalogue entry, no asterisk | 0.85 |
| Catalogue entry with asterisk (*) = uncertain value | 0.60–0.65 |
| Comparative table (not focal species) | 0.80–0.85 |
| Abstract only | 0.40–0.55 |
| Inferred or ambiguous | ≤ 0.65 |

## results.csv field order (must match exactly for append compatibility)
```
doi, paper_title, paper_authors, first_author, paper_year, paper_journal,
species, family, subfamily, genus,
chromosome_number_2n, n_haploid, sex_chr_system, sex_of_specimen, karyotype_formula,
chromosome_morphology, haploid_autosome_count, ploidy, b_chromosomes,
staining_method, NOR_position, heterochromatin_pattern,
collection_locality, country, voucher_info, collection_year, number_of_specimens,
extraction_confidence, flag_for_review, source_type, pdf_source, pdf_filename, pdf_url,
notes, processed_date
```

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
