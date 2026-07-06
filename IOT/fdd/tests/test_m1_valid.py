"""M-VALID + M-DIAG skeleton acceptance tests. Authored in Project, placed by human (rule 12).

Pins API:
  valid.leave_units_out_splits(df, unit_col, n_folds=3) -> list[(train_idx, test_idx)]
      unit-disjoint folds; every unit appears in exactly one test fold. Row-level random
      splitting is forbidden project-wide (CLAUDE.md validation law).
  valid.score_events(preds, truths, match_days=7) -> dict
      preds/truths: DataFrames [unit, day(int), family]; matching = same unit and
      |day delta| <= match_days. Categories (event-level Yuill-Braun):
        correct      matched, same family
        misdiagnosis matched, different family (pred family not in {None,"no_response"})
        no_response  matched, pred family in {None,"no_response"}
        missed       truth with no matching pred
        false_alarm  pred with no matching truth
      returns {"correct","missed","false_alarm","misdiagnosis","no_response"} -> int
  diag.diagnose(row: dict, mode: str, exv_saturated: bool = False) -> dict
      returns C5-shaped dict with keys >= {"fault_hypothesis","evidence","counter_evidence",
      "confidence","field_checklist"}; evidence items expose feature names via
      [e["feature"] for e in evidence].
      v0 hardcoded physics priors:
        heating leak: exv_resid UP + sc_resid DOWN + capacity_resid DOWN -> refrigerant_low_or_leak
        rule #3 gate: any sh-based evidence admitted ONLY when exv_saturated is True
        indoor flag: capacity_resid DOWN with refrigerant side clean -> indoor_side_nonspecific
        near-zero row -> "none"
"""
import pandas as pd
import pytest

from fdd import diag, valid
from fdd.diag import diagnose

pytestmark = pytest.mark.m1


# ---------------- valid ----------------

def test_leave_units_out_disjoint_and_complete():
    df = pd.DataFrame({
        "hash_sn": [u for u in "ABCDEF" for _ in range(4)],
        "x": range(24),
    })
    splits = valid.leave_units_out_splits(df, unit_col="hash_sn", n_folds=3)
    assert len(splits) == 3
    tested = []
    for train_idx, test_idx in splits:
        tr = set(df.loc[train_idx, "hash_sn"])
        te = set(df.loc[test_idx, "hash_sn"])
        assert tr.isdisjoint(te)
        tested.extend(te)
    assert sorted(tested) == list("ABCDEF")  # each unit tests exactly once


def test_score_events_five_categories():
    truths = pd.DataFrame([
        {"unit": "A", "day": 10, "family": "refrigerant_low_or_leak"},
        {"unit": "B", "day": 20, "family": "sensor_fault"},
        {"unit": "C", "day": 30, "family": "refrigerant_low_or_leak"},
        {"unit": "E", "day": 40, "family": "refrigerant_low_or_leak"},
    ])
    preds = pd.DataFrame([
        {"unit": "A", "day": 12, "family": "refrigerant_low_or_leak"},  # correct
        {"unit": "B", "day": 21, "family": "refrigerant_low_or_leak"},  # misdiagnosis
        {"unit": "D", "day": 5,  "family": "refrigerant_low_or_leak"},  # false_alarm
        {"unit": "E", "day": 40, "family": "no_response"},              # no_response
    ])                                                                   # C -> missed
    s = valid.score_events(preds, truths, match_days=7)
    assert s == {"correct": 1, "missed": 1, "false_alarm": 1,
                 "misdiagnosis": 1, "no_response": 1}


def test_score_events_match_window():
    truths = pd.DataFrame([{"unit": "A", "day": 10, "family": "sensor_fault"}])
    preds = pd.DataFrame([{"unit": "A", "day": 18, "family": "sensor_fault"}])  # +8d > 7d
    s = valid.score_events(preds, truths, match_days=7)
    assert s["correct"] == 0 and s["missed"] == 1 and s["false_alarm"] == 1


# ---------------- diag ----------------

C5_KEYS = {"fault_hypothesis", "evidence", "counter_evidence", "confidence", "field_checklist"}

LEAK_ROW = {"exv_resid": 25.0, "sc_resid": -2.0, "capacity_resid": -0.10,
            "tf_resid": 0.0, "i_resid": 0.0, "approach": 0.0}


def test_diag_heating_leak_pattern():
    out = diag.diagnose(dict(LEAK_ROW), mode="heating")
    assert C5_KEYS <= set(out.keys())
    assert out["fault_hypothesis"] == "refrigerant_low_or_leak"
    names = {e["feature"] for e in out["evidence"]}
    assert {"exv_resid", "sc_resid"} <= names
    assert out["confidence"] >= 0.5


