# TraitTrawler: Methods Description

*For a methods-style publication in Methods in Ecology and Evolution*

---

## Overview

TraitTrawler is an autonomous literature mining system that extracts
structured phenotypic data from the primary scientific literature. The
system searches bibliographic databases, retrieves full-text PDFs,
extracts trait records with mandatory double-entry verification, resolves
taxonomy, calibrates confidence scores, and writes validated records to a
flat-file database. It is taxon- and trait-agnostic: the same pipeline
that builds a Coleoptera karyotype database works for avian body mass,
plant phenology, or parasite host ranges.

The system is implemented as a Claude Code skill (Anthropic, 2025) — a
structured prompt package that configures a large language model (LLM)
orchestrator to coordinate specialized sub-agents. It requires no
programming, no API keys, and no local software beyond the Claude
desktop application and a web browser. A researcher configures a project
by specifying target taxa, trait fields, search keywords, and domain
knowledge; the system then operates autonomously for hours, producing a
provenance-tagged CSV suitable for downstream meta-analysis.

---

## System Architecture

### Agent hierarchy

TraitTrawler uses a four-agent pipeline coordinated by a Manager process
(Claude Opus 4.6, Anthropic). The Manager is a deterministic
state-machine loop that delegates all decision-making to a dispatch
script. It spawns, monitors, and processes returns from four specialized
agents, each running Claude Sonnet 4.6:

| Agent | Role | Concurrency |
|-------|------|-------------|
| Searcher | Query bibliographic APIs, triage results | Max 1, background |
| Fetcher | Acquire full-text PDFs | Max 1 API + 1 browser, background |
| Extractor | Read paper, extract structured records | Up to 5, background |
| Auditor | Verify every record against source text | 1, foreground (blocking) |

Agents communicate exclusively via filesystem folders containing JSON
handoff files. No agent reads another agent's specification or shares
in-memory state. All persistent state is maintained in JSON files within
a `state/` directory, enabling recovery after interruptions.

### Data flow

```
Bibliographic APIs -> queue.json -> Fetcher -> ready_for_extraction/
                                                    |
                                               Extractor
                                                    |
                                               finds/*.json
                                                    |
                                         Auditor (verification)
                                                    |
                                     scrub.py -> write_finds.py
                                                    |
                                              results.csv
                                                    |
                                             inline_qc.py
                                      +-----------+-----------+
                                      |           |           |
                                auto-fix    audit queue   human queue
                                (~50%)       (~45%)        (<5%)
```

### Dispatch loop

The Manager executes a three-step loop after each agent returns:

1. **Process return**: a script reads the agent's output files, updates
   state, and deletes the processed files.
2. **Checkpoint**: the dispatch script saves session state (papers
   processed, records written, coverage estimate) to
   `pipeline_state.json`.
3. **Recommend**: the dispatch script evaluates queue depths, active
   agents, and exhaustion conditions, then returns a list of actions
   (e.g., "spawn 3 extractors", "run verify_and_write").

The Manager executes every recommended action without deliberation. This
design confines all decision logic to a single Python script, making
behaviour deterministic and auditable.

---

## Literature Search

### Source databases

For each query, the Searcher agent queries four bibliographic sources in
parallel:

1. **PubMed** via NCBI E-utilities (`esearch.fcgi`, `efetch.fcgi`;
   retmax=50 per query).
2. **OpenAlex** via REST API
   (`api.openalex.org/works?search={query}&per_page=50`), which also
   indexes preprints from bioRxiv, medRxiv, and EcoEvoRxiv.
3. **bioRxiv and medRxiv** via the bioRxiv API, browsing recent
   preprints (default: last 6 months) in relevant subject categories.
4. **Crossref** via the bibliographic search endpoint
   (`api.crossref.org/works?query.bibliographic={query}&rows=50`).

Results are deduplicated across sources by DOI. Papers without DOIs are
excluded from automated search results (though they can be processed via
user-supplied PDFs).

### Query generation

Search queries are defined in a project configuration file as a list of
strings, typically constructed as a cross-product of taxonomic names and
trait-related keywords (e.g., 148 Coleoptera family names x 11 keywords
= 1,669 queries for the validation study). Queries are dispatched in
batches of 20, and the system tracks which queries have been executed in
a search log to prevent repetition across sessions.

