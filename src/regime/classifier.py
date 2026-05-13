"""Walk-forward composite z-score regime classifier.

All parameters come from config.regime. Thresholds are derived at runtime from
the pre-backtest composite slice — zero hardcoded values.

For each month-end T:
  1. Z-score each FRED indicator against its own trailing-window mean / std,
     computed strictly from prior months (shift(1) before rolling).
  2. Apply per-indicator stress sign (negate for `stress_low`).
  3. Average to a composite stress score.
  4. Classify against thresholds fit on the pre-backtest slice of composite values.

The label at month-end T applies to positions held during month T+1.
"""
import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def classify_regimes(fred: pd.DataFrame, regime_cfg: dict) -> dict:
    """Build walk-forward composite z-score regime labels.

    Args:
        fred: FRED data with DatetimeIndex and at least the columns listed in
            `regime_cfg["indicators"]`.
        regime_cfg: The `regime` section of config.yaml. Required keys:
            - window_months (int)
            - min_periods (int)
            - threshold_quantiles (list[float, float])
            - threshold_fit_start (ISO date str)
            - threshold_fit_end (ISO date str)
            - indicators (dict[str, str])  series -> "stress_high" | "stress_low"
            - allocation (dict[str, float])  regime -> deployment fraction

    Returns:
        Dict with:
            "labels":      pd.Series of categorical regime labels indexed by month-end
            "allocations": pd.Series of deployment fractions indexed by month-end
            "composite":   pd.Series of composite stress scores
            "thresholds":  {"low": float, "high": float}
            "fit_n":       int (number of pre-backtest observations used)

    Raises:
        ValueError: on unknown stress direction, missing required indicators,
            or empty fit window.
    """
    indicators    = regime_cfg["indicators"]
    window        = regime_cfg["window_months"]
    min_p         = regime_cfg["min_periods"]
    q_low, q_high = regime_cfg["threshold_quantiles"]
    fit_start     = regime_cfg["threshold_fit_start"]
    fit_end       = regime_cfg["threshold_fit_end"]
    allocation    = regime_cfg["allocation"]

    missing = set(indicators) - set(fred.columns)
    if missing:
        raise ValueError(f"FRED missing indicator columns: {missing}")

    # Resample each indicator to month-end (last value within each month)
    monthly = fred[list(indicators)].resample("ME").last()

    # Trailing-window z-score. shift(1) makes mean/std strictly past-looking.
    tmean = monthly.shift(1).rolling(window, min_periods=min_p).mean()
    tstd  = monthly.shift(1).rolling(window, min_periods=min_p).std()
    z     = (monthly - tmean) / tstd

    # Apply per-indicator stress direction (flip sign for stress_low)
    stress_z = pd.DataFrame(index=z.index)
    for series, direction in indicators.items():
        if direction == "stress_high":
            stress_z[series] = z[series]
        elif direction == "stress_low":
            stress_z[series] = -z[series]
        else:
            raise ValueError(
                f"unknown stress direction '{direction}' for {series}; "
                "expected 'stress_high' or 'stress_low'"
            )

    composite = stress_z.mean(axis=1)

    # Fit thresholds on the pre-backtest slice
    pretrain = composite.loc[fit_start:fit_end].dropna()
    if len(pretrain) == 0:
        raise ValueError(
            f"no composite values in fit window [{fit_start}, {fit_end}]. "
            "Check fred.pull_start and regime.min_periods."
        )
    thresh_low  = float(pretrain.quantile(q_low))
    thresh_high = float(pretrain.quantile(q_high))

    labels = pd.cut(
        composite,
        bins=[-np.inf, thresh_low, thresh_high, np.inf],
        labels=["risk_on", "neutral", "risk_off"],
    )
    allocations = labels.astype(str).map(allocation).astype(float)

    log.info(f"Regime classifier built: window={window}mo, min_periods={min_p}")
    log.info(f"  fit window: [{fit_start}, {fit_end}]  n={len(pretrain)}")
    log.info(f"  thresholds: low={thresh_low:.3f}  high={thresh_high:.3f}")
    log.info(f"  allocation: {allocation}")

    return {
        "labels":      labels,
        "allocations": allocations,
        "composite":   composite,
        "thresholds":  {"low": thresh_low, "high": thresh_high},
        "fit_n":       len(pretrain),
    }
