#!/usr/bin/env python3
"""
Automated audit queue processor for TraitTrawler.

Processes records in state/audit_queue.json with automated rules:
- Auto-approve records meeting quality criteria
- Auto-flag suspicious records (tau=24.0 with no SD, missing light_condition, LD)
- Leave ambiguous records as pending for manual review

Usage:
    python3 scripts/auto_audit.py --project-root /path/to/project --dry-run
    python3 scripts/auto_audit.py --project-root /path/to/project --apply
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone


def load_audit_queue(project_root):
    """Load the audit queue from state/audit_queue.json."""
    path = os.path.join(project_root, "state", "audit_queue.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return []


def classify_record(record):
    """Apply automated audit rules to a single record.

    Returns (action, reasons) where action is one of:
        "approve" - record passes automated checks
        "flag" - record has issues that need attention
        "pending" - record needs manual review (ambiguous)
    """
    reasons = []
    tau = record.get("tau_mean_hours", "")
    sd = record.get("tau_sd_hours", "")
    sem = record.get("tau_sem_hours", "")
    light = record.get("light_condition", "").strip()
    confidence = 0.0
    try:
        confidence = float(record.get("extraction_confidence", 0))
    except (ValueError, TypeError):
        pass

    # Rule 1: tau=24.0 with no variability measure
    if tau:
        try:
            tau_f = float(tau)
            has_variability = bool(str(sd).strip()) or bool(str(sem).strip())
            if abs(tau_f - 24.0) < 0.001 and not has_variability:
                reasons.append("tau=24.0h with no SD/SEM — possible entrained period")
        except (ValueError, TypeError):
            pass

    # Rule 2: Missing light_condition
    if not light:
        reasons.append("Missing light_condition — cannot verify free-running")

    # Rule 3: LD conditions (not free-running)
    if light:
        light_lower = light.lower()
        ld_patterns = ["ld", "12:12", "14:10", "16:8", "10:14",
                       "natural photoperiod", "light-dark", "light:dark"]
        for pat in ld_patterns:
            if pat in light_lower and "dd" not in light_lower:
                reasons.append(f"Light condition '{light}' suggests LD, not free-running")
                break

    # Rule 4: Missing PDF path
    pdf_path = record.get("pdf_path", "").strip()
    pdf_exists = record.get("pdf_exists", True)
    if not pdf_path or pdf_exists is False:
        reasons.append("Missing or unverified PDF")

    # Rule 5: Missing source_page
    source_page = record.get("source_page", "").strip()
    if not source_page:
        reasons.append("Missing source_page — extraction provenance unclear")

    # Classify based on accumulated reasons
    if reasons:
        return "flag", reasons

    # If confidence is decent and no issues found, approve
    if confidence >= 0.60:
        return "approve", ["Passes all automated checks"]

    # Low confidence with no specific issues — needs manual review
    return "pending", [f"Low confidence ({confidence}) — needs manual verification"]


def process_audit_queue(project_root, dry_run=True):
    """Process the entire audit queue."""
    queue = load_audit_queue(project_root)
    if not queue:
        print("Audit queue is empty.")
        return {"total": 0, "approved": 0, "flagged": 0, "pending": 0}

    results = {"total": len(queue), "approved": 0, "flagged": 0, "pending": 0,
               "details": []}

    for record in queue:
        action, reasons = classify_record(record)

        if action == "approve":
            results["approved"] += 1
            record["audit_status"] = "auto_approved"
        elif action == "flag":
            results["flagged"] += 1
            record["audit_status"] = "auto_flagged"
            record["audit_notes"] = "; ".join(reasons)
        else:
            results["pending"] += 1
            record["audit_status"] = "pending_manual"

        results["details"].append({
            "row_index": record.get("row_index", "?"),
            "species": record.get("species", "?"),
            "tau": record.get("tau_mean_hours", "?"),
            "light": record.get("light_condition", ""),
            "action": action,
            "reasons": reasons,
        })

    # Print summary
    print(f"Audit Queue Processing {'(DRY RUN)' if dry_run else '(APPLIED)'}:")
    print(f"  Total records: {results['total']}")
    print(f"  Auto-approved: {results['approved']}")
    print(f"  Auto-flagged:  {results['flagged']}")
    print(f"  Pending manual: {results['pending']}")
    print()

    # Print details grouped by action
    for action_label in ["flag", "pending", "approve"]:
        items = [d for d in results["details"] if d["action"] == action_label]
        if items:
            print(f"--- {action_label.upper()} ({len(items)}) ---")
            for item in items:
                species = item["species"]
                tau = item["tau"]
                light = item["light"] or "(none)"
                reason_str = "; ".join(item["reasons"])
                print(f"  Row {item['row_index']}: {species}, tau={tau}, "
                      f"light={light}")
                print(f"    -> {reason_str}")
            print()

    if not dry_run:
        # Write updated queue back
        queue_path = os.path.join(project_root, "state", "audit_queue.json")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

        # Backup original
        backup_path = os.path.join(project_root, "state",
                                   f"audit_queue_pre_auto_{timestamp}.json")
        original_queue = load_audit_queue(project_root)
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(original_queue, f, indent=2)

        # Write updated queue
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2)

        # Write audit results log
        results_path = os.path.join(project_root, "state",
                                    f"auto_audit_results_{timestamp}.json")
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"Queue updated: {queue_path}")
        print(f"Backup saved: {backup_path}")
        print(f"Results log: {results_path}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Automated audit queue processor for TraitTrawler"
    )
    parser.add_argument("--project-root", required=True,
                        help="Path to project root")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Preview actions without modifying files")
    group.add_argument("--apply", action="store_true",
                       help="Apply audit actions and update queue")
    args = parser.parse_args()

    process_audit_queue(args.project_root, dry_run=not args.apply)


if __name__ == "__main__":
    main()
