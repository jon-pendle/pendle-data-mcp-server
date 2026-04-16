"""
Pendle Protocol product specification.

Contains:
- Table definitions with per-table catalogs
- Product-level context (business rules shared across tables)
- Extra tools (pool discovery)
"""

from . import ProductSpec, TableSpec


# ── Product-level context (returned with index) ──────────────────────

_CONTEXT = """\
# Pendle Data Catalog

## Business Context

Pendle Protocol: decentralized yield trading. Boros Protocol: Pendle's margin yield trading.
$PENDLE: governance/utility token. Pool = Market (interchangeable).
IY = Implied Yield (market consensus on future yield, from token amounts not USD). Fixed APY = Implied APY.
Data is daily granularity. "latest" / "current" = yesterday's complete data (today is incomplete).
Token names are exclusive: one character difference = different token (e.g. "USD0" ≠ "USD0++").

pool_id format: CONCAT(pool, '_', chain) for pool_metrics / pool_metrics_lifetime,
                CONCAT(pool, '_', chain_id) for market_meta.

## Pool Discovery

Users often give informal pool names (e.g. "Susde May", "Reusd Jun").
Do NOT use SQL LIKE patterns to guess pool names. Instead:
1. Call get_pendle_pools_tool() — returns all pools with pool_id (format: poolName_chainId),
   expiry_date, expiry_month, yield_source, base_asset, underlying_issuer.
2. Fuzzy-match user input against pool_id + expiry month in context.
3. Use matched pool_ids as exact values in run_sql WHERE clauses.

## Analysis Rules

- "latest" / "current" = CURRENT_DATE() - 1 (yesterday's complete data).
- For comparisons, always fetch BOTH periods (DoD: 2 days, WoW: 2 weeks, MoM: 2 months).
- Use specific dates (WHERE dt >= '...' AND dt <= '...'), not relative intervals for comparisons.
- Maturity: pool matures at 00:00 UTC on expiry_date. TVL at maturity = data from expiry_date - 1.
- Near maturity: IY may spike (short duration, user rotation).
- Format: $1.2M, $3.4B. Rates as percentages (5.2%). IY changes in percentage points ("IY +0.25pp").
- Pendle Revenue = explicit swap fees + implicit swap fees + yield fees.
- DeFiLlama: use separate tools (get_defillama_*). Never guess slugs — look up first.

## Cannot Be Answered
- Per-protocol collateral breakdown (Aave vs Euler vs Morpho) → Recommend dashboard.
- Real-time / intraday data → daily granularity only.
- Individual wallet / user positions → not available.
- Non-Pendle protocol internals → only DeFiLlama TVL available.
"""


# ── Per-table catalogs ───────────────────────────────────────────────

