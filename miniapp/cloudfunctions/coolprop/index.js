/* 微信云开发云函数:CoolProp 物性计算
 * 等价迁移自网站 server.py(CoolProp 8.0 Python → coolprop-wasm 7.2,数值已比对一致)
 *
 * 小程序端调用:
 *   wx.cloud.callFunction({ name: 'coolprop', data: { action: 'phcycle', params: { fluid:'R410A', pe:1085, pc:2735, sh:5, sc:5, eff:0.7 } } })
 *     .then(r => r.result)   // 与网站 /api/* 返回同形 JSON;出错为 { error: '...' }
 *
 * 单位约定与网站一致:压力 kPa、温度 °C、焓 kJ/kg(IIR 基准:0°C 饱和液 h=200)、
 * 熵 kJ/(kg·K)(IIR s=1.0)、含湿量 g/kg 干空气。
 */
'use strict';

// coolprop-wasm 是 ESM 包,CJS 云函数环境用动态 import;实例全局缓存(容器复用免重复初始化 ~1.5s)
let cpPromise = null;
const getCP = () => cpPromise || (cpPromise = import('coolprop-wasm').then(m => m.initCoolProp()));

// 展示名 → CoolProp 名(R454B 预定义混合物须用 .mix 名)
const FLUIDS = {
  R410A: 'R410A', R32: 'R32', R454B: 'R454B.mix',
  R134a: 'R134a', R290: 'R290', R404A: 'R404A',
  R407C: 'R407C', R22: 'R22', R1234yf: 'R1234yf',
  R600a: 'R600a', R717: 'R717', R744: 'R744',
};
const GLIDE_BLENDS = new Set(['R454B', 'R407C', 'R404A', 'R410A']);
// 预定义混合物无法查临界参数 → 文献常数兜底(R454B/Opteon XL41)
const CRIT_FALLBACK = { 'R454B.mix': { T: 351.25, P: 5267e3, M: 0.0626 } };

const critCache = {}, offsetCache = {};

function cpFluid(name) {
  if (!FLUIDS[name]) throw new Error('未知冷媒: ' + name);
  return FLUIDS[name];
}

function maybe(fn) {
  try {
    const v = fn();
    if (v === null || v === undefined || Number.isNaN(v) || !Number.isFinite(v)) return null;
    return v;
  } catch (e) { return null; }
}

function crit(CP, cn) {
  if (!critCache[cn]) {
    critCache[cn] = CRIT_FALLBACK[cn] || {
      T: CP.Props1SI('Tcrit', cn),
      P: CP.Props1SI('pcrit', cn),
      M: CP.Props1SI('molarmass', cn),
    };
  }
  return critCache[cn];
}

// 焓熵基准统一 IIR(与网站/常用表册一致)
function offsets(CP, cn) {
  if (!offsetCache[cn]) {
    try {
      const h0 = CP.PropsSI('H', 'T', 273.15, 'Q', 0, cn);
      const s0 = CP.PropsSI('S', 'T', 273.15, 'Q', 0, cn);
      offsetCache[cn] = [h0 - 200000.0, s0 - 1000.0];
    } catch (e) { offsetCache[cn] = [0, 0]; }
  }
  return offsetCache[cn];
}
const dispH = (CP, cn, h) => (h - offsets(CP, cn)[0]) / 1000.0;
const dispS = (CP, cn, s) => (s - offsets(CP, cn)[1]) / 1000.0;
const siH = (CP, cn, h) => h * 1000.0 + offsets(CP, cn)[0];
const siS = (CP, cn, s) => s * 1000.0 + offsets(CP, cn)[1];

