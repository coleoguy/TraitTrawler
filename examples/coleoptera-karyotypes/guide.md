# Coleoptera Karyotype Agent — Research Guide

This document defines the agent's goals, standards, and decision rules.
Edit this file to change the agent's behavior. The agent reads it at startup.

---

## Mission

Systematically survey the scientific literature to build a comprehensive database of
karyotype records for Coleoptera. For each record, capture as much cytogenetic
detail as the source paper reports.

---

## Taxonomic Scope

**Target order:** Coleoptera (all families; see priority list below)

**Priority families** (search these first and most thoroughly):
- Curculionidae (largest beetle family; weevils; includes Scolytinae, Platypodinae)
- Chrysomelidae (leaf beetles; multiple sex chromosome systems)
- Cerambycidae (longhorn beetles)
- Carabidae (ground beetles; high diversity)
- Scarabaeidae (scarabs; B chromosomes common)
- Tenebrionidae (darkling beetles; many old Eurasian records)
- Coccinellidae (ladybirds; well-studied model)
- Staphylinidae (rove beetles; understudied)
- Elateridae (click beetles)
- Buprestidae (jewel beetles)
- Lucanidae (stag beetles)

**Excluded groups** (do not extract data for):
- Non-Coleoptera outgroup taxa appearing in comparative tables
- Flow cytometry genome size data without an accompanying karyotype

---

## Data Standards

A record is **valid** and should be saved if it contains at minimum:
- A species name (binomial at minimum)
- A chromosome number (2n) OR a sex chromosome system

A record should be **flagged for review** (`flag_for_review = true`) if:
- Species name is ambiguous, incomplete, or only genus-level
- 2n conflicts with published records for the same species
- Paper is a review/secondary citation rather than original primary data
- Extraction confidence is below 0.75
- 2n is very unusual (< 8 or > 120 for presumed diploids)
- Sex chromosome system contradicts what is typical for that family
- Ploidy above 2x (polyploid)
- B chromosome count may be included in the reported 2n (ambiguous)
- Species name unclear due to non-Latin script and no transliteration given

A record should be **discarded** if:
- Extraction confidence is below 0.50
- The taxon is clearly not Coleoptera
- Data appears nonsensical or fabricated

---

## Core Notation Conventions

### Diploid number (2n)
- Almost always written **2n = X** or **2n=X** in the paper.
- Some older papers write **2n = 2x = X** (polyploid notation) — extract both
  the 2n value and the ploidy level.
- If male and female 2n differ (common when sex chromosomes differ in copy number),
  record them as separate rows with `sex_of_specimen` populated.
- Do **not** confuse 2n with the Fundamental Number (FN or NF = number of chromosome
  arms). FN is sometimes reported alongside 2n; ignore FN for `chromosome_number_2n`.

### Haploid number (n)
- n is typically reported for meiotic preparations.
- For XY species: male meiotic n = (autosomes/2) + X + Y; female n = (autosomes/2) + X.
- If a paper reports only n, derive 2n only if the sex chromosome system is
  explicitly known — otherwise flag for review.

### Karyotype formula and autosome count
- Standard format: **2n = 18A + XY** (autosomes + sex chromosomes).
- Variants: `2n = 18 + XY`, `2n = 18 + X0`, `2n = 18 + neo-XY`,
  `2n = 16 + 2m` (m = microchromosomes), `2n = 20 + 0-3B` (B chromosomes).
- Capture the formula string verbatim in `karyotype_formula`.
- `haploid_autosome_count` = number of autosome **pairs** (A):
  if formula is `2n = 18A + XY` then `haploid_autosome_count = 9`.
  Formula: `haploid_autosome_count = (2n - sex_chr_count) / 2`.

---

## Pre-Write Validation Rules

These rules are applied by the agent before writing any record to `results.csv`
(SKILL.md §7e). If a record fails any rule, re-read the source and recompute
before writing.

| Check | Rule | Action if fails |
|-------|------|----------------|
| HAC biological minimum | `haploid_autosome_count ≥ 3` | Re-read source; HAC < 3 is always a parsing error for beetles |
| HAC/2n arithmetic | `2 × HAC + sex_chr_count = chromosome_number_2n` | Re-read and recompute; likely stored 2n/2 instead of (2n − sex_chr_count)/2 |
| XY-type flag | `HAC × 2 = chromosome_number_2n` for any XY-type record | Likely omitted sex chromosome subtraction — recompute |

