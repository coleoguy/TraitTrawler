#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 scripts/taxonomy_resolver.py --species "Name1" "Name2" --cache state/taxonomy_cache.json --kingdom Animalia
# OUTPUT: JSON to stdout with resolution results for each species
"""
TraitTrawler Taxonomy Resolver
===============================
Validates species names against the GBIF Backbone Taxonomy.
Resolves synonyms, auto-fills higher taxonomy, caches results.

Usage:
    python3 taxonomy_resolver.py --species "Cicindela sylvatica" "Dynastes hercules" \
        --cache state/taxonomy_cache.json --kingdom Animalia

    python3 taxonomy_resolver.py --csv results.csv --species-column species \
        --cache state/taxonomy_cache.json --kingdom Animalia

Output: JSON to stdout with resolution results for each species.
"""

import argparse
import csv
import json
import os
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


GBIF_MATCH_URL = "https://api.gbif.org/v1/species/match"
GBIF_SPECIES_URL = "https://api.gbif.org/v1/species"
RATE_LIMIT_DELAY = 0.35  # seconds between requests (~3/sec)


def load_cache(cache_path):
    """Load taxonomy cache from disk."""
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def save_cache(cache, cache_path):
    """Save taxonomy cache to disk."""
    if cache_path:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        os.replace(tmp, cache_path)


def gbif_match(species_name, kingdom="Animalia"):
    """Query GBIF species match API."""
    url = (
        f"{GBIF_MATCH_URL}"
        f"?name={quote(species_name)}"
        f"&kingdom={quote(kingdom)}"
        f"&strict=false"
    )
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError) as e:
        return {"matchType": "NONE", "error": str(e)}


def gbif_family_species_count(family_name):
    """Get approximate species count for a family from GBIF."""
    url = (
        f"{GBIF_SPECIES_URL}/search"
        f"?rank=FAMILY&q={quote(family_name)}&limit=1"
    )
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("results"):
                key = data["results"][0].get("key")
                if key:
                    # Get descendant species count
                    count_url = (
                        f"{GBIF_SPECIES_URL}/{key}/species?limit=0"
                    )
                    with urlopen(Request(count_url), timeout=15) as cr:
                        count_data = json.loads(cr.read().decode("utf-8"))
                        return count_data.get("count", 0)
    except (URLError, HTTPError, TimeoutError):
        pass
    return 0


def resolve_species(species_name, kingdom, cache):
    """Resolve a single species name. Returns a result dict."""
    # Check cache first
    if species_name in cache:
        cached = cache[species_name]
        return {
            "query": species_name,
            "cached": True,
            **cached
        }

    # Query GBIF
    time.sleep(RATE_LIMIT_DELAY)
    match = gbif_match(species_name, kingdom)

    result = {
        "query": species_name,
        "cached": False,
        "match_type": match.get("matchType", "NONE"),
        "status": match.get("status", "UNKNOWN"),
        "confidence": match.get("confidence", 0),
        "gbif_key": match.get("usageKey"),
        "matched_name": match.get("scientificName", ""),
        "accepted_name": None,
        "accepted_key": None,
        "kingdom": match.get("kingdom", ""),
        "phylum": match.get("phylum", ""),
        "class": match.get("class", ""),
        "order": match.get("order", ""),
        "family": match.get("family", ""),
        "genus": match.get("genus", ""),
        "rank": match.get("rank", ""),
        "action": "none",
        "note": ""
    }

    match_type = result["match_type"]
    status = result["status"]

    if match_type == "NONE":
        result["action"] = "flag_not_found"
        result["note"] = "Species not found in GBIF Backbone Taxonomy"

    elif match_type == "HIGHERRANK":
        result["action"] = "flag_higher_rank"
        result["note"] = (
            f"GBIF matched to higher rank only: "
            f"{result['matched_name']} (rank: {result['rank']})"
        )

    elif status == "SYNONYM":
        # Get accepted name
        accepted_key = match.get("acceptedUsageKey")
        accepted_name = match.get("species", match.get("canonicalName", ""))
        # If the match response includes accepted info directly
        if accepted_key:
            result["accepted_key"] = accepted_key
            # Try to get the accepted name details
            try:
                time.sleep(RATE_LIMIT_DELAY)
                acc_url = f"{GBIF_SPECIES_URL}/{accepted_key}"
                with urlopen(Request(acc_url, headers={"Accept": "application/json"}), timeout=15) as resp:
                    acc_data = json.loads(resp.read().decode("utf-8"))
                    accepted_name = acc_data.get("canonicalName", acc_data.get("species", accepted_name))
                    result["family"] = acc_data.get("family", result["family"])
                    result["genus"] = acc_data.get("genus", result["genus"])
                    result["order"] = acc_data.get("order", result["order"])
            except (URLError, HTTPError, TimeoutError):
                pass

        result["accepted_name"] = accepted_name
        result["action"] = "synonym_resolved"
        result["note"] = (
            f"Original name: {species_name}, resolved to accepted name "
            f"via GBIF (acceptedUsageKey: {accepted_key})"
        )

    elif match_type == "FUZZY":
        if result["confidence"] >= 90:
            result["action"] = "fuzzy_high_confidence"
            result["accepted_name"] = result["matched_name"]
            result["note"] = (
                f"GBIF fuzzy match: {result['matched_name']} "
                f"(confidence: {result['confidence']}%)"
            )
        else:
            result["action"] = "fuzzy_low_confidence"
            result["note"] = (
                f"GBIF low-confidence fuzzy match: {result['matched_name']} "
                f"({result['confidence']}%)"
            )

    elif match_type == "EXACT" and status == "ACCEPTED":
        result["action"] = "accepted"
        result["accepted_name"] = result["matched_name"]
        result["note"] = ""

    elif match_type == "EXACT" and status == "DOUBTFUL":
        result["action"] = "flag_doubtful"
        result["accepted_name"] = result["matched_name"]
        result["note"] = "GBIF status: DOUBTFUL"

    else:
        # EXACT match with other status
        result["action"] = "accepted"
        result["accepted_name"] = result["matched_name"]

    # Update cache
    cache_entry = {
        "status": result["status"],
        "accepted_name": result["accepted_name"] or species_name,
        "gbif_key": result["gbif_key"],
        "family": result["family"],
        "genus": result["genus"],
        "order": result["order"],
        "match_type": result["match_type"],
        "confidence": result["confidence"],
        "lookup_date": time.strftime("%Y-%m-%d")
    }
    cache[species_name] = cache_entry

    return result


