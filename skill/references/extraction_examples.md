# Extraction Examples and Notation Guide

Reference this file when extracting from catalogue entries, dense tables, or
ambiguous notation. The guide.md in the project root has broader taxonomic context —
read both.

---

## Catalogue / Reference Book Notation (e.g. Smith 1978 *Animal Cytogenetics*)

The most common compact format — one line per taxon:

```
Species_name  [2n_male]♂[, 2n_female]♀  [formula]  [Author(s) year(s)]
```

### Sex suffix notation
| Written | Meaning | Record as |
|---|---|---|
| `22♂` or `22d` | 2n = 22 in males | `chromosome_number_2n=22`, `sex_of_specimen=male` |
| `24♀` or `24Q` | 2n = 24 in females | `chromosome_number_2n=24`, `sex_of_specimen=female` |
| `22♂, 24♀` | dimorphic | Create TWO records, one per sex |
| `22` (no suffix) | sex unknown/not stated | `sex_of_specimen=unknown` |

### Formula notation
| Written | Meaning |
|---|---|
| `9+Xyp` | 9 autosome pairs + Xyp sex chromosome system |
| `9+X` | 9 autosome pairs + X0 system (write `X0` in sex_chr_system) |
| `8+neoXY` | 8 autosome pairs + neo-XY system |
| `9II+Xyp` | IDENTICAL to `9+Xyp` — II means bivalents (meiotic). Strip II, record formula verbatim |
| `10II+X` | IDENTICAL to `10+X` |

### Asterisk
`2n=22*` → uncertain value → `extraction_confidence ≤ 0.65`, note in `notes` field.

### Author codes in catalogue entries
Single letters (S=Smith, A=Asana, V=Virkki, K=Kacker, Y=Yadav, M=Manna) are
citation abbreviations only — they are NOT fields to record. Ignore them.

### Example catalogue entries and resulting records

**Input:**
```
Carabus auratus  38♂  19+Xyp  S65
```
**Output record:**
- species: `Carabus auratus`
- chromosome_number_2n: 38
- sex_of_specimen: male
- haploid_autosome_count: 19
- sex_chr_system: `Xyp`
- karyotype_formula: `19+Xyp`
- source_type: catalogue
- extraction_confidence: 0.85

---

**Input (dimorphic):**
```
Dytiscus marginalis  36♂, 37♀  17+Xyp  V71
```
**Output:** TWO records:
1. species: `Dytiscus marginalis`, 2n=36, sex=male, sex_chr_system=`Xyp`, haploid_autosome_count=17
2. species: `Dytiscus marginalis`, 2n=37, sex=female, sex_chr_system=null (female-only cannot confirm system)

---

**Input (uncertain):**
```
Bembidion quadrimaculatum  20*  9+X  S65
```
**Output:**
- chromosome_number_2n: 20
- sex_chr_system: `X0`
- extraction_confidence: 0.62
- notes: `2n asterisked in source (uncertain value). Verbatim: "20* 9+X S65"`

---

## Dense Comparative Tables

These appear in the Introduction or Discussion of many cytogenetics papers as context
for the focal species. They are equally valuable — extract EVERY row.

Common table headers that signal comparative data:
- "Chromosome numbers in genus X"
- "Karyotype data for family Y"
- "Published chromosome counts for tribe Z"
- "Summary of cytogenetic data"

**Two-pass extraction procedure:**

Pass 1 — enumerate every species name in the table (including footnoted or
parenthetical entries). Write out the full list with row count before proceeding.

Pass 2 — extract each species in order. Do not skip rows marked "same as above"
or "cf. previous" — resolve what the actual values are and create explicit records.

**Table with merged cells / spanning headers:**
If a table has a header like "Genus Carabus" spanning multiple rows, all rows
beneath it belong to that genus. Apply subfamily from the nearest taxonomic
header above.

---

## Vision-Extracted Text (Scanned PDFs)

Text from scanned papers often has OCR artifacts:
- `l` (lowercase L) and `1` (one) confused: `2l` likely means `21`
- `O` (letter) and `0` (zero) confused in chromosome counts
- Superscripts may be dropped: `X^p` becomes `Xp` — note in `notes` field
- Table columns may run together: use context (autosome count + sex system should
  sum to roughly 2n/2) to validate

When uncertain due to OCR artifacts, set `extraction_confidence ≤ 0.70` and
note the artifact in `notes`.

---

## Sex Chromosome System Reference

Never normalize — record exactly as written in source:

| Written in source | Record as | Notes |
|---|---|---|
| `XY` | `XY` | Standard |
| `X0` or `X1` | `X0` | Single X, no Y |
| `Xyp` | `Xyp` | Y with parachromatin; common in Coleoptera |
| `Xy` | `Xy` | Distinct from Xyp |
| `neo-XY` or `neoXY` | as written | Record verbatim |
| `X1X2Y` | `X1X2Y` | Multiple X system |
| `ZW` | `ZW` | Female heterogamety |

`Xyp ≠ Xy ≠ neo-XY ≠ XY` — these are biologically distinct. Never substitute.

---

## Female-Only Specimens

If a paper studied only female beetles:
- `sex_of_specimen`: female
- `sex_chr_system`: **null** — females are XX regardless of the male system
- Never infer X0, XY, or any system from female specimen data alone
- Exception: if the paper explicitly names the sex chromosome system based on
  other evidence (e.g., males from same population studied by a cited reference
  and stated in text) — then record that system and note the source.

---

## haploid_autosome_count Computation

Always compute from 2n and sex chromosome system when both are known:

| Sex chr system | Sex chr count | Formula |
|---|---|---|
| XY, X0, Xyp, Xy | 1 (X) for females; 2 (X+Y) for males XY; 1 for X0 males | varies |
| Standard XY males | 2 (X+Y) | haploid_autosome_count = (2n − 2) / 2 |
| X0 males | 1 (X only) | haploid_autosome_count = (2n − 1) / 2 |
| XY females (XX) | 2 (X+X) | haploid_autosome_count = (2n − 2) / 2 |
| X1X2Y males | 3 | haploid_autosome_count = (2n − 3) / 2 |

If sex chromosome count is ambiguous, compute conservatively and note.
