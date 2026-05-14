"""Diagnostics: compute metrics + emit PNG charts and CSV tables to outputs/.

Consumes per-(top-pct cutoff) backtest results, regime classifier output, and config.
Pure consumer — no portfolio logic, no backtest re-runs.

Writes:
  outputs/charts/
    cumulative_returns.png         — cumulative excess return overlay across all top-pct cutoffs + benchmark
    drawdown.png                   — drawdown curves overlaid for all top-pct cutoffs + benchmark
    regime_timeline.png            — regime labels + stress window shading
    rolling_ir.png                 — 2-panel rolling chart: Sharpe (cutoffs + benchmark) and IR (cutoffs only)
    risk_adjusted_comparison.png   — 2x2 small-multiples: ann_return / Sharpe / Sortino / Calmar
                                       across top-pct cutoffs + benchmark

  outputs/csv/
    summary_stats.csv        — IR, Sharpe, Sortino, Calmar, MaxDD, turnover, hit rate per top-pct cutoff + benchmark row
    monthly_returns.csv      — date x (portfolio_topX, benchmark, allocation, regime)
    regime_stats.csv         — per-(series, regime) risk/return decomp (each top-pct cutoff + benchmark)
    subperiod_stats.csv      — by sub-period decomposition
    exposure_decomp.csv      — sector + rating exposure per top-pct cutoff

Single public entry: `generate_diagnostics(...)`.
"""
import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless-safe; no display required
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def generate_diagnostics(
    results: dict,
    regime_out: dict,
    cfg: dict,
    output_dir: Path,
) -> None:
    """Compute performance metrics + write PNGs/CSVs for the PM memo.

    Args:
        results: dict mapping each sensitivity top-pct cutoff (e.g. 0.10) to its
            backtest output dict (from `run_backtest`).
        regime_out: output of `classify_regimes` (for regime timeline plot).
        cfg: full config dict. Uses `signal.primary_top_pct` and the
            `diagnostics` section (sub_periods, rolling_window_months, stress_windows).
        output_dir: typically `Path("outputs")`; writes to `charts/` + `csv/` subdirs.
    """
    if not results:
        log.warning("generate_diagnostics: empty results dict; nothing to write")
        return

    output_dir   = Path(output_dir)
    charts_dir   = output_dir / "charts"
    csv_dir      = output_dir / "csv"
    charts_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    primary_q = cfg["signal"]["primary_top_pct"]
    if primary_q not in results:
        log.warning(f"primary top_pct {primary_q} not in results; using {sorted(results)[0]}")
        primary_q = sorted(results)[0]
    primary_bt = results[primary_q]

    diag_cfg       = cfg.get("diagnostics", {})
    sub_periods    = diag_cfg.get("sub_periods", [])
    rolling_window = diag_cfg.get("rolling_window_months", 12)
    stress_windows = diag_cfg.get("stress_windows", [])

    log.info(f"Generating diagnostics for {len(results)} top-pct cutoff variants -> {output_dir}")

    # --- Compute layer ---
    summary_rows = {q: _compute_summary_stats(bt) for q, bt in results.items()}
    summary_df   = pd.DataFrame(summary_rows).T.rename_axis("top_pct")
    summary_df.loc["benchmark"] = _compute_benchmark_stats(primary_bt)

    regime_stats_df = _compute_regime_stats(results, primary_bt)

    subperiod_df = _compute_subperiod_stats(results, sub_periods) if sub_periods else pd.DataFrame()

    exposure_rows = {q: _compute_exposure(bt["holdings"]) for q, bt in results.items()}
    exposure_df   = pd.DataFrame(exposure_rows).T.rename_axis("top_pct")

    # --- Write CSVs ---
    summary_df.to_csv(csv_dir / "summary_stats.csv", float_format="%.6f")
    log.info(f"  wrote {csv_dir / 'summary_stats.csv'}")

    _write_monthly_returns(results, csv_dir / "monthly_returns.csv")
    log.info(f"  wrote {csv_dir / 'monthly_returns.csv'}")

    regime_stats_df.to_csv(csv_dir / "regime_stats.csv", float_format="%.6f", index=False)
    log.info(f"  wrote {csv_dir / 'regime_stats.csv'}")

    if not subperiod_df.empty:
        subperiod_df.to_csv(csv_dir / "subperiod_stats.csv", float_format="%.6f")
        log.info(f"  wrote {csv_dir / 'subperiod_stats.csv'}")

    exposure_df.to_csv(csv_dir / "exposure_decomp.csv", float_format="%.6f")
    log.info(f"  wrote {csv_dir / 'exposure_decomp.csv'}")

    # --- Write PNGs ---
    _plot_cumulative(results, primary_q, charts_dir / "cumulative_returns.png")
    log.info(f"  wrote {charts_dir / 'cumulative_returns.png'}")

    _plot_drawdown(results, primary_q, charts_dir / "drawdown.png")
    log.info(f"  wrote {charts_dir / 'drawdown.png'}")

    _plot_regime_timeline(regime_out, stress_windows, charts_dir / "regime_timeline.png")
    log.info(f"  wrote {charts_dir / 'regime_timeline.png'}")

    _plot_rolling(results, primary_q, rolling_window, charts_dir / "rolling_ir.png")
    log.info(f"  wrote {charts_dir / 'rolling_ir.png'}")

    _plot_risk_adjusted_comparison(summary_df, charts_dir / "risk_adjusted_comparison.png")
    log.info(f"  wrote {charts_dir / 'risk_adjusted_comparison.png'}")

    # --- Headline log line ---
    p = summary_rows[primary_q]
    log.info(
        f"Diagnostics complete. Primary (top_pct={primary_q}): "
        f"IR={p['info_ratio']:.3f}  Sharpe={p['sharpe']:.3f}  "
        f"Sortino={p['sortino']:.3f}  Calmar={p['calmar']:.3f}  "
        f"MaxDD={p['max_drawdown']:.3f}  AnnRet={p['ann_return']:.3f}"
    )


