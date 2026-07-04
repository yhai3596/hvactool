"""M-SENSE acceptance tests. Authored in Project, placed by human (rule 12).

Pins API:
  sense.SENSORS = ("Ta", "Ts", "Th", "Tl", "Lp", "Hp")
  sense.fit_reference(df) -> dict
      per-sensor consistency statistics fitted on a known-clean record.
      All statistics computed on STEADY rows only (via seg.segment); defrost/special excluded.
      Suggested internals (guidance, not asserted): steady-level stats, P-T consistency
      (sh_phys/sc_phys residual bands), defrost-plateau Th vs tc_sat, cross-sensor relations.
  sense.check(df, reference) -> pd.DataFrame
      columns include at least ["sensor", "drift_flag"]; one row per sensor in SENSORS.
Behavioral DoD (dev doc): injected +/-2K bias or ramp-to-2K -> flagged (100% detection);
clean record vs its own reference -> zero flags (zero false alarm). Pressure injection 0.5 bar.
Factory-fingerprint comparison is stubbed until C4 data (not tested here).
"""
import pytest

from fdd import sense

pytestmark = pytest.mark.m1


def _inject_bias(df, col, delta):
    d = df.copy()
    d[col] = d[col] + delta
    return d


def _inject_ramp(df, col, total):
    d = df.copy()
    n = len(d)
    d[col] = d[col] + [total * i / (n - 1) for i in range(n)]
    return d


def test_zero_false_alarm_on_clean(sample):
    ref = sense.fit_reference(sample)
    out = sense.check(sample, ref)
    assert set(out["sensor"]) == set(sense.SENSORS)
    assert not out["drift_flag"].any(), out[out["drift_flag"]]["sensor"].tolist()


@pytest.mark.parametrize("col,delta", [
    ("Ts", +2.0), ("Ts", -2.0), ("Tl", -2.0),   # Ta 移除:降级后不由 ta_th 检测
    ("Lp", +0.5), ("Hp", -0.5),
])
def test_bias_injection_detected(sample, col, delta):
    """Ta removed: ta_th demoted to context channel (co-linearity proof, FDD-I-006).
    Ta sensor trust now via off-cycle equalization check — see test below."""
    ref = sense.fit_reference(sample)
    out = sense.check(_inject_bias(sample, col, delta), ref).set_index("sensor")
    assert out.loc[col, "drift_flag"], f"{col} bias {delta} not flagged"


def test_ta_trust_via_off_cycle_equalization():
    """Ta-free trust source: during off-cycle (CompRps==0, >Nmin), refrigerant
    migrates to equilibrium; Ta should converge to settled coil temps. A Ta bias
    breaks this convergence. Synthetic off-cycle segment until M3 real data.
    (FDD-I-006: replaces the ta_th-based Ta injection assertion.)"""
    import numpy as np
    import pandas as pd
    n = 60
    base = pd.DataFrame({
        "CompRps": np.zeros(n), "PowerComp": np.zeros(n),
        "Ta": 20.0 + np.random.default_rng(0).normal(0, 0.05, n),
        "Th": 20.0 + np.random.default_rng(1).normal(0, 0.05, n),
        "Tl": 20.0 + np.random.default_rng(2).normal(0, 0.05, n),
        "Ts": 20.0 + np.random.default_rng(3).normal(0, 0.05, n),
        "Lp": 9.0 + np.random.default_rng(4).normal(0, 0.02, n),
        "Hp": 9.2 + np.random.default_rng(5).normal(0, 0.02, n),  # near-equalized
        "Timestamp": pd.date_range("2026-01-01", periods=n, freq="10s", tz="UTC"),
    })
    clean = sense.check_off_cycle_equalization(base)
    assert not clean[clean["sensor"] == "Ta"]["drift_flag"].any()
    biased = base.copy(); biased["Ta"] += 2.0
    out = sense.check_off_cycle_equalization(biased)
    assert out[out["sensor"] == "Ta"]["drift_flag"].any()
    assert not out[out["sensor"] == "Th"]["drift_flag"].any()  # no co-flag


def test_ramp_injection_detected(sample):
    ref = sense.fit_reference(sample)
    out = sense.check(_inject_ramp(sample, "Ts", 2.0), ref).set_index("sensor")
    assert out.loc["Ts", "drift_flag"]


def test_injection_does_not_flag_independent_sensor(sample):
    """Attribution sanity: Ts bias must not flag Ta (independent ambient)."""
    ref = sense.fit_reference(sample)
    out = sense.check(_inject_bias(sample, "Ts", +2.0), ref).set_index("sensor")
    assert not out.loc["Ta", "drift_flag"]
