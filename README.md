# Systematic Credit Signal & Portfolio Prototype

> This project aims to build a reproducible, production minded mini pipeline that researches and tests a simple systematic credit signal and portfolio protoype.

## Overview

[Pipeline purpose, scope, and high-level approach.]
Effectively:
1 - What the pipeline does
2 - Why THIS design
3 - Why THIS data
4 - What this is not

## Quick Start

### Default run (no network or API key required)

```bash
pip install -r requirements.txt
python -m src.main
```

The pipeline runs end-to-end using the committed FRED parquet cache and provided bond panel. No external data is fetched.

### Optional: Rebuild FRED cache

The repository ships with `raw_data/fred_cache.parquet` (VIXCLS, T10Y2Y, NFCI). The pipeline reads from this cache and does not require a FRED API key.

To rebuild the cache from the FRED API:
1. Obtain a free API key from https://fred.stlouisfed.org/
2. Add the key to `config/config.yaml` under `fred.api_key`
3. Run `python scripts/fred_download.py`

The download script will fail with a clear error message if the API key is missing or invalid.

## Repository Structure

```
project/
├── config/
│   └── config.yaml                     # Pipeline parameters (dates, constraints, thresholds)
├── logs/                               # Runtime logs from pipeline executions
├── notebooks/
│   └── inspection.ipynb                # Exploratory data analysis
├── outputs/
│   ├── charts/                         # Generated PNG/PDF visualizations
│   └── csv/                            # Generated results tables
├── raw_data/
│   ├── USHY_INDEX_20260301_part_1.csv
│   └── fred_cache.parquet
├── scripts/
│   └── fred_download.py                # Optional: rebuild FRED cache from API
├── src/
│   ├── main.py                         # Pipeline orchestration entry point
│   ├── data/
│   │   ├── ingest_bonds.py
│   │   ├── ingest_fred.py              # Pure cache loader (reads parquet)
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
│   └── test_portfolio.py               # Portfolio construction tests
├── .gitignore
├── README.md
└── requirements.txt
```

## Data

### Provided Bond Panel

**Source:** Historical data set for the US High Yield corporate bond index, provided as part of the assignment.

**File:** `raw_data/USHY_INDEX_20260301_part_1.csv`

**Coverage:**
- **Frequency:** Monthly observations, dated to the first calendar day of each month.
- **Time range:** January 2010 through December 2018.
- **Universe size:** 6,696 unique CUSIPs across the full period.
- **Total observations:** 218,657 rows × 18 columns.

**Scope:** US dollar-denominated, below-investment-grade corporate debt. The panel includes bond-level identifiers, three-tier classification (instrument type, issuer type, sector), credit ratings, bond mechanics (duration, maturity), risk and pricing metrics (OAS, OAD, OASD, DTS, Yield-to-Worst), and monthly return measures (total return and excess return).

### FRED Macro Series

The regime classifier uses three publicly available macro indicators from FRED, selected from an initial candidate set of seven. Series were chosen on three criteria: (1) data availability across the 2010-2018 backtest window, (2) effectively zero publication lag to support point-in-time use, and (3) each indicator captures a different dimension of macro risk.

**Selected:**
- **`VIXCLS`** — CBOE Volatility Index. Daily. Captures equity volatility and broad risk appetite.
- **`T10Y2Y`** — 10Y minus 2Y Treasury spread. Daily. Yield curve / growth-stress indicator.
- **`NFCI`** — Chicago Fed National Financial Conditions Index. Weekly. Composite of 105 financial-condition measures.

**Key item to note:**
- NFCI is a composite of 105 measures, and VIX is one of them. VIX gets equal weight to NFCI's broader basket because equity volatility is the single most direct read on credit risk appetite, and we want it weighted higher than NFCI's composite construction would give it.

**Considered and rejected:**
- **`BAMLH0A0HYM2`** (ICE BofA HY OAS) — FRED restricted to rolling 3-year window effective April 2026; 2010-2018 history unavailable.
- **`T10Y3M`** — no inversion event in 2010-2018; provides no regime variation in scope.
- **`DGS3MO`, `DGS10`** — yield-level series; add slow-moving context rather than regime signal.
- **`STLFSI4`** — highly correlated with NFCI; redundant when NFCI is included.
- **`GDPC1`** — quarterly cadence; frequency mismatch with monthly rebalance.

### Variable Map

