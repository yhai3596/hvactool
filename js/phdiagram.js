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

  function draw(R, st, dt) {
    prep();
    setRange(R);
    ctx.clearRect(0, 0, W, H);

    // ---- 网格与坐标 ----
    ctx.font = '10px Consolas';
    ctx.lineWidth = 1;
    for (const p of [0.1, 0.2, 0.5, 1, 2, 5]) {
      ctx.strokeStyle = 'rgba(120,180,220,0.16)';
      ctx.beginPath(); ctx.moveTo(MG.l, Y(p)); ctx.lineTo(W - MG.r, Y(p)); ctx.stroke();
      ctx.fillStyle = '#9fc0dc'; ctx.textAlign = 'right';
      ctx.fillText(pLabel(p), MG.l - 5, Y(p) + 3);
    }
    for (let h = Math.ceil(hMin / 50) * 50; h < hMax; h += 50) {
      ctx.strokeStyle = 'rgba(120,180,220,0.11)';
      ctx.beginPath(); ctx.moveTo(X(h), MG.t); ctx.lineTo(X(h), H - MG.b); ctx.stroke();
      ctx.fillStyle = '#9fc0dc'; ctx.textAlign = 'center';
      ctx.fillText(hLabel(h), X(h), H - MG.b + 13);
    }
    ctx.fillStyle = '#b8d4ec'; ctx.textAlign = 'center';
    ctx.fillText((window.T ? window.T('ph_h') : 'h  比焓') + (unitIP ? '  Btu/lb' : '  kJ/kg'), (MG.l + W - MG.r) / 2, H - 6);
    ctx.save(); ctx.translate(12, (MG.t + H - MG.b) / 2); ctx.rotate(-Math.PI / 2);
    ctx.fillText((window.T ? window.T('ph_p') : 'P  绝对压力') + (unitIP ? '  psi (log)' : '  MPa (log)'), 0, 0); ctx.restore();

    // ---- 等温线 ----
    ctx.strokeStyle = 'rgba(150,180,215,0.40)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    for (const T of [-20, 0, 20, 40, 60]) {
      if (T >= R.TcritC - 4) continue;
      const Pt = psat(R, T);
      // 液区（近似竖直）
      ctx.beginPath(); ctx.moveTo(X(hf(R, T)), Y(Pt)); ctx.lineTo(X(hf(R, T) - 4), Y(Math.min(pMax, Pt * 4))); ctx.stroke();
      // 两相区（水平）
      ctx.beginPath(); ctx.moveTo(X(hf(R, T)), Y(Pt)); ctx.lineTo(X(hg(R, T)), Y(Pt)); ctx.stroke();
      // 过热区
      ctx.beginPath();
      let first = true;
      for (let p = Pt; p > pMin; p *= 0.88) {
        const h = hg(R, tsat(R, p)) + R.cpv * (T - tsat(R, p));
        if (h > hMax) break;
        first ? ctx.moveTo(X(h), Y(p)) : ctx.lineTo(X(h), Y(p));
        first = false;
      }
      ctx.stroke();
      ctx.fillStyle = 'rgba(170,196,224,0.85)'; ctx.textAlign = 'left';
      ctx.fillText(Math.round(tLabel(T)) + (unitIP ? '°F' : '°C'), X(hg(R, T)) + 3, Y(Pt) - 3);
    }
    ctx.setLineDash([]);

    // ---- 饱和穹顶 ----
    ctx.beginPath();
    let first = true;
    for (let T = -45; T <= R.TcritC - 0.4; T += 1) {
      const x = X(hf(R, T)), y = Y(psat(R, T));
      first ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      first = false;
    }
    for (let T = R.TcritC - 0.4; T >= -45; T -= 1) {
      ctx.lineTo(X(hg(R, T)), Y(psat(R, T)));
    }
    ctx.strokeStyle = R.color;
    ctx.lineWidth = 2.2;
    ctx.shadowColor = R.color; ctx.shadowBlur = 3;
    ctx.stroke();
    ctx.shadowBlur = 0;
    // 临界点
    const Tcr = R.TcritC - 0.4;
    ctx.fillStyle = R.color;
    ctx.beginPath(); ctx.arc(X((hf(R, Tcr) + hg(R, Tcr)) / 2), Y(psat(R, Tcr)), 2.5, 0, 7); ctx.fill();

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
    ctx.strokeStyle = '#fbbf24';
    ctx.lineWidth = 2;
    ctx.shadowColor = '#fbbf24'; ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // 状态点
    const pts = [[p1, '1', window.T ? window.T('pt_suction') : '吸气'], [p2, '2', window.T ? window.T('pt_discharge') : '排气'], [p3, '3', window.T ? window.T('pt_condout') : '冷凝出'], [p4, '4', window.T ? window.T('pt_evapin') : '蒸发进']];
    ctx.font = 'bold 11px Consolas';
    for (const [p, n, lbl] of pts) {
      ctx.fillStyle = '#fff7e0';
      ctx.beginPath(); ctx.arc(p[0], p[1], 3.6, 0, 7); ctx.fill();
      ctx.strokeStyle = '#fbbf24'; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(p[0], p[1], 6, 0, 7); ctx.stroke();
      const dx = (n === '3' || n === '4') ? -36 : 9;
      const ty = p[1] + (n === '2' ? -9 : (n === '1' ? 15 : -9));
      ctx.textAlign = 'left';
      // 文字描边提升可读性
      ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(5,10,20,0.85)';
      ctx.strokeText(n + ' ' + lbl, p[0] + dx, ty);
      ctx.fillStyle = '#fcd34d';
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
    ctx.fillStyle = '#fff';
    ctx.shadowColor = '#fbbf24'; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.arc(px, py, 3, 0, 7); ctx.fill();
    ctx.shadowBlur = 0;

    // ---- 角标数据 ----
    const tu = unitIP ? '°F' : '°C', du = unitIP ? '°F' : 'K';
    ctx.font = 'bold 11px Consolas'; ctx.textAlign = 'left';
    ctx.fillStyle = '#7dd3fc';
    ctx.fillText(`Te ${tLabel(st.Te).toFixed(1)}${tu}   Tc ${tLabel(st.Tc).toFixed(1)}${tu}`, MG.l + 6, MG.t + 13);
    ctx.fillStyle = '#6ee7b7';
    ctx.fillText(`SH ${dtLabel(st.SH).toFixed(1)}${du}   SC ${dtLabel(st.SC).toFixed(1)}${du}`, MG.l + 6, MG.t + 27);
  }

  function setUnits(ip) { unitIP = ip; }

  return { draw, setUnits };
})();
