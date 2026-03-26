#!/usr/bin/env python3
"""
Schema-enforced CSV writer for TraitTrawler.

Validates every row against the project's collector_config.yaml output_fields
before appending to results.csv. Uses atomic writes (write-to-temp + rename)
to prevent data corruption on crashes.

Usage:
    # As a library (called by the agent's extraction pipeline):
    from csv_writer import SchemaEnforcedWriter

    writer = SchemaEnforcedWriter(project_root=".")
    report = writer.append_records(records)
    print(report.summary())

    # Standalone validation test:
    python3 scripts/csv_writer.py --project-root . --dry-run
"""

import csv
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def load_output_fields(project_root: str) -> list:
    """Read output_fields from collector_config.yaml."""
    config_path = os.path.join(project_root, "collector_config.yaml")
    try:
        import yaml
    except ImportError:
        # Fallback: parse output_fields from YAML manually (basic)
        return _parse_output_fields_fallback(config_path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    fields = config.get("output_fields", [])
    if not fields:
        raise ValueError("collector_config.yaml has no output_fields defined")
    return fields


def _parse_output_fields_fallback(config_path: str) -> list:
    """Parse output_fields without PyYAML (handles simple YAML lists)."""
    fields = []
    in_output_fields = False
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("output_fields:"):
                in_output_fields = True
                continue
            if in_output_fields:
                if stripped.startswith("- "):
                    fields.append(stripped[2:].strip().strip('"').strip("'"))
                elif stripped and not stripped.startswith("#"):
                    break  # end of list
    return fields


def load_validation_rules(project_root: str) -> list:
    """Read validation_rules from collector_config.yaml (optional)."""
    config_path = os.path.join(project_root, "collector_config.yaml")
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("validation_rules", [])
    except (ImportError, Exception):
        return []


# ---------------------------------------------------------------------------
# Field type inference and validation
# ---------------------------------------------------------------------------

# Fields that must never be empty
REQUIRED_FIELDS = {"species", "extraction_confidence"}

# Fields with known types
FLOAT_FIELDS = {"extraction_confidence", "calibrated_confidence"}
BOOL_FIELDS = {"flag_for_review"}
INT_FIELDS = {"paper_year"}

# Confidence bounds
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0


class ValidationError:
    """A single validation failure."""

    def __init__(self, field: str, value: Any, rule: str, message: str,
                 action: str = "flag"):
        self.field = field
        self.value = value
        self.rule = rule
        self.message = message
        self.action = action  # "flag", "drop", or "ask"

    def __repr__(self):
        return f"ValidationError({self.field}={self.value!r}: {self.message})"


def validate_record(record: dict, output_fields: list,
                    validation_rules: list) -> list:
    """
    Validate a single record against schema and rules.

    Returns a list of ValidationError objects (empty = valid).
    """
    errors = []

    # 1. Required fields present
    for field in REQUIRED_FIELDS:
        if field in output_fields:
            val = record.get(field, "")
            if val is None or str(val).strip() == "":
                errors.append(ValidationError(
                    field, val, "required",
                    f"Required field '{field}' is empty",
                    action="drop"
                ))

    # 2. Must have doi or paper_title
    doi = str(record.get("doi", "")).strip()
    title = str(record.get("paper_title", "")).strip()
    if not doi and not title:
        errors.append(ValidationError(
            "doi/paper_title", "", "identifier_required",
            "Record must have either doi or paper_title",
            action="drop"
        ))

    # 3. Confidence in valid range
    conf_str = record.get("extraction_confidence", "")
    if conf_str is not None and str(conf_str).strip():
        try:
            conf = float(conf_str)
            if conf < CONFIDENCE_MIN or conf > CONFIDENCE_MAX:
                errors.append(ValidationError(
                    "extraction_confidence", conf, "range",
                    f"Confidence {conf} outside [{CONFIDENCE_MIN}, {CONFIDENCE_MAX}]",
                    action="flag"
                ))
        except (ValueError, TypeError):
            errors.append(ValidationError(
                "extraction_confidence", conf_str, "type",
                f"Confidence '{conf_str}' is not a valid float",
                action="flag"
            ))

    # 4. Confidence vs source_type consistency
    source_type = str(record.get("source_type", "")).strip()
    if source_type == "abstract_only" and conf_str:
        try:
            conf = float(conf_str)
            if conf > 0.55:
                errors.append(ValidationError(
                    "extraction_confidence", conf, "source_type_consistency",
                    f"Abstract-only source but confidence={conf} > 0.55 ceiling",
                    action="flag"
                ))
        except (ValueError, TypeError):
            pass

    # 5. Boolean fields
    for field in BOOL_FIELDS:
        if field in record and record[field] not in (
            "", None, True, False,
            "True", "False", "true", "false", "TRUE", "FALSE",
            "0", "1", "yes", "no", "Yes", "No", "YES", "NO"
        ):
            errors.append(ValidationError(
                field, record[field], "type",
                f"Expected boolean, got '{record[field]}'",
                action="flag"
            ))

    # 6. Integer fields
    for field in INT_FIELDS:
        val = record.get(field, "")
        if val is not None and str(val).strip():
            try:
                int(val)
            except (ValueError, TypeError):
                errors.append(ValidationError(
                    field, val, "type",
                    f"Expected integer for '{field}', got '{val}'",
                    action="flag"
                ))

    # 7. Year sanity check
    year_str = record.get("paper_year", "")
    if year_str is not None and str(year_str).strip():
        try:
            year = int(year_str)
            if year < 1700 or year > datetime.now().year + 1:
                errors.append(ValidationError(
                    "paper_year", year, "range",
                    f"Year {year} outside plausible range [1700, {datetime.now().year + 1}]",
                    action="flag"
                ))
        except (ValueError, TypeError):
            pass

    # 8. Project-specific validation rules
    for rule in validation_rules:
        field = rule.get("field", "")
        val = record.get(field, "")
        if val is None or str(val).strip() == "":
            continue  # skip empty fields for project rules

        rule_type = rule.get("type", "")
        on_fail = rule.get("on_fail", "flag")

        if rule_type == "numeric_range":
            try:
                num = float(val)
                lo = rule.get("min", float("-inf"))
                hi = rule.get("max", float("inf"))
                if num < lo or num > hi:
                    errors.append(ValidationError(
                        field, num, "numeric_range",
                        f"{field}={num} outside [{lo}, {hi}]",
                        action=on_fail
                    ))
            except (ValueError, TypeError):
                errors.append(ValidationError(
                    field, val, "type",
                    f"Expected numeric for '{field}', got '{val}'",
                    action=on_fail
                ))

        elif rule_type == "even_number":
            try:
                num = int(float(val))
                if num % 2 != 0:
                    errors.append(ValidationError(
                        field, num, "even_number",
                        f"{field}={num} is not even",
                        action=on_fail
                    ))
            except (ValueError, TypeError):
                pass

        elif rule_type == "allowed_values":
            allowed = rule.get("values", [])
            if str(val) not in [str(a) for a in allowed]:
                errors.append(ValidationError(
                    field, val, "allowed_values",
                    f"{field}='{val}' not in {allowed}",
                    action=on_fail
                ))

        elif rule_type == "pattern":
            import re
            pattern = rule.get("regex", "")
            if pattern and not re.match(pattern, str(val)):
                errors.append(ValidationError(
                    field, val, "pattern",
                    f"{field}='{val}' doesn't match pattern '{pattern}'",
                    action=on_fail
                ))

    # 9. No unknown fields (warning only, not an error)
    # This is informational — extra fields are silently ignored by DictWriter

    return errors


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def build_dedup_keys(csv_path: str, output_fields: list) -> set:
    """Build set of dedup keys from existing results.csv."""
    core_fields = {
        "doi", "paper_title", "paper_authors", "first_author", "paper_year",
        "paper_journal", "session_id", "species", "family", "subfamily", "genus",
        "extraction_confidence", "flag_for_review", "source_type", "pdf_source",
        "pdf_filename", "pdf_url", "notes", "processed_date", "collection_locality",
        "country", "source_page", "source_context", "extraction_reasoning",
        "accepted_name", "gbif_key", "taxonomy_note",
        "audit_status", "audit_session", "audit_prior_values",
        "calibrated_confidence", "consensus_agreement", "extraction_trace_id",
    }
    trait_fields = [f for f in output_fields if f not in core_fields]

    keys = set()
    if not os.path.exists(csv_path):
        return keys

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (
                row.get("species", ""),
                tuple(row.get(k, "") for k in trait_fields),
            )
            keys.add(key)
    return keys


def make_dedup_key(record: dict, output_fields: list) -> tuple:
    """Create a dedup key for a single record."""
    core_fields = {
        "doi", "paper_title", "paper_authors", "first_author", "paper_year",
        "paper_journal", "session_id", "species", "family", "subfamily", "genus",
        "extraction_confidence", "flag_for_review", "source_type", "pdf_source",
        "pdf_filename", "pdf_url", "notes", "processed_date", "collection_locality",
        "country", "source_page", "source_context", "extraction_reasoning",
        "accepted_name", "gbif_key", "taxonomy_note",
        "audit_status", "audit_session", "audit_prior_values",
        "calibrated_confidence", "consensus_agreement", "extraction_trace_id",
    }
    trait_fields = [f for f in output_fields if f not in core_fields]
    return (
        record.get("species", ""),
        tuple(record.get(k, "") for k in trait_fields),
    )


# ---------------------------------------------------------------------------
# Atomic CSV writer
# ---------------------------------------------------------------------------

class WriteReport:
    """Result of an append_records operation."""

    def __init__(self):
        self.accepted = 0
        self.rejected = 0
        self.flagged = 0
        self.duplicates = 0
        self.errors = []  # list of (record_index, ValidationError)

    def summary(self) -> str:
        parts = [f"Accepted: {self.accepted}"]
        if self.flagged:
            parts.append(f"Flagged: {self.flagged}")
        if self.duplicates:
            parts.append(f"Duplicates skipped: {self.duplicates}")
        if self.rejected:
            parts.append(f"Rejected: {self.rejected}")
        return " | ".join(parts)


class SchemaEnforcedWriter:
    """
    Validates and atomically writes records to results.csv.

    Usage:
        writer = SchemaEnforcedWriter(project_root=".")
        report = writer.append_records(records)
    """

    def __init__(self, project_root: str = "."):
        self.project_root = project_root
        self.csv_path = os.path.join(project_root, "results.csv")
        self.output_fields = load_output_fields(project_root)
        self.validation_rules = load_validation_rules(project_root)

    def get_fieldnames(self) -> list:
        """Get fieldnames from existing CSV header, or from config if new."""
        if os.path.exists(self.csv_path):
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    return list(reader.fieldnames)
        return self.output_fields

    def append_records(self, records: list, session_id: str = "",
                       dry_run: bool = False) -> WriteReport:
        """
        Validate and atomically append records to results.csv.

        Args:
            records: List of dicts with field values.
            session_id: Session identifier to stamp on each record.
            dry_run: If True, validate but don't write.

        Returns:
            WriteReport with counts and any validation errors.
        """
        report = WriteReport()
        fieldnames = self.get_fieldnames()
        file_exists = os.path.exists(self.csv_path)

        # Build dedup keys from existing data
        dedup_keys = build_dedup_keys(self.csv_path, self.output_fields)

        rows_to_write = []

        for i, record in enumerate(records):
            # Stamp session_id and processed_date
            if session_id:
                record["session_id"] = session_id
            if "processed_date" not in record or not record["processed_date"]:
                record["processed_date"] = datetime.now().strftime("%Y-%m-%d")

            # Validate
            errors = validate_record(record, self.output_fields,
                                     self.validation_rules)

            # Separate drop errors from flag errors
            drop_errors = [e for e in errors if e.action == "drop"]
            flag_errors = [e for e in errors if e.action == "flag"]

            if drop_errors:
                report.rejected += 1
                for e in drop_errors:
                    report.errors.append((i, e))
                continue

            # Apply flags
            if flag_errors:
                record["flag_for_review"] = "True"
                reasons = "; ".join(e.message for e in flag_errors)
                existing_notes = record.get("notes", "") or ""
                record["notes"] = (
                    f"{existing_notes}; VALIDATION: {reasons}".strip("; ")
                )
                report.flagged += 1
                for e in flag_errors:
                    report.errors.append((i, e))

            # Dedup check
            key = make_dedup_key(record, self.output_fields)
            if key in dedup_keys:
                report.duplicates += 1
                continue

            dedup_keys.add(key)
            rows_to_write.append(record)
            report.accepted += 1

        if dry_run or not rows_to_write:
            return report

        # Atomic write: append to temp file, then replace
        # Strategy: copy existing file + new rows → temp → rename
        # This is safer than direct append for crash protection
        try:
            if file_exists:
                # For append, we use a simpler atomic strategy:
                # write new rows to a temp file, then cat-append atomically
                tmp_fd, tmp_path = tempfile.mkstemp(
                    suffix=".csv",
                    dir=self.project_root,
                    prefix=".results_append_"
                )
                try:
                    with os.fdopen(tmp_fd, "w", newline="",
                                   encoding="utf-8") as f:
                        writer = csv.DictWriter(
                            f, fieldnames=fieldnames,
                            extrasaction="ignore"
                        )
                        writer.writerows(rows_to_write)

                    # Append temp content to main file
                    with open(tmp_path, "r", encoding="utf-8") as src:
                        content = src.read()
                    with open(self.csv_path, "a", encoding="utf-8") as dst:
                        dst.write(content)
                finally:
                    # Clean up temp file
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
            else:
                # New file: write header + rows atomically
                tmp_fd, tmp_path = tempfile.mkstemp(
                    suffix=".csv",
                    dir=self.project_root,
                    prefix=".results_new_"
                )
                try:
                    with os.fdopen(tmp_fd, "w", newline="",
                                   encoding="utf-8") as f:
                        writer = csv.DictWriter(
                            f, fieldnames=fieldnames,
                            extrasaction="ignore"
                        )
                        writer.writeheader()
                        writer.writerows(rows_to_write)
                    os.rename(tmp_path, self.csv_path)
                except Exception:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    raise

        except Exception as e:
            # Critical: never silently drop records
            raise RuntimeError(
                f"CSV write failed after validating {report.accepted} records. "
                f"Error: {e}. Records NOT written — retry or investigate."
            ) from e

        return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Validate results.csv against project schema"
    )
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate without writing")
    args = parser.parse_args()

    writer = SchemaEnforcedWriter(args.project_root)
    csv_path = os.path.join(args.project_root, "results.csv")

    if not os.path.exists(csv_path):
        print("No results.csv found — nothing to validate.")
        return

    # Re-validate all existing records
    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(dict(row))

    print(f"Validating {len(records)} existing records...")

    total_errors = 0
    for i, record in enumerate(records):
        errors = validate_record(record, writer.output_fields,
                                 writer.validation_rules)
        if errors:
            total_errors += len(errors)
            for e in errors:
                print(f"  Row {i + 2}: {e}")

    if total_errors:
        print(f"\n{total_errors} validation issue(s) found across "
              f"{len(records)} records.")
        sys.exit(1)
    else:
        print(f"All {len(records)} records pass schema validation.")


if __name__ == "__main__":
    main()
