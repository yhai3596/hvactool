"""M-BASE (M2, gated on lab data): L1 per-SKU envelope (XGBoost regression on lab),
L2 factory component fingerprint (charge-state EXCLUDED), L3 30-day field baseline +
rolling binned self-baseline with change-point freeze (quarantine flag)."""
def fit_envelope(lab_df, sku): raise NotImplementedError