# ---------- Compute helpers ----------

def _compute_summary_stats(bt: dict) -> dict:
    """Per-(top-pct cutoff) summary metrics. Returns are already excess (vs. duration-matched Treasury)."""
    pf = bt["portfolio_returns"]
    ac = bt["active_returns"]
    tn = bt["turnover"]

    ann_return = float(pf.mean() * 12)
    ann_vol    = float(pf.std() * np.sqrt(12))
    sharpe     = float(pf.mean() / pf.std() * np.sqrt(12)) if pf.std() > 0 else float("nan")
    ir         = float(ac.mean() / ac.std() * np.sqrt(12)) if ac.std() > 0 else float("nan")
    te         = float(ac.std() * np.sqrt(12))

    cum    = pf.cumsum()
    dd     = cum - cum.cummax()
    max_dd = float(dd.min())

    sortino = _sortino(pf)
    calmar  = _calmar(ann_return, max_dd)

    return {
        "ann_return":      ann_return,
        "ann_vol":         ann_vol,
        "sharpe":          sharpe,
        "sortino":         sortino,
        "calmar":          calmar,
        "info_ratio":      ir,
        "tracking_error":  te,
        "max_drawdown":    max_dd,
        "mean_turnover":   float(tn.mean()) if len(tn) else float("nan"),
        "hit_rate":        float((pf > 0).mean()),
        "active_hit_rate": float((ac > 0).mean()),
    }


def _sortino(returns: pd.Series) -> float:
    """Annualized Sortino with MAR=0 (downside std = std of negative returns only).

    Returns NaN if there are <2 negative observations or downside std is zero.
    """
    downside = returns[returns < 0]
    if len(downside) < 2:
        return float("nan")
    dstd = float(downside.std())
    if dstd <= 0:
        return float("nan")
    return float(returns.mean() / dstd * np.sqrt(12))


def _calmar(ann_return: float, max_dd: float) -> float:
    """Calmar = ann_return / |max_drawdown|. NaN when max_dd is zero (no drawdown observed)."""
    if max_dd == 0 or not np.isfinite(max_dd):
        return float("nan")
    return float(ann_return / abs(max_dd))


def _compute_benchmark_stats(primary_bt: dict) -> dict:
    """Summary stats for the equal-weighted eligible-HY benchmark.

    Reported on the same scale as the strategy rows. IR/TE/active_hit_rate are
    NaN by construction (benchmark vs itself). Turnover is NaN — benchmark is a
    reconstituted cross-sectional mean, not a tradeable book.
    """
    bm = primary_bt["benchmark_returns"]
    ann_return = float(bm.mean() * 12)
    ann_vol    = float(bm.std() * np.sqrt(12))
    sharpe     = float(bm.mean() / bm.std() * np.sqrt(12)) if bm.std() > 0 else float("nan")
    cum    = bm.cumsum()
    max_dd = float((cum - cum.cummax()).min())
    sortino = _sortino(bm)
    calmar  = _calmar(ann_return, max_dd)
    return {
        "ann_return":      ann_return,
        "ann_vol":         ann_vol,
        "sharpe":          sharpe,
        "sortino":         sortino,
        "calmar":          calmar,
        "info_ratio":      float("nan"),
        "tracking_error":  float("nan"),
        "max_drawdown":    max_dd,
        "mean_turnover":   float("nan"),
        "hit_rate":        float((bm > 0).mean()),
        "active_hit_rate": float("nan"),
    }


