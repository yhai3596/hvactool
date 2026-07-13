# HVAC 工具站 · 微信小程序(Phase 0 产物)

面向**国内暖通工程师**的小程序版规划落地起点。本目录当前包含已验证的 **CoolProp 云函数**;小程序前端(Phase 1:单位换算/冷媒物性/压焓计算/湿空气 4 个页面)待此云函数部署后开发。

## 为什么走云函数

小程序 `request` 域名必须 ICP 备案,而站点后端在境外;`wx.cloud.callFunction` 走微信通道**不需要任何域名配置**。计算引擎用 `coolprop-wasm`(CoolProp 7.2 的 WASM 封装)在云函数 Node 环境运行,已本地验证:

- 与线上 Python CoolProp 8.0 数值一致(压焓循环 h/qe/COP 对齐到小数点后 4 位)
- 12 种站点冷媒全部可用(R454B 经 `R454B.mix` 名称映射,与 server.py 同法)
- 湿空气 `HAPropsSI` 可用(湿球/露点/焓/含湿量与教科书值一致)
- 性能:实例常驻后单次循环计算 ~1.3ms;冷启动首算(混合物模型加载)~1.5s

## 部署步骤(需要你在微信开发者工具里操作)

1. **注册小程序**(个人主体即可):https://mp.weixin.qq.com → 获取 AppID
2. 下载微信开发者工具,新建项目(填 AppID),勾选/开通**云开发**(选按量付费基础环境,本用量在免费额度内),记下环境 ID
3. 项目里建 `cloudfunctions/` 目录,把本目录的 `cloudfunctions/coolprop/`(index.js + package.json)拷入
4. 开发者工具中右键 `cloudfunctions/coolprop` → **上传并部署:云端安装依赖**(会在云端 npm 安装 coolprop-wasm,~30MB 依赖,云函数上限内)
5. **改云函数配置(重要)**:云开发控制台 → 云函数 → coolprop → 版本与配置 → 超时时间改为 **20 秒**(默认 3 秒会被冷启动 + WASM 首载卡死),内存 256MB 够用
6. 控制台测试:云开发 → 云函数 → coolprop → 测试,入参:
   ```json
   { "action": "phcycle", "params": { "fluid": "R410A", "pe": 1085, "pc": 2735, "sh": 5, "sc": 5, "eff": 0.7 } }
   ```
   期望返回 `points['1'].h ≈ 430.02`、`qe ≈ 164.06`、`cop_c ≈ 4.48`(与网站压焓计算器默认工况一致)

## 云函数 API(与网站 /api/* 同形,单位一致:kPa / °C / kJ·kg⁻¹ IIR 基准)

| action | params | 对应网站接口 |
|---|---|---|
| `health` | — | /api/health |
| `fluidinfo` | fluid | /api/fluidinfo |
| `sat` | fluid, by:'T'\|'P', value | /api/sat |
| `sattable` | fluid, t1, t2, dt | /api/sattable |
| `dome` | fluid | /api/dome(压焓图饱和穹顶) |
| `phcycle` | fluid, pe, pc, sh, sc, eff[, mdot g/s] | /api/phcycle |
| `props` | fluid, pair('TP'/'PQ'/'PH'/'PS'/'TQ'…), v1, v2 | /api/props |
| `psychro` | 任意两个: tdb/twb/tdp/rh/w/h [+ p kPa] | /api/psychro |
| `watersat` | by:'T'\|'P', value | /api/watersat |

小程序端调用示例:

```js
wx.cloud.callFunction({
  name: 'coolprop',
  data: { action: 'sat', params: { fluid: 'R32', by: 'T', value: 5 } }
}).then(r => {
  if (r.result.error) { /* 提示 */ } else { /* r.result.p_dew … */ }
});
```

## 本地自测(可选,不影响部署)

```bash
cd cloudfunctions/coolprop && npm i && node test-local.cjs
```

## Phase 1 前端规划摘要(已获批,待云函数部署后开工)

- 4 个页面:单位换算(纯前端)/ 冷媒物性 / 压焓计算(canvas P-h 图,触控拖点)/ 湿空气
- 默认**中文 + 公制**(与网站相反,面向国内工程师);免登录
- sim 仿真不迁移(以演示视频页呈现);quiz 不迁移
- 冷启动体验:页面首次调用前 `health` 预热 + loading 提示
