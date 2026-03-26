---
description: Backend responders (pendle-backend-v3/apps/responder) — 8 handlers that execute on-chain risk actions in response to triggerer jobs
last_updated: 2026-03-17
related:
  - offchain-bots/overview.md
  - offchain-bots/backend-triggerers.md
  - contracts/risk-bots.md
  - contracts/bots-facets.md
---

# Backend Responders — Detailed Reference

Source: `pendle-backend-v3/apps/responder/src/responses/`. Eight handlers that receive typed jobs from the `RESPONDER_PROTOCOL_QUEUE` and execute on-chain actions via the BotController.

---

## Architecture

```
RESPONDER_PROTOCOL_QUEUE (concurrency 10)
    ↓
ResponseProtocol Dispatcher (routes by job type)
    ↓
Per-Handler Queues (HANDLE_*_QUEUE)
    ↓ optional batching
Handler Services
    ↓ prepares transactions
TRANSACTION_EXECUTOR_QUEUE
    ↓ prioritized, deduplicated
On-Chain Execution (BotController multicall)
```

### Routing

| Job Type | Routes To |
|----------|-----------|
| `HealthChange` | Pauser, PublicCanceling, SuspiciousTrader, Deleverage, Liquidate, Alerts |
| `OIChange` | ClosingOnlyMode |
| `AbnormalTrading` | SuspiciousTrader |
| `SuspiciousWithdrawal` | SuspiciousTrader |
| `AbnormalOI` | SuspiciousTrader |
| `HealthJumpOrderCancel` | HealthJumpOrderCancel |

`HealthChange` fans out to 6 handlers — each independently decides whether to act based on health thresholds.

### Priority System

Lower number = higher priority. All responder actions compete for the same transaction executor:

| Service | Priority |
|---------|----------|
| Pauser | 10 |
| Deleverager | 20 |
| Red Zone | 30 |
| Yellow Zone | 31 |
| Liquidator | 40 |
| Suspicious Trader | 50 |
| Health Jump Cancel | 60 |
| OOB Order Purge | 70 |
| Closing-Only Mode | 80 |
| Public Canceling | 90 |

### Transaction Execution

Multi-bot support: multiple bot accounts from `RESPONDER_PRIVATE_KEY` (CSV). Per-bot nonce tracking, dynamic RPC rotation. Native balance synced every 5 minutes.

### Deduplication

Three mechanisms:
1. **BullMQ native**: `deduplication: { id }` prevents duplicate job additions within dedup window
2. **Custom DedupService**: in-memory Set with 1-minute TTL, cleaned every 10s. Used by Deleverage and Liquidate batchers
3. **Redis locking**: CLO enable timestamp with 30-minute TTL prevents rapid toggling

### Batching

Configurable per handler: `maxBatchSize`, `flushIntervalMs`, optional `shouldSplitFn`. Used by Health Monitoring (100 items / 50ms), Deleverage, and Liquidate.

---

## 1. Pauser

**Queue**: `HANDLE_PAUSER_QUEUE` | **Priority**: 10 (highest)

**Triggered by**: `HealthChange` with health ≤ `pauseThreshold`

### Pre-Checks

- Health still below `pauseThresHR` (on-chain, cached 1 hour in Redis)
- `maintMargin ≥ smallMMThreshold[tokenId]` — don't pause for tiny accounts
- Not all markets for that tokenId already paused
- At least one unpaused market exists for tokenId

### Execution

`PauserFacet.pauseMarkets(marketAcc, marketIds[])` — pauses all unpaused markets for the user's token.

**Deduplication**: by `marketIds.join(',')` — prevents duplicate pause attempts for same market set.

---

## 2. Deleverager

**Queue**: `HANDLE_DELEVERAGE_QUEUE` | **Priority**: 20

**Triggered by**: `HealthChange` with health ≤ `deleverageThreshold`

### Two Execution Paths

**Bad debt path** (`totalValue < 0`):
- Immediate detection, calculates bad debt parameters via `BadDebtHelper`
- Sends `P1_PAUSE_DELEVERAGE` alert for manual intervention
- No automated on-chain execution (manual review required)

**Normal path** (`totalValue ≥ 0`, health below threshold):
1. Filter losers: health ≤ threshold AND has positions
2. For each loser: fetch margin, determine if projection needed (FundingRateMode.Settled)
3. Group positions by `(marketId, side)`
4. Calculate deleverage factor via on-chain simulation: `delevFactor = 1 - (value / (mm × desiredHR) - payment)`
5. Compute `sizeToDeleverage = size × factor` (or full size if smallMM)
6. Find eligible winners per position via `NormalHelper` (must have opposite positions)
7. Merge winner calls per loser, truncate if total winners exceed `maxWinnersPerCall` (set `allowPartial = true`)

### Execution

`BotMiscFacet.multicall([DeleveragerFacet.deleverageToHealth(...)])` — one multicall per loser with all their market positions.

**Deduplication**: via `DeleverageDedupService` (1-minute lifetime). Configurable batch size and flush interval.

---

## 3. Liquidator

