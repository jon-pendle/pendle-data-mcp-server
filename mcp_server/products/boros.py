"""
Boros Protocol product specification.

Contains:
- Table definitions (for run_sql whitelist + partition guardrails)
- Full data catalog (markdown prose for LLM consumption)
- Extra tools (market discovery)
"""

import os
import json
from pathlib import Path

from . import ProductSpec, TableSpec

# KB path: /app/boros-kb in Docker, or relative to project root locally
_KB_ROOT = os.environ.get(
    "BOROS_KB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "boros-kb"),
)

# Pre-built whitelist of KB files (relative paths).
# Eliminates path traversal, symlink, and TOCTOU risks by design.
_KB_ALLOWED_FILES: dict[str, Path] = {}


def _build_kb_file_map() -> dict[str, Path]:
    """Scan KB directory once at import time, return {relative_path: absolute_path}."""
    root = Path(_KB_ROOT).resolve()
    if not root.is_dir():
        return {}
    allowed: dict[str, Path] = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root))
            allowed[rel] = p
    return allowed


_KB_ALLOWED_FILES = _build_kb_file_map()


_CONTEXT = """\
# Boros Data Catalog

## Business Context

Boros is not Pendle V2. There are no PT/YT concepts.

### YU Core Concepts

YU (Yield Unit) is the fundamental unit of trade on Boros. It represents the tokenized
floating funding rate of a perpetual contract (e.g., Binance BTC funding rate).

- Long YU: receive the floating rate, pay fixed.
- Short YU: receive fixed, pay the floating rate.
- YU notional value: size of the underlying asset that a position earns yield from.
  Example: 10 YU in a BTC market = 10 BTC notional.
- YU position value: actual market value of the YU position, driven by implied APR and
  time-to-maturity. Much smaller than notional value; decays to zero at maturity.
  `position_value ≈ implied_APR × time_remaining × notional`

### PnL Accounting

- Settlement PnL: periodic funding cashflow (flow, each epoch).
- Trade PnL: mark-to-market from APR change (not from time decay).
- Position value decay to zero at maturity is NOT short-side profit by itself.

### Fee Composition

All fee columns in `market_metrics_all_in_one_daily` are **gross**. Net = gross − rebate.

- Settlement fee (gross): `settlement_fees` / `settlement_fees_in_usd`
- Trading fee (gross total): `swap_fees` / `swap_fees_in_usd`
- Trading fee breakdown (gross):
  - `limit_order_swap_fees` / `limit_order_swap_fees_in_usd`
  - `all_otc_fees` / `all_otc_fees_in_usd` (all OTC trades)
  - `amm_otc_fees` / `amm_otc_fees_in_usd` (subset of OTC matched against AMM)
- Rebate fields: `settlement_rebate_in_usd`, `taker_rebate_in_usd`, `otc_rebate_in_usd`, `total_rebate_in_usd`

Net fee example: `net_total_fees_usd = (settlement_fees_in_usd + swap_fees_in_usd) - total_rebate_in_usd`

Warning: `swap_fees` is the total trading fee; its breakdown components (`limit_order_swap_fees`,
`all_otc_fees`) should NOT be added to `swap_fees` again to avoid double-counting.

### OI and Volume Conventions

**CRITICAL: both metrics are two-sided (double-counted). Always divide by 2 for market-level
reporting unless the raw user-level breakdown is explicitly needed.**

- `notional_oi / 2` = market open interest.
- `notional_value / 2` = market trading volume.
- `trade_value` = economic value transferred (no halving needed).

### Data Source Policy

- If a table has `data_source`, ALWAYS filter `data_source = 'production'`.
- Never mix production and staging in one result.

## Operational Knowledge (Boros Knowledge Base)

For risk parameters, market maker terms, trading strategies, zone thresholds,
known addresses, and other operational context beyond what's in the data tables:
1. Call get_boros_kb_index() to see all available topics and file paths
2. Call read_boros_kb(path) to load a specific file
"""


# ── Per-table catalogs ───────────────────────────────────────────────