def _compute_regime_stats(results: dict, primary_bt: dict) -> pd.DataFrame:
    """Per-regime, per-series risk + return decomposition.

    One row per (series, regime). Series = each top-pct cutoff + 'benchmark'.
    Regime labels are aligned with each month's actual classification from
    `regime_labels`; benchmark uses the primary cutoff's regime series
    (identical across cutoffs).
    """
    regime_series = primary_bt["regime_labels"]
    rows = []

    for q, bt in sorted(results.items()):
        pf = bt["portfolio_returns"]
        for regime in ("risk_on", "neutral", "risk_off"):
            mask = (regime_series == regime).reindex(pf.index, fill_value=False)
            sub  = pf[mask]
            rows.append(_regime_row(f"top{int(q*100)}", regime, sub))

    bm = primary_bt["benchmark_returns"]
    for regime in ("risk_on", "neutral", "risk_off"):
        mask = (regime_series == regime).reindex(bm.index, fill_value=False)
        sub  = bm[mask]
        rows.append(_regime_row("benchmark", regime, sub))

    return pd.DataFrame(rows)


def _regime_row(series_name: str, regime: str, sub: pd.Series) -> dict:
    if len(sub) < 2:
        return {
            "series": series_name, "regime": regime, "n_months": int(len(sub)),
            "mean_monthly": float("nan"), "ann_return": float("nan"),
            "ann_vol": float("nan"), "sharpe": float("nan"),
            "sortino": float("nan"), "calmar": float("nan"),
            "max_drawdown": float("nan"), "hit_rate": float("nan"),
        }
    cum = sub.cumsum()
    max_dd = float((cum - cum.cummax()).min())
    vol = float(sub.std() * np.sqrt(12))
    sharpe = float(sub.mean() / sub.std() * np.sqrt(12)) if sub.std() > 0 else float("nan")
    ann_return = float(sub.mean() * 12)
    return {
        "series":       series_name,
        "regime":       regime,
        "n_months":     int(len(sub)),
        "mean_monthly": float(sub.mean()),
        "ann_return":   ann_return,
        "ann_vol":      vol,
        "sharpe":       sharpe,
        "sortino":      _sortino(sub),
        "calmar":       _calmar(ann_return, max_dd),
        "max_drawdown": max_dd,
        "hit_rate":     float((sub > 0).mean()),
    }


def _compute_drawdown(returns: pd.Series) -> pd.Series:
    cum = returns.cumsum()
    return cum - cum.cummax()


def _compute_subperiod_stats(results: dict, sub_periods: list) -> pd.DataFrame:
    """For each (top-pct cutoff, sub-period), compute summary stats."""
    rows = []
    for q, bt in results.items():
        for period in sub_periods:
            start = pd.Timestamp(period["start"])
            end   = pd.Timestamp(period["end"])

            ret_mask  = (bt["portfolio_returns"].index >= start) & (bt["portfolio_returns"].index <= end)
            turn_mask = (bt["turnover"].index >= start) & (bt["turnover"].index <= end) if len(bt["turnover"]) else None

            sliced = {
                "portfolio_returns": bt["portfolio_returns"][ret_mask],
                "active_returns":    bt["active_returns"][ret_mask],
                "turnover":          bt["turnover"][turn_mask] if turn_mask is not None else bt["turnover"],
            }
            if len(sliced["portfolio_returns"]) < 2:
                continue
            stats = _compute_summary_stats(sliced)
            stats["top_pct"] = q
            stats["period"]   = period["name"]
            rows.append(stats)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index(["top_pct", "period"])


