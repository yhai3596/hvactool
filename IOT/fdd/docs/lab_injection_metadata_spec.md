# 植入实验数据元数据规范(FDD-I-012 #4)

**目的**:冷媒欠充梯度(及后续任何故障植入)实验数据交付时,**必带结构化元数据**,不依赖
文件名解析。文件名考古(如 M2 的 "-20℃报C3"、"H4 升频")是脆弱且有歧义的;植入实验是**受控**
的,元数据应在采集时结构化记录。本规范是给这批冷媒数据交付定的接收格式——数据整理的 2–3 天里,
数据方按此附元数据,避免到货后考古。

## 交付形态

每个植入实验数据文件(RamChecker CSV 或同构)配一条元数据记录,推荐 **sidecar**:
`<datafile>.meta.yaml`(与数据文件同名 + `.meta.yaml`),或一张汇总
`injection_manifest.csv`(每数据文件一行)。字段如下。

## 必带字段

| 字段 | 类型 | 说明 | 示例 |
|---|---|---|---|
| `sku` | str | 外机型号,须匹配 config/unit_sku_map.yaml | EODA19H-4860AA |
| `unit` | str | 机台号(须在 unit_sku_map.yaml 登记,data_type=fault_injected) | 71 |
| `fault_type` | str | 故障族,须 ∈ C2 FAULT_FAMILIES | refrigerant_low_or_leak |
| `severity` | float | 故障幅度数值 | 0.20 |
| `severity_unit` | str | severity 的口径(见下,**必须显式**) | pct_removed |
| `condition` | str | 工况标签(AHRI 或极限),同 c4 test_condition 口径 | A / H1N / H4 / H_low20 |
| `injection_method` | str | 植入方式(便于溯源/复现) | 抽真空称重抽走 / 补注 / 阀门泄放 |

可选:`nominal_charge_g`(额定充注量,克)、`actual_charge_g`(实测充注量)、`note`(自由文本)、
`operator`、`date`。

## severity_unit 口径(方向待锁定 —— 交付前必须与数据方确认)

`severity` 的**方向未定**,数据方须在 `severity_unit` 显式声明,禁止混口径静默合并:
- `pct_removed`:抽走比例,0=额定、越大越欠充(如 0.20 = 抽走 20%);
- `pct_remaining`:剩余比例,1.0=额定、越小越欠充(如 0.80 = 剩 80%);
- `grams_removed`:抽走克数(需配 `nominal_charge_g` 换算)。

一次交付内**统一一种口径**;确认后本项目锁定并更新 c2_labels(移除 UNCONFIRMED 标)与
diag.severity_regression 的映射方向。

## 与管线的对接

1. 机台先进 `config/unit_sku_map.yaml`,`data_type: fault_injected`——c4 加载即把该机台
   数据排出健康基线池(rating_anchor=False),只入诊断/严重度链路。
2. 元数据经 M-LABEL(C2)进入 `severity`/`severity_unit` 字段(C2 LABEL_SCHEMA 已扩)。
3. 端到端:标签(带 severity)→ 残差(exv_resid/sc_resid/capacity_resid,制热主通道)
   → `diag.severity_regression`(桩,映射待拟合)→ C5 输出含 `severity`。
4. 梯度数据到货后,用多档 severity 的残差幅度拟合 `residual → undercharge%` 映射,
   替换 severity_regression 的占位尺度,置 `fitted=True`。

## 反面示例(拒收)

- 只有文件名 "欠充20%",无结构化 severity/severity_unit → 退回补元数据;
- severity=0.2 但无 severity_unit(方向不明)→ 退回;
- unit 未在 unit_sku_map.yaml 登记 → c4 报 UNMAPPED,数据不入池。