_POOL_METRICS_DAILY = """\
## `pendle-data.analytics.pool_metrics_all_in_one_daily`

Primary fact table. One row per pool per day. **Partition: dt (DATE) — always filter on dt.**
Join to market_meta: `pm.pool = mm.pool AND pm.chain = mm.chain_id`

### Aggregation Rules

Columns have two aggregation contexts:
1. **Across pools** (same day): always SUM (except holder counts → see below)
2. **Across days** (same group): depends on metric type:
   - **stock** (point-in-time snapshot like TVL): use **AVG**
   - **flow** (cumulative like volume/fees): use **SUM**
   - **rate** (yield/APY): use **TVL-weighted average** (see pattern below)
   - **holder count**: use **AVG** within a group; **NOT additive across pools**

When using DATE_TRUNC for weekly/monthly aggregation, use a two-layer CTE:
- Inner layer: GROUP BY dt + dimensions → daily per-group totals
- Outer layer: DATE_TRUNC + correct per-column aggregation (AVG/SUM/weighted)

### Columns

#### Dimensions (use in GROUP BY / WHERE via JOIN to market_meta)
| Column | Table | Description |
|--------|-------|-------------|
| dt | pm | Date (partition key) |
| pool | pm | Pool name |
| chain | pm | Chain numeric ID |
| market_meta.chain | mm | Chain name (ethereum, arbitrum, ...) |
| market_meta.yield_source | mm | Yield category (e.g. "3-Lending") |
| market_meta.base_asset | mm | Asset type (ETH, Stable, BTC) |
| market_meta.underlying_issuer | mm | Protocol providing yield (Aave, Lido, Ethena, ...) |
| market_meta.expiry_date | mm | Pool maturity date |

#### TVL — stock metrics (cross-day: AVG)
| Column | Description | Unit |
|--------|-------------|------|
| overall_tvl | Total Value Locked (AMM + floating PT + floating YT) | USD |
| amm_tvl | AMM liquidity pool TVL | USD |
| total_pt_in_usd | All PT tokens (in LP + floating) | USD |
| floating_pt_in_usd | PT tokens NOT in LP | USD |
| floating_yt_in_usd | All YT tokens (YT is never in LP) | USD |
| pt_tvl_in_collateral | PT as lending collateral (all protocols combined) | USD |
| lp_tvl_in_collateral | LP as lending collateral (all protocols combined) | USD |

Derived: pt_in_lp = total_pt_in_usd - floating_pt_in_usd; sy_in_lp = amm_tvl - pt_in_lp.
⚠️ Collateral columns here are aggregated across ALL lending protocols. For per-protocol breakdown, use `pt_collateral_daily_balance` table instead.

#### Volume — flow metrics (cross-day: SUM)
| Column | Description | Unit |
|--------|-------------|------|
| notional_trading_volume | Total volume (limit + AMM) | USD |
| notional_trading_volume_limit | Limit order volume | USD |
| notional_trading_volume_amm | AMM volume | USD |

#### Swap Fees — flow metrics (cross-day: SUM)
| Column | Description | Unit |
|--------|-------------|------|
| total_swap_fee_usd | Explicit swap fees (AMM + limit) | USD |
| total_limit_swap_fee_usd | Limit order explicit fees | USD |
| total_implicit_swap_fee_usd | AMM implicit fees | USD |

Total Swap Fees = total_swap_fee_usd + total_implicit_swap_fee_usd.
Pendle Revenue = swap fees + yield fees.

#### Yield Fees — flow metrics (cross-day: SUM)
| Column | Description | Unit |
|--------|-------------|------|
| expected_yield_fee | Theoretical pre-maturity yield fee | USD |
| expected_expire_fee | Theoretical post-maturity yield fee | USD |
| avg_daily_realized_yield_fee_in_usd | Actually claimed fees, epoch-averaged | USD |

⚠️ CRITICAL RULES:
- Always present BOTH expected and realized perspectives separately.
- Combine expected_yield_fee + expected_expire_fee as "total expected yield fees" (unless user asks to separate).
- NEVER sum expected + realized — fundamentally different metrics (theoretical vs actually settled).
- NEVER multiply avg_daily_realized_yield_fee_in_usd by days — it is epoch-based.
- For aggregated metrics over a date range, use SUM() directly on the daily rows.

#### Yield Rates — rate metrics (cross-day: TVL-weighted average)
| Column | Description | Unit |
|--------|-------------|------|
| latest_tv_weighted_implied_yield | TVL-weighted implied yield | rate (0.05 = 5%) |
| lp_base_apy | LP base APY | rate (0.05 = 5%) |

Aggregation pattern for rates:
```sql
-- Inner CTE
SUM(latest_tv_weighted_implied_yield * overall_tvl) AS iy_num,
SUM(overall_tvl) AS iy_den
-- Outer query
SUM(iy_num) / NULLIF(SUM(iy_den), 0) AS implied_yield
```
lp_base_apy uses amm_tvl as weight instead of overall_tvl.

#### Underlying TVL — stock metrics (cross-day: AVG)
| Column | Description | Unit |
|--------|-------------|------|
| underlying_supply | Underlying token supply per pool | tokens |
| underlying_tvl | Underlying token TVL | USD |

⚠️ NOT additive across pools — multiple pools can share the same underlying asset. Use MAX or deduplicate by underlying asset when aggregating across pools.

#### Emissions — flow metrics (cross-day: SUM)
| Column | Description | Unit |
|--------|-------------|------|
| pendle_emission_amount | PENDLE emissions (sPENDLE era, 2026-01-29+) | tokens |
| pendle_emission_value | PENDLE emissions value (sPENDLE era, 2026-01-29+) | USD |
| pendle_emission_amount_legacy | PENDLE emissions (vePENDLE era, before 2026-01-29) | tokens |
| pendle_emission_value_legacy | PENDLE emissions value (vePENDLE era, before 2026-01-29) | USD |

⚠️ Method changed 2026-01-29 (vePENDLE → sPENDLE). Use `pendle_emission_*_legacy` for pre-2026-01-29 and `pendle_emission_amount/value` for post. Do not mix. Prefer USD value.

#### AIM Emission Breakdown — flow metrics (cross-day: SUM)
| Column | Description | Unit |
|--------|-------------|------|
| aim_daily_fee | AIM emission: fee component | tokens |
| aim_daily_tvl | AIM emission: TVL component | tokens |
| aim_daily_discretionary | AIM emission: discretionary component | tokens |

⚠️ Available from 2026-01-29+ (sPENDLE era only). Expected: aim_daily_fee + aim_daily_tvl + aim_daily_discretionary ≈ pendle_emission_amount.

#### Limit Order Incentives — flow metrics (cross-day: SUM)
| Column | Description | Unit |
|--------|-------------|------|
| limit_order_allocated_incentive_amount | Daily allocated LO incentives (from config amount_per_sec) | tokens |
| limit_order_consumed_incentive_amount | Daily consumed LO incentives (actual distributions) | tokens |
| limit_order_incentive_min_apy | Lower bound of incentivized APY range | rate |
| limit_order_incentive_max_apy | Upper bound of incentivized APY range | rate |

#### Campaign Incentives — flow metrics (cross-day: SUM)
| Column | Description | Unit |
|--------|-------------|------|
| campaign_incentive | Total campaign incentives | USD |
| co_bribe_campaign_incentive | Co-bribe portion | USD |
| lp_holder_campaign_incentive | LP holder portion | USD |
| yt_holder_campaign_incentive | YT holder portion | USD |
| lp_yt_holder_campaign_incentive | LP+YT holder portion | USD |
| external_incentives | Non-co-bribe campaign incentive total | USD |
| external_incentives_to_lp_holders | External incentives to LP holders | USD |
| external_incentives_to_yt_holders | External incentives to YT holders | USD |
| external_incentives_to_lp_yt_holders | External incentives to LP+YT holders | USD |

#### Holder Counts — stock metrics (cross-day: AVG)
| Column | Description | Unit |
|--------|-------------|------|
| pt_holder_count | PT holder addresses (end-of-day snapshot) | count |
| yt_holder_count | YT holder addresses | count |
| lp_holder_count | LP holder addresses | count |
| pt_and_yt_holder_count | Addresses holding BOTH PT and YT | count |

⚠️ NOT additive across pools — same address appears in multiple pools.
Use AVG or MAX when aggregating across pools, never SUM.

### SQL Examples

#### Protocol-level daily metrics
```sql
SELECT dt,
  SUM(overall_tvl) AS tvl,
  SUM(notional_trading_volume) AS volume,
  SUM(total_swap_fee_usd) + SUM(total_implicit_swap_fee_usd) AS total_swap_fees,
  SUM(expected_yield_fee) AS yield_fee
FROM `pendle-data.analytics.pool_metrics_all_in_one_daily`
WHERE dt >= '2026-03-01' AND dt <= '2026-03-16'
GROUP BY dt ORDER BY dt
```

#### Pool-level weekly metrics with two-layer CTE
```sql
WITH daily AS (
  SELECT pm.dt,
    CONCAT(pm.pool, '_', pm.chain) AS pool_id,
    SUM(pm.overall_tvl) AS tvl,
    SUM(pm.notional_trading_volume) AS volume,
    SUM(pm.expected_yield_fee) AS yield_fee,
    SUM(pm.latest_tv_weighted_implied_yield * pm.overall_tvl) AS iy_num,
    SUM(pm.overall_tvl) AS iy_den
  FROM `pendle-data.analytics.pool_metrics_all_in_one_daily` pm
  WHERE pm.dt >= '2026-03-01' AND pm.dt <= '2026-03-16'
  GROUP BY pm.dt, pool_id
)
SELECT DATE_TRUNC(dt, WEEK) AS week, pool_id,
  AVG(tvl) AS avg_tvl,                -- stock → AVG
  SUM(volume) AS total_volume,         -- flow → SUM
  SUM(yield_fee) AS total_yield_fee,   -- flow → SUM
  SUM(iy_num) / NULLIF(SUM(iy_den), 0) AS weighted_iy  -- rate → weighted
FROM daily GROUP BY 1, 2 ORDER BY week, avg_tvl DESC
```

#### Filter by base_asset via JOIN
```sql
SELECT pm.dt, SUM(pm.overall_tvl) AS eth_tvl
FROM `pendle-data.analytics.pool_metrics_all_in_one_daily` pm
JOIN `pendle-data.analytics.market_meta` mm
  ON pm.pool = mm.pool AND pm.chain = mm.chain_id
WHERE pm.dt >= '2026-03-10' AND pm.dt <= '2026-03-16'
  AND mm.base_asset = 'ETH'
GROUP BY pm.dt ORDER BY pm.dt
```

#### Top 5 pools by yield fee
```sql
SELECT CONCAT(pm.pool, '_', pm.chain) AS pool_id,
  SUM(pm.expected_yield_fee) AS yield_fee, AVG(pm.overall_tvl) AS avg_tvl
FROM `pendle-data.analytics.pool_metrics_all_in_one_daily` pm
WHERE pm.dt >= '2026-03-10' AND pm.dt <= '2026-03-16'
GROUP BY pool_id ORDER BY yield_fee DESC LIMIT 5
```
"""