### Triage

Each retrieved paper is classified as *likely* (title contains triage
keywords AND target taxa), *uncertain* (ambiguous or missing abstract),
or *unlikely* (wrong taxonomic order, purely methodological, no trait
data). Likely and uncertain papers enter the processing queue; unlikely
papers are recorded in `processed.json` with the rejection reason.

Triage rules are configured per project via `collector_config.yaml`
(inclusion/exclusion keywords, target taxa). After 100+ papers, the
system tracks triage-to-outcome accuracy (proportion of triaged papers
that yield data) and reports false-positive rates to guide keyword
refinement.

---

## PDF Acquisition

### Open-access cascade

For each queued paper, the Fetcher agent attempts retrieval through a
five-source cascade, stopping at the first valid PDF:

1. **Unpaywall** (`api.unpaywall.org/v2/{doi}`)
2. **OpenAlex** (`api.openalex.org/works/doi:{doi}`)
3. **Europe PMC** (`europepmc.org`, conditional on open-access flag)
4. **Semantic Scholar** (`api.semanticscholar.org`, `openAccessPdf` field)
5. **CORE** (`api.core.ac.uk/v3/search/works`)

Papers that cannot be retrieved via API are routed to a browser-based
Fetcher that navigates directly to the publisher page using the
researcher's institutional access (via a Chrome browser extension).

### Content validation

Every downloaded file undergoes three validation steps before entering
the pipeline:

1. **Format check**: file size > 100 bytes and begins with `%PDF-`.
2. **Content check**: at least one page with > 200 characters of
   extractable text (via pdfplumber), filtering paywall placeholder
   pages.
3. **Identity verification**: extracted title and author metadata from
   the PDF are compared against the expected paper to detect wrong-paper
   delivery (~5% mismatch rate observed from CORE).

PDFs that pass validation are saved with standardized filenames
(`Lastname-Year-Keyword-index.pdf`) and linked to their queue entry via
a JSON handoff file. Papers that fail all retrieval attempts are recorded
in `leads.csv` for manual interlibrary loan.

### User-supplied PDFs

Researchers can drop PDFs into a `provided_pdfs/` folder at any time.
The routing script extracts the DOI from the PDF text (first two pages),
checks for duplicates by content hash (SHA-256) and by DOI/title against
`processed.json`, and either links the PDF to existing records or
creates a new extraction handoff. Papers already processed in prior
sessions are skipped at routing time, avoiding redundant extraction.

---

## Data Extraction

### Extraction procedure

The Extractor agent receives a handoff file specifying the PDF path,
DOI, and basic metadata. It reads the project's domain knowledge
document (`guide.md`), schema configuration, and any accumulated
extraction examples, then processes the PDF as follows:

1. **Document classification**: the PDF is categorized as table-heavy,
   prose, catalogue, or scanned based on layout analysis. Table-heavy
   documents trigger a mandatory two-pass extraction strategy.

2. **Two-pass extraction** (table-heavy documents): In pass 1, the
   agent enumerates every species present in every data table and counts
   them. In pass 2, it extracts each record and verifies the count
   matches the enumeration. This prevents omissions from large tables.

3. **Data extraction**: records are extracted in priority order: tables,
   results sections, discussion (new data only, not restatements of
   cited values), appendices and supplementary materials. Each record
   includes the species binomial, all configured trait fields, the
   source page number, a verbatim source context quote (max 200
   characters), and extraction reasoning where the value is ambiguous.

4. **Compilation table handling**: tables that compile data from other
   publications are identified by caption keywords
   ("previous", "literature", "published", "comparison") and the
   presence of a reference column. Three configurable strategies are
   available: extract with attribution to the original source and a
   -0.15 confidence penalty (default), skip entirely, or extract cited
   references as leads for future retrieval.

5. **Self-validation**: the agent runs a schema validation script on its
   output JSON and fixes any errors while it still has the PDF in
   context.

### Confidence scoring

Each extracted record receives a confidence score on a continuous [0, 1]
scale reflecting the certainty of extraction:

