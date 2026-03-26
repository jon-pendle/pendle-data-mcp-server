---
description: Backend triggerers (pendle-backend-v3/apps/sync) — 6 event-driven handlers that detect risk conditions and emit jobs to the responder queue
last_updated: 2026-03-16
related:
  - offchain-bots/overview.md
  - offchain-bots/backend-responders.md
  - contracts/risk-bots.md
  - contracts/bots-facets.md
---

# Backend Triggerers — Detailed Reference

Source: `pendle-backend-v3/apps/sync/src/triggerer/`. Six handlers that detect risk conditions from on-chain events and periodic cron jobs, then emit typed jobs to the `RESPONDER_PROTOCOL_QUEUE` via BullMQ.

---

## Architecture

```
On-Chain Events (position changes, transfers, market data)
    ↓
TRIGGERER_EVENT_QUEUE (concurrency 10)
    ↓ routes by event type
Triggerer Service → 6 Handler Services
    ↓ each handler detects conditions
    ↓ emits typed jobs
RESPONDER_PROTOCOL_QUEUE
    ↓
Response Protocol Dispatcher (see offchain-backend-responders.md)
```

Each handler has its own internal queue for isolation. Cron-based triggers run via a `SchedulerService` that emits synthetic jobs at configured intervals.

### Cron Schedule

| Job | Frequency | Handler |
|-----|-----------|---------|
| RebuildWatchlist | 15 minutes | Health Monitoring |
| RecomputeAll | 5 minutes | Health Jump Order Cancel |
| MarketDataChangeEvents | 1 second | OI Monitoring, Mark APR Monitoring |

### Job Options

Triggerer jobs retry 3 times with exponential backoff (1s base delay). Completed/failed jobs pruned at 10 entries.

---

## 1. Health Monitoring

**Queue**: `TRIGGERER_HEALTH_MONITORING_QUEUE`

Maintains per-market watchlists of accounts approaching dangerous health levels. Three detection modes:

### MarketAccChange (event-driven)

When a position changes:
1. Fetch account margin (health + projected health with upcoming FIndex)
2. Use worst-case: `min(health, projHealth)`
3. If health ≤ `watchlistHealthThreshold` → add to watchlist
4. If health ≤ `liquidateThreshold` → emit `HealthChange` job

Batched: 100 items, 50ms flush interval.

### MarkRateChange (1-second cron)

When mark rate changes in a market:
1. Re-evaluate all accounts in that market's watchlist
2. Recalculate health with new mark rate
3. Emit `HealthChange` for accounts crossing thresholds

Deduplicated by `marketId` to avoid redundant rechecks within the same cron cycle.

### RebuildWatchlist (15-minute cron)

Full rebuild from MongoDB — loads all accounts with active positions in each market into the watchlist. Catches any accounts missed by event-based detection.

### Priority Assignment

| Health Range | Priority | Numeric |
|-------------|----------|---------|
| health ≤ 0.4 | CRITICAL | 0 |
| health ≤ deleverage threshold | HIGH | 20 |
| health ≤ liquidate threshold | NORMAL | 30 |
| Otherwise | LOW | 40 |

**Output**: `ResponseProtocolJobType.HealthChange` → routes to Pauser, Deleverager, Liquidator, PublicCanceling, SuspiciousTrader, and Alert responders.

---

## 2. OI Monitoring

**Queue**: `TRIGGERER_OI_CHANGE_QUEUE` | **Trigger**: Market data changes (1s cron)

### CLO Toggle Detection

Reads CLO thresholds from on-chain `CloSetter` contract per market:
- `OI ≥ upperThres && status === GOOD` → emit `OIChange` (should turn ON CLO)
- `OI < lowerThres && status === CLO` → emit `OIChange` (should turn OFF CLO)

Deduplicated by `marketId`.

### Suspicious Large Position Detection

Calculates minimum suspicious OI:
```
minSusOi = max(notionalOI × oiPercentageThreshold, susOiFloor[tokenId])
```

For each position where `|size| > minSusOi`:
- Filter out: whitelisted traders, already withdrawal-restricted accounts
- Skip if trader is already marked as whitelisted suspicious trader

**Output**:
- `ResponseProtocolJobType.OIChange` (CLO toggle) — priority HIGH
- `ResponseProtocolJobType.AbnormalOI` (large positions) — priority LOW

---

## 3. Withdrawal Monitoring

**Queue**: `TRIGGERER_WITHDRAWAL_MONITORING_QUEUE` | **Trigger**: Transfer events

### Detection

On each transfer event:
1. Compare withdrawal amount against `largeWithdrawalThreshold` from on-chain WithdrawalPolice contract (per token)
2. Flag: `isLargeWithdrawal = (amount ≥ threshold)`

### Daily Quota Check

Applied only if `!isLargeWithdrawal && (isSuspiciousTrader || isRedZone)`:
- Atomic MongoDB operation: check and increment daily total (UTC date-keyed)
- Quota: `fastWithdrawalUsdDailyQuota` from config
- Returns `{ fastApproved: boolean, remainingQuota: number }`