_MARKET_META = """\
## `pendle-data.analytics.market_meta`

Pool metadata / reference data. One row per pool. No partition key.
Join key to pool_metrics: `pool` + `chain_id` (= pool_metrics.chain).

| Column | Type | Description |
|--------|------|-------------|
| pool | STRING | Pool name (join key) |
| chain_id | INT64 | Chain numeric ID (join key) |
| chain | STRING | Chain name (ethereum, arbitrum, ...) |
| market_id | STRING | chain_id + market address (e.g. "8453-0x6144...") |
| expiry_date | DATE | Market maturity date (at 00:00 UTC) |
| yield_source | STRING | Yield category (e.g. "3-Lending") |
| base_asset | STRING | Asset type (ETH, Stable, BTC) |
| underlying_issuer | STRING | Protocol providing yield (Aave, Lido, ...) |
| fee_tier | FLOAT64 | Swap fee rate (e.g. 0.0002) |
| yield_range_min | FLOAT64 | Liquidity range lower bound |
| yield_range_max | FLOAT64 | Liquidity range upper bound |
| first_log_dt | STRING | Pool start date (may contain timestamp; cast with SAFE_CAST(TRIM(first_log_dt) AS DATE)) |
| protocol_name | STRING | For DeFiLlama cross-reference |
| community_flag | STRING | "Pendle Team" or permissionless |
| underlying_name | STRING | Underlying asset name |
| accounting_asset_name | STRING | Accounting asset name |
| py_unit_name | STRING | What 1 PT redeems to at maturity |
| penco_meta | ARRAY<STRUCT> | Pencosystem metadata |
| initiated_by | STRING | Market initiator |
| asset_desc | STRING | Asset description |

Use for pool discovery: find pool IDs, filter by chain/expiry/yield_source.
For penco_meta: `ARRAY_TO_STRING(ARRAY(SELECT CONCAT(info.protocol,'_',info.category) FROM UNNEST(penco_meta) AS info), ',')`

### SQL Example
```sql
SELECT CONCAT(pool, '_', chain_id) AS pool_id,
  expiry_date, yield_source, base_asset, underlying_issuer
FROM `pendle-data.analytics.market_meta`
WHERE expiry_date > CURRENT_DATE()
ORDER BY expiry_date
```
"""

_PRICE_FEEDS = """\
## `pendle-data.sentio_dump.price_feeds`

Daily token prices. **Partition: date (DATE) — always filter on date.**

| Column | Type | Description |
|--------|------|-------------|
| date | DATE | Price date |
| symbol | STRING | Token symbol (lowercase: "pendle", "btc", "eth", ...) |
| avg_price | FLOAT64 | Average daily price in USD |

### SQL Example
```sql
SELECT date AS dt, avg_price
FROM `pendle-data.sentio_dump.price_feeds`
WHERE symbol = 'pendle'
  AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY date
```
"""

_POOL_METRICS_LIFETIME = """\
## `pendle-data.analytics.pool_metrics_lifetime`

Lifetime aggregated stats per pool. One row per pool. No partition key.

| Column | Type | Description |
|--------|------|-------------|
| pool | STRING | Pool name |
| chain | INT64 | Chain ID |
| pool_ddl | DATE | Pool DDL date |
| first_trade_dt | DATE | First trade date |
| last_trade_dt | DATE | Last trade date |
| min_implied_yield | FLOAT64 | Min IY over lifetime |
| max_implied_yield | FLOAT64 | Max IY over lifetime |
| avg_implied_yield | FLOAT64 | Avg IY over lifetime |
| median_implied_yield | FLOAT64 | Median IY over lifetime |
| avg_amm_tvl | FLOAT64 | Avg AMM TVL |
| avg_overall_tvl | FLOAT64 | Avg overall TVL |
| max_amm_tvl | FLOAT64 | Max AMM TVL |
| max_overall_tvl | FLOAT64 | Max overall TVL |
| avg_notional_trading_volume | FLOAT64 | Avg daily volume |
| avg_notional_trading_volume_limit | FLOAT64 | Avg daily limit volume |
| avg_notional_trading_volume_amm | FLOAT64 | Avg daily AMM volume |
| avg_nodex_notional_trading_volume | FLOAT64 | Avg daily nodex volume |
| avg_swap_fee_usd | FLOAT64 | Avg daily swap fees |
| avg_implicit_swap_fee_usd | FLOAT64 | Avg daily implicit fees |
| avg_limit_swap_fee_usd | FLOAT64 | Avg daily limit fees |
| pool_active_days | INT64 | Days with trading activity |

### SQL Example
```sql
SELECT CONCAT(pool, '_', chain) AS pool_id,
  avg_overall_tvl, avg_implied_yield, pool_active_days
FROM `pendle-data.analytics.pool_metrics_lifetime`
ORDER BY avg_overall_tvl DESC LIMIT 10
```
"""


# ── Pendle-specific tools ─────────────────────────────────────────────

_USER_POOL_TVL_DAILY = """\
## `pendle-data.user_token_balance.user_pool_tvl_daily`

Per-user daily TVL by pool, broken down by token type.
Grain: one row per (user, pool, chain_id, ds). Partition: `ds` (DATE).

### Columns
| Column | Type | Description |
|--------|------|-------------|
| ds | DATE | Date |
| user | STRING | Wallet address |
| pool | STRING | Pool name |
| chain_id | INT64 | Chain ID |
| base_asset | STRING | Pool base asset |
| underlying_issuer | STRING | Yield provider |
| yield_source | STRING | Yield category |
| sy_balance / sy_tvl_usd | NUMERIC | SY token balance and USD value |
| pt_balance / pt_tvl_usd | NUMERIC | PT token balance and USD value |
| yt_balance / yt_tvl_usd | NUMERIC | YT token balance and USD value |
| lp_balance / lp_tvl_usd | NUMERIC | LP token balance and USD value |
| total_pool_tvl_usd | NUMERIC | Total TVL in pool (PT + YT + LP, excludes SY) |
| token_types_count | INT64 | Distinct token types held (SY/PT/YT/LP) |

### SQL Example
```sql
-- Top 10 users by TVL in a specific pool
SELECT user, total_pool_tvl_usd, pt_tvl_usd, yt_tvl_usd, lp_tvl_usd
FROM `pendle-data.user_token_balance.user_pool_tvl_daily`
WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND pool = 'Ethena sUSDE 7MAY2026' AND chain_id = 1
ORDER BY total_pool_tvl_usd DESC
LIMIT 10
```
"""

