"""DoD for M-ZOHO-V2 on the synthetic fixture (real exports never enter this repo)."""
import pytest, pandas as pd
from fdd import zoho_v2

pytestmark = pytest.mark.m0
TODAY = "2026-07-02"

def test_date_clamp(zoho_fx):
    out = zoho_v2.clamp_dates(zoho_fx, today=TODAY)
    d = pd.to_datetime(out["event_date"])
    assert (d >= "2018-01-01").all() and (d <= TODAY).all()
    assert (out.loc[zoho_fx["event_date"] < "2018-01-01", "date_flag"] == "clamped_fallback").all()

def test_ai_safe_has_no_cleartext_sn(zoho_fx):
    safe = zoho_v2.make_ai_safe(zoho_fx)
    assert "normalized_sn" not in safe.columns
    assert "hash_sn" in safe.columns

def test_queue_reranking_puts_refrigerant_first(zoho_fx):
    q = zoho_v2.rerank_queue(zoho_fx, top_n=10)
    share = (q["fault_family"] == "refrigerant_low_or_leak").mean()
    assert share >= 0.30

def test_repair_action_standardization():
    assert zoho_v2.standardize_repair_action("Tech recharged refrigerant and fixed leak") == "refrigerant_recharge"
    assert zoho_v2.standardize_repair_action("replaced outdoor fan motor") == "motor_replace"
    assert zoho_v2.standardize_repair_action("customer education call") is None
