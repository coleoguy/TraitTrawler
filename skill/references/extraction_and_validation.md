# Extraction and Validation

## Contents

- [§5. Full-Text Fetch](#5-full-text-fetch) — OA cascade, proxy, scanned PDFs, large PDFs, abstract fallback, leads
- [§6. PDF Naming and Organization](#6-pdf-naming-and-organization) — file naming convention and subdirectories
- [§7. Extraction](#7-extraction) — paper classification, two-pass table strategy, field definitions, domain rules, provenance
- [§7f. Record Validation](#7f-record-validation) — universal and project-specific checks, failure actions
- [§7g. Taxonomy Check](#7g-taxonomy-check-after-extraction-before-writing) — GBIF resolution, synonym handling
- [§8. Write to results.csv](#8-write-to-resultscsv) — deduplication logic, post-batch verification

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

5. **CORE** (core.ac.uk): `https://api.core.ac.uk/v3/search/works?q=doi:{doi}&limit=1`
   Check `results[0].downloadUrl` for a PDF link. No API key needed for basic access.

If a PDF URL is found, download and extract text:

1. First try WebFetch to get the PDF URL's content. WebFetch may return the
   text content directly for HTML-hosted papers.
2. If you need the actual PDF file on disk (for pdfplumber or vision extraction),
   use Python with urllib (which is in the standard library and usually works):
   ```python
   import urllib.request
   urllib.request.urlretrieve(pdf_url, local_path)
   ```
3. Then extract text with pdfplumber. If pdfplumber returns empty text
   (scanned PDF), see §5d.
4. If both WebFetch and urllib fail, try using Claude in Chrome to navigate
   to the PDF URL and save it.

**Note**: Always try WebFetch first for API calls (JSON endpoints like Unpaywall,
OpenAlex, etc.). For actual PDF file downloads, urllib is more reliable since
WebFetch is optimized for text content, not binary files.

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

For vision extraction, use the Read tool to read the PDF file directly —
Claude can read PDF files natively and extract text from scanned pages.
Read in chunks of 20 pages at a time using the `pages` parameter (e.g.,
`pages: "1-20"`, then `pages: "21-40"`). First 30 pages max unless the
user approves more. Watch for common OCR-like artifacts in the extracted
text (l/1 confusion, O/0 confusion, dropped superscripts) — note in
`notes` field.

**Model escalation for scanned PDFs**: If OCR artifacts are detected in the
extracted text (multiple l/1 or O/0 confusions, garbled superscripts),
escalate to the escalation model for re-extraction. Log per SKILL.md §2.

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

### 5f. Abstract fallback

If everything else fails, use the abstract. Set `source_type: abstract_only`
and `extraction_confidence ≤ 0.5`. Still extract — abstracts often contain
key data values even without full methodology.

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
Read full text and extract all records. Apply all rules from `guide.md` and
the triage/trait rules in `collector_config.yaml`.

**Model escalation for prose**: If the initial extraction produces records where
the majority have `extraction_confidence < model_routing.escalation_confidence_threshold`
(default: 0.5), re-extract the paper with the escalation model (default: opus).
Replace the low-confidence records with the re-extracted ones. Log per SKILL.md §2.

**Table-heavy papers — two passes (critical for completeness):**

*Pass 1 — Enumerate:* Read only the tables. List every species/taxon name across
all tables. Count the rows. Write the extraction plan explicitly before proceeding:
```
Tables found: 3 | Total species rows: 47
Species: Species_1, Species_2, Species_3...
```

*Pass 2 — Extract:* Work through the enumerated list one by one. After extraction,
verify: record count should match enumerated species count. If not, find the gaps.

**Model escalation for tables**: If the row-count mismatch exceeds the threshold
in `model_routing.escalation_row_mismatch_pct` (default: 10%), re-run pass 2
with the escalation model (default: opus). Log the escalation per SKILL.md §2.

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

All project-specific extraction rules live in `guide.md` and the triage rules
in `collector_config.yaml`. Read both before extracting. The rules in those
files take precedence over general reasoning.

Universal rules (apply to all projects):
- Extract data EXPLICITLY stated — never infer values not present in the text.
- Comparative tables in Introduction/Discussion are equally valuable to main results.
- Record notation exactly as written — never normalize (e.g., `Xyp ≠ Xy ≠ neo-XY`).

### 7e. Provenance tracking

For every extracted record, populate these provenance fields:
- **source_page**: Page number(s) where the data was found (e.g., "12", "45-47")
- **source_context**: Verbatim text passage or table row the record came from,
  truncated to 200 characters. This makes every record auditable without
  returning to the original PDF.
- **extraction_reasoning**: One-sentence note when ambiguity existed (e.g.,
  "2n=20 stated in Table 2 row 3; sex system inferred from formula 9+Xyp").
  Leave blank when extraction was unambiguous.

---

## 7f. Record Validation

Before writing each record to results.csv, validate it universally and
against project-specific rules.

### Universal validation checks (always apply):

1. **Required fields present**: either `doi` or `paper_title` must be non-empty.
2. **Species non-empty**: `species` field must contain a value (not null/empty).
3. **Confidence in valid range**: `extraction_confidence` must be a float 0.0–1.0.
4. **Confidence vs. source_type**: if `source_type == "abstract_only"`, then
   `extraction_confidence ≤ 0.55`. (Abstracts give less data, so lower ceiling.)
5. **No exact duplicates**: check against existing rows in `results.csv` for
   matching (doi, species, and all trait-specific field values). Skip duplicate
   and log to `state/needs_attention.csv` with reason `duplicate_record`.

### Project-specific validation checks:

Read `collector_config.yaml` → `validation_rules` (optional). Each rule specifies:
- `field`: name of the field to check
- `type`: one of `numeric_range`, `even_number`, `allowed_values`, `pattern`
- Rule-specific parameters (e.g., `min`, `max` for `numeric_range`)
- `on_fail`: action when validation fails (`flag`, `drop`, or `ask`)

Example `validation_rules` in YAML:
```yaml
validation_rules:
  - field: body_mass_g
    type: numeric_range
    min: 0.001
    max: 200000
    on_fail: flag
  - field: chromosome_number_2n
    type: even_number
    on_fail: flag
```

### Validation failure actions:

- **`flag`**: Add the record to `results.csv` with `flag_for_review = True`.
  Log the failure reason in the `notes` field.
- **`drop`**: Do NOT write the record. Log to `state/needs_attention.csv`
  with the field, rule violated, actual value, and reason.
- **`ask`**: Pause extraction and show the user: "Record validation: {field}
  failed {rule}. Actual value: {value}. [keep/flag/drop]". Respect the user's choice.

---

## 7g. Taxonomy Check (after extraction, before writing)

After extracting records from a paper and before writing to CSV, run the
taxonomy check on every species in the batch. See
[taxonomy.md](references/taxonomy.md) for full details.

**Quick summary**:
1. Collect unique species names from the extraction batch
2. Check `state/taxonomy_cache.json` for cached results
3. For uncached names, query GBIF Backbone Taxonomy via
   `scripts/taxonomy_resolver.py` or direct WebFetch
4. Apply results:
   - **SYNONYM**: Update `species` to accepted name. Add original name to
     `notes`: "Original name: {extracted}, resolved via GBIF"
   - **ACCEPTED**: No change. Auto-fill empty `family`/`genus` from GBIF
   - **FUZZY (high confidence)**: Ask user to confirm correction
   - **FUZZY (low confidence)**: Flag for review, keep original name
   - **NO MATCH**: Keep original, note "Not in GBIF", log as discovery
5. Populate `accepted_name`, `gbif_key`, and `taxonomy_note` fields

**Important**: Taxonomy resolution runs BEFORE deduplication. This ensures
that "Cicindela sylvatica" (synonym) and "Cylindera sylvatica" (accepted)
are recognized as the same species for dedup purposes.

---

## 8. Write to results.csv

Append extracted records to the `output_csv` path from `collector_config.yaml`.
Use only the fields listed in `output_fields`. Add `session_id` to every record.

### 8a. Deduplication

Before appending, perform a deduplication check. A record is a duplicate if
an existing record has the **same species AND identical values for ALL
trait-specific fields**. The dedup key does NOT include DOI — this means that
if Paper A and Paper B both report the exact same trait values for the same
species, only one record is kept. Different trait values for the same species
from different papers are NOT duplicates — they represent independent
observations (potentially real biological variation).

Trait-specific fields are all fields in `output_fields` that are not in the
core field set (paper metadata, taxonomy, data quality, provenance). The
agent identifies them from `collector_config.yaml`.

```python
import csv, os

fieldnames = [...]  # from collector_config.yaml output_fields
rows = [...]        # extracted records (after taxonomy check)
session_id = "2026-03-24T14:30:00Z"  # from §1c
path = "results.csv"

# Core fields excluded from dedup key
core_fields = {
    "doi", "paper_title", "paper_authors", "first_author", "paper_year",
    "paper_journal", "session_id", "species", "family", "subfamily", "genus",
    "extraction_confidence", "flag_for_review", "source_type", "pdf_source",
    "pdf_filename", "pdf_url", "notes", "processed_date", "collection_locality",
    "country", "source_page", "source_context", "extraction_reasoning",
    "accepted_name", "gbif_key", "taxonomy_note",
    "audit_status", "audit_session", "audit_prior_values"
}
trait_fields = [f for f in fieldnames if f not in core_fields]

for row in rows:
    row['session_id'] = session_id

# Build dedup keys from existing records: (species, trait_value_tuple)
existing_keys = set()
if os.path.exists(path):
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for existing_row in reader:
            key = (existing_row.get('species', ''),
                   tuple(existing_row.get(k, '') for k in trait_fields))
            existing_keys.add(key)

rows_to_write = []
for row in rows:
    key = (row.get('species', ''),
           tuple(row.get(k, '') for k in trait_fields))
    if key not in existing_keys:
        rows_to_write.append(row)
        existing_keys.add(key)  # prevent intra-batch duplicates too

file_exists = os.path.exists(path)
with open(path, "a", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    if not file_exists:
        writer.writeheader()
    writer.writerows(rows_to_write)
```

Use `extrasaction="ignore"` so unknown fields never crash the write.

### 8b. Post-batch verification

After writing a batch of records, run the verification script:

```bash
python3 verify_session.py --project-root .
```

(The script is copied to the project root at §1e — no need to reference
`${CLAUDE_SKILL_DIR}` here.)

Read the JSON report at `state/verification_report.json`. If errors are found,
report them to the user and offer to review. Do not silently continue past
verification failures.
