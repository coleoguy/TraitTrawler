#!/usr/bin/env python3
"""Migration pre-flight: scan a real-world data folder and propose a plan.

Heath (or any user) arrives with a messy folder: the main curated CSV
plus auxiliary files like "suspect records.csv", "papers needed.txt",
maybe adjudication logs, and a pdfs/ subdirectory with PDFs whose names
rarely match the CSV's filename column exactly.

This script:

  1. Walks the directory tree, classifies each file by type and
     likely role (main dataset, review queue, papers-needed, adjudication
     decisions, orphan).
  2. Sniffs CSV dialect and encoding (comma vs tab, UTF-8 vs Latin-1).
  3. Proposes column-name mappings against the canonical v6.1 schema
     using fuzzy matching against known aliases.
  4. Counts PDFs and flags obvious problems (zero-byte, unreadable).
  5. Writes state/bootstrap/migration_plan.json + migration_plan.md.
  6. Returns a summary the Manager shows the user for approval.

This is the FIRST script the bootstrap subagent runs. The user
approves/edits the proposed plan before anything is written to the
ledger.

Usage:
    python migration_preflight.py --root <project_root> --source <folder>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


# ------------------------------------------------------------------
# Canonical column aliases — INFRASTRUCTURE AND PROVENANCE ONLY
# ------------------------------------------------------------------
# These aliases are trait-agnostic: every project has a species, every
# project has a DOI or a source file or a page reference. No trait-
# specific aliases live here — those must come from the user-supplied
# column_map.json (which is typically populated interactively during
# the preflight dialogue, or merged in from state/trait_profile.md §11
# after the trait_learner has run).
# ------------------------------------------------------------------

ALIASES: dict[str, list[str]] = {
    "canonical_species": [
        "canonical_species", "species", "species_name", "sp", "sp_name",
        "speciesname", "taxon", "taxon_name", "binomial", "scientificname",
        "scientific_name", "organism",
    ],
    "doi": [
        "doi", "DOI", "paper_doi", "article_doi", "identifier", "id_doi",
    ],
    "pdf_filename": [
        "pdf_filename", "pdf_file", "pdf", "filename", "file", "paper_pdf",
        "pdf_name", "source_file",
    ],
    "pdf_path": [
        "pdf_path", "pdf_location", "file_path", "path",
    ],
    "first_author": [
        "first_author", "firstauthor", "author", "authors", "first", "auth",
    ],
    "year": [
        "year", "paper_year", "pub_year", "publication_year", "yr", "date",
    ],
    "trait_key": [
        "trait_key", "trait", "trait_name", "field", "character", "variable",
    ],
    "trait_value": [
        "trait_value", "value", "measurement", "result",
    ],
    "verbatim_quote": [
        "verbatim_quote", "quote", "source_context", "context", "evidence",
        "excerpt", "source_text",
    ],
    "page": [
        "page", "page_number", "pg", "page_num", "source_page",
    ],
    "notation_style": [
        "notation_style", "notation", "style", "format",
    ],
    "is_compilation": [
        "is_compilation", "compilation", "review_table", "from_review",
    ],
    "original_citation": [
        "original_citation", "orig_cite", "primary_source", "source",
    ],
    "title": [
        "title", "paper_title", "article_title",
    ],
    "curator": [
        "curator", "curatedby", "curated_by", "recordedby", "recorded_by",
    ],
}


def load_user_aliases(path: Path | None) -> dict[str, list[str]]:
    """Load project-specific trait column aliases supplied by the user.

    Format:
        {"canonical_column_name": ["alias1", "alias2", ...], ...}

    Used to merge in trait-specific aliases the user knows from their
    own data, without embedding those aliases in the core skill.
    """
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    out: dict[str, list[str]] = {}
    for canon, aliases in data.items():
        if isinstance(aliases, list):
            out[canon] = [str(a) for a in aliases]
        elif isinstance(aliases, str):
            out[canon] = [aliases]
    return out


# ------------------------------------------------------------------
# File classification
# ------------------------------------------------------------------

CSV_EXT = {".csv", ".tsv", ".tab", ".txt"}
PDF_EXT = {".pdf"}
AUX_EXT = {".bib", ".ris", ".json", ".jsonl", ".yaml", ".yml"}


def sniff_csv(path: Path, max_bytes: int = 16384) -> dict:
    """Detect encoding, delimiter, row count, and header."""
    raw = path.read_bytes()[:max_bytes]
    encoding = "utf-8"
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            raw.decode(enc)
            encoding = enc
            break
        except UnicodeDecodeError:
            continue
    text = raw.decode(encoding, errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4000])
        delimiter = dialect.delimiter
    except Exception:
        # Heuristic fallback
        if "\t" in text.split("\n", 1)[0]:
            delimiter = "\t"
        else:
            delimiter = ","
    # Count rows and get header
    with path.open("r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            header = []
        row_count = sum(1 for _ in reader)
    return {
        "encoding": encoding,
        "delimiter": delimiter,
        "header": header,
        "row_count": row_count,
    }


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def classify_filename(name: str) -> str:
    """Heuristic classification by filename patterns."""
    n = name.lower().replace("-", "_").replace(" ", "_")
    if any(k in n for k in ("suspect", "review", "flag", "pending",
                             "uncertain", "queue")):
        return "review_queue"
    if any(k in n for k in ("papers_needed", "wanted", "to_get", "to_fetch",
                             "needed", "wishlist", "fetch_list", "ill_list")):
        return "papers_needed"
    if any(k in n for k in ("adjudic", "resolution", "decided",
                             "dispute", "conflict_resolv")):
        return "adjudications"
    if any(k in n for k in ("result", "dataset", "data", "main", "hbdat",
                             "master", "curated", "records", "trait", "karyo")):
        return "main_dataset"
    if n.endswith(".bib") or n.endswith(".ris"):
        return "citation_list"
    return "unknown"


def map_columns(headers: list[str],
                user_aliases: dict[str, list[str]] | None = None
                ) -> tuple[dict[str, str], list[str]]:
    """Propose a column alias mapping.

    Merges the core infrastructure/provenance aliases with any user-
    supplied trait-specific aliases. Returns (mapping, unmapped) where:
      mapping: {user_column_name: canonical_name}
      unmapped: list of headers that did not map above threshold

    The unmapped list is the crucial signal — those are columns the
    bootstrap subagent should explicitly ask the user about rather
    than silently ignore.
    """
    mapping: dict[str, str] = {}
    unmapped: list[str] = []

    # Merge user aliases on top of core ALIASES
    merged = {canon: list(aliases) for canon, aliases in ALIASES.items()}
    if user_aliases:
        for canon, aliases in user_aliases.items():
            merged.setdefault(canon, []).extend(aliases)

    alias_to_canon: dict[str, str] = {}
    for canon, aliases in merged.items():
        for a in aliases:
            alias_to_canon[a.lower().replace("_", "").replace(" ", "")] = canon

    for h in headers:
        if not h:
            continue
        key = h.lower().replace("_", "").replace(" ", "").replace("-", "")
        if key in alias_to_canon:
            mapping[h] = alias_to_canon[key]
            continue
        best_score = 0.0
        best_canon = None
        for alias_key, canon in alias_to_canon.items():
            s = _sim(key, alias_key)
            if s > best_score:
                best_score = s
                best_canon = canon
        if best_score >= 0.85 and best_canon:
            mapping[h] = best_canon
        else:
            unmapped.append(h)
    return mapping, unmapped


# ------------------------------------------------------------------
# Main scan
# ------------------------------------------------------------------


def scan_directory(source: Path,
                    user_aliases: dict[str, list[str]] | None = None) -> dict:
    """Walk the tree, return a structured inventory."""
    files: list[dict] = []
    pdfs: list[dict] = []
    for p in sorted(source.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        rel = str(p.relative_to(source))
        size = p.stat().st_size
        if ext in PDF_EXT:
            pdfs.append({
                "path": rel, "size_bytes": size,
                "warn_empty": size == 0,
            })
            continue
        if ext in CSV_EXT or ext in AUX_EXT:
            kind = classify_filename(p.name)
            rec: dict = {"path": rel, "size_bytes": size, "kind": kind,
                         "extension": ext}
            if ext in CSV_EXT and size > 0:
                try:
                    sniff = sniff_csv(p)
                    rec["csv"] = sniff
                    mapping, unmapped = map_columns(sniff["header"], user_aliases)
                    rec["proposed_mapping"] = mapping
                    rec["unmapped_headers"] = unmapped
                except Exception as e:
                    rec["error"] = f"sniff failed: {e}"
            files.append(rec)
    return {"files": files, "pdfs": pdfs,
            "pdf_count": len(pdfs),
            "empty_pdf_count": sum(1 for p in pdfs if p["warn_empty"])}


def pick_main_dataset(files: list[dict]) -> dict | None:
    """Choose the most likely main dataset CSV.

    Strategy: among files classified 'main_dataset' or 'unknown', pick
    the one with the largest row_count. Break ties by file size.
    """
    candidates = [f for f in files if f.get("kind") in ("main_dataset", "unknown")
                  and "csv" in f]
    if not candidates:
        return None
    return max(candidates,
               key=lambda f: (f["csv"].get("row_count", 0), f["size_bytes"]))


def propose_plan(source: Path, inventory: dict) -> dict:
    """Turn an inventory into an actionable migration plan."""
    files = inventory["files"]
    pdfs = inventory["pdfs"]

    main = pick_main_dataset(files)
    roles: dict[str, list[str]] = {
        "main_dataset": [],
        "review_queue": [],
        "papers_needed": [],
        "adjudications": [],
        "citation_list": [],
        "unknown": [],
    }
    for f in files:
        kind = f.get("kind", "unknown")
        roles.setdefault(kind, []).append(f["path"])
    if main and main["path"] not in roles["main_dataset"]:
        # Promote unknown to main if it has the most rows
        if main["path"] in roles.get("unknown", []):
            roles["unknown"].remove(main["path"])
        roles["main_dataset"].append(main["path"])

    warnings: list[str] = []
    if inventory["empty_pdf_count"] > 0:
        warnings.append(f"{inventory['empty_pdf_count']} zero-byte PDFs")
    if len(roles["main_dataset"]) == 0:
        warnings.append("no main dataset CSV detected — bootstrap cannot proceed")
    if len(roles["main_dataset"]) > 1:
        warnings.append(
            f"multiple main-dataset candidates detected: {roles['main_dataset']}"
        )
    if main and main.get("unmapped_headers"):
        n = len(main["unmapped_headers"])
        warnings.append(
            f"{n} column(s) in main dataset could not be auto-mapped: "
            f"{main['unmapped_headers'][:6]}…"
        )

    plan = {
        "source_root": str(source),
        "pdf_count": inventory["pdf_count"],
        "csv_count": sum(1 for f in files if "csv" in f),
        "roles": roles,
        "main_dataset": main,
        "warnings": warnings,
        "all_files": files,
    }
    return plan


def render_plan_markdown(plan: dict) -> str:
    """Human-readable summary the Manager shows for approval."""
    lines: list[str] = [
        "# Migration Pre-flight Plan",
        "",
        f"- Source: `{plan['source_root']}`",
        f"- PDFs found: **{plan['pdf_count']}**",
        f"- CSV/TSV files: **{plan['csv_count']}**",
        "",
        "## Role assignments",
        "",
    ]
    for role, paths in plan["roles"].items():
        if not paths:
            continue
        lines.append(f"### {role} ({len(paths)})")
        for p in paths:
            lines.append(f"- `{p}`")
        lines.append("")

    main = plan.get("main_dataset")
    if main:
        lines += [
            "## Main dataset detail",
            "",
            f"- Path: `{main['path']}`",
            f"- Rows: {main['csv']['row_count']}",
            f"- Encoding: {main['csv']['encoding']}",
            f"- Delimiter: `{main['csv']['delimiter']!r}`",
            f"- Header: {main['csv']['header']}",
            "",
            "### Proposed column mapping",
            "",
            "| Your column | Canonical v6.1 column |",
            "|---|---|",
        ]
        for user_col, canon in sorted(main.get("proposed_mapping", {}).items()):
            lines.append(f"| `{user_col}` | `{canon}` |")
        lines.append("")
        if main.get("unmapped_headers"):
            lines += [
                "### Unmapped headers (need your input or will pass through)",
                "",
            ]
            for h in main["unmapped_headers"]:
                lines.append(f"- `{h}`")
            lines.append("")

    if plan["warnings"]:
        lines.append("## ⚠ Warnings")
        lines.append("")
        for w in plan["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    lines += [
        "## What happens when you approve",
        "",
        "1. `main_dataset` → imported by `bootstrap.py` into `state/ledger.jsonl` "
        "as `ValidatedByHuman` ground truth.",
        "2. `review_queue` → loaded into `state/review_queue.jsonl` with "
        "`resolution_state: pending` so phase 6 can work through them.",
        "3. `papers_needed` → converted to `candidates.jsonl` entries so the "
        "fetcher subagent can attempt retrieval in phase 4.",
        "4. `adjudications` → imported as pre-made adjudication records so "
        "the Adjudicator does not re-rule these.",
        "5. `citation_list` → parsed to extract DOIs/titles, added to "
        "`candidates.jsonl`.",
        "6. PDF pairing runs separately via `pair_pdfs.py` with confidence "
        "scoring; orphan PDFs are reported, not silently ignored.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True,
                    help="Project root (must already have state/ dir)")
    ap.add_argument("--source", type=Path, required=True,
                    help="Folder to scan for migration data")
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--user-aliases", type=Path, default=None,
                    help="Optional JSON of project-specific column aliases "
                         "{canonical_name: [alias1, alias2, ...]}. Merged with "
                         "the built-in infrastructure aliases. Use this to teach "
                         "preflight about YOUR trait column names without "
                         "polluting the core skill.")
    args = ap.parse_args()

    root = args.root.resolve()
    source = args.source.resolve()
    if not source.exists():
        print(f"source not found: {source}", file=sys.stderr)
        return 2

    bootstrap_dir = root / "state" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    out_md = args.out_md or (bootstrap_dir / "migration_plan.md")
    out_json = args.out_json or (bootstrap_dir / "migration_plan.json")

    user_aliases = load_user_aliases(args.user_aliases)
    inventory = scan_directory(source, user_aliases)
    plan = propose_plan(source, inventory)
    plan["user_aliases_path"] = str(args.user_aliases) if args.user_aliases else None
    plan["user_aliases_loaded"] = list(user_aliases.keys())

    out_json.write_text(json.dumps(plan, indent=2, default=str))
    out_md.write_text(render_plan_markdown(plan))

    summary = {
        "pdf_count": plan["pdf_count"],
        "csv_count": plan["csv_count"],
        "main_dataset": plan["main_dataset"]["path"] if plan["main_dataset"] else None,
        "role_counts": {k: len(v) for k, v in plan["roles"].items() if v},
        "warnings": plan["warnings"],
        "plan_md": str(out_md),
        "plan_json": str(out_json),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
