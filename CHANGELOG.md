# CHANGELOG

## 注册失败根因修复（CORS）+ 注册同源代理 — 2026-07-10

用户浏览器注册"成功率太低"的**真正根因**：Edge Function 的 CORS `Allow-Headers` 漏了 supabase-js 实际发送的 `x-client-info` 头 → 预检 OPTIONS 通过但真实 POST 被浏览器整体拦截（`net::ERR_FAILED`，请求根本不发出）。这解释了此前 Edge 日志"只有 OPTIONS 没有 POST"、以及"curl 全成功（无 CORS）、浏览器总失败"的矛盾。

- **CORS 修复**（`register-with-invite` v4 / `admin-api` v3）：`Allow-Headers` 补全 `x-client-info`，并**反射预检的 `Access-Control-Request-Headers`**，对 SDK 未来新增头免疫；浏览器实测由 3/3 失败 → 全部成功（有效码 726ms 注册成功）
- **注册同源代理**（双保险，兼治国内直连 supabase.co 不稳）：[server.py](server.py) 新增 `POST /api/register`，由新加坡服务器转发注册请求（连接级失败重试 3 次、HTTP 业务错误原样透传）；[login.html](login.html) 注册**优先走页面同源** `/api/register`（国内网络更稳），后端不可用（404/501/502/504）自动回退直连 Supabase（带重试）——本地静态预览/旧后端均兼容
- server.py 变更经 autopull 自动重启后端生效，无需服务器操作

## 管理后台 + 埋点统计 + 注册可靠性修复 — 2026-07-09

新增仅管理员可见的后台(用户/积分/邀请码/建号/设置)、全站行为埋点、可配置邀请说明,并修复注册间歇性失败。资源版本 `v=216 → v=217`。

- **数据库地基**(Supabase migration,纯新增不动存量):`admins` 表 + 播种 `yhai3596@outlook.com`;`is_admin()` 助手;`events` 埋点表(RLS 仅允许 INSERT、禁 SELECT,用户读不到他人行为);`app_settings` 站点配置(公开只读、写仅 service_role)
- **`admin-api` Edge Function**(服务端权威,双层门:`getUser` 验签 + `admins` 成员校验):动作 `list_users / adjust_credits / issue_invites / create_user / get_analytics / get_settings / update_settings`;配套 SECURITY DEFINER 助手 `admin_list_users / admin_issue_invites / admin_analytics`(已从 anon/authenticated 收回执行权,仅 service_role 可调,修复了默认授权残留漏洞)
- **后台前端** [admin.html](admin.html):管理员登录后导航显示 🛠 入口;四块——用户管理(改积分/补发码)、新增账号(免确认+1000积分+5码)、埋点看板(各页 PV/均停留/点击、热门点击、每日趋势)、站点设置(编辑邀请说明中英文);非管理员访问显示"仅管理员"
- **埋点** [js/lib/analytics.js](js/lib/analytics.js)(经 shell 全站注入):页面浏览 + 停留时长(visibilitychange 累计 + keepalive 上报)+ 点击(仅按钮/链接/`[data-track]`,**不采输入框值**);直插 events 表、`user_id` 恒 null 不含 PII
- **邀请说明可配置**:邀请码弹窗底部读 `app_settings.invite_note`,按当前语言显示,管理员后台可编辑中英文
- **注册可靠性修复**:定位到 `register-with-invite` 的 `createUser` 对 Supabase Edge/GoTrue 存在约 17% 瞬时失败(连接被丢弃/空响应,**干净回滚无孤儿残留**)。修复两层——后端 `createUser` 瞬时错误**重试 3 次**(重复邮箱不重试);前端 [login.html](login.html) 对**网络级失败自动重试 3 次**(带"正在重试…"提示),业务错误(邀请码无效等)立即返回不重试
- **安全底线**:所有后台写只经 service_role 函数;`config.js` 保持 `AUTH_REQUIRED=true`;前端隐藏入口仅观感,真正的门在服务端

## 全站中英双语 i18n + 语言切换器数据化 — 2026-07-09

全站彻底双语（中/EN），**默认英语 + 美制单位**，可在导航栏一键切换，切换后静态与动态文案（含 Canvas/SVG 绘图、结果表、横幅、tooltip、下拉选项）一次性重渲染。

