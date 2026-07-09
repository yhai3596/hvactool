/* =====================================================
 * main.js —— 应用状态与主循环
 *  求解(8Hz) → 一阶惯性平滑(动态过渡) → 场景/压焓图/仪表渲染
 * ===================================================== */

const App = {
  inputs: { comp: 60, fanIn: 70, fanOut: 70, exv: 55, charge: 100, hxIn: 100, hxOut: 100, tIn: 27, tOut: 35, ref: 'R410A' },
  inputsEff: null,             // 叠加时序覆盖后的生效输入
  process: 'cooling',          // 界面过程：cooling/heating/defrost/oilreturn
  internalMode: 'cooling',     // 内部循环方向
  flags: { frost: 0, defrost: false, steam: false, dripRate: 0, oil: false },
  seq: null,
  target: null,                // 求解目标值
  disp: null,                  // 平滑显示值
  paused: false,               // 手动模式：暂停物理过渡（定格数值便于对比）
  baseline: null,              // 手动模式：基准快照 {sensorId: 值}
};

/* 各量的一阶惯性时间常数（秒）—— 模拟真实系统响应 */
const TAU = {
  Pd: 1.2, Ps: 1.2, Pe: 1.2, Pc: 1.2, PR: 1.5,
  Td: 3.5, Tsuc: 2.5, Te: 2.5, Tc: 2.5,
  SH: 2.2, SC: 2.2, dshDis: 3, shSuc: 2.5,
  condMid: 2.5, condOut: 2.5, evapMid: 2.5, evapOut: 2.5,
  supplyT: 4, outAirT: 4, returnT: 0.5, ambT: 0.5,
  mdot: 1.5, Qe: 2, Qc: 2, W: 1.5, COP: 2, ratio: 1.5,
  h1: 1.8, h2: 1.8, h3: 1.8, h4: 1.8,
};

let lastT = 0, solveAcc = 1, phAcc = 1, uiAcc = 1;

function smooth(dt) {
  const t = App.target, d = App.disp;
  for (const k in t) {
    if (typeof t[k] !== 'number') { d[k] = t[k]; continue; }
    const tau = TAU[k] || 2.5;
    d[k] += (t[k] - d[k]) * Math.min(dt / tau, 1);
  }
}

/* 制热结霜 / 自然化霜的慢过程 */
function frostDynamics(dt) {
  const f = App.flags;
  if (f.defrost) return;                       // 化霜时序自行处理
  if (App.internalMode === 'heating' && App.disp) {
    const te = App.disp.Te;
    if (te < -1 && App.inputs.tOut < 7) {
      f.frost = Math.min(1, f.frost + (-1 - te) * 0.0011 * dt);
    }
  }
  if (App.internalMode === 'cooling' || (App.disp && App.disp.Te > 4)) {
    f.frost = Math.max(0, f.frost - 0.02 * dt);   // 自然消融
  }
  // 自动化霜
  if (App.process === 'heating' && f.frost >= 0.95 && !App.seq) {
    UI.selectProcess('defrost');
  }
}

function loop(now) {
  requestAnimationFrame(loop);
  const dt = clamp((now - lastT) / 1000, 0, 0.05);
  lastT = now;

  // ---- 时序 ----
  let ov = {};
  if (App.seq) {
    const res = App.seq.tick(App, dt);
    ov = res.override;
    UI.showSeq(res);
    if (App.seq.done) {
      const back = App.internalMode;         // 化霜后回制热 / 回油后回原模式
      App.seq = null;
      App.process = back;
      App.flags.dripRate = 0;
      UI.paintButtons();
      UI.showSeq(null);
      document.getElementById('procDesc').textContent = window.T ? T(UI.PROC_DESC[back]) : UI.PROC_DESC[back];
    }
  }
  App.inputsEff = Object.assign({}, App.inputs, ov);

  // ---- 求解（8Hz）----
  solveAcc += dt;
  if (!App.paused && (solveAcc > 0.12 || !App.target)) {
    solveAcc = 0;
    App.target = solveCycle(App.inputsEff, App.internalMode, App.flags);
    if (!App.disp) App.disp = Object.assign({}, App.target);
  }

  if (!App.paused) { smooth(dt); frostDynamics(dt); }

  // ---- 渲染 ----
  Scene.update(dt, App.disp, App.inputsEff, {
    frost: App.flags.frost, defrost: App.flags.defrost, steam: App.flags.steam,
    dripRate: App.flags.dripRate, oil: App.flags.oil,
    internalMode: App.internalMode, process: App.process,
  });

  phAcc += dt;
  if (phAcc > 0.1) {
    PH.draw(REFRIGERANTS[App.inputs.ref], App.disp, phAcc);
    phAcc = 0;
  }
  uiAcc += dt;
  if (uiAcc > 0.2) {
    uiAcc = 0;
    UI.render();
  }
}

window.addEventListener('load', () => {
  UI.init(App);
  Scene.init();
  App.inputsEff = Object.assign({}, App.inputs);
  App.target = solveCycle(App.inputsEff, App.internalMode, App.flags);
  App.disp = Object.assign({}, App.target);
  requestAnimationFrame(t => { lastT = t; requestAnimationFrame(loop); });
});
