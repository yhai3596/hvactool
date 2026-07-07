/* =====================================================
 * refprops.js —— 冷媒物性（拟合近似，教学演示用）
 * 基准: IIR 参考态 (0°C 饱和液 h=200 kJ/kg)
 * Psat: ln(P_kPa) = A - B / T_K   (两点拟合)
 * 潜热: Watson 关系  L = L0 * ((Tc-T)/(Tc-T0))^0.38
 * ===================================================== */

const REFRIGERANTS = {
  R410A: {
    label: 'R410A', A: 15.377, B: 2375,
    TcritC: 71.4, PcritMPa: 4.90,
    L0: 221,          // 0°C 潜热 kJ/kg
    cpl: 1.55,        // 液相比热 kJ/(kg·K)
    cpv: 1.20,        // 过热气相有效比热
    Rgas: 114.5,      // 比气体常数 J/(kg·K)
    kExp: 0.145,      // 等熵指数项 (γ-1)/γ
    color: '#22d3ee',
  },
  R32: {
    label: 'R32', A: 15.429, B: 2384,
    TcritC: 78.1, PcritMPa: 5.78,
    L0: 315, cpl: 1.85, cpv: 1.50, Rgas: 159.9, kExp: 0.200,
    color: '#4ade80',
  },
  R454B: {
    label: 'R454B', A: 15.326, B: 2371,
    TcritC: 78.1, PcritMPa: 5.27,
    L0: 250, cpl: 1.65, cpv: 1.35, Rgas: 132.8, kExp: 0.174,
    color: '#a78bfa',
  },
};

function clamp(x, a, b) { return x < a ? a : (x > b ? b : x); }
function lerp(a, b, k) { return a + (b - a) * k; }

/** 饱和压力 MPa（T: °C） */
function psat(R, T) {
  T = clamp(T, -60, R.TcritC - 0.2);
  return Math.exp(R.A - R.B / (T + 273.15)) / 1000;
}

/** 饱和温度 °C（P: MPa） */
function tsat(R, P) {
  P = Math.max(P, 0.02);
  return R.B / (R.A - Math.log(P * 1000)) - 273.15;
}

/** 饱和液焓 kJ/kg */
function hf(R, T) {
  T = clamp(T, -60, R.TcritC - 0.2);
  return 200 + R.cpl * T + 0.004 * T * T;
}

/** 汽化潜热 kJ/kg（Watson） */
function latent(R, T) {
  const TcK = R.TcritC + 273.15, TK = clamp(T, -60, R.TcritC - 0.5) + 273.15;
  return R.L0 * Math.pow(Math.max((TcK - TK) / (TcK - 273.15), 0.005), 0.38);
}

/** 饱和气焓 kJ/kg */
function hg(R, T) { return hf(R, T) + latent(R, T); }

/** 过热蒸气密度 kg/m³（理想气体近似，P: MPa, T: °C） */
function rhoVap(R, P, T) {
  return (P * 1e6) / (R.Rgas * (T + 273.15));
}
