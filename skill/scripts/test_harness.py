#!/usr/bin/env python3
"""
Test harness for TraitTrawler — generates synthetic project data.

Creates a complete project directory with realistic fake data for testing
dashboard generation, CSV validation, and other utilities without needing
a real collection session.

Usage:
    python3 scripts/test_harness.py --output-dir /tmp/test_tt --records 200
    python3 dashboard_generator.py --project-root /tmp/test_tt
    open /tmp/test_tt/dashboard.html
"""

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Realistic taxonomic data for synthetic records
_FAMILIES = [
    ("Scarabaeidae", ["Dynastes", "Megasoma", "Golofa", "Chalcosoma", "Oryctes"]),
    ("Cerambycidae", ["Anoplophora", "Batocera", "Cerambyx", "Prionus", "Rosalia"]),
    ("Carabidae", ["Carabus", "Pterostichus", "Harpalus", "Nebria", "Cicindela"]),
    ("Chrysomelidae", ["Leptinotarsa", "Chrysolina", "Diabrotica", "Altica", "Donacia"]),
    ("Staphylinidae", ["Staphylinus", "Philonthus", "Quedius", "Paederus", "Ocypus"]),
    ("Curculionidae", ["Sitophilus", "Otiorhynchus", "Phyllobius", "Hylobius", "Pissodes"]),
    ("Coccinellidae", ["Coccinella", "Harmonia", "Hippodamia", "Adalia", "Chilocorus"]),
    ("Lucanidae", ["Lucanus", "Dorcus", "Prosopocoilus", "Cyclommatus", "Hexarthrius"]),
]

_JOURNALS = [
    "Comp Cytogenetics", "J Insect Science", "Coleopt Bull",
    "Zool J Linn Soc", "Entomol Exp Appl", "Syst Entomol",
    "Ann Entomol Soc Am", "Insect Syst Divers", "Eur J Entomol",
]

_COUNTRIES = [
    "Brazil", "United States", "Japan", "Germany", "Australia",
    "Mexico", "South Africa", "China", "India", "Colombia",
    "Peru", "France", "Thailand", "Costa Rica", "Ecuador",
]

_SOURCES = ["full_text", "table", "catalogue", "abstract_only"]
_PDF_SOURCES = ["unpaywall", "openalex", "europepmc", "proxy", "abstract_only"]

_AUTHOR_LASTNAMES = [
    "Smith", "Garcia", "Tanaka", "Mueller", "Santos", "Kim", "Johnson",
    "Oliveira", "Nakamura", "Schmidt", "Wang", "Silva", "Yamamoto",
    "Martinez", "Anderson", "Brown", "Wilson", "Taylor", "Thomas", "Lee",
]


def _rand_species(family_data):
    family, genera = random.choice(family_data)
    genus = random.choice(genera)
    epithet = random.choice(["magnificus", "obscurus", "grandis", "minor",
                              "australis", "orientalis", "niger", "rufus",
                              "maculatus", "punctatus", "lineatus", "brevis"])
    return genus + " " + epithet, genus, family


def _rand_author():
    return random.choice(_AUTHOR_LASTNAMES)


