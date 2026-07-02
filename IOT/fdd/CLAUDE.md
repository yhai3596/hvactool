# CLAUDE.md — FDD 机队故障诊断系统

北美住宅变频热泵外机(R410A,3 系列 × 2 型号,208/230V 单相,内外机无通讯 + 第三方内机)机队 FDD:物理残差 + 统计漂移 + 可解释树模型。全流程本地运行。规格文档:《FDD 项目方案 v1.1》《FDD 系统开发文档 v1.0》(docs/,自 E:\AICoding\IOT\PRD 复制的副本;口径冲突时以本 CLAUDE.md 为权威版本)。

## 铁律(每次编码必须遵守,违反任何一条即为缺陷)

1. **压力**:Lp/Hp 为密封式表压(bar)。绝压 = 表压 + 1.013,全机队固定。**禁止**对压力换算做海拔修正;海拔只允许作为风侧空气密度协变量出现。
2. **过冷度**:sc_phys = tc_sat − Tl。**必须剥掉控制器公式里的 −1**(那是显示偏置,不是物理量)。任何特征/残差出现 `− 1` 项即为回归缺陷。
3. **制热模式 Sh 被 EEV 伺服钉在 ≈0 K(实测 0.02±0.3),禁止把 Sh 作为制热泄漏的主证据**。制热泄漏载体 = exv_resid + sc_resid + capacity_resid;Sh 仅在 EEV 饱和(开度触顶)后作为晚期指标启用。制冷模式 Sh 正常使用。
4. **能效/COP/容量类特征禁用 PowerIn**(内含曲轴加热带),用 PowerComp(+风机)。PowerIn − PowerComp − 风机 = 寄生功率特征 p_parasitic。
5. **电流类跨机特征必须以 V1 为协变量**(机队 208/230V 双峰,187–256V)。
6. **稳态定义**:CompState=1 ∧ 段内 >5 min ∧ CompRps 与 Exv 的 2 min 滚动标准差双低阈。**CompState=2 全段剔除**(含真化霜与周期低频程序);AcState ∉ {4,5} 不入运行分析。
7. **St = 四通阀状态**(1 制热位,0 化霜/制冷位),是化霜边界的地面真值。化霜判据以 St 为主,Th 尖峰只做校验。
8. **Tcs = 动态目标冷凝温度**(控制器设定,样本内 38/39/40/45),不是实测温度。tcs_gap = tc_sat − Tcs 是"学习漂移 vs 故障漂移"的判别量:目标变 = 控制决策;追不上目标或追上但 Rps/Exv 代价抬升 = 能力短缺。
9. **TH 语义随模式翻转**:制热 = 室外蒸发器盘管中部(结霜/蒸发通道),制冷 = 冷凝器中部。代码中禁止硬编码"condenser"语义。
10. **制热 Sc 含安装管路温降偏置**(Tl 在室外机液管,管长因安装而异):制热工况只允许逐机漂移比较,禁止跨机绝对值比较。
11. 禁止修改 tests/ 目录下的任何文件。若认为某条测试或铁律有误,停止工作、输出理由,等待人工裁决。
12. tests/ 的变更仅允许誊写本 Project 起草并经人工授权的测试原文,每次授权限当次指令所列文件;agent 不得自拟测试或改动断言/阈值。

## 锁定发现

- 固件饱和温度查表相对 CoolProp 存在系统性压力尺度偏差,高低压两侧均现(Sh 侧稳态约 0.58K,Sc 侧使物理偏移由预期 1.0 变为约 1.84)。同源性:低压侧与高压侧的 sh_phys−Sh、sc_phys−(Sc+1) 两个残差与各自饱和温度的 spearman 同为负(−0.75 / −0.66),方向交叉验证一致,支持单一固件压力尺度偏差同时解释两侧;−2% 具体数值为拟合估计,待厂商确认。此为继 −1 过冷显示偏置、密封表压之后第三个系统性误差源,影响所有依赖饱和温度的特征。残差分析一律用 sh_phys/sc_phys 物理口径,禁用固件上报 Sh/Sc。

## 验证法则

- 训练/验证切分**只允许 leave-units-out(按设备)**,禁止按行随机切分。
- 指标按**事件级**计算(Yuill-Braun 五分类:正确/漏检/误报/误诊/无响应),禁止按 10 秒行级算准确率。
- 对照双基线:CoolantLackLimit 提前量、Title 24 目标过冷度法。
- sh_phys/sc_phys 恒为 CoolProp 物理口径,任何"复现固件"逻辑只能存在于独立函数,禁止参与物理量定义或验收断言。
- 测试断言不达标时报告实测值并停止,禁止通过改口径、改被测量方向、造事后机制解释使其达标——未解释/不达标是合法中间状态。
- 不对已推送提交做 rebase/force-push,历史修正用 revert 追加。

## 标签卫生

- 标签可信度分级 L0 现象文本 / L1 故障码 / L2 维修动作 / L3 工程师根因 / L4 修后数据恢复验证。
- **训练集只准入 L3/L4**(或 sn_status=valid 且复核 confirmed);`valid_multiple_candidates` 未解歧**禁止**入训练,只入候选池。
- 日期合法窗口 [2018-01-01, 今日],越界回退 Created Time 并打标(已知 195 条 Failure Date 垃圾)。

## 数据安全(硬禁令)

