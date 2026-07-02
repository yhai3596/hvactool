"""M-FEAT feature registry (M1). Bins: mode x Ta(2K) x CompRps(10 bands). Rules #3 #4 #5 #9 #10 bind.

API (pinned by tests/test_m1_feat.py):
  REGISTRY (13, locked + two adopted 2026-07-02: tf_resid, indoor_load_proxy)
  fit_baseline(raw_df) -> model      # 3-level binned means fitted on steady rows
  compute(raw_df, model) -> DataFrame  # steady rows only, ORIGINAL row index kept,
                                       # columns REGISTRY + bin_id + fallback_level
  defrost_frequency(raw_df) -> float  # events/hour, whole record

All physical quantities come from conv.materialize; reported Sh/Sc are NEVER read
(rule: physics scope only -- sc via sc_phys, sh not a heating feature at all, rule #3).

Sparse-bin fallback (pinned): a bin needs n >= MIN_BIN_N steady rows, else fall back
to the mode x Ta marginal baseline, else to the mode-global baseline. Rows are never
dropped for sparsity; fallback_level (0/1/2) records the level used per row.

defrost_freq is deliberately NOT in REGISTRY: registry features are per-steady-row
residuals, defrost frequency is a whole-record event rate whose time base includes
defrost segments -- it lives in the standalone defrost_frequency().
"""
import numpy as np
import pandas as pd

from fdd import conv, seg

REGISTRY = (
    "exv_resid", "sc_resid", "capacity_resid", "approach", "th_coil_resid",
    "comp_slip", "fan_slip", "power_resid", "p_parasitic", "tcs_gap",
    "i_resid", "tf_resid", "indoor_load_proxy",
)

MIN_BIN_N = 12                                  # >= 2 min of 10 s rows per bin
TA_BIN_K = 2.0                                  # Ta bin step (K)
RPS_BAND_W = conv.COMP_RPS_FULLSCALE / 10.0     # 10 CompRps bands over full scale
V1_NOMINAL = 230.0                              # rule #5: V1-covariate normalization
LOAD_PROXY_WIN_MIN = 30.0                       # YSignal duty-cycle window (minutes)

_COOLING_MODES = ("cooling", "cool_dehum")
# quantities whose residuals need a binned baseline
_BASE_QTYS = ["Exv", "sc_phys", "q_cap", "Th", "i_va", "Tf"]
_KEYS0 = ["mode", "ta_bin", "rps_bin"]
_KEYS1 = ["mode", "ta_bin"]


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    """materialize + segment + bin keys + baseline source quantities."""
    work = seg.segment(conv.materialize(df))
    work["ta_bin"] = np.floor(work["Ta"] / TA_BIN_K).astype(int)
    work["rps_bin"] = np.clip(np.floor(work["CompRps"] / RPS_BAND_W), 0, 9).astype(int)
    cooling = work["mode"].isin(_COOLING_MODES)
    work["q_cap"] = np.where(cooling, work["Qc"], work["Qh"])   # capacity source per mode
    work["i_va"] = work["I2"] * work["V1"]                      # rule #5: VA, V1 covariate
    # indoor load proxy: YSignal rolling duty cycle. COVARIATE ONLY (third-party
    # indoor unit, no comms) -- never an indoor-side diagnostic.
    elapsed = seg._elapsed_seconds(work)
    cadence = float(np.median(np.diff(elapsed))) if len(work) > 1 else seg.FALLBACK_CADENCE_S
    win = max(1, int(round(LOAD_PROXY_WIN_MIN * 60.0 / cadence)))
    work["indoor_load_proxy"] = work["YSignal"].rolling(win, min_periods=1).mean()
    return work


