#!/usr/bin/env python3
"""Append-only JSONL audit ledger.

Every row in results.csv has exactly one ledger entry identified by
`ledger_id`. The ledger captures everything needed to reproduce or
contest the row:

    sha256 + page + verbatim_quote + schema_hash + trait_profile_hash
    + model versions + hook verdicts + adjudication (if any)

Library functions for other scripts; also usable as a CLI for tail/search.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_row_hash(row: dict) -> str:
    """Stable hash of a Row for dedup and ledger linkage."""
    key_fields = {k: row.get(k) for k in sorted(row) if k != "ledger_id"}
    return hashlib.sha256(
        json.dumps(key_fields, sort_keys=True, default=str).encode()
    ).hexdigest()


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def append_entry(
    ledger_path: Path,
    row: dict,
    claim: dict,
    hook_results: list[dict],
    session_id: str,
    extractor_model: str,
    semantic_verifier_model: str,
    adjudicator_model: str | None = None,
    adjudication: dict | None = None,
    trait_profile_path: Path | None = None,
    schema_path: Path | None = None,
    skill_version: str = "6.0.0",
) -> str:
    """Append a ledger entry. Returns the ledger_id."""
    ledger_id = f"ldg_{uuid.uuid4().hex[:16]}"
    entry = {
        "ledger_id": ledger_id,
        "row_hash": canonical_row_hash(row),
        "sha256": row.get("sha256"),
        "pdf_path": row.get("pdf_path"),
        "page": row.get("page"),
        "verbatim_quote": row.get("verbatim_quote"),
        "quote_preceding_10w": row.get("quote_preceding_10w"),
        "quote_following_10w": row.get("quote_following_10w"),
        "claim_id": claim.get("claim_id"),
        "extractor_model": extractor_model,
        "semantic_verifier_model": semantic_verifier_model,
        "adjudicator_model": adjudicator_model,
        "skill_version": skill_version,
        "trait_profile_hash": md5_file(trait_profile_path) if trait_profile_path and trait_profile_path.exists() else None,
        "schema_hash": md5_file(schema_path) if schema_path and schema_path.exists() else None,
        "session_id": session_id,
        "timestamp_utc": iso_utc(),
        "uncertainty": claim.get("uncertainty"),
        "hook_results": hook_results,
        "adjudication": adjudication,
    }
    with ledger_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return ledger_id


def iter_ledger(ledger_path: Path):
    if not ledger_path.exists():
        return
    with ledger_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def find_by_id(ledger_path: Path, ledger_id: str) -> dict | None:
    for entry in iter_ledger(ledger_path):
        if entry.get("ledger_id") == ledger_id:
            return entry
    return None


def cli() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("count")
    fb = sub.add_parser("find")
    fb.add_argument("--id", required=True)
    tl = sub.add_parser("tail")
    tl.add_argument("-n", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "count":
        n = sum(1 for _ in iter_ledger(args.path))
        print(json.dumps({"entries": n}))
    elif args.cmd == "find":
        entry = find_by_id(args.path, args.id)
        print(json.dumps(entry, indent=2) if entry else "not found")
    elif args.cmd == "tail":
        entries = list(iter_ledger(args.path))[-args.n:]
        for e in entries:
            print(json.dumps(e))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
