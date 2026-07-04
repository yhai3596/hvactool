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

# ---- frost-phase segmentation (FDD-I-003; single source for sense & envelope) ----
# Calibration provenance (7 confirmed defrosts + H2 certification windows):
# - FROST_TH_ONSET_C = 0.0: clean-coil H1N runs sit at Th ≈ +1.8..+2.7 C; every observed
#   defrost initiated from Th ≤ −3.4 C; 0 C (freezing) splits the populations.
# - FROST_DRIFT_RATE_K_MIN = 0.05: lab H2 windows (heavy frosting) measured Th drift
#   0.09..0.23 K/min; field 5 h light-frost record drifts ≈0.01..0.03 K/min
#   (clean-classified); 0.05 splits both populations with ≥3x margin.
# - FROST_SLOPE_LAG_MIN = 5: slope estimation lag; rows without certified history
#   (NaN slope inside the frost zone) are conservatively 'frosting' — clean must be
#   POSITIVELY certified (漂移未启动), never assumed.
FROST_TH_ONSET_C = 0.0
FROST_DRIFT_RATE_K_MIN = 0.05
FROST_SLOPE_LAG_MIN = 5.0
FROST_SMOOTH_ROWS = 12          # ~2 min at the 10 s timebase
_TIME_JUMP_FACTOR = 5.0         # gaps > 5x cadence break slope continuity (stitched chunks)
# ---- dual-class rating anchor (FDD-I-004) ----
# Frost-condition anchor = steady & frosting & rate-plateau & defrost-not-imminent.
# Calibration provenance: H2/H4 certification windows hold mid-frost slope wander
# < ~0.01 K/min per 5-min lag (quasi-equilibrium frosting), while early buildup ramps
# 0 -> 0.2 K/min within ~10 min and pre-trigger runaway steepens sharply; 0.02 K/min^2
# splits both. Defrost guard 5 min: the 7 confirmed events show the terminal dive
# inside the last minutes before the St flip.
FROST_ACCEL_MAX_K_MIN2 = 0.02
DEFROST_GUARD_MIN = 5.0


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

    # frost-phase classification (orthogonal to steady; a row may be steady & frosting)
    lag = max(2, int(round(FROST_SLOPE_LAG_MIN * 60.0 / cadence)))
    dstep = elapsed.diff()
    block = ((dstep.abs() > _TIME_JUMP_FACTOR * cadence) | (dstep < 0)).cumsum()
    th_s = out["Th"].groupby(block).transform(
        lambda s: s.rolling(FROST_SMOOTH_ROWS, min_periods=4).median())
    slope = th_s.groupby(block).diff(lag) / (lag * cadence / 60.0)   # K/min
    frost_zone = ((out["segment_type"] == "run") & (out["St"] == 1)
                  & (out["Th"] < FROST_TH_ONSET_C))
    out["frost_phase"] = np.select(
        [out["segment_type"] == "defrost",
         frost_zone & (slope <= -FROST_DRIFT_RATE_K_MIN),
         frost_zone & (slope > -FROST_DRIFT_RATE_K_MIN)],   # certified not-drifting
        ["defrost", "frosting", "clean"],
        default="none",
    )
    out.loc[frost_zone & slope.isna(), "frost_phase"] = "frosting"   # uncertifiable

    # dual-class rating anchor (FDD-I-004): no-frost conditions anchor on clean steady;
    # frost conditions anchor on QUASI-EQUILIBRIUM frosting (rate plateau, no defrost
    # imminent) — "clean-coil only" is a no-frost-condition rule, a category error when
    # applied to H2/H4 (frost-process points).
    accel = slope.groupby(block).diff(lag) / (lag * cadence / 60.0)   # K/min^2
    plateau = slope.notna() & accel.notna() & (accel.abs() < FROST_ACCEL_MAX_K_MIN2)
    guard_s = DEFROST_GUARD_MIN * 60.0
    no_trigger = pd.Series(True, index=out.index)
    is_def_start = ((out["segment_type"] == "defrost")
                    & (out["segment_type"].shift() != "defrost"))
    for _, gidx in out.groupby(block).groups.items():
        el = elapsed.loc[gidx].to_numpy()
        starts = elapsed.loc[gidx][is_def_start.loc[gidx]].to_numpy()
        if len(starts):
            pos = np.searchsorted(starts, el, side="left")
            safe = np.minimum(pos, len(starts) - 1)
            nxt = np.where(pos < len(starts), starts[safe], np.inf)
            no_trigger.loc[gidx] = (nxt - el) > guard_s
    clean_anchor = out["steady"] & out["frost_phase"].isin(("clean", "none"))
    frost_anchor = (out["steady"] & (out["frost_phase"] == "frosting")
                    & plateau & no_trigger)
    out["anchor_type"] = np.select([clean_anchor, frost_anchor],
                                   ["clean_steady", "frosting_steady"], default=None)
    out["rating_anchor"] = clean_anchor | frost_anchor
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
