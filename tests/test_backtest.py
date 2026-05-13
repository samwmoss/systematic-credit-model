"""Tests for src/evaluation/backtest.py — contract-based, lightweight.

Two contract tests on the most leakage-sensitive module in the pipeline:
  1. The 1-month signal-to-return lag is enforced (anti-leakage)
  2. Regime allocation scales the portfolio return correctly

Run from project root:
    pytest tests/test_backtest.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.data.ingest_bonds import ingest_bonds
from src.data.ingest_fred import ingest_fred
from src.data.merge import merge_bonds_fred
from src.evaluation.backtest import run_backtest
from src.portfolio.construction import build_portfolio
from src.regime.classifier import classify_regimes

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open(PROJECT_ROOT / "config" / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def pipeline(cfg) -> dict:
    """Build the full pipeline once for all tests in this module."""
    bonds      = ingest_bonds(cfg["data"])
    fred       = ingest_fred(cfg["fred"])
    merged     = merge_bonds_fred(bonds, fred)
    portfolio  = build_portfolio(merged, cfg["signal"], cfg["portfolio"])
    regime_out = classify_regimes(fred, cfg["regime"])
    bt         = run_backtest(merged, portfolio, regime_out, cfg["dates"], cfg["signal"])
    return {
        "merged":     merged,
        "portfolio":  portfolio,
        "regime_out": regime_out,
        "bt":         bt,
        "cfg":        cfg,
    }


def test_backtest_lag_correct(pipeline):
    """The realized portfolio return at date T+1 must equal the regime-scaled
    weighted sum of NEXT month's Excess_Return_MTD (row T+1's data), NOT the
    current month's. This is the anti-leakage contract from A.8.
    """
    portfolio  = pipeline["portfolio"]
    merged     = pipeline["merged"]
    bt         = pipeline["bt"]
    regime_out = pipeline["regime_out"]

    rebal_dates = sorted(portfolio.Date.unique())
    # Pick a date solidly in the middle so prev/next lookups don't hit edges
    rebal_date  = rebal_dates[len(rebal_dates) // 2]
    realize_date = rebal_dates[rebal_dates.index(rebal_date) + 1]

    # Manually compute what backtest SHOULD produce for this realize_date,
    # using row T+1's returns (the correct-lag path).
    holdings     = portfolio[portfolio.Date == rebal_date].set_index("Cusip")["weight"]
    next_returns = merged[merged.Date == realize_date].set_index("Cusip")["Excess_Return_MTD"]
    full_deployment = float((holdings * next_returns.reindex(holdings.index, fill_value=0.0)).sum())
    alloc           = float(regime_out["allocations"][rebal_date])
    expected        = alloc * full_deployment

    actual = float(bt["portfolio_returns"].loc[realize_date])
    assert np.isclose(actual, expected, atol=1e-9), (
        f"Lag contract broken at realize {realize_date.date()}: "
        f"expected {expected:.6f} (alloc {alloc} x weighted T+1 return {full_deployment:.6f}), got {actual:.6f}"
    )


def test_backtest_regime_scaling(pipeline):
    """For a date with non-1.0 regime allocation, portfolio return must equal
    allocation x full-deployment return. Verifies the regime overlay is applied
    multiplicatively at the backtest layer.
    """
    portfolio  = pipeline["portfolio"]
    merged     = pipeline["merged"]
    bt         = pipeline["bt"]

    # Find a backtest date where allocation is not 1.0 (i.e., regime is neutral or risk_off)
    non_one = bt["allocations"][bt["allocations"] != 1.0]
    if len(non_one) == 0:
        pytest.skip("no non-risk_on dates in backtest output — cannot test regime scaling differential")

    realize_date = non_one.index[0]
    alloc        = float(non_one.iloc[0])

    rebal_dates = sorted(portfolio.Date.unique())
    rebal_date  = rebal_dates[rebal_dates.index(realize_date) - 1]

    holdings        = portfolio[portfolio.Date == rebal_date].set_index("Cusip")["weight"]
    next_returns    = merged[merged.Date == realize_date].set_index("Cusip")["Excess_Return_MTD"]
    full_deployment = float((holdings * next_returns.reindex(holdings.index, fill_value=0.0)).sum())
    expected        = alloc * full_deployment

    actual = float(bt["portfolio_returns"].loc[realize_date])
    assert np.isclose(actual, expected, atol=1e-9), (
        f"Regime scaling broken at {realize_date.date()}: "
        f"expected {alloc} x {full_deployment:.6f} = {expected:.6f}, got {actual:.6f}"
    )
