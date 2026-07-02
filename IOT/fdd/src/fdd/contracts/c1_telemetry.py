"""C1 telemetry contract: 48 locked raw columns + derived columns materialized at ingest.

Hard rules bound here (CLAUDE.md #1,#2,#4,#7,#8):
- abs pressure = gauge + ATM_OFFSET_BAR exactly (sealed gauge). No altitude term.
- sc_phys strips the controller's -1 display bias.
- p_parasitic uses PowerIn - PowerComp - fan estimate; efficiency features must NOT use PowerIn.
"""
ATM_OFFSET_BAR = 1.013          # sealed-gauge fixed offset, fleet-wide
REFRIGERANT = "R410A"

RAW_COLUMNS = [
    "Timestamp","DayTime","AcState","CompState",
    "HpLimit","LpLimit","TdLimit","TfLimit","I2Limit","I1Limit","WetLimit","DsmLimit","CoolantLackLimit",
    "Ta","Td","Ts","Th","Tl","Tf","Lp","Hp","V2","I2","Comp","Fan","Exv",
    "St","Cch","Tes","Tcs","N0","Sc","Sh","Qc","Qh","V1","I1",
    "PowerIn","PowerCompTheo","PowerComp","YSignal","OSignal","CompRps","FanRpm","V12","V15","WSignal","Dipsw",
]

DERIVED = {
    "lp_abs":      "Lp + ATM_OFFSET_BAR",
    "hp_abs":      "Hp + ATM_OFFSET_BAR",
    "te_sat":      "CoolProp Tsat(lp_abs, R410A, dew)",
    "tc_sat":      "CoolProp Tsat(hp_abs, R410A, bubble)",
    "sc_phys":     "tc_sat - Tl            # NO -1 (rule #2)",
    "sh_phys":     "Ts - te_sat",
    "reversing":   "St                     # 1 heating position, 0 defrost/cooling (rule #7)",
    "tcs_gap":     "tc_sat - Tcs           # control-target tracking gap (rule #8)",
    "p_parasitic": "PowerIn - PowerComp - fan_power_est",
    "comp_slip":   "normalized |Comp_cmd - CompRps| (command 0-50 vs actual rps)",
    "fan_slip":    "normalized |Fan_cmd - FanRpm|  (command 0-10 vs actual rpm 0-1500)",
}

# AcState dictionary (locked, from field spec + 24V logic sheet + data verification)
ACSTATE = {1:"normal_stop",2:"abnormal_stop",3:"waiting",4:"cooling",5:"heating",
           6:"oil_return",7:"defrost",11:"cool_dehum",12:"dehum_only",13:"humid_only",
           14:"heat_humid",15:"emergency_heat",16:"fan_only",17:"gas_heat"}
COMPSTATE = {0:"off",1:"run",2:"special_program"}   # 2 = defrost OR periodic low-freq program; both excluded from steady state
