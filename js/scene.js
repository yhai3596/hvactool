/* =====================================================
 * scene.js —— SVG 场景动画引擎
 *  - 冷媒粒子沿管路网络流动（相态/温度/流速可视化）
 *  - 风机旋转、压缩机振动、四通阀换向、EXV 开度
 *  - 结霜/化霜（霜层、冰凌、水滴、蒸汽）、雪、太阳
 *  - 室内送风/回风气流
 * ===================================================== */

const Scene = (() => {
  const $ = id => document.getElementById(id);
  const SVGNS = 'http://www.w3.org/2000/svg';

  // ---- 温度 → 颜色（蓝=冷 → 青 → 黄 → 红=热，高饱和以增强区分度）----
  function tempColor(t) {
    const k = clamp((t + 25) / 135, 0, 1);          // -25 ~ 110°C
    const hue = 205 - 215 * k;                        // 205(蓝) → -10(红)
    const light = 60 - 8 * k;
    return `hsl(${(hue + 360) % 360}, 96%, ${light}%)`;
  }

  // ---- 管路采样 ----
  const pathPts = {};   // id -> [{x,y}...] 每 6px 一点
  function samplePath(id) {
    const el = $(id);
    const L = el.getTotalLength();
    const pts = [];
    const n = Math.max(2, Math.round(L / 6));
    for (let i = 0; i <= n; i++) {
      const p = el.getPointAtLength(L * i / n);
      pts.push({ x: p.x, y: p.y });
    }
    return pts;
  }

  // ---- 流路定义（顺流方向段序） ----
  const ROUTES = {
    cooling: [
      { id: 'pDis', rev: false, kind: 'dis' },
      { id: 'pV4C', rev: false, kind: 'dis' },
      { id: 'pCoilOut', rev: false, kind: 'cond' },
      { id: 'pLiqA', rev: false, kind: 'liq' },
      { id: 'pLiqB', rev: false, kind: 'flash' },
      { id: 'pCoilIn', rev: true, kind: 'evap' },
      { id: 'pGasLine', rev: true, kind: 'suc' },
      { id: 'pSuc', rev: false, kind: 'suc' },
    ],
    heating: [
      { id: 'pDis', rev: false, kind: 'dis' },
      { id: 'pGasLine', rev: false, kind: 'dis' },
      { id: 'pCoilIn', rev: false, kind: 'cond' },
      { id: 'pLiqB', rev: true, kind: 'liq' },
      { id: 'pLiqA', rev: true, kind: 'flash' },
      { id: 'pCoilOut', rev: true, kind: 'evap' },
      { id: 'pV4C', rev: true, kind: 'suc' },
      { id: 'pSuc', rev: false, kind: 'suc' },
    ],
  };
  // 各段流动阻力对应的视觉流速倍率
  const SPEED_MULT = { dis: 1.9, cond: 1.25, liq: 0.85, flash: 1.5, evap: 1.25, suc: 1.9 };

  let route = [];        // [{pts,kind,len,start}]
  let routeLen = 0;
  let particles = [];    // {s}
  const N_PART = 130;
  let partEls = [];

  function buildRoute(mode) {
    route = [];
    routeLen = 0;
    for (const seg of ROUTES[mode]) {
      let pts = pathPts[seg.id];
      if (seg.rev) pts = [...pts].reverse();
      const len = pts.length * 6;
      route.push({ pts, kind: seg.kind, len, start: routeLen });
      routeLen += len;
    }
    for (const p of particles) p.s = (p.s % 1 + 1) % 1;
  }

  // 位置 s(0..1) → {x,y,kind,f}
  function routeState(s) {
    let d = s * routeLen;
    for (const seg of route) {
      if (d <= seg.len || seg === route[route.length - 1]) {
        const f = clamp(d / seg.len, 0, 1);
        const fi = f * (seg.pts.length - 1);
        const i = Math.min(Math.floor(fi), seg.pts.length - 2);
        const k = fi - i;
        return {
          x: lerp(seg.pts[i].x, seg.pts[i + 1].x, k),
          y: lerp(seg.pts[i].y, seg.pts[i + 1].y, k),
          kind: seg.kind, f,
        };
      }
      d -= seg.len;
    }
  }

  // 段内相态与温度
  function phaseTemp(kind, f, st) {
    switch (kind) {
      case 'dis': return { ph: 'gas', t: st.Td };
      case 'cond':
        if (f < 0.12) return { ph: 'gas', t: lerp(st.Td, st.Tc, f / 0.12) };
        if (f < 0.86) return { ph: '2ph', t: st.Tc };
        return { ph: 'liq', t: lerp(st.Tc, st.Tc - st.SC, (f - 0.86) / 0.14) };
      case 'liq': return { ph: 'liq', t: st.Tc - st.SC };
      case 'flash': return { ph: '2ph', t: st.Te };
      case 'evap':
        if (f < 0.82) return { ph: '2ph', t: st.Te };
        return { ph: 'gas', t: lerp(st.Te, st.Te + st.SH * 0.85, (f - 0.82) / 0.18) };
      default: return { ph: 'gas', t: st.Tsuc };
    }
  }

  // ---- 效果粒子池 ----
  let snowFlakes = [], drips = [], steams = [], inStreaks = [], outStreaks = [], oilDots = [];
  let fanAngle = 0, swirlAngle = 0, hatchOff = 0, v4pos = 0, time = 0;
  let pins = [], unitIP = false;

  function mk(tag, parent, attrs) {
    const el = document.createElementNS(SVGNS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    parent.appendChild(el);
    return el;
  }

  function init() {
    ['pDis', 'pV4C', 'pCoilOut', 'pLiqA', 'pLiqB', 'pCoilIn', 'pGasLine', 'pSuc']
      .forEach(id => pathPts[id] = samplePath(id));

    const pg = $('particles');
    for (let i = 0; i < N_PART; i++) {
      particles.push({ s: i / N_PART });
      partEls.push(mk('circle', pg, { r: 3 }));
    }
    buildRoute('cooling');

    // 贯流风扇斜纹
    const ch = $('cfHatch');
    for (let x = 680; x < 950; x += 16) {
      mk('line', ch, { x1: x, y1: 276, x2: x + 10, y2: 256 });
    }

    // 图钉：点击管路放置（点图钉本身移除）
    $('scene').addEventListener('click', e => {
      if (e.target.closest('.pin')) return;
      const p = svgPoint(e);
      const n = nearestS(p.x, p.y);
      if (n.dist < 20) addPin(n.s);
    });
  }

  // ---- 四通阀视觉 ----
  function updateV4(targetMode, dt) {
    const tgt = targetMode === 'cooling' ? 0 : 1;
    v4pos += clamp(tgt - v4pos, -dt * 2.2, dt * 2.2);
    $('v4Slider').setAttribute('x', lerp(336, 372, v4pos));
    if (v4pos < 0.5) {
      $('v4Hot').setAttribute('d', 'M365,318 L392,300');
      $('v4Cold').setAttribute('d', 'M338,300 L342,318');
    } else {
      $('v4Hot').setAttribute('d', 'M365,318 L338,300');
      $('v4Cold').setAttribute('d', 'M392,300 L342,318');
    }
    const mid = 1 - Math.abs(v4pos - 0.5) * 2;   // 换向瞬间闪烁
    $('v4Hot').setAttribute('opacity', 0.85 - 0.6 * mid);
    $('v4Cold').setAttribute('opacity', 0.85 - 0.6 * mid);
  }

  let curRouteMode = 'cooling';

  /**
   * 每帧更新
   * @param dt   秒
   * @param st   平滑后的显示状态（solveCycle 输出结构）
   * @param inp  当前生效输入（含时序覆盖）
   * @param fl   {frost, defrost, dripRate, steam, oil, internalMode, process}
   */
  function update(dt, st, inp, fl) {
    time += dt;
    if (fl.internalMode !== curRouteMode) {
      curRouteMode = fl.internalMode;
      buildRoute(curRouteMode);
    }
    updateV4(curRouteMode, dt);

    // ---- 冷媒粒子（放慢约 60%，相态用形状+大小强化区分）----
    const baseV = clamp(10 + 700 * st.mdot, 5, 62);   // px/s
    for (let i = 0; i < N_PART; i++) {
      const p = particles[i];
      const rs = routeState(p.s);
      const mult = SPEED_MULT[rs.kind] || 1.2;
      p.s = (p.s + baseV * mult * dt / routeLen) % 1;
      const pt = phaseTemp(rs.kind, rs.f, st);
      const el = partEls[i];
      const c = tempColor(pt.t);
      el.setAttribute('cx', rs.x.toFixed(1));
      el.setAttribute('cy', rs.y.toFixed(1));
      if (pt.ph === 'gas') {                 // 气态：空心环（大而通透）
        el.setAttribute('r', 3.8);
        el.setAttribute('fill', 'none');
        el.setAttribute('stroke', c);
        el.setAttribute('stroke-width', 2.1);
        el.setAttribute('opacity', 0.95);
      } else if (pt.ph === 'liq') {          // 液态：实心大点
        el.setAttribute('r', 4.3);
        el.setAttribute('fill', c);
        el.setAttribute('stroke', 'none');
        el.setAttribute('opacity', 1);
      } else {                               // 两相：实心/空心交替的小点（明显区别于纯气纯液）
        el.setAttribute('opacity', 0.95);
        if (i % 2) { el.setAttribute('r', 3.4); el.setAttribute('fill', c); el.setAttribute('stroke', 'none'); }
        else { el.setAttribute('r', 3); el.setAttribute('fill', 'none'); el.setAttribute('stroke', c); el.setAttribute('stroke-width', 1.8); }
      }
    }

    // ---- 管路辉光配色 ----
    const kindTemp = {
      dis: st.Td, cond: st.Tc, liq: st.Tc - st.SC,
      flash: st.Te, evap: st.Te, suc: st.Tsuc,
    };
    for (const seg of ROUTES[curRouteMode]) {
      const el = $('f' + seg.id.slice(1));
      el.setAttribute('stroke', tempColor(kindTemp[seg.kind]));
    }

    // ---- 压缩机 ----
    const hz = inp.comp;
    swirlAngle = (swirlAngle + hz * 5.5 * dt) % 360;
    $('compSwirl').setAttribute('transform', `rotate(${swirlAngle.toFixed(1)} 360 478)`);
    const jit = 0.8 * Math.sin(time * hz * 0.55) * clamp(hz / 60, 0, 1.6);
    $('compBody').setAttribute('transform', `translate(${jit.toFixed(2)},0)`);
    $('compGlow').setAttribute('opacity', (0.08 + 0.3 * hz / 120).toFixed(2));
    $('compHzTxt').textContent = hz.toFixed(0) + ' Hz';

    // ---- 风机 ----
    fanAngle = (fanAngle + inp.fanOut * 6.2 * dt) % 360;
    $('outFanRot').setAttribute('transform', `rotate(${fanAngle.toFixed(1)} 150 385)`);
    $('outFanRpm').textContent = Math.round(inp.fanOut * 9.5) + ' rpm';
    hatchOff = (hatchOff + inp.fanIn * 0.9 * dt) % 16;
    $('cfHatch').setAttribute('transform', `translate(${hatchOff.toFixed(1)},0)`);

    // ---- EXV ----
    const circ = 2 * Math.PI * 15;
    $('exvArc').setAttribute('stroke-dasharray', `${(inp.exv / 100 * circ).toFixed(1)} ${circ.toFixed(1)}`);

    // ---- 结霜 / 化霜 ----
    $('frost').setAttribute('opacity', (fl.frost * 0.8).toFixed(2));
    $('icicles').setAttribute('opacity', clamp((fl.frost - 0.45) * 1.4, 0, 0.9).toFixed(2));
    updateDrips(dt, fl.dripRate || 0);
    updateSteam(dt, fl.steam ? 1 : 0);

    // ---- 环境 ----
    $('sun').setAttribute('opacity', clamp((inp.tOut - 24) / 10, 0, 0.9).toFixed(2));
    updateSnow(dt, inp.tOut);
    updateAir(dt, st, inp, fl);
    updateOil(dt, fl.oil, st);

    // ---- 场景水印 ----
    const wm = { cooling: 'COOLING · 制冷运行', heating: 'HEATING · 制热运行', defrost: 'DEFROST · 化霜中', oilreturn: 'OIL RETURN · 回油运转' };
    $('sceneMode').textContent = wm[fl.process] || '';

    updatePins(st);
  }

  // ---- 水滴 ----
  function updateDrips(dt, rate) {
    if (rate > 0 && Math.random() < rate * dt * 14) {
      drips.push({ x: 396 + Math.random() * 42, y: 536, vy: 30 + Math.random() * 40, el: mk('circle', $('drips'), { r: 2, fill: '#9bd7f7', opacity: 0.9 }) });
    }
    for (let i = drips.length - 1; i >= 0; i--) {
      const d = drips[i];
      d.vy += 220 * dt; d.y += d.vy * dt;
      if (d.y > 556) { d.el.remove(); drips.splice(i, 1); continue; }
      d.el.setAttribute('cx', d.x); d.el.setAttribute('cy', d.y);
    }
  }

  // ---- 化霜蒸汽 ----
  function updateSteam(dt, on) {
    if (on && Math.random() < dt * 9) {
      steams.push({ x: 400 + Math.random() * 40, y: 320 + Math.random() * 200, r: 3, o: 0.5, el: mk('circle', $('steam'), { fill: '#cfeeff' }) });
    }
    for (let i = steams.length - 1; i >= 0; i--) {
      const s = steams[i];
      s.r += 9 * dt; s.y -= 26 * dt; s.o -= 0.28 * dt;
      if (s.o <= 0) { s.el.remove(); steams.splice(i, 1); continue; }
      s.el.setAttribute('cx', s.x); s.el.setAttribute('cy', s.y);
      s.el.setAttribute('r', s.r.toFixed(1)); s.el.setAttribute('opacity', s.o.toFixed(2));
    }
  }

  // ---- 雪 ----
  function updateSnow(dt, tOut) {
    const want = tOut < 3 ? Math.round(clamp((3 - tOut) * 5, 6, 45)) : 0;
    while (snowFlakes.length < want) {
      snowFlakes.push({ x: Math.random() * 630, y: Math.random() * 540, v: 14 + Math.random() * 22, ph: Math.random() * 6.28, el: mk('circle', $('snow'), { r: 1.2 + Math.random() * 1.4, fill: '#dbeafe', opacity: 0.7 }) });
    }
    while (snowFlakes.length > want) snowFlakes.pop().el.remove();
    for (const f of snowFlakes) {
      f.y += f.v * dt; f.ph += dt;
      if (f.y > 542) { f.y = -4; f.x = Math.random() * 630; }
      f.el.setAttribute('cx', (f.x + Math.sin(f.ph) * 6).toFixed(1));
      f.el.setAttribute('cy', f.y.toFixed(1));
    }
  }

  // ---- 气流 ----
  function updateAir(dt, st, inp, fl) {
    // 室内送风
    const fi = inp.fanIn / 100;
    if (fi > 0.03 && Math.random() < dt * fi * 26) {
      inStreaks.push({ x: 700 + Math.random() * 215, y: 284, vx: (35 + Math.random() * 42) * fi, vy: (45 + Math.random() * 55) * fi, life: 1.4, el: mk('line', $('inAir'), { 'stroke-width': 2, 'stroke-linecap': 'round' }) });
    }
    for (let i = inStreaks.length - 1; i >= 0; i--) {
      const a = inStreaks[i];
      a.life -= dt; a.x += a.vx * dt; a.y += a.vy * dt;
      if (a.life <= 0 || a.y > 552) { a.el.remove(); inStreaks.splice(i, 1); continue; }
      a.el.setAttribute('x1', a.x); a.el.setAttribute('y1', a.y);
      a.el.setAttribute('x2', a.x - a.vx * 0.12); a.el.setAttribute('y2', a.y - a.vy * 0.12);
      a.el.setAttribute('stroke', tempColor(st.supplyT));
      a.el.setAttribute('opacity', (clamp(a.life, 0, 1) * 0.55).toFixed(2));
    }
    $('inReturn').setAttribute('opacity', (0.15 + 0.5 * fi).toFixed(2));
    $('louver').setAttribute('opacity', fi > 0.03 ? 1 : 0.35);

    // 外机出风（向左）
    const fo = inp.fanOut / 100;
    if (fo > 0.03 && Math.random() < dt * fo * 20) {
      outStreaks.push({ x: 68, y: 322 + Math.random() * 128, v: (60 + Math.random() * 80) * fo, life: 1.1, el: mk('line', $('outAir'), { 'stroke-width': 2, 'stroke-linecap': 'round' }) });
    }
    for (let i = outStreaks.length - 1; i >= 0; i--) {
      const a = outStreaks[i];
      a.life -= dt; a.x -= a.v * dt;
      if (a.life <= 0 || a.x < 4) { a.el.remove(); outStreaks.splice(i, 1); continue; }
      a.el.setAttribute('x1', a.x); a.el.setAttribute('y1', a.y);
      a.el.setAttribute('x2', a.x + 14); a.el.setAttribute('y2', a.y);
      a.el.setAttribute('stroke', tempColor(st.outAirT));
      a.el.setAttribute('opacity', (clamp(a.life, 0, 1) * 0.5).toFixed(2));
    }
  }

  // ---- 回油油滴 ----
  function updateOil(dt, on, st) {
    if (on && oilDots.length < 14) {
      oilDots.push({ s: Math.random(), el: mk('circle', $('oilDots'), { r: 2, fill: '#f59e0b', opacity: 0.9 }) });
    }
    const baseV = clamp(10 + 700 * st.mdot, 5, 62);
    for (let i = oilDots.length - 1; i >= 0; i--) {
      const o = oilDots[i];
      const rs = routeState(o.s);
      o.s = (o.s + baseV * 1.3 * dt / routeLen) % 1;
      if (!on && Math.random() < dt * 1.5) { o.el.remove(); oilDots.splice(i, 1); continue; }
      o.el.setAttribute('cx', rs.x.toFixed(1));
      o.el.setAttribute('cy', (rs.y + 2.5).toFixed(1));   // 贴管壁流动
    }
  }

  // ================= 运行图图钉 =================
  const PH_NAME = { gas: '气态', liq: '液态', '2ph': '两相' };
  // 压力口径：排气段=排气压力 Pd，冷凝/液管=冷凝压力 Pc，节流后/蒸发=蒸发压力 Pe，回气=回气压力 Ps
  function pressBy(kind, st) {
    return ({ dis: st.Pd, cond: st.Pc, liq: st.Pc, flash: st.Pe, evap: st.Pe, suc: st.Ps })[kind] || st.Pe;
  }
  function fmtPinT(t) { return unitIP ? (t * 1.8 + 32).toFixed(1) + '°F' : t.toFixed(1) + '°C'; }
  function fmtPinP(p) { return unitIP ? Math.round(p * 145.0377) + ' psi' : p.toFixed(2) + ' MPa'; }

  function svgPoint(evt) {
    const svg = $('scene');
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }
  // 鼠标点 → 最近流路位置 s(0..1) 及距离
  function nearestS(x, y) {
    let bd = 1e9, bs = 0;
    for (const seg of route) {
      const n = seg.pts.length;
      for (let i = 0; i < n; i++) {
        const dx = seg.pts[i].x - x, dy = seg.pts[i].y - y, d = dx * dx + dy * dy;
        if (d < bd) { bd = d; bs = (seg.start + (n > 1 ? i / (n - 1) : 0) * seg.len) / routeLen; }
      }
    }
    return { s: bs, dist: Math.sqrt(bd) };
  }
  function addPin(s) {
    const rs0 = routeState(s);
    let ox = 16, oy = -60;
    if (rs0) { if (rs0.x > 1010) ox = -100; if (rs0.y < 78) oy = 16; }
    const g = mk('g', $('pins'), { class: 'pin' });
    const pin = {
      s, ox, oy, g,
      lead: mk('line', g, { class: 'pin-lead' }),                             // 底层：引线
      mark: mk('text', g, { class: 'pin-mark' }),                            // 图钉 📌，针尖指锚点
      box: mk('rect', g, { class: 'pin-box', width: 82, height: 50, rx: 5 }),// 参数框（可拖）
      t1: mk('text', g, { class: 'pin-ph' }),
      t2: mk('text', g, { class: 'pin-t' }),
      t3: mk('text', g, { class: 'pin-p' }),
    };
    pin.mark.textContent = '📌';
    // 点图钉 → 删除
    pin.mark.addEventListener('click', ev => { ev.stopPropagation(); removePin(pin); });
    // 拖参数框（框体与文字）→ 移动
    for (const el of [pin.box, pin.t1, pin.t2, pin.t3]) el.addEventListener('mousedown', ev => startDrag(ev, pin));
    pins.push(pin);
  }
  function startDrag(ev, pin) {
    ev.stopPropagation(); ev.preventDefault();
    const start = svgPoint(ev), sox = pin.ox, soy = pin.oy;
    function move(e) { const p = svgPoint(e); pin.ox = sox + (p.x - start.x); pin.oy = soy + (p.y - start.y); }
    function up() { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); }
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  }
  function removePin(pin) {
    pin.g.remove();
    const i = pins.indexOf(pin); if (i >= 0) pins.splice(i, 1);
  }
  function clearPins() { while (pins.length) removePin(pins[0]); }
  function updatePins(st) {
    for (const pin of pins) {
      const rs = routeState(pin.s);
      if (!rs) continue;
      const pt = phaseTemp(rs.kind, rs.f, st);
      const P = pressBy(rs.kind, st);
      const ax = rs.x, ay = rs.y;
      const bx = ax + pin.ox, by = ay + pin.oy;
      // 图钉 📌：针尖(字形左下)对准锚点；emoji 自带斜插外观，无需再旋转
      pin.mark.setAttribute('x', (ax - 2).toFixed(1));
      pin.mark.setAttribute('y', (ay + 1).toFixed(1));
      // 参数框（可拖）+ 引线
      pin.box.setAttribute('x', bx.toFixed(1)); pin.box.setAttribute('y', by.toFixed(1));
      pin.lead.setAttribute('x1', ax.toFixed(1)); pin.lead.setAttribute('y1', (ay - 4).toFixed(1));
      pin.lead.setAttribute('x2', (bx + 41).toFixed(1)); pin.lead.setAttribute('y2', (by + 25).toFixed(1));
      pin.t1.textContent = PH_NAME[pt.ph] || '';
      pin.t2.textContent = fmtPinT(pt.t);
      pin.t3.textContent = fmtPinP(P);
      pin.t1.setAttribute('x', (bx + 7).toFixed(1)); pin.t1.setAttribute('y', (by + 16).toFixed(1));
      pin.t2.setAttribute('x', (bx + 7).toFixed(1)); pin.t2.setAttribute('y', (by + 31).toFixed(1));
      pin.t3.setAttribute('x', (bx + 7).toFixed(1)); pin.t3.setAttribute('y', (by + 45).toFixed(1));
    }
  }
  function setUnits(ip) { unitIP = ip; }

  return { init, update, tempColor, setUnits, clearPins };
})();
