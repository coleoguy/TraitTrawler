# results.csv Field Schema

All fields use null (empty cell) when not reported. Append-only — never modify
existing rows.

**CRITICAL: Before writing any record, validate it against the constraints below.
A record that fails a REJECT constraint must not be written. A record that fails
a FLAG constraint should be written with `flag_for_review = true`.**

## Paper metadata
| Field | Type | Constraint | Notes |
|---|---|---|---|
| `doi` | string | — | Full DOI, e.g. `10.3897/compcytogen.v10i3.9504` |
| `paper_title` | string | — | Full title as published |
| `paper_authors` | string | — | Full author list as published |
| `first_author` | string | ASCII only | Last name of first author only, ASCII transliterated |
| `paper_year` | integer | REJECT if not 1900–current year | 4-digit year |
| `paper_journal` | string | — | Journal name as published |

## Taxonomy
| Field | Type | Constraint | Notes |
|---|---|---|---|
| `species` | string | REJECT if not valid binomial (see guide.md §Species Name Validation) | Binomial, e.g. `Dynastes hercules`. Subspecies (trinomial) and "sp." entries are valid. |
| `family` | string | REJECT if not in valid Coleoptera family list (see guide.md §Valid Families) | Modern family name only. Apply obsolete→modern mapping. Never "Coleoptera" or "UNKNOWN". |
| `subfamily` | string | — | Subfamily if reported or inferable from taxonomic header |
| `tribe` | string | — | Tribe if explicitly stated in paper |
| `genus` | string | Must equal first word of `species` | Derived from species field |

## Core karyotype
| Field | Type | Constraint | Notes |
|---|---|---|---|
| `chromosome_number_2n` | integer | REJECT if not 2–200 or valid range string | Diploid chromosome number |
| `n_haploid` | integer | Must be positive integer if present | Haploid number |
| `fundamental_number` | integer | Must be positive integer ≥ 2n if present | Total chromosome arms (FN/NF) |
| `sex_chr_system` | string | Must be from canonical vocabulary (see below) | Normalized at extraction time |
| `sex_of_specimen` | string | Must be `male`, `female`, or blank | Never "unknown"; never non-sex data |
| `karyotype_formula` | string | — | Full formula verbatim, e.g. `2n=20=8m+10sm+2st` |
| `haploid_autosome_count` | integer | Must be positive integer if present | Autosome pairs = (2n − sex_chr_count) / 2 |

### sex_chr_system canonical vocabulary

The field must contain ONE of these values (or be blank):

```
XY, Xyp, Xyr, Xyc, X0, neoXY, neoX0,
XXY, XXXY, XXXXY,
XXYY, XXXYY,
XYY, XYYY, XYYYY,
Parthenogenetic, ZW
```

**Normalization table (apply before writing):**

| Source text | Write as | Rationale |
|---|---|---|
| XO, Xo, xo, X-O | `X0` | Zero, not letter O |
| Xy (when Y is NOT described as punctiform/ring) | `XY` | Lowercase y was size note |
| neo-XY, Neo-XY, NeoXY, neoXy, neo-Xy | `neoXY` | Standardize casing, drop hyphen |
| XyP, XYp, Xy(p) | `Xyp` | Standardize casing |
| XYr | `Xyr` | Match Xyp convention |
| XX/XY, XX:XY, XY:XX | `XY` | Same system, normalize to male |
| XX/X0, X0/XX | `X0` | Same system, normalize to male |
| X₁X₂Y, X1X2Y (numbered notation) | `XXY` | Simple repeated-letter notation |
| X₁X₂X₃Y, X1X2X3Y | `XXXY` | Simple repeated-letter notation |
| X₁X₂X₃X₄Y, X1X2X3X4Y | `XXXXY` | Simple repeated-letter notation |
| X₁X₂Y₁Y₂, X1X2Y1Y2 | `XXYY` | Simple repeated-letter notation |
| unknown, unclear, not specified | (blank) | No data = blank |

**DISTINCT systems — never merge:** Xyp ≠ Xyr ≠ Xyc ≠ XY ≠ X0

## Chromosome details
| Field | Type | Constraint | Notes |
|---|---|---|---|
| `preparation_type` | string | Must be from: `meiotic`, `spermatogonial`, `mitotic`, or blank | See guide.md for normalization |
| `chromosome_morphology` | string | — | Free text description of autosome morphology |
| `sex_chr_morphology` | string | — | Morphological description of sex chromosomes specifically |
| `ploidy` | string | Must be from canonical vocabulary (see below) or blank | Only populate if paper explicitly discusses ploidy |
| `b_chromosomes` | string | — | B chromosome count or range, e.g. `0-2`, `1`, `absent` |
| `intraspecific_polymorphism` | boolean | `true` or blank | Set true when multiple cytotypes in same species |
| `haploid_male` | boolean | `true` or blank | Set true for arrhenotokous haploid males |
| `reproductive_mode` | string | Must be from: `arrhenotoky`, `thelytoky`, `deuterotoky`, or blank | Only for non-standard reproduction |