_MARKET_METRICS = """\
## `pendle-data.boros_analytics.market_metrics_all_in_one_daily`

Primary fact table. Grain: one row per (`data_source`, `market_id`, `dt`).
Partition: `dt` (DATE) — always filter on `dt`.

Join to market metadata: `m.market_id = mm.id AND m.data_source = mm.data_source`

### Aggregation Rules

- **Flow metrics** (cross-day): `SUM`
- **Snapshot metrics** (cross-day): **period-end by default** (last available date in window).
  Use `AVG` only if the user explicitly asks for an average.
- **User counts**: `AVG` or `MAX`, never `SUM` across markets.

### Metric Groups

#### Settlement / Yield (flow → SUM)
- `yield_paid`, `yield_received`, `abs_settlements`, `settlement_fees`
- `yield_paid_in_usd`, `yield_received_in_usd`, `settlements_in_usd`, `settlement_fees_in_usd`
- `settlement_rebate_in_usd`, `taker_rebate_in_usd`, `otc_rebate_in_usd`, `total_rebate_in_usd`

#### Trading / Fee (flow → SUM)
- `notional_value`, `trade_value`, `swap_fees`
- `notional_value_in_usd`, `trade_value_in_usd`, `swap_fees_in_usd`
- `limit_order_swap_fees`, `limit_order_swap_fees_in_usd`
- `amm_otc_fees`, `amm_otc_fees_in_usd`
- `all_otc_fees`, `all_otc_fees_in_usd`

#### Open Interest / Position / APR / TVL (snapshot → period-end by default)
- `notional_oi`, `notional_oi_in_usd`  ← two-sided; divide by 2 for market OI
- `position_value`, `position_value_in_usd`
- `mark_apr`: market implied yield (the "price" of YU).
- `floating_apr`: current underlying funding rate from the external exchange.
- `time_to_maturity`
- `amm_tvl_usd`

#### User Activity
- `user_count`, `user_has_swap_fee_count`
- WARNING: NOT additive across markets. Never `SUM` user counts across different markets.

### SQL Examples
```sql
-- Daily protocol-level metrics (all markets aggregated)
SELECT dt,
  SUM(notional_value_in_usd) / 2 AS trading_volume_usd,
  SUM(swap_fees_in_usd) AS swap_fees_usd,
  SUM(settlement_fees_in_usd) AS settlement_fees_usd,
  SUM(notional_oi_in_usd) / 2 AS open_interest_usd
FROM `pendle-data.boros_analytics.market_metrics_all_in_one_daily`
WHERE dt >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND data_source = 'production'
GROUP BY dt ORDER BY dt

-- Per-market APR and OI snapshot (latest day)
SELECT m.market_id, mm.name AS market_name, mm.platform_name,
  m.mark_apr, m.floating_apr, m.notional_oi_in_usd / 2 AS oi_usd, m.amm_tvl_usd
FROM `pendle-data.boros_analytics.market_metrics_all_in_one_daily` m
JOIN `pendle-data.boros_analytics.market_meta` mm
  ON m.market_id = mm.id AND m.data_source = mm.data_source
WHERE m.dt = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND m.data_source = 'production'
ORDER BY oi_usd DESC
```
"""

_MARKET_META = """\
## `pendle-data.boros_analytics.market_meta`

Market metadata / reference data. Grain: one row per (`data_source`, `id`).

Use like Pendle pool meta:
- Discover exact `market_id` values
- Map informal names to canonical market IDs
- Filter by maturity, platform, asset, or token fields

### Market Name Structure

A Boros market `name` follows the pattern: `{pair}-{platform_code}-{token_code}-{YYMMDD}`

Examples:
- `BTCUSDT-BN-T-260327`  → BTC/USDT on Binance, collateral=T (underlying token), expires 2026-03-27
- `XAGUSDT-BN-$-260327`  → XAG/USDT on Binance, collateral=$ (USD stablecoin), expires 2026-03-27
- `HYPEUSDT-YY-$-260327` → HYPE/USDT on Bybit (YY), collateral=$, expires 2026-03-27
- `BTCUSDT-GT-T-260227`  → BTC/USDT on Gate (GT), collateral=T, expires 2026-02-27

The third component is the **collateral token**: `T` = native token, `$` = USD stablecoin.
Use `token_symbol` in `market_meta` to get the exact collateral token name.

Key fields for market identification:

| Field | Meaning | Example |
|---|---|---|
| `name` | Canonical market name in `{pair}-{platform}-{collateral}-{YYMMDD}` format | `"BTCUSDT-BN-T-260327"` |
| `funding_rate_symbol` | Perpetual contract pair (the `{pair}` component) | `"BTCUSDT"`, `"XAGUSDT"` |
| `platform_name` | Full exchange name (expands the `{platform_code}`) | `"Binance"` (BN), `"Bybit"` (YY), `"Gate"` (GT) |
| `token_symbol` | Collateral token symbol | `"Underlying"`, `"USDT"` |
| `asset_symbol` | Underlying asset of the funding rate | `"BTC"`, `"ETH"` |
| `maturity` | Market expiry (DATETIME) | `2026-03-27 00:00:00` |
| `id` | Numeric market ID — use this as `market_id` in fact tables | `42` |

When a user refers to a market informally (e.g., "BTC Binance March", "HYPE market"),
query `market_meta` first to resolve the exact `id` (= `market_id` in fact tables), then use
that `market_id` in all subsequent queries.

Common fields:
- `data_source`, `id`, `name`, `symbol`, `maturity`, `maturity_ts`
- `platform_name`, `funding_rate_symbol`, `asset_symbol`
- `yield_platform_name`, `yield_funding_rate_symbol`, `yield_name`
- `token_symbol`, `token_address`, `token_decimals`
- `taker_fee`, `oct_fee`, `settle_fee_rate`, `settlement_interval_hours`
- `amm_address`, `amm_id`

### SQL Example
```sql
SELECT id AS market_id, name, platform_name, asset_symbol, token_symbol, maturity
FROM `pendle-data.boros_analytics.market_meta`
WHERE data_source = 'production'
  AND (maturity IS NULL OR maturity > CURRENT_DATETIME())
ORDER BY name
```
"""

