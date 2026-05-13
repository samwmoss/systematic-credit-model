"""Tests for src/portfolio/construction.py — contract-based, lightweight.

Run from project root:
    pytest tests/test_portfolio.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.data.ingest_bonds import ingest_bonds
from src.data.ingest_fred import ingest_fred
from src.data.merge import merge_bonds_fred
from src.portfolio.construction import build_portfolio

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CAP_TOLERANCE = 1e-9   # float-precision tolerance; iterative enforcement is exact


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open(PROJECT_ROOT / "config" / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def portfolio(cfg) -> pd.DataFrame:
    bonds = ingest_bonds(cfg["data"])
    fred  = ingest_fred(cfg["fred"])
    merged = merge_bonds_fred(bonds, fred)
    return build_portfolio(merged, cfg["signal"], cfg["portfolio"])


def test_issuer_cap_honored(portfolio, cfg):
    """No Ticker exceeds issuer_cap on any Date (within float precision)."""
    cap   = cfg["portfolio"]["issuer_cap"]
    field = cfg["portfolio"]["issuer_field"]
    if cap is None:
        pytest.skip("issuer_cap not set in config")
    max_per_group = portfolio.groupby(["Date", field]).weight.sum().max()
    assert max_per_group <= cap + CAP_TOLERANCE, \
        f"max {field} weight = {max_per_group:.6f} exceeds cap = {cap:.6f}"


def test_sector_cap_honored(portfolio, cfg):
    """No Class3 exceeds sector_cap on any Date (within float precision)."""
    cap   = cfg["portfolio"]["sector_cap"]
    field = cfg["portfolio"]["sector_field"]
    if cap is None:
        pytest.skip("sector_cap not set in config")
    max_per_group = portfolio.groupby(["Date", field]).weight.sum().max()
    assert max_per_group <= cap + CAP_TOLERANCE, \
        f"max {field} weight = {max_per_group:.6f} exceeds cap = {cap:.6f}"


def test_weights_sum_to_one(portfolio):
    """Within each Date, portfolio weights sum to 1.0 (full deployment)."""
    sums = portfolio.groupby("Date").weight.sum()
    assert np.allclose(sums.values, 1.0, atol=1e-9), \
        f"weight sums range [{sums.min():.6f}, {sums.max():.6f}]"