**Queue**: `HANDLE_LIQUIDATE_QUEUE` | **Priority**: 40

**Triggered by**: `HealthChange` with health ≤ `liquidateThreshold`

### Pre-Flight

- Verify health still ≤ threshold
- Get all positions sorted by `|size|` descending (largest first)

### Liquidation Params

| Condition | `maxVioHealthRatio` | `minProfit` |
|-----------|-------------------|-------------|
| `maintMargin < smallMMThreshold` | 0 | 0 |
| Low health | `okHealthThreshold` | 0 |
| Normal | `okHealthThreshold` | `minProfit[tokenId]` |

### Execution

1. **Simulate**: `LiquidationExecutor.simulateBatchLiquidate(params)` — tests all liquidations
2. **Filter**: only simulation successes proceed
3. **Execute**: `BotMiscFacet.multicall([LiquidationExecutor.executeLiquidation(...)])` for successful params
4. Alert `P3_RISK_EVENTS` on failures

**Deduplication**: via `LiquidateDedupService` (1-minute lifetime). Configurable batch size and flush interval.

---

## 4. Zone Responder

**Queue**: `HANDLE_ZONE_QUEUE` | **Priority**: 30 (red) / 31 (yellow)

Implements a multi-metric risk zone system with 5 independent levers.

### Risk Metrics

| Metric | Window | Calculation |
|--------|--------|-------------|
| **Liquidation Cost (lc)** | Configurable snapshots | `min(longLiqCost, shortLiqCost) / totalOI` |
| **Unhealthy Volume (uv)** | Current | `max(lvShort, lvLong)` — sum of positions beyond mark price |
| **Price Deviation (pd)** | Configurable minutes | Deviation of traded rates from mark rate (orderbook + AMM data) |
| **Deleverage Point Diff** | Current | Distance from mark price to deleverage thresholds (long/short sides) |

Each metric has WHITE/YELLOW/RED thresholds.

### Zone Levels

`NONE → WHITE → YELLOW → RED → BLACK` (escalation path)

### 5 Levers (Red Zone)

All lever actions are called through the **ZoneResponder** contract (standalone, not a BotController facet). ZoneResponder stores pre-configured red/white values and internally calls Market/MarketHub.

| Lever | Red Zone Action | ZoneResponder Call | Internal Call |
|-------|----------------|-------------------|---------------|
| Cooldown | Increase global withdrawal cooldown | `increaseGlobalCooldown()` | → `MarketHub.setGlobalCooldown(_redGlobalCooldown)` |
| Liquidation Incentive | Boost LiqSettings base/slope | `increaseLiquidationIncentive(marketId)` | → `Market.setGlobalLiquidationSettings(_redLiqSettings)` |
| Rate Deviation Bound | Tighten acceptable rate ranges | `decreaseRateDeviationBound(marketId)` | → `Market.setGlobalRateBoundConfig()` + `setGlobalLimitOrderConfig()` |
| CLO | Prevent new position growth | `turnOnCLO(marketId)` | → `Market.setGlobalStatus(CLO)` (requires current status = GOOD) |
| Strict Health | Enforce enhanced margin validation | `turnOnStrictHealthCheck(marketId)` | → `MarketHub.enableStrictHealthCheck(marketId)` |

### White Zone (Reset)

White zone resets each lever to pre-configured normal values via mirror functions:

| Lever | ZoneResponder Call | Internal Call |
|-------|-------------------|---------------|
| Cooldown | `resetGlobalCooldown()` | → `MarketHub.setGlobalCooldown(_whiteGlobalCooldown)` |
| Liquidation Incentive | `resetLiquidationIncentive(marketId)` | → `Market.setGlobalLiquidationSettings(_whiteLiqSettings)` |
| Rate Deviation Bound | `resetRateDeviationBound(marketId)` | → `Market.setGlobalRateBoundConfig()` + `setGlobalLimitOrderConfig()` |
| CLO | `turnOffCLO(marketId)` | → `Market.setGlobalStatus(GOOD)` (requires current status = CLO) |
| Strict Health | `turnOffStrictHealthCheck(marketId)` | → `MarketHub.disableStrictHealthCheck(marketId)` |

Red/white values are pre-configured via admin-only setters (`setRedGlobalCooldown`, `setRedLiqSettings`, `setRedRateDeviationConfig` / `setWhite...`).

### 30-Minute CLO Lockout

When zone transitions to RED, CLO is locked for 30 minutes via `cloEnableLockedAt` in MongoDB. Prevents rapid CLO toggling during volatile periods.

---

## 5. Suspicious Trader

**Queue**: `HANDLE_SUSPICIOUS_TRADER_QUEUE` | **Priority**: 50

**Triggered by**: Multiple job types with different logic per source.

### Per-Source Handling

