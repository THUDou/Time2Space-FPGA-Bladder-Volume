/* ============================================================
   Time2Space 上位机 — 前端逻辑 v3（零外部依赖，全部 canvas 手绘）
   专业级渲染: 散斑 B 模式 / 精密仪表盘 / 3D 球面重建 / 趋势
   ============================================================ */
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
    pitch: 0.55,
    drag: null,
    waveCells: [],
    barFills: [],
    barVals: [],
    animVol: 0,       // 平滑容积动画
    animTime: 0,
  };

  const log = (msg) => {
    const t = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    state.logs.push(`[${t}] ${msg}`);
    if (state.logs.length > 300) state.logs = state.logs.slice(-300);
    $("#logBox").textContent = state.logs.join("\n");
    $("#logBox").scrollTop = $("#logBox").scrollHeight;
  };

  // ======================== 通道条 & 波形卡 ========================
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
      <canvas width="280" height="80"></canvas>`;
    waveGrid.appendChild(cell);
    state.waveCells.push(cell);
  }

  // ======================== B 模式扇形 ========================
  const sector = $("#sectorCanvas");
  const sctx = sector.getContext("2d");

  // 生成专业级散斑纹理（多尺度噪声 + 组织颗粒感）
  const speckle = document.createElement("canvas");
  speckle.width = sector.width;
  speckle.height = sector.height;
  (function buildSpeckle() {
    const c = speckle.getContext("2d");
    const W = speckle.width, H = speckle.height;
    // 底色
    c.fillStyle = "#0A0F1E";
    c.fillRect(0, 0, W, H);
    // 多层散斑
    for (let layer = 0; layer < 3; layer++) {
      const img = c.createImageData(W, H);
      const d = img.data;
      const scale = layer === 0 ? 1 : layer === 1 ? 2 : 4;
      const intensity = layer === 0 ? 18 : layer === 1 ? 22 : 15;
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          const i = (y * W + x) * 4;
          // 伪随机散斑（基于坐标哈希）
          const n = ((x * 374761393 + y * 668265263) ^ (layer * 2654435761)) >>> 0;
          const r = (n % 255) / 255;
          // 深度衰减：越深越暗
          const depthFade = 1 - (y / H) * 0.65;
          const v = r * intensity * depthFade * (1 + layer * 0.2);
          d[i]     = 10 + v * 0.4;
          d[i + 1] = 16 + v * 0.55;
          d[i + 2] = 30 + v * 0.9;
          d[i + 3] = 255;
        }
      }
      c.globalAlpha = layer === 0 ? 0.7 : layer === 1 ? 0.35 : 0.25;
      c.putImageData(img, 0, 0);
    }
    c.globalAlpha = 1;
  })();

  function drawSector(d) {
    const W = sector.width, H = sector.height;
    const cx = W / 2, cy = 38;
    const rOuter = H - 56;
    const a0 = Math.PI * 0.20, a1 = Math.PI * 0.80;

    sctx.clearRect(0, 0, W, H);

    // 扇形裁剪
    sctx.save();
    sctx.beginPath();
    sctx.moveTo(cx, cy);
    sctx.arc(cx, cy, rOuter, a0, a1);
    sctx.closePath();
    sctx.clip();

    // 散斑底
    sctx.drawImage(speckle, 0, 0);

    // 顶部近场组织层
    const tGrad = sctx.createLinearGradient(0, cy, 0, cy + 80);
    tGrad.addColorStop(0, "rgba(148,163,184,0.22)");
    tGrad.addColorStop(0.5, "rgba(148,163,184,0.10)");
    tGrad.addColorStop(1, "rgba(148,163,184,0)");
    sctx.fillStyle = tGrad;
    sctx.fillRect(0, cy, W, 85);

    if (d) {
      const px = (cm) => 40 + (Math.min(Math.max(cm, 1), 13) - 1) / 12 * (rOuter - 40);
      const ys = d.dist_cm || [];
      const bw = Math.max(...ys, 6), aw = Math.min(...ys.filter((v) => v > 0), 9) || 5;
      const rA = px(aw), rB = px(bw + 2.4);
      const aL = a0 + 0.08, aR = a1 - 0.08;

      // 尿液无回声区（黑色无回声）
      sctx.beginPath();
      sctx.arc(cx, cy, rB, aL, aR);
      sctx.arc(cx, cy, rA, aR, aL, true);
      sctx.closePath();
      sctx.fillStyle = "rgba(5,10,22,0.93)";
      sctx.fill();

      // 内部微弱噪声（液体不是纯黑）
      const fGrad = sctx.createRadialGradient(cx, cy + (rA + rB) / 2 * 0.7, 10, cx, cy + (rA + rB) / 2 * 0.7, (rB - rA) / 2 + 20);
      fGrad.addColorStop(0, "rgba(15,25,50,0.25)");
      fGrad.addColorStop(1, "rgba(5,10,22,0)");
      sctx.fillStyle = fGrad;
      sctx.fillRect(0, cy, W, H);

      // 膀胱壁强回波（带辉光的弧线）
      for (const [rr, alpha, thick] of [[rA, 0.92, 5.5], [rB, 0.82, 4.5]]) {
        // 外层辉光
        sctx.beginPath();
        sctx.arc(cx, cy, rr, aL, aR);
        sctx.strokeStyle = `rgba(226,232,240,${alpha * 0.25})`;
        sctx.lineWidth = thick + 8;
        sctx.lineCap = "round";
        sctx.stroke();
        // 主亮线
        sctx.beginPath();
        sctx.arc(cx, cy, rr, aL, aR);
        sctx.strokeStyle = `rgba(226,232,240,${alpha})`;
        sctx.lineWidth = thick;
        sctx.shadowColor = "rgba(226,232,240,0.55)";
        sctx.shadowBlur = 12;
        sctx.stroke();
        sctx.shadowBlur = 0;
        // 高光核心
        sctx.beginPath();
        sctx.arc(cx, cy, rr, aL, aR);
        sctx.strokeStyle = "rgba(255,255,255,0.6)";
        sctx.lineWidth = thick * 0.35;
        sctx.stroke();
      }

      // 侧壁
      sctx.strokeStyle = "rgba(226,232,240,0.45)";
      sctx.lineWidth = 3;
      for (const aa of [aL, aR]) {
        sctx.beginPath();
        sctx.moveTo(cx + Math.cos(aa) * rA, cy + Math.sin(aa) * rA);
        sctx.lineTo(cx + Math.cos(aa) * rB, cy + Math.sin(aa) * rB);
        sctx.stroke();
      }

      // 9 条声轴（非常暗弱）
      sctx.strokeStyle = "rgba(34,197,94,0.07)";
      sctx.lineWidth = 1;
      for (let i = 0; i < 9; i++) {
        const a = a0 + (a1 - a0) * (i + 0.5) / 9;
        sctx.beginPath();
        sctx.moveTo(cx, cy);
        sctx.lineTo(cx + Math.cos(a) * rOuter, cy + Math.sin(a) * rOuter);
        sctx.stroke();
      }

      // 深度标注（前壁/后壁/厚度）
      const midA = (aL + aR) / 2;
      const labelX = cx + Math.cos(midA) * (rA + rB) / 2;
      const labelY = cy + Math.sin(midA) * (rA + rB) / 2;
      sctx.save();
      sctx.fillStyle = "rgba(34,197,94,0.9)";
      sctx.font = "bold 11px 'Fira Code', monospace";
      sctx.textAlign = "center";
      sctx.fillText(`${aw.toFixed(1)}–${bw.toFixed(1)} cm`, labelX, labelY);
      sctx.restore();
    }

    // 扫查线（带余晖）
    const sweepA = a0 + ((a1 - a0) * (state.sweep % 1));
    const sGrad = sctx.createLinearGradient(cx, cy, cx + Math.cos(sweepA) * rOuter, cy + Math.sin(sweepA) * rOuter);
    sGrad.addColorStop(0, "rgba(34,197,94,0.55)");
    sGrad.addColorStop(0.3, "rgba(34,197,94,0.25)");
    sGrad.addColorStop(1, "rgba(34,197,94,0.0)");
    sctx.beginPath();
    sctx.moveTo(cx, cy);
    sctx.arc(cx, cy, rOuter, sweepA - 0.05, sweepA + 0.05);
    sctx.closePath();
    sctx.fillStyle = sGrad;
    sctx.fill();

    // 扫查余晖
    for (let trail = 1; trail <= 3; trail++) {
      const tA = sweepA - trail * 0.055;
      const tGrad = sctx.createLinearGradient(cx, cy, cx + Math.cos(tA) * rOuter, cy + Math.sin(tA) * rOuter);
      tGrad.addColorStop(0, `rgba(34,197,94,${0.12 / trail})`);
      tGrad.addColorStop(1, "rgba(34,197,94,0)");
      sctx.beginPath();
      sctx.moveTo(cx, cy);
      sctx.arc(cx, cy, rOuter, tA - 0.025, tA + 0.025);
      sctx.closePath();
      sctx.fillStyle = tGrad;
      sctx.fill();
    }

    sctx.restore();

    // 深度刻度（扇形外侧）
    sctx.fillStyle = "rgba(148,163,184,0.6)";
    sctx.font = "10px 'Fira Code', monospace";
    sctx.textAlign = "left";
    for (let cm = 2; cm <= 12; cm += 2) {
      const yy = 40 + (cm - 1) / 12 * (rOuter - 40);
      sctx.fillText(cm + "cm", cx + W * 0.37, yy + 3);
      sctx.fillRect(cx + W * 0.355, yy, 9, 1);
    }

    // 顶部标题
    sctx.fillStyle = "rgba(148,163,184,0.55)";
    sctx.font = "10px 'Fira Sans', sans-serif";
    sctx.textAlign = "right";
    sctx.fillText("B-MODE", W - 14, 22);
    sctx.textAlign = "left";

    // 底部帧信息
    sctx.fillStyle = "rgba(148,163,184,0.75)";
    sctx.font = "11px 'Fira Sans', sans-serif";
    const info = d ? `PRF 100Hz · 通道轮询 9 · 帧 ${d.stats?.frames ?? 0}` : "等待数据…";
    sctx.fillText(info, 16, H - 16);

    // 右下角频率标记
    sctx.fillStyle = "rgba(34,197,94,0.5)";
    sctx.font = "10px 'Fira Code', monospace";
    sctx.textAlign = "right";
    sctx.fillText("3.5 MHz", W - 14, H - 16);
    sctx.textAlign = "left";
  }

  // ======================== 仪表盘 ========================
  const gauge = $("#gaugeCanvas");
  const gctx = gauge.getContext("2d");

  function drawGauge(vol) {
    const W = gauge.width, H = gauge.height;
    const cx = W / 2, cy = H - 22;
    const R = Math.min(W, H * 1.9) / 2 - 26;

    gctx.clearRect(0, 0, W, H);

    // 平滑动画
    const target = vol || 0;
    state.animVol += (target - state.animVol) * 0.08;
    const displayVol = state.animVol;

    const a0 = Math.PI * 0.95, a1 = Math.PI * 2.05;
    const range = a1 - a0;

    // 刻度线（主刻度 + 次刻度）
    for (let i = 0; i <= 25; i++) {
      const frac = i / 25;
      const a = a0 + range * frac;
      const isMajor = i % 5 === 0;
      const r1 = R - (isMajor ? 20 : 14), r2 = R - 5;
      const x1 = cx + Math.cos(a) * r1, y1 = cy + Math.sin(a) * r1;
      const x2 = cx + Math.cos(a) * r2, y2 = cy + Math.sin(a) * r2;
      gctx.beginPath();
      gctx.moveTo(x1, y1); gctx.lineTo(x2, y2);
      gctx.strokeStyle = isMajor ? "rgba(148,163,184,0.5)" : "rgba(148,163,184,0.2)";
      gctx.lineWidth = isMajor ? 1.8 : 1;
      gctx.stroke();
    }

    // 数值刻度
    gctx.fillStyle = "rgba(148,163,184,0.7)";
    gctx.font = "10px 'Fira Code', monospace";
    gctx.textAlign = "center";
    for (let i = 0; i <= 5; i++) {
      const a = a0 + range * (i / 5);
      const tx = cx + Math.cos(a) * (R - 30), ty = cy + Math.sin(a) * (R - 30);
      gctx.fillText(String(i * 100), tx, ty + (i === 0 || i === 5 ? 12 : -6));
    }

    // 底弧
    gctx.beginPath();
    gctx.arc(cx, cy, R, a0, a1);
    gctx.lineWidth = 14;
    gctx.lineCap = "round";
    gctx.strokeStyle = "rgba(148,163,184,0.1)";
    gctx.stroke();

    // 值弧（带渐变 + 辉光）
    const frac = Math.min(Math.max(displayVol / 500, 0), 1);
    const arcGrad = gctx.createLinearGradient(cx - R, cy, cx + R, cy);
    arcGrad.addColorStop(0, "#16A34A");
    arcGrad.addColorStop(0.4, "#22C55E");
    arcGrad.addColorStop(0.8, "#4ADE80");
    arcGrad.addColorStop(1, "#86EFAC");

    // 辉光底层
    gctx.beginPath();
    gctx.arc(cx, cy, R, a0, a0 + range * frac);
    gctx.lineWidth = 18;
    gctx.strokeStyle = "rgba(34,197,94,0.12)";
    gctx.stroke();

    // 主弧
    gctx.beginPath();
    gctx.arc(cx, cy, R, a0, a0 + range * frac);
    gctx.lineWidth = 14;
    gctx.strokeStyle = arcGrad;
    gctx.stroke();

    // 高光弧
    gctx.beginPath();
    gctx.arc(cx, cy, R - 3, a0 + range * Math.max(0, frac - 0.08), a0 + range * frac);
    gctx.lineWidth = 3;
    gctx.strokeStyle = "rgba(255,255,255,0.25)";
    gctx.stroke();

    // 指针
    const needleA = a0 + range * frac;
    const nLen = R - 28;
    const nx = cx + Math.cos(needleA) * nLen, ny = cy + Math.sin(needleA) * nLen;
    gctx.beginPath();
    gctx.moveTo(cx, cy); gctx.lineTo(nx, ny);
    gctx.strokeStyle = "rgba(248,250,252,0.85)";
    gctx.lineWidth = 2.5;
    gctx.lineCap = "round";
    gctx.stroke();

    // 指针尖端光点
    gctx.beginPath();
    gctx.arc(nx, ny, 5, 0, Math.PI * 2);
    gctx.fillStyle = "#86EFAC";
    gctx.shadowColor = "rgba(34,197,94,0.8)";
    gctx.shadowBlur = 10;
    gctx.fill();
    gctx.shadowBlur = 0;

    // 中心圆
    gctx.beginPath();
    gctx.arc(cx, cy, 7, 0, Math.PI * 2);
    gctx.fillStyle = "#1E293B";
    gctx.fill();
    gctx.beginPath();
    gctx.arc(cx, cy, 3.5, 0, Math.PI * 2);
    gctx.fillStyle = "#22C55E";
    gctx.fill();

    // 底部标签
    gctx.fillStyle = "rgba(148,163,184,0.5)";
    gctx.font = "9px 'Fira Sans', sans-serif";
    gctx.fillText("mL", cx, cy + 16);
  }

  // ======================== 3D 重建 ========================
  const recon = $("#reconCanvas");
  const rctx = recon.getContext("2d");

  recon.addEventListener("pointerdown", (e) => {
    state.drag = { x: e.clientX, y: e.clientY, spin: state.spin, pitch: state.pitch };
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
    const pitch = state.pitch;
    const scale = 1000;

    const project = (p) => {
      const x = p[0], y = p[1], z = p[2] - 0.06;
      const s = Math.sin(state.spin), c = Math.cos(state.spin);
      const X = x * c - y * s;
      const Y = x * s + y * c;
      const sp = Math.sin(pitch), cp = Math.cos(pitch);
      const Y2 = Y * cp - z * sp * 1.2;
      const Z2 = Y * sp + z * cp;
      const persp = 1 / (1 + Z2 * 5.5);
      return [W / 2 + X * scale * persp, H / 2 + Y2 * scale * persp, Z2];
    };

    // 地面网格（极坐标 → 更有科技感）
    rctx.strokeStyle = "rgba(71,85,105,0.18)";
    rctx.lineWidth = 1;
    for (let ring = 1; ring <= 4; ring++) {
      const r = ring * 0.012;
      const pts = [];
      for (let i = 0; i <= 48; i++) {
        const a = (i / 48) * Math.PI * 2;
        pts.push(project([Math.cos(a) * r, Math.sin(a) * r, 0.06]));
      }
      rctx.beginPath();
      pts.forEach((p, i) => i ? rctx.lineTo(p[0], p[1]) : rctx.moveTo(p[0], p[1]));
      rctx.stroke();
    }
    // 放射线
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      const inner = project([Math.cos(a) * 0.012, Math.sin(a) * 0.012, 0.06]);
      const outer = project([Math.cos(a) * 0.048, Math.sin(a) * 0.048, 0.06]);
      rctx.beginPath();
      rctx.moveTo(inner[0], inner[1]); rctx.lineTo(outer[0], outer[1]);
      rctx.stroke();
    }

    if (!d || !d.points) return;
    const cr = (d.center_mm || [0, 0, 76]).map((v) => v / 1000);
    const rr = (d.radius_mm || 40) / 1000;

    // 球面半透明填充（从后到前深度排序）
    const spherePts = [];
    for (let lat = -Math.PI / 2; lat <= Math.PI / 2; lat += Math.PI / 8) {
      for (let lon = 0; lon < Math.PI * 2; lon += Math.PI / 8) {
        const px = Math.cos(lat) * Math.cos(lon) * rr;
        const py = Math.cos(lat) * Math.sin(lon) * rr;
        const pz = Math.sin(lat) * rr;
        spherePts.push({
          p: [cr[0] + px, cr[1] + py, cr[2] + pz],
          z: project([cr[0] + px, cr[1] + py, cr[2] + pz])[2],
          lat, lon
        });
      }
    }
    spherePts.sort((a, b) => a.z - b.z); // 远 → 近

    // 球面线框（经线 + 纬线）
    const drawArc = (pts, alpha) => {
      rctx.beginPath();
      pts.forEach((p, i) => {
        const q = project([cr[0] + p[0], cr[1] + p[1], cr[2] + p[2]]);
        i ? rctx.lineTo(q[0], q[1]) : rctx.moveTo(q[0], q[1]);
      });
      rctx.strokeStyle = `rgba(34,197,94,${alpha})`;
      rctx.lineWidth = 1.15;
      rctx.stroke();
    };

    // 经线
    for (let k = 0; k < 10; k++) {
      const t0 = (k / 10) * Math.PI * 2;
      const pts = [];
      for (let i = 0; i <= 40; i++) {
        const ph = (i / 40) * Math.PI * 2;
        pts.push([Math.cos(ph) * Math.cos(t0) * rr, Math.cos(ph) * Math.sin(t0) * rr, Math.sin(ph) * rr]);
      }
      drawArc(pts, 0.38);
    }
    // 纬线
    for (let k = 1; k < 7; k++) {
      const lat = -Math.PI / 2 + (k / 7) * Math.PI;
      const pts = [];
      for (let i = 0; i <= 56; i++) {
        const t = (i / 56) * Math.PI * 2;
        pts.push([Math.cos(t) * Math.cos(lat) * rr, Math.sin(t) * Math.cos(lat) * rr, Math.sin(lat) * rr]);
      }
      drawArc(pts, 0.32);
    }

    // 赤道高亮
    {
      const pts = [];
      for (let i = 0; i <= 72; i++) {
        const t = (i / 72) * Math.PI * 2;
        pts.push([Math.cos(t) * rr, Math.sin(t) * rr, 0]);
      }
      drawArc(pts, 0.65);
    }

    // 9 测点（带脉冲光圈）
    const t = Date.now() / 1000;
    d.points.forEach((p, idx) => {
      const q = project(p);
      // 脉冲光圈
      const pulse = 8 + Math.sin(t * 2.5 + idx * 0.7) * 3;
      rctx.beginPath();
      rctx.arc(q[0], q[1], pulse, 0, Math.PI * 2);
      rctx.strokeStyle = `rgba(34,197,94,${0.15 + Math.sin(t * 2 + idx) * 0.08})`;
      rctx.lineWidth = 1.5;
      rctx.stroke();
      // 核心点
      rctx.beginPath();
      rctx.arc(q[0], q[1], 5, 0, Math.PI * 2);
      rctx.fillStyle = "#22C55E";
      rctx.shadowColor = "rgba(34,197,94,0.7)";
      rctx.shadowBlur = 10;
      rctx.fill();
      rctx.shadowBlur = 0;
      // 白心
      rctx.beginPath();
      rctx.arc(q[0], q[1], 1.8, 0, Math.PI * 2);
      rctx.fillStyle = "#F0FDF4";
      rctx.fill();
    });

    // 球心十字 + 标签
    const cpt = project(cr);
    rctx.strokeStyle = "rgba(226,232,240,0.55)";
    rctx.lineWidth = 1.2;
    rctx.beginPath();
    rctx.moveTo(cpt[0] - 8, cpt[1]); rctx.lineTo(cpt[0] + 8, cpt[1]);
    rctx.moveTo(cpt[0], cpt[1] - 8); rctx.lineTo(cpt[0], cpt[1] + 8);
    rctx.stroke();

    // 坐标轴指示器（右下角）
    const axLen = 28, axX = W - 55, axY = H - 45;
    const axes = [
      [[axLen, 0, 0], "#EF4444", "X"],
      [[0, axLen, 0], "#22C55E", "Y"],
      [[0, 0, axLen], "#38BDF8", "Z"],
    ];
    for (const [vec, color, label] of axes) {
      const end = project(vec.map((v) => v / 1000 * 2));
      const dx = end[0] - project([0, 0, 0])[0];
      const dy = end[1] - project([0, 0, 0])[1];
      rctx.beginPath();
      rctx.moveTo(axX, axY);
      rctx.lineTo(axX + dx * 0.4, axY + dy * 0.4);
      rctx.strokeStyle = color;
      rctx.lineWidth = 2;
      rctx.stroke();
      rctx.fillStyle = color;
      rctx.font = "bold 9px 'Fira Code', monospace";
      rctx.fillText(label, axX + dx * 0.4 + 3, axY + dy * 0.4 + 3);
    }

    // 底部信息
    rctx.fillStyle = "rgba(148,163,184,0.8)";
    rctx.font = "11px 'Fira Sans', sans-serif";
    rctx.fillText(`球心 (${d.center_mm.map((v) => (v / 10).toFixed(1)).join(", ")}) cm`, 14, H - 14);
    rctx.fillStyle = "rgba(34,197,94,0.5)";
    rctx.font = "10px 'Fira Code', monospace";
    rctx.textAlign = "right";
    rctx.fillText(`r = ${(d.radius_mm / 10).toFixed(1)} cm`, W - 14, H - 14);
    rctx.textAlign = "left";
  }

  // ======================== 趋势 ========================
  const trend = $("#trendCanvas");
  const tctx = trend.getContext("2d");

  function drawTrend(d) {
    const W = trend.width, H = trend.height;
    tctx.clearRect(0, 0, W, H);
    const hist = (d && d.history) || [];
    const padL = 50, padB = 26, padT = 16, padR = 16;

    // 网格（带渐隐）
    tctx.strokeStyle = "rgba(71,85,105,0.22)";
    tctx.lineWidth = 1;
    tctx.fillStyle = "rgba(148,163,184,0.5)";
    tctx.font = "10px 'Fira Code', monospace";
    tctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const y = padT + (H - padT - padB) * (i / 4);
      tctx.beginPath();
      tctx.moveTo(padL, y); tctx.lineTo(W - padR, y);
      tctx.stroke();
      tctx.fillText(String(500 - i * 125), padL - 8, y + 3);
    }
    tctx.textAlign = "left";

    if (hist.length < 2) {
      tctx.fillStyle = "rgba(148,163,184,0.45)";
      tctx.font = "13px 'Fira Sans', sans-serif";
      tctx.textAlign = "center";
      tctx.fillText("趋势数据积累中…", W / 2, H / 2);
      tctx.textAlign = "left";
      return;
    }
    const t1 = hist[hist.length - 1][0];
    const t0 = Math.max(hist[0][0], t1 - 240);
    const X = (t) => padL + (W - padL - padR) * ((t - t0) / (t1 - t0 || 1));
    const Y = (v) => padT + (H - padT - padB) * (1 - Math.min(Math.max(v / 500, 0), 1));

    // 渐变面积填充
    const grad = tctx.createLinearGradient(0, padT, 0, H - padB);
    grad.addColorStop(0, "rgba(34,197,94,0.32)");
    grad.addColorStop(0.5, "rgba(34,197,94,0.12)");
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

    // 发光线
    tctx.beginPath();
    hist.forEach(([t, v], i) => {
      const x = X(t), y = Y(v);
      i ? tctx.lineTo(x, y) : tctx.moveTo(x, y);
    });
    tctx.strokeStyle = "rgba(34,197,94,0.15)";
    tctx.lineWidth = 6;
    tctx.stroke();
    tctx.beginPath();
    hist.forEach(([t, v], i) => {
      const x = X(t), y = Y(v);
      i ? tctx.lineTo(x, y) : tctx.moveTo(x, y);
    });
    tctx.strokeStyle = "#22C55E";
    tctx.lineWidth = 2.5;
    tctx.lineCap = "round";
    tctx.lineJoin = "round";
    tctx.stroke();

    // 端点（带脉冲）
    const [te, ve] = hist[hist.length - 1];
    const xe = X(te), ye = Y(ve);
    const pulse = 8 + Math.sin(Date.now() / 300) * 2;
    tctx.beginPath();
    tctx.arc(xe, ye, pulse, 0, Math.PI * 2);
    tctx.strokeStyle = "rgba(34,197,94,0.25)";
    tctx.lineWidth = 1.5;
    tctx.stroke();
    tctx.beginPath();
    tctx.arc(xe, ye, 5, 0, Math.PI * 2);
    tctx.fillStyle = "#86EFAC";
    tctx.shadowColor = "rgba(34,197,94,0.9)";
    tctx.shadowBlur = 14;
    tctx.fill();
    tctx.shadowBlur = 0;

    // 当前值标注
    tctx.fillStyle = "rgba(34,197,94,0.9)";
    tctx.font = "bold 11px 'Fira Code', monospace";
    tctx.textAlign = "left";
    tctx.fillText(`${ve.toFixed(0)} mL`, xe + 10, ye - 8);

    // 时间轴标签
    tctx.fillStyle = "rgba(148,163,184,0.45)";
    tctx.font = "9px 'Fira Code', monospace";
    tctx.textAlign = "center";
    tctx.fillText("0m", padL, H - 8);
    tctx.fillText("-2m", padL + (W - padL - padR) / 2, H - 8);
    tctx.fillText("-4m", W - padR, H - 8);
    tctx.textAlign = "left";
  }

  // ======================== 波形 ========================
  function drawWaves(d) {
    const waves = (d && d.wave) || [];
    const tof = (d && d.tof) || [];
    state.waveCells.forEach((cell, i) => {
      const cv = cell.querySelector("canvas");
      const ctx = cv.getContext("2d");
      const W = cv.width, H = cv.height;
      ctx.clearRect(0, 0, W, H);

      // 背景
      ctx.fillStyle = "rgba(11, 17, 32, 0.4)";
      ctx.fillRect(0, 0, W, H);

      // 网格
      ctx.strokeStyle = "rgba(71,85,105,0.18)";
      ctx.lineWidth = 1;
      for (let g = 1; g < 5; g++) {
        const y = (H * g) / 5;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      for (let g = 1; g < 8; g++) {
        const x = (W * g) / 8;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      }

      const w = waves[i] || [];
      if (!w.length) return;
      const tofLabel = cell.querySelector(".wf-tof");
      if (tofLabel) tofLabel.textContent = `TOF ${tof[i] ?? "—"}`;

      // 波形面积填充
      const gradFill = ctx.createLinearGradient(0, 0, 0, H);
      gradFill.addColorStop(0, "rgba(56,189,248,0.15)");
      gradFill.addColorStop(1, "rgba(34,197,94,0.03)");
      ctx.beginPath();
      ctx.moveTo(0, H);
      w.forEach((v, k) => {
        const x = (k / 255) * W;
        const y = H - 5 - (v / 255) * (H - 12);
        ctx.lineTo(x, y);
      });
      ctx.lineTo(W, H);
      ctx.closePath();
      ctx.fillStyle = gradFill;
      ctx.fill();

      // 波形线
      const grad = ctx.createLinearGradient(0, 0, W, 0);
      grad.addColorStop(0, "rgba(56,189,248,0.85)");
      grad.addColorStop(0.5, "rgba(34,197,94,0.9)");
      grad.addColorStop(1, "rgba(34,197,94,0.85)");
      ctx.beginPath();
      w.forEach((v, k) => {
        const x = (k / 255) * W;
        const y = H - 5 - (v / 255) * (H - 12);
        k ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.8;
      ctx.lineJoin = "round";
      ctx.stroke();

      // TOF 光标
      const pos = ((tof[i] || 0) / 16 / 255) * W;
      ctx.strokeStyle = "rgba(245,158,11,0.7)";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(pos, 2); ctx.lineTo(pos, H - 2);
      ctx.stroke();
      ctx.setLineDash([]);
      // 光标顶端小三角
      ctx.fillStyle = "rgba(245,158,11,0.9)";
      ctx.beginPath();
      ctx.moveTo(pos - 3, 0); ctx.lineTo(pos + 3, 0); ctx.lineTo(pos, 5);
      ctx.fill();
    });
  }

  // ======================== 渲染主循环 ========================
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
    // 更新率：显示完整估计次数/秒（约 11 次），不是通道帧率
    const fpsVal = d.stats ? d.stats.fps : 0;
    const estRate = Math.round(fpsVal / 9 * 10) / 10;
    $("#fpsValue").textContent = d.stats ? `${estRate} 次/秒` : "—";
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

  // ======================== 数据轮询 ========================
  async function poll() {
    try {
      const res = await fetch("/api/state");
      state.data = await res.json();
      updateReadouts(state.data);
    } catch (e) { /* 保持上一帧 */ }
  }

  function loop() {
    state.sweep += 0.012;
    if (!state.drag) state.spin += 0.0035;
    state.animTime = Date.now();
    renderAll();
    requestAnimationFrame(loop);
  }

  setInterval(poll, 220);
  poll().then(() => { renderAll(); loop(); });

  // ======================== 连接控制 ========================
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

  // ======================== 页签 ========================
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