_USER_TVL_DAILY = """\
## `pendle-data.user_token_balance.user_tvl_daily`

Per-user daily TVL aggregated across all pools.
Grain: one row per (user, ds). Partition: `ds` (DATE).

### Columns
| Column | Type | Description |
|--------|------|-------------|
| ds | DATE | Date |
| user | STRING | Wallet address |
| total_tvl_usd | NUMERIC | Total TVL across all pools |
| total_sy_tvl_usd | NUMERIC | Total SY value across all pools |
| total_pt_tvl_usd | NUMERIC | Total PT value across all pools |
| total_yt_tvl_usd | NUMERIC | Total YT value across all pools |
| total_lp_tvl_usd | NUMERIC | Total LP value across all pools |
| active_pools_count | INT64 | Number of pools with holdings |
| active_chains_count | INT64 | Number of chains with holdings |

### SQL Example
```sql
-- Top 20 users by total TVL
SELECT user, total_tvl_usd, active_pools_count, active_chains_count
FROM `pendle-data.user_token_balance.user_tvl_daily`
WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
ORDER BY total_tvl_usd DESC
LIMIT 20
```
"""

_USER_STATS_PER_POOL = """\
## `pendle-data.sentio_dump.user_stats_per_pool_daily_v1`

Per-user daily trading stats by pool with profile-based user attributes.
Grain: one row per (user_address, pool, chain_id, ds). Partition: `ds` (DATE).

⚠️ **v1 vs v2**: Both tables are active and cover the same grain. Choose by use-case:
- **v1**: granular per-action-type metrics (swap_pt_buy_*, liquidity_add_*, etc.), whale flags, narrative_type. Best for action-type breakdown.
- **v2**: aggregated value_usd/notional_trading_volume, first-action cohort attributes, cross-chain first active dates, money market first use. Best for cohort analysis and retention.

### Key Columns

#### Identity & Profile
- `user_address`, `pool`, `chain_id`, `ds`
- `narrative_type`: market narrative classification
- `wallet_type`: wallet classification
- `prof_is_new_user`: whether user is new
- `prof_first_active_dt`, `prof_lp_first_active_dt`, `prof_pt_first_active_dt`, `prof_yt_first_active_dt`: first active dates (overall and by token type)
- `prof_active_pools_cnt`, `prof_active_lp_pools_cnt`, `prof_active_pt_pools_cnt`, `prof_active_yt_pools_cnt`: active pool counts
- `prof_is_lrt_active`, `prof_is_lsd_active`, `prof_is_rwa_active`, `prof_is_point_active`: category activity flags
- `prof_lp_whale`, `prof_pt_whale`, `prof_yt_whale`: whale flags

#### Liquidity Add (flow → SUM)
- `liquidity_add_amount`, `liquidity_add_market_value_usd`, `liquidity_add_notional_value_usd`
- `liquidity_add_total_swap_fee_usd`, `liquidity_add_total_implicit_swap_fee_usd`
- `liquidity_add_tx_cnt`

#### Liquidity Remove (flow → SUM)
- `liquidity_remove_amount`, `liquidity_remove_market_value_usd`, `liquidity_remove_notional_value_usd`
- `liquidity_remove_total_swap_fee_usd`, `liquidity_remove_total_implicit_swap_fee_usd`
- `liquidity_remove_tx_cnt`

#### Swap PT Buy/Sell (flow → SUM)
- `swap_pt_buy_amount`, `swap_pt_buy_market_value_usd`, `swap_pt_buy_notional_value_usd`
- `swap_pt_buy_total_swap_fee_usd`, `swap_pt_buy_total_implicit_swap_fee_usd`, `swap_pt_buy_tx_cnt`
- `swap_pt_sell_amount`, `swap_pt_sell_market_value_usd`, `swap_pt_sell_notional_value_usd`
- `swap_pt_sell_total_swap_fee_usd`, `swap_pt_sell_total_implicit_swap_fee_usd`, `swap_pt_sell_tx_cnt`

#### Swap YT Buy/Sell (flow → SUM)
- `swap_yt_buy_amount`, `swap_yt_buy_market_value_usd`, `swap_yt_buy_notional_value_usd`
- `swap_yt_buy_total_swap_fee_usd`, `swap_yt_buy_total_implicit_swap_fee_usd`, `swap_yt_buy_tx_cnt`
- `swap_yt_sell_amount`, `swap_yt_sell_market_value_usd`, `swap_yt_sell_notional_value_usd`
- `swap_yt_sell_total_swap_fee_usd`, `swap_yt_sell_total_implicit_swap_fee_usd`, `swap_yt_sell_tx_cnt`

#### Redeem & Mint PY (flow → SUM)
- `redeem_py_amount`, `redeem_py_market_value_usd`, `redeem_py_notional_value_usd`, `redeem_py_tx_cnt`
- `mint_py_amount`, `mint_py_market_value_usd`, `mint_py_notional_value_usd`, `mint_py_tx_cnt`

#### Profile Trading Volume
- `prof_lp_market_trading_volume`, `prof_lp_notional_trading_volume`
- `prof_swap_market_trading_volume`, `prof_swap_notional_trading_volume`

### SQL Example
```sql
-- Top whale LP providers this week
SELECT user_address, pool, chain_id,
  SUM(liquidity_add_market_value_usd) AS total_lp_added_usd,
  MAX(prof_lp_whale) AS is_whale
FROM `pendle-data.sentio_dump.user_stats_per_pool_daily_v1`
WHERE ds >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1, 2, 3
HAVING is_whale = TRUE
ORDER BY total_lp_added_usd DESC
LIMIT 20
```
"""

_USER_STATS_PER_POOL_V2 = """\
## `pendle-data.sentio_dump.user_stats_per_pool_daily_v2`

Per-user daily trading stats by pool with cohort/first-action enrichment.
Grain: one row per (user_address, pool, chain_id, ds). Partition: `ds` (DATE).

⚠️ **v1 vs v2**: Both tables are active and cover the same grain. Choose by use-case:
- **v1**: granular per-action-type metrics (swap_pt_buy_*, liquidity_add_*, etc.), whale flags, narrative_type. Best for action-type breakdown.
- **v2**: aggregated value_usd/notional_trading_volume, first-action cohort attributes, cross-chain first active dates, money market first use. Best for cohort analysis and retention.

### Key Columns

#### Identity & Cohort
- `user_address`, `pool`, `chain_id`, `ds`
- `yield_source`, `base_asset`, `underlying_issuer`
- `first_txn_date` / `first_txn_ts`: user's first ever transaction
- `days_since_first_txn`: tenure in days
- `first_pool`, `first_chain_id`, `first_action_type`, `first_event_type`
- `first_txn_value_usd`, `first_txn_notional_trading_volume`
- `first_pool_yield_source`, `first_pool_base_asset`, `first_pool_underlying_issuer`

#### Daily Trading Activity (flow → SUM)
- `value_usd`: total USD value of transactions on this pool on this date
- `notional_trading_volume`: total notional volume
- `notional_trading_volume_limit`: limit order volume
- `total_swap_fee_usd`: explicit swap fees
- `total_limit_swap_fee_usd`: limit order fees
- `total_implicit_swap_fee_usd`: implicit fees
- `txn_ct`: transaction count

#### Cross-Chain First Active Dates
- `eth_first_active_ds`, `arb_first_active_ds`, `op_first_active_ds`,
  `bsc_first_active_ds`, `mantle_first_active_ds`, `base_first_active_ds`,
  `sonic_first_active_ds`, `bera_first_active_ds`, `hyperevm_first_active_ds`,
  `plasma_first_active_ds`

#### Wallet & Money Market
- `wallet_agents_sorted`, `first_agent`: wallet agent associations
- `syrup_first_use_date`, `morpho_first_use_date`, `euler_first_use_date`,
  `dolomite_first_use_date`, `gearbox_first_use_date`, `zerolend_first_use_date`,
  `avalon_first_use_date`: first PT collateral use per lending protocol

### SQL Example
```sql
-- New users this week and their first action
SELECT user_address, first_txn_date, first_pool, first_action_type,
  first_txn_value_usd, first_pool_base_asset
FROM `pendle-data.sentio_dump.user_stats_per_pool_daily_v2`
WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND first_txn_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY first_txn_date DESC
```
"""

