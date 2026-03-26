---
description: End-to-end flow for delaying funding rate settlement and deleveraging at-risk users beforehand
last_updated: 2026-03-19
related:
  - risk/alert-specs.md
  - offchain-bots/funding-rate-bot.md
  - contracts/bots-facets.md
  - contracts/bot-math-libs.md
  - offchain-bots/backend-triggerers.md
  - offchain-bots/backend-responders.md
---

# Pre-Settlement Deleverage

Also known as: early funding rate update, delay funding rate update, deleverage before settlement.

## Problem

Every hour, the funding rate bot submits a new FIndex update on-chain. This triggers settlement — each position's floating interest and fees are applied, changing account value. If a user's positions have accumulated large adverse funding, the settlement can push their health ratio below the deleverage threshold (0.7) in a single transaction, with no opportunity to intervene.

## Solution — Level 1.2 Protocol

From `risk/alert-specs.md`:

1. **Detect** that a user's health after the upcoming settlement would drop below 0.7
2. **Delay** the funding rate settlement
3. **Deleverage** the user before the settlement executes
4. **Settle** once the user's post-settlement health is above 0.7

---

## End-to-End Flow

```
Hour boundary approaches
        │
        ▼
┌──────────────────────────────────────┐
│  Health Monitoring Triggerer         │
│  (1s mark-rate cron + 15m rebuild)   │
│                                      │
│  For each account, compute:          │
│    projectedHealth = simulate with   │
│    upcoming FIndex updates           │
│    effectiveHealth = min(health,     │
│                       projectedHealth)│
├──────────────────────────────────────┤
│  projectedHealth < 0.7?              │
│    YES ──► emit HealthChange job     │
│    NO  ──► normal path               │
└──────────────────────────────────────┘
        │ YES
        ▼
┌──────────────────────────────────────┐
│  Deleverager Responder (priority 20) │
│                                      │
│  1. Confirm FundingRateMode.Settled  │
│     (projection needed)             │
│  2. Compute delevFactor on-chain     │
│  3. Find opposite-side winners       │
│  4. Call deleverageToHealth()         │
│     ──► positions reduced            │
│  5. Signal /allow-early-update       │
│     to funding rate bot              │
└──────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  Funding Rate Bot                    │
│                                      │
│  Normal: submit 30s after hour       │
│  (Gate markets: 120s after hour)     │
│  Max delay: 30s past target          │
│                                      │
│  With delay: hold submission until   │
│  responder signals /allow-early-     │
│  update, then submit                 │
└──────────────────────────────────────┘
        │
        ▼
  Settlement executes on reduced
  positions ──► health stays ≥ 0.7
```

---

## Component Details

### 1. Settlement Simulation — `SettleSimMathLib`

Source: `contracts/bot-math-libs.md` § SettleSimMath

Simulates the impact of a pending FIndex update on user health **before** it executes on-chain. Used by both the health-jump detection bot and the proactive deleverager.

#### Setup — `settleAndCreate()`

1. Settle all existing positions via `marketHub.settleAllAndGet`
2. Record post-settlement cash
3. For each non-matured market, snapshot two states:
   - **marketBefore**: current FIndex, current timeToMat, current rMark
   - **marketAfter**: new FIndex (with pending update applied), reduced timeToMat, same rMark

The "before" and "after" states share the same rMark — the simulation assumes mark rate doesn't change during the funding update.

#### Value and MM Before/After

**Before** (`calcTotalValueMMBefore`):

```
totalValue = accCash + Σᵢ positionValue(sizeᵢ, rMarkᵢ, timeToMatᵢ_before)
totalMM    = Σᵢ calcMM(marketᵢ_before, sizeᵢ, kMMᵢ)
```

**After** (`calcTotalValueMMAfter`):

```
totalValue = accCash
           + Σᵢ [settlement(sizeᵢ, fIndexᵢ_before, fIndexᵢ_after)
               + positionValue(sizeᵢ, rMarkᵢ, timeToMatᵢ_after)]
totalMM    = Σᵢ calcMM(marketᵢ_after, sizeᵢ, kMMᵢ)
```

Where:

```
positionValue(signedSize, rMark, timeToMat) = signedSize × rMark × timeToMat / (ONE × YEAR)

settlement(signedSize, fIndex_before, fIndex_after)
    = signedSize × (floatingIndex_after − floatingIndex_before)    // floating interest
    − |signedSize| × (feeIndex_after − feeIndex_before)           // settlement fee (always a cost)
```

#### FIndex Update Construction

