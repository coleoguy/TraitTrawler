#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 dashboard_generator.py [--project-root /path/to/root]
# OUTPUT: Creates {project_root}/dashboard.html (self-contained, zero external deps)
"""
TraitTrawler Dashboard Generator
=================================
Reads project data files and produces a self-contained HTML dashboard with
CSS/SVG charts, interactive column picker, and activity panel.

No external dependencies (no CDN, no Chart.js). Works offline and via
file:// protocol. Auto-refreshes every 60 seconds.

Usage:
    python3 dashboard_generator.py [--project-root /path/to/root]
"""

import argparse
import csv
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime


# Fields that already have dedicated charts or are not chartable
_CORE_FIELDS = {
    "doi", "paper_title", "paper_authors", "first_author", "paper_year",
    "paper_journal", "session_id", "species", "family", "subfamily", "genus",
    "extraction_confidence", "flag_for_review", "source_type",
    "pdf_source", "pdf_filename", "pdf_url", "notes", "processed_date",
    "collection_locality", "country", "voucher_info",
    "source_page", "source_context", "extraction_reasoning",
    "accepted_name", "gbif_key", "taxonomy_note",
    "audit_status", "audit_session", "audit_prior_values",
}

_SKIP_FIELDS = {
    "notes", "pdf_url", "pdf_filename", "paper_title", "paper_authors",
    "doi", "collection_locality", "voucher_info", "karyotype_formula",
    "chromosome_morphology", "heterochromatin_pattern", "NOR_position",
}

_MAX_CATEGORICAL = 25


# ── Data loading ─────────────────────────────────────────────────────────

def safe_read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def safe_read_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}


def safe_read_jsonl_tail(path, n=5):
    """Read last n lines of a JSONL file."""
    if not os.path.exists(path):
        return []
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)
        return [json.loads(l) for l in lines[-n:]]
    except Exception:
        return []


