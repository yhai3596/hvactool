"""DoD for M-SEG on the sample. Ground truth established 2026-07 data verification."""
import pytest
from fdd import seg

pytestmark = pytest.mark.m0

def test_defrost_and_special_counts(sample):
    out = seg.segment(sample)
    s = out.drop_duplicates("segment_id")
    assert (s["segment_type"] == "defrost").sum() == 2
    assert (s["segment_type"] == "special").sum() == 5

def test_no_steady_rows_inside_compstate2(sample):
    out = seg.segment(sample)
    assert not out.loc[sample["CompState"] == 2, "steady"].any()

def test_steady_coverage_band(sample):
    out = seg.segment(sample)
    run = out["segment_type"] == "run"
    cov = out.loc[run, "steady"].mean()
    assert 0.40 <= cov <= 0.80, f"steady coverage {cov:.2f}"

def test_defrost_by_st_not_th(sample):
    """Defrost decision must key on St flip; Th spike is verification only."""
    out = seg.segment(sample)
    defrost_rows = out["segment_type"] == "defrost"
    assert (sample.loc[defrost_rows, "St"] == 0).any()
