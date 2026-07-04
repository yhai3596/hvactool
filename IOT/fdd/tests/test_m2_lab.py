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

import numpy as np
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
    """Coverage counts rating conditions per SKU, but ONLY from healthy_baseline units.
    Fault-injected units' conditions must NOT count toward baseline coverage — otherwise
    envelope would fit a healthy baseline on fault data (false GREEN). This aligns the
    coverage gate with the anchor-layer split (FDD-I-012 Item 1: injected units have
    rating_anchor zeroed)."""
    healthy = lab[lab["data_type"] == "healthy_baseline"] if "data_type" in lab.columns else lab
    rating = healthy[healthy["condition_class"] == "rating"]
    cov = rating.groupby("sku")["test_condition"].nunique()
    insufficient = cov[cov < 4]
    assert insufficient.empty, f"SKUs below 4 healthy rating conditions: {insufficient.to_dict()}"


def test_injected_unit_excluded_from_baseline():
    """A fault-injected unit's rows must be zeroed from rating_anchor (excluded from
    envelope baseline) while still flowing into the diagnostic chain. Guards the
    FDD-I-012 Item 1 split against regression when real injected data arrives."""
    from fdd import c4
    # synthetic: one injected unit, rating-condition-like steady rows
    df = c4._make_synthetic_injected_unit()  # helper: data_type=fault_injected, steady H1-like rows
    assert (df["rating_anchor"] == False).all(), "injected unit leaked into rating_anchor (baseline)"
    assert len(df) > 0, "injected unit rows dropped entirely — must flow to diagnostic chain"


def test_envelope_physical_plausibility(lab):
    """M2 envelope DoD: physical plausibility, not leave-one-out MAPE (that is M3,
    field data). Three checks per SKU/mode (FDD-I-008 two-tier DoD):
    (1) MONOTONICITY (sign corrected FDD-I-009): heating Qh rises with Ta, cooling
        Qc falls with Ta — standard heat-pump physics.
    (2) MAGNITUDE (relaxed FDD-I-009): capacity positive, adjacent-condition capacity
        ratio within [0.3, 3.0] (no order-of-magnitude jump). Absolute per-condition
        rated-value check deferred to M3 (needs AHRI cert rated table).
    (3) NO PATHOLOGICAL EXTRAPOLATION: single-condition mode uses mean, no slope
        extrapolation across large Ta gaps.
    """
    from fdd import baseline
    rating = lab[lab["rating_anchor"]]
    violations = []
    for sku, g in rating.groupby("sku"):
        model = baseline.fit_envelope(g, sku)
        for mode, cap_col, expect_sign in [("heating", "Qh", +1), ("cooling", "Qc", -1)]:
            gm = g[g["AcState"] == 5] if mode == "heating" else g[g["AcState"] == 4]
            conds = sorted(gm["test_condition"].unique())
            if len(conds) < 2:
                continue  # single-condition: monotonicity N/A, checked by (3)
            # (1) monotonicity sign
            slope = baseline.capacity_ta_slope(model, mode)
            if np.sign(slope) != expect_sign and abs(slope) > 0.01:
                violations.append((sku, mode, "monotonicity", round(float(slope), 4),
                                   f"expected sign {expect_sign}"))
            # (2) magnitude: positive + adjacent ratio in [0.3, 3.0]
            caps = [baseline.predicted_capacity(model, mode, c) for c in conds]
            if any(cval <= 0 for cval in caps):
                violations.append((sku, mode, "non_positive_capacity", caps))
            for i in range(len(caps) - 1):
                ratio = caps[i + 1] / caps[i] if caps[i] > 0 else float("inf")
                if not (0.3 <= ratio <= 3.0):
                    violations.append((sku, mode, "magnitude_jump", conds[i:i+2],
                                       round(float(ratio), 2)))
        # (3) no pathological extrapolation
        for mode in ["heating", "cooling"]:
            if baseline.has_pathological_extrapolation(model, mode):
                violations.append((sku, mode, "pathological_extrapolation"))
    assert not violations, f"envelope physical-plausibility violations: {violations}"


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
    """M-SEG steady-state detector validation on extreme conditions. transient_report
    is not a generic report -- it verifies the SSD thresholds (calibrated on a narrow
    5h warm-winter sample + 7 defrost events) hold on the conditions most likely to
    break them: extreme conditions (oil-return, defrost, deep cold/hot) with violent
    transients. Extreme conditions carry condition labels in lab data, serving as the
    check set for steady segmentation.

    Asserts three physical invariants the SSD must satisfy on extreme conditions:
    (1) Oil-return segments produce NO steady rows (compressor oil-injection, violent
        parameter swings -- steadiness there is a detector failure).
    (2) Defrost segments (CompState==2) produce NO rating_anchor rows (they are
        excluded from steady by definition; any anchor is a segmentation leak).
    (3) steady_share on any extreme condition does not exceed steady_share on the
        matched rating condition of the same SKU/mode (extreme should be LESS steady;
        inversion means the detector is too permissive).

    回油验证 awaiting O1 回油数据 (FDD-I-010 item 1): no oil-return condition exists in
    the delivered lab data, so assertion (1)'s oil subset is empty until O1 delivers
    oil-return runs; (2)/(3) are exercised on the H_low20 -20C extreme.
    """
    from fdd import seg
    rep = seg.transient_report(lab)
    assert {"sku", "test_condition", "condition_class", "rows",
            "steady_share", "anchor_rows"} <= set(rep.columns)

    ext = rep[rep["condition_class"] == "extreme"]
    if len(ext) == 0:
        pytest.skip("no extreme-condition records in delivered lab data")

    violations = []
    # (1) oil-return: zero steady
    oil = ext[ext["test_condition"].str.contains("oil|回油|OIL", case=False, na=False)]
    for _, r in oil.iterrows():
        if r["steady_share"] > 0.0:
            violations.append(("oil_return_has_steady", r["sku"], r["test_condition"],
                               round(float(r["steady_share"]), 3)))

    # (2) defrost: zero rating_anchor
    defrost = ext[ext["test_condition"].str.contains("defrost|除霜|DEF", case=False, na=False)]
    for _, r in defrost.iterrows():
        if r["anchor_rows"] > 0:
            violations.append(("defrost_has_anchor", r["sku"], r["test_condition"],
                               int(r["anchor_rows"])))

    # (3) extreme steady_share <= matched rating steady_share (same SKU)
    rating = rep[rep["condition_class"] == "rating"]
    for _, er in ext.iterrows():
        same_sku_rating = rating[rating["sku"] == er["sku"]]
        if len(same_sku_rating) == 0:
            continue
        max_rating_steady = same_sku_rating["steady_share"].max()
        if er["steady_share"] > max_rating_steady + 0.05:  # 5% tolerance
            violations.append(("extreme_steadier_than_rating", er["sku"],
                               er["test_condition"], round(float(er["steady_share"]), 3),
                               round(float(max_rating_steady), 3)))

    assert not violations, f"SSD transient-report violations: {violations}"


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
