"""M-CONV physical conversion library. Milestone: M0.

Materializes C1 derived columns. Hard rules #1 #2 #3 #4 bind here.
DoD (tests/test_m0_conv.py):
  - |sh_phys - reported Sh| P95 <= 0.15 K on sample, excluding St==0 rows
  - (sc_phys - reported Sc) == 1.0 +/- 0.1 on run segments
  - lp_abs == Lp + 1.013 exactly
"""
import pathlib

import numpy as np
import pandas as pd
from CoolProp.CoolProp import PropsSI

from fdd.contracts.c1_telemetry import ACSTATE, ATM_OFFSET_BAR, REFRIGERANT

BAR_TO_PA = 1e5
_PCRIT_PA = PropsSI("PCRIT", REFRIGERANT)   # saturation undefined at/above critical

# Precomputed R410A saturation table (scripts/gen_sat_table.py). M3 processes billions of
# rows; per-row PropsSI is slow and native-segfault-prone at scale, so te_sat/tc_sat
# interpolate this table (no native calls in the hot path). SAME physics as CoolProp,
# cached; interpolation error < 0.01 K (verified on lab data). Falls back to PropsSI if
# the table file is absent.
_SAT_TABLE_PATH = pathlib.Path(__file__).with_name("sat_table.npz")
try:
    _t = np.load(_SAT_TABLE_PATH)
    _SAT_P, _SAT_DEW, _SAT_BUBBLE = _t["p_bar"], _t["dew_c"], _t["bubble_c"]
except Exception:                            # table missing -> PropsSI fallback
    _SAT_P = _SAT_DEW = _SAT_BUBBLE = None


def _sat_temp_c_table(p_abs_bar, quality: float) -> np.ndarray:
    """Interpolated R410A saturation temp (deg C) from the precomputed table; NaN outside
    the table domain. quality 1.0 -> dew (suction/te), 0.0 -> bubble (liquid/tc)."""
    if _SAT_P is None:
        return _sat_temp_c(p_abs_bar, quality)
    p = np.asarray(p_abs_bar, dtype=float)
    tab = _SAT_DEW if quality == 1.0 else _SAT_BUBBLE
    out = np.interp(p, _SAT_P, tab, left=np.nan, right=np.nan)
    return np.where(np.isfinite(p), out, np.nan)

# Slip normalization full-scales. Command scales come from the C1 contract;
# actual-side scales are sample-derived (CompRps ~ 2.5 x Comp cmd) and pending
# confirmation -- centralized here so confirmation is a one-line change.
COMP_CMD_FULLSCALE = 50.0
COMP_RPS_FULLSCALE = 125.0      # unverified: 50 cmd x ~2.5 rps/cmd observed on sample
FAN_CMD_FULLSCALE = 10.0
FAN_RPM_FULLSCALE = 1500.0
FAN_RATED_W_UNVERIFIED = 150.0  # placeholder rating for fan power est., pending fan curve

# Controller firmware saturation-table replica (NOT physics). Empirically the
# firmware's implied Tsat matches CoolProp R410A evaluated at
# (0.980665 * gauge + 1.0133) bar abs across the full sample pressure range
# (deviation ~ -2.0% of abs pressure on both sides, = kgf/cm2 -> bar factor).
# Vendor confirms sensor readings are bar (value/10 = MPa), so the bias lives in
# the firmware lookup table (axis likely kgf/cm2). Pending vendor confirmation
# (CLAUDE.md 悬而未决). Physical columns must NEVER use these constants.
CTRL_TABLE_PRESSURE_SCALE = 0.980665
CTRL_TABLE_ATM_BAR = 1.0133


def saturation_temp_c(p_abs_bar: float, side: str) -> float:
    """R410A saturation temperature (deg C) at absolute pressure (bar).
    side: 'low' -> dew point (suction), 'high' -> bubble point (liquid).
    R410A is a near-azeotrope, glide ~0.1K, but use dew for Sh and bubble
    for Sc to match convention."""
    if side == "low":
        q = 1.0
    elif side == "high":
        q = 0.0
    else:
        raise ValueError(f"side must be 'low' or 'high', got {side!r}")
    return PropsSI("T", "P", p_abs_bar * BAR_TO_PA, "Q", q, REFRIGERANT) - 273.15


def _sat_temp_c(p_abs_bar: pd.Series, quality: float) -> np.ndarray:
    """Vectorized saturation temperature; NaN where pressure is out of the
    two-phase domain instead of raising."""
    p_pa = p_abs_bar.to_numpy(dtype=float) * BAR_TO_PA
    out = np.full(p_pa.shape, np.nan)
    valid = np.isfinite(p_pa) & (p_pa > 0.0) & (p_pa < _PCRIT_PA)
    if valid.any():
        out[valid] = PropsSI("T", "P", p_pa[valid], "Q", quality, REFRIGERANT) - 273.15
    return out


