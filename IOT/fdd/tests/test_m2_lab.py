"""M2 lab-data acceptance skeleton. Authored in Project, placed by human (rule 12).

WAIT-STATE BY DESIGN: every test here SKIPS until O1 delivers lab files into
data/raw/lab/. The skip reason names the blocker so the wait is visible in every
pytest run, not only in chat.

Pins API (implement at M2 start, after arrival-day schema diff):
  c4.load_lab(root) -> pd.DataFrame
      columns = C1 RAW_COLUMNS (after mapping-layer normalization)
                + ["sku", "test_condition", "condition_class"]
      condition_class in {"rating", "extreme"}; mapping layer may derive sku /
      test_condition from filenames or metadata. All format differences are absorbed
      in c4 (contract layer), never in downstream modules.
  c4.schema_diff(df) -> {"missing": [...], "extra": [...], "dtype_mismatch": [...]}
  baseline.fit_envelope(lab_df, sku) -> model      # model class decided at M2, not pinned
  baseline.predict_envelope(model, df) -> pd.DataFrame   # columns >= applicable TARGETS
  seg.transient_report(df) -> pd.DataFrame
      per test_condition: ["test_condition", "rows", "steady_share"]

Envelope DoD (dev doc v1.0, unchanged): leave-one-RATING-condition-out per SKU;
capacity MAPE <= 5 %; temperature MAE <= 1.0 K; evaluated on steady rows of the
held-out condition. Extreme conditions never enter envelope fit or holdout.

EXPECTED-RED NOTICE: test_sense_condition_invariance is ALLOWED to be red on
arrival day. ta_th (and possibly others) use sample-calibrated provisional
thresholds (margin 1.67x, logged in CLAUDE.md); failing across real condition
spread triggers threshold re-calibration via a Project-issued amendment.
Red here = scheduled work signal, not a stop condition.
"""
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAB_DIR = ROOT / "data" / "raw" / "lab"
_lab_present = LAB_DIR.exists() and any(LAB_DIR.iterdir())

pytestmark = [
    pytest.mark.m2,
    pytest.mark.skipif(not _lab_present,
                       reason="awaiting O1: lab data not found at data/raw/lab/"),
]

ESSENTIAL_LAB = {"Timestamp", "Ta", "Td", "Ts", "Th", "Tl", "Lp", "Hp", "Exv",
                 "CompRps", "FanRpm", "AcState", "CompState", "St", "Qh", "Qc",
                 "PowerComp", "Tcs"}

TEMP_TARGETS = ["Td", "tc_sat", "te_sat"]


@pytest.fixture(scope="session")
def lab():
    from fdd import c4
    return c4.load_lab(LAB_DIR)


def _capacity_col(mode: str) -> str:
    return "Qh" if mode == "heating" else "Qc"


def test_schema_resolves_essential(lab):
    """Amended 2026-07-03: bench-side sources cannot carry all 48 C1 columns
    (thermostat signals etc. do not exist on a test rig). Essential-18 must be
    present WITH REAL DATA (NaN-fill cannot satisfy this); the rest may be
    NaN-filled and must be listed in c4.NAN_FILLED for provenance."""
    from fdd import c4
    diff = c4.schema_diff(lab)
    assert not (set(diff["missing"]) & ESSENTIAL_LAB), \
        f"essential columns unresolved: {set(diff['missing']) & ESSENTIAL_LAB}"
    for col in sorted(ESSENTIAL_LAB - {"Timestamp"}):
        assert lab[col].notna().mean() > 0.5, f"{col} is NaN-dominated (fill loophole)"
    assert {"sku", "test_condition", "condition_class"} <= set(lab.columns)
    assert set(c4.NAN_FILLED).isdisjoint(ESSENTIAL_LAB)


def test_condition_coverage_minimum(lab):
    """Envelope holdout is statistically void below 4 rating conditions per SKU."""
    cov = lab[lab["condition_class"] == "rating"].groupby("sku")["test_condition"].nunique()
    assert len(cov) > 0
    assert (cov >= 4).all(), f"insufficient rating-condition coverage: {cov[cov < 4].to_dict()}"


@pytest.mark.skip(reason="leave-one MAPE<=5% demoted to M3 field DoD (FDD-I-007): lab "
                         "certification-point density (2-3 pts/mode) structurally cannot "
                         "support leave-one-condition-out; awaiting M3 field data")
