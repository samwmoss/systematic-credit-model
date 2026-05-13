"""Tests for src/data/ — contract-based, lightweight.

Run from project root:
    pytest tests/test_data.py -v
"""
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.data.ingest_bonds import ingest_bonds
from src.data.ingest_fred import ingest_fred
from src.data.merge import merge_bonds_fred

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open(PROJECT_ROOT / "config" / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def bonds(cfg) -> pd.DataFrame:
    return ingest_bonds(cfg["data"])


@pytest.fixture(scope="module")
def merged(cfg, bonds) -> pd.DataFrame:
    return merge_bonds_fred(bonds, ingest_fred(cfg["fred"]))


def test_bonds_drop_rules_applied(bonds, cfg):
    """No row in the output violates any locked drop rule (driven by config)."""
    data_cfg = cfg["data"]
    for col in data_cfg["drop_null_cols"]:
        assert bonds[col].isnull().sum() == 0, f"nulls remain in {col}"
    assert not bonds.Eff_Rating_Group.isin(data_cfg["drop_rating_groups"]).any()
    assert not bonds.Class1.isin(data_cfg["drop_class1"]).any()
    assert not bonds.Class2.isin(data_cfg["drop_class2"]).any()


def test_bonds_date_convention(bonds, cfg):
    """Date matches the configured end-of-month convention (A.8 finding)."""
    if cfg["data"].get("date_convention") == "end_of_month":
        assert (bonds.Date == bonds.Date + pd.offsets.MonthEnd(0)).all()


def test_merge_no_pit_leakage(merged):
    """No row joins a FRED value dated after its bond Date — the PIT contract."""
    assert (merged["fred_asof_date"] <= merged["Date"]).all()


def test_fred_missing_cache_fails_loudly(cfg, tmp_path):
    """ingest_fred raises FileNotFoundError when the cache file is absent."""
    bad_cfg = dict(cfg["fred"])
    bad_cfg["cache_path"] = str(tmp_path / "nonexistent.parquet")
    with pytest.raises(FileNotFoundError, match="FRED cache not found"):
        ingest_fred(bad_cfg)
