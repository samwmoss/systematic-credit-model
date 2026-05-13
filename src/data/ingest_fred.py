"""FRED cache loader: reads the committed parquet, no API call.

The cache is built/refreshed by scripts/fred_download.py. This module is the
runtime path — pure read, fails loudly if the cache is missing or malformed.
"""
import logging
from pathlib import Path
import pandas as pd

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def ingest_fred(fred_cfg: dict) -> pd.DataFrame:
    """Load the FRED parquet cache.

    Args:
        fred_cfg: The `fred` section of config.yaml.

    Returns:
        DataFrame with DatetimeIndex and one column per series in
        `fred_cfg["series"]`.

    Raises:
        FileNotFoundError: if the cache file does not exist.
        ValueError: if expected series columns are missing from the cache.
    """
    cache_path = Path(fred_cfg["cache_path"])
    if not cache_path.is_absolute():
        cache_path = PROJECT_ROOT / cache_path

    if not cache_path.exists():
        raise FileNotFoundError(
            f"FRED cache not found at {cache_path}. "
            f"Build it with: python scripts/fred_download.py"
        )

    log.info(f"Loading FRED cache from {cache_path}")
    df = pd.read_parquet(cache_path)

    expected = set(fred_cfg.get("series", []))
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(
            f"FRED cache at {cache_path} is missing expected series: {missing}. "
            f"Rebuild with: python scripts/fred_download.py"
        )

    log.info(f"  shape: {df.shape}  range: {df.index.min().date()} -> {df.index.max().date()}")
    log.info(f"  nulls: {df.isnull().sum().to_dict()}")
    return df
