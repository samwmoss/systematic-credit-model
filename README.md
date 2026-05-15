# Systematic Credit Signal & Portfolio Prototype

> This project aims to build a reproducible, production minded mini pipeline that researches and tests a simple systematic credit signal and portfolio.

## Overview

1. **What the pipeline does.** Ranks US High Yield bonds by OAS/OASD carry on each monthly rebalance date, constructs a long-only portfolio under explicit issuer (5%) and sector (20%) caps with inverse-DTS weighting, scales total deployment by a composite-z-score regime classifier over VIX / 10Y-2Y / NFCI, and runs a 2010-2018 backtest with full diagnostics (Sharpe, Sortino, Calmar, IR, drawdown, turnover, exposure, per-regime decomposition).

2. **Why this design.** One signal with clear economic intuition (spread compensation per unit of spread risk), one regime overlay for portfolio-level position sizing, two explicit risk controls, and a single-command run. Engineering quality and defensibility were prioritized over alpha maximization per the assignment's stated grading criteria. 

3. **Why this data.** The bond panel was provided. FRED macro series (VIXCLS, T10Y2Y, NFCI) were selected from a candidate set of seven for full coverage of the 2010-2018 backtest window, near-zero publication lag (supports point-in-time use). The FRED parquet cache is committed to the repository so the entire pipeline reproduces from this folder alone; no network access or API key required.

4. **What this is not.** Not a deployment-ready strategy. Transaction costs are not modeled, the IR benchmark is internal rather than an external HY index (FRED licensing changes restricted access to BAMLH0A0HYM2 in April 2026), and the prototype has no live-execution layer. 

## Quick Start

### Optional: Rebuild FRED cache

The repo ships with `raw_data/fred_cache.parquet` (VIXCLS, T10Y2Y, NFCI). Skip unless you want fresh macro data:

1. Get a free FRED API key from https://fred.stlouisfed.org/
2. Add it to `config/config.yaml` under `fred.api_key`
3. Run `python scripts/fred_download.py` (fails loudly if the key is missing or invalid)

### Default run (no network or API key required)

```bash
git clone https://github.com/samwmoss/systematic-credit-model
cd systematic-credit-model
pip install -r requirements.txt
pytest -v tests/
python -m src.main
```

## Repository Structure

```
project/
├── config/
│   └── config.yaml                     # Pipeline parameters (dates, constraints, thresholds)
├── logs/                               # Runtime logs from pipeline executions
├── notebooks/
│   └── inspection.ipynb                # Exploratory data analysis
├── outputs/
│   ├── charts/
│   │   ├── cumulative_returns.png      # Top-pct sensitivity overlay vs benchmark
│   │   ├── drawdown.png                # Drawdown curves overlaid for all top-pct cutoffs + benchmark
│   │   ├── risk_adjusted_comparison.png# ann_return / Sharpe / Sortino / Calmar across top-pct cutoffs + benchmark
│   │   ├── regime_timeline.png         # Regime labels with stress-window shading
│   │   └── rolling_ir.png              # 2-panel: rolling Sharpe (cutoffs + benchmark) + rolling IR (cutoffs only)
│   └── csv/
│       ├── summary_stats.csv           # IR, Sharpe, Sortino, Calmar, max DD, hit rate per top-pct cutoff + benchmark
│       ├── regime_stats.csv            # Per-(series, regime) Sharpe / Sortino / Calmar / vol / DD decomposition
│       ├── subperiod_stats.csv         # post-GFC / low-vol / energy-Q4 splits
│       ├── exposure_decomp.csv         # Sector + rating exposure per top-pct cutoff
│       └── monthly_returns.csv         # Date × (portfolio_topX, benchmark, allocation, regime)
├── raw_data/
│   ├── USHY_INDEX_20260301_part_1.csv
│   └── fred_cache.parquet
├── scripts/
│   └── fred_download.py                
├── src/
│   ├── main.py                         # Pipeline orchestration entry point
│   ├── data/
│   │   ├── ingest_bonds.py
│   │   ├── ingest_fred.py              
│   │   ├── merge.py
│   │   └── validate.py
│   ├── features/
│   │   └── signal.py                   # Credit signal calculation
│   ├── regime/
│   │   └── classifier.py               # Regime classification logic
│   ├── portfolio/
│   │   └── construction.py             # Portfolio construction with constraints
│   ├── evaluation/
│   │   ├── backtest.py                 # Backtest engine
│   │   └── diagnostics.py              # Performance diagnostics
│   └── utils/
│       └── logging_config.py           # Logging configuration
├── tests/
│   ├── test_data.py                    # Data ingestion + validation tests
│   ├── test_signal.py                  # Signal calculation tests
│   ├── test_regime.py                  # Regime classifier tests
│   ├── test_portfolio.py               # Portfolio construction tests
│   └── test_backtest.py                # Backtest engine tests (lag + regime scaling)
├── pm_memo.pdf
├── README.md
└── requirements.txt
```

