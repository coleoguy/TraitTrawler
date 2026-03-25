# Avian Body Mass — Extraction Guide

## Units
- Always record mass in **grams (g)**
- If the paper reports ounces or pounds, convert: 1 oz = 28.35 g, 1 lb = 453.6 g
- Note the conversion in the `notes` field

## Which measurement to prefer
1. **Wild-caught** over captive
2. **Breeding season** over non-breeding (note season in `season` field)
3. **Adult** over juvenile (note in `age_class`)
4. If both sexes reported separately, create **one row per sex**
5. If only "unsexed" or pooled mass is given, record sex as "unknown"

## Summary statistics
- `body_mass_g_mean`: arithmetic mean if reported; single value if n = 1
- `body_mass_g_sd`: standard deviation (not SE). If SE is given, convert: SD = SE × √n
- `body_mass_g_min` / `body_mass_g_max`: range endpoints
- `sample_size`: number of individuals measured

## Taxonomy
- Use the IOC World Bird List as the reference taxonomy
- If the paper uses a synonym, record the **current accepted name** as `species` and note the synonym in `notes`
- Populate `order`, `family`, `genus` from the accepted name

## Common pitfalls
- Tables titled "Morphometrics" sometimes omit mass — check column headers
- "Weight" in older literature usually means mass; record as body_mass_g
- Egg mass ≠ body mass — skip unless the paper also reports adult mass
- Some handbooks report "typical" ranges without sample sizes — flag_for_review = TRUE