/* P(Pa) 或 T(K) 处饱和信息(含滑移) */
function satInfo(CP, cn, { P, T }) {
  const out = {};
  if (P != null) {
    const Tb = maybe(() => CP.PropsSI('T', 'P', P, 'Q', 0, cn));
    const Td = maybe(() => CP.PropsSI('T', 'P', P, 'Q', 1, cn));
    if (Tb === null || Td === null) return null;
    out.t_bubble = Tb - 273.15; out.t_dew = Td - 273.15; out.glide = Td - Tb;
    out.hf = dispH(CP, cn, CP.PropsSI('H', 'P', P, 'Q', 0, cn));
    out.hg = dispH(CP, cn, CP.PropsSI('H', 'P', P, 'Q', 1, cn));
    out.sf = dispS(CP, cn, CP.PropsSI('S', 'P', P, 'Q', 0, cn));
    out.sg = dispS(CP, cn, CP.PropsSI('S', 'P', P, 'Q', 1, cn));
    out.rhof = CP.PropsSI('D', 'P', P, 'Q', 0, cn);
    out.rhog = CP.PropsSI('D', 'P', P, 'Q', 1, cn);
  } else {
    const Pb = maybe(() => CP.PropsSI('P', 'T', T, 'Q', 0, cn));
    const Pd = maybe(() => CP.PropsSI('P', 'T', T, 'Q', 1, cn));
    if (Pb === null || Pd === null) return null;
    out.p_bubble = Pb / 1000.0; out.p_dew = Pd / 1000.0;
    out.hf = dispH(CP, cn, CP.PropsSI('H', 'T', T, 'Q', 0, cn));
    out.hg = dispH(CP, cn, CP.PropsSI('H', 'T', T, 'Q', 1, cn));
    out.sf = dispS(CP, cn, CP.PropsSI('S', 'T', T, 'Q', 0, cn));
    out.sg = dispS(CP, cn, CP.PropsSI('S', 'T', T, 'Q', 1, cn));
    out.rhof = CP.PropsSI('D', 'T', T, 'Q', 0, cn);
    out.rhog = CP.PropsSI('D', 'T', T, 'Q', 1, cn);
  }
  out.latent = out.hg - out.hf;
  return out;
}

/* 两个独立参数 → 全状态(内部 SI) */
function fullState(CP, cn, k1, v1, k2, v2) {
  const st = {};
  const T = CP.PropsSI('T', k1, v1, k2, v2, cn);
  const P = CP.PropsSI('P', k1, v1, k2, v2, cn);
  st.T = T - 273.15; st.P = P / 1000.0;
  st.h = dispH(CP, cn, CP.PropsSI('H', k1, v1, k2, v2, cn));
  st.s = dispS(CP, cn, CP.PropsSI('S', k1, v1, k2, v2, cn));
  const rho = CP.PropsSI('D', k1, v1, k2, v2, cn);
  st.rho = rho; st.v = rho ? 1.0 / rho : null;
  const q = maybe(() => CP.PropsSI('Q', k1, v1, k2, v2, cn));
  st.quality = (q !== null && q >= 0.0 && q <= 1.0) ? q : null;
  st.cp = maybe(() => CP.PropsSI('C', k1, v1, k2, v2, cn) / 1000.0);
  st.cv = maybe(() => CP.PropsSI('O', k1, v1, k2, v2, cn) / 1000.0);
  st.mu = maybe(() => CP.PropsSI('V', k1, v1, k2, v2, cn) * 1e6);
  st.k = maybe(() => CP.PropsSI('L', k1, v1, k2, v2, cn) * 1000.0);
  const Pcrit = crit(CP, cn).P;
  if (P >= Pcrit * 0.999) st.phase = '超临界';
  else if (st.quality !== null) st.phase = '两相（湿蒸气）';
  else {
    const sat = satInfo(CP, cn, { P });
    if (sat) {
      if (st.T >= sat.t_dew - 0.01) { st.phase = '过热蒸气'; st.superheat = st.T - sat.t_dew; }
      else { st.phase = '过冷液体'; st.subcool = sat.t_bubble - st.T; }
    } else st.phase = '—';
  }
  return st;
}