### ploidy canonical vocabulary

```
diploid, triploid, tetraploid, pentaploid, hexaploid, aneuploid, haploid
```

Leave blank if diploid (default assumption). Only populate when paper
explicitly states ploidy level.

## Cytogenetic methods
| Field | Type | Constraint | Notes |
|---|---|---|---|
| `staining_method` | string | Prefer canonical terms (see below) | Primary method used to determine 2n |
| `fish_probe` | string | — | FISH probe used, e.g. `45S rDNA`, `telomeric (TTAGGG)n` |
| `NOR_count` | integer | Positive integer if present | Number of NOR/rDNA signal clusters |
| `NOR_position` | string | — | Location description, e.g. `terminal, pair 3` |
| `NOR_on_sex_chromosome` | boolean | `true`, `false`, or blank | Whether rDNA/NOR signal found on sex chromosomes |
| `heterochromatin_pattern` | string | — | C-banding results description |
| `number_of_cells_examined` | integer | Positive integer if present | Number of metaphase plates examined |

### staining_method canonical terms

| Write as | When paper says |
|---|---|
| `conventional Giemsa` | Giemsa staining, standard staining, solid staining |
| `C-banding` | constitutive heterochromatin banding, C-bands |
| `G-banding` | Giemsa banding, G-bands |
| `AgNOR` | silver staining, Ag-NOR, nucleolar organizer region staining |
| `FISH` | fluorescence in situ hybridization, rDNA-FISH |
| `DAPI` | DAPI staining, DAPI fluorescence |
| `CMA3` | chromomycin A3, CMA staining |
| `orcein` | aceto-orcein, lacto-aceto-orcein |
| `feulgen` | Feulgen reaction, Feulgen staining |

## Collection info
| Field | Type | Constraint | Notes |
|---|---|---|---|
| `collection_locality` | string | — | Free-text locality as reported in paper |
| `latitude` | float | -90 to 90 if present | Decimal degrees; southern = negative |
| `longitude` | float | -180 to 180 if present | Decimal degrees; western = negative |
| `country` | string | ISO country name; see guide.md §Country Normalization | Normalized from locality text |
| `host_plant` | string | — | Host plant binomial or common name |
| `voucher_info` | string | — | Voucher specimen identifier if reported |
| `collection_year` | integer | 1800–current year if present | Year specimens were collected |
| `number_of_specimens` | integer | Positive integer if present | Number of individuals karyotyped |

## Data quality
| Field | Type | Constraint | Notes |
|---|---|---|---|
| `extraction_confidence` | float | MUST be 0.0–1.0 numeric | Lower if ambiguous, inferred, or from catalogue |
| `flag_for_review` | boolean | `true` or blank/false | Set true if confidence < 0.75 or any FLAG condition |
| `source_type` | string | Must be from: `full_text`, `table`, `catalogue`, `abstract_only`, `abstract_and_tables` | How the data was extracted |
| `pdf_source` | string | Must be from: `unpaywall`, `openalex`, `europepmc`, `semantic_scholar`, `tamu_proxy`, `abstract_only`, `local_pdf`, `scanned_skipped`, `browser_failed`, `cnki_paywalled` | How full text was obtained |
| `pdf_filename` | string | — | Human-readable filename, e.g. `Smith_2003_CompCytogen_9504.pdf` |
| `pdf_url` | string | — | URL the PDF was downloaded from |
| `notes` | string | — | Caveats, ambiguities, OCR artifacts, original values before normalization |
| `processed_date` | string | ISO date format `YYYY-MM-DD` | Date this record was added |

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
| Non-English extraction from tables only | ≤ 0.60 |

## CSV field order (must match exactly for append compatibility)
```
family, subfamily, tribe, genus, species,
haploid_autosome_count, sex_chr_system, chromosome_number_2n, n_haploid, fundamental_number,
karyotype_formula,
sex_of_specimen, ploidy, b_chromosomes, intraspecific_polymorphism, haploid_male,
reproductive_mode, preparation_type,
staining_method, fish_probe, NOR_count, NOR_on_sex_chromosome,
country, collection_year, number_of_specimens, number_of_cells_examined, latitude, longitude,
paper_year, first_author, doi, paper_journal,
extraction_confidence, flag_for_review, source_type, pdf_source, processed_date,
chromosome_morphology, sex_chr_morphology, NOR_position, heterochromatin_pattern,
collection_locality, host_plant, voucher_info,
paper_title, paper_authors, pdf_filename, pdf_url, notes
```
