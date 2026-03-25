#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 dashboard_generator.py [--project-root /path/to/root]
# OUTPUT: Creates {project_root}/dashboard.html (self-contained HTML with Chart.js)
"""
TraitTrawler Dashboard Generator
=================================
Reads project data files (results.csv, leads.csv, state/*.json, config.py,
collector_config.yaml) and produces a self-contained HTML dashboard with
summary statistics and interactive charts via Chart.js.

The dashboard is fully generic — it auto-detects trait-specific fields from
collector_config.yaml and generates appropriate charts (doughnut for categorical,
histogram for numeric). Core charts (cumulative timeline, family breakdown,
year, source, confidence, country, leads) are always present.

The generated HTML auto-refreshes every 60 seconds, so you can leave it open
in a browser while the agent runs and watch progress live.

Usage:
    python3 dashboard_generator.py [--project-root /path/to/root]

If --project-root is omitted, uses the current working directory.
The dashboard is written to {project_root}/dashboard.html.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
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

# Fields that are inherently free-text and should never be charted
_SKIP_FIELDS = {
    "notes", "pdf_url", "pdf_filename", "paper_title", "paper_authors",
    "doi", "collection_locality", "voucher_info", "karyotype_formula",
    "chromosome_morphology", "heterochromatin_pattern", "NOR_position",
}

# Maximum unique values for a field to be treated as categorical
_MAX_CATEGORICAL = 25


def safe_read_csv(path):
    """Read a CSV file, returning list of dicts. Empty list if missing."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def safe_read_json(path):
    """Read a JSON file. Returns {} or [] depending on content. Empty dict if missing."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}


def read_config(project_root):
    """Read project_name and output_fields from collector_config.yaml."""
    config_path = os.path.join(project_root, "collector_config.yaml")
    project_name = "TraitTrawler"
    trait_name = ""
    output_fields = []

    if not os.path.exists(config_path):
        return project_name, trait_name, output_fields

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Project name
        m = re.search(r'^project_name:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        if m:
            project_name = m.group(1)

        # Trait name
        m = re.search(r'^trait_name:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        if m:
            trait_name = m.group(1)

        # Output fields — collect all "  - field_name" lines after "output_fields:"
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
                elif stripped.startswith("#"):
                    continue  # skip comments within the list
                elif stripped == "":
                    continue  # skip blank lines within list
                elif not stripped.startswith("-"):
                    break  # end of list
    except Exception:
        pass

    return project_name, trait_name, output_fields


def count_search_queries(config_py_path):
    """Count total search queries defined in config.py.

    Tries to safely evaluate the file to count SEARCH_TERMS.
    Falls back to counting quoted strings if evaluation fails.
    """
    if not os.path.exists(config_py_path):
        return 0
    try:
        with open(config_py_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return 0
    # Safe approach: execute in restricted namespace to count SEARCH_TERMS
    try:
        ns = {"__builtins__": {"list": list, "dict": dict, "len": len, "set": set,
                               "range": range, "str": str, "int": int, "float": float,
                               "print": lambda *a, **k: None}}
        exec(content, ns)
        terms = ns.get("SEARCH_TERMS", [])
        if isinstance(terms, list):
            return len(terms)
    except Exception:
        pass
    # Fallback: count quoted strings ≥3 chars
    return len(re.findall(r'["\']([^"\']{3,})["\']', content))


def classify_field(values):
    """Classify field values as 'categorical', 'numeric', or 'skip'.

    Returns (classification, parsed_data) where parsed_data is:
      - Counter for categorical
      - list of numbers for numeric
      - None for skip
    """
    if not values:
        return "skip", None

    # Try parsing as numbers
    numbers = []
    for v in values:
        try:
            numbers.append(float(v) if "." in str(v) else int(v))
        except (ValueError, TypeError):
            pass

    # If >60% parse as numbers and there are enough unique values, treat as numeric
    if len(numbers) > 0.6 * len(values) and len(set(numbers)) > _MAX_CATEGORICAL:
        return "numeric", numbers

    # If >60% parse as numbers but few unique values, treat as categorical
    if len(numbers) > 0.6 * len(values) and len(set(numbers)) <= _MAX_CATEGORICAL:
        counts = Counter(str(int(n)) if isinstance(n, (int, float)) and n == int(n) else str(n) for n in numbers)
        return "categorical", counts

    # Categorical: count unique values
    counts = Counter(v for v in values if v)
    unique = len(counts)

    if unique > _MAX_CATEGORICAL:
        return "skip", None  # too many unique values = probably free text
    if unique < 2:
        return "skip", None  # only one value = not interesting

    return "categorical", counts


def field_display_name(field):
    """Convert field_name to a readable chart title."""
    return field.replace("_", " ").replace("2n", "2n").title()


def generate_dashboard(project_root):
    """Generate the dashboard HTML from project data files."""

    # --- Load all data ---
    results = safe_read_csv(os.path.join(project_root, "results.csv"))
    leads = safe_read_csv(os.path.join(project_root, "leads.csv"))
    processed = safe_read_json(os.path.join(project_root, "state", "processed.json"))
    search_log = safe_read_json(os.path.join(project_root, "state", "search_log.json"))
    total_queries = count_search_queries(os.path.join(project_root, "config.py"))
    project_name, trait_name, output_fields = read_config(project_root)

    # --- Compute summary stats ---
    n_records = len(results)
    n_papers_processed = len(processed) if isinstance(processed, dict) else 0
    n_queries_run = len(search_log) if isinstance(search_log, (dict, list)) else 0

    # Leads
    n_leads = len(leads)
    lead_statuses = Counter(l.get("status", "new") for l in leads)
    lead_reasons = Counter(l.get("reason", "unknown") for l in leads)

    # Taxonomy
    family_counts = Counter(r.get("family", "Unknown") for r in results if r.get("family"))
    top_families = family_counts.most_common(20)
    species_set = set(r.get("species", "") for r in results if r.get("species"))
    n_species = len(species_set)
    genus_set = set(r.get("genus", "") for r in results if r.get("genus"))
    n_genera = len(genus_set)
    family_set = set(r.get("family", "") for r in results if r.get("family"))
    n_families = len(family_set)

    # Source type
    source_counts = Counter(
        r.get("pdf_source", "unknown") or "unknown" for r in results
    )

    # Confidence
    confidence_buckets = Counter()
    for r in results:
        val = r.get("extraction_confidence", "")
        if val:
            try:
                c = float(val)
                if c >= 0.9:
                    confidence_buckets["0.90-1.00"] += 1
                elif c >= 0.8:
                    confidence_buckets["0.80-0.89"] += 1
                elif c >= 0.7:
                    confidence_buckets["0.70-0.79"] += 1
                elif c >= 0.6:
                    confidence_buckets["0.60-0.69"] += 1
                else:
                    confidence_buckets["< 0.60"] += 1
            except (ValueError, TypeError):
                pass

    # Cumulative records over time
    date_counts = Counter(r.get("processed_date") or "unknown" for r in results)
    sorted_dates = sorted(
        ((d, c) for d, c in date_counts.items() if d and d != "unknown"),
        key=lambda x: x[0]
    )
    cumulative = []
    running = 0
    for d, c in sorted_dates:
        running += c
        cumulative.append((d, running))

    # Country
    country_counts = Counter(
        r.get("country", "Not reported") or "Not reported" for r in results
    )
    top_countries = country_counts.most_common(15)

    # Year
    year_counts = Counter()
    for r in results:
        y = r.get("paper_year", "")
        if y:
            try:
                year_counts[int(y)] += 1
            except (ValueError, TypeError):
                pass
    sorted_years = sorted(year_counts.items())

    # Flagged
    n_flagged = sum(
        1 for r in results
        if str(r.get("flag_for_review", "")).lower() in ("true", "1", "yes")
    )

    # --- Auto-detect trait-specific charts ---
    trait_charts = []  # list of (field_name, classification, data)
    trait_fields = [f for f in output_fields if f not in _CORE_FIELDS and f not in _SKIP_FIELDS]

    for field in trait_fields:
        values = [r.get(field, "") for r in results if r.get(field, "")]
        classification, data = classify_field(values)
        if classification != "skip" and data:
            trait_charts.append((field, classification, data))

    # --- Recent records feed (last 25) ---
    # Pick up to 3 trait-specific fields to display
    display_trait_fields = [f for f in output_fields
                            if f not in _CORE_FIELDS and f not in _SKIP_FIELDS][:3]
    recent_records = []
    for r in results[-25:]:  # last 25 rows (most recent at bottom of CSV)
        conf_val = r.get("extraction_confidence", "")
        try:
            conf_float = float(conf_val)
            conf_display = f"{conf_float:.2f}"
        except (ValueError, TypeError):
            conf_float = 0.0
            conf_display = conf_val or "—"
        # Confidence color class
        if conf_float >= 0.85:
            conf_class = "conf-high"
        elif conf_float >= 0.65:
            conf_class = "conf-mid"
        else:
            conf_class = "conf-low"

        trait_vals = []
        for tf in display_trait_fields:
            v = r.get(tf, "")
            trait_vals.append(v if v else "—")

        first_author = r.get("first_author", "")
        year = r.get("paper_year", "")
        cite = f"{first_author} {year}".strip() if first_author else (r.get("paper_title", "")[:30] or "—")

        recent_records.append({
            "species": r.get("species", "—"),
            "family": r.get("family", "—"),
            "trait_vals": trait_vals,
            "confidence": conf_display,
            "conf_class": conf_class,
            "source": r.get("pdf_source", "—"),
            "cite": cite,
            "flagged": str(r.get("flag_for_review", "")).lower() in ("true", "1", "yes"),
        })
    # Reverse so most recent is at the top
    recent_records = list(reversed(recent_records))

    # --- Generate timestamp ---
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Build HTML ---
    html = _build_html(
        now=now,
        project_name=project_name,
        trait_name=trait_name,
        n_records=n_records,
        n_species=n_species,
        n_genera=n_genera,
        n_families=n_families,
        n_papers_processed=n_papers_processed,
        n_queries_run=n_queries_run,
        total_queries=total_queries,
        n_flagged=n_flagged,
        n_leads=n_leads,
        lead_statuses=lead_statuses,
        lead_reasons=lead_reasons,
        top_families=top_families,
        source_counts=source_counts,
        confidence_buckets=confidence_buckets,
        cumulative=cumulative,
        top_countries=top_countries,
        sorted_years=sorted_years,
        trait_charts=trait_charts,
        recent_records=recent_records,
        display_trait_fields=display_trait_fields,
    )

    out_path = os.path.join(project_root, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to {out_path}")
    print(f"  Records: {n_records} | Species: {n_species} | Families: {n_families} | Papers: {n_papers_processed}")
    if trait_charts:
        print(f"  Trait charts: {', '.join(tc[0] for tc in trait_charts)}")
    return out_path


def _js(obj):
    """Convert Python object to JS literal string."""
    return json.dumps(obj)


def _build_trait_chart_html(chart_id, field_name, classification):
    """Build the HTML canvas element for a trait-specific chart."""
    title = field_display_name(field_name)
    wide = ' wide' if classification == "numeric" else ''
    return f"""
  <div class="chart-card{wide}">
    <h3>{title}</h3>
    <canvas id="{chart_id}"></canvas>
  </div>"""


def _build_trait_chart_js(chart_id, field_name, classification, data):
    """Build the JS Chart.js constructor for a trait-specific chart."""
    if classification == "categorical":
        # Doughnut chart for categorical data
        items = data.most_common(15)
        labels = [item[0] for item in items]
        values = [item[1] for item in items]
        return f"""
