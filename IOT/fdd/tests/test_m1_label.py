"""M-LABEL acceptance tests. Authored in Project, placed by human (rule 12). Stub-driven (C3).

Pins API:
  label.JOIN_WINDOW_DAYS = (-21, +3)     # platform event ts relative to ticket event_date
  label.join_events(labels_df, events_df) -> pd.DataFrame
      labels_df columns >= [hash_sn, fault_family, event_date]
      events_df columns >= [hash_sn, ts_utc, fault_code]
      returns labels_df + [matched(bool), matched_event_ts, matched_fault_code];
      multiple events in window -> nearest by |delta t|; per-ticket matching (two tickets
      may match the same event).
  label.training_admission(df) -> pd.DataFrame
      admits rows where (label_tier >= 3) OR (sn_status=="valid" AND review_state=="confirmed");
      HARD exclusion regardless of anything else: sn_status=="valid_multiple_candidates".
  label.verify_closure(residual_daily: pd.Series[date-indexed], repair_date, band, within_days=14) -> bool
      True iff residual enters [band[0], band[1]] at some day <= repair_date+within_days
      and stays inside through the end of the available series.
"""
import pandas as pd
import pytest

from fdd import label

pytestmark = pytest.mark.m1


def _labels(rows):
    return pd.DataFrame(rows)


def _events(rows):
    df = pd.DataFrame(rows)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"])
    return df


def test_join_window_edges():
    lab = _labels([
        {"hash_sn": "u1", "fault_family": "refrigerant_low_or_leak", "event_date": "2024-03-01"},
        {"hash_sn": "u2", "fault_family": "refrigerant_low_or_leak", "event_date": "2024-03-01"},
        {"hash_sn": "u3", "fault_family": "refrigerant_low_or_leak", "event_date": "2024-03-01"},
        {"hash_sn": "u4", "fault_family": "refrigerant_low_or_leak", "event_date": "2024-03-01"},
    ])
    ev = _events([
        {"hash_sn": "u1", "ts_utc": "2024-02-09", "fault_code": "E1"},  # -21d  -> match
        {"hash_sn": "u2", "ts_utc": "2024-02-08", "fault_code": "E1"},  # -22d  -> no
        {"hash_sn": "u3", "ts_utc": "2024-03-04", "fault_code": "E1"},  # +3d   -> match
        {"hash_sn": "u4", "ts_utc": "2024-03-05", "fault_code": "E1"},  # +4d   -> no
    ])
    out = label.join_events(lab, ev).set_index("hash_sn")
    assert bool(out.loc["u1", "matched"]) and bool(out.loc["u3", "matched"])
    assert not bool(out.loc["u2", "matched"]) and not bool(out.loc["u4", "matched"])


def test_join_picks_nearest_event():
    lab = _labels([{"hash_sn": "u1", "fault_family": "compressor_fault", "event_date": "2024-03-01"}])
    ev = _events([
        {"hash_sn": "u1", "ts_utc": "2024-02-10", "fault_code": "FAR"},   # -20d
        {"hash_sn": "u1", "ts_utc": "2024-02-28", "fault_code": "NEAR"},  # -2d
    ])
    out = label.join_events(lab, ev)
    assert out.loc[0, "matched"] and out.loc[0, "matched_fault_code"] == "NEAR"


def test_two_tickets_may_share_one_event():
    lab = _labels([
        {"hash_sn": "u1", "fault_family": "sensor_fault", "event_date": "2024-03-01"},
        {"hash_sn": "u1", "fault_family": "sensor_fault", "event_date": "2024-03-03"},
    ])
    ev = _events([{"hash_sn": "u1", "ts_utc": "2024-02-28", "fault_code": "E7"}])
    out = label.join_events(lab, ev)
    assert out["matched"].all()


def test_no_cross_sn_matching():
    lab = _labels([{"hash_sn": "u1", "fault_family": "eev_fault", "event_date": "2024-03-01"}])
    ev = _events([{"hash_sn": "OTHER", "ts_utc": "2024-02-28", "fault_code": "E9"}])
    out = label.join_events(lab, ev)
    assert not out.loc[0, "matched"]


def test_training_admission_matrix():
    df = pd.DataFrame([
        {"id": 1, "label_tier": 4, "sn_status": "valid", "review_state": "confirmed"},   # in
        {"id": 2, "label_tier": 3, "sn_status": "valid", "review_state": "pending"},     # in (tier)
        {"id": 3, "label_tier": 2, "sn_status": "valid", "review_state": "confirmed"},   # in (valid+confirmed)
        {"id": 4, "label_tier": 2, "sn_status": "valid", "review_state": "pending"},     # out
        {"id": 5, "label_tier": 4, "sn_status": "valid_multiple_candidates",
         "review_state": "confirmed"},                                                    # out (hard)
        {"id": 6, "label_tier": 1, "sn_status": "suspicious", "review_state": "confirmed"},  # out
    ])
    kept = set(label.training_admission(df)["id"])
    assert kept == {1, 2, 3}


def test_closure_recovery_within_window():
    days = pd.date_range("2024-03-01", periods=30, freq="D")
    vals = [-2.5] * 10 + [-1.0, -0.4] + [0.0] * 18   # repair at day 10, recovers day 11
    s = pd.Series(vals, index=days)
    assert label.verify_closure(s, repair_date=pd.Timestamp("2024-03-11"),
                                band=(-0.5, 0.5), within_days=14) is True


def test_closure_fails_when_residual_persists():
    days = pd.date_range("2024-03-01", periods=30, freq="D")
    s = pd.Series([-2.5] * 30, index=days)
    assert label.verify_closure(s, repair_date=pd.Timestamp("2024-03-11"),
                                band=(-0.5, 0.5), within_days=14) is False


def test_closure_fails_on_relapse():
    days = pd.date_range("2024-03-01", periods=30, freq="D")
    vals = [-2.5] * 10 + [0.0] * 8 + [-2.5] * 12     # recovers then relapses
    s = pd.Series(vals, index=days)
    assert label.verify_closure(s, repair_date=pd.Timestamp("2024-03-11"),
                                band=(-0.5, 0.5), within_days=14) is False
