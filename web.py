"""
web.py — Furnace monitor Flask dashboard and API.

Serves a local dashboard and /api/burns JSON endpoint.
Run with: venv/bin/python web.py
Access at: http://<pi-ip>:8080
"""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

CONFIG_PATH = Path(__file__).parent / "config.json"
CSV_PATH = Path(__file__).parent / "burns.csv"

app = Flask(__name__)


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_sessions(days=30):
    days = min(int(days), 365)
    cutoff = datetime.now() - timedelta(days=days)
    sessions = []
    if not CSV_PATH.exists():
        return sessions, days
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            try:
                start = datetime.strptime(row["start_time"], "%Y-%m-%d %H:%M:%S")
                if start >= cutoff:
                    sessions.append({
                        "session_id": int(row["session_id"]),
                        "start_time": row["start_time"],
                        "end_time": row["end_time"],
                        "duration_seconds": int(row["duration_seconds"]),
                    })
            except (ValueError, KeyError):
                continue
    sessions.sort(key=lambda s: s["start_time"])
    return sessions, days


def load_all_sessions():
    sessions = []
    if not CSV_PATH.exists():
        return sessions
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            try:
                sessions.append({
                    "session_id": int(row["session_id"]),
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "duration_seconds": int(row["duration_seconds"]),
                })
            except (ValueError, KeyError):
                continue
    return sessions


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.route("/api/burns")
def api_burns():
    days = request.args.get("days", 30)
    sessions, days_requested = load_sessions(days)
    return jsonify({
        "sessions": sessions,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days_requested": days_requested,
    })


@app.route("/api/status")
def api_status():
    all_sessions = load_all_sessions()
    last_burn = None
    if all_sessions:
        last = all_sessions[-1]
        last_burn = last["end_time"]
    return jsonify({
        "status": "ok",
        "last_burn": last_burn,
        "currently_burning": False,  # monitor.py owns state; web.py is read-only
    })


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Furnace Monitor</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/hammerjs@2"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f172a;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    min-height: 100vh;
    padding: 24px 16px;
  }
  h1 {
    font-size: 1.5rem;
    font-weight: 700;
    color: #fb923c;
    margin-bottom: 24px;
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }
  .card {
    background: #1e293b;
    border-radius: 12px;
    padding: 16px;
  }
  .card-label {
    font-size: 0.75rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
  }
  .card-value {
    font-size: 1.25rem;
    font-weight: 600;
    color: #e2e8f0;
  }
  .card-sub {
    font-size: 0.75rem;
    color: #94a3b8;
    margin-top: 2px;
  }
  .controls {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  button {
    background: #1e293b;
    color: #94a3b8;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 0.875rem;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  button.active {
    background: #fb923c;
    color: #0f172a;
    font-weight: 600;
  }
  button:hover:not(.active) {
    background: #334155;
    color: #e2e8f0;
  }
  .chart-container {
    background: #1e293b;
    border-radius: 12px;
    padding: 20px;
  }
  canvas { width: 100% !important; }
  .no-data {
    color: #64748b;
    text-align: center;
    padding: 48px 0;
    font-size: 0.95rem;
  }
</style>
</head>
<body>
<h1>Furnace Monitor</h1>

<div class="cards" id="cards">
  <div class="card"><div class="card-label">Today</div><div class="card-value" id="c-today">—</div><div class="card-sub" id="c-today-sub"></div></div>
  <div class="card"><div class="card-label">Yesterday</div><div class="card-value" id="c-yesterday">—</div></div>
  <div class="card"><div class="card-label">This week</div><div class="card-value" id="c-week">—</div></div>
  <div class="card"><div class="card-label">Longest burn</div><div class="card-value" id="c-longest">—</div><div class="card-sub" id="c-longest-sub"></div></div>
  <div class="card"><div class="card-label">Last burn</div><div class="card-value" id="c-last">—</div></div>
</div>

<div class="controls">
  <button id="btn-timeline" class="active" onclick="setView('timeline')">Timeline</button>
  <button id="btn-daily" onclick="setView('daily')">Daily totals</button>
  <button onclick="resetZoom()" style="margin-left:auto">Reset zoom</button>
</div>

<div class="chart-container">
  <div id="no-data" class="no-data" style="display:none">No burn data available yet.</div>
  <canvas id="chart"></canvas>
</div>

<script>
let sessions = [];
let chart = null;
let currentView = 'timeline';

function fmtDuration(secs) {
  const m = Math.floor(secs / 60), s = secs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function fmtHours(secs) {
  const h = secs / 3600;
  return h >= 1 ? `${h.toFixed(1)} hrs` : `${Math.round(secs / 60)} min`;
}

function dateKey(dtStr) {
  return dtStr.slice(0, 10);
}

function localDateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth()+1).padStart(2,'0');
  const d = String(date.getDate()).padStart(2,'0');
  return `${y}-${m}-${d}`;
}