_CROSS_CHAIN_SWAP_INTENTS = """\
## `pendle-data.analytics.cross_chain_swap_intents_curated`

Cross-chain PT swap volume with bridge attribution.
Grain: one row per completed swap intent (`intent_id`). Not partitioned (full table rebuild).

### Key Columns
| Column | Type | Description |
|--------|------|-------------|
| date | DATE | Swap date |
| intent_id | STRING | Unique intent identifier |
| user_address | STRING | Wallet that initiated the swap |
| swap_tx_hash | STRING | On-chain transaction hash |
| action_type | STRING | `BUY_PT` or `SELL_PT` |
| bridge | STRING | Bridge used: `LayerZero` or `Bungee` |
| from_chain_id | INT64 | Source chain |
| to_chain_id | INT64 | Destination chain |
| hub_chain_id | INT64 | Hub chain where PT lives |
| hub_chain_pt | STRING | PT contract address on hub chain |
| token_in | STRING | Input token address |
| token_out | STRING | Output token address |
| pt_amount | FLOAT64 | PT amount (18-decimal adjusted) |
| volume_usd | FLOAT64 | USD volume (PT amount × PT price) |

### Notes
- Bridge logic: LayerZero when source/dest ≠ hub chain for SELL_PT/BUY_PT respectively; Bungee for the reverse leg.

### SQL Example
```sql
-- Daily cross-chain swap volume by bridge (last 30 days)
SELECT date, bridge, action_type,
  COUNT(*) AS swaps,
  ROUND(SUM(volume_usd), 2) AS total_volume_usd
FROM `pendle-data.analytics.cross_chain_swap_intents_curated`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 4 DESC
```
"""

_PT_COLLATERAL_DAILY = """\
## `pendle-data.analytics.pt_collateral_daily_balance`

Daily PT collateral balance across all lending protocols (money markets).
Grain: one row per (`protocol`, `chain_name`, `asset_address`, `market_id`, `ds`).
Partition: `ds` (DATE). Incremental.

Covers 13 protocols: Aave, Avalon, Dolomite, Euler, Gearbox, Hyperlend, Lista,
Morpho, RDNTCapital, Silo, Thetanuts_Finance, ZeroLend, maneki.finance.

### Key Columns
| Column | Type | Description |
|--------|------|-------------|
| ds | DATE | Date (partition key) |
| protocol | STRING | Lending protocol name (Aave, Morpho, Euler, ...) |
| chain_name | STRING | Blockchain name (ethereum, arbitrum, bnb, ...) |
| chain_id | INT64 | Chain numeric ID |
| pool | STRING | Pendle pool name |
| asset_type | STRING | `PT` (native), `PT-CROSS` (cross-chain via OFT), `LP` |
| asset_address | STRING | Token contract address |
| market_id | STRING | Lending market identifier (Morpho market ID, or 'NA') |
| balance | FLOAT64 | Total token balance in this market (token units, not USD) |
| active_holders | INT64 | Users with balance > 0 on this day |
| cumulative_holders | INT64 | Total users who ever held (historical) |
| base_asset | STRING | Underlying asset type (ETH, Stable, BTC) |
| asset_price | FLOAT64 | Token price on this day (balance × asset_price = USD value) |
| expiry_date | DATE | PT expiry date |

### Important Notes
- `balance` is in **token units** — multiply by `asset_price` for USD value.
- Same pool can appear multiple times per protocol if there are multiple `market_id`s (especially Morpho/Lista).
- `PT-CROSS` = PT bridged via OFT to another chain (e.g. Ethereum PT used on BNB Lista). ~8% of total.
- `LP` = LP token used as collateral (rare, ~0.001% of total).
- This table resolves the limitation in pool_metrics where collateral cannot be broken down by protocol.

### SQL Examples
```sql
-- PT collateral by protocol (latest day, USD value)
SELECT protocol, asset_type,
  ROUND(SUM(balance * asset_price), 2) AS total_usd,
  SUM(active_holders) AS total_holders
FROM `pendle-data.analytics.pt_collateral_daily_balance`
WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY 1, 2
ORDER BY total_usd DESC

-- PT collateral for a specific pool across all protocols
SELECT ds, protocol, chain_name, asset_type,
  ROUND(balance * asset_price, 2) AS usd_value, active_holders
FROM `pendle-data.analytics.pt_collateral_daily_balance`
WHERE ds >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND pool = 'Ethena sUSDE 9APR2026'
ORDER BY ds, protocol
```
"""

_MM_USER_COLLATERAL_DAILY = """\
## `pendle-data.analytics.mm_user_collateral_daily_balance`

Per-user daily PT collateral balance in each lending protocol.
Grain: one row per (`user`, `chain_id`, `mm_protocol`, `token_address`, `ds`).
Partition: `ds` (DATE).

Covers all protocols except Gearbox (Gearbox uses credit accounts, tracked separately
in pt_collateral_daily_balance only).

### Key Columns
| Column | Type | Description |
|--------|------|-------------|
| ds | DATE | Date (partition key) |
| user | STRING | Wallet address |
| chain_id | INT64 | Chain ID |
| mm_protocol | STRING | Lending protocol name |
| token_address | STRING | PT/LP token contract address |
| delta | FLOAT64 | Daily balance change (token units) |
| raw_balance | NUMERIC | Cumulative raw balance (wei) |
| balance | FLOAT64 | Normalized balance (token units) |
| asset_price | FLOAT64 | Token price (balance × asset_price = USD) |

### SQL Example
```sql
-- Top 10 users by PT collateral in Morpho (latest day)
SELECT user, mm_protocol, token_address,
  ROUND(balance * asset_price, 2) AS usd_value
FROM `pendle-data.analytics.mm_user_collateral_daily_balance`
WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND mm_protocol = 'Morpho'
  AND balance > 0
ORDER BY usd_value DESC
LIMIT 10
```
"""

