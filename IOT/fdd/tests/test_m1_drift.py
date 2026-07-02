"""M-DRIFT acceptance tests. Authored in Project, placed by human (rule 12).

Pins API — implementation must match exactly:
  drift.BASELINE_N = 28                      # sigma/mu0 estimation window (leading points)
  drift.robust_sigma(x) -> float             # 1.4826 * median(|x - median(x)|)
  drift.cusum_detect(x, sigma, k=0.5, h=5.0) -> dict
      two-sided tabular CUSUM; mu0 = median of first BASELINE_N points;
      returns {"alarm": bool, "onset_idx": int|None, "direction": int}  # +1/-1/0
      onset_idx = first index where a decision statistic crosses h*sigma
  drift.detect(df, value_col, group_cols) -> pd.DataFrame
      one row per group: [*group_cols, "alarm", "onset_idx", "direction"];
      per-group sigma = robust_sigma(first BASELINE_N points of the group)
  drift.classify_channel(directions: dict, thermostat_changed: bool, tcs_gap_drift: bool) -> str
      directions: {feature_name: +1/-1/0}. Rule (locked, per CLAUDE.md #8):
        fault      := (actuator drift AND any refrigerant residual drift) OR tcs_gap_drift
        learning   := actuator-only drift AND thermostat_changed AND not tcs_gap_drift
        none       := no drift anywhere AND not tcs_gap_drift
        ambiguous  := everything else
      actuator features: exv_resid, comp_slip, fan_slip
      refrigerant features: sc_resid, capacity_resid
  drift.synthetic_ramp_report() -> pd.DataFrame
      defaults pinned (deterministic): ramp_days=(30,60,90), n_seeds=20, series_days=120,
      onset_day=30, total_drift_sigma=6.0, sigma=1.0, seed0=0, rng=np.random.default_rng(seed0+i);
      false alarms measured on n_seeds independent pure-noise series of the same length;
      columns: ramp_days, detection_rate, mean_delay_days, false_alarm_rate;
      delay = onset_idx - onset_day (days).
Thresholds k/h are module constants for M1; real calibration deferred to M4 (labeled data).
"""
import numpy as np
import pandas as pd
import pytest

from fdd import drift

pytestmark = pytest.mark.m1


def test_robust_sigma_matches_std_on_gaussian():
    x = np.random.default_rng(0).normal(0.0, 2.0, 4000)
    assert abs(drift.robust_sigma(x) - 2.0) < 0.1


def test_robust_sigma_ignores_outliers():
    x = np.concatenate([np.random.default_rng(1).normal(0.0, 1.0, 500), np.full(25, 50.0)])
    assert drift.robust_sigma(x) < 1.5


def test_cusum_positive_step():
    x = np.concatenate([np.zeros(60), np.full(60, 3.0)])
    r = drift.cusum_detect(x, sigma=1.0)
    assert r["alarm"] and r["direction"] == 1
    assert 60 <= r["onset_idx"] <= 70


def test_cusum_negative_step_symmetric():
    x = np.concatenate([np.zeros(60), np.full(60, -3.0)])
    r = drift.cusum_detect(x, sigma=1.0)
    assert r["alarm"] and r["direction"] == -1


def test_cusum_no_alarm_on_flat_noise_free():
    r = drift.cusum_detect(np.zeros(200), sigma=1.0)
    assert (not r["alarm"]) and r["direction"] == 0 and r["onset_idx"] is None


def test_detect_groups():
    n = 80
    flat = np.zeros(n)
    stepped = np.concatenate([np.zeros(n // 2), np.full(n - n // 2, 4.0)])
    df = pd.DataFrame({
        "hash_sn": ["a"] * n + ["b"] * n,
        "feature": ["exv_resid"] * (2 * n),
        "value": np.concatenate([flat, stepped]),
    })
    out = drift.detect(df, value_col="value", group_cols=("hash_sn", "feature"))
    assert len(out) == 2
    row = out.set_index("hash_sn")
    assert not row.loc["a", "alarm"]
    assert row.loc["b", "alarm"] and row.loc["b", "direction"] == 1


def test_classify_fault_refrigerant_comovement():
    d = {"exv_resid": 1, "sc_resid": -1, "capacity_resid": -1, "comp_slip": 0, "fan_slip": 0}
    assert drift.classify_channel(d, thermostat_changed=False, tcs_gap_drift=False) == "fault"


def test_classify_fault_when_target_tracking_fails():
    d = {"exv_resid": 1, "sc_resid": 0, "capacity_resid": 0, "comp_slip": 0, "fan_slip": 0}
    assert drift.classify_channel(d, thermostat_changed=False, tcs_gap_drift=True) == "fault"


def test_classify_learning_actuator_only_with_thermostat_change():
    d = {"exv_resid": 1, "sc_resid": 0, "capacity_resid": 0, "comp_slip": 1, "fan_slip": 0}
    assert drift.classify_channel(d, thermostat_changed=True, tcs_gap_drift=False) == "learning"


def test_classify_ambiguous_actuator_only_no_cause():
    d = {"exv_resid": 1, "sc_resid": 0, "capacity_resid": 0, "comp_slip": 0, "fan_slip": 0}
    assert drift.classify_channel(d, thermostat_changed=False, tcs_gap_drift=False) == "ambiguous"


def test_classify_none():
    d = {"exv_resid": 0, "sc_resid": 0, "capacity_resid": 0, "comp_slip": 0, "fan_slip": 0}
    assert drift.classify_channel(d, thermostat_changed=False, tcs_gap_drift=False) == "none"


def test_synthetic_ramp_report_contract():
    rep = drift.synthetic_ramp_report()
    assert list(rep["ramp_days"]) == [30, 60, 90]
    assert (rep["detection_rate"] == 1.0).all()
    d = list(rep["mean_delay_days"])
    assert d[0] < d[1] < d[2], f"delay not monotone: {d}"
    assert d[2] <= 45.0
    assert (rep["false_alarm_rate"] <= 0.40).all()
