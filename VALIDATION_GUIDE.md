# Validation Guide

A step-by-step playbook for running the three-tier validation study. Each tier is independent — run them in any order. The whole thing takes about 15–20 hours of TraitTrawler runtime spread across a few days.

**What you'll end up with:** Three completed datasets showing TraitTrawler works on (1) your home turf, (2) someone else's gold standard, and (3) a completely novel domain. Plus all the metrics you need for the manuscript.

---

## Before You Start (One-Time Setup)

- [ ] Make sure you have Claude Pro/Max with Cowork enabled
- [ ] Claude in Chrome extension installed and logged into TAMU library
- [ ] TraitTrawler skill installed in Cowork
- [ ] This repo cloned somewhere you can find it

Create a folder for the whole validation study:

```bash
mkdir -p ~/validation_study/{tier1_beetles,tier2_pantheria,tier3_menopause}
```

---

## Tier 1: Coleoptera Karyotypes

**The point:** You ARE the world expert. You have the human-curated database. This tier shows peak accuracy when the domain knowledge is maxed out.

### What you're comparing against

Your own curated beetle karyotype database (4,959 records, 4,298 species). You already did the big comparison (5,339 AI vs 4,959 human). For this validation, you need a **blind holdout test** — papers the agent hasn't seen, where you verify every single field by hand.

### Step 1: Pick 20 holdout papers

Pick 20 papers that span the difficulty spectrum. You want a mix:

- [ ] 5 easy papers (clean tables, one species per row, explicit values)
- [ ] 5 medium papers (multiple tables, some notation quirks)
- [ ] 5 hard papers (catalogues, non-English, ambiguous notation)
- [ ] 5 edge cases (very old papers, scanned PDFs, review papers with comparative tables)

**How to pick them:** Go through your personal PDF collection. Pick papers you KNOW the answers for — you're going to verify every extracted field. Write down the 20 DOIs in a text file.

```
# ~/validation_study/tier1_beetles/holdout_dois.txt
10.3897/CompCytogen.v10i3.9504
10.1007/s10709-003-2534-z
... (18 more)
```

### Step 2: Set up a fresh project

```bash
cp -r examples/coleoptera-karyotypes/ ~/validation_study/tier1_beetles/project/
```

Edit `collector_config.yaml`:
- Set your `proxy_url` and `contact_email`
- Set `batch_size: 25` (enough for 20 papers plus a few extras)

**Important:** Do NOT copy any existing `state/` folder or `results.csv`. This must be a clean start.

### Step 3: Run calibration

Open the `project/` folder in Cowork. Say:

```
Run calibration with these seed papers: [paste 3-5 DOIs that are NOT in your holdout set]
```

Let calibration finish. It will build guide.md from scratch based on those seed papers. Start a new conversation when it tells you to.

### Step 4: Process the holdout papers

Drop the 20 holdout PDFs into `project/pdfs/`. Say:

```
Process the PDFs in the pdfs folder. PDF-only mode.
```

Let it run. It will extract records from all 20 papers.

**What you should see:** Progress updates every 5 papers, a session summary at the end with record counts, confidence distribution, and QC summary.

### Step 5: Verify every record by hand

This is the tedious part. Open `results.csv` and go through every single record. For each one:

1. Open the original paper (use `pdf_filename` to find it)
2. Go to `source_page`
3. Check each trait field against the actual text/table
4. Mark in a spreadsheet: field name, extracted value, correct value, correct? (yes/no)

**Make it easier:** Create a spreadsheet with columns: `doi | species | field | extracted | correct_value | match`. One row per field per record. If the paper has 5 records with 4 trait fields each, that's 20 rows to verify.

Save this as `~/validation_study/tier1_beetles/gold_standard.csv`.

### Step 6: Also check for missed records

Go back through each paper and check: did TraitTrawler miss any species? For each missed species, add a row:

```
doi | species | _record_level | [empty] | present | no
```

This captures false negatives — species that were in the paper but the agent didn't extract.

### Step 7: Compute metrics

Feed your gold standard into the benchmark script:

```bash
# Convert your spreadsheet to the benchmark_gold.jsonl format:
# Each row becomes a JSON line:
# {"doi": "...", "species": "...", "field": "...", "extracted_value": "...", "gold_value": "...", "correct": true/false, "predicted_confidence": 0.92}

# Then copy it to the project state folder:
cp gold_standard.jsonl project/state/benchmark_gold.jsonl

# Run the benchmark:
python3 project/scripts/benchmark.py --project-root project/ --full
```

**What you get:**
- Per-field precision, recall, F1 (e.g., chromosome_number: P=0.97, R=0.95, F1=0.96)
- Record-level precision and recall
- Brier score
- Which fields are weakest

Also run calibration to get the reliability diagram:

