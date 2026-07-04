# CLAUDE.md — FDD 正式使用设备故障诊断系统

北美住宅变频热泵外机(R410A,3 系列 × 2 型号,208/230V 单相,内外机无通讯 + 第三方内机)正式使用设备 FDD:物理残差 + 统计漂移 + 可解释树模型。全流程本地运行。规格文档:《FDD 项目方案 v1.1》《FDD 系统开发文档 v1.0》(docs/,自 E:\AICoding\IOT\PRD 复制的副本;口径冲突时以本 CLAUDE.md 为权威版本)。

## 铁律(每次编码必须遵守,违反任何一条即为缺陷)

1. **压力**:Lp/Hp 为密封式表压(bar)。绝压 = 表压 + 1.013,全正式使用设备固定。**禁止**对压力换算做海拔修正;海拔只允许作为风侧空气密度协变量出现。
2. **过冷度**:sc_phys = tc_sat − Tl。**必须剥掉控制器公式里的 −1**(那是显示偏置,不是物理量)。任何特征/残差出现 `− 1` 项即为回归缺陷。
3. **制热模式 Sh 被 EEV 伺服钉在 ≈0 K(实测 0.02±0.3),禁止把 Sh 作为制热泄漏的主证据**。制热泄漏载体 = exv_resid + sc_resid + capacity_resid;Sh 仅在 EEV 饱和(开度触顶)后作为晚期指标启用。制冷模式 Sh 正常使用。
4. **能效/COP/容量类特征禁用 PowerIn**(内含曲轴加热带),用 PowerComp(+风机)。PowerIn − PowerComp − 风机 = 寄生功率特征 p_parasitic。
5. **电流类跨机特征必须以 V1 为协变量**(正式使用设备 208/230V 双峰,187–256V)。
6. **稳态定义**:CompState=1 ∧ 段内 >5 min ∧ CompRps 与 Exv 的 2 min 滚动标准差双低阈。**CompState=2 全段剔除**(含真化霜与周期低频程序);AcState ∉ {4,5} 不入运行分析。全部窗口/点数常量锚定 10 秒时基;任何数据源进入管线前由 C4 层归一到 10 秒,模块内禁止出现采样率分支。
7. **St = 四通阀状态**(1 制热位,0 化霜/制冷位),是化霜边界的地面真值。化霜判据以 St 为主,Th 尖峰只做校验。
8. **Tcs = 动态目标冷凝温度**(控制器设定,样本内 38/39/40/45),不是实测温度。tcs_gap = tc_sat − Tcs 是"学习漂移 vs 故障漂移"的判别量:目标变 = 控制决策;追不上目标或追上但 Rps/Exv 代价抬升 = 能力短缺。
9. **TH 语义随模式翻转**:制热 = 室外蒸发器盘管中部(结霜/蒸发通道),制冷 = 冷凝器中部。代码中禁止硬编码"condenser"语义。
10. **制热 Sc 含安装管路温降偏置**(Tl 在室外机液管,管长因安装而异):制热工况只允许逐机漂移比较,禁止跨机绝对值比较。
11. 禁止修改 tests/ 目录下的任何文件。若认为某条测试或铁律有误,停止工作、输出理由,等待人工裁决。
12. tests/ 的变更仅允许誊写本 Project 起草并经人工授权的测试原文,每次授权限当次指令所列文件;agent 不得自拟测试或改动断言/阈值。测试原文亦可由人工直接放置为文件,CC 职责为核对清单一致性、删除对应占位、提交。
13. 测试就位 + 本 Project 模块指令下达 = 实现授权,不设方案审批环节;停下仅限规则冲突或断言不达标。
14. 机械/运维类指令(路径、命令旗标、环境参数)与仓库实况冲突时:先验证前提(对样/dry-run),做意图保持的等价修复,执行后完整披露并把正确命令入档。规格类内容(测试、阈值、口径、物理定义、验收标准)不适用本条,一律停下等裁决(第 11–13 条不变)。
15. 未知枚举值处置(2026-07-03 裁决成文):翻译表外枚举行隔离不加载 + 计数披露(load 溯源 attrs)+ 列入厂商问题清单,不停线;仅当隔离影响击穿闸门判定或隔离量超过载入行 5% 时停下等裁决。
16. HVAC 术语替换仅作用于人读叙述层(文档/回执/锁定发现);机器实现层(代码标识符/测试断言/契约字段/统计术语如 leave-units-out/CUSUM/residual/bin)保持技术命名不动。"机队"在叙述层统一改"正式使用设备"(人工确认统一用词,2026-07-04)。

## 锁定发现