**Petitpierre et al. (1988) trap:** This catalogue lists meiotic entries as
`11+Xyp`, `10+XO` etc., where the leading integer is the **bivalent count =
HAC**. Do not read the leading integer as a sex chromosome count. The correct
HAC for an entry reading `11+Xyp` is 11, giving 2n = 2×11 + 2 = 24.
Any record from Petitpierre 1988 with HAC = 1 is a parsing error.

**Compound sex chromosome rule:** When a paper describes a meiotic multivalent,
chain, or ring of N elements (e.g., "chain of 4", "trivalent"), set
`sex_chr_count = N` (not 2). A "chain of 4" = X₁X₂Y₁Y₂ → sex_chr_count = 4.
Never collapse a described multivalent to a simple XY. See Cicindelidae section.

---

## Deduplication Rules

Applied after extracting a full batch from one paper (SKILL.md §7e):

- Scan the batch for same-species records where `haploid_autosome_count` differs
  by exactly 1 from the same `first_author` + `paper_year`. These are likely
  double-parse artifacts from catalogue entries being read twice. Compare both
  against the source text, keep the correct one, discard the duplicate. Log in
  `notes`.

---

## Sex Chromosome Systems in Coleoptera

Coleoptera show extreme diversity in sex chromosome systems.

| System | Example formula | Notes |
|--------|----------------|-------|
| XY | 2n=20, XY | Most common; male heterogametic |
| Xyp | 2n=20, Xyp | Y forms parachute/pyknotic body at meiosis I — DISTINCT from XY; record verbatim |
| X0 | 2n=19♂/20♀ | Male has single X, no Y; male 2n is odd |
| Neo-XY | 2n=20, neo-XY | Autosome–sex chromosome fusion; neo-X or neo-Y larger than standard |
| XXY | 2n=22, XXY | Two X chromosomes + one Y in males |
| XXXY | 2n=24, XXXY | Three X + one Y in males |
| XXXXY | 2n=26, XXXXY | Four X + one Y in males |
| XYY | 2n=22, XYY | One X + two Y in males |
| XYYY | 2n=24, XYYY | One X + three Y in males |
| XYYYY | 2n=26, XYYYY | One X + four Y in males |
| X₁X₂Y | 2n=22, X₁X₂Y | Multiple X; common in Chrysomelidae, some Cerambycidae |
| X₁X₂Y₁ | — | Rare; record exactly as written |
| ZW (♀ heterogamety) | 2n=20, ZW | Uncommon; document explicitly |
| XX/X0 | 2n=20♀/19♂ | Female is XX, male is X0 — standard |

**Rules:**
- Record `sex_chr_system` EXACTLY as written in the source — never normalize or substitute.
  **Xyp ≠ Xy ≠ XY ≠ neo-XY ≠ X0.** "Xyp" denotes a cytologically distinct configuration
  (Y forms a parachute/pyknotic body at meiosis I) and must be preserved verbatim.
  Do NOT convert Xyp to XY.
- **Multivalent/chain systems:** When a paper describes a meiotic chain of N or
  ring of N chromosomes, set `sex_chr_count = N` (not 2). A "chain of 4" forming
  at meiosis I = X₁X₂Y₁Y₂ system → sex_chr_count = 4. Never collapse a described
  multivalent to a simple XY.
- **Female-only specimens:** If only female specimens were examined and the paper provides
  no male data, leave `sex_chr_system` **blank**. In beetles, females are typically XX
  regardless of whether the male system is XO, XY, Xyp, etc. A single X chromosome count
  from a female specimen does NOT imply an XO system. Never record XO or infer any system
  from female-only data unless the paper explicitly identifies it from males.
- If sex chromosomes are inferred (not directly observed), set `flag_for_review = true`
  and explain in `notes`.
- For X0 systems the male 2n is odd; female 2n is even — verify consistency.
- neo-XY arises from autosome–sex chromosome fusions; the neo-chromosome is
  morphologically distinct (larger). Note in `notes` if described.

---

## Family-Specific Notes

### Chrysomelidae
- X₁X₂Y system is common, especially in subfamilies Galerucinae, Alticinae,
  Cassidinae, and Cryptocephalinae.
- 2n typically ranges from 16 to 36 depending on subfamily.
- Bruchinae (seed beetles) were formerly family Bruchidae — use Chrysomelidae.

### Cerambycidae
- Mostly XY; some Lamiinae have X₁X₂Y.
- 2n commonly 20–22.

### Carabidae
- Mostly XY; some lineages show very high 2n (~70-80) due to chromosome fission.
- 2n typically 18–30 but can reach 80+.

### Cicindelidae (tiger beetles)
Cicindelidae (sometimes treated as Carabidae: Cicindelinae) have compound sex
chromosome systems in derived tribes. **Never simplify these to XY.**

