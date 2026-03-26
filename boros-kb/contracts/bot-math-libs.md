---
description: Bot math libraries — full mathematical derivations and correctness proofs for LiquidationMath, ArbitrageMath, SettleSimMath, SwapBoundMath
last_updated: 2026-03-17
related:
  - contracts/margin-engine.md
  - contracts/liquidation.md
  - contracts/risk-bots.md
  - contracts/bots-facets.md
  - contracts/amm.md
---

# Bot Math Libraries — Derivations and Proofs

Source: `contracts/bots/math/`. Four libraries that power on-chain bot calculations. This document derives every formula from first principles and proves correctness of the key algorithms.

**Notation**: All arithmetic is 18-decimal fixed-point (`ONE = 1e18`). `YEAR = 365 days` (in seconds). Division modes: `mulDown` rounds toward zero, `mulCeil/rawDivUp` rounds away from zero, `rawDivFloor` rounds toward negative infinity. We omit scaling factors in derivations for clarity and note rounding direction where it matters.

For core margin formulas (PM, IM, MM, piecewise regime, health ratio), see `contracts/margin-engine.md`. This document references those formulas by name and focuses on bot-specific derivations built on top of them.

---

## SwapBoundMath — Abstraction Layer for Bot Constraints

**Source**: `contracts/bots/math/SwapBoundMath.sol`

SwapBoundMath is the **foundation** that all other bot math libraries build on. Its purpose is not "preventing bad rates" — it **abstracts all limitations** (rate deviation bounds, initial margin requirements, maintenance margin) into reusable primitives. LiquidationMath, ArbitrageMath, and SettleSimMath compose these primitives without reimplementing margin logic.

### SwapBoundMathParams — Market State Snapshot

`create(market)` captures a complete market snapshot into a single struct:

| Field | Derivation |
|-------|------------|
| `config` | `IMarket.getMarketConfig()` — all market parameters |
| `tickStep` | From `market.descriptor()` |
| `iThresh` | `TickMath.getRateAtTick(iTickThresh, tickStep)` — rate threshold |
| `tThresh` | From config — time threshold |
| `timeToMat` | `maturity − latestFTime` |
| `rMark` | `market.getMarkRateView()` — current mark rate |
| `maxRateDeviation` | Derived (see below) |

Guard: reverts with `MarketMatured` if `latestFTime ≥ maturity`.

### Rate Deviation Bound

```
maxRateDeviation = max(iThresh, |rMark|) × maxRateDeviationFactorBase1e4 / 1e4
```

`checkBookRateDeviation(bookRate)` returns:

```
|rMark − bookRate| ≤ maxRateDeviation
```

This is the same rate deviation bound enforced by the core market (see `contracts/margin-engine.md`, Rate Bounds Check). The bot replicates it to filter orderbook ticks before attempting swaps.

### Margin Primitives

`calcIM` and `calcMM` replicate the core margin engine formulas exactly (see `contracts/margin-engine.md` for the full derivation). The only difference: bot formulas assume **no open orders** (PM = position-only), since the bot's position consists solely of the trade being executed.

| Bot Function | Core Function | Difference |
|-------------|--------------|------------|
| `SwapBoundMath.calcIM` | `MarginViewUtils._calcIM` | No open-order netting in PM |
| `SwapBoundMath.calcMM` | `MarginViewUtils._calcMM` | Identical (piecewise regime included) |
| `SettleSimMath._calcMM` | `MarginViewUtils._calcMM` | Identical (inlined for gas) |

The libraries replicate core formulas rather than calling through proxies to avoid cross-contract call overhead in gas-intensive simulation loops.

---

## LiquidationMath — Derivations and Proofs

**Source**: `contracts/bots/math/LiquidationMath.sol` (two libraries: `LiquidationMathLib` + `LiquidationMathHighLevelLib`)

### Algorithmic Summary

LiquidationMath determines the optimal liquidation: given a violator with health ratio < 1, find the maximum position size to liquidate such that:
1. The liquidation is **profitable** (incentive covers hedging costs)
2. The **liquidator maintains IM solvency** after taking on the position
3. The **violator's health ratio** improves but doesn't exceed `maxVioHealthRatio` (preventing over-liquidation)
4. The hedge trade can be **executed on available book/AMM liquidity** within rate deviation bounds

