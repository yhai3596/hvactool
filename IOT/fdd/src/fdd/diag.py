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
  mode="cooling" (FDD-I-019, replaces the former NotImplementedError sentinel):
    cooling decision order pinned by DK-015 — confirm superheat first, then subcooling:
      |sh_resid| <= SH_NORM_BAND_COOL and sc_resid < SC_LOW -> refrigerant_low_or_leak
        (early; sc_resid REQUIRED main channel; capacity_resid corroboration NOT gate)
      sh_resid > SH_HIGH_COOL and sc_resid < SC_LOW         -> refrigerant_low_or_leak
        (advanced; sh self-gated — TXV invisible, rising Sh IS metering-authority loss,
        no exv_saturated gate, DK-009-c)
      sh_resid > SH_HIGH_COOL and sc_resid > SC_HIGH        -> metering_restriction
      else (incl. exv_resid alone deviating)                -> none
    exv_resid is FORBIDDEN as cooling leak evidence (rule #17 / DK-009: cooling EEV is
    full-open non-servo; its only cooling semantics = EEV stuck / control anomaly).
    cooling sh_resid must be computed on the per-unit x same-bin reference plane
    (DK-017); cross-unit/global reference is forbidden upstream of this function.
    dsh_phys is annotation-only (DK-015): below DSH_SAFETY_MIN_K it appends a
    compressor-safety checklist line; never an AND gate; missing dsh_phys must run.

