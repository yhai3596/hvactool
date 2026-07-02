"""C2 label contract. Label credibility tiers L0-L4 (adopted from external review, 2026-07-02).

Training admission (rule: label hygiene): only L3/L4, or (sn_status=='valid' AND review_state=='confirmed').
'valid_multiple_candidates' NEVER enters training unresolved.
"""
from enum import IntEnum

class LabelTier(IntEnum):
    L0_PHENOMENON = 0     # subject/description text
    L1_FAULT_CODE = 1     # Error Code / platform code / protection bit
    L2_REPAIR_ACTION = 2  # standardized repair action (recharge / sensor swap / board swap / motor swap)
    L3_ENGINEER_ROOT = 3  # human-confirmed root cause
    L4_RECOVERY_VERIFIED = 4  # post-repair residual returned to baseline (auto-verifiable)

FAULT_FAMILIES = ["refrigerant_low_or_leak","compressor_fault","fan_motor_fault","main_board_fault",
                  "sensor_fault","eev_fault","noise","power_voltage_issue",
                  "installation_or_matching_issue","iot_gateway_issue","thermostat_or_control_issue",
                  "filter_or_maintenance","customer_inquiry_or_non_fault","unknown"]

LABEL_SCHEMA = ["hash_sn","fault_family","event_date","date_source","fault_confidence",
                "sn_status","label_tier","review_state","repair_action","repair_date"]

DATE_VALID_WINDOW = ("2018-01-01", None)   # None -> generation date; out-of-range -> fallback Created Time + flag