_ORDERBOOK_SNAPSHOT = """\
## `pendle-data.boros_analytics.orderbook_snapshot_hourly`

Hourly orderbook depth snapshots at market level. Grain: one row per (`data_source`, `market_id`, `snapshot_dt`).
Partition: `snapshot_dt` (TIMESTAMP) — always filter on `snapshot_dt`.

Join to market metadata: `ob.market_id = mm.id AND ob.data_source = mm.data_source`

### Dimensions
| Column | Type | Description |
|--------|------|-------------|
| data_source | STRING | Always filter = 'production' |
| market_id | INT64 | Market numeric ID (join to market_meta.id) |
| market_name | STRING | Human-readable market name |
| snapshot_dt | TIMESTAMP | Snapshot timestamp (partition key) |
| token_symbol | STRING | Collateral token symbol |

### Market-Level Rate Columns
| Column | Type | Description |
|--------|------|-------------|
| reference_apr | FLOAT64 | Reference APR (external rate) |
| mark_apr | FLOAT64 | Mark-to-market APR |
| mid_apr | FLOAT64 | Mid-point APR |
| last_traded_apr | FLOAT64 | Last traded APR |
| best_bid_apr | FLOAT64 | Best bid APR (highest buy) |
| best_ask_apr | FLOAT64 | Best ask APR (lowest sell) |
| spread_apr | FLOAT64 | Spread = best_ask_apr - best_bid_apr |
| spread_apr_pct | FLOAT64 | Spread as % of reference_apr |
| max_rate_deviation | FLOAT64 | Max allowed rate deviation |
| notional_oi_in_usd | FLOAT64 | Notional open interest (two-sided, divide by 2) |

### Liquidity & Depth Columns — Naming Convention

~400 columns follow a systematic pattern: `{user_type_prefix}_{metric}_{side}`

**User type prefixes:**
| Prefix | Meaning |
|--------|---------|
| _(none)_ | Total (all user types combined) |
| `organic_` | Organic users only |
| `mm_` | All market makers (ExMM + inMM) |
| `exmm_` | External market makers only |
| `inmm_` | Internal market makers only |
| `amm_` | AMM only |

**Metrics:**
| Metric Pattern | Description |
|----------------|-------------|
| `num_active_orders_{side}` / `num_orders_{threshold}_{side}` | Order count |
| `total_liquidity_token_{side}` / `depth_{threshold}_token_{side}` | Liquidity in tokens |
| `total_liquidity_usd_{side}` / `depth_{threshold}_usd_{side}` | Liquidity in USD |
| `total_position_value_{side}` / `depth_{threshold}_position_value_{side}` | Position value |

**Sides:** `short_side`, `long_side`

**Depth thresholds (distance from mid):**
| Threshold | Column infix | Description |
|-----------|-------------|-------------|
| Total | `total_liquidity_*` | All active orders (no distance limit) |
| 30 bps | `depth_30bps_*` | Orders within 30 bps of mid |
| 120 bps | `depth_120bps_*` | Orders within 120 bps |
| 300 bps | `depth_300bps_*` | Orders within 300 bps |
| 20% MRD | `depth_20pctMRD_*` | Within 20% of max_rate_deviation |
| MRD | `depth_MRD_*` | Within max_rate_deviation |
| Tier 1 | `depth_t1_*` | Within tier 1 range, aka 25% MRD |
| Tier 2 | `depth_t2_*` | Within tier 2 range, aka MRD |

### Example Column Names
```
total_liquidity_usd_short_side         — total short-side USD liquidity (all users)
organic_liquidity_usd_long_side        — organic long-side USD liquidity
mm_depth_30bps_usd_long_side           — MM long-side USD depth within 30 bps
exmm_depth_120bps_token_short_side     — ExMM short-side token depth within 120 bps
amm_depth_MRD_position_value_long_side — AMM long-side position value within MRD
```

### Aggregation Rules
- Hourly snapshot (point-in-time): use latest snapshot or AVG for period summaries.
- All liquidity/depth columns are **stock metrics** — do NOT SUM across time.
- To get daily summary: filter latest snapshot per day, or AVG across hours.
- Liquidity columns ARE additive across markets (unlike holder/user counts).

### SQL Example
```sql
-- Daily avg depth and spread by market, last 7 days
SELECT DATE(ob.snapshot_dt) AS dt, ob.market_name,
  AVG(ob.total_liquidity_usd_short_side + ob.total_liquidity_usd_long_side) AS avg_total_liq_usd,
  AVG(ob.depth_30bps_usd_short_side + ob.depth_30bps_usd_long_side) AS avg_depth_30bps_usd,
  AVG(ob.organic_liquidity_usd_short_side + ob.organic_liquidity_usd_long_side) AS avg_organic_liq_usd,
  AVG(ob.spread_apr) AS avg_spread
FROM `pendle-data.boros_analytics.orderbook_snapshot_hourly` ob
WHERE ob.snapshot_dt >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND ob.data_source = 'production'
GROUP BY dt, ob.market_name
ORDER BY dt, ob.market_name
```
"""


