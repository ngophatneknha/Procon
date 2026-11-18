"""Generates the standalone interactive HTML5 Hex Map Visualizer (`E:\\procon\\visualizer.html`)."""

from __future__ import annotations
import json
from pathlib import Path


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Procon Vietnam 2026 — HEXUDON Interactive Visualizer & Strategy Replay</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #1e293b;
      --panel-border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --gold: #f59e0b;
      --green: #22c55e;
      --red: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      display: grid;
      grid-template-columns: 360px 1fr;
      height: 100vh;
      overflow: hidden;
    }
    .sidebar {
      background: var(--panel);
      border-right: 1px solid var(--panel-border);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      overflow-y: auto;
    }
    .title-box h1 {
      font-size: 18px;
      font-weight: 700;
      color: var(--accent);
      letter-spacing: 0.3px;
    }
    .title-box p {
      font-size: 12px;
      color: var(--muted);
      margin-top: 4px;
    }
    .card {
      background: rgba(15, 23, 42, 0.65);
      border: 1px solid var(--panel-border);
      border-radius: 10px;
      padding: 12px;
    }
    .card h2 {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: var(--muted);
      margin-bottom: 8px;
    }
    select, button, input[type="range"] {
      width: 100%;
      font-family: inherit;
    }
    select, button {
      background: #0f172a;
      color: var(--text);
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 13px;
      cursor: pointer;
    }
    button:hover {
      border-color: var(--accent);
      background: #1e293b;
    }
    button.primary {
      background: #0284c7;
      border-color: #38bdf8;
      font-weight: 600;
    }
    .controls-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 6px;
      margin-top: 8px;
    }
    .day-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .day-pill {
      flex: 1 1 calc(25% - 6px);
      text-align: center;
      padding: 6px 4px;
      font-size: 12px;
      border-radius: 6px;
      background: #0f172a;
      border: 1px solid var(--panel-border);
      cursor: pointer;
    }
    .day-pill.active {
      background: #0284c7;
      border-color: var(--accent);
      font-weight: 700;
    }
    .stat-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .stat-item {
      background: #0f172a;
      border: 1px solid rgba(51, 65, 85, 0.7);
      border-radius: 8px;
      padding: 8px 10px;
    }
    .stat-label {
      font-size: 11px;
      color: var(--muted);
    }
    .stat-value {
      font-size: 17px;
      font-weight: 700;
      margin-top: 2px;
      color: var(--accent);
    }
    .stat-value.gold { color: var(--gold); }
    .stat-value.green { color: var(--green); }
    .agent-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .agent-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: #0f172a;
      padding: 7px 10px;
      border-radius: 6px;
      font-size: 12px;
      border-left: 4px solid var(--accent);
    }
    .agent-row.refuel {
      border-left-color: #f97316;
    }
    .fuel-bar-wrap {
      width: 85px;
      height: 8px;
      background: #334155;
      border-radius: 4px;
      overflow: hidden;
    }
    .fuel-bar {
      height: 100%;
      background: linear-gradient(90deg, #22c55e, #38bdf8);
      transition: width 0.15s ease;
    }
    .legend-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      font-size: 12px;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .swatch {
      width: 14px;
      height: 14px;
      border-radius: 3px;
      border: 1px solid rgba(255,255,255,0.2);
    }
    .main-view {
      position: relative;
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }
    .topbar {
      padding: 10px 18px;
      background: rgba(30, 41, 59, 0.85);
      border-bottom: 1px solid var(--panel-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
    }
    .canvas-container {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: auto;
      padding: 16px;
    }
    canvas {
      background: #0b1120;
      border-radius: 12px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }
  </style>
</head>
<body>
  <aside class="sidebar">
    <div class="title-box">
      <h1>HEXUDON PROCON 2026</h1>
      <p>Hệ thống Mô phỏng & Tối ưu Lộ trình Đa Tác nhân</p>
    </div>

    <div class="card">
      <h2>Kịch bản Thi đấu (Scenario)</h2>
      <select id="scenarioSelect"></select>
    </div>

    <div class="card">
      <h2>Chọn Ngày (Day 1 .. D)</h2>
      <div id="dayPills" class="day-pills"></div>
      <div style="margin-top: 10px;">
        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
          <span>Bước (Step): <strong id="stepLabel">0 / 0</strong></span>
          <span id="eventBanner" style="color:#f59e0b; font-weight:600;"></span>
        </div>
        <input type="range" id="stepSlider" min="0" max="30" value="0" />
        <div class="controls-row">
          <button id="btnPrev">◀ Step</button>
          <button id="btnPlay" class="primary">▶ Play</button>
          <button id="btnNext">Step ▶</button>
          <button id="btnReset">↺ Đầu</button>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Bảng Điểm 4 Tiêu Chí Ưu Tiên (Match Score)</h2>
      <div class="stat-grid">
        <div class="stat-item">
          <div class="stat-label">P1: Loại Udon Toàn trận</div>
          <div class="stat-value gold" id="scoreP1">0 / 0</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">P2: Tổng Loại Hàng ngày</div>
          <div class="stat-value green" id="scoreP2">0</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">P3: Tổng Phần Udon</div>
          <div class="stat-value" id="scoreP3">0</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">P4: Thời gian Phản hồi</div>
          <div class="stat-value" id="scoreP4">0 ms</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Trạng Thái Đội Xe (Agents & Fuel)</h2>
      <div id="agentList" class="agent-list"></div>
    </div>

    <div class="card">
      <h2>Chú giải Bản đồ (Bảng 1)</h2>
      <div class="legend-grid">
        <div class="legend-item"><span class="swatch" style="background:#4ade80;"></span>Đồng bằng (2B, 1NL)</div>
        <div class="legend-item"><span class="swatch" style="background:#b45309;"></span>Núi (3B, 2NL)</div>
        <div class="legend-item"><span class="swatch" style="background:#0284c7;"></span>Ao (Cấm đi)</div>
        <div class="legend-item"><span class="swatch" style="background:#94a3b8;"></span>Đường Thoáng (1B, 2NL)</div>
        <div class="legend-item"><span class="swatch" style="background:#f59e0b;"></span>Đường Đông (2B, 2NL)</div>
        <div class="legend-item"><span class="swatch" style="background:#ef4444;"></span>Đường Tắc (4B, 2NL)</div>
      </div>
    </div>
  </aside>

  <main class="main-view">
    <div class="topbar">
      <div id="topStatus">Đang tải bản đồ...</div>
      <div style="color:var(--muted);">Hệ tọa độ Lục giác <code>even-r</code> (Hàng chẵn lệch phải 0.5 ô theo Hình 1)</div>
    </div>
    <div class="canvas-container">
      <canvas id="hexCanvas" width="1050" height="780"></canvas>
    </div>
  </main>

  <script>
    const REPLAYS = __REPLAYS_JSON__;

    const CHAIN_COLORS = [
      "#f43f5e", "#ec4899", "#a855f7", "#6366f1", "#3b82f6",
      "#06b6d4", "#10b981", "#84cc16", "#eab308", "#f97316",
      "#ef4444", "#14b8a6", "#8b5cf6", "#d946ef", "#fb7185",
      "#38bdf8", "#4ade80", "#facc15"
    ];

    let currentScenarioIdx = 0;
    let currentDayIdx = 0;
    let currentStepIdx = 0;
    let playTimer = null;

    const scenarioSelect = document.getElementById("scenarioSelect");
    const dayPills = document.getElementById("dayPills");
    const stepSlider = document.getElementById("stepSlider");
    const stepLabel = document.getElementById("stepLabel");
    const eventBanner = document.getElementById("eventBanner");
    const canvas = document.getElementById("hexCanvas");
    const ctx = canvas.getContext("2d");

    function init() {
      REPLAYS.forEach((rep, idx) => {
        const opt = document.createElement("option");
        opt.value = idx;
        opt.textContent = rep.scenario_name || `Scenario ${idx + 1}`;
        scenarioSelect.appendChild(opt);
      });

      scenarioSelect.addEventListener("change", (e) => {
        stopPlay();
        currentScenarioIdx = parseInt(e.target.value, 10);
        currentDayIdx = 0;
        currentStepIdx = 0;
        renderDayPills();
        updateView();
      });

      stepSlider.addEventListener("input", (e) => {
        stopPlay();
        currentStepIdx = parseInt(e.target.value, 10);
        updateView();
      });

      document.getElementById("btnPrev").addEventListener("click", () => {
        stopPlay();
        if (currentStepIdx > 0) {
          currentStepIdx--;
          updateView();
        }
      });

      document.getElementById("btnNext").addEventListener("click", () => {
        stopPlay();
        const dayObj = getCurrentDay();
        if (currentStepIdx < dayObj.frames.length - 1) {
          currentStepIdx++;
          updateView();
        }
      });

      document.getElementById("btnReset").addEventListener("click", () => {
        stopPlay();
        currentStepIdx = 0;
        updateView();
      });

      document.getElementById("btnPlay").addEventListener("click", () => {
        if (playTimer) {
          stopPlay();
        } else {
          startPlay();
        }
      });

      renderDayPills();
      updateView();
    }

    function getCurrentReplay() {
      return REPLAYS[currentScenarioIdx];
    }

    function getCurrentDay() {
      return getCurrentReplay().days[currentDayIdx];
    }

    function startPlay() {
      const btn = document.getElementById("btnPlay");
      btn.textContent = "⏸ Pause";
      playTimer = setInterval(() => {
        const rep = getCurrentReplay();
        const dayObj = getCurrentDay();
        if (currentStepIdx < dayObj.frames.length - 1) {
          currentStepIdx++;
          updateView();
        } else if (currentDayIdx < rep.days.length - 1) {
          currentDayIdx++;
          currentStepIdx = 0;
          renderDayPills();
          updateView();
        } else {
          stopPlay();
        }
      }, 240);
    }

    function stopPlay() {
      if (playTimer) {
        clearInterval(playTimer);
        playTimer = null;
      }
      document.getElementById("btnPlay").textContent = "▶ Play";
    }

    function renderDayPills() {
      const rep = getCurrentReplay();
      dayPills.innerHTML = "";
      rep.days.forEach((d, idx) => {
        const pill = document.createElement("div");
        pill.className = "day-pill" + (idx === currentDayIdx ? " active" : "");
        pill.textContent = `Ngày ${d.day}`;
        pill.addEventListener("click", () => {
          stopPlay();
          currentDayIdx = idx;
          currentStepIdx = 0;
          renderDayPills();
          updateView();
        });
        dayPills.appendChild(pill);
      });
    }

    function updateView() {
      const rep = getCurrentReplay();
      const cfg = rep.config;
      const dayObj = getCurrentDay();
      const frame = dayObj.frames[currentStepIdx];

      stepSlider.max = dayObj.frames.length - 1;
      stepSlider.value = currentStepIdx;
      stepLabel.textContent = `${frame.step} / ${dayObj.max_steps}`;

      document.getElementById("scoreP1").textContent =
        `${rep.score.priority_1_unique_chains_total} / ${rep.total_chains_available}`;
      document.getElementById("scoreP2").textContent =
        `${rep.score.priority_2_cumulative_daily_unique_chains}`;
      document.getElementById("scoreP3").textContent =
        `${rep.score.priority_3_total_portions}`;
      document.getElementById("scoreP4").textContent =
        `${rep.score.priority_4_total_response_time_ms} ms`;

      document.getElementById("topStatus").innerHTML =
        `<strong>${rep.scenario_name}</strong> &nbsp;|&nbsp; ` +
        `Ngày ${dayObj.day}/${cfg.num_days} &nbsp;|&nbsp; ` +
        `Loại Udon trong ngày: <strong>${frame.collected_chains_today.length}</strong> &nbsp;|&nbsp; ` +
        ` Lũy kế Toàn trận: <strong>${dayObj.cumulative_unique_chains}/${rep.total_chains_available}</strong>`;

      // Event banner
      const events = [];
      if (frame.collected_events && frame.collected_events.length > 0) {
        events.push(`🍜 Thu thập ${frame.collected_events.length} Udon!`);
      }
      if (frame.refueled_agents && frame.refueled_agents.length > 0) {
        events.push(`⛽ Tiếp đầy xăng Xe #${frame.refueled_agents.join(", #")}!`);
      }
      eventBanner.textContent = events.join("  ");

      // Render Agent Status List
      const agentList = document.getElementById("agentList");
      agentList.innerHTML = "";
      rep.roles.forEach((role, idx) => {
        const cellId = frame.agent_cells[idx];
        const fuel = frame.agent_fuels[idx];
        const row = document.createElement("div");
        row.className = "agent-row" + (role === "REFUEL" ? " refuel" : "");

        const pct = role === "REFUEL" ? 100 : Math.round((fuel / cfg.max_fuel) * 100);
        const fuelText = role === "REFUEL" ? "∞ (Tiếp xăng)" : `${fuel}/${cfg.max_fuel}`;
        const icon = role === "REFUEL" ? "🚚" : "🚓";

        row.innerHTML = `
          <div>
            <strong>${icon} Xe #${idx} (${role})</strong>
            <div style="color:var(--muted); font-size:11px;">Ô hiện tại: #${cellId}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:11px; margin-bottom:3px;">NL: <strong>${fuelText}</strong></div>
            <div class="fuel-bar-wrap">
              <div class="fuel-bar" style="width:${pct}%; background:${role === 'REFUEL' ? '#f97316' : (pct <= 25 ? '#ef4444' : '#22c55e')}"></div>
            </div>
          </div>
        `;
        agentList.appendChild(row);
      });

      drawHexMap(rep, dayObj, frame);
    }

    function drawHexPolygon(ctx, cx, cy, radius) {
      ctx.beginPath();
      for (let i = 0; i < 6; i++) {
        const angleDeg = 60 * i - 30; // Pointy-top hexagon
        const angleRad = (Math.PI / 180) * angleDeg;
        const x = cx + radius * Math.cos(angleRad);
        const y = cy + radius * Math.sin(angleRad);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
    }

    function drawHexMap(rep, dayObj, frame) {
      const cfg = rep.config;
      const W = cfg.width;
      const H = cfg.height;

      const availW = canvas.width - 60;
      const availH = canvas.height - 60;
      const hexR = Math.min(
        availW / ((W + 0.6) * Math.sqrt(3)),
        availH / (H * 1.5 + 0.6)
      );
      const hexW = Math.sqrt(3) * hexR;
      const hexH = 2 * hexR;

      const offsetX = (canvas.width - (W + 0.5) * hexW) / 2 + hexW * 0.5;
      const offsetY = (canvas.height - (H * 1.5 * hexR + 0.5 * hexR)) / 2 + hexR;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Build Spot lookup
      const spotMap = {};
      cfg.spots.forEach(s => { spotMap[s.cell_id] = s; });

      const cellCenters = [];

      // 1. Draw all Hex Cells (even-r: even rows shifted right by +0.5 * hexW)
      for (let r = 0; r < H; r++) {
        const rowShift = (r % 2 === 0) ? (0.5 * hexW) : 0;
        for (let c = 0; c < W; c++) {
          const cellId = r * W + c;
          const cx = offsetX + c * hexW + rowShift;
          const cy = offsetY + r * (1.5 * hexR);
          cellCenters[cellId] = { cx, cy };

          const terrain = cfg.terrains[cellId];
          let fill = "#22c55e";
          if (terrain === "PLAIN") fill = "#3b7a57";
          else if (terrain === "MOUNTAIN") fill = "#92400e";
          else if (terrain === "POND") fill = "#0369a1";
          else if (terrain === "ROAD") {
            const rs = dayObj.road_states[String(cellId)] || 0;
            if (rs === 0) fill = "#64748b";      // Smooth
            else if (rs === 1) fill = "#d97706"; // Congested
            else fill = "#dc2626";               // Jam
          }

          drawHexPolygon(ctx, cx, cy, hexR - 1);
          ctx.fillStyle = fill;
          ctx.fill();
          ctx.lineWidth = 1;
          ctx.strokeStyle = "#0f172a";
          ctx.stroke();

          // Cell ID label
          if (hexR >= 16) {
            ctx.fillStyle = "rgba(255,255,255,0.4)";
            ctx.font = `${Math.max(8, Math.floor(hexR * 0.32))}px sans-serif`;
            ctx.textAlign = "center";
            ctx.fillText(String(cellId), cx, cy - hexR * 0.42);
          }

          // Spot (Udon Shop) icon & stock
          if (spotMap[cellId]) {
            const sp = spotMap[cellId];
            const remStock = frame.spot_stocks[String(cellId)] ?? sp.max_stock;
            const chainColor = CHAIN_COLORS[(sp.chain_id - 1) % CHAIN_COLORS.length];

            ctx.beginPath();
            ctx.arc(cx, cy + 2, hexR * 0.42, 0, Math.PI * 2);
            ctx.fillStyle = remStock > 0 ? chainColor : "#334155";
            ctx.fill();
            ctx.lineWidth = 2;
            ctx.strokeStyle = "#ffffff";
            ctx.stroke();

            ctx.fillStyle = "#ffffff";
            ctx.font = `bold ${Math.max(9, Math.floor(hexR * 0.36))}px sans-serif`;
            ctx.textAlign = "center";
            ctx.fillText(`C${sp.chain_id}`, cx, cy + 4);

            if (hexR >= 15) {
              ctx.font = `bold ${Math.max(8, Math.floor(hexR * 0.28))}px sans-serif`;
              ctx.fillStyle = "#fde047";
              ctx.fillText(`${remStock}/${sp.max_stock}`, cx, cy + hexR * 0.68);
            }
          }
        }
      }

      // 2. Draw Agents (handling multiple agents on the same cell with slight offsets)
      const occupantsByCell = {};
      frame.agent_cells.forEach((cellId, agIdx) => {
        if (!occupantsByCell[cellId]) occupantsByCell[cellId] = [];
        occupantsByCell[cellId].push(agIdx);
      });

      Object.keys(occupantsByCell).forEach(cellStr => {
        const cellId = parseInt(cellStr, 10);
        const agIndices = occupantsByCell[cellId];
        const center = cellCenters[cellId];
        if (!center) return;

        agIndices.forEach((agIdx, k) => {
          const role = rep.roles[agIdx];
          const angle = (2 * Math.PI * k) / agIndices.length;
          const spread = agIndices.length > 1 ? hexR * 0.28 : 0;
          const ax = center.cx + spread * Math.cos(angle);
          const ay = center.cy + spread * Math.sin(angle);

          ctx.beginPath();
          ctx.arc(ax, ay, hexR * 0.36, 0, Math.PI * 2);
          ctx.fillStyle = role === "REFUEL" ? "#f97316" : "#0ea5e9";
          ctx.fill();
          ctx.lineWidth = 2.5;
          ctx.strokeStyle = "#ffffff";
          ctx.stroke();

          ctx.fillStyle = "#ffffff";
          ctx.font = `bold ${Math.max(9, Math.floor(hexR * 0.35))}px sans-serif`;
          ctx.textAlign = "center";
          ctx.fillText(role === "REFUEL" ? `R${agIdx}` : `P${agIdx}`, ax, ay + 3.5);
        });
      });
    }

    init();
  </script>
</body>
</html>
"""


def build_visualizer() -> None:
    root = Path(__file__).resolve().parent
    replays_path = root / "sample_replays.json"
    if not replays_path.exists():
        from run_benchmark import run_all_benchmarks
        replays = run_all_benchmarks()
    else:
        replays = json.loads(replays_path.read_text(encoding="utf-8"))

    html_content = HTML_TEMPLATE.replace("__REPLAYS_JSON__", json.dumps(replays))
    out_path = root / "visualizer.html"
    out_path.write_text(html_content, encoding="utf-8")
    print(f"Generated standalone interactive visualizer at: {out_path}")


if __name__ == "__main__":
    build_visualizer()
