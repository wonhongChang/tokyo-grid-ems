import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SAMPLE_CSV = REPO_ROOT / "data" / "raw" / "2024" / "202401_power_usage" / "20240101_power_usage.csv"


@pytest.fixture(scope="session")
def sample_csv_path() -> Path:
    if not SAMPLE_CSV.exists():
        pytest.skip(f"Sample CSV not found: {SAMPLE_CSV}")
    return SAMPLE_CSV


@pytest.fixture(scope="session")
def parsed_sample(sample_csv_path):
    from python.tepc_parser import parse_tepc_daily_csv
    return parse_tepc_daily_csv(sample_csv_path)