_PENDLE_INCOMES_EACH_EPOCH = """\
## `pendle-data.analytics.pendle_incomes_all_in_one_each_epoch`

Per-epoch (Thursday-to-Wednesday weekly cycle) Pendle protocol income aggregates.
Grain: one row per epoch (`epoch_start_date`). Not partitioned (full rebuild).

Aggregates `pendle_incomes_all_in_one_daily` to weekly epochs (week starts Thursday),
joined with realized yield fees, liquid-locker bribes, vePENDLE distributions,
and sPENDLE buyback/airdrop data.

### Key Columns
| Column | Type | Description |
|--------|------|-------------|
| epoch_start_date | DATE | Epoch start (Thursday) — unique key |
| epoch_end_date | DATE | Epoch end (Wednesday, epoch_start_date + 6 days) |
| pendle_emission_amount | FLOAT64 | Total PENDLE tokens emitted in epoch |
| pendle_emission_value | FLOAT64 | USD value of PENDLE emissions |
| explicit_swap_fees | FLOAT64 | Explicit swap fees in USD (AMM + limit) |
| explicit_amm_swap_fees | FLOAT64 | Explicit AMM swap fees in USD |
| explicit_limit_swap_fees | FLOAT64 | Explicit limit-order swap fees in USD |
| implicit_swap_fees | FLOAT64 | Implicit swap fees in USD |
| expected_yield_fees | FLOAT64 | Expected yield fees from non-expired pools |
| expected_expired_yield | FLOAT64 | Expected yield from pools that expired in epoch |
| realized_yield_fees_from_dune_data | FLOAT64 | Realized YT fees from Dune-sourced data |
| explicit_amm_swap_fees_from_dune_data | FLOAT64 | AMM swap fees (Dune-sourced) |
| explicit_limit_swap_fees_from_dune_data | FLOAT64 | Limit swap fees (Dune-sourced) |
| campaign_incentive | FLOAT64 | Total Merkle campaign incentives in USD |
| co_bribe_campaign_incentive | FLOAT64 | Co-bribe portion of campaign incentives |
| lp_holder_campaign_incentive | FLOAT64 | Incentives to LP holders |
| yt_holder_campaign_incentive | FLOAT64 | Incentives to YT holders |
| lp_yt_holder_campaign_incentive | FLOAT64 | Incentives to LP+YT holders |
| epoch_realized_yield_fees | FLOAT64 | Realized yield fees in USD (from realized_yield_fee_weekly) |
| epoch_eqb_bribe | FLOAT64 | Equilibria bribe USD value |
| epoch_penpie_bribe | FLOAT64 | Penpie bribe USD value |
| vependle_monthly_rewards_distributed_in_usd | FLOAT64 | vePENDLE rewards distributed (only set in distribution epochs — implicit distribution flag) |
| vependle_monthly_airdrop_distributed_in_usd | FLOAT64 | vePENDLE airdrop distributed in epoch |
| epoch_spendle_airdrop_in_usd | FLOAT64 | sPENDLE airdrop USD value |
| epoch_spendle_buyback_in_usd | FLOAT64 | sPENDLE buyback USD value (buyback_amount × PENDLE price) |

### Notes
- Epoch = week starting Thursday 00:00 UTC (Pendle's vote epoch convention).
- vePENDLE fields are recorded only in distribution epochs — non-null acts as an implicit "distribution happened" flag.
- For daily granularity use `pendle_incomes_all_in_one_daily` (same metrics, daily grain).

### SQL Example
```sql
-- Last 12 epochs of Pendle revenue breakdown
SELECT epoch_start_date,
  ROUND(explicit_swap_fees + implicit_swap_fees + epoch_realized_yield_fees, 2) AS pendle_revenue_usd,
  ROUND(pendle_emission_value, 2) AS emissions_usd,
  ROUND(campaign_incentive, 2) AS incentives_usd
FROM `pendle-data.analytics.pendle_incomes_all_in_one_each_epoch`
ORDER BY epoch_start_date DESC
LIMIT 12
```
"""

_LIMIT_ORDER_OB_DEPTH = """\
## `pendle-data.pendle_api.limit_order_ob_depth_hourly`

Hourly limit order orderbook depth by implied yield bucket. One row per (hour, chain_id, yt, iy_bucket).
**Partition: DATE(hour) — always filter on DATE(hour).**
Join to market_meta: `LOWER(ob.yt) = LOWER(mm.yt_address) AND CAST(ob.chain_id AS STRING) = CAST(mm.chain_id AS STRING)`.

### Key Concepts

Four order types forming two-sided PT and YT books:
- **TOKEN_FOR_PT** (PT bid): taker pays tokens, receives PT. Bids rest at IY > mid.
- **PT_FOR_TOKEN** (PT ask): maker provides PT for tokens. Asks rest at IY < mid.
- **TOKEN_FOR_YT** (YT bid): taker pays tokens, receives YT. Bids rest at IY < mid.
- **YT_FOR_TOKEN** (YT ask): maker provides YT for tokens. Asks rest at IY > mid.

`iy_bucket` = INT64, implied_yield × 1000. Each bucket = 10 bps interval.
Cumulative columns pre-compute running depth (no need to self-join):
- ASC cumulation (TOKEN_FOR_PT, YT_FOR_TOKEN): depth(N) = SUM of buckets ≤ N.
- DESC cumulation (PT_FOR_TOKEN, TOKEN_FOR_YT): depth(N) = SUM of buckets ≥ N.

### Columns

#### Dimensions
| Column | Type | Description |
|--------|------|-------------|
| hour | DATETIME | Snapshot hour (partition by DATE(hour)) |
| chain_id | INT64 | Chain ID |
| yt | STRING | YT token address |
| pool_name | STRING | Pool name (from market_meta join) |
| market_expiry | TIMESTAMP | Market expiry |
| iy_bucket | INT64 | Implied yield bucket (IY × 1000) |

#### Per-bucket size (flow → SUM across buckets for total depth)
| Column | Description | Unit |
|--------|-------------|------|
| token_for_pt_size_usd | PT bid size at this bucket | USD |
| token_for_pt_size_pt | PT bid size | PT tokens |
| token_for_pt_order_count | PT bid order count | count |
| pt_for_token_size_usd | PT ask size at this bucket | USD |
| pt_for_token_size_pt | PT ask size | PT tokens |
| pt_for_token_order_count | PT ask order count | count |
| token_for_yt_size_usd | YT bid size at this bucket | USD |
| token_for_yt_size_yt | YT bid size | YT tokens |
| token_for_yt_order_count | YT bid order count | count |
| yt_for_token_size_usd | YT ask size at this bucket | USD |
| yt_for_token_size_yt | YT ask size | YT tokens |
| yt_for_token_order_count | YT ask order count | count |

#### Pre-computed cumulative depth
| Column | Description | Direction |
|--------|-------------|-----------|
| token_for_pt_cumulative_usd / _pt | PT bid depth up to this bucket | ASC (≤ bucket) |
| pt_for_token_cumulative_usd / _pt | PT ask depth from this bucket | DESC (≥ bucket) |
| token_for_yt_cumulative_usd / _yt | YT bid depth from this bucket | DESC (≥ bucket) |
| yt_for_token_cumulative_usd / _yt | YT ask depth up to this bucket | ASC (≤ bucket) |

### Aggregation Rules
- Per-bucket size: SUM across buckets for total depth; SUM across hours for volume over time.
- Cumulative columns: do NOT SUM across buckets (already cumulated). Read the value at a specific bucket for depth at that IY level.
- Across pools: SUM USD columns; do NOT sum token columns across different pools.

### SQL Examples

#### Total PT bid/ask depth for a pool at latest hour
```sql
WITH latest AS (
  SELECT MAX(hour) AS h
  FROM `pendle-data.pendle_api.limit_order_ob_depth_hourly`
  WHERE DATE(hour) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND pool_name = 'Ethena sUSDE 29MAY2025'
)
SELECT iy_bucket,
  token_for_pt_cumulative_usd AS pt_bid_depth_usd,
  pt_for_token_cumulative_usd AS pt_ask_depth_usd
FROM `pendle-data.pendle_api.limit_order_ob_depth_hourly`, latest
WHERE hour = latest.h
  AND pool_name = 'Ethena sUSDE 29MAY2025'
ORDER BY iy_bucket
```
"""

