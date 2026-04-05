#!/usr/bin/env python3
"""
Review and apply learning discoveries for TraitTrawler v5.

Classifies learning/*.json discovery files as ROUTINE (auto-applied to
guide.md) or STRUCTURAL (queued for human review). Also auto-generates
extraction examples from high-confidence verified records.

The Manager calls this at session end (or on demand) to keep guide.md
up to date without human intervention for safe, additive changes.

Usage:
    python3 scripts/review_discoveries.py --project-root .

Output: JSON summary to stdout.
"""

import argparse
import glob
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from state_utils import safe_read_json, safe_write_json, append_jsonl, FileLock


# ---------------------------------------------------------------------------
# Classification rules
# ---------------------------------------------------------------------------

ROUTINE_TYPES = {
    "notation_variant",
    "new_journal",
    "prolific_author",
    "species_not_in_guide",
}

STRUCTURAL_TYPES = {
    "new_extraction_rule",
    "validation_gap",
    "taxonomic_revision",
}

# Map discovery type to the guide.md section it targets
SECTION_MAP = {
    "notation_variant": ("Notation", "Sex Chromosome"),
    "new_journal":      ("Journals",),
    "prolific_author":  ("Authors",),
    "species_not_in_guide": ("Taxonomy", "Taxonomic Scope"),
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Guide.md editing
# ---------------------------------------------------------------------------

def _find_section_end(lines, header_pattern):
    """Find the line index range for a section matching header_pattern.

    Returns (header_idx, next_header_idx) or (None, None) if not found.
    The insertion point is next_header_idx (i.e., append before next section).
    """
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match ## Header or ## Header ...
        if re.match(r"^##\s+" + header_pattern, stripped, re.IGNORECASE):
            header_idx = i
            break

    if header_idx is None:
        return None, None

    # Find the next ## header after this one
    for j in range(header_idx + 1, len(lines)):
        if re.match(r"^##\s+", lines[j].strip()):
            return header_idx, j

    # No next header -- section runs to end of file
    return header_idx, len(lines)


def _append_to_section(lines, section_names, content):
    """Append content to the first matching section in guide.md.

    Tries each name in section_names until a match is found.
    If none match, appends under a new '## Discoveries' header.

    Returns the modified lines list.
    """
    for name in section_names:
        pattern = re.escape(name)
        header_idx, end_idx = _find_section_end(lines, pattern)
        if header_idx is not None:
            # Insert before end_idx, with a blank line separator
            insert = []
            if end_idx > 0 and lines[end_idx - 1].strip():
                insert.append("\n")
            insert.append(content + "\n")
            return lines[:end_idx] + insert + lines[end_idx:]

    # No matching section -- create a Discoveries section at the end
    lines.append("\n")
    lines.append("## Discoveries\n")
    lines.append("\n")
    lines.append(content + "\n")
    return lines


def _format_discovery_entry(discovery):
    """Format a discovery dict as a markdown bullet for guide.md."""
    value = discovery.get("value", "")
    source = discovery.get("source", "")
    doi = discovery.get("doi", "")
    notes = discovery.get("notes", "")

    parts = [f"- {value}"]
    if source:
        parts.append(f"(source: {source})")
    if doi:
        parts.append(f"[{doi}]")
    if notes:
        parts.append(f"-- {notes}")

    return " ".join(parts)


def apply_routine_to_guide(guide_path, discovery):
    """Append a single routine discovery to guide.md.

    Reads the file, appends to the correct section, writes atomically.
    Never deletes existing content.

    Returns True if guide was updated, False on error.
    """
    dtype = discovery.get("type", "")
    section_names = SECTION_MAP.get(dtype, ("Discoveries",))
    entry = _format_discovery_entry(discovery)

    # Read current guide
    try:
        with open(guide_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = "# Guide\n\n"
    except OSError as e:
        print(f"WARNING: Cannot read {guide_path}: {e}", file=sys.stderr)
        return False

    # Check for duplicate (exact value already present)
    value = discovery.get("value", "")
    if value and value in content:
        return True  # Already present, skip silently

    lines = content.splitlines(keepends=True)
    lines = _append_to_section(lines, section_names, entry)

    # Atomic write: temp file then rename
    parent_dir = os.path.dirname(guide_path) or "."
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            suffix=".md.tmp", dir=parent_dir,
            prefix=".guide_"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, guide_path)
        return True
    except OSError as e:
        print(f"WARNING: Atomic write failed for {guide_path}: {e}",
              file=sys.stderr)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


# ---------------------------------------------------------------------------
# Structural discovery queueing
# ---------------------------------------------------------------------------

def queue_for_human(state_dir, discovery):
    """Append a structural discovery to pending_guide_changes.json."""
    path = os.path.join(state_dir, "pending_guide_changes.json")
    with FileLock(path):
        pending = safe_read_json(path, default=[])
        discovery["queued_at"] = now_iso()
        pending.append(discovery)
        safe_write_json(path, pending)


# ---------------------------------------------------------------------------
# Extraction example generation
# ---------------------------------------------------------------------------

def _count_examples(examples_path):
    """Count the number of example entries in extraction_examples.md."""
    if not os.path.exists(examples_path):
        return 0
    try:
        with open(examples_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return 0
    # Count fenced code blocks or "**Output record:**" markers as examples
    return len(re.findall(r"\*\*Output record:\*\*", content))


def generate_examples(project_root):
    """Check audit_queue.json for confirmed high-confidence records.

    If 5+ qualifying records exist and extraction_examples.md has fewer
    than 10 examples, append a new example from the best candidate.

    Returns number of examples generated (0 or 1).
    """
    state_dir = os.path.join(project_root, "state")
    audit_path = os.path.join(state_dir, "audit_queue.json")
    examples_path = os.path.join(project_root, "extraction_examples.md")

    audit = safe_read_json(audit_path, default=[])
    if not isinstance(audit, list):
        # Handle dict-shaped audit queues (keyed by DOI)
        if isinstance(audit, dict):
            flat = []
            for key, val in audit.items():
                if isinstance(val, dict):
                    val.setdefault("doi", key)
                    flat.append(val)
                elif isinstance(val, list):
                    flat.extend(val)
            audit = flat
        else:
            return 0

    # Find confirmed high-confidence records
    qualified = []
    for record in audit:
        verification = record.get("verification", "")
        confidence = record.get("extraction_confidence", 0)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            continue
        if verification == "confirmed" and confidence > 0.90:
            qualified.append(record)

    if len(qualified) < 5:
        return 0

    current_count = _count_examples(examples_path)
    if current_count >= 10:
        return 0

    # Pick the best candidate (highest confidence, prefer records with DOI)
    qualified.sort(
        key=lambda r: (bool(r.get("doi")), r.get("extraction_confidence", 0)),
        reverse=True,
    )
    best = qualified[0]

    # Format the example -- just structured data, no PDF text
    species = best.get("species", "Unknown")
    doi = best.get("doi", "")
    source_page = best.get("source_page", "")

    trait_lines = []
    skip_keys = {"species", "doi", "source_page", "verification",
                 "audit_timestamp", "queued_at", "session_id",
                 "processed_date", "pdf_path", "pdf_source",
                 "flag_for_review"}
    for k, v in sorted(best.items()):
        if k in skip_keys or v is None or v == "":
            continue
        trait_lines.append(f"- {k}: `{v}`")

    example_block = (
        f"\n---\n\n"
        f"**Auto-generated example** (verified, confidence "
        f"{best.get('extraction_confidence', '?')})\n\n"
        f"- species: `{species}`\n"
    )
    example_block += "\n".join(trait_lines) + "\n"
    if source_page:
        example_block += f"- source_page: `{source_page}`\n"
    if doi:
        example_block += f"- doi: `{doi}`\n"
    example_block += "\n**Output record:**\n"
    example_block += f"(See fields above -- extracted from verified audit data)\n"

    # Append to extraction_examples.md
    try:
        with open(examples_path, "a", encoding="utf-8") as f:
            f.write(example_block)
        return 1
    except OSError as e:
        print(f"WARNING: Cannot append to {examples_path}: {e}",
              file=sys.stderr)
        return 0


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def review_discoveries(project_root):
    """Process all learning/*.json files and update guide.md."""
    learning_dir = os.path.join(project_root, "learning")
    processed_dir = os.path.join(learning_dir, ".processed")
    state_dir = os.path.join(project_root, "state")
    guide_path = os.path.join(project_root, "guide.md")

    os.makedirs(processed_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)

    # Collect discovery files (skip .processed/ subdirectory)
    pattern = os.path.join(learning_dir, "*.json")
    files = sorted(glob.glob(pattern))

    auto_applied = 0
    queued_for_human = 0
    guide_updated = False
    errors = []

    for fpath in files:
        fname = os.path.basename(fpath)

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                discovery = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: Cannot read {fpath}: {e}", file=sys.stderr)
            errors.append({"file": fname, "error": str(e)})
            continue

        if not isinstance(discovery, dict):
            errors.append({"file": fname, "error": "Not a JSON object"})
            continue

        dtype = discovery.get("type", "")
        discovery["_source_file"] = fname
        discovery["_reviewed_at"] = now_iso()

        if dtype in ROUTINE_TYPES:
            ok = apply_routine_to_guide(guide_path, discovery)
            if ok:
                auto_applied += 1
                guide_updated = True
            else:
                errors.append({"file": fname, "error": "guide.md write failed"})
                continue  # Don't move file if write failed
        else:
            # STRUCTURAL or unknown type -- queue for human
            queue_for_human(state_dir, discovery)
            queued_for_human += 1

        # Move to .processed/
        dest = os.path.join(processed_dir, fname)
        try:
            os.replace(fpath, dest)
        except OSError as e:
            print(f"WARNING: Cannot move {fpath} to {dest}: {e}",
                  file=sys.stderr)

    # Auto-generate extraction examples
    examples_generated = generate_examples(project_root)

    # Log the review event
    log_path = os.path.join(state_dir, "run_log.jsonl")
    append_jsonl(log_path, {
        "event": "discoveries_reviewed",
        "files_processed": len(files),
        "auto_applied": auto_applied,
        "queued_for_human": queued_for_human,
        "examples_generated": examples_generated,
        "errors": len(errors),
    })

    summary = {
        "files_processed": len(files),
        "auto_applied": auto_applied,
        "queued_for_human": queued_for_human,
        "examples_generated": examples_generated,
        "guide_updated": guide_updated,
    }
    if errors:
        summary["errors"] = errors

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Review learning discoveries and update guide.md"
    )
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    args = parser.parse_args()

    summary = review_discoveries(args.project_root)
    json.dump(summary, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
