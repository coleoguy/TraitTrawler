---
name: traittrawler
description: >
  Autonomous literature data collector. Invoke this skill when the user wants to
  collect trait data from the scientific literature, process papers, extract
  structured records, fetch PDFs through a library proxy, or add records to
  results.csv. Also triggers on phrases like "run the agent", "collect some data",
  "work on the database", or "let's gather some papers". The skill is taxon- and
  trait-agnostic — it adapts to any system defined in the project's config files.
  It runs for as long as the user wants and picks up exactly where it left off.
compatibility: "Requires Bash, Read, Write, WebFetch, Claude in Chrome MCP, PubMed MCP, bioRxiv MCP"
---

# TraitTrawler

This skill searches the scientific literature, retrieves full-text papers, and
extracts structured data records into a CSV. Everything about *what* to collect
lives in three project files: `collector_config.yaml` (taxa, trait, fields),
`config.py` (search queries), and `guide.md` (domain knowledge for extraction).
The skill itself is taxon- and trait-agnostic.

You run until the user stops you or the search queue is exhausted. Pick up
exactly where the previous session ended.

**Project root**: the folder Cowork has open (the current working directory).
All paths below are relative to this root.

---

## 0. First-Run Detection

Before anything else, check whether `collector_config.yaml` exists in the
current working directory or any parent folder the user might have selected.

**If `collector_config.yaml` does NOT exist → run setup wizard:**

Ask the user the following questions one at a time (wait for each answer):

1. "What folder should I use as the project root? (I'll create all files there)"
2. "What taxa are you collecting data for? (e.g. Coleoptera, Aves, Mammalia)"
3. "What trait or data type are you collecting? (e.g. karyotype, body size, mating system)"
4. "What keywords in a paper title make it clearly relevant even without an abstract?"
5. "What is your contact email? (used for API polite-pool access)"
6. "What institution do you use for library access? (for the proxy URL)"
   — For Texas A&M: proxy is `http://proxy.library.tamu.edu/login?url=`
   — For others: offer to look it up or ask them to paste it
7. "What should I call the output CSV file? (default: results.csv)"

Then:
- Locate the skill directory (same as §1a):
  ```bash
  SKILL_DIR="$(dirname "$(find /sessions -path '*/skills/traittrawler/SKILL.md' -print -quit 2>/dev/null)")"
  ```
- Create `collector_config.yaml` from answers (using the template in
  `$SKILL_DIR/references/config_template.yaml`). **Important**: based on the
  user's answer to question 3 (trait type), populate `output_fields` with the
  appropriate trait-specific fields from `$SKILL_DIR/references/csv_schema.md`.
  Do NOT leave trait fields commented out — the generated config must include
  all fields the project will actually use.
- Create `state/` folder with empty state files (see §9a for schemas):
  `processed.json` (`{}`), `queue.json` (`[]`), `search_log.json` (`{}`),
  `large_pdf_progress.json` (`{}`)
- Create `pdfs/` folder
- Create `results.csv` with just the header row (field order from csv_schema.md)
- **Generate `config.py`** (search terms) if it doesn't exist:
  Ask the user two more questions:
  8. "What are the major taxonomic groups I should search? (e.g. family names,
     order names — I'll cross these with the trait keywords)"
  9. "Any specific journals or author names that are especially relevant?"

  Then generate `config.py` by cross-producting the taxonomic groups × trait
  keywords (derived from the triage_keywords in collector_config.yaml), plus
  the journal/author terms. Follow this structure:
  ```python
  """Search queries for {project_name}."""
  _TAXA = ["Family1", "Family2", ...]
  _TRAIT_KW = ["keyword1", "keyword2", ...]  # from triage_keywords
  _GENERAL = ["broad query 1", ...]
  _JOURNAL = ["keyword JournalName", ...]
  SEARCH_TERMS = [f"{t} {k}" for t in _TAXA for k in _TRAIT_KW]
  SEARCH_TERMS += _GENERAL
  SEARCH_TERMS += _JOURNAL
  SEARCH_TERMS = list(dict.fromkeys(SEARCH_TERMS))  # deduplicate
  ```
  Tell the user the query count and remind them they can edit `config.py`
  to add or remove terms anytime.

