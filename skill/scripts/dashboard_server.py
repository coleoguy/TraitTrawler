#!/usr/bin/env python3
"""
Live dashboard server for TraitTrawler.

Serves the dashboard with live data updates via Server-Sent Events (SSE).
The dashboard auto-updates when results.csv or state files change — no
need to regenerate the HTML. Also provides a command input that writes
to state/user_commands.txt for the agent to pick up.

Usage:
    python3 scripts/dashboard_server.py --project-root . [--port 8347]

Then open http://localhost:8347 in your browser. The agent opens this
automatically at session start.

The server watches results.csv and state/processed.json for changes and
pushes updates to connected browsers via SSE. No external dependencies.
"""

import argparse
import csv
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class DashboardState:
    """Tracks file modification times and current data."""

    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.last_mtimes = {}
        self.listeners = []
        self.lock = threading.Lock()

    def watched_files(self):
        return {
            "results": self.project_root / "results.csv",
            "leads": self.project_root / "leads.csv",
            "processed": self.project_root / "state" / "processed.json",
            "search_log": self.project_root / "state" / "search_log.json",
            "live_progress": self.project_root / "state" / "live_progress.jsonl",
        }

    def check_for_changes(self):
        """Return True if any watched file has been modified."""
        changed = False
        for name, path in self.watched_files().items():
            try:
                mtime = os.stat(path).st_mtime
            except FileNotFoundError:
                mtime = 0
            if name not in self.last_mtimes or self.last_mtimes[name] != mtime:
                self.last_mtimes[name] = mtime
                changed = True
        return changed

    def get_summary(self):
        """Read current project data and return a summary dict."""
        results_path = self.project_root / "results.csv"
        leads_path = self.project_root / "leads.csv"
        processed_path = self.project_root / "state" / "processed.json"
        search_log_path = self.project_root / "state" / "search_log.json"
        progress_path = self.project_root / "state" / "live_progress.jsonl"

        # Count records
        n_records = 0
        species = set()
        families = set()
        confidences = []
        recent = []

        if results_path.exists():
            with open(results_path, "r", newline="", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                n_records = len(rows)
                for r in rows:
                    sp = r.get("species", "").strip()
                    if sp:
                        species.add(sp)
                    fam = r.get("family", "").strip()
                    if fam:
                        families.add(fam)
                    try:
                        confidences.append(float(r.get("extraction_confidence", 0)))
                    except (ValueError, TypeError):
                        pass
                # Last 5 records for live feed
                for r in rows[-5:]:
                    recent.append({
                        "species": r.get("species", "?"),
                        "family": r.get("family", "?"),
                        "confidence": r.get("extraction_confidence", "?"),
                        "source": r.get("pdf_source", "?"),
                        "cite": f"{r.get('first_author', '')} {r.get('paper_year', '')}".strip(),
                    })

        # Count leads
        n_leads = 0
        if leads_path.exists():
            with open(leads_path, "r", newline="", encoding="utf-8", errors="replace") as f:
                n_leads = sum(1 for _ in csv.DictReader(f))

        # Count processed papers
        n_papers = 0
        if processed_path.exists():
            try:
                with open(processed_path) as f:
                    n_papers = len(json.load(f))
            except (json.JSONDecodeError, ValueError):
                pass

        # Count queries
        n_queries = 0
        if search_log_path.exists():
            try:
                with open(search_log_path) as f:
                    n_queries = len(json.load(f))
            except (json.JSONDecodeError, ValueError):
                pass

        # Last progress line
        last_progress = None
        if progress_path.exists():
            try:
                with open(progress_path, "rb") as f:
                    # Read last non-empty line
                    f.seek(0, 2)
                    pos = f.tell()
                    lines = []
                    while pos > 0 and len(lines) < 2:
                        pos -= 1
                        f.seek(pos)
                        ch = f.read(1)
                        if ch == b"\n" and pos > 0:
                            line = f.readline().decode("utf-8", errors="replace").strip()
                            if line:
                                lines.append(line)
                    if lines:
                        last_progress = json.loads(lines[0])
            except Exception:
                pass

        mean_conf = sum(confidences) / len(confidences) if confidences else 0

        return {
            "records": n_records,
            "species": len(species),
            "families": len(families),
            "papers": n_papers,
            "queries": n_queries,
            "leads": n_leads,
            "mean_confidence": round(mean_conf, 3),
            "recent": list(reversed(recent)),
            "last_progress": last_progress,
            "timestamp": datetime.now().isoformat(),
        }


# Global state
state = None


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the dashboard server."""

    def log_message(self, format, *args):
        """Suppress default access logs."""
        pass

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self.serve_dashboard()
        elif parsed.path == "/data":
            self.serve_data()
        elif parsed.path == "/events":
            self.serve_sse()
        elif parsed.path == "/dashboard.html":
            # Redirect to the live version
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            # Serve static files from project root (for dashboard.html assets)
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/command":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                command = data.get("command", "").strip()
                if command:
                    cmd_path = state.project_root / "state" / "user_commands.txt"
                    with open(cmd_path, "a") as f:
                        f.write(f"{datetime.now().isoformat()} {command}\n")
                    self.send_json({"status": "ok", "command": command})
                else:
                    self.send_json({"status": "error", "message": "empty command"})
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)})
        else:
            self.send_error(404)

    def send_json(self, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(data))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def serve_data(self):
        """Return current project summary as JSON."""
        summary = state.get_summary()
        self.send_json(summary)

    def serve_sse(self):
        """Server-Sent Events stream — pushes updates when files change."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            while True:
                if state.check_for_changes():
                    summary = state.get_summary()
                    data = json.dumps(summary)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                time.sleep(3)  # Check every 3 seconds
        except (BrokenPipeError, ConnectionResetError):
            pass

    def serve_dashboard(self):
        """Serve the live dashboard HTML."""
        html = DASHBOARD_HTML
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TraitTrawler Live</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
         background: #0f1117; color: #e4e4e7; padding: 20px; }
  .header { display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #27272a; }
  .header h1 { font-size: 22px; font-weight: 600; }
  .header h1 span { color: #3b82f6; }
  .status { font-size: 13px; color: #71717a; }
  .status .live { color: #22c55e; font-weight: 600; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px; margin-bottom: 24px; }
  .kpi { background: #18181b; border: 1px solid #27272a; border-radius: 10px;
         padding: 16px; text-align: center; }
  .kpi .value { font-size: 32px; font-weight: 700; color: #f4f4f5; }
  .kpi .label { font-size: 12px; color: #71717a; margin-top: 4px; text-transform: uppercase;
                letter-spacing: 0.5px; }
  .kpi.highlight .value { color: #3b82f6; }
  .feed { background: #18181b; border: 1px solid #27272a; border-radius: 10px;
          padding: 16px; margin-bottom: 24px; }
  .feed h2 { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #a1a1aa; }
  .feed-item { display: grid; grid-template-columns: 1fr 120px 60px 60px 120px;
               gap: 8px; padding: 8px 0; border-bottom: 1px solid #27272a;
               font-size: 13px; align-items: center; }
  .feed-item:last-child { border-bottom: none; }
  .feed-item .species { font-style: italic; color: #e4e4e7; }
  .feed-item .family { color: #71717a; }
  .feed-item .conf { font-weight: 600; font-variant-numeric: tabular-nums; }
  .conf-high { color: #22c55e; }
  .conf-mid { color: #eab308; }
  .conf-low { color: #ef4444; }
  .feed-item .source { color: #71717a; font-size: 12px; }
  .feed-item .cite { color: #a1a1aa; font-size: 12px; }
  .command-bar { background: #18181b; border: 1px solid #27272a; border-radius: 10px;
                 padding: 16px; margin-bottom: 24px; }
  .command-bar h2 { font-size: 14px; font-weight: 600; margin-bottom: 8px; color: #a1a1aa; }
  .command-bar .hint { font-size: 12px; color: #52525b; margin-bottom: 8px; }
  .command-row { display: flex; gap: 8px; }
  .command-row input { flex: 1; background: #09090b; border: 1px solid #3f3f46;
                       border-radius: 6px; padding: 8px 12px; color: #e4e4e7;
                       font-size: 14px; font-family: 'SF Mono', 'Fira Code', monospace; }
  .command-row input:focus { outline: none; border-color: #3b82f6; }
  .command-row button { background: #3b82f6; border: none; border-radius: 6px;
                        padding: 8px 16px; color: white; font-weight: 600; cursor: pointer;
                        font-size: 14px; }
  .command-row button:hover { background: #2563eb; }
  .command-log { margin-top: 8px; font-size: 12px; color: #22c55e; min-height: 20px; }
  .progress-bar { background: #27272a; border-radius: 4px; height: 6px;
                  margin-bottom: 24px; overflow: hidden; }
  .progress-bar .fill { background: #3b82f6; height: 100%; transition: width 0.5s ease; }
  .footer { text-align: center; font-size: 11px; color: #3f3f46; padding-top: 16px; }
</style>
</head>
<body>

<div class="header">
  <h1><span>TraitTrawler</span> Live Dashboard</h1>
  <div class="status">
    <span class="live" id="status-dot">&#9679;</span>
    <span id="status-text">Connecting...</span>
  </div>
</div>

<div class="kpis" id="kpis">
  <div class="kpi highlight"><div class="value" id="kpi-records">-</div><div class="label">Records</div></div>
  <div class="kpi"><div class="value" id="kpi-species">-</div><div class="label">Species</div></div>
  <div class="kpi"><div class="value" id="kpi-families">-</div><div class="label">Families</div></div>
  <div class="kpi"><div class="value" id="kpi-papers">-</div><div class="label">Papers</div></div>
  <div class="kpi"><div class="value" id="kpi-leads">-</div><div class="label">Leads</div></div>
  <div class="kpi"><div class="value" id="kpi-confidence">-</div><div class="label">Mean Conf.</div></div>
</div>

<div class="feed" id="feed">
  <h2>Recent Extractions</h2>
  <div id="feed-items"><div style="color:#52525b;font-size:13px;">Waiting for data...</div></div>
</div>

<div class="command-bar">
  <h2>Send Command to Agent</h2>
  <div class="hint">Commands: skip, pause, redo last, show trace, run QC, consensus on last, stop</div>
  <div class="command-row">
    <input type="text" id="cmd-input" placeholder="Type a command..." autocomplete="off">
    <button id="cmd-send">Send</button>
  </div>
  <div class="command-log" id="cmd-log"></div>
</div>

<div class="footer">
  Updates every 3 seconds when files change &bull; Full dashboard at <a href="/dashboard.html" style="color:#3b82f6;">dashboard.html</a>
  &bull; <a href="/data" style="color:#3b82f6;">raw JSON</a>
</div>

<script>
function update(data) {
  document.getElementById('kpi-records').textContent = data.records.toLocaleString();
  document.getElementById('kpi-species').textContent = data.species.toLocaleString();
  document.getElementById('kpi-families').textContent = data.families.toLocaleString();
  document.getElementById('kpi-papers').textContent = data.papers.toLocaleString();
  document.getElementById('kpi-leads').textContent = data.leads.toLocaleString();
  document.getElementById('kpi-confidence').textContent = data.mean_confidence.toFixed(2);

  document.getElementById('status-text').textContent = 'Updated ' + new Date(data.timestamp).toLocaleTimeString();

  // Recent feed
  const container = document.getElementById('feed-items');
  if (data.recent && data.recent.length > 0) {
    container.innerHTML = data.recent.map(r => {
      const conf = parseFloat(r.confidence) || 0;
      const cls = conf >= 0.85 ? 'conf-high' : conf >= 0.65 ? 'conf-mid' : 'conf-low';
      return `<div class="feed-item">
        <span class="species">${esc(r.species)}</span>
        <span class="family">${esc(r.family)}</span>
        <span class="conf ${cls}">${conf.toFixed(2)}</span>
        <span class="source">${esc(r.source)}</span>
        <span class="cite">${esc(r.cite)}</span>
      </div>`;
    }).join('');
  }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

// SSE connection
let es;
function connect() {
  es = new EventSource('/events');
  es.onmessage = function(e) {
    try { update(JSON.parse(e.data)); } catch(err) { console.error(err); }
  };
  es.onerror = function() {
    document.getElementById('status-dot').style.color = '#ef4444';
    document.getElementById('status-text').textContent = 'Disconnected — retrying...';
    es.close();
    setTimeout(connect, 5000);
  };
  es.onopen = function() {
    document.getElementById('status-dot').style.color = '#22c55e';
  };
}
connect();

// Initial fetch
fetch('/data').then(r => r.json()).then(update).catch(() => {});

// Command sending
document.getElementById('cmd-send').addEventListener('click', sendCmd);
document.getElementById('cmd-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') sendCmd();
});

function sendCmd() {
  const input = document.getElementById('cmd-input');
  const cmd = input.value.trim();
  if (!cmd) return;
  fetch('/command', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({command: cmd})
  }).then(r => r.json()).then(data => {
    document.getElementById('cmd-log').textContent = '> ' + cmd + ' (sent)';
    input.value = '';
  }).catch(err => {
    document.getElementById('cmd-log').textContent = 'Error: ' + err;
  });
}
</script>
</body>
</html>"""


def file_watcher(dashboard_state, interval=3):
    """Background thread that checks for file changes."""
    while True:
        dashboard_state.check_for_changes()
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="TraitTrawler live dashboard server")
    parser.add_argument("--project-root", default=os.getcwd(),
                        help="Path to the TraitTrawler project root")
    parser.add_argument("--port", type=int, default=8347,
                        help="Port to serve on (default: 8347)")
    args = parser.parse_args()

    global state
    state = DashboardState(args.project_root)

    # Initial check
    state.check_for_changes()

    server = HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    server.daemon_threads = True

    print(f"TraitTrawler dashboard: http://localhost:{args.port}")
    print(f"Project root: {args.project_root}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server.")
        server.shutdown()


if __name__ == "__main__":
    main()