def generate_test_project(output_dir, n_records=100, n_papers=20):
    """Create a complete synthetic TraitTrawler project."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(exist_ok=True)
    (root / "pdfs").mkdir(exist_ok=True)
    (root / "state" / "extraction_traces").mkdir(parents=True, exist_ok=True)
    (root / "state" / "snapshots").mkdir(parents=True, exist_ok=True)

    # Generate papers
    papers = []
    base_date = datetime(2026, 3, 1, 10, 0, 0)
    for i in range(n_papers):
        author = _rand_author()
        year = random.randint(1995, 2025)
        journal = random.choice(_JOURNALS)
        doi = f"10.{random.randint(1000,9999)}/test.{random.randint(1000,9999)}"
        papers.append({
            "doi": doi,
            "first_author": author,
            "paper_authors": f"{author}, A.; Co-Author, B.",
            "paper_title": f"Karyotype variation in {random.choice(_FAMILIES)[0]}",
            "paper_year": str(year),
            "paper_journal": journal,
            "processed_time": base_date + timedelta(minutes=i * 8),
        })

    # Generate records
    fieldnames = [
        "doi", "paper_title", "paper_authors", "first_author",
        "paper_year", "paper_journal", "session_id",
        "species", "family", "subfamily", "genus",
        "accepted_name", "gbif_key",
        "diploid_number", "sex_chromosome_system", "karyotype_formula",
        "collection_locality", "country",
        "source_page", "source_context", "extraction_reasoning",
        "extraction_confidence", "flag_for_review",
        "source_type", "pdf_source", "pdf_filename", "pdf_url",
        "notes", "processed_date",
    ]

    rows = []
    session_id = "2026-03-01T10:00:00Z"
    processed = {}
    progress_lines = []

    records_so_far = 0
    for pi, paper in enumerate(papers):
        n_from_paper = max(1, int(random.gauss(n_records / n_papers, 2)))
        n_from_paper = min(n_from_paper, n_records - records_so_far)
        if records_so_far >= n_records:
            break

        for _ in range(n_from_paper):
            species, genus, family = _rand_species(_FAMILIES)
            src_type = random.choice(_SOURCES)
            conf = round(random.betavariate(8, 2), 2)  # skewed toward high confidence
            if src_type == "abstract_only":
                conf = min(conf, 0.55)

            rows.append({
                "doi": paper["doi"],
                "paper_title": paper["paper_title"],
                "paper_authors": paper["paper_authors"],
                "first_author": paper["first_author"],
                "paper_year": paper["paper_year"],
                "paper_journal": paper["paper_journal"],
                "session_id": session_id,
                "species": species,
                "family": family,
                "subfamily": "",
                "genus": genus,
                "accepted_name": species,
                "gbif_key": str(random.randint(1000000, 9999999)),
                "diploid_number": str(random.choice([18, 20, 22, 24, 26, 28, 36, 38])),
                "sex_chromosome_system": random.choice(["XY", "X0", "XY", "neo-XY", "Xyp"]),
                "karyotype_formula": f"2n={random.choice([18,20,22,24])}",
                "collection_locality": f"Region {random.randint(1,20)}",
                "country": random.choice(_COUNTRIES),
                "source_page": str(random.randint(1, 30)),
                "source_context": f"Table {random.randint(1,5)}: {species} 2n={random.randint(18,38)}",
                "extraction_reasoning": "" if conf > 0.8 else "Ambiguous notation",
                "extraction_confidence": str(conf),
                "flag_for_review": "true" if conf < 0.75 else "false",
                "source_type": src_type,
                "pdf_source": random.choice(_PDF_SOURCES),
                "pdf_filename": f"{paper['first_author']}_{paper['paper_year']}_{paper['paper_journal'].split()[0]}_{paper['doi'].split('.')[-1]}.pdf",
                "pdf_url": "",
                "notes": "",
                "processed_date": paper["processed_time"].isoformat() + "Z",
            })
            records_so_far += 1

        processed[paper["doi"]] = {
            "title": paper["paper_title"],
            "records": n_from_paper,
            "session": session_id,
        }

        progress_lines.append(json.dumps({
            "timestamp": paper["processed_time"].isoformat() + "Z",
            "paper": f"{paper['first_author']} et al. {paper['paper_year']}",
            "records": n_from_paper,
            "total_records": records_so_far,
            "queue_remaining": max(0, n_papers - pi - 1),
        }))

    # Write results.csv
    with open(root / "results.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Write leads.csv
    lead_fields = ["doi", "paper_title", "first_author", "paper_year",
                   "lead_status", "failure_reason"]
    leads = []
    for i in range(random.randint(5, 15)):
        leads.append({
            "doi": f"10.{random.randint(1000,9999)}/lead.{i}",
            "paper_title": f"Lead paper {i}",
            "first_author": _rand_author(),
            "paper_year": str(random.randint(2000, 2025)),
            "lead_status": random.choice(["needs_fulltext", "paywall", "scanned_skip"]),
            "failure_reason": random.choice(["no OA source", "paywall", "scanned PDF"]),
        })
    with open(root / "leads.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=lead_fields)
        writer.writeheader()
        writer.writerows(leads)

    # Write state files
    with open(root / "state" / "processed.json", "w") as fh:
        json.dump(processed, fh, indent=2)
    with open(root / "state" / "queue.json", "w") as fh:
        json.dump([], fh)
    with open(root / "state" / "search_log.json", "w") as fh:
        json.dump({"karyotype Coleoptera": {"count": 45, "date": "2026-03-01"}}, fh)
    with open(root / "state" / "live_progress.jsonl", "w") as fh:
        fh.write("\n".join(progress_lines) + "\n")
    with open(root / "state" / "run_log.jsonl", "w") as fh:
        fh.write(json.dumps({
            "timestamp": "2026-03-01T10:00:00Z",
            "session_id": session_id,
            "event": "session_start",
            "session_target": n_papers,
        }) + "\n")
        fh.write(json.dumps({
            "timestamp": "2026-03-01T12:30:00Z",
            "session_id": session_id,
            "event": "session_end",
            "papers_processed": len(processed),
            "records_added": len(rows),
        }) + "\n")

    # Write collector_config.yaml
    yaml_text = f"""project_name: "Test Karyotype Project"
contact_email: "test@example.com"
target_taxa:
  - Coleoptera
trait_name: "karyotype"
trait_description: "Chromosome numbers and sex chromosome systems in beetles"
proxy_url: ""
institution: "Test University"
output_csv: "results.csv"
output_fields:
  - doi
  - paper_title
  - paper_authors
  - first_author
  - paper_year
  - paper_journal
  - species
  - family
  - genus
  - diploid_number
  - sex_chromosome_system
  - karyotype_formula
  - country
  - extraction_confidence
  - flag_for_review
  - source_type
  - pdf_source
  - processed_date
  - session_id
source_type_values: [full_text, table, catalogue, abstract_only]
pdf_source_values: [unpaywall, openalex, europepmc, semanticscholar, core, proxy, local_pdf, browser_failed, scanned_skipped]
report_every: 2
batch_size: 20
"""
    with open(root / "collector_config.yaml", "w") as fh:
        fh.write(yaml_text)

    # Write minimal config.py and guide.md
    with open(root / "config.py", "w") as fh:
        fh.write('SEARCH_TERMS = ["karyotype Coleoptera", "chromosome number beetles"]\n')
    with open(root / "guide.md", "w") as fh:
        fh.write("# Karyotype Collection Guide\n\nExtract diploid numbers and sex chromosome systems.\n")

    print(f"Generated test project at {root}")
    print(f"  {len(rows)} records, {len(processed)} papers, {len(leads)} leads")
    return root


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler test data generator")
    parser.add_argument("--output-dir", default="/tmp/test_traittrawler",
                        help="Directory to create test project in")
    parser.add_argument("--records", type=int, default=100,
                        help="Number of synthetic records to generate")
    parser.add_argument("--papers", type=int, default=20,
                        help="Number of synthetic papers")
    args = parser.parse_args()

    generate_test_project(args.output_dir, n_records=args.records, n_papers=args.papers)


if __name__ == "__main__":
    main()
