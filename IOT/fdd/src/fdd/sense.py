"""M-SENSE sensor trust layer — v3 binned-reference regime (M2 amendment).
Rules: steady rows only, physics via conv.materialize, reported Sh/Sc are NEVER read.

v3 (Project 2026-07-03): references are per (mode x Ta 2K bin x channel) — the bin
boundary definition is SHARED with M-FEAT (feat.ta_bin / feat.TA_BIN_K, single source).
Rationale (locked finding): only th_te is condition-invariant; sh/sc/ta_th genuinely
move with operating condition, so a GLOBAL reference false-alarms across seasons.

API:
  SENSORS, fit_reference(df) -> dict[(mode, ta_bin)][channel] = {median, mad_sigma, n}
  check(df, reference) -> one row per sensor:
      status in {ok, flagged, no_reference}; drift_flag == (status == "flagged")
      (compat column for M1 tests); triggered_channels; channel_stats (per owning
      channel: {(mode, bin): tail_median - ref_median} over judged bins).
  A bin is judgeable only with n >= MIN_BIN_N rows on BOTH the reference fit and the
  check tail; anything else is a reported no_reference — silent pass-through forbidden.

Channels (cross-sensor physics differences):
  sh: sh_phys -> {Ts, Lp};  sc: sc_phys -> {Tl, Hp};
  th_te: Th - te_sat -> {Th};  ta_th: Ta - Th -> {Ta}.
Detection tail: last max(50, 25%) steady rows of the checked record.
THRESHOLDS unchanged from M1 sample calibration — PROVISIONAL, M4 recalibrates.
HARD BAN unchanged: no raw-column-mean-vs-reference-mean trigger anywhere.
Factory fingerprint comparison stays stubbed until C4 factory data is adjudicated.
"""
import numpy as np
import pandas as pd

from fdd import conv, feat, seg
from fdd.drift import robust_sigma

SENSORS = ("Ta", "Ts", "Th", "Tl", "Lp", "Hp")
CHANNELS = ("sh", "sc", "th_te", "ta_th")
THRESHOLDS = {"sh": 0.8, "sc": 0.45, "th_te": 1.0, "ta_th": 1.2}   # provisional (M4)
CHANNEL_SENSORS = {
    "sh": ("Ts", "Lp"),
    "sc": ("Tl", "Hp"),
    "th_te": ("Th",),
    "ta_th": ("Ta",),
}
TAIL_MIN_ROWS = 50
TAIL_FRACTION = 0.25
MIN_BIN_N = 30          # bin judgeability floor (fit AND check sides)


def _steady_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Steady rows with mode, shared Ta bin, and the four channel series."""
    work = seg.segment(conv.materialize(df))
    st = work[work["steady"]]
    cooling = st["mode"].isin(("cooling", "cool_dehum")).to_numpy()
    return pd.DataFrame({
        "mode": st["mode"],
        "ta_bin": feat.ta_bin(st["Ta"]).to_numpy(),
        "sh": st["sh_phys"],
        "sc": st["sc_phys"],
        # MODE GATE (adjudicated): heating Th tracks frost phase (rule #9; it IS the
        # th_coil_resid feature) — a gauge cannot also be the measurand. Cooling pairs
        # Th with tc_sat (same side, condenser mid); heating is gated to no_reference.
        "th_te": np.where(cooling, st["Th"] - st["tc_sat"], np.nan),
        "ta_th": st["Ta"] - st["Th"],
    }, index=st.index)


def fit_reference(df: pd.DataFrame) -> dict:
    """Per-(mode, ta_bin) channel medians (+ MAD sigma) on steady rows; bins with
    fewer than MIN_BIN_N rows yield no reference (checked side reports no_reference)."""
    s = _steady_frame(df)
    ref = {}
    for (mode, tb), g in s.groupby(["mode", "ta_bin"]):
        if len(g) < MIN_BIN_N:
            continue
        ent = {}
        for ch in CHANNELS:
            v = g[ch].dropna()
            if len(v) >= MIN_BIN_N:
                ent[ch] = {"median": float(v.median()),
                           "mad_sigma": robust_sigma(v.to_numpy()), "n": len(v)}
        if ent:
            ref[(mode, int(tb))] = ent
    return ref


def check(df: pd.DataFrame, reference: dict) -> pd.DataFrame:
    """Per-sensor status against a binned reference. One row per sensor, always."""
    s = _steady_frame(df)
    tail_n = max(TAIL_MIN_ROWS, int(TAIL_FRACTION * len(s)))
    tail = s.iloc[-tail_n:]
    ch_status, ch_stats, ch_gated = {}, {}, {}
    for ch in CHANNELS:
        stats, exceeded, gated = {}, False, False
        for (mode, tb), g in tail.groupby(["mode", "ta_bin"]):
            v = g[ch].dropna()
            if len(v) < len(g) and ch == "th_te" and len(v) < MIN_BIN_N:
                gated = True            # heating rows are mode-gated NaN
            r = reference.get((mode, int(tb)))
            if r is None or ch not in r or len(v) < MIN_BIN_N:
                continue
            stat = float(v.median()) - r[ch]["median"]
            stats[(mode, int(tb))] = stat
            if abs(stat) > THRESHOLDS[ch]:
                exceeded = True
        ch_stats[ch] = stats
        ch_gated[ch] = gated and not stats
        ch_status[ch] = "flagged" if exceeded else ("ok" if stats else "no_reference")
    rows = []
    for sensor in SENSORS:
        owning = [c for c, ss in CHANNEL_SENSORS.items() if sensor in ss]
        statuses = [ch_status[c] for c in owning]
        status = ("flagged" if "flagged" in statuses
                  else "ok" if "ok" in statuses else "no_reference")
        reason = None
        if status == "no_reference":
            reason = "mode_gated" if any(ch_gated[c] for c in owning) else "bin_uncovered"
        rows.append({
            "sensor": sensor,
            "status": status,
            "reason": reason,           # optional; never asserted on
            "drift_flag": status == "flagged",
            "triggered_channels": [c for c in owning if ch_status[c] == "flagged"],
            "channel_stats": {c: ch_stats[c] for c in owning},
        })
    return pd.DataFrame(rows)


def fingerprint_check(df: pd.DataFrame, fingerprint) -> pd.DataFrame:
    """Factory-fingerprint comparison — STUB until C4 factory mapping is adjudicated."""
    raise NotImplementedError("C4 factory/production fingerprint comparison pending")