new Chart(document.getElementById('{chart_id}'), {{
  type: 'doughnut',
  data: {{
    labels: {_js(labels)},
    datasets: [{{
      data: {_js(values)},
      backgroundColor: palette({len(labels)}),
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 8, font: {{ size: 11 }} }} }}
    }}
  }}
}});"""

    elif classification == "numeric":
        # Histogram for numeric data
        if not data:
            return ""
        # Use integer bins if all values are integers
        all_int = all(isinstance(v, int) or (isinstance(v, float) and v == int(v)) for v in data)
        if all_int:
            int_data = [int(v) for v in data]
            hist = Counter(int_data)
            min_v = min(hist.keys())
            max_v = max(hist.keys())
            # If range is huge, bin into groups
            span = max_v - min_v + 1
            if span <= 60:
                labels = list(range(min_v, max_v + 1))
                values = [hist.get(n, 0) for n in labels]
            else:
                # Bin into ~30 groups
                bin_size = max(1, span // 30)
                labels = []
                values = []
                for start in range(min_v, max_v + 1, bin_size):
                    end = min(start + bin_size - 1, max_v)
                    label = f"{start}-{end}" if start != end else str(start)
                    labels.append(label)
                    values.append(sum(hist.get(n, 0) for n in range(start, end + 1)))
        else:
            # Float data — bin into 20 buckets
            min_v = min(data)
            max_v = max(data)
            n_bins = 20
            bin_width = (max_v - min_v) / n_bins if max_v > min_v else 1
            labels = []
            values = []
            for i in range(n_bins):
                lo = min_v + i * bin_width
                hi = lo + bin_width
                labels.append(f"{lo:.1f}")
                count = sum(1 for v in data if lo <= v < hi)
                if i == n_bins - 1:
                    count = sum(1 for v in data if v >= lo)
                values.append(count)

        title = field_display_name(field_name)
        return f"""
