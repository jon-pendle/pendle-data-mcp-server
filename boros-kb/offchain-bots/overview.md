---
description: Offchain bot architecture — two independent systems (failsafe + backend) that monitor Boros and execute risk actions
last_updated: 2026-03-16
related:
  - offchain-bots/failsafe-bots.md
  - offchain-bots/backend-triggerers.md
  - offchain-bots/backend-responders.md
  - contracts/risk-bots.md
  - contracts/bots-facets.md
---

# Offchain Bots — Architecture Overview

Boros runs two **independent** offchain bot systems that monitor on-chain state and execute risk management actions. Both systems call the same on-chain `BotController` facets (see `contracts/risk-bots.md`), but differ in architecture and design philosophy.

---

## Two Systems, One Goal

| | Failsafe Bots (`pendle-risks-bot-v3`) | Backend Bots (`pendle-backend-v3`) |
|---|---|---|
| **Philosophy** | Minimal dependencies — RPC-only, no DB | Full infrastructure — BullMQ, MongoDB, Redis |
| **Detection** | Poll-based loops (5–60s cycles) | Event-driven triggerer-responder via queues |
| **State** | In-memory + JSON file cache | MongoDB + Redis + in-memory watchlists |
| **Deployment** | 4 independent processes | 2 services: sync (triggerers) + responder |
| **Redundancy role** | Last-resort backup if backend is down | Primary system for normal operations |
| **Coverage** | Pausing, liquidation, withdrawal police, funding rate | Liquidation, deleverage, pausing, CLO, order cancel, health-jump cancel, zone response, suspicious trader detection, withdrawal police |

**Why two systems?** The failsafe bots are deliberately simple and self-contained — they can run on a single machine with just an RPC endpoint and private key. If the backend infrastructure (queues, databases, services) goes down, the failsafe bots continue operating independently.

---

## Failsafe Bots (`pendle-risks-bot-v3`)

4 independent bots, each runnable as a standalone process:

| Bot | Monitors | Action | Cycle |
|-----|----------|--------|-------|
| **Pausing** | Account health via Explorer contract | `pauseMarkets()` when health < 0.4 | 5s |
| **Liquidation** | Account solvency (totalValue < maintMargin) | `executeLiquidation()` batched, worst-health first | 5s |
| **Withdrawal Police** | Pending withdrawal amounts per user+token | `restrictLargeWithdrawal()` when above threshold | 15s |
| **Funding Rate** | CEX funding rates from 3 oracle sources | `updateFloatingIndex()` timed to hour boundaries | 0.5–60s |

**Data sources**: RPC multicalls (batches of 256 accounts), external API for user/market lists (with file-cache fallback), CEX feeds for funding rates.

**Key design decisions**: No database. File-based caching for restart recovery. Batch operations via multicall. Health-weighted liquidation priority. Multi-oracle fallback (Chainlink, Chaos Labs, Pendle).

See `offchain-bots/failsafe-bots.md` for detailed per-bot documentation.

---

## Backend Bots (Triggerer-Responder)

The backend system splits detection from execution:

```
On-Chain Events
    ↓
Triggerer Service (apps/sync)
    ↓ detects conditions
RESPONDER_PROTOCOL_QUEUE (BullMQ)
    ↓ routes by job type
Response Handlers (apps/responder)
    ↓ prepares transactions
TRANSACTION_EXECUTOR_QUEUE
    ↓ prioritized, deduplicated
On-Chain Execution
```

### Triggerers (Detection)

6 handlers that detect conditions and emit jobs:

| Handler | Trigger Source | Detects | Output Job |
|---------|---------------|---------|------------|
| **Health Monitoring** | Position changes + mark rate changes + 15m cron | Users with health ≤ liquidation threshold | `HealthChange` |
| **OI Monitoring** | Market data (1s cron) | OI above/below CLO thresholds + suspicious large positions | `OIChange`, `AbnormalOI` |
| **Withdrawal Monitoring** | Transfer events | Large/suspicious withdrawals with daily quota tracking | `SuspiciousWithdrawal` |
| **Mark APR Monitoring** | Market data (1s cron) | >10% APR deviation in 15m/1h/2h windows | Rebuilds health watchlist |
| **Health Jump Order Cancel** | Position changes | Orders that would push health < IM after FIndex update | `HealthJumpOrderCancel` |
| **Transaction Analysis** | Trade events | Short position times, high-frequency trading near payment dates | `AbnormalTrading` |

### Responders (Execution)

8 handlers that execute on-chain actions:

| Handler | Triggered By | On-Chain Action | Priority |
|---------|-------------|-----------------|----------|
| **Pauser** | Health ≤ pause threshold | `pauseMarkets()` | 10 (highest) |
| **Deleverager** | Health ≤ deleverage threshold | `deleverageToHealth()` | 20 |
| **Zone** | Aggregated risk metrics | Red zone: 5 levers (cooldown, liq incentive, rate bounds, CLO, strict health) | 30 |
| **Liquidator** | Health ≤ liquidation threshold | `executeLiquidation()` batched | 40 |
| **Suspicious Trader** | Abnormal trading/OI/withdrawal | `restrictWithdrawalUnconditionally()` + DB record | 50 |
| **Health Jump Cancel** | Orders would deteriorate health | `forceCancelAllHealthJump()` | 60 |
| **CLO Mode** | OI threshold breach | `toggleCLO()` with 30m lockout | 80 |
| **Public Canceling** | Health ≤ risky threshold | `forceCancelAllRiskyUser()` | 90 (lowest) |

See `offchain-bots/backend-triggerers.md` and `offchain-bots/backend-responders.md` for detailed documentation.

---

## Alert Channels

Both systems share the same alert priority scheme:

| Channel | Level | Examples |
|---------|-------|---------|
| `P1_RED_ZONE` | Critical | Zone transitions, funding failures |
| `P1_PAUSE_DELEVERAGE` | Critical | Markets paused, bad debt detected |
| `P1_BOTS_DEAD` | Critical | Bot process failures, oracle failures |
| `P2_SUS_WITHDRAWAL` | Medium | Large/suspicious withdrawals restricted |
| `P2_YELLOW_ZONE` | Medium | Zone warnings |
| `P3_RISK_EVENTS` | Info | Simulation failures, suspicious traders logged |
| `P3_BOT_ACTIVITIES` | Info | Liquidations executed, routine operations |

---

## Overlap and Coordination

Both systems can execute the same on-chain actions. This is intentional — the failsafe system provides redundancy. Key differences in behavior:

- **Liquidation**: Both systems liquidate. Backend batches more aggressively and has priority-based ordering. Failsafe uses simpler batch simulation.
- **Withdrawal police**: Both restrict large withdrawals. Backend additionally tracks suspicious trading patterns and daily quotas via MongoDB.
- **Pausing**: Both pause markets. Backend has more granular health thresholds. Failsafe uses a fixed H_f = 0.4.
- **Funding rate**: Only the failsafe system handles funding rate updates. Backend does not submit FIndex updates.
- **Deleverage, CLO, zone response, health-jump cancel**: Only the backend system handles these. The failsafe system does not implement them.

On-chain, the `BotController` facets are idempotent — duplicate calls (e.g., both systems trying to liquidate the same account) will revert harmlessly if the first transaction already resolved the condition.