_POOL_META_FIELDS = {
    "pool_id": "CONCAT(pool, '_', chain_id) AS pool_id",
    "expiry_date": "expiry_date",
    "expiry_month": "DATE_TRUNC(expiry_date, MONTH) AS expiry_month",
    "yield_source": "yield_source",
    "base_asset": "base_asset",
    "underlying_issuer": "underlying_issuer",
    "chain": "chain",
    "chain_id": "chain_id",
    "market_id": "market_id",
    "fee_tier": "fee_tier",
    "yield_range_min": "yield_range_min",
    "yield_range_max": "yield_range_max",
    "first_log_dt": "first_log_dt",
    "protocol_name": "protocol_name",
    "community_flag": "community_flag",
    "underlying_name": "underlying_name",
    "accounting_asset_name": "accounting_asset_name",
    "py_unit_name": "py_unit_name",
    "initiated_by": "initiated_by",
    "asset_desc": "asset_desc",
}

_ACTIVE_FIELDS = [
    "pool_id", "expiry_date", "yield_source", "base_asset", "underlying_issuer",
]

_ALL_FIELDS = ["pool_id", "base_asset"]


def _register_pendle_tools(mcp, track_fn):
    """Register Pendle-specific MCP tools (pool discovery)."""

    @mcp.tool(
        description=(
            "Get Pendle pool metadata. pool_id contains pool name + expiry "
            "month + chain (e.g. 'Ethena sUSDE 7MAY2026_1').\n\n"
            "is_active_only=true (default): returns active pools with full detail "
            "(pool_id, expiry_date, yield_source, base_asset, "
            "underlying_issuer).\n"
            "is_active_only=false: returns ALL pools (including expired) with "
            "minimal fields (pool_id, base_asset) for name matching.\n\n"
            "Extra fields via 'fields' parameter: expiry_date, expiry_month, "
            "yield_source, chain, chain_id, market_id, fee_tier, "
            "yield_range_min, yield_range_max, first_log_dt, protocol_name, "
            "community_flag, underlying_name, py_unit_name, "
            "accounting_asset_name, initiated_by, asset_desc.\n\n"
            "ALWAYS call this first when users mention pool names. "
            "Fuzzy-match against pool_id to find exact pool_ids, "
            "then use those in run_sql. NEVER use SQL LIKE patterns."
        )
    )
    async def get_pendle_pools_tool(
        is_active_only: bool = True,
        fields: list[str] | str | None = None,
    ) -> str:
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",") if f.strip()]
        track_fn("get_pendle_pools", is_active_only=is_active_only, fields=fields)
        import json as _json
        import pandas_gbq as _pgbq

        if fields:
            selected = fields
        else:
            selected = _ACTIVE_FIELDS if is_active_only else _ALL_FIELDS

        invalid = [f for f in selected if f not in _POOL_META_FIELDS]
        if invalid:
            return _json.dumps({"error": f"Unknown fields: {invalid}. "
                                f"Available: {list(_POOL_META_FIELDS.keys())}"})

        if "pool_id" not in selected:
            selected = ["pool_id"] + list(selected)

        select_exprs = [_POOL_META_FIELDS[f] for f in selected]
        sql = f"SELECT {', '.join(select_exprs)} FROM `pendle-data.analytics.market_meta`"
        if is_active_only:
            sql += " WHERE expiry_date > CURRENT_DATE()"
        sql += " ORDER BY pool_id"

        try:
            df = _pgbq.read_gbq(sql, progress_bar_type=None)
            if df.empty:
                return _json.dumps({"error": "No pools found."})
            for col in df.columns:
                if df[col].dtype.name in ("datetime64[ns]", "dbdate"):
                    df[col] = df[col].astype(str)
            csv = df.to_csv(index=False)
            return _json.dumps({"total_count": len(df), "data": csv})
        except Exception as e:
            return _json.dumps({"error": str(e)})


# ── Product spec ──────────────────────────────────────────────────────

