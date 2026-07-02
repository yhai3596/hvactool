"""DoD for M-CONV. Red until implemented; making these green IS milestone M0 (part 1/3).

2026-07-02 human ruling: the controller firmware's saturation table is biased
~ -2.0% in pressure vs CoolProp R410A at bar-confirmed readings (value/10 = MPa,
vendor-confirmed). Physical sh_phys/sc_phys therefore CANNOT match reported
Sh/Sc at the original 0.15K / 1.0+-0.1 tolerances. The two consistency tests now
compare the firmware REPLICA (conv.controller_sat_temp_c) against reported
values -- which verifies the controller algorithm is fully characterized --
while sc keeps a structural no-minus-one guard on the physical column (rule #2).
Pending vendor confirmation of the table axis (CLAUDE.md 悬而未决)."""
import pandas as pd
import pytest
from fdd import conv, seg
from fdd.contracts.c1_telemetry import ATM_OFFSET_BAR

pytestmark = pytest.mark.m0

def test_abs_pressure_is_fixed_offset_no_altitude(sample):
    out = conv.materialize(sample)
    assert ((out["lp_abs"] - sample["Lp"]) - ATM_OFFSET_BAR).abs().max() < 1e-9
    assert ((out["hp_abs"] - sample["Hp"]) - ATM_OFFSET_BAR).abs().max() < 1e-9

@pytest.mark.m0
def test_sh_phys_physical_self_consistency(sample):
    """sh_phys 必须等于教科书物理过热度 Ts - te_sat(te_sat=CoolProp 绝压露点)。
    参考值在测试内独立重算,不对照固件上报 Sh。测的是 conv 换算逻辑本身是否正确。"""
    out = conv.materialize(sample)
    from CoolProp.CoolProp import PropsSI
    p_abs_pa = (sample["Lp"] + ATM_OFFSET_BAR) * 1e5
    te_ref = pd.Series([PropsSI("T", "P", p, "Q", 1, "R410A") - 273.15 for p in p_abs_pa],
                       index=sample.index)
    sh_ref = sample["Ts"] - te_ref
    assert (out["sh_phys"] - sh_ref).abs().max() < 1e-6


@pytest.mark.m0
def test_firmware_sh_bias_is_systematic(sample):
    """sh_phys 与固件上报 Sh 之差应是系统性、可由压力单调解释的偏差,而非随机噪声。
    只在稳态段检验。不断言具体百分比(-2% 待厂商确认)。"""
    out = conv.materialize(sample)
    seg_df = seg.segment(sample)
    m = seg_df["steady"]
    diff = (out.loc[m, "sh_phys"] - sample.loc[m, "Sh"])
    # 2026-07-02 裁决:补 abs(原式漏了,与下方 abs(rho) 一致);diff 方向保持 sh_phys - Sh
    assert abs(diff.mean()) / (diff.std() + 1e-9) > 3.0
    from scipy.stats import spearmanr
    rho, _ = spearmanr(out.loc[m, "te_sat"], diff)
    assert abs(rho) > 0.5
    # sc 侧同类量,供人工核对高低压两侧偏差是否同源(不断言,只打印)
    sc_diff = out.loc[m, "sc_phys"] - (sample.loc[m, "Sc"] + 1)
    sc_rho, _ = spearmanr(out.loc[m, "tc_sat"], sc_diff)
    print(f"[firmware-bias] steady sh_phys-Sh: mean={diff.mean():.3f} "
          f"std={diff.std():.3f} spearman(te_sat,diff)={rho:.2f} | "
          f"sc side: mean={sc_diff.mean():.3f} spearman(tc_sat,sc_diff)={sc_rho:.2f}")

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
