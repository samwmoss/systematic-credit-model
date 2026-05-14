"""Tests for src/features/signal.py — contract-based, lightweight.

Run from project root:
    pytest tests/test_signal.py -v
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.data.ingest_bonds import ingest_bonds
from src.data.ingest_fred import ingest_fred
from src.data.merge import merge_bonds_fred
from src.features.signal import compute_signal

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open(PROJECT_ROOT / "config" / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def eligible(cfg) -> pd.DataFrame:
    bonds = ingest_bonds(cfg["data"])
    fred  = ingest_fred(cfg["fred"])
    merged = merge_bonds_fred(bonds, fred)
    return merged[(merged.OASD > 0) & (merged.DTS > 0)].reset_index(drop=True)


@pytest.fixture(scope="module")
def signal_primary(cfg, eligible) -> pd.DataFrame:
    return compute_signal(eligible, cfg["signal"])


def test_signal_cutoff_size(signal_primary, eligible, cfg):
    """Selected count per date = max(1, round(N * primary_top_pct))."""
    q = cfg["signal"]["primary_top_pct"]
    selected_per_date = signal_primary.groupby("Date").size()
    eligible_per_date = eligible.groupby("Date").size()
    expected = (eligible_per_date * q).round().clip(lower=1).astype(int)
    assert (selected_per_date == expected.reindex(selected_per_date.index)).all()


def test_signal_weights_sum_to_one(signal_primary):
    """Within each rebalance date, position weights sum to 1.0."""
    sums = signal_primary.groupby("Date").weight.sum()
    assert np.allclose(sums.values, 1.0, atol=1e-9), \
        f"weight sums range [{sums.min():.6f}, {sums.max():.6f}]"