### Liquidation Incentive Factor

From `create()`:

```
k = base + slope × (1 − HR₀)
incentiveFactor = min(k, HR₀)
```

where `HR₀ = vioInitialValue / vioInitialMM ∈ [0, 1)`.

The `min(k, HR₀)` cap is the critical safety bound — see **Theorem 1** below for why it prevents bad debt creation.

### Deriving the Liquidation All-In Rate

**Goal**: Derive a closed-form rate `liqAllInRate` such that any hedge trade at a rate "better" than `liqAllInRate` is profitable for the liquidator.

**Step 1**: Liquidation trade construction.

The liquidation transfers `sizeToLiq` from the violator to the liquidator. The trade cost is discounted by an incentive proportional to the margin relief provided:

```
deltaMM = MM(vioSize) − MM(vioSize − sizeToLiq)
incentive = deltaMM × incentiveFactor
annualizedIncentive = incentive × YEAR / timeToMat
signedCost = sizeToLiq × rMark − annualizedIncentive
```

**Step 2**: Express deltaMM in terms of sizeToLiq.

In the **standard MM regime** (the typical case — see Remark below for piecewise):

```
MM(s) = |s| × max(|rMark|, iThresh) × kMM × max(timeToMat, tThresh) / (ONE × YEAR)
```

