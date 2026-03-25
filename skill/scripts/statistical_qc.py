#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 scripts/statistical_qc.py --project-root /path/to/project [--full]
# OUTPUT: qc_summary.json (always), qc_report.html (with --full flag)
"""
TraitTrawler Statistical QC
=============================
Generates diagnostic statistics and plots for a TraitTrawler project.

Usage:
    python3 statistical_qc.py --project-root /path/to/project [--full]

Without --full: generates qc_summary.json only (fast).
With --full: generates qc_report.html with embedded plots.

Dependencies: scipy, matplotlib (optional — degrades gracefully).
"""

import argparse
import base64
import csv
import io
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

try:
    from scipy import stats as sp_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def safe_read_csv(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def read_jsonl(path):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def read_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}


# ──────────────────────────────────────────────
# Chao1 estimator
# ──────────────────────────────────────────────

def chao1(species_list):
    """
    Compute Chao1 species richness estimator.
    species_list: list of species names (with repeats from multiple papers).
    Returns (S_obs, S_est, ci_low, ci_high).
    """
    counts = Counter(species_list)
    s_obs = len(counts)
    f1 = sum(1 for c in counts.values() if c == 1)  # singletons
    f2 = sum(1 for c in counts.values() if c == 2)  # doubletons

    if f2 == 0:
        # Bias-corrected Chao1 when f2 = 0
        s_est = s_obs + (f1 * (f1 - 1)) / 2 if f1 > 1 else s_obs
    else:
        s_est = s_obs + (f1 ** 2) / (2 * f2)

    # Approximate 95% CI (log-normal)
    if s_est > s_obs:
        c = s_est - s_obs
        var_c = f1 * (f1 - 1) / (2 * (f2 + 1)) + (f1 ** 2 * f2 * (f1 - 1) ** 2) / (4 * (f2 + 1) ** 4) if f2 > 0 else f1 * (f1 - 1) / 2
        if var_c > 0 and c > 0:
            t = math.log(1 + var_c / (c ** 2))
            ci_low = s_obs + c / math.exp(1.96 * math.sqrt(t))
            ci_high = s_obs + c * math.exp(1.96 * math.sqrt(t))
        else:
            ci_low = s_est
            ci_high = s_est
    else:
        ci_low = s_obs
        ci_high = s_obs

    return s_obs, s_est, ci_low, ci_high, f1, f2


def accumulation_curve(records):
    """
    Build a species accumulation curve ordered by processed_date.
    Returns list of (paper_index, cumulative_species).
    """
    # Sort by processed_date, then by DOI for stability
    sorted_recs = sorted(records, key=lambda r: (r.get("processed_date", ""), r.get("doi", "")))

    seen_species = set()
    curve = []
    paper_idx = 0
    current_doi = None

    for rec in sorted_recs:
        doi = rec.get("doi", "")
        if doi != current_doi:
            paper_idx += 1
            current_doi = doi
        sp = rec.get("species", "").strip()
        if sp:
            seen_species.add(sp)
        curve.append((paper_idx, len(seen_species)))

    # Deduplicate to one point per paper (last entry)
    paper_curve = {}
    for idx, count in curve:
        paper_curve[idx] = count
    return sorted(paper_curve.items())


# ──────────────────────────────────────────────
# Outlier detection
# ──────────────────────────────────────────────

def detect_outliers_continuous(values, group_name, field_name, alpha=0.05):
    """Grubbs' test for outliers in continuous data."""
    outliers = []
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (ValueError, TypeError):
            continue

    if len(nums) < 8:
        return outliers

    mean = sum(nums) / len(nums)
    sd = (sum((x - mean) ** 2 for x in nums) / (len(nums) - 1)) ** 0.5
    if sd == 0:
        return outliers

    for val in nums:
        z = abs(val - mean) / sd
        if z > 3.0:  # Simple Z-score fallback if no scipy
            outliers.append({
                "field": field_name,
                "value": val,
                "group": group_name,
                "z_score": round(z, 2),
                "reason": f"Z-score {z:.1f} > 3.0",
                "recommendation": "review"
            })

    if HAS_SCIPY and len(nums) >= 8:
        # Proper Grubbs' test
        n = len(nums)
        t_crit = sp_stats.t.ppf(1 - alpha / (2 * n), n - 2)
        g_crit = ((n - 1) / math.sqrt(n)) * math.sqrt(t_crit ** 2 / (n - 2 + t_crit ** 2))

        for val in nums:
            g = abs(val - mean) / sd
            if g > g_crit:
                # Already added by Z-score check, update reason
                for o in outliers:
                    if o["value"] == val and o["field"] == field_name:
                        o["reason"] = f"Grubbs G={g:.2f} > {g_crit:.2f}"
                        break

    return outliers