def fit_baseline(df: pd.DataFrame) -> dict:
    """Fit 3-level same-condition baselines on steady rows.
    Level 0: mode x Ta(2K) x CompRps band; level 1: mode x Ta; level 2: mode."""
    st = _prepare(df).loc[lambda w: w["steady"]]
    g0, g1, g2 = st.groupby(_KEYS0), st.groupby(_KEYS1), st.groupby("mode")
    return {
        "lvl0_mean": g0[_BASE_QTYS].mean(), "lvl0_n": g0.size(),
        "lvl1_mean": g1[_BASE_QTYS].mean(), "lvl1_n": g1.size(),
        "lvl2_mean": g2[_BASE_QTYS].mean(),
        "global_mean": st[_BASE_QTYS].mean(),   # last resort for unseen modes
    }


def compute(df: pd.DataFrame, model: dict) -> pd.DataFrame:
    """Per-steady-row features. Keeps the original row index (steady subset);
    never drops a row for bin sparsity (fallback instead)."""
    st = _prepare(df).loc[lambda w: w["steady"]]
    keys0 = pd.MultiIndex.from_frame(st[_KEYS0])
    keys1 = pd.MultiIndex.from_frame(st[_KEYS1])
    keys2 = st["mode"].to_numpy()

    n0 = model["lvl0_n"].reindex(keys0).fillna(0).to_numpy()
    n1 = model["lvl1_n"].reindex(keys1).fillna(0).to_numpy()
    level = np.where(n0 >= MIN_BIN_N, 0, np.where(n1 >= MIN_BIN_N, 1, 2))

    base = {}
    for q in _BASE_QTYS:
        b0 = model["lvl0_mean"][q].reindex(keys0).to_numpy()
        b1 = model["lvl1_mean"][q].reindex(keys1).to_numpy()
        b2 = model["lvl2_mean"][q].reindex(keys2).fillna(model["global_mean"][q]).to_numpy()
        base[q] = np.select([level == 0, level == 1], [b0, b1], default=b2)

    cooling = st["mode"].isin(_COOLING_MODES).to_numpy()
    out = pd.DataFrame(index=st.index)
    out["exv_resid"] = st["Exv"].to_numpy() - base["Exv"]
    out["sc_resid"] = st["sc_phys"].to_numpy() - base["sc_phys"]      # rule #2 upstream
    out["capacity_resid"] = (st["q_cap"].to_numpy() - base["q_cap"]) / base["q_cap"]
    # approach is mode-dependent (rule #9: TH/coil semantics flip with mode)
    out["approach"] = np.where(cooling,
                               st["tc_sat"].to_numpy() - st["Ta"].to_numpy(),
                               st["Ta"].to_numpy() - st["te_sat"].to_numpy())
    out["th_coil_resid"] = st["Th"].to_numpy() - base["Th"]           # mode is in the bin key
    out["comp_slip"] = st["comp_slip"].to_numpy()
    out["fan_slip"] = st["fan_slip"].to_numpy()
    out["power_resid"] = st["PowerComp"].to_numpy() - st["PowerCompTheo"].to_numpy()  # rule #4
    out["p_parasitic"] = st["p_parasitic"].to_numpy()                 # rule #4
    out["tcs_gap"] = st["tcs_gap"].to_numpy()                         # rule #8
    out["i_resid"] = (st["i_va"].to_numpy() - base["i_va"]) / V1_NOMINAL  # rule #5
    out["tf_resid"] = st["Tf"].to_numpy() - base["Tf"]
    out["indoor_load_proxy"] = st["indoor_load_proxy"].to_numpy()
    out["bin_id"] = (st["mode"].astype(str) + "|ta" + st["ta_bin"].astype(str)
                     + "|rps" + st["rps_bin"].astype(str))
    out["fallback_level"] = level
    return out


def defrost_frequency(df: pd.DataFrame) -> float:
    """Whole-record defrost event rate (events/hour). Events = St-keyed defrost
    segments (rule #7); time base = TOTAL record duration incl. defrost segments,
    which is why this is not a registry (per-steady-row) feature."""
    work = seg.segment(df)
    n_events = work.loc[work["segment_type"] == "defrost", "segment_id"].nunique()
    elapsed = seg._elapsed_seconds(work)
    hours = float(elapsed.iloc[-1] - elapsed.iloc[0]) / 3600.0
    return n_events / hours if hours > 0 else float("nan")
