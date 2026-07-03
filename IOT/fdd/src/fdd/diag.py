"""M-DIAG diagnosis skeleton (M1). v0 = hardcoded physics priors; replaced by
interpretable trees at M4. Rule #3 binds (heating Sh is servo-pinned: sh evidence
only after EEV saturation).

API pinned by tests/test_m1_valid.py + module instruction (pins, no local freedom):
  diagnose(row: dict, mode: str, exv_saturated: bool = False) -> dict (C5-shaped)
    heating decision order (locked):
      EXV_UP and SC_DOWN and CAP_DOWN            -> refrigerant_low_or_leak
      else CAP_DOWN and not EXV_UP and not SC_DOWN -> indoor_side_nonspecific
      else                                        -> none
    lp-class keys: absent -> no part in the decision; present -> additional evidence
    only (no pinned threshold yet; direction-consistent values recorded, M4 calibrates).
    exv_saturated is CONSUMED here, never derived (saturation detection wires up at the
    integration layer, not in this skeleton).
  mode="cooling" raises NotImplementedError — the cooling matrix lands with M2 data;
  no speculative branch without tests.

Trigger thresholds are module constants (pinned; M4 recalibrates with labels).
confidence is a v0 placeholder constant per hypothesis — REPLACED at M4 by model scores.
"""

# v0 trigger thresholds (pinned)
EXV_UP = 10.0        # exv_resid >= EXV_UP
SC_DOWN = -0.8       # sc_resid <= SC_DOWN
CAP_DOWN = -0.05     # capacity_resid <= CAP_DOWN
SH_HIGH = 2.0        # sh_resid >= SH_HIGH (heating: only when exv_saturated, rule #3)

# v0 placeholder confidences — replaced by calibrated model scores at M4
CONFIDENCE = {"refrigerant_low_or_leak": 0.7, "indoor_side_nonspecific": 0.5, "none": 0.1}

FIELD_CHECKLIST = {
    "refrigerant_low_or_leak": [
        "检漏", "称重核对充注量", "查阀芯与喇叭口接头", "记录环温与运行模式",
    ],
    "indoor_side_nonspecific": [
        "核对内机匹配", "滤网与盘管清洁度", "风道风量",
    ],
    "none": [],
}

_LP_KEYS = ("lp_resid", "lp_abs_resid", "te_sat_resid")   # additional evidence only


def _ev(feature: str, direction: int, magnitude: float) -> dict:
    return {"feature": feature, "direction": direction, "magnitude": abs(magnitude)}


def diagnose(row: dict, mode: str, exv_saturated: bool = False) -> dict:
    """C5-shaped diagnosis for one feature row (dict of residuals)."""
    if mode == "cooling":
        raise NotImplementedError("制冷矩阵随 M2 数据落地")
    if mode != "heating":
        raise ValueError(f"unknown mode: {mode!r}")

    exv = row.get("exv_resid", 0.0)
    sc = row.get("sc_resid", 0.0)
    cap = row.get("capacity_resid", 0.0)

    exv_up = exv >= EXV_UP
    sc_down = sc <= SC_DOWN
    cap_down = cap <= CAP_DOWN

    if exv_up and sc_down and cap_down:
        hypothesis = "refrigerant_low_or_leak"
    elif cap_down and not exv_up and not sc_down:
        hypothesis = "indoor_side_nonspecific"
    else:
        hypothesis = "none"

    evidence, counter = [], []
    if exv_up:
        evidence.append(_ev("exv_resid", +1, exv))
    if sc_down:
        evidence.append(_ev("sc_resid", -1, sc))
    if cap_down:
        evidence.append(_ev("capacity_resid", -1, cap))
    # counter-evidence: opposite direction beyond the mirrored limit (may be empty)
    if exv <= -EXV_UP:
        counter.append(_ev("exv_resid", -1, exv))
    if sc >= -SC_DOWN:
        counter.append(_ev("sc_resid", +1, sc))
    if cap >= -CAP_DOWN:
        counter.append(_ev("capacity_resid", +1, cap))

    # lp-class keys: additional evidence only, never part of the decision
    if hypothesis == "refrigerant_low_or_leak":
        for k in _LP_KEYS:
            if k in row and row[k] < 0:
                evidence.append(_ev(k, -1, row[k]))

    # rule #3: heating sh evidence gated on EEV saturation (flag consumed, not derived)
    if exv_saturated and row.get("sh_resid", 0.0) >= SH_HIGH:
        evidence.append(_ev("sh_resid", +1, row["sh_resid"]))

    return {
        "fault_hypothesis": hypothesis,
        "evidence": evidence,
        "counter_evidence": counter,
        "confidence": CONFIDENCE[hypothesis],
        "field_checklist": list(FIELD_CHECKLIST[hypothesis]),
    }
