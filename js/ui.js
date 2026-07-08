/* =====================================================
 * ui.js —— 控制面板、测点仪表、场景标签、诊断提示
 * ===================================================== */

const UI = (() => {
  const $ = id => document.getElementById(id);

  const DEFAULTS = {
    cooling: { comp: 60, fanIn: 70, fanOut: 70, exv: 55, charge: 100, hxIn: 100, hxOut: 100, tIn: 27, tOut: 35 },
    heating: { comp: 70, fanIn: 70, fanOut: 80, exv: 50, charge: 100, hxIn: 100, hxOut: 100, tIn: 20, tOut: 2 },
  };

  const SLIDERS = [
    { k: 'comp', label: '压缩机转速', min: 20, max: 120, step: 1, unit: 'Hz' },
    { k: 'fanIn', label: '内风机', min: 0, max: 100, step: 1, unit: '%' },
    { k: 'fanOut', label: '外风机', min: 0, max: 100, step: 1, unit: '%' },
    { k: 'exv', label: 'EXV 开度', min: 5, max: 100, step: 1, unit: '%', extra: v => Math.round(v * 4.8) + 'P' },
    { k: 'charge', label: '冷媒量', min: 40, max: 130, step: 1, unit: '%' },
    { k: 'hxIn', label: '内换热器', min: 50, max: 150, step: 1, unit: '%' },
    { k: 'hxOut', label: '外换热器', min: 50, max: 150, step: 1, unit: '%' },
    { k: 'tIn', label: '室内温度', min: 16, max: 32, step: 0.5, unit: '°C', kind: 'temp' },
    { k: 'tOut', label: '室外温度', min: -25, max: 45, step: 0.5, unit: '°C', kind: 'temp' },
  ];

  // ---------- 单位制（公制 SI / 美制 IP）----------
  // 内部计算一律 SI；仅显示时换算。温度 °C→°F，压力 MPa→psi，温差 K→Δ°F，能力 kW→kBtu/h，流量 g/s→lb/h
  const UNIT = {
    temp:  { si: ['°C', v => v],   ip: ['°F', v => v * 1.8 + 32] },
    press: { si: ['MPa', v => v],  ip: ['psi', v => v * 145.03774] },
    dt:    { si: ['K', v => v],    ip: ['Δ°F', v => v * 1.8] },
    cap:   { si: ['kW', v => v],   ip: ['kBtu/h', v => v * 3.412142] },
    flow:  { si: ['g/s', v => v],  ip: ['lb/h', v => v * 7.936641] },
    x:     { si: ['%', v => v],    ip: ['%', v => v] },
    none:  { si: ['', v => v],     ip: ['', v => v] },
  };
  let unitSys = localStorage.getItem('hvac-sim-units') || 'si';
  const uconv = (kind, v) => UNIT[kind || 'none'][unitSys][1](v);
  const ulabel = kind => UNIT[kind || 'none'][unitSys][0];
  const isIP = () => unitSys === 'ip';

  // 节流后（=蒸发器进口）干度
  function throttleQuality(s) {
    const R = REFRIGERANTS[app.inputs.ref];
    const a = hf(R, s.Te), b = hg(R, s.Te);
    return b > a ? clamp((s.h4 - a) / (b - a), 0, 1) : 0;
  }

  const SENSORS = [
    { id: 'pd', cls: 'p', label: '排气压力', kind: 'press', dec: 2, get: s => s.Pd },
    { id: 'ps', cls: 'p', label: '回气压力', kind: 'press', dec: 2, get: s => s.Ps },
    { id: 'dsh', cls: 'sh', label: '排气过热度', kind: 'dt', dec: 1, get: s => s.dshDis },
    { id: 'ssh', cls: 'sh', label: '回气过热度', kind: 'dt', dec: 1, get: s => s.shSuc },
    { id: 'sc', cls: 'sh', label: '过冷度', kind: 'dt', dec: 1, get: s => s.SC },
    { id: 'td', cls: 't', label: '排气温度', kind: 'temp', dec: 1, get: s => s.Td },
    { id: 'ts', cls: 't', label: '回气温度', kind: 'temp', dec: 1, get: s => s.Tsuc },
    { id: 'cm', cls: 't', label: '冷凝器中部', kind: 'temp', dec: 1, get: s => s.condMid },
    { id: 'co', cls: 't', label: '冷凝器出口', kind: 'temp', dec: 1, get: s => s.condOut },
    { id: 'em', cls: 't', label: '蒸发器中部', kind: 'temp', dec: 1, get: s => s.evapMid },
    { id: 'eo', cls: 't', label: '蒸发器出口', kind: 'temp', dec: 1, get: s => s.evapOut },
    { id: 'sa', cls: 'air', label: '内侧出风', kind: 'temp', dec: 1, get: s => s.supplyT },
    { id: 'ra', cls: 'air', label: '内侧回风', kind: 'temp', dec: 1, get: s => s.returnT },
    { id: 'oa', cls: 'air', label: '外侧环境', kind: 'temp', dec: 1, get: s => s.ambT },
    { id: 'of', cls: 'air', label: '外机出风', kind: 'temp', dec: 1, get: s => s.outAirT },
    // ---- 节流与蒸发器状态 ----
    { section: '节流部件 · 蒸发器 进出口状态' },
    { id: 'thit', cls: 't', label: '节流前温度（过冷液）', kind: 'temp', dec: 1, get: s => s.condOut },
    { id: 'thip', cls: 'p', label: '节流前压力', kind: 'press', dec: 2, get: s => s.Pc },
    { id: 'thox', cls: 'sh', label: '节流后干度', kind: 'x', dec: 0, get: s => throttleQuality(s) * 100 },
    { id: 'thot', cls: 't', label: '节流后温度（两相）', kind: 'temp', dec: 1, get: s => s.Te },
    { id: 'thop', cls: 'p', label: '节流后压力', kind: 'press', dec: 2, get: s => s.Pe },
    { id: 'evit', cls: 't', label: '蒸发器进口温度', kind: 'temp', dec: 1, get: s => s.Te },
    { id: 'evip', cls: 'p', label: '蒸发器进口压力', kind: 'press', dec: 2, get: s => s.Pe },
    { id: 'evot', cls: 't', label: '蒸发器出口温度', kind: 'temp', dec: 1, get: s => s.evapOut },
    { id: 'evop', cls: 'p', label: '蒸发器出口压力', kind: 'press', dec: 2, get: s => s.Ps },
  ];

  const fmtDec = cfg => (cfg.kind === 'press' && isIP()) ? 1 : cfg.dec;

  const PROC_DESC = {
    cooling: '压缩机排出高温高压气体 → 室外冷凝器放热冷凝 → EXV 节流降压 → 室内蒸发器吸热蒸发（吹冷风）→ 低压气体经气液分离器回压缩机。',
    heating: '四通阀换向：高温排气进入室内冷凝器放热（吹热风）→ EXV 节流 → 室外蒸发器从环境吸热 → 回气返回压缩机。低温高湿环境外盘会逐渐结霜。',
    defrost: '反向循环化霜：暂停制热，四通阀切至制冷方向，用高温排气融化室外盘管霜层，期间内外风机停转。',
    oilreturn: '回油运转：压缩机升至高频、EXV 开大，用高流速冷媒把滞留在管路与换热器中的润滑油带回压缩机，保障润滑。',
  };

  let app = null;
  const sliderEls = {};
  const sensorEls = {};
  const sensorHist = {};
  let lastHints = '';

  // ---------- 初始化 ----------
  function init(a) {
    app = a;
    buildSliders();
    buildSensors();

    document.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => selectProcess(btn.dataset.mode));
    });
    document.querySelectorAll('.ref-btn[data-ref]').forEach(btn => {
      btn.addEventListener('click', () => {
        app.inputs.ref = btn.dataset.ref;
        document.querySelectorAll('.ref-btn[data-ref]').forEach(b => b.classList.toggle('active', b === btn));
        $('phRef').textContent = btn.dataset.ref;
      });
    });
    $('resetBtn').addEventListener('click', () => {
      const base = app.internalMode === 'heating' ? 'heating' : 'cooling';
      Object.assign(app.inputs, DEFAULTS[base]);
      syncSliders();
    });
    document.querySelectorAll('.ref-btn[data-us]').forEach(btn => {
      btn.addEventListener('click', () => setUnits(btn.dataset.us));
    });
    // 应用持久化的单位制
    document.querySelectorAll('.ref-btn[data-us]').forEach(b => b.classList.toggle('active', b.dataset.us === unitSys));
    if (typeof PH !== 'undefined' && PH.setUnits) PH.setUnits(unitSys === 'ip');
    if (typeof Scene !== 'undefined' && Scene.setUnits) Scene.setUnits(unitSys === 'ip');

    // 运行模式（自动 / 手动对比）
    $('modeAuto').addEventListener('click', () => setRunMode('auto'));
    $('modeManual').addEventListener('click', () => setRunMode('manual'));
    $('setBaseBtn').addEventListener('click', setBaseline);
    $('clearBaseBtn').addEventListener('click', clearBaseline);
    $('pauseBtn').addEventListener('click', togglePause);
  }

  function setRunMode(m) {
    const manual = m === 'manual';
    $('modeAuto').classList.toggle('on', !manual);
    $('modeManual').classList.toggle('on', manual);
    $('manualBtns').style.display = manual ? 'inline-flex' : 'none';
    if (manual) {
      $('ctlNote').textContent = '手动对比：点「设为基准」记录当前工况 → 调参数看各测点变化量 Δ；可「暂停」定格数值';
    } else {
      clearBaseline();
      if (app.paused) togglePause();          // 退出手动即恢复运行
      $('ctlNote').textContent = '可单独或同时调节多个参数，系统将动态过渡到新工况';
    }
  }
  function setBaseline() {
    if (!app.disp) return;
    app.baseline = {};
    for (const cfg of SENSORS) if (!cfg.section) app.baseline[cfg.id] = cfg.get(app.disp);
    render();
  }
  function clearBaseline() { app.baseline = null; render(); }
  function togglePause() {
    app.paused = !app.paused;
    const b = $('pauseBtn');
    b.textContent = app.paused ? '▶ 继续' : '⏸ 暂停';
    b.classList.toggle('ghost', !app.paused);   // 暂停时变实心高亮
  }

  function buildSliders() {
    const box = $('sliders');
    for (const cfg of SLIDERS) {
      const row = document.createElement('div');
      row.className = 'slider-row';
      row.innerHTML = `<label>${cfg.label}</label>
        <input type="range" min="${cfg.min}" max="${cfg.max}" step="${cfg.step}">
        <div class="val"><span></span>${cfg.extra ? '<small></small>' : ''}</div>`;
      box.appendChild(row);
      const input = row.querySelector('input');
      const val = row.querySelector('.val span');
      const extra = row.querySelector('.val small');
      input.value = app.inputs[cfg.k];
      input.addEventListener('input', () => {
        app.inputs[cfg.k] = parseFloat(input.value);
        paint();
      });
      const paint = () => {
        const v = parseFloat(input.value);   // 模型单位（SI）
        if (cfg.kind) {
          const dv = uconv(cfg.kind, v);
          val.textContent = (Math.round(dv * 10) / 10) + ' ' + ulabel(cfg.kind);
        } else {
          val.textContent = v + ' ' + cfg.unit;
        }
        if (extra) extra.textContent = cfg.extra(v);
        input.style.setProperty('--fill', ((v - cfg.min) / (cfg.max - cfg.min) * 100) + '%');
      };
      paint();
      sliderEls[cfg.k] = { input, paint, row };
    }
  }

  function syncSliders() {
    for (const cfg of SLIDERS) {
      const s = sliderEls[cfg.k];
      s.input.value = app.inputs[cfg.k];
      s.paint();
    }
  }

  function buildSensors() {
    const grid = $('sensorGrid');
    for (const s of SENSORS) {
      if (s.section) {
        const hdr = document.createElement('div');
        hdr.className = 'sensor-section';
        hdr.textContent = s.section;
        grid.appendChild(hdr);
        continue;
      }
      const div = document.createElement('div');
      div.className = 'sensor ' + s.cls;
      div.innerHTML = `<div class="k">${s.label}</div>
        <div class="v"><span class="num">—</span><span class="u">${ulabel(s.kind)}</span></div>
        <span class="trend"></span>
        <div class="delta"></div>`;
      grid.appendChild(div);
      sensorEls[s.id] = { num: div.querySelector('.num'), unit: div.querySelector('.u'), trend: div.querySelector('.trend'), delta: div.querySelector('.delta'), box: div, calm: 0 };
      sensorHist[s.id] = [];
    }
  }

  // ---------- 模式切换 ----------
  function selectProcess(p) {
    if (app.seq && !app.seq.done) return;   // 时序进行中不允许切换
    if (p === 'cooling' || p === 'heating') {
      app.process = p;
      app.internalMode = p;
      Object.assign(app.inputs, DEFAULTS[p]);
      syncSliders();
    } else if (p === 'defrost') {
      if (app.internalMode !== 'heating') {
        app.internalMode = 'heating';
        Object.assign(app.inputs, DEFAULTS.heating);
        syncSliders();
      }
      app.flags.frost = Math.max(app.flags.frost, 0.65);   // 演示：直接给足霜量
      app.process = 'defrost';
      app.seq = new Sequence('defrost', app);
    } else if (p === 'oilreturn') {
      app.process = 'oilreturn';
      app.seq = new Sequence('oilreturn', app);
    }
    paintButtons();
    $('procDesc').textContent = PROC_DESC[app.process];
  }

  function paintButtons() {
    document.querySelectorAll('.mode-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === app.process));
    const names = { cooling: '制冷运行', heating: '制热运行', defrost: '化霜中', oilreturn: '回油运转' };
    $('procName').textContent = names[app.process];
  }

  // ---------- 时序进度 ----------
  function showSeq(res) {
    const box = $('seqProgress');
    if (!res) {
      box.style.display = 'none';
      lockSliders([]);
      return;
    }
    box.style.display = 'flex';
    $('seqStep').textContent = res.name;
    $('seqBar').style.width = (res.progress * 100).toFixed(0) + '%';
    if (res.desc) $('procDesc').textContent = res.name + '：' + res.desc;
    lockSliders(app.seq.type === 'defrost' ? ['comp', 'fanIn', 'fanOut'] : ['comp', 'exv']);
  }

  function lockSliders(keys) {
    for (const k in sliderEls) {
      sliderEls[k].row.classList.toggle('locked', keys.includes(k));
    }
  }

  // ---------- 周期渲染 ----------
  function fmt(v, dec) { return (v === undefined || isNaN(v)) ? '—' : v.toFixed(dec); }

  // 手动模式：测点卡显示「基准 X.X  Δ±Y.Y」
  function updateDelta(el, cfg, v) {
    if (!el.delta) return;
    if (!app.baseline || app.baseline[cfg.id] === undefined) { el.delta.textContent = ''; return; }
    const dec = fmtDec(cfg);
    const bv = uconv(cfg.kind, app.baseline[cfg.id]);
    const dv = v - bv;
    const eps = Math.pow(10, -dec) / 2;
    const cls = Math.abs(dv) < eps ? 'base' : (dv > 0 ? 'up' : 'dn');
    const sign = dv > 0 ? '+' : '';
    el.delta.innerHTML = `<span class="base">基准 ${fmt(bv, dec)}</span> <span class="${cls}">Δ${sign}${fmt(dv, dec)}</span>`;
  }

  function setStatUnits() {
    const cap = ' ' + ulabel('cap'), flow = ' ' + ulabel('flow');
    const c = $('stCap').querySelector('small'); if (c) c.textContent = cap;
    const p = $('stPow').querySelector('small'); if (p) p.textContent = cap;
    const m = $('stMdot').querySelector('small'); if (m) m.textContent = flow;
  }

  // 切换单位制：更新所有测点单位标签、滑块、性能，并通知压焓图重绘
  function setUnits(sys) {
    if (sys === unitSys) return;
    unitSys = sys;
    localStorage.setItem('hvac-sim-units', sys);
    document.querySelectorAll('.ref-btn[data-us]').forEach(b => b.classList.toggle('active', b.dataset.us === sys));
    for (const cfg of SENSORS) {
      if (cfg.section || !sensorEls[cfg.id]) continue;
      sensorEls[cfg.id].unit.textContent = ulabel(cfg.kind);
    }
    syncSliders();
    if (typeof PH !== 'undefined' && PH.setUnits) PH.setUnits(sys === 'ip');
    if (typeof Scene !== 'undefined' && Scene.setUnits) Scene.setUnits(sys === 'ip');
    render();
  }

  function render() {
    const s = app.disp;
    if (!s) return;

    // 测点表
    for (const cfg of SENSORS) {
      if (cfg.section) continue;
      const raw = cfg.get(s);                       // 原始 SI 值（用于变化检测）
      const v = uconv(cfg.kind, raw);               // 显示值（按单位制换算）
      const el = sensorEls[cfg.id];
      el.num.textContent = fmt(v, fmtDec(cfg));
      updateDelta(el, cfg, v);
      const h = sensorHist[cfg.id];
      h.push(raw);
      if (h.length > 16) h.shift();
      const d = raw - h[0];
      el.trend.textContent = d > 0.12 ? '▲' : (d < -0.12 ? '▼' : '');
      el.trend.style.color = d > 0.12 ? '#f87171' : '#38bdf8';

      // 动态高亮：数值正在变化时放大变红，稳定后自动恢复（基于原始 SI 值检测）
      const prev = el.prev;
      el.prev = raw;
      if (prev !== undefined && !isNaN(raw)) {
        const absD = Math.abs(raw - prev);
        const relRate = absD / (Math.abs(raw) + 0.02);            // 每帧相对变化
        // 需同时超过相对与绝对阈值，过滤稳态求解器/渲染混叠产生的末位抖动
        if (relRate > 0.0025 && absD > 0.03) {
          el.box.classList.add('changing');
          el.box.dataset.dir = raw > prev ? 'up' : 'down';
          el.calm = 0;
        } else if (el.box.classList.contains('changing')) {
          if (++el.calm > 3) el.box.classList.remove('changing');   // 连续稳定几帧后恢复
        }
      }
    }

    // 性能
    const heatSide = app.internalMode === 'heating';
    $('capLbl').textContent = heatSide ? '制热量' : '制冷量';
    const capKW = (heatSide ? s.Qc : s.Qe) / 1000, powKW = s.W / 1000;
    $('stCap').firstChild.textContent = fmt(uconv('cap', capKW), isIP() ? 1 : 2);
    $('stPow').firstChild.textContent = fmt(uconv('cap', powKW), isIP() ? 1 : 2);
    $('stCop').textContent = s.COP.toFixed(2);
    $('stMdot').firstChild.textContent = fmt(uconv('flow', s.mdot * 1000), 0);
    $('stPr').textContent = s.PR.toFixed(2);
    setStatUnits();

    // 场景标签（随单位制换算）
    const cool = app.internalMode === 'cooling';
    const tU = ' ' + ulabel('temp'), pU = ' ' + ulabel('press');
    const T = (v, d = 1) => fmt(uconv('temp', v), d) + tU;
    const P = (v, d = 2) => fmt(uconv('press', v), isIP() ? 1 : d) + pU;
    $('cDisT').textContent = T(s.Td);
    $('cDisP').textContent = P(s.Pd);
    $('cSucT').textContent = T(s.Tsuc);
    $('cSucP').textContent = P(s.Ps);
    $('cOCRole').textContent = cool ? '· 冷凝器' : '· 蒸发器';
    $('cICRole').textContent = cool ? '· 蒸发器' : '· 冷凝器';
    $('cOCMid').textContent = '中 ' + T(cool ? s.condMid : s.evapMid);
    $('cOCOut').textContent = '出 ' + T(cool ? s.condOut : s.evapOut);
    $('cICMid').textContent = '中 ' + T(cool ? s.evapMid : s.condMid);
    $('cICOut').textContent = '出 ' + T(cool ? s.evapOut : s.condOut);
    $('cFrost').textContent = app.flags.frost > 0.02 ? '霜' + Math.round(app.flags.frost * 100) + '%' : '';
    $('cExv').textContent = Math.round(app.inputsEff.exv) + ' % · ' + Math.round(app.inputsEff.exv * 4.8) + 'P';
    $('cSupply').textContent = T(s.supplyT);
    $('cRoom').textContent = T(s.returnT);
    $('cAmb').textContent = T(s.ambT);
    $('cOutAir').textContent = T(s.outAirT);

    renderHints(s);

    // 化霜按钮闪烁提醒
    const dfBtn = document.querySelector('.mode-btn[data-mode="defrost"]');
    dfBtn.classList.toggle('pulse', app.process === 'heating' && app.flags.frost > 0.6);
  }

  function renderHints(s) {
    const R = REFRIGERANTS[app.inputs.ref];
    const list = [];
    if (s.SH < 1.2) list.push(['过热度过低 · 回液风险', 1]);
    if (s.SH > 15) list.push(['过热度过高 · 缺氟或节流不足', 0]);
    if (s.SC < 1) list.push(['过冷度过低 · 冷媒量偏少', 0]);
    if (s.SC > 15) list.push(['过冷度过高 · 冷媒量偏多或节流过小', 0]);
    if (s.Td > 108) list.push(['排气温度过高', 1]);
    if (s.PR > 8) list.push(['压比过大 · 工况恶劣', 0]);
    if (s.Ps < 0.15) list.push(['低压过低 · 保护倾向', 1]);
    if (s.Pd > R.PcritMPa * 0.88) list.push(['高压过高 · 保护倾向', 1]);
    if (app.process === 'heating' && app.flags.frost > 0.6) list.push(['外盘结霜严重 · 建议化霜', 0]);

    const key = list.map(x => x[0]).join('|');
    if (key === lastHints) return;
    lastHints = key;
    $('hints').innerHTML = list.map(([t, bad]) =>
      `<span class="hint-pill${bad ? ' bad' : ''}">⚠ ${t}</span>`).join('');
  }

  return { init, render, showSeq, selectProcess, paintButtons, syncSliders, PROC_DESC };
})();
