"""
Market Funding Rate product specification.

Covers cross-exchange funding rate data across three tables:
- coinglass.market_funding_rate: high-frequency raw rates (Dataform-managed)
- funding_rate_pairs.pair_timeseries: 90D history with OI, 8h-equivalent FR
- funding_rate_pairs.funding_rate_pairs_analysis: pre-computed OI-weighted
  cross-pair differentials (7d / 30d / 90d windows)
"""

from . import ProductSpec, TableSpec


_CONTEXT = """\
# Market Funding Rate Data Catalog

## Overview

Three tables cover market-wide perpetual funding rates across exchanges.
They are complementary but NOT directly joinable — they use different key
formats and different `funding_rate` normalizations.

| Table (short name) | Purpose | FR unit | Key format |
|---|---|---|---|
| `market_funding_rate` | Current/recent rates, all tracked pairs | per-settlement-period | `exchange` + `trading_pair_symbol` |
| `pair_timeseries` | 90D history snapshots + OI per pair | 8h-equivalent | `pair_key` = `exchange:symbol` |
| `funding_rate_pairs_analysis` | Pre-computed snapshots of OI-weighted avg + cross-pair diff | 8h-equivalent | `exchange_a/b` + `symbol_a/b` |

## CRITICAL: funding_rate Normalization Differs Between Tables

**`market_funding_rate`**:
- `funding_rate` = raw rate per settlement period (e.g., 0.0001 = 0.01% per 8h on Binance)
- `normalized_funding_rate = funding_rate / funding_rate_interval` = per-hour rate
- Use `normalized_funding_rate` for cross-exchange comparison in this table.

**`pair_timeseries` and `funding_rate_pairs_analysis`**:
- `funding_rate` = **8-hour equivalent** (all sources normalized to Binance's 8h interval).
- Annualized rate ≈ `funding_rate × 3 × 365` (3 settlements per day at 8h interval).

**Never mix `funding_rate` from `market_funding_rate` with `funding_rate` from
`pair_timeseries` in the same calculation — they are in different units.**

## Exchange Name Casing: Always Use LOWER() for Filtering

Exchange names are not consistently cased across tables. **Always apply `LOWER()`
when filtering by exchange name** to avoid silent mismatches.
"""


# ── Per-table catalogs ───────────────────────────────────────────────

_MARKET_FUNDING_RATE = """\
## `pendle-data.coinglass.market_funding_rate`

High-frequency funding rate time series. Covers all pairs tracked by Coinglass
plus all Hyperliquid pairs.

- Partition: `dt` (TIMESTAMP) — always filter on `dt`.
- Unique key: `(exchange, trading_pair_symbol, dt)`.

### Fields

- `exchange`: exchange name (e.g., `'Binance'`, `'Bybit'`, `'Hyperliquid'`, `'Gate'`)
- `trading_pair_symbol`: composite key `'{exchange}-{raw_symbol}'` (e.g., `'Binance-BTCUSDT'`)
- `trading_pair_symbol_raw`: symbol as used on the exchange (e.g., `'BTCUSDT'`)
- `funding_rate_interval`: settlement interval in hours (Binance=8, Hyperliquid=1, etc.)
- `dt`: settlement timestamp (TIMESTAMP)
- `funding_rate`: raw rate per settlement period
- `normalized_funding_rate`: per-hour rate = `funding_rate / funding_rate_interval`

### Use For
- Latest / recent funding rates for a specific pair
- High-frequency analysis within a short window
- Checking current rate vs historical level

### Example
```sql
-- Latest funding rate for BTC across exchanges (normalized to per-hour for comparison)
SELECT exchange, trading_pair_symbol_raw, dt,
  funding_rate,
  normalized_funding_rate,
  normalized_funding_rate * 8 AS rate_8h_equiv
FROM `pendle-data.coinglass.market_funding_rate`
WHERE dt >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
  AND trading_pair_symbol_raw = 'BTCUSDT'
ORDER BY dt DESC, exchange
```
"""

_PAIR_TIMESERIES = """\
## `pendle-data.funding_rate_pairs.pair_timeseries`

90-day rolling history per pair, including open interest. Broader market coverage
than `market_funding_rate` (includes Stage 1 candidate pairs from OI screening).

- Partition: `date` (DATE) — always filter on `date`.
- Key: `pair_key` = `'{exchange}:{symbol}'` (colon separator).

### Fields

- `pair_key`: `'{exchange}:{symbol}'` (e.g., `'Binance:BTCUSDT'`, `'Hyperliquid:BTC'`)
- `base_asset`: underlying asset (e.g., `'BTC'`, `'ETH'`)
- `timestamp`: unix seconds
- `funding_rate`: **8h-equivalent rate** (see normalization section above)
- `open_interest_usd`: open interest in USD at that timestamp
- `date`: partition key (the date this snapshot was fetched, = today's date)

### Use For
- OI-weighted funding rate calculations
- Comparing FR across exchanges for the same asset with OI context
- Longer historical windows (up to 90D)

### Example
```sql
-- OI-weighted average funding rate for BTC pairs over last 30 days
-- funding_rate is already 8h-equivalent; annualized = *3*365
SELECT
  pair_key,
  SUM(funding_rate * open_interest_usd) / NULLIF(SUM(open_interest_usd), 0)
    AS oi_weighted_avg_fr_8h,
  SUM(funding_rate * open_interest_usd) / NULLIF(SUM(open_interest_usd), 0) * 3 * 365
    AS oi_weighted_avg_fr_annualized,
  AVG(open_interest_usd) AS avg_oi_usd
FROM `pendle-data.funding_rate_pairs.pair_timeseries`
WHERE date = (SELECT MAX(date) FROM `pendle-data.funding_rate_pairs.pair_timeseries`)
  AND base_asset = 'BTC'
  AND TIMESTAMP_SECONDS(timestamp) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY pair_key
ORDER BY oi_weighted_avg_fr_8h DESC
```
"""

