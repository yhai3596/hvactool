# M0 验收摘要(最终代码状态重新生成)

- 日期:2026-07-02
- 环境:Python 3.12(.venv),`pip install -e ".[dev]"`(依赖含 scipy)
- 命令:`pytest -m m0` → **13 passed, 5 deselected**(M0 完成 = 全绿 ✅)
- 代码基线:M-CONV / M-SEG / M-ZOHO-V2 三模块实现 + "M-CONV: separate physical sh/sc from firmware bias replica; fix bias-systematic test"(物理层与固件复现分离后的最终形态)
- 样本:data/sample/data_run_sample.xls(1692 行 × 48 列,约 5 小时制热)

## 测试通过状态(13/13)

| 模块 | 测试 | 状态 |
|---|---|---|
| M-CONV | test_abs_pressure_is_fixed_offset_no_altitude(绝压 = 表压 + 1.013,无海拔修正) | ✅ PASSED |
| M-CONV | test_sh_phys_physical_self_consistency(sh_phys ≡ Ts − CoolProp 绝压露点,测试内独立重算,差 < 1e-6) | ✅ PASSED |
| M-CONV | test_firmware_sh_bias_is_systematic(固件偏差系统性:\|mean\|/std > 3 且 \|spearman\| > 0.5) | ✅ PASSED |
| M-CONV | test_sc_phys_strips_minus_one(sc_phys ≡ tc_sat − Tl 无 −1 项 + 复现偏置 ≡ 1.0±0.1) | ✅ PASSED |
| M-CONV | test_tcs_gap_uses_target_not_measurement(tcs_gap 用目标值) | ✅ PASSED |
| M-SEG | test_defrost_and_special_counts(2 化霜 / 5 special) | ✅ PASSED |
| M-SEG | test_no_steady_rows_inside_compstate2(CompState=2 内稳态行 = 0) | ✅ PASSED |
| M-SEG | test_steady_coverage_band(稳态覆盖率 ∈ [0.40, 0.80]) | ✅ PASSED |
| M-SEG | test_defrost_by_st_not_th(化霜判据 = St,非 Th) | ✅ PASSED |
| M-ZOHO-V2 | test_date_clamp(日期钳制 [2018, 今日] + 回退打标) | ✅ PASSED |
| M-ZOHO-V2 | test_ai_safe_has_no_cleartext_sn(无明文 SN,保留 hash_sn) | ✅ PASSED |
| M-ZOHO-V2 | test_queue_reranking_puts_refrigerant_first(top 队列冷媒占比 ≥ 30%) | ✅ PASSED |
| M-ZOHO-V2 | test_repair_action_standardization(维修动作 → L2 标准化) | ✅ PASSED |

## M-CONV 物理口径与固件偏差表征

物理列定义(锁定):sh_phys = Ts − te_sat(CoolProp R410A 露点 @ lp_abs = Lp + 1.013)、sc_phys = tc_sat − Tl(泡点 @ hp_abs,无 −1)。固件复现逻辑完全隔离于 `firmware_sh_replica` / `firmware_sc_replica`,不参与物理列定义。

固件偏差实测(稳态段,`[firmware-bias]` 测试输出):

| 侧 | 量 | 稳态均值 | std | spearman(饱和温度, 差值) |
|---|---|---|---|---|
| Sh(低压) | sh_phys − Sh | **−0.364 K** | 0.072(系统性 5.1σ) | **−0.75** |
| Sc(高压) | sc_phys − (Sc + 1) | **+0.832 K** | — | **−0.66** |
| Sc(高压) | sc_phys − Sc(原始差) | **+1.832 K** | 0.014 | — |

参考:sh_phys 对上报 Sh 的全程 P95 |差|(St=0 豁免)= 0.583 K。两侧 spearman 同为负,方向交叉验证一致,支持单一固件压力尺度偏差同时解释两侧;−2% 具体数值为拟合估计,待厂商确认(详见 CLAUDE.md 锁定发现)。

## 样本分段统计(M-SEG)

| 指标 | 数值 | 验收要求 |
|---|---|---|
| 真化霜段(CompState=2 且 St 翻 0) | **2** | = 2 ✅ |
| special 段(CompState=2 且 St 保持 1,周期低频程序,整段剔除) | **5** | = 5 ✅ |
| run 段 | 8 | — |
| off 段 | 6 | — |
| 稳态覆盖率(run 行中 steady=True 占比) | **0.629** | ∈ [0.40, 0.80] ✅ |
| CompState=2 段内稳态行数 | **0** | = 0 ✅ |

## 备注

- 固件饱和温度查表偏差已列入 CLAUDE.md 锁定发现(第三个系统性误差源);残差分析一律用 sh_phys/sc_phys 物理口径,禁用固件上报 Sh/Sc。
- M-ZOHO-V2 修复 #8(SN 类型分类器)为 passthrough 模式:SN 编码规则(O6)到货前一律返回 unknown,valid_multiple 不自动解歧。
- M-SEG 稳态阈值(RPS_STD_MAX=1.5 / EXV_STD_MAX=6.0)为样本标定值,M2 实验室数据到货后重标。
