"""Pipeline validation: schema, range, and PIT-leakage checks.

Each function logs a structured report and raises AssertionError on contract
violation. Called from main.py after each ingestion step as an audit gate.
"""
import logging
import pandas as pd

log = logging.getLogger(__name__)

REQUIRED_BOND_COLS = {
    "Date", "Cusip", "Ticker", "Class1", "Class2", "Class3",
    "Eff_Rating_Group", "Index_Rating_Number", "Maturity_Date",
    "Years_To_Maturity", "DTS", "OAS", "OAD", "OASD",
    "Yield_To_Worst", "Total_Return_MTD", "Excess_Return_MTD",
}


def validate_bonds(df: pd.DataFrame, dates_cfg: dict | None = None) -> None:
    """Post-ingestion contract on the cleaned bond panel.

    Args:
        df: Cleaned bond panel.
        dates_cfg: Optional `config.dates` section. If provided, also asserts every
            bond Date falls within [backtest_start, backtest_end] (end-of-month).

    Raises:
        AssertionError: on schema, dtype, null, or date-range contract violation.
    """
    log.info(f"Validating bond panel: {df.shape}")

    missing = REQUIRED_BOND_COLS - set(df.columns)
    assert not missing, f"bond panel missing columns: {missing}"

    assert pd.api.types.is_datetime64_any_dtype(df["Date"]), "Date is not datetime"

    for col in ["OAS", "OASD", "DTS", "Excess_Return_MTD"]:
        n = df[col].isnull().sum()
        assert n == 0, f"{col} has {n} nulls remaining after ingestion"

    if dates_cfg:
        start = pd.Timestamp(dates_cfg["backtest_start"]) + pd.offsets.MonthEnd(0)
        end   = pd.Timestamp(dates_cfg["backtest_end"])   + pd.offsets.MonthEnd(0)
        out_of_range = ((df["Date"] < start) | (df["Date"] > end)).sum()
        assert out_of_range == 0, (
            f"{out_of_range} bond rows outside configured backtest window "
            f"[{start.date()}, {end.date()}]"
        )

    log.info("  bonds OK")


def validate_fred(df: pd.DataFrame, expected_series: list, fred_cfg: dict | None = None) -> None:
    """Post-ingestion contract on the FRED cache.

    Args:
        df: FRED cache DataFrame.
        expected_series: List of series IDs that must be present.
        fred_cfg: Optional `config.fred` section. If provided, also asserts the
            FRED date range covers [pull_start, pull_end] within a 7-day grace.

    Raises:
        AssertionError: on missing series, non-datetime index, or insufficient coverage.
    """
    log.info(f"Validating FRED cache: {df.shape}")

    missing = set(expected_series) - set(df.columns)
    assert not missing, f"FRED cache missing series: {missing}"
    assert pd.api.types.is_datetime64_any_dtype(df.index), "FRED index is not datetime"

    if fred_cfg:
        pull_start = pd.Timestamp(fred_cfg["pull_start"])
        pull_end   = pd.Timestamp(fred_cfg["pull_end"])
        grace      = pd.Timedelta(days=7)
        assert df.index.min() <= pull_start + grace, (
            f"FRED starts {df.index.min().date()}, expected near {pull_start.date()}"
        )
        assert df.index.max() >= pull_end - grace, (
            f"FRED ends {df.index.max().date()}, expected near {pull_end.date()}"
        )

    log.info("  FRED OK")


def validate_merge(df: pd.DataFrame) -> None:
    """PIT-leakage assertion on the merged panel.

    Raises:
        AssertionError: if any row's fred_asof_date is after its bond Date.
    """
    log.info(f"Validating merge: {df.shape}")

    assert "fred_asof_date" in df.columns, "merge output missing fred_asof_date"

    leak = (df["fred_asof_date"] > df["Date"]).sum()
    assert leak == 0, f"PIT leakage: {leak} rows have fred_asof_date > Date"

    log.info("  merge OK (PIT clean)")
