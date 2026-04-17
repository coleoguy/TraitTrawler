# TraitTrawler v6: Challenges and Design Suggestions

## Current Challenges

### 1. Record provenance is good but not verifiable without effort

Every record carries `source_page`, `source_context` (200 char verbatim quote), and `extraction_reasoning`. In practice, verifying a record still requires: opening the PDF, navigating to the page, finding the relevant table or sentence, and mentally matching the quote to the surrounding context. For a database with thousands of records, this is a bottleneck to both self-auditing and reviewer confidence. The 200-char context window is often too small to disambiguate which table cell or which sentence within a results paragraph a value came from.

### 2. The Auditor verifies but doesn't document its verification

The Auditor re-reads cited pages and confirms/corrects values, but its output is a JSON with a status label and optional correction. There is no persistent, human-readable trail showing *what the Auditor actually saw* versus *what the Extractor claimed*. When a record is marked "confirmed," there is no evidence of confirmation beyond the label. When "corrected," the prior value is stored but the reasoning for the correction is often minimal.

### 3. Confidence scores are a black box to downstream users

Calibrated confidence is a single float. A downstream user looking at a record with confidence 0.82 has no way to know whether the uncertainty is because (a) the value was in a compilation table, (b) the notation was ambiguous, (c) the PDF was low quality, or (d) the Extractor and Auditor disagreed and split the difference. The confidence number compresses multiple orthogonal dimensions of uncertainty into one scalar.

### 4. Compilation table provenance is weak

Records from compilation tables get `source_type: "compilation"` and a -0.15 confidence penalty, but they don't reliably capture the *original* citation. The original reference is often in a column of the compilation table, but the Extractor doesn't always extract it into a structured field. This means a compilation-sourced record may cite the review paper as its source rather than the primary paper, which is a provenance failure.

### 5. PDF linkage is fragile

`pdf_filename` and `pdf_path` connect records to source PDFs, but these are local filesystem paths. If PDFs are moved, renamed, or the project is shared, the links break. There's no content-based identifier (hash) tying a record to a specific PDF file.

### 6. Human review queue is a dead end

Records flagged for human review go to a CSV, but there's no structured workflow for resolving them. The queue grows; there's no mechanism to mark items as resolved, feed corrections back into results.csv, or track reviewer decisions. In the coleoweekend trial, the queue bloated to 6,960 rows (1,084 unique) before the dedup fix.

### 7. Cross-session reproducibility is incomplete

`session_id` and `processed_date` identify when a record was created, but the specific model version, skill version, guide.md hash, and config hash at extraction time aren't stored per-record. If guide.md evolves mid-session (via the learning system), two records from the same session may have been extracted under different domain knowledge states.

### 8. No image/figure extraction

Karyotype images, metaphase plates, and idiograms in papers are ignored entirely. For cytogenetics specifically, these figures often contain data not stated in the text (arm ratios, centromere positions, band patterns). More broadly, any trait domain where key data lives in figures (morphometric plots, phylogenies, maps) is systematically under-extracted.

---

## Suggestions for v6

### A. Per-record evidence bundles

For each extracted record, generate a small evidence package:

- A cropped screenshot or bounding-box coordinates of the exact table cell, figure, or sentence the value came from (not just a page number and 200-char quote)
- The Auditor's independent re-read result stored alongside the Extractor's original, as a diff
- A structured `evidence` JSON field per record containing: page, bbox/coordinates, full verbatim passage (not truncated), table ID if applicable, figure reference if applicable

This makes verification a 2-second visual check instead of a multi-minute hunt. It also makes the database self-documenting for reviewers and collaborators.

### B. Decomposed confidence into structured uncertainty

Replace or supplement the single confidence float with a structured uncertainty profile:

```json
{
  "value_clarity": 0.95,
  "source_reliability": 0.70,
  "notation_ambiguity": 0.90,
  "pdf_quality": 1.0,
  "auditor_agreement": true,
  "is_compilation": false,
  "overall": 0.85
}
```

The overall score can still be computed for filtering, but the components let users make informed decisions. A record with high value_clarity but low source_reliability (compilation table) is very different from one with low value_clarity (ambiguous notation) but high source_reliability (original primary data).

### C. Original citation extraction for compilation tables

When extracting from compilation/review tables, require the Extractor to capture the `original_citation` field (author, year, and DOI/title if available). Run a lightweight lookup to resolve to a DOI. This lets downstream users trace the record to its actual primary source, and enables deduplication against records extracted directly from that primary source.

### D. Content-addressed PDF storage

Hash every PDF (SHA-256) at ingest time. Store the hash as `pdf_sha256` on every record. This provides:

- Immutable linkage between record and source document regardless of file moves
- Deduplication of identical PDFs acquired through different routes
- Verification that a PDF hasn't been corrupted or swapped

### E. Structured human review workflow

Replace the flat CSV queue with a resolution-tracked system:

- Each review item gets a unique ID, creation date, and reason code
- Resolution states: `pending`, `confirmed`, `corrected`, `rejected`, `deferred`
- Corrections feed back into results.csv automatically
- A review dashboard shows queue depth, age distribution, and resolution rate
- Support batch review (show the user 10 items from the same paper at once with the PDF context pre-loaded)

### F. Per-record extraction provenance metadata

Store on each record:

- `skill_version`: TraitTrawler version used
- `guide_md_hash`: MD5 of guide.md at extraction time
- `config_hash`: MD5 of collector_config.yaml
- `extractor_model`: exact model string (e.g., "claude-sonnet-4-6-20260401")
- `auditor_model`: exact model string
- `extraction_trace_id`: link to the full extraction reasoning chain (already partially present but not consistently populated)

This enables post-hoc analysis of whether accuracy varies by model version, guide version, or config state.

### G. Figure and image awareness

For papers with karyotype images, idiograms, or data figures:

- Log which figures exist and what they contain (even if not fully extractable)
- Cross-reference text-extracted values against figure captions
- Flag records where a figure contradicts or supplements the text data
- For future work: extract data directly from simple figures (bar charts, scatter plots) using vision capabilities

### H. Exportable evidence reports

Generate per-paper or per-batch HTML reports that show, for each record:

- The extracted values in a table
- The source context (highlighted in the original page image or text)
- The Auditor's verification result
- The confidence breakdown
- Any flags or notes

These reports serve double duty: they're the quality documentation needed for publication, and they're the review interface for the human review queue. A reviewer can scan a report in minutes instead of individually checking records against PDFs.

### I. Differential quality metrics by data source

Track and report accuracy separately for:

- Records from tables vs. prose vs. figures
- Records from primary data vs. compilation tables
- Records from open-access vs. paywalled (proxy-fetched) papers
- Records by journal, decade, and language

This identifies systematic weak spots (e.g., "accuracy drops for pre-1990 papers" or "compilation tables have 3x the error rate") and informs both user trust and pipeline improvement.

### J. Active learning for human review prioritization

Instead of routing all low-confidence records equally to the review queue, use the accumulated review history to learn which error patterns actually matter. Prioritize review items by expected information gain: a record that would change a downstream analysis if wrong is more valuable to verify than one in a well-sampled clade where the value is consistent with 10 other sources.
