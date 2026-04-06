#!/usr/bin/env python3
# PURPOSE: Execute this script. Do not read it into context.
# USAGE: python3 dashboard_generator.py [--project-root /path/to/root]
# OUTPUT: Creates {project_root}/dashboard.html (self-contained, zero external deps)
"""
TraitTrawler Dashboard Generator
=================================
Reads results.csv and produces a self-contained HTML dashboard with:
- Summary KPIs
- Interactive data table with selectable columns
- Species accumulation curve across publication years
- User-selectable grouping for accumulation facets

No external dependencies (no CDN, no Chart.js). Works offline and via
file:// protocol. Generated on demand — not auto-refreshed.

Usage:
    python3 dashboard_generator.py [--project-root /path/to/root]
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime


# ── Data loading ─────────────────────────────────────────────────────────

def safe_read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def read_config(project_root):
    config_path = os.path.join(project_root, "collector_config.yaml")
    project_name = "TraitTrawler"
    output_fields = []

    if not os.path.exists(config_path):
        return project_name, output_fields

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'^project_name:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        if m:
            project_name = m.group(1)
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
    return project_name, output_fields


def _h(text):
    """HTML-escape a string."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── Species accumulation data ────────────────────────────────────────────

def build_accumulation_data(results):
    """Build species accumulation curves faceted by available grouping fields.

    Returns (accum_dict, candidate_fields).
    accum_dict: {field_name: {group_value: [[year, cumulative_count], ...]}}
    Also returns the overall (unfaceted) curve as {"_overall": [[year, count]]}.
    """
    # Identify candidate grouping fields (categorical, 2-50 unique values)
    field_values = defaultdict(set)
    for r in results:
        for k, v in r.items():
            if v and isinstance(v, str) and v.strip():
                field_values[k].add(v.strip())

    skip = {"doi", "paper_title", "paper_authors", "notes", "source_context",
            "extraction_reasoning", "pdf_path", "pdf_source", "source_page",
            "species", "paper_year", "processed_date", "session_id",
            "accepted_name", "gbif_key", "taxonomy_note", "audit_status",
            "audit_session", "audit_prior_values", "extraction_trace_id",
            "source_query", "pdf_url", "pdf_filename", "first_author",
            "paper_journal", "source_type", "flag_for_review",
            "extraction_confidence", "calibrated_confidence"}

    candidate_fields = []
    for field, vals in field_values.items():
        if field in skip:
            continue
        if 2 <= len(vals) <= 50:
            candidate_fields.append(field)

    # Always include family if present
    if "family" in field_values and "family" not in candidate_fields:
        candidate_fields.insert(0, "family")

    # Build per-year species sets
    year_species = defaultdict(set)
    for r in results:
        sp = r.get("species", "").strip()
        yr = r.get("paper_year", "").strip()
        if sp and yr:
            try:
                year_species[int(yr)].add(sp)
            except ValueError:
                pass

    if not year_species:
        return {}, candidate_fields

    sorted_years = sorted(year_species.keys())

    # Overall accumulation
    seen = set()
    overall = []
    for yr in sorted_years:
        seen |= year_species[yr]
        overall.append([yr, len(seen)])

    accum = {"_overall": overall}

    # Faceted accumulation
    for field in candidate_fields:
        group_year_species = defaultdict(lambda: defaultdict(set))
        for r in results:
            sp = r.get("species", "").strip()
            yr = r.get("paper_year", "").strip()
            gv = r.get(field, "").strip()
            if sp and yr and gv:
                try:
                    group_year_species[gv][int(yr)].add(sp)
                except ValueError:
                    pass

        field_accum = {}
        for gv, ys in group_year_species.items():
            seen_g = set()
            curve = []
            for yr in sorted_years:
                seen_g |= ys.get(yr, set())
                curve.append([yr, len(seen_g)])
            field_accum[gv] = curve
        accum[field] = field_accum

    return accum, candidate_fields


# ── Main generator ───────────────────────────────────────────────────────

