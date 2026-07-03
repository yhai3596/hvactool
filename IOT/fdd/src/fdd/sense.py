"""M-SENSE sensor trust layer (M1). Rules: steady rows only, physics via conv.materialize,
reported Sh/Sc are NEVER read.

API pinned by tests/test_m1_sense.py + module instruction (pins, no local freedom):
  SENSORS = ("Ta", "Ts", "Th", "Tl", "Lp", "Hp")
  fit_reference(df) -> dict   # per-channel steady-record median (+ MAD sigma for reports)
  check(df, reference) -> DataFrame [sensor, drift_flag, ...] one row per sensor

Four consistency channels (all derived, physics scope):
  sh    : sh_phys                  -> sensors {Ts, Lp}
  sc    : sc_phys                  -> sensors {Tl, Hp}
  th_te : Th - te_sat              -> sensors {Th}
  ta_th : Ta - Th                  -> sensors {Ta}
Detection statistic: median(tail steady window) - reference median, tail window =
last max(50, 25% x steady rows); |stat| > threshold triggers the channel; a sensor's
drift_flag = any of its channels triggered (paired sensors on a shared channel may
co-flag; attribution refinement deferred).

HARD BAN (pinned): no sensor may be triggered solely by "raw-column mean vs reference
mean" — a naive level-shift detector false-alarms whenever reference and check windows
span different seasons. All channels above are cross-sensor/physics differences, which
cancel common weather drift. Factory-fingerprint comparison is stubbed until C4 arrives.

THRESHOLDS are sample-calibrated module constants (margin rationale archived); if a test
is red, report measured values and STOP — do not touch thresholds or channel definitions.
"""
import numpy as np
import pandas as pd

from fdd import conv, seg
from fdd.drift import robust_sigma

SENSORS = ("Ta", "Ts", "Th", "Tl", "Lp", "Hp")

THRESHOLDS = {"sh": 0.8, "sc": 0.45, "th_te": 1.0, "ta_th": 1.2}   # pinned, do not tune

CHANNEL_SENSORS = {
    "sh": ("Ts", "Lp"),
    "sc": ("Tl", "Hp"),
    "th_te": ("Th",),
    "ta_th": ("Ta",),
}

TAIL_MIN_ROWS = 50
TAIL_FRACTION = 0.25


def _channel_series(df: pd.DataFrame) -> dict:
    """Steady-row channel series. Physics via conv.materialize only (no reported Sh/Sc)."""
    work = seg.segment(conv.materialize(df))
    st = work[work["steady"]]
    return {
        "sh": st["sh_phys"],
        "sc": st["sc_phys"],
        "th_te": st["Th"] - st["te_sat"],
        "ta_th": st["Ta"] - st["Th"],
    }


def fit_reference(df: pd.DataFrame) -> dict:
    """Per-channel median over the full steady record of a known-clean period,
    plus MAD sigma (report/diagnostic use; detection uses the median only)."""
    channels = _channel_series(df)
    return {
        ch: {"median": float(s.median()), "mad_sigma": robust_sigma(s.to_numpy())}
        for ch, s in channels.items()
    }


def check(df: pd.DataFrame, reference: dict) -> pd.DataFrame:
    """Flag sensor drift vs a fitted reference. One row per sensor in SENSORS;
    drift_flag = any owning channel's |tail median - reference median| > threshold."""
    channels = _channel_series(df)
    n_steady = len(next(iter(channels.values())))
    tail_n = max(TAIL_MIN_ROWS, int(TAIL_FRACTION * n_steady))
    stats, triggered = {}, {}
    for ch, s in channels.items():
        stat = float(s.iloc[-tail_n:].median()) - reference[ch]["median"]
        stats[ch] = stat
        triggered[ch] = abs(stat) > THRESHOLDS[ch]
    rows = []
    for sensor in SENSORS:
        owning = [ch for ch, sens in CHANNEL_SENSORS.items() if sensor in sens]
        hit = [ch for ch in owning if triggered[ch]]
        rows.append({
            "sensor": sensor,
            "drift_flag": bool(hit),
            "triggered_channels": hit,
            "channel_stats": {ch: stats[ch] for ch in owning},
        })
    return pd.DataFrame(rows)


def fingerprint_check(df: pd.DataFrame, fingerprint) -> pd.DataFrame:
    """Factory-fingerprint comparison — STUB until C4 lab/production data arrives.
    Interface reserved; do not fold into check() before C4 schema diff."""
    raise NotImplementedError("C4 factory/production fingerprint data not yet delivered")
