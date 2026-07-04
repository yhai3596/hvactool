"""One-time offline generator: R410A saturation lookup table (dew + bubble).

M3 processes billions of rows; per-row PropsSI is slow and carries a native-segfault
risk that repeats at scale. This precomputes T_sat(P) once so conv.materialize can
interpolate (no native calls in the hot path). The table IS CoolProp — same physics,
cached. Run once; if CoolProp segfaults mid-run, just rerun (idempotent, checkpointed).

Output: src/fdd/sat_table.npz {p_bar, dew_c, bubble_c}. Grid 1.0..46.0 bar abs (covers
R410A Tsat -51..+68 C, below Pcrit 49 bar), step 0.0005 bar. The step is set fine enough
that linear-interp error < 1e-6 K everywhere in-range, so the M0 sh_phys/sc_phys
self-consistency tests (which pin materialize's te_sat to direct PropsSI within 1e-6 K)
stay green — the table must not move sealed values, not merely stay within 0.01 K.

Usage: .venv/Scripts/python scripts/gen_sat_table.py
"""
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from CoolProp.CoolProp import PropsSI                       # noqa: E402
from fdd.contracts.c1_telemetry import REFRIGERANT          # noqa: E402

BAR_TO_PA = 1e5
P_MIN, P_MAX, P_STEP = 1.0, 46.0, 0.0005
OUT = ROOT / "src" / "fdd" / "sat_table.npz"
CKPT = ROOT / "src" / "fdd" / "_sat_table_ckpt.npz"


def main():
    p_bar = np.round(np.arange(P_MIN, P_MAX + P_STEP / 2, P_STEP), 4)
    dew = np.full(p_bar.shape, np.nan)
    bubble = np.full(p_bar.shape, np.nan)
    start = 0
    if CKPT.exists():                                        # resume after a crash
        c = np.load(CKPT)
        if np.array_equal(c["p_bar"], p_bar):
            dew, bubble, start = c["dew"].copy(), c["bubble"].copy(), int(c["done"])
            print(f"resuming from checkpoint at {start}/{len(p_bar)}")
    for i in range(start, len(p_bar)):
        pa = float(p_bar[i]) * BAR_TO_PA
        dew[i] = PropsSI("T", "P", pa, "Q", 1.0, REFRIGERANT) - 273.15
        bubble[i] = PropsSI("T", "P", pa, "Q", 0.0, REFRIGERANT) - 273.15
        if i % 500 == 0:
            np.savez(CKPT, p_bar=p_bar, dew=dew, bubble=bubble, done=i + 1)
    np.savez_compressed(OUT, p_bar=p_bar, dew_c=dew, bubble_c=bubble)
    if CKPT.exists():
        CKPT.unlink()
    print(f"wrote {OUT} ({len(p_bar)} points, {P_MIN}..{P_MAX} bar)")


if __name__ == "__main__":
    main()