def generate_dashboard(project_root):
    results = safe_read_csv(os.path.join(project_root, "results.csv"))
    project_name, output_fields = read_config(project_root)

    n_records = len(results)
    species_set = {r.get("species", "") for r in results if r.get("species")}
    family_counts = Counter(r.get("family", "Unknown") for r in results if r.get("family"))
    n_families = len(family_counts)

    # Count unique papers
    paper_ids = set()
    for r in results:
        doi = r.get("doi", "").strip()
        title = r.get("paper_title", "").strip()
        paper_ids.add(doi if doi else title)
    paper_ids.discard("")
    n_papers = len(paper_ids)

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

    # All fields from data
    all_fields = []
    if results:
        all_fields = list(results[0].keys())

    # Accumulation data
    accum_data, accum_fields = build_accumulation_data(results)

    # Sanitize for JSON embedding
    table_json = json.dumps(results, ensure_ascii=True)
    fields_json = json.dumps(all_fields)
    output_fields_json = json.dumps(output_fields)
    accum_json = json.dumps(accum_data, ensure_ascii=True)
    accum_fields_json = json.dumps(accum_fields)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conf_color = "#4ade80" if mean_conf >= 0.85 else (
        "#fbbf24" if mean_conf >= 0.7 else "#f87171")

    html = _build_html(
        project_name=project_name,
        now=now,
        n_records=n_records,
        n_species=len(species_set),
        n_families=n_families,
        n_papers=n_papers,
        mean_conf=mean_conf,
        conf_color=conf_color,
        n_flagged=n_flagged,
        table_json=table_json,
        fields_json=fields_json,
        output_fields_json=output_fields_json,
        accum_json=accum_json,
        accum_fields_json=accum_fields_json,
    )

    out_path = os.path.join(project_root, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to {out_path}")
    print(f"  Records: {n_records} | Species: {len(species_set)} | "
          f"Families: {n_families} | Papers: {n_papers}")
    return out_path


def _build_html(**d):
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
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px; text-align: center; }}
.kpi .val {{ font-size: 28px; font-weight: 700; color: var(--accent); }}
.kpi .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi.warn .val {{ color: var(--amber); }}

.section-header {{
  font-size: 16px; font-weight: 600; color: var(--accent);
  margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
}}

/* Accumulation chart */
.accum-controls {{
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px; margin-bottom: 16px;
}}
.accum-controls label {{ color: var(--muted); font-size: 13px; margin-right: 12px; }}
.accum-controls select {{
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 4px 8px; font-size: 13px;
}}
.chart-canvas {{
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px;
}}
.chart-canvas canvas {{ width: 100%; height: 400px; }}
.chart-legend {{
  display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 10px; font-size: 12px;
}}
.chart-legend-item {{ display: flex; align-items: center; gap: 4px; cursor: pointer; }}
.chart-legend-dot {{ width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }}

/* Column picker + data table */
.table-section {{ margin-top: 24px; }}
.table-controls {{
  display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap;
}}
.picker-toggle {{
  background: var(--card); border: 1px solid var(--border); color: var(--accent);
  padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px;
}}
.picker-toggle:hover {{ background: var(--border); }}
.search-input {{
  background: var(--card); border: 1px solid var(--border); color: var(--text);
  padding: 8px 12px; border-radius: 6px; font-size: 13px; flex: 1; min-width: 200px;
}}
.search-input::placeholder {{ color: var(--muted); }}
.row-count {{ color: var(--muted); font-size: 12px; }}
.picker-panel {{
  display: none; background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px; margin-bottom: 12px;
  max-height: 250px; overflow-y: auto;
  column-count: 3; column-gap: 16px;
}}
.picker-panel.open {{ display: block; }}
.picker-panel label {{
  display: block; font-size: 12px; color: var(--text); padding: 2px 0;
  cursor: pointer; break-inside: avoid;
}}
.picker-panel label:hover {{ color: var(--accent); }}
.picker-panel input {{ margin-right: 6px; }}

