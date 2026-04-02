"""
Frontend Tracking product specification.

Enriched Mixpanel event tables for V2 and Boros, linking frontend behavior
to on-chain transactions where possible.
"""

from . import ProductSpec, TableSpec


_CONTEXT = """\
# Frontend Tracking Data Catalog

## Overview

Enriched frontend event data from Mixpanel, combining user browsing behavior
with on-chain transaction data. Two tables: one for Pendle V2, one for Boros.

Both tables originate from `mixpanel_events_curated`, which handles:
- Event decoding, deduplication, session detection (30-min inactivity gap)
- Wallet forward-fill (from Wallet Connected events) and backward-fill (within session)
- App identification (v2 / boros via properties.app or $current_url)

## ⚠️ CRITICAL: Query Size Warning

These tables are LARGE (~75K rows/day for V2, ~4K/day for Boros).
ALWAYS apply tight filters to avoid returning too much data:

- **Date filter**: query 1 day at a time, or at most 7 days when analyzing all users. NEVER query a full history without aggregation.
- **User filter**: when analyzing specific users, filter by wallet_address (max 10-20 users).
- **Event filter**: filter by event_name for funnel analysis, not SELECT *.
- **Aggregation**: for trends, GROUP BY DATE(event_time) and COUNT/SUM — don't return raw events.

Example anti-pattern (BAD): `SELECT * WHERE DATE(event_time) >= '2026-03-01'` → millions of rows
Example good pattern: `SELECT DATE(event_time), event_name, COUNT(*) GROUP BY 1, 2 WHERE DATE(event_time) = '2026-03-18'`

## Identity

- `device_id`: browser/device identifier (always present, even without wallet)
- `session_id`: per-device session ID (timestamp of first event in session)
- `wallet_address`: user wallet (may be NULL for anonymous sessions — ~30% of sessions have no wallet)
- One device can connect multiple wallets; one wallet can appear on multiple devices
- Boros enriched: wallet extracted from event properties (more complete than session-level fill)

## Session Model

- Session = continuous activity on one device with <30 min gap between events
- `session_id` = formatted timestamp of the session's first event
- Average session: ~10 events
- Wallet is forward-filled (events after connect inherit the wallet) and backward-filled
  within the same session (events before connect get the wallet too)
"""

_V2_ENRICHED = """\
## `pendle-data.frontend_tracking.v2_mixpanel_events_enriched`

Pendle V2 frontend events enriched with on-chain transaction data.
Grain: one row per event (`device_id`, `insert_id`). Partition: `DATE(event_time)`.

Only V2 events (app = 'v2'). ~75K rows/day.

### On-chain enrichment (via deterministic keys, not time-window matching)

Three JOINs link frontend events to on-chain data:
1. **txn_hash** → trading volume, fees from `user_activity_log` (Contract Interaction events with success=true)
2. **market_address** → pool name from `market_meta` (Market View / Pool View events)
3. **order_id** → limit order fill volume from `effective_trade_info` (Limit Order events)

### Key Columns

#### Core
- `device_id`, `session_id`, `event_time`, `event_name`, `wallet_address`, `wallet_agent`

## V2 Event Types (event_name values)

| Event Name | Stage | Description |
|---|---|---|
| `$mp_web_page_view` | Awareness | Any page load (Mixpanel auto-track) |
| `Wallet Connected` | Awareness | User connects wallet |
| `Dashboard View` | Awareness | Dashboard page viewed |
| `Market View` | Awareness | Market list page viewed |
| `Market Filtered View` | Consideration | Market list with filters applied |
| `Pool View` | Consideration | Individual pool page viewed |
| `Pool Click` | Consideration | Pool clicked from list |
| `Market PT Click` / `Market YT Click` | Consideration | PT or YT tab clicked on market |
| `Sort Market List` | Consideration | Market list sorted |
| `Toggle Market Main Tab` / `Toggle Market Secondary Tab` | Consideration | Tab switching on market page |
| `Dashboard Single Position View` | Consideration | Position detail viewed |
| `Pool Filtered View` | Consideration | Pool page with filters |
| `Contract Interaction` | Activation | On-chain transaction initiated (swap, addLiquidity, etc.) |
| `Contract Interaction (Approve)` | Activation | Token approval transaction |
| `Contract Interaction (Limit Order)` | Activation | Limit order placed |

#### Structured Properties (extracted from raw JSON)
- `market_view_mode`: view mode for market/prime market views
- `pools_view_mode`: view mode for pool views
- `visited_market_address` / `clicked_market_address`: market address from view/click events
- `contract_action`: action type (e.g. swap, addLiquidity) from Contract Interaction
- `contract_action_state`: success/failure
- `contract_action_txn_hash`: on-chain tx hash (success only)
- `contract_action_limit_order_hash`: limit order ID

#### On-chain Data (from JOINs)
- `visited_pool`: pool name (from market_address → market_meta)
- `onchain_user_address`: on-chain wallet (from txn_hash match)
- `onchain_value_usd`: transaction USD value
- `onchain_notional_trading_volume`: notional volume
- `onchain_total_swap_fee_usd`, `onchain_total_implicit_swap_fee_usd`, `onchain_total_limit_swap_fee_usd`
- `filled_limit_order_notional_volume`: limit order fill amount
- `properties`: raw Mixpanel event JSON payload for ad-hoc field access

### SQL Example
```sql
-- Conversion funnel: Market View → Contract Interaction → On-chain success (last 7 days)
WITH sessions AS (
  SELECT session_id, device_id, wallet_address,
    COUNTIF(event_name = 'Market View') AS views,
    COUNTIF(event_name = 'Contract Interaction') AS interactions,
    COUNTIF(contract_action_state = 'true') AS successes,
    SUM(onchain_value_usd) AS total_value_usd
  FROM `pendle-data.frontend_tracking.v2_mixpanel_events_enriched`
  WHERE DATE(event_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1, 2, 3
)
SELECT
  COUNT(*) AS total_sessions,
  COUNTIF(views > 0) AS sessions_with_view,
  COUNTIF(interactions > 0) AS sessions_with_interaction,
  COUNTIF(successes > 0) AS sessions_with_success,
  ROUND(SUM(total_value_usd), 2) AS total_value_usd
FROM sessions
WHERE wallet_address IS NOT NULL
```
"""

