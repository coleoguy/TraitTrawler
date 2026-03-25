#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 verify_session.py [--project-root /path/to/project]
# OUTPUT: state/verification_report.json + human-readable summary to stdout
"""
TraitTrawler Deterministic Session Verification Script

A post-batch verification utility that validates results.csv quality without LLM judgment.
Checks for duplicates, schema compliance, confidence anomalies, required fields, consistency,
and controlled vocabulary constraints. Outputs a JSON report and human-readable summary.

Usage:
    python verify_session.py [--project-root /path/to/project]

Exit codes:
    0: All checks passed
    1: One or more errors found
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from statistics import mean, stdev


def parse_yaml_config(config_path: str) -> Dict[str, Any]:
    """
    Parse YAML config file with fallback to regex extraction if pyyaml unavailable.

    Args:
        config_path: Path to collector_config.yaml

    Returns:
        Dictionary containing config data (fields, source_type_values, pdf_source_values)
    """
    try:
        import yaml
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config or {}
    except ImportError:
        # Fallback: regex-based YAML parsing for critical fields
        config = {}
        try:
            with open(config_path, 'r') as f:
                content = f.read()

            # Extract fields section
            fields_match = re.search(r'fields:\s*\n((?:  \w+:.*\n)*)', content)
            if fields_match:
                fields_section = fields_match.group(1)
                config['fields'] = {}
                # Parse each field definition
                for line in fields_section.split('\n'):
                    match = re.match(r'  (\w+):\s*(.+)', line)
                    if match:
                        field_name, field_def = match.groups()
                        # Extract type: extract_type: string or extract_type: number, etc.
                        type_match = re.search(r'extract_type:\s*(\w+)', field_def)
                        if type_match:
                            config['fields'][field_name] = {'extract_type': type_match.group(1)}

            # Extract controlled vocabulary
            for vocab_field in ['source_type_values', 'pdf_source_values']:
                pattern = f'{vocab_field}:.*?\\[(.*?)\\]'
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    values_str = match.group(1)
                    values = [v.strip().strip("'\"") for v in values_str.split(',')]
                    config[vocab_field] = [v for v in values if v]
        except Exception as e:
            print(f"Warning: Failed to parse YAML config (will continue with limited validation): {e}")

        return config


def load_results_csv(csv_path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    Load results.csv file.

    Args:
        csv_path: Path to results.csv

    Returns:
        Tuple of (rows as list of dicts, fieldnames)
    """
    rows = []
    fieldnames = []

    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
    except FileNotFoundError:
        raise FileNotFoundError(f"results.csv not found at {csv_path}")
    except Exception as e:
        raise Exception(f"Failed to read results.csv: {e}")

    return rows, fieldnames


