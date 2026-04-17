#!/usr/bin/env python3
"""Propose output schema columns from a trait_profile.md.

Fully trait-agnostic. Columns come from:
  1. A fixed set of GROUNDING + PROVENANCE columns (always present):
     - file/page/quote linkage (sha256, page, verbatim_quote, ...)
     - Darwin Core fields (basisOfRecord, identificationVerificationStatus,
       recordedBy) — the standard for biodiversity-data provenance
     - PAV fields (authoredBy, curatedBy, createdBy) — needed because
       DwC+PROV-O alone cannot distinguish human curator from paper author
     - PROV-O fields (wasDerivedFrom, wasGeneratedBy) — W3C data-lineage
     - Dublin Core fields (source, created)
  2. Trait-specific columns: read from §11 "Proposed Columns" in
     trait_profile.md, which the trait_learner writes after observing the
     seed papers. NEVER guessed from the trait name.
  3. Trait-specific hooks: paths to state/hooks/*.py files listed by the
     trait_learner in the proposed schema, after being sandbox-validated
     and user-approved.

Output: state/schema.proposed.json. The Manager presents it to the user
via AskUserQuestion; on approval it is renamed to state/schema.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# ------------------------------------------------------------------
# Always-present columns
# ------------------------------------------------------------------

GROUNDING_COLUMNS = {
    "sha256":             {"type": "string", "required": True,
                           "description": "SHA256 of the source PDF"},
    "page":               {"type": "int", "required": True,
                           "description": "1-indexed page number of the cited passage"},
    "verbatim_quote":     {"type": "string", "required": True,
                           "description": "Literal quote supporting the value"},
    "quote_preceding_10w":{"type": "string", "required": False,
                           "description": "Ten words preceding the quote"},
    "quote_following_10w":{"type": "string", "required": False,
                           "description": "Ten words following the quote"},
    "notation_style":     {"type": "string", "required": False,
                           "description": "inline_prose | table_cell | figure_caption | abstract"},
    "source_modality":    {"type": "enum", "required": False,
                           "values": ["text", "image", "both"],
                           "description": "Whether the extractor used page text, rendered image, or both"},
}

# Darwin Core terms (https://dwc.tdwg.org/terms/) for biodiversity data
# provenance. These are the TDWG standard and are required by GBIF IPT.
DARWIN_CORE_COLUMNS = {
    "dwc_basisOfRecord":                  {"type": "enum", "required": True,
                                            "values": ["HumanObservation",
                                                       "MachineObservation",
                                                       "PreservedSpecimen",
                                                       "LivingSpecimen",
                                                       "FossilSpecimen",
                                                       "MaterialSample"],
                                            "description": "DwC basisOfRecord — MachineObservation for AI rows, HumanObservation for curator rows"},
    "dwc_identificationVerificationStatus": {"type": "enum", "required": True,
                                             "values": ["PredictedByMachine",
                                                        "ValidatedByHuman",
                                                        "Unverified"],
                                             "description": "DwC term distinguishing AI-predicted vs human-validated rows"},
    "dwc_recordedBy":                     {"type": "string", "required": True,
                                            "description": "Curator name or tool version (e.g. TraitTrawler v6.1)"},
    "dwc_dataGeneralizations":            {"type": "string", "required": False,
                                            "description": "Free-text note if species was fuzzy-matched or values generalized"},
}

# PAV (Provenance, Authoring, Versioning) — W3C/biomedical standard that
# complements PROV-O with a curator-vs-author distinction that PROV-O lacks.
# See Ciccarese et al. 2013, JBMS.
PAV_COLUMNS = {
    "pav_authoredBy":  {"type": "string", "required": False,
                        "description": "ORCID or name of the original paper author(s)"},
    "pav_curatedBy":   {"type": "string", "required": False,
                        "description": "ORCID or name of the human curator (null for AI rows)"},
    "pav_createdBy":   {"type": "string", "required": True,
                        "description": "Tool/agent that created the digital record"},
}

# PROV-O (W3C recommendation) for lineage.
PROV_O_COLUMNS = {
    "prov_wasDerivedFrom":  {"type": "string", "required": True,
                             "description": "DOI or SHA256 of the source PDF"},
    "prov_wasGeneratedBy":  {"type": "string", "required": True,
                             "description": "Activity URI (ledger_id)"},
}

# Dublin Core terms for citation and temporal metadata.
DUBLIN_CORE_COLUMNS = {
    "dcterms_source":   {"type": "string", "required": False,
                         "description": "Citation string for the source paper"},
    "dcterms_created":  {"type": "string", "required": True,
                         "description": "ISO-8601 timestamp when row was created"},
}

# Identifier columns — project-specific but common enough to always emit
IDENTIFIER_COLUMNS = {
    "doi":              {"type": "string", "required": False},
    "first_author":     {"type": "string", "required": False},
    "year":             {"type": "int",    "required": False},
    "is_compilation":   {"type": "bool",   "required": True,
                         "description": "True if row came from a compilation/review table"},
    "original_citation":{"type": "string", "required": False,
                         "description": "For compilation rows: the primary source the table cites"},
    "canonical_species":{"type": "string", "required": False,
                         "description": "GBIF-resolved canonical species name"},
    "species_gbif_key": {"type": "int",    "required": False,
                         "description": "GBIF taxon usageKey"},
    "taxonomy_status":  {"type": "enum",   "required": False,
                         "values": ["resolved", "unresolved", "synonym_mapped", "fuzzy_matched"]},
    "uncertainty":      {"type": "json",   "required": False,
                         "description": "Structured uncertainty (value_clarity, notation_ambiguity, pdf_quality, ...)"},
    "claim_id":         {"type": "string", "required": False},
    "ledger_id":        {"type": "string", "required": False},
    "source_type":      {"type": "enum",   "required": True,
                         "values": ["full_text", "table", "compilation",
                                    "abstract_only", "human_curated_bootstrap"],
                         "description": "Where the record came from"},
}


PROVENANCE_COLUMNS: dict[str, dict] = {
    **GROUNDING_COLUMNS,
    **DARWIN_CORE_COLUMNS,
    **PAV_COLUMNS,
    **PROV_O_COLUMNS,
    **DUBLIN_CORE_COLUMNS,
    **IDENTIFIER_COLUMNS,
}


# ------------------------------------------------------------------
# Trait-profile parsing
# ------------------------------------------------------------------


def parse_profile(md: str) -> dict:
    """Extract §-numbered sections from trait_profile.md."""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^##\s+(\d+)\.\s+(.*)$", line)
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


def guess_trait_name(profile_md: str) -> str:
    for line in profile_md.splitlines():
        if line.strip().startswith("trait:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return "value"


def parse_proposed_columns_section(text: str) -> dict:
    """Parse §11 'Proposed Columns' from trait_profile.md.

    Expected format (written by trait_learner):

        ## 11. Proposed Columns

        ### column_name
        - type: int | float | string | enum | bool | json
        - required: true | false
        - values: [list] (for enum only)
        - description: free text
        - cited_value_required: true | false (optional)

    Returns a dict of column_name -> config. Returns empty dict if §11 is
    missing or malformed — the manager will fall back to an all-
    provenance schema and ask the user to add trait columns manually.
    """
    cols: dict[str, dict] = {}
    if not text:
        return cols
    current = None
    cfg: dict = {}
    for line in text.splitlines():
        m = re.match(r"^###\s+(\S+)\s*$", line)
        if m:
            if current and cfg:
                cols[current] = cfg
            current = m.group(1)
            cfg = {}
            continue
        if current is None:
            continue
        m = re.match(r"^\s*-\s+(\w+)\s*:\s*(.+)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.lower() in ("true", "false"):
                cfg[key] = val.lower() == "true"
            elif val.startswith("[") and val.endswith("]"):
                try:
                    cfg[key] = json.loads(val)
                except json.JSONDecodeError:
                    cfg[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif val.isdigit():
                cfg[key] = int(val)
            else:
                cfg[key] = val
    if current and cfg:
        cols[current] = cfg
    return cols


def parse_proposed_hooks_dir(project_root: Path) -> list[str]:
    """Return relative paths to all approved hooks in state/hooks/."""
    hook_dir = project_root / "state" / "hooks"
    if not hook_dir.exists():
        return []
    out = []
    for p in sorted(hook_dir.glob("*.py")):
        out.append(f"state/hooks/{p.name}")
    return out


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, default=Path("state/trait_profile.md"))
    ap.add_argument("--out", type=Path, default=Path("state/schema.proposed.json"))
    ap.add_argument("--project-root", type=Path, default=Path("."))
    args = ap.parse_args()

    if not args.profile.exists():
        print(f"profile not found: {args.profile}", file=sys.stderr)
        return 2

    md = args.profile.read_text()
    sections = parse_profile(md)
    trait_name = guess_trait_name(md)

    trait_cols = parse_proposed_columns_section(
        sections.get("proposed columns", "")
    )

    # Schema = trait cols (listed first) + provenance
    columns = {**trait_cols, **PROVENANCE_COLUMNS}

    trait_hooks = parse_proposed_hooks_dir(args.project_root.resolve())

    schema = {
        "trait_name": trait_name,
        "primary_trait_key": trait_name,
        "columns": columns,
        "trait_hooks": trait_hooks,
        "_notes": [
            "Trait columns come from §11 Proposed Columns in trait_profile.md.",
            "Provenance columns follow Darwin Core + PAV + PROV-O + Dublin Core.",
            "trait_hooks are paths to approved project-local hook Python files.",
            "No trait-specific logic lives in the core skill.",
        ],
    }
    args.out.write_text(json.dumps(schema, indent=2))
    print(json.dumps({
        "status": "ok",
        "out": str(args.out),
        "trait": trait_name,
        "trait_column_count": len(trait_cols),
        "provenance_column_count": len(PROVENANCE_COLUMNS),
        "total_column_count": len(columns),
        "trait_hooks": trait_hooks,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