```
newFIndex = FIndex(
    fundingTimestamp,
    oldFloatingIndex + fundingRate,
    oldFeeIndex + settleFeeRate × timePassed / (ONE × YEAR)
)
```

Each update is verified against its oracle (Chainlink, ChaosLabs, or Pendle) replicating the same validation as `FundingRateVerifier`. See `contracts/funding-oracle.md`.

---

### 2. Deleverage Factor — `calcDelevFactor()`

Source: `contracts/bots-facets.md` § DeleveragerFacet

Given the simulation outputs, compute the fraction `f` of position to remove so that post-deleverage + post-settlement health equals `desiredHealthRatio`.

The same `f` is applied uniformly across **all** active markets:

```
toDelevSize = position × f   (per market)
```

Since deleverage at mark rate preserves total value (cash and position value offset), and all size-proportional components (MM, settlement payment, position value delta) scale by `(1 − f)`:

```
newValue = totalValueBefore + (totalPayment + totalDeltaPosValue) × (1 − f)
newMM   = totalMMAfter × (1 − f)
```

Setting `newValue / newMM = desiredHR` and solving:

```
f = 1 − totalValueBefore / (desiredHR × totalMMAfter − totalPayment − totalDeltaPosValue)
```

If `desiredHealthRatio = 0`, returns `f = 1` (full deleverage).

---

### 3. On-Chain Execution — `DeleveragerFacet.deleverageToHealth()`

Source: `contracts/bots-facets.md` § DeleveragerFacet

```solidity
struct DeleverageToHealthRequest {
    MarketAcc lose;
    MarketId[] marketIds;
    MarketAcc[][] wins;                    // possible winners per market
    UpcomingFIndexUpdate[] fIndexUpdates;   // projected FIndex changes
    int256 desiredHealthRatio;             // target HR (0 = fully deleverage)
    bool allowAMM;
    bool allowPartial;
}
```

**Flow**:

1. Settle loser, simulate projected FIndex via `SettleSimMathLib`
2. Compute `delevFactor` via `calcDelevFactor()`
3. For each market: compute `toDelevSize = position × delevFactor`. Assign to eligible winners (opposite-side positions, healthier than loser)
4. Execute `forceDeleverage` per winner per market with `alpha = 0` (no bad debt — requires `totalValueBefore > 0`)
5. If `!allowPartial`, verify full deleverage completed (reverts with `DeleveragerIncomplete` otherwise)

Wrapped in `BotMiscFacet.multicall()` — one multicall per loser with all their market positions.

---

### 4. Health Jump Order Cancel

Source: `offchain-bots/backend-triggerers.md` § Health Jump Order Cancel

A parallel protection: proactively cancels orders that would push account health below initial margin after the upcoming FIndex update.

- **Event-driven**: on position change, calls `OrderCanceler.findHealthJumpOrders(marketAcc, [])`
- **Cron**: every 5 minutes, batch-checks all accounts with active orders
- **Projection**: if market uses `FundingRateMode.Settled`, computes with projected FIndex values and takes the worse of normal vs projected results

---

### 5. Funding Rate Bot Timing

Source: `offchain-bots/funding-rate-bot.md`

| Config | Value |
|--------|-------|
| Normal target execution | 30s after hour boundary |
| Gate markets target | 120s after hour boundary |
| Max delay past target | 30s (`MAX_FUNDING_UPDATE_DELAY_s`) |
| Execute window | wakes 3s before target (`EXECUTE_WINDOW_s`) |
| Early update endpoint | `POST /allow-early-update` (auth-protected) |
| Endpoint payload | `{ timestamp, disallowedMarketIds? }` |

The `disallowedMarketIds` field allows excluding specific markets from an early update round if those markets still have at-risk users being deleveraged.

---

## Configuration Summary

| Parameter | Value | Source |
|-----------|-------|--------|
| Health trigger threshold | 0.7 | `risk/alert-specs.md` Level 1.2 |
| Deleverage responder priority | 20 | `offchain-bots/backend-responders.md` |
| Health check frequency | 1s (mark rate cron) | `offchain-bots/backend-triggerers.md` |
| Full health rebuild | every 15 min | `offchain-bots/backend-triggerers.md` |
| Dedup lifetime | 1 minute | `offchain-bots/backend-responders.md` |
| Max winners per call | configurable (`maxWinnersPerCall`) | `offchain-bots/backend-responders.md` |

## Bad Debt Path

If `totalValue < 0` (user is already insolvent before settlement), the automated deleverage path is **not used**. Instead:

- `BadDebtHelper` computes bad debt parameters
- A `P1_PAUSE_DELEVERAGE` alert fires for manual intervention
- No automated on-chain execution — requires manual review
