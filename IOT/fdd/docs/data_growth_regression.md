# 数据扩充回归流程 + 测试断言分类(FDD-I-012 #3)

新数据(冷媒欠充梯度、更多机台/工况)到货后,全套测试必然出现红。**红的性质决定处置**:
样本特征断言红 = 预期,走"重标基线";物理不变量断言红 = 真 bug,停下。

## 回归流程

```
新数据到货
  → 更新 config/unit_sku_map.yaml(新机台 sku + data_type:健康/植入)
  → .venv/Scripts/python -m pytest -m "m0 or m1 or m2"
  → 逐个红断言判性质:
       物理不变量红  → 查 bug,停下报实测(铁律:不达标是合法中间状态,不改口径)
       样本特征红    → 重标:改 config/calibration.yaml 的对应值(带 source/date/scope),
                       不改代码;若断言本身是绝对数字(在测试内),走 Project 授权测试原文修订
  → 重标后重跑,全绿 = 回归完成
```

**关键**:重标只改 config,不改代码/口径/被测量方向。绝对数字若嵌在测试断言里(非模块常量),
放宽/参数化需 Project 起草测试原文(铁律 12,agent 不自拟测试)。

## 断言分类(111 条,11 文件)

分类轴:**物理不变量**(任何数据量成立:物理定义、算法逻辑、契约结构、注入方向性)
vs **样本特征**(当前数据量/固定样本特有的绝对数字)。

| 测试文件 | 断言 | 物理不变量 | 样本特征(绝对数字) |
|---|---|---|---|
| test_m0_conv | 9 | sh=Ts−te_sat 恒等、lp_abs=Lp+1.013、sc 系统性偏差方向 | **sh P95≤0.15K**、**sc≡1.0±0.1**(固定 5h 样本固件偏差) |
| test_m0_seg | 5 | CompState=2 内零稳态 | **==2 化霜/==5 special/稳态覆盖[0.40,0.80]**(固定样本) |
| test_m0_zoho | 8 | 8 修复逻辑、无明文 SN、日期钳制方向 | — |
| test_m1_feat | 14 | 注册表锁、无 NaN、注入方向性(符号)、覆盖≥0.9 | **defrost_freq[0.3,0.5]**、自残差本底(exv<1.0/sc<0.05/cap<0.01)(固定样本) |
| test_m1_feat_fallback | 5 | fallback 层级语义、level2 全球回退 | — |
| test_m1_drift | 19 | robust_sigma、CUSUM 阶跃、检出率==1、延迟单调 | **false_alarm≤0.40**(合成种子固定,非数据敏感;薄余量) |
| test_m1_sense | 8 | 零误报、注入检出、停机平衡归因 | — |
| test_m1_label | 9 | 窗口边界、准入矩阵、闭环逻辑 | — |
| test_m1_valid | 13 | LUO 切分、五分类计数、diag C5 | — |
| test_m2_lab | 14 | schema、单调性符号、量级相邻比、sense 不变性、transient(1)(2) | **coverage≥4**、**transient(3) 极限≤额定+0.05**(数据敏感) |
| test_m2_prodline | 7 | (skip,待 O-track) | — |

**统计**:物理不变量 ≈ 90 条;样本特征 ≈ 12 条,分两类——
① **固定样本特有**(M0-seg 的 2/5/覆盖带、M1-feat 的 defrost_freq/自残差):只在 5h 样本 fixture 变时红,冷媒(lab)数据到货**不触发**;
② **lab 数据敏感**(M2 coverage≥4、transient(3)):随 lab 数据增长变化。

## 冷媒数据到货时首先失效的样本特征断言

冷媒欠充数据是**植入机(data_type=fault_injected)**,c4 已将其排出 rating_anchor 池——
故 envelope 物理合理性 / sense 不变性 / transient 均**受保护**(只用健康基线),不因植入数据红。

**首先失效候选**(按概率):
1. **test_condition_coverage_minimum(coverage≥4)**——该断言按 `condition_class=="rating"` 计数,
   **未按 data_type 过滤**:植入机的 rating 工况行会被计入。若植入机是**已有 SKU**→覆盖不减(甚至增),不红;
   若引入**新 SKU 或该 SKU 工况<4**→红。语义上 coverage 应只数健康基线工况,该断言需加 data_type 过滤
   (Project 授权测试原文修订);当前是唯一直接暴露于 lab 数据、口径待收紧的断言。
2. **test_ssd_transient_report 断言(3)**——若欠充在极限工况(如深冷)采集,新增 extreme 行的
   steady_share 与额定比较可能移动(±0.05 容差);属数据敏感,重标走 config 或 Project 测试修订。
3. **M0/M1 固定样本断言**(2/5 化霜、defrost_freq、自残差)——冷媒 lab 数据**不触发**(它们锚在 5h 样本);
   仅当有人替换样本 fixture 才需重标。

## 待 Project 授权的测试原文修订(铁律 12,agent 不自拟)

本文档只做**分类与流程**,不改测试断言。以下修订需 Project 起草原文:
- coverage 断言加 `data_type=="healthy_baseline"` 过滤(收紧口径,植入机不计健康覆盖);
- 固定样本绝对数字加注释 `# SAMPLE-SPECIFIC: re-baseline on data growth` 或参数化;
- transient(3) 容差参数化到 config。
