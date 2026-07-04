"""M-SENSE sensor trust layer — v4 (M2, FDD-I-006). Steady rows via seg; physics via
conv.materialize; reported Sh/Sc are NEVER read.

Trust-source map (locked finding, "condition quantity must not double as the trust check
for a sensor it contains"):
  Ts / Tl / Lp / Hp  <- steady P-T consistency (sh / sc channels, binned reference)
  Th                 <- defrost-plateau Th - tc_sat (consensus at the coil plateau)
  Ta                 <- off-equalization check (>4 h off: refrigerant settled, all temps
                        converge; a Ta-FREE reference for the ambient sensor)
  ta_th / th_te      <- CONTEXT ONLY (condition / frost-phase monitoring for M-DIAG);
                        they NEVER emit a sensor flag.

Why ta_th is downgraded: ta_th = Ta - Th is collinear with a Ta bias — the bias moves the
point along the within-bin Ta slope and is inseparable from it (proven over two failed
detection attempts, FDD-I-004/005). This is the 2nd instance of the gauge/measurand
separation principle (1st: th_te frost phase).

check() output: one row per sensor with status in {ok, flagged, no_reference};
drift_flag == (status == "flagged") (compat); reason in {mode_gated, bin_uncovered,
no_off_segment, no_defrost_plateau, context_only}; channel_stats / context_stats for
diagnostics. THRESHOLDS provisional (M4); off-equalization / plateau thresholds M3.
Factory fingerprint comparison stays stubbed until C4.
"""
import numpy as np
import pandas as pd

from fdd import config, conv, feat, seg
from fdd.drift import robust_sigma

SENSORS = ("Ta", "Ts", "Th", "Tl", "Lp", "Hp")
FLAG_CHANNELS = ("sh", "sc")            # only these emit sensor flags
CONTEXT_CHANNELS = ("ta_th", "th_te")   # computed, output as context, NEVER flag
# thresholds from config/calibration.yaml (FDD-I-012 #2); provisional, M4 recal
THRESHOLDS = {"sh": config.cal("sense.threshold_sh"), "sc": config.cal("sense.threshold_sc")}
CHANNEL_SENSORS = {"sh": ("Ts", "Lp"), "sc": ("Tl", "Hp")}
TAIL_MIN_ROWS = 50
TAIL_FRACTION = 0.25
MIN_BIN_N = config.cal("sense.min_bin_n")

# off-equalization (Ta-free ambient trust) — provisional, M3 real-data calibration
OFF_MIN_HOURS = 4.0
OFF_MIN_ROWS = 20                        # min off-cycle rows for a verdict
OFF_EQ_THRESHOLD = config.cal("sense.off_eq_threshold")   # consensus deviation (K)
OFF_CONSENSUS_TEMPS = ("Ta", "Th", "Ts", "Tl")
# defrost-plateau Th trust
TH_PLATEAU_THRESHOLD = config.cal("sense.th_plateau_threshold")   # Th - tc_sat plateau (K)


def _steady_frame(df: pd.DataFrame) -> pd.DataFrame:
    """rating_anchor rows with mode, Ta bin, and the four channel series (two flag,
    two context)."""
    work = seg.segment(conv.materialize(df))
    st = work[work["rating_anchor"]]
    cooling = st["mode"].isin(("cooling", "cool_dehum")).to_numpy()
    return pd.DataFrame({
        "mode": st["mode"],
        "ta_bin": feat.ta_bin(st["Ta"]).to_numpy(),
        "sh": st["sh_phys"],
        "sc": st["sc_phys"],
        # context channels: th_te mode-gated to cooling (heating Th is frost phase),
        # ta_th = Ta - Th (condition/load proxy). Neither flags a sensor.
        "th_te": np.where(cooling, st["Th"] - st["tc_sat"], np.nan),
        "ta_th": (st["Ta"] - st["Th"]).to_numpy(),
    }, index=st.index)


def fit_reference(df: pd.DataFrame) -> dict:
    """Binned medians for the flag channels (+ context channels for M-DIAG) and the
    defrost-plateau Th - tc_sat reference. Off-equalization needs no fit (check-time
    consensus)."""
    s = _steady_frame(df)
    ref = {ch: {} for ch in FLAG_CHANNELS + CONTEXT_CHANNELS}
    for ch in FLAG_CHANNELS + CONTEXT_CHANNELS:
        for (mode, b), g in s.groupby(["mode", "ta_bin"]):
            v = g[ch].dropna().to_numpy()
            if len(v) >= MIN_BIN_N:
                ref[ch][(mode, int(b))] = {"median": float(np.median(v)),
                                           "mad_sigma": robust_sigma(v), "n": len(v)}
    plateau = _defrost_plateau_delta(df)
    ref["_th_plateau"] = {"median": float(np.median(plateau))} if len(plateau) else None
    return ref


def _defrost_plateau_delta(df: pd.DataFrame) -> np.ndarray:
    """Th - tc_sat over defrost-plateau rows (Th at >=90% of the defrost-segment peak).
    Coil-side consensus that is independent of the Th steady baseline."""
    work = seg.segment(conv.materialize(df)) if "segment_type" not in df else df
    out = []
    defr = work[work["segment_type"] == "defrost"]
    if not len(defr):
        return np.array([])
    for _, g in defr.groupby("segment_id"):
        pk = g["Th"].max()
        if pk < 5.0:
            continue
        p = g[g["Th"] >= 0.9 * pk]
        out.append((p["Th"] - p["tc_sat"]).to_numpy())
    return np.concatenate(out) if out else np.array([])


