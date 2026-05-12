"""
Market Funding Rate product specification.

Covers cross-instrument "premium over spot" data:
- coinglass.market_funding_rate: high-frequency raw perp funding rates (Dataform-managed)
- funding_rate_pairs.pair_timeseries: 90D history with OI, 8h-equivalent perp FR
- funding_rate_pairs.funding_rate_pairs_analysis: pre-computed OI-weighted
  cross-pair differentials (7d / 30d / 90d windows)
- boros_analytics.futures_basis_hourly: TradFi dated-futures basis (CME + Deribit),
  i.e. (futures_price - spot_price)/spot_price annualized as premium_apr
"""

from . import ProductSpec, TableSpec


_CONTEXT = """\
# Market Funding Rate Data Catalog

## Overview

This product covers two related instrument families, both expressing "premium over spot":

**(A) Perpetual funding rates** — three tables across crypto perp exchanges
(Coinglass + Hyperliquid pairs). Complementary but NOT directly joinable:
different key formats and different `funding_rate` unit conventions.

**(B) TradFi dated-futures basis** — one table covering CME + Deribit dated
futures with the same instrument design as TradFi futures: a fixed expiry
and a per-contract spot-vs-futures basis annualized as `premium_apr`.

| Table (short name) | Family | Purpose | FR unit | Key format |
|---|---|---|---|---|
| `market_funding_rate` | A — perp | Current/recent rates, all tracked pairs | per-settlement-period | `exchange` + `trading_pair_symbol` |
| `pair_timeseries` | A — perp | 90D history snapshots + OI per pair | 8h-equivalent | `pair_key` = `exchange:symbol` |
| `funding_rate_pairs_analysis` | A — perp | Pre-computed snapshots of OI-weighted avg + cross-pair diff | 8h-equivalent | `exchange_a/b` + `symbol_a/b` |
| `futures_basis_hourly` | B — dated | Per-contract futures-vs-spot premium across exchanges, by maturity | annualized APR (decimal) | `exchange` + `contract_symbol` |

## CRITICAL: funding_rate / premium Normalization Differs Between Tables

**`market_funding_rate`** (perp):
- `funding_rate` = raw rate per settlement period (e.g., 0.0001 = 0.01% per 8h on Binance)
- `normalized_funding_rate = funding_rate / funding_rate_interval` = per-hour rate
- Use `normalized_funding_rate` for cross-exchange comparison in this table.

**`pair_timeseries` and `funding_rate_pairs_analysis`** (perp):
- `funding_rate` = **8-hour equivalent** (all sources normalized to Binance's 8h interval).
- Annualized rate ≈ `funding_rate × 3 × 365` (3 settlements per day at 8h interval).

**`futures_basis_hourly`** (dated):
- `premium_apr` = **annualized basis as decimal** (e.g., 0.0584 = 5.84% APR).
  Already annualized — no further × 365 or × 3 transformation. Compare
  directly to `8h_equivalent × 3 × 365`.

**Never mix `funding_rate` from `market_funding_rate` with `funding_rate` from
`pair_timeseries` in the same calculation.** Likewise: don't compare raw
`funding_rate` (A-family, per-period) directly to `premium_apr` (B-family,
already annualized) — annualize A first.

## Exchange Name Casing: Always Use LOWER() for Filtering

Exchange names are not consistently cased across tables (Coinglass tables use
`'Binance'`, `'Bybit'`; `futures_basis_hourly` uses `'cme'`, `'deribit'`).
**Always apply `LOWER()` when filtering by exchange name** to avoid silent mismatches.
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
- `price`: daily open price of the underlying in USD (LEFT JOIN — may be NULL).
  Sourced from `hyperliquid.price_ohlcv_daily.open_price` for Hyperliquid pairs,
  and `coinglass.price_ohlc.open` (`price_type = 'futures'`) for other exchanges.
  Note: this is a **daily** open price joined onto every intraday `dt` row, so
  all rows on the same date share the same price value.

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


_FUTURES_BASIS_HOURLY = """\
## `pendle-data.boros_analytics.futures_basis_hourly`

TradFi dated-futures basis observations across exchanges. Lives in
`boros_analytics` because of physical adjacency to Boros analytics, but the
data itself is general crypto+commodity market data, not Boros-protocol data.

- Partition: `ts` (TIMESTAMP) — always filter on `ts`.
- Grain: `(exchange, contract_symbol, ts)`. Each contract has many rows over
  its lifetime (one per snapshot); each snapshot has one row per active contract.
- Source: `funding-data-api.futures_basis` Mongo collection (provider:
  `cme-databento` for CME, `deribit-public` for Deribit).
- Coverage: 2021-05-06 → today; ~373K rows total (size as of 2026-05-12).
- Exchanges: `'cme'` + `'deribit'` (lowercase, no LOWER() needed but harmless).
- Underlyings (5): BTC, ETH, SOL, XAG (silver), XAU (gold). Crypto-only
  overlap CME ∩ Deribit is BTC + ETH; CME has the metals + SOL extras.

### Granularity caveat

Despite the `_hourly` suffix, the **actual cadence depends on the exchange**:
- **CME**: one row per contract per day at 00:00 UTC (exchange-traded
  futures only publish once per day per contract).
- **Deribit**: genuinely hourly observations.

So `COUNT(*)` per day per (exchange, contract_symbol) is typically 1 for CME
and 24 for Deribit. Don't assume uniform spacing across exchanges.

### Fields

- `oid_str`: STRING — Mongo `_id` as hex (incremental key for the fetcher).
- `exchange`: STRING — `'cme'` or `'deribit'`.
- `base_symbol`: STRING — underlying asset (`'BTC'`, `'ETH'`, `'SOL'`, `'XAG'`, `'XAU'`).
- `contract_symbol`: STRING — exchange-specific contract id
  (e.g. `'BTCK26.CME'` = May 2026 BTC future on CME, `'BTC-29MAY26'` on Deribit).
