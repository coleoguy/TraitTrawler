#!/usr/bin/env python3
"""Propose output schema columns from a trait_profile.md.

Reads state/trait_profile.md and emits state/schema.proposed.json
with:
  - the domain-agnostic provenance columns (always present)
  - trait-specific columns inferred from sections 1-9 of the profile
  - trait-specific hooks registered in `trait_hooks`

The Manager presents this to the user via AskUserQuestion. On
approval, the Manager renames .proposed.json -> schema.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROVENANCE_COLUMNS = {
    "sha256":             {"type": "string", "required": True,
                           "description": "SHA256 of the source PDF"},
    "page":               {"type": "int", "required": True,
                           "description": "1-indexed page number of the cited passage"},
    "verbatim_quote":     {"type": "string", "required": True,
                           "description": "Literal quote supporting the value"},
    "quote_preceding_10w":{"type": "string", "required": False,
                           "description": "Ten words preceding the quote, for disambiguation"},
    "quote_following_10w":{"type": "string", "required": False,
                           "description": "Ten words following the quote"},
    "doi":                {"type": "string", "required": False,
                           "description": "DOI of the source paper"},
    "first_author":       {"type": "string", "required": False},
    "year":               {"type": "int",    "required": False},
    "is_compilation":     {"type": "bool",   "required": True,
                           "description": "Whether this row came from a compilation table"},
    "original_citation":  {"type": "string", "required": False,
                           "description": "For compilation rows: the primary source the table cites"},
    "canonical_species":  {"type": "string", "required": False,
                           "description": "GBIF-resolved canonical species name"},
    "taxonomy_status":    {"type": "enum",   "required": False,
                           "values": ["resolved", "unresolved", "synonym_mapped"]},
    "notation_style":     {"type": "string", "required": False,
                           "description": "How the value was presented: inline_prose | table_cell | figure_caption | abstract"},
    "uncertainty":        {"type": "json",   "required": False,
                           "description": "Structured uncertainty (value_clarity, notation_ambiguity, pdf_quality, ...)"},
    "claim_id":           {"type": "string", "required": False},
    "ledger_id":          {"type": "string", "required": False,
                           "description": "Pointer to state/ledger.jsonl"},
}


def parse_profile(md: str) -> dict:
    """Extract structured data from trait_profile.md sections."""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^## (\d+)\.\s+(.*)$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = m.group(2).strip().lower()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def infer_trait_columns(profile_sections: dict, trait_name: str) -> dict:
    """Heuristic: emit one numeric column per numeric notation seen.

    This is a best-effort starting schema. The user edits it.
    """
    cols: dict[str, dict] = {}
    units_text = profile_sections.get("units and variants", "")
    notation_text = profile_sections.get("notation conventions", "")

    trait_slug = re.sub(r"\W+", "_", trait_name.strip().lower()).strip("_")
    # Primary numeric value column
    cols[f"{trait_slug}_value"] = {
        "type": "float",
        "required": True,
        "description": f"Primary numeric value of {trait_name}",
        "cited_value_required": True,
    }
    # Unit column if units section has multiple variants
    if units_text and len(units_text.splitlines()) > 2:
        cols[f"{trait_slug}_unit"] = {
            "type": "string",
            "required": True,
            "description": "Unit of the measured value (canonical form)",
        }
    # Qualifier column if §7 is non-trivial
    qualifiers = profile_sections.get("qualifiers", "")
    if qualifiers and len(qualifiers) > 30:
        cols[f"{trait_slug}_qualifier"] = {
            "type": "string",
            "required": False,
            "description": "Sex, stage, tissue, or context qualifier for the value",
        }
    return cols


def guess_trait_name(profile_md: str) -> str:
    for line in profile_md.splitlines():
        if line.startswith("trait:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return "value"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, default=Path("state/trait_profile.md"))
    ap.add_argument("--out", type=Path, default=Path("state/schema.proposed.json"))
    args = ap.parse_args()

    if not args.profile.exists():
        print(f"profile not found: {args.profile}", file=sys.stderr)
        return 2

    md = args.profile.read_text()
    sections = parse_profile(md)
    trait_name = guess_trait_name(md)

    columns = dict(PROVENANCE_COLUMNS)
    trait_cols = infer_trait_columns(sections, trait_name)
    # trait columns before provenance columns in display order
    columns = {**trait_cols, **columns}

    # Default trait_hooks: none unless this is a recognizable karyotype project
    trait_hooks: list[str] = []
    lower_trait = trait_name.lower()
    if any(kw in lower_trait for kw in ("karyotype", "chromosome", "2n", "diploid")):
        trait_hooks = ["hook_2n_range", "hook_hac_consistency",
                       "hook_sex_system_regex"]
        # Register the canonical karyotype columns
        columns.update({
            "diploid_2n":              {"type": "int", "required": False},
            "haploid_autosome_count":  {"type": "int", "required": False},
            "sex_chrom_count":         {"type": "int", "required": False},
            "sex_system":              {"type": "enum", "required": False,
                                        "values": ["XY", "XX", "ZW", "ZZ", "X0",
                                                   "Z0", "X1X2Y", "X1Y1X2Y2",
                                                   "neoXY", "multiple", "unknown"]},
        })

    schema = {
        "trait_name": trait_name,
        "primary_trait_key": trait_name,
        "columns": columns,
        "trait_hooks": trait_hooks,
        "_notes": [
            "columns listed here are a starting point inferred from trait_profile.md",
            "the user may edit, add, or remove any column",
            "trait_hooks register domain-specific validators from scripts/hooks.py",
        ],
    }
    args.out.write_text(json.dumps(schema, indent=2))
    print(json.dumps({"status": "ok", "out": str(args.out),
                      "trait": trait_name,
                      "column_count": len(columns),
                      "trait_hooks": trait_hooks}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