_USER_MARKET_METRICS = """\
## `pendle-data.boros_analytics.user_market_metric_all_in_one_daily`

User-market daily metrics. Grain: one row per (`data_source`, `user_address`, `market_id`, `dt`).
Partition: `dt` (DATE) — always filter on `dt`. Requires `data_source = 'production'`.

Join to market metadata: `m.market_id = mm.id AND m.data_source = mm.data_source`

### Key Columns

#### Identity
- `user_address`, `market_id`, `market_name`, `token_symbol`
- `user_classification`: AMM / ExMM / inMM / carry trader classification
- `user_desc`: human-readable label (if known)
- `maturity`, `epoch_start_date`

#### Settlement (flow → SUM)
- `yield_paid`, `yield_received`, `abs_settlements`, `settlement_fees`
- `yield_paid_in_usd`, `yield_received_in_usd`, `abs_settlements_in_usd`, `settlement_fees_in_usd`
- `settlement_rebate` / `_in_usd`: settlement fee rebate
- `realized_settlement_pnl_daily_net` / `_in_usd`: daily net settlement PnL (received - paid - fees)
- `realized_settlement_pnl_cum_net` / `_in_usd`: cumulative net settlement PnL

#### Rebates (flow → SUM)
- `taker_rebate` / `_in_usd`: taker swap fee rebate
- `otc_rebate` / `_in_usd`: OTC fee rebate
- `total_rebate` / `_in_usd`: sum of settlement + taker + OTC rebates

#### Trading (flow → SUM)
- `daily_notional_vol` / `_in_usd`: daily notional volume (two-sided)
- `daily_vol` / `_in_usd`: daily trade value
- `daily_swap_fees` / `_in_usd`: daily total swap fees
- `daily_limit_order_swap_fees` / `_in_usd`
- `daily_amm_otc_fees` / `_in_usd`
- `daily_all_otc_fees` / `_in_usd`

#### Position (snapshot)
- `notional_size` / `_usd`: end-of-day net position (signed)
- `abs_notional_size` / `_usd`: absolute position size
- `avg_fixed_apr`: position-weighted average fixed APR
- `market_apr`, `days_to_maturity`

#### PnL (snapshot — cumulative)
- `realized_trading_pnl_cum_net` / `_in_usd`: cumulative trading PnL
- `unrealized_pnl` / `_in_usd`: mark-to-market unrealized PnL

### Aggregation Rules
- Volume/fees: SUM across days, SUM across users.
- Position/PnL: snapshot — use latest day or AVG.
- user_classification NOT additive — same address may have different labels.

### SQL Example
```sql
-- Top 10 users by total trading volume last 7 days
SELECT user_address, user_classification,
  SUM(daily_notional_vol_in_usd) / 2 AS volume_usd,
  SUM(daily_swap_fees_in_usd) AS fees_usd
FROM `pendle-data.boros_analytics.user_market_metric_all_in_one_daily`
WHERE dt >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND data_source = 'production'
GROUP BY 1, 2
ORDER BY volume_usd DESC
LIMIT 10
```
"""

_USER_MARGIN_BALANCE = """\
## `pendle-data.boros_analytics.user_margin_balance_daily`

Per-user daily margin balance tracking. Grain: (`data_source`, `user_address`, `token_symbol`, `dt`).
Partition: `dt` (DATE) — always filter on `dt`. Requires `data_source = 'production'`.

### Key Columns
- `user_address`, `token_symbol`, `dt`
- `is_new_user`: true on the user's first deposit date
- `daily_net_amount` / `_usd`: net deposits - withdrawals (native token / USD)
- `daily_settlement_net_amount` / `_usd`: net settlement flow
- `realized_trading_pnl_daily_net` / `_in_usd`: daily trading PnL
- `realized_trading_pnl_cum_net` / `_in_usd`: cumulative trading PnL
- `realized_settlement_pnl_cum_net` / `_in_usd`: cumulative settlement PnL
- `realized_pnl_cum_net` / `_in_usd`: cumulative total PnL (trading + settlement)
- `margin_balance` / `_usd`: current margin balance (cumulative of all flows)

### Aggregation Rules
- daily flows (net_amount, settlement, pnl): SUM across users/tokens for platform totals.
- margin_balance: snapshot — SUM across users gives platform total margin at that date.
- Use `margin_balance_daily` (aggregated view) for platform-level totals by cohort.

### SQL Example
```sql
-- Platform total margin balance by token, latest
SELECT token_symbol,
  COUNT(DISTINCT user_address) AS users,
  SUM(margin_balance) AS total_margin,
  SUM(margin_balance_usd) AS total_margin_usd
FROM `pendle-data.boros_analytics.user_margin_balance_daily`
WHERE dt = (SELECT MAX(dt) FROM `pendle-data.boros_analytics.user_margin_balance_daily`
            WHERE data_source = 'production')
  AND data_source = 'production'
GROUP BY 1
```
"""