Trigger thresholds: heating = module constants (pinned; M4 recalibrates with labels);
cooling = config assets (config/calibration.yaml diag:, FDD-I-019-R1 mechanical #3).
confidence is a v0 placeholder constant per hypothesis — REPLACED at M4 by model scores.
"""
from fdd import config

# v0 trigger thresholds (pinned) — heating branch, untouched by FDD-I-019
EXV_UP = 10.0        # exv_resid >= EXV_UP
SC_DOWN = -0.8       # sc_resid <= SC_DOWN
CAP_DOWN = -0.05     # capacity_resid <= CAP_DOWN
SH_HIGH = 2.0        # sh_resid >= SH_HIGH (heating: only when exv_saturated, rule #3)

# cooling-branch thresholds (FDD-I-019): config assets, M4 recalibrates on UC gradient
SH_NORM_BAND_COOL = config.cal("diag.sh_norm_band_cool")   # K; plane: per_unit_bin (DK-017)
SH_HIGH_COOL = config.cal("diag.sh_high_cool")             # K; band edge = high threshold
SC_LOW = config.cal("diag.sc_low")                         # K
SC_HIGH = config.cal("diag.sc_high")                       # K; metering direction
CAP_LOW = config.cal("diag.cap_low")                       # fraction; corroboration only
DSH_SAFETY_MIN_K = config.cal("diag.dsh_safety_min_k")     # K; annotation band (provisional)

# v0 placeholder confidences — replaced by calibrated model scores at M4
CONFIDENCE = {"refrigerant_low_or_leak": 0.7, "indoor_side_nonspecific": 0.5,
              "metering_restriction": 0.65, "none": 0.1}
# cooling early-leak tiers (FDD-I-019): sc single-evidence < sc+capacity double-evidence;
# intrinsically below heating's three-feature 0.7 — the honest DK-009-e asymmetry,
# not to be artificially levelled.
CONFIDENCE_COOL = {"sc_only": 0.5, "sc_cap": 0.65}

FIELD_CHECKLIST = {
    "refrigerant_low_or_leak": [
        "检漏", "称重核对充注量", "查阀芯与喇叭口接头", "记录环温与运行模式",
    ],
    "indoor_side_nonspecific": [
        "核对内机匹配", "滤网与盘管清洁度", "风道风量",
    ],
    "metering_restriction": [
        "查内机节流件(TXV/毛细管)与过滤网堵塞", "查液管截止阀开度与管路折瘪", "记录环温与运行模式",
    ],
    "none": [],
}

_LP_KEYS = ("lp_resid", "lp_abs_resid", "te_sat_resid")   # additional evidence only


def _ev(feature: str, direction: int, magnitude: float) -> dict:
    return {"feature": feature, "direction": direction, "magnitude": abs(magnitude)}


def diagnose(row: dict, mode: str, exv_saturated: bool = False) -> dict:
    """C5-shaped diagnosis for one feature row (dict of residuals)."""
    if mode == "cooling":
        return _diagnose_cooling(row)
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

    # severity estimate for the undercharge hypothesis (FDD-I-012 #4): interface wired
    # end-to-end; the residual->undercharge-% mapping is a stub until the gradient data.
    severity = severity_regression(exv, sc, cap) if hypothesis == "refrigerant_low_or_leak" else None

    return {
        "fault_hypothesis": hypothesis,
        "evidence": evidence,
        "counter_evidence": counter,
        "confidence": CONFIDENCE[hypothesis],
        "field_checklist": list(FIELD_CHECKLIST[hypothesis]),
        "severity": severity,
    }


def _diagnose_cooling(row: dict) -> dict:
    """Cooling matrix (FDD-I-019; DK-009/DK-015/DK-016/DK-017). See module docstring
    for the pinned decision order. exv_resid NEVER enters evidence here (rule #17);
    a lone exv_resid deviation (EEV stuck / control anomaly class) is out of this
    batch -> v0 returns none."""
    sh = row.get("sh_resid", 0.0)
    sc = row.get("sc_resid", 0.0)
    cap = row.get("capacity_resid", 0.0)

    sh_normal = abs(sh) <= SH_NORM_BAND_COOL
    sh_high = sh > SH_HIGH_COOL
    sc_low = sc < SC_LOW
    sc_high = sc > SC_HIGH
    cap_low = cap < CAP_LOW

    evidence, counter = [], []
    if sh_normal and sc_low:
        # C-early leak (DK-015 order: SSH normal -> judge SC; SC low = classic early
        # undercharge). sc_resid REQUIRED main channel (interview 1.2); capacity_resid
        # corroboration, NOT a hard gate (FDD-I-019 star change: +7% controller-capacity
        # bias constancy unverified -> hard-gating it risks false negatives); sh stays
        # context only, never evidence here.
        hypothesis = "refrigerant_low_or_leak"
        evidence.append(_ev("sc_resid", -1, sc))
        if cap_low:
            evidence.append(_ev("capacity_resid", -1, cap))
            confidence = CONFIDENCE_COOL["sc_cap"]
        else:
            confidence = CONFIDENCE_COOL["sc_only"]
    elif sh_high and sc_low:
        # C-advanced leak: no exv_saturated gate (DK-009-c: the indoor TXV is invisible;
        # a rising Sh IS the metering-authority-loss signal — self-gated).
        hypothesis = "refrigerant_low_or_leak"
        evidence.append(_ev("sh_resid", +1, sh))
        evidence.append(_ev("sc_resid", -1, sc))
        if cap_low:
            evidence.append(_ev("capacity_resid", -1, cap))
        confidence = CONFIDENCE[hypothesis]
    elif sh_high and sc_high:
        # C-metering restriction: SC positive is intrinsically counter-evidence to
        # refrigerant_low -> minimal D-N4 counter template (Hp corroboration = M4).
        hypothesis = "metering_restriction"
        evidence.append(_ev("sh_resid", +1, sh))
        evidence.append(_ev("sc_resid", +1, sc))
        counter.append({**_ev("sc_resid", +1, sc), "against": "refrigerant_low_or_leak"})
        confidence = CONFIDENCE[hypothesis]
    else:
        hypothesis = "none"
        confidence = CONFIDENCE[hypothesis]

    checklist = list(FIELD_CHECKLIST[hypothesis])
    dsh = row.get("dsh_phys")
    if dsh is not None and dsh == dsh and dsh < DSH_SAFETY_MIN_K:
        # annotation ONLY (DK-015): compressor-safety line; never an AND gate; the
        # optional confidence markdown ("可下调") is NOT enacted pending Alan's value.
        checklist.append(f"排气过热度低于安全参考带(dsh_phys<{DSH_SAFETY_MIN_K:.0f}K):压缩机回液/湿压缩安全核查")

    severity = (severity_regression(0.0, sc, cap)
                if hypothesis == "refrigerant_low_or_leak" else None)
    return {
        "fault_hypothesis": hypothesis,
        "evidence": evidence,
        "counter_evidence": counter,
        "confidence": confidence,
        "field_checklist": checklist,
        "severity": severity,
    }


# undercharge-severity residual scales (unfitted placeholders — the real scale comes from
# regressing the undercharge gradient data). Heating main channels only (rule #3: Sh is
# servo-pinned in heating; leak carrier = exv_resid + sc_resid + capacity_resid).
_SEV_EXV_SCALE = 50.0        # exv_resid span across the undercharge gradient (placeholder)
_SEV_SC_SCALE = 5.0          # -sc_resid span (placeholder)
_SEV_CAP_SCALE = 0.20        # -capacity_resid span (placeholder)


def severity_regression(exv_resid: float, sc_resid: float, capacity_resid: float) -> dict:
    """Undercharge severity from heating main-channel residual magnitudes
    (exv_resid up, sc_resid down, capacity_resid down).

    STUB (FDD-I-012 #4): the residual-magnitude -> undercharge-% MAPPING awaits the
    undercharge gradient data (72 h). This is NOT NotImplementedError — the end-to-end
    chain (label -> residual -> severity -> C5) runs today; only the fitted scale is
    pending. `estimate` is a monotone, direction-correct proxy in [0,1] (0 = nominal,
    1 = severe) built from unfitted per-channel scales; `fitted=False` marks it
    provisional; `unit` carries the UNCONFIRMED convention until the data team locks the
    undercharge-% direction (see c2_labels.SEVERITY_UNIT_UNCONFIRMED)."""
    from fdd.contracts.c2_labels import SEVERITY_UNIT_UNCONFIRMED
    proxy = (max(exv_resid, 0.0) / _SEV_EXV_SCALE
             + max(-sc_resid, 0.0) / _SEV_SC_SCALE
             + max(-capacity_resid, 0.0) / _SEV_CAP_SCALE) / 3.0
    return {
        "estimate": float(min(max(proxy, 0.0), 1.0)),
        "unit": SEVERITY_UNIT_UNCONFIRMED,
        "method": "unfitted_monotone_proxy",
        "fitted": False,
    }