```bash
# First, generate calibration data from your gold standard:
# (same data, formatted for the calibration script)
cp gold_standard.jsonl project/state/calibration_data.jsonl

python3 project/scripts/calibration.py --project-root project/ --full
```

**What you get:** ECE score, reliability diagram showing predicted vs. actual accuracy.

### What to put in the manuscript (Tier 1)

> "We evaluated extraction accuracy on a blind holdout set of 20 papers
> spanning easy, medium, hard, and edge-case difficulty levels. A domain
> expert (H.B.) verified every extracted field against the original paper.
> Table X shows per-field precision, recall, and F1. The overall record-level
> F1 was [X]. The confidence calibration reliability diagram (Fig. X) shows
> an Expected Calibration Error of [X], indicating that the system's
> confidence scores are [well/poorly] calibrated."

---

## Tier 2: PanTHERIA Mammal Body Mass

**The point:** Can TraitTrawler extract a completely different trait for a completely different taxon, starting from scratch, and produce results that match a canonical gold-standard dataset?

### What you're comparing against

PanTHERIA (Jones et al. 2009, Ecology 90:2648). It has species-level body mass data for thousands of mammals. Download it:

```bash
# Download PanTHERIA
cd ~/validation_study/tier2_pantheria/
curl -L "https://esapubs.org/archive/ecol/E090/184/PanTHERIA_1-0_WR05_Aug2008.txt" -o pantheria.txt
```

The body mass column is `5-1_AdultBodyMass_g`. Species names are in `MSW05_Binomial`.

### Step 1: Create a new project folder

```bash
mkdir -p ~/validation_study/tier2_pantheria/project
cd ~/validation_study/tier2_pantheria/project
```

### Step 2: Run the setup wizard from scratch

Open the folder in Cowork. Say:

```
Let's set up a new trait database. I want to collect body mass data for mammals.
```

Answer the wizard questions:
- Taxa: "Mammalia"
- Trait: "adult body mass"
- Keywords: let the agent research them ("you figure it out")
- Email: your email
- Institution: Texas A&M
- Taxonomic groups: let the agent research ("you figure it out" — it will propose orders/families)
- Journals/authors: let the agent research
- How trait is reported: let the agent research — this is the cold-start test

**This is important:** Let the agent figure things out on its own as much as possible. The whole point is showing it can bootstrap from zero.

### Step 3: Run calibration

The agent will find seed papers and run calibration. Let it do its thing. When it says "start a new conversation," do that.

### Step 4: Collect data

Start a new conversation. Say:

```
Run a session. Do 100 papers.
```

This will take 4–6 hours. You can do it across multiple sessions — say "do 30 papers" three times with breaks in between.

**What you should see:** The agent searching PubMed and OpenAlex for mammal body mass papers, downloading PDFs, extracting body mass values with sample sizes and sex, writing to results.csv.

### Step 5: Compare against PanTHERIA

Now the fun part. You need to match your extracted records against PanTHERIA by species name and compare body mass values.

```python
# ~/validation_study/tier2_pantheria/compare.py
import csv
import pandas as pd
import numpy as np

# Load PanTHERIA
pantheria = pd.read_csv("pantheria.txt", sep="\t")
pantheria = pantheria[["MSW05_Binomial", "5-1_AdultBodyMass_g"]]
pantheria.columns = ["species", "pantheria_mass_g"]
pantheria = pantheria[pantheria["pantheria_mass_g"] != -999.00]  # -999 = missing

# Load TraitTrawler results
tt = pd.read_csv("project/results.csv")
# Aggregate to species-level means (TT may have multiple records per species)
tt_means = tt.groupby("species")["body_mass_g_mean"].mean().reset_index()
tt_means.columns = ["species", "tt_mass_g"]

# Merge on species name
merged = pd.merge(tt_means, pantheria, on="species", how="inner")

print(f"Species in TraitTrawler: {len(tt_means)}")
print(f"Species in PanTHERIA: {len(pantheria)}")
print(f"Species in both (overlap): {len(merged)}")
print(f"Jaccard similarity: {len(merged) / (len(tt_means) + len(pantheria) - len(merged)):.3f}")

# Correlation
if len(merged) > 5:
    r = np.corrcoef(np.log10(merged["tt_mass_g"]), np.log10(merged["pantheria_mass_g"]))[0, 1]
    print(f"Log10 body mass correlation: r = {r:.3f}")

    # RMSE on log scale
    rmse = np.sqrt(np.mean((np.log10(merged["tt_mass_g"]) - np.log10(merged["pantheria_mass_g"]))**2))
    print(f"RMSE (log10 g): {rmse:.3f}")

    # Percent within 2x of PanTHERIA value
    ratio = merged["tt_mass_g"] / merged["pantheria_mass_g"]
    within_2x = ((ratio > 0.5) & (ratio < 2.0)).mean()
    print(f"Within 2x of PanTHERIA: {within_2x*100:.1f}%")

# Species NOT in PanTHERIA (novel contributions)
novel = set(tt_means["species"]) - set(pantheria["species"])
print(f"Species in TT but NOT in PanTHERIA: {len(novel)}")

merged.to_csv("comparison.csv", index=False)
print("Saved comparison.csv")
```

