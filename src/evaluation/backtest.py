"""Monthly-rebalance backtest engine.

Pure computation. Consumes pre-built portfolio + regime classifier output and
emits time series of returns + holdings + survivorship monitor.

The single critical contract enforced here: the **1-month signal-to-return lag**
(per A.8 + config.signal.lag_months). Signal computed from row T's data is
applied to row T+1's realized Excess_Return_MTD. This is the line of defense
against the leakage failure mode #4.

No file I/O. Plots / CSVs are produced by `diagnostics.py` from this module's
output dict. Multi-top-pct sensitivity loop lives in `main.py`.
"""
import logging
import pandas as pd

log = logging.getLogger(__name__)


def run_backtest(
    merged: pd.DataFrame,
    portfolio: pd.DataFrame,
    regime_out: dict,
    dates_cfg: dict,
    signal_cfg: dict,
) -> dict:
    """Run the monthly-rebalance backtest.

    Args:
        merged: Bond panel + FRED columns (output of `merge_bonds_fred`). Used
            for next-month return lookup and the equal-weighted benchmark.
        portfolio: Pre-built portfolio (output of `build_portfolio`). One top-pct
            cutoff at a time. Required cols: Date, Cusip, weight.
        regime_out: Output of `classify_regimes`. Uses `regime_out["allocations"]`
            and `regime_out["labels"]`.
        dates_cfg: The `dates` section of config.yaml. Trims the rebalance
            window if the portfolio extends beyond [backtest_start, backtest_end].
        signal_cfg: The `signal` section of config.yaml. Uses `lag_months` to
            determine return realization offset (locked at 1 per A.8).

    Returns:
        Dict of monthly time series indexed by REALIZATION DATE (T + lag):
            portfolio_returns: pd.Series of strategy excess returns
            benchmark_returns: pd.Series of equal-weighted eligible HY universe returns
            active_returns:    portfolio - benchmark (IR numerator)
            allocations:       regime allocation fraction used per realization date
            regime_labels:     regime label per realization date
            n_bonds_held:      position count per Date
            n_bonds_exited:    bonds with positions at T but no row at T+lag (failure mode #2 monitor)
            turnover:          monthly half-sum of |weight changes| (one-way trade convention)
            holdings:          input portfolio (returned for downstream exposure analysis)

    Raises:
        ValueError: if signal_cfg["lag_months"] is not >= 1.
    """
    lag = signal_cfg["lag_months"]
    if lag < 1:
        raise ValueError(f"signal.lag_months must be >= 1; got {lag}")

    rebal_dates = sorted(portfolio.Date.unique())

    # Trim to configured backtest window
    bt_start = pd.Timestamp(dates_cfg["backtest_start"])
    bt_end   = pd.Timestamp(dates_cfg["backtest_end"]) + pd.offsets.MonthEnd(0)
    rebal_dates = [d for d in rebal_dates if bt_start <= d <= bt_end]

    log.info(
        f"Backtest start: lag={lag}mo, "
        f"window=[{rebal_dates[0].date()}, {rebal_dates[-1].date()}], "
        f"n_rebal={len(rebal_dates)}"
    )

    allocations_series = regime_out["allocations"]
    labels_series      = regime_out["labels"]

    portfolio_returns = []
    benchmark_returns = []
    active_returns    = []
    realized_dates    = []
    used_allocations  = []
    used_labels       = []
    n_held            = []
    n_exited          = []
    turnover_records  = []

    prev_holdings = None

    for i in range(len(rebal_dates) - lag):
        rebal_date   = rebal_dates[i]
        realize_date = rebal_dates[i + lag]

        # Holdings at rebal_date (weights sum to 1 per build_portfolio contract)
        holdings = portfolio[portfolio.Date == rebal_date].set_index("Cusip")["weight"]
        if holdings.empty:
            log.warning(f"  no holdings at rebal_date={rebal_date.date()}; skipping")
            continue

        # Next-month bond panel for return realization + benchmark
        next_panel = merged[merged.Date == realize_date]
        if next_panel.empty:
            log.warning(f"  no merged data at realize_date={realize_date.date()}; skipping")
            continue
        next_returns = next_panel.set_index("Cusip")["Excess_Return_MTD"]

        # Reindex held bonds to next-month returns; missing => survivorship exit
        held_returns = next_returns.reindex(holdings.index)
        n_missing    = int(held_returns.isnull().sum())
        held_returns = held_returns.fillna(0.0)

        full_deployment_return = float((holdings * held_returns).sum())

        # Regime allocation at rebal_date (label was computed at end of T)
        alloc = allocations_series.get(rebal_date)
        if alloc is None or pd.isna(alloc):
            log.warning(f"  no regime allocation at {rebal_date.date()}; defaulting to 1.0")
            alloc = 1.0
        else:
            alloc = float(alloc)

        portfolio_return = alloc * full_deployment_return

        # Benchmark: equal-weighted excess return of eligible HY universe at realize_date
        eligible_next    = next_panel[(next_panel.OASD > 0) & (next_panel.DTS > 0)]
        benchmark_return = float(eligible_next["Excess_Return_MTD"].mean())

        active_return = portfolio_return - benchmark_return

        # Turnover: half-sum of absolute weight changes between consecutive holdings
        if prev_holdings is not None:
            all_cusips = holdings.index.union(prev_holdings.index)
            curr      = holdings.reindex(all_cusips, fill_value=0.0)
            prev      = prev_holdings.reindex(all_cusips, fill_value=0.0)
            turnover  = 0.5 * float((curr - prev).abs().sum())
            turnover_records.append((realize_date, turnover))

        portfolio_returns.append(portfolio_return)
        benchmark_returns.append(benchmark_return)
        active_returns.append(active_return)
        realized_dates.append(realize_date)
        used_allocations.append(alloc)
        used_labels.append(
            labels_series.get(rebal_date) if rebal_date in labels_series.index else None
        )
        n_held.append(len(holdings))
        n_exited.append(n_missing)

        prev_holdings = holdings

    idx = pd.DatetimeIndex(realized_dates, name="Date")

    out = {
        "portfolio_returns": pd.Series(portfolio_returns, index=idx, name="portfolio"),
        "benchmark_returns": pd.Series(benchmark_returns, index=idx, name="benchmark"),
        "active_returns":    pd.Series(active_returns,    index=idx, name="active"),
        "allocations":       pd.Series(used_allocations,  index=idx, name="allocation"),
        "regime_labels":     pd.Series(used_labels,       index=idx, name="regime"),
        "n_bonds_held":      pd.Series(n_held,            index=idx, name="n_held"),
        "n_bonds_exited":    pd.Series(n_exited,          index=idx, name="n_exited"),
        "holdings":          portfolio,
    }
    if turnover_records:
        t_idx, t_vals = zip(*turnover_records)
        out["turnover"] = pd.Series(t_vals, index=pd.DatetimeIndex(t_idx, name="Date"), name="turnover")
    else:
        out["turnover"] = pd.Series(dtype=float, name="turnover")

    max_exit_pct = 100 * max(n_exited) / max(n_held) if n_held else 0.0
    log.info(
        f"Backtest complete: {len(portfolio_returns)} monthly returns; "
        f"mean alloc={pd.Series(used_allocations).mean():.3f}; "
        f"mean turnover={out['turnover'].mean():.3f}; "
        f"max exits/month={max(n_exited) if n_exited else 0} ({max_exit_pct:.1f}% of holdings)"
    )
    if max_exit_pct > 5.0:
        log.warning(
            f"  high survivorship exit rate detected (max {max_exit_pct:.1f}%); "
            "see Failure Mode #2 in README"
        )

    return out