_USER_EOD_POSITION = """\
## `pendle-data.boros_analytics.user_eod_position_summary`

Daily end-of-day position summary per user-market with cumulative PnL and incentives.
Grain: (`data_source`, `user_address`, `market_id`, `market_name`, `token_symbol`, `dt`).
Partition: `dt` (DATE) — always filter on `dt`. Requires `data_source = 'production'`.

Built on top of `user_market_metric_all_in_one_daily` with additional:
- Position value calculation (using days_to_maturity)
- Cumulative volumes
- Incentive tracking (AMM LP rewards + maker incentives from Merkle campaigns)
- Total PnL = realized trading + realized settlement + unrealized

### Key Columns (unique to this table, not in user_market_metric)

#### Position Value
- `total_abs_position_value` / `_usd`: |notional| × price × days_to_maturity/365

#### Cumulative Volume
- `cumulative_total_daily_notional_vol_usd`
- `cumulative_total_daily_vol_usd`

#### PnL (combined)
- `total_pnl` / `_usd`: realized_trading + realized_settlement + unrealized

#### Incentives (USD — flow → SUM)
- `daily_amm_lp_rewards_usd`, `cumulative_amm_lp_rewards_usd`
- `daily_maker_incentive_usd`, `cumulative_maker_incentive_usd`
- `daily_total_incentives_usd`, `cumulative_total_incentives_usd`

#### Incentives (token amount — flow → SUM)
- `daily_amm_lp_rewards_token_amount`, `cumulative_amm_lp_rewards_token_amount`
- `daily_maker_incentive_token_amount`, `cumulative_maker_incentive_token_amount`
- `daily_total_incentives_token_amount`, `cumulative_total_incentives_token_amount`

Token amounts are raw ERC20 units (already divided by 1e18). Use for tracking PENDLE token distributions independent of price.

### SQL Example
```sql
-- User total PnL including incentives, latest snapshot
SELECT user_address,
  SUM(total_pnl_usd) AS total_pnl_usd,
  SUM(cumulative_total_incentives_usd) AS total_incentives_usd,
  SUM(total_pnl_usd) + SUM(cumulative_total_incentives_usd) AS total_return_usd
FROM `pendle-data.boros_analytics.user_eod_position_summary`
WHERE dt = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND data_source = 'production'
GROUP BY 1
ORDER BY total_return_usd DESC
LIMIT 20
```
"""

_PRICE_FEEDS = """\
## `pendle-data.boros_analytics.price_feeds`

Boros token price reference data (hourly granularity). Covers: WETH, WBTC, PENDLE, BNB, HYPE, XRP, USD₮0.
Not partitioned but small table.

| Column | Type | Description |
|--------|------|-------------|
| symbol | STRING | Token symbol (WETH, WBTC, PENDLE, BNB, HYPE, XRP, USD₮0) |
| address | STRING | Token contract address on Arbitrum |
| dt | TIMESTAMP | Price timestamp (hourly) |
| price | FLOAT64 | Token price in USD |

Note: symbol names differ from Pendle price_feeds (WETH not eth, WBTC not btc).
USD₮0 is always price=1.

### SQL Example
```sql
SELECT symbol, dt, price
FROM `pendle-data.boros_analytics.price_feeds`
WHERE symbol = 'WETH'
  AND dt >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY dt
```
"""

