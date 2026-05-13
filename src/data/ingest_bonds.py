"""Bond panel ingestion: load CSV, apply locked drop rules, shift Date label.

Date convention is end-of-month, validated in notebooks/inspection.ipynb (A.8):
the row labeled `2011-08-01` is the end-of-August-2011 snapshot. This module
shifts Date to `2011-08-31` so downstream PIT logic uses standard `<=` joins
without month-arithmetic.

Drops are read from config.data; the rationale lives in README Data Quality Notes.
"""
import logging
from pathlib import Path
import pandas as pd

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def ingest_bonds(data_cfg: dict) -> pd.DataFrame:
    """Load and clean the bond panel per locked EDA rules.

    Args:
        data_cfg: The `data` section of config.yaml.

    Returns:
        Cleaned bond DataFrame with Date in end-of-month form and index reset.

    Raises:
        FileNotFoundError: if the bond CSV is not at the configured path.
    """
    # Guard rails — these decisions are locked from EDA. Enforce config-vs-code contract
    # so flipping the config flag isn't silently ignored.
    if data_cfg.get("winsorize", False):
        raise NotImplementedError(
            "config.data.winsorize=True: deliberately disabled per EDA. The inverse-DTS "
            "portfolio weighting handles outliers structurally. See README Data Quality Notes."
        )
    if data_cfg.get("min_history_months", 0) > 0:
        raise ValueError(
            f"config.data.min_history_months={data_cfg['min_history_months']}: would introduce "
            "survivorship bias. See EDA Section A closing and README Data Quality Notes."
        )

    csv_path = Path(data_cfg["bond_csv"])
    if not csv_path.is_absolute():
        csv_path = PROJECT_ROOT / csv_path
    if not csv_path.exists():
        raise FileNotFoundError(f"Bond CSV not found at {csv_path}. Check config.data.bond_csv.")

    log.info(f"Loading bond panel from {csv_path}")
    df = pd.read_csv(csv_path)
    n_in = len(df)
    log.info(f"  loaded {n_in:,} rows x {df.shape[1]} cols")

    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    if data_cfg.get("date_convention") == "end_of_month":
        df["Date"] = df["Date"] + pd.offsets.MonthEnd(0)
        log.info("  shifted Date to end-of-month")

    # Null drops (locked: OASD, DTS — 9 rows, same rows in both)
    null_cols = data_cfg.get("drop_null_cols", [])
    if null_cols:
        n0 = len(df)
        df = df.dropna(subset=null_cols)
        log.info(f"  dropped {n0 - len(df):,} rows with null in {null_cols}")

    # Categorical drops (rating groups, Class1, Class2)
    for col, key in [
        ("Eff_Rating_Group", "drop_rating_groups"),
        ("Class1",           "drop_class1"),
        ("Class2",           "drop_class2"),
    ]:
        values = data_cfg.get(key, [])
        if not values:
            continue
        n0 = len(df)
        df = df[~df[col].isin(values)]
        log.info(f"  dropped {n0 - len(df):,} rows with {col} in {values}")

    n_out = len(df)
    log.info(f"  final: {n_out:,} rows ({100 * n_out / n_in:.2f}% retained)")
    return df.reset_index(drop=True)
