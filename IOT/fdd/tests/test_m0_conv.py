"""DoD for M-CONV. Red until implemented; making these green IS milestone M0 (part 1/3).

2026-07-02 human ruling: the controller firmware's saturation table is biased
~ -2.0% in pressure vs CoolProp R410A at bar-confirmed readings (value/10 = MPa,
vendor-confirmed). Physical sh_phys/sc_phys therefore CANNOT match reported
Sh/Sc at the original 0.15K / 1.0+-0.1 tolerances. The two consistency tests now
compare the firmware REPLICA (conv.controller_sat_temp_c) against reported
values -- which verifies the controller algorithm is fully characterized --
while sc keeps a structural no-minus-one guard on the physical column (rule #2).
Pending vendor confirmation of the table axis (CLAUDE.md 悬而未决)."""
import pytest
from fdd import conv
from fdd.contracts.c1_telemetry import ATM_OFFSET_BAR

pytestmark = pytest.mark.m0

def test_abs_pressure_is_fixed_offset_no_altitude(sample):
    out = conv.materialize(sample)
    assert ((out["lp_abs"] - sample["Lp"]) - ATM_OFFSET_BAR).abs().max() < 1e-9
    assert ((out["hp_abs"] - sample["Hp"]) - ATM_OFFSET_BAR).abs().max() < 1e-9

def test_sh_phys_matches_controller_p95(sample):
    sh_replica = sample["Ts"] - conv.controller_sat_temp_c(sample["Lp"], "low")
    d = (sh_replica - sample["Sh"]).abs()
    d = d[sample["St"] == 1]            # defrost rows exempt
    assert d.quantile(0.95) <= 0.15, f"P95={d.quantile(0.95):.3f}K"

def test_sc_phys_strips_minus_one(sample):
    out = conv.materialize(sample)
    # structural rule-#2 guard: physical sc_phys is exactly tc_sat - Tl, no -1 term
    assert (out["sc_phys"] - (out["tc_sat"] - sample["Tl"])).abs().max() < 1e-9
    run = sample["CompState"] == 1
    sc_replica = conv.controller_sat_temp_c(sample["Hp"], "high") - sample["Tl"]
    off = (sc_replica[run] - sample.loc[run, "Sc"])
    assert abs(off.mean() - 1.0) <= 0.1, f"mean offset {off.mean():.3f}, expected ~1.0 (the stripped bias)"

def test_tcs_gap_uses_target_not_measurement(sample):
    out = conv.materialize(sample)
    assert "tcs_gap" in out.columns
    assert out["tcs_gap"].notna().mean() > 0.9
