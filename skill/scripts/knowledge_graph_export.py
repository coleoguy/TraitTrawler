#!/usr/bin/env python3
"""
Knowledge graph provenance export for TraitTrawler.

Exports extraction provenance as JSON-LD for interoperability with
biodiversity knowledge graphs. Also detects cross-paper conflicts
where multiple papers report different values for the same species/trait.

Usage:
    python3 scripts/knowledge_graph_export.py --project-root . --format jsonld --output provenance.jsonld
    python3 scripts/knowledge_graph_export.py --project-root . --format conflicts --output conflicts.json
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def load_results(project_root):
    """Load results.csv into a list of dicts."""
    path = Path(project_root) / "results.csv"
    if not path.exists():
        return [], []

    with open(path) as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames) if reader.fieldnames else []
        rows = list(reader)
    return rows, fieldnames


def load_config(project_root):
    """Load collector_config.yaml to identify trait fields."""
    config_path = Path(project_root) / "collector_config.yaml"
    if not config_path.exists():
        return {}

    try:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fallback: parse output_fields manually
        config = {}
        with open(config_path) as f:
            in_fields = False
            fields = []
            for line in f:
                if "output_fields:" in line:
                    in_fields = True
                    continue
                if in_fields:
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        fields.append(stripped[2:].strip())
                    elif stripped and not stripped.startswith("#"):
                        in_fields = False
            config["output_fields"] = fields
        return config


CORE_FIELDS = {
    "doi", "paper_title", "paper_authors", "first_author", "paper_year",
    "paper_journal", "session_id", "species", "family", "subfamily", "genus",
    "extraction_confidence", "calibrated_confidence", "flag_for_review",
    "source_type", "pdf_source", "pdf_filename", "pdf_url", "notes",
    "processed_date", "collection_locality", "country", "source_page",
    "source_context", "extraction_reasoning", "extraction_trace_id",
    "accepted_name", "gbif_key", "taxonomy_note", "consensus_agreement",
    "audit_status", "audit_session", "audit_prior_values",
}


def identify_trait_fields(fieldnames):
    """Identify trait-specific fields (non-core)."""
    return [f for f in fieldnames if f not in CORE_FIELDS]


def detect_conflicts(rows, trait_fields):
    """Detect cross-paper conflicts: same species, different trait values."""
    species_data = defaultdict(list)
    for row in rows:
        species = row.get("species", "").strip()
        if species:
            species_data[species].append(row)

    conflicts = []
    concordant = []

    for species, records in species_data.items():
        dois = set(r.get("doi", "") for r in records)
        if len(dois) < 2:
            continue  # Need data from multiple papers

        for field in trait_fields:
            values_by_doi = defaultdict(list)
            for r in records:
                val = r.get(field, "").strip()
                doi = r.get("doi", "").strip()
                if val and doi:
                    values_by_doi[doi].append({
                        "value": val,
                        "confidence": float(r.get("extraction_confidence", 0) or 0),
                        "calibrated_confidence": float(r.get("calibrated_confidence", 0) or 0) if r.get("calibrated_confidence") else None,
                        "source": r.get("first_author", "") + " " + r.get("paper_year", ""),
                    })

            if len(values_by_doi) < 2:
                continue

            unique_values = set()
            for doi_entries in values_by_doi.values():
                for entry in doi_entries:
                    unique_values.add(entry["value"])

            if len(unique_values) > 1:
                # Conflict: different values from different papers
                conflict_entry = {
                    "species": species,
                    "field": field,
                    "values": {},
                    "status": "conflicted",
                }
                for doi, entries in values_by_doi.items():
                    for entry in entries:
                        conflict_entry["values"][doi] = {
                            "value": entry["value"],
                            "confidence": entry["confidence"],
                            "source": entry["source"],
                        }

                # Confidence-weighted resolution
                best_doi = max(
                    values_by_doi.keys(),
                    key=lambda d: max(e["confidence"] for e in values_by_doi[d]),
                )
                best_entry = max(values_by_doi[best_doi], key=lambda e: e["confidence"])
                conflict_entry["resolution"] = {
                    "recommended_value": best_entry["value"],
                    "reason": f"highest confidence ({best_entry['confidence']:.2f}) from {best_entry['source']}",
                }
                conflicts.append(conflict_entry)
            else:
                concordant.append({
                    "species": species,
                    "field": field,
                    "value": list(unique_values)[0],
                    "n_papers": len(values_by_doi),
                    "status": "concordant",
                })

    return conflicts, concordant


def export_jsonld(rows, trait_fields, output_path):
    """Export extraction provenance as JSON-LD."""
    graph = []

    for row in rows:
        species = row.get("species", "").strip()
        doi = row.get("doi", "").strip()
        if not species or not doi:
            continue

        for field in trait_fields:
            value = row.get(field, "").strip()
            if not value:
                continue

            record = {
                "@id": f"record:{row.get('extraction_trace_id', '')}_{field}",
                "@type": "dwc:MeasurementOrFact",
                "dwc:scientificName": species,
                "dwc:measurementType": field,
                "dwc:measurementValue": value,
                "prov:wasGeneratedBy": {
                    "@type": "prov:Activity",
                    "prov:used": {"@id": f"doi:{doi}"},
                    "tt:sourcePage": row.get("source_page", ""),
                    "tt:sourceContext": row.get("source_context", "")[:200],
                    "tt:extractionConfidence": float(row.get("extraction_confidence", 0) or 0),
                    "tt:sessionId": row.get("session_id", ""),
                },
            }

            # Add calibrated confidence if available
            cal_conf = row.get("calibrated_confidence", "").strip()
            if cal_conf:
                record["prov:wasGeneratedBy"]["tt:calibratedConfidence"] = float(cal_conf)

            # Add consensus info if available
            consensus = row.get("consensus_agreement", "").strip()
            if consensus:
                record["prov:wasGeneratedBy"]["tt:consensusAgreement"] = consensus

            # Add taxonomy info
            accepted = row.get("accepted_name", "").strip()
            if accepted and accepted != species:
                record["dwc:acceptedNameUsage"] = accepted
                record["dwc:taxonomicStatus"] = "synonym"

            gbif_key = row.get("gbif_key", "").strip()
            if gbif_key:
                record["dwc:taxonID"] = f"gbif:{gbif_key}"

            graph.append(record)

    jsonld = {
        "@context": {
            "dwc": "http://rs.tdwg.org/dwc/terms/",
            "schema": "http://schema.org/",
            "prov": "http://www.w3.org/ns/prov#",
            "tt": "http://traittrawler.org/terms/",
        },
        "@graph": graph,
    }

    with open(output_path, "w") as f:
        json.dump(jsonld, f, indent=2)

    print(f"Exported {len(graph)} provenance records to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler knowledge graph export")
    parser.add_argument("--project-root", required=True, help="Project root directory")
    parser.add_argument(
        "--format",
        choices=["jsonld", "conflicts", "both"],
        default="both",
        help="Export format",
    )
    parser.add_argument("--output", help="Output file path (default: auto-named)")
    args = parser.parse_args()

    project_root = args.project_root
    rows, fieldnames = load_results(project_root)

    if not rows:
        print("No results to export.")
        return

    trait_fields = identify_trait_fields(fieldnames)

    if args.format in ("jsonld", "both"):
        output = args.output or os.path.join(project_root, "provenance.jsonld")
        export_jsonld(rows, trait_fields, output)

    if args.format in ("conflicts", "both"):
        conflicts, concordant = detect_conflicts(rows, trait_fields)
        output = args.output if args.format == "conflicts" else os.path.join(project_root, "conflicts.json")

        result = {
            "total_species_with_multi_paper_data": len(set(c["species"] for c in conflicts + concordant)),
            "conflicts": conflicts,
            "concordant_count": len(concordant),
            "summary": f"{len(conflicts)} conflicts across {len(set(c['species'] for c in conflicts))} species",
        }

        with open(output, "w") as f:
            json.dump(result, f, indent=2)

        print(f"\n── Cross-Paper Conflicts ──────────")
        if conflicts:
            for c in conflicts[:10]:  # show top 10
                vals = ", ".join(
                    f'"{v["value"]}" ({v["source"]})'
                    for v in c["values"].values()
                )
                print(f" {c['species']}: {c['field']}: {vals}")
                print(f"   → Resolution: {c['resolution']['recommended_value']} ({c['resolution']['reason']})")
        else:
            print(" No conflicts detected — all multi-paper species are concordant")
        print(f" {len(conflicts)} conflicts | {len(concordant)} concordant observations")
        print(f"────────────────────────────────────")


if __name__ == "__main__":
    main()
