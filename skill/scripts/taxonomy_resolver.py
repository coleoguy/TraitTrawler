#!/usr/bin/env python3
"""Resolve species names against the GBIF backbone.

Tries the `pygbif` package if available. Falls back to a lightweight
urllib call. Returns canonical name + GBIF taxon key, or
{"status": "unresolved"} on failure.

Cache hits to disk (state/taxonomy_cache.json) so repeat lookups are free.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import urlopen


def _lookup_via_http(name: str) -> dict:
    url = f"https://api.gbif.org/v1/species/match?name={quote_plus(name)}"
    try:
        with urlopen(url, timeout=10) as r:
            data = json.load(r)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    if data.get("matchType") == "NONE":
        return {"status": "unresolved", "raw": data}
    return {
        "status": "resolved",
        "canonical_name": data.get("canonicalName") or data.get("scientificName"),
        "gbif_key": data.get("usageKey"),
        "rank": data.get("rank"),
        "match_type": data.get("matchType"),
        "synonym": bool(data.get("synonym")),
    }


def resolve(name: str, cache_path: Path | None = None) -> dict:
    if not name or not name.strip():
        return {"status": "unresolved", "error": "empty name"}
    name = name.strip()
    cache: dict[str, dict] = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            cache = {}
    if name in cache:
        return cache[name]
    result = _lookup_via_http(name)
    if cache_path is not None and result.get("status") in ("resolved", "unresolved"):
        cache[name] = result
        cache_path.write_text(json.dumps(cache, indent=2))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--cache", type=Path, default=Path("state/taxonomy_cache.json"))
    args = ap.parse_args()
    r = resolve(args.name, args.cache)
    print(json.dumps(r, indent=2))
    return 0 if r.get("status") == "resolved" else 1


if __name__ == "__main__":
    sys.exit(main())