_PAIRS_ANALYSIS = """\
## `pendle-data.funding_rate_pairs.funding_rate_pairs_analysis`

Pre-computed OI-weighted average funding rates and cross-pair differentials.
Updated daily. Top 100 pairs per asset per time window.

- Partition: `date` (DATE) — always filter on `date`.
- Key: `(base_asset, exchange_a, symbol_a, exchange_b, symbol_b, lookback_days)`.
- `lookback_days` values: `7`, `30`, `90`.

### Fields

- `base_asset`: underlying asset (e.g., `'BTC'`)
- `exchange_a`, `symbol_a`: first pair in the comparison
- `exchange_b`, `symbol_b`: second pair in the comparison
- `avg_fr_a`, `avg_fr_b`: OI-weighted average FR (8h-equivalent) for each pair
- `avg_oi_a`, `avg_oi_b`: average open interest in USD for each pair
- `fr_diff`: `abs(avg_fr_a - avg_fr_b)` — funding rate spread between the two pairs
- `fp_diff`: `fr_diff × min(avg_oi_a, avg_oi_b)` — estimated funding payment differential in USD
- `lookback_days`: time window used (`7`, `30`, or `90`)
- `date`: analysis run date

### Use For
- Quickly identifying pairs with the largest funding rate spread for an asset
- Finding arbitrage or hedging opportunities between exchanges
- Ranking markets by funding payment differential (= economic significance of the spread)

### Example
```sql
-- Top 10 BTC pairs by funding rate spread (30-day window, latest analysis)
SELECT
  exchange_a, symbol_a, exchange_b, symbol_b,
  ROUND(avg_fr_a * 3 * 365 * 100, 4) AS apr_a_pct,
  ROUND(avg_fr_b * 3 * 365 * 100, 4) AS apr_b_pct,
  ROUND(fr_diff * 3 * 365 * 100, 4)  AS spread_apr_pct,
  ROUND(fp_diff, 0)                   AS funding_payment_diff_usd
FROM `pendle-data.funding_rate_pairs.funding_rate_pairs_analysis`
WHERE date = (SELECT MAX(date) FROM `pendle-data.funding_rate_pairs.funding_rate_pairs_analysis`)
  AND base_asset = 'BTC'
  AND lookback_days = 30
ORDER BY fp_diff DESC
LIMIT 10
```
"""


SPEC = ProductSpec(
    product_id="market_funding_rate",
    display_name="Market Funding Rate",
    tables=(
        # ── Raw high-frequency funding rates ───────────────────────────
        TableSpec(
            "pendle-data.coinglass.market_funding_rate",
            partition_col="dt",
            description=(
                "High-frequency funding rate time series (all Coinglass + Hyperliquid pairs).\n"
                "Key fields: exchange, trading_pair_symbol, funding_rate (per-settlement-period), "
                "normalized_funding_rate (per-hour).\n"
                "→ Use for: latest/recent rates, high-frequency analysis, current vs historical."
            ),
            catalog=_MARKET_FUNDING_RATE,
        ),
        # ── 90D history with OI ────────────────────────────────────────
        TableSpec(
            "pendle-data.funding_rate_pairs.pair_timeseries",
            partition_col="date",
            description=(
                "90-day rolling history per pair with OI. FR is 8h-equivalent.\n"
                "Key fields: pair_key (exchange:symbol), funding_rate, open_interest_usd.\n"
                "→ Use for: OI-weighted FR calculations, cross-exchange comparison with OI context."
            ),
            catalog=_PAIR_TIMESERIES,
        ),
        # ── Pre-computed cross-pair analysis ───────────────────────────
        TableSpec(
            "pendle-data.funding_rate_pairs.funding_rate_pairs_analysis",
            partition_col="date",
            description=(
                "Pre-computed OI-weighted avg FR and cross-pair differentials (7d/30d/90d).\n"
                "Key fields: exchange_a/b, symbol_a/b, avg_fr_a/b, fr_diff, fp_diff.\n"
                "→ Use for: finding largest FR spreads, arbitrage opportunities, pair ranking."
            ),
            catalog=_PAIRS_ANALYSIS,
        ),
        # ── Add new funding rate tables here ───────────────────────────
    ),
    context=_CONTEXT,
    tool_description=(
        "Returns the Market Funding Rate catalog INDEX: normalization rules "
        "(CRITICAL — funding_rate units differ between tables), exchange name "
        "casing warnings, and table summaries.\n\n"
        "CALL THIS FIRST before querying any funding rate table. "
        "Then call get_table_detail(table_name) for full column definitions."
    ),
    register_extra_tools=None,
)