Run it:
```bash
cd ~/validation_study/tier2_pantheria/
python3 compare.py
```

### Step 6: Make the comparison plot

```python
# ~/validation_study/tier2_pantheria/plot.py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

merged = pd.read_csv("comparison.csv")

fig, ax = plt.subplots(figsize=(8, 8))
ax.scatter(np.log10(merged["pantheria_mass_g"]),
           np.log10(merged["tt_mass_g"]),
           alpha=0.5, s=20, c="#2196F3")
ax.plot([0, 7], [0, 7], "k--", linewidth=1, label="1:1 line")
ax.set_xlabel("PanTHERIA log10(body mass, g)", fontsize=12)
ax.set_ylabel("TraitTrawler log10(body mass, g)", fontsize=12)
ax.set_title(f"TraitTrawler vs PanTHERIA (n={len(merged)} species)", fontsize=13)
ax.legend()
ax.set_aspect("equal")
plt.tight_layout()
plt.savefig("pantheria_comparison.png", dpi=300)
print("Saved pantheria_comparison.png")
```

### What to put in the manuscript (Tier 2)

> "To test generalizability, we configured TraitTrawler for adult body mass
> in mammals — a taxon and trait unrelated to the development dataset. The
> agent bootstrapped from scratch: it researched search terms, identified
> seed papers, calibrated extraction rules, and collected data from [N]
> papers over [N] sessions. We compared species-level body mass means
> against PanTHERIA (Jones et al. 2009). Of [N] species extracted, [N]
> overlapped with PanTHERIA. The log10 body mass correlation was r = [X]
> (Fig. X). [N] species were extracted by TraitTrawler but absent from
> PanTHERIA, representing novel data contributions."

---

## Tier 3: Human Menopause Age of Onset

**The point:** This is the "wow" tier. No existing compiled database. A medically relevant topic. Shows a clinical researcher could use this tool to build a dataset for a systematic review in a day instead of six months.

### What you're comparing against

There's no single gold-standard database. Instead, compare against published meta-analyses:

- **Schoenaker et al. 2014** (Human Reproduction Update): 46 studies from 24 countries, mean age 48.8 years
- **Ahuja 2016** (Journal of Mid-Life Health): Asian populations
- Any other large meta-analysis you can find

The test: Does TraitTrawler independently recover the same studies the meta-analyses found, and do the extracted values match?

### Step 1: Download the meta-analysis study lists

Read the Schoenaker et al. paper. Make a list of the 46 studies they included with: author, year, country, reported mean menopause age, sample size.

Save as `~/validation_study/tier3_menopause/meta_analysis_studies.csv`:

```
author,year,country,mean_age,sample_size,doi
Gold,2001,USA,51.4,3302,10.xxxx/xxxx
...
```

This is your reference dataset. You'll check how many of these 46 studies TraitTrawler independently discovers and extracts correctly.

### Step 2: Create a new project from scratch

```bash
mkdir -p ~/validation_study/tier3_menopause/project
cd ~/validation_study/tier3_menopause/project
```

### Step 3: Run setup wizard

Open in Cowork. Say:

```
Set up a new trait database. I want to collect age at natural menopause from the human epidemiological literature.
```

Answer the wizard:
- Taxa: "Homo sapiens" (or just say "humans")
- Trait: "age at natural menopause"
- Keywords: let the agent research ("you figure it out")
- Email: your email
- Institution: Texas A&M

When it asks about output fields, you want something like:
- `mean_age_menopause` (float, years)
- `sd_age_menopause` (float)
- `median_age_menopause` (float, if reported instead of mean)
- `sample_size` (integer)
- `population` (string — "Japanese women", "rural Indian women", etc.)
- `country` (string)
- `study_design` (string — "cross-sectional", "longitudinal", "retrospective")
- `menopause_definition` (string — how they defined natural menopause)
- `age_range` (string — e.g., "45-55")

### Step 4: Run calibration

Use 3-5 of the meta-analysis papers as seed papers (give it the DOIs from Schoenaker et al. that you know are open-access). Let calibration finish.

### Step 5: Collect data

```
Run a session. Do 100 papers.
```

Let it run. This is a very different literature from beetles — expect:
- More abstract-only extractions (medical papers are often paywalled)
- More heterogeneity in how data is reported (means, medians, ranges)
- More complex inclusion criteria (pre- vs. post-menopausal, natural vs. surgical)