- **i18n 引擎**（新增 [js/lib/i18n.js](js/lib/i18n.js)）：`DICT{en,zh}` 字典 + 全局 `window.T(key, vars)`（支持 `{var}` 占位替换）；`data-i18n` / `-ph`（placeholder）/ `-title`（tooltip）/ `-html`（富文本）四类属性；`I18N.apply(root)` 遍历渲染；`setLang(l)` 整页重载，默认 `en`（localStorage `hvac-lang`）；缺词三级回退（当前语言→英文→key）
- **单位默认美制**：`units.js` / `ui.js` 默认 `ip`
- **覆盖页面**：核心框架（导航/页脚/登录/首页）+ 系统仿真（含 p-h 图坐标轴与状态点、图钉参数栏）+ **7 个计算页**：压焓计算 phcalc、湿空气 psychro、冷媒物性 refprops、水力 hydronic、风管 duct、能耗电费 energy、单位换算 units
- **动态文案全覆盖**：结果卡片/状态点表/管段动态表（18 列）/EC(H)R 与 ESP 横幅/风管 SVG 示意图/焓湿图与压焓图 Canvas 标注/单位换算下拉（`value` 保留内部键、显示走翻译，换算逻辑不受影响）
- **后端中文映射**：refprops 相态（过热蒸气/过冷液体/两相/超临界）与两相区提示由前端映射翻译；后端 `server.py` 所有报错文案（未知冷媒/缺少参数/冷凝压力必须高于蒸发压力/超出饱和范围/介质仅支持…/计算失败等）由 [api.js](js/lib/api.js) 的 `trBackendMsg()` 统一翻译（精确串 + 带动态参数前缀串，动态尾部原样保留），全站 toast 一处翻译全覆盖（均避免改后端需重启）
- **语言切换器数据化**：新增语言注册表 `I18N.langs`；[shell.js](js/lib/shell.js) 从注册表生成切换器，**≤2 语言用分段按钮、≥3 自动切下拉**（`.lang-select` 样式）—— 以后加语言 = 注册表加一行 + DICT 加一个语言块，无需改 UI
- **资源版本**：全站 `v=215 → v=216`（i18n.js/shell.js/site.css/api.js 等共享文件改动，统一 cache-bust）

## 迁移至新加坡服务器 + 部署复盘手册 — 2026-07-08

因国内服务器未 ICP 备案被拦，迁移至境外，并沉淀完整运维文档。

- **迁移**：站点从国内 `119.29.105.107` 迁至腾讯云**新加坡** `43.156.58.154`（OpenCloudOS 9.6），DNS 切至新 IP，境外服务器免 ICP 备案
- **证书**：改为**服务器本地 acme.sh + GoDaddy DNS-01 自签自续**（境外能出境，不再需本机中转）
- **自动更新**：新增 `autopull-sg.sh` + `install-autopull.sh`，服务器 systemd timer `hvac-autopull.timer` **每分钟 `git pull`**，`git push` 即上线（因 SSH 被网络层封锁，弃用 SSH 中转）；仓库须保持 public
- **环境清理**：彻底卸载宝塔面板、禁用腾讯云云镜、禁用 sshd 密码登录
- **部署手册**：新增 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) —— 迁移全过程复盘 + 问题库(ICP/DNS/云镜/宝塔/防火墙/OpenCloudOS/证书/`pkill -f` 自杀坑等) + QA + 命令速查 + 排查决策树
- 部署脚本累积修复：nginx 被宝塔 dnf exclude（`--disableexcludes=all`）、官方源 openssl 依赖冲突（用系统源）、systemd 无 www-data 用户（root 跑）、git shallow clone 错误（去 `--depth`）

## 生产部署上线 — 2026-07-07

首次部署至生产服务器，双域名 HTTPS 对外访问。