function populateCards(data) {
  const todayKey = localDateKey(new Date());
  const yd = new Date(); yd.setDate(yd.getDate()-1);
  const yesterdayKey = localDateKey(yd);
  const weekAgo = new Date(); weekAgo.setDate(weekAgo.getDate()-7);

  let todaySecs = 0, todayCount = 0, yesterdaySecs = 0, weekSecs = 0;
  let longestSecs = 0, longestDate = null, lastEnd = null;

  data.forEach(s => {
    const k = dateKey(s.start_time);
    const dur = s.duration_seconds;
    if (k === todayKey) { todaySecs += dur; todayCount++; }
    if (k === yesterdayKey) yesterdaySecs += dur;
    const t = new Date(s.start_time.replace(' ','T'));
    if (t >= weekAgo) weekSecs += dur;
    if (dur > longestSecs) { longestSecs = dur; longestDate = k; }
    const e = new Date(s.end_time.replace(' ','T'));
    if (!lastEnd || e > lastEnd) lastEnd = e;
  });

  document.getElementById('c-today').textContent = `${todayCount} burn${todayCount!==1?'s':''}, ${fmtHours(todaySecs)}`;
  document.getElementById('c-yesterday').textContent = fmtHours(yesterdaySecs);
  document.getElementById('c-week').textContent = fmtHours(weekSecs);
  document.getElementById('c-longest').textContent = longestSecs ? fmtDuration(longestSecs) : '—';
  if (longestDate) document.getElementById('c-longest-sub').textContent = longestDate;

  if (lastEnd) {
    const diffMs = Date.now() - lastEnd.getTime();
    const diffMin = Math.round(diffMs / 60000);
    document.getElementById('c-last').textContent =
      diffMin < 60 ? `${diffMin} min ago` : lastEnd.toLocaleString();
  }
}

function fmtTimelineLabel(dtStr) {
  const d = new Date(dtStr.replace(' ', 'T'));
  let h = d.getHours();
  const min = String(d.getMinutes()).padStart(2, '0');
  const ampm = h >= 12 ? 'pm' : 'am';
  h = h % 12 || 12;
  return `${d.getMonth()+1}/${d.getDate()} ${h}:${min}${ampm}`;
}

function buildTimeline(data) {
  const labels = data.map(s => fmtTimelineLabel(s.start_time));
  const values = data.map(s => +(s.duration_seconds / 60).toFixed(1));
  return {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Burn duration (min)',
        data: values,
        backgroundColor: '#fb923c',
        borderRadius: 3,
        barPercentage: 0.6,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => fmtDuration(data[ctx.dataIndex].duration_seconds),
          }
        },
        zoom: {
          pan: { enabled: true, mode: 'x' },
          zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' },
        },
      },
      scales: {
        x: { ticks: { color: '#64748b', maxTicksLimit: 10 }, grid: { color: '#1e293b' } },
        y: { ticks: { color: '#64748b' }, grid: { color: '#334155' }, title: { display: true, text: 'Duration (min)', color: '#64748b' } },
      },
    }
  };
}

function buildDaily(data) {
  const totals = {};
  data.forEach(s => {
    const k = dateKey(s.start_time);
    totals[k] = (totals[k] || 0) + s.duration_seconds;
  });
  const sortedKeys = Object.keys(totals).sort();
  const values = sortedKeys.map(k => +(totals[k] / 3600).toFixed(2));
  const labels = sortedKeys.map(k => { const [y,m,d] = k.split('-'); return `${d}/${m}/${y.slice(2)}`; });
  return {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Daily burn time (hrs)',
        data: values,
        backgroundColor: '#fb923c',
        borderRadius: 4,
        barPercentage: 0.7,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => fmtHours(Math.round(ctx.parsed.y * 3600)),
          }
        },
        zoom: {
          pan: { enabled: true, mode: 'x' },
          zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' },
        },
      },
      scales: {
        x: { ticks: { color: '#64748b' }, grid: { color: '#1e293b' } },
        y: { ticks: { color: '#64748b' }, grid: { color: '#334155' }, title: { display: true, text: 'Hours', color: '#64748b' } },
      },
    }
  };
}

function renderChart() {
  const noData = document.getElementById('no-data');
  const canvas = document.getElementById('chart');

  if (!sessions.length) {
    noData.style.display = 'block';
    canvas.style.display = 'none';
    return;
  }
  noData.style.display = 'none';
  canvas.style.display = 'block';

  const cfg = currentView === 'timeline' ? buildTimeline(sessions) : buildDaily(sessions);
  if (chart) chart.destroy();
  chart = new Chart(canvas, cfg);
}

function setView(view) {
  currentView = view;
  document.getElementById('btn-timeline').classList.toggle('active', view === 'timeline');
  document.getElementById('btn-daily').classList.toggle('active', view === 'daily');
  renderChart();
}

function resetZoom() {
  if (chart) chart.resetZoom();
}

async function init() {
  try {
    const res = await fetch('/api/burns?days=30');
    const json = await res.json();
    sessions = json.sessions || [];
  } catch (e) {
    sessions = [];
  }
  populateCards(sessions);
  renderChart();
}

init();
</script>
</body>
</html>"""


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


if __name__ == "__main__":
    cfg = load_config()
    app.run(host="0.0.0.0", port=cfg.get("port", 8080), debug=False)