new Chart(document.getElementById('{chart_id}'), {{
  type: 'bar',
  data: {{
    labels: {_js([str(l) for l in labels])},
    datasets: [{{
      label: '# Records',
      data: {_js(values)},
      backgroundColor: COLORS.purple,
      borderRadius: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ title: {{ display: true, text: '{title}' }}, ticks: {{ maxTicksLimit: 30 }} }},
      y: {{ beginAtZero: true, title: {{ display: true, text: 'Records' }} }}
    }}
  }}
}});"""

    return ""


def _build_html(**d):
    """Build the full self-contained HTML dashboard."""

    # Prepare chart data for core charts
    family_labels = [f[0] for f in d["top_families"]]
    family_values = [f[1] for f in d["top_families"]]

    source_labels = list(d["source_counts"].keys())
    source_values = list(d["source_counts"].values())

    conf_order = ["0.90-1.00", "0.80-0.89", "0.70-0.79", "0.60-0.69", "< 0.60"]
    conf_values = [d["confidence_buckets"].get(k, 0) for k in conf_order]

    cum_labels = [c[0] for c in d["cumulative"]]
    cum_values = [c[1] for c in d["cumulative"]]

    country_labels = [c[0] for c in d["top_countries"]]
    country_values = [c[1] for c in d["top_countries"]]

    year_labels = [str(y[0]) for y in d["sorted_years"]]
    year_values = [y[1] for y in d["sorted_years"]]

    lead_status_labels = list(d["lead_statuses"].keys())
    lead_status_values = list(d["lead_statuses"].values())
    lead_reason_labels = list(d["lead_reasons"].keys())
    lead_reason_values = list(d["lead_reasons"].values())

    queries_pct = (
        round(100 * d["n_queries_run"] / d["total_queries"], 1)
        if d["total_queries"] > 0 else 0
    )

    # Build recent records feed
    recent_records_rows = ""
    for rec in d.get("recent_records", []):
        flag_marker = ' <span class="flagged">&#9873;</span>' if rec["flagged"] else ""
        trait_cells = "".join(f"<td>{v}</td>" for v in rec["trait_vals"])
        recent_records_rows += f"""      <tr>
        <td class="species">{rec['species']}{flag_marker}</td>
        <td>{rec['family']}</td>
        {trait_cells}
        <td class="{rec['conf_class']}">{rec['confidence']}</td>
        <td>{rec['source']}</td>
        <td>{rec['cite']}</td>
      </tr>\n"""

    trait_headers = "".join(
        f"<th>{field_display_name(f)}</th>"
        for f in d.get("display_trait_fields", [])
    )
    n_recent = len(d.get("recent_records", []))
    recent_section = ""
    if n_recent > 0:
        recent_section = f"""