| Score range | Criteria |
|-------------|----------|
| 0.90-1.00 | Explicit value in a table or results section with methods description |
| 0.80-0.89 | Value clearly stated but no methods description for how it was obtained |
| 0.80-0.85 | Value from a catalogue or comparative table, clearly stated |
| 0.60-0.65 | Value reported as uncertain by the original authors |
| <= 0.65 | Value inferred from text or ambiguously stated |

Compilation-table records receive a -0.15 penalty from their base score.

### Output format

Each paper produces a JSON file in the `finds/` directory containing
the DOI, title, PDF path, extraction timestamp, and an array of
records. Each record includes species binomial, trait field values, raw
confidence, source page, source context, and extraction reasoning.
Papers yielding no relevant data produce a separate no-data report.

---

## Double-Entry Verification

### Auditor procedure

Every extracted record undergoes mandatory verification by the Auditor
agent before entering the database. The Auditor reads only the cited
source pages (typically 1-2 pages per record, not the entire paper),
making verification approximately 10x faster than a full re-extraction.

For each record, the Auditor:

1. Reads the cited page(s) from the PDF.
2. Compares each extracted value against the source text.
3. Assigns a verification status:
   - **Confirmed**: value matches the source exactly.
   - **Corrected**: value was incorrect; the Auditor provides the correct
     value with an explanation.
   - **Ambiguous**: the source text is genuinely unclear; the record is
     routed to the human review queue.
4. Checks for missed records on the same pages.
5. Adjusts confidence: confirmed records with original confidence < 0.80
   receive a +0.10 boost (capped at 1.0); corrected records are set to
   0.75; ambiguous records are set to 0.50.

This extract-then-verify design is analogous to double-entry data
verification in systematic reviews (Buscemi et al., 2006), where two
independent assessments of each data point reduce transcription error.
Unlike three-way consensus voting (in which three agents independently
extract and a majority vote resolves disagreements), the verification
pass is *informed* -- the Auditor knows what to check -- enabling it to
catch errors that consensus misses (e.g., when all extractors make the
same mistake on ambiguous notation). The extract + verify approach
operates at approximately 45% of the token cost of three-agent consensus
while providing stronger error detection.

---

## Deterministic Normalization

Before records are written to the database, a deterministic
normalization script (`scrub.py`) applies the following transformations
to each finds file:

1. **Field name aliasing**: non-standard field names are mapped to
   canonical names (e.g., `sex_chrom` to `sex_chromosome_system`, `2n`
   to `diploid_2n_male`).
2. **Confidence normalization**: word-based confidence values ("high",
   "medium", "low") are converted to numeric equivalents (0.85, 0.65,
   0.40) and clamped to [0, 1].
3. **Sex chromosome system normalization**: variant notations are mapped
   to a controlled vocabulary (e.g., `xyp` to `Xyp`, `neo-xy` to
   `NeoXY`, `xo` to `X0`).
4. **Species name cleanup**: author citations appended to binomials are
   stripped via regex.
5. **Numeric normalization**: unit suffixes and equation prefixes are
   removed (e.g., `2n=24` to `24`, `23.8 h` to `23.8`); ranges are
   preserved with a note.
6. **Metadata backfill**: per-record metadata is populated from
   paper-level fields; author lists are converted from arrays to
   semicolon-delimited strings.
7. **Boolean coercion**: non-boolean values in the `flag_for_review`
   field (a known failure mode) are coerced to `False`.
8. **Null cleanup**: all `null`/`None` values are replaced with empty
   strings.

All transformations are lossless and deterministic, requiring no LLM
inference.

---

## Database Writing and Validation

### Schema-enforced writing

Records pass through a schema-enforced writer (`csv_writer.py`) that
applies field-level validation before appending to `results.csv`:

- **Required fields**: `species` and `extraction_confidence` (records
  missing either are dropped to a `needs_attention.csv` rejection file
  with the reason preserved).
- **Identification**: every record must have a `doi` or `paper_title`;
  records with neither are dropped.
- **Type enforcement**: float fields (`extraction_confidence`,
  `calibrated_confidence`), integer fields (`paper_year`), and boolean
  fields (`flag_for_review`) are validated and coerced where possible.
- **Confidence bounds**: values outside [0, 1] are flagged.
- **Abstract-only detection**: records with
  `source_type: "abstract_only"` are hard-dropped (abstract extraction
  is unreliable; the paper is routed to leads).

