"""Rebuild raw_data/fred_cache.parquet from the FRED API.

Standalone utility. Not part of the runtime pipeline (which reads the committed
parquet cache via src/data/ingest_fred.py). Run when refreshing the cache.

Requires fred.api_key in config/config.yaml. Fails loudly with a clear,
actionable error if anything is missing or wrong.

Usage:
    python scripts/fred_download.py
"""
import sys
from pathlib import Path
import yaml
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH  = PROJECT_ROOT / "config" / "config.yaml"

def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if not CONFIG_PATH.exists():
        fail(f"config not found at {CONFIG_PATH}. Run from the project root: python scripts/fred_download.py")

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    fred_cfg   = config.get("fred") or {}
    api_key    = fred_cfg.get("api_key")
    series_ids = fred_cfg.get("series")
    cache_path = fred_cfg.get("cache_path")
    pull_start = fred_cfg.get("pull_start")
    pull_end   = fred_cfg.get("pull_end")

    if not api_key:
        fail("fred.api_key missing or empty in config/config.yaml. Get a free key at https://fred.stlouisfed.org/ and add it under the fred section.")
    if not series_ids:
        fail("fred.series missing or empty in config/config.yaml. Expected a list of FRED series IDs (e.g., [VIXCLS, T10Y2Y, NFCI]).")
    if not cache_path:
        fail("fred.cache_path missing in config/config.yaml. Expected a relative path like 'raw_data/fred_cache.parquet'.")
    if not pull_start or not pull_end:
        fail("fred.pull_start and/or fred.pull_end missing in config/config.yaml. Expected ISO dates like '2000-01-01'.")

    try:
        from fredapi import Fred
    except ImportError:
        fail("fredapi package not installed. Run: pip install fredapi")

    print(f"Pulling FRED series {series_ids}   window: {pull_start} -> {pull_end}")
    fred = Fred(api_key=api_key)

    raw = {}
    for sid in series_ids:
        try:
                ts = fred.get_series(sid, observation_start=pull_start, observation_end=pull_end)
        except Exception as e:
            fail(f"failed to pull series '{sid}': {e}. Verify the series ID and API key (https://fred.stlouisfed.org/docs/api/api_key.html).")
        if ts is None or len(ts) == 0:
                fail(f"series '{sid}' returned no data for window {pull_start} -> {pull_end}. Verify the series is published over that range.")
        raw[sid] = ts
        print(f"  {sid}: {len(ts):,} obs   {ts.index.min().date()} -> {ts.index.max().date()}   nulls={ts.isnull().sum()}")

    df = pd.DataFrame(raw)
    df.index.name = "date"

    out_path = PROJECT_ROOT / cache_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        df.to_parquet(out_path, engine="pyarrow", compression="snappy")
    except ImportError:
        fail("pyarrow not installed. Run: pip install pyarrow")
    except Exception as e:
        fail(f"failed to write parquet at {out_path}: {e}.")

    try:
        check = pd.read_parquet(out_path)
    except Exception as e:
        fail(f"parquet wrote but failed to roundtrip-read at {out_path}: {e}.")

    if check.shape != df.shape:
        fail(f"parquet roundtrip shape mismatch. wrote {df.shape}, read {check.shape}.")
    if set(check.columns) != set(series_ids):
        fail(f"parquet roundtrip columns mismatch. expected {series_ids}, got {list(check.columns)}.")

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print()
    print(f"SUCCESS: wrote {out_path}")
    print(f"  shape: {df.shape}   size: {size_mb:.2f} MB")
    print(f"  date range: {df.index.min().date()} -> {df.index.max().date()}")


if __name__ == "__main__":
    main()