_USER_AAARR_METRICS = """\
## `pendle-data.boros_analytics.user_aaarr_metrics`

Boros AARRR funnel metrics per daily calc_point. One row per day, aggregated across all users.
**Partition: calc_point (DATE) — always filter on calc_point.**

⚠️ This is NOT a strict cohort funnel. Uses unconventional stage definitions specific to Boros.
Obs windows: 7d and 30d. Retention qualification: fixed 60d.

### Funnel Stages

1. **Awareness**: wallet connected (from Mixpanel frontend events)
2. **Consideration**: deposit modal opened → deposit initiated → order submitted (from Mixpanel)
3. **Activation**: first-ever taker trade falls within obs window (from on-chain data)
4. **Engagement**: ≥3 trades within obs window
5. **Monetization**: ≥1 trade in obs window AND cumulative LTV > $50
6. **Retention**: qualified (≥1 trade in past 60d) then confirmed by trading in future windows

### Key Column Groups

#### Awareness (from Mixpanel wallet_connected events)
- `awareness_wallet_connected_{7d,30d}`: user count
- `awareness_wallet_connected_{7d,30d}_new_user`: new user count (no trade before calc_point)
- `awareness_wallet_connected_{7d,30d}_avg_ltv`: average LTV of connected users

#### Consideration (from Mixpanel deposit/order events)
- `consideration_deposit_modal_opened_{7d,30d}` / `_new_user` / `_avg_ltv`
- `consideration_deposit_initiated_{7d,30d}` / `_new_user` / `_avg_ltv`
- `consideration_order_submitted_{7d,30d}` / `_new_user` / `_avg_ltv`

#### Activation (first trade in obs window)
- `activation_{7d,30d}_user_count` / `_avg_ltv`

#### Engagement (≥3 trades in obs window)
- `engagement_{7d,30d}_user_count` / `_avg_ltv`

#### Monetization (≥1 trade + LTV > $50)
- `monetization_{7d,30d}_user_count` / `_avg_ltv`

#### Retention (qualified + confirmed by future trading)
- `retention_qualified_user_count`: users with ≥1 trade in past 60d (shared denominator)
- `retention_{30d,60d,90d}_user_count` / `_avg_ltv`: confirmed retained users
- `retention_{30d,60d,90d}_user_count_{30d,60d,90d}_back`: LAG values for time comparison

⚠️ Retention columns are NULL until the confirmation window has fully closed.
- 30d retention: NULL for calc_points within last 30 days
- 60d retention: NULL for calc_points within last 60 days
- 90d retention: NULL for calc_points within last 90 days

### Aggregation Rules
- All counts are pre-aggregated across users. Do NOT SUM across calc_points.
- For weekly/monthly: use AVG for counts, AVG for avg_ltv.
- Retention rate = retention_Xd_user_count / retention_qualified_user_count.

### LTV Definition
LTV = cumulative (limit_order_swap_fees + all_otc_fees + settlement_fees) from first trade to calc_point.

### SQL Example
```sql
-- Weekly AARRR funnel summary
SELECT DATE_TRUNC(calc_point, WEEK) AS week,
  AVG(awareness_wallet_connected_7d) AS avg_awareness,
  AVG(activation_7d_user_count) AS avg_activation,
  AVG(engagement_7d_user_count) AS avg_engagement,
  AVG(monetization_7d_user_count) AS avg_monetization,
  AVG(retention_30d_user_count) AS avg_retained_30d,
  AVG(SAFE_DIVIDE(retention_30d_user_count, retention_qualified_user_count)) AS avg_retention_rate_30d
FROM `pendle-data.boros_analytics.user_aaarr_metrics`
WHERE calc_point >= '2026-01-01' AND calc_point <= '2026-03-25'
GROUP BY week ORDER BY week
```
"""

_BOROS_META_FIELDS = {
    "market_id": "id AS market_id",
    "market_name": "name AS market_name",
    "maturity": "maturity",
    "platform_name": "platform_name",
    "asset_symbol": "asset_symbol",
    "token_symbol": "token_symbol",
    "symbol": "symbol",
    "address": "address",
    "token_id": "token_id",
    "token_name": "token_name",
    "token_address": "token_address",
    "token_decimals": "token_decimals",
    "yield_name": "yield_name",
    "yield_platform_name": "yield_platform_name",
    "yield_funding_rate_symbol": "yield_funding_rate_symbol",
    "funding_rate_symbol": "funding_rate_symbol",
    "funding_premium_symbol": "funding_premium_symbol",
    "payment_period": "payment_period",
    "taker_fee": "taker_fee",
    "oct_fee": "oct_fee",
    "settle_fee_rate": "settle_fee_rate",
    "max_rate_deviation": "max_rate_deviation",
    "i_threshold": "i_threshold",
    "settlement_interval_hours": "settlement_interval_hours",
    "amm_address": "amm_address",
    "amm_id": "amm_id",
}

_ACTIVE_FIELDS = [
    "market_id",
    "market_name",
    "maturity",
    "platform_name",
    "asset_symbol",
    "token_symbol",
]
_ALL_FIELDS = ["market_id", "market_name", "asset_symbol", "token_symbol"]