### Deduplication

Two-stage deduplication prevents redundant records:

1. **Primary key**: species + all trait field values (exact match).
2. **Secondary key** (DOI-scoped): species + primary trait field + DOI
   (catches re-extraction where values drifted slightly).

### Metadata backfill

For records with a DOI but missing bibliographic metadata
(authors, title, year, journal), the write pipeline queries the Crossref
API (`api.crossref.org/works/{doi}`) with a 10-second timeout and
backfills empty fields. This eliminates a major source of validation
flags in prior versions where missing metadata triggered false-positive
review flags.

### Atomic writes

All CSV operations use atomic writes (write to temporary file, `fsync`,
then `os.replace`) with file locking (`fcntl.flock`) to prevent
corruption from concurrent agents. Results.csv is snapshotted before
every write operation (rolling window of three snapshots) to enable
instant rollback.

### Duplicate-write prevention

A tracker file (`state/written_finds.json`) records the filename of
every successfully processed finds file. On re-run -- including cases
where the source file cannot be deleted due to filesystem sandbox
restrictions -- already-written files are skipped, preventing the
record duplication that was the primary data integrity issue in early
versions.

---

## Confidence Calibration

Raw confidence scores from the Extractor are calibrated using isotonic
regression (Niculescu-Mizil & Caruana, 2005) to ensure that a stated
confidence of 0.90 corresponds to approximately 90% empirical accuracy.

### Calibration data

Each Auditor verification produces a calibration observation:
`{predicted_confidence, correct}` where `correct = True` if the Auditor
confirmed the value and `False` if it was corrected. These observations
accumulate in `state/calibration_data.jsonl`.

### Model fitting

When at least 10 observations are available, scikit-learn's
`IsotonicRegression` (y_min=0, y_max=1, out_of_bounds="clip") is
fitted to the data. The model is stored as threshold arrays and applied
to new records via linear interpolation. A binned fallback (10
equal-width bins) is used when scikit-learn is unavailable.

### Evaluation metrics

- **Expected Calibration Error (ECE)**: weighted average of
  |accuracy - confidence| across 10 equal-width bins. Target: ECE < 0.05.
- **Brier score**: mean squared error of predicted probabilities.
- **Maximum Calibration Error (MCE)**: worst-bin |accuracy - confidence|.

Per-field calibration models are fitted when at least 30 observations
are available for a single field, allowing field-specific confidence
adjustment (e.g., chromosome counts may be more reliably extracted than
sex chromosome systems).

### Automatic recalibration

The model is automatically refitted every 20 records written,
maintaining calibration accuracy as extraction patterns evolve across a
session.

---

## Inline Quality Control

After every write operation, an inline QC pipeline (`inline_qc.py`)
evaluates all records and classifies issues into three tiers:

### Tier 1: Automatic fixes

Deterministic corrections applied directly to `results.csv`:

- **Taxonomy resolution**: missing `family` and `genus` fields are
  filled via the GBIF Backbone Taxonomy API (see below).
- **Publication year**: missing `paper_year` is backfilled from Crossref.
- **PDF path resolution**: missing `pdf_path` is matched against the
  local PDF library by DOI substring or author-year pattern.

### Tier 2: Audit queue

Records requiring manual or automated re-examination:

- **Low confidence**: extraction_confidence < 0.70.
- **Statistical outliers**: per-species Z-score > 3.0 for numeric trait
  fields (Grubbs' test when scipy is available; Z-score fallback
  otherwise; minimum group size: 5).
- **Cross-paper conflicts** (one-sided): same species and trait field
  with different values from different papers, where one value has
  confidence <= 0.80.
- **Guide drift**: records extracted before a change to the domain
  knowledge document, detected by MD5 hash comparison.

### Tier 3: Human review queue

Genuinely ambiguous cases routed to a CSV file for expert review:

- **Cross-paper conflicts** (high-confidence): 2+ papers report
  different values for the same species and trait field, both with
  confidence > 0.80, and the spread exceeds 50% of the median value
  for numeric fields. Non-numeric disagreements (e.g., different sex
  chromosome system strings) are always flagged.
