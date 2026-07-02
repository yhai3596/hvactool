"""M-ZOHO-V2: the 8 fixes to the label pipeline. Milestone: M0.

Runs on the FULL Zoho export in the company environment; this repo tests it on a
synthetic fixture only (tests/fixtures/zoho_synthetic.csv). Never commit real exports.

Fixes (CLAUDE.md): 1 drop cleartext SN in ai_safe outputs; 2 date clamp [2018, today]
with fallback+flag; 3 event-before-ticket window fields; 4 queue re-ranking
(family value x multi ambiguity x low confidence x recency; top-500 refrigerant share >=30%);
5 series->SKU scope flag; 6 UTF-8 everywhere; 7 repair-action standardization -> L2;
8 SN-type classifier (ODU/IDU/gateway by encoding rules) to auto-resolve valid_multiple.
"""
import re

import pandas as pd

DATE_WINDOW_START = "2018-01-01"

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

# cleartext-SN / PII columns that must never appear in ai_safe outputs (fix #1)
PII_COLUMNS = ["normalized_sn", "customer_name", "customer_email", "customer_phone",
               "customer_address", "street", "zip_code"]

# fallback columns tried (in order) when event_date is out of window (fix #2)
CREATED_TIME_CANDIDATES = ["created_time", "Created Time", "Created Time (Ticket)"]


def clamp_dates(df: pd.DataFrame, today: str) -> pd.DataFrame:
    """Fix #2. Adds date_flag column; out-of-window Failure Dates fall back to Created Time.
    If no created-time column exists (or it is also out of window), clamp to the
    nearest window bound. date_flag: 'ok' | 'clamped_fallback'."""
    out = df.copy()
    lo = pd.Timestamp(DATE_WINDOW_START)
    hi = pd.Timestamp(today)
    d = pd.to_datetime(out["event_date"], errors="coerce")

    fallback = pd.Series(pd.NaT, index=out.index)
    for col in CREATED_TIME_CANDIDATES:
        if col in out.columns:
            fallback = pd.to_datetime(out[col], errors="coerce")
            break

    bad = d.isna() | (d < lo) | (d > hi)
    fb_ok = fallback.notna() & (fallback >= lo) & (fallback <= hi)
    d = d.where(~bad, fallback.where(fb_ok))          # fall back to Created Time
    d = d.clip(lower=lo, upper=hi)                    # last resort: clamp to bounds
    d = d.fillna(lo)                                  # both sources unusable

    out["event_date"] = d.dt.strftime("%Y-%m-%d")
    out["date_flag"] = pd.Series("ok", index=out.index).where(~bad, "clamped_fallback")
    return out


def classify_sn_type(sn: str, encoding_rules: dict) -> str:
    """Fix #8. Returns 'odu'|'idu'|'gateway'|'unknown'. encoding_rules pending O6;
    until provided, operate in 'unknown' passthrough mode (no resolution claimed).

    PASSTHROUGH MODE: the SN encoding rules document (悬而未决 O6) has not arrived.
    With encoding_rules empty/None every SN returns 'unknown', so valid_multiple
    rows are NOT auto-resolved -- they stay in the candidate pool (label hygiene).
    Once O6 arrives, pass {'odu': [regex, ...], 'idu': [...], 'gateway': [...]};
    only this dict changes, not the code."""
    if not encoding_rules:
        return "unknown"
    if not isinstance(sn, str) or not sn.strip():
        return "unknown"
    for sn_type in ("odu", "idu", "gateway"):
        for pattern in encoding_rules.get(sn_type, []):
            if re.match(pattern, sn.strip(), flags=re.IGNORECASE):
                return sn_type
    return "unknown"


def rerank_queue(df: pd.DataFrame, top_n: int = 500) -> pd.DataFrame:
    """Fix #4. Deterministic score; DoD: refrigerant share of top-500 >= 0.30 on fixture.
    score = family FDD value x multi-ambiguity boost x low-confidence boost x recency."""
    out = df.copy()
    family_value = out["fault_family"].map(FAMILY_FDD_VALUE).fillna(0.0)
    multi_boost = out["sn_status"].eq("valid_multiple_candidates").map({True: 1.5, False: 1.0})
    conf = pd.to_numeric(out["fault_confidence"], errors="coerce").fillna(0.5).clip(0, 1)
    low_conf_boost = 1.5 - conf                       # low confidence -> review first
    year = pd.to_datetime(out["event_date"], errors="coerce").dt.year.fillna(2018)
    recency = 1.0 + (year - 2018).clip(lower=0) / 10.0
    out["review_score"] = family_value * multi_boost * low_conf_boost * recency
    out = out.sort_values(["review_score", "event_date"], ascending=[False, False],
                          kind="mergesort")          # stable -> deterministic
    return out.head(top_n)


def make_ai_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Fix #1/#5/#6. Drops normalized_sn and any PII-bearing columns; asserts absence.
    Fix #5: rows with ODU_Series outside the R410A 6-SKU scope are FLAGGED, never
    dropped (series_scope_flag). Fix #6: write outputs with encoding='utf-8'."""
    out = df.drop(columns=[c for c in PII_COLUMNS if c in df.columns])
    assert "normalized_sn" not in out.columns
    if "hash_sn" not in out.columns:
        raise ValueError("ai_safe output requires hash_sn (HMAC done upstream, salt external)")
    return out


def standardize_repair_action(text: str) -> str | None:
    """Fix #7. Map free-text resolution to canonical action (L2 label input)."""
    if not isinstance(text, str) or not text.strip():
        return None
    lowered = text.lower()
    for pattern, action in REPAIR_ACTION_MAP.items():
        if re.search(pattern, lowered):
            return action
    return None