## Data

### Provided Bond Panel

Below-investment-grade corporate debt index, provided with the assignment. File: `raw_data/USHY_INDEX_20260301_part_1.csv`.

- **Frequency:** Monthly, first-of-month labels (see Variable Map for end-of-month convention).
- **Window:** Jan 2010 – Dec 2018.
- **Size:** 6,696 unique CUSIPs, 218,657 rows × 18 columns

### FRED Macro Series

Three macro indicators selected from a candidate set of seven. Selection criteria: (1) coverage across 2010-2018 backtest, (2) near-zero publication lag (point-in-time use), (3) orthogonal coverage of macro stress dimensions.

**Selected:**
- **`VIXCLS`** — CBOE Volatility Index (daily). Equity volatility / risk appetite.
- **`T10Y2Y`** — 10Y minus 2Y Treasury spread (daily). Yield curve / growth-stress.
- **`NFCI`** — Chicago Fed Financial Conditions Index (weekly). Composite of 105 measures (VIX is one); we use VIX separately because equity vol is the most direct read on credit risk appetite.

**Considered and rejected:**
- **`BAMLH0A0HYM2`** (ICE BofA HY OAS) — FRED restricted to rolling 3-year window post-April 2026; 2010-2018 history unavailable.
- **`T10Y3M`** — no inversion event in 2010-2018; no regime variation in scope.
- **`DGS3MO`, `DGS10`** — yield-level series, slow-moving.
- **`STLFSI4`** — highly correlated with NFCI.
- **`GDPC1`** — quarterly cadence, mismatch with monthly rebalance.

### Variable Map

- `Date` — First-of-month label representing the end-of-month-YYYY-MM snapshot: risk metrics (`OAS`, `OASD`, `DTS`, `Years_To_Maturity`) reflect month-end state; return fields reflect that calendar month's realization. Data fully available no earlier than first business day of following month. Validation in Leakage Checks.
- `Cusip` / `ISIN` — Bond-level identifiers. ISIN unused for US-only data.
- `Ticker` — Issuer-level identifier. Used for issuer caps.
- `Class1` / `Class2` / `Class3` — Instrument type / issuer type / sector. Class3 (19 sectors) used for sector caps; Class1 / Class2 used only for ingestion drops.
- `Eff_Rating_Group` — Letter rating bucket (AA through D_NR).
- `Maturity_Date` — Corrupted (99.1% sentinel `1/1/1900`). Replaced by `Years_To_Maturity`.
- `Years_To_Maturity` — Years to maturity from observation date.
- `OAS` / `OASD` / `DTS` — Spread (bps), spread duration, and `OASD × OAS` (risk-budgeted exposure). Core signal + weighting inputs.
- `Total_Return_MTD` / `Excess_Return_MTD` — Monthly total return and excess return over duration-matched Treasury. **`Excess_Return_MTD` is the backtest dependent variable; signal at row T predicts return at row T+1.**

### Data Quality Notes

Locked from EDA (`notebooks/inspection.ipynb`, Section A):

