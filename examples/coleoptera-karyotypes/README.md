# Example: Coleoptera Karyotypes

This is the configuration used in the TraitTrawler validation study (Blackmon 2026, MEE). It collects diploid chromosome numbers, sex chromosome systems, karyotype formulas, and cytogenetic method details for beetles from the scientific literature.

## Files

| File | Purpose |
|:-----|:--------|
| `collector_config.yaml` | Project settings: Coleoptera taxa, karyotype output fields, TAMU proxy |
| `config.py` | 1,669 search queries (148 families × 11 cytogenetics keywords + general + journal) |
| `guide.md` | Domain knowledge: sex chromosome notation, family-specific rules, validation checks, staining conventions |
| `extraction_examples.md` | Worked examples for catalogue entries, dense tables, OCR artifacts |

## To use

1. Copy this folder to a new location (e.g., `~/coleoptera-karyotypes/`)
2. Edit `collector_config.yaml`: set your `proxy_url`, `institution`, and `contact_email`
3. Open the folder in Cowork with the TraitTrawler skill installed
4. Say "let's collect some data"

The agent will read all four files at startup and begin searching.

## Query coverage

The 1,669 queries in `config.py` cover all four suborders of Coleoptera:
Archostemata (4 families), Myxophaga (4), Adephaga (10), and Polyphaga (130 families across 12 superfamily groups). Each family is crossed with 11 cytogenetics keywords. An additional 12 general terms and 29 journal/author-targeted queries round out the set.

See the main [README](../../README.md) for full documentation.
