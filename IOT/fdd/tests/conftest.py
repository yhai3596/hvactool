import pandas as pd, pytest, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

@pytest.fixture(scope="session")
def sample() -> pd.DataFrame:
    """The 5h heating-mode sample (1692 rows x 48 cols). Known ground truth:
    2 true defrosts (St flips), 5 special low-freq segments, Sh servo-pinned in steady heating."""
    return pd.read_excel(ROOT / "data/sample/data_run_sample.xls", header=0)

@pytest.fixture(scope="session")
def zoho_fx() -> pd.DataFrame:
    return pd.read_csv(ROOT / "tests/fixtures/zoho_synthetic.csv")