- **Null `OASD` / `DTS`** — 9 rows dropped at ingestion (same 9 rows in both columns).
- **Fallen angels (BBB / A / AA)** — 691 rows dropped. The panel is the US HY index; BBB-and-above are residual mis-classifications.
- **`D_NR`** (defaulted / not rated) — 1,450 rows dropped. Returns dominated by recovery dynamics, not carry.
- **Government_Related / Agency** — 16 rows dropped (8 each).
- **No minimum-history filter.** Bonds enter from first observation. A minimum-history rule would create survivorship bias by excluding bonds that defaulted or exited shortly after issuance; exactly the population whose realized losses must hit the backtest for honest evaluation.

**Outlier handling — no winsorization.** Inverse-DTS weighting (`1 / DTS`) structurally shrinks extreme-spread bonds' position weight toward zero; outlier ranks don't translate to outlier portfolio exposure. Statistical clipping is replaced by stale-OAS detection at the universe stage (see Failure Modes #1).

**Universe-stage filters (applied during portfolio construction):**
- `OASD == 0` (2,300 rows) and `DTS == 0` (2,786 rows).
- Stale-OAS detection — flagged via `|ΔOAS_m/m| < 1 bp` (baseline 1.75% in panel). Deferred to production (Roadmap); threshold in `config.data.staleness_flag_bps`, currently no consumer.

### Leakage Checks + Merge Notes

**Point-in-time FRED join.** Row `T` (end-of-month snapshot) joins to FRED data with date `≤ end_of_month(T)`. Both knowable no earlier than first business day of month `T+1`. Sample dates in `inspection.ipynb` Section C.

**Signal-to-return lag.** Row `T` contains both end-of-`T` signal inputs and month-`T`'s realized return. Signal layer applies a **one-month lag**: ranking from row `T`, position held during month `T+1`, return realized at row `T+1`'s `Excess_Return_MTD`. Implemented in `signal.py` and `evaluation/backtest.py`.

**FRED publication lag.** Daily series ≤ 3 days; NFCI ≤ 6 days. 7-day grace in `validate_fred` accommodates publication-calendar irregularities.

**Walk-forward standardization.** Regime classifier uses a strictly past-looking trailing window (algorithm in § Regime Classifier). FRED pulled from 2000-01-01 for warmup and out-of-sample threshold fitting; backtest evaluates 2010-2018.

**Date-convention validation (EDA A.8).** Cross-sectional mean `Total_Return_MTD` at six anchor rows matches direction of ICE BofA US HY Master II Index monthly returns (e.g., 2011-08-01 → -4.14% vs August 2011 HY index -4.0%), confirming row `T` tracks the calendar month of label `T`. Corroborates same-row alignment.

## Business Requirements

### Business Objectives

This pipeline is a production-minded research prototype: a systematic credit signal + portfolio framework that a fixed-income team could plausibly extend into a live process. Per the assignment brief, engineering quality is the primary evaluation criterion; quantitative choices are secondary but must be defensible.

Three project-level objectives drove design:

- **Reproducibility from the repo alone.** Single-command end-to-end run, committed data cache, pinned dependencies. Anyone with the repo regenerates every output in ~10 seconds.
- **Defensibility over performance.** Every signal, weighting, and regime choice has an economic justification. 
- **Production-awareness without production scope.** Failure modes and their detection mechanisms are documented; the production roadmap distinguishes what's built from what would be needed to deploy.

## Functional Requirements

### Functional Capabilities

The system performs six end-to-end capabilities under a single command (`python -m src.main`):

1. **Data ingestion + validation** — Bond panel (CSV) and FRED macro series (parquet cache), with schema, range, and leakage gates at each stage.
2. **Point-in-time merge** — FRED data aligned to monthly bond observation dates using only information available at the rebalance (`FRED_date ≤ end_of_month(T)`).
3. **Regime classification** — Monthly regime label (risk-on / neutral / risk-off) from a walk-forward composite z-score over three macro indicators.
4. **Portfolio construction** — Long-only ranking by OAS/OASD, inverse-DTS weighting, iterative joint enforcement of issuer (5%) and sector (20%) caps.
5. **Backtest + diagnostics** — Monthly-rebalance loop with one-month signal-to-return lag, regime-scaled deployment, and comprehensive risk-adjusted metrics (IR, Sharpe, Sortino, Calmar) plus drawdown, turnover, exposure, and per-(series, regime) decomposition.
6. **Logging + output** — Structured run logs to `logs/`; charts (5 PNGs) and tables (5 CSVs) to `outputs/`.

## Technical Requirements

### Architecture

The system is organized into five functional layers with strict module boundaries:

1. **Data layer** (`src/data/`) — ingestion, validation, merging.
2. **Feature layer** (`src/features/`) — signal computation.
3. **Regime layer** (`src/regime/`) — macro-regime classification.
4. **Portfolio layer** (`src/portfolio/`) — constraint-aware portfolio construction.
5. **Evaluation layer** (`src/evaluation/`) — backtest engine and diagnostics.

Each layer is importable as a package. All parameters live in `config/config.yaml`. Logging is shared via `src/utils/logging_config.py`. 

### Module Specifications

- `src/main.py` — Pipeline orchestration entry point. `python -m src.main` runs the full pipeline end-to-end (8 stages: bond ingest → FRED ingest → merge → regime → signal → portfolio → backtest → diagnostics). Returns a dict of artifacts for inspection.
- `src/data/ingest_bonds.py` — Load bond CSV from `config.data.bond_csv`, parse dates, shift to end-of-month convention, apply locked ingestion drops (null OASD/DTS, fallen angels, D_NR, Government_Related, Agency).
- `src/data/ingest_fred.py` — Pure cache loader. Loads FRED series from `raw_data/fred_cache.parquet`. Fails with a clear error if the cache file is missing.
- `scripts/fred_download.py` — Optional utility for rebuilding the FRED parquet cache from API. Not part of the runtime pipeline. Requires `fred.api_key` configured in `config.yaml`. Fails loudly with a directive error if the key is missing.
- `src/data/merge.py` — Align FRED series to monthly bond dates with explicit point-in-time controls. Aggregate daily/weekly FRED to monthly using last-known value before bond date.
- `src/data/validate.py` — Schema checks, range checks, missing-value reporting, leakage assertions.
- `src/features/signal.py` — Compute carry signal (OAS/OASD) and rank within universe per date.
- `src/regime/classifier.py` — Apply rule-based thresholds across VIX, T10Y2Y, NFCI to produce monthly regime label.
- `src/portfolio/construction.py` — Apply universe filter (`OASD > 0`, `DTS > 0`), delegate signal selection + inverse-DTS weighting, enforce issuer (`Ticker`) and sector (`Class3`) caps iteratively until each cap is honored exactly within float precision. Returns position weights summing to 1.0 per Date; regime scaling applied later in the backtest layer.
- `src/evaluation/backtest.py` — Monthly-rebalance loop, portfolio return computation, holdings tracking.
- `src/evaluation/diagnostics.py` — IR, Sharpe, Sortino, Calmar vs. equal-weighted eligible HY universe; drawdown, turnover, sector/rating exposure decomposition; rolling 12-month performance; sub-period (2010-12 / 2013-15 / 2016-18) and per-(series, regime) decomposition. Outputs 5 PNGs to `outputs/charts/` and 5 CSVs to `outputs/csv/`.
- `src/utils/logging_config.py` — Centralized logger configuration; file and console handlers.

### Technology Stack

- **Language:** Python 3.11+.
- **Core libraries:** `pandas`, `numpy`, `pyarrow` (parquet), `pyyaml` (config), `matplotlib` (charts).
- **Data access:** `fredapi` for FRED ingestion.
- **Testing:** `pytest` with assertion-based unit tests.
- **Logging:** Python standard library `logging`.
- **Storage:** CSV for provided bond data (per assignment), parquet for cached macro data and intermediate state.

## Design Decisions

### Signal Choice

**Signal:** Regime-aware spread carry. Rank bonds by OAS / OASD within the eligible universe each rebalance date. Long the top 20% (primary), inverse-DTS weighted (each bond's weight is proportional to 1/DTS, so each bond contributes approximately equal risk to the portfolio). Position size scaled by the regime classifier (see § Regime Classifier). The backtest additionally reports the top 10% and top 30% cutoffs as sensitivity variants.

**Construction:**
- **Numerator (OAS):** Option-Adjusted Spread in basis points. The clean credit spread over duration-matched Treasury, after stripping embedded optionality.
- **Denominator (OASD):** Option-Adjusted Spread Duration. The bond's price sensitivity to credit spread movements.
- **Ratio interpretation:** Basis points of spread compensation per year of spread duration. Higher ratio = better-compensated per unit of credit risk taken.

**Economic intuition.** This is a relative-value signal, not a directional credit bet; for a standardized unit of spread risk, which bonds pay the most. Two mechanisms support it: (1) bonds over-compensating per unit of risk earn higher excess returns on average; (2) HY liquidity is uneven, so carry differentials persist for weeks to months, long enough for monthly rebalancing to capture before reversion. Documented in HY carry literature (Houweling & van Zundert 2017; Israel et al. 2018) on monthly data with statistically significant alpha after controlling for rating, duration, and sector.

**Why "regime-aware".** A pure carry signal loads on credit risk with negative skew. Small steady monthly gains punctuated by large drawdowns when credit conditions deteriorate. The regime overlay does not change which bonds the signal picks; it changes how much capital is deployed based on macro environment. Full position in risk-on, reduced in risk-off. This converts a static long-credit bet into a stress-aware credit strategy.

**Considered and rejected:**

- **Rank by OAS alone.** Rejected — picks for highest absolute spread, which loads systematically on CCC, distressed, and long-duration bonds. A directional credit-risk bet, not a relative-value signal.
- **Rank by OASD alone.** Rejected — picks for highest spread-duration, which loads systematically on long-dated, high-quality bonds with low call optionality. A leveraged bet on credit spreads tightening, not a relative-value signal.
- **Rank by OAS / DTS.** Mathematically degenerate. Since `DTS = OASD × OAS`, the ratio `OAS / DTS = OAS / (OASD × OAS) = 1 / OASD`. The OAS information cancels out, leaving an inverse-spread-duration ranking with no credit-quality consideration.
- **Rank by OAS / OAD.** Rejected — OAD is rate duration, not spread duration. Dividing a credit-risk numerator by a rate-risk denominator mixes two distinct risk dimensions with no clean financial interpretation.
- **Machine-learning signal.** Rejected — the brief asks for a signal with economic intuition. Black-box models lack the economic interpretability a PM needs and don't match the engineering-quality focus.

### Regime Classifier

**Purpose:** Convert monthly macro indicators into a single regime label that scales total deployed capital. The classifier does not change which bonds the signal picks — it changes how much portfolio-level exposure is deployed.

**Inputs:** VIX (`VIXCLS`), 10Y-2Y Treasury spread (`T10Y2Y`), Chicago Fed NFCI (`NFCI`). See § Data → FRED Macro Series for selection rationale.

**Regime states:** Three discrete labels — `risk_on`, `neutral`, `risk_off`. Three states (rather than two or five) balance hierarchical clarity against over-fitting: binary creates whiplash at the threshold; five forces fine-grained allocation decisions the data cannot support.

**Combination method (locked):** Walk-forward composite z-score, monthly cadence. For each rebalance date `T`:

1. Resample each FRED indicator to monthly cadence (last available value per month).
2. Compute trailing-60-month z-score (mean / std from data with index `< T`, strictly past-looking); sign-flip per indicator so all three move in the stress direction.
3. Average the three z-scores → composite stress score.
4. Apply percentile thresholds (33rd / 67th, fit on pre-2010 composites) to label `risk_on` / `neutral` / `risk_off`.

Runtime thresholds on the current config resolve to ~**−0.548 / +0.249**; values adapt automatically to any change in pull window, z-score window, or fit-window endpoints.

**Resulting regime frequency on backtest (2010-2018):** ~47% neutral, ~27% risk_off, ~26% risk_on.

**Considered and rejected:**
- **Vote-based** with fixed percentile thresholds — 61% neutral in backtest, insufficient regime variation to drive portfolio scaling.
- **Full-sample z-score** — standardizes against 2010-2018 mean/std, which uses post-rebalance data and introduces look-ahead. Retained in EDA notebook (B.6) as visualization reference only; not used in production.
- **Bond-level regime application** (filter or re-rank bonds based on regime). Rejected — regime measures systematic risk affecting the entire market; the right response is portfolio-level position sizing, not bond-level filtering. Keeps signal and regime layers cleanly separable.

### Portfolio Construction

**Strategy:** Long-only portfolio of US High Yield bonds, monthly rebalance. Holdings determined by the carry signal (§ Signal Choice), weighted within the selected top-X% set, and scaled at the portfolio level by the regime classifier (§ Regime Classifier).

**Universe Definition.** Before signal ranking, the eligible universe is filtered by:
- Required fields present on rebalance date: `OAS`, `OASD`, `DTS`, `Years_To_Maturity`, `Eff_Rating_Group`, `Excess_Return_MTD`
- `OASD > 0` and `DTS > 0` (signal denominator and weighting denominator must be non-zero)
- Drops applied at ingestion (see Data Quality Notes): fallen angels, D_NR, Government_Related / Agency, null-field rows

**Selection:** Per § Signal Choice — top 20% by `OAS / OASD` (primary); top 10% and top 30% reported as sensitivity.

**Weighting:** Within the selected top-X% set, weight each bond proportional to `1 / DTS` so each position contributes approximately equal risk. Weights normalize to sum to 1 within the selected set before regime scaling.

**Constraints:**
- **Issuer cap** — Maximum 5% portfolio weight per issuer (enforced via `Ticker`). Anchored to the 90th percentile of bonds-per-issuer-per-month in the panel (≈ 4 bonds out of an ~80-bond selected set under the primary 20% cutoff).
- **Sector cap** — Maximum 20% portfolio weight per sector (enforced via `Class3`). Set above the 18% mean for Consumer_Cyclical so it binds only during sector-concentration events (e.g., Energy 2015-16).
- **Rating bucket exposure** — No explicit CCC max or BB min constraint. Fallen angels (BBB and above) excluded at ingestion; eligible universe is B / BB / CCC only. The signal naturally tilts toward CCC under risk-on; the regime classifier handles aggregate risk-taking through position-scaling, not bucket-level filtering.

**Constraint Enforcement Order (within `construction.py`):**
1. Apply universe filter (`OASD > 0`, `DTS > 0`).
2. Compute signal and select top X%.
3. Apply inverse-DTS weighting within the selected set.
4. Enforce caps iteratively in the configured order (default: issuer → sector). For each cap: while any group exceeds the cap, trim the lowest-signal bonds within violating groups, then rescale survivors to sum to 1.0. Convergence is mathematically guaranteed for any cap > 0 with a feasible universe; typically converges within 2–5 passes. Caps are honored exactly within float precision.

Regime scaling is applied at the backtest layer, not in construction (see Rebalance Logic).

**Rebalance Logic:**
- **Frequency:** Monthly.
- **Timing:** A rebalance for month `T+1` uses bond row `T` (end-of-month snapshot) and FRED data with date `≤ end_of_month(T)`. Positions held during month `T+1`; realized return is row `T+1`'s `Excess_Return_MTD`. Both the bond row and matched FRED value become knowable on the first business day of month `T+1`.

**Considered and rejected:**

- **Equal-weighted within the selected top-X% set.** Rejected — inverse-DTS weighting equalizes per-bond risk contribution; equal weighting lets high-DTS bonds dominate portfolio risk.
- **Market-cap weighting.** Rejected — would tilt the portfolio toward larger issuers regardless of signal strength. The signal's purpose is to identify mispriced bonds, not to track issuer size.
- **Issuer cap at Cusip level.** Rejected — Cusip is bond-level; issuer concentration must be enforced at the Ticker level to prevent multi-bond exposure to the same company.
- **Sector cap using Class2 (issuer type).** Rejected — Class2 distinguishes Industrial / Financial / Utility, too coarse to control sector concentration meaningfully. Class3 (19 sectors) provides actionable granularity.
- **Cash held at T-bill yield.** Rejected — `Excess_Return_MTD` is already net of the duration-matched Treasury, so deploying a T-bill yield contribution from un-deployed capital would double-count the rate leg. Cash share contributes zero excess return by construction.
### Failure Modes + Detection

The pipeline is designed for monthly backtest evaluation. If extended to production, three failure modes are most likely to materialize. Each is paired with a concrete detection mechanism.

**1. Stale OAS / matrix-priced bonds.**

*What it is:* HY bonds trade infrequently. Bonds that haven't transacted in weeks are matrix-priced — OAS interpolated from comparable bonds rather than from real trades. When the market moves, matrix-priced OAS lags reality; the signal continues ranking the bond as if its OAS reflects current conditions.

*How it manifests:* Bonds with stale OAS may rank artificially high or low relative to their true market state. Portfolio holdings become anchored to stale prices.

*Detection:* Flag bonds whose `OAS` has not changed by more than 1 bp month-over-month. Baseline rate measured in EDA: **1.75% of bond-months** in the 2010-2018 panel. In production, monitor the share — a spike above ~5% indicates the matrix-pricing source has degraded.

**2. Survivorship and delisting attribution failure.**

*What it is:* Bonds exit the panel for multiple reasons — maturity, call, default, rating-migration. Whether this biases the backtest depends on the source convention: a well-formed panel records the terminal-event return in the bond's last row before removal; a poorly-formed panel silently drops the terminal return.

*Status in this prototype:* Panel empirically verified to follow the standard convention (test `test_exit_row_captures_terminal_event`); see § Assumptions → Survivorship handling for the distribution of exit-row returns. Backtest's `fill_value=0` for bonds with no row at T+1 is therefore not a material bias source. `n_bonds_exited` is monitored at run time (WARNING fires above 5% monthly exit rate). A per-Cusip exit-reason ledger reconciled against external HY default-rate data is on the Roadmap for production-grade attribution.

**3. Regime classifier drift.**

*What it is:* The regime classifier is calibrated on 2000-2009 macro behavior. If indicators behave differently in production (e.g., VIX persistently elevated, NFCI stuck in one state), regime labels become uninformative and position scaling unreliable.

*Already visible at mild level:* Backtest shows ~47% neutral vs designed 33%, suggesting the 2000-2009 fit window (crisis-inclusive) is slightly over-conservative for the 2010-2018 expansion.

*Detection:* Monitor the distribution of regime labels over rolling 12-month windows. If a single regime exceeds 80% of the window, recalibrate the threshold-fit window. Cross-check against independent stress measures (credit spreads, equity drawdowns) to confirm directional consistency.

## Assumptions

**Data.** Bond panel is monthly and complete: no missing months between January 2010 and December 2018. Field semantics, ingestion drops, and identifier roles documented in § Data.

**FRED data.** Revisions during the backtest window are negligible for VIXCLS / T10Y2Y / NFCI (values pulled at runtime match what would have been available point-in-time). Parquet cache committed for reproducibility; pulled 2026-05-12. Runtime pipeline does not refresh the cache.

**Backtest validation posture:**

- The carry signal (`OAS / OASD`) and inverse-DTS weighting are closed-form rules with no fitted parameters, nothing to overfit. No formal in-sample / out-of-sample backtest split is required for the signal layer; universe filters and rating exclusions are definitional, not learned.
- The two constraint values that are in-sample design choices sector cap (20%) and issuer cap (5%, 90th-percentile-anchored) are coarse heuristics chosen from full-panel distributions, not tuned hyperparameters.
- **Headline performance metrics.** Four risk-adjusted measures: IR, Sharpe, Sortino, Calmar. IR uses the equal-weighted excess return of the eligible HY universe as benchmark; IR penalizes the regime overlay's deliberate deviations symmetrically, which makes Sharpe / Sortino / Calmar the more informative metrics for this strategy. All risk-adjusted metrics reported gross of transaction costs. Per-(series, regime) decomposition exported in `regime_stats.csv`.

**Leakage-free design (verified by tests):**

1. **Signal-to-return lag** — verified by `test_backtest_lag_correct`.
2. **Point-in-time FRED join** — verified by `test_merge_no_pit_leakage`.
3. **Walk-forward regime classifier** — verified by `test_regime_thresholds_derived_from_config`.

Mechanics in § Data → Leakage Checks; module locations in § Module Specifications.

**Survivorship handling (verified empirically).** Bond panel records terminal-event returns in each bond's last available row(verified by `test_exit_row_captures_terminal_event`). Of 4,724 bonds that exit the panel before the end: ~80% near-zero terminal return (maturities / calls), ~5% mild losses (rating migrations), ~1.5% catastrophic (defaults, clustered in 2015-16 energy as expected). `fill_value=0` for bonds with no row at T+1 is therefore not a material bias source — those bonds are post-event by definition. A per-Cusip exit-reason ledger for production-grade attribution is on the Roadmap.

## Config

All pipeline parameters live in `config/config.yaml`. The top-level structure:

- `dates` — Backtest start, end, rebalance frequency
- `signal` — Top-pct cutoff (`primary_top_pct` + `sensitivity_top_pcts`), weighting scheme, signal-to-return lag
- `regime` — Combination method, allocation scaling (100/66/33), threshold-fit rule
- `portfolio` — Constraint values (issuer cap, sector cap)
- `data` — Universe filters
- `fred` — API key (optional, used only by `fred_download.py`)
- `logging` — Log level, log file path

The `fred.api_key` field is intentionally blank in the committed config. The runtime pipeline does not require this field; it is read only by `scripts/fred_download.py` when rebuilding the FRED cache.

## Limitations + Roadmap

### Known Limitations

- **IR benchmark is internal.** The IR uses the equal-weighted excess return of the eligible HY universe; the conventional external benchmark (ICE BofA US HY Master II / BAMLH0A0HYM2) is unavailable via FRED post-April 2026. IR penalizes the regime overlay's deliberate deviations symmetrically — Sharpe / Sortino / Calmar are the more informative metrics for this strategy.
- **Transaction costs not modeled.** Reported risk-adjusted metrics are gross. The cost-impact estimate and its implications for cutoff selection are in Roadmap item 1.

### Roadmap
Given more time, the following extensions would meaningfully strengthen the pipeline:

1. **Transaction cost modeling.** At ~49% monthly turnover with 50 bps round-trip HY bid-ask, gross 2.67% return faces ~2.9% annual cost drag (~1.9% scaled by mean deployment 0.66) — current cutoff selection is not viable net of realistic costs. Net-of-cost optimization may shift the preferred cutoff or rebalance frequency.
2. **Signal vs. regime overlay ablation.** Carry-only run (allocation = 1.0) needed to decompose Sharpe / Calmar contribution between bond selection and regime scaling. Drawdown reduction is mechanically overlay-driven; selection's absolute-return contribution remains unisolated.
3. **External benchmark cross-validation.** ICE BofA US HY Master II returned ~5.5–6% annually over 2010–2018 per Bloomberg; internal benchmark (4.81%) is order-of-magnitude consistent but composition-matched external comparison would strengthen attribution and confirm the labeled-month date convention at scale.
4. **Per-Cusip exit-reason ledger.** ~44 bond exits per month in the panel. Attribute each exit to a reason code (call, default, maturity, rating migration) and reconcile against external HY default-rate data — refines survivorship attribution beyond the current empirical `fill_value=0` convention.