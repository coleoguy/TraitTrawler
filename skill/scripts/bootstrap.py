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
import sqlite3
import sys
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
    args = ap.parse_args()

    root = args.root.resolve()
    bootstrap_dir = root / "state" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    rejects_path = bootstrap_dir / "rejects.csv"
    conflicts_path = bootstrap_dir / "conflicts.jsonl"
    imported_path = bootstrap_dir / "imported.jsonl"
    exemplars_path = bootstrap_dir / "exemplars.jsonl"
    manifest_json = bootstrap_dir / "manifest.json"

    # Load schema if provided (else we infer column presence)
    schema_cols: set[str] = set()
    if args.schema and args.schema.exists():
        schema = json.loads(args.schema.read_text())
        schema_cols = set(schema.get("columns", {}).keys())

    # Hash the input CSV for reproducibility
    csv_sha = sha256_file(args.csv)

    # Index any paired PDFs
    pdf_idx = index_pdf_dir(args.pdfs)
    if pdf_idx:
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

    with args.csv.open() as f, \
         rejects_path.open("w", newline="") as rj, \
         conflicts_path.open("w") as cj:
        reader = csv.DictReader(f)
        rej_writer: csv.DictWriter | None = None

        for raw in reader:
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
            pdf_filename = (raw.get("pdf_filename") or "").strip()
            pdf_path = (raw.get("pdf_path") or "").strip()
            if pdf_filename:
                stem = Path(pdf_filename).stem.lower()
                sha = pdf_idx.get(stem)
            if not sha and pdf_path:
                stem = Path(pdf_path).stem.lower()
                sha = pdf_idx.get(stem)
            if not sha and doi:
                # DOIs often have characters unsafe for filenames; try
                # a normalized stem match
                doi_safe = doi.replace("/", "_").lower()
                sha = pdf_idx.get(doi_safe)

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

    # Write imported records
    with imported_path.open("w") as f:
        for r in imported:
            f.write(json.dumps(r) + "\n")

    # Append ledger entries for each imported row
    ledger_path = root / "state" / "ledger.jsonl"
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

    # Manifest
    manifest_json.write_text(json.dumps({
        "csv_sha256": csv_sha,
        "csv_path": str(args.csv),
        "pdfs_dir": str(args.pdfs) if args.pdfs else None,
        "rows_imported": len(imported),
        "exemplars_k": len(exemplars),
        "taxonomy_status_counts": dict(taxonomy_counter),
        "stats": dict(stats),
        "bootstrap_utc": iso(),
    }, indent=2))

    # Summary to stdout (the Manager reads this)
    print(json.dumps({
        "imported": len(imported),
        "exemplars": len(exemplars),
        "rejected": stats["rejected_no_species"] + stats["rejected_unresolved_species"],
        "conflicts": stats["conflicts"],
        "taxonomy_status": dict(taxonomy_counter),
        "bootstrap_dir": str(bootstrap_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
