"""M-FEAT fallback amendment. Authored in Project, placed by human (rule 12).

Closes a spec gap found at M1-A acceptance: the fallback machinery (design pins: n>=12
per full bin; level 0 = mode x Ta x Rps -> level 1 = mode x Ta marginal -> level 2 =
mode-global; output column "fallback_level") was pinned by implementation instruction
but carried no test assertion, while the 5h sample exercises it on only 28 rows
(level 1) and 0 rows (level 2) -- the least-verified path is the one that carries load
exactly during anomalous conditions.

Expected GREEN immediately if the implementation followed the pins; RED = real bug in
the fallback path, report and stop.
"""
import pytest

from fdd import feat

pytestmark = pytest.mark.m1


def test_fallback_column_present_and_bounded(sample):
    m = feat.fit_baseline(sample)
    out = feat.compute(sample, m)
    assert "fallback_level" in out.columns
    assert set(out["fallback_level"].unique()) <= {0, 1, 2}


def test_unseen_bins_fall_back_to_global_without_dropping(sample):
    """Ta +20K pushes every steady row into Ta bins never fitted: both the full bin and
    the mode x Ta marginal are unavailable, so every row must resolve at level 2
    (mode-global), with zero row loss and zero NaN. Steady mask is Ta-independent
    (CompState / segment position / rolling std of CompRps & Exv), so row counts must
    match the unshifted record exactly."""
    m = feat.fit_baseline(sample)
    d = sample.copy()
    d["Ta"] = d["Ta"] + 20.0
    out = feat.compute(d, m)
    ref = feat.compute(sample, m)
    assert len(out) == len(ref)
    assert (out["fallback_level"] == 2).all()
    assert out[list(feat.REGISTRY)].notna().all().all()
