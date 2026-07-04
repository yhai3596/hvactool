"""M-LABEL label connection engine (M1, stub-driven until C3 arrives).

API pinned by tests/test_m1_label.py + module instruction (pins, no local freedom):
  JOIN_WINDOW_DAYS = (-21, +3)   # day-granularity CLOSED interval, delta = event day - ticket day
  join_events(labels_df, events_df)   # per-ticket nearest-|delta| match, tie -> earlier event;
                                      # never cross-SN; tickets may share one event;
                                      # unmatched -> matched=False / NaT / NaN
  training_admission(df)              # row filter only, all columns kept (label hygiene):
                                      # (label_tier >= 3) OR (valid AND confirmed);
                                      # sn_status == "valid_multiple_candidates" is a HARD
                                      # exclusion, no tier/review state exempts it
  verify_closure(residual_daily, repair_date, band, within_days=14)
      entry = first in-band value on/after repair_date; True iff entry occurs within
      within_days and every non-NaN day from entry through series end stays in band.
      Real-data guards (pinned, beyond test coverage): NaN days are ignored in the
      stay-in-band check (neither satisfy nor violate); fewer than MIN_POST_DAYS non-NaN
      days from entry -> False (no L4 closure on one or two days of data).

Tier upgrade wiring (closure True -> L4) deliberately NOT here; it lands with the real
C3 connection in M3 — this module stays pure functions on frames/series.
"""
import numpy as np
import pandas as pd

from fdd import config

# calibration from config/calibration.yaml (FDD-I-012 #2)
JOIN_WINDOW_DAYS = tuple(config.cal("label.join_window_days"))   # (-21, +3)
MIN_POST_DAYS = config.cal("label.min_post_days")   # min non-NaN days for a closure verdict


def join_events(labels_df: pd.DataFrame, events_df: pd.DataFrame) -> pd.DataFrame:
    """Join platform events (C3) to tickets (C2). Day-granularity closed window:
    JOIN_WINDOW_DAYS[0] <= (event day - ticket day) <= JOIN_WINDOW_DAYS[1]."""
    out = labels_df.copy()
    ev = events_df.copy()
    ev["_day"] = pd.to_datetime(ev["ts_utc"]).dt.normalize()

    matched, m_ts, m_code = [], [], []
    for _, ticket in out.iterrows():
        t_day = pd.Timestamp(ticket["event_date"]).normalize()
        cand = ev[ev["hash_sn"] == ticket["hash_sn"]].copy()   # never cross-SN
        if len(cand):
            cand["_delta"] = (cand["_day"] - t_day).dt.days
            cand = cand[(cand["_delta"] >= JOIN_WINDOW_DAYS[0])
                        & (cand["_delta"] <= JOIN_WINDOW_DAYS[1])]
        if len(cand):
            # nearest by |delta|; tie -> earlier event (deterministic)
            cand = cand.iloc[np.lexsort((cand["_day"].to_numpy(),
                                         cand["_delta"].abs().to_numpy()))]
            hit = cand.iloc[0]
            matched.append(True)
            m_ts.append(pd.Timestamp(hit["ts_utc"]))
            m_code.append(hit["fault_code"])
        else:
            matched.append(False)
            m_ts.append(pd.NaT)
            m_code.append(np.nan)
    out["matched"] = matched
    out["matched_event_ts"] = m_ts
    out["matched_fault_code"] = m_code
    return out


def training_admission(df: pd.DataFrame) -> pd.DataFrame:
    """Label-hygiene row filter (all columns kept). Admit (label_tier >= 3) OR
    (sn_status valid AND review_state confirmed); valid_multiple_candidates is a
    hard exclusion regardless of anything else."""
    hard_ok = df["sn_status"] != "valid_multiple_candidates"
    admit = (df["label_tier"] >= 3) | (
        (df["sn_status"] == "valid") & (df["review_state"] == "confirmed")
    )
    return df[hard_ok & admit]


def verify_closure(residual_daily: pd.Series, repair_date, band, within_days: int = 14) -> bool:
    """True iff the residual enters [band] within within_days of repair_date (inclusive
    of the repair day) and every non-NaN day from entry through the end of the series
    stays in band, with at least MIN_POST_DAYS non-NaN days from entry."""
    repair_date = pd.Timestamp(repair_date)
    lo, hi = band
    post = residual_daily[residual_daily.index >= repair_date].dropna()
    in_band = post[(post >= lo) & (post <= hi)]
    if in_band.empty:
        return False
    entry = in_band.index[0]
    if entry > repair_date + pd.Timedelta(days=within_days):
        return False
    tail = post[post.index >= entry]        # non-NaN only: NaN days are ignored
    if len(tail) < MIN_POST_DAYS:
        return False                        # no closure verdict on thin data
    return bool(((tail >= lo) & (tail <= hi)).all())
