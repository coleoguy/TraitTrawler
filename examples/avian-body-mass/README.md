# Example: Avian Body Mass

This directory demonstrates how to adapt TraitTrawler for a different taxon and trait — in this case, body mass data for birds.

## Files

| File | Purpose |
|:-----|:--------|
| `collector_config.yaml` | Project settings: taxa, trait definition, output fields, proxy URL |
| `config.py` | Search queries (80 order × keyword combos + 11 general/journal) |
| `guide.md` | Domain knowledge for the extraction agent: units, preferences, pitfalls |

## To use

1. Copy these three files to a fresh folder
2. Edit `collector_config.yaml`: set your `project_root`, `proxy_url`, and `institution`
3. Open the folder in Cowork with the TraitTrawler skill installed
4. Say "let's collect some data"

See the main [README](../../README.md) for full instructions.