- **Ambiguous verification**: the Auditor marked the record as
  ambiguous.

### Numeric conflict tolerance

For chromosome count fields, small differences are expected biological
variation (B-chromosome polymorphism, population-level variation,
counting uncertainty). Differences within a per-field tolerance
(+/-2 for diploid number, +/-1 for haploid number and autosome count)
are not queued for review but are noted in the record.

### Coverage tracking

After each write, the system computes the Chao1 nonparametric species
richness estimator (Chao, 1984):

    S_Chao1 = S_obs + f1^2 / (2 * f2)

where S_obs is the number of observed species, f1 the number of
singletons (species observed once), and f2 the number of doubletons
(species observed twice). When f2 = 0, the bias-corrected form
S_obs + f1(f1 - 1)/2 is used. The completeness ratio
S_obs / S_Chao1 informs search strategy: values below 0.50 suggest
broadening queries, while values above 0.90 indicate near-exhaustive
coverage.

---

## Taxonomy Resolution

Species names are resolved against the GBIF Backbone Taxonomy
(gbif.org) via the species match API
(`api.gbif.org/v1/species/match?name={name}&strict=false`). Rate
limiting (0.35 s between requests) respects API guidelines. Results are
cached locally with a configurable TTL (default: 90 days).

Match outcomes are handled as follows:

| Match type | Confidence | Action |
|------------|-----------|--------|
| Exact, accepted | -- | Fill family, genus, set accepted_name and gbif_key |
| Synonym | -- | Update species to accepted name, note original |
| Fuzzy, >= 90% | High | Accept with note |
| Fuzzy, < 90% | Low | Flag for review |
| Higher rank only | -- | Flag; do not update species |
| No match | -- | Flag; retain original name |

Offline mode (GBIF unavailable) defers resolution without caching
placeholder results, ensuring the cache contains only verified lookups.

---

## Adaptive Learning

### Domain knowledge evolution

During extraction, agents log discoveries (new notation variants, new
taxa, ambiguity patterns) to JSON files in a `learning/` directory. A
review script classifies each discovery as routine or structural:

- **Routine discoveries** (new notation variant, new journal, new
  prolific author): automatically appended to the domain knowledge
  document (`guide.md`) with duplicate detection.
- **Structural discoveries** (new extraction rules, taxonomic revisions):
  queued for human approval at session end.

This means the domain knowledge document improves continuously during
collection. Later extractions within the same session benefit from
earlier discoveries.

### Extraction example generation

When the Auditor confirms a record with confidence > 0.90, that record
becomes a candidate extraction example. After accumulating at least 5
confirmed examples, the system writes them to an examples file that
future Extractors receive as worked examples, improving accuracy over
time.

### Triage accuracy tracking

The system records triage-to-outcome pairs and computes per-query data
yield (records per paper). Queries with < 10% yield are deprioritized;
journals with consistently high yield are weighted in future triage.

---

## Bootstrap from Existing Data

When starting a new session on a project with existing data (e.g.,
upgrading from a prior version or importing a hand-curated
spreadsheet), the system automatically detects existing `results.csv`
and runs a nine-step bootstrap:

1. **Calibration seed**: treats all existing records as correct, fits an
   initial isotonic regression model.
2. **Coverage baseline**: computes Chao1 from existing species.
3. **Processed paper registry**: imports all DOIs and title-based keys
   to prevent re-extraction of any paper already in the database,
   including papers that yielded no data.
4. **Domain knowledge scaffold**: generates an initial `guide.md` from
   observed families, genera, notation variants, and value ranges.
5. **Extraction examples**: samples high-confidence records as worked
   examples.
6. **Triage intelligence**: computes journal-level and query-level yield
   statistics.
7. **Search log**: imports prior query execution history.
8. **Interlibrary loan list**: identifies papers with missing PDFs.
9. **Pipeline state**: initializes the checkpoint file.

The more prior state the user provides (results.csv alone, or a
complete project folder including cached taxonomic lookups, calibration
data, and search history), the stronger the bootstrap.

---

## Session Management

### Session lifecycle

A session begins by copying utility scripts, creating required
directories, snapshotting the current database, and reading the pipeline
checkpoint. The Manager then enters the dispatch loop and runs until the
target paper count is reached, all search and extraction streams are
exhausted, or the user intervenes.

