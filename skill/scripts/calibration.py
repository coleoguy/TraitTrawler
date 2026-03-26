#!/usr/bin/env python3
"""
Confidence calibration for TraitTrawler.

Fits an isotonic regression model to map raw extraction confidence scores
to calibrated probabilities. Computes Expected Calibration Error (ECE)
and generates reliability diagrams.

Usage:
    python3 scripts/calibration.py --project-root .
    python3 scripts/calibration.py --project-root . --full  # with plots
"""

import argparse
import json
import os
import sys
import numpy as np
from pathlib import Path


def load_calibration_data(project_root):
    """Load paired (predicted_confidence, correct) observations."""
    path = Path(project_root) / "state" / "calibration_data.jsonl"
    if not path.exists():
        return [], [], []

    predictions = []
    actuals = []
    fields = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("predicted_confidence") is not None:
                predictions.append(float(entry["predicted_confidence"]))
                actuals.append(1.0 if entry.get("correct", False) else 0.0)
                fields.append(entry.get("field", "unknown"))

    return predictions, actuals, fields


def compute_ece(predictions, actuals, n_bins=10):
    """Compute Expected Calibration Error."""
    predictions = np.array(predictions)
    actuals = np.array(actuals)

    if len(predictions) == 0:
        return 0.0, [], [], []

    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_centers = []
    bin_accuracies = []
    bin_confidences = []
    bin_counts = []

    ece = 0.0
    for i in range(n_bins):
        mask = (predictions >= bin_edges[i]) & (predictions < bin_edges[i + 1])
        if i == n_bins - 1:  # include right edge for last bin
            mask = (predictions >= bin_edges[i]) & (predictions <= bin_edges[i + 1])

        count = mask.sum()
        if count > 0:
            avg_confidence = predictions[mask].mean()
            avg_accuracy = actuals[mask].mean()
            ece += (count / len(predictions)) * abs(avg_accuracy - avg_confidence)

            bin_centers.append((bin_edges[i] + bin_edges[i + 1]) / 2)
            bin_accuracies.append(float(avg_accuracy))
            bin_confidences.append(float(avg_confidence))
            bin_counts.append(int(count))

    return float(ece), bin_centers, bin_accuracies, bin_confidences


def fit_isotonic_model(predictions, actuals):
    """Fit isotonic regression for confidence calibration."""
    try:
        from sklearn.isotonic import IsotonicRegression
        ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        ir.fit(predictions, actuals)
        return {
            "method": "isotonic_regression",
            "thresholds_x": ir.X_thresholds_.tolist() if hasattr(ir, 'X_thresholds_') else [],
            "thresholds_y": ir.y_thresholds_.tolist() if hasattr(ir, 'y_thresholds_') else [],
        }
    except ImportError:
        # Fallback: binned calibration
        bins = np.linspace(0, 1, 11)
        bin_map = {}
        preds = np.array(predictions)
        acts = np.array(actuals)
        for i in range(10):
            mask = (preds >= bins[i]) & (preds < bins[i + 1])
            if i == 9:
                mask = (preds >= bins[i]) & (preds <= bins[i + 1])
            if mask.sum() > 0:
                bin_map[f"{bins[i]:.1f}-{bins[i+1]:.1f}"] = {
                    "n": int(mask.sum()),
                    "predicted_mean": float(preds[mask].mean()),
                    "calibrated": float(acts[mask].mean()),
                }
        return {"method": "binned_calibration", "bins": bin_map}


def fit_per_field(predictions, actuals, fields, min_observations=30):
    """Fit calibration models per field."""
    unique_fields = set(fields)
    per_field = {}
    for field in unique_fields:
        mask = [i for i, f in enumerate(fields) if f == field]
        if len(mask) >= min_observations:
            field_preds = [predictions[i] for i in mask]
            field_acts = [actuals[i] for i in mask]
            ece, _, _, _ = compute_ece(field_preds, field_acts)
            model = fit_isotonic_model(field_preds, field_acts)
            per_field[field] = {
                "n_observations": len(mask),
                "ece": round(ece, 4),
                "model": model,
            }
    return per_field