def check_off_cycle_equalization(df: pd.DataFrame) -> pd.DataFrame:
    """Ta-FREE trust source. In an off cycle (CompRps==0) the refrigerant settles and the
    convergent temps (OFF_CONSENSUS_TEMPS) agree; a sensor deviating from the cross-sensor
    consensus median by > OFF_EQ_THRESHOLD is suspected drifting. One row per sensor
    [sensor, status, drift_flag, deviation]; pressures / absent temps -> no_reference.

    Operates on the raw temp columns directly (no seg/materialize) so a short SETTLED off
    segment (a synthetic M3-stub segment) is judgeable. Real running records feed this via
    check(), which only passes off segments > OFF_MIN_HOURS."""
    d = df[df["CompRps"] == 0] if "CompRps" in df.columns else df
    temps = [c for c in OFF_CONSENSUS_TEMPS if c in d.columns]
    judge = len(d) >= OFF_MIN_ROWS and len(temps) >= 3
    med, consensus = {}, None
    if judge:
        settled = d.iloc[len(d) // 2:]                       # 2nd half = settled
        med = {c: float(settled[c].median()) for c in temps}
        consensus = float(np.median(list(med.values())))     # robust cross-sensor center
    rows = []
    for s in SENSORS:
        if judge and s in med:
            dev = med[s] - consensus
            status = "flagged" if abs(dev) > OFF_EQ_THRESHOLD else "ok"
            rows.append({"sensor": s, "status": status,
                         "drift_flag": status == "flagged", "deviation": dev})
        else:
            rows.append({"sensor": s, "status": "no_reference",
                         "drift_flag": False, "deviation": np.nan})
    return pd.DataFrame(rows)


def check(df: pd.DataFrame, reference: dict) -> pd.DataFrame:
    """Per-sensor trust status. Ts/Tl/Lp/Hp via sh/sc; Th via defrost plateau; Ta via
    off-equalization; ta_th/th_te are context-only (never flag)."""
    s = _steady_frame(df)
    tail_n = max(TAIL_MIN_ROWS, int(TAIL_FRACTION * len(s)))
    tail = s.iloc[-tail_n:]

    # --- flag channels (sh/sc) ---
    ch_status, ch_stats = {}, {}
    for ch in FLAG_CHANNELS:
        stats, exceeded = {}, False
        for (mode, tb), g in tail.groupby(["mode", "ta_bin"]):
            v = g[ch].dropna().to_numpy()
            r = reference.get(ch, {}).get((mode, int(tb)))
            if r is None or len(v) < MIN_BIN_N:
                continue
            stat = float(np.median(v)) - r["median"]
            stats[(mode, int(tb))] = stat
            if abs(stat) > THRESHOLDS[ch]:
                exceeded = True
        ch_stats[ch] = stats
        ch_status[ch] = "flagged" if exceeded else ("ok" if stats else "no_reference")

    # --- context channels (ta_th/th_te): stats only, no flag ---
    ctx = {}
    for ch in CONTEXT_CHANNELS:
        vals = {}
        for (mode, tb), g in tail.groupby(["mode", "ta_bin"]):
            v = g[ch].dropna().to_numpy()
            if len(v) >= MIN_BIN_N:
                vals[(mode, int(tb))] = float(np.median(v))
        ctx[ch] = vals

    # --- Ta via off-cycle equalization (only off segments > OFF_MIN_HOURS qualify) ---
    ta_status, ta_dev = "no_reference", np.nan
    work_full = seg.segment(conv.materialize(df))
    el = seg._elapsed_seconds(work_full)
    for _, g in work_full[work_full["segment_type"] == "off"].groupby("segment_id"):
        dur_h = (el.loc[g.index].iloc[-1] - el.loc[g.index].iloc[0]) / 3600.0
        if dur_h >= OFF_MIN_HOURS:
            r = check_off_cycle_equalization(g).set_index("sensor").loc["Ta"]
            ta_status = r["status"]
            ta_dev = float(r["deviation"]) if pd.notna(r["deviation"]) else np.nan
    # --- Th via defrost plateau ---
    th_status, th_dev = "no_reference", np.nan
    rp = reference.get("_th_plateau")
    plateau = _defrost_plateau_delta(df)
    if rp is not None and len(plateau):
        th_dev = float(np.median(plateau) - rp["median"])
        th_status = "flagged" if abs(th_dev) > TH_PLATEAU_THRESHOLD else "ok"

    rows = []
    for sensor in SENSORS:
        owning = [c for c, ss in CHANNEL_SENSORS.items() if sensor in ss]
        if owning:                                   # Ts/Tl/Lp/Hp -> sh/sc
            statuses = [ch_status[c] for c in owning]
            status = ("flagged" if "flagged" in statuses
                      else "ok" if "ok" in statuses else "no_reference")
            reason = None if status != "no_reference" else "bin_uncovered"
            cstats = {c: ch_stats[c] for c in owning}
        elif sensor == "Ta":                         # off-cycle equalization
            status = ta_status
            reason = None if status != "no_reference" else "no_off_segment"
            cstats = {"off_equalization": ta_dev}
        elif sensor == "Th":                         # defrost plateau
            status = th_status
            reason = None if status != "no_reference" else "no_defrost_plateau"
            cstats = {"th_plateau_delta": th_dev}
        else:
            status, reason, cstats = "no_reference", "context_only", {}
        rows.append({
            "sensor": sensor,
            "status": status,
            "reason": reason,
            "drift_flag": status == "flagged",
            "channel_stats": cstats,
            "context_stats": {c: ctx[c] for c in CONTEXT_CHANNELS},
        })
    return pd.DataFrame(rows)


def fingerprint_check(df: pd.DataFrame, fingerprint) -> pd.DataFrame:
    """Factory-fingerprint comparison — STUB until C4 factory mapping is adjudicated."""
    raise NotImplementedError("C4 factory/production fingerprint comparison pending")