### Step 6: Compare against the meta-analysis

```python
# ~/validation_study/tier3_menopause/compare.py
import csv
import pandas as pd

# Load meta-analysis studies
meta = pd.read_csv("meta_analysis_studies.csv")

# Load TraitTrawler results
tt = pd.read_csv("project/results.csv")

# How many of the 46 meta-analysis studies did TT find?
meta_dois = set(meta["doi"].dropna().str.lower())
tt_dois = set(tt["doi"].dropna().str.lower())
recovered = meta_dois & tt_dois

print(f"Meta-analysis studies: {len(meta)}")
print(f"TraitTrawler papers processed: {tt['doi'].nunique()}")
print(f"Meta-analysis studies recovered by TT: {len(recovered)} / {len(meta_dois)} ({len(recovered)/len(meta_dois)*100:.0f}%)")

# For recovered studies, compare mean menopause age
for doi in recovered:
    meta_row = meta[meta["doi"].str.lower() == doi].iloc[0]
    tt_rows = tt[tt["doi"].str.lower() == doi]

    meta_age = meta_row["mean_age"]
    tt_ages = tt_rows["mean_age_menopause"].dropna()

    if len(tt_ages) > 0:
        tt_age = tt_ages.mean()
        diff = abs(tt_age - meta_age)
        print(f"  {meta_row['author']} {meta_row['year']}: meta={meta_age}, TT={tt_age:.1f}, diff={diff:.1f}")

# Studies TT found that are NOT in the meta-analysis (novel)
novel_dois = tt_dois - meta_dois
print(f"\nStudies found by TT but NOT in meta-analysis: {len(novel_dois)}")

# Countries in TT data
if "country" in tt.columns:
    print(f"Countries represented: {tt['country'].nunique()}")
    print(tt["country"].value_counts().head(10))
```

### Step 7: Run cross-paper conflict detection

```bash
python3 project/scripts/knowledge_graph_export.py --project-root project/ --format conflicts
```

This will show where different studies report different menopause ages for the same population — exactly the kind of heterogeneity a systematic review needs to document.

### What to put in the manuscript (Tier 3)

> "To demonstrate medical applicability, we tasked TraitTrawler with
> collecting age at natural menopause from the epidemiological literature,
> a domain with no existing compiled database. Starting from scratch, the
> agent extracted [N] population-level observations from [N] papers across
> [N] countries. Of the 46 studies included in a published meta-analysis
> (Schoenaker et al. 2014), TraitTrawler independently recovered [N]
> ([X]%). For recovered studies, the mean menopause age differed by [X]
> years on average. TraitTrawler additionally identified [N] studies not
> included in the meta-analysis, representing potential contributions to
> future reviews. Cross-paper conflict analysis detected [N] populations
> with discordant values."

---

## Putting It All Together for the Manuscript

### Table: Three-Tier Validation Summary

| | Tier 1: Beetles | Tier 2: PanTHERIA | Tier 3: Menopause |
|---|---|---|---|
| **Domain** | Coleoptera karyotypes | Mammal body mass | Human menopause age |
| **Gold standard** | Expert verification | PanTHERIA database | Published meta-analysis |
| **Prior knowledge** | Expert (battle-tested guide.md) | Cold start | Cold start |
| **Papers processed** | 20 (holdout) | ~100 | ~100 |
| **Record-level F1** | [fill in] | N/A (species-level comparison) | N/A (study-level recovery) |
| **Per-field accuracy** | [fill in per field] | r = [correlation] | [mean age diff] |
| **Novel contributions** | N/A (holdout only) | [N] spp not in PanTHERIA | [N] studies not in meta-analysis |
| **ECE** | [fill in] | N/A | N/A |
| **Runtime** | ~2 hours | ~5 hours | ~5 hours |

### Figure ideas

1. **Reliability diagram** (Tier 1) — shows confidence calibration
2. **Scatter plot** (Tier 2) — TT body mass vs PanTHERIA body mass, log scale, 1:1 line
3. **World map** (Tier 3) — dots for populations extracted, colored by menopause age
4. **Species accumulation curves** — all three tiers showing Chao1 convergence

---

## Checklist: Are You Done?

- [ ] Tier 1: 20 holdout papers processed, every field verified, metrics computed
- [ ] Tier 2: ~100 mammal papers processed, PanTHERIA comparison done, scatter plot made
- [ ] Tier 3: ~100 menopause papers processed, meta-analysis comparison done, conflicts detected
- [ ] All three `results.csv` files saved
- [ ] Benchmark and calibration scripts run on Tier 1 data
- [ ] Comparison scripts run on Tier 2 and Tier 3 data
- [ ] Summary table filled in
- [ ] Figures generated
