# HVAC 工具站

> 暖通工程计算与仿真工具集：变频热泵动态仿真 + CoolProp 高精度物性 + 湿空气 / 水力 / 风管 / 能耗 / 单位换算，含 Supabase 用户登录。

**在线访问**（生产环境，HTTPS）：

- 🔗 https://hvac.geopro.cc
- 🔗 https://hvac.geotoday.net

两个域名指向同一站点，均已启用 Let's Encrypt 证书并强制 HTTPS。

---

## 目录

- [功能一览](#功能一览)
- [v2.3 交互特性](#v23-交互特性)
- [技术栈](#技术栈)
- [本地开发运行](#本地开发运行)
- [生产部署架构](#生产部署架构)
- [部署 / 更新流程](#部署--更新流程)
- [HTTPS 证书与自动续期](#https-证书与自动续期)
- [物性 API](#物性-api)
- [账号系统](#账号系统)
- [目录结构](#目录结构)
- [注意与限制](#注意与限制)
- [更新日志](#更新日志)

---

## 功能一览

| 页面 | 功能 | 计算引擎 |
|---|---|---|
| `index.html` | 门户 + 服务状态 | — |
| `sim.html` | 变频一拖一动态仿真（制冷/制热/化霜/回油、冷媒粒子、压焓图、节流与蒸发器进出口测点、9 参数、公制/美制切换） | 前端简化模型 |
| `refprops.html` | 12 种冷媒任意状态点 焓/熵/密度/干度 + 饱和表 + 滑移 | CoolProp 8 |
| `phcalc.html` | 蒸发/冷凝压力（或温度）→ 焓差、COP、排气温度、能力，真实压焓图 | CoolProp 8 |
| `psychro.html` | 干球/湿球/RH/露点/含湿量/焓 任意两参数互算 + 水蒸气饱和换算 | CoolProp HAProps (ASHRAE RP-1485) |
| `hydronic.html` | 分段管路阻力（Colebrook）、泵扬程、EC(H)R 输送能效判定 | 前端 + CoolProp 水/乙二醇物性 |
| `duct.html` | 等摩阻法风管选型（圆/矩形）、系统静压累加、机外静压校核 | 前端 |
| `energy.html` | 北美各州 SEER2/HSPF2 全年耗电与电费测算、双机型对比 | 前端（州级 CLH/HLH/电价内置可改） |
| `units.html` | 美制/公制 12 类单位换算 | 前端 |
| `quiz.html` | 2026 A2L / EPA 608 考证诊断小测（12 题即时判分 + 错因诊断 + 留资 CTA，公开免登录，需求验证 MVP） | 前端 |

冷媒清单：R410A · R32 · R454B · R134a · R290 · R404A · R407C · R22 · R1234yf · R600a · R717(氨) · R744(CO₂)。
R454B 采用 CoolProp 预定义混合物（临界参数取 Opteon XL41 文献值），混合冷媒两相区报告泡露点与温度滑移。

## v2.3 交互特性

- **节流部件 · 蒸发器进出口状态**：仿真页新增「节流前温度（过冷液）/压力」「节流后温度（两相）/压力/干度」「蒸发器进口/出口 温度/压力」测点分组
- **公制/美制单位切换**：仿真页头部「公制/美制」开关（localStorage 记忆），全页面换算——温度 °C→°F、压力 MPa→psi、温差 K→Δ°F、能力 kW→kBtu/h、流量 g/s→lb/h（含压焓图坐标轴）；内部计算保持 SI
- **双单位制（工具页）**：导航栏「输入 / 输出」各自独立选 公制(SI) 或 美制(IP)，全站计算页生效并记忆
- **压焓图可拖拽**：拖动状态点直接改蒸发/冷凝压力、过热/过冷度，松手自动 CoolProp 精算；悬停读 (h, P, Tsat)
- **焓湿图**：湿空气页含 RH 曲线族 + 等焓线图，可点击图面取点计算
- **三主题**：深色 / 浅色 / 高对比，导航栏切换（仿真页场景固定深色）

## 技术栈

- **前端**：原生 HTML / CSS / JavaScript（无框架、无构建），Canvas/SVG 绘图，`supabase-js`（CDN）
- **后端**：Python 3 标准库 `http.server`（`server.py`），静态托管 + CoolProp JSON API
- **物性引擎**：[CoolProp](http://www.coolprop.org/) 8.x（`PropsSI` / `HAPropsSI`）
- **认证**：Supabase（邮箱 + 密码，publishable key 前端直连）
- **生产**：Ubuntu 24.04 + nginx 反向代理 + systemd + Let's Encrypt

## 本地开发运行

```bash
pip install coolprop          # 仅需一次
python server.py              # 启动 http://127.0.0.1:8137
# Windows 亦可双击 start.bat
```

首次使用请在页面右上角注册账号（邮箱 + 密码，需点击确认邮件中的链接完成验证）。
如只想本地单机使用、不要登录门禁，把 `js/lib/config.js` 中 `AUTH_REQUIRED` 改为 `false`。

## 生产部署架构

> 📖 **完整部署复盘与运维手册见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** —— 含迁移全过程、所有踩过的坑(ICP/云镜/宝塔/防火墙/pkill 等)、QA、命令速查、排查决策树。运维前请先读它。
>
> ⚠️ 现网生产已迁至**新加坡服务器**（OpenCloudOS 9，免 ICP），代码更新走**服务器每分钟自动 `git pull`**（`git push` 即上线）。下方部分内容为早期国内部署的通用说明，**权威信息以 DEPLOYMENT.md 为准**。

```
                 用户浏览器 (HTTPS)
                        │
         hvac.geopro.cc / hvac.geotoday.net
                        │  :443 (Let's Encrypt)
                        ▼
   ┌──────────────────────────────────────────┐
   │  Ubuntu 24.04  (腾讯云 CVM)                │
   │                                            │
   │  nginx  ─ 80 → 301 跳转 https              │
   │         └ 443 ssl → 反向代理               │
   │                    http://127.0.0.1:8137   │
   │                          │                 │
   │  systemd: hvac.service                     │
   │    venv/bin/python server.py               │
   │    (静态托管 + CoolProp API, 仅本机监听)   │
   └──────────────────────────────────────────┘
```

- 站点代码位于服务器 `/var/www/hvac`，以 `www-data` 运行
- `server.py` 由 systemd 单元 `hvac.service` 常驻，监听 `127.0.0.1:8137`（不直接对外）
- nginx 终止 TLS 并反代到 8137；`hvac.geopro.cc` 与 `hvac.geotoday.net` 各一 `server` 块、各自证书
- DNS 在 GoDaddy：两域名各一条 `A` 记录 `hvac → 服务器公网 IP`（根域名分别托管于 Vercel / 其它，未改动）

## 部署 / 更新流程

**一键部署（推荐）**：改完代码后运行 `deploy.sh`（Windows 可双击 `deploy-hvac.bat`）——自动打包 → 上传 → 按需重启后端 → 服务器侧线上验证。仅当 `server.py` 变化时才重启后端；前端为静态实时托管，改动即时生效、**零中断**。

```bash
bash deploy.sh
```

> 由于服务器出境网络受限、无法自行 `git pull`，部署由本机中转（本机能连 GitHub 也能 SSH 服务器）。

<details><summary>手动分步（等价原理）</summary>

在本机打包并推送到服务器：

```bash
# 1. 打包（排除本地环境/缓存）
tar --exclude='./.git' --exclude='./.claude' --exclude='./__pycache__' \
    -czf /tmp/hvac.tgz -C /path/to/HVAC .

# 2. 上传并解压
scp /tmp/hvac.tgz root@<server>:/tmp/
ssh root@<server> 'tar xzf /tmp/hvac.tgz -C /var/www/hvac && chown -R www-data:www-data /var/www/hvac'

# 3. 重启后端服务
ssh root@<server> 'systemctl restart hvac'
```

</details>

> 前端为纯静态，改动 HTML/CSS/JS 后浏览器需刷新缓存——站点资源均带 `?v=NNN` 版本号，升级时递增即可（当前 v213）。

## HTTPS 证书与自动续期

> ⚠️ 该服务器出境网络受限，**无法在服务器上直接连接任何 ACME CA 签发证书**。因此证书统一在**能出境的本机**用 [acme.sh](https://github.com/acmesh-official/acme.sh) 签发，再自动推送到服务器。

- **签发/续期**：本机 acme.sh + **GoDaddy API（`dns_gd`）** 自动完成 DNS-01 验证（自动加/删 `_acme-challenge` TXT，无需手动）
- **自动部署钩子**：每个域名 `--install-cert --reloadcmd` 已绑定——续期成功后自动 `scp` 新证书到服务器 `/etc/ssl/hvac/` 并 `systemctl reload nginx`
- **自动续期计划**：Windows 计划任务 `acme-hvac-renew` 每天检查（`renew-hvac.bat` → `acme.sh --cron`），证书临近到期（约提前 30 天）自动续
- **手动立即续期**：双击 `renew-hvac.bat`
- 证书类型 ECC，Let's Encrypt，有效期 90 天

## 物性 API

`server.py` 提供的 JSON 接口（生产环境经 nginx 代理，本地为 `http://127.0.0.1:8137`）：

| 端点 | 用途 |
|---|---|
| `/api/health` | 健康检查（返回 CoolProp 版本与冷媒清单） |
| `/api/props` | 任意状态点物性（焓/熵/密度/干度/比热/黏度/导热…） |
| `/api/sat` `/api/sattable` | 饱和点 / 饱和表 |
| `/api/dome` `/api/phcycle` | 压焓图饱和穹顶 / 理论循环 |
| `/api/psychro` `/api/watersat` | 湿空气 / 水蒸气饱和 |
| `/api/liquid` | 水 / 30%·50% 乙二醇输送物性 |

冷媒物性统一采用 **IIR 基准**（0°C 饱和液 h=200 kJ/kg，s=1.0 kJ/kg·K），与常用物性表册一致。

## 账号系统与后台

- **邀请码注册制**：注册需有效邀请码，经 Edge Function `register-with-invite` 建号（免邮件确认，注册即可登录），每人注册后获 5 个邀请码
- **积分**：初始 1000，每日按日历天惰性扣 30，每成功邀请 1 人 +300；`credit_log` 记流水，顶栏 ⚡ 显示
- **中英双语**：全站可切换（默认英语 + 美制），`js/lib/i18n.js` 字典 + 全局 `window.T()` + `data-i18n`
- **管理后台** `admin.html`（仅管理员 `is_admin()` 显示入口）：用户管理（改积分 / 补发码）、新增账号、埋点看板、站点设置（可配邀请说明中英文）。所有后台写经 Edge Function `admin-api`，服务端 `getUser` 验签 + `admins` 成员校验才放行——**前端隐藏仅观感，真正的门在服务端**
- **埋点** `js/lib/analytics.js`（全站注入）：页面浏览 / 停留时长 / 点击（仅按钮·链接，不采输入框值），直插 `events` 表（RLS 仅允许 INSERT，用户读不到他人行为）
- **注册 / 后台可靠性**：浏览器直连 supabase.co 的 Edge Function 在国内网络不稳，前端优先走**同源代理** `POST /api/fn/<name>`（server.py 转发到 Supabase），失败自动回退直连
- 前端仅持有 **publishable key**（设计上可公开）；密码由 Supabase 加密托管；`supabase-js` CDN 加载失败自动降级离线模式，不阻断工具使用

## 目录结构

```
HVAC/
├── index.html  sim.html  refprops.html  phcalc.html
├── psychro.html  hydronic.html  duct.html  energy.html
├── units.html  login.html  admin.html   管理后台（仅管理员）
├── server.py               Python 后端：静态托管 + CoolProp JSON API + 注册/后台同源代理
├── start.bat               Windows 本地一键启动
├── css/
│   ├── style.css           仿真页样式
│   └── site.css            工具站共享样式
├── js/
│   ├── lib/config.js       Supabase 地址/公开钥、导航、门禁开关
│   ├── lib/i18n.js         中英双语字典 + window.T()
│   ├── lib/shell.js        导航注入 + 登录门禁 + 页脚 + 语言/主题切换
│   ├── lib/analytics.js    全站埋点（浏览/停留/点击）
│   ├── lib/api.js          fetch 封装 + toast + 后端报错翻译
│   ├── lib/units.js        双单位制引擎
│   └── refprops/model/scene/phdiagram/sequence/ui/main.js   仿真引擎
├── README.md   CHANGELOG.md
```

## 注意与限制

- 物性 API 后端仅监听 `127.0.0.1`，不直接对外网开放（生产经 nginx 代理）
- `energy.html` 的各州 CLH/HLH/电价为 ENERGY STAR / EIA 量级的内置参考值，请按当地实际修改；极寒地区热泵电辅热未计入
- 水力页 EC(H)R 限值系数 A/B/α 默认值请按 GB 50189-2015 具体分档核对
- `sim.html` 仿真为教学定性模型；`refprops` / `phcalc` / `psychro` 为 CoolProp 高精度计算

## 文档

- 📖 [使用说明](docs/使用说明.md) — 9 个页面的详细操作手册（输入 / 输出 / 步骤 / 注意）
- 📣 系统介绍（对外发布版）：[知乎版](docs/介绍-知乎.md) · [公众号版](docs/介绍-公众号.md) · [CSDN 版](docs/介绍-CSDN.md)

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

---

© 版权 Alan 所有 · 欢迎交流联系！关注 Alan 的公众号：**Alan 的 AI 世界**
