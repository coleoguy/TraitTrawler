#!/usr/bin/env python3
"""
Build audit manifests from finds/ files for the blind Auditor.

For each finds file, extract only (species, source_page, pdf_path) tuples
— NOT the trait values — so the Auditor can re-extract independently
without anchoring bias.

Usage:
    python3 scripts/build_audit_manifest.py --project-root . --dir finds/
    python3 scripts/build_audit_manifest.py --project-root . --finds-file finds/X.json

Output: JSON summary to stdout, manifest files in audit_manifests/.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_manifest(finds_path, manifest_dir):
    """Build a manifest for one finds file.

    Returns the manifest path or None if no records to audit.
    """
    with open(finds_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    doi = data.get("doi", "")
    pdf_path = data.get("pdf_path", "")
    records = data.get("records", [])

    if not records or not pdf_path:
        return None

    # Build the stripped manifest — species + source_page only
    manifest_records = []
    for r in records:
        species = r.get("species", "").strip()
        source_page = str(r.get("source_page", "")).strip()
        if not species:
            continue
        manifest_records.append({
            "species": species,
            "source_page": source_page,
        })

    if not manifest_records:
        return None

    # Write manifest
    base = os.path.splitext(os.path.basename(finds_path))[0]
    manifest_path = os.path.join(manifest_dir, f"{base}_manifest.json")
    manifest = {
        "doi": doi,
        "pdf_path": pdf_path,
        "finds_file": os.path.basename(finds_path),
        "manifest_records": manifest_records,
        "created": now_iso(),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--dir", default="finds/")
    parser.add_argument("--finds-file", default=None)
    args = parser.parse_args()

    project_root = args.project_root
    manifest_dir = os.path.join(project_root, "audit_manifests")
    os.makedirs(manifest_dir, exist_ok=True)

    if args.finds_file:
        path = args.finds_file
        if not os.path.isabs(path):
            path = os.path.join(project_root, path)
        files = [path]
    else:
        pattern = os.path.join(project_root, args.dir, "*.json")
        files = sorted(glob.glob(pattern))

    manifests = []
    for fpath in files:
        if not os.path.isfile(fpath):
            continue
        m_path = build_manifest(fpath, manifest_dir)
        if m_path:
            manifests.append(os.path.relpath(m_path, project_root))

    print(json.dumps({
        "files_processed": len(files),
        "manifests_created": len(manifests),
        "manifests": manifests,
    }, indent=2))


if __name__ == "__main__":
    main()
