/* Time2Space 上位机 — 前端逻辑（零外部依赖，全部 canvas 手绘） */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const state = {
    mode: "demo",
    connected: false,
    data: null,
    history: [],
    logs: [],
    sweep: 0,
    spin: 0.55,
    drag: null,
    waveCells: [],
    barFills: [],
    barVals: [],
  };

  const log = (msg) => {
    const t = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    state.logs.push(`[${t}] ${msg}`);
    if (state.logs.length > 200) state.logs = state.logs.slice(-200);
    $("#logBox").textContent = state.logs.join("\n");
    $("#logBox").scrollTop = $("#logBox").scrollHeight;
  };

  // ---------------- 通道条 & 波形卡 初始化 ----------------
  const chBars = $("#channelBars");
  for (let i = 0; i < 9; i++) {
    const row = document.createElement("div");
    row.className = "ch-row";
    row.innerHTML = `<span class="lbl">CH${i}</span>
      <div class="bar-track"><div class="bar-fill" style="width:0%"></div></div>
      <span class="val">— cm</span>`;
    chBars.appendChild(row);
    state.barFills.push(row.querySelector(".bar-fill"));
    state.barVals.push(row.querySelector(".val"));
  }

  const waveGrid = $("#waveGrid");
  for (let i = 0; i < 9; i++) {
    const cell = document.createElement("div");
    cell.className = "wave-cell";
    cell.innerHTML = `<header><span>CH${i}</span><b class="wf-tof">—</b></header>
      <canvas width="240" height="70"></canvas>`;
    waveGrid.appendChild(cell);
    state.waveCells.push(cell);
  }

  // ---------------- 扇形 B 模式 ----------------
  const sector = $("#sectorCanvas");
  const sctx = sector.getContext("2d");
  const speckle = document.createElement("canvas");
  speckle.width = sector.width;
  speckle.height = sector.height;
  (function buildSpeckle() {
    const c = speckle.getContext("2d");
    const img = c.createImageData(speckle.width, speckle.height);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = Math.random() * 26;
      img.data[i] = 14 + v * 0.5;
      img.data[i + 1] = 22 + v * 0.7;
      img.data[i + 2] = 40 + v;
      img.data[i + 3] = 255;
    }
    c.putImageData(img, 0, 0);
  })();

  function drawSector(d) {
    const W = sector.width, H = sector.height;
    const cx = W / 2, cy = 34;
    const rOuter = H - 52;
    const a0 = Math.PI * 0.22, a1 = Math.PI * 0.78;

    sctx.clearRect(0, 0, W, H);
    sctx.save();
    sctx.beginPath();
    sctx.moveTo(cx, cy);
    sctx.arc(cx, cy, rOuter, Math.PI / 2 - (Math.PI - (a1 - a0)) / 2 - (Math.PI - (a1 - a0)) / 2, 0);
    // 扇形路径
    sctx.beginPath();
    sctx.moveTo(cx, cy);
    sctx.arc(cx, cy, rOuter, a0, a1);
    sctx.closePath();
    sctx.clip();

    sctx.drawImage(speckle, 0, 0);
    // 顶部组织层
    const grad = sctx.createLinearGradient(0, cy, 0, cy + 90);
    grad.addColorStop(0, "rgba(148,163,184,0.28)");
    grad.addColorStop(1, "rgba(148,163,184,0)");
    sctx.fillStyle = grad;
    sctx.fillRect(0, cy, W, 90);

    if (d) {
      // 深度 → 像素半径：1..13cm 映射到 40..rOuter
      const px = (cm) => 40 + (Math.min(Math.max(cm, 1), 13) - 1) / 12 * (rOuter - 40);
      const ys = d.dist_cm || [];
      const bw = Math.max(...ys, 6), aw = Math.min(...ys.filter((v) => v > 0), 9) || 5;
      const rA = px(aw), rB = px(bw + 2.4);
      const aL = a0 + 0.10, aR = a1 - 0.10;

      // 尿液无回声区：前后壁弧之间
      sctx.beginPath();
      sctx.arc(cx, cy, rB, aL, aR);
      sctx.arc(cx, cy, rA, aR, aL, true);
      sctx.closePath();
      sctx.fillStyle = "rgba(6,12,26,0.92)";
      sctx.fill();

      // 膀胱壁强回波（沿深度弧线，真实 B 模观感）
      for (const [rr, alpha, thick] of [[rA, 0.95, 5], [rB, 0.85, 4]]) {
        sctx.beginPath();
        sctx.arc(cx, cy, rr, aL, aR);
        sctx.strokeStyle = `rgba(226,232,240,${alpha})`;
        sctx.lineWidth = thick;
        sctx.lineCap = "round";
        sctx.shadowColor = "rgba(226,232,240,0.6)";
        sctx.shadowBlur = 9;
        sctx.stroke();
        sctx.shadowBlur = 0;
      }
      // 侧壁闭合
      sctx.strokeStyle = "rgba(226,232,240,0.55)";
      sctx.lineWidth = 3;
      for (const aa of [aL, aR]) {
        sctx.beginPath();
        sctx.moveTo(cx + Math.cos(aa) * rA, cy + Math.sin(aa) * rA);
        sctx.lineTo(cx + Math.cos(aa) * rB, cy + Math.sin(aa) * rB);
        sctx.stroke();
      }

      // 9 条声轴（暗弱）
      sctx.strokeStyle = "rgba(34,197,94,0.10)";
      sctx.lineWidth = 1;
      for (let i = 0; i < 9; i++) {
        const a = a0 + (a1 - a0) * (i + 0.5) / 9;
        sctx.beginPath();
        sctx.moveTo(cx, cy);
        sctx.lineTo(cx + Math.cos(a) * rOuter, cy + Math.sin(a) * rOuter);
        sctx.stroke();
      }
    }

    // 扫查线
    const sweepA = a0 + ((a1 - a0) * (state.sweep % 1));
    const beam = sctx.createLinearGradient(cx, cy, cx + Math.cos(sweepA) * rOuter, cy + Math.sin(sweepA) * rOuter);
    beam.addColorStop(0, "rgba(34,197,94,0.45)");
    beam.addColorStop(1, "rgba(34,197,94,0.02)");
    sctx.beginPath();
    sctx.moveTo(cx, cy);
    sctx.arc(cx, cy, rOuter, sweepA - 0.045, sweepA + 0.045);
    sctx.closePath();
    sctx.fillStyle = beam;
    sctx.fill();

    sctx.restore();

    // 深度刻度
    sctx.fillStyle = "rgba(148,163,184,0.75)";
    sctx.font = "11px 'Fira Code', monospace";
    for (let cm = 2; cm <= 12; cm += 2) {
      const yy = 40 + (cm - 1) / 12 * (rOuter - 40);
      sctx.fillText(cm + "cm", cx + W * 0.36, yy);
      sctx.fillRect(cx + W * 0.34, yy - 0.5, 8, 1);
    }

    // 底部帧信息
    sctx.fillStyle = "rgba(148,163,184,0.85)";
    sctx.font = "11.5px 'Fira Sans', sans-serif";
    const info = d ? `PRF 100Hz · 通道轮询 9 · 帧 ${d.stats?.frames ?? 0}` : "等待数据…";
    sctx.fillText(info, 16, H - 14);
  }

  // ---------------- 仪表盘 ----------------
  const gauge = $("#gaugeCanvas");
  const gctx = gauge.getContext("2d");

  function drawGauge(vol) {
    const W = gauge.width, H = gauge.height;
    const cx = W / 2, cy = H - 18, R = Math.min(W, H * 1.85) / 2 - 18;
    gctx.clearRect(0, 0, W, H);
    const a0 = Math.PI, a1 = Math.PI * 2;
    // 底弧
    gctx.beginPath();
    gctx.arc(cx, cy, R, a0, a1);
    gctx.lineWidth = 13;
    gctx.lineCap = "round";
    gctx.strokeStyle = "rgba(148,163,184,0.18)";
    gctx.stroke();
    // 值弧
    const frac = Math.min(Math.max((vol || 0) / 500, 0), 1);
    const grad = gctx.createLinearGradient(cx - R, 0, cx + R, 0);
    grad.addColorStop(0, "#22C55E");
    grad.addColorStop(0.7, "#4ADE80");
    grad.addColorStop(1, "#86EFAC");
    gctx.beginPath();
    gctx.arc(cx, cy, R, a0, a0 + Math.PI * frac);
    gctx.strokeStyle = grad;
    gctx.stroke();
    // 刻度
    gctx.fillStyle = "rgba(148,163,184,0.8)";
    gctx.font = "10px 'Fira Code', monospace";
    for (let i = 0; i <= 5; i++) {
      const a = a0 + Math.PI * (i / 5);
      const x1 = cx + Math.cos(a) * (R - 20), y1 = cy + Math.sin(a) * (R - 20);
      gctx.fillText(String(i * 100), x1 - 8, y1 + (i === 0 || i === 5 ? 12 : -8));
    }
  }

  // ---------------- 3D 重建 ----------------
  const recon = $("#reconCanvas");
  const rctx = recon.getContext("2d");

  recon.addEventListener("pointerdown", (e) => {
    state.drag = { x: e.clientX, y: e.clientY, spin: state.spin, pitch: state.pitch || 0.5 };
  });
  window.addEventListener("pointermove", (e) => {
    if (!state.drag) return;
    state.spin = state.drag.spin + (e.clientX - state.drag.x) * 0.008;
    state.pitch = Math.min(1.3, Math.max(0.05, state.drag.pitch + (e.clientY - state.drag.y) * 0.006));
  });
  window.addEventListener("pointerup", () => (state.drag = null));

  function drawRecon(d) {
    const W = recon.width, H = recon.height;
    rctx.clearRect(0, 0, W, H);
    const pitch = state.pitch || 0.55;
    const cy_ = 0.55, cz_ = 0.06; // 旋转参考
    const scale = 1050; // m -> px

    const project = (p) => {
      // p: [x,y,z] in m, 以膀胱中心附近为原点
      const x = p[0], y = p[1] - cy_ * 0.0, z = p[2] - cz_;
      const s = Math.sin(state.spin), c = Math.cos(state.spin);
      const X = x * c - y * s;
      const Y = x * s + y * c;
      const sp = Math.sin(pitch), cp = Math.cos(pitch);
      const Y2 = Y * cp - z * sp * 1.2;
      const Z2 = Y * sp + z * cp;
      const persp = 1 / (1 + Z2 * 6);
      return [W / 2 + X * scale * persp, H / 2 + Y2 * scale * persp, Z2];
    };

    // 网格地面
    rctx.strokeStyle = "rgba(71,85,105,0.28)";
    rctx.lineWidth = 1;
    for (let i = -3; i <= 3; i++) {
      const a = project([i * 0.012, -0.036, 0.06]);
      const b = project([i * 0.012, 0.036, 0.06]);
      const c2 = project([-0.036, i * 0.012, 0.06]);
      const e = project([0.036, i * 0.012, 0.06]);
      rctx.beginPath(); rctx.moveTo(a[0], a[1]); rctx.lineTo(b[0], b[1]); rctx.stroke();
      rctx.beginPath(); rctx.moveTo(c2[0], c2[1]); rctx.lineTo(e[0], e[1]); rctx.stroke();
    }

    if (!d || !d.points) return;
    // 拟合球
    const cr = (d.center_mm || [0, 0, 76]).map((v) => v / 1000);
    const rr = (d.radius_mm || 40) / 1000;

    // 球面线框
    const drawArc = (pts) => {
      rctx.beginPath();
      pts.forEach((p, i) => {
        const q = project([cr[0] + p[0], cr[1] + p[1], cr[2] + p[2]]);
        i ? rctx.lineTo(q[0], q[1]) : rctx.moveTo(q[0], q[1]);
      });
      rctx.stroke();
    };
    rctx.strokeStyle = "rgba(34,197,94,0.5)";
    rctx.lineWidth = 1.25;
    for (let k = 0; k < 8; k++) {
      const t0 = (k / 8) * Math.PI * 2;
      const pts = [];
      for (let i = 0; i <= 36; i++) {
        const ph = (i / 36) * Math.PI * 2;
        pts.push([Math.cos(ph) * Math.cos(t0) * rr, Math.cos(ph) * Math.sin(t0) * rr, Math.sin(ph) * rr]);
      }
      drawArc(pts);
    }
    for (let k = 1; k < 6; k++) {
      const lat = -Math.PI / 2 + (k / 6) * Math.PI;
      const pts = [];
      for (let i = 0; i <= 48; i++) {
        const t = (i / 48) * Math.PI * 2;
        pts.push([Math.cos(t) * Math.cos(lat) * rr, Math.sin(t) * Math.cos(lat) * rr, Math.sin(lat) * rr]);
      }
      drawArc(pts);
    }

    // 9 测点
    d.points.forEach((p) => {
      const q = project(p);
      rctx.beginPath();
      rctx.arc(q[0], q[1], 5, 0, Math.PI * 2);
      rctx.fillStyle = "#22C55E";
      rctx.shadowColor = "rgba(34,197,94,0.8)";
      rctx.shadowBlur = 10;
      rctx.fill();
      rctx.shadowBlur = 0;
      rctx.beginPath();
      rctx.arc(q[0], q[1], 8, 0, Math.PI * 2);
      rctx.strokeStyle = "rgba(34,197,94,0.35)";
      rctx.lineWidth = 1;
      rctx.stroke();
    });

    // 中心十字
    const cpt = project(cr);
    rctx.strokeStyle = "rgba(226,232,240,0.7)";
    rctx.beginPath();
    rctx.moveTo(cpt[0] - 7, cpt[1]); rctx.lineTo(cpt[0] + 7, cpt[1]);
    rctx.moveTo(cpt[0], cpt[1] - 7); rctx.lineTo(cpt[0], cpt[1] + 7);
    rctx.stroke();

    rctx.fillStyle = "rgba(148,163,184,0.9)";
    rctx.font = "11px 'Fira Sans', sans-serif";
    rctx.fillText(`球心 (${d.center_mm.map((v) => (v / 10).toFixed(1)).join(", ")}) cm`, 12, H - 12);
  }

  // ---------------- 趋势 ----------------
  const trend = $("#trendCanvas");
  const tctx = trend.getContext("2d");

  function drawTrend(d) {
    const W = trend.width, H = trend.height;
    tctx.clearRect(0, 0, W, H);
    const hist = (d && d.history) || [];
    const padL = 46, padB = 22, padT = 14, padR = 12;

    // 网格
    tctx.strokeStyle = "rgba(71,85,105,0.3)";
    tctx.fillStyle = "rgba(148,163,184,0.7)";
    tctx.font = "10px 'Fira Code', monospace";
    for (let i = 0; i <= 4; i++) {
      const y = padT + (H - padT - padB) * (i / 4);
      tctx.beginPath();
      tctx.moveTo(padL, y); tctx.lineTo(W - padR, y);
      tctx.stroke();
      tctx.fillText(String(500 - i * 125), 8, y + 3);
    }

    if (hist.length < 2) {
      tctx.fillStyle = "rgba(148,163,184,0.55)";
      tctx.font = "12px 'Fira Sans', sans-serif";
      tctx.fillText("趋势数据积累中…", W / 2 - 44, H / 2);
      return;
    }
    const t1 = hist[hist.length - 1][0];
    const t0 = Math.max(hist[0][0], t1 - 240);
    const X = (t) => padL + (W - padL - padR) * ((t - t0) / (t1 - t0 || 1));
    const Y = (v) => padT + (H - padT - padB) * (1 - Math.min(Math.max(v / 500, 0), 1));

    // 渐变填充
    const grad = tctx.createLinearGradient(0, padT, 0, H - padB);
    grad.addColorStop(0, "rgba(34,197,94,0.35)");
    grad.addColorStop(1, "rgba(34,197,94,0.01)");
    tctx.beginPath();
    hist.forEach(([t, v], i) => {
      const x = X(t), y = Y(v);
      i ? tctx.lineTo(x, y) : tctx.moveTo(x, y);
    });
    tctx.lineTo(X(t1), H - padB);
    tctx.lineTo(X(t0), H - padB);
    tctx.closePath();
    tctx.fillStyle = grad;
    tctx.fill();

    // 线
    tctx.beginPath();
    hist.forEach(([t, v], i) => {
      const x = X(t), y = Y(v);
      i ? tctx.lineTo(x, y) : tctx.moveTo(x, y);
    });
    tctx.strokeStyle = "#22C55E";
    tctx.lineWidth = 2.2;
    tctx.stroke();

    // 端点
    const [te, ve] = hist[hist.length - 1];
    const xe = X(te), ye = Y(ve);
    tctx.beginPath();
    tctx.arc(xe, ye, 4.5, 0, Math.PI * 2);
    tctx.fillStyle = "#86EFAC";
    tctx.shadowColor = "rgba(34,197,94,0.9)";
    tctx.shadowBlur = 12;
    tctx.fill();
    tctx.shadowBlur = 0;
    tctx.fillStyle = "rgba(148,163,184,0.8)";
    tctx.font = "10px 'Fira Code', monospace";
    tctx.fillText("0m", padL, H - 8);
    tctx.fillText("-4m", W / 2 - 12, H - 8);
  }

  // ---------------- 波形 ----------------
  function drawWaves(d) {
    const waves = (d && d.wave) || [];
    const tof = (d && d.tof) || [];
    state.waveCells.forEach((cell, i) => {
      const cv = cell.querySelector("canvas");
      const ctx = cv.getContext("2d");
      const W = cv.width, H = cv.height;
      ctx.clearRect(0, 0, W, H);
      const w = waves[i] || [];
      if (!w.length) return;
      const tofLabel = cell.querySelector(".wf-tof");
      if (tofLabel) tofLabel.textContent = `TOF ${tof[i] ?? "—"}`;

      // 网格
      ctx.strokeStyle = "rgba(71,85,105,0.25)";
      ctx.lineWidth = 1;
      for (let g = 1; g < 4; g++) {
        const y = (H * g) / 4;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      // 波形
      ctx.beginPath();
      w.forEach((v, k) => {
        const x = (k / 255) * W;
        const y = H - 4 - (v / 255) * (H - 10);
        k ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      const grad = ctx.createLinearGradient(0, 0, W, 0);
      grad.addColorStop(0, "rgba(56,189,248,0.9)");
      grad.addColorStop(1, "rgba(34,197,94,0.9)");
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.6;
      ctx.stroke();
      // TOF 光标
      const pos = ((tof[i] || 0) / 16 / 255) * W;
      ctx.strokeStyle = "rgba(245,158,11,0.8)";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(pos, 2); ctx.lineTo(pos, H - 2);
      ctx.stroke();
      ctx.setLineDash([]);
    });
  }

  // ---------------- 渲染主循环 ----------------
  function renderAll() {
    const d = state.data;
    drawSector(d);
    drawGauge(d ? d.volume_ml : 0);
    drawRecon(d);
    drawTrend(d);
    drawWaves(d);
  }

  function updateReadouts(d) {
    if (!d) return;
    $("#volumeValue").textContent = d.volume_ml ? d.volume_ml.toFixed(0) : "—";
    $("#radiusValue").textContent = d.radius_mm ? `${d.radius_mm.toFixed(1)} mm` : "—";
    const cm = d.center_mm || [0, 0, 0];
    $("#centerValue").textContent = `${(cm[2] / 10).toFixed(1)} cm`;
    $("#fpsValue").textContent = d.stats ? (d.stats.rate || `${d.stats.fps} /s`) : "—";
    $("#framesValue").textContent = d.stats ? String(d.stats.frames) : "—";

    (d.dist_cm || []).forEach((v, i) => {
      const pct = Math.min(Math.max((v / 12) * 100, 0), 100);
      if (state.barFills[i]) state.barFills[i].style.width = pct + "%";
      if (state.barVals[i]) state.barVals[i].textContent = `${v.toFixed(1)} cm`;
    });

    const pill = $("#statusPill");
    const st = $("#statusText");
    if (d.connected) {
      pill.classList.remove("off");
      st.textContent = d.label || "已连接";
    } else {
      pill.classList.add("off");
      st.textContent = d.error || "未连接 · 演示兜底";
    }
    $("#liveChip").style.display = d.connected ? "" : "none";
  }

  // ---------------- 数据轮询 ----------------
  async function poll() {
    try {
      const res = await fetch("/api/state");
      state.data = await res.json();
      updateReadouts(state.data);
    } catch (e) {
      /* 保持上一帧 */
    }
  }

  function loop() {
    state.sweep += 0.012;
    if (!state.drag) state.spin += 0.0035;
    renderAll();
    requestAnimationFrame(loop);
  }

  setInterval(poll, 220);
  poll().then(() => { renderAll(); loop(); });

  // ---------------- 连接控制 ----------------
  async function refreshPorts() {
    try {
      const res = await fetch("/api/ports");
      const j = await res.json();
      const sel = $("#portSelect");
      sel.innerHTML = `<option value="">选择串口…</option>`;
      (j.ports || []).forEach((p) => {
        const o = document.createElement("option");
        o.value = p.device;
        o.textContent = `${p.device} — ${p.desc}`;
        sel.appendChild(o);
      });
      if (!j.have_serial) log("提示：未安装 pyserial，串口模式不可用（演示模式正常）");
    } catch (e) {
      log("串口列表获取失败");
    }
  }
  refreshPorts();

  $$(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".mode-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.mode = btn.dataset.mode;
      if (state.mode === "demo") {
        doDisconnect();
        log("切换到演示模式（合成回波）");
      } else {
        log(`切换到${state.mode === "bt" ? "蓝牙串口" : "有线串口"}模式，请选择 COM 口后点连接`);
        refreshPorts();
      }
    });
  });

  async function doConnect() {
    const mode = state.mode === "demo" ? "demo" : "serial";
    const port = $("#portSelect").value;
    const baud = $("#baudSelect").value;
    if (mode === "serial" && !port) {
      log("请先选择串口");
      alert("请先在下拉框选择 COM 口");
      return;
    }
    const res = await fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, port, baud: Number(baud) }),
    });
    const j = await res.json();
    if (j.ok) {
      log(`已连接 ${mode === "serial" ? port + " @" + baud : "演示引擎"}`);
      $("#connectBtn").classList.remove("primary");
      $("#connectBtn").classList.add("danger");
      $("#connectBtn").lastChild.textContent = " 断开";
    } else {
      log("连接失败：" + (j.error || "未知错误"));
      alert("连接失败：" + (j.error || "未知错误"));
    }
  }

  async function doDisconnect() {
    await fetch("/api/disconnect", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    $("#connectBtn").classList.add("primary");
    $("#connectBtn").classList.remove("danger");
    $("#connectBtn").lastChild.textContent = " 连接";
    log("已断开，回落演示模式");
    state.mode = "demo";
    $$(".mode-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === "demo"));
  }

  $("#connectBtn").addEventListener("click", () => {
    if ($("#connectBtn").classList.contains("danger")) doDisconnect();
    else doConnect();
  });

  // ---------------- 页签 ----------------
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".tab").forEach((t) => t.classList.remove("active"));
      $$(".tab-pane").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $("#tab-" + tab.dataset.tab).classList.add("active");
    });
  });

  log("上位机就绪 · 演示模式运行中");
  log("两手方案：A 蓝牙 HC-05/04 → COM 口；B USB-TTL → COM 口");
})();
