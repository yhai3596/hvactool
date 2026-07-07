/* =====================================================
 * sequence.js —— 化霜 / 回油 过程时序状态机
 * 时序步骤覆盖压缩机频率、风机、EXV 等输入并驱动视觉标志，
 * 底层热力模型照常求解，因此测点与压焓图同步演变。
 * （时间为演示加速时标）
 * ===================================================== */

class Sequence {
  /**
   * @param type 'defrost' | 'oilreturn'
   * @param app  全局状态（inputs / flags / internalMode / target）
   */
  constructor(type, app) {
    this.type = type;
    this.i = 0;
    this.t = 0;
    this.done = false;
    // 记录进入时序前的运行参数，结束后恢复
    this.snap = { comp: app.inputs.comp, fanIn: app.inputs.fanIn, fanOut: app.inputs.fanOut, exv: app.inputs.exv };
    this.steps = type === 'defrost' ? this.defrostSteps(app) : this.oilSteps(app);
    this.total = this.steps.reduce((a, s) => a + s.dur, 0);
    if (this.steps[0].enter) this.steps[0].enter(app);
  }

  defrostSteps(app) {
    const sn = this.snap, ov = {};
    return [
      { name: '化霜判定', desc: '外盘温度低、结霜量大，满足进入化霜条件', dur: 2.2,
        tick: () => ({}) },
      { name: '压缩机降频', desc: '降低频率，为四通阀换向做准备', dur: 3,
        tick: k => ({ comp: lerp(sn.comp, 30, k) }) },
      { name: '内外风机停止', desc: '停内风机防吹冷风，停外风机集中热量化霜', dur: 1.5,
        tick: k => ({ comp: 30, fanIn: sn.fanIn * (1 - k), fanOut: sn.fanOut * (1 - k) }) },
      { name: '四通阀换向', desc: '切换为制冷循环，热气转向室外盘管', dur: 1.4,
        enter: a => { a.internalMode = 'cooling'; },
        tick: () => ({ comp: 30, fanIn: 0, fanOut: 0 }) },
      { name: '升频化霜', desc: '高温排气进入室外盘管，霜层开始融化', dur: 3.5,
        enter: a => { a.flags.defrost = true; a.flags.steam = true; },
        tick: k => ({ comp: lerp(30, 85, k), fanIn: 0, fanOut: 0 }) },
      { name: '化霜进行中', desc: '排气热量融化霜层，水滴落下、蒸汽升腾', dur: 24, dynamic: true,
        tick: (k, a, dt) => {
          a.flags.frost = Math.max(0, a.flags.frost - (a.target ? a.target.Qc : 4000) * 6.5 / 4e5 * dt);
          a.flags.dripRate = 1;
          if (a.flags.frost <= 0.01) this.skip();
          return { comp: 85, fanIn: 0, fanOut: 0 };
        } },
      { name: '化霜完成·降频', desc: '外盘已升温，霜化尽，准备换回制热', dur: 2.5,
        enter: a => { a.flags.defrost = false; a.flags.steam = false; a.flags.frost = 0; },
        tick: k => { return { comp: lerp(85, 30, k), fanIn: 0, fanOut: 0 }; } },
      { name: '四通阀换回', desc: '恢复制热循环方向', dur: 1.4,
        enter: a => { a.internalMode = 'heating'; a.flags.dripRate = 0.3; },
        tick: () => ({ comp: 30, fanIn: 0, fanOut: 0 }) },
      { name: '外风机恢复', desc: '内风机延迟启动（防冷风）', dur: 3,
        enter: a => { a.flags.dripRate = 0; },
        tick: k => ({ comp: 30, fanIn: 0, fanOut: sn.fanOut * k }) },
      { name: '升频恢复制热', desc: '内盘升温后内风机渐启，回到化霜前工况', dur: 3.5,
        tick: k => ({ comp: lerp(30, sn.comp, k), fanOut: sn.fanOut, fanIn: sn.fanIn * clamp((k - 0.4) / 0.6, 0, 1) }) },
    ];
  }

  oilSteps(app) {
    const sn = this.snap;
    return [
      { name: '回油判定', desc: '长时间低频运转，润滑油滞留管路与换热器', dur: 2,
        tick: () => ({}) },
      { name: '升频·EXV 开大', desc: '提高冷媒流速，稀释并携带润滑油', dur: 3,
        tick: k => ({ comp: lerp(sn.comp, 105, k), exv: lerp(sn.exv, 85, k) }) },
      { name: '回油运转', desc: '高流速气流将油膜带回压缩机（琥珀色油滴）', dur: 12,
        enter: a => { a.flags.oil = true; },
        tick: () => ({ comp: 105, exv: 85 }) },
      { name: '恢复原工况', desc: '回油完成，参数恢复', dur: 3,
        enter: a => { a.flags.oil = false; },
        tick: k => ({ comp: lerp(105, sn.comp, k), exv: lerp(85, sn.exv, k) }) },
    ];
  }

  skip() { this._skip = true; }

  /** 每帧推进；返回 {name, desc, progress, override} */
  tick(app, dt) {
    const st = this.steps[this.i];
    this.t += dt;
    const k = clamp(this.t / st.dur, 0, 1);
    const ov = st.tick ? (st.tick(k, app, dt) || {}) : {};

    if (this.t >= st.dur || this._skip) {
      this._skip = false;
      this.i++;
      this.t = 0;
      if (this.i >= this.steps.length) {
        this.done = true;
      } else if (this.steps[this.i].enter) {
        this.steps[this.i].enter(app);
      }
    }
    const elapsed = this.steps.slice(0, this.i).reduce((a, s) => a + s.dur, 0) + (this.done ? 0 : this.t);
    return { name: st.name, desc: st.desc, progress: clamp(elapsed / this.total, 0, 1), override: ov };
  }
}
