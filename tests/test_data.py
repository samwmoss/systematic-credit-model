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


def test_exit_row_captures_terminal_event(bonds):
    """For bonds that exit the panel before its end, the last available row's
    Excess_Return_MTD captures the terminal event:
      - Maturities / calls: return near zero (par receipt)
      - Defaults: return deeply negative (loss recorded in last row, bond then removed)

    The distribution being centered near zero with a small catastrophic tail
    is what justifies `fill_value=0` in backtest.run_backtest — the
    disappearance at T+1 doesn't lose information because the terminal-event
    return lives in the bond's last existing row. If a future data revision
    breaks this convention, this test catches it.

    See README Failure Mode #2 for the documented analysis.
    """
    panel_end      = bonds.Date.max()
    last_per_cusip = bonds.groupby("Cusip").Date.max()
    exiting_cusips = last_per_cusip[last_per_cusip < panel_end].index

    exit_rows = (
        bonds[bonds.Cusip.isin(exiting_cusips)]
        .sort_values(["Cusip", "Date"])
        .groupby("Cusip")
        .tail(1)
    )
    er = exit_rows["Excess_Return_MTD"]

    # Median exit-row return is near zero — most exits are routine maturities / calls.
    assert -1.0 < er.median() < 1.0, (
        f"Median exit-row Excess_Return_MTD = {er.median():.3f}; expected near 0 "
        "if panel follows standard terminal-event convention. If this fails, the "
        "panel may not record terminal returns in the last row, invalidating the "
        "fill_value=0 assumption in backtest.run_backtest."
    )

    # Catastrophic exits (probable defaults) are a small minority of all exits.
    pct_catastrophic = float((er < -20).mean())
    assert pct_catastrophic < 0.05, (
        f"{pct_catastrophic*100:.1f}% of exits have terminal return < -20%; "
        "expected <5% for a standard HY index panel. Higher fraction would "
        "suggest the panel is missing many default-month returns."
    )