- 固件饱和温度查表相对 CoolProp 存在系统性压力尺度偏差,高低压两侧均现(Sh 侧稳态约 0.58K,Sc 侧使物理偏移由预期 1.0 变为约 1.84)。同源性:低压侧与高压侧的 sh_phys−Sh、sc_phys−(Sc+1) 两个残差与各自饱和温度的 spearman 同为负(−0.75 / −0.66),方向交叉验证一致,支持单一固件压力尺度偏差同时解释两侧;−2% 具体数值为拟合估计,待厂商确认。此为继 −1 过冷显示偏置、密封表压之后第三个系统性误差源,影响所有依赖饱和温度的特征。残差分析一律用 sh_phys/sc_phys 物理口径,禁用固件上报 Sh/Sc。
- 控制器计算能力值(Qch≡QrX_W 链)相对台架实测 +2%~+12%(5 交叠窗,均值≈+7%,σ=0.04)——第四个系统性计算偏差;逐机漂移检测免疫(同源自消);绝对能力陈述必须带此修正;偏差随模式/负荷的特性待更多交叠窗表征。
- 跨工况不变性实测(U44, ΔTa 23–31K):th_te −0.10 为唯一全局不变通道(冷媒内部关系);sh −1.50(伺服工况策略)、sc −0.57(充注再分布)、ta_th −2.20(风侧负荷比)均随工况真实漂移;传感器一致性必须分箱参照,全局参照跨季必误报;M-DRIFT/M-FEAT 先天分箱免疫。
- 制热模式 th_te 在同 Ta 箱内随霜相位真实偏移(实测 +2.88K,轻霜 5h 样本;重霜更大);M1 全局参照下的绿为跨箱稀释假绿;分箱制使 sh/sc/ta_th 清洁统计量降至 0.04/0.13/0.14(余量 5–20 倍改善)。
- 架构原则——尺与被测物分离:M-FEAT 在某模式注册为特征的量,禁止在该模式充当 sense 不变量;通道表带模式门,新建通道强制对注册表交叉核对;本条源于 th_te 事件(Project 侧成文矛盾,铁律 9/注册表 vs sense 通道表)。
- 仲裁定性——信任旗为 M-DIAG 仲裁输入非独立判决;sh/sc 通道在真实泄漏晚期会连带触发,故障模式并发时故障解释优先,接线留集成层。
- 实验室固件(59/62 列)饱和表对 CoolProp 无偏(±0.1K,斜率≈0);现场固件 −2% 压力尺度偏差在实验室不复现;固件版本差异 vs 工况区间差异两因未分离;重叠压力区间的现场 Teg/Tcg vs CoolProp 交叉验证待 M3 现场数据。
- H2 额定点本身是结霜进程非稳态:同窗内 sc/sh/ta_th/th_te 沿净→结霜→化霜真实移动(实测 bin0 漂移 sc−1.77/ta_th−2.53/sh−1.19);H2 的合法额定锚仅限净盘管相位(rating_anchor);波及 envelope(H2 锚)与 sense(H2 自检),二者共用 seg 的 frost_phase。
- th_te 执照收窄——th_te 全局不变执照仅无霜制热有效;结霜工况 th_te 为相位状态量,不承担信任校验(实测 H1N→H2 同机 +0.4~+1.2K)。
- envelope 模型类预定——M2 L1 包络为低阶物理回归(4 额定点/SKU 仅够定物理曲线 1-2 参数,统计学习模型样本量差两数量级必过拟合);树模型 DoD 属 M4 正式使用设备标签,非 M2。
- 额定锚按工况分两类:无霜工况锚为净盘管稳态,结霜工况(H2/H4)锚为结霜准平衡段(frosting_steady)并将结霜相位作为 envelope 协变量;"额定锚必须净盘管"为无霜工况专属规则,套用于结霜工况是范畴错误(Project 侧,已致 4860AA 一度误判仅 2 锚)。
- ta_th=Ta−Th 与 Ta 偏置共线,任何 Ta 感知的分箱/去相关都吸收 Ta 偏置(几何证明:偏置沿箱内斜率方向,不可分离);ta_th 降级为工况漂移通道,Ta 偏置检测移至停机平衡检验(Ta-free)。传感器信任映射:Ts/Tl/Lp/Hp←稳态一致性(sh/sc);Th←化霜平台期 Th−tc_sat;Ta←停机平衡检验;ta_th/th_te 仅工况/相位监测,不发传感器 flag。此为"工况量不得兼任其内含传感器的信任校验"原则的第二例(第一例 th_te)。
- envelope DoD 分两级:M2 实验室阶段验物理合理性(单调性/量级/无病态外推),M3 现场阶段验留一 MAPE≤5%;将 M3 精度标准压到 M2 是 DoD 错配(Project 侧,已致 envelope 在 4 认证点/SKU 下结构性无法通过留一验证)。
- envelope 单调性判据:制热 Qh 随 Ta 升、制冷 Qc 随 Ta 降(标准热泵物理:制热室外温升→蒸发吸热增,制冷室外温升→冷凝压力增容量降);FDD-I-008 指令误将制冷方向套至制热侧,已更正。
- envelope 量级判据 M2 验相对(正值+相邻工况容量比 ∈ [0.3,3.0] 无跳变),M3 验绝对(逐工况 AHRI 额定容量,需认证报告额定表);对 SKU 单一额定值做全工况基准是错的,低温工况对单点额定必然偏低(实测 4860AA H4=62.8% 对 SKU 额定,对 H4 自身额定约 100%)。
- 稳态判据极限工况验证欠账:transient_report 三断言在 M2 全绿,但检验集缺失——实验室数据无回油工况(0 文件)、除霜工况已重分类为 H2 rating,唯一 extreme 是 H_low20(44 行/2 稳态)。断言(1)(2)空跑、(3)单点。稳态判据在极限工况上的验证实为欠账,挂 M3:现场数据含大量真实回油/除霜/深冷极限段(有时间无标签),M3 补做此验证。M2 全绿指代码逻辑正确,不指判据经极限工况验证。
- 4860AA 低温建模下沿:−20℃(H_low20)稳态率 0.045,44 行仅 2 稳态;对比 −15℃(H4)有 6097 frosting_steady 锚。−20℃ 超机型正常工作包络下沿,压缩机在能力边界持续漂移无准平衡。4860AA 可建模低温下沿约 −15℃,−20℃ 及以下为包络外,该区间残差分析基线不可建、结果不可靠。
- M3 大批量禁用逐行 PropsSI(慢 + native segfault 风险,几十亿行必反复触发);改预计算 R410A 饱和查表(1.0–46 bar,步长 0.0005 bar,露点/泡点各一张,90001 点)+ 线性插值,无 native 崩溃、可复现。此为 M3 前置技术项,M2 期消化;查表口径恒等于 CoolProp(离线预计算)。精度双门:指令精度 DoD <0.01K,但 M0 自洽测试(test_sh_phys_physical_self_consistency)将 materialize 的 te_sat 钉在直算 PropsSI 的 1e-6K 内——0.01 bar 粗表(误差 6e-5K)会击穿该封板测试,故步长收至 0.0005 bar(离网格最坏 5e-8K,数据落网格点即机器精度),封板 sh_phys/sc_phys 数值不移。查表用 conv._sat_temp_c_table,PropsSI 直算 conv._sat_temp_c 保留作生成/校验。
- 标定值为配置资产(config/calibration.yaml + unit_sku_map.yaml,PyYAML):数据扩充触发重标改配置不改代码,每值带 source/date/scope 可追溯;模块 import 时经 config.cal(点路径)读取,值与外部化前完全一致(行为中性)。机台→SKU、data_type(健康/植入)、SKU 额定、H4 代理 SKU 均外部化,随数据交付更新;未知机台不丢弃(load_lab attrs.unmapped_units 报告)。两处标定数字在测试断言内(envelope 相邻比 [0.3,3.0]、M0 自洽 1e-6K),不外部化(改需 Project 授权测试原文)。
- 植入机数据双路封堵必须成对:①anchor 层 rating_anchor 清零(c4._apply_data_type_routing),②coverage 门只数 healthy_baseline 工况——只做一条会假绿(植入工况计入健康覆盖→envelope 用故障数据拟合健康包络)。两路共用同一 data_type 分流函数,穿透测试(test_injected_unit_excluded_from_baseline)守住不回归。

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
- 假名化协议:①规范化(strip/大写/去空格连字符)先于 HMAC-SHA256(key=环境变量 FDD_HMAC_KEY),取 hex 前 16 位;②工厂双 SN(ODU_SerialNo→hash_sn、PCB_SerialNo→hash_pcb_sn)同规则,明文列不得出现在任何产出物;③M-ZOHO-V2 第 9 项修复:全量重跑时按本协议从 normalized_sn 重算 hash_sn 后删明文列,三源同钥同规则;④密钥仅经 os.environ,存在性验证只输出 SET/UNSET 与长度。
- 密钥相关 shell 仅允许 `python -c "print(bool(os.environ.get('FDD_HMAC_KEY')), len(os.environ.get('FDD_HMAC_KEY') or ''))"`;禁止任何回显密钥内容(含切片)的命令(2026-07-04 泄露事件后成文;v1 密钥已作废,无落盘产物)。

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
| M-FEAT 特征库 | src/fdd/feat.py | M1 | 特征注册表全量无 NaN 泄漏;注入扰动方向性测试。注册表 13 项以 test_m1_feat.py 为准:tf_resid/indoor_load_proxy 为 2026-07-02 外部评审采纳项(开发文档 v1.0 成文于采纳前,该处已过时);defrost_freq 刻意移出注册表——注册表限逐稳态行残差,化霜频率是全记录事件率(时间基含化霜段),独立为 defrost_frequency() 验收。 |
| M-DRIFT | src/fdd/drift.py | M1 | 合成斜坡(30/60/90 天)检出延迟与误报报告 |
| M-SENSE | src/fdd/sense.py | M1 | 注入 ±2K 偏置/斜坡检出 100%,零误报 |
| M-LABEL | src/fdd/label.py | M1(桩) | 桩数据全路径 + 边界用例;窗口 [工单日−21d, +3d] |
| M-VALID | src/fdd/valid.py | M1 | 合成数据产出完整五分类报告模板 |
| M-BASE | src/fdd/baseline.py | M2(等实验室数据) | L1 留出点 MAPE ≤5%/1K |
| M-DIAG | src/fdd/diag.py | M1 骨架 | 桩标签端到端产出合法 C5 |

