"""M-DRIFT (M1): per (SN x feature x bin) CUSUM + robust-Z. Learning-vs-fault gate via tcs_gap
+ thermostat stats (rule #8). Output: onset, direction, magnitude, slope."""
def cusum(series, k, h): raise NotImplementedError
