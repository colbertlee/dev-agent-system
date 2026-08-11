"""Web Dashboard：展示工作流状态与 Prometheus 指标。"""
from __future__ import annotations

from typing import Any, Dict, List

from dev_agent_system.metrics import DEFAULT as DEFAULT_METRICS
from dev_agent_system.tracker import WorkflowTracker


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DevAgent System Dashboard</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2rem; background: #f5f6f7; color: #1a1a1a; }}
    h1 {{ font-size: 1.5rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-top: 1rem; }}
    .card {{ background: #fff; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
    .card h2 {{ font-size: 1.1rem; margin-top: 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ text-align: left; padding: 0.5rem; border-bottom: 1px solid #e0e0e0; }}
    th {{ color: #666; font-weight: 600; }}
    pre {{ background: #f0f0f0; padding: 0.75rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; }}
    .badge {{ display: inline-block; padding: 0.2rem 0.5rem; border-radius: 999px; font-size: 0.75rem; background: #e2e8f0; }}
    .badge.completed {{ background: #dcfce7; color: #166534; }}
    .badge.working {{ background: #fef3c7; color: #92400e; }}
    .badge.failed {{ background: #fee2e2; color: #991b1b; }}
    .metrics {{ white-space: pre-wrap; font-family: monospace; }}
  </style>
</head>
<body>
  <h1>DevAgent System Dashboard</h1>
  <p>实时工作流状态与 Prometheus 指标（每 2 秒自动刷新）</p>
  <div class="grid">
    <div class="card">
      <h2>当前工作流</h2>
      <table>
        <thead><tr><th>Request ID</th><th>状态</th><th>迭代</th><th>当前 Agent</th><th>耗时(s)</th></tr></thead>
        <tbody id="workflows"></tbody>
      </table>
    </div>
    <div class="card">
      <h2>当前任务详情</h2>
      <pre id="detail">选择一个 Request ID 查看详情</pre>
    </div>
    <div class="card">
      <h2>指标 /metrics</h2>
      <pre id="metrics" class="metrics">Loading...</pre>
    </div>
  </div>
  <script>
    const fmtTime = (t) => t ? new Date(t * 1000).toLocaleString() : '-';
    const statusClass = (s) => {{ if (s === 'completed') return 'completed'; if (s === 'working') return 'working'; if (s === 'failed') return 'failed'; return ''; }};

    async function loadDashboard() {{
      try {{
        const [statusRes, metricsRes] = await Promise.all([
          fetch('/api/status'),
          fetch('/metrics')
        ]);
        const data = await statusRes.json();
        const metricsText = await metricsRes.text();
        document.getElementById('metrics').textContent = metricsText;

        const tbody = document.getElementById('workflows');
        tbody.innerHTML = '';
        data.workflows.forEach(w => {{
          const tr = document.createElement('tr');
          tr.style.cursor = 'pointer';
          tr.innerHTML = `<td>${{w.request_id}}</td><td><span class="badge ${{statusClass(w.status)}}">${{w.status}}</span></td><td>${{w.iteration}}</td><td>${{w.current_agent || '-'}}</td><td>${{w.elapsed_seconds.toFixed(1)}}</td>`;
          tr.onclick = () => loadDetail(w.request_id);
          tbody.appendChild(tr);
        }});
      }} catch (e) {{
        console.error(e);
      }}
    }}

    async function loadDetail(requestId) {{
      try {{
        const res = await fetch('/api/status/' + encodeURIComponent(requestId));
        const w = await res.json();
        document.getElementById('detail').textContent = JSON.stringify(w, null, 2);
      }} catch (e) {{
        console.error(e);
      }}
    }}

    setInterval(loadDashboard, 2000);
    loadDashboard();
  </script>
</body>
</html>
"""


def dashboard_html() -> str:
    return DASHBOARD_HTML


def status_data(tracker: WorkflowTracker, metrics: Any, limit: int = 50) -> Dict[str, Any]:
    return {
        "workflows": tracker.all_snapshots(limit),
        "metrics_rendered": metrics.render_prometheus(),
    }
