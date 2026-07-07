/* =====================================================
 * model.js —— 简化稳态循环求解器
 * 输入: 用户参数 + 内部循环方向 + 化霜/结霜标志
 * 输出: 全部测点 / 循环状态点 / 性能指标
 *
 * 求解思路（定性正确的半经验模型）:
 *  - 压缩机: 容积式质量流量 mdot = ηv·Vd·Hz·ρ吸气
 *  - EXV:    孔口流量 ∝ 开度·√(ρ液·ΔP)，与压缩机流量之比决定过热度
 *  - 冷媒量: 影响过冷度（多→过冷大）与过热度（少→过热大）
 *  - 换热器: Q = UA·(空气温 - 饱和温)，UA 随风量^0.65 与面积缩放
 *  - 迭代松弛求 Te / Tc 平衡点
 * ===================================================== */

const V_DISP = 26e-6;      // 压缩机每转排量 m³
const EXV_NOM = 55;        // 标定开度 %

/** 每种冷媒标定 EXV 系数：额定工况(Te=10,Tc=45,60Hz)下 流量比=1 */
(function calibrate() {
  for (const key in REFRIGERANTS) {
    const R = REFRIGERANTS[key];
    const rho = rhoVap(R, psat(R, 10), 15);
    const mNom = 0.92 * V_DISP * 60 * rho;
    const dP = (psat(R, 45) - psat(R, 10)) * 1e6;
    R.keCal = mNom / Math.sqrt(1050 * dP);
  }
})();

/**
 * 求解循环
 * @param inp  {comp,fanIn,fanOut,exv,charge,hxIn,hxOut,tIn,tOut,ref}
 * @param mode 'cooling' | 'heating'  内部循环方向
 * @param fl   {defrost:boolean, frost:0..1}
 */
function solveCycle(inp, mode, fl) {
  const R = REFRIGERANTS[inp.ref];
  const cool = (mode === 'cooling');

  // ---- 空气侧换热能力 ----
  const fi = 0.06 + 0.94 * (inp.fanIn / 100);
  const fo = 0.06 + 0.94 * (inp.fanOut / 100);
  const UAin  = 620 * Math.pow(fi, 0.65) * (inp.hxIn / 100);
  const UAout = 1080 * Math.pow(fo, 0.65) * (inp.hxOut / 100) * (1 - 0.55 * fl.frost);

  let evapAirT = cool ? inp.tIn : inp.tOut;
  let condAirT = cool ? inp.tOut : inp.tIn;
  let UAe = cool ? UAin : UAout;
  let UAc = cool ? UAout : UAin;

  // 化霜: 内部为制冷循环，室外盘管为冷凝器，霜层是 0°C 附近的巨大热汇
  if (fl.defrost) {
    condAirT = 0.5;
    UAc = 60 + 1500 * fl.frost;
  }

  const Hz = Math.max(inp.comp, 1);
  const m = R.kExp / 0.82;   // 多变过程有效指数

  let Te = evapAirT - 8, Tc = condAirT + 10;
  let SH = 5, SC = 5, mdot = 0.04, Td = 70, PR = 3, ratio = 1;
  let h1 = 0, h2 = 0, h3 = 0, Pe = 1, Pc = 2;

  for (let i = 0; i < 40; i++) {
    Te = clamp(Te, -45, evapAirT - 0.3);
    Tc = clamp(Tc, condAirT + 0.3, R.TcritC - 3);
    if (Tc <= Te + 2) Tc = Te + 2;

    Pe = psat(R, Te);
    Pc = psat(R, Tc);
    PR = Math.max(Pc / Pe, 1.05);

    // ---- EXV / 冷媒量 → 过热度、过冷度 ----
    const dP = Math.max((Pc - Pe) * 1e6, 1e4);
    const mExv = R.keCal * (inp.exv / EXV_NOM) * Math.sqrt(1050 * dP);
    const etaV = clamp(0.98 - 0.028 * (PR - 1.5), 0.45, 0.98);
    const rho = rhoVap(R, Pe, Te + SH);
    mdot = etaV * V_DISP * Hz * rho;
    ratio = clamp(mExv / Math.max(mdot, 1e-4), 0.05, 3);

    SH = 5 * Math.pow(1 / ratio, 2.2) + Math.max(0, 92 - inp.charge) * 0.45;
    if (inp.charge > 118) SH = Math.min(SH, 1.0);   // 过充 → 回液倾向
    SH = clamp(SH, 0.3, 45);

    SC = clamp(5 + 0.22 * (inp.charge - 100) + 9 * (1 - Math.min(ratio, 1.6)), 0.2, 24);

    // ---- 循环状态点 ----
    h1 = hg(R, Te) + R.cpv * SH;
    const T1K = Te + SH + 273.15;
    Td = clamp(T1K * Math.pow(PR, m) - 273.15, Tc + 3, 140);
    // 排气焓：冷凝压力侧从饱和气外推（高压区比热约为低压区 1.55 倍）
    h2 = Math.max(hg(R, Tc) + R.cpv * 1.55 * (Td - Tc), h1 + 5);
    h3 = hf(R, Tc) - R.cpl * SC;

    // 蒸发器有效吸热只计入盘管内过热(≤8K)，过量过热发生在回气管路
    const h1e = hg(R, Te) + R.cpv * Math.min(SH, 8);
    const Qe = Math.max(mdot * (h1e - h3) * 1000, 50);   // W
    const Qc = Math.max(mdot * (h2 - h3) * 1000, 60);

    // ---- 换热平衡 → 更新 Te / Tc ----
    const TeN = evapAirT - Qe / UAe;
    const TcN = condAirT + Qc / UAc;
    Te += 0.5 * (TeN - Te);
    Tc += 0.5 * (TcN - Tc);
  }

  // ---- 最终性能 ----
  const Qe = mdot * (hg(R, Te) + R.cpv * Math.min(SH, 8) - h3) * 1000;
  const Qc = mdot * (h2 - h3) * 1000;
  const W = mdot * (h2 - h1) * 1000 / 0.88 + 25 + 1.4 * Hz;
  const Tsuc = Te + SH + 0.5;

  // ---- 空气侧出口温度 ----
  const CAirIn  = 460 * fi;
  const CAirOut = 1150 * fo;
  // 送风温度受盘管表面温度物理约束（不可能低于蒸发温 / 高于冷凝温）
  let supplyT, outAirT;
  if (cool) {
    supplyT = clamp(inp.tIn - 0.72 * Qe / CAirIn, Te + 1.5, inp.tIn);
    outAirT = Math.min(inp.tOut + Qc / CAirOut, Tc - 1);
  } else {
    supplyT = clamp(inp.tIn + Qc / CAirIn, inp.tIn, Tc - 1);
    outAirT = Math.max(inp.tOut - 0.92 * Qe / CAirOut, Te + 1);
  }

  const Pd = Pc * 1.02, Ps = Pe * 0.97;

  return {
    mode, ref: inp.ref,
    Te, Tc, Pe, Pc, Pd, Ps, PR, SH, SC, Td, Tsuc, mdot, ratio,
    dshDis: Td - tsat(R, Pd),          // 排气过热度
    shSuc: Tsuc - tsat(R, Ps),         // 回气过热度
    condMid: Tc, condOut: Tc - SC,
    evapMid: Te, evapOut: Te + SH * 0.85,
    supplyT, returnT: inp.tIn, ambT: inp.tOut, outAirT,
    Qe, Qc, W,
    COP: (cool ? Qe : Qc) / Math.max(W, 1),
    h1, h2, h3, h4: h3,
  };
}