_BOROS_ENRICHED = """\
## `pendle-data.frontend_tracking.boros_mixpanel_events_enriched`

Boros frontend events with structured property extraction.
Grain: one row per event (`device_id`, `insert_id`). Partition: `DATE(event_time)`.

Only Boros events (app = 'boros'). ~4K rows/day.

### Key difference from V2 enriched
- **No on-chain JOINs** — Boros order_submitted doesn't include txn_hash (orders are off-chain, matching is async)
- **wallet_address from properties** — more complete than curated forward-fill
  (Boros events include wallet_address in properties after connect)

### Key Columns

#### Core
- `device_id`, `session_id`, `event_time`, `event_name`, `wallet_address`, `wallet_agent`
- `device_type`, `environment`, `source`

#### Market Context
- `market`: market pair (e.g. 'BTCUSDT', 'SOLUSDC')
- `market_id`: numeric market ID (matches boros_analytics.market_meta.id)
- `exchange`: exchange name (Binance, Hyperliquid, Lighter, etc.)
- `collateral`: collateral token

#### Order (boros_order_submitted, boros_order_form_interacted)
- `direction`: long / short
- `order_type`: limit / market
- `margin_mode`: cross / isolated
- `leverage`: leverage multiplier
- `notional_size_yu`, `notional_size_usd`: order size
- `implied_apr`, `underlying_apr`: APR at time of order

#### Deposit (boros_deposit_initiated)
- `deposit_collateral_asset`, `deposit_chain`, `deposit_method`
- `deposit_amount`, `deposit_amount_usd`

#### Strategy (boros_strategy_executed)
- `strategy_type`: e.g. cross_exchange_arbitrage
- `strategy_capital_usd`, `strategy_fixed_apr_pct`, `strategy_max_roi_pct`

#### Other
- `page`: page name (boros_page_viewed)
- `peepo_input_type`, `peepo_question_text`: chatbot interactions
- `referral_code`: referral attribution
- `tx_hash`: only from boros_trading_rewards_claimed
- `rewards_accrued`: reward amount claimed
- `properties`: raw Mixpanel event JSON payload for ad-hoc field access

## Boros Event Types (event_name values)

| Event Name | Stage | Description |
|---|---|---|
| `boros_session_start` | Awareness | Any Boros page load (page field: markets/portfolio/vault/etc.) |
| `boros_wallet_connected` | Awareness | Wallet connect on Boros |
| `boros_referral_link_landed` | Awareness | Arrived via referral link |
| `boros_market_clicked` | Consideration | Market selected (has market, exchange, implied_apr) |
| `boros_orderbook_interacted` | Consideration | Orderbook row clicked |
| `boros_rate_chart_interacted` | Consideration | Rate chart interaction session |
| `boros_market_trades_tab_viewed` | Consideration | Switched to trades tab |
| `boros_get_started_page_viewed` | Consideration | Get Started page |
| `boros_get_started_searched` | Consideration | Strategy search executed |
| `boros_get_started_rate_prefill_clicked` | Consideration | Quick-fill button clicked (Current/7dma/30dma) |
| `boros_get_started_card_connect_wallet_clicked` | Consideration | Connect Wallet clicked on strategy card |
| `boros_get_started_card_market_page_clicked` | Consideration | Market Page clicked on strategy card |
| `boros_get_started_chart_interacted` | Consideration | Historical funding rate chart interaction |
| `boros_peepo_opened` | Consideration | Chatbot opened |
| `boros_peepo_question_asked` | Consideration | Chatbot question submitted |
| `boros_peepo_closed` | Consideration | Chatbot closed |
| `boros_strategy_page_viewed` | Consideration | Strategy page viewed |
| `boros_strategy_card_clicked` | Consideration | Strategy card clicked |
| `boros_vault_page_viewed` | Consideration | Liquidity Vaults page viewed |
| `boros_leaderboard_viewed` | Consideration | Leaderboard page viewed |
| `boros_onboarding_modal_shown` | Onboarding | Welcome to Boros modal displayed |
| `boros_onboarding_cta_clicked` | Onboarding | CTA clicked in Welcome modal (boros_academy/in_app_walkthrough) |
| `boros_walkthrough_step_completed` | Onboarding | Walkthrough step completed |
| `boros_walkthrough_completed` | Onboarding | Full walkthrough finished |
| `boros_deposit_modal_opened` | Activation | Deposit modal opened |
| `boros_deposit_method_selected` | Activation | My Wallet or External Transfer selected |
| `boros_deposit_chain_selected` | Activation | Chain selected for external transfer |
| `boros_deposit_initiated` | Activation | Deposit transaction confirmed |
| `boros_login_clicked` | Activation | Login button clicked (pre-trade) |
| `boros_order_form_interacted` | Activation | Order form edited (has direction, order_type) |
| `boros_order_submitted` | Activation | Order placed (has full order details) |
| `boros_strategy_executed` | Engagement | Strategy flow completed |
| `boros_tp_sl_set` | Engagement | TP/SL set on position |
| `boros_vault_deposit_initiated` | Engagement | Vault deposit confirmed |
| `boros_vault_withdraw_initiated` | Engagement | Vault withdrawal initiated |
| `boros_portfolio_page_viewed` | Engagement | Portfolio viewed (has balance) |
| `boros_settlement_history_viewed` | Engagement | Settlement history viewed |
| `boros_account_page_viewed` | Monetization | Account page viewed (has volume, rewards) |
| `boros_trading_rewards_claimed` | Monetization | Trading rewards claimed (has tx_hash) |
| `boros_referral_code_created` | Monetization | Referral code created |
| `boros_referral_code_used` | Monetization | Referral code applied |
| `boros_referral_rewards_claimed` | Monetization | Referral rewards claimed |
| `boros_withdraw_initiated` | Monetization | Collateral withdrawal initiated |

### SQL Example
```sql
-- Boros order submission funnel by market (last 7 days)
SELECT market, exchange,
  COUNTIF(event_name = 'boros_market_clicked') AS market_clicks,
  COUNTIF(event_name = 'boros_order_form_interacted') AS form_interactions,
  COUNTIF(event_name = 'boros_order_submitted') AS orders_submitted,
  ROUND(SUM(CASE WHEN event_name = 'boros_order_submitted' THEN notional_size_usd END), 2) AS total_order_usd
FROM `pendle-data.frontend_tracking.boros_mixpanel_events_enriched`
WHERE DATE(event_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND market IS NOT NULL
GROUP BY 1, 2
ORDER BY orders_submitted DESC

## Funnel Stages

| Stage | Definition | Data Source |
|---|---|---|
| **Awareness** | Page view, wallet connect | Frontend (these tables) |
| **Consideration** | Market click, orderbook interaction, chart usage | Frontend (these tables) |
| **Activation** | First on-chain trade | On-chain (pendle/boros metrics tables) |
| **Engagement** | 3+ trades in 30 days | On-chain |
| **Monetization** | ≥$50 lifetime fees + active | On-chain |
```
"""