- 任何输出/共享文件**禁止**包含明文 SN(normalized_sn 列必须删除),只留 hash_sn(HMAC,盐外部保管)。
- 含客户 PII 的 Zoho 原始文件不得进入本仓库工作区;本仓库只接触脱敏产物与遥测。
- 管线代码禁止调用任何外部 API(本地化是安全审批承诺,也是架构约束)。
- 地理位置只允许"气候区 + 海拔带"粒度。

## 契约摘要(src/fdd/contracts/)

- **C1 遥测**(48 列已锁定):摄取时物化派生列 lp_abs/hp_abs/te_sat/tc_sat(CoolProp R410A)/sc_phys/sh_phys/mode/reversing(St)/p_parasitic/comp_slip/fan_slip/tcs_gap。时间戳 UTC + tz 列。
- **C2 标签**:labels(hash_sn, fault_family, event_date, date_source, confidence, sn_status, label_tier L0–L4, review_state)。
- **C3 平台事件(桩)**:events(hash_sn, ts_utc, fault_code, protection_bit, severity, cleared_ts, model, telemetry_first/last_date, fw_version)。实际 schema 到达后只改字段映射层。
- **C4 实验室/产线**:结构同 C1 + test_condition / station 标签列;到货第一步跑 schema diff。
- **C5 输出五件套**:{hash_sn, 时间窗, 故障假设, 证据[], 反证[], 置信度, 现场核查清单[], 版本}。出域物仅限聚合统计与模型。

## 模块地图与 M0 目标

| 模块 | 文件 | 里程碑 | DoD(见 tests/) |
|---|---|---|---|
| M-CONV 物理转换 | src/fdd/conv.py | **M0** | 样本上 sh_phys−上报Sh 的 P95 ≤0.15K(St=0 段豁免);sc_phys−上报Sc ≡ 1.0±0.1 |
| M-SEG 分段/稳态 | src/fdd/seg.py | **M0** | 样本 2 段真化霜(St 判据)/5 段 special 全捕获;CompState=2 内稳态行 = 0 |
| M-ZOHO-V2 | src/fdd/zoho_v2.py | **M0** | 8 项修复(合成 fixture 上验收);ai_safe 输出无 normalized_sn;越界日期归零 |
| M-FEAT 特征库 | src/fdd/feat.py | M1 | 特征注册表全量无 NaN 泄漏;注入扰动方向性测试 |
| M-DRIFT | src/fdd/drift.py | M1 | 合成斜坡(30/60/90 天)检出延迟与误报报告 |
| M-SENSE | src/fdd/sense.py | M1 | 注入 ±2K 偏置/斜坡检出 100%,零误报 |
| M-LABEL | src/fdd/label.py | M1(桩) | 桩数据全路径 + 边界用例;窗口 [工单日−21d, +3d] |
| M-VALID | src/fdd/valid.py | M1 | 合成数据产出完整五分类报告模板 |
| M-BASE | src/fdd/baseline.py | M2(等实验室数据) | L1 留出点 MAPE ≤5%/1K |
| M-DIAG | src/fdd/diag.py | M1 骨架 | 桩标签端到端产出合法 C5 |

`pytest -m m0` 全绿 = M0 完成。测试即规格:测试先于实现存在,红是初始状态。

## M-ZOHO-V2 的 8 项修复

1 删除明文 SN 列;2 日期钳制 [2018, 今日] + 回退打标;3 匹配窗口按"事件先于工单"([−21d, +3d]);4 复核队列重排(类别价值 × multi 歧义 × 低置信 × 近年份;top500 冷媒占比 ≥30%);5 series→SKU 范围过滤(范围外打标不删);6 编码统一 UTF-8;7 **维修动作标准化**(补冷媒/换传感器/换主板/换电机→L2 标签);8 **SN 类型分类器**(按 SN 编码规则区分外机/内机/网关 SN,自动解歧 valid_multiple——multi 主成因是三类 SN 混录)。

## 悬而未决(写代码时留接口,不留假设)

- CompState=2 周期低频程序的名称(固件问题已发出;处理方式已定:剔除)。
- 跨 SKU 传感器位置一致性(硬件问题第 4 问,影响跨 SKU 特征互通;未确认前跨 SKU 比较打 unverified 标)。
- 时间戳时区口径(摄取按样本 −05:00 + tz_unverified 标)。
- N0/Cch/V12/V15 语义(保留原始列,不入特征)。
- SN 编码规则全文(O6,修复 #8 的前置)。
- **固件饱和温度查表偏差**:样本反推固件 Tsat ≈ CoolProp R410A @ (0.980665×表压 + 1.0133) bar,偏差 ≈ −2.0% 压力(= kgf/cm²→bar 系数)。读数单位已确认为 bar(数值/10 = MPa),偏差归于固件表轴,待厂商确认。复现函数 conv.controller_sat_temp_c 仅用于一致性校验,禁止入物理列/特征。

## 常用命令

本机解释器:必须用项目虚拟环境 `fdd/.venv`(Python 3.12.0),即 `.venv/Scripts/python -m ...`。**禁止用系统 Python 跑测试**(系统为 3.10,未安装 fdd 包,collection 直接 ModuleNotFoundError)。

```bash
.venv/Scripts/python -m pytest -m m0          # M0 验收
.venv/Scripts/python -m pytest -m m0 -k conv  # 单模块
.venv/Scripts/python scripts/smoke.py         # 环境与样本数据自检
```
