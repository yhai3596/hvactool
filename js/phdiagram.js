/* =====================================================
 * phdiagram.js —— 压焓图绘制（Canvas，对数压力轴）
 * 饱和穹顶 + 等温线 + 实时循环 1-2-3-4 + 巡回光点
 * ===================================================== */

const PH = (() => {
  const cv = document.getElementById('phCanvas');
  const ctx = cv.getContext('2d');
  const DESIGN_W = 406, DESIGN_H = 330;   // 高度压缩，让性能/测点上移
  let W = DESIGN_W, H = DESIGN_H;
  const MG = { l: 48, r: 14, t: 14, b: 36 };

  let hMin = 130, hMax = 520;
  const pMin = 0.07, pMax = 7.0;
  let unitIP = false;                      // 压力 psi / 焓 Btu/lb
  // 主题调色板：读 CSS 变量并缓存；主题切换时置空重读（每帧零 getComputedStyle）
  let PAL = null;
  window.addEventListener('hvac-theme-change', () => { PAL = null; });
  function pal() {
    if (PAL) return PAL;
    const v = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    PAL = { grid: v('--ph-grid'), grid2: v('--ph-grid2'), tick: v('--ph-tick'), axis: v('--ph-axis'),
            iso: v('--ph-iso'), isot: v('--ph-isot'), cycle: v('--ph-cycle'), cyct: v('--ph-cyct'),
            ptfill: v('--ph-ptfill'), orbit: v('--ph-orbit'), outline: v('--ph-outline'),
            numT: v('--num-t'), numSh: v('--num-sh') };
    return PAL;
  }
  const PSI = 145.03774, BTULB = 0.4299226;
  const pLabel = p => unitIP ? Math.round(p * PSI) : p.toFixed(p < 1 ? 1 : 0);
  const hLabel = h => unitIP ? Math.round(h * BTULB) : h;
  const tLabel = t => unitIP ? (t * 1.8 + 32) : t;
  const dtLabel = d => unitIP ? (d * 1.8) : d;

  // hi-DPI 背板：按显示尺寸 × devicePixelRatio 分配位图，逻辑坐标不变（消除模糊）
  function prep() {
    const dpr = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2.5);
    const rect = cv.getBoundingClientRect();
    W = Math.round(rect.width) || DESIGN_W;
    H = Math.round(W * DESIGN_H / DESIGN_W);
    const bw = Math.round(W * dpr), bh = Math.round(H * dpr);
    if (cv.width !== bw || cv.height !== bh) {
      cv.width = bw; cv.height = bh;
      cv.style.height = H + 'px';
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function setRange(R) {
    hMin = hf(R, -42) - 15;
    hMax = hg(R, 30) + R.cpv * 110 + 20;
  }

  const X = h => MG.l + (h - hMin) / (hMax - hMin) * (W - MG.l - MG.r);
  const Y = p => H - MG.b - (Math.log10(p) - Math.log10(pMin)) / (Math.log10(pMax) - Math.log10(pMin)) * (H - MG.t - MG.b);

  let orbit = 0;   // 巡回光点位置 0..1

  // 静态层（网格/等温线/饱和穹顶）缓存：仅在 冷媒/单位/主题/尺寸 变化时重绘，
  // 平时每次刷新只画动态循环线与光点（省去大头绘制与 shadowBlur）
  let bgCv = null, bgR = null, bgUnit = null, bgTheme = '', bgW = 0, bgH = 0;
  function drawStatic(g, R, C) {
    // ---- 网格与坐标 ----
    g.font = '10px Consolas';
    g.lineWidth = 1;
    for (const p of [0.1, 0.2, 0.5, 1, 2, 5]) {
      g.strokeStyle = C.grid;
      g.beginPath(); g.moveTo(MG.l, Y(p)); g.lineTo(W - MG.r, Y(p)); g.stroke();
      g.fillStyle = C.tick; g.textAlign = 'right';
      g.fillText(pLabel(p), MG.l - 5, Y(p) + 3);
    }
    for (let h = Math.ceil(hMin / 50) * 50; h < hMax; h += 50) {
      g.strokeStyle = C.grid2;
      g.beginPath(); g.moveTo(X(h), MG.t); g.lineTo(X(h), H - MG.b); g.stroke();
      g.fillStyle = C.tick; g.textAlign = 'center';
      g.fillText(hLabel(h), X(h), H - MG.b + 13);
    }
    g.fillStyle = C.axis; g.textAlign = 'center';
    g.fillText((window.T ? window.T('ph_h') : 'h  比焓') + (unitIP ? '  Btu/lb' : '  kJ/kg'), (MG.l + W - MG.r) / 2, H - 6);
    g.save(); g.translate(12, (MG.t + H - MG.b) / 2); g.rotate(-Math.PI / 2);
    g.fillText((window.T ? window.T('ph_p') : 'P  绝对压力') + (unitIP ? '  psi (log)' : '  MPa (log)'), 0, 0); g.restore();

    // ---- 等温线 ----
    g.strokeStyle = C.iso;
    g.lineWidth = 1;
    g.setLineDash([3, 4]);
    for (const T of [-20, 0, 20, 40, 60]) {
      if (T >= R.TcritC - 4) continue;
      const Pt = psat(R, T);
      // 液区（近似竖直）
      g.beginPath(); g.moveTo(X(hf(R, T)), Y(Pt)); g.lineTo(X(hf(R, T) - 4), Y(Math.min(pMax, Pt * 4))); g.stroke();
      // 两相区（水平）
      g.beginPath(); g.moveTo(X(hf(R, T)), Y(Pt)); g.lineTo(X(hg(R, T)), Y(Pt)); g.stroke();
      // 过热区
      g.beginPath();
      let first = true;
      for (let p = Pt; p > pMin; p *= 0.88) {
        const h = hg(R, tsat(R, p)) + R.cpv * (T - tsat(R, p));
        if (h > hMax) break;
        first ? g.moveTo(X(h), Y(p)) : g.lineTo(X(h), Y(p));
        first = false;
      }
      g.stroke();
      g.fillStyle = C.isot; g.textAlign = 'left';
      g.fillText(Math.round(tLabel(T)) + (unitIP ? '°F' : '°C'), X(hg(R, T)) + 3, Y(Pt) - 3);
    }
    g.setLineDash([]);

    // ---- 饱和穹顶 ----
    g.beginPath();
    let first = true;
    for (let T = -45; T <= R.TcritC - 0.4; T += 1) {
      const x = X(hf(R, T)), y = Y(psat(R, T));
      first ? g.moveTo(x, y) : g.lineTo(x, y);
      first = false;
    }
    for (let T = R.TcritC - 0.4; T >= -45; T -= 1) {
      g.lineTo(X(hg(R, T)), Y(psat(R, T)));
    }
    g.strokeStyle = R.color;
    g.lineWidth = 2.2;
    g.shadowColor = R.color; g.shadowBlur = 3;
    g.stroke();
    g.shadowBlur = 0;
    // 临界点
    const Tcr = R.TcritC - 0.4;
    g.fillStyle = R.color;
    g.beginPath(); g.arc(X((hf(R, Tcr) + hg(R, Tcr)) / 2), Y(psat(R, Tcr)), 2.5, 0, 7); g.fill();
  }

  function draw(R, st, dt) {
    const C = pal();
    prep();
    setRange(R);
    const theme = document.documentElement.dataset.theme || 'dark';
    if (R !== bgR || unitIP !== bgUnit || theme !== bgTheme || cv.width !== bgW || cv.height !== bgH) {
      bgR = R; bgUnit = unitIP; bgTheme = theme; bgW = cv.width; bgH = cv.height;
      if (!bgCv) bgCv = document.createElement('canvas');
      bgCv.width = cv.width; bgCv.height = cv.height;
      const g = bgCv.getContext('2d');
      g.setTransform(cv.width / W, 0, 0, cv.height / H, 0, 0);
      drawStatic(g, R, C);
    }
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(bgCv, 0, 0, W, H);

    if (!st) return;

    // ---- 循环 1-2-3-4 ----
    const p1 = [X(st.h1), Y(st.Pe)];
    const p2 = [X(st.h2), Y(st.Pc)];
    const p3 = [X(st.h3), Y(st.Pc)];
    const p4 = [X(st.h4), Y(st.Pe)];

    ctx.beginPath();
    ctx.moveTo(...p1);
    // 压缩线略带曲率
    ctx.quadraticCurveTo(p1[0] + (p2[0] - p1[0]) * 0.7, p1[1] + (p2[1] - p1[1]) * 0.35, ...p2);
    ctx.lineTo(...p3);
    ctx.lineTo(...p4);
    ctx.lineTo(...p1);
    ctx.strokeStyle = C.cycle;
    ctx.lineWidth = 2;
    ctx.shadowColor = C.cycle; ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // 状态点
    const pts = [[p1, '1', window.T ? window.T('pt_suction') : '吸气'], [p2, '2', window.T ? window.T('pt_discharge') : '排气'], [p3, '3', window.T ? window.T('pt_condout') : '冷凝出'], [p4, '4', window.T ? window.T('pt_evapin') : '蒸发进']];
    ctx.font = 'bold 11px Consolas';
    for (const [p, n, lbl] of pts) {
      ctx.fillStyle = C.ptfill;
      ctx.beginPath(); ctx.arc(p[0], p[1], 3.6, 0, 7); ctx.fill();
      ctx.strokeStyle = C.cycle; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(p[0], p[1], 6, 0, 7); ctx.stroke();
      const dx = (n === '3' || n === '4') ? -36 : 9;
      const ty = p[1] + (n === '2' ? -9 : (n === '1' ? 15 : -9));
      ctx.textAlign = 'left';
      // 文字描边提升可读性
      ctx.lineWidth = 3; ctx.strokeStyle = C.outline;
      ctx.strokeText(n + ' ' + lbl, p[0] + dx, ty);
      ctx.fillStyle = C.cyct;
      ctx.fillText(n + ' ' + lbl, p[0] + dx, ty);
    }

    // ---- 巡回光点 ----
    orbit = (orbit + dt * clamp(st.mdot * 3, 0.06, 0.5)) % 1;
    const segs = [[p1, p2], [p2, p3], [p3, p4], [p4, p1]];
    const lens = segs.map(([a, b]) => Math.hypot(b[0] - a[0], b[1] - a[1]));
    const total = lens.reduce((a, b) => a + b, 0);
    let s = orbit * total, px = p1[0], py = p1[1];
    for (let i = 0; i < 4; i++) {
      if (s <= lens[i]) {
        const k = s / lens[i];
        px = lerp(segs[i][0][0], segs[i][1][0], k);
        py = lerp(segs[i][0][1], segs[i][1][1], k);
        break;
      }
      s -= lens[i];
    }
    ctx.fillStyle = C.orbit;
    ctx.shadowColor = C.cycle; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.arc(px, py, 3, 0, 7); ctx.fill();
    ctx.shadowBlur = 0;

    // ---- 角标数据 ----
    const tu = unitIP ? '°F' : '°C', du = unitIP ? '°F' : 'K';
    ctx.font = 'bold 11px Consolas'; ctx.textAlign = 'left';
    ctx.fillStyle = C.numT;
    ctx.fillText(`Te ${tLabel(st.Te).toFixed(1)}${tu}   Tc ${tLabel(st.Tc).toFixed(1)}${tu}`, MG.l + 6, MG.t + 13);
    ctx.fillStyle = C.numSh;
    ctx.fillText(`SH ${dtLabel(st.SH).toFixed(1)}${du}   SC ${dtLabel(st.SC).toFixed(1)}${du}`, MG.l + 6, MG.t + 27);
  }

  function setUnits(ip) { unitIP = ip; }

  return { draw, setUnits };
})();
