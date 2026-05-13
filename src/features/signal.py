"""Carry signal: rank bonds by OAS/OASD per date, select top cutoff, weight by 1/DTS.

Per A.8 date convention, the bond row dated T contains both:
  - signal inputs (OAS, OASD, DTS) measured at end-of-month T
  - realized return Excess_Return_MTD earned during month T

The signal at row T therefore predicts month T+1's return (`config.signal.lag_months`).
This module does not apply the lag — the backtest engine handles the time shift between
signal computation and return realization.
"""
import logging
import pandas as pd

log = logging.getLogger(__name__)


def compute_signal(
    panel: pd.DataFrame,
    signal_cfg: dict,
    quintile: float | None = None,
) -> pd.DataFrame:
    """Rank bonds by carry per date, select top quintile, weight by inverse-DTS.

    Per-date workflow:
      1. carry = panel[numerator] / panel[denominator]   (typically OAS / OASD)
      2. Rank descending; select top max(1, round(quintile * N)) bonds per Date
      3. Weight by 1 / DTS; normalize per Date to sum to 1

    Args:
        panel: Eligible-universe bond panel. Caller must apply universe filters
            upstream (OASD > 0, DTS > 0, plus the drops from ingest_bonds).
            Required columns: Date, Cusip, the signal_cfg numerator/denominator,
            and DTS for inverse-DTS weighting.
        signal_cfg: The `signal` section of config.yaml. Keys used:
            numerator, denominator, weighting, primary_quintile.
        quintile: Cutoff override for sensitivity runs (e.g. 0.10, 0.30).
            Defaults to signal_cfg["primary_quintile"].

    Returns:
        DataFrame of selected bonds with all original columns plus:
            - carry  : numerator / denominator ratio
            - weight : portfolio weight within the cut (sums to 1 per Date)

    Raises:
        ValueError: if the configured weighting scheme is unsupported.
    """
    numerator   = signal_cfg["numerator"]
    denominator = signal_cfg["denominator"]
    weighting   = signal_cfg["weighting"]
    if quintile is None:
        quintile = signal_cfg["primary_quintile"]

    log.info(
        f"Computing signal: {numerator}/{denominator}  cutoff={quintile}  weighting={weighting}"
    )

    work = panel.copy()
    work["carry"] = work[numerator] / work[denominator]

    # Vectorized top-N selection per Date.
    n_per_date = work.groupby("Date")["carry"].transform("count")
    cutoff_n   = (n_per_date * quintile).round().clip(lower=1).astype(int)
    rank_in_d  = work.groupby("Date")["carry"].rank(method="first", ascending=False)
    selected   = work[rank_in_d <= cutoff_n].copy()

    if weighting == "inverse_dts":
        inv = 1.0 / selected["DTS"]
        selected["weight"] = inv.groupby(selected["Date"]).transform(lambda s: s / s.sum())
    else:
        raise ValueError(f"unknown weighting '{weighting}'; expected 'inverse_dts'")

    log.info(
        f"  selected {len(selected):,} bond-date rows across {selected.Date.nunique()} dates"
    )

    # Put carry + weight last for readability
    cols = [c for c in selected.columns if c not in ("carry", "weight")] + ["carry", "weight"]
    return selected[cols].reset_index(drop=True)
