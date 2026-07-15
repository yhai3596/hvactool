# CHANGELOG

## 题库分片装载 + 构建校验流水线 + 本地错题本(Leitner-lite) — 2026-07-15

题库规模化的 Stage 1 基建(方案:题库 ≤300 题不上数据库,静态分片 + git 即内容管线)。资源版本 `v=227 → v=228`。

- **编写源/产物分离**:[js/quiz-bank.js](js/quiz-bank.js) 保持唯一编写源(带注释),**不再被页面加载**;新构建脚本 [tools/build-bank.mjs](tools/build-bank.mjs) 负责结构校验(mc 引用存在/答案索引/4 选项/id 唯一/题干查重/错误项必挂误区/孤儿误区告警)+ 生成 [bank/](bank/) 分片产物(manifest.json 含误区表与 qid 索引 + 每板块一个 json,单片 ≤13KB)。**维护约定:改 quiz-bank.js 后必跑 `node tools/build-bank.mjs`,产物一并提交**(服务器 git pull 部署)
- **异步分片装载**([js/quiz.js](js/quiz.js)):进页预热(manifest + 9 分片并行 fetch,本地实测 ~110ms),点「开始」通常零等待;拉取失败点击时给「题库加载失败」提示不白屏;沿用 `?v=N` 缓存约定(quiz.js 内 fetch URL 同步参与全站 sed bump),SW cache-first 天然兼容
- **本地错题本**(localStorage `hvac-quiz-hist`,匿名可用):每题记 答错/答对/连对次数;「曾答错且未连对 2 次」= 待复习 → 抽样时同板块内**优先出现**并在答题界面标「复习」徽标,连对 2 次自动出队(Leitner-lite);首屏显示「上次成绩 x/n · 待复习错题 m 道」;报告页显示「较上次 ▲/▼」
- **浏览器全流程验证**:新用户无进度行→首局写入 18 题记录→重测 11 道错题全部带徽标优先出现→两局全对后 due 16→12→0 严格出队→中英文案与 due=0 分支均正确;控制台零报错
- 测试期间顺带确认:SW cache-first 下改共享 js 不 bump 版本会拿旧文件(症状:功能"没生效")——本次把 `?v=N` 约定扩展到 quiz.js 内的 fetch URL,一次 sed 全站同步

## 考证小测扩容(40 题分层抽样)+ AI 深挖(DeepSeek,积分计费) — 2026-07-14

资源版本 `v=226 → v=227`。题库从 12 题扩容到 40 题、每次作答改为分层随机抽样，并上线登录用户可用的 LLM 深度解析。