| Source | Detection | Action |
|--------|-----------|--------|
| `HealthChange` | health ≤ healthThreshold | Record as `CRITICAL_HEALTH` |
| `AbnormalTrading` | No re-validation | Record reason (`SHORT_POSITION_TIME` or `HIGH_TRADE_NEAR_NEXT_PAYMENT_COUNT`) |
| `AbnormalOI` | Re-validate: position still > `minSusOi` | Record as `HIGH_OI` |
| `SuspiciousWithdrawal` + large | `isLargeWithdrawal = true` | Record as `BIG_WITHDRAWAL` |
| `SuspiciousWithdrawal` + quota | `!fastApproved` | Restrict on-chain + record |

### DB Recording

Upserts `SuspiciousTrader` document per root address: `{ root, reason, detectedAt, isWhitelisted }`.

### On-Chain Action

`WithdrawalPoliceFacet.restrictWithdrawalUnconditionally(root)` — only for suspicious withdrawals that are not fast-approved.

### Alerting

- Fast-approved large withdrawals → `P3_RISK_EVENTS` (logged but not restricted)
- Restricted withdrawals → `P2_SUS_WITHDRAWAL`

---

## 6. Health Jump Order Cancel

**Queue**: `HANDLE_HEALTH_JUMP_ORDER_CANCEL_QUEUE` | **Priority**: 60

**Triggered by**: `HealthJumpOrderCancel` jobs from triggerer.

### Execution

Receives proof from triggerer: `{ marketAcc, isProj, proofs: [{ marketId, orderIds[] }] }`.

If `isProj = true`: includes funding rate proofs for each market (projected FIndex values).

**On-chain**: `OrderCancellerFacet.forceCancelAllHealthJump(marketAcc, fIndexUpdates[], proofs[])`

**Deduplication**: by `marketAcc`.

---

## 7. Closing-Only Mode

**Queue**: `HANDLE_CLOSING_ONLY_MODE_QUEUE` | **Priority**: 80

**Triggered by**: `OIChange` jobs from OI Monitoring triggerer.

### CLO Toggle Logic

**Turn ON** (all must be true):
- `OI ≥ upperThres`
- `marketStatus === GOOD`
- Execute: `CLOSetterFacet.toggleCLO(marketId)`
- On success: store CLO enable timestamp in Redis (30-min TTL)

**Turn OFF** (all must be true):
- `OI < lowerThres`
- `marketStatus === CLO`
- `zone !== RED` (not in crisis)
- `now - cloEnabledTimestamp ≥ 30 min` OR `cloEnableLockedAt = null` (zone responder not locked)
- Execute: `CLOSetterFacet.toggleCLO(marketId)`

### 30-Minute Lockout

Enforced via Redis TTL. Prevents rapid CLO on/off oscillation when OI hovers near thresholds.

**Deduplication**: by `marketId + notionalOI`.

---

## 8. Public Canceling (Force Cancel Risky)

**Queue**: `HANDLE_PUBLIC_CANCELING_QUEUE` | **Priority**: 90 (lowest)

**Triggered by**: `HealthChange` with health ≤ `riskyThresHR`

### Pre-Check

- Verify health still < `riskyThresHR` (on-chain `MarketHub.getRiskyThresHR()`, cached 1 hour in Redis)
- Filter to positions with active orders in non-expired markets

### Execution

`OrderCancellerFacet.forceCancelAllRiskyUser(marketAcc)` — cancels all open orders for the risky user.

**Deduplication**: by `marketAcc`.

---

## Alert Channels

All responders share the same alert infrastructure:

| Channel | Level | Examples |
|---------|-------|---------|
| `P1_RED_ZONE` (11) | Critical | Zone transitions to red |
| `P1_PAUSE_DELEVERAGE` (12) | Critical | Markets paused, bad debt detected |
| `P1_SKIP_FUNDING` (13) | Critical | Funding rate update failures |
| `P1_BOTS_DEAD` (14) | Critical | Bot process failures |
| `P1_INFRA_DEAD` (15) | Critical | Infrastructure failures |
| `P2_SUS_WITHDRAWAL` (21) | High | Withdrawals restricted |
| `P2_YELLOW_ZONE` (22) | High | Zone warnings |
| `P2_MARKET_MAKER_DEAD` (23) | High | MM connectivity issues |
| `P3_RISK_EVENTS` (30) | Info | Simulation failures, suspicious traders logged |
| `P3_BOT_ACTIVITIES` (31) | Info | Liquidations executed, routine operations |

---

## MongoDB Models

| Model | Used By |
|-------|---------|
| `PositionInSync` | Health Jump Cancel (active positions) |
| `LimitOrderInSync` | Health Jump Cancel (active orders) |
| `PnlTransactionInSync` | Transaction Analysis (trade history) |
| `AbnormalTradingStats` | Transaction Analysis (per-user metrics) |
| `SuspiciousTrader` | Suspicious Trader (flagged accounts) |
| `BotZoneResponder` | Zone Responder (zone state + CLO lock) |
| `DailyFastWithdrawalTotal` | Withdrawal Monitoring (daily quotas) |
| `MarketSnapshot1m` | Zone Responder (price deviation metrics) |
| `AmmSnapshot1m` | Zone Responder (AMM state for zone detection) |
| `OrderBooks` | Zone Responder (orderbook data) |