- **Generate `guide.md`** (domain knowledge) if it doesn't exist:
  Ask the user:
  10. "What should I know about how this trait is reported in the literature?
      (units, notation conventions, common pitfalls, what to extract vs. skip)"

  Generate `guide.md` from their answer, structured with sections for:
  Units/notation, What to extract, What to skip, Common pitfalls, and
  Taxonomy notes. Tell the user: "I've created `guide.md` from your answers.
  You can edit it anytime to add rules — the more specific you are, the
  better the extractions will be."

Once setup is complete, proceed to §1 (Startup) normally.

**If `collector_config.yaml` exists → skip to §1.**

---

## 1. Startup

### 1a. Locate the skill directory

The skill's bundled reference files live alongside this SKILL.md file.
Resolve once at startup and store as `SKILL_DIR`:

```bash
SKILL_DIR="$(dirname "$(find /sessions -path '*/skills/traittrawler/SKILL.md' -print -quit 2>/dev/null)")"
```

### 1b. Read files in order before doing anything else

**Project files** (in `project_root`):

1. `collector_config.yaml` — taxa targets, trait definition, triage rules,
   institution proxy URL, contact email, output paths. This is the master config.
2. `config.py` — full search term list (a collaborator with a different project
   supplies their own)
3. `guide.md` — domain knowledge (inject into all triage and extraction reasoning)
4. `state/processed.json` — DOI/title keys already handled (do NOT reprocess)
5. `state/queue.json` — papers fetched but not yet extracted
6. `state/search_log.json` — queries already run (do not repeat)
7. `results.csv` — count existing records for status report
8. `leads.csv` — papers where full text was unavailable but triage was
   likely/uncertain (see §5g). Count for status report.

**Skill reference files** (in `SKILL_DIR/references/`):

9. `csv_schema.md` — generic field definitions for paper metadata, data quality,
   and leads.csv. Read for reference on confidence guidelines and field types.

**Project-specific reference files** (in project root, optional):

10. `extraction_examples.md` — if present, read it. Contains notation rules,
    worked examples, and edge cases specific to this project's trait/taxon.
    Not all projects will have this file.

Report status before starting the loop, using `project_name` from config:

```
════════════════════════════════════════════════
 {project_name} — Starting
════════════════════════════════════════════════
 Records in database : 1,247
 Papers processed    : 340
 Leads (need PDF)    : 18
 Queue depth         : 12 pending
 Queries run         : 89 / 730
 Next query          : "Chrysomelidae karyotype"
════════════════════════════════════════════════
```

---

## 2. Main Loop

Repeat until the user stops you or you run out of searches:

**→ Search → Triage → Fetch → Extract → Update state → Report → repeat**

Aim to fully process 5–10 papers per reporting cycle. After each cycle, print a
rolling update (format in §10) so the user can see progress without asking.

---

## 3. Search

Pull the next unrun query from the search term list in `config.py`.

**PubMed** (primary): Use the PubMed MCP `search_articles`. For each result,
call `get_article_metadata` to get DOI, abstract, journal.

**bioRxiv/medRxiv** (secondary): Use `search_preprints` — covers recent work not
yet in PubMed. Call `get_preprint` for metadata.

Deduplicate against `processed.json` (by DOI; fall back to normalized title).
Add new papers to `queue.json`. Log query to `search_log.json`.
Skip queries already in `search_log.json`.

---

## 4. Triage

Classify each paper yourself using the `triage_rules` in `collector_config.yaml`
and the domain knowledge in `guide.md`. No external API call needed.

The three categories are always:
- **likely**: paper almost certainly contains the target trait data for the target taxa
- **uncertain**: abstract absent/ambiguous, or title implies relevance but can't confirm.
  Err strongly toward uncertain — false negatives are permanent data loss.
- **unlikely**: clearly irrelevant to the trait and/or taxa

**Rule**: If the abstract is missing but title contains any of the `triage_keywords`
from `collector_config.yaml` → classify as "likely".

Move likely/uncertain to fetch. Mark unlikely as processed immediately
(`processed.json` with `"triage": "unlikely"`).

---

## 5. Full-Text Fetch

Try sources in order. Stop as soon as you have usable text.

### 5a. Local cache
Check `pdfs/` for a cached file. If found, go straight to extraction.

### 5b. Open-access sources

Try each using WebFetch (use `contact_email` from `collector_config.yaml`):

1. **Unpaywall**: `https://api.unpaywall.org/v2/{doi}?email={contact_email}`
   Walk `best_oa_location` then `oa_locations` for `url_for_pdf`.

2. **OpenAlex**: `https://api.openalex.org/works/doi:{doi}?select=best_oa_location,open_access&mailto={contact_email}`
   Check `best_oa_location.pdf_url`.