Since liquidation always reduces |position| (the sizeToLiq direction opposes the violator's position sign):

```
deltaMM = |sizeToLiq| × max(|rMark|, iThresh) × kMM × max(timeToMat, tThresh) / (ONE × YEAR)
```

Define the **per-unit MM coefficient**:

```
c_MM = max(|rMark|, iThresh) × kMM × max(timeToMat, tThresh) / (ONE × YEAR)
```

So `deltaMM = |sizeToLiq| × c_MM`.

**Step 3**: Compute per-unit incentive rate.

```
annualizedIncentive / |sizeToLiq|
    = deltaMM × incentiveFactor × YEAR / (timeToMat × |sizeToLiq|)
    = c_MM × incentiveFactor × YEAR / timeToMat
    = max(|rMark|, iThresh) × kMM × incentiveFactor × max(timeToMat, tThresh) / (ONE × timeToMat)
```

This is exactly the `liqIncentiveRate` computed in the code:

```solidity
int256 liqIncentiveRate = Int(
    (max(|rMark|, iThresh) * kMM * incentiveFactor * max(timeToMat, tThresh)) / timeToMat
);
```

**Step 4**: Compute break-even hedge rate.

The liquidation trade gives the liquidator a position at effective rate `rMark − liqIncentiveRate/ONE` (for closeSide = LONG; the incentive reduces the buy price). The liquidator also pays `liqFeeRate` on the liquidation.

For the liquidator to break even when hedging on the orderbook at rate `bookRate`, the book trade (at rate `bookRate + takerFeeRate` all-in) must offset the liquidation cost:

**closeSide = LONG** (violator was SHORT, liquidator buys):

```
break-even:  bookRate + takerFeeRate ≤ rMark + liqIncentiveRate − liqFeeRate
```

So: `liqAllInRate = rMark + liqIncentiveRate − liqFeeRate`

**closeSide = SHORT** (violator was LONG, liquidator sells):

```
break-even:  bookRate − takerFeeRate ≥ rMark − liqIncentiveRate + liqFeeRate
```

So: `liqAllInRate = rMark − liqIncentiveRate + liqFeeRate`

The taker fee is handled separately in `isBookRateProfitable()`:

```solidity
// closeSide == LONG:  bookRate + takerFeeRate ≤ liqAllInRate
// closeSide == SHORT: bookRate − takerFeeRate ≥ liqAllInRate
```

**Remark (piecewise MM regime)**: The `liqAllInRate` formula uses the standard-regime MM coefficient. If the piecewise regime applies (rare for liquidatable positions — see below), `liqAllInRate` slightly overestimates the incentive. This is safe: the pre-filter admits slightly too many ticks, but `_tryLiquidate` recomputes via exact `calcMM`, and binary search converges to the correct boundary.

### Theorem 1: Health Ratio Monotonicity (Justifies Binary Search)

**Statement**: Under standard MM, the violator's post-liquidation health ratio `HR(d)` is monotonically non-decreasing in the liquidated amount `d = deltaMM`.

**Proof**:

After liquidating an amount corresponding to margin reduction `d`:

```
V(d) = V₀ − f × d       (value decreases by incentive paid)
M(d) = M₀ − d            (margin decreases by deltaMM)
HR(d) = V(d) / M(d) = (V₀ − f × d) / (M₀ − d)
```

where `f = incentiveFactor`, `V₀ = vioInitialValue`, `M₀ = vioInitialMM`.

Taking the derivative:

```
dHR/dd = [−f × (M₀ − d) + (V₀ − f × d)] / (M₀ − d)²
       = (V₀ − f × M₀) / (M₀ − d)²
```

The denominator is always positive (we never liquidate more than the full margin). The numerator's sign depends on `V₀/M₀` vs `f`:

- **Case 1: `f < HR₀`** (i.e., `f = base + slope × (1 − HR₀)` won the `min`). Then `V₀ − f × M₀ = M₀ × (HR₀ − f) > 0`, so `dHR/dd > 0`. **HR is strictly increasing.** ∎

- **Case 2: `f = HR₀`** (the `min(k, HR₀)` cap is active). Then `V₀ − f × M₀ = 0`, so `dHR/dd = 0`. **HR is constant** at `HR₀` regardless of liquidation size. This is the "critical case" noted in the code — the violator's entire remaining value exactly covers the incentive, so liquidation doesn't improve their health. The code handles this by checking `vioFinalValue > 1e6` (not dust) before applying the HR constraint. ∎

**Corollary (binary search validity)**: The `_tryLiquidate` function returns `LIQUIDATE_MORE` for small sizes and `LIQUIDATE_LESS` for large sizes, with a single transition point. This is because:

1. **Liquidator IM constraint**: As `sizeToLiq` increases, `liqIntermValue` decreases (more cost) and `liqIntermIM` increases (more margin required). Once violated, stays violated for all larger sizes. Monotone: `MORE → LESS`. ✓

2. **Violator HR constraint**: As `sizeToLiq` increases, `HR_final` increases (Theorem 1). Once `HR_final > maxVioHealthRatio`, stays above for all larger sizes. Monotone: `MORE → LESS`. ✓

The intersection of two monotone constraints is a contiguous interval `[0, s*]` where both are satisfied. Binary search correctly finds `s*`. ∎

### Theorem 2: Piecewise MM Regime Considerations

The piecewise MM regime activates when three conditions hold simultaneously:
1. `|rMark| > iThresh`
2. `timeToMat < tThresh × kMM`
3. `signedSize × rMark > 0` (position benefits from rate direction)

**Observation**: Condition 3 requires the position to be in the "beneficial" direction. For a user whose *only* position is adverse, piecewise never activates and the standard liqAllInRate is exact.

In cross-margin, a user may be liquidatable (total HR < 1) despite having a beneficial position in one market. In this case, the piecewise regime could theoretically apply to that market's deltaMM computation.

**Why correctness is preserved**: The `liqAllInRate` is only used for **pre-filtering** ticks in the sweep loop (via `isBookRateProfitable` and `calcSwapAMMToBookRate`). The actual liquidation validation happens in `_tryLiquidate`, which calls `calcLiqTrade → calcMM`, handling piecewise exactly. Since both MM regimes are **linear in |size|** (different coefficient, same proportionality), Theorem 1's monotonicity proof applies identically — the numerator `V₀ − f × M₀` is the same regardless of regime.

### Profit Calculation

`calcExpectedProfit` computes the liquidator's total P&L after all costs:

```
profit = 0
profit −= upfrontFixedCost(liqTrade)           // liquidation position cost
profit −= floatingFee(|sizeToLiq|, liqFeeRate)  // liquidation protocol fee
profit −= upfrontFixedCost(ammCost)             // AMM hedge cost (if any)
profit −= ammOtcFee(|ammSize|)                  // AMM OTC fee
profit −= upfrontFixedCost(bookCost)            // book hedge cost (if any)
profit −= bookTakerFee(|bookSize|)              // book taker fee
```

The liquidator profits when the incentive (embedded in the liqTrade cost discount) exceeds total hedging and fee costs.

### Dual Constraint Validation — `_tryLiquidate`

Every candidate size must pass two simultaneous checks:

**Constraint 1 — Liquidator IM solvency:**

```
liqIntermValue = liqInitialValue
              − upfrontFixedCost(liqTrade)
              − floatingFee(|sizeToLiq|, liqFeeRate)
              + positionValue(sizeToLiq, rMark, timeToMat)

liqIntermIM = calcIM(sizeToLiq, liqKIM)

Require: liqIntermValue ≥ liqIntermIM
```

The liquidator holds position `sizeToLiq` (not yet hedged). The position value partially offsets the trade cost — see `contracts/margin-engine.md` for `positionValue = signedSize × rMark × timeToMat / (ONE × YEAR)`.

**Constraint 2 — Violator health improvement (when maxVioHealthRatio ≠ 0):**

```
vioFinalValue = vioInitialValue
              − upfrontFixedCost(liqTrade.opposite())
              − positionValue(vioSize, rMark, timeToMat)
              + positionValue(vioSize − sizeToLiq, rMark, timeToMat)

vioFinalMM = vioInitialMM − calcMM(vioSize, kMM) + calcMM(vioSize − sizeToLiq, kMM)

Require: vioFinalValue ≤ 1e6  OR  vioFinalValue ≤ maxVioHealthRatio × vioFinalMM
```

Note the `1e6` dust guard: if the violator's remaining value is negligible, liquidate fully regardless of HR constraint.

**Derivation of vioFinalValue simplification**:

The position value terms telescope:

```
−positionValue(s_v) + positionValue(s_v − s_l)
= (−s_v + s_v − s_l) × rMark × timeToMat / (ONE × YEAR)
= −s_l × rMark × timeToMat / (ONE × YEAR)
```

And the opposite trade's upfront cost:

```
upfrontFixedCost(opposite) = −(s_l × rMark − annualizedIncentive) × timeToMat / YEAR
```

Combining (at the 1/ONE scale):

```
Δvalue_vio = (s_l × rMark − annInc) × t/Y − s_l × rMark × t/(ONE × Y)
           = −annInc × t/Y
           = −incentive
           = −deltaMM × incentiveFactor
```

So `vioFinalValue = V₀ − deltaMM × f` and `vioFinalMM = M₀ − deltaMM`, confirming the Theorem 1 formulation. ∎

### Main Algorithm — `calcLiquidation`

Two-phase sweep over orderbook + AMM liquidity:

**Phase 1 — Tick sweep** (via `TickSweepState`):

The sweep iterates through the orderbook on the hedge side (`closeSide.opposite()`). For each tick:

1. Check `canSwapToBookRate(tickRate)` — rate must be profitable AND within deviation bound
2. Compute AMM swap needed to push the AMM to the book rate: `calcSwapAMMToBookRate(tickRate)`
3. Combine: `liqSize = −(withAMM + withBook)` (negate because hedge is opposite to liquidation)
4. Validate via `_tryLiquidate(liqSize)`:
   - `LIQUIDATE_MORE` → accept this tick, try more (`transitionUp`)
   - `LIQUIDATE_LESS` → reject, narrow search (`transitionDown`)

**Phase 2 — Binary search refinement** (`_binSearch`):

After the sweep finds the boundary tick, binary search within the last tick to find the exact maximum size. The search distributes additional size between AMM and book:

```
more ∈ [0, min(remainingVioSize, maxMoreAMM + tickSize)]
moreWithAMM = min(more, maxMoreAMM)
moreWithBook = more − moreWithAMM
```

Binary search on `more`, checking `_tryLiquidate` at each midpoint. Valid by Theorem 1's corollary.

---

## ArbitrageMath — AMM-Book Spread Capture

**Source**: `contracts/bots/math/ArbitrageMath.sol` (two libraries: `ArbitrageMathLib` + `ArbitrageMathHighLevelLib`)

### Algorithmic Summary

ArbitrageMath detects and captures price discrepancies between the AMM and orderbook. The bot buys from one venue and sells to the other when a spread exists, subject to IM constraints and minimum profit thresholds.

### Fee-Adjusted Rate Conversion

To compare book and AMM prices on equal footing, `convertBookRateToAMMRate` adjusts for all fees:

```
ammRate = bookRate ∓ (takerFeeRate + ammAllInFeeRate)
```

**Derivation**: The bot trades on both venues simultaneously. For `bookSide = LONG`:
- Buys on book at `bookRate`, paying `takerFeeRate`
- Sells on AMM at `ammRate`, paying `ammAllInFeeRate` (= `ammOtcFeeRate + ammInternalFeeRate`)
- Break-even when: `ammRate = bookRate − takerFeeRate − ammAllInFeeRate`

For `bookSide = SHORT`:
- Sells on book at `bookRate`, receiving `−takerFeeRate`
- Buys on AMM at `ammRate`, paying `ammAllInFeeRate`
- Break-even when: `ammRate = bookRate + takerFeeRate + ammAllInFeeRate`

### IM Check

The executor holds a net position during arbitrage (book fills immediately, AMM fills separately). `checkEnoughIM` ensures solvency:

```
signedSize = arbSize in bookSide.opposite() direction
intermValue = initialValue
            − upfrontFixedCost(bookCost)
            − floatingFee(arbSize, takerFeeRate)
            + positionValue(signedSize, rMark, timeToMat)
intermIM = calcIM(signedSize, kIM)

Require: intermValue ≥ intermIM
```

The executor's position is in `bookSide.opposite()` because the book trade creates a position that the AMM trade will offset. Between the two legs, the executor holds this intermediate position and must maintain IM.

### Profit Calculation

```
profit = −upfrontFixedCost(ammCost) − ammOtcFee(arbSize) − upfrontFixedCost(bookCost) − bookTakerFee(arbSize)
```

The book and AMM costs have opposite signs (buy on one, sell on the other), so profit arises from the spread between them minus total fees.

### Main Algorithm — `calcArbitrage`

Two modes controlled by `maximizeProfit`:

**Maximize profit mode** (`maximizeProfit = true`): Find the largest arbitrage where the spread covers fees. Uses fee-adjusted rate comparison (`accountForFees = true`) to check if `bookSize ≤ ammCapacity`.

**Threshold mode** (`maximizeProfit = false`): The goal is to push the AMM rate as close as possible to the book rate — ideally making them equal — while still achieving `profit ≥ minProfit`. Uses a **two-tier check**:

1. First check with `accountForFees = false`: compute AMM capacity as if targeting `ammRate = bookRate` (ignoring fees), because the ideal outcome is rate convergence. If `bookSize > ammSize`, transition down.
2. If AMM can absorb at the fee-ignoring rate, compute actual profit — if `≥ minProfit`, accept (we successfully pushed AMM rate to book rate while remaining profitable).
3. If profit is insufficient, fall back to `accountForFees = true` (fee-adjusted rate) to find a smaller but still profitable arb size.

**Binary search refinement** (`_calcFinalArbSize` + `_binSearch`):

After sweep, refines within the boundary tick. The optimal additional size is bounded by:

```
optimalMore = min(tickSize, maxWithAMM_atMaxProfit − curWithBook)
maxMore = min(tickSize, maxWithAMM_atMinProfit − curWithBook)
```

Binary search finds the largest `more ∈ [0, maxMore]` satisfying both IM and (if `more > optimalMore`) profit constraints. This means: up to `optimalMore`, only IM is checked (profit is guaranteed); beyond that, profit must also exceed `minProfit`.

---

## SettleSimMath — Settlement Projection

**Source**: `contracts/bots/math/SettleSimMath.sol`

### Purpose

Simulates the impact of a pending funding rate update on user health **before** execution. Answers: "Will this user become undercollateralized after the next funding rate settlement?" Used by the health-jump detection bot and proactive deleverager.

### Core Formulas

**Position value** (from `PaymentLib`):

```
positionValue(signedSize, rMark, timeToMat) = signedSize × rMark × timeToMat / (ONE × YEAR)
```

**Settlement payment** (from `PaymentLib.calcSettlement`):

```
settlement(signedSize, fIndex_before, fIndex_after)
    = signedSize × (floatingIndex_after − floatingIndex_before)           // floating interest
    − |signedSize| × (feeIndex_after − feeIndex_before)                  // settlement fee
```

The floating interest component can be positive or negative depending on rate direction and position side. The settlement fee is always negative (cost to the user).

**New FIndex construction** (from `calcNewFIndex`):

```
newFIndex = FIndex(
    fundingTimestamp,
    oldFloatingIndex + fundingRate,
    calcNewFeeIndex(oldFeeIndex, settleFeeRate, fundingTimestamp − oldFTime)
)
```

where `calcNewFeeIndex = oldFeeIndex + settleFeeRate × (timePassed) / (ONE × YEAR)` (rounding up).

### Setup — `settleAndCreate`

1. Settle all existing positions via `marketHub.settleAllAndGet`
2. Record post-settlement cash
3. For each non-matured market, snapshot two states:
   - **marketBefore**: current FIndex, current timeToMat, current rMark
   - **marketAfter**: new FIndex (with pending update applied), reduced timeToMat, same rMark

The "before" and "after" states share the same rMark — the simulation assumes mark rate doesn't change during the funding update (conservative for health-jump detection).

### Value/MM Before and After

**Before settlement** (`calcTotalValueMMBefore`):

```
totalValue = accCash + Σᵢ positionValue(sizeᵢ, rMarkᵢ_before, timeToMatᵢ_before)
totalMM = Σᵢ calcMM(marketᵢ_before, sizeᵢ, kMMᵢ)
```

**After settlement** (`calcTotalValueMMAfter`):

```
totalValue = accCash
           + Σᵢ [settlement(sizeᵢ, fIndexᵢ_before, fIndexᵢ_after)
               + positionValue(sizeᵢ, rMarkᵢ_after, timeToMatᵢ_after)]
totalMM = Σᵢ calcMM(marketᵢ_after, sizeᵢ, kMMᵢ)
```

### Delta Position Value

```
deltaPositionValue = Σᵢ [positionValue(sizeᵢ, rMarkᵢ_after, tᵢ_after) − positionValue(sizeᵢ, rMarkᵢ_before, tᵢ_before)]
```

Since rMark stays the same: `deltaPositionValue = Σᵢ sizeᵢ × rMarkᵢ × (tᵢ_after − tᵢ_before) / (ONE × YEAR)`. This is purely the effect of time passage on position value.

### FIndex Update Verification

`calcNewFIndex` validates the pending funding rate report against the appropriate oracle, replicating the same verification logic as FundingRateVerifier:

| Oracle | Verification |
|--------|-------------|
| Chainlink | `ChainlinkVerifierLib.verifyFundingRateReport(report, oracle, feedId, maxFee, period, lastFTime)` |
| ChaosLabs | `ChaosLabsVerifierLib.verifyFundingRateReport(updateId, oracle, typeHash, market, period, lastFTime)` |
| Pendle | `PendleVerifierLib.verifyFundingRateReport(oracle, period, lastFTime)` |

Each verifier returns `(fundingRate, fundingTimestamp)` after validating: correct feed, sequential epoch, correct period. See `contracts/funding-oracle.md` for the full on-chain pipeline.

---

## Tick Sweep State Machine

Both LiquidationMath and ArbitrageMath use `TickSweepStateLib` for adaptive orderbook traversal. See `contracts/router-math-libs.md`, "Shared Infrastructure — TickSweepStateLib" section for the full state machine documentation (stage transitions, getLastTickAndSumSize/getSumCost semantics).

---

## Shared Formulas Reference

### Payment Functions (from `PaymentLib`)

| Function | Formula | Rounding |
|----------|---------|----------|
| `calcPositionValue(s, r, t)` | `s × r × t / (ONE × YEAR)` | Floor (rawDivFloor) |
| `calcUpfrontFixedCost(cost, t)` | `cost × t / YEAR` | Ceil (rawDivCeil) |
| `calcFloatingFee(|s|, rate, t)` | `|s| × rate × t / (ONE × YEAR)` | Up (rawDivUp) |

### Rounding Conventions

| Operation | Direction | Rationale |
|-----------|-----------|-----------|
| IM / MM | Round up | Conservative — overestimate margin requirement |
| Position value | Round down (floor) | Conservative — underestimate asset value |
| Incentive | Round down (mulDown) | Less incentive = safer for protocol |
| Upfront cost | Round up (ceil) | Overestimate cost = conservative |
| Fees | Round up | Overcharge fees = protocol-safe |

All rounding is "against the user, in favor of the protocol" — the standard conservative convention.

### Constants

```
ONE      = 1e18                      // Fixed-point unit
IONE     = 1e18 (int256)             // Signed fixed-point unit
YEAR     = 365 days                  // Seconds per year
ONE_MUL_YEAR = 1e18 × 365 days      // Combined scaling denominator
```
