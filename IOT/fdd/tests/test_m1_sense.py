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
    ("Ts", +2.0), ("Ts", -2.0), ("Tl", -2.0), ("Ta", +2.0),
    ("Lp", +0.5), ("Hp", -0.5),
])
def test_bias_injection_detected(sample, col, delta):
    ref = sense.fit_reference(sample)
    out = sense.check(_inject_bias(sample, col, delta), ref).set_index("sensor")
    assert out.loc[col, "drift_flag"], f"{col} bias {delta} not flagged"


def test_ramp_injection_detected(sample):
    ref = sense.fit_reference(sample)
    out = sense.check(_inject_ramp(sample, "Ts", 2.0), ref).set_index("sensor")
    assert out.loc["Ts", "drift_flag"]


def test_injection_does_not_flag_independent_sensor(sample):
    """Attribution sanity: Ts bias must not flag Ta (independent ambient)."""
    ref = sense.fit_reference(sample)
    out = sense.check(_inject_bias(sample, "Ts", +2.0), ref).set_index("sensor")
    assert not out.loc["Ta", "drift_flag"]
