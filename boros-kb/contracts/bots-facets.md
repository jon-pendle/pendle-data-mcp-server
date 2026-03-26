---
description: Detailed per-facet documentation for BotController — parameters, logic flows, error cases
last_updated: 2026-03-16
related:
  - contracts/risk-bots.md
  - contracts/liquidation.md
  - contracts/margin-engine.md
  - contracts/settlement.md
---

# Bot Facets — Detailed Reference

Per-facet documentation for the BotController system. For architecture overview, see `contracts/risk-bots.md`.

---

## LiquidationExecutorFacet

**Source**: `contracts/bots/liquidation/LiquidationExecutorFacet.sol`

```
struct LiquidationParams {
    MarketId marketId;
    AMMId ammId;            // optional — 0 means no AMM hedge
    MarketAcc violator;
    int256 maxVioHealthRatio;  // 0 = max liquidation, else cap at this HR
    uint256 minProfit;
}
```

**Flow**:
1. Transfer violator's cash to liquidator's cross account (prerequisite)
2. `LiquidationMathLib.create()`: settle violator, compute HR, calculate optimal liquidation size and expected profit. Determines `withAMM` and `withBook` hedge sizes
3. `marketHub.liquidate()`: transfer positions + extract penalty
4. If `withAMM != 0`: hedge via `swapWithAMM(ammId, size)` (FOK)
5. If `withBook != 0`: hedge via `swapWithBook(marketId, size)` (FOK)
6. Return cash from isolated → cross account
7. Validate: `profit == expectedProfit` (exact match) and `profit >= minProfit`

**AMM guard**: Violator cannot be an AMM (`LiquidationAMMNotAllowed`).

**Errors**: `InsufficientProfit`, `ProfitMismatch`, `LiquidationAMMNotAllowed`

---

## ArbitrageExecutorFacet

**Source**: `contracts/bots/arbitrage/ArbitrageExecutorFacet.sol`

```
struct ArbitrageParams {
    Side bookSide;         // which side of book to match against
    AMMId ammId;
    int256 minProfit;
    bool maximizeProfit;   // true = search best tick, false = use market price
}
```

**Flow**:
1. Get AMM account and market cache
2. `ArbitrageMathLib.create()`: fetch fee rates (taker + AMM), compute initial value
3. `calcArbitrage()`: sweep `numTicksToTryAtOnce` ticks, compute AMM swap size at each tick rate, calculate fee-adjusted profit. If `maximizeProfit`, find best tick; else use current
4. Validate: `arbSize > 0` (`ZeroArbitrageSize`), `profit >= minProfit`
5. Execute: match book on one side, swap AMM on opposite side
6. Validate: actual profit matches expected

**Errors**: `ZeroArbitrageSize`, `InsufficientProfit`, `ProfitMismatch`

---

## DeleveragerFacet

**Source**: `contracts/bots/risk/DeleveragerFacet.sol`, `contracts/bots/math/SettleSimMath.sol`

### Storage
- `deleverageThresHR` — health ratio threshold (typically 0.7). A user is "risky" when `totalValue < totalMM × deleverageThresHR`.

### `manualDeleverage(req)`

```
struct DeleverageRequest {
    MarketAcc lose;
    MarketId[] marketIds;
    ManualDeleverageInput[] inputs;  // per-market: lossFactor, winners[], sizes[]
    bool allowAMM;
}
```

**Flow**:
1. Validate: no duplicate marketIds, inputs match lengths, AMM constraints
2. Settle loser across all markets, compute total value and MM
3. Verify `_isRisky(totalValue, totalMM)` — reverts `DeleveragerHealthNonRisky`
4. Verify each winner is healthier than loser: `winValue × loseMM > loseValue × winMM` (cross-multiply to avoid division)
5. Route to normal or bad debt path:

**Normal path** (`loseValue >= 0`): for each market and winner, call `forceDeleverage` with `alpha = 0`. The market-level trade executes at mark rate (see `contracts/liquidation.md`).

**Bad debt path** (`loseValue < 0`): for each market, compute `alpha` to distribute losses across winners proportionally. After each winner deleverage, verify the winner is not in bad debt. The loser must be **fully** deleveraged (`loseRemainSize == 0`).

### Alpha calculation — `_calcAlpha()`

Alpha controls what fraction of the loser's bad debt is absorbed by each winner in each market.

```
pRemain = loseRemainSize / loseOrigSize    // fraction of position not yet deleveraged
alpha = (lossFactor × pRemain) / (lossFactor + Σ lossFactors of remaining markets)
```

The `lossFactor` is a per-market weight provided by the caller (the bot). As the loser's position is deleveraged market by market, `pRemain` shrinks, ensuring the total distributed bad debt converges to the full bad debt. Setting `lossFactor = 0` for a market skips loss sharing for that market entirely.

At the market level (`_calcDelevTradeAft`), alpha translates to the trade price adjustment:

```
lossFactor_per_winner = alpha × sizeToWin / loseSize
loss = loseValue × lossFactor_per_winner
annualizedLoss = loss × YEAR / timeToMat
signedCost = sizeToWin × rMark − annualizedLoss
```

