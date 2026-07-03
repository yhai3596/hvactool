"""M2 production-line data acceptance skeleton. Authored in Project, placed by human (rule 12).

DOUBLE WAIT-STATE BY DESIGN: skips until (a) O-track delivers prodline files into
data/raw/prodline/, and (b) the HMAC salt protocol (O-track item) provides the key
via environment variable FDD_HMAC_KEY. Both blockers are named in skip reasons so
they surface in every pytest run.

Pins API:
  c4.load_prodline(root) -> pd.DataFrame
      columns = C1 RAW_COLUMNS (after mapping) + ["sku", "station", "test_step", "hash_sn"]
      hash_sn = HMAC(FDD_HMAC_KEY, raw SN), 16 hex chars, computed AT LOAD;
      the returned frame must contain NO raw-SN column of any name (cleartext SN
      never crosses the contract boundary -- security rule).
  baseline.fit_fingerprint(prod_df) -> pd.DataFrame
      one row per hash_sn: component-level statistics (sensor offsets at equalized
      state, compressor electrical, fan characteristics).
      HARD RULE (charge-state exclusion, plan v1.1): fingerprint output columns must
      NOT include running charge indicators -- forbidden set asserted below.
"""
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROD_DIR = ROOT / "data" / "raw" / "prodline"
_prod_present = PROD_DIR.exists() and any(PROD_DIR.iterdir())
_key_present = bool(os.environ.get("FDD_HMAC_KEY"))

pytestmark = [
    pytest.mark.m2,
    pytest.mark.skipif(not _prod_present,
                       reason="awaiting O-track: prodline data not found at data/raw/prodline/"),
    pytest.mark.skipif(not _key_present,
                       reason="awaiting O-track: HMAC salt protocol (FDD_HMAC_KEY unset)"),
]

FINGERPRINT_FORBIDDEN = {"sc_phys", "sh_phys", "Sc", "Sh"}   # charge-state exclusion


@pytest.fixture(scope="session")
def prod():
    from fdd import c4
    return c4.load_prodline(PROD_DIR)


def test_schema_and_pseudonymization(prod):
    from fdd import c4
    diff = c4.schema_diff(prod)
    assert diff["missing"] == [], f"C1 columns unresolved after mapping: {diff['missing']}"
    assert {"sku", "station", "test_step", "hash_sn"} <= set(prod.columns)
    lowered = {c.lower() for c in prod.columns}
    assert not ({"sn", "serial", "serial_number", "normalized_sn"} & lowered), \
        "cleartext SN column crossed the contract boundary"
    assert prod["hash_sn"].str.fullmatch(r"[0-9a-f]{16}").all()


def test_fingerprint_scaffold_and_charge_exclusion(prod):
    from fdd import baseline
    fp = baseline.fit_fingerprint(prod)
    assert fp.index.name == "hash_sn" or "hash_sn" in fp.columns
    assert len(fp) > 0
    assert not (FINGERPRINT_FORBIDDEN & set(fp.columns)), \
        f"charge-state quantity leaked into factory fingerprint: {FINGERPRINT_FORBIDDEN & set(fp.columns)}"
