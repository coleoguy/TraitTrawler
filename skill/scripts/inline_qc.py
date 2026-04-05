#!/usr/bin/env python3
"""
Inline post-write QC pipeline for TraitTrawler v5.

Runs automatically after every write_finds.py call. Classifies issues into
three tiers:
  - Tier 1: Auto-fixable (deterministic fixes applied in-place to results.csv)
  - Tier 2: Audit queue (appended to state/audit_queue.json)
  - Tier 3: Human review queue (appended to state/human_review_queue.csv)

Also detects cross-paper conflicts, computes coverage stats, and triggers
auto-calibration when enough new records have accumulated.

Usage:
    python3 scripts/inline_qc.py --project-root . --session-id 20260404T120000

Output: JSON summary to stdout.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

# Add scripts/ to path so we can import sibling modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from state_utils import FileLock, safe_read_json, safe_write_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso():
    """Canonical UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_read_csv(path):
    """Read a CSV file into a list of dicts. Returns [] if missing."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def atomic_rewrite_csv(csv_path, rows, fieldnames):
    """Rewrite a CSV file atomically using temp-file-then-rename.

    Follows the same pattern as csv_writer.py: write to a temp file in the
    same directory, fsync, then os.replace for POSIX atomicity.
    """
    parent_dir = os.path.dirname(csv_path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".csv",
        dir=parent_dir,
        prefix=".results_qc_"
    )
    try:
        with os.fdopen(tmp_fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, csv_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _is_valid_binomial(species):
    """Check if a species string looks like a valid binomial (Genus epithet)."""
    parts = species.strip().split()
    if len(parts) < 2:
        return False
    # Genus starts uppercase, epithet starts lowercase
    return parts[0][0].isupper() and parts[1][0].islower()


def _get_trait_fields(fieldnames):
    """Return trait fields from CSV header (excludes core/provenance/text fields).

    Only returns fields that contain actual trait data suitable for
    cross-paper conflict detection and outlier analysis. Excludes all
    metadata, provenance, free-text notes, and verification fields.
    """
    exclude = {
        # Core identification
        "doi", "paper_title", "paper_authors", "first_author", "paper_year",
        "paper_journal", "session_id", "species", "family", "subfamily",
        "genus", "processed_date",
        # Confidence and flags
        "extraction_confidence", "calibrated_confidence", "flag_for_review",
        # Source provenance
        "source_type", "pdf_source", "pdf_path", "pdf_filename", "pdf_url",
        "source_page", "source_context", "extraction_reasoning",
        "collection_locality", "country",
        # Taxonomy
        "accepted_name", "gbif_key", "taxonomy_note",
        # Audit and verification
        "audit_status", "audit_session", "audit_prior_values",
        "verification", "verification_notes",
        # Consensus (legacy)
        "consensus", "consensus_vote", "consensus_agreement",
        "extraction_trace_id",
        # Free-text notes fields (these differ per paper by design)
        "notes", "karyotype_notes", "chromosome_notes", "morphology_notes",
        "methodology_notes", "additional_notes", "scrub_notes",
    }
    # Also exclude any field ending in _notes (catch-all for project-specific notes)
    return [f for f in fieldnames if f and f not in exclude
            and not f.endswith("_notes")]


# ---------------------------------------------------------------------------
# Crossref lookup (same pattern as write_finds.py)
# ---------------------------------------------------------------------------

_CROSSREF_CACHE = {}


def _crossref_lookup(doi):
    """Fetch metadata for a single DOI from Crossref. Returns dict or None."""
    if doi in _CROSSREF_CACHE:
        return _CROSSREF_CACHE[doi]

    url = (f"https://api.crossref.org/works/"
           f"{urllib.request.quote(doi, safe='')}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "TraitTrawler/5.0 (mailto:coleoguy@gmail.com)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("message", {})

        year = None
        for date_field in ("published-print", "published-online",
                           "issued", "created"):
            parts = (msg.get(date_field, {}).get("date-parts") or [[]])[0]
            if parts and parts[0]:
                year = parts[0]
                break

        result = {"paper_year": year}
        _CROSSREF_CACHE[doi] = result
        return result
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError, KeyError):
        _CROSSREF_CACHE[doi] = None
        return None


# ---------------------------------------------------------------------------
# Tier 1 -- Auto-fixable (deterministic, fix in-place)
# ---------------------------------------------------------------------------

def tier1_fix_taxonomy(row, project_root):
    """Fix missing family/genus when species is a valid binomial.

    Calls taxonomy_resolver.py as a subprocess to look up higher taxonomy.
    Returns True if any field was fixed.
    """
    species = (row.get("species") or "").strip()
    family = (row.get("family") or "").strip()
    genus = (row.get("genus") or "").strip()

    if (family and genus) or not species or not _is_valid_binomial(species):
        return False

    cache_path = os.path.join(project_root, "state", "taxonomy_cache.json")
    config_path = os.path.join(project_root, "collector_config.yaml")
    kingdom = "Animalia"
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        kingdom = config.get("kingdom", "Animalia")
    except (ImportError, FileNotFoundError):
        pass

    cmd = [
        sys.executable,
        os.path.join(project_root, "scripts", "taxonomy_resolver.py"),
        "--species", species,
        "--cache", cache_path,
        "--kingdom", kingdom,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=30)
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        for r in data.get("results", []):
            if r.get("query", "").strip() == species:
                fixed = False
                if not family and r.get("family"):
                    row["family"] = r["family"]
                    fixed = True
                if not genus and r.get("genus"):
                    row["genus"] = r["genus"]
                    fixed = True
                return fixed
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return False


def tier1_fix_paper_year(row):
    """Fix missing paper_year via Crossref lookup when DOI is present.

    Returns True if paper_year was fixed.
    """
    year = (row.get("paper_year") or "").strip()
    doi = (row.get("doi") or "").strip()
    if year or not doi:
        return False

    meta = _crossref_lookup(doi)
    if meta and meta.get("paper_year"):
        row["paper_year"] = str(meta["paper_year"])
        return True
    return False


def tier1_fix_pdf_path(row, project_root):
    """Fix missing pdf_path when PDF exists in pdfs/ directory.

    Matches by DOI substring or first_author+year in filenames.
    Returns True if pdf_path was fixed.
    """
    pdf_path = (row.get("pdf_path") or "").strip()
    if pdf_path:
        return False

    pdfs_dir = os.path.join(project_root, "pdfs")
    if not os.path.isdir(pdfs_dir):
        return False

    doi = (row.get("doi") or "").strip()

    try:
        pdf_files = [f for f in os.listdir(pdfs_dir) if f.endswith(".pdf")]
    except OSError:
        return False

    # Try matching by DOI (replace / with - for filename matching)
    if doi:
        doi_slug = doi.replace("/", "-").replace(".", "-")
        for fname in pdf_files:
            if doi_slug in fname or doi.split("/")[-1] in fname:
                row["pdf_path"] = os.path.join("pdfs", fname)
                return True

    # Try matching by first author + year
    first_author = (row.get("first_author") or "").strip()
    year = (row.get("paper_year") or "").strip()
    if first_author and year:
        pattern = f"{first_author}-{year}".lower()
        for fname in pdf_files:
            if pattern in fname.lower():
                row["pdf_path"] = os.path.join("pdfs", fname)
                return True

    return False


def run_tier1(rows, session_id, project_root):
    """Apply all Tier 1 auto-fixes to rows from the current session.

    Only touches rows matching the given session_id.
    Returns count of fixes applied.
    """
    fixes = 0
    for row in rows:
        if session_id and row.get("session_id") != session_id:
            continue
        if tier1_fix_taxonomy(row, project_root):
            fixes += 1
        if tier1_fix_paper_year(row):
            fixes += 1
        if tier1_fix_pdf_path(row, project_root):
            fixes += 1
    return fixes


# ---------------------------------------------------------------------------
# Tier 2 -- Audit queue
# ---------------------------------------------------------------------------

def _make_audit_entry(row, row_idx, reason, details):
    """Build a single audit queue entry dict."""
    return {
        "row_id": row_idx,
        "species": row.get("species", ""),
        "doi": row.get("doi", ""),
        "reason": reason,
        "details": details,
        "pdf_path": row.get("pdf_path", ""),
        "source_page": row.get("source_page", ""),
        "added_at": now_iso(),
    }


def tier2_low_confidence(rows, session_id, threshold=0.70):
    """Flag rows with extraction_confidence below threshold."""
    entries = []
    for idx, row in enumerate(rows):
        if session_id and row.get("session_id") != session_id:
            continue
        try:
            conf = float(row.get("extraction_confidence", 1.0))
        except (ValueError, TypeError):
            continue
        if conf < threshold:
            entries.append(_make_audit_entry(
                row, idx, "low_confidence",
                f"extraction_confidence={conf:.2f}"
            ))
    return entries


def tier2_statistical_outliers(rows):
    """Flag numeric trait fields where any value has Z > 3.0.

    Groups values by species to compute per-species mean/SD (Grubbs test
    approximation). Returns list of audit entries.
    """
    if not rows:
        return []

    fieldnames = list(rows[0].keys())
    trait_fields = _get_trait_fields(fieldnames)
    entries = []

    for field in trait_fields:
        # Group numeric values by species
        by_species = defaultdict(list)
        row_map = defaultdict(list)  # species -> [(row_idx, value)]
        for idx, row in enumerate(rows):
            sp = (row.get("species") or "").strip()
            val_str = (row.get(field) or "").strip()
            if not sp or not val_str:
                continue
            try:
                val = float(val_str)
                by_species[sp].append(val)
                row_map[sp].append((idx, val))
            except (ValueError, TypeError):
                continue

        # Check for outliers within each species group
        for sp, values in by_species.items():
            if len(values) < 3:
                continue
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            sd = math.sqrt(variance) if variance > 0 else 0
            if sd == 0:
                continue

            for row_idx, val in row_map[sp]:
                z = abs(val - mean) / sd
                if z > 3.0:
                    entries.append(_make_audit_entry(
                        rows[row_idx], row_idx, "statistical_outlier",
                        f"{field}={val}, group_mean={mean:.2f}, "
                        f"group_sd={sd:.2f}, z={z:.2f}"
                    ))
    return entries


def tier2_guide_drift(rows, session_id, project_root):
    """Flag records if guide.md has changed since extraction.

    Checks state/guide_md5.txt against current guide.md MD5. If they differ,
    all records from the current session may reflect outdated domain knowledge.
    """
    md5_path = os.path.join(project_root, "state", "guide_md5.txt")
    if not os.path.exists(md5_path):
        return []

    try:
        with open(md5_path, "r", encoding="utf-8") as f:
            stored_md5 = f.read().strip()
    except OSError:
        return []

    guide_path = os.path.join(project_root, "guide.md")
    if not os.path.exists(guide_path):
        return []

    try:
        with open(guide_path, "rb") as f:
            current_md5 = hashlib.md5(f.read()).hexdigest()
    except OSError:
        return []

    if current_md5 == stored_md5:
        return []

    # Guide has drifted -- flag all session records
    entries = []
    for idx, row in enumerate(rows):
        if session_id and row.get("session_id") != session_id:
            continue
        entries.append(_make_audit_entry(
            row, idx, "guide_drift",
            f"guide.md MD5 changed: {stored_md5[:8]}.. -> {current_md5[:8]}.."
        ))
    return entries


# ---------------------------------------------------------------------------
# Cross-paper conflict detection
# ---------------------------------------------------------------------------

# Numeric fields where small differences are expected (B-chromosomes,
# counting ambiguity, population-level variation).
NUMERIC_CONFLICT_TOLERANCE = {
    "diploid_2n_male": 2,
    "diploid_2n_female": 2,
    "haploid_n_male": 1,
    "haploid_n_female": 1,
    "n_autosomes": 1,
}


def _try_int(val):
    """Try to parse a value as integer. Returns None on failure."""
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def detect_cross_paper_conflicts(rows):
    """Detect same species + same trait field with different values from
    different DOIs.

    Uses three strategies to reduce false positives:
    - Tolerance-based filtering for numeric fields (±1-2 is B-chrom or counting)
    - Collapse multiple values per species to ONE entry (not O(n^2) pairs)
    - Mark multi-paper agreement as intraspecific variation (not error)

    Returns:
        tier2_entries: list of audit queue entries (one side low confidence)
        tier3_entries: list of human review entries (genuinely ambiguous)
        conflict_count: total number of conflicts found
    """
    if not rows:
        return [], [], 0

    fieldnames = list(rows[0].keys())
    trait_fields = _get_trait_fields(fieldnames)
    tier2 = []
    tier3 = []
    conflict_count = 0

    for field in trait_fields:
        tolerance = NUMERIC_CONFLICT_TOLERANCE.get(field, 0)

        # Group by species -> {doi: [(row_idx, value, confidence)]}
        by_species = defaultdict(lambda: defaultdict(list))
        for idx, row in enumerate(rows):
            sp = (row.get("species") or "").strip()
            doi = (row.get("doi") or "").strip()
            val = (row.get(field) or "").strip()
            if not sp or not doi or not val:
                continue
            try:
                conf = float(row.get("extraction_confidence", 0))
            except (ValueError, TypeError):
                conf = 0.0
            by_species[sp][doi].append((idx, val, conf))

        for sp, doi_groups in by_species.items():
            if len(doi_groups) < 2:
                continue

            # Collect unique values across all DOIs (best confidence per DOI)
            doi_best = {}  # doi -> (idx, val, conf)
            for doi, entries in doi_groups.items():
                best = max(entries, key=lambda x: x[2])
                doi_best[doi] = best

            # Get unique values
            unique_vals = {}  # val -> (doi, idx, conf)
            for doi, (idx, val, conf) in doi_best.items():
                if val not in unique_vals or conf > unique_vals[val][2]:
                    unique_vals[val] = (doi, idx, conf)

            if len(unique_vals) < 2:
                continue

            # Check if all differences are within tolerance
            vals_list = list(unique_vals.keys())
            if tolerance > 0:
                all_within_tolerance = True
                for i in range(len(vals_list)):
                    for j in range(i + 1, len(vals_list)):
                        v_i = _try_int(vals_list[i])
                        v_j = _try_int(vals_list[j])
                        if v_i is not None and v_j is not None:
                            if abs(v_i - v_j) > tolerance:
                                all_within_tolerance = False
                                break
                        else:
                            all_within_tolerance = False
                            break
                    if not all_within_tolerance:
                        break

                if all_within_tolerance:
                    # Small numeric difference — auto-note, don't queue
                    continue

            # Real conflict: collapse to ONE entry per species+field
            conflict_count += 1
            all_vals_str = ", ".join(sorted(unique_vals.keys()))
            all_dois = [f"{doi} (conf={conf:.2f})"
                        for val, (doi, idx, conf) in unique_vals.items()]
            notes = f"Values: {all_vals_str} from {'; '.join(all_dois)}"

            # Check confidence levels
            confs = [conf for _, _, conf in unique_vals.values()]
            min_conf = min(confs)
            max_conf = max(confs)

            # If 2+ independent papers report different values with high
            # confidence, this is likely real intraspecific variation
            high_conf_dois = sum(1 for c in confs if c > 0.80)
            if high_conf_dois >= 2 and len(unique_vals) >= 2:
                # Multi-paper high-confidence disagreement = likely real
                # variation. Only flag if the difference is very large
                # (suggesting extraction error vs real biology).
                numeric_vals = [_try_int(v) for v in vals_list]
                numeric_vals = [v for v in numeric_vals if v is not None]
                if len(numeric_vals) >= 2:
                    spread = max(numeric_vals) - min(numeric_vals)
                    median_val = sorted(numeric_vals)[len(numeric_vals) // 2]
                    # Large spread relative to median = likely error
                    if median_val > 0 and spread / median_val > 0.5:
                        # >50% spread — flag for human review (one entry)
                        first_val = vals_list[0]
                        first_doi, first_idx, first_conf = unique_vals[first_val]
                        tier3.append({
                            "row_id": first_idx,
                            "species": sp,
                            "doi": first_doi,
                            "trait_field": field,
                            "extracted_value": all_vals_str,
                            "alternative_value": "",
                            "reason": "cross_paper_conflict_large_spread",
                            "source_page": rows[first_idx].get("source_page", ""),
                            "auditor_notes": notes,
                            "status": "pending",
                        })
                    # else: moderate spread with multiple high-conf papers
                    # = intraspecific variation, no queue entry needed
                else:
                    # Non-numeric high-conf conflict (e.g., SCS strings)
                    first_val = vals_list[0]
                    first_doi, first_idx, first_conf = unique_vals[first_val]
                    tier3.append({
                        "row_id": first_idx,
                        "species": sp,
                        "doi": first_doi,
                        "trait_field": field,
                        "extracted_value": all_vals_str,
                        "alternative_value": "",
                        "reason": "cross_paper_conflict_both_high_conf",
                        "source_page": rows[first_idx].get("source_page", ""),
                        "auditor_notes": notes,
                        "status": "pending",
                    })
            elif min_conf <= 0.80:
                # One side has low confidence — audit queue (not human)
                low_val = min(unique_vals.keys(),
                              key=lambda v: unique_vals[v][2])
                low_doi, low_idx, low_conf = unique_vals[low_val]
                tier2.append(_make_audit_entry(
                    rows[low_idx], low_idx,
                    "cross_paper_conflict", notes
                ))

    return tier2, tier3, conflict_count


# ---------------------------------------------------------------------------
# Tier 3 -- Human review queue
# ---------------------------------------------------------------------------

def tier3_ambiguous_verification(rows, session_id):
    """Flag records where the Auditor marked verification as 'ambiguous'."""
    entries = []
    for idx, row in enumerate(rows):
        if session_id and row.get("session_id") != session_id:
            continue
        verification = (row.get("verification") or "").strip().lower()
        if verification == "ambiguous":
            entries.append({
                "row_id": idx,
                "species": row.get("species", ""),
                "doi": row.get("doi", ""),
                "trait_field": "",
                "extracted_value": "",
                "alternative_value": "",
                "reason": "ambiguous_verification",
                "source_page": row.get("source_page", ""),
                "auditor_notes": row.get("notes", ""),
                "status": "pending",
            })
    return entries


def append_audit_queue(project_root, entries):
    """Append entries to state/audit_queue.json, skipping duplicates."""
    if not entries:
        return 0
    path = os.path.join(project_root, "state", "audit_queue.json")
    with FileLock(path):
        queue = safe_read_json(path, default=[])
        existing_keys = set()
        for item in queue:
            key = (str(item.get("row_id", "")), item.get("reason", ""))
            existing_keys.add(key)
        added = 0
        for entry in entries:
            key = (str(entry.get("row_id", "")), entry.get("reason", ""))
            if key not in existing_keys:
                queue.append(entry)
                existing_keys.add(key)
                added += 1
        safe_write_json(path, queue)
    return added


def append_human_review_queue(project_root, entries):
    """Append entries to state/human_review_queue.csv, skipping duplicates."""
    if not entries:
        return 0
    path = os.path.join(project_root, "state", "human_review_queue.csv")
    fieldnames = [
        "row_id", "species", "doi", "trait_field", "extracted_value",
        "alternative_value", "reason", "source_page", "auditor_notes",
        "status",
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Load existing keys for dedup
    existing_keys = set()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (
                        row.get("species", ""),
                        row.get("trait_field", ""),
                        row.get("extracted_value", ""),
                        row.get("alternative_value", ""),
                    )
                    existing_keys.add(key)
        except (OSError, csv.Error):
            pass

    # Append only new entries
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    added = 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for entry in entries:
            key = (
                entry.get("species", ""),
                entry.get("trait_field", ""),
                entry.get("extracted_value", ""),
                entry.get("alternative_value", ""),
            )
            if key not in existing_keys:
                writer.writerow(entry)
                existing_keys.add(key)
                added += 1
    return added


# ---------------------------------------------------------------------------
# Coverage tracking (calls coverage_tracker.py)
# ---------------------------------------------------------------------------

def compute_coverage(project_root):
    """Compute coverage stats using coverage_tracker.py via subprocess.

    Falls back to a basic count if the subprocess fails.
    """
    cmd = [
        sys.executable,
        os.path.join(project_root, "scripts", "coverage_tracker.py"),
        "--project-root", project_root,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=60)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            s_obs = data.get("s_obs", 0)
            chao1 = data.get("chao1", 0)
            completeness = data.get("completeness", 0.0)
            if not completeness and chao1 > 0:
                completeness = round(s_obs / chao1, 3)
            return {
                "s_obs": s_obs,
                "chao1": chao1,
                "completeness": completeness,
            }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass

    # Fallback: read state/coverage_tracker.json if it exists
    ct_path = os.path.join(project_root, "state", "coverage_tracker.json")
    ct = safe_read_json(ct_path, default={})
    if ct:
        s_obs = ct.get("s_obs", 0)
        chao1 = ct.get("chao1", 0)
        completeness = ct.get("completeness", 0.0)
        if not completeness and chao1 > 0:
            completeness = round(s_obs / chao1, 3)
        return {"s_obs": s_obs, "chao1": chao1, "completeness": completeness}

    # Last resort: basic species count from results.csv
    csv_path = os.path.join(project_root, "results.csv")
    rows = safe_read_csv(csv_path)
    species = set(r.get("species", "").strip() for r in rows
                  if r.get("species", "").strip())
    return {"s_obs": len(species), "chao1": 0, "completeness": 0.0}


# ---------------------------------------------------------------------------
# Auto-calibration trigger
# ---------------------------------------------------------------------------

def maybe_trigger_calibration(project_root):
    """Run calibration.py if >= 20 records since last calibration."""
    meta_path = os.path.join(project_root, "state", "calibration_meta.json")
    meta = safe_read_json(meta_path, default={})
    records_since = meta.get("records_since_last_calibration", 0)

    if records_since < 20:
        return

    cmd = [
        sys.executable,
        os.path.join(project_root, "scripts", "calibration.py"),
        "--project-root", project_root,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # Reset counter on success
        meta["records_since_last_calibration"] = 0
        meta["last_calibration"] = now_iso()
        safe_write_json(meta_path, meta)
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"WARNING: Auto-calibration failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_inline_qc(project_root, session_id):
    """Execute the full inline QC pipeline.

    Steps:
      1. Read results.csv
      2. Tier 1: auto-fix deterministic issues (rewrite CSV if changed)
      3. Tier 2: build audit queue entries
      4. Cross-paper conflict detection (routes to Tier 2 or Tier 3)
      5. Tier 3: build human review queue entries
      6. Persist audit and human review queues
      7. Coverage tracking
      8. Auto-calibration trigger
      9. Emit JSON summary to stdout

    Returns:
        dict: The summary object.
    """
    csv_path = os.path.join(project_root, "results.csv")
    rows = safe_read_csv(csv_path)

    if not rows:
        summary = {
            "records_checked": 0,
            "tier1_auto_fixed": 0,
            "tier2_audit_queue": 0,
            "tier3_human_queue": 0,
            "cross_paper_conflicts": 0,
            "coverage": {"s_obs": 0, "chao1": 0, "completeness": 0.0},
        }
        json.dump(summary, sys.stdout, indent=2)
        print()
        return summary

    fieldnames = list(rows[0].keys())

    # -- Tier 1: Auto-fix ------------------------------------------------
    tier1_count = run_tier1(rows, session_id, project_root)

    if tier1_count > 0:
        # Rewrite results.csv atomically with the fixes applied
        atomic_rewrite_csv(csv_path, rows, fieldnames)

    # -- Tier 2: Audit queue ---------------------------------------------
    audit_entries = []
    audit_entries.extend(tier2_low_confidence(rows, session_id))
    audit_entries.extend(tier2_statistical_outliers(rows))
    audit_entries.extend(tier2_guide_drift(rows, session_id, project_root))

    # -- Cross-paper conflicts -------------------------------------------
    conflict_t2, conflict_t3, conflict_count = \
        detect_cross_paper_conflicts(rows)
    audit_entries.extend(conflict_t2)

    # -- Tier 3: Human review queue --------------------------------------
    human_entries = list(conflict_t3)
    human_entries.extend(tier3_ambiguous_verification(rows, session_id))

    # -- Persist queues --------------------------------------------------
    append_audit_queue(project_root, audit_entries)
    append_human_review_queue(project_root, human_entries)

    # -- Coverage tracking -----------------------------------------------
    coverage = compute_coverage(project_root)

    # -- Auto-calibration trigger ----------------------------------------
    maybe_trigger_calibration(project_root)

    # -- Summary ---------------------------------------------------------
    summary = {
        "records_checked": len(rows),
        "tier1_auto_fixed": tier1_count,
        "tier2_audit_queue": len(audit_entries),
        "tier3_human_queue": len(human_entries),
        "cross_paper_conflicts": conflict_count,
        "coverage": coverage,
    }

    json.dump(summary, sys.stdout, indent=2)
    print()
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def deduplicate_queues(project_root):
    """One-time deduplication of existing audit and human review queues."""
    # Audit queue
    audit_path = os.path.join(project_root, "state", "audit_queue.json")
    if os.path.exists(audit_path):
        with FileLock(audit_path):
            queue = safe_read_json(audit_path, default=[])
            seen = set()
            deduped = []
            for item in queue:
                key = (str(item.get("row_id", "")), item.get("reason", ""))
                if key not in seen:
                    deduped.append(item)
                    seen.add(key)
            removed = len(queue) - len(deduped)
            safe_write_json(audit_path, deduped)
            print(f"Audit queue: {len(queue)} -> {len(deduped)} "
                  f"({removed} duplicates removed)", file=sys.stderr)

    # Human review queue
    hr_path = os.path.join(project_root, "state", "human_review_queue.csv")
    if os.path.exists(hr_path):
        fieldnames = [
            "row_id", "species", "doi", "trait_field", "extracted_value",
            "alternative_value", "reason", "source_page", "auditor_notes",
            "status",
        ]
        rows = []
        try:
            with open(hr_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
        except (OSError, csv.Error):
            return

        seen = set()
        deduped = []
        for row in rows:
            key = (
                row.get("species", ""),
                row.get("trait_field", ""),
                row.get("extracted_value", ""),
                row.get("alternative_value", ""),
            )
            if key not in seen:
                deduped.append(row)
                seen.add(key)

        removed = len(rows) - len(deduped)
        tmp = hr_path + ".dedup.tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(deduped)
        os.replace(tmp, hr_path)
        print(f"Human review queue: {len(rows)} -> {len(deduped)} "
              f"({removed} duplicates removed)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Post-write inline QC pipeline for TraitTrawler v5"
    )
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--session-id", default="",
                        help="Session identifier (only QC rows from this "
                             "session for Tier 1 fixes and session-scoped "
                             "checks)")
    parser.add_argument("--deduplicate", action="store_true",
                        help="Deduplicate existing audit and human review "
                             "queues, then exit")
    args = parser.parse_args()

    if args.deduplicate:
        deduplicate_queues(args.project_root)
        return

    run_inline_qc(args.project_root, args.session_id)


if __name__ == "__main__":
    main()