3. **Europe PMC**: `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:{doi}&resultType=lite&format=json`
   If `isOpenAccess: Y` and has PMCID, construct PDF URL.

4. **Semantic Scholar**: `https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf`
   Check `openAccessPdf.url`. Also try title search if no DOI.

If a PDF URL is found: download with WebFetch and save to disk, then extract
text with pdfplumber. If pdfplumber returns empty text (scanned PDF), see §5d.

**Note**: Always use WebFetch for HTTP requests — never use `curl`, `wget`, or
Python `requests` directly, as these may be blocked by the runtime sandbox.

### 5c. Institution proxy (paywalled papers)

If all OA sources fail, use Claude in Chrome silently.
Use `proxy_url` from `collector_config.yaml`:

1. Navigate to: `{proxy_url}https://doi.org/{doi}`
2. If you land on a PDF or publisher page with a PDF link — download it.
3. If you land on a login/SSO page — user is not authenticated. Report once:
   `⚠ Proxy needs login — paywalled papers will be skipped until authenticated.`
   Then skip browser for subsequent papers until user confirms login.
4. Save PDF to `pdfs/{subfolder}/{filename}` (see §6).
5. Record `pdf_source: proxy` in the extracted record.

### 5d. Scanned PDF handling

When pdfplumber returns empty text (image-only PDF), do not silently skip or
automatically burn vision tokens. Instead:

- Check `collector_config.yaml` → `vision_extraction`:
  - If `ask`: prompt the user once per document:
    `📷 "{title}" appears to be a scanned PDF ({N} pages). Use vision extraction?
     It's thorough but slow (~2 min). [y/n/always/never]`
    Remember the answer for the rest of the session.
  - If `always`: proceed with vision extraction automatically (good for known
    scanned-only sources like Biodiversity Heritage Library).
  - If `never`: mark `pdf_source: scanned_skipped`, fall through to abstract.

For vision extraction: render pages as JPEG (300 DPI, first 30 pages max),
send to Claude with the OCR prompt from `guide.md`. Watch for common artifacts
(l/1 confusion, O/0 confusion, dropped superscripts) — note in `notes` field.

### 5e. Large PDF handling

When a PDF exceeds 100 pages or 10 MB:

1. Check `state/large_pdf_progress.json` for a resume bookmark
   (`{"doi": "...", "last_page": 47, "chunks_done": 3}`).
2. If resuming: start from `last_page + 1`. Announce:
   `📚 Resuming large PDF from page {N}: "{title}"`
3. Process in batches of 50 pages per session. After each batch, update
   `large_pdf_progress.json` and continue with the next paper.
4. When a large PDF is fully processed, remove its entry from
   `large_pdf_progress.json`.

This means a 400-page Animal Cytogenetics volume will be worked through across
multiple sessions without losing progress or reprocessing pages.

### 5f. Abstract fallback

If everything else fails, use the abstract. Set `source_type: abstract_only`
and `extraction_confidence ≤ 0.5`. Still extract — abstracts often contain
a 2n count and sex chromosome system.

### 5g. Leads tracking

After attempting all fetch sources for a paper, if the paper triaged as
**likely** or **uncertain** and full text could NOT be obtained (i.e., the
paper fell through to abstract-only or was skipped entirely), append a row
to `leads.csv` in the project root. This gives the user an actionable list
of papers worth manually obtaining.

**leads.csv fields:**

| Field | Type | Notes |
|---|---|---|
| `doi` | string | Full DOI |
| `paper_title` | string | Full title |
| `first_author` | string | Last name of first author |
| `paper_year` | integer | Publication year |
| `paper_journal` | string | Journal name |
| `triage` | string | `likely` or `uncertain` |
| `reason` | string | Why full text failed — one of: `paywall_no_proxy_auth`, `pdf_download_failed`, `pdf_timeout`, `scanned_skipped`, `browser_failed`, `no_oa_source` |
| `abstract_extracted` | boolean | `true` if abstract-only extraction was done |
| `records_from_abstract` | integer | Number of records extracted from abstract (0 if none) |
| `date_added` | string | ISO date the lead was logged |
| `status` | string | `new` on creation. User can manually mark `obtained` or `skip` |

Write leads the same way as results.csv (Python csv.DictWriter, append mode,
`extrasaction="ignore"`). Create the file with headers if it doesn't exist.