<!-- Recent Records Feed -->
<div class="section-header">Recent Records (last {n_recent})</div>
<div class="record-feed">
  <div class="feed-scroll">
    <table>
      <thead>
        <tr>
          <th>Species</th>
          <th>Family</th>
          {trait_headers}
          <th>Confidence</th>
          <th>Source</th>
          <th>Paper</th>
        </tr>
      </thead>
      <tbody>
{recent_records_rows}      </tbody>
    </table>
  </div>
</div>
"""

    # Build trait-specific chart sections
    trait_html_blocks = []
    trait_js_blocks = []
    for i, (field, classification, data) in enumerate(d.get("trait_charts", [])):
        chart_id = f"traitChart{i}"
        trait_html_blocks.append(_build_trait_chart_html(chart_id, field, classification))
        trait_js_blocks.append(_build_trait_chart_js(chart_id, field, classification, data))

    trait_charts_html = "\n".join(trait_html_blocks)
    trait_charts_js = "\n".join(trait_js_blocks)

    # Trait section header
    trait_section = ""
    if trait_html_blocks:
        trait_label = d.get("trait_name", "Trait").title() if d.get("trait_name") else "Trait"
        trait_section = f"""
<!-- Trait-Specific Charts -->
<div class="section-header">{trait_label} Data</div>
<div class="chart-grid">
{trait_charts_html}
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{d['project_name']} — TraitTrawler Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f172a;
    --card: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --green: #4ade80;
    --amber: #fbbf24;
    --red: #f87171;
    --purple: #a78bfa;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 24px;
    line-height: 1.5;
  }}
  .header {{
    text-align: center;
    margin-bottom: 32px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }}
  .header h1 {{
    font-size: 28px;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 4px;
  }}
  .header .subtitle {{
    color: var(--muted);
    font-size: 14px;
  }}
  .header .refresh-note {{
    color: var(--muted);
    font-size: 11px;
    margin-top: 4px;
    opacity: 0.6;
  }}
  .section-header {{
    font-size: 16px;
    font-weight: 600;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 28px 0 16px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}
  .kpi {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    text-align: center;
  }}
  .kpi .value {{
    font-size: 32px;
    font-weight: 700;
    color: var(--accent);
    line-height: 1.1;
  }}
  .kpi .value.green {{ color: var(--green); }}
  .kpi .value.amber {{ color: var(--amber); }}
  .kpi .value.red {{ color: var(--red); }}
  .kpi .value.purple {{ color: var(--purple); }}
  .kpi .label {{
    font-size: 12px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
  }}
  .progress-bar-container {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 28px;
  }}
  .progress-bar-container .label {{
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 8px;
  }}
  .progress-bar {{
    background: var(--border);
    border-radius: 6px;
    height: 20px;
    overflow: hidden;
  }}
  .progress-bar .fill {{
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--green));
    border-radius: 6px;
    transition: width 0.5s;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 600;
    color: var(--bg);
    min-width: 36px;
  }}
  .chart-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
    gap: 20px;
    margin-bottom: 28px;
  }}
  .chart-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
  }}
  .chart-card h3 {{
    font-size: 14px;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
  }}
  .chart-card canvas {{
    max-height: 320px;
  }}
  .chart-card.wide {{
    grid-column: 1 / -1;
  }}
  .record-feed {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0;
    margin-bottom: 28px;
    overflow: hidden;
  }}
  .record-feed table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  .record-feed th {{
    background: #0f172a;
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 10px 12px;
    text-align: left;
    position: sticky;
    top: 0;
    z-index: 1;
  }}
  .record-feed td {{
    padding: 8px 12px;
    border-top: 1px solid var(--border);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 200px;
  }}
  .record-feed tr:hover td {{
    background: rgba(56, 189, 248, 0.05);
  }}
  .record-feed .species {{ font-style: italic; color: var(--text); }}
  .record-feed .conf-high {{ color: var(--green); font-weight: 600; }}
  .record-feed .conf-mid {{ color: var(--amber); font-weight: 600; }}
  .record-feed .conf-low {{ color: var(--red); font-weight: 600; }}
  .record-feed .flagged {{ color: var(--red); }}
  .record-feed .feed-scroll {{
    max-height: 420px;
    overflow-y: auto;
  }}
  @media (max-width: 900px) {{
    .chart-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>TraitTrawler Dashboard</h1>
  <div class="subtitle">{d['project_name']} &mdash; Updated {d['now']}</div>
  <div class="refresh-note">Auto-refreshes every 60 seconds</div>
</div>

<!-- KPI Cards -->
<div class="kpi-grid">
  <div class="kpi">
    <div class="value">{d['n_records']:,}</div>
    <div class="label">Total Records</div>
  </div>
  <div class="kpi">
    <div class="value green">{d['n_species']:,}</div>
    <div class="label">Unique Species</div>
  </div>
  <div class="kpi">
    <div class="value">{d['n_genera']:,}</div>
    <div class="label">Genera</div>
  </div>
  <div class="kpi">
    <div class="value purple">{d['n_families']:,}</div>
    <div class="label">Families</div>
  </div>
  <div class="kpi">
    <div class="value">{d['n_papers_processed']:,}</div>
    <div class="label">Papers Processed</div>
  </div>
  <div class="kpi">
    <div class="value amber">{d['n_leads']:,}</div>
    <div class="label">Leads (Need PDF)</div>
  </div>
  <div class="kpi">
    <div class="value red">{d['n_flagged']:,}</div>
    <div class="label">Flagged for Review</div>
  </div>
</div>

<!-- Search Progress Bar -->
<div class="progress-bar-container">
  <div class="label">Search Progress: {d['n_queries_run']:,} / {d['total_queries']:,} queries ({queries_pct}%)</div>
  <div class="progress-bar">
    <div class="fill" style="width: {queries_pct}%">{queries_pct}%</div>
  </div>
</div>

{recent_section}

<!-- Core Charts -->
<div class="section-header">Collection Progress</div>
<div class="chart-grid">

  <div class="chart-card wide">
    <h3>Cumulative Records Over Time</h3>
    <canvas id="cumulativeChart"></canvas>
  </div>

  <div class="chart-card">
    <h3>Records by Family (Top 20)</h3>
    <canvas id="familyChart"></canvas>
  </div>

  <div class="chart-card">
    <h3>Records by Publication Year</h3>
    <canvas id="yearChart"></canvas>
  </div>

  <div class="chart-card">
    <h3>Full-Text Source</h3>
    <canvas id="sourceChart"></canvas>
  </div>

  <div class="chart-card">
    <h3>Extraction Confidence</h3>
    <canvas id="confChart"></canvas>
  </div>

  <div class="chart-card">
    <h3>Records by Country (Top 15)</h3>
    <canvas id="countryChart"></canvas>
  </div>

</div>

<!-- Trait-Specific Charts (auto-generated) -->
{trait_section}

<!-- Leads Charts -->
<div class="section-header">Leads (Papers Needing Full Text)</div>
<div class="chart-grid">

  <div class="chart-card">
    <h3>Lead Failure Reasons</h3>
    <canvas id="leadReasonChart"></canvas>
  </div>

  <div class="chart-card">
    <h3>Lead Status</h3>
    <canvas id="leadStatusChart"></canvas>
  </div>

</div>

<script>
const COLORS = {{
  blue: '#38bdf8',
  green: '#4ade80',
  amber: '#fbbf24',
  red: '#f87171',
  purple: '#a78bfa',
  cyan: '#22d3ee',
  pink: '#f472b6',
  orange: '#fb923c',
  lime: '#a3e635',
  teal: '#2dd4bf',
}};
const PALETTE = Object.values(COLORS);
function palette(n) {{ let c=[]; for(let i=0;i<n;i++) c.push(PALETTE[i%PALETTE.length]); return c; }}

Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif";

// --- Core Charts ---

// Cumulative records
new Chart(document.getElementById('cumulativeChart'), {{
  type: 'line',
  data: {{
    labels: {_js(cum_labels)},
    datasets: [{{
      label: 'Total Records',
      data: {_js(cum_values)},
      borderColor: COLORS.blue,
      backgroundColor: 'rgba(56,189,248,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ maxTicksLimit: 12 }} }},
      y: {{ beginAtZero: true }}
    }}
  }}
}});

// Family bar chart
new Chart(document.getElementById('familyChart'), {{
  type: 'bar',
  data: {{
    labels: {_js(family_labels)},
    datasets: [{{
      data: {_js(family_values)},
      backgroundColor: palette({len(family_labels)}),
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ beginAtZero: true }} }}
  }}
}});

// Year chart
new Chart(document.getElementById('yearChart'), {{
  type: 'bar',
  data: {{
    labels: {_js(year_labels)},
    datasets: [{{
      data: {_js(year_values)},
      backgroundColor: COLORS.teal,
      borderRadius: 3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ maxTicksLimit: 15 }} }},
      y: {{ beginAtZero: true }}
    }}
  }}
}});