.data-table-wrap {{ overflow-x: auto; max-height: 600px; overflow-y: auto; }}
.data-table {{
  width: 100%; border-collapse: collapse; font-size: 12px;
}}
.data-table th {{
  position: sticky; top: 0; background: var(--card); z-index: 1;
  text-align: left; padding: 8px 6px; color: var(--accent);
  border-bottom: 2px solid var(--border); white-space: nowrap;
  cursor: pointer; user-select: none;
}}
.data-table th:hover {{ color: var(--green); }}
.data-table td {{
  padding: 5px 6px; border-bottom: 1px solid var(--border);
  max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
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
  <div class="sub">Generated {d['now']}</div>
</div>

<div class="kpi-grid">
  <div class="kpi"><div class="val">{d['n_records']}</div><div class="label">Records</div></div>
  <div class="kpi"><div class="val">{d['n_species']}</div><div class="label">Species</div></div>
  <div class="kpi"><div class="val">{d['n_families']}</div><div class="label">Families</div></div>
  <div class="kpi"><div class="val">{d['n_papers']}</div><div class="label">Papers</div></div>
  <div class="kpi"><div class="val" style="color:{d['conf_color']}">{d['mean_conf']:.2f}</div><div class="label">Mean Confidence</div></div>
  <div class="kpi{' warn' if d['n_flagged'] > 0 else ''}"><div class="val">{d['n_flagged']}</div><div class="label">Flagged</div></div>
</div>

<div class="section-header">Species Accumulation</div>
<div class="accum-controls">
  <label for="accum-facet">Group by:</label>
  <select id="accum-facet">
    <option value="_overall">Overall (no grouping)</option>
  </select>
</div>
<div class="chart-canvas">
  <canvas id="accumChart"></canvas>
  <div class="chart-legend" id="accumLegend"></div>
</div>

<div class="section-header">Data Table ({d['n_records']} records)</div>
<div class="table-section">
  <div class="table-controls">
    <div class="picker-toggle" onclick="document.getElementById('picker').classList.toggle('open')">
      Column Picker
    </div>
    <input type="text" class="search-input" id="tableSearch" placeholder="Filter rows (searches all columns)...">
    <div class="row-count" id="rowCount"></div>
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
  // ── Data ──────────────────────────────────────────────────────────
  var DATA = {d['table_json']};
  var FIELDS = {d['fields_json']};
  var OUTPUT_FIELDS = {d['output_fields_json']};
  var ACCUM = {d['accum_json']};
  var ACCUM_FIELDS = {d['accum_fields_json']};

  var PALETTE = [
    '#38bdf8','#4ade80','#fbbf24','#f87171','#a78bfa',
    '#fb923c','#2dd4bf','#e879f9','#60a5fa','#34d399',
    '#facc15','#f472b6','#818cf8','#a3e635','#22d3ee',
    '#c084fc','#fb7185','#67e8f9','#86efac','#fcd34d'
  ];
  var STORAGE_KEY = 'tt_dashboard_columns';

  // ── Accumulation Chart ────────────────────────────────────────────
  var facetSelect = document.getElementById('accum-facet');
  ACCUM_FIELDS.forEach(function(f) {{
    var opt = document.createElement('option');
    opt.value = f;
    opt.textContent = f.replace(/_/g, ' ');
    facetSelect.appendChild(opt);
  }});

  var hiddenGroups = {{}};

  function drawAccum() {{
    var canvas = document.getElementById('accumChart');
    var ctx = canvas.getContext('2d');
    var facet = facetSelect.value;
    var curves;

    if (facet === '_overall') {{
      curves = {{'Overall': ACCUM['_overall'] || []}};
    }} else {{
      curves = ACCUM[facet] || {{}};
    }}

    // Get all years across all curves
    var allYears = new Set();
    Object.values(curves).forEach(function(pts) {{
      pts.forEach(function(p) {{ allYears.add(p[0]); }});
    }});
    var years = Array.from(allYears).sort(function(a,b) {{ return a - b; }});
    if (years.length === 0) {{
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#94a3b8';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No data', canvas.width / 2, canvas.height / 2);
      return;
    }}

    // Sort groups by final count descending
    var groups = Object.keys(curves).sort(function(a, b) {{
      var ca = curves[a], cb = curves[b];
      return (cb.length ? cb[cb.length-1][1] : 0) - (ca.length ? ca[ca.length-1][1] : 0);
    }});

    // Set canvas size for retina
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 400 * dpr;
    canvas.style.height = '400px';
    ctx.scale(dpr, dpr);
    var W = rect.width, H = 400;
    ctx.clearRect(0, 0, W, H);

    var padL = 55, padR = 20, padT = 10, padB = 40;
    var cW = W - padL - padR, cH = H - padT - padB;

    var minYear = years[0], maxYear = years[years.length - 1];
    var yearSpan = maxYear - minYear || 1;

    // Find max value across visible curves
    var maxVal = 1;
    groups.forEach(function(g) {{
      if (hiddenGroups[facet + ':' + g]) return;
      curves[g].forEach(function(p) {{ if (p[1] > maxVal) maxVal = p[1]; }});
    }});

    // Grid lines
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 0.5;
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';
    for (var i = 0; i <= 4; i++) {{
      var yv = Math.round(maxVal * i / 4);
      var yp = padT + cH - (cH * i / 4);
      ctx.beginPath(); ctx.moveTo(padL, yp); ctx.lineTo(W - padR, yp); ctx.stroke();
      ctx.fillText(yv, padL - 6, yp + 4);
    }}

    // X-axis labels
    ctx.textAlign = 'center';
    var nLabels = Math.min(years.length, 12);
    var step = Math.max(1, Math.ceil(years.length / nLabels));
    for (var j = 0; j < years.length; j += step) {{
      var xp = padL + ((years[j] - minYear) / yearSpan) * cW;
      ctx.fillText(years[j], xp, H - 8);
    }}

    // Draw curves
    groups.forEach(function(g, gi) {{
      if (hiddenGroups[facet + ':' + g]) return;
      var color = PALETTE[gi % PALETTE.length];
      var pts = curves[g];
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      pts.forEach(function(p, pi) {{
        var x = padL + ((p[0] - minYear) / yearSpan) * cW;
        var y = padT + cH - (p[1] / maxVal) * cH;
        if (pi === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }});
      ctx.stroke();

      // Dots at data points (only if few enough)
      if (pts.length <= 40) {{
        ctx.fillStyle = color;
        pts.forEach(function(p) {{
          var x = padL + ((p[0] - minYear) / yearSpan) * cW;
          var y = padT + cH - (p[1] / maxVal) * cH;
          ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
        }});
      }}
    }});

    // Axis labels
    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Publication Year', padL + cW / 2, H - 2);
    ctx.save();
    ctx.translate(12, padT + cH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Cumulative Species', 0, 0);
    ctx.restore();

    // Legend
    var legendEl = document.getElementById('accumLegend');
    legendEl.innerHTML = '';
    groups.forEach(function(g, gi) {{
      var color = PALETTE[gi % PALETTE.length];
      var isHidden = !!hiddenGroups[facet + ':' + g];
      var item = document.createElement('div');
      item.className = 'chart-legend-item';
      item.style.opacity = isHidden ? '0.3' : '1';
      item.innerHTML = '<div class="chart-legend-dot" style="background:' + color + '"></div>' +
        '<span>' + g.replace(/_/g, ' ') + '</span>';
      item.onclick = function() {{
        hiddenGroups[facet + ':' + g] = !hiddenGroups[facet + ':' + g];
        drawAccum();
      }};
      legendEl.appendChild(item);
    }});
  }}

  facetSelect.addEventListener('change', drawAccum);
  drawAccum();
  window.addEventListener('resize', drawAccum);

  // ── Data Table ────────────────────────────────────────────────────
  var DEFAULT_COLS = ['species','family','genus','extraction_confidence',
    'first_author','paper_year','pdf_source','processed_date'];

  function getVisibleCols() {{
    try {{
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    }} catch(e) {{}}
    return DEFAULT_COLS.filter(function(c) {{ return FIELDS.indexOf(c) >= 0; }});
  }}
  function saveVisibleCols(cols) {{
    try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(cols)); }} catch(e) {{}}
  }}

  var visibleCols = getVisibleCols();
  // On first visit, auto-show trait fields from collector_config output_fields
  if (!localStorage.getItem(STORAGE_KEY)) {{
    OUTPUT_FIELDS.forEach(function(f) {{
      if (DEFAULT_COLS.indexOf(f) < 0 && FIELDS.indexOf(f) >= 0 &&
          visibleCols.indexOf(f) < 0) {{
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
        else {{ visibleCols = visibleCols.filter(function(c) {{ return c !== f; }}); }}
        saveVisibleCols(visibleCols);
        buildTable();
      }};
      label.appendChild(cb);
      label.appendChild(document.createTextNode(f.replace(/_/g, ' ')));
      panel.appendChild(label);
    }});
  }}

  var sortCol = null, sortAsc = true;
  var searchFilter = '';

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
      if (sortCol === col) th.textContent += sortAsc ? ' \u25B2' : ' \u25BC';
      head.appendChild(th);
    }});

    var rows = DATA.slice();

    // Filter
    if (searchFilter) {{
      var q = searchFilter.toLowerCase();
      rows = rows.filter(function(row) {{
        return visibleCols.some(function(col) {{
          return (row[col] || '').toString().toLowerCase().indexOf(q) >= 0;
        }});
      }});
    }}

    // Sort
    if (sortCol) {{
      rows.sort(function(a, b) {{
        var va = a[sortCol] || '', vb = b[sortCol] || '';
        var na = parseFloat(va), nb = parseFloat(vb);
        if (!isNaN(na) && !isNaN(nb)) return sortAsc ? na - nb : nb - na;
        return sortAsc ? va.toString().localeCompare(vb.toString()) : vb.toString().localeCompare(va.toString());
      }});
    }} else {{
      rows.reverse();
    }}

    document.getElementById('rowCount').textContent = rows.length + ' of ' + DATA.length + ' rows';

    rows.forEach(function(row) {{
      var tr = document.createElement('tr');
      visibleCols.forEach(function(col) {{
        var td = document.createElement('td');
        var val = row[col] || '';
        td.textContent = val;
        td.title = val;
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

  document.getElementById('tableSearch').addEventListener('input', function(e) {{
    searchFilter = e.target.value;
    buildTable();
  }});

  buildPicker();
  buildTable();
}})();
</script>
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
