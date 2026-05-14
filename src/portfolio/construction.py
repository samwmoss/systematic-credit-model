"""Portfolio construction: universe filter + signal selection + cap enforcement.

Returns final long-only weights summing to 1.0 per Date (full deployment).
Regime scaling is NOT applied here — that lives in the backtest engine.

Enforcement is **iterative until convergence** per the locked design
(README § Constraint Enforcement Order):
    1. Universe filter (OASD > 0, DTS > 0)
    2. Signal selection + inverse-DTS weighting (delegated to compute_signal)
    3. Caps applied in the order from portfolio_cfg["constraint_order"]
       (default: issuer_cap -> sector_cap)

Per-cap algorithm (iterative; converges in 2-5 passes typically):
    - For each Date: while any group exceeds the cap, drop lowest-carry bonds
      from violating groups until each group sum <= cap, then rescale surviving
      bonds so weights re-sum to 1.0 (full deployment).
    - Repeat trim+rescale until no group exceeds the cap.

A `max_iter` safeguard raises RuntimeError if convergence fails (pathological
universe shape only — won't happen with the locked config + bond panel).
The cap value is therefore honored exactly within float precision.
"""
import logging
import pandas as pd

from src.features.signal import compute_signal

log = logging.getLogger(__name__)

CAP_CONVERGENCE_TOL    = 1e-9   # float-comparison epsilon for "group sum <= cap"
MAX_CAP_ITERATIONS     = 20     # inner per-cap iter; typical convergence 2-5
MAX_JOINT_ITERATIONS   = 20     # outer joint-cap iter; typical convergence 2-4


def build_portfolio(
    panel: pd.DataFrame,
    signal_cfg: dict,
    portfolio_cfg: dict,
    top_pct: float | None = None,
) -> pd.DataFrame:
    """Build the long-only portfolio per locked design.

    Args:
        panel: Merged bond panel (output of merge_bonds_fred).
        signal_cfg: The `signal` section of config.yaml.
        portfolio_cfg: The `portfolio` section of config.yaml. Required keys:
            issuer_cap, sector_cap, issuer_field, sector_field, constraint_order.
        top_pct: Top-X% cutoff override for sensitivity runs (e.g. 0.10, 0.30).
            Defaults to signal_cfg["primary_top_pct"].

    Returns:
        DataFrame of held bonds with all original columns plus `carry` and
        `weight`. Within each Date, weights sum to 1.0 (full deployment).
        Every cap in portfolio_cfg is honored exactly (within float epsilon).

    Raises:
        RuntimeError: if any cap fails to converge within MAX_CAP_ITERATIONS
            on any Date (indicates a pathological universe shape).
    """
    issuer_cap       = portfolio_cfg["issuer_cap"]
    sector_cap       = portfolio_cfg["sector_cap"]
    issuer_field     = portfolio_cfg["issuer_field"]
    sector_field     = portfolio_cfg["sector_field"]
    constraint_order = portfolio_cfg["constraint_order"]

    log.info(
        f"Building portfolio: top_pct={top_pct or signal_cfg['primary_top_pct']}, "
        f"issuer_cap={issuer_cap}, sector_cap={sector_cap}"
    )

    eligible = _filter_universe(panel)
    log.info(f"  universe: {len(eligible):,} bond-date rows")

    selected = compute_signal(eligible, signal_cfg, top_pct=top_pct)

    cap_specs = {
        "issuer_cap": (issuer_field, issuer_cap),
        "sector_cap": (sector_field, sector_cap),
    }
    active_caps = []
    for cap_name in constraint_order:
        if cap_name not in cap_specs:
            log.warning(f"  unknown constraint '{cap_name}' in constraint_order; skipping")
            continue
        group_col, cap_val = cap_specs[cap_name]
        if cap_val is None:
            log.info(f"  skipping {cap_name}: not set in config")
            continue
        active_caps.append((cap_name, group_col, cap_val))

    # Outer loop: iterate over all caps until *jointly* satisfied. Necessary
    # because each cap's redistribute step can re-violate previously-satisfied
    # caps (e.g., sector trim's rescale pushes an at-cap issuer back over).
    for joint_iter in range(MAX_JOINT_ITERATIONS):
        for cap_name, group_col, cap_val in active_caps:
            selected = _enforce_cap(selected, group_col, cap_val)
        if _all_caps_clean(selected, active_caps):
            break
    else:
        worst = _worst_violation(selected, active_caps)
        raise RuntimeError(
            f"Joint cap enforcement failed to converge in {MAX_JOINT_ITERATIONS} "
            f"outer iterations. Worst residual: {worst}"
        )
    log.info(f"  joint cap convergence: {joint_iter + 1} outer iterations")

    sums = selected.groupby("Date").weight.sum()
    log.info(
        f"  final: {len(selected):,} bond-date rows  "
        f"weight sum range [{sums.min():.6f}, {sums.max():.6f}]"
    )
    return selected