**Do NOT add a lead if:**
- The paper triaged as "unlikely" (already filtered out)
- Full text was successfully obtained (even if extraction found 0 records)
- The paper is already in `leads.csv` (deduplicate by DOI/title)

---

## 6. PDF Naming and Organization

Save PDFs as:
```
pdfs/{Subfolder}/{FirstAuthor}_{Year}_{JournalAbbrev}_{ShortDOI}.pdf
```

- **Subfolder**: the primary grouping field from `collector_config.yaml` →
  `pdf_subfolder_field` (default: `family`). Use `unknown/` if not yet known;
  rename after extraction if identified.
- **FirstAuthor**: last name of first author, ASCII only, no spaces.
- **Year**: 4-digit publication year.
- **JournalAbbrev**: first meaningful word of journal name, ≤12 chars.
- **ShortDOI**: last segment of DOI after final `/` or `.`, ≤10 chars.

Example: `pdfs/Carabidae/Smith_2003_CompCytogen_9504.pdf`

Create subdirectories as needed: `mkdir -p pdfs/{Subfolder}`.

---

## 7. Extraction

### 7a. Classify the paper

Before extracting, read enough text to identify document type:
- **prose**: standard journal article, trait data in Results/Discussion
- **table-heavy**: dense tables listing trait data for many species
- **catalogue**: reference book / review appendix with one-line-per-taxon entries

### 7b. Extraction strategy by type

**Prose papers — single pass:**
Read full text and extract all records. Apply all rules from `guide.md` and the
`extraction_rules` in `collector_config.yaml`.

**Table-heavy papers — two passes (critical for completeness):**

*Pass 1 — Enumerate:* Read only the tables. List every species/taxon name across
all tables. Count the rows. Write the list explicitly before proceeding:
```
Tables found: 3 | Total species rows: 47
Species: Carabus auratus, Carabus nemoralis, Pterostichus melanarius...
```

*Pass 2 — Extract:* Work through the enumerated list one by one. After extraction,
verify: record count should match enumerated species count. If not, find the gaps.

**Catalogue entries — chunked two-pass:**
Break into chunks of ~100 taxon lines. For each chunk: enumerate names first,
then extract. If the project has `extraction_examples.md`, refer to it for
notation rules (already read at startup §1b).

### 7c. Field definitions

Refer to `SKILL_DIR/references/csv_schema.md` (already read at startup §1b) for
the full field list with types and rules. The `output_fields` list in
`collector_config.yaml` defines which fields are active for this project — a
collaborator with a different trait will have a different list.

### 7d. Domain rules

All project-specific extraction rules live in `guide.md` and `collector_config.yaml`
→ `extraction_rules`. Read both before extracting. The rules in those files take
precedence over general reasoning.

Universal rules (apply to all projects):
- Extract data EXPLICITLY stated — never infer values not present in the text.
- Comparative tables in Introduction/Discussion are equally valuable to main results.
- Record notation exactly as written — never normalize (e.g., `Xyp ≠ Xy ≠ neo-XY`).

---

## 8. Write to results.csv

Append extracted records to the `output_csv` path from `collector_config.yaml`.
Use only the fields listed in `output_fields`. Use Python via Bash:

```python
import csv, os
fieldnames = [...]  # from collector_config.yaml output_fields
rows = [...]        # extracted records
path = "results.csv"
file_exists = os.path.exists(path)
with open(path, "a", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    if not file_exists:
        writer.writeheader()
    writer.writerows(rows)
```

Use `extrasaction="ignore"` so unknown fields never crash the write.

---

## 9. State Management

### 9a. State file schemas

**`processed.json`** — object keyed by DOI (or normalized title if no DOI):
```json
{
  "10.3897/compcytogen.v10i3.9504": {
    "title": "Karyotype of Carabus auratus",
    "triage": "likely",
    "outcome": "extracted",
    "records": 3,
    "date": "2026-03-20"
  },
  "10.1234/example.5678": {
    "title": "Weevil feeding behavior",
    "triage": "unlikely",
    "outcome": "skipped",
    "records": 0,
    "date": "2026-03-20"
  }
}
```

**`queue.json`** — array of paper objects awaiting fetch/extraction:
```json
[
  {
    "doi": "10.1234/example.9999",
    "title": "Chrysomelidae chromosome survey",
    "authors": "Smith et al.",
    "year": 2021,
    "journal": "Comp Cytogenet",
    "abstract": "We report karyotypes for 12 species...",
    "triage": "likely",
    "source": "pubmed",
    "added_date": "2026-03-20"
  }
]
```

