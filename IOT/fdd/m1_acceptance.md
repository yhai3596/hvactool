# M1 验收摘要(2026-07-03)

全量:`pytest -m m0` 13 通过,`pytest -m m1` 47 通过,合计 60。环境:fdd/.venv(Python 3.12.0)。
测试套件全部由本 Project 起草、人工放置(CLAUDE.md 第 12 条放置模式),实现零改动测试、零调阈值。

## 模块 × 测试数

| 模块 | 实现 | 测试文件 | 测试数 | commit |
|---|---|---|---|---|
| M-FEAT | src/fdd/feat.py | test_m1_feat.py + test_m1_feat_fallback.py | 9 + 2 = 11 | 96e25f4 |
| M-DRIFT | src/fdd/drift.py | test_m1_drift.py | 12 | fe9084a |
| M-SENSE | src/fdd/sense.py | test_m1_sense.py | 9 | f04814d |
| M-LABEL | src/fdd/label.py | test_m1_label.py | 8 | c36e915 |
| M-VALID + M-DIAG | src/fdd/valid.py + diag.py | test_m1_valid.py | 7 | 6804aa7 |
| 合计 | | | **47** | |

## M-FEAT 要点

- 注册表 13 项锁定;三级稀疏箱回退(n≥12,mode×Ta×Rps → mode×Ta → mode),样本回退分布 96.01% / 3.99% / 0%,覆盖率 701/701 = 100%。
- 方向性注入(Exv+30 / Tl+2K / Qh×0.9)实测:exv_resid +30.176、sc_resid −1.999、capacity_resid −0.0989——几乎精确复现注入量。
- defrost_frequency = 0.400 次/h(2 段真化霜 / 5 h)。

## M-DRIFT 合成斜坡报告(k=0.5, h=5, 种子钉死)

| ramp_days | detection_rate | mean_delay_days | false_alarm_rate |
|---|---|---|---|
| 30 | 1.0 | 9.00 | 0.35 |
| 60 | 1.0 | 14.00 | 0.35 |
| 90 | 1.0 | 18.25 | 0.35 |

风险备注:false_alarm_rate 0.35 距断言上限 0.40 余量仅一档种子(120 天窗、未标定 h=5 的真实水平,理论 ARL₀≈465 天);**M4 标定首要对象**。

## M-SENSE 清洁余量与注入统计量

清洁样本(后窗中位数 − 参考中位数)对阈值:

| 通道 | clean stat | 阈值 | 余量 |
|---|---|---|---|
| sh (Ts,Lp) | +0.244 | 0.80 | 0.56 |
| sc (Tl,Hp) | −0.097 | 0.45 | 0.35 |
| th_te (Th) | +0.414 | 1.00 | 0.59 |
| ta_th (Ta) | +0.720 | 1.20 | 0.48(样本后段环温爬升所致;跨天气窗口最可能率先误报,M4 标定名单) |

六注入用例精确统计量:

| 注入 | 通道 | 实测 stat | 预测 | 对齐 |
|---|---|---|---|---|
| Ts +2.0 | sh | +2.244 | +2.24 | ✓ |
| Ts −2.0 | sh | −1.756 | −1.76 | ✓ |
| Tl −2.0 | sc | +1.903 | +1.90 | ✓ |
| Ta +2.0 | ta_th | +2.720 | +2.72 | ✓ |
| Lp +0.5 | sh | −2.667 | −2.0±0.4 | 带外 0.27,<0.3 停止线 |
| Hp −0.5 | sc | −0.973 | −0.95±0.1 | ✓ |

**勘误**:早前回执中"±0.5 bar ≈ 1.1–1.6 K"为 Project 侧转写错误;实测低压侧 +0.5 bar → te_sat ≈ +2.9 K(样本低压区饱和曲线斜率陡),高压侧 −0.5 bar → tc_sat ≈ −0.88 K。Lp 用例预测带(−2.0±0.4)本身沿用了同一错误斜率假设,实测 −2.667 经其余五点交叉验证确认链路无恙。

## M-LABEL 边界语义清单(实现锁定)

- 匹配窗口:日粒度**闭区间**,delta = 事件日 − 工单日,−21 ≤ delta ≤ +3(两端含;−21/+3 匹配,−22/+4 不匹配)。
- 多事件:|delta| 最小;打平取较早事件(确定性)。
- 跨 SN 永不匹配;每工单独立匹配,多工单允许共享同一事件。
- 未匹配行:matched=False、matched_event_ts=NaT、matched_fault_code=NaN。
- training_admission:纯行过滤保留全列;准入 = (label_tier ≥ 3) ∨ (sn_status=valid ∧ review_state=confirmed);`valid_multiple_candidates` 硬排除,任何 tier/review 不豁免。
- verify_closure:入带点 = repair_date(含当日)起首个带内值,须 ≤ repair_date+within_days;入带后至序列末尾非 NaN 全带内才 True。测试外守卫:NaN 日忽略(不违反也不满足);入带后非 NaN 天数 < 5(MIN_POST_DAYS)→ False。
- tier→L4 升级接线留 M3(真实 C3 连接时)。

## M-VALID + M-DIAG 要点

- leave_units_out_splits:单元字典序 ceil 等分,确定性;行级随机切分全项目禁止。
- score_events:防重复计数消费制匹配(truths 按 (unit,day) 序;pred 至多消费一次;correct → no_response → misdiagnosis 判定序)。
- 双基线对照(CoolantLackLimit 提前量 / Title-24)留 stub,M4 落地。
- diag v0 阈值:EXV_UP ≥10 / SC_DOWN ≤−0.8 / CAP_DOWN ≤−0.05 / SH_HIGH ≥2.0;判定序 leak → indoor_side_nonspecific → none;sh 证据仅 exv_saturated=True 时准入(铁律 #3);confidence 占位 0.7/0.5/0.1,M4 由树模型替换;mode="cooling" → NotImplementedError(随 M2 数据落地)。