def detect_outliers_discrete(values, group_name, field_name):
    """Modal frequency method for discrete numeric data."""
    outliers = []
    nums = []
    for v in values:
        try:
            nums.append(int(float(v)))
        except (ValueError, TypeError):
            continue

    if len(nums) < 5:
        return outliers

    counts = Counter(nums)
    mode_val, mode_count = counts.most_common(1)[0]
    mode_freq = mode_count / len(nums)

    if mode_freq > 0.5:
        for val, cnt in counts.items():
            if cnt == 1 and val != mode_val:
                outliers.append({
                    "field": field_name,
                    "value": val,
                    "group": group_name,
                    "reason": f"Singleton in group where mode={mode_val} ({mode_freq:.0%})",
                    "recommendation": "likely error" if abs(val - mode_val) <= 2 else "possible variation"
                })

    return outliers


# ──────────────────────────────────────────────
# Confidence analysis
# ──────────────────────────────────────────────

def confidence_stats(records):
    confs = []
    for r in records:
        try:
            confs.append(float(r.get("extraction_confidence", 0)))
        except (ValueError, TypeError):
            pass
    if not confs:
        return {}
    return {
        "mean": round(sum(confs) / len(confs), 3),
        "median": round(sorted(confs)[len(confs) // 2], 3),
        "below_050": sum(1 for c in confs if c < 0.5),
        "below_075": sum(1 for c in confs if c < 0.75),
        "above_090": sum(1 for c in confs if c >= 0.9),
        "values": confs
    }


# ──────────────────────────────────────────────
# Main analysis
# ──────────────────────────────────────────────

def analyze(project_root):
    results = safe_read_csv(os.path.join(project_root, "results.csv"))
    run_log = read_jsonl(os.path.join(project_root, "state", "run_log.jsonl"))
    processed = read_json(os.path.join(project_root, "state", "processed.json"))
    taxonomy_cache = read_json(os.path.join(project_root, "state", "taxonomy_cache.json"))

    if not results:
        return {"error": "No records in results.csv", "total_records": 0}

    # Basic counts
    species_list = [r.get("species", "").strip() for r in results if r.get("species", "").strip()]
    unique_species = set(species_list)
    families = set(r.get("family", "").strip() for r in results if r.get("family", "").strip())
    flagged = sum(1 for r in results if r.get("flag_for_review", "").lower() in ("true", "1", "yes"))

    # Chao1
    s_obs, s_est, ci_low, ci_high, f1, f2 = chao1(species_list)
    pct_sampled = round(s_obs / s_est * 100, 1) if s_est > 0 else 100.0

    # Accumulation curve
    acc_curve = accumulation_curve(results)

    # Confidence
    conf = confidence_stats(results)

    # Source breakdown
    sources = Counter(r.get("pdf_source", "unknown") for r in results)

    # Session efficiency from run_log
    sessions = [e for e in run_log if e.get("event") == "session_end"]
    session_count = len(sessions)

    # Records per paper
    papers_processed = len(processed) if processed else 0
    rpp = round(len(results) / papers_processed, 1) if papers_processed > 0 else 0

    # Outlier detection
    all_outliers = []
    # Detect numeric fields from results
    if results:
        # Read config to find trait fields
        config_path = os.path.join(project_root, "collector_config.yaml")
        trait_fields = []
        core_fields = {
            "doi", "paper_title", "paper_authors", "first_author", "paper_year",
            "paper_journal", "session_id", "species", "family", "subfamily",
            "genus", "extraction_confidence", "flag_for_review", "source_type",
            "pdf_source", "pdf_filename", "pdf_url", "notes", "processed_date",
            "collection_locality", "country", "source_page", "source_context",
            "extraction_reasoning", "audit_status", "audit_session",
            "audit_prior_values", "accepted_name", "gbif_key", "taxonomy_note"
        }
        if results:
            all_fields = set(results[0].keys())
            trait_fields = [f for f in all_fields if f not in core_fields and f]

        group_field = "family"  # default grouping
        for tf in trait_fields:
            # Collect values by group
            by_group = defaultdict(list)
            for r in results:
                grp = r.get(group_field, "unknown").strip() or "unknown"
                val = r.get(tf, "").strip()
                if val:
                    by_group[grp].append(val)

            for grp, vals in by_group.items():
                if len(vals) < 5:
                    continue
                # Determine if discrete or continuous
                try:
                    nums = [float(v) for v in vals]
                    all_int = all(n == int(n) for n in nums)
                    unique_ratio = len(set(int(n) for n in nums)) / len(nums)

                    if all_int and unique_ratio < 0.3:
                        all_outliers.extend(detect_outliers_discrete(vals, grp, tf))
                    else:
                        all_outliers.extend(detect_outliers_continuous(vals, grp, tf))
                except (ValueError, TypeError):
                    pass  # categorical — skip for now

    summary = {
        "total_records": len(results),
        "unique_species": len(unique_species),
        "families": len(families),
        "chao1_estimate": round(s_est, 0),
        "chao1_ci_low": round(ci_low, 0),
        "chao1_ci_high": round(ci_high, 0),
        "pct_sampled": pct_sampled,
        "singletons": f1,
        "doubletons": f2,
        "mean_confidence": conf.get("mean", 0),
        "median_confidence": conf.get("median", 0),
        "flagged_for_review": flagged,
        "outliers_detected": len(all_outliers),
        "sessions_completed": session_count,
        "papers_processed": papers_processed,
        "records_per_paper_mean": rpp,
        "source_breakdown": dict(sources),
        "accumulation_curve": acc_curve,
        "confidence_values": conf.get("values", []),
        "outliers": all_outliers,
        "generated": datetime.now().isoformat()
    }

    return summary


def generate_html_report(summary, project_root):
    """Generate a self-contained HTML QC report with embedded charts."""
    if not HAS_MPL:
        return "<html><body><h1>QC Report</h1><p>matplotlib not available. Install with: pip install matplotlib</p></body></html>"

    plots = {}

    # 1. Species accumulation curve
    acc = summary.get("accumulation_curve", [])
    if acc:
        fig, ax = plt.subplots(figsize=(8, 5))
        papers = [p[0] for p in acc]
        species = [p[1] for p in acc]
        ax.plot(papers, species, "b-", linewidth=2, label="Observed species")

        s_est = summary.get("chao1_estimate", 0)
        if s_est > 0:
            ax.axhline(y=s_est, color="r", linestyle="--", alpha=0.7,
                       label=f"Chao1 estimate: {s_est:.0f}")
            ci_low = summary.get("chao1_ci_low", 0)
            ci_high = summary.get("chao1_ci_high", 0)
            ax.axhspan(ci_low, ci_high, alpha=0.1, color="red", label="95% CI")

        ax.set_xlabel("Papers processed", fontsize=12)
        ax.set_ylabel("Cumulative species", fontsize=12)
        ax.set_title("Species Accumulation Curve", fontsize=14)
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        plt.close(fig)
        plots["accumulation"] = base64.b64encode(buf.getvalue()).decode()

    # 2. Confidence distribution
    confs = summary.get("confidence_values", [])
    if confs:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.hist(confs, bins=20, range=(0, 1), color="#4a90d9", edgecolor="white", alpha=0.8)
        mean_c = summary.get("mean_confidence", 0)
        ax.axvline(x=mean_c, color="red", linestyle="--", label=f"Mean: {mean_c:.2f}")
        ax.axvline(x=0.75, color="orange", linestyle=":", alpha=0.7, label="Flag threshold (0.75)")
        ax.set_xlabel("Extraction Confidence", fontsize=12)
        ax.set_ylabel("Record Count", fontsize=12)
        ax.set_title("Confidence Distribution", fontsize=14)
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        plt.close(fig)
        plots["confidence"] = base64.b64encode(buf.getvalue()).decode()

    # 3. Source breakdown
    sources = summary.get("source_breakdown", {})
    if sources:
        fig, ax = plt.subplots(figsize=(7, 5))
        labels = list(sources.keys())
        values = list(sources.values())
        colors = plt.cm.Set3(range(len(labels)))
        ax.pie(values, labels=labels, autopct="%1.0f%%", colors=colors, startangle=90)
        ax.set_title("Records by Source", fontsize=14)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        plt.close(fig)
        plots["sources"] = base64.b64encode(buf.getvalue()).decode()

    # Build HTML
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>TraitTrawler QC Report</title>
<style>
body {{ font: 14px/1.6 system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; }}
h1 {{ color: #1a1a2e; border-bottom: 2px solid #4a90d9; padding-bottom: 10px; }}
h2 {{ color: #4a90d9; margin-top: 30px; }}
.kpi {{ display: flex; flex-wrap: wrap; gap: 15px; margin: 20px 0; }}
.kpi-card {{ background: #f8f9fa; border-radius: 8px; padding: 15px 20px; flex: 1; min-width: 150px; text-align: center; }}
.kpi-value {{ font-size: 28px; font-weight: bold; color: #1a1a2e; }}
.kpi-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
.plot {{ text-align: center; margin: 20px 0; }}
.plot img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
th {{ background: #f8f9fa; font-weight: 600; }}
.footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #999; font-size: 12px; }}
</style></head><body>
<h1>TraitTrawler QC Report</h1>
<p>Generated: {summary.get('generated', 'unknown')}</p>

<div class="kpi">
<div class="kpi-card"><div class="kpi-value">{summary['total_records']:,}</div><div class="kpi-label">Records</div></div>
<div class="kpi-card"><div class="kpi-value">{summary['unique_species']:,}</div><div class="kpi-label">Species</div></div>
<div class="kpi-card"><div class="kpi-value">{summary.get('chao1_estimate', 0):,.0f}</div><div class="kpi-label">Chao1 Estimate</div></div>
<div class="kpi-card"><div class="kpi-value">{summary.get('pct_sampled', 0):.1f}%</div><div class="kpi-label">Sampled</div></div>
<div class="kpi-card"><div class="kpi-value">{summary.get('mean_confidence', 0):.2f}</div><div class="kpi-label">Mean Confidence</div></div>
<div class="kpi-card"><div class="kpi-value">{summary.get('outliers_detected', 0)}</div><div class="kpi-label">Outliers</div></div>
</div>
"""

    if "accumulation" in plots:
        html += f'<h2>Species Accumulation</h2><div class="plot"><img src="data:image/png;base64,{plots["accumulation"]}"></div>\n'
        html += f'<p>Chao1 estimate: {summary.get("chao1_estimate", 0):,.0f} species (95% CI: {summary.get("chao1_ci_low", 0):,.0f}–{summary.get("chao1_ci_high", 0):,.0f}). Singletons: {summary.get("singletons", 0)}, Doubletons: {summary.get("doubletons", 0)}.</p>\n'

    if "confidence" in plots:
        html += f'<h2>Confidence Distribution</h2><div class="plot"><img src="data:image/png;base64,{plots["confidence"]}"></div>\n'

    if "sources" in plots:
        html += f'<h2>Source Breakdown</h2><div class="plot"><img src="data:image/png;base64,{plots["sources"]}"></div>\n'

    # Outlier table
    outliers = summary.get("outliers", [])
    if outliers:
        html += "<h2>Outliers Detected</h2>\n<table><tr><th>Field</th><th>Value</th><th>Group</th><th>Reason</th><th>Recommendation</th></tr>\n"
        for o in outliers[:50]:
            html += f"<tr><td>{o.get('field','')}</td><td>{o.get('value','')}</td><td>{o.get('group','')}</td><td>{o.get('reason','')}</td><td>{o.get('recommendation','')}</td></tr>\n"
        html += "</table>\n"

    html += f'<div class="footer">TraitTrawler Statistical QC | {summary["total_records"]} records | {summary["sessions_completed"]} sessions</div>\n'
    html += "</body></html>"
    return html


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler Statistical QC")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--full", action="store_true", help="Generate full HTML report with plots")

    args = parser.parse_args()
    project_root = args.project_root

    summary = analyze(project_root)

    # Always write summary JSON
    summary_path = os.path.join(project_root, "qc_summary.json")
    # Remove non-serializable items for JSON output
    json_summary = {k: v for k, v in summary.items() if k != "confidence_values"}
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(json_summary, f, indent=2)
    print(f"QC summary written to {summary_path}", file=sys.stderr)

    if args.full:
        html = generate_html_report(summary, project_root)
        report_path = os.path.join(project_root, "qc_report.html")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"QC report written to {report_path}", file=sys.stderr)

    # Print summary to stdout for the agent
    print(json.dumps({
        "total_records": summary.get("total_records", 0),
        "unique_species": summary.get("unique_species", 0),
        "chao1_estimate": summary.get("chao1_estimate", 0),
        "pct_sampled": summary.get("pct_sampled", 0),
        "mean_confidence": summary.get("mean_confidence", 0),
        "outliers_detected": summary.get("outliers_detected", 0),
        "singletons": summary.get("singletons", 0),
        "doubletons": summary.get("doubletons", 0),
        "records_per_paper_mean": summary.get("records_per_paper_mean", 0),
    }, indent=2))


if __name__ == "__main__":
    main()
