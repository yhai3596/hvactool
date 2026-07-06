# 指令 FDD-I-018 · 2436AA envelope 干净重拟合 + 拆分 envelope_input／rating_anchor

**版本**:v1
**文件生成时间**:2026-07-06
**回执首行**:回显 `响应指令: FDD-I-018` + 远端 tip 提交哈希。所有达标项报实测数值,不接「通过/达标」二字。

**背景**:FDD-I-017 已文件级重标 31 号 5 个少冷媒文件为 fault_injected(28,690 行),sense 预存红消,污染归因证实。2436AA envelope 此前因 31 号植入数据混入被污染(H1 30%/H2 99%),现植入数据已在分流层排除,可干净重拟合。同时落实已定的 NONSTD_HEAT 双规则(登记表 DK-007):①出额定锚池、②留 envelope 拟合输入——Item 6 侦察证实二者当前是同一集合 `lab[rating_anchor]`,本指令拆开。

**新程序硬触发器(本批起生效,替代模糊的「规格类停」)**:执行中若发现**任何 DoD 只能通过改动本指令「改动落点」未列出的字段/函数/文件才能满足**,写代码前**停下**,回报「该 DoD 需动 X,请确认」,不自决+披露。这是可机械检验的规则,不留自证空间。

---

## Item 1 · 拆分 rating_anchor 与 envelope_input(落实 NONSTD 规则①②)

**现状(Item 6 侦察)**:`tests/test_m2_lab.py:114` 用 `lab[lab["rating_anchor"]]` 同时供额定锚池与 envelope 拟合输入,二者同一集合。`baseline.py` 无 condition_class/label 过滤,靠 rating_anchor 布尔排除。

**要做**:引入独立布尔列 `envelope_input`,与 `rating_anchor` 解耦:
- `rating_anchor`:供额定覆盖门 / O-CERT 量级校验。**NONSTD_HEAT 行 `rating_anchor=False`**(规则①,非 AHRI 标准点不计额定覆盖;沿用 FDD-I-016 的 condition_class=extreme)。
- `envelope_input`:供 L1 envelope 拟合。**NONSTD_HEAT 的稳态锚行 `envelope_input=True`**(规则②,健康数据延展制热高 Ta 端)。
- 其余健康稳态行:两列同为 True(行为不变)。
- **fault_injected 行:两列同为 False**(FDD-I-017 已排除,本批保持)。

**改动落点**:`baseline.py` 拟合入口的行选择从 `rating_anchor` 改读 `envelope_input`;`c4.py`/`config` 中 anchor 赋值处派生 `envelope_input`;`tests/test_m2_lab.py` 的 envelope 装配从 `lab[rating_anchor]` 改 `lab[envelope_input]`。

**边界**:若拆分需改动上述未列出的消费者(覆盖门、瞬态报告、O-CERT 桩),停下回报——此三者应继续读 `rating_anchor`,不得被本次改动波及。

---

## Item 2 · 2436AA envelope 干净重拟合

- **前提**:Item 1 完成后,`envelope_input` 集合中 2436AA 已无 31 号 fault_injected 行、含 NONSTD_HEAT 健康行。
- **动作**:重拟合 2436AA 的 L1 envelope(4860AA 若未受污染则不动,受则同法)。
- **DoD(报实测)**:
  - 重拟合前后 `envelope_input` 行数/构成对照(确认 fault_injected 全出、NONSTD_HEAT 全入);
  - envelope 物理合理性 DoD(单调性 / 相邻工况比 [0.3,3.0] / 无病态外推)——这是 M2 级验收,**留一 MAPE≤5% 仍属 M3(FDD-I-007,test_envelope_holdout_dod 保持 skip,不在本批解封)**;
  - 重拟合后 2436AA 各工况 envelope 期望值与污染前对照,量化污染修复幅度(尤其 H1)。

---

## Item 3 · 明令未做(推迟至 O-CERT/M3,非本批)

以下经中立评估确认不在旗舰(冷媒诊断)关键路径,本批不做,不阻塞重拟合:
- **变频容量档细化**(H1_Full/H1_Low/Nom/Int 全 taxonomy):诊断用连续 (Ta, InvHz),不用离散容量档;离散档仅 O-CERT 量级校验需要 → M3。
- **Full 频率带修正**(H3/H4 越带,全负荷 88–142Hz 顶出 [70,86]):envelope 不用容量轴(Item 6 证实),只卡 O-CERT join → M3。本批容量轴保持现状,不改 config capacity.*。
- **工况命名重开**:环境字母 A/B/C/D/H0/H1/H2/H3/H4 已对齐 AHRI Table 8(FDD-I-017 Item 2a 实测 in_band),不动。
- **NONSTD_HEAT 改名**(High-heat):化妆项,沿用 NONSTD_HEAT,不改名。
- **存量迁移/severity 解析**:31 号 5 文件已 fault_injected 排除,重拟合不需要它们入库或解析档位。

---

## DoD 汇总(报实测)

1. Item 1:`envelope_input`/`rating_anchor` 拆分后,以下三组行的两列取值实测表——(a) 健康稳态行、(b) NONSTD_HEAT 稳态行、(c) fault_injected 行;NONSTD 必须 (input=True, anchor=False)。
2. Item 2:重拟合前后行数对照 + 物理合理性 DoD 实测 + H1 期望值污染修复幅度。
3. 回归:M0 13/13、M1 47/47、`test_m2_condition_of.py` 43/43、`test_m2_envelope_input.py`(新增,见下)前后全绿;`test_envelope_holdout_dod` 保持 skip;其余 M2 无翻转。
4. 单元测试(方案侧起草、人工放置,CC 不得自拟自改——铁律 11/12):见附《test_m2_envelope_input.py 断言》,钉死规则①②。

---

## 停下条件

- **规格类**:DoD 需动改动落点外的字段/函数/文件(见新硬触发器)、拆分波及覆盖门/瞬态/O-CERT 桩、物理合理性 DoD 不过 → 停,回报,等裁决。
- **机械类**:路径/旗标/参数 → 对样验证 + 等价修复 + 回执披露,不停。