def test_envelope_holdout_dod(lab):
    """M-BASE L1 leave-one-rating-condition-out. Low-order physical regression;
    frost conditions (H2/H4) carry a frost-phase covariate. H4 for 4860AA uses the
    unit-44 low-temp proxy anchor (h4_proxy=True). MAPE/MAE thresholds are DoD, not
    tunable; a proxy-anchor condition breaching them is a REPORTED signal, not a
    threshold to relax."""
    from fdd import baseline, conv, seg
    rating = lab[lab["rating_anchor"]]
    evaluated, failures = 0, []
    for sku, g in rating.groupby("sku"):
        conds = sorted(g["test_condition"].unique())
        if len(conds) < 4:
            continue
        for held in conds:
            train, test = g[g["test_condition"] != held], g[g["test_condition"] == held]
            model = baseline.fit_envelope(train, sku)
            t = seg.segment(test)
            t = conv.materialize(test)[t["rating_anchor"]] if "rating_anchor" in t else conv.materialize(test)
            if len(t) < 30:
                continue
            pred = baseline.predict_envelope(model, t)
            mode = "heating" if (test["AcState"] == 5).mean() > 0.5 else "cooling"
            cap = "Qh" if mode == "heating" else "Qc"
            mape = ((pred[cap] - t[cap]).abs() / t[cap].abs().clip(lower=1e-9)).mean()
            if mape > 0.05:
                failures.append((sku, held, "MAPE", cap, round(float(mape), 4)))
            for col in ["Td", "tc_sat", "te_sat"]:
                mae = (pred[col] - t[col]).abs().mean()
                if mae > 1.0:
                    failures.append((sku, held, "MAE", col, round(float(mae), 3)))
            evaluated += 1
    assert evaluated > 0, "no SKU has >=4 rating conditions with >=30 anchor rows"
    assert not failures, f"envelope DoD violations (proxy-anchor breaches are signals): {failures}"


def test_ssd_transient_report(lab):
    """Arrival-day version asserts the harness runs; steady-threshold re-pinning
    happens by amendment once real transient distributions are seen."""
    from fdd import seg
    ext = lab[lab["condition_class"] == "extreme"]
    assert len(ext) > 0, "no extreme-condition records delivered"
    rep = seg.transient_report(ext)
    assert {"test_condition", "rows", "steady_share"} <= set(rep.columns)
    assert len(rep) > 0


def test_sense_condition_invariance(lab):
    """v3 (Project-authored): binned-reference regime, within-unit, heating mode.
    (1) SELF: reference fitted on the first 60% (by time) of a condition's steady
        rows must yield zero flagged sensors on the last 40%.
    (2) CROSS: checking condition B against a reference fitted ONLY on condition A
        must yield per-sensor status in {ok, no_reference}; "flagged" is forbidden.
        no_reference is a legal, REPORTED outcome for uncovered Ta bins; silent
        pass-through is forbidden: one status row per sensor, always."""
    from fdd import sense
    rating = lab[lab["condition_class"] == "rating"]
    self_pairs, violations = 0, []
    for (sku, unit), g in rating.groupby(["sku", "unit"]):
        heat = g[g["AcState"] == 5]
        conds = sorted(heat["test_condition"].unique())
        for c in conds:
            gc = heat[heat["test_condition"] == c].sort_values("Timestamp")
            n = len(gc)
            if n < 100:
                continue
            ref = sense.fit_reference(gc.iloc[: int(n * 0.6)])
            out = sense.check(gc.iloc[int(n * 0.6):], ref)
            bad = out[out["status"] == "flagged"]["sensor"].tolist()
            if bad:
                violations.append(("self", sku, unit, c, bad))
            self_pairs += 1
        if len(conds) >= 2:
            a, b = conds[0], conds[1]
            ref = sense.fit_reference(heat[heat["test_condition"] == a])
            out = sense.check(heat[heat["test_condition"] == b], ref)
            assert set(out["status"]) <= {"ok", "flagged", "no_reference"}
            assert len(out) == len(sense.SENSORS)
            bad = out[out["status"] == "flagged"]["sensor"].tolist()
            if bad:
                violations.append(("cross", sku, unit, a, b, bad))
    if self_pairs == 0:
        pytest.skip("no condition offers >=100 steady rows -- gated by O1")
    assert not violations, f"invariance violations: {violations}"
