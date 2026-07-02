"""M-FEAT acceptance tests. Authored in Project, transcribed verbatim (rule 11 amendment).
Pins API: feat.REGISTRY, feat.fit_baseline(raw_df)->model, feat.compute(raw_df, model)->DataFrame
(steady rows only, columns >= REGISTRY + 'bin_id'), feat.defrost_frequency(raw_df)->events/hour.
fit_baseline/compute internally call conv.materialize + seg.segment; only steady rows enter."""
import pandas as pd
import pytest
from fdd import feat

pytestmark = pytest.mark.m1

EXPECTED_REGISTRY = {
    "exv_resid","sc_resid","capacity_resid","approach","th_coil_resid",
    "comp_slip","fan_slip","power_resid","p_parasitic","tcs_gap",
    "i_resid","tf_resid","indoor_load_proxy",
}

def _perturb_undercharge(df):
    """Constant-offset synthetic undercharge (heating): keeps rolling variances,
    hence identical steady mask. Exv +30 steps, Tl +2.0K (sc_phys -2), Qh x0.9, Lp -0.3 bar."""
    d = df.copy()
    d["Exv"] += 30; d["Tl"] += 2.0; d["Qh"] *= 0.9; d["Lp"] -= 0.3
    return d

def test_registry_is_locked():
    assert set(feat.REGISTRY) == EXPECTED_REGISTRY

def test_no_nan_and_coverage(sample):
    m = feat.fit_baseline(sample)
    out = feat.compute(sample, m)
    assert len(out) > 0 and not out[list(EXPECTED_REGISTRY)].isna().any().any()
    from fdd import seg
    steady_n = seg.segment(sample)["steady"].sum()
    assert len(out) >= 0.9 * steady_n
    # self-residuals near zero (baseline fitted on same data)
    assert abs(out["exv_resid"].mean()) < 1.0
    assert abs(out["sc_resid"].mean()) < 0.05
    assert abs(out["capacity_resid"].mean()) < 0.01

def test_undercharge_directionality(sample):
    m = feat.fit_baseline(sample)
    out = feat.compute(_perturb_undercharge(sample), m)
    assert out["exv_resid"].mean() >= 20.0          # injected +30
    assert out["sc_resid"].mean() <= -1.5           # injected -2.0 via Tl
    assert out["capacity_resid"].mean() <= -0.07    # injected -10% relative

def test_reported_sh_sc_are_unused(sample):
    """Rule: physics quantities only. Corrupting firmware-reported Sh/Sc must change nothing."""
    m = feat.fit_baseline(sample)
    ref = feat.compute(sample, m)
    d = sample.copy(); d["Sh"] += 5.0; d["Sc"] += 5.0
    out = feat.compute(d, m)
    pd.testing.assert_frame_equal(out[list(EXPECTED_REGISTRY)], ref[list(EXPECTED_REGISTRY)],
                                  atol=1e-9, check_exact=False)

def test_sc_resid_tracks_physics(sample):
    m = feat.fit_baseline(sample)
    ref = feat.compute(sample, m)["sc_resid"].mean()
    d = sample.copy(); d["Tl"] += 2.0
    out = feat.compute(d, m)["sc_resid"].mean()
    assert out - ref <= -1.5                        # sc_phys = tc_sat - Tl

def test_i_resid_v1_covariate(sample):
    """Constant-VA rescale (V1 x0.9, currents /0.9) must leave i_resid ~invariant."""
    m = feat.fit_baseline(sample)
    ref = feat.compute(sample, m)["i_resid"].mean()
    d = sample.copy(); d["V1"] *= 0.9; d["I1"] /= 0.9; d["I2"] /= 0.9
    out = feat.compute(d, m)["i_resid"].mean()
    assert abs(out - ref) < 0.05 * sample["I2"].mean()

def test_tf_resid_direction(sample):
    m = feat.fit_baseline(sample)
    d = sample.copy(); d["Tf"] += 3.0
    assert feat.compute(d, m)["tf_resid"].mean() >= 2.0

def test_approach_heating_formula(sample):
    from fdd import conv
    m = feat.fit_baseline(sample)
    out = feat.compute(sample, m)
    der = conv.materialize(sample).loc[out.index]
    expected = sample.loc[out.index, "Ta"] - der["te_sat"]
    assert (out["approach"] - expected).abs().max() < 1e-6

def test_defrost_frequency(sample):
    f = feat.defrost_frequency(sample)     # 2 true defrosts / ~5h
    assert 0.3 <= f <= 0.5