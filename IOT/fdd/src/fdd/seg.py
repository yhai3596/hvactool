"""M-SEG state segmentation & steady-state detector. Milestone: M0.

Hard rules #6 #7 bind here.
DoD (tests/test_m0_seg.py) on data/sample:
  - exactly 2 defrost segments (St-based) and 5 special segments detected
  - zero steady rows inside CompState==2
  - steady coverage in [0.40, 0.80] of run rows
"""
import numpy as np
import pandas as pd

STEADY_MIN_MINUTES = 5.0
ROLL_WINDOW_MIN = 2.0
# thresholds calibrated on sample; re-calibrate when lab transient data arrives (M2)
RPS_STD_MAX = 1.5
EXV_STD_MAX = 6.0
FALLBACK_CADENCE_S = 10.0   # sample cadence if Timestamp is unparseable


def _elapsed_seconds(df: pd.DataFrame) -> pd.Series:
    """Seconds since first row, from Timestamp; falls back to fixed cadence."""
    try:
        ts = pd.to_datetime(df["Timestamp"], utc=True)
        if ts.isna().any():
            raise ValueError("unparseable timestamps")
        return (ts - ts.iloc[0]).dt.total_seconds()
    except Exception:
        return pd.Series(np.arange(len(df)) * FALLBACK_CADENCE_S, index=df.index)


def segment(df: pd.DataFrame) -> pd.DataFrame:
    """Add columns: segment_id, segment_type in
    {run, off, defrost, special, transition}, steady(bool).
    defrost := CompState==2 AND St flipped to 0 within segment (Th spike = verification only).
    special := CompState==2 AND St stays 1 (periodic low-freq program -> ALWAYS excluded).
    steady  := run AND >STEADY_MIN_MINUTES into segment AND rolling std(CompRps)<RPS_STD_MAX
               AND rolling std(Exv)<EXV_STD_MAX."""
    out = df.copy()
    cs = out["CompState"]
    out["segment_id"] = (cs != cs.shift()).cumsum()

    # segment type: rule #7 -- defrost keyed on St (four-way valve), never on Th
    st_min = out.groupby("segment_id")["St"].transform("min")
    state = out.groupby("segment_id")["CompState"].transform("first")
    out["segment_type"] = np.select(
        [state == 0, state == 1, (state == 2) & (st_min == 0)],
        ["off", "run", "defrost"],
        default="special",
    )

    # steady detection (rule #6), on run rows only; CompState==2 fully excluded
    elapsed = _elapsed_seconds(out)
    cadence = float(np.median(np.diff(elapsed))) if len(out) > 1 else FALLBACK_CADENCE_S
    win = max(2, int(round(ROLL_WINDOW_MIN * 60.0 / cadence)))
    rps_std = out["CompRps"].rolling(win, min_periods=win).std()
    exv_std = out["Exv"].rolling(win, min_periods=win).std()
    seg_start = elapsed.groupby(out["segment_id"]).transform("first")
    into_seg_min = (elapsed - seg_start) / 60.0
    out["steady"] = (
        (out["segment_type"] == "run")
        & (out["CompState"] == 1)
        & (into_seg_min > STEADY_MIN_MINUTES)
        & (rps_std < RPS_STD_MAX)
        & (exv_std < EXV_STD_MAX)
    )
    return out


def summarize_segments(df: pd.DataFrame) -> pd.DataFrame:
    """Per-segment summary: type, duration, key means (for QA reports)."""
    out = df if "segment_id" in df.columns else segment(df)
    elapsed = _elapsed_seconds(out)
    g = out.assign(_t=elapsed).groupby("segment_id")
    summary = pd.DataFrame({
        "segment_type": g["segment_type"].first(),
        "n_rows": g.size(),
        "duration_min": (g["_t"].last() - g["_t"].first()) / 60.0,
        "steady_share": g["steady"].mean(),
        "comp_rps_mean": g["CompRps"].mean(),
        "exv_mean": g["Exv"].mean(),
        "ta_mean": g["Ta"].mean(),
        "lp_mean": g["Lp"].mean(),
        "hp_mean": g["Hp"].mean(),
    })
    return summary.reset_index()