- **上线地址**：https://hvac.geopro.cc 与 https://hvac.geotoday.net（同一站点，均强制 HTTPS）
- **服务器**：腾讯云 Ubuntu 24.04；站点置于 `/var/www/hvac`（`www-data`），`server.py` 由 systemd 单元 `hvac.service` 常驻监听 `127.0.0.1:8137`（venv + CoolProp 8.0.0）
- **反向代理**：nginx 各域名一个 `server` 块，80→301 跳转 HTTPS，443 反代到 8137；两域名各自证书
- **DNS**：GoDaddy 两条 `A` 记录 `hvac → 公网 IP`（根域名分别托管 Vercel / 其它，未改动）
- **证书**：Let's Encrypt（ECC，90 天）。因服务器出境网络受限、无法直连任何 ACME CA，改由**本机** acme.sh 签发/续期
- **自动续期**：本机 acme.sh + GoDaddy API（`dns_gd`）全自动 DNS-01 验证；`--install-cert --reloadcmd` 续期后自动 scp 证书到服务器并 reload nginx；Windows 计划任务 `acme-hvac-renew` 每日检查（`renew-hvac.bat`），临期自动续，2026-09-05 首次自动续期
- **首份 README 生产化**：加入在线地址、部署架构图、部署/更新流程、证书续期运维、API 表
- **一键部署脚本**：`deploy.sh`（Windows 双击 `deploy-hvac.bat`）——本机中转打包上传，智能判断：仅 `server.py` 变化才重启后端并等就绪，前端静态改动即时生效零中断；含服务器侧 HTTP 200 验证。因服务器出境受限无法自行 `git pull`，故由本机中转
- **配套文档**（`docs/`）：使用说明手册（9 页详解）+ 系统介绍 3 篇（知乎 / 公众号 / CSDN 发布版，介绍工具特点与国内服务器部署实战）

## v2.3 — 2026-07-07

仿真页测点扩充 + 公制/美制单位切换 + 布局优化（4 项）。

- **节流部件进出口状态**：新增「节流前温度（过冷液）/ 压力」「节流后温度（两相）/ 压力 / 干度」测点——节流前取冷凝出口过冷液(condOut, Pc)，节流后取蒸发露点两相态(Te, Pe)并按 h4 实时算干度
- **蒸发器进出口状态**：新增蒸发器进口/出口的温度与压力测点（进口=节流后，出口 evapOut/Ps），测点区加分组小标题「节流部件 · 蒸发器 进出口状态」
- **公制/美制单位切换**：头部加「公制/美制」开关（localStorage 记忆）。选美制时全页面换算——温度 °C→°F、压力 MPa→psi、温差 K→Δ°F、能力 kW→kBtu/h、流量 g/s→lb/h；覆盖 24 个测点卡、温度滑块读数、性能指标、场景标签、压焓图坐标轴（焓 kJ/kg→Btu/lb、压力→psi、等温线与角标）；内部计算保持 SI，变化高亮检测基于原始 SI 值不受换算影响
- **压焓图高度压缩**：P-h 图设计高度 440→330（约 -25%），系统性能与运行测点整体上移，减少滚动
- 实测：制冷额定下 节流前 40.9°C/2.82MPa 过冷液 → 节流后 11.0°C/1.12MPa 干度26% → 蒸发出 15.7°C 过热；切美制后 105.7°F/408psi、室温滑块 80.6°F、制冷量 27.2 kBtu/h，压焓图轴同步换算，切回公制正常
- 修复：单位按钮与冷媒按钮共用 .ref-btn 类，冷媒切换处理器加 [data-ref] 限定避免误触；资源版本号 v212→v213

## v2.2 — 2026-07-07

仿真页体验优化 + 图表清晰度 + 站点页脚（4 项）。