def fan_power_est(fan_rpm: pd.Series) -> np.ndarray:
    """Fan power estimate via cubic affinity law on rpm fraction.
    Rating is a placeholder constant until the fan curve is confirmed."""
    frac = np.clip(np.asarray(fan_rpm, dtype=float) / FAN_RPM_FULLSCALE, 0.0, None)
    return FAN_RATED_W_UNVERIFIED * frac ** 3


def controller_sat_temp_c(p_gauge_bar: pd.Series, side: str) -> np.ndarray:
    """REPLICA of the controller firmware's pressure -> saturation-temperature
    lookup, for controller-consistency checks ONLY -- not a physical quantity.
    side: 'low' -> dew, 'high' -> bubble (same convention as saturation_temp_c).
    Physical te_sat/tc_sat use lp_abs/hp_abs directly (rule #1)."""
    if side == "low":
        q = 1.0
    elif side == "high":
        q = 0.0
    else:
        raise ValueError(f"side must be 'low' or 'high', got {side!r}")
    p_used = pd.Series(p_gauge_bar, dtype=float) * CTRL_TABLE_PRESSURE_SCALE + CTRL_TABLE_ATM_BAR
    return _sat_temp_c(p_used, quality=q)


def firmware_sh_replica(df: pd.DataFrame) -> pd.Series:
    """Replica of the CONTROLLER's reported Sh, for bias cross-validation ONLY.
    Must NEVER participate in the definition of sh_phys (rule: physical columns
    use CoolProp at lp_abs/hp_abs, nothing else)."""
    te_ctrl = pd.Series(controller_sat_temp_c(df["Lp"], "low"), index=df.index)
    return df["Ts"] - te_ctrl


def firmware_sc_replica(df: pd.DataFrame) -> pd.Series:
    """Replica of the CONTROLLER's tc_sat - Tl (before its -1 display bias),
    for bias cross-validation ONLY. Must NEVER participate in sc_phys."""
    tc_ctrl = pd.Series(controller_sat_temp_c(df["Hp"], "high"), index=df.index)
    return tc_ctrl - df["Tl"]


def materialize(df: pd.DataFrame) -> pd.DataFrame:
    """Add all C1 DERIVED columns to a raw telemetry frame. Vectorized; no external calls.
    Must NOT mutate input. Must NOT apply any altitude correction (rule #1).
    sc_phys = tc_sat - Tl  (rule #2: strip the -1)."""
    out = df.copy()
    out["lp_abs"] = out["Lp"] + ATM_OFFSET_BAR          # rule #1: fixed offset only
    out["hp_abs"] = out["Hp"] + ATM_OFFSET_BAR
    out["te_sat"] = _sat_temp_c_table(out["lp_abs"], quality=1.0)   # dew (table interp)
    out["tc_sat"] = _sat_temp_c_table(out["hp_abs"], quality=0.0)   # bubble (table interp)
    out["sc_phys"] = out["tc_sat"] - out["Tl"]          # rule #2: no -1 term
    out["sh_phys"] = out["Ts"] - out["te_sat"]
    out["dsh_phys"] = out["Td"] - out["tc_sat"]         # discharge superheat (D-N6, FDD-I-019)
    out["mode"] = out["AcState"].map(ACSTATE).fillna("unknown")
    out["reversing"] = out["St"]                        # rule #7: 4-way valve position
    out["tcs_gap"] = out["tc_sat"] - out["Tcs"]         # rule #8: target, not measurement
    out["p_parasitic"] = out["PowerIn"] - out["PowerComp"] - fan_power_est(out["FanRpm"])
    out["comp_slip"] = (out["Comp"] / COMP_CMD_FULLSCALE
                        - out["CompRps"] / COMP_RPS_FULLSCALE).abs()
    out["fan_slip"] = (out["Fan"] / FAN_CMD_FULLSCALE
                       - out["FanRpm"] / FAN_RPM_FULLSCALE).abs()
    return out


def verify_against_controller(df: pd.DataFrame) -> dict:
    """Cross-check sh_phys/sc_phys vs reported Sh/Sc. Returns
    {'sh_p95_diff': float, 'sc_offset_mean': float, 'sc_offset_std': float,
     'n_checked': int} with St==0 rows excluded from the Sh check."""
    out = df if "sh_phys" in df.columns else materialize(df)
    sh_diff = (out["sh_phys"] - out["Sh"]).abs()
    sh_diff = sh_diff[out["St"] == 1]
    run = out["CompState"] == 1
    sc_offset = out.loc[run, "sc_phys"] - out.loc[run, "Sc"]
    return {
        "sh_p95_diff": float(sh_diff.quantile(0.95)),
        "sc_offset_mean": float(sc_offset.mean()),
        "sc_offset_std": float(sc_offset.std()),
        "n_checked": int(sh_diff.notna().sum()),
    }