/* ---------------- actions(与网站 /api/* 一一对应) ---------------- */
const ACTIONS = {

  health(CP) {
    let ver = 'wasm';
    try { ver = CP.get_global_param_string('version'); } catch (e) {}
    return { ok: true, coolprop: ver, runtime: 'wasm-cloudfn', fluids: Object.keys(FLUIDS) };
  },

  fluidinfo(CP, p) {
    const f = p.fluid, cn = cpFluid(f);
    const c = crit(CP, cn);
    return {
      fluid: f,
      t_crit: c.T - 273.15, p_crit: c.P / 1000.0, molar_mass: c.M * 1000.0,
      t_min: maybe(() => CP.Props1SI('Tmin', cn) - 273.15),
      glide_blend: GLIDE_BLENDS.has(f),
    };
  },

  sat(CP, p) {
    const cn = cpFluid(p.fluid);
    const sat = (p.by === 'T')
      ? satInfo(CP, cn, { T: Number(p.value) + 273.15 })
      : satInfo(CP, cn, { P: Number(p.value) * 1000.0 });
    if (!sat) throw new Error('超出饱和范围（可能高于临界点）');
    sat.fluid = p.fluid;
    return sat;
  },

  sattable(CP, p) {
    const cn = cpFluid(p.fluid);
    const t1 = p.t1 != null ? Number(p.t1) : -40.0;
    const t2 = p.t2 != null ? Number(p.t2) : 60.0;
    const dt = Math.max(p.dt != null ? Number(p.dt) : 10.0, 1.0);
    const tcrit = crit(CP, cn).T - 273.15;
    const rows = [];
    for (let t = t1; t <= t2 + 1e-6 && t < tcrit - 1; t += dt) {
      const s = satInfo(CP, cn, { T: t + 273.15 });
      if (s) { s.t = t; rows.push(s); }
    }
    return { fluid: p.fluid, rows };
  },

  dome(CP, p) {
    const cn = cpFluid(p.fluid);
    const Pc = crit(CP, cn).P;
    const Pt = Math.max(maybe(() => CP.Props1SI('pmin', cn)) || 20000.0, 20000.0);
    const n = 70, Ps = [], hfs = [], hgs = [], Ts = [];
    for (let i = 0; i < n; i++) {
      const P = Pt * Math.pow(Pc * 0.995 / Pt, i / (n - 1.0));
      const hf = maybe(() => dispH(CP, cn, CP.PropsSI('H', 'P', P, 'Q', 0, cn)));
      const hg = maybe(() => dispH(CP, cn, CP.PropsSI('H', 'P', P, 'Q', 1, cn)));
      const td = maybe(() => CP.PropsSI('T', 'P', P, 'Q', 1, cn));
      if (hf === null || hg === null) continue;
      Ps.push(P / 1000.0); hfs.push(hf); hgs.push(hg);
      Ts.push(td !== null ? td - 273.15 : null);
    }
    return { fluid: p.fluid, p: Ps, hf: hfs, hg: hgs, t: Ts, t_crit: crit(CP, cn).T - 273.15, p_crit: Pc / 1000.0 };
  },

  phcycle(CP, p) {
    const f = p.fluid, cn = cpFluid(f);
    const pe = Number(p.pe) * 1000.0, pc = Number(p.pc) * 1000.0;
    const sh = p.sh != null ? Number(p.sh) : 5.0;
    const sc = p.sc != null ? Number(p.sc) : 5.0;
    const eff = Math.min(Math.max(p.eff != null ? Number(p.eff) : 0.70, 0.3), 1.0);
    const mdot = p.mdot != null ? Number(p.mdot) : 0.0;
    if (pc <= pe * 1.01) throw new Error('冷凝压力必须高于蒸发压力');

    const tDewE = CP.PropsSI('T', 'P', pe, 'Q', 1, cn);
    const tBubC = CP.PropsSI('T', 'P', pc, 'Q', 0, cn);
    let h1, s1, rho1, T1;
    if (sh > 0.01) {
      h1 = CP.PropsSI('H', 'P', pe, 'T', tDewE + sh, cn);
      s1 = CP.PropsSI('S', 'P', pe, 'T', tDewE + sh, cn);
      rho1 = CP.PropsSI('D', 'P', pe, 'T', tDewE + sh, cn);
      T1 = tDewE + sh;
    } else {
      h1 = CP.PropsSI('H', 'P', pe, 'Q', 1, cn);
      s1 = CP.PropsSI('S', 'P', pe, 'Q', 1, cn);
      rho1 = CP.PropsSI('D', 'P', pe, 'Q', 1, cn);
      T1 = tDewE;
    }
    const h2s = CP.PropsSI('H', 'P', pc, 'S', s1, cn);
    const h2 = h1 + (h2s - h1) / eff;
    const T2 = CP.PropsSI('T', 'P', pc, 'H', h2, cn);
    let h3, T3;
    if (sc > 0.01) { h3 = CP.PropsSI('H', 'P', pc, 'T', tBubC - sc, cn); T3 = tBubC - sc; }
    else { h3 = CP.PropsSI('H', 'P', pc, 'Q', 0, cn); T3 = tBubC; }
    const h4 = h3;
    const q4 = maybe(() => CP.PropsSI('Q', 'P', pe, 'H', h4, cn));
    const T4 = CP.PropsSI('T', 'P', pe, 'H', h4, cn);

    const qe = (h1 - h4) / 1000.0, qc = (h2 - h3) / 1000.0, w = (h2 - h1) / 1000.0;
    const out = {
      fluid: f,
      t_evap_dew: tDewE - 273.15, t_cond_bubble: tBubC - 273.15,
      points: {
        '1': { T: T1 - 273.15, P: pe / 1000, h: dispH(CP, cn, h1), s: dispS(CP, cn, s1) },
        '2s': { T: CP.PropsSI('T', 'P', pc, 'H', h2s, cn) - 273.15, P: pc / 1000, h: dispH(CP, cn, h2s) },
        '2': { T: T2 - 273.15, P: pc / 1000, h: dispH(CP, cn, h2) },
        '3': { T: T3 - 273.15, P: pc / 1000, h: dispH(CP, cn, h3) },
        '4': { T: T4 - 273.15, P: pe / 1000, h: dispH(CP, cn, h4), x: q4 },
      },
      qe, qc, w,
      cop_c: qe / w, cop_h: qc / w,
      pr: pc / pe, rho_suction: rho1,
      vol_capacity: qe * rho1,
    };
    if (mdot > 0) {
      const m = mdot / 1000.0;
      out.mdot = mdot; out.Qe_kW = qe * m; out.Qc_kW = qc * m; out.W_kW = w * m;
    }
    return out;
  },

  props(CP, p) {
    const f = p.fluid, cn = cpFluid(f);
    const pair = String(p.pair || '');
    const conv = (letter, val) => {
      switch (letter) {
        case 'T': return ['T', Number(val) + 273.15];
        case 'P': return ['P', Number(val) * 1000.0];
        case 'Q': return ['Q', Number(val)];
        case 'H': return ['H', siH(CP, cn, Number(val))];
        case 'S': return ['S', siS(CP, cn, Number(val))];
        case 'D': return ['D', Number(val)];
        default: throw new Error('不支持的参数: ' + letter);
      }
    };
    const [k1, sv1] = conv(pair[0], p.v1);
    const [k2, sv2] = conv(pair[1], p.v2);
    if (pair === 'TP' || pair === 'PT') {
      const Tval = k1 === 'T' ? sv1 : sv2;
      const Pval = k1 === 'P' ? sv1 : sv2;
      const sat = satInfo(CP, cn, { P: Pval });
      if (sat && sat.t_bubble - 0.05 < Tval - 273.15 && Tval - 273.15 < sat.t_dew + 0.05) {
        return { two_phase_ambiguous: true, sat, hint: '该温压组合位于两相区，温度与压力不独立；请改用 压力+干度 或 温度+干度 查询。' };
      }
    }
    const st = fullState(CP, cn, k1, sv1, k2, sv2);
    st.sat_at_p = satInfo(CP, cn, { P: st.P * 1000.0 });
    if (st.T + 273.15 < crit(CP, cn).T) st.sat_at_t = satInfo(CP, cn, { T: st.T + 273.15 });
    st.fluid = f;
    return st;
  },

  psychro(CP, p) {
    const P = (p.p != null ? Number(p.p) : 101.325) * 1000.0;
    const keymap = { tdb: 'T', twb: 'B', tdp: 'D', rh: 'R', w: 'W', h: 'H' };
    const given = [];
    for (const k of Object.keys(keymap)) {
      if (p[k] !== undefined && p[k] !== null && p[k] !== '') {
        let v = Number(p[k]);
        if (k === 'tdb' || k === 'twb' || k === 'tdp') v += 273.15;
        else if (k === 'rh') v /= 100.0;
        else if (k === 'w') v /= 1000.0;
        else if (k === 'h') v *= 1000.0;
        given.push([keymap[k], v]);
      }
    }
    if (given.length !== 2) throw new Error('请提供恰好两个已知参数（当前 ' + given.length + ' 个）');
    const [a, b] = given;
    const get = (out) => CP.HAPropsSI(out, a[0], a[1], b[0], b[1], 'P', P);
    const Tdb = get('T');
    const out = {
      p: P / 1000.0,
      tdb: Tdb - 273.15, twb: get('B') - 273.15, tdp: get('D') - 273.15,
      rh: get('R') * 100.0, w: get('W') * 1000.0, h: get('H') / 1000.0,
      v: get('V'), p_w: get('P_w') / 1000.0,
      p_ws: CP.HAPropsSI('P_w', 'T', Tdb, 'R', 1.0, 'P', P) / 1000.0,
    };
    out.rho = (1.0 + out.w / 1000.0) / out.v;
    return out;
  },

  watersat(CP, p) {
    if (p.by === 'T') {
      const T = Number(p.value) + 273.15;
      return { t: T - 273.15, p_sat: CP.PropsSI('P', 'T', T, 'Q', 0, 'Water') / 1000.0 };
    }
    const P = Number(p.value) * 1000.0;
    return { p: P / 1000.0, t_sat: CP.PropsSI('T', 'P', P, 'Q', 0, 'Water') - 273.15 };
  },
};

exports.main = async (event) => {
  try {
    const CP = await getCP();
    const fn = ACTIONS[event && event.action];
    if (!fn) return { error: '未知 action: ' + (event && event.action) };
    return fn(CP, (event && event.params) || {});
  } catch (e) {
    return { error: String((e && e.message) || e) };
  }
};