- **冷媒流动放慢约 60%**：粒子基速 `20+1800·mdot`(≤170) → `10+700·mdot`(≤62)，段速倍率整体下调（dis 2.6→1.9 等），状态更易观察；油滴同步放慢
- **相态区分强化**：tempColor 提高饱和度至 96% 并加宽映射（-25~110°C 蓝→红）；气态=大空心环(r3.8, 描边2.1)、液态=实心大点(r4.3)、两相=实心/空心交替小点，形状+大小+颜色三重区分
- **测点动态高亮**：数值变化中自动放大(16→21px)+变红(#ff5a67)+边框微光，稳定后自动恢复；用「相对变化率>0.25%/帧 且 绝对变化>0.03」双阈值 + 连续 3 帧稳定判定，过滤稳态求解器/渲染混叠的末位抖动（实测切参数 8~13 个测点亮起，13s 后全部归零）
- **图表清晰度（消除模糊）**：P-h 图(sim/phcalc)与焓湿图(psychro)全部改 hi-DPI 背板——按显示尺寸 × devicePixelRatio(封顶 2.5) 分配 canvas 位图、ctx.setTransform 缩放，逻辑坐标与鼠标命中同步换算；字号 9→11px、饱和穹顶/循环线加粗(1.6→2.2~2.6)、状态点标签加深色描边、网格与坐标文字提亮。实测 sim phCanvas 显示 429×465 → 背板 644×698(dpr1.5)
- **站点页脚**：shell.js 注入统一 `#siteFooter`（全页面）——「© 版权 Alan 所有 · 欢迎交流联系！关注 Alan 的公众号：Alan 的 AI 世界」
- 资源版本号 v=210 → v=212（强制刷新缓存）

## v2.1 — 2026-07-07

交互与国际化增强（5 项）。

- **独立双单位制**：新增 `js/lib/units.js` 单位引擎（26 类量纲），导航栏「输入/输出」两个独立的 公制(SI)/美制(IP) 开关，localStorage 记忆；覆盖冷媒物性、压焓计算、湿空气、水力（GPM/ft/psi/ftH₂O/100ft/ft/s）、风管（CFM/in/inH₂O/FPM）、能耗（Btu/h⇄kW、ft²⇄m²）6 个页面；切换输入制时输入框数值自动换算，切换输出制时结果、表头、图表坐标即时重绘；页面内部计算一律 SI
- **压焓图交互选点**：4 个状态点变为可拖拽手柄（点1/4 上下改蒸发压力、点2/3 上下改冷凝压力、点1 左右改过热度、点3 左右改过冷度），拖动时表单同步 + 本地近似预览，防抖 260ms 调 CoolProp 精算；悬停显示 (h, P, 饱和温度) 读数；/api/dome 增加露点温度数组
- **焓湿图**：湿空气页新增 psychrometric chart（RH 10~100% 曲线族 + 等焓线，前端 Arden Buck 近似绘线），计算后状态点落图带引导线与数据框；支持点击图面取点（干球+含湿量）自动经 CoolProp 精算
- **风管示意图**：校核后自动生成最不利风路直线展开 SVG——风机(标 ESP)→各管段（宽∝长度、高∝管径、圆/矩形造型区分、流向箭头）→末端风口；每段标注名称/尺寸/长度/ΣK/风量/流速/ΔP，超速段红色告警，顶部汇总条
- **三主题**：深色（默认）/ 浅色 / 高对比（纯黑+高亮），导航栏切换、localStorage 记忆；CSS 全变量化改造（--input-bg/--card-bg/--num/--ok/--tbl-line 等），Canvas/SVG 图表配色经 cssv() 跟随主题；sim.html 仿真场景锁定深色（data-fixed-theme），其主题选择器隐藏且不覆盖用户偏好
- **修复**：`const Units` 非 window 属性导致 shell 检测失败（补 window.Units）；静态文件加 Cache-Control: no-store + 全站资源 ?v=210 版本号，根治升级后浏览器用旧缓存（曾致 config.js 旧门禁误跳转）
- **验证**：压焓页输出美制 50.01°F/70.53 Btu/lb/2.52 lb/ft³ 换算准确；拖点2 → Pc 2735→3291 kPa 表单同步 psia 并精算；焓湿图点击取点 RH 54.3% 一致；水力输出美制 2.2 psi/42.4 ft/37.9 GPM 而输入列独立保持公制；风管示意图 12 项标注齐全；三主题切换 + 仿真页锁深色通过

## v2.0 — 2026-07-07

从单页仿真升级为多页工具站（Python CoolProp 后端 + Supabase 认证）。

- **架构**：`server.py`（stdlib http.server，静态托管 + 10 个 CoolProp JSON API，仅 127.0.0.1）；`start.bat` 一键启动；原仿真页原样迁移至 `sim.html`，`index.html` 改为门户
- **用户登录**：Supabase 项目 `hvac-tools`（免费档）邮箱注册/登录/退出；工具页门禁（`AUTH_REQUIRED` 可关）；CDN 加载失败自动降级离线模式不阻断使用
- **冷媒物性查询** refprops.html：12 种冷媒（R410A/R32/R454B/R134a/R290/R404A/R407C/R22/R1234yf/R600a/R717/R744）任意两参数状态点（TP/PQ/TQ/PH/PS）→ 焓/熵/密度/干度/比热/黏度/导热 + 相态与过热过冷度判定 + 饱和表生成；IIR 基准与物性表一致；混合冷媒报告泡露点与滑移；两相区 T+P 不独立自动提示
- **压焓在线计算器** phcalc.html：蒸发/冷凝压力或温度输入 → 理论单级循环（等熵效率修正），焓差/COP/排气温度/容积制冷量/能力，真实穹顶压焓图
- **湿空气** psychro.html：ASHRAE RP-1485（HAProps），6 种参数组合互算 + 海拔取压 + 水蒸气饱和 T↔P
- **水力计算** hydronic.html：水/30%/50% 乙二醇物性（CoolProp INCOMP），钢管/PPR/铜管内径库，Swamee-Jain 摩阻 + 管件 K 值，分段汇总 → 泵扬程/轴功率/EC(H)R-a 实际值与限值判定，流速超限标红
- **风管设计** duct.html：等摩阻法反求直径 + 标准圆管/矩形组合推荐（当量直径、长宽比≤4），分段静压累加 + 机外静压校核（裕量≥10% 判定）
- **能耗电费** energy.html：50 州 + DC 内置 CLH/HLH/居民电价（可改），按面积估算能力，SEER2/HSPF2 当量满负荷小时法测算全年 kWh 与电费，双机型对比 + 柱图
- **单位换算** units.html：12 类（长度/面积/体积/质量/温度/压力/体积流量/流速/功率冷量/能量/密度/传热系数）
- **修正**：R454B.mix 无法 Props1SI 查临界参数 → 文献常数兜底（Tc 78.1°C / Pc 5.267 MPa / M 62.6）
- **验证**：R410A 饱和点/R134a hf(0°C)=200.0 与手册一致；湿空气 35°C/40% → Twb 23.93°C；风管 3000 m³/h @1 Pa/m → D 416mm（教科书值）；登录门禁→注册→SQL 确认→登录→回跳全链路通过

## v1.0 — 2026-07-07

首版发布。

- 页面骨架 + 场景 SVG（室外机剖视 / 房屋剖面 / 管路网络 / 测点标签）
- 冷媒物性模块：R410A / R32 / R454B（Antoine 饱和压力两点拟合 + Watson 潜热 + IIR 基准焓）
- 简化稳态循环求解器：压缩机容积流量 × EXV 孔口流量平衡 → 过热度/过冷度；UA 换热平衡迭代 Te/Tc；多变压缩排温
- 冷媒粒子流动动画（相态形状 + 温度着色 + 流速∝流量，制冷/制热流向切换）
- 部件动画：压缩机振动/涡旋、四通阀换向、内外风机、EXV 开度弧圈
- 压焓图：饱和穹顶、等温线、循环 1-2-3-4、巡回光点
- 化霜时序状态机（判定→降频→停风机→换向→升频化霜→融霜→换回→防冷风恢复，约 27s）
- 回油时序（升频 105Hz + EXV 85%，油滴可视化，约 20s）
- 制热自动积霜（Te<-1 °C 且外温<7 °C）与霜满自动化霜
- 15 测点仪表 + 5 项性能指标 + 诊断提示 pills
- 环境效果：雪（外温<3 °C）、太阳（>24 °C）、霜层/冰凌/水滴/蒸汽

### 开发中修正记录

- 送风温度加盘管表面温度物理约束（制冷不低于 Te+1.5，制热不高于 Tc-1）
- 蒸发器有效焓差只计入 ≤8K 过热，修正"节流关小制冷量虚高"
- 排气焓改为冷凝压力侧从饱和气外推（×1.55 高压比热），COP 从 2.1 修正到 3.5 量级
- 外机 UA 900→1080、外侧风量热容 880→1150 W/K，冷凝温差更真实
- 测点标签避让风机/水印重叠；室内送风气流角度调整