- **题库扩容** [js/quiz-bank.js](js/quiz-bank.js)：12 → 40 题，新增 EPA 608 Type I（4 题）/ Type III（4 题）/ A2L 机房安全与检漏（4 题，接 IMC Ch.11 概念）/ 州执照机械规范方向 16 题（IMC Ch.4 通风、Ch.6 风管、Ch.7 燃烧空气、Ch.8 烟道排气各 4 题）；新增 14 个误区节点。机械规范题目仅原创复述行业通识概念与广泛采用的经验数值（燃烧空气开口 1in²/4000Btu、密闭空间 50ft³/1000Btu 判定等），**不摘录 IMC 条文原文**（版权规范，仅供事实核对用途）；各州实际采用版本/地方修订不同，页面已加免责说明
- **分层抽样出题** [js/quiz.js](js/quiz.js)：题库增长后不再每次全量出 40 题，改为按 9 个板块每板块抽 2 题（不足则全取）、共 18 题，整体再打乱顺序；每次开始/重测题目组合不同，控制单次时长在 ~7 分钟；报告页按主题正确率统计改为只统计本次抽样子集
- **AI 深度解析**（登录 + 积分门，非公开免登录功能）：
  - 新 Supabase Edge Function [quiz-ai](https://lnzepjubgtdclvmridxw.supabase.co/functions/v1/quiz-ai)：verify_jwt 手动校验（复用 admin-api 模式）→ 限流（10 分钟内 ≤8 次）→ 余额检查（<15 分拒绝）→ 调用 DeepSeek（`deepseek-chat`，需在 Supabase 项目 Secrets 配置 `DEEPSEEK_API_KEY`，未配置时优雅降级返回 `ai_not_configured` 而非报错）→ 成功后经 `apply_credit` RPC 扣 15 分并返回剩余积分；LLM 调用失败不扣费
  - 前端 [js/quiz.js](js/quiz.js) 每道错题反馈区新增「🤖 AI 深度解析」按钮：未登录态显示登录引导（不阻断答题流程）；同源代理优先（`/api/fn/quiz-ai`，[server.py](server.py) 白名单新增 `quiz-ai`）失败回退直连 Edge Function，与注册流程同一套双路径约定
  - 中英文案、积分不足/限流/服务未配置/网络错误四种失败态均有独立提示
- **待办**：需用户自行在 Supabase 后台 Project Settings → Edge Functions → Secrets 添加 `DEEPSEEK_API_KEY` 才能实际调用成功（未设置时功能优雅降级，不影响其余功能）
- **顺带发现（已转独立任务，未在本次改动中处理）**：`apply_credit` 函数 EXECUTE 权限当前授予 PUBLIC，任何持有站点公开 key 的人可越权调用刷改任意用户积分——数据库权限修复需用户另行确认执行

## PWA(可安装+离线壳)+ 小程序 CoolProp 云函数包 — 2026-07-13

小程序规划(面向国内暖通工程师)Phase 0 落地:现站 PWA 化 + 已验证的云函数计算引擎。资源版本 `v=225 → v=226`。

- **PWA**:[manifest.webmanifest](manifest.webmanifest)(standalone,压焓循环视觉图标 192/512/180)+ [sw.js](sw.js)(HTML network-first / 静态 cache-first(靠 ?v=N 失效)/ **/api 永不缓存** / 跨域不拦);[shell.js](js/lib/shell.js) 注册(https/localhost,失败静默);12 页加 `theme-color`/manifest/apple-touch-icon
  - **维护约定:全站 bump ?v=N 时必须同步改 sw.js 的 `SW_VERSION`**(旧缓存 activate 时清除)
  - 本地验证:SW activated 全站 scope、预缓存 12 项、/api 确认不入缓存;安卓 Chrome 将出"安装应用",iOS 用"添加到主屏幕"
- **小程序云函数包** [miniapp/](miniapp/README.md)(Phase 0 spike 通过,待用户在微信开发者工具部署):
  - [cloudfunctions/coolprop/index.js](miniapp/cloudfunctions/coolprop/index.js):9 个 action(health/fluidinfo/sat/sattable/dome/phcycle/props/psychro/watersat)等价迁移自 server.py,单位/IIR 基准/R454B `.mix` 映射一致
  - 引擎 `coolprop-wasm`(CoolProp 7.2 WASM,CJS 动态 import,实例常驻缓存):**与线上 Python 8.0 数值对齐到小数点后 4 位**(h1 430.0167/qe 164.0567/COP 4.4779);12 冷媒全可用;HAPropsSI 湿空气可用;热调用 ~1.3ms
  - `wx.cloud.callFunction` 走微信通道 → **绕开小程序 request 域名备案要求**(境外后端不合规问题就此解决);README 含部署步骤(云函数超时须 3s→20s)与 API 表
- 选型背景:小程序面向国内工程师(默认中文+公制,与网站相反);个人主体无 web-view,套壳不可行;sim SVG 场景不迁移;详见对话规划(裁剪 MVP:单位换算/物性/压焓/湿空气 4 页,免登录)

## 移动端收尾:sim 图例瘦身 + 图钉提示移出场景 + 控制台参与折叠 — 2026-07-13

二期遗留两小项清零。资源版本 `v=224 → v=225`(v224 已被同日考证小测占用,顺延防缓存不失效)。

- **图例不再遮场景**:图钉操作长提示(`lg_pin`)手机上从场景内图例移出 —— 图例瘦身为单行小盒(气/液/两相/颜色=温度,~271px),右上 Ambient 等参数框不再被遮;提示改为场景下方 `.scene-tip` 独立一行(复用现有词条,零新增 i18n;桌面 `display:none` 维持原样)
- **控制台可折叠**:[sim.html](sim.html) 控制台标题加 `data-fold-head` 标记;[shell.js](js/lib/shell.js) 栏目折叠头选择器扩展(`.panel-title` 或 `.ctl-head [data-fold-head]`),点击只绑标题文字(不误触 模式切换/Reset);折叠时保留头行(site.css 折叠规则补 `:not(.ctl-head)`);记忆 key 自动沿用(`hvac-fold-sim-ctl_title`)
- **CSS 教训(纯追加策略注意点)**:`.scene-tip` 桌面隐藏基础规则最初被追加在 media 块之后,同优先级"后者胜"把手机显示规则也盖掉 —— **追加的非 media 基础规则必须落在 media 块之前**;首轮 iframe 验证(`tipVisible:false`)抓出后已修
- **验证**:375px iframe —— 图例 271px/提示下移可见/点标题折叠(滑杆藏、头行留)/localStorage 记忆刷新保持/再点展开清除、页面零溢出;1200px 桌面 —— 提示隐藏、图例完整、无折叠箭头、滑杆常显

## 考证小测(需求验证 MVP):2026 A2L / EPA 608 错因诊断 — 2026-07-13

在现有工具站上挂一个面向美国 HVAC 技师的考证诊断小测,验证「考试模拟 + 学习工具」方向的真实需求(可行性分析见 [docs/EXAM-TOOL-FEASIBILITY.md](docs/EXAM-TOOL-FEASIBILITY.md))。资源版本 `v=223 → v=224`。

- **新页面 [quiz.html](quiz.html)**(公开、免登录):12 道仿真考题(5 A2L / 4 EPA 608 核心 / 3 条 2026 新规),选项乱序,点选即时判对错并给出一句话解析
- **错因诊断引擎**([js/quiz.js](js/quiz.js) + 题库 [js/quiz-bank.js](js/quiz-bank.js)):每个干扰项映射一个已知误区(16 个误区节点,含"把 A2L 当丙烷""以为 R-410A 不能再修""按 ODP/GWP 推断排放合法性"等),交卷后跨题聚类——同一误区命中 ≥2 题标「反复出现」;按主题出正确率条 + 个性化下一步建议;全部浏览器本地推断、无外呼
- **需求验证漏斗**:复用 events 匿名埋点,新增 `quiz_start / quiz_answer(题:选项:对错) / quiz_done(得分) / quiz_lead(留资) / quiz_fb(有用与否)`;[analytics.js](js/lib/analytics.js) 暴露 `window.hvacTrack` 供页面自定义事件
- **留资 CTA**:报告页「完整模拟器早期资格」邮箱收集(写入 events 表 `event_type=quiz_lead`,10s 超时、失败可重试、本地记忆已填邮箱)
- **入口**:导航「考证小测 / Exam Quiz」+ 首页第一张门户卡(NEW · EXAM PREP)
- **公开页白名单**:[shell.js](js/lib/shell.js) `isPublic` 加 `quiz`(登录墙会杀死验证流量;其余页面门禁不变)
- **i18n**:界面词条中英双语;题目与诊断内容为英文(与真实考试语言一致,页内已注明)
- **合规文案**:声明非 EPA 官方考试、无隶属关系;内容基准 2026-07 现行规则(AIM Act Technology Transitions / 2024 ERR 规则 / 40 CFR 82),并提示以 EPA 最新口径为准
- **验证**:Playwright 全流程——12 题作答→8/12 得分→2 个「反复出现」聚类(Q2·Q11 / Q5·Q8)→主题条 3/5·3/4·2/3→坏邮箱拦截→反馈→重测;375px 手机零横向溢出、零 JS 错误;中英双语截图抽查

## 移动端二期:压焓图/图钉触控拖拽 + 仿真场景横滑放大 — 2026-07-12

一期解决"能看",二期解决"能操作":两处纯 mouse 交互触屏化,仿真场景手机上放大 2 倍横滑看细节。资源版本 `v=222 → v=223`。

- **压焓图触控拖拽**([phcalc.html](phcalc.html)):四状态点拖拽 mouse 事件 → **Pointer Events**(鼠标/触屏/笔统一;`setPointerCapture` 防脱靶 + `pointercancel` 兜底);手机命中半径 14→26 逻辑单位(≈16px 物理,手指可按);拖拽重算防抖 260→400ms(移动网络少发请求,本地近似绘制不受影响);画布手机 `touch-action:none`(拖点不被页面滚动打断,图在页尾且可折叠)
- **仿真图钉触控**([scene.js](js/scene.js)):图钉参数框拖拽 pointer 化(capture 到目标元素);`.pin-box` 等加 `touch-action:none`(只影响触屏,桌面零副作用)
- **场景横滑放大**(用户选型 B):手机上场景 SVG 按 **760px** 渲染(约 2 倍),`#scenePanel` 横向滑动查看管路/阀件/测点细节,与页面纵向滚动不冲突;右缘渐隐暗示可滑;图例缩小(9px)少遮场景
- **桌面零变化**:事件语义等价(Pointer Events 对鼠标行为一致),命中半径/防抖桌面维持原值;场景/touch-action 规则均锁在移动 media 内
- **验证**:375px iframe 触屏 `PointerEvent` 模拟拖点 → 蒸发压力 157.37→247.05 输入框实时联动 ✓;1200px 桌面鼠标拖拽/hover 光标回归 ✓;场景手机可滑(760>343)且页面零溢出、桌面场景跟随容器无横滑 ✓

## 全站移动端适配(一期)+ 说明/栏目折叠 — 2026-07-12

手机端从"980px 桌面页缩小渲染"变为原生移动布局;PC 端零改动(移动规则全部锁在 `@media (max-width:899px)` 内,只追加不修改)。资源版本 `v=220 → v=222`。

- **viewport 补全**:9 个缺失页面补 `<meta name="viewport">`(此前仅 index/sim 有)
- **解锁桌面锁宽**:`body min-width:1280` / `.tool-page min-width:1100` 在 ≤899px 置零
- **导航手机形态**([shell.js](js/lib/shell.js)):导航链接包进 `.nav-links` 容器(桌面 `display:contents` 渲染完全不变),手机上独占一行**横滑 tab 条**,当前页自动滚入居中;控件 `flex-shrink:0` 防压缩裁字;取消 sticky 省屏
- **工具页单列化**:`.tool-layout`/仿真 `.layout` 单列,取消左右各自 sticky 独立滚动;门户卡片 4→2→1 列阶梯
- **输入触控优化**:输入框/下拉 16px(根治 iOS 聚焦自动放大)+ min-height 42px;主按钮 44px 且 btn-row 内均分;全局 `touch-action:manipulation` 去双击缩放延迟;滑杆热区 30px/滑块 18px
- **两处 `minmax(0,1fr)` 关键修复**:phcalc/sim 的 canvas 运行时按 dpr 重设 `width` 属性(如 946px),会把 `1fr` 网格轨道内在宽撑破视口 —— 布局轨道与表单列均显式压零
- **宽表格兜底**:`.data-table` 手机上自身横向滚动;结果卡 `minmax(130px,1fr)`
- **sim 一期兜底**:header/模式按钮换行、滑杆单列、性能 3 列/测点 2 列;场景 SVG 与压焓图本身按宽自适应(精修见二期)
- **说明折叠**:各页 `.note` 手机上自动收成「▸ 说明/Notes」一行(shell.js 注入,默认收起,点击展开;`fold_note` 中英词条)
- **栏目折叠 + 记忆**:`.panel-title` 手机上可点击收起该栏(右侧 ▾/▸ 指示,触控区加大);收起状态按 `hvac-fold-<页>-<栏目词条名>` 存 localStorage,下次访问保持;展开时补发 `resize` 兜底 canvas 重绘;桌面永远全显(折叠规则仅在移动 media 内,状态残留无害)
- **验证**:375px iframe 实测 10 页全部 `scrollWidth=375` 零横向溢出;折叠→刷新→记忆→展开→canvas 完好全链路通过;1440px 桌面截图回归与线上一致;三主题抽查正常

## 全站主题体验 + 性能体检 — 2026-07-12

仿真页启用三主题、高对比换为米黄"纸感"、场景/压焓图全面主题化，并做全站性能体检修复两处高消耗设计。资源版本 `v=218 → v=220`。

- **仿真页启用主题切换**：去掉 `data-fixed-theme` 固定深色；深/浅/米黄三主题可切
- **场景全面主题化（零 HTML/JS 改动）**：场景 SVG ~90 处内联颜色经 CSS `[fill=]/[stroke=]/[stop-color=]` 属性选择器接管 → `--sc-*` 变量组（深色=原值逐像素一致；浅色/米黄=「白天场景」：晴空/暖米天空、浅色金属机组、白底参数框）；scene.js 动态元素（雪/滴水/蒸汽）同规则命中
- **压焓图主题化 + 静态层缓存**：[phdiagram.js](js/phdiagram.js) 13 处颜色 → `--ph-*` 主题调色板（缓存，切主题才重读）；网格/等温线/饱和穹顶缓存为离屏静态层，仅切 冷媒/单位/主题/尺寸 时重建 —— 单次绘制 0.10ms → **0.022ms**
- **高对比 → 米黄「纸感」主题**：纯黑+荧光整套换为米黄底/暖白面板/深青强调/暖棕文字；内部键沿用 `contrast`（已存偏好自动迁移）；按钮标签中英同步（米黄/Cream）
- **浅底修复**：ghost（透明底）按钮排除出「浅色主题白字」规则 —— 修复浅色/米黄下手动模式「暂停/清除」等按钮文字隐形（悬停才现）；标题渐变浅底换主题深色；性能条/测点四色数值浅底用深色版
- **性能体检**（实测：仿真页 JS 总负载 ≈ 1.3% 单核）：
  - 移除 sim 页 `background-attachment: fixed`（Windows 滚动整页背景重绘的经典卡顿源），渐变背景移入 `position:fixed` 合成层，视觉等同
  - 排查确认健康：求解 8Hz/压焓 10Hz/仪表 5Hz 分层、无 setInterval 轮询、常驻动画仅 2 个 opacity 级、SVG 滤镜 2 处、动态粒子无泄漏
- **api.js 防御**：后端不可用返回 HTML 错误页时不再报晦涩的 `Unexpected token '<'`，改为友好提示「无法连接本地计算服务…」（中英）
- **导航移除「← ECOER Portal」链接**（连本地也不再显示）

## 导航加 ECOER Portal 回链（仅本地显示）— 2026-07-10

- [shell.js](js/lib/shell.js)：导航栏新增「← ECOER Portal」链接（`http://127.0.0.1:8787/`），供本地开发在工具站与 ECOER Portal 间跳转
- **仅本地显示**：`location.hostname` 为 `localhost`/`127.0.0.1` 时才渲染；线上 `hvac.geopro.cc` / `hvac.geotoday.net` 自动隐藏（避免访客点到指向自己电脑的坏链接）
- 资源版本 `shell.js v=217 → v=218`

## 后台调用同源代理（修复 admin 页不可用）— 2026-07-10

后台页所有动作报 `Failed to send a request to the Edge Function` —— 浏览器直连 supabase.co 的 functions 调用被拦（与注册同类：CORS 修复前的缓存页面 / 国内网络对 functions 端点丢包）。治本：后台调用也走同源代理。

- [server.py](server.py)：注册专用代理升级为**白名单函数代理** `POST /api/fn/<name>`（仅 `register-with-invite` / `admin-api`），**Authorization 透传**（后台需管理员 JWT）；`/api/register` 保留为旧别名
- [admin.html](admin.html)：`adminApi()` 双路径 —— 首选同源 `/api/fn/admin-api`（同源无 CORS 预检），后端不可用（404/501/502/504）自动回退直连；业务/权限错误直接上抛不回退
- 实测：无 JWT 经代理调用 → `401 unauthorized` 原样透传（链路通、服务端鉴权门完好）；浏览器回退路径 CORS 穿透正常

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
