"""Pipeline orchestration entry point.

Run from project root:
    python -m src.main

Loads config, runs the full pipeline end-to-end:
  1. Bond ingestion + validation
  2. FRED ingestion + validation
  3. Point-in-time merge + validation
  4. Regime classification
  5. Signal computation across sensitivity top-pct cutoffs (diagnostic visibility)
  6. Portfolio construction per top-pct cutoff (universe filter + signal + cap enforcement)
  7. Backtest per top-pct cutoff (monthly rebalance, 1-month lag, regime scaling)
  8. Diagnostics — PNGs to outputs/charts/ and CSVs to outputs/csv/
"""
import logging
from pathlib import Path

import yaml

from src.data.ingest_bonds import ingest_bonds
from src.data.ingest_fred import ingest_fred
from src.data.merge import merge_bonds_fred
from src.data.validate import validate_bonds, validate_fred, validate_merge
from src.evaluation.backtest import run_backtest
from src.evaluation.diagnostics import generate_diagnostics
from src.features.signal import compute_signal
from src.portfolio.construction import build_portfolio
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

    log.info("[1/8] Bond ingestion")
    bonds = ingest_bonds(cfg["data"])
    validate_bonds(bonds, dates_cfg=cfg["dates"])

    log.info("[2/8] FRED ingestion")
    fred = ingest_fred(cfg["fred"])
    validate_fred(fred, cfg["fred"]["series"], fred_cfg=cfg["fred"])

    log.info("[3/8] Point-in-time merge")
    merged = merge_bonds_fred(bonds, fred)
    validate_merge(merged)

    # Universe filter — diagnostic visibility only; build_portfolio applies its own internally.
    eligible = merged[(merged.OASD > 0) & (merged.DTS > 0)].reset_index(drop=True)
    log.info(
        f"  eligible universe: {len(eligible):,} bond-date rows "
        f"({len(eligible) / len(merged):.1%} of merged)"
    )

    log.info("[4/8] Regime classification")
    regime = classify_regimes(fred, cfg["regime"])

    log.info("[5/8] Signal computation across sensitivity top-pct cutoffs (diagnostic)")
    signals = {}
    for q in cfg["signal"]["sensitivity_top_pcts"]:
        signals[q] = compute_signal(eligible, cfg["signal"], top_pct=q)

    log.info("[6/8] Portfolio construction (per sensitivity top-pct cutoff)")
    portfolios = {}
    for q in cfg["signal"]["sensitivity_top_pcts"]:
        log.info(f"  top_pct = {q}")
        portfolios[q] = build_portfolio(merged, cfg["signal"], cfg["portfolio"], top_pct=q)

    log.info("[7/8] Backtest (per sensitivity top-pct cutoff)")
    results = {}
    for q in cfg["signal"]["sensitivity_top_pcts"]:
        log.info(f"  top_pct = {q}")
        results[q] = run_backtest(merged, portfolios[q], regime, cfg["dates"], cfg["signal"])

    log.info("[8/8] Diagnostics")
    output_dir = PROJECT_ROOT / "outputs"
    generate_diagnostics(results, regime, cfg, output_dir)

    log.info("=" * 60)
    log.info("Pipeline run complete")
    log.info("=" * 60)

    return {
        "cfg":        cfg,
        "bonds":      bonds,
        "fred":       fred,
        "merged":     merged,
        "eligible":   eligible,
        "regime":     regime,
        "signals":    signals,
        "portfolios": portfolios,
        "results":    results,
    }


if __name__ == "__main__":
    main()
