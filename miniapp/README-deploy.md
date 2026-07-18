# 微信云托管部署手册 · HVAC CoolProp 计算服务

> 方案背景：云函数跑 CoolProp WASM 已被验证**彻底不可行**（SCF runtime 不支持大 wasm 的
> bulk-memory/SIMD 特性，`WebAssembly.instantiate` rejected，256/512/1024MB 均复现）。
> 本方案改用**微信云托管（Docker 容器）直接跑现成 Python + CoolProp 8.0**，
> 小程序端 `wx.cloud.callContainer` 调用，**无需域名备案**。
> 旧目录 `cloudfunctions/coolprop/` 保留作记录，**已废弃，不要部署**。

## 部署包内容（`miniapp/container/`）

| 文件 | 作用 |
|---|---|
| `app.py` | 容器入口：监听 `0.0.0.0:80`，只暴露 GET 计算 API + `/health` 健康检查 |
| `server.py` | 与主站**完全一致**的已验证计算代码（app.py import 复用，未改动） |
| `requirements.txt` | `CoolProp==8.0.0`（与主站同版本，数值对齐） |
| `Dockerfile` | `python:3.11-slim`，腾讯 PyPI 镜像装依赖，`EXPOSE 80` |
| `container.config.json` | 服务配置参考值（端口 80 / 0.25核 / 0.5GB / 常驻1台 / 最大3台） |

**端口三处一致 = 80**：`app.py` 默认值 / Dockerfile `EXPOSE` / 控制台"端口"。

## GUI 操作步骤（你手动做）

### 第 1 步 · 开通云托管环境
1. 浏览器打开 https://cloud.weixin.qq.com/ ，用**小程序管理员微信**扫码登录，选对小程序账号。
2. 若未开通：点「开通」→ 新建环境，**付费方式选「按量付费」**（预付费环境开不了云托管）。
3. 记下**环境ID**（形如 `prod-xxxxxx`，后面小程序端要填）。
4. 新环境自带 **3 个月约 ¥400 免费额度**（CPU 720核·时 / 内存 1440GB·时 / 构建 600分钟 / 公网流量 5GB）。

### 第 2 步 · 新建服务
1. 左侧「服务管理」→「新建服务」。
2. 服务名称填：`hvac-coolprop`（若改名，小程序端 `X-WX-SERVICE` 要同步改）。
3. 是否开通公网访问：**不开**（只给小程序用，走微信内网协议更安全；调试想用 curl 时再临时开）。

### 第 3 步 · 部署版本（上传代码包方式）
1. 把 `E:\AICoding\HVAC\miniapp\container\` **里面的 5 个文件**打成 zip。
   ⚠ 关键：**Dockerfile 必须位于 zip 根目录**——进入 container 文件夹后全选 5 个文件 → 右键 →
   「压缩为 ZIP 文件」。不要在外层选中 container 文件夹整个压缩（那样 zip 根目录是
   `container/`，会报"Dockerfile 不合法"）。zip 总共几十 KB，远小于 2MiB 上限。
2. 服务详情页 →「发布版本」/「新建版本」：
   - 上传方式：**本地代码包（ZIP）**
   - Dockerfile 路径：`Dockerfile`（默认）
   - **端口：80**
   - 规格：CPU `0.25` 核 / 内存 `0.5` GB
   - 实例数：最小 `1`（常驻免冷启动，免费期内额度足够）/ 最大 `3`
   - 扩缩容条件：CPU 使用率 60%
   - 环境变量：不需要填
3. 提交后看「构建日志」：分「构建」「部署」两段，**约 3 分钟**。
   - 构建失败最常见原因：Dockerfile 不在 zip 根目录（回到 3.1 重打包）。
   - 部署卡住/健康检查失败：核对端口是否填 80。

### 第 4 步 · 验证服务
1. 服务详情页自带「测试」工具（或云托管控制台的服务调试页）：
   - 路径填 `/api/health`，方法 GET，发送。
   - 预期返回：`{"ok": true, "coolprop": "8.0.0", "fluids": ["R410A", ...]}`
2. 再测一条真实计算：路径 `/api/props?fluid=R410A&pair=PQ&v1=1000&v2=1`，
   预期返回含 `"T"`、`"h"`、`"phase"` 的 JSON（1000 kPa 饱和气，T ≈ 7.4°C）。
3. （可选交叉验证）与线上主站对数：
   `https://hvac.geopro.cc/api/props?fluid=R410A&pair=PQ&v1=1000&v2=1`
   两边数值应一致（同一份 server.py、同版本 CoolProp）。

### 第 5 步 · 小程序端接入
1. 确认小程序基础库 ≥ 2.23.0（开发者工具右上角「详情」→「本地设置」）。
2. `app.js` 里全局初始化一次：
   ```js
   App({ onLaunch() { wx.cloud.init() } })
   ```
3. 把 `miniapp/miniapp-callcontainer-example.js` 拷进小程序项目（如 `utils/api.js`），
   把文件顶部 `CLOUD_ENV` 换成第 1 步记下的环境ID；`SERVICE` 与第 2 步服务名一致。
4. 开发者工具控制台跑连通性自检：
   ```js
   const { callApi } = require('./utils/api.js')
   callApi('/api/health').then(console.log)
   ```
   看到 `{ok:true, coolprop:"8.0.0", ...}` 即打通。

### 常见报错速查
| 报错 | 原因 / 处理 |
|---|---|
| `-501000 Invalid host` | `config.env` 环境ID填错 |
| `-606004 Cannot find path` | path 拼错（注意要带 `/api/` 前缀） |
| `-601034 没有权限` | 小程序 AppID 与云托管环境**主体不同**，或未在该账号下开通 |
| `Cloud API isn't enabled` | 没先执行 `wx.cloud.init()` |
| 构建报 Dockerfile 不合法 | Dockerfile 不在 zip 根目录 |

## 费用参考（部署后可在控制台「资源用量」核对）

- 免费期（3 个月）：`minNum=1` 常驻 0.25核/0.5GB ≈ 月耗 180核·时 + 360GB·时，**在免费额度内**。
- 免费期后：常驻 ≈ **¥21/月**（CPU ¥9.9 + 内存 ¥11.5）+ 流量（纯 JSON，可忽略）。
  想更省：服务设置里把最小实例数改 0（代价 = 冷启动约数秒）。

## 后续（Phase 1 前端开工的前置条件）

- [ ] 云托管服务部署成功，`/api/health` 通过（第 4 步）
- [ ] 小程序端 `callApi('/api/health')` 打通（第 5 步）
- [ ] 记录环境ID 到本 README（环境ID：`＿＿＿＿＿＿`）
