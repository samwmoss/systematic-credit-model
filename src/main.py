"""Pipeline orchestration entry point.

Run from project root:
    python -m src.main

Loads config, runs the full data layer (ingest -> validate -> merge -> validate),
classifies regimes, computes the signal for every sensitivity quintile, and logs
summary statistics. Produces no outputs yet — the backtest commit will extend
this entry point to write portfolio returns and diagnostics to outputs/.
"""
import logging
from pathlib import Path

import yaml

from src.data.ingest_bonds import ingest_bonds
from src.data.ingest_fred import ingest_fred
from src.data.merge import merge_bonds_fred
from src.data.validate import validate_bonds, validate_fred, validate_merge
from src.features.signal import compute_signal
from src.regime.classifier import classify_regimes
from src.utils.logging_config import setup_logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH  = PROJECT_ROOT / "config" / "config.yaml"

log = logging.getLogger(__name__)


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def main() -> dict:
    """Run the pipeline end-to-end. Returns a dict of intermediate artifacts for inspection / tests."""
    cfg = load_config()
    setup_logging(cfg["logging"])

    log.info("=" * 60)
    log.info("Pipeline run starting")
    log.info("=" * 60)

    log.info("[1/5] Bond ingestion")
    bonds = ingest_bonds(cfg["data"])
    validate_bonds(bonds, dates_cfg=cfg["dates"])

    log.info("[2/5] FRED ingestion")
    fred = ingest_fred(cfg["fred"])
    validate_fred(fred, cfg["fred"]["series"], fred_cfg=cfg["fred"])

    log.info("[3/5] Point-in-time merge")
    merged = merge_bonds_fred(bonds, fred)
    validate_merge(merged)

    # Universe filter — will move to portfolio/construction.py when that lands.
    eligible = merged[(merged.OASD > 0) & (merged.DTS > 0)].reset_index(drop=True)
    log.info(
        f"  eligible universe: {len(eligible):,} bond-date rows "
        f"({len(eligible) / len(merged):.1%} of merged)"
    )

    log.info("[4/5] Regime classification")
    regime = classify_regimes(fred, cfg["regime"])

    log.info("[5/5] Signal computation across sensitivity quintiles")
    signals = {}
    for q in cfg["signal"]["sensitivity_quintiles"]:
        signals[q] = compute_signal(eligible, cfg["signal"], quintile=q)

    log.info("=" * 60)
    log.info("Pipeline run complete")
    log.info("=" * 60)

    return {
        "cfg":      cfg,
        "bonds":    bonds,
        "fred":     fred,
        "merged":   merged,
        "eligible": eligible,
        "regime":   regime,
        "signals":  signals,
    }


if __name__ == "__main__":
    main()