// Source doughnut
new Chart(document.getElementById('sourceChart'), {{
  type: 'doughnut',
  data: {{
    labels: {_js(source_labels)},
    datasets: [{{
      data: {_js(source_values)},
      backgroundColor: palette({len(source_labels)}),
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 8, font: {{ size: 11 }} }} }}
    }}
  }}
}});

// Confidence bar
new Chart(document.getElementById('confChart'), {{
  type: 'bar',
  data: {{
    labels: {_js(conf_order)},
    datasets: [{{
      data: {_js(conf_values)},
      backgroundColor: [COLORS.green, COLORS.blue, COLORS.amber, COLORS.orange, COLORS.red],
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ y: {{ beginAtZero: true }} }}
  }}
}});

// Country bar
new Chart(document.getElementById('countryChart'), {{
  type: 'bar',
  data: {{
    labels: {_js(country_labels)},
    datasets: [{{
      data: {_js(country_values)},
      backgroundColor: palette({len(country_labels)}),
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ beginAtZero: true }} }}
  }}
}});

// --- Trait-Specific Charts ---
{trait_charts_js}

// --- Leads Charts ---

// Lead failure reasons
new Chart(document.getElementById('leadReasonChart'), {{
  type: 'bar',
  data: {{
    labels: {_js(lead_reason_labels)},
    datasets: [{{
      data: {_js(lead_reason_values)},
      backgroundColor: COLORS.amber,
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ beginAtZero: true }} }}
  }}
}});

// Lead status
new Chart(document.getElementById('leadStatusChart'), {{
  type: 'doughnut',
  data: {{
    labels: {_js(lead_status_labels)},
    datasets: [{{
      data: {_js(lead_status_values)},
      backgroundColor: palette({len(lead_status_labels)}),
      borderWidth: 0,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 8, font: {{ size: 11 }} }} }}
    }}
  }}
}});

// --- Auto-refresh every 60 seconds ---
setTimeout(function() {{ location.reload(); }}, 60000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate TraitTrawler dashboard")
    parser.add_argument("--project-root", default=os.getcwd(),
                        help="Path to the TraitTrawler project root")
    args = parser.parse_args()
    generate_dashboard(args.project_root)