def _register_boros_tools(mcp, track_fn):
    """Register Boros-specific MCP tools (market discovery + knowledge base)."""

    # ── Knowledge Base tools ──────────────────────────────────────────

    @mcp.tool(
        description=(
            "Get the Boros knowledge base index — lists all available topics "
            "with file paths and one-line descriptions. Topics include: "
            "risk parameters, market maker terms, zone thresholds, trading "
            "strategies, known addresses, and more.\n\n"
            "Call this first, then use read_boros_kb(path) to load specific files."
        )
    )
    async def get_boros_kb_index() -> str:
        track_fn("get_boros_kb_index")
        index_file = _KB_ALLOWED_FILES.get("INDEX.md")
        if index_file is None:
            return json.dumps({"error": "Boros KB not available (INDEX.md not found)"})
        return index_file.read_text()

    @mcp.tool(
        description=(
            "Read a file from the Boros knowledge base. "
            "Use get_boros_kb_index() first to discover available file paths.\n\n"
            "Returns the full content of the requested file (markdown, YAML, or TOML).\n"
            "Example paths: 'risk/global/zone-table.md', 'markets/markets.yaml', "
            "'risk/market-params/March2026/23_BTCUSDT-BN-T-260327.toml'"
        )
    )
    async def read_boros_kb(path: str) -> str:
        track_fn("read_boros_kb", path=path)
        # Normalize path separators and look up in pre-built whitelist.
        # Only files scanned at startup are servable — no path traversal possible.
        normalized = str(Path(path))
        target = _KB_ALLOWED_FILES.get(normalized)
        if target is None:
            return json.dumps({"error": f"File not found: {path}"})
        return target.read_text()

    # ── Market Discovery tool ─────────────────────────────────────────

    @mcp.tool(
        description=(
            "Get Boros market metadata from market_meta. "
            "ALWAYS returns production data_source only.\n\n"
            "is_active_only=true (default): returns active markets "
            "(maturity is null or maturity > CURRENT_DATETIME()) with useful default fields.\n"
            "is_active_only=false: returns all production markets with minimal fields for matching.\n\n"
            "Use this tool like pool meta in Pendle: map informal names to exact market_id first, "
            "then query metrics tables with exact market_id values."
        )
    )
    async def get_boros_markets_tool(
        is_active_only: bool = True,
        fields: list[str] | None = None,
    ) -> str:
        track_fn("get_boros_markets", is_active_only=is_active_only, fields=fields)
        import json as _json
        import pandas_gbq as _pgbq  # type: ignore[import-not-found]

        selected = fields if fields else (_ACTIVE_FIELDS if is_active_only else _ALL_FIELDS)

        invalid = [f for f in selected if f not in _BOROS_META_FIELDS]
        if invalid:
            return _json.dumps(
                {
                    "error": f"Unknown fields: {invalid}. "
                    f"Available: {list(_BOROS_META_FIELDS.keys())}"
                }
            )

        if "market_id" not in selected:
            selected = ["market_id"] + list(selected)

        select_exprs = [_BOROS_META_FIELDS[f] for f in selected]
        sql = (
            f"SELECT {', '.join(select_exprs)} "
            "FROM `pendle-data.boros_analytics.market_meta` "
            "WHERE data_source = 'production'"
        )
        if is_active_only:
            sql += " AND (maturity IS NULL OR maturity > CURRENT_DATETIME())"
        sql += " ORDER BY market_name"

        try:
            df = _pgbq.read_gbq(sql, progress_bar_type=None)
            if df.empty:
                return _json.dumps({"error": "No markets found."})
            for col in df.columns:
                if df[col].dtype.name in ("datetime64[ns]", "dbdate"):
                    df[col] = df[col].astype(str)
            csv = df.to_csv(index=False)
            return _json.dumps({"total_count": len(df), "data": csv})
        except Exception as e:
            return _json.dumps({"error": str(e)})


