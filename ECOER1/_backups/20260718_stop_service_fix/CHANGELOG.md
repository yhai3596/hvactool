# Changelog

## 0.1.1 — 2026-07-18

- 修复「停止服务」按钮对非 Portal 亲生进程不显示的问题：现在只要 web 服务处于在线/启动中/端口占用状态，停止按钮就会显示。
- `ServiceManager.stop()` 支持回退到端口定位：当 Portal 不持有子进程时，通过项目 URL 解析端口，查找监听 PID 并优雅终止（超时时强制结束）。
- 新增 `Project.port` 属性，从项目 URL 中提取端口。
- 前端状态刷新不再依赖 `owned` 字段，直接按服务状态判断是否可停止。
- 补充相关单元测试，覆盖外部进程按端口停止、端口空闲时拒绝停止、URL 端口解析等场景。

## 0.1.0 — 2026-07-10

- 初始化 ECOER Portal MVP。
- 登记 AHRI、美国竞品分析、VOC 和 HVAC 工具站。
- 增加本地登录、健康检查、受控启动和运行记录设计。
- 增加端口占用保护：健康端点不匹配时拒绝重复启动。
- 完成 20 项单元测试、HTTP smoke、真实 VOC 分类 smoke 和浏览器登录流程验证。
- 修复 Windows PowerShell 5.1 中文提示乱码；启动脚本会在本地校验密码至少 8 位。
- Portal 配置错误改为简洁提示，不再输出 Python traceback。
- 新增 Console Event Exporter 和 Zoho 空调反馈独立看板。
- VOC 增加 Excel 上传、参数确认、后台分类状态和结果下载。
- 启动按钮增加提交中、启动中、在线、失败和端口占用反馈。
- AHRI 改用本地端口 8001，避开 8000 上的空调音频监控系统。
- 修复 Zoho 看板 `[bundle] error`：在二次打包容器解压 JavaScript 资源后，将其中的 React/ReactDOM 地址改为 Portal 本地资源，不再依赖 unpkg。
- AHRI、Console Event Exporter、美国竞品分析与 HVAC 页面增加返回 ECOER Portal 的链接。
- Zoho 独立看板由 Portal 注入固定返回入口，原始 HTML 保持不变。
- Zoho 白名单看板的专用 CSP 允许其 DC/Babel 模板所需的字符串编译；该权限不应用于 Portal 其他页面。
- 新增桌面快捷方式与一键启动脚本：自动启动 Portal、等待健康检查并打开默认浏览器；已运行时直接打开。
- 接入 `E:\AICoding\US\rebate-enablement-prototype`，使用本地端口 8090 提供受控启动、健康检查和打开入口。
- 项目卡片新增“停止服务”：仅对当前 Portal 实例通过 `Popen` 启动且仍持有句柄的在线/启动中服务显示；先 `terminate()`，超时后才 `kill()`，不按进程名或端口结束外部进程。
- 接入 `E:\AICoding\MES` 视觉质检 MVP，使用本地端口 8140 提供健康检查、受控启动和统一打开入口。