def main():
    parser = argparse.ArgumentParser(description="Resolve species names via GBIF")
    parser.add_argument("--species", nargs="+", help="Species names to resolve")
    parser.add_argument("--csv", help="CSV file to read species from")
    parser.add_argument("--species-column", default="species", help="Column name in CSV")
    parser.add_argument("--cache", default="state/taxonomy_cache.json", help="Cache file path")
    parser.add_argument("--kingdom", default="Animalia", help="GBIF kingdom filter")
    parser.add_argument("--family-counts", nargs="+", help="Get species counts for families")

    args = parser.parse_args()

    cache = load_cache(args.cache)

    # Handle family species count queries
    if args.family_counts:
        counts = {}
        for family in args.family_counts:
            cache_key = f"__family_count__{family}"
            if cache_key in cache:
                counts[family] = cache[cache_key]
            else:
                time.sleep(RATE_LIMIT_DELAY)
                count = gbif_family_species_count(family)
                counts[family] = count
                cache[cache_key] = count
        save_cache(cache, args.cache)
        json.dump(counts, sys.stdout, indent=2)
        print()
        return

    # Collect species names
    species_names = set()
    if args.species:
        species_names.update(args.species)
    if args.csv and os.path.exists(args.csv):
        with open(args.csv, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get(args.species_column, "").strip()
                if name:
                    species_names.add(name)

    if not species_names:
        print(json.dumps({"error": "No species names provided"}))
        sys.exit(1)

    # Resolve each species
    results = []
    cached_count = 0
    resolved_count = 0
    for name in sorted(species_names):
        result = resolve_species(name, args.kingdom, cache)
        results.append(result)
        if result["cached"]:
            cached_count += 1
        else:
            resolved_count += 1

    # Save updated cache
    save_cache(cache, args.cache)

    # Output
    output = {
        "total": len(results),
        "cached": cached_count,
        "resolved": resolved_count,
        "results": results,
        "summary": {
            "accepted": sum(1 for r in results if r["action"] == "accepted"),
            "synonym_resolved": sum(1 for r in results if r["action"] == "synonym_resolved"),
            "fuzzy_high": sum(1 for r in results if r["action"] == "fuzzy_high_confidence"),
            "fuzzy_low": sum(1 for r in results if r["action"] == "fuzzy_low_confidence"),
            "not_found": sum(1 for r in results if r["action"] == "flag_not_found"),
            "higher_rank": sum(1 for r in results if r["action"] == "flag_higher_rank"),
        }
    }

    json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
