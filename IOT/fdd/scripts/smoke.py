"""Environment + data self-check. Run first in any new session."""
import pandas as pd, pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
df = pd.read_excel(root/"data/sample/data_run_sample.xls", header=0)
assert df.shape == (1692, 48), df.shape
try:
    from CoolProp.CoolProp import PropsSI
    t = PropsSI("T","P",4.92e5,"Q",1,"R410A") - 273.15
    print(f"CoolProp OK: Tsat(4.92 bar abs, dew) = {t:.2f} C  (expect ~ -14.5)")
except Exception as e:
    print("CoolProp missing/broken:", e); sys.exit(1)
print("sample OK:", df.shape, "| St==0 rows:", (df.St==0).sum(), "(expect 40)")
