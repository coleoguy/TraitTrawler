#!/usr/bin/env python3
"""Bootstrap a v6 project from an existing curated dataset.

Ingests a CSV of human-curated trait records (optionally with paired
PDFs), canonicalizes species via GBIF, hashes any paired PDFs into
manifest.sqlite, writes imported rows as ledger entries with
`source_type: "human_curated_bootstrap"` and
`dwc_identificationVerificationStatus: "ValidatedByHuman"`, and emits
exemplars for the Extractor plus derived hooks for user approval.

Inputs:
  --root        project root
  --csv         curated CSV file
  --pdfs        optional directory of paired PDFs
  --schema      optional path to schema.json (else uses the minimal
                schema_proposed if it exists, else infers columns from CSV)
  --strict      fail hard on any unresolved GBIF name (default: mark
                taxonomy_status='unresolved' and continue)

Outputs (under state/bootstrap/):
  imported.parquet      (or imported.jsonl if pyarrow missing)
  exemplars.jsonl       (k-means representative rows; fallback: random)
  conflicts.jsonl       (rows that collided on the composite key)
  rejects.csv           (rows dropped for missing required fields)
  manifest.json         (sha256 of input CSV + column provenance)

Also appends to state/ledger.jsonl and state/manifest.sqlite.

This script is conservative: on any uncertainty it flags for user
review rather than silently accepting or rejecting.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_row_uid(row: dict) -> str:
    """Deterministic row key: SHA256(doi ‖ species ‖ trait ‖ value)."""
    key = "|".join([
        str(row.get("doi") or ""),
        str(row.get("canonical_species") or row.get("species") or ""),
        str(row.get("trait_key") or ""),
        str(row.get("trait_value") or ""),
    ]).lower()
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ------------------------------------------------------------------
# GBIF species matching
# ------------------------------------------------------------------


def resolve_species(name: str, cache: dict) -> dict:
    """Cached GBIF lookup; falls back to a local 'unresolved' marker on
    network failure so bootstrap never hangs on a dead internet."""
    if not name:
        return {"status": "unresolved", "canonical_name": None, "gbif_key": None}
    if name in cache:
        return cache[name]
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    try:
        from taxonomy_resolver import resolve as _resolve  # type: ignore
    except ImportError:
        cache[name] = {"status": "unresolved", "canonical_name": name}
        return cache[name]
    try:
        r = _resolve(name, None)
    except Exception:
        r = {"status": "unresolved", "canonical_name": name}
    cache[name] = r
    return r


# ------------------------------------------------------------------
# Exemplar selection
# ------------------------------------------------------------------


def select_exemplars(rows: list[dict], k: int = 50, seed: int = 42) -> list[dict]:
    """Choose k representative rows.

    Ideal: k-means on embeddings of (verbatim_quote, notation).
    Without an embedding service here, we approximate with:
      - Group rows by (notation_style, is_compilation, trait_key discretized).
      - From each group, pick up to ceil(k / n_groups) rows at random.
      - Fill the remainder with random rows if under k.

    This produces stratified coverage over the most important axes
    without needing an external embedding model. The design brief
    recommends real embeddings in a follow-up PR.
    """
    rng = random.Random(seed)
    if len(rows) <= k:
        return list(rows)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (
            r.get("notation_style") or "unknown",
            bool(r.get("is_compilation")),
            r.get("trait_key") or "",
        )
        groups[key].append(r)
    per = max(1, k // max(1, len(groups)))
    out: list[dict] = []
    for grp in groups.values():
        sample = grp if len(grp) <= per else rng.sample(grp, per)
        out.extend(sample)
    if len(out) < k:
        remaining = [r for r in rows if r not in out]
        rng.shuffle(remaining)
        out.extend(remaining[: k - len(out)])
    return out[:k]


# ------------------------------------------------------------------
# PDF pairing
# ------------------------------------------------------------------


def index_pdf_dir(pdf_dir: Path | None) -> dict[str, str]:
    """Build a { doi-or-hint-key: sha256 } map by hashing every PDF
    in the directory. Users typically name PDFs with DOI or first-
    author/year — we hash everything and let the caller resolve."""
    idx: dict[str, str] = {}
    if not pdf_dir or not pdf_dir.exists():
        return idx
    for p in sorted(pdf_dir.rglob("*.pdf")):
        sha = sha256_file(p)
        idx[sha] = str(p)
        # also index by filename stem (crude doi hint)
        idx[p.stem.lower()] = sha
    return idx


# ------------------------------------------------------------------
# Auxiliary-file routing: suspect records + papers needed
# ------------------------------------------------------------------


def _route_suspect_csv(path: Path, root: Path, column_map: dict[str, str],
                       delimiter: str, encoding: str, dry_run: bool) -> int:
    """Load a 'suspect records' CSV into state/review_queue.jsonl.

    Each row becomes a pending review-queue item with resolution_state
    pending so phase 6 can work through them later.
    """
    queue_path = root / "state" / "review_queue.jsonl"
    import uuid as _uuid
    n = 0
    mode = "a" if queue_path.exists() else "w"
    if dry_run:
        # Count rows without writing
        with path.open("r", encoding=encoding, errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            return sum(1 for _ in reader)
    with path.open("r", encoding=encoding, errors="replace", newline="") as f, \
         queue_path.open(mode) as q:
        reader = csv.DictReader(f, delimiter=delimiter)
        for raw in reader:
            if column_map:
                for k, v in list(raw.items()):
                    if k in column_map:
                        raw[column_map[k]] = v
            item = {
                "review_id": f"rv_boot_{_uuid.uuid4().hex[:10]}",
                "created_utc": iso(),
                "source": "bootstrap_suspect_csv",
                "source_path": str(path),
                "row": raw,
                "failure_reasons": [raw.get("reason") or "flagged by curator"],
                "verbatim_quote": raw.get("verbatim_quote") or raw.get("quote"),
                "page": raw.get("page"),
                "sha256": raw.get("sha256"),
                "resolution_state": "pending",
                "resolution": None,
                "resolved_by": None,
                "resolved_utc": None,
            }
            q.write(json.dumps(item) + "\n")
            n += 1
    return n


def _route_papers_needed(path: Path, root: Path, dry_run: bool) -> int:
    """Parse a 'papers needed' list (CSV, .bib, .ris, or newline-delimited)
    and append entries to candidates.jsonl.
    """
    candidates_path = root / "candidates.jsonl"
    import uuid as _uuid
    ext = path.suffix.lower()
    records: list[dict] = []

    if ext in (".csv", ".tsv", ".tab"):
        # Treat as CSV; look for doi / title / year / author columns
        try:
            from migration_preflight import sniff_csv as _sniff_csv  # type: ignore
            sniff = _sniff_csv(path)
            delimiter = sniff["delimiter"]
            encoding = sniff["encoding"]
        except Exception:
            delimiter = ","
            encoding = "utf-8"
        with path.open("r", encoding=encoding, errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for raw in reader:
                records.append({
                    "doi": (raw.get("doi") or raw.get("DOI") or "").strip() or None,
                    "title": (raw.get("title") or raw.get("paper_title") or "").strip() or None,
                    "first_author": (raw.get("first_author") or raw.get("author") or "").strip() or None,
                    "year": raw.get("year") or None,
                })
    elif ext in (".bib", ".ris"):
        # Extract DOI and title lines crudely
        text = path.read_text(errors="replace")
        rec: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("%"):
                if rec:
                    records.append(dict(rec))
                    rec = {}
                continue
            # BibTeX-ish
            m = re.match(r"^(\w+)\s*=\s*\{?([^}]*)\}?,?$", line)
            if m:
                key = m.group(1).lower()
                val = m.group(2).strip("{},\"")
                if key in ("doi", "title", "author", "year"):
                    rec[key] = val
            # RIS
            m2 = re.match(r"^([A-Z]{2})\s*-\s*(.+)$", line)
            if m2:
                k2, v2 = m2.group(1), m2.group(2)
                if k2 == "DO":
                    rec["doi"] = v2
                elif k2 in ("TI", "T1"):
                    rec["title"] = v2
                elif k2 == "AU":
                    rec.setdefault("first_author", v2)
                elif k2 == "PY":
                    rec["year"] = v2
        if rec:
            records.append(dict(rec))
    else:
        # Newline-delimited — one DOI or title per line
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if re.match(r"^10\.\d{4,}/", line):
                records.append({"doi": line, "title": None})
            else:
                records.append({"doi": None, "title": line})

    if dry_run:
        return len(records)

    n = 0
    with candidates_path.open("a") as f:
        for rec in records:
            cand = {
                "candidate_id": f"cand_boot_{_uuid.uuid4().hex[:10]}",
                "source_api": "bootstrap_papers_needed",
                "doi": rec.get("doi"),
                "title": rec.get("title"),
                "first_author": rec.get("first_author"),
                "year": rec.get("year"),
                "triage_priority": 0.8,
                "phase": "bootstrap",
                "fetch_hint": "doi" if rec.get("doi") else "title",
                "imported_utc": iso(),
            }
            f.write(json.dumps(cand) + "\n")
            n += 1
    return n


# ------------------------------------------------------------------
# Migration report
# ------------------------------------------------------------------


def _render_migration_report(*, root: Path, csv_path: Path,
                              imported: list[dict], stats: Counter,
                              taxonomy_counter: Counter,
                              pairing_strategy_counter: Counter,
                              orphan_shas: list[str],
                              suspect_imported: int,
                              papers_needed_added: int,
                              dry_run: bool) -> str:
    paired = sum(1 for r in imported if r.get("sha256"))
    unpaired = len(imported) - paired
    lines = [
        f"# Migration Report {'(DRY RUN)' if dry_run else ''}",
        "",
        f"- Source CSV: `{csv_path}`",
        f"- Project root: `{root}`",
        f"- Mode: {'dry-run (no ledger writes)' if dry_run else 'committed'}",
        "",
        "## Rows",
        f"- Imported: **{len(imported)}**",
        f"- Rejected (no species): {stats.get('rejected_no_species', 0)}",
        f"- Rejected (unresolved GBIF in --strict): {stats.get('rejected_unresolved_species', 0)}",
        f"- Conflicts (duplicate composite key in input): {stats.get('conflicts', 0)}",
        "",
        "## Taxonomy",
    ]
    for status, n in taxonomy_counter.most_common():
        lines.append(f"- {status}: {n}")

    lines += [
        "",
        "## PDF Pairing",
        f"- Rows paired to a PDF: **{paired}**",
        f"- Rows without a PDF: **{unpaired}**",
        f"- Orphan PDFs (on disk but not paired to any row): **{len(orphan_shas)}**",
        "",
        "### Pairing strategies used",
    ]
    for strat, n in pairing_strategy_counter.most_common():
        lines.append(f"- {strat}: {n}")

    lines += [
        "",
        "## Auxiliary files",
        f"- Suspect-records rows loaded into review queue: **{suspect_imported}**",
        f"- Papers-needed entries added to candidates.jsonl: **{papers_needed_added}**",
        "",
        "## What you should do next",
    ]
    if unpaired > 0:
        lines.append(
            f"- {unpaired} rows have no PDF linked. They are still in the "
            f"ledger as ValidatedByHuman ground truth, but extractor cannot "
            f"verify grounding. Decide: supply PDFs via `papers_needed` to "
            f"fetch them, or accept the rows as compilation-style records."
        )
    if orphan_shas:
        lines.append(
            f"- {len(orphan_shas)} PDFs exist on disk but did not pair to "
            f"any row. Review `state/bootstrap/pairing_report.json`'s "
            f"`orphan_pdfs_sample` list; these may be papers you fetched "
            f"but did not yet curate, or papers that should have matched "
            f"but did not (typos, aliases)."
        )
    if taxonomy_counter.get("fuzzy_matched", 0) > 0:
        lines.append(
            f"- {taxonomy_counter['fuzzy_matched']} species names were "
            f"fuzzy-matched by GBIF. Spot-check `state/bootstrap/imported.jsonl` "
            f"for any you disagree with and edit the canonical_species field."
        )
    if stats.get("conflicts", 0) > 0:
        lines.append(
            f"- {stats['conflicts']} rows had duplicate (doi, species, trait, value) "
            f"composite keys. Review `state/bootstrap/conflicts.jsonl` and "
            f"merge or delete as appropriate."
        )
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--pdfs", type=Path, default=None)
    ap.add_argument("--schema", type=Path, default=None)
    ap.add_argument("--exemplars-k", type=int, default=50)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--skip-gbif", action="store_true",
                    help="Skip GBIF lookups (faster for testing).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Produce reports but do not write ledger entries, "
                         "exemplars, or manifest rows.")
    ap.add_argument("--column-map", type=Path, default=None,
                    help="JSON file {user_col: canonical_col} to apply to CSV headers.")
    ap.add_argument("--pairing-report", type=Path, default=None,
                    help="Path to a pair_pdfs.py report to trust for PDF linkage.")
    ap.add_argument("--suspect-csv", type=Path, default=None,
                    help="Auxiliary 'suspect records' CSV to route to review_queue.jsonl.")
    ap.add_argument("--papers-needed", type=Path, default=None,
                    help="List of needed papers (CSV or newline-delimited DOIs/titles) "
                         "to add to candidates.jsonl.")
    ap.add_argument("--delimiter", default=None,
                    help="CSV delimiter; auto-detected if omitted.")
    ap.add_argument("--encoding", default="utf-8")
    ap.add_argument("--gbif-workers", type=int, default=8,
                    help="Parallel threads for GBIF species-match lookups (default 8). "
                         "GBIF is IO-bound HTTP, so threading gives ~8x speedup on the "
                         "first pass. All responses are cached so re-runs are free.")
    args = ap.parse_args()

    root = args.root.resolve()
    bootstrap_dir = root / "state" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    rejects_path = bootstrap_dir / "rejects.csv"
    conflicts_path = bootstrap_dir / "conflicts.jsonl"
    imported_path = bootstrap_dir / "imported.jsonl"
    exemplars_path = bootstrap_dir / "exemplars.jsonl"
    manifest_json = bootstrap_dir / "manifest.json"
    migration_report_path = bootstrap_dir / "migration_report.md"

    # Load schema if provided (else we infer column presence)
    schema_cols: set[str] = set()
    if args.schema and args.schema.exists():
        schema = json.loads(args.schema.read_text())
        schema_cols = set(schema.get("columns", {}).keys())

    # Hash the input CSV for reproducibility
    csv_sha = sha256_file(args.csv)

    # Load column mapping if provided
    column_map: dict[str, str] = {}
    if args.column_map and args.column_map.exists():
        column_map = json.loads(args.column_map.read_text())

    # Load pairing report if provided (preferred over crude stem matching)
    pairing_lookup: dict[int, dict] = {}
    if args.pairing_report and args.pairing_report.exists():
        p_report = json.loads(args.pairing_report.read_text())
        for r in p_report.get("per_row", []):
            pairing_lookup[r["row_index"]] = r

    # Index any paired PDFs (used only as fallback if no pairing_report)
    pdf_idx = index_pdf_dir(args.pdfs)
    if pdf_idx and not args.dry_run:
        # Register each unique PDF in manifest.sqlite
        db = root / "state" / "manifest.sqlite"
        con = sqlite3.connect(db)
        try:
            seen_shas = set()
            for key, val in pdf_idx.items():
                if len(key) == 64 and all(c in "0123456789abcdef" for c in key):
                    sha = key
                    path_s = val
                else:
                    continue
                if sha in seen_shas:
                    continue
                seen_shas.add(sha)
                existing = con.execute(
                    "SELECT 1 FROM pdfs WHERE sha256 = ?", (sha,)
                ).fetchone()
                if existing:
                    continue
                p = Path(path_s)
                con.execute(
                    """INSERT INTO pdfs (sha256, canonical_path, original_filename,
                                          bytes, added_utc, fetch_status)
                       VALUES (?, ?, ?, ?, ?, 'bootstrap')""",
                    (sha, str(p), p.name, p.stat().st_size, iso()),
                )
            con.commit()
        finally:
            con.close()

    # Process rows
    gbif_cache: dict = {}
    imported: list[dict] = []
    seen_uids: dict[str, dict] = {}
    stats = Counter()
    taxonomy_counter = Counter()
    pairing_strategy_counter: Counter = Counter()

    # Detect delimiter if the user didn't specify
    delimiter = args.delimiter or ","
    if not args.delimiter:
        try:
            from migration_preflight import sniff_csv as _sniff_csv  # type: ignore
            sniff = _sniff_csv(args.csv)
            delimiter = sniff["delimiter"]
        except Exception:
            pass

    # Pre-warm GBIF cache in parallel on unique species names.
    # For 4,000 rows with ~2,500 distinct species, this turns an 8-min
    # serial pass into a ~1-min parallel pass. Skipped if --skip-gbif.
    if not args.skip_gbif:
        unique_species: set[str] = set()
        with args.csv.open("r", encoding=args.encoding, errors="replace",
                            newline="") as f:
            peek_reader = csv.DictReader(f, delimiter=delimiter)
            for raw in peek_reader:
                if column_map:
                    for k, v in list(raw.items()):
                        if k in column_map:
                            raw.setdefault(column_map[k], v)
                name = (raw.get("canonical_species") or raw.get("species")
                        or raw.get("species_name") or "").strip()
                if name:
                    unique_species.add(name)
        if unique_species:
            print(f"warming GBIF cache for {len(unique_species)} unique species "
                  f"(workers={args.gbif_workers})…", file=sys.stderr)
            def _resolve_one(name: str) -> tuple[str, dict]:
                return name, resolve_species(name, {})
            with ThreadPoolExecutor(max_workers=args.gbif_workers) as ex:
                futures = {ex.submit(_resolve_one, n): n for n in unique_species}
                for fut in as_completed(futures):
                    try:
                        name, result = fut.result()
                        gbif_cache[name] = result
                    except Exception as e:
                        n = futures[fut]
                        print(f"  WARN: GBIF lookup failed for {n}: {e}",
                              file=sys.stderr)
                        gbif_cache[n] = {"status": "unresolved",
                                          "canonical_name": n}

    with args.csv.open("r", encoding=args.encoding, errors="replace",
                        newline="") as f, \
         rejects_path.open("w", newline="") as rj, \
         conflicts_path.open("w") as cj:
        reader = csv.DictReader(f, delimiter=delimiter)
        rej_writer: csv.DictWriter | None = None

        for row_idx, raw in enumerate(reader):
            # Apply user-supplied column mapping so downstream code reads
            # canonical names. Keep originals around too.
            if column_map:
                aliased = {}
                for k, v in raw.items():
                    if k in column_map:
                        aliased[column_map[k]] = v
                    aliased[k] = v  # preserve original
                raw = aliased
            stats["total_rows"] += 1

            # Require at minimum: species + some trait value
            species = (raw.get("canonical_species") or raw.get("species")
                       or raw.get("species_name") or "").strip()
            if not species:
                stats["rejected_no_species"] += 1
                if rej_writer is None:
                    rej_writer = csv.DictWriter(rj, fieldnames=list(raw.keys())
                                                + ["rejection_reason"])
                    rej_writer.writeheader()
                rej_writer.writerow({**raw, "rejection_reason": "no_species"})
                continue

            # Canonicalize species
            if args.skip_gbif:
                tax = {"status": "resolved", "canonical_name": species,
                       "gbif_key": None}
            else:
                tax = resolve_species(species, gbif_cache)
            if tax.get("status") != "resolved" and args.strict:
                stats["rejected_unresolved_species"] += 1
                if rej_writer is None:
                    rej_writer = csv.DictWriter(rj, fieldnames=list(raw.keys())
                                                + ["rejection_reason"])
                    rej_writer.writeheader()
                rej_writer.writerow({**raw, "rejection_reason": "unresolved_species"})
                continue

            taxonomy_counter[tax.get("status", "unknown")] += 1

            # Attempt PDF pairing
            sha = None
            doi = (raw.get("doi") or "").strip()
            pairing_strategy = "UNPAIRED"
            pairing_confidence = 0.0

            if pairing_lookup:
                # Prefer the fuzzy-pairing report if given
                pp = pairing_lookup.get(row_idx)
                if pp and pp.get("sha256"):
                    sha = pp["sha256"]
                    pairing_strategy = pp.get("strategy", "UNKNOWN")
                    pairing_confidence = pp.get("confidence", 0.0)
            if not sha:
                # Fallback: crude stem-based matching
                pdf_filename = (raw.get("pdf_filename") or "").strip()
                pdf_path = (raw.get("pdf_path") or "").strip()
                if pdf_filename:
                    stem = Path(pdf_filename).stem.lower()
                    sha = pdf_idx.get(stem)
                    if sha:
                        pairing_strategy = "EXACT_STEM"
                        pairing_confidence = 1.0
                if not sha and pdf_path:
                    stem = Path(pdf_path).stem.lower()
                    sha = pdf_idx.get(stem)
                    if sha:
                        pairing_strategy = "EXACT_STEM"
                        pairing_confidence = 1.0
                if not sha and doi:
                    doi_safe = doi.replace("/", "_").lower()
                    sha = pdf_idx.get(doi_safe)
                    if sha:
                        pairing_strategy = "DOI_NORMALIZED"
                        pairing_confidence = 0.92
            pairing_strategy_counter[pairing_strategy] += 1

            # Build the imported row with standard provenance fields
            row = dict(raw)
            row["canonical_species"] = tax.get("canonical_name") or species
            if tax.get("gbif_key"):
                row["species_gbif_key"] = tax.get("gbif_key")
            row["taxonomy_status"] = (
                "fuzzy_matched" if tax.get("match_type") == "FUZZY"
                else tax.get("status", "unresolved")
            )
            row["source_type"] = "human_curated_bootstrap"
            row["dwc_basisOfRecord"] = "HumanObservation"
            row["dwc_identificationVerificationStatus"] = "ValidatedByHuman"
            row["dwc_recordedBy"] = raw.get("curator") or raw.get("recordedBy") or "human_curator"
            row["pav_curatedBy"] = raw.get("curator") or raw.get("pav_curatedBy")
            row["pav_createdBy"] = "TraitTrawler bootstrap v6.1"
            row["prov_wasDerivedFrom"] = sha or doi or None
            row["dcterms_created"] = iso()
            if sha:
                row["sha256"] = sha
                row["grounding_verified"] = True  # human curator did it
                row["pairing_strategy"] = pairing_strategy
                row["pairing_confidence"] = pairing_confidence
            row["trait_key"] = (raw.get("trait_key") or raw.get("trait")
                                or raw.get("trait_name") or "")
            row["trait_value"] = (raw.get("trait_value") or raw.get("value")
                                  or "")

            uid = canonical_row_uid(row)
            row["row_uid"] = uid

            # Composite-key dedup check against prior imported rows
            if uid in seen_uids:
                stats["conflicts"] += 1
                cj.write(json.dumps({
                    "row_uid": uid,
                    "first": seen_uids[uid],
                    "second": row,
                }) + "\n")
                continue
            seen_uids[uid] = row
            imported.append(row)
            stats["imported"] += 1

    # Write imported records (always — used by derive_hooks.py, even in dry-run)
    with imported_path.open("w") as f:
        for r in imported:
            f.write(json.dumps(r) + "\n")

    # Append ledger entries for each imported row (SKIPPED in dry-run)
    ledger_path = root / "state" / "ledger.jsonl"
    if not args.dry_run:
        with ledger_path.open("a") as f:
            for r in imported:
                f.write(json.dumps({
                    "ledger_id": f"ldg_boot_{r['row_uid']}",
                    "row_uid": r["row_uid"],
                    "source_type": "human_curated_bootstrap",
                    "sha256": r.get("sha256"),
                    "doi": r.get("doi"),
                    "canonical_species": r.get("canonical_species"),
                    "trait_key": r.get("trait_key"),
                    "trait_value": r.get("trait_value"),
                    "dwc_identificationVerificationStatus": "ValidatedByHuman",
                    "dwc_recordedBy": r.get("dwc_recordedBy"),
                    "pav_curatedBy": r.get("pav_curatedBy"),
                    "pairing_strategy": r.get("pairing_strategy"),
                    "pairing_confidence": r.get("pairing_confidence"),
                    "timestamp_utc": iso(),
                    "provenance": {
                        "bootstrap_csv_sha256": csv_sha,
                        "bootstrap_csv_path": str(args.csv),
                    },
                }) + "\n")

    # Exemplars
    exemplars = select_exemplars(imported, k=args.exemplars_k)
    with exemplars_path.open("w") as f:
        for r in exemplars:
            f.write(json.dumps({
                "row_uid": r["row_uid"],
                "canonical_species": r.get("canonical_species"),
                "trait_key": r.get("trait_key"),
                "trait_value": r.get("trait_value"),
                "verbatim_quote": r.get("verbatim_quote"),
                "notation_style": r.get("notation_style"),
                "is_compilation": r.get("is_compilation"),
            }) + "\n")

    # Auxiliary files — suspect records → review queue
    suspect_imported = 0
    if args.suspect_csv and args.suspect_csv.exists():
        suspect_imported = _route_suspect_csv(args.suspect_csv, root,
                                               column_map, delimiter,
                                               args.encoding, args.dry_run)

    # Auxiliary — papers needed → candidates.jsonl
    papers_needed_added = 0
    if args.papers_needed and args.papers_needed.exists():
        papers_needed_added = _route_papers_needed(args.papers_needed, root,
                                                    args.dry_run)

    # Orphan PDFs: PDFs that exist on disk but nothing in imported linked them.
    paired_shas = {r["sha256"] for r in imported if r.get("sha256")}
    orphan_shas: list[str] = []
    if pdf_idx:
        for key, val in pdf_idx.items():
            if len(key) == 64 and all(c in "0123456789abcdef" for c in key):
                if key not in paired_shas:
                    orphan_shas.append(key)

    # Manifest
    manifest_json.write_text(json.dumps({
        "csv_sha256": csv_sha,
        "csv_path": str(args.csv),
        "pdfs_dir": str(args.pdfs) if args.pdfs else None,
        "rows_imported": len(imported),
        "exemplars_k": len(exemplars),
        "taxonomy_status_counts": dict(taxonomy_counter),
        "pairing_strategies": dict(pairing_strategy_counter),
        "orphan_pdf_count": len(orphan_shas),
        "suspect_imported": suspect_imported,
        "papers_needed_added": papers_needed_added,
        "stats": dict(stats),
        "dry_run": args.dry_run,
        "bootstrap_utc": iso(),
    }, indent=2))

    # Migration report
    migration_report_path.write_text(_render_migration_report(
        root=root,
        csv_path=args.csv,
        imported=imported,
        stats=stats,
        taxonomy_counter=taxonomy_counter,
        pairing_strategy_counter=pairing_strategy_counter,
        orphan_shas=orphan_shas,
        suspect_imported=suspect_imported,
        papers_needed_added=papers_needed_added,
        dry_run=args.dry_run,
    ))

    # Summary to stdout (the Manager reads this)
    print(json.dumps({
        "dry_run": args.dry_run,
        "imported": len(imported),
        "paired_to_pdf": sum(1 for r in imported if r.get("sha256")),
        "unpaired_rows": sum(1 for r in imported if not r.get("sha256")),
        "orphan_pdfs": len(orphan_shas),
        "exemplars": len(exemplars),
        "rejected": stats["rejected_no_species"] + stats["rejected_unresolved_species"],
        "conflicts": stats["conflicts"],
        "taxonomy_status": dict(taxonomy_counter),
        "pairing_strategies": dict(pairing_strategy_counter),
        "suspect_records_added": suspect_imported,
        "papers_needed_added": papers_needed_added,
        "migration_report": str(migration_report_path),
        "bootstrap_dir": str(bootstrap_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
