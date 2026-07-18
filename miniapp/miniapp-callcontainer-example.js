/**
 * 微信云托管 · callContainer 调用封装 + 四页示例
 * ------------------------------------------------
 * 前置（app.js 里全局执行一次）：
 *   App({ onLaunch() { wx.cloud.init() } })
 * 要求：小程序基础库 ≥ 2.23.0；小程序与云托管环境同主体。
 * 无需域名备案：小程序 ↔ 云托管走微信专有协议（CallContainer）。
 */

// ↓↓ 部署完成后，把这两个值换成你控制台里的真实值 ↓↓
const CLOUD_ENV = '你的云托管环境ID';     // 云托管控制台 → 设置 → 环境ID（形如 prod-xxxxxx）
const SERVICE = 'hvac-coolprop';          // 云托管控制台 → 服务列表 → 服务名称

/**
 * 通用 GET 调用：callApi('/api/props', {fluid:'R410A', pair:'PQ', v1:1000, v2:1})
 * 返回 Promise<data>；HTTP 非 200 或后端 {error} 时 reject。
 */
function callApi(path, params = {}) {
  const qs = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== '')
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join('&');
  return wx.cloud.callContainer({
    config: { env: CLOUD_ENV },
    path: qs ? `${path}?${qs}` : path,
    method: 'GET',
    header: {
      'X-WX-SERVICE': SERVICE,
      // 免登录场景不带用户凭据，可提速
      'X-WX-EXCLUDE-CREDENTIALS': 'unionid, cloudbase-access-token, openid',
    },
  }).then((res) => {
    if (res.statusCode === 200) return res.data;
    const msg = (res.data && res.data.error) || `HTTP ${res.statusCode}`;
    throw new Error(msg);
  });
}

module.exports = { callApi };

/* ================= 四个页面的调用示例 =================

// 0) 连通性自检（部署后先跑这个）
callApi('/api/health').then(console.log);
// → { ok:true, coolprop:'8.0.0', fluids:[ 'R410A', ... ] }

// 1) 物性查询页（refprops）：R410A 在 1000 kPa 的饱和气
callApi('/api/props', { fluid: 'R410A', pair: 'PQ', v1: 1000, v2: 1 })
  .then((st) => console.log(st.T, st.h, st.s, st.phase));

// 1b) 饱和表：R32，-40..60°C 步长 10
callApi('/api/sattable', { fluid: 'R32', t1: -40, t2: 60, dt: 10 })
  .then((r) => console.log(r.rows.length));

// 2) 压焓循环页（phcalc）：蒸发 950 kPa / 冷凝 3200 kPa，过热 5K 过冷 5K
callApi('/api/phcycle', { fluid: 'R410A', pe: 950, pc: 3200, sh: 5, sc: 5, eff: 0.7 })
  .then((c) => console.log(c.cop_c, c.points));

// 2b) 饱和穹顶曲线（画图用）
callApi('/api/dome', { fluid: 'R410A' }).then((d) => console.log(d.p.length));

// 3) 湿空气页（psychro）：干球 26°C + 相对湿度 50%，标准大气压
callApi('/api/psychro', { tdb: 26, rh: 50 })
  .then((a) => console.log(a.twb, a.tdp, a.w, a.h));

// 4) 单位换算页：纯前端本地换算，不需要调后端。
//    若要顺带展示介质物性：
callApi('/api/liquid', { fluid: 'meg30', t: 7 }).then(console.log);

======================================================= */