| System | sex_chr_count | Expected n autosomes |
|--------|--------------|---------------------|
| XY | 2 | 9 (standard Cicindela) |
| X₁X₂Y | 3 | 9 |
| X₁X₂X₃Y | 4 | 9 |
| X₁X₂X₃X₄Y | 5 | 9 |

**Multivalent trigger:** When the paper describes a meiotic "chain of N" or
"ring of N" or "multivalent with N chromosomes", set `sex_chr_count = N`.
The genus *Cicindela* almost always has n = 9 autosomes (HAC = 9); any
extracted HAC ≠ 9 for this genus is a red flag — re-check sex_chr_count.

Confirmed complex systems (set `flag_for_review = false` — these are correct):
- *Cicindela argentata*: X₁X₂X₃Y (sex_chr_count = 4)
- *Cicindela aurulenta*: X₁X₂X₃Y (sex_chr_count = 4)
- *Cicindela suturalis*: X₁X₂Y (sex_chr_count = 3)

### Curculionidae s.l. (weevils)
- Most diverse family; includes Scolytinae (bark beetles) and Platypodinae
  (formerly treated as Platypodidae and Scolytidae — update to Curculionidae).
- Many polyploid species, especially in parthenogenetic Otiorhynchus.
  Triploids (2n=3x) and tetraploids (2n=4x) are known.
- Always record ploidy if stated.

### Scarabaeidae
- Often very large chromosomes and heterochromatin-rich karyotypes.
- B chromosomes (0–5+) are common in dung beetles (Phanaeus, Dichotomius, etc.).
  The 2n in `chromosome_number_2n` should be the **standard complement without Bs**.

### Coccinellidae
- Usually 2n=20, XY — serves as a useful sanity check.
- Some species show intraspecific variation; record each distinct 2n as a separate row.

### Lucanidae and Scarabaeidae
- Large, heterochromatin-rich chromosomes are expected; C-banding papers common.

### Tenebrionidae
- Many records from USSR/Eastern Europe in Russian; tables are usually extractable.
- Diverse 2n range; X0 common in some genera.

### Scolytinae / bark beetles
- Confirm polyploids carefully — 2n=8 is modal for haplodiploid species;
  some polyploids have 2n=16, 24.

### Dytiscidae / Hydrophilidae (aquatic beetles)
- Some parthenogenetic species; flag polyploids.

---

## Chromosome Morphology

Standard morphological classes (capture in `chromosome_morphology`):
- **M** = metacentric (arm ratio ≤ 1.7)
- **SM** = submetacentric (arm ratio 1.7–3.0)
- **ST** or **A** = subtelocentric / acrocentric (arm ratio 3.0–7.0)
- **T** = telocentric (centromere at terminus)
- **m** = microchromosome (distinctly smaller than other autosomes)

Some papers give full morphological formulas like `4M + 6SM + 8ST + 2T + XY` —
capture verbatim in `karyotype_formula` and summarize in `chromosome_morphology`.

---

## Staining Methods

Populate `staining_method` using these standardized terms:

| Use this term | When paper says |
|---------------|----------------|
| conventional Giemsa | "Giemsa staining", "standard staining", "solid staining" |
| C-banding | "constitutive heterochromatin banding", "C-bands", "C-banding" |
| G-banding | "Giemsa banding", "G-bands" |
| AgNOR | "silver staining", "Ag-NOR", "nucleolar organizer region staining" |
| FISH | "fluorescence in situ hybridization", "rDNA-FISH", "telomere FISH" |
| DAPI | "DAPI staining", "DAPI fluorescence" |
| CMA3 | "chromomycin A3", "CMA staining" |
| orcein | "aceto-orcein", "lacto-aceto-orcein" |
| feulgen | "Feulgen reaction", "Feulgen staining" |

If multiple methods are used, capture the one used to determine 2n (usually
conventional or C-banding). List additional methods in `notes`.

---

## NOR (Nucleolus Organizer Region)

- NOR position is determined by AgNOR staining or rDNA FISH.
- Capture in `NOR_position` as a brief phrase, e.g.:
  `"terminal, pair 3"`, `"X chromosome pericentromeric"`,
  `"interstitial, multiple pairs"`, `"detected, location unspecified"`.
- If the paper does not mention NOR at all, leave blank.

---

## Heterochromatin Patterns

Capture in `heterochromatin_pattern` from C-banding results. Examples:
- `"pericentromeric C-bands on all pairs"`
- `"large C-band block on Y chromosome"`
- `"C-negative autosomes, C-positive X"`
- `"extensive heterochromatin on sex chromosomes only"`
- If not reported, leave blank (do not infer).