SPEC = ProductSpec(
    product_id="pendle",
    display_name="Pendle Protocol",
    tables=(
        TableSpec(
            "pendle-data.analytics.pool_metrics_all_in_one_daily",
            partition_col="dt",
            description=(
                "Daily pool-level metrics. Grain: one row per pool per day.\n"
                "Key metrics: TVL (overall_tvl, amm_tvl), volume (notional_trading_volume), "
                "swap fees (explicit + implicit), yield fees (expected, realized), "
                "implied yield, LP APY, emissions, campaigns, holder counts.\n"
                "→ Use for: TVL, volume, fees, yield, emissions, holder analysis."
            ),
            catalog=_POOL_METRICS_DAILY,
        ),
        TableSpec(
            "pendle-data.analytics.market_meta",
            description=(
                "Pool metadata / reference data. One row per pool.\n"
                "Fields: pool name, chain, expiry_date, yield_source, base_asset, "
                "underlying_issuer, fee_tier, yield_range, protocol_name, penco_meta.\n"
                "→ Use for: pool discovery, name→ID mapping, JOIN to pool_metrics."
            ),
            catalog=_MARKET_META,
        ),
        TableSpec(
            "pendle-data.sentio_dump.price_feeds",
            partition_col="date",
            description=(
                "Daily token prices (PENDLE, BTC, ETH, and others).\n"
                "Fields: date, symbol, avg_price.\n"
                "→ Use for: token price lookups, market context."
            ),
            catalog=_PRICE_FEEDS,
        ),
        TableSpec(
            "pendle-data.analytics.pool_metrics_lifetime",
            description=(
                "Lifetime aggregated stats per pool since inception.\n"
                "Key metrics: min/max/avg/median implied yield, avg/max TVL, "
                "avg daily volume, pool_active_days.\n"
                "→ Use for: cross-pool comparison, historical performance."
            ),
            catalog=_POOL_METRICS_LIFETIME,
        ),
        # ── User-level tables ─────────────────────────────────────────
        TableSpec(
            "pendle-data.user_token_balance.user_pool_tvl_daily",
            partition_col="ds",
            description=(
                "Per-user daily TVL by pool with token type breakdown (SY/PT/YT/LP).\n"
                "Grain: (user, pool, chain_id, ds).\n"
                "Key metrics: sy/pt/yt/lp_tvl_usd, total_pool_tvl_usd, token_types_count.\n"
                "→ Use for: user holdings per pool, token composition, top holders."
            ),
            catalog=_USER_POOL_TVL_DAILY,
        ),
        TableSpec(
            "pendle-data.user_token_balance.user_tvl_daily",
            partition_col="ds",
            description=(
                "Per-user daily TVL aggregated across all pools.\n"
                "Grain: (user, ds).\n"
                "Key metrics: total_tvl_usd, total by token type, active_pools/chains_count.\n"
                "→ Use for: top users by TVL, user portfolio summary, whale tracking."
            ),
            catalog=_USER_TVL_DAILY,
        ),
        TableSpec(
            "pendle-data.sentio_dump.user_stats_per_pool_daily_v1",
            partition_col="ds",
            description=(
                "Per-user daily trading stats by pool with profile-based attributes.\n"
                "Grain: (user_address, pool, chain_id, ds).\n"
                "Key metrics: liquidity add/remove, swap PT/YT buy/sell, mint/redeem PY "
                "(amount, market_value_usd, notional_value_usd, fees, tx_cnt), "
                "whale flags, narrative_type, wallet_type, profile trading volumes.\n"
                "→ Use for: user trading activity, whale tracking, category analysis.\n"
                "⚠️ For cohort/first-action analysis and retention, use v2 instead."
            ),
            catalog=_USER_STATS_PER_POOL,
        ),
        TableSpec(
            "pendle-data.sentio_dump.user_stats_per_pool_daily_v2",
            partition_col="ds",
            description=(
                "Per-user daily trading stats by pool with cohort/first-action enrichment.\n"
                "Grain: (user_address, pool, chain_id, ds).\n"
                "Key metrics: value_usd, notional_trading_volume, swap fees, txn_ct, "
                "first_txn_date, days_since_first_txn, cross-chain first active dates, "
                "money market first use dates.\n"
                "→ Use for: cohort analysis, new user tracking, retention, cross-chain behavior.\n"
                "⚠️ For per-action-type breakdown (PT buy/sell, LP add/remove), use v1 instead."
            ),
            catalog=_USER_STATS_PER_POOL_V2,
        ),
        # ── Cross-chain swap intents ─────────────────────────────────
        TableSpec(
            "pendle-data.analytics.cross_chain_swap_intents_curated",
            partition_col=None,
            description=(
                "Cross-chain PT swap volume with bridge attribution.\n"
                "Grain: one row per completed intent (intent_id).\n"
                "Key metrics: volume_usd, pt_amount, bridge (LayerZero/Bungee), action_type.\n"
                "→ Use for: cross-chain swap volume, bridge comparison, user cross-chain activity."
            ),
            catalog=_CROSS_CHAIN_SWAP_INTENTS,
        ),
        # ── PT Collateral tables ──────────────────────────────────────
        TableSpec(
            "pendle-data.analytics.pt_collateral_daily_balance",
            partition_col="ds",
            description=(
                "Daily PT collateral balance across all lending protocols (13 MMs).\n"
                "Grain: (protocol, chain_name, asset_address, market_id, ds).\n"
                "Key metrics: balance (token units), asset_price, active/cumulative holders, "
                "asset_type (PT / PT-CROSS / LP).\n"
                "→ Use for: PT collateral by protocol, chain, pool; protocol-level breakdown "
                "that pool_metrics cannot provide."
            ),
            catalog=_PT_COLLATERAL_DAILY,
        ),
        TableSpec(
            "pendle-data.analytics.mm_user_collateral_daily_balance",
            partition_col="ds",
            description=(
                "Per-user daily PT collateral balance in each lending protocol.\n"
                "Grain: (user, chain_id, mm_protocol, token_address, ds).\n"
                "Key metrics: balance, delta, asset_price.\n"
                "→ Use for: top PT collateral holders, per-user breakdown by protocol.\n"
                "Note: covers all protocols except Gearbox."
            ),
            catalog=_MM_USER_COLLATERAL_DAILY,
        ),
        # ── Pendle protocol-level incomes (epoch grain) ──────────────────
        TableSpec(
            "pendle-data.analytics.pendle_incomes_all_in_one_each_epoch",
            partition_col=None,
            description=(
                "Per-epoch (Thursday weekly) Pendle protocol income aggregates.\n"
                "Grain: one row per epoch_start_date.\n"
                "Key metrics: emissions, swap fees (explicit/implicit/AMM/limit), "
                "yield fees (expected/realized), campaign incentives, LL bribes "
                "(eqb/penpie), vePENDLE distributions, sPENDLE buyback/airdrop.\n"
                "→ Use for: weekly/epoch-level Pendle revenue, emissions, incentive analysis."
            ),
            catalog=_PENDLE_INCOMES_EACH_EPOCH,
        ),
        # ── Limit order orderbook depth ──────────────────────────────────
        TableSpec(
            "pendle-data.pendle_api.limit_order_ob_depth_hourly",
            partition_col="DATE(hour)",
            description=(
                "Pendle v2 (V2) limit order orderbook depth by IY bucket. "
                "Grain: (hour, chain_id, yt, iy_bucket).\n"
                "Key metrics: per-bucket size (USD/tokens) for PT bid/ask and YT bid/ask, "
                "pre-computed cumulative depth, order counts.\n"
                "→ Use for: Pendle V2 orderbook depth, liquidity distribution by IY level, "
                "bid-ask spread, limit order activity. NOT Boros orderbook."
            ),
            catalog=_LIMIT_ORDER_OB_DEPTH,
        ),
    ),
    context=_CONTEXT,
    tool_description=(
        "Returns the Pendle data catalog INDEX: business context, analysis rules, "
        "and table summaries with key metrics.\n\n"
        "CALL THIS FIRST before writing any Pendle SQL query. "
        "Then call get_pendle_table_detail(table_name) for full column definitions."
    ),
    table_detail_description=(
        "Full column definitions, aggregation rules, and SQL examples for a "
        "Pendle Protocol table (also known as Pendle v2 or 'v2'). "
        "For Boros margin trading data, use get_boros_table_detail instead.\n\n"
        "Available tables: pool_metrics_all_in_one_daily, market_meta, price_feeds, "
        "pool_metrics_lifetime, user_pool_tvl_daily, user_tvl_daily, "
        "user_stats_per_pool_daily_v1, user_stats_per_pool_daily_v2, "
        "cross_chain_swap_intents_curated, pt_collateral_daily_balance, "
        "mm_user_collateral_daily_balance, pendle_incomes_all_in_one_each_epoch, "
        "limit_order_ob_depth_hourly."
    ),
    register_extra_tools=_register_pendle_tools,
)