def read_config(project_root):
    config_path = os.path.join(project_root, "collector_config.yaml")
    project_name = "TraitTrawler"
    trait_name = ""
    output_fields = []

    if not os.path.exists(config_path):
        return project_name, trait_name, output_fields

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'^project_name:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        if m:
            project_name = m.group(1)
        m = re.search(r'^trait_name:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        if m:
            trait_name = m.group(1)
        in_fields = False
        for line in content.split("\n"):
            stripped = line.strip()
            if re.match(r'^output_fields\s*:', stripped):
                in_fields = True
                continue
            if in_fields:
                if stripped.startswith("- "):
                    field = stripped[2:].strip().strip("'\"")
                    if field and not field.startswith("#"):
                        output_fields.append(field)
                elif stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                    break
    except Exception:
        pass
    return project_name, trait_name, output_fields


def classify_field(values):
    if not values:
        return "skip", None
    numbers = []
    for v in values:
        try:
            numbers.append(float(v) if "." in str(v) else int(v))
        except (ValueError, TypeError):
            pass
    if len(numbers) > 0.6 * len(values) and len(set(numbers)) > _MAX_CATEGORICAL:
        return "numeric", numbers
    if len(numbers) > 0.6 * len(values) and len(set(numbers)) <= _MAX_CATEGORICAL:
        counts = Counter(str(int(n)) if isinstance(n, (int, float)) and n == int(n) else str(n) for n in numbers)
        return "categorical", counts
    counts = Counter(v for v in values if v)
    if len(counts) > _MAX_CATEGORICAL or len(counts) < 2:
        return "skip", None
    return "categorical", counts


# ── SVG/CSS chart builders ───────────────────────────────────────────────

def _h(text):
    """HTML-escape a string."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_PALETTE = [
    "#38bdf8", "#4ade80", "#fbbf24", "#f87171", "#a78bfa",
    "#fb923c", "#2dd4bf", "#e879f9", "#60a5fa", "#34d399",
    "#facc15", "#f472b6", "#818cf8", "#a3e635", "#22d3ee",
]


def svg_bar_chart(labels, values, title="", width=400, height=200):
    """Generate an inline SVG horizontal bar chart."""
    if not values:
        return f'<div class="chart-empty">{_h(title)}: no data</div>'
    max_val = max(values) if values else 1
    bar_h = min(24, max(14, (height - 30) // len(labels)))
    total_h = bar_h * len(labels) + 30
    lines = [f'<svg viewBox="0 0 {width} {total_h}" class="chart-svg">']
    if title:
        lines.append(f'<text x="{width//2}" y="16" class="chart-title">{_h(title)}</text>')
    y = 28
    for i, (label, val) in enumerate(zip(labels, values)):
        pct = (val / max_val * 0.65) if max_val else 0
        bw = max(2, int(pct * width))
        color = _PALETTE[i % len(_PALETTE)]
        lbl = _h(str(label))
        if len(lbl) > 18:
            lbl = lbl[:16] + ".."
        lines.append(f'<text x="2" y="{y + bar_h - 4}" class="bar-label">{lbl}</text>')
        lines.append(f'<rect x="{int(width*0.32)}" y="{y}" width="{bw}" height="{bar_h - 3}" '
                     f'fill="{color}" rx="3"/>')
        lines.append(f'<text x="{int(width*0.32) + bw + 4}" y="{y + bar_h - 4}" '
                     f'class="bar-val">{val}</text>')
        y += bar_h
    lines.append('</svg>')
    return "\n".join(lines)


def svg_line_chart(points, title="", width=500, height=200):
    """Generate an inline SVG line chart from (label, value) pairs."""
    if not points or len(points) < 2:
        return f'<div class="chart-empty">{_h(title)}: insufficient data</div>'
    values = [p[1] for p in points]
    max_val = max(values) if values else 1
    min_val = min(values) if values else 0
    span = max_val - min_val if max_val != min_val else 1
    pad_l, pad_r, pad_t, pad_b = 50, 20, 30, 30
    cw = width - pad_l - pad_r
    ch = height - pad_t - pad_b
    n = len(points)

    coords = []
    for i, (_, v) in enumerate(points):
        x = pad_l + (i / max(1, n - 1)) * cw
        y = pad_t + ch - ((v - min_val) / span) * ch
        coords.append((x, y))

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    fill_pts = polyline + f" {coords[-1][0]:.1f},{pad_t + ch} {coords[0][0]:.1f},{pad_t + ch}"

    lines = [f'<svg viewBox="0 0 {width} {height}" class="chart-svg">']
    if title:
        lines.append(f'<text x="{width//2}" y="18" class="chart-title">{_h(title)}</text>')
    # Y-axis labels
    for i in range(5):
        yv = min_val + (span * i / 4)
        yp = pad_t + ch - (ch * i / 4)
        lines.append(f'<text x="{pad_l - 4}" y="{yp + 4}" class="axis-label">{int(yv)}</text>')
        lines.append(f'<line x1="{pad_l}" y1="{yp}" x2="{width - pad_r}" y2="{yp}" '
                     f'stroke="#334155" stroke-width="0.5"/>')
    # Fill area
    lines.append(f'<polygon points="{fill_pts}" fill="#38bdf8" fill-opacity="0.15"/>')
    # Line
    lines.append(f'<polyline points="{polyline}" fill="none" stroke="#38bdf8" stroke-width="2"/>')
    # X-axis: show ~5 evenly spaced labels with smart time formatting
    n_labels = min(5, n)
    label_indices = [int(i * (n - 1) / max(1, n_labels - 1)) for i in range(n_labels)]
    # Determine if data spans single day or multiple days
    first_ts = str(points[0][0])
    last_ts = str(points[-1][0])
    same_day = first_ts[:10] == last_ts[:10] if len(first_ts) >= 10 and len(last_ts) >= 10 else False
    for idx in label_indices:
        lbl = str(points[idx][0])
        if same_day and len(lbl) >= 16:
            lbl = lbl[11:16]  # just HH:MM
        elif len(lbl) >= 16:
            lbl = lbl[5:16]  # MM-DDTHH:MM
        x = coords[idx][0]
        lines.append(f'<text x="{x}" y="{height - 6}" class="axis-label">{_h(lbl)}</text>')
    lines.append('</svg>')
    return "\n".join(lines)


def css_doughnut(labels, values, title=""):
    """Generate a CSS conic-gradient doughnut chart."""
    if not values or sum(values) == 0:
        return f'<div class="chart-empty">{_h(title)}: no data</div>'
    total = sum(values)
    segments = []
    angle = 0
    for i, (label, val) in enumerate(zip(labels, values)):
        color = _PALETTE[i % len(_PALETTE)]
        pct = val / total * 360
        segments.append(f"{color} {angle:.1f}deg {angle + pct:.1f}deg")
        angle += pct
    gradient = ", ".join(segments)

    legend = []
    for i, (label, val) in enumerate(zip(labels, values)):
        color = _PALETTE[i % len(_PALETTE)]
        pct = val / total * 100
        lbl = _h(str(label))
        if len(lbl) > 22:
            lbl = lbl[:20] + ".."
        legend.append(f'<div class="legend-item">'
                     f'<span class="legend-dot" style="background:{color}"></span>'
                     f'{lbl} <span class="legend-val">({val}, {pct:.0f}%)</span></div>')

    return f"""<div class="doughnut-wrap">
  <div class="doughnut-title">{_h(title)}</div>
  <div class="doughnut-row">
    <div class="doughnut" style="background: conic-gradient({gradient})"></div>
    <div class="legend">{''.join(legend)}</div>
  </div>
</div>"""


# ── Main generator ───────────────────────────────────────────────────────

def generate_dashboard(project_root):
    results = safe_read_csv(os.path.join(project_root, "results.csv"))
    leads = safe_read_csv(os.path.join(project_root, "leads.csv"))
    processed = safe_read_json(os.path.join(project_root, "state", "processed.json"))
    progress = safe_read_jsonl_tail(
        os.path.join(project_root, "state", "live_progress.jsonl"), n=5)
    project_name, trait_name, output_fields = read_config(project_root)

    n_records = len(results)
    n_papers = len(processed) if isinstance(processed, dict) else 0
    species_set = {r.get("species", "") for r in results if r.get("species")}
    family_counts = Counter(r.get("family", "Unknown") for r in results if r.get("family"))
    n_families = len(family_counts)
    n_leads = len(leads)

    # Mean confidence
    confs = []
    for r in results:
        try:
            confs.append(float(r.get("extraction_confidence", "")))
        except (ValueError, TypeError):
            pass
    mean_conf = sum(confs) / len(confs) if confs else 0

    n_flagged = sum(1 for r in results
                    if str(r.get("flag_for_review", "")).lower() in ("true", "1", "yes"))

    # ── Charts ───────────────────────────────────────────────────────
    # Cumulative timeline
    date_counts = Counter(r.get("processed_date") or "" for r in results)
    sorted_dates = sorted(((d, c) for d, c in date_counts.items() if d), key=lambda x: x[0])
    cumulative = []
    running = 0
    for d, c in sorted_dates:
        running += c
        cumulative.append((d, running))
    timeline_svg = svg_line_chart(cumulative, title="Cumulative Records")

    # Family breakdown (top 15)
    top_fam = family_counts.most_common(15)
    family_chart = svg_bar_chart(
        [f[0] for f in top_fam], [f[1] for f in top_fam], title="Records by Family")

    # Confidence distribution
    conf_buckets = Counter()
    for c in confs:
        if c >= 0.9:
            conf_buckets["0.90-1.00"] += 1
        elif c >= 0.8:
            conf_buckets["0.80-0.89"] += 1
        elif c >= 0.7:
            conf_buckets["0.70-0.79"] += 1
        elif c >= 0.6:
            conf_buckets["0.60-0.69"] += 1
        else:
            conf_buckets["< 0.60"] += 1
    conf_order = ["0.90-1.00", "0.80-0.89", "0.70-0.79", "0.60-0.69", "< 0.60"]
    conf_chart = svg_bar_chart(conf_order, [conf_buckets.get(k, 0) for k in conf_order],
                                title="Confidence Distribution")

    # Source type
    source_counts = Counter(r.get("pdf_source", "unknown") or "unknown" for r in results)
    src_items = source_counts.most_common(10)
    source_chart = css_doughnut(
        [s[0] for s in src_items], [s[1] for s in src_items], title="Source Breakdown")

    # Trait-specific charts
    trait_fields = [f for f in output_fields if f not in _CORE_FIELDS and f not in _SKIP_FIELDS]
    trait_charts_html = []
    for field in trait_fields:
        values = [r.get(field, "") for r in results if r.get(field, "")]
        classification, data = classify_field(values)
        if classification == "skip" or not data:
            continue
        title = field.replace("_", " ").title()
        if classification == "categorical":
            items = data.most_common(15)
            trait_charts_html.append(css_doughnut(
                [it[0] for it in items], [it[1] for it in items], title=title))
        elif classification == "numeric":
            # Simple histogram via bar chart
            bins = _histogram_bins(data)
            trait_charts_html.append(svg_bar_chart(
                [b[0] for b in bins], [b[1] for b in bins], title=title))

    # ── Activity panel ───────────────────────────────────────────────
    activity_html = ""
    if progress:
        last = progress[-1]
        activity_items = []
        for p in reversed(progress):
            paper = _h(p.get("paper", ""))
            recs = p.get("records", 0)
            ts = p.get("timestamp", "")
            if len(ts) > 16:
                ts = ts[11:16]  # just HH:MM
            activity_items.append(
                f'<div class="activity-item">'
                f'<span class="activity-time">{ts}</span> '
                f'{paper} — <strong>{recs}</strong> records</div>')
        queue_rem = last.get("queue_remaining", "?")
        total_now = last.get("total_records", n_records)
        activity_html = f"""
<div class="activity-panel">
  <div class="activity-header">Recent Activity <span class="activity-queue">Queue: {queue_rem} remaining</span></div>
  {''.join(activity_items)}
</div>"""

    # ── Data table (last 200 rows as JSON) ───────────────────────────
    all_fields = []
    if results:
        all_fields = list(results[0].keys())
    table_rows = results[-200:] if len(results) > 200 else results
    # Sanitize for JSON embedding
    table_json = json.dumps(table_rows, ensure_ascii=True)
    fields_json = json.dumps(all_fields)

    # ── Lead summary ─────────────────────────────────────────────────
    lead_statuses = Counter(l.get("lead_status", l.get("status", "new")) for l in leads)
    lead_items = lead_statuses.most_common(10)
    lead_chart = ""
    if lead_items:
        lead_chart = css_doughnut(
            [it[0] for it in lead_items], [it[1] for it in lead_items],
            title="Lead Status")

    # ── Assemble HTML ────────────────────────────────────────────────
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trait_section = ""
    if trait_charts_html:
        trait_label = (trait_name or "Trait").title()
        cards = "".join('<div class="chart-card">' + c + '</div>' for c in trait_charts_html)
        trait_section = (
            f'<div class="section-header">{_h(trait_label)} Data</div>'
            f'<div class="chart-grid">{cards}</div>'
        )

    html = _build_html(
        project_name=project_name,
        now=now,
        n_records=n_records,
        n_species=len(species_set),
        n_families=n_families,
        n_papers=n_papers,
        n_leads=n_leads,
        mean_conf=mean_conf,
        n_flagged=n_flagged,
        timeline_svg=timeline_svg,
        family_chart=family_chart,
        conf_chart=conf_chart,
        source_chart=source_chart,
        activity_html=activity_html,
        trait_section=trait_section,
        lead_chart=lead_chart,
        table_json=table_json,
        fields_json=fields_json,
        n_table_rows=len(table_rows),
    )

    out_path = os.path.join(project_root, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to {out_path}")
    print(f"  Records: {n_records} | Species: {len(species_set)} | "
          f"Families: {n_families} | Papers: {n_papers}")
    return out_path


def _histogram_bins(data, n_bins=15):
    """Bin numeric data into histogram buckets. Returns [(label, count), ...]."""
    if not data:
        return []
    all_int = all(isinstance(v, int) or (isinstance(v, float) and v == int(v)) for v in data)
    if all_int:
        int_data = [int(v) for v in data]
        hist = Counter(int_data)
        if len(hist) <= 30:
            return sorted(hist.items())
        # Bin into groups
        mn, mx = min(int_data), max(int_data)
        bin_size = max(1, (mx - mn + 1) // n_bins)
        bins = Counter()
        for v in int_data:
            b = ((v - mn) // bin_size) * bin_size + mn
            bins[f"{b}-{b + bin_size - 1}"] = bins.get(f"{b}-{b + bin_size - 1}", 0) + 1
        return sorted(bins.items())
    else:
        mn, mx = min(data), max(data)
        if mn == mx:
            return [(str(mn), len(data))]
        step = (mx - mn) / n_bins
        bins = Counter()
        for v in data:
            b = int((v - mn) / step)
            b = min(b, n_bins - 1)
            lo = mn + b * step
            bins[f"{lo:.1f}"] = bins.get(f"{lo:.1f}", 0) + 1
        return sorted(bins.items())


def _build_html(**d):
    conf_color = "#4ade80" if d["mean_conf"] >= 0.85 else (
        "#fbbf24" if d["mean_conf"] >= 0.7 else "#f87171")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_h(d['project_name'])} — TraitTrawler Dashboard</title>
<style>
:root {{
  --bg: #0f172a; --card: #1e293b; --border: #334155;
  --text: #e2e8f0; --muted: #94a3b8; --accent: #38bdf8;
  --green: #4ade80; --amber: #fbbf24; --red: #f87171;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg); color: var(--text); padding: 20px; line-height: 1.5;
}}
.header {{ text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }}
.header h1 {{ font-size: 24px; font-weight: 700; color: var(--accent); margin-bottom: 2px; }}
.header .sub {{ color: var(--muted); font-size: 13px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }}
.kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px; text-align: center; }}
.kpi .val {{ font-size: 28px; font-weight: 700; color: var(--accent); }}
.kpi .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi.highlight .val {{ color: var(--green); }}
.kpi.warn .val {{ color: var(--amber); }}

.activity-panel {{
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px; margin-bottom: 20px;
}}
.activity-header {{ font-size: 14px; font-weight: 600; color: var(--accent); margin-bottom: 8px; }}
.activity-queue {{ float: right; color: var(--muted); font-weight: 400; font-size: 12px; }}
.activity-item {{ font-size: 13px; color: var(--text); padding: 3px 0; border-bottom: 1px solid var(--border); }}
.activity-item:last-child {{ border-bottom: none; }}
.activity-time {{ color: var(--muted); font-family: monospace; font-size: 12px; }}

.section-header {{
  font-size: 16px; font-weight: 600; color: var(--accent);
  margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
}}
.chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; margin-bottom: 20px; }}
.chart-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }}
.chart-empty {{ color: var(--muted); font-size: 13px; padding: 20px; text-align: center; }}

.chart-svg {{ width: 100%; height: auto; }}
.chart-svg .chart-title {{ fill: var(--accent); font-size: 13px; font-weight: 600; text-anchor: middle; }}
.chart-svg .bar-label {{ fill: var(--muted); font-size: 11px; }}
.chart-svg .bar-val {{ fill: var(--text); font-size: 11px; }}
.chart-svg .axis-label {{ fill: var(--muted); font-size: 10px; text-anchor: end; }}

.doughnut-wrap {{ padding: 4px; }}
.doughnut-title {{ font-size: 13px; font-weight: 600; color: var(--accent); margin-bottom: 8px; }}
.doughnut-row {{ display: flex; align-items: center; gap: 16px; }}
.doughnut {{
  width: 120px; height: 120px; border-radius: 50%; flex-shrink: 0;
  position: relative;
}}
.doughnut::after {{
  content: ''; position: absolute;
  top: 25%; left: 25%; width: 50%; height: 50%;
  background: var(--card); border-radius: 50%;
}}
.legend {{ font-size: 12px; }}
.legend-item {{ padding: 1px 0; white-space: nowrap; }}
.legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
.legend-val {{ color: var(--muted); }}

/* Column picker + data table */
.table-section {{ margin-top: 24px; }}
.picker-toggle {{
  background: var(--card); border: 1px solid var(--border); color: var(--accent);
  padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px;
  margin-bottom: 8px; display: inline-block;
}}
.picker-toggle:hover {{ background: var(--border); }}
.picker-panel {{
  display: none; background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px; margin-bottom: 12px;
  max-height: 200px; overflow-y: auto;
  column-count: 3; column-gap: 16px;
}}
.picker-panel.open {{ display: block; }}
.picker-panel label {{
  display: block; font-size: 12px; color: var(--text); padding: 2px 0;
  cursor: pointer; break-inside: avoid;
}}
.picker-panel label:hover {{ color: var(--accent); }}
.picker-panel input {{ margin-right: 6px; }}

.data-table-wrap {{ overflow-x: auto; max-height: 500px; overflow-y: auto; }}
.data-table {{
  width: 100%; border-collapse: collapse; font-size: 12px;
}}
.data-table th {{
  position: sticky; top: 0; background: var(--card);
  text-align: left; padding: 8px 6px; color: var(--accent);
  border-bottom: 2px solid var(--border); white-space: nowrap;
  cursor: pointer;
}}
.data-table th:hover {{ color: var(--green); }}
.data-table td {{
  padding: 5px 6px; border-bottom: 1px solid var(--border);
  max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.data-table tr:hover td {{ background: rgba(56, 189, 248, 0.05); }}
.conf-high {{ color: var(--green); }}
.conf-mid {{ color: var(--amber); }}
.conf-low {{ color: var(--red); }}
</style>
</head>
<body>

<div class="header">
  <h1>{_h(d['project_name'])}</h1>
  <div class="sub">Updated {d['now']} &middot; auto-refreshes every 60s</div>
</div>

<div class="kpi-grid">
  <div class="kpi highlight"><div class="val">{d['n_records']}</div><div class="label">Records</div></div>
  <div class="kpi"><div class="val">{d['n_species']}</div><div class="label">Species</div></div>
  <div class="kpi"><div class="val">{d['n_families']}</div><div class="label">Families</div></div>
  <div class="kpi"><div class="val">{d['n_papers']}</div><div class="label">Papers</div></div>
  <div class="kpi"><div class="val">{d['n_leads']}</div><div class="label">Leads</div></div>
  <div class="kpi"><div class="val" style="color:{conf_color}">{d['mean_conf']:.2f}</div><div class="label">Mean Confidence</div></div>
  <div class="kpi{' warn' if d['n_flagged'] > 0 else ''}"><div class="val">{d['n_flagged']}</div><div class="label">Flagged</div></div>
</div>

{d['activity_html']}

<div class="section-header">Overview</div>
<div class="chart-grid">
  <div class="chart-card">{d['timeline_svg']}</div>
  <div class="chart-card">{d['family_chart']}</div>
  <div class="chart-card">{d['conf_chart']}</div>
  <div class="chart-card">{d['source_chart']}</div>
</div>

{d['trait_section']}

{f'<div class="section-header">Leads</div><div class="chart-grid"><div class="chart-card">{d["lead_chart"]}</div></div>' if d['lead_chart'] else ''}

<div class="section-header">Data Table (last {d['n_table_rows']} records)</div>
<div class="table-section">
  <div class="picker-toggle" onclick="document.getElementById('picker').classList.toggle('open')">
    Column Picker
  </div>
  <div id="picker" class="picker-panel"></div>
  <div class="data-table-wrap">
    <table class="data-table" id="dataTable">
      <thead><tr id="tableHead"></tr></thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
</div>

<script>
(function() {{
  var DATA = {d['table_json']};
  var FIELDS = {d['fields_json']};
  var STORAGE_KEY = 'tt_dashboard_columns';

  // Default columns to show
  var DEFAULT_COLS = ['species','family','genus','extraction_confidence','first_author',
    'paper_year','pdf_source','source_type','processed_date'];

  function getVisibleCols() {{
    try {{
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    }} catch(e) {{}}
    return DEFAULT_COLS.filter(function(c){{ return FIELDS.indexOf(c) >= 0; }});
  }}
  function saveVisibleCols(cols) {{
    try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(cols)); }} catch(e) {{}}
  }}

  var visibleCols = getVisibleCols();
  // Add any trait-specific fields from FIELDS that aren't in defaults
  // to the defaults on first visit
  if (!localStorage.getItem(STORAGE_KEY)) {{
    FIELDS.forEach(function(f) {{
      if (DEFAULT_COLS.indexOf(f) < 0 && f.indexOf('diploid') >= 0 || f.indexOf('sex_chrom') >= 0 || f.indexOf('karyotype') >= 0) {{
        visibleCols.push(f);
      }}
    }});
  }}

  function buildPicker() {{
    var panel = document.getElementById('picker');
    panel.innerHTML = '';
    FIELDS.forEach(function(f) {{
      var label = document.createElement('label');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = visibleCols.indexOf(f) >= 0;
      cb.onchange = function() {{
        if (cb.checked) {{ visibleCols.push(f); }}
        else {{ visibleCols = visibleCols.filter(function(c){{ return c !== f; }}); }}
        saveVisibleCols(visibleCols);
        buildTable();
      }};
      label.appendChild(cb);
      label.appendChild(document.createTextNode(f.replace(/_/g, ' ')));
      panel.appendChild(label);
    }});
  }}

  var sortCol = null, sortAsc = true;

  function buildTable() {{
    var head = document.getElementById('tableHead');
    var body = document.getElementById('tableBody');
    head.innerHTML = '';
    body.innerHTML = '';

    visibleCols.forEach(function(col) {{
      var th = document.createElement('th');
      th.textContent = col.replace(/_/g, ' ');
      th.onclick = function() {{
        if (sortCol === col) sortAsc = !sortAsc;
        else {{ sortCol = col; sortAsc = true; }}
        buildTable();
      }};
      if (sortCol === col) th.textContent += sortAsc ? ' \\u25B2' : ' \\u25BC';
      head.appendChild(th);
    }});

    var rows = DATA.slice();
    if (sortCol) {{
      rows.sort(function(a, b) {{
        var va = a[sortCol] || '', vb = b[sortCol] || '';
        var na = parseFloat(va), nb = parseFloat(vb);
        if (!isNaN(na) && !isNaN(nb)) return sortAsc ? na - nb : nb - na;
        return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      }});
    }} else {{
      rows.reverse(); // most recent first
    }}

    rows.forEach(function(row) {{
      var tr = document.createElement('tr');
      visibleCols.forEach(function(col) {{
        var td = document.createElement('td');
        var val = row[col] || '';
        td.textContent = val;
        if (col === 'extraction_confidence') {{
          var n = parseFloat(val);
          if (n >= 0.85) td.className = 'conf-high';
          else if (n >= 0.65) td.className = 'conf-mid';
          else if (val) td.className = 'conf-low';
        }}
        tr.appendChild(td);
      }});
      body.appendChild(tr);
    }});
  }}

  buildPicker();
  buildTable();
}})();
</script>

<script>setTimeout(function(){{ location.reload(); }}, 60000);</script>
</body>
</html>"""


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate TraitTrawler dashboard")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    args = parser.parse_args()
    generate_dashboard(args.project_root)


if __name__ == "__main__":
    main()