def test_diag_sh_gated_until_eev_saturation():
    row = dict(LEAK_ROW); row["sh_resid"] = 4.0
    out = diag.diagnose(row, mode="heating", exv_saturated=False)
    assert "sh_resid" not in {e["feature"] for e in out["evidence"]}
    out2 = diag.diagnose(row, mode="heating", exv_saturated=True)
    assert "sh_resid" in {e["feature"] for e in out2["evidence"]}


def test_diag_none_on_healthy():
    row = {k: 0.0 for k in LEAK_ROW}
    out = diag.diagnose(row, mode="heating")
    assert out["fault_hypothesis"] == "none"


def test_diag_indoor_nonspecific_flag():
    row = {"exv_resid": 0.0, "sc_resid": 0.0, "capacity_resid": -0.12,
           "tf_resid": 0.0, "i_resid": 0.0, "approach": 0.0}
    out = diag.diagnose(row, mode="heating")
    assert out["fault_hypothesis"] == "indoor_side_nonspecific"


# ---------------- diag cooling branch (FDD-I-019 attachment, transcribed verbatim) ----

LEAK_ROW_COOL_EARLY = dict(mode='cooling', exv_resid=0.0, sh_resid=0.5,
                           sc_resid=-2.0, capacity_resid=-0.10)  # sc+capacity 双证
LEAK_ROW_COOL_SCONLY = dict(mode='cooling', exv_resid=0.0, sh_resid=0.5,
                            sc_resid=-2.0, capacity_resid=0.0)   # sc 单证(capacity 未触发)
LEAK_ROW_COOL_ADV   = dict(mode='cooling', exv_resid=0.0, sh_resid=5.0,
                           sc_resid=-2.0, capacity_resid=-0.10)
RESTRICT_ROW_COOL   = dict(mode='cooling', exv_resid=0.0, sh_resid=5.0,
                           sc_resid=+2.5, capacity_resid=-0.05)

def test_leak_cooling_early_two_features():
    out = diagnose(LEAK_ROW_COOL_EARLY, mode='cooling')
    assert out['fault_hypothesis'] == 'refrigerant_low_or_leak'
    feats = {e['feature'] for e in out['evidence']}
    assert 'sc_resid' in feats and 'capacity_resid' in feats   # 双证时 capacity 入 evidence
    assert 'exv_resid' not in feats      # DK-009(a)(d)
    assert 'sh_resid' not in feats       # 早期:SSH 正常带只作上下文
    assert out['confidence'] >= 0.65

def test_leak_cooling_early_sc_only():
    # ★sc 低但 capacity 未低:仍判 refrigerant_low(sc 为主证),置信低于双证
    out = diagnose(LEAK_ROW_COOL_SCONLY, mode='cooling')
    assert out['fault_hypothesis'] == 'refrigerant_low_or_leak'
    feats = {e['feature'] for e in out['evidence']}
    assert 'sc_resid' in feats
    assert 'capacity_resid' not in feats   # 未触发,不入 evidence
    assert 0.5 <= out['confidence'] < 0.65

def test_leak_cooling_advanced_sh_self_gated():
    out = diagnose(LEAK_ROW_COOL_ADV, mode='cooling', exv_saturated=False)
    assert out['fault_hypothesis'] == 'refrigerant_low_or_leak'
    feats = {e['feature'] for e in out['evidence']}
    assert 'sh_resid' in feats           # DK-009(c):制冷 Sh 自门控
    assert 'exv_resid' not in feats

def test_metering_restriction_cooling():
    out = diagnose(RESTRICT_ROW_COOL, mode='cooling')
    assert out['fault_hypothesis'] == 'metering_restriction'
    sc_ev = [e for e in out['evidence'] if e['feature'] == 'sc_resid'][0]
    assert sc_ev['direction'] == +1      # SC 正向 = 对 refrigerant_low 的反证方向

def test_cooling_exv_alone_not_leak():
    row = dict(mode='cooling', exv_resid=+25.0, sh_resid=0.0,
               sc_resid=0.0, capacity_resid=0.0)
    out = diagnose(row, mode='cooling')
    assert out['fault_hypothesis'] != 'refrigerant_low_or_leak'

def test_cooling_tolerates_missing_dsh():
    out = diagnose(LEAK_ROW_COOL_EARLY, mode='cooling')   # 无 dsh_phys 键
    assert out['fault_hypothesis'] == 'refrigerant_low_or_leak'