SPEC = ProductSpec(
    product_id="frontend_tracking",
    display_name="Frontend Tracking",
    tables=(
        TableSpec(
            "pendle-data.frontend_tracking.v2_mixpanel_events_enriched",
            partition_col="event_time",
            description=(
                "V2 frontend events enriched with on-chain data. ~75K rows/day.\n"
                "Key: txn_hash→trading data, market_address→pool name, order_id→fill volume.\n"
                "Columns: event_name, wallet_address, visited_pool, contract_action, "
                "onchain_value_usd, onchain_trading_volume, onchain_fees.\n"
                "→ Use for: conversion funnels, feature attribution, browse-to-trade analysis."
            ),
            catalog=_V2_ENRICHED,
        ),
        TableSpec(
            "pendle-data.frontend_tracking.boros_mixpanel_events_enriched",
            partition_col="event_time",
            description=(
                "Boros frontend events with structured properties. ~4K rows/day.\n"
                "Key: market, exchange, direction, order_type, deposit, strategy fields.\n"
                "No on-chain JOINs (Boros orders don't have txn_hash).\n"
                "→ Use for: Boros funnel analysis, order flow, deposit tracking, strategy usage."
            ),
            catalog=_BOROS_ENRICHED,
        ),
    ),
    context=_CONTEXT,
    tool_description=(
        "Returns the Frontend Tracking catalog INDEX: enriched Mixpanel event tables "
        "for V2 and Boros, with on-chain enrichment details and funnel analysis patterns.\n\n"
        "CALL THIS when analyzing user behavior, conversion funnels, or feature attribution. "
        "Then call get_frontend_tracking_table_detail(table_name) for full column definitions."
    ),
    table_detail_description=(
        "Full column definitions, aggregation rules, and SQL examples for a "
        "Frontend Tracking table (enriched Mixpanel events for Pendle V2 and Boros).\n\n"
        "Available tables: v2_mixpanel_events_enriched, boros_mixpanel_events_enriched."
    ),
    register_extra_tools=None,
)
