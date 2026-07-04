"""M-DRIFT drift detection (M1). CUSUM + robust scale per (SN x feature x bin). Rule #8 binds.

API pinned by tests/test_m1_drift.py (docstring is the spec — no local freedom):
  BASELINE_N = 28                       # sigma/mu0 estimation window (leading points)
  robust_sigma(x)                       # 1.4826 * median(|x - median(x)|)  (MAD scale)
  cusum_detect(x, sigma, k=0.5, h=5.0)  # two-sided tabular CUSUM; mu0 = median of first
                                        # BASELINE_N points; onset_idx = first index where a
                                        # decision statistic crosses h*sigma
  detect(df, value_col, group_cols)     # one row per group; per-group sigma from the
                                        # group's first BASELINE_N points
  classify_channel(directions, thermostat_changed, tcs_gap_drift)
                                        # learning/fault dual channel per rule #8 (locked table)
  synthetic_ramp_report()               # 30/60/90-day ramps, deterministic seeds

Pinned guard: sigma_eff = max(robust_sigma, SIGMA_FLOOR) — a zero-variance group must not
divide-by-zero, and with no subsequent deviation must stay alarm=False.

k/h are module constants for M1; real calibration deferred to M4 (labeled data).
"""
import numpy as np
import pandas as pd

from fdd import config

# calibration from config/calibration.yaml (FDD-I-012 #2); k/h re-cal on labels at M4
BASELINE_N = config.cal("drift.baseline_n")
CUSUM_K = config.cal("drift.cusum_k")   # slack, in sigma units
CUSUM_H = config.cal("drift.cusum_h")   # decision threshold, in sigma units
SIGMA_FLOOR = 1e-9      # zero-variance guard (pinned)

# rule #8 channel discrimination feature sets (locked)
ACTUATOR_FEATURES = ("exv_resid", "comp_slip", "fan_slip")
REFRIGERANT_FEATURES = ("sc_resid", "capacity_resid")


def robust_sigma(x) -> float:
    """MAD-based robust scale: 1.4826 * median(|x - median(x)|)."""
    x = np.asarray(x, dtype=float)
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def cusum_detect(x, sigma: float, k: float = CUSUM_K, h: float = CUSUM_H) -> dict:
    """Two-sided tabular CUSUM. mu0 = median of the first BASELINE_N points.
    Returns {"alarm": bool, "onset_idx": int|None, "direction": +1/-1/0};
    onset_idx = first index where a decision statistic crosses h*sigma."""
    x = np.asarray(x, dtype=float)
    sigma_eff = max(float(sigma), SIGMA_FLOOR)
    mu0 = float(np.median(x[:BASELINE_N]))
    slack = k * sigma_eff
    thresh = h * sigma_eff
    s_hi = s_lo = 0.0
    for i, v in enumerate(x):
        d = v - mu0
        s_hi = max(0.0, s_hi + d - slack)
        s_lo = max(0.0, s_lo - d - slack)
        if s_hi > thresh:
            return {"alarm": True, "onset_idx": i, "direction": 1}
        if s_lo > thresh:
            return {"alarm": True, "onset_idx": i, "direction": -1}
    return {"alarm": False, "onset_idx": None, "direction": 0}


def detect(df: pd.DataFrame, value_col: str, group_cols) -> pd.DataFrame:
    """Run CUSUM per group (e.g. SN x feature x bin). One row per group:
    [*group_cols, alarm, onset_idx, direction]. Per-group sigma is estimated
    on the group's first BASELINE_N points (robust_sigma, floored)."""
    group_cols = list(group_cols)
    rows = []
    for key, g in df.groupby(group_cols, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        vals = g[value_col].to_numpy(dtype=float)
        r = cusum_detect(vals, robust_sigma(vals[:BASELINE_N]))
        rows.append({**dict(zip(group_cols, key)), **r})
    return pd.DataFrame(rows, columns=[*group_cols, "alarm", "onset_idx", "direction"])


def classify_channel(directions: dict, thermostat_changed: bool, tcs_gap_drift: bool) -> str:
    """Learning/fault dual-channel discrimination (rule #8, locked table):
      fault      := (actuator drift AND any refrigerant residual drift) OR tcs_gap_drift
      learning   := actuator-only drift AND thermostat_changed AND not tcs_gap_drift
      none       := no drift anywhere AND not tcs_gap_drift
      ambiguous  := everything else
    directions: {feature_name: +1/-1/0}."""
    actuator = any(directions.get(f, 0) != 0 for f in ACTUATOR_FEATURES)
    refrigerant = any(directions.get(f, 0) != 0 for f in REFRIGERANT_FEATURES)
    if (actuator and refrigerant) or tcs_gap_drift:
        return "fault"
    if actuator and not refrigerant and thermostat_changed:
        return "learning"
    if not actuator and not refrigerant:
        return "none"
    return "ambiguous"


def synthetic_ramp_report(ramp_days=(30, 60, 90), n_seeds=20, series_days=120,
                          onset_day=30, total_drift_sigma=6.0, sigma=1.0,
                          seed0=0) -> pd.DataFrame:
    """Detection delay & false-alarm report on synthetic daily ramps (all defaults pinned).
    Per seed i: noise = default_rng(seed0+i).normal(0, sigma, series_days); ramp rises
    linearly from onset_day, reaching total_drift_sigma*sigma after ramp_days days.
    False alarms: the n_seeds pure-noise series of the same length.
    Columns: ramp_days, detection_rate, mean_delay_days, false_alarm_rate;
    delay = onset_idx - onset_day (days). Thresholds k/h = module constants (M4 calibrates)."""
    noise = [np.random.default_rng(seed0 + i).normal(0.0, sigma, series_days)
             for i in range(n_seeds)]
    false_alarm_rate = float(np.mean([cusum_detect(n, sigma)["alarm"] for n in noise]))
    days = np.arange(series_days)
    rows = []
    for ramp in ramp_days:
        ramp_signal = np.where(
            days >= onset_day,
            np.minimum((days - onset_day) / ramp, 1.0) * total_drift_sigma * sigma,
            0.0,
        )
        delays = []
        for i in range(n_seeds):
            r = cusum_detect(noise[i] + ramp_signal, sigma)
            if r["alarm"]:
                delays.append(r["onset_idx"] - onset_day)
        rows.append({
            "ramp_days": ramp,
            "detection_rate": len(delays) / n_seeds,
            "mean_delay_days": float(np.mean(delays)) if delays else float("nan"),
            "false_alarm_rate": false_alarm_rate,
        })
    return pd.DataFrame(rows)
