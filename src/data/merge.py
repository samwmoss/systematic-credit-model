"""Point-in-time merge of FRED indicators into the bond panel.

For each bond row dated T (end-of-month snapshot per A.8), attach the latest
FRED values with date <= T. Uses pd.merge_asof for efficiency; FRED is
forward-filled to daily so weekly NFCI values stay populated between releases.
"""
import logging
import pandas as pd

log = logging.getLogger(__name__)


def merge_bonds_fred(bonds: pd.DataFrame, fred: pd.DataFrame) -> pd.DataFrame:
    """PIT-correct backward join of FRED columns into the bond panel.

    Args:
        bonds: Cleaned bond panel with `Date` column (end-of-month).
        fred:  FRED cache with DatetimeIndex and one column per series.

    Returns:
        Bond panel with FRED series appended plus a `fred_asof_date` column
        recording which FRED observation was joined (for audit + downstream
        leakage assertion in validate.validate_merge).

    Raises:
        AssertionError: if any joined row has fred_asof_date > Date.
    """
    log.info(f"Merging {len(bonds):,} bond rows with FRED ({len(fred.columns)} series)")

    fred_filled = fred.ffill().reset_index()
    fred_filled = fred_filled.rename(columns={fred_filled.columns[0]: "fred_asof_date"})

    bonds_sorted = bonds.sort_values("Date").reset_index(drop=True)

    merged = pd.merge_asof(
        bonds_sorted,
        fred_filled,
        left_on="Date",
        right_on="fred_asof_date",
        direction="backward",
        allow_exact_matches=True,
    )

    leak = (merged["fred_asof_date"] > merged["Date"]).sum()
    assert leak == 0, f"PIT leakage: {leak} rows have fred_asof_date > Date"

    lags = (merged["Date"] - merged["fred_asof_date"]).dt.days
    log.info(
        f"  FRED-to-bond lag: median={lags.median():.0f}d  "
        f"p95={lags.quantile(0.95):.0f}d  max={lags.max()}d"
    )
    log.info(f"  merged shape: {merged.shape}")
    return merged