SPEC = ProductSpec(
    product_id="boros",
    display_name="Boros Protocol",
    tables=(
        # ── Fact: daily market metrics ─────────────────────────────────
        TableSpec(
            "pendle-data.boros_analytics.market_metrics_all_in_one_daily",
            partition_col="dt",
            require_production_source=True,
            description=(
                "Daily market metrics. Grain: (data_source, market_id, dt).\n"
                "Key metrics: OI (notional_oi), volume (notional_value), fees "
                "(swap_fees, settlement_fees, rebates), APR (mark_apr, floating_apr), "
                "TVL (amm_tvl_usd), user count.\n"
                "→ Use for: volume, fees, OI, APR trends, user activity."
            ),
            catalog=_MARKET_METRICS,
        ),
        # ── Dimension: market metadata ─────────────────────────────────
        TableSpec(
            "pendle-data.boros_analytics.market_meta",
            require_production_source=True,
            description=(
                "Market reference data. Grain: (data_source, id).\n"
                "Fields: name, maturity, platform_name, asset_symbol, token_symbol, fees, AMM config.\n"
                "→ Use for: market discovery, name→ID mapping, JOIN to fact tables."
            ),
            catalog=_MARKET_META,
        ),
        # ── Fact: hourly orderbook snapshots ───────────────────────────
        TableSpec(
            "pendle-data.boros_analytics.orderbook_snapshot_hourly",
            partition_col="snapshot_dt",
            require_production_source=True,
            description=(
                "Boros Protocol hourly orderbook depth snapshots. "
                "Grain: (data_source, market_id, snapshot_dt).\n"
                "Key metrics: liquidity depth by user type (organic/MM/ExMM/inMM/AMM) × "
                "side (long/short) × threshold (30bps/120bps/300bps/MRD/t1/t2), "
                "spread, best bid/ask APR, OI.\n"
                "→ Use for: Boros orderbook depth, spread, liquidity composition, MM vs organic breakdown. "
                "NOT Pendle v2 orderbook."
            ),
            catalog=_ORDERBOOK_SNAPSHOT,
        ),
        # ── User-market level ───────────────────────────────────────────
        TableSpec(
            "pendle-data.boros_analytics.user_market_metric_all_in_one_daily",
            partition_col="dt",
            require_production_source=True,
            description=(
                "User-market daily metrics. Grain: (data_source, user_address, market_id, dt).\n"
                "Key metrics: position (notional_size), volume (daily_notional_vol), "
                "fees (swap_fees, settlement_fees), PnL (trading + settlement, daily + cumulative), "
                "user_classification (AMM/ExMM/inMM/carry).\n"
                "→ Use for: top traders, per-user PnL, user activity analysis, fee breakdown."
            ),
            catalog=_USER_MARKET_METRICS,
        ),
        TableSpec(
            "pendle-data.boros_analytics.user_margin_balance_daily",
            partition_col="dt",
            require_production_source=True,
            description=(
                "Per-user daily margin balance. Grain: (data_source, user_address, token_symbol, dt).\n"
                "Key metrics: margin_balance, daily_net_amount (deposits-withdrawals), "
                "realized PnL (trading + settlement, daily + cumulative), is_new_user.\n"
                "→ Use for: total platform deposits, user fund flows, new vs existing user analysis."
            ),
            catalog=_USER_MARGIN_BALANCE,
        ),
        TableSpec(
            "pendle-data.boros_analytics.user_eod_position_summary",
            partition_col="dt",
            require_production_source=True,
            description=(
                "User EOD position summary with total PnL and incentives. "
                "Grain: (data_source, user_address, market_id, token_symbol, dt).\n"
                "Key metrics: total_pnl (trading+settlement+unrealized), position_value, "
                "cumulative volumes, incentives (AMM LP rewards + maker incentives).\n"
                "→ Use for: user total PnL, incentive tracking, position value analysis."
            ),
            catalog=_USER_EOD_POSITION,
        ),
        # ── Reference: price feeds ─────────────────────────────────────
        TableSpec(
            "pendle-data.boros_analytics.price_feeds",
            description=(
                "Boros token prices (hourly). Symbols: WETH, WBTC, PENDLE, BNB, HYPE, XRP, USD₮0.\n"
                "→ Use for: token price lookups for Boros-specific symbols."
            ),
            catalog=_PRICE_FEEDS,
        ),
        # ── AARRR funnel metrics ──────────────────────────────────────
        TableSpec(
            "pendle-data.boros_analytics.user_aaarr_metrics",
            partition_col="calc_point",
            description=(
                "Daily AARRR funnel metrics (Awareness → Activation → Engagement → Monetization → Retention).\n"
                "Grain: one row per calc_point (day), pre-aggregated across all users.\n"
                "Key metrics: user counts + avg LTV per stage, 7d/30d obs windows, "
                "retention 30d/60d/90d with LAG comparisons.\n"
                "→ Use for: funnel conversion analysis, retention tracking, user growth trends."
            ),
            catalog=_USER_AAARR_METRICS,
        ),
        # ── Add new Boros tables here ──────────────────────────────────
    ),
    context=_CONTEXT,
    tool_description=(
        "Returns the Boros data catalog INDEX: business context (YU, fees, OI conventions), "
        "data_source policy, and table summaries with key metrics.\n\n"
        "CALL THIS FIRST before writing any Boros SQL query. "
        "Then call get_boros_table_detail(table_name) for full column definitions."
    ),
    table_detail_description=(
        "Full column definitions, aggregation rules, and SQL examples for a "
        "Boros Protocol table (margin yield trading / interest rate swaps). "
        "For Pendle v2 core data, use get_pendle_table_detail instead.\n\n"
        "Available tables: market_metrics_all_in_one_daily, market_meta, "
        "orderbook_snapshot_hourly, user_market_metric_all_in_one_daily, "
        "user_margin_balance_daily, user_eod_position_summary, "
        "price_feeds, user_aaarr_metrics."
    ),
    register_extra_tools=_register_boros_tools,
)