### Fault tolerance

- **Checkpoint-driven recovery**: after LLM context compaction (where
  earlier conversation turns are summarized to free memory), the Manager
  reads `pipeline_state.json` and resumes the dispatch loop without
  state loss.
- **Pre-write snapshots**: results.csv is copied before every append
  (rolling window of 3), enabling recovery from write errors.
- **Session-start backup**: a permanent archive of results.csv is
  created at each session start.
- **Per-agent retry policy**: each agent type has at most 1 automatic
  retry on failure. After 2 failures for the same paper, the work item
  is retired with the failure reason logged.
- **Idempotent writes**: a written-files tracker prevents re-processing
  of finds files that could not be deleted due to filesystem
  restrictions.

### Concurrency control

The Manager enforces concurrency limits: 1 Searcher, 1 API Fetcher, 1
Browser Fetcher (API and Browser may run concurrently), up to 5
Extractors, and 1 foreground verify-and-write pipeline. All shared state
files use POSIX file locking to prevent race conditions between
concurrent background agents.

---

## Context Conservation

A key design goal is minimizing the Manager's context consumption to
enable multi-hour autonomous sessions within the LLM's context window.

| Component | Tokens consumed |
|-----------|----------------|
| Manager specification | ~7,000 (fixed) |
| Per-dispatch-cycle overhead | ~200 |
| Agent spawn prompt | ~500 each |
| Reference document loading | 0 during collection |
| Sub-agent hook output | 0 (hooks removed in v5) |

With a ~200-token cost per dispatch cycle and no accumulating state in
context, the system can theoretically execute ~1,400 dispatch cycles
(~450 papers) before reaching context limits. In practice, sessions of
3-6 hours processing 50-100+ papers are routine.

---

## Provenance and Reproducibility

Every record in `results.csv` carries:

- `doi`: persistent identifier of the source paper.
- `source_page`: page number where the value was found.
- `source_context`: verbatim text (max 200 characters) from which the
  value was extracted.
- `extraction_reasoning`: explanation when the extraction was
  non-obvious.
- `extraction_confidence`: calibrated probability that the value is
  correct.
- `verification`: Auditor assessment (confirmed/corrected/ambiguous).
- `pdf_path`: local path to the source PDF.
- `session_id`: which collection session produced the record.
- `processed_date`: date the record was written.

The full event log (`state/run_log.jsonl`) records every agent spawn,
return, error, and state transition with timestamps. Session reports
summarize throughput, error rates, source breakdown, and triage accuracy.
Reproducibility snapshots capture configuration hashes at session start.

---

## Software and Dependencies

TraitTrawler is implemented as a Claude Code skill (Anthropic, 2025)
using Claude Opus 4.6 for the Manager and Claude Sonnet 4.6 for all
sub-agents. The system runs within the Claude desktop application (macOS
or Windows) or the Claude web application with Cowork mode.

Python dependencies (installed automatically if missing): `pdfplumber`
(PDF text extraction), `PyYAML` (configuration parsing). Optional:
`scikit-learn` (isotonic regression for confidence calibration), `scipy`
(Grubbs' test for outlier detection).

External APIs used: NCBI E-utilities (PubMed), OpenAlex, bioRxiv/medRxiv
API, Crossref, Unpaywall, Europe PMC, Semantic Scholar, CORE, and GBIF
Backbone Taxonomy. All API access uses polite-pool email headers where
supported and respects rate limits.

The system is distributed as a `.skill` package (a ZIP archive
containing the Manager specification, agent specifications, utility
scripts, and reference documents). Source code is available at
github.com/coleoguy/TraitTrawler under the MIT license.

---

## References

- Buscemi, N. et al. (2006). Single data extraction generated more
  errors than double data extraction in systematic reviews. Journal of
  Clinical Epidemiology, 59(7), 697-703.
- Chao, A. (1984). Nonparametric estimation of the number of classes in
  a population. Scandinavian Journal of Statistics, 11(4), 265-270.
- Niculescu-Mizil, A. & Caruana, R. (2005). Predicting good
  probabilities with supervised learning. Proceedings of the 22nd
  International Conference on Machine Learning, 625-632.