def _filter_universe(panel: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where signal/weight denominators are undefined."""
    return panel[(panel.OASD > 0) & (panel.DTS > 0)].reset_index(drop=True)


def _all_caps_clean(selected: pd.DataFrame, active_caps: list) -> bool:
    """True if every active cap is honored on every Date (within float epsilon)."""
    for _, group_col, cap_val in active_caps:
        max_g = selected.groupby(["Date", group_col]).weight.sum().max()
        if max_g > cap_val + CAP_CONVERGENCE_TOL:
            return False
    return True


def _worst_violation(selected: pd.DataFrame, active_caps: list) -> dict:
    """Return the worst residual violation across all caps (for error reporting)."""
    out = {}
    for cap_name, group_col, cap_val in active_caps:
        max_g = selected.groupby(["Date", group_col]).weight.sum().max()
        out[cap_name] = {"cap": cap_val, "max_group_weight": float(max_g)}
    return out


def _enforce_cap(
    selected: pd.DataFrame,
    group_col: str,
    cap: float,
) -> pd.DataFrame:
    """Iterative per-Date cap enforcement: trim + rescale until convergence.

    For each Date, repeats trim+rescale until no group exceeds the cap. Each
    iteration: drop lowest-carry bonds from violating groups until group sum
    <= cap, then rescale all survivors so weights re-sum to 1.0.

    Raises:
        RuntimeError: if convergence not reached within MAX_CAP_ITERATIONS.
    """
    pieces           = []
    total_violations = 0
    total_trimmed    = 0
    iterations_used  = []

    for date, group in selected.groupby("Date", sort=False):
        for iteration in range(MAX_CAP_ITERATIONS):
            group_sums = group.groupby(group_col).weight.sum()
            violators  = group_sums[group_sums > cap + CAP_CONVERGENCE_TOL].index.tolist()

            if not violators:
                break

            total_violations += len(violators)

            to_drop = set()
            for violator in violators:
                v_rows = group[group[group_col] == violator].sort_values("carry")
                running_sum = group_sums[violator]
                for idx, row in v_rows.iterrows():
                    if running_sum <= cap:
                        break
                    to_drop.add(idx)
                    running_sum -= row.weight

            total_trimmed += len(to_drop)

            survivors      = group.drop(list(to_drop)).copy()
            trimmed_total  = group.loc[list(to_drop), "weight"].sum()
            if trimmed_total > 0 and len(survivors) > 0:
                survivors["weight"] = survivors["weight"] / (1 - trimmed_total)

            group = survivors
        else:
            raise RuntimeError(
                f"Cap '{group_col}' <= {cap} failed to converge for date "
                f"{date.date() if hasattr(date, 'date') else date} "
                f"after {MAX_CAP_ITERATIONS} iterations. "
                f"Last group sums: {dict(group_sums)}"
            )

        iterations_used.append(iteration)
        pieces.append(group)

    if iterations_used:
        max_iter = max(iterations_used)
        avg_iter = sum(iterations_used) / len(iterations_used)
        log.info(
            f"  cap '{group_col}' <= {cap}: "
            f"{total_violations} violations resolved across iterations "
            f"({total_trimmed} bond-trims total); "
            f"convergence avg={avg_iter:.1f} iter, max={max_iter} iter"
        )

    return pd.concat(pieces, ignore_index=True)