def generate_reliability_plot(bin_centers, bin_accuracies, ece, output_path):
    """Generate reliability diagram as PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(1, 1, figsize=(6, 6))
        ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Perfect calibration")
        ax.bar(
            bin_centers,
            bin_accuracies,
            width=0.08,
            alpha=0.7,
            color="#2196F3",
            edgecolor="#1565C0",
            label=f"TraitTrawler (ECE={ece:.3f})",
        )
        ax.set_xlabel("Predicted Confidence", fontsize=12)
        ax.set_ylabel("Observed Accuracy", fontsize=12)
        ax.set_title("Confidence Calibration (Reliability Diagram)", fontsize=13)
        ax.legend(loc="upper left", fontsize=10)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()
        return True
    except ImportError:
        return False


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler confidence calibration")
    parser.add_argument("--project-root", required=True, help="Project root directory")
    parser.add_argument("--full", action="store_true", help="Generate plots and HTML report")
    args = parser.parse_args()

    project_root = args.project_root
    predictions, actuals, fields = load_calibration_data(project_root)

    if len(predictions) < 10:
        print(f"Insufficient calibration data ({len(predictions)} observations, need >= 10).")
        print("Calibration data accumulates from: benchmarks, audits, and user corrections.")
        summary = {
            "n_observations": len(predictions),
            "status": "insufficient_data",
            "message": "Need >= 10 observations for calibration",
        }
        out_path = Path(project_root) / "state" / "calibration_model.json"
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)
        return

    # Compute ECE
    ece, bin_centers, bin_accuracies, bin_confidences = compute_ece(predictions, actuals)

    # Compute Brier score
    preds_arr = np.array(predictions)
    acts_arr = np.array(actuals)
    brier = float(np.mean((preds_arr - acts_arr) ** 2))

    # Maximum Calibration Error
    if bin_accuracies and bin_confidences:
        mce = float(max(abs(a - c) for a, c in zip(bin_accuracies, bin_confidences)))
    else:
        mce = 0.0

    # Fit global model
    global_model = fit_isotonic_model(predictions, actuals)

    # Fit per-field models
    per_field = fit_per_field(predictions, actuals, fields)

    # Save calibration model
    calibration = {
        "n_observations": len(predictions),
        "status": "calibrated",
        "ece": round(ece, 4),
        "mce": round(mce, 4),
        "brier_score": round(brier, 4),
        "global_model": global_model,
        "per_field": per_field,
        "date": str(np.datetime64("today")),
    }

    out_path = Path(project_root) / "state" / "calibration_model.json"
    with open(out_path, "w") as f:
        json.dump(calibration, f, indent=2)

    # Print summary
    print(f"── Calibration ────────────────────")
    print(f" Calibration data  : {len(predictions)} observations ({len(set(fields))} fields)")
    print(f" Global ECE        : {ece:.3f} ({'well-calibrated' if ece < 0.05 else 'needs improvement' if ece < 0.15 else 'poorly calibrated'})")
    print(f" Brier score       : {brier:.3f}")
    if per_field:
        worst_field = max(per_field.items(), key=lambda x: x[1]["ece"])
        print(f" Worst field ECE   : {worst_field[0]} ({worst_field[1]['ece']:.3f})")
    print(f"────────────────────────────────────")

    # Generate plot if requested
    if args.full and bin_centers:
        plot_path = Path(project_root) / "calibration_reliability.png"
        if generate_reliability_plot(bin_centers, bin_accuracies, ece, plot_path):
            print(f"\nReliability diagram saved to {plot_path}")
        else:
            print("\nmatplotlib not available — skipping reliability diagram")


if __name__ == "__main__":
    main()