The winner receives the position at mark rate minus their share of the annualized bad debt.

### `deleverageToHealth(req)`

```
struct DeleverageToHealthRequest {
    MarketAcc lose;
    MarketId[] marketIds;
    MarketAcc[][] wins;          // possible winners per market
    UpcomingFIndexUpdate[] fIndexUpdates;  // projected FIndex changes
    int256 desiredHealthRatio;   // target HR (0 = fully deleverage)
    bool allowAMM;
    bool allowPartial;
}
```

**Flow**:
1. Settle loser, simulate projected FIndex via `SettleSimMathLib` (see below)
2. Compute `delevFactor` — the fraction of position to remove across all markets
3. For each market: `toDelevSize = position × delevFactor`. Assign to eligible winners (opposite-side positions only, healthier than loser). Winners are filtered in-place.
4. Execute `forceDeleverage` per winner per market with `alpha = 0` (no bad debt — `calcDelevFactor` requires `totalValueBefore > 0`)
5. If `!allowPartial`, verify full deleverage completed (`DeleveragerIncomplete`)

### Deleverage factor derivation — `calcDelevFactor()`

The goal: find `f` (fraction of position to remove) such that after deleverage + projected settlement, the user's health ratio reaches `desiredHealthRatio`.

**Setup** (via `SettleSimMathLib`):

The simulation settles the user with current FIndex, then projects what happens if upcoming `fIndexUpdates` are applied. This gives us:
- `totalValueBefore`: value with current state (after settling, before FIndex update)
- `totalValueAfter`: value after projected FIndex update (includes settlement payments)
- `totalPayment`: funding payments from projected settlement
- `totalMMAfter`: maintenance margin with projected state
- `totalDeltaPosValue`: change in position value from FIndex update (due to timeToMat changing)

**Derivation**:

The same `delevFactor` is applied uniformly to **all** active markets (`toDelevSize = position × f` per market). So every component that's proportional to size — MM, position value, settlement payment — scales by `(1 − f)` across all markets.

`totalMMAfter` is the sum of MM across all markets (with projected state). Since all markets scale by `(1 − f)`:

```
newMM = totalMMAfter × (1 − f)
```

`totalValueBefore = accCash + Σ positionValue_i`. Deleverage at mark rate preserves total value (cash changes, but position value changes by the opposite amount — they cancel out). After the projected settlement, payments and position value deltas are proportional to size:

```
newValue = totalValueBefore + (totalPayment + totalDeltaPosValue) × (1 − f)
```

Setting `newValue / newMM = desiredHR`:

```
totalValueBefore + (totalPayment + totalDeltaPosValue) × (1 − f) = desiredHR × totalMMAfter × (1 − f)
```

Solving for `(1 − f)`:

```
(1 − f) = totalValueBefore / (desiredHR × totalMMAfter − totalPayment − totalDeltaPosValue)
```

Therefore:

```
f = 1 − totalValueBefore / (desiredHR × totalMMAfter − totalPayment − totalDeltaPosValue)
```

If `desiredHealthRatio = 0`, returns `f = 1` (full deleverage).

### Settlement simulation — `SettleSimMathLib`

**Source**: `contracts/bots/math/SettleSimMath.sol`

Allows the deleverage bot to **proactively deleverage** before an upcoming funding rate update would worsen health. The simulation:

1. Settles the user with current on-chain state via `marketHub.settleAllAndGet()`
2. For each active market, captures "before" state (current FIndex, markRate, timeToMat, kMM)
3. Computes "after" state by applying `fIndexUpdates`: verifies the funding rate report against the correct oracle (Chainlink/ChaosLabs/Pendle), calculates `newFIndex = oldFIndex + fundingRate`, updates `feeIndex` and `timeToMat`
4. Provides `calcTotalValueMMBefore()`, `calcTotalValueMMAfter()`, `calcDeltaPositionValue()` — all using the same MM formula as `MarginViewUtils` (including the piecewise near-maturity correction)

**Errors**: `DeleveragerHealthNonRisky`, `DeleveragerLoserHealthier`, `DeleveragerLoserInBadDebt`, `DeleveragerWinnerInBadDebt`, `DeleveragerIncomplete`, `DeleveragerAMMNotAllowed`, `DeleveragerDuplicateMarketId`

---

## OrderCancellerFacet

**Source**: `contracts/bots/risk/OrderCancellerFacet.sol`

### Storage
- `healthJumpCancelThresHR` — threshold for health-jump cancellation

### `forcePurgeOobOrders(marketIds, maxNTicksPurgeOneSide)`
Delegates to `marketHub.forcePurgeOobOrders()`. Gas-limited by `maxNTicksPurgeOneSide` — call repeatedly until all OOB orders cleared. Returns ticks purged per side.

### `forceCancelAllRiskyUser(user)`
Gets user's entered markets, calls `marketHub.forceCancelAllRiskyUser()`. On-chain validates `HR < riskyThresHR`.