---

## B Chromosomes

- B chromosomes are supernumerary, not part of the standard complement.
- They are often polymorphic (0, 1, 2 per individual).
- Record in `b_chromosomes`: range like `"0-2"`, fixed count `"1"`, or `"absent"`.
- `chromosome_number_2n` should be the **standard complement without Bs**, unless
  the paper only gives 2n inclusive of Bs (note this ambiguity in `notes`).

---

## Polyploidy

- Record ploidy in `ploidy`: `"diploid"`, `"triploid"`, `"tetraploid"`,
  or `"2x"`, `"3x"`, `"4x"`.
- Default assumption is diploid — **only populate ploidy if explicitly stated**.
- Parthenogenetic species may be triploid or tetraploid; flag for review.

---

## Taxon Name Handling

- Use the **binomial species name as given in the paper** for `species`.
- Populate `family` using **current classification** even if paper uses obsolete names.
  Note the original name in `notes`.
- `genus` = first word of `species`.

### Family synonymies — correct silently and note original in `notes`:
| Paper may say | Use in `family` |
|--------------|----------------|
| Bruchidae | Chrysomelidae |
| Anobiidae | Ptinidae |
| Scolytidae | Curculionidae |
| Platypodidae | Curculionidae |
| Rhynchophoridae | Curculionidae |
| Bostrychidae | Bostrichidae |
| Dermestidae s.s. | Dermestidae |

---

## Multiple Species / Records per Paper

- Each **species × locality × staining method** combination = one row.
- If same species studied from multiple localities with different 2n, one row per locality.
- If paper reports karyotypes for 20+ species in a table, extract **every row**.
- Populate `number_of_specimens` from the table when given.
- Secondary citations (paper cites another paper's karyotype) — do NOT extract;
  only primary observations.

---

## Language Handling

- Russian, Japanese, Spanish, Portuguese, Chinese papers are valid sources.
- Russian papers almost always use standard cytogenetic notation (2n=, XY) even in
  Cyrillic text — tables are usually interpretable.
- Japanese papers typically have English abstracts and English figure labels.
- If species name is unclear due to non-Latin script and no Latin equivalent is given,
  flag for review and note in `notes`.

---

## Search Strategy

**Additional high-value search terms** (supplement config.py):
- Specific genus names known for cytogenetics: *Xyleborus*, *Otiorhynchus*,
  *Diabrotica*, *Chrysomela*, *Tribolium*, *Callosobruchus*, *Dytiscus*,
  *Hydrophilus*, *Popillia*, *Melolontha*, *Coccinella*
- Journal-specific: "Caryologia beetles", "Genetica karyotype Coleoptera",
  "Cytologia Coleoptera", "Comparative Cytogenetics Coleoptera"
- Russian/Soviet terms: "Coleoptera кариотип" (karyotype), "жесткокрылые хромосомы"
- Key cytogenetics journals: Caryologia, Cytologia, Cytogenetics and Cell Genetics,
  Comparative Cytogenetics, Zoological Journal of the Linnean Society,
  Genetica, Chromosome Research

**Languages:** English, Russian, Japanese, Spanish, Portuguese, German — all valid.

**Date range:** No restriction — karyotype work goes back to the 1930s.
Historical papers from 1950s–1980s Soviet literature are especially underrepresented
in modern databases and are high-value targets.

---

## Judgment Rules

1. **Multiple species per paper:** Extract a separate record for each species.
2. **Conflicting 2n counts in one paper:** Record both values; note conflict in `notes`.
3. **Subspecies:** Record at subspecies level if reported; include full trinomial in `species`.
4. **Hybrid data:** Include but note in `notes`.
5. **B chromosomes:** Always record if mentioned.
6. **Voucher/locality:** Always capture if present.
7. **PDF unavailable:** Use abstract data only; set `extraction_confidence ≤ 0.6`.
   Add a note: `"abstract only"`.
8. **Unusual 2n (< 8 or > 120):** Extract but set `flag_for_review = true`.
9. **Meioformula only:** If paper gives only meiotic n and no 2n, populate
   `n_haploid` and leave `chromosome_number_2n` blank; flag for review.

---

## Stopping Conditions

Stop searching when ANY of the following is true:
- 10,000 records have been extracted
- 15 consecutive search rounds return no new papers (raised from 5 — many
  legitimate query blocks are narrow and return nothing, especially genus-level
  or author-level searches in undersampled groups)
- All search terms in `config.py` have been processed at least once

---

## Notes / Running Log

Use this section to track observations as the agent runs:
- (add notes here periodically; the agent may also append summary lines after each run)
