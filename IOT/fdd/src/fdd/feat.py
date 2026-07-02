"""M-FEAT feature registry (M1). Bins: mode x Ta(2K) x CompRps(10 bands). Rules #3 #4 #5 #9 #10 bind.
Registry (locked + two adopted 2026-07-02): exv_resid, sc_resid, capacity_resid, approach,
th_coil_resid, comp_slip, fan_slip, power_resid, p_parasitic, tcs_gap, i_resid(V1 covariate),
defrost_freq, tf_resid (Tf vs f(PowerComp,Ta,CompRps)), indoor_load_proxy (Y/W duty, cycling
freq, runtime fraction — covariate only, NOT an indoor diagnostic)."""
def build_features(df, bins_cfg): raise NotImplementedError
