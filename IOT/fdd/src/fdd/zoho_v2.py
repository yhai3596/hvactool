"""M-ZOHO-V2: the 8 fixes to the label pipeline. Milestone: M0.

Runs on the FULL Zoho export in the company environment; this repo tests it on a
synthetic fixture only (tests/fixtures/zoho_synthetic.csv). Never commit real exports.

Fixes (CLAUDE.md): 1 drop cleartext SN in ai_safe outputs; 2 date clamp [2018, today]
with fallback+flag; 3 event-before-ticket window fields; 4 queue re-ranking
(family value x multi ambiguity x low confidence x recency; top-500 refrigerant share >=30%);
5 series->SKU scope flag; 6 UTF-8 everywhere; 7 repair-action standardization -> L2;
8 SN-type classifier (ODU/IDU/gateway by encoding rules) to auto-resolve valid_multiple.
"""
import pandas as pd

FAMILY_FDD_VALUE = {"refrigerant_low_or_leak": 5, "fan_motor_fault": 4, "compressor_fault": 4,
                    "sensor_fault": 3, "eev_fault": 3, "main_board_fault": 2, "noise": 1}

REPAIR_ACTION_MAP = {
    # keyword patterns -> canonical action; extend during review
    "recharge|refrigerant added|leak repair": "refrigerant_recharge",
    "sensor repl|thermistor": "sensor_replace",
    "board repl|pcb|control board": "board_replace",
    "motor repl|fan motor": "motor_replace",
    "compressor repl": "compressor_replace",
}

def clamp_dates(df: pd.DataFrame, today: str) -> pd.DataFrame:
    """Fix #2. Adds date_flag column; out-of-window Failure Dates fall back to Created Time."""
    raise NotImplementedError

def classify_sn_type(sn: str, encoding_rules: dict) -> str:
    """Fix #8. Returns 'odu'|'idu'|'gateway'|'unknown'. encoding_rules pending O6;
    until provided, operate in 'unknown' passthrough mode (no resolution claimed)."""
    raise NotImplementedError

def rerank_queue(df: pd.DataFrame, top_n: int = 500) -> pd.DataFrame:
    """Fix #4. Deterministic score; DoD: refrigerant share of top-500 >= 0.30 on fixture."""
    raise NotImplementedError

def make_ai_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Fix #1/#5/#6. Drops normalized_sn and any PII-bearing columns; asserts absence."""
    raise NotImplementedError

def standardize_repair_action(text: str) -> str | None:
    """Fix #7. Map free-text resolution to canonical action (L2 label input)."""
    raise NotImplementedError
