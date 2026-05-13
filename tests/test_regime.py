"""Tests for src/regime/classifier.py — contract-based, lightweight.

Run from project root:
    pytest tests/test_regime.py -v
"""
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.data.ingest_fred import ingest_fred
from src.regime.classifier import classify_regimes

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open(PROJECT_ROOT / "config" / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def out(cfg) -> dict:
    fred = ingest_fred(cfg["fred"])
    return classify_regimes(fred, cfg["regime"])


def test_regime_thresholds_derived_from_config(out, cfg):
    """Thresholds equal the configured quantiles of the pretrain composite slice — no hardcoded values."""
    fit_start = cfg["regime"]["threshold_fit_start"]
    fit_end   = cfg["regime"]["threshold_fit_end"]
    q_low, q_high = cfg["regime"]["threshold_quantiles"]

    pretrain = out["composite"].loc[fit_start:fit_end].dropna()
    expected_low  = float(pretrain.quantile(q_low))
    expected_high = float(pretrain.quantile(q_high))

    assert out["thresholds"]["low"]  == pytest.approx(expected_low,  rel=1e-9)
    assert out["thresholds"]["high"] == pytest.approx(expected_high, rel=1e-9)


def test_regime_allocations_match_labels(out, cfg):
    """Allocation at each date equals config.regime.allocation[label_at_that_date]."""
    allocation = cfg["regime"]["allocation"]
    labels = out["labels"].dropna().astype(str)
    allocs = out["allocations"].loc[labels.index]
    expected = labels.map(allocation).astype(float)
    assert (allocs == expected).all()
