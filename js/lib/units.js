/* =====================================================
 * units.js —— 页面级 公制(SI)/美制(IP) 双单位制引擎
 *  - 输入单位制与输出单位制独立选择，localStorage 记忆
 *  - 输入框: <input data-uk="press">，标签单位: <span data-ul="press"></span>
 *  - 页面内部计算一律 SI；输出用 Units.val()/Units.u() 格式化
 * ===================================================== */
const Units = (() => {
  /* f: 1 SI 单位 = f 个 IP 单位 */
  const K = {
    temp:  { si: '°C', ip: '°F', toIP: c => c * 1.8 + 32, toSI: f => (f - 32) / 1.8 },
    dtemp: { si: 'K', ip: '°R', f: 1.8 },
    press: { si: 'kPa', ip: 'psia', f: 0.1450377377 },
    kpa:   { si: 'kPa', ip: 'psi', f: 0.1450377377 },
    h:     { si: 'kJ/kg', ip: 'Btu/lb', f: 0.4299226 },
    s:     { si: 'kJ/(kg·K)', ip: 'Btu/(lb·°R)', f: 0.2388459 },
    rho:   { si: 'kg/m³', ip: 'lb/ft³', f: 0.06242796 },
    vspec: { si: 'm³/kg', ip: 'ft³/lb', f: 16.018463 },
    power: { si: 'kW', ip: 'Btu/h', f: 3412.141633 },
    mbh:   { si: 'kW', ip: 'MBH', f: 3.412141633 },
    ton:   { si: 'kW', ip: 'tons', f: 0.2843451361 },
    flowW: { si: 'm³/h', ip: 'GPM', f: 4.402867539 },
    flowA: { si: 'm³/h', ip: 'CFM', f: 0.5885777703 },
    vel:   { si: 'm/s', ip: 'FPM', f: 196.8503937 },
    velW:  { si: 'm/s', ip: 'ft/s', f: 3.280839895 },
    len:   { si: 'm', ip: 'ft', f: 3.280839895 },
    lenS:  { si: 'mm', ip: 'in', f: 1 / 25.4 },
    paD:   { si: 'Pa', ip: 'inH₂O', f: 1 / 249.089 },
    fricA: { si: 'Pa/m', ip: 'inH₂O/100ft', f: 1 / 8.1717 },
    fricW: { si: 'Pa/m', ip: 'ftH₂O/100ft', f: 1 / 98.064 },
    head:  { si: 'm', ip: 'ft', f: 3.280839895 },
    humr:  { si: 'g/kg', ip: 'gr/lb', f: 7.0 },
    area:  { si: 'm²', ip: 'ft²', f: 10.76391042 },
    mflow: { si: 'g/s', ip: 'lb/h', f: 7.936641439 },
    volcap:{ si: 'kJ/m³', ip: 'Btu/ft³', f: 0.02683919 },
  };

  let sysIn = localStorage.getItem('hvac-u-in') || 'ip';
  let sysOut = localStorage.getItem('hvac-u-out') || 'ip';
  const cbIn = [], cbOut = [];

  function convert(kind, v, from, to) {
    if (from === to || v === null || v === undefined || isNaN(v)) return v;
    const k = K[kind];
    if (!k) return v;
    if (k.toIP) return to === 'ip' ? k.toIP(v) : k.toSI(v);
    return to === 'ip' ? v * k.f : v / k.f;
  }

  const toSI = (kind, v) => convert(kind, v, sysIn, 'si');
  const val = (kind, siv) => convert(kind, siv, 'si', sysOut);        // 输出数值
  const u = kind => K[kind] ? K[kind][sysOut] : '';                   // 输出单位
  const uIn = kind => K[kind] ? K[kind][sysIn] : '';                  // 输入单位
  const nice = v => (v === null || isNaN(v)) ? v : +parseFloat(Number(v).toPrecision(5));

  function relabel() {
    document.querySelectorAll('[data-ul]').forEach(el => { el.textContent = uIn(el.dataset.ul); });
  }

  function setIn(sys) {
    if (sys === sysIn) return;
    document.querySelectorAll('input[data-uk]').forEach(el => {
      const v = parseFloat(el.value);
      if (!isNaN(v)) el.value = nice(convert(el.dataset.uk, convert(el.dataset.uk, v, sysIn, 'si'), 'si', sys));
    });
    sysIn = sys;
    localStorage.setItem('hvac-u-in', sys);
    relabel();
    paintToggle();
    cbIn.forEach(f => f());
  }

  function setOut(sys) {
    if (sys === sysOut) return;
    sysOut = sys;
    localStorage.setItem('hvac-u-out', sys);
    paintToggle();
    cbOut.forEach(f => f());
  }

  /* 导航栏双开关 */
  function mount(container) {
    const div = document.createElement('span');
    div.id = 'unitToggle';
    div.innerHTML =
      `<span class="ut-lbl" data-i18n="in_label">输入</span><span class="ut-seg" data-io="in"><button data-s="si" data-i18n="unit_si">公制</button><button data-s="ip" data-i18n="unit_ip">美制</button></span>` +
      `<span class="ut-lbl" data-i18n="out_label">输出</span><span class="ut-seg" data-io="out"><button data-s="si" data-i18n="unit_si">公制</button><button data-s="ip" data-i18n="unit_ip">美制</button></span>`;
    container.appendChild(div);
    div.querySelectorAll('button').forEach(b => {
      b.onclick = () => (b.parentElement.dataset.io === 'in' ? setIn : setOut)(b.dataset.s);
    });
    paintToggle();
    relabel();
  }

  function paintToggle() {
    const t = document.getElementById('unitToggle');
    if (!t) return;
    t.querySelectorAll('.ut-seg').forEach(seg => {
      const cur = seg.dataset.io === 'in' ? sysIn : sysOut;
      seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.s === cur));
    });
  }

  /* 页面初始加载：HTML 中默认值按 SI 书写，若记忆为 IP 则转换一次 */
  function initDefaults() {
    if (sysIn === 'ip') {
      document.querySelectorAll('input[data-uk]').forEach(el => {
        const v = parseFloat(el.value);
        if (!isNaN(v)) el.value = nice(convert(el.dataset.uk, v, 'si', 'ip'));
      });
    }
    relabel();
  }

  return { toSI, val, u, uIn, nice, mount, initDefaults, relabel,
           onIn: f => cbIn.push(f), onOut: f => cbOut.push(f),
           get sysIn() { return sysIn; }, get sysOut() { return sysOut; } };
})();
window.Units = Units;   // 供 shell.js 探测