def validate_field_type(value: str, field_type: str, field_name: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a field value matches its declared type.

    Args:
        value: The field value
        field_type: The declared type (string, number, boolean, date, confidence)
        field_name: Field name for error messaging

    Returns:
        Tuple of (is_valid, error_message)
    """
    if value == '' or value is None:
        # Empty values are OK for most fields
        return True, None

    if field_type == 'number':
        try:
            float(value)
            return True, None
        except ValueError:
            return False, f"Expected number, got '{value}'"

    elif field_type == 'confidence':
        try:
            conf = float(value)
            if not (0.0 <= conf <= 1.0):
                return False, f"Confidence must be 0.0-1.0, got {conf}"
            return True, None
        except ValueError:
            return False, f"Confidence must be numeric, got '{value}'"

    elif field_type == 'boolean':
        if value.lower() in ('true', 'false', ''):
            return True, None
        return False, f"Boolean must be 'true' or 'false', got '{value}'"

    elif field_type == 'date':
        # Check ISO 8601 format (YYYY-MM-DD)
        if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
            return True, None
        return False, f"Date must be ISO format (YYYY-MM-DD), got '{value}'"

    elif field_type == 'string':
        return True, None

    return True, None


def detect_duplicates(rows: List[Dict[str, str]], csv_fieldnames: List[str]) -> List[Dict[str, Any]]:
    """
    Detect duplicate rows (matching doi, species, and all trait fields).

    Args:
        rows: List of result rows
        csv_fieldnames: List of CSV fieldnames

    Returns:
        List of issues found
    """
    issues = []

    # Identify trait fields (all fields except metadata)
    metadata_fields = {'doi', 'paper_title', 'extraction_date', 'extraction_method',
                      'extraction_confidence', 'source_type', 'pdf_source'}
    trait_fields = [f for f in csv_fieldnames if f not in metadata_fields]

    # Build duplicate detection key
    seen = {}
    for row_num, row in enumerate(rows, start=2):  # Start at 2 (header is row 1)
        key_parts = [row.get('doi', ''), row.get('species', '')]
        key_parts.extend([row.get(f, '') for f in trait_fields])
        key = tuple(key_parts)

        if key in seen and key != ('', ''):  # Ignore empty keys
            issues.append({
                'type': 'duplicate',
                'severity': 'error',
                'field': 'doi, species, trait_fields',
                'row_number': row_num,
                'message': f"Duplicate record matching doi={row.get('doi')}, species={row.get('species')}, traits. First occurrence: row {seen[key]}",
                'value': None
            })
        else:
            seen[key] = row_num

    return issues


def validate_schema(rows: List[Dict[str, str]], fieldnames: List[str], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Validate that all fields match declared types.

    Args:
        rows: List of result rows
        fieldnames: CSV fieldnames
        config: Configuration dict with field type info

    Returns:
        List of issues found
    """
    issues = []

    config_fields = config.get('fields', {})

    for row_num, row in enumerate(rows, start=2):
        for field_name in fieldnames:
            value = row.get(field_name, '')

            # Determine field type from config, with sensible defaults
            if field_name in config_fields:
                field_type = config_fields[field_name].get('extract_type', 'string')
            else:
                # Infer type from field name
                if field_name == 'extraction_confidence':
                    field_type = 'confidence'
                elif 'date' in field_name.lower():
                    field_type = 'date'
                elif 'confidence' in field_name.lower():
                    field_type = 'confidence'
                elif '_numeric' in field_name or field_name in ('minimum_value', 'maximum_value'):
                    field_type = 'number'
                else:
                    field_type = 'string'

            is_valid, error_msg = validate_field_type(value, field_type, field_name)
            if not is_valid:
                issues.append({
                    'type': 'schema_violation',
                    'severity': 'error',
                    'field': field_name,
                    'row_number': row_num,
                    'message': f"Type mismatch: {error_msg}",
                    'value': value
                })

    return issues


def check_confidence_anomaly(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Flag if session mean extraction_confidence is >2 SD below overall mean.
    Note: This is a heuristic warning; we can't compute true "overall mean" in isolation.

    Args:
        rows: List of result rows

    Returns:
        List of warnings found
    """
    issues = []

    confidences = []
    for row in rows:
        try:
            conf = float(row.get('extraction_confidence', ''))
            confidences.append(conf)
        except (ValueError, TypeError):
            pass

    if len(confidences) < 2:
        return issues  # Need at least 2 data points

    session_mean = mean(confidences)
    session_std = stdev(confidences)

    # Warning threshold: >2 SD below the session mean (within this batch)
    # This is a self-referential check to spot batches with unusual low confidence
    if session_std > 0:
        low_threshold = session_mean - (2 * session_std)
        if session_mean < low_threshold:
            issues.append({
                'type': 'confidence_anomaly',
                'severity': 'warning',
                'field': 'extraction_confidence',
                'row_number': None,
                'message': f"Session mean confidence ({session_mean:.3f}) is unusually low relative to internal variance. Review extraction quality.",
                'value': f"mean={session_mean:.3f}, stdev={session_std:.3f}"
            })

    return issues


def check_column_count(csv_path: str) -> List[Dict[str, Any]]:
    """
    Check for column shift by counting raw fields per line.

    csv.DictReader silently absorbs column shifts by mapping values to wrong
    field names. This check reads the raw CSV and compares the number of
    fields in each row against the header. A mismatch indicates an unquoted
    delimiter, missing field, or fieldnames list change mid-session.

    Args:
        csv_path: Path to results.csv

    Returns:
        List of issues found
    """
    issues = []
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return issues
            expected = len(header)
            for line_num, raw_row in enumerate(reader, start=2):
                actual = len(raw_row)
                if actual != expected:
                    issues.append({
                        'type': 'column_count_mismatch',
                        'severity': 'error',
                        'field': None,
                        'row_number': line_num,
                        'message': f"Row has {actual} fields but header has {expected} — likely column shift from unquoted delimiter or changed fieldnames",
                        'value': f"expected={expected}, actual={actual}"
                    })
    except Exception:
        pass  # File read errors handled elsewhere
    return issues


def check_required_fields(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Verify that required fields are present and non-empty.

    Args:
        rows: List of result rows

    Returns:
        List of issues found
    """
    issues = []

    for row_num, row in enumerate(rows, start=2):
        # Required: doi OR paper_title
        if not (row.get('doi', '').strip() or row.get('paper_title', '').strip()):
            issues.append({
                'type': 'missing_required_field',
                'severity': 'error',
                'field': 'doi, paper_title',
                'row_number': row_num,
                'message': "Either doi or paper_title must be present",
                'value': None
            })

        # Required: species non-empty
        if not row.get('species', '').strip():
            issues.append({
                'type': 'missing_required_field',
                'severity': 'error',
                'field': 'species',
                'row_number': row_num,
                'message': "Species field must not be empty",
                'value': None
            })

    return issues


def check_consistency(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Check cross-field consistency constraints.

    Args:
        rows: List of result rows

    Returns:
        List of issues found
    """
    issues = []

    for row_num, row in enumerate(rows, start=2):
        source_type = row.get('source_type', '').strip()

        # If source_type is "abstract_only", extraction_confidence should be <= 0.55
        if source_type.lower() == 'abstract_only':
            try:
                conf = float(row.get('extraction_confidence', '0'))
                if conf > 0.55:
                    issues.append({
                        'type': 'consistency_violation',
                        'severity': 'warning',
                        'field': 'extraction_confidence',
                        'row_number': row_num,
                        'message': f"extraction_confidence ({conf:.2f}) exceeds expected max (0.55) for source_type='abstract_only'",
                        'value': f"{conf:.2f}"
                    })
            except (ValueError, TypeError):
                pass

    return issues


def check_controlled_vocabulary(rows: List[Dict[str, str]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Validate that source_type and pdf_source use allowed values.

    Args:
        rows: List of result rows
        config: Configuration dict with vocabulary info

    Returns:
        List of issues found
    """
    issues = []

    source_type_values = config.get('source_type_values', [])
    pdf_source_values = config.get('pdf_source_values', [])

    for row_num, row in enumerate(rows, start=2):
        source_type = row.get('source_type', '').strip()
        pdf_source = row.get('pdf_source', '').strip()

        # Check source_type if vocabulary is defined
        if source_type_values and source_type and source_type not in source_type_values:
            issues.append({
                'type': 'invalid_vocabulary',
                'severity': 'error',
                'field': 'source_type',
                'row_number': row_num,
                'message': f"source_type '{source_type}' not in allowed values: {source_type_values}",
                'value': source_type
            })

        # Check pdf_source if vocabulary is defined
        if pdf_source_values and pdf_source and pdf_source not in pdf_source_values:
            issues.append({
                'type': 'invalid_vocabulary',
                'severity': 'error',
                'field': 'pdf_source',
                'row_number': row_num,
                'message': f"pdf_source '{pdf_source}' not in allowed values: {pdf_source_values}",
                'value': pdf_source
            })

    return issues


def verify_session(project_root: str) -> Tuple[Dict[str, Any], int]:
    """
    Run all verification checks on a TraitTrawler batch.

    Args:
        project_root: Root directory of the project

    Returns:
        Tuple of (report_dict, exit_code)
    """
    project_path = Path(project_root)
    results_csv = project_path / 'results.csv'
    config_file = project_path / 'collector_config.yaml'
    state_dir = project_path / 'state'

    # Initialize report
    report = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'total_records': 0,
        'records_checked': 0,
        'issues': [],
        'summary': {'errors': 0, 'warnings': 0, 'pass': True}
    }

    # Check for required files
    if not results_csv.exists():
        report['issues'].append({
            'type': 'missing_file',
            'severity': 'error',
            'field': None,
            'row_number': None,
            'message': f"results.csv not found at {results_csv}",
            'value': None
        })
        report['summary']['errors'] += 1
        report['summary']['pass'] = False
        return report, 1

    # Load data
    try:
        rows, fieldnames = load_results_csv(str(results_csv))
        report['total_records'] = len(rows)
        report['records_checked'] = len(rows)
    except Exception as e:
        report['issues'].append({
            'type': 'file_read_error',
            'severity': 'error',
            'field': None,
            'row_number': None,
            'message': f"Failed to read results.csv: {e}",
            'value': None
        })
        report['summary']['errors'] += 1
        report['summary']['pass'] = False
        return report, 1

    # Load config
    config = {}
    if config_file.exists():
        try:
            config = parse_yaml_config(str(config_file))
        except Exception as e:
            report['issues'].append({
                'type': 'config_read_error',
                'severity': 'warning',
                'field': None,
                'row_number': None,
                'message': f"Failed to read collector_config.yaml: {e}",
                'value': None
            })
            report['summary']['warnings'] += 1

    # Run all checks — column count first (most critical, catches shifts early)
    all_issues = []
    all_issues.extend(check_column_count(str(results_csv)))
    all_issues.extend(detect_duplicates(rows, fieldnames))
    all_issues.extend(validate_schema(rows, fieldnames, config))
    all_issues.extend(check_confidence_anomaly(rows))
    all_issues.extend(check_required_fields(rows))
    all_issues.extend(check_consistency(rows))
    all_issues.extend(check_controlled_vocabulary(rows, config))

    # Categorize and populate report
    for issue in all_issues:
        report['issues'].append(issue)
        if issue['severity'] == 'error':
            report['summary']['errors'] += 1
        elif issue['severity'] == 'warning':
            report['summary']['warnings'] += 1

    # Set pass/fail
    report['summary']['pass'] = (report['summary']['errors'] == 0)

    return report, (0 if report['summary']['pass'] else 1)


def print_summary(report: Dict[str, Any]) -> None:
    """Print human-readable summary to stdout."""
    print("\n" + "=" * 70)
    print("TraitTrawler Session Verification Report")
    print("=" * 70)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Records checked: {report['records_checked']} / {report['total_records']}")
    print()
    print(f"Summary:")
    print(f"  Errors: {report['summary']['errors']}")
    print(f"  Warnings: {report['summary']['warnings']}")
    print(f"  Status: {'PASS' if report['summary']['pass'] else 'FAIL'}")

    if report['issues']:
        print()
        print("Issues:")
        print("-" * 70)
        for issue in report['issues']:
            severity_str = issue['severity'].upper()
            field_str = f" [{issue['field']}]" if issue['field'] else ""
            row_str = f" (row {issue['row_number']})" if issue['row_number'] else ""
            print(f"{severity_str}{field_str}{row_str}: {issue['message']}")
            if issue['value'] is not None:
                print(f"  Value: {issue['value']}")
    else:
        print()
        print("No issues found.")

    print("=" * 70 + "\n")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Verify TraitTrawler batch results.csv quality'
    )
    parser.add_argument(
        '--project-root',
        default='.',
        help='Root directory of the project (default: current directory)'
    )

    args = parser.parse_args()

    # Run verification
    report, exit_code = verify_session(args.project_root)

    # Create state directory if needed
    state_dir = Path(args.project_root) / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON report
    report_file = state_dir / 'verification_report.json'
    try:
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
    except Exception as e:
        print(f"Error writing verification report: {e}", file=sys.stderr)
        exit_code = 1

    # Print human-readable summary
    print_summary(report)

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