### Trigger Condition

Emits job if any: `isLargeWithdrawal || isSuspiciousTrader || isRedZone`

**Output**: `ResponseProtocolJobType.SuspiciousWithdrawal` — priority HIGH. Deduplicated by `root + tokenId + amount`.

---

## 4. Mark APR Monitoring

**Queue**: `TRIGGERER_MARK_APR_DRIFT_QUEUE` | **Trigger**: Market data changes (1s cron)

Tracks APR deviations across three sliding windows: **15 minutes, 1 hour, 2 hours**.

### Per-Window State

```
{ openApr, peakDeviation, periodStartTime }
```

### Detection

On each market data change:
1. Calculate deviation: `move = |newMarkApr - openApr| / openApr`
2. Track peak: `peakDeviation = max(peakDeviation, move)`
3. If `peakDeviation ≥ 10%` threshold → trigger
4. Reset window if expired: `now - periodStartTime ≥ duration`

Special case: if `openApr = 0` and `newMarkApr ≠ 0`, force `peakDeviation = MAX_SAFE_INTEGER` (rare but costly).

### Output

Does **not** emit to `RESPONDER_PROTOCOL_QUEUE` directly. Instead triggers two internal rebuilds:
- `HealthMonitoringJobName.RebuildWatchlist` → health watchlist rebuild
- `HealthJumpOrderCancelJobName.RecomputeAll` → health-jump order recheck

This ensures significant rate movements cascade into health re-evaluation across the system.

---

## 5. Health Jump Order Cancel

**Queue**: `TRIGGERER_HEALTH_JUMP_ORDER_CANCEL_QUEUE` | **Triggers**: Position changes (event) + 5-minute cron

Proactively detects orders that would push account health below initial margin after an upcoming FIndex update.

### MarketAccChange (event-driven)

When a position changes:
1. Call on-chain simulation: `OrderCanceler.findHealthJumpOrders(marketAcc, [])`
2. Returns `{ risky: bool, buffer: number, proofs: [{ marketId, orderIds[] }] }`
3. If market is in Settled projection mode, also compute with projected funding rate proofs
4. Compare normal vs projected results; use whichever detects risk

### RecomputeAll (5-minute cron)

For each market:
1. Fetch all accounts with active orders (`LimitOrderStatus.Filling`) from MongoDB
2. Batch-detect for all accounts
3. Log failures, continue processing

### Projection Logic

If market uses Settled funding rate mode:
- Compute with projected FIndex values
- Compare `norm` (current) vs `proj` (projected) results
- Return whichever is risky
- Graceful fallback: skip projection if simulation call fails

**Output**: `ResponseProtocolJobType.HealthJumpOrderCancel` — priority LOW. Deduplicated by `marketAcc`.

---

## 6. Transaction Analysis

**Queue**: `TRIGGERER_TRANSACTION_QUEUE` | **Trigger**: Trade events

Detects suspicious trading patterns by tracking per-user statistics.

### Per-User Stats (AbnormalTradingStats in MongoDB)

```
{
  positionCount,              // cumulative closed positions
  marketTradeCount,           // taker trade count
  avgPositionTime,            // rolling average time positions held
  tradeNearNextPaymentCount   // trades within 10 min of payment period
}
```

### On Position Close

1. Find opening transaction, calculate time held
2. Update rolling average: `avgPositionTime = (old_avg × old_count + time) / (old_count + 1)`

### Anomaly Triggers

| Pattern | Condition |
|---------|-----------|
| Short position time | `marketTradeCount > 10 && avgPositionTime < 10 min && positionCount > 0` |
| High trade near payment | `marketTradeCount > 5 && (tradeNearNextPaymentCount / marketTradeCount) ≥ 0.9` |

Either condition triggers immediately — not both required.

**Output**: `ResponseProtocolJobType.AbnormalTrading` — priority LOW. No deduplication (one-off detection per transaction).

---

## Queue Flow Summary

```
Events ──→ TRIGGERER_EVENT_QUEUE
              ├─→ TRIGGERER_HEALTH_MONITORING_QUEUE ──→ HealthChange
              ├─→ TRIGGERER_OI_CHANGE_QUEUE ──────────→ OIChange, AbnormalOI
              ├─→ TRIGGERER_WITHDRAWAL_MONITORING_QUEUE → SuspiciousWithdrawal
              ├─→ TRIGGERER_MARK_APR_DRIFT_QUEUE ─────→ (internal rebuild triggers)
              ├─→ TRIGGERER_HEALTH_JUMP_ORDER_CANCEL_QUEUE → HealthJumpOrderCancel
              └─→ TRIGGERER_TRANSACTION_QUEUE ─────────→ AbnormalTrading

All job types ──→ RESPONDER_PROTOCOL_QUEUE ──→ Response Handlers
```
