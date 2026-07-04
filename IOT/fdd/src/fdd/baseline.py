"""M-BASE (M2). L1 per-SKU envelope = LOW-ORDER PHYSICAL REGRESSION (FDD-I-006 #2).

4 rating points / SKU is two orders of magnitude short of a statistical-learning model's
sample need, so L1 is a physics-shaped low-order regression, NOT XGBoost (tree DoD is an
M4 fleet-label task per the locked finding):
  - capacity (Qh heating / Qc cooling) ~ linear in Ta, fit per mode;
  - saturation temps (tc_sat, te_sat) and discharge Td ~ linear in Ta, per mode;
  - frost-condition points (H2/H4) carry a frost-phase covariate (frosting vs clean coil)
    so the frost offset does not contaminate the Ta slope.
One model per SKU; predict picks the sub-model by the row's mode (AcState).

L2 factory fingerprint (charge-state EXCLUDED) and L3 field baseline remain stubbed.
"""
import numpy as np
import pandas as pd

from fdd import conv

ENVELOPE_TARGETS = ("Qh", "Qc", "tc_sat", "te_sat", "Td")
_MODE_AC = {"heating": 5, "cooling": 4}
SURR_LO, SURR_HI = 0.70, 1.30           # capacity-level band vs rated (plausibility)


def _materialized(df: pd.DataFrame) -> pd.DataFrame:
    return df if "tc_sat" in df.columns else conv.materialize(df)


def _frost_covariate(sub: pd.DataFrame) -> np.ndarray:
    """1.0 for frosting-steady rows, else 0.0 (clean coil / no-frost)."""
    if "anchor_type" in sub.columns:
        return (sub["anchor_type"] == "frosting_steady").to_numpy(dtype=float)
    return np.zeros(len(sub))


def fit_envelope(train_df: pd.DataFrame, sku: str) -> dict:
    """Per-mode low-order physical regression. Design matrix = [Ta, frost, 1];
    frost column dropped when a mode has no frost variation (keeps it low-order)."""
    d = _materialized(train_df)
    model = {"sku": sku, "heating": {}, "cooling": {}}
    for mode, ac in _MODE_AC.items():
        sub = d[d["AcState"] == ac]
        if not len(sub):
            continue
        Ta = sub["Ta"].to_numpy(dtype=float)
        frost = _frost_covariate(sub)
        # A Ta slope is only real ACROSS conditions: a single lab condition spans ~1-2 K
        # of Ta noise, and fitting a slope inside it captures noise that extrapolates
        # catastrophically. Require >=2 distinct rating conditions for a slope; frost is a
        # usable covariate only if SEPARABLE from Ta (collinear in this data -> dropped).
        n_cond = sub["test_condition"].nunique() if "test_condition" in sub.columns else 1
        use_frost = (n_cond >= 2 and frost.std() > 0.0
                     and abs(np.corrcoef(Ta, frost)[0, 1]) < 0.9)
        cols = [Ta, frost, np.ones(len(sub))] if use_frost else [Ta, np.ones(len(sub))]
        X = np.column_stack(cols)
        for tgt in ENVELOPE_TARGETS:
            if tgt not in sub.columns:
                continue
            y = sub[tgt].to_numpy(dtype=float)
            m = np.isfinite(y) & np.isfinite(Ta)
            if m.sum() < 2:
                continue
            if n_cond < 2:                      # single condition -> intercept only (robust)
                coef = {"kind": "mean", "value": float(np.mean(y[m]))}
            else:
                beta, *_ = np.linalg.lstsq(X[m], y[m], rcond=None)
                coef = {"kind": "linear", "beta": beta, "use_frost": use_frost}
            model[mode][tgt] = coef
    return model


def predict_envelope(model: dict, df: pd.DataFrame) -> pd.DataFrame:
    """Predict envelope targets for each row (by its mode). Columns = ENVELOPE_TARGETS."""
    d = _materialized(df)
    Ta = d["Ta"].to_numpy(dtype=float)
    frost = _frost_covariate(d)
    ac = d["AcState"].to_numpy()
    out = pd.DataFrame(index=d.index)
    for tgt in ENVELOPE_TARGETS:
        pred = np.full(len(d), np.nan)
        for mode, acode in _MODE_AC.items():
            coef = model.get(mode, {}).get(tgt)
            if coef is None:
                continue
            sel = ac == acode
            if not sel.any():
                continue
            if coef["kind"] == "mean":
                pred[sel] = coef["value"]
            else:
                beta = coef["beta"]
                if coef["use_frost"]:
                    pred[sel] = beta[0] * Ta[sel] + beta[1] * frost[sel] + beta[2]
                else:
                    pred[sel] = beta[0] * Ta[sel] + beta[1]
        out[tgt] = pred
    return out


def physical_plausibility(model: dict, train_df: pd.DataFrame, rated_kw: float) -> dict:
    """M2 lab-stage envelope DoD = PHYSICAL PLAUSIBILITY (leave-one MAPE demoted to M3).
    Reports, per mode, three criteria:
      (1) capacity monotonicity in Ta  — the fitted slope's SIGN (reported, not asserted:
          the expected direction is Project-adjudicated when the test is drafted;
          measured data shows heating Qh RISES with Ta and cooling Qc falls, the physical
          heat-pump direction);
      (2) capacity level in [0.7,1.3] x rated PER CONDITION (nominal band used here; a
          cold-derated point like H4 legitimately sits below the nominal band and needs
          its own AHRI-rated value — flagged, not auto-failed);
      (3) no ill-conditioned extrapolation (single condition -> mean; already enforced).
    Returns a per-mode/per-condition report; NOT a hard gate (the drafted test is next)."""
    d = _materialized(train_df)
    rep = {"sku": model.get("sku"), "modes": {}, "conditions": {}}
    for mode, cap in (("cooling", "Qc"), ("heating", "Qh")):
        c = model.get(mode, {}).get(cap)
        if c is None:
            rep["modes"][mode] = {"status": "no_model"}
        elif c["kind"] == "mean":
            rep["modes"][mode] = {"kind": "mean", "slope": None, "extrap_safe": True,
                                  "cap_kw": c["value"]}
        else:
            rep["modes"][mode] = {"kind": "linear", "slope_kw_per_K": float(c["beta"][0]),
                                  "capacity_rises_with_Ta": bool(c["beta"][0] > 0),
                                  "extrap_safe": True}
    if "test_condition" in d.columns:
        for cond, g in d.groupby("test_condition"):
            cap = "Qh" if g["AcState"].median() == 5 else "Qc"
            lvl = float(g[cap].median())
            rep["conditions"][cond] = {
                "cap_kw": round(lvl, 2), "frac_of_nominal": round(lvl / rated_kw, 3),
                "in_nominal_band": SURR_LO * rated_kw <= lvl <= SURR_HI * rated_kw}
    return rep


def fit_fingerprint(prod_df):
    """L2 factory component fingerprint (charge-state EXCLUDED) — STUB until C4 factory."""
    raise NotImplementedError("L2 factory fingerprint pending C4 factory mapping")