- `Date` — Monthly label (first of each month). The row labeled `YYYY-MM-01` represents the **end-of-month-YYYY-MM** snapshot: risk metrics (`OAS`, `OASD`, `DTS`, `Yield_To_Worst`, `Years_To_Maturity`) reflect the month-end state, and return fields (`Total_Return_MTD`, `Excess_Return_MTD`) reflect the return realized **during that calendar month**. The label is a convention only — the data is fully available no earlier than the first business day of the following month. Validated in `inspection.ipynb` Section A.8.
- `Cusip` / `ISIN` — Bond-level identifiers. ISIN is redundant for US-only data.
- `Ticker` — Issuer-level identifier. Used for issuer concentration caps.
- `Class1` — Instrument type (Corporate, Government_Related).
- `Class2` — Issuer type (Industrial, Financial_Institutions, Utility, Agency).
- `Class3` — Sector. 19 unique values.
- `Eff_Rating_Group` — Letter rating bucket (AA through D_NR).
- `Index_Rating_Number` — Notch-level rating (3 = AA, 24 = default).
- `Maturity_Date` — **Corrupted (99.1% sentinel). Do not use.** Replaced by `Years_To_Maturity`.
- `Years_To_Maturity` — Years to maturity from observation date.
- `OAS` — Option-Adjusted Spread (bps). Core credit spread metric.
- `OAD` — Option-Adjusted Duration. Rate sensitivity.
- `OASD` — Option-Adjusted Spread Duration. Spread sensitivity.
- `DTS` — Duration Times Spread (`OASD × OAS`). Risk-budgeted spread exposure.
- `Yield_To_Worst` — Yield under worst-case call schedule.
- `Total_Return_MTD` — Monthly total return.
- `Excess_Return_MTD` — Return over duration-matched Treasury, **realized during the calendar month identified by the `Date` label** (see above). Confirmed by EDA cross-reference against external HY index returns at six anchor months (e.g., row dated `2011-08-01` shows -4.14% mean excess return, matching August 2011's HY selloff). **Backtest dependent variable; signal inputs at row T predict return at row T+1.**

### Data Quality Notes

The following ingestion rules are locked from EDA (`notebooks/inspection.ipynb`, Section A):

- **9 rows with null `OASD` / `DTS`** — dropped at ingestion (same 9 rows in both columns).
- **Fallen angels (`Eff_Rating_Group` ∈ {BBB, A, AA})** — 691 rows dropped. The panel is the US High Yield index; BBB-and-above bonds are residual mis-classifications.
- **No minimum-history filter.** Bonds enter the eligible universe from their first observation in the panel. A minimum-history requirement would create survivorship bias by systematically excluding bonds that defaulted or exited the index within a few months of issuance — exactly the population whose realized losses must hit the backtest for honest performance evaluation.
- **`D_NR` (defaulted / not rated)** — 1,450 rows dropped. Returns are dominated by recovery dynamics rather than carry signal.
- **`Class1 = Government_Related`** (8 rows) and **`Class2 = Agency`** (8 rows) — dropped. 
- **`Maturity_Date` sentinel** — 99.11% of rows hold `1/1/1900`; column not used. `Years_To_Maturity` substitutes (already noted in Variable Map).

**Outlier handling — no winsorization.** Extreme values in `OAS`, `DTS`, `Excess_Return_MTD`, and `Years_To_Maturity` are left as-is. Rationale: the inverse-DTS portfolio weighting (1 / `DTS`) structurally shrinks the position weight of extreme-spread bonds toward zero, so outlier ranks do not translate into outlier portfolio exposure. Statistical clipping is replaced by an explicit **stale-OAS detection** filter at the universe stage (see Failure Modes #1 and Roadmap).

**Universe-stage filters** (applied after ingestion, in portfolio construction):
- `OASD == 0` (2,300 rows) and `DTS == 0` (2,786 rows) — excluded from eligible universe (signal denominator and weighting denominator both undefined).
- Stale-OAS bonds — flagged via month-over-month `|ΔOAS| < 1 bp` (baseline rate 1.75% in panel); deferred to portfolio construction commit.

### Leakage Checks + Merge notes

**Point-in-time join rule.** Bond row labeled `T` represents the end-of-month-`T` snapshot (see Variable Map). The FRED join uses FRED data with date `≤ end_of_month(T)` — i.e., the FRED value contemporaneous with the bond snapshot's actual as-of date. For real-time-available data, both the bond row and the matched FRED value are knowable no earlier than the first business day of month `T+1`. The rule is demonstrated on three sample dates in `inspection.ipynb` Section C.

**Signal-to-return alignment.** Because row `T` contains both the end-of-`T` signal inputs and month-`T`'s realized return, the signal layer applies a **one-month lag**: ranking is computed from row `T`'s `OAS / OASD`, the position is held during month `T+1`, and the realized return is row `T+1`'s `Excess_Return_MTD`. This shift lives in `signal.py` and `evaluation/backtest.py`.

**Per-series lag at month-ends:**
- `VIXCLS`: median 0 days, max 3 days (daily series, holiday gaps only).
- `T10Y2Y`: median 0 days, max 3 days.
- `NFCI`: median 3 days, max 6 days (weekly series, last observation typically within a week).

**Walk-forward standardization.** The regime classifier's z-score normalization uses a trailing 60-month rolling window (mean and std computed only from data with index `< T`). FRED is pulled from 2000-01-01 to provide the warmup period; the 2000-2009 stretch is used exclusively for warmup and for fitting the regime label thresholds out-of-sample. Backtest evaluation runs 2010-2018.

**Date-convention validation.** EDA Section A.8 cross-references the panel's cross-sectional mean `Total_Return_MTD` at six anchor rows against externally-known ICE BofA US HY Master II Index monthly returns. All six rows match the *current-month* external return (e.g., row `2011-08-01` → -4.14% vs August 2011 HY index -4.0%), not the prior month. Within-bond OAS-change correlation (-0.30 contemporaneous vs +0.01 forward) corroborates that OAS and return at the same row track the same calendar month.

## Business Requirements 

### Business Objectives

- **Engineering-grade research infrastructure.** Produce a reproducible, production-minded pipeline that a systematic fixed income team could extend into a live process. Engineering quality (readability, structure, reproducibility, testing, robustness) is the primary evaluation criterion.
- **Defensible quantitative choices.** Define one systematic credit-risk or relative-value signal with clear economic intuition, framed in language portfolio managers can engage with.
- **Realistic portfolio prototype.** Convert the signal into a long-only portfolio governed by at least two explicit risk constraints (issuer, sector, rating bucket, or duration target).
- **Honest performance evaluation.** Backtest over a representative period, report at least two diagnostics covering drawdown, turnover, and exposure decomposition.
- **Production-awareness.** Document at least two failure modes and corresponding detection logic that would be needed if this pipeline ran in production.
- **PM-readable deliverables.** Produce a 2-page memo for portfolio managers covering what was built, why it makes sense, what can break, and what's next.

### Considered and Rejected

- **Alpha-maximization framing.** Considered building toward strongest possible Sharpe / IR. Rejected — the assignment explicitly prioritizes engineering quality and judgment over performance. Optimizing for backtest metrics would compromise architectural clarity and risk over-fitting.
- **Long/short portfolio.** Considered to demonstrate signal versatility. Rejected — the brief explicitly states "long-only preferred over long/short," and shorting in HY introduces operational complexity (borrow costs, locate availability) inconsistent with a clean prototype.
- **High-frequency rebalance (weekly or daily).** Considered for higher signal turnover. Rejected — provided data is monthly; weekly rebalance would force interpolation and introduce artifacts. Monthly cadence matches data frequency.
- **Multiple competing signals.** Considered building a multi-factor model. Rejected — the brief specifies "one systematic signal." Scope discipline prioritized over breadth.

## Functional Requirements 

### Functional Capabilities

The system must perform the following functions:

- **Ingest the provided bond panel** from CSV, validate schema, handle known data quality issues (corrupted Maturity_Date, missing DTS/OASD, negative OAS, extreme outliers), and emit a cleaned panel.
- **Load FRED macro indicators** (`VIXCLS`, `T10Y2Y`, `NFCI`) from the committed parquet cache (`raw_data/fred_cache.parquet`). The default pipeline run requires no network or API credentials. An optional download utility (`scripts/fred_download.py`) rebuilds the cache from the FRED API.
- **Merge bond and macro data point-in-time.** Align FRED data to monthly bond observation dates using only information available as of the rebalance date. Run explicit leakage checks.
- **Classify monthly regime** as risk-on, neutral, or risk-off based on rule-based thresholds across VIX, T10Y2Y, and NFCI.
- **Compute the credit signal** at the bond level on each rebalance date. Rank bonds within the eligible universe.
- **Construct the portfolio** subject to at least two explicit constraints (issuer cap, sector cap, rating bucket). Scale exposure based on regime classification.
- **Run the backtest** as a monthly-rebalance loop over the 2010-2018 window. Compute portfolio excess returns using `Excess_Return_MTD` as the dependent variable.
- **Compute diagnostics:** drawdown, turnover, and exposure decomposition (sector and rating).
- **Log all runs** with structured records of data loaded, rows processed, missing data handled, and outputs generated. Logs persist to `logs/`.
- **Produce outputs** to `outputs/` — charts as PNG, tabular results as CSV.
- **Execute end-to-end from a single command.** No manual intervention required between data ingestion and output generation.

### Considered and Rejected

- **HMM-based regime classifier.** Considered for sophistication. Rejected — opaque to PMs, requires significant tuning, and scope-creep risk for a 1-week build. Rule-based threshold classifier is transparent, auditable, and sufficient.
- **Machine-learning signal (XGBoost on features).** Considered for predictive power. Rejected — the brief asks for a signal with economic intuition. Black-box models are harder to defend to a PM and don't match the engineering-quality focus.
- **Issuer-cap enforcement at the Cusip level.** Considered but rejected — Cusip is bond-level; issuer concentration must be enforced at the Ticker level to prevent multi-bond exposure to the same company.
- **Total return as backtest dependent variable.** Considered. Rejected — total return contaminates the credit signal with rate exposure. `Excess_Return_MTD` isolates the credit return that the signal predicts.


## Technical Requirements

### Architecture

The system is organized into five functional layers with strict module boundaries:

1. **Data layer** (`src/data/`) — ingestion, validation, merging.
2. **Feature layer** (`src/features/`) — signal computation.
3. **Regime layer** (`src/regime/`) — macro-regime classification.
4. **Portfolio layer** (`src/portfolio/`) — constraint-aware portfolio construction.
5. **Evaluation layer** (`src/evaluation/`) — backtest engine and diagnostics.

Each layer is importable as a package. All parameters live in `config/config.yaml`. Logging is shared via `src/utils/logging_config.py`. The pipeline is orchestrated by a single entry point and runs end-to-end with one command.

### Module Specifications

- `src/data/ingest_bonds.py` — Load bond CSV from `config.data.bond_csv`, parse dates, shift to end-of-month convention (per A.8), apply locked ingestion drops (null OASD/DTS, fallen angels, D_NR, Government_Related, Agency).
- `src/data/ingest_fred.py` — Pure cache loader. Loads FRED series from `raw_data/fred_cache.parquet`. Fails with a clear error if the cache file is missing.
- `scripts/fred_download.py` — Optional utility for rebuilding the FRED parquet cache from API. Not part of the runtime pipeline. Requires `fred.api_key` configured in `config.yaml`. Fails loudly with a directive error if the key is missing.
- `src/data/merge.py` — Align FRED series to monthly bond dates with explicit point-in-time controls. Aggregate daily/weekly FRED to monthly using last-known value before bond date.
- `src/data/validate.py` — Schema checks, range checks, missing-value reporting, leakage assertions.
- `src/features/signal.py` — Compute carry signal (OAS/OASD) and rank within universe per date.
- `src/regime/classifier.py` — Apply rule-based thresholds across VIX, T10Y2Y, NFCI to produce monthly regime label.
- `src/portfolio/construction.py` — Apply constraints (issuer, sector, rating), produce position weights, scale by regime.
- `src/evaluation/backtest.py` — Monthly-rebalance loop, portfolio return computation, holdings tracking.
- `src/evaluation/diagnostics.py` — Drawdown, turnover, sector/rating exposure decomposition. Output charts and CSVs.
- `src/utils/logging_config.py` — Centralized logger configuration; file and console handlers.

### Technology Stack

- **Language:** Python 3.11+.
- **Core libraries:** `pandas`, `numpy`, `pyarrow` (parquet), `pyyaml` (config), `matplotlib` (charts).
- **Data access:** `fredapi` for FRED ingestion.
- **Testing:** `pytest` with assertion-based unit tests.
- **Logging:** Python standard library `logging`.
- **Storage:** CSV for provided bond data (per assignment), parquet for cached macro data and intermediate state.

### Considered and Rejected

- **Cached FRED storage in CSV.** Considered for simplicity. Rejected in favor of parquet — preserves dtypes (no date re-parsing), compresses better, faster repeat reads. Demonstrates the brief's "performance hygiene" requirement.
- **Jupyter notebook as core logic.** Considered for transparency. Rejected — the brief states "core logic should be importable as modules." Notebooks are reserved for EDA (`notebooks/inspection.ipynb`).
- **Single-script implementation.** Considered for simplicity. Rejected — fails the "clear structure: separate modules" requirement of the brief.
- **Monolithic ingestion + cleaning in one file.** Considered for simplicity. Rejected — separating bond ingestion, FRED ingestion, merge, and validation isolates failure surfaces and improves testability.
- **Equal-weighted portfolio construction.** Considered for simplicity. Rejected in favor of DTS-aware weighting that controls per-bond risk contribution.
- **Live FRED API at runtime (no committed cache).** Considered for always-fresh data. Rejected — introduces network dependency at evaluation time, requires API key configuration, and exposes the pipeline to FRED rate limits, revisions, and downtime. Historical FRED data is publication-stable for 2010-2018. Committed parquet cache preserves reproducibility from the repository alone. A standalone download script (`scripts/fred_download.py`) is provided for cache rebuild but is **not part of the runtime path**.

## Design Decisions

### Signal Choice

**Signal:** Regime-aware spread carry. Rank bonds by **OAS / OASD** within the eligible universe each rebalance date. Long the **top 20% (primary)**, **inverse-DTS weighted** (each bond's weight is proportional to 1/DTS, so each bond contributes approximately equal risk to the portfolio). Position size scaled by the regime classifier (see § Regime Classifier). The backtest additionally reports the **top 10% and top 30% cutoffs** as sensitivity variants — same signal, same regime classifier, same constraints — to verify the strategy isn't a knife-edge at the 20% choice. The 20% case is the headline, consistent with carry-strategy literature; 10/30 are reported for transparency, not selection.

**Construction:**
- **Numerator (OAS):** Option-Adjusted Spread in basis points. The clean credit spread over duration-matched Treasury, after stripping embedded optionality.
- **Denominator (OASD):** Option-Adjusted Spread Duration. The bond's price sensitivity to credit spread movements.
- **Ratio interpretation:** Basis points of spread compensation per year of spread duration. Higher ratio = better-compensated per unit of credit risk taken.

**Economic intuition:**

This is a relative-value signal, not a directional credit bet. The ratio asks a single question: "Forget absolute spread and absolute risk — for a standardized unit of spread risk, which bonds are paying me the most?"

Two economic mechanisms support the signal:
- **Risk premia.** Bonds over-compensating investors per unit of risk earn higher excess returns on average over time.
- **Local mispricing persistence.** HY liquidity is uneven; information takes time to reflect in prices. Carry differentials between bonds persist for weeks or months — long enough for a monthly-rebalanced portfolio to capture the differential before reversion.

The signal is well-documented in the literature (Houweling-Van Zundert 2017, Israel-Palhares-Richardson 2018) on monthly HY data with statistically significant alpha after controlling for rating, duration, and sector.

**Why this signal is "regime-aware":**

A pure carry signal systematically loads on credit risk, the bonds it picks are the bonds most exposed to credit stress. Carry strategies in HY have negative skew: accumulating small monthly gains and occasionally taking large drawdowns when credit conditions deteriorate.

The regime overlay does not change which bonds the signal picks. It changes **how much capital is deployed** based on the macro environment. Full position in risk-on regimes; reduced position in risk-off. This converts the signal from a static long-credit bet into a stress-aware credit strategy.

**Considered and rejected:**

- **Rank by OAS alone.** Rejected — picks for highest absolute spread, which loads systematically on CCC, distressed, and long-duration bonds. A directional credit-risk bet, not a relative-value signal.
- **Rank by OASD alone.** Rejected — picks for highest spread-duration, which loads systematically on long-dated, high-quality bonds with low call optionality. A leveraged bet on credit spreads tightening, not a relative-value signal.
- **Rank by OAS / DTS.** Mathematically degenerate. Since `DTS = OASD × OAS`, the ratio `OAS / DTS = OAS / (OASD × OAS) = 1 / OASD`. The OAS information cancels out, leaving an inverse-spread-duration ranking that biases toward short-duration bonds with no credit-quality consideration.
- **Rank by OAS / OAD.** Rejected — OAD is rate duration, not spread duration. Dividing a credit-risk numerator (spread) by a rate-risk denominator (OAD) mixes two distinct risk dimensions. The resulting ratio has no clean financial interpretation.
- **Multi-factor signal** (carry + momentum + quality). Rejected — brief specifies "one systematic signal." Scope discipline prioritized.
- **Machine-learning signal.** Rejected — see FRD § Considered and Rejected. Black-box models lack the economic interpretability a PM needs.

### Regime Classifier

**Purpose:** Convert monthly macro indicators into a single regime label that scales total deployed capital. The classifier does not change which bonds the signal picks — it changes how much portfolio-level exposure is deployed.

**Inputs:** VIX (`VIXCLS`), 10Y-2Y Treasury spread (`T10Y2Y`), and Chicago Fed NFCI (`NFCI`). See § Data → FRED Macro Series for selection rationale.

**Regime states:** Three discrete labels — `risk_on`, `neutral`, `risk_off`. Three states (rather than two or five) balance hierarchical clarity against over-fitting: binary regimes create whiplash at the threshold; five regimes force unnecessarily fine-grained allocation decisions the data cannot support.

**Combination method (locked):** Walk-forward composite z-score with rolling window, monthly cadence. All parameters live in `config.regime` — window length, min_periods, fit window, fit quantiles, per-indicator sign flip, and allocation. The classifier computes thresholds at runtime from the pre-backtest slice, so any config change re-derives them automatically (no hardcoded values).

For each rebalance date `T` (first of month), the classifier:
1. Resamples each FRED series in `config.regime.indicators` to monthly cadence (last available value per month).
2. Computes the mean and standard deviation of each series over the trailing `config.regime.window_months` ending at `T-1` (strictly past-looking; `min_periods` per config).
3. Z-scores the current month's value against those trailing stats.
4. Sign-flips per indicator entry (`stress_low` negates the series so all three z-scores move in the stress direction).
5. Averages the three z-scores → composite stress score.
6. Applies thresholds derived at construction time from the composite values in `[config.regime.threshold_fit_start, config.regime.threshold_fit_end]` at the percentiles in `config.regime.threshold_quantiles`. Composite below the lower threshold → `risk_on`; above the upper → `risk_off`; otherwise `neutral`.

Fitting on the pre-backtest slice makes the thresholds out-of-sample for the 2010-2018 backtest. On the current configuration the runtime values resolve to approximately **−0.548 / +0.249**, but the values adapt automatically to any change in pull window, z-score window, fit-window endpoints, or fit quantiles.

**Resulting regime frequency on backtest (2010-2018):** ~47% neutral, ~27% risk_off, ~26% risk_on. Materially better resolution than vote-based (~61% neutral).

**Considered and rejected:**
- **Vote-based** with fixed percentile thresholds — 61% neutral in backtest, insufficient regime variation to drive portfolio scaling decisions.
- **Full-sample z-score** — standardizes against 2010-2018 mean/std, which uses post-rebalance data and introduces look-ahead. Retained in the EDA notebook (B.6) as a visualization reference only; not used in production.
- **HMM-based regime classification.** Rejected — see FRD § Considered and Rejected. Hidden-state inference is harder to defend to a PM than transparent classification methods and adds scope for a 1-week build.
- **Binary regime (risk-on / risk-off only).** Rejected — creates whiplash at the threshold and forces hard switches that don't match the gradual nature of credit-condition deterioration.
- **Five-state regime.** Rejected — marginal allocation differences between adjacent states become arbitrary and over-fit; three states capture bull/neutral/bear with enough resolution to matter.
- **Bond-level regime application (filter or re-rank bonds based on regime).** Rejected — regime measures systematic risk, which affects the entire market. The right response is portfolio-level position sizing, not bond-level filtering. Keeps the signal layer and regime layer cleanly separable.
- **STLFSI4 alongside NFCI.** Rejected — see § Data → FRED Macro Series. Redundant with NFCI.

### Portfolio Construction

**Strategy:** Long-only portfolio of US High Yield bonds, monthly rebalance. Holdings are determined by the carry signal (see § Signal Choice), weighted within the long quintile, and scaled at the portfolio level by the regime classifier (see § Regime Classifier).

**Universe Definition.** Before signal ranking, the eligible universe is filtered by:
- Required fields present on rebalance date: `OAS`, `OASD`, `DTS`, `Years_To_Maturity`, `Eff_Rating_Group`, `Excess_Return_MTD`
- `OASD > 0` and `DTS > 0` (signal denominator and weighting denominator must be non-zero)
- Drops applied at ingestion (see Data Quality Notes): fallen angels, D_NR, Government_Related / Agency, null-field rows

**Selection:** Rank eligible bonds by `OAS / OASD` on each rebalance date. The primary case longs the top 20%; the backtest also runs top 10% and top 30% as sensitivity variants. All three use identical regime, weighting, and constraint logic — only the universe cutoff changes.

**Weighting:** Within the long quintile, weight each bond proportional to `1 / DTS` so each position contributes approximately equal risk to the portfolio. Weights normalize to sum to 1 within the quintile before regime scaling.

**Constraints:**
- **Issuer cap** — Maximum **portfolio weight per issuer** (enforced via `Ticker`). Anchored to the 90th percentile of bonds-per-issuer-per-month in the panel (≈ 4 bonds), expressed as a portfolio weight cap. Specific weight value to be locked alongside the long-quintile size in the portfolio construction commit.
- **Sector cap** — Maximum **20% portfolio weight per sector** (enforced via `Class3`). Set above the 18% mean for Consumer_Cyclical so it binds only during sector-concentration events (e.g., Energy 2015-16).
- **Rating bucket exposure** — No explicit CCC max or BB min constraint. Fallen angels (BBB and above) are already excluded at ingestion; the eligible universe is B / BB / CCC only. The signal naturally tilts toward CCC under risk-on; the regime classifier handles aggregate risk-taking through position-scaling, not bucket-level filtering.

**Constraint Enforcement Order:**
1. Apply universe filter.
2. Compute signal and select top quintile.
3. Apply inverse-DTS weighting within the quintile.
4. Enforce constraints in priority order: issuer cap → sector cap → rating bucket. Where a constraint is violated, trim the lowest-signal bonds within the violating category until the constraint is satisfied. Redistribute trimmed weight proportionally across remaining eligible bonds.
5. Apply regime scaling to total deployed capital.

**Rebalance Logic:**
- **Frequency:** Monthly.
- **Timing:** A rebalance for month `T+1` uses bond row `T` (end-of-month-`T` snapshot — see Variable Map and Leakage Checks + Merge notes) and FRED data with date `≤ end_of_month(T)`. Signal inputs `OAS_T` / `OASD_T` produce the ranking; positions are held during month `T+1`; realized return is row `T+1`'s `Excess_Return_MTD`. Both the bond row and the matched FRED value become knowable on the first business day of month `T+1`.
- **Cash handling:** Capital not deployed in the long quintile (under neutral or risk-off regimes) is treated as held in a Treasury-bill proxy. The proxy's return is the duration-matched short-Treasury yield from the FRED series, applied to the un-deployed capital share.

**Considered and rejected:**

- **Equal-weighted within quintile.** Rejected — see TRD § Considered and Rejected. Inverse-DTS weighting equalizes per-bond risk contribution; equal weighting lets high-DTS bonds dominate portfolio risk.
- **Market-cap weighting.** Rejected — would tilt the portfolio toward larger issuers regardless of signal strength. The signal's purpose is to identify mispriced bonds, not to track issuer size.
- **Issuer cap at Cusip level.** Rejected — see FRD § Considered and Rejected. Multi-bond issuers would defeat the concentration limit.
- **Sector cap using Class2 (issuer type).** Rejected — Class2 distinguishes Industrial / Financial / Utility, which is too coarse to control sector concentration meaningfully. Class3 (19 sectors) provides actionable granularity.
- **Long/short construction.** Rejected — see BRD § Considered and Rejected.
- **Multi-period optimization.** Rejected — adds scope for marginal benefit in a 1-week build. Single-period rebalance is the standard for carry strategies and easier to defend.
- **Cash held at zero return.** Rejected — understates realistic cash performance; the duration-matched T-bill proxy more accurately reflects what an un-deployed capital share would earn in practice.

### Failure Modes + Detection

The pipeline is designed for monthly backtest evaluation. If extended to production, three failure modes are most likely to materialize. Each is paired with a concrete detection mechanism.

**1. Stale OAS / matrix-priced bonds.**

*What it is:* HY bonds trade infrequently. Bonds that haven't transacted in weeks are matrix-priced — their OAS is interpolated from comparable bonds rather than from real trades. When the underlying market moves, the matrix-priced OAS lags reality. The signal continues ranking the bond as if its OAS reflects current conditions, when it actually reflects a stale picture.

*How it manifests:* Bonds with stale OAS may rank artificially high (carry looks attractive) or low (carry looks unattractive) relative to their true market state. Portfolio holdings become anchored to stale prices.

*Detection:* Flag bonds whose `OAS` has not changed by more than 1 bp month-over-month. Baseline rate measured in EDA: **1.75% of bond-months** meet this threshold in the 2010-2018 panel. In production, monitor the share of stale-OAS observations per month — a spike above ~5% indicates the matrix-pricing source has degraded and the signal's reliability needs review.

**2. Survivorship and delisting attribution failure.**

*What it is:* Bonds exit the panel for multiple reasons — maturity, call, default, rating-migration out of HY. If the pipeline silently drops bonds with missing data on a rebalance date, defaulted bonds (which often appear with extreme negative returns or missing fields) get excluded from the portfolio return calculation. This systematically overstates backtest performance.

*How it manifests:* Backtest results look better than reality. The cumulative return curve does not reflect the full losses from bond defaults during the period.

*Detection:* Maintain a ledger of bond exits indexed by Cusip and exit date. For each exit, attribute the reason (call, default, maturity, rating migration). Assert that every bond's final return is captured in the portfolio return for the month in which it exited. Audit the count of exits per month against external HY default-rate data as a sanity check.

**3. Regime classifier drift.**

*What it is:* The regime classifier is calibrated on 2010-2018 indicator behavior. If macro indicators behave differently in production — e.g., VIX persistently elevated, NFCI stuck in one state — the classifier produces unhelpful regime labels. The position scaling becomes unreliable and may either over-expose during stress or under-expose during recovery.

*How it manifests:* Regime labels stop varying meaningfully. Allocation scaling produces unintended exposure relative to the macro environment.

*Detection:* Monitor the distribution of regime labels over rolling 12-month windows. If a single regime exceeds 80% of the window, flag the classifier for recalibration. Cross-check regime labels against independent stress measures (credit spreads outside the backtest window, equity drawdowns) to confirm the classifier's directional consistency.

**4. Date-convention mis-implementation.**

*What it is:* The bond panel uses first-of-month labels but represents end-of-that-month snapshots. A naive reading of the `Date` column will produce a 1-month leakage (signal computed from contemporaneous data predicting the same month's return).

*How it manifests:* Backtest performance looks artificially strong with no obvious symptom. Drawdowns may even appear smoother because the signal "predicts" returns it has already observed.

*Detection:* Periodically run the date-convention sanity test (`inspection.ipynb` Section A.8) against an external HY index benchmark. If the cross-sectional mean of `Excess_Return_MTD` at row `T` diverges from the labeled month's external return by more than ~1%, investigate either a data-vendor convention change or a merge-layer regression.


## Assumptions

The pipeline relies on the following explicit assumptions. A reviewer can audit pipeline behavior against this list.

**Data:**
- The `Date` column is a label, not the snapshot date. A row dated `3/1/2015` reflects the **end-of-March 2015** snapshot: OAS / OASD / DTS at month-end and `Excess_Return_MTD` realized during March. Validated in `inspection.ipynb` Section A.8 against external HY index returns at six anchor months. The data is realistically available only on the first business day of April 2015 (row publication trails the label by approximately one month).
- `Maturity_Date` is corrupted (99.1% sentinel `1/1/1900`) and is not used. `Years_To_Maturity` substitutes.
- `DTS` is precomputed in the source data as `OASD × OAS`. The pipeline uses it directly rather than recomputing.
- `Excess_Return_MTD` is the dependent variable for backtest performance.
- The bond panel is monthly and complete — no missing months between January 2010 and December 2018.

**Identifiers:**
- `Class3` represents sector for portfolio constraint purposes. `Class1` and `Class2` represent instrument type and issuer type respectively and are not used for sector caps.
- `Ticker` represents issuer for concentration cap purposes. `Cusip` and `ISIN` are bond-level identifiers and are not used for issuer enforcement.

**FRED data:**
- VIXCLS, T10Y2Y, and NFCI are stable and available via FRED across the 2010-2018 backtest window.
- ICE BofA HY OAS series (BAMLH0A0HYM2) is unavailable via FRED for the 2010-2018 window due to the April 2026 licensing restriction on rolling 3-year history.
- FRED data revisions during the backtest window are negligible for the selected series. Values pulled at runtime match the values that would have been available point-in-time.
- FRED parquet cache (`raw_data/fred_cache.parquet`) is committed to the repository for reproducibility. Cache values were pulled from FRED on **2026-05-12**. The runtime pipeline does not refresh the cache.

**Portfolio:**
- Long-only construction. No shorting is permitted.
- Monthly rebalance frequency matches data frequency. No intra-month decisions.
- Capital not deployed under neutral or risk-off regimes is held in a Treasury-bill proxy, not at zero return.
- Transaction costs are not modeled in the backtest. A production deployment would need to incorporate realistic bid-ask spreads (30-100 bps in HY) and market impact.

**Universe and data quality (locked from EDA):**
- Fallen angels (BBB / A / AA) — **excluded from eligible universe** (dropped at ingestion).
- `D_NR` — **excluded from eligible universe** (dropped at ingestion).
- `Class1 = Government_Related` / `Class2 = Agency` — **excluded from eligible universe** (dropped at ingestion).
- Negative `OAS` values and extreme outliers — **not winsorized**; controlled structurally via inverse-DTS portfolio weighting and stale-OAS detection at the universe stage.
- Near-maturity threshold — **not applied as a separate rule**; the `OASD > 0` universe filter covers the relevant edge cases (a bond approaching maturity has its spread duration collapse toward zero and is naturally excluded).
- No minimum-history filter — applying one would introduce survivorship bias by excluding bonds that defaulted or exited shortly after issuance.

**Backtest validation posture:**
- The carry signal (`OAS / OASD`) and inverse-DTS weighting are closed-form rules with **no fitted parameters** — there is nothing to overfit, and no formal in-sample / out-of-sample backtest split is required. Universe filters and rating exclusions are definitional, not learned.
- The regime classifier's z-score thresholds are fit on **pre-2010 walk-forward composites** — out-of-sample for the 2010-2018 backtest.
- The two constraint values that are in-sample design choices — sector cap (20%) and issuer cap (anchored to the 90th-percentile concentration) — are coarse heuristics chosen from full-panel distributions, not tuned hyperparameters.
- Robustness is reported via (a) the quintile-size sensitivity variants (10% / 20% / 30%) described in § Signal Choice and § Portfolio Construction, (b) rolling 12-month performance windows in diagnostics, and (c) sub-period decomposition across 2010-2012 / 2013-2015 / 2016-2018.

## Config

All pipeline parameters live in `config/config.yaml`. The top-level structure:

- `dates` — Backtest start, end, rebalance frequency
- `signal` — Quintile cutoff, weighting scheme
- `regime` — Combination method, allocation scaling (100/66/33), threshold-fit rule (quantiles + fit window endpoints)
- `portfolio` — Constraint values (issuer cap, sector cap, rating bucket limits)
- `data` — Universe filters (fallen angels, OAS handling, maturity threshold)
- `fred` — API key (optional, used only by `fred_download.py`)
- `logging` — Log level, log file path

The `fred.api_key` field is intentionally blank in the committed config. The runtime pipeline does not require this field. It is read only by `scripts/fred_download.py` when rebuilding the FRED cache.

## Limitations + Roadmap

### Known Limitations

[Honest acknowledgment of pipeline limitations.]

### Roadmap

Given more time or production scope, the following extensions would meaningfully strengthen the pipeline. Each was scoped out of the initial build to maintain delivery discipline.

1. **Return-attribution validation.** Cross-reference our cross-sectional mean `Excess_Return_MTD` per bond date against an external HY index excess-return benchmark (e.g., ICE BofA US HY Master II) to confirm the date convention at scale. EDA confirmed the labeled-month convention on three anchor months; a full-window comparison would harden the assumption.

2. **FRED publication-lag monitoring.** Track the join lag distribution per series over time. The pipeline's PIT join uses the strict-before rule with no enforced maximum lag; in production, a per-series lag SLA (e.g., NFCI lag must be ≤ 7 days) would surface FRED publication outages before they contaminate regime labels.

3. **Survivorship audit.** EDA found ~44 bond exits per month. Implement an explicit exit ledger that attributes each Cusip exit to a reason code (call, default, maturity, rating-migration out) and reconciles total exits against external HY default-rate data as a sanity check.

4. **Stale-OAS production filter.** EDA's stale-OAS probe (1.75% baseline rate) is currently a detection mechanism only. Promote it to an active universe filter: exclude bonds with `|ΔOAS| < 1 bp` for N consecutive months from the eligible universe at the rebalance, on the grounds that their OAS is matrix-priced and signal-contaminating.

5. **Top-quintile composition stability tracking.** EDA measured 87% retention month-over-month in the top OAS/OASD quintile (~13% monthly turnover). In production, monitor this metric in real time — a sudden drop in retention would indicate either a regime shift in the carry signal's bond selection or a data-quality break.

## Dependencies

[Reference to requirements.txt and any external data dependencies.]