**`search_log.json`** — object keyed by query string:
```json
{
  "Carabidae karyotype": {
    "date": "2026-03-20",
    "pubmed_results": 23,
    "biorxiv_results": 1,
    "new_to_queue": 8
  }
}
```

### 9b. Update procedure

After every paper (success or failure):
- Add DOI (or normalized title) to `processed.json`
- Remove from `queue.json`
- If full text was unavailable and triage was likely/uncertain → append to `leads.csv` (see §5g)
- Write all files immediately — session can end anytime without data loss

Use atomic writes (write to `.tmp` then `os.rename`) to avoid corruption.

---

## 10. Progress Reporting

After every 5 papers, print a rolling update:

```
📄 [15/45 queued] "Smith et al. 2003 — Carabidae cytogenetics"
   → 8 records | source: proxy 🌐 | pdfs/Carabidae/Smith_2003_CompCytogen_9504.pdf
   → Session: +34 records | Database total: 1,281
```

Zero-record papers:
```
📄 [16/45] "Jones 1998 — Weevil feeding behavior"
   → 0 records (no target trait data — marked processed)
```

Large PDF progress:
```
📚 [large PDF, pages 51-100/380] "John 1975 — Animal Cytogenetics Vol. 3"
   → 142 records this batch | resuming next session from page 101
```

---

## 11. Session End

Print a summary when the user stops or searches are exhausted:

```
══════════════════════════════════════
 Session Complete
══════════════════════════════════════
 Papers processed this session : 23
 Records added                 : 89
 Via proxy (browser)           : 7
 Via open access               : 11
 Abstract-only                 : 5
 Leads added (need full text)  : 3
 Large PDFs in progress        : 1 (resuming p.101)
 Database total                : 1,336
 Leads total                   : 18
 Queue remaining               : 4
 Queries remaining             : 608 / 730
══════════════════════════════════════
```

---

## 12. Error Handling

- **Rate limits (429)**: back off 30s, retry once; if still failing, skip source.
- **PDF download timeout**: skip after 60s; note URL for retry next session.
- **Malformed state file JSON**: warn user, show raw content, do not overwrite.
- **results.csv write failure**: stop immediately — never silently drop records.
- **Chrome navigation fails**: mark `pdf_source: browser_failed`, fall through to abstract.
- **Proxy returns wrong content-type**: don't save as PDF; log and continue.

---

## 13. Dashboard

The skill includes a self-contained HTML dashboard that visualizes collection
progress and summary statistics. It lives at `{project_root}/dashboard.html`
and is regenerated automatically.

### When to update

Regenerate the dashboard at these points:
1. **Session start** (§1) — after reading state files, before the first batch
2. **Every 10 papers processed** — alongside the rolling progress update (§10)
3. **Session end** (§11) — as part of the session summary

### How to update

At **session start** (§1), copy the dashboard generator from `SKILL_DIR`
(already resolved in §1a) into the project root so it's always available:

```bash
cp "$SKILL_DIR/dashboard_generator.py" "{project_root}/dashboard_generator.py"
```

Then regenerate the dashboard any time with:

```bash
python3 "{project_root}/dashboard_generator.py" --project-root "{project_root}"
```

The script reads `results.csv`, `leads.csv`, `state/processed.json`,
`state/search_log.json`, and `config.py` and writes a single
self-contained `dashboard.html` with Chart.js visualizations.
No internet connection needed to view the output — Chart.js is
loaded from CDN at generation time and all data is inlined.

### What the dashboard shows

**KPI cards** (top row):
- Total records, unique species, papers processed
- Leads (need full text), flagged for review

**Search progress bar**: queries completed vs. total from `config.py`

**Charts** (auto-generated based on available data):
- Cumulative records over time (line chart)
- Records by taxonomic group — top 20 (horizontal bar)
- Records by publication year (bar)
- Full-text source breakdown (doughnut)
- Extraction confidence distribution (bar)
- Records by country — top 15 (horizontal bar)
- Lead failure reasons (horizontal bar)
- Lead status breakdown (doughnut)
- Additional trait-specific charts if recognized fields are present
  (e.g., chromosome number distribution for karyotype projects)

### Dashboard output location

The dashboard is always written to `{project_root}/dashboard.html`.
After generation at session start and session end, mention it to the user:

```
📊 Dashboard updated → dashboard.html
```

Do NOT open it in Chrome or ask the user to view it — just note that it
exists. The user can open it at their leisure.