`pytest -m m0` 全绿 = M0 完成。测试即规格:测试先于实现存在,红是初始状态。

## M-ZOHO-V2 的 8 项修复

1 删除明文 SN 列;2 日期钳制 [2018, 今日] + 回退打标;3 匹配窗口按"事件先于工单"([−21d, +3d]);4 复核队列重排(类别价值 × multi 歧义 × 低置信 × 近年份;top500 冷媒占比 ≥30%);5 series→SKU 范围过滤(范围外打标不删);6 编码统一 UTF-8;7 **维修动作标准化**(补冷媒/换传感器/换主板/换电机→L2 标签);8 **SN 类型分类器**(按 SN 编码规则区分外机/内机/网关 SN,自动解歧 valid_multiple——multi 主成因是三类 SN 混录);9 **假名化重算**(按数据安全区假名化协议从 normalized_sn 重算 hash_sn 后删明文列,三源同钥同规则)。

## 悬而未决(写代码时留接口,不留假设)

- CompState=2 周期低频程序的名称(固件问题已发出;处理方式已定:剔除)。
- 跨 SKU 传感器位置一致性(硬件问题第 4 问,影响跨 SKU 特征互通;未确认前跨 SKU 比较打 unverified 标)。
- 时间戳时区口径(摄取按样本 −05:00 + tz_unverified 标)。
- N0/Cch/V12/V15 语义(保留原始列,不入特征)。
- SN 编码规则全文(O6,修复 #8 的前置)。
- **固件饱和温度查表偏差**:样本反推固件 Tsat ≈ CoolProp R410A @ (0.980665×表压 + 1.0133) bar,偏差 ≈ −2.0% 压力(= kgf/cm²→bar 系数)。读数单位已确认为 bar(数值/10 = MPa),偏差归于固件表轴,待厂商确认。复现函数 conv.controller_sat_temp_c 仅用于一致性校验,禁止入物理列/特征。
- **ODU_CtrlMode 完整枚举字典**(厂商问题):翻译表仅 4=制冷/11=制热/13=除霜(物理钉住);实测另见 5(制冷停机前置秒段)、10(启动过渡)、0/1/2/3(停机族),均为观察非认定,裁决前按铁律 15 隔离处置。

## 推送协议

远端唯一命名 fdd-github;唯一允许推送 fdd-export:main(fdd/ 的 subtree split);每次推送前重跑 split;fast-forward only(M0 禁令延续);E:/AICoding 主分支永不出机;GitHub 仓库保持 private;data/raw、data/lake 保持 gitignore。

```bash
# 在仓库根 E:/AICoding 执行(prefix 以仓库根计):
git subtree split --prefix=IOT/fdd -B fdd-export
git push fdd-github fdd-export:main   # refspec 已锁 fdd-export:main,禁 force
```

## 常用命令

本机解释器:必须用项目虚拟环境 `fdd/.venv`(Python 3.12.0),即 `.venv/Scripts/python -m ...`。**禁止用系统 Python 跑测试**(系统为 3.10,未安装 fdd 包,collection 直接 ModuleNotFoundError)。

```bash
.venv/Scripts/python -m pytest -m m0          # M0 验收
.venv/Scripts/python -m pytest -m m0 -k conv  # 单模块
.venv/Scripts/python scripts/smoke.py         # 环境与样本数据自检
```