### `forceCancelAllHealthJump(user, fIndexUpdates, proofs)`

Proactive cancellation of orders that would deteriorate health after upcoming FIndex update.

```
struct HealthJumpProof {
    MarketId marketId;
    OrderId[] ids;       // orders to cancel
}
```

**Flow**:
1. Settle user with current FIndex
2. Simulate settlement with projected `fIndexUpdates` using `SettleSimMathLib`
3. For each market in proof, compute `delta`:
   - `delta = -upfrontCost(orders) + settlement(newFIndex) - settlement(oldFIndex) + positionValue(newRate) - marginRequired(newRate)`
4. Sum deltas across all markets → `buffer`
5. Require `buffer < 0` (user would become risky) — else `OrderCancellerNotRisky`
6. Cancel all orders in proof

### `findHealthJumpOrders(user, fIndexUpdates)` — simulation only

Off-chain discovery: identifies minimal set of orders causing negative health buffer.

**Algorithm**: For each market, get all open orders. Sort by rate (long: most expensive first; short: cheapest first). Incrementally add orders, computing cumulative delta. Return orders that contribute to worst delta below `healthJumpCancelThresHR`.

**Errors**: `OrderCancellerNotRisky`, `OrderCancellerDuplicateMarketId`, `OrderCancellerDuplicateOrderId`, `OrderCancellerInvalidOrder`

---

## CLOSetterFacet

**Source**: `contracts/bots/risk/CLOSetterFacet.sol`

### Storage
- `cloThresholds[MarketId]` → `CLOThreshold { lowerThres, upperThres }`

### `toggleCLO(marketId)`

Hysteresis-based state machine:
- If OI > `upperThres` AND market is `GOOD` → set `CLO`
- If OI < `lowerThres` AND market is `CLO` → set `GOOD`
- Otherwise → revert `CLOThresholdNotMet`

Validation: `lowerThres < upperThres` (`CLOInvalidThreshold`)

---

## PauserFacet

**Source**: `contracts/bots/risk/PauserFacet.sol`

### Storage
- `minTotalMM[TokenId]` — minimum maintenance margin to trigger pause

### `pauseMarkets(user, marketIds)`

1. Settle user, compute totalValue, totalMM
2. Validate: `totalValue + cash < totalMM * pauseThresHR` AND `totalMM >= minTotalMM[tokenId]` — else `PauserNotRisky`
3. Validate: all markets use same token as user — else `PauserTokenMismatch`
4. Set each market status to `PAUSED`

### `findRiskyUsers(users)` — simulation only
Filters input array, returns only risky accounts. Used off-chain to discover which users to pause.

---

## WithdrawalPoliceFacet

**Source**: `contracts/bots/risk/WithdrawalPoliceFacet.sol`

### Storage
- `largeWithdrawalUnscaledThreshold[TokenId]`
- `restrictedCooldown` — elevated cooldown applied to restricted users

### Functions

| Function | Effect |
|----------|--------|
| `restrictLargeWithdrawal(user, tokenId)` | If pending withdrawal >= threshold, set personal cooldown to `restrictedCooldown`. Else revert `WithdrawalPoliceUnsatCondition` |
| `restrictWithdrawalUnconditionally(user)` | Always set cooldown to `restrictedCooldown` |
| `disallowWithdrawal(user)` | Set cooldown to `type(uint32).max - 1` (effectively permanent) |
| `resetPersonalCooldown(user)` | Clear restriction (set to `type(uint32).max` which signals "use global default") |

**Constraints**: `restrictedCooldown` must be > `globalCooldown` and < `type(uint32).max`.

---

## MiscFacet

**Source**: `contracts/bots/base/MiscFacet.sol`

Administrative functions for the BotController:
- `deposit()` / `withdraw()` / `requestWithdrawal()` — fund management for the bot's trading accounts
- `enterMarketIsolated(marketId)` — join markets (handles entrance fee + min cash)
- `setSelectorToFacets(SelectorsToFacet[])` — register new facets
- `setNumTicksToTryAtOnce(n)` — configure tick sweep depth
- `multicall(Call[])` — batch delegatecalls with per-call failure tolerance

---

## Event Summary

| Facet | Key Events |
|-------|------------|
| LiquidationExecutor | `LiquidationExecuted(violator, profit)` |
| ArbitrageExecutor | `ArbitrageExecuted(ammId, profit)` |
| Deleverager | `DeleverageThresHRSet(newHR)` |
| OrderCanceller | `HealthJumpCancelThresHRSet(newHR)` |
| CLOSetter | `CLOThresholdSet(marketId, threshold)` |
| Pauser | `MinTotalMMSet(tokenId, newMinTotalMM)` |
| WithdrawalPolice | `RestrictWithdrawal(user, newCooldown)`, `DisallowWithdrawal(user)`, `ResetPersonalCooldown(user)` |
| ZoneResponder | `Red*Set(...)`, `White*Set(...)` — per-lever config events |
| MarkRatePusher | `MaxDeltaSet(newMaxDelta)` |
| MiscFacet | `SelectorToFacetSet(selector, facet)` |
