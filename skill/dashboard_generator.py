#!/usr/bin/env python3
"""
TraitTrawler Dashboard Generator
=================================
Reads project data files (results.csv, leads.csv, needs_attention.csv,
state/*.json, config.py) and produces a self-contained HTML dashboard
with summary statistics and interactive charts via Chart.js.

Usage:
    python3 skill/dashboard_generator.py [--project-root /path/to/root]

If --project-root is omitted, uses the current working directory.
The dashboard is written to {project_root}/dashboard.html.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime


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


def count_search_queries(config_py_path):
    """Count total search queries defined in config.py."""
    if not os.path.exists(config_py_path):
        return 0
    count = 0
    with open(config_py_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Count quoted strings in lists — rough heuristic
    import re
    matches = re.findall(r'["\']([^"\']{3,})["\']', content)
    return len(matches)


def generate_dashboard(project_root):
    """Generate the dashboard HTML from project data files."""

    # --- Load all data ---
    results = safe_read_csv(os.path.join(project_root, "results.csv"))
    leads = safe_read_csv(os.path.join(project_root, "leads.csv"))
    needs_attn = safe_read_csv(os.path.join(project_root, "needs_attention.csv"))
    processed = safe_read_json(os.path.join(project_root, "state", "processed.json"))
    search_log = safe_read_json(os.path.join(project_root, "state", "search_log.json"))
    total_queries = count_search_queries(os.path.join(project_root, "config.py"))

    # --- Compute summary stats ---
    n_records = len(results)
    n_papers_processed = len(processed) if isinstance(processed, dict) else 0
    n_queries_run = len(search_log) if isinstance(search_log, (dict, list)) else 0

    # Leads breakdown
    lead_statuses = Counter(l.get("status", "unknown") for l in leads)
    n_leads_total = len(leads)
    n_leads_new = lead_statuses.get("new", 0)
    n_leads_extracted = lead_statuses.get("extracted", 0)
    n_leads_in_progress = lead_statuses.get("in_progress", 0)
    n_leads_no_data = lead_statuses.get("no_data", 0)
    n_leads_needs_attn = lead_statuses.get("needs_attention", 0)

    n_needs_attention = len(needs_attn)

    # --- Taxonomic breakdown ---
    family_counts = Counter(r.get("family", "Unknown") for r in results if r.get("family"))
    top_families = family_counts.most_common(20)

    species_set = set(r.get("species", "") for r in results if r.get("species"))
    n_species = len(species_set)

    genus_set = set(r.get("genus", "") for r in results if r.get("genus"))
    n_genera = len(genus_set)

    family_set = set(r.get("family", "") for r in results if r.get("family"))
    n_families = len(family_set)

    # --- Sex chromosome systems ---
    sex_chr_counts = Counter(
        r.get("sex_chr_system", "Not reported") or "Not reported"
        for r in results
    )
    top_sex_chr = sex_chr_counts.most_common(15)

    # --- Chromosome number distribution ---
    chr_numbers = []
    for r in results:
        val = r.get("chromosome_number_2n", "")
        if val:
            try:
                chr_numbers.append(int(val))
            except (ValueError, TypeError):
                pass

    chr_histogram = Counter(chr_numbers)

    # --- Source type breakdown ---
    source_counts = Counter(
        r.get("pdf_source", "unknown") or "unknown" for r in results
    )

    # --- Extraction confidence distribution ---
    confidence_buckets = Counter()
    for r in results:
        val = r.get("extraction_confidence", "")
        if val:
            try:
                c = float(val)
                if c >= 0.9:
                    confidence_buckets["0.90–1.00"] += 1
                elif c >= 0.8:
                    confidence_buckets["0.80–0.89"] += 1
                elif c >= 0.7:
                    confidence_buckets["0.70–0.79"] += 1
                elif c >= 0.6:
                    confidence_buckets["0.60–0.69"] += 1
                else:
                    confidence_buckets["< 0.60"] += 1
            except (ValueError, TypeError):
                pass

    # --- Records over time ---
    date_counts = Counter(r.get("processed_date", "unknown") for r in results)
    sorted_dates = sorted(
        ((d, c) for d, c in date_counts.items() if d != "unknown"),
        key=lambda x: x[0]
    )
    cumulative = []
    running = 0
    for d, c in sorted_dates:
        running += c
        cumulative.append((d, running))

    # --- Country distribution ---
    country_counts = Counter(
        r.get("country", "Not reported") or "Not reported" for r in results
    )
    top_countries = country_counts.most_common(15)

    # --- Papers by year ---
    year_counts = Counter()
    for r in results:
        y = r.get("paper_year", "")
        if y:
            try:
                year_counts[int(y)] += 1
            except (ValueError, TypeError):
                pass
    sorted_years = sorted(year_counts.items())

    # --- Needs attention reasons ---
    attn_reasons = Counter(na.get("reason", "unknown") for na in needs_attn)

    # --- Flag for review count ---
    n_flagged = sum(
        1 for r in results
        if str(r.get("flag_for_review", "")).lower() in ("true", "1", "yes")
    )

    # --- Generate timestamp ---
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Build HTML ---
    html = _build_html(
        now=now,
        n_records=n_records,
        n_species=n_species,
        n_genera=n_genera,
        n_families=n_families,
        n_papers_processed=n_papers_processed,
        n_queries_run=n_queries_run,
        total_queries=total_queries,
        n_leads_total=n_leads_total,
        n_leads_new=n_leads_new,
        n_leads_extracted=n_leads_extracted,
        n_leads_in_progress=n_leads_in_progress,
        n_leads_no_data=n_leads_no_data,
        n_leads_needs_attn=n_leads_needs_attn,
        n_needs_attention=n_needs_attention,
        n_flagged=n_flagged,
        top_families=top_families,
        top_sex_chr=top_sex_chr,
        chr_histogram=chr_histogram,
        source_counts=source_counts,
        confidence_buckets=confidence_buckets,
        cumulative=cumulative,
        top_countries=top_countries,
        sorted_years=sorted_years,
        attn_reasons=attn_reasons,
        lead_statuses=lead_statuses,
    )

    out_path = os.path.join(project_root, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to {out_path}")
    print(f"  Records: {n_records} | Species: {n_species} | Families: {n_families} | Papers: {n_papers_processed}")
    return out_path


def _js_array(items):
    """Convert Python list to JS array literal string."""
    return json.dumps(items)


def _build_html(**d):
    """Build the full self-contained HTML dashboard."""

    # Prepare chart data
    family_labels = [f[0] for f in d["top_families"]]
    family_values = [f[1] for f in d["top_families"]]

    sex_chr_labels = [s[0] for s in d["top_sex_chr"]]
    sex_chr_values = [s[1] for s in d["top_sex_chr"]]

    # Chromosome histogram — bin into ranges for cleaner display
    chr_hist = d["chr_histogram"]
    if chr_hist:
        min_c = min(chr_hist.keys())
        max_c = max(chr_hist.keys())
        chr_labels = list(range(min_c, max_c + 1))
        chr_values = [chr_hist.get(n, 0) for n in chr_labels]
    else:
        chr_labels = []
        chr_values = []

    source_labels = list(d["source_counts"].keys())
    source_values = list(d["source_counts"].values())

    conf_order = ["0.90–1.00", "0.80–0.89", "0.70–0.79", "0.60–0.69", "< 0.60"]
    conf_labels = conf_order
    conf_values = [d["confidence_buckets"].get(k, 0) for k in conf_order]

    cum_labels = [c[0] for c in d["cumulative"]]
    cum_values = [c[1] for c in d["cumulative"]]

    country_labels = [c[0] for c in d["top_countries"]]
    country_values = [c[1] for c in d["top_countries"]]

    year_labels = [str(y[0]) for y in d["sorted_years"]]
    year_values = [y[1] for y in d["sorted_years"]]

    lead_labels = list(d["lead_statuses"].keys())
    lead_values = list(d["lead_statuses"].values())

    attn_labels = list(d["attn_reasons"].keys())
    attn_values = list(d["attn_reasons"].values())

    queries_pct = (
        round(100 * d["n_queries_run"] / d["total_queries"], 1)
        if d["total_queries"] > 0 else 0
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TraitTrawler Dashboard</title>
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
  .attn-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  .attn-table th, .attn-table td {{
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
  }}
  .attn-table th {{
    color: var(--muted);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
  }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }}
  .badge.new {{ background: #164e63; color: var(--accent); }}
  .badge.extracted {{ background: #14532d; color: var(--green); }}
  .badge.needs {{ background: #451a03; color: var(--amber); }}
  @media (max-width: 900px) {{
    .chart-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>TraitTrawler Dashboard</h1>
  <div class="subtitle">Coleoptera Karyotype Database &mdash; Updated {d['now']}</div>
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
    <div class="value green">{d['n_leads_new']:,}</div>
    <div class="label">Leads (New)</div>
  </div>
  <div class="kpi">
    <div class="value amber">{d['n_needs_attention']:,}</div>
    <div class="label">Needs Attention</div>
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

<!-- Charts -->
<div class="chart-grid">

  <!-- Cumulative Records Over Time -->
  <div class="chart-card wide">
    <h3>Cumulative Records Over Time</h3>
    <canvas id="cumulativeChart"></canvas>
  </div>

  <!-- Records by Family -->
  <div class="chart-card">
    <h3>Records by Family (Top 20)</h3>
    <canvas id="familyChart"></canvas>
  </div>

  <!-- Sex Chromosome Systems -->
  <div class="chart-card">
    <h3>Sex Chromosome Systems</h3>
    <canvas id="sexChrChart"></canvas>
  </div>

  <!-- Chromosome Number Distribution -->
  <div class="chart-card wide">
    <h3>Diploid Chromosome Number (2n) Distribution</h3>
    <canvas id="chrHistChart"></canvas>
  </div>

  <!-- Papers by Publication Year -->
  <div class="chart-card">
    <h3>Records by Publication Year</h3>
    <canvas id="yearChart"></canvas>
  </div>

  <!-- PDF Source Breakdown -->
  <div class="chart-card">
    <h3>Full-Text Source</h3>
    <canvas id="sourceChart"></canvas>
  </div>

  <!-- Extraction Confidence -->
  <div class="chart-card">
    <h3>Extraction Confidence</h3>
    <canvas id="confChart"></canvas>
  </div>

  <!-- Country Distribution -->
  <div class="chart-card">
    <h3>Records by Country (Top 15)</h3>
    <canvas id="countryChart"></canvas>
  </div>

  <!-- Lead Status Pipeline -->
  <div class="chart-card">
    <h3>Lead Pipeline Status</h3>
    <canvas id="leadChart"></canvas>
  </div>

  <!-- Needs Attention Reasons -->
  <div class="chart-card">
    <h3>Needs Attention — Reasons</h3>
    <canvas id="attnChart"></canvas>
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

// Cumulative records
new Chart(document.getElementById('cumulativeChart'), {{
  type: 'line',
  data: {{
    labels: {_js_array(cum_labels)},
    datasets: [{{
      label: 'Total Records',
      data: {_js_array(cum_values)},
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
    labels: {_js_array(family_labels)},
    datasets: [{{
      data: {_js_array(family_values)},
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

// Sex chromosome doughnut
new Chart(document.getElementById('sexChrChart'), {{
  type: 'doughnut',
  data: {{
    labels: {_js_array(sex_chr_labels)},
    datasets: [{{
      data: {_js_array(sex_chr_values)},
      backgroundColor: palette({len(sex_chr_labels)}),
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

// Chromosome number histogram
new Chart(document.getElementById('chrHistChart'), {{
  type: 'bar',
  data: {{
    labels: {_js_array(chr_labels)},
    datasets: [{{
      label: '# Records',
      data: {_js_array(chr_values)},
      backgroundColor: COLORS.purple,
      borderRadius: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ title: {{ display: true, text: '2n' }}, ticks: {{ maxTicksLimit: 30 }} }},
      y: {{ beginAtZero: true, title: {{ display: true, text: 'Records' }} }}
    }}
  }}
}});

// Year chart
new Chart(document.getElementById('yearChart'), {{
  type: 'bar',
  data: {{
    labels: {_js_array(year_labels)},
    datasets: [{{
      data: {_js_array(year_values)},
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
    labels: {_js_array(source_labels)},
    datasets: [{{
      data: {_js_array(source_values)},
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
    labels: {_js_array(conf_labels)},
    datasets: [{{
      data: {_js_array(conf_values)},
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
    labels: {_js_array(country_labels)},
    datasets: [{{
      data: {_js_array(country_values)},
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

// Lead pipeline
new Chart(document.getElementById('leadChart'), {{
  type: 'doughnut',
  data: {{
    labels: {_js_array(lead_labels)},
    datasets: [{{
      data: {_js_array(lead_values)},
      backgroundColor: palette({len(lead_labels)}),
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

// Attention reasons
new Chart(document.getElementById('attnChart'), {{
  type: 'bar',
  data: {{
    labels: {_js_array(attn_labels)},
    datasets: [{{
      data: {_js_array(attn_values)},
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
</script>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate TraitTrawler dashboard")
    parser.add_argument("--project-root", default=os.getcwd(),
                        help="Path to the TraitTrawler project root")
    args = parser.parse_args()
    generate_dashboard(args.project_root)
