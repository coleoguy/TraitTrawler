#!/usr/bin/env python3
"""
Extraction benchmarking for TraitTrawler.

Computes precision, recall, F1 per field against gold-standard data.
Gold-standard data accumulates from calibration holdouts, audit
confirmations, and user corrections.

Usage:
    python3 scripts/benchmark.py --project-root .
    python3 scripts/benchmark.py --project-root . --full  # with detailed report
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def load_gold_data(project_root):
    """Load gold-standard benchmark data."""
    path = Path(project_root) / "state" / "benchmark_gold.jsonl"
    if not path.exists():
        return []
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data.append(json.loads(line))
    return data


def compute_field_metrics(gold_data):
    """Compute precision, recall, F1 per field."""
    field_stats = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "total": 0})

    for entry in gold_data:
        field = entry.get("field", "unknown")
        if field == "_record_level":
            # False negative: entire record missed
            field_stats["_record_level"]["fn"] += 1
            continue

        field_stats[field]["total"] += 1
        if entry.get("correct", False):
            field_stats[field]["tp"] += 1
        else:
            if entry.get("extracted_value") is not None:
                field_stats[field]["fp"] += 1  # wrong value extracted
            else:
                field_stats[field]["fn"] += 1  # value not extracted

    metrics = {}
    for field, stats in field_stats.items():
        tp = stats["tp"]
        fp = stats["fp"]
        fn = stats["fn"]

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = tp / stats["total"] if stats["total"] > 0 else 0.0

        metrics[field] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "total": stats["total"],
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "accuracy": round(accuracy, 3),
        }

    return metrics


def compute_record_level_metrics(gold_data):
    """Compute record-level precision and recall."""
    record_correct = 0
    record_total = 0
    records_missed = 0

    # Group by doi + species for record-level analysis
    records = defaultdict(lambda: {"correct_fields": 0, "total_fields": 0})
    for entry in gold_data:
        if entry.get("field") == "_record_level":
            records_missed += 1
            continue
        key = (entry.get("doi", ""), entry.get("species", ""))
        records[key]["total_fields"] += 1
        if entry.get("correct", False):
            records[key]["correct_fields"] += 1

    for key, stats in records.items():
        record_total += 1
        if stats["total_fields"] > 0 and stats["correct_fields"] == stats["total_fields"]:
            record_correct += 1

    record_precision = record_correct / record_total if record_total > 0 else 0.0
    total_expected = record_total + records_missed
    record_recall = record_total / total_expected if total_expected > 0 else 0.0
    record_f1 = (
        2 * record_precision * record_recall / (record_precision + record_recall)
        if (record_precision + record_recall) > 0
        else 0.0
    )

    return {
        "records_extracted": record_total,
        "records_correct": record_correct,
        "records_missed": records_missed,
        "precision": round(record_precision, 3),
        "recall": round(record_recall, 3),
        "f1": round(record_f1, 3),
    }


def compute_brier_score(gold_data):
    """Compute Brier score from calibration data."""
    cal_path = None  # Will check in main
    scores = []
    for entry in gold_data:
        conf = entry.get("predicted_confidence")
        correct = entry.get("correct")
        if conf is not None and correct is not None:
            actual = 1.0 if correct else 0.0
            scores.append((float(conf) - actual) ** 2)
    return round(sum(scores) / len(scores), 4) if scores else None


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler extraction benchmarking")
    parser.add_argument("--project-root", required=True, help="Project root directory")
    parser.add_argument("--full", action="store_true", help="Generate detailed HTML report")
    args = parser.parse_args()

    project_root = args.project_root
    gold_data = load_gold_data(project_root)

    if not gold_data:
        print("No benchmark data available.")
        print("Benchmark data is created during calibration (§0b) and from audit outcomes (§15).")
        print("Run 'benchmark this paper' to manually add benchmark data.")
        return

    # Compute metrics
    field_metrics = compute_field_metrics(gold_data)
    record_metrics = compute_record_level_metrics(gold_data)
    brier = compute_brier_score(gold_data)

    # Save benchmark log
    log_path = Path(project_root) / "state" / "benchmark_log.json"
    existing = []
    if log_path.exists():
        with open(log_path) as f:
            existing = json.load(f)

    # Compute overall F1
    all_tp = sum(m["tp"] for f, m in field_metrics.items() if f != "_record_level")
    all_fp = sum(m["fp"] for f, m in field_metrics.items() if f != "_record_level")
    all_fn = sum(m["fn"] for f, m in field_metrics.items() if f != "_record_level")
    overall_p = all_tp / (all_tp + all_fp) if (all_tp + all_fp) > 0 else 0
    overall_r = all_tp / (all_tp + all_fn) if (all_tp + all_fn) > 0 else 0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0

    snapshot = {
        "n_observations": len(gold_data),
        "overall_f1": round(overall_f1, 3),
        "per_field": {f: m for f, m in field_metrics.items() if f != "_record_level"},
        "record_level": record_metrics,
        "brier_score": brier,
    }

    # Don't duplicate entries — just keep the latest
    existing.append(snapshot)
    with open(log_path, "w") as f:
        json.dump(existing, f, indent=2)

    # Print summary
    print(f"── Benchmark Report ───────────────────")
    print(f" Gold-standard observations : {len(gold_data)} fields across {record_metrics['records_extracted']} records")
    print(f" Per-field accuracy:")
    for field, m in sorted(field_metrics.items()):
        if field == "_record_level":
            continue
        print(f"   {field:30s}: {m['accuracy']*100:.1f}% (P={m['precision']:.2f}, R={m['recall']:.2f}, F1={m['f1']:.2f})")
    print(f" Record-level:")
    print(f"   Precision                : {record_metrics['precision']*100:.1f}%")
    print(f"   Recall                   : {record_metrics['recall']*100:.1f}%")
    print(f"   F1                       : {record_metrics['f1']*100:.1f}%")
    if brier is not None:
        print(f" Brier score               : {brier}")
    # Recommend weakest field
    trait_fields = {f: m for f, m in field_metrics.items() if f != "_record_level" and m["total"] >= 5}
    if trait_fields:
        weakest = min(trait_fields.items(), key=lambda x: x[1]["f1"])
        print(f" Recommendation            : {weakest[0]} needs more guide.md examples (F1={weakest[1]['f1']:.2f})")
    print(f"────────────────────────────────────────")


if __name__ == "__main__":
    main()