- `expiry_date`: DATE — contract expiry (00:00 UTC on this date).
- `days_to_expiry`: FLOAT — fractional days from observation `ts` to expiry.
- `ts`: TIMESTAMP — observation time (PARTITION COLUMN).
- `granularity`: STRING — provider-reported (`'hourly'` for Deribit).
- `futures_price`: FLOAT — futures contract price at `ts` (USD).
- `spot_price`: FLOAT — spot reference at `ts` (USD). Equals `futures_price`
  in rare degenerate rows (e.g. silver `SIK26.CMX` on a quiet day).
- `premium_apr`: FLOAT — **annualized basis as decimal**.
  `≈ ln(futures_price/spot_price) / (days_to_expiry/365)`.
  Positive = contango (futures > spot), negative = backwardation.
- `is_spot_proxy`: BOOL — true when spot is proxied (e.g. perp index price
  used as spot fallback for an underlying without a direct spot market).
- `provider`: STRING — data source (`'cme-databento'`, `'deribit-public'`).
- `created_at` / `updated_at`: TIMESTAMP — fetcher metadata.

### Use For
- Latest basis term-structure for a single underlying (basis curve).
- Cross-exchange basis comparison (CME vs Deribit on overlapping BTC/ETH).
- Calendar spreads (long-tenor − short-tenor `premium_apr`).
- Comparing dated-futures basis to perp funding rate as alternative carry yield.

### Aggregation rules
- Always filter on `ts` partition. For "latest", use
  `DATE(ts) = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)` and pick the latest
  `ts` per contract.
- `premium_apr` is already annualized — do not multiply by 365 again.
- To compare to perp funding rate (8h-equivalent), convert perp first:
  `perp_apr ≈ pair_timeseries.funding_rate × 3 × 365`.

### Example 1 — latest CME basis term-structure for BTC
```sql
WITH latest AS (
  SELECT contract_symbol, MAX(ts) AS ts
  FROM `pendle-data.boros_analytics.futures_basis_hourly`
  WHERE DATE(ts) >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
    AND exchange = 'cme' AND base_symbol = 'BTC'
  GROUP BY contract_symbol
)
SELECT f.contract_symbol, f.expiry_date,
       ROUND(f.days_to_expiry, 1)    AS days_to_exp,
       ROUND(f.spot_price, 2)         AS spot,
       ROUND(f.futures_price, 2)      AS future,
       ROUND(f.premium_apr * 100, 3)  AS basis_apr_pct
FROM `pendle-data.boros_analytics.futures_basis_hourly` f
JOIN latest USING (contract_symbol, ts)
WHERE DATE(f.ts) >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
ORDER BY f.expiry_date
```

### Example 2 — CME vs Deribit basis for the closest-expiry BTC contract
```sql
SELECT exchange, contract_symbol, expiry_date,
       ROUND(AVG(premium_apr * 100), 3) AS avg_basis_apr_pct,
       MIN(ts) AS first_obs, MAX(ts) AS last_obs
FROM `pendle-data.boros_analytics.futures_basis_hourly`
WHERE DATE(ts) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND base_symbol = 'BTC'
  AND expiry_date > CURRENT_DATE()
GROUP BY exchange, contract_symbol, expiry_date
ORDER BY expiry_date, exchange
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
        # ── TradFi dated-futures basis (CME + Deribit) ─────────────────
        TableSpec(
            "pendle-data.boros_analytics.futures_basis_hourly",
            partition_col="ts",
            description=(
                "TradFi dated-futures basis (CME + Deribit). Grain: "
                "(exchange, contract_symbol, ts). Coverage 2021-05-06→today, "
                "~373K rows. 5 underlyings: BTC, ETH, SOL, XAG (silver), XAU (gold). "
                "Key fields: exchange ('cme'/'deribit'), base_symbol, contract_symbol, "
                "expiry_date, days_to_expiry, futures_price, spot_price, "
                "premium_apr (annualized basis as decimal, e.g. 0.0584 = 5.84% APR).\n"
                "Granularity caveat: CME = daily (00:00 UTC, one row/contract/day), "
                "Deribit = genuinely hourly. Don't assume uniform spacing.\n"
                "→ Use for: futures basis term-structure, calendar spreads, "
                "cross-exchange basis comparison (CME vs Deribit), "
                "alternative carry-yield analysis vs perp funding."
            ),
            catalog=_FUTURES_BASIS_HOURLY,
        ),
        # ── Add new funding rate / basis tables here ───────────────────
    ),
    context=_CONTEXT,
    tool_description=(
        "Returns the Market Funding Rate catalog INDEX: covers BOTH perp funding "
        "rates (Coinglass + Hyperliquid) and TradFi dated-futures basis "
        "(CME + Deribit via futures_basis_hourly). Includes normalization rules "
        "(CRITICAL — per-period vs 8h-equivalent vs already-annualized APR differ "
        "between tables), exchange name casing warnings, and table summaries.\n\n"
        "CALL THIS FIRST before querying any rate/basis table. "
        "Then call get_market_funding_rate_table_detail(table_name) for full column definitions."
    ),
    table_detail_description=(
        "Full column definitions, aggregation rules, and SQL examples for a "
        "Market Funding Rate table — covers cross-exchange perp funding rates "
        "AND TradFi dated-futures basis. NOT Pendle or Boros protocol data.\n\n"
        "Available tables: market_funding_rate, pair_timeseries, "
        "funding_rate_pairs_analysis, futures_basis_hourly."
    ),
    register_extra_tools=None,
)
