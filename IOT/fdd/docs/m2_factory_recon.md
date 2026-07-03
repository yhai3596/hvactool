# M2 工厂(商检/产线)样本侦察·初步(2026-07-04,零明文 SN 入本文)

范围:data/raw/factory/{2024,2025}商检数据,共 3,465 文件(含产线检测软件 exe/zip 与
ECOER_ProductionLine_Log_*.csv 日志;软件版本 ver0_7_12 / v0_8_3 并存)。本文为首轮结构侦察,
逐工位全量统计(SN 唯一计数全集、ResultOK/NG 全量分布、WM 功率一致性抽样、四通阀极性全量核验)
待下轮专项——文件量大,按台账逐项收口。

## 1. 结构(首文件抽样)
列 34,与 wade factory 表行数一致:Time, PCB_SerialNo, ODU_SerialNo, Ton(3/5Ton), Main-Soft,
INV-Soft, LineMode, PFC, 4-way-valve, INV, EEV, Fan, Hp, Lp, Ta, Ts, Th, **TL(大写)**, TL2, Td, Tf,
Volt2, Current2, Volt1, ErrCode, RunTime, LineDrive, ResultOK, ResultNG, WM_Voltage, WM_Current,
WM_ElectricPower, WM_Frequency, WM_Power Factor。

- Time 仅时分秒 → 日期锚取文件名 ECOER_ProductionLine_Log_YYYYMMDDHHMMSS(与 RamChecker 同方案)。
- SN 双字段:ODU_SerialNo 20 字符(样式 0E×××…),抽样文件内唯一数 22;PCB_SerialNo 早行为占位 "--"
  后现真值——先于 ODU SN 出现(与 wade 注释一致)。本文只报样式与计数,明文永不入产出物。
- ResultOK/ResultNG ∈ {0,1} 双列并存(抽样确认存在,全量分布待专项)。
- 四通阀列名为 `4-way-valve`;极性核验(制热段应为 0,St=1−value)待全量专项。

## 2. c4 产线映射草案(已入码,c4.py)
- FACTORY_RENAME 草案:TL→Tl(大小写归一)、TL2→Tl2、EEV→Exv、Volt1→V1、Current2→I2、ErrCode→Error_Code。
- **St = 1 − `4-way-valve`(极性钉死待全量核验后生效)**。
- 双假名化:ODU_SerialNo→hash_sn、PCB_SerialNo→hash_pcb_sn,协议见 CLAUDE.md 数据安全区。
- load_prodline 在 FDD_HMAC_KEY 未设时**明确拒绝运行**(已实现,先于任何读取)。
