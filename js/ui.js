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
    { k: 'comp', label: 'sl_comp', min: 20, max: 120, step: 1, unit: 'Hz' },
    { k: 'fanIn', label: 'sl_fanin', min: 0, max: 100, step: 1, unit: '%' },
    { k: 'fanOut', label: 'sl_fanout', min: 0, max: 100, step: 1, unit: '%' },
    { k: 'exv', label: 'sl_exv', min: 5, max: 100, step: 1, unit: '%', extra: v => Math.round(v * 4.8) + 'P' },
    { k: 'charge', label: 'sl_charge', min: 40, max: 130, step: 1, unit: '%' },
    { k: 'hxIn', label: 'sl_hxin', min: 50, max: 150, step: 1, unit: '%' },
    { k: 'hxOut', label: 'sl_hxout', min: 50, max: 150, step: 1, unit: '%' },
    { k: 'tIn', label: 'sl_tin', min: 16, max: 32, step: 0.5, unit: '°C', kind: 'temp' },
    { k: 'tOut', label: 'sl_tout', min: -25, max: 45, step: 0.5, unit: '°C', kind: 'temp' },
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
  let unitSys = localStorage.getItem('hvac-sim-units') || 'ip';
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
    { id: 'pd', cls: 'p', label: 'sen_pd', kind: 'press', dec: 2, get: s => s.Pd },
    { id: 'ps', cls: 'p', label: 'sen_ps', kind: 'press', dec: 2, get: s => s.Ps },
    { id: 'dsh', cls: 'sh', label: 'sen_dsh', kind: 'dt', dec: 1, get: s => s.dshDis },
    { id: 'ssh', cls: 'sh', label: 'sen_ssh', kind: 'dt', dec: 1, get: s => s.shSuc },
    { id: 'sc', cls: 'sh', label: 'sen_sc', kind: 'dt', dec: 1, get: s => s.SC },
    { id: 'td', cls: 't', label: 'sen_td', kind: 'temp', dec: 1, get: s => s.Td },
    { id: 'ts', cls: 't', label: 'sen_ts', kind: 'temp', dec: 1, get: s => s.Tsuc },
    { id: 'cm', cls: 't', label: 'sen_cm', kind: 'temp', dec: 1, get: s => s.condMid },
    { id: 'co', cls: 't', label: 'sen_co', kind: 'temp', dec: 1, get: s => s.condOut },
    { id: 'em', cls: 't', label: 'sen_em', kind: 'temp', dec: 1, get: s => s.evapMid },
    { id: 'eo', cls: 't', label: 'sen_eo', kind: 'temp', dec: 1, get: s => s.evapOut },
    { id: 'sa', cls: 'air', label: 'sen_sa', kind: 'temp', dec: 1, get: s => s.supplyT },
    { id: 'ra', cls: 'air', label: 'sen_ra', kind: 'temp', dec: 1, get: s => s.returnT },
    { id: 'oa', cls: 'air', label: 'sen_oa', kind: 'temp', dec: 1, get: s => s.ambT },
    { id: 'of', cls: 'air', label: 'sen_of', kind: 'temp', dec: 1, get: s => s.outAirT },
    // ---- 节流与蒸发器状态 ----
    { section: 'sen_section' },
    { id: 'thit', cls: 't', label: 'sen_thit', kind: 'temp', dec: 1, get: s => s.condOut },
    { id: 'thip', cls: 'p', label: 'sen_thip', kind: 'press', dec: 2, get: s => s.Pc },
    { id: 'thox', cls: 'sh', label: 'sen_thox', kind: 'x', dec: 0, get: s => throttleQuality(s) * 100 },
    { id: 'thot', cls: 't', label: 'sen_thot', kind: 'temp', dec: 1, get: s => s.Te },
    { id: 'thop', cls: 'p', label: 'sen_thop', kind: 'press', dec: 2, get: s => s.Pe },
    { id: 'evit', cls: 't', label: 'sen_evit', kind: 'temp', dec: 1, get: s => s.Te },
    { id: 'evip', cls: 'p', label: 'sen_evip', kind: 'press', dec: 2, get: s => s.Pe },
    { id: 'evot', cls: 't', label: 'sen_evot', kind: 'temp', dec: 1, get: s => s.evapOut },
    { id: 'evop', cls: 'p', label: 'sen_evop', kind: 'press', dec: 2, get: s => s.Ps },
  ];

  const fmtDec = cfg => (cfg.kind === 'press' && isIP()) ? 1 : cfg.dec;

  const PROC_DESC = { cooling: 'pd_cooling', heating: 'pd_heating', defrost: 'pd_defrost', oilreturn: 'pd_oil' };

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
      row.innerHTML = `<label>${window.T ? T(cfg.label) : cfg.label}</label>
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
        hdr.textContent = window.T ? T(s.section) : s.section;
        grid.appendChild(hdr);
        continue;
      }
      const div = document.createElement('div');
      div.className = 'sensor ' + s.cls;
      div.innerHTML = `<div class="k">${window.T ? T(s.label) : s.label}</div>
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
    $('procDesc').textContent = T(PROC_DESC[app.process]);
  }

  function paintButtons() {
    document.querySelectorAll('.mode-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === app.process));
    const names = { cooling: 'proc_cooling', heating: 'proc_heating', defrost: 'proc_defrost', oilreturn: 'proc_oil' };
    $('procName').textContent = T(names[app.process]);
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
    $('capLbl').textContent = window.T(heatSide ? 'st_cap_heat' : 'st_cap_cool');
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
    $('cOCRole').textContent = window.T(cool ? 'role_cond' : 'role_evap');
    $('cICRole').textContent = window.T(cool ? 'role_evap' : 'role_cond');
    $('cOCMid').textContent = window.T('mid_p') + ' ' + T(cool ? s.condMid : s.evapMid);
    $('cOCOut').textContent = window.T('out_p') + ' ' + T(cool ? s.condOut : s.evapOut);
    $('cICMid').textContent = window.T('mid_p') + ' ' + T(cool ? s.evapMid : s.condMid);
    $('cICOut').textContent = window.T('out_p') + ' ' + T(cool ? s.evapOut : s.condOut);
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
    if (s.SH < 1.2) list.push([T('hint_sh_low'), 1]);
    if (s.SH > 15) list.push([T('hint_sh_high'), 0]);
    if (s.SC < 1) list.push([T('hint_sc_low'), 0]);
    if (s.SC > 15) list.push([T('hint_sc_high'), 0]);
    if (s.Td > 108) list.push([T('hint_td_high'), 1]);
    if (s.PR > 8) list.push([T('hint_pr_high'), 0]);
    if (s.Ps < 0.15) list.push([T('hint_ps_low'), 1]);
    if (s.Pd > R.PcritMPa * 0.88) list.push([T('hint_pd_high'), 1]);
    if (app.process === 'heating' && app.flags.frost > 0.6) list.push([T('hint_frost'), 0]);

    const key = list.map(x => x[0]).join('|');
    if (key === lastHints) return;
    lastHints = key;
    $('hints').innerHTML = list.map(([t, bad]) =>
      `<span class="hint-pill${bad ? ' bad' : ''}">⚠ ${t}</span>`).join('');
  }

  return { init, render, showSeq, selectProcess, paintButtons, syncSliders, PROC_DESC };
})();