def _compute_exposure(holdings: pd.DataFrame) -> dict:
    """Top sectors by mean weight + rating bucket distribution."""
    out: dict = {}

    if "Class3" not in holdings.columns or "Eff_Rating_Group" not in holdings.columns:
        log.warning("holdings missing Class3 or Eff_Rating_Group; skipping exposure decomp")
        return out

    sector_means = (
        holdings.groupby(["Date", "Class3"])["weight"].sum()
        .groupby("Class3").mean()
        .sort_values(ascending=False)
    )
    for i, (sector, w) in enumerate(sector_means.head(5).items()):
        out[f"top{i+1}_sector_name"]   = str(sector)
        out[f"top{i+1}_sector_weight"] = float(w)

    rating_means = (
        holdings.groupby(["Date", "Eff_Rating_Group"])["weight"].sum()
        .groupby("Eff_Rating_Group").mean()
    )
    for rating in ("B", "BB", "CCC"):
        out[f"mean_weight_{rating}"] = float(rating_means.get(rating, 0.0))

    return out


# ---------- Plot helpers ----------

def _plot_cumulative(results: dict, primary_q: float, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))

    for q in sorted(results.keys()):
        pf  = results[q]["portfolio_returns"]
        cum = pf.cumsum()
        is_primary = (q == primary_q)
        ax.plot(
            cum.index, cum.values,
            label=f"Top {int(q*100)}%" + (" (primary)" if is_primary else ""),
            linewidth=2.5 if is_primary else 1.2,
            alpha=1.0 if is_primary else 0.7,
        )

    bm = results[primary_q]["benchmark_returns"]
    ax.plot(
        bm.index, bm.cumsum().values,
        label="Benchmark (eq-wgt eligible HY)",
        linestyle="--", linewidth=1.2, color="gray",
    )

    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title("Cumulative Excess Return — Top-Pct Sensitivity Overlay")
    ax.set_ylabel("Cumulative excess return (%)")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_drawdown(results: dict, primary_q: float, path: Path) -> None:
    """Drawdown curves overlaid for all top-pct cutoffs + benchmark.

    Primary cutoff is rendered bold; non-primary cutoffs are thinner / faded;
    benchmark is dashed grey. Y-axis spans the deepest drawdown across all
    series so the relative magnitude (strategy DD vs benchmark DD) is visible.
    """
    fig, ax = plt.subplots(figsize=(11, 5))

    for q in sorted(results.keys()):
        pf = results[q]["portfolio_returns"]
        dd = _compute_drawdown(pf)
        is_primary = (q == primary_q)
        ax.plot(
            dd.index, dd.values,
            label=f"Top {int(q*100)}%" + (" (primary)" if is_primary else ""),
            linewidth=2.5 if is_primary else 1.2,
            alpha=1.0 if is_primary else 0.7,
        )

    bm    = results[primary_q]["benchmark_returns"]
    bm_dd = _compute_drawdown(bm)
    ax.plot(
        bm_dd.index, bm_dd.values,
        label="Benchmark (eq-wgt eligible HY)",
        linestyle="--", linewidth=1.2, color="gray",
    )

    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title("Drawdown — Top-Pct Sensitivity Overlay vs Benchmark")
    ax.set_ylabel("Drawdown (cumulative excess return below high-water mark, %)")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_regime_timeline(regime_out: dict, stress_windows: list, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4))

    labels = regime_out["labels"].dropna()
    code = labels.astype(str).map({"risk_on": 1, "neutral": 0, "risk_off": -1}).astype(float)
    ax.fill_between(code.index, code.values, 0, alpha=0.4, step="pre")
    ax.set_yticks([-1, 0, 1])
    ax.set_yticklabels(["off", "neutral", "on"])

    for sw in stress_windows:
        ax.axvspan(pd.Timestamp(sw["start"]), pd.Timestamp(sw["end"]), alpha=0.15, color="red")

    ax.set_title("Regime Classifier — Walk-Forward Composite Z-Score")
    ax.set_ylabel("Regime")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_risk_adjusted_comparison(summary_df: pd.DataFrame, path: Path) -> None:
    """2x2 small-multiples: ann_return, Sharpe, Sortino, Calmar across top-pct cutoffs + benchmark.

    Each panel has its own y-scale (metric magnitudes differ). Benchmark bar is
    rendered in grey to distinguish it from the strategy variants.
    """
    metrics = [
        ("ann_return", "Annualized Return (%)"),
        ("sharpe",     "Sharpe Ratio"),
        ("sortino",    "Sortino Ratio"),
        ("calmar",     "Calmar Ratio"),
    ]

    # Build label list + color list. Top-pct cutoff rows are floats (0.1, 0.2, 0.3);
    # benchmark is a string. Preserve summary_df row order.
    labels = []
    colors = []
    for idx in summary_df.index:
        if isinstance(idx, str) and idx == "benchmark":
            labels.append("Benchmark")
            colors.append("0.55")  # grey
        else:
            labels.append(f"top{int(float(idx) * 100)}")
            colors.append("steelblue")

    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, (col, title) in zip(axes.flat, metrics):
        values = summary_df[col].values
        ax.bar(labels, values, color=colors, edgecolor="black", linewidth=0.5)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(title)
        ax.grid(True, alpha=0.3, axis="y")
        # Annotate bars with values
        for i, v in enumerate(values):
            if np.isnan(v):
                continue
            ax.text(i, v, f"{v:.2f}", ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=9)

    fig.suptitle("Risk-Adjusted Performance — Top-Pct Cutoffs vs Benchmark",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_rolling(results: dict, primary_q: float, window: int, path: Path) -> None:
    """Two-panel rolling chart: Sharpe (top) + IR (bottom), per top-pct cutoff.

    Sharpe panel includes benchmark (dashed grey); IR panel does not, since IR
    is computed against the benchmark and benchmark-vs-itself is identically zero.
    Primary cutoff is rendered bold; non-primary cutoffs are thinner / faded.
    """
    fig, (ax_s, ax_ir) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    # --- Top panel: rolling Sharpe per cutoff + benchmark ---
    for q in sorted(results.keys()):
        pf = results[q]["portfolio_returns"]
        rs = (pf.rolling(window).mean() / pf.rolling(window).std()) * np.sqrt(12)
        is_primary = (q == primary_q)
        ax_s.plot(
            rs.index, rs.values,
            label=f"Top {int(q*100)}%" + (" (primary)" if is_primary else ""),
            linewidth=2.5 if is_primary else 1.2,
            alpha=1.0 if is_primary else 0.7,
        )

    bm    = results[primary_q]["benchmark_returns"]
    bm_rs = (bm.rolling(window).mean() / bm.rolling(window).std()) * np.sqrt(12)
    ax_s.plot(
        bm_rs.index, bm_rs.values,
        label="Benchmark (eq-wgt eligible HY)",
        linestyle="--", linewidth=1.2, color="gray",
    )

    ax_s.axhline(0, color="black", linewidth=0.5)
    ax_s.set_title(f"Rolling {window}-Month Sharpe — Top-Pct Sensitivity Overlay vs Benchmark")
    ax_s.set_ylabel("Annualized Sharpe")
    ax_s.legend(loc="best")
    ax_s.grid(True, alpha=0.3)

    # --- Bottom panel: rolling IR per cutoff (no benchmark — IR vs self = 0) ---
    for q in sorted(results.keys()):
        ac = results[q]["active_returns"]
        rir = (ac.rolling(window).mean() / ac.rolling(window).std()) * np.sqrt(12)
        is_primary = (q == primary_q)
        ax_ir.plot(
            rir.index, rir.values,
            label=f"Top {int(q*100)}%" + (" (primary)" if is_primary else ""),
            linewidth=2.5 if is_primary else 1.2,
            alpha=1.0 if is_primary else 0.7,
        )

    ax_ir.axhline(0, color="black", linewidth=0.5)
    ax_ir.set_title(f"Rolling {window}-Month Information Ratio — Top-Pct Sensitivity")
    ax_ir.set_ylabel("Annualized IR")
    ax_ir.set_xlabel("Date")
    ax_ir.legend(loc="best")
    ax_ir.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------- CSV helpers ----------

def _write_monthly_returns(results: dict, path: Path) -> None:
    """Wide CSV: Date x (portfolio_topX for each top-pct cutoff, benchmark, allocation, regime)."""
    any_bt = next(iter(results.values()))
    df = pd.DataFrame(index=any_bt["portfolio_returns"].index)
    df.index.name = "Date"

    for q, bt in sorted(results.items()):
        df[f"portfolio_top{int(q*100)}"] = bt["portfolio_returns"]

    # Benchmark / allocation / regime from the middle cutoff (or smallest if single)
    qs = sorted(results.keys())
    primary_idx = qs[len(qs) // 2]
    primary_bt  = results[primary_idx]

    df["benchmark"]  = primary_bt["benchmark_returns"]
    df["allocation"] = primary_bt["allocations"]
    df["regime"]     = primary_bt["regime_labels"]

    df.to_csv(path, float_format="%.6f")
