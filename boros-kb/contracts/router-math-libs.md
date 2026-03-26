---
description: Router math libraries — full mathematical derivations and correctness proofs for SwapMath (book-AMM split) and LiquidityMath (single-sided liquidity addition)
last_updated: 2026-03-18
related:
  - contracts/bot-math-libs.md
  - contracts/amm.md
  - contracts/order-lifecycle.md
  - contracts/margin-engine.md
  - contracts/architecture.md
---

# Router Math Libraries — Derivations and Proofs

Source: `contracts/core/router/math/`. Two libraries that compute optimal orderbook-AMM trade splitting for the Router. This document derives every formula, proves correctness of the algorithms, and explains *why* they are designed this way.

**Notation**: Same as `contracts/bot-math-libs.md`. All arithmetic is 18-decimal fixed-point (`ONE = 1e18`). `YEAR = 365 days`. See that document for `PaymentLib` formulas. We use `|x|` for absolute value and `sign(x)` for sign.

---

## SwapMath — Optimal Book-AMM Trade Splitting

**Source**: `contracts/core/router/math/SwapMath.sol` (two libraries: `SwapMathLib` + `SwapMathHighLevelLib`)

### Problem Statement

A user wants to trade `totalSize` (signed, in `userSide`). Two venues are available:
1. **Orderbook**: discrete liquidity at specific ticks (rates)
2. **AMM**: continuous liquidity with an implied rate that moves as you trade

**Goal**: Split `totalSize = withBook + withAMM` to give the user the best execution — fill at the AMM when it's cheaper than the book (after fees), fill on the book otherwise.

### Why This Split Matters

Without splitting, the user would trade entirely on one venue:
- Book-only: misses cheaper AMM liquidity when the AMM rate is better
- AMM-only: suffers excessive price impact for large trades when the book has better rates

The optimal strategy fills the AMM up to the point where its fee-adjusted rate equals the book's fee-adjusted rate, then fills the rest on the book. SwapMath implements this.

### Fee-Adjusted Rate Conversion

The core insight: to compare book and AMM prices on equal footing, all fees must be included.

**Step 1: Book tick → base rate** (`convertBookTickToBaseRate`):

The user trades on the book at `bookRate` (from the tick) and pays `takerFeeRate`:

```
userSide = LONG:   baseRate = bookRate + takerFeeRate    (buying costs more)
userSide = SHORT:  baseRate = bookRate − takerFeeRate    (selling receives less)
```

The base rate is the user's all-in cost of trading on the book at this tick.

**Step 2: Base rate → AMM rate** (`convertBaseRateToAMMRate`):

For the user to be indifferent between book and AMM, the AMM's implied rate (after AMM fees) must equal the base rate:

```
userSide = LONG:   ammRate = baseRate − ammAllInFeeRate   (AMM must be cheaper to justify using it)
userSide = SHORT:  ammRate = baseRate + ammAllInFeeRate   (AMM must offer higher rate)
```

where `ammAllInFeeRate = ammOtcFeeRate + ammInternalFeeRate`.

**Why subtract for LONG and add for SHORT?**

For a LONG user:
- Book all-in cost = `bookRate + takerFeeRate` (higher is worse)
- AMM all-in cost = `ammRate + ammAllInFeeRate` (higher is worse)
- Indifference: `bookRate + takerFeeRate = ammRate + ammAllInFeeRate`
- Solve: `ammRate = bookRate + takerFeeRate − ammAllInFeeRate`

For a SHORT user:
- Book all-in revenue = `bookRate − takerFeeRate` (lower is worse)
- AMM all-in revenue = `ammRate − ammAllInFeeRate` (lower is worse)
- Indifference: `bookRate − takerFeeRate = ammRate − ammAllInFeeRate`
- Solve: `ammRate = bookRate − takerFeeRate + ammAllInFeeRate`

### `calcSwapAMMToBookTick` — How Much AMM to Fill

Given a book tick, computes the maximum AMM swap that pushes the AMM's implied rate to the fee-adjusted indifference point:

```
1. baseRate = convertBookTickToBaseRate(bookTick)
2. ammRate = convertBaseRateToAMMRate(baseRate)
3. swapSize = AMM.calcSwapSize(ammRate)    // how much to swap to push AMM rate to ammRate
4. return isOfSide(swapSize, userSide) ? swapSize : 0
```

The sign check (step 4) ensures we only return AMM fills in the user's direction. If pushing the AMM to the target rate would require trading in the opposite direction, the AMM is already beyond that rate and returns 0.

**Why push AMM to *this specific* rate?** At this rate, the user is indifferent between AMM and book after fees. Any AMM liquidity at a better rate than this is strictly cheaper than the book — so we should use the AMM. Any AMM liquidity beyond this rate is more expensive than the book — so we should use the book.

### Cost Computations

**AMM cost** (`calcSwapAMM`):

```
ammCost = AMM.swapView(ammSwapSize)              // annualized cost from AMM curve
netCashToAMM = upfrontFixedCost(ammCost, t)      // convert to upfront (scale by timeToMat/YEAR)
netCashIn = netCashToAMM + ammOtcFee(|ammSwapSize|)   // add OTC fee
```

The AMM returns an annualized cost; `upfrontFixedCost` converts to the actual cash amount paid for this maturity. The OTC fee is a separate protocol fee on the swap notional.

**Book cost** (`calcSwapBook`):

```
netCashIn = upfrontFixedCost(bookCost, t) + bookTakerFee(|bookSwapSize|)
```

`bookCost` is the sum of `size × rate` across matched ticks (annualized). `bookTakerFee` is the taker fee on notional.

### Main Algorithm — `calcSwapAmountBookAMM`

**Input**: `totalSize` (signed trade size), `limitTick` (worst acceptable price)

**Output**: `(withBook, withAMM)` such that `withBook + withAMM = totalSize`

**Algorithm**:

```
1. Create tick sweep on matching side (opposite of userSide)
2. For each tick batch/tick:
   a. Check canMatch(limitTick, lastTick) — is this tick within price limit?
   b. Compute tmpWithAMM = calcSwapAMMToBookTick(lastTick)
   c. Compute tmpWithBook = accumulated book size
   d. newTotalSize = tmpWithBook + tmpWithAMM
   e. If |newTotalSize| > |totalSize|: transitionDown (we overshot)
   f. If newTotalSize == totalSize: return immediately (exact match)
   g. Else: accept tick, transitionUp
3. After sweep: _calcFinalSwapAmount for the boundary case
```

**Phase 2 — Final split** (`_calcFinalSwapAmount`):

After the sweep identifies the boundary tick (or exhausts all ticks):

```
finalTick = canMatch(limitTick, lastTick) ? lastTick : limitTick
maxWithAMM = calcSwapAMMToBookTick(finalTick)
withAMM = min(|totalSize − withBook|, |maxWithAMM|) × sign(userSide)
withBook = totalSize − withAMM
```

The AMM gets as much as it can absorb up to the final tick's rate (capped by remaining size). The book gets the residual.

**Why `withBook = totalSize − withAMM` instead of accumulated book size?** The accumulated `withBook` tracks confirmed book fills from the sweep. But in the final step, we may need more book fill than what the sweep confirmed (if the AMM can't absorb all remaining size). By computing `withBook = totalSize − withAMM`, we ensure the total is always exact. The actual book fill happens via a limit order placed at `limitTick` — if the book can't fill it, the order goes unfilled (subject to TIF enforcement).

### `limitTick` and `canMatch` — Price Protection

`limitTick` is the user's worst acceptable rate. `canMatch(limitTick, lastTick)` checks:

```
matchingSide = userSide.opposite()
matchingSide sweeps top-down (LONG):  limitTick ≤ lastTick   (limit below best bid)
matchingSide sweeps bottom-up (SHORT): limitTick ≥ lastTick   (limit above best ask)
```

If the best available tick is beyond the limit, the sweep stops. The final tick falls back to `limitTick`, and the AMM gets whatever it can absorb at the limit rate. Remaining size goes to the book as a limit order (may not fill).

**Caller context**:
- Normal swaps: `limitTick` from user's order parameters (price protection)
- Liquidity removal swaps: `limitTick = MAX_TICK` (LONG) or `MIN_TICK` (SHORT) — no price limit, fill at any price

### Correctness Argument

**Claim**: The algorithm produces the minimum-cost split for the user.

**Informal proof**: The AMM's implied rate monotonically worsens as you trade more (by the AMM's constant-product invariant). The book's rate is discrete and worsens tick by tick. At each tick, we fill the AMM up to the point where `AMM_rate + AMM_fees = book_rate + taker_fee`. Any AMM fill below this point is cheaper than the book; any AMM fill beyond is more expensive.

The sweep processes ticks from best to worst, accumulating both AMM and book capacity. When total capacity first exceeds `totalSize`, we've found the boundary — the exact crossover point where the optimal split lies. Binary search within the boundary tick (via `TickSweepState`) pins down the exact amount.

---

## LiquidityMath — Single-Sided Liquidity Addition

**Source**: `contracts/core/router/math/LiquidityMath.sol`

### Problem Statement

A user wants to add liquidity to the AMM with only cash (no existing position). The AMM's `mintByBorosRouter` requires **proportional** cash + size contributions matching the AMM's current ratio. So the user must first **swap** to acquire the right amount of position, then contribute both to the AMM.

**Goal**: Find `(withBook, withAMM)` — the swap amounts that, after execution, leave the user with exactly the right cash/size ratio for a proportional mint.

### Why This Is Hard

Three interacting effects make this a nonlinear problem:

1. **AMM state changes during swap**: Swapping with the AMM shifts its implied rate and its cash/size ratio. The target ratio (for minting) depends on the AMM's *post-swap* state, which depends on how much you swapped.

2. **Fees consume cash**: Taker fees, OTC fees, and the mint OTC fee all reduce the user's available cash. More swapping → more fees → less cash for the mint contribution.

3. **Book fills are discrete**: The book provides liquidity at specific ticks, not at arbitrary amounts. The exact split depends on which ticks have liquidity.

These coupled effects mean there's no closed-form solution. LiquidityMath uses **iterative approximation** — sweep the book for a coarse answer, then binary search within the boundary tick for the precise split.

### Setup — `_createLiquidityMathParams`

From `AMMModule._createLiquidityMathParams`:

```
ammCash, ammSize = settleAndGetCashAMM(amm)     // AMM's current state
userSide = ammSize > 0 ? LONG : SHORT           // user swaps IN THE SAME DIRECTION as AMM
totalCashIn = req.netCashIn                      // user's total cash budget
```

**Why `userSide = same direction as AMM`?** The user needs to acquire position to contribute to the AMM. The AMM holds position in some direction (e.g., LONG). The user must also contribute LONG position. To acquire LONG position, the user buys (LONG) on the book/AMM. So the user's swap side matches the AMM's position direction.

**Key insight**: `userSide == ammSide` — noted in the code comment. This is unusual: normally in a swap, the user trades *against* the AMM. Here, the user trades *with* the AMM in the same direction by simultaneously trading on the book.

### The Proportionality Condition — `_trySwap`

After a candidate swap `(ammSwapSize, bookSwapSize, bookCost)`, compute the resulting state:

**Step 1 — Compute total swap cost:**

```
netSizeOut = bookSwapSize + ammSwapSize              // total position acquired

(netCashIn_amm, cashToAMM) = calcSwapAMM(ammSwapSize)   // AMM swap cost + cash paid to AMM
netCashIn = netCashIn_amm
          + calcSwapBook(bookSwapSize, bookCost)         // book swap cost
          + calcAmmOtcFee(netSizeOut)                    // mint OTC fee (on total size transferred)
```

The mint OTC fee is pre-accounted because the subsequent `_mintAMM` will charge it on the size contribution.

**Step 2 — Check budget constraint:**

```
if netCashIn ≥ totalCashIn → SWAP_LESS_SIZE
```

If the swap costs exhaust (or exceed) the user's entire cash budget, nothing is left for the cash portion of the mint. Swap less.

**Step 3 — Check AMM capacity:**

```
if |ammSwapSize| ≥ |ammSize| → SWAP_LESS_SIZE
```

Cannot swap out the AMM's entire position — this would leave the AMM with zero size, making the proportionality condition degenerate (division by zero in the ratio).

**Step 4 — The proportionality check:**

After the swap, the user will contribute to the AMM:
- **Size contribution**: `netSizeOut` (all acquired position goes to the AMM)
- **Cash contribution**: `totalCashIn − netCashIn` (remaining cash after swap costs)

The AMM's state after the swap:
- **AMM cash**: `ammCash + cashToAMM` (received cash from AMM swap)
- **AMM size**: `ammSize − ammSwapSize` (gave away position in AMM swap)

For a proportional mint:

```
netSizeOut / (totalCashIn − netCashIn) = (ammSize − ammSwapSize) / (ammCash + cashToAMM)
```

Cross-multiplying (and taking absolute values since size can be negative):

```
sizeNumerator = |netSizeOut × (ammCash + cashToAMM)|
cashNumerator = |(totalCashIn − netCashIn) × (ammSize − ammSwapSize)|
```

**Decision logic:**

```
sizeNumerator > cashNumerator → SWAP_LESS_SIZE
isASmallerApproxB(sizeNumerator, cashNumerator, eps) → SATISFIED
otherwise → SWAP_MORE_SIZE
```

where `isASmallerApproxB(a, b, eps) = (a ≤ b) AND (a ≥ b × (1 − eps))`.

### Deriving the Proportionality Condition

**Why `sizeNumerator ≤ cashNumerator`?**

The mint function accepts `exactSizeIn` (fully consumed) and computes the proportional cash. If the user provides more size relative to cash than the AMM's ratio, the mint would require more cash than the user has. Formally:

The AMM mints LP proportional to the smaller of the two contributions:

```
LP_from_size = totalLP × exactSizeIn / ammSize_postSwap
LP_from_cash = totalLP × cashIn / ammCash_postSwap
```

We need `LP_from_size ≤ LP_from_cash` so that all size is consumed (the "size must be used completely" constraint). This gives:

```
exactSizeIn / ammSize_postSwap ≤ cashIn / ammCash_postSwap
exactSizeIn × ammCash_postSwap ≤ cashIn × ammSize_postSwap
```

Which is exactly `sizeNumerator ≤ cashNumerator`. ∎

**Why approximate equality, not exact?**

The swap cost is a nonlinear function of swap size (the AMM's price curve is nonlinear). Binary search can only converge to within some tolerance. The epsilon `eps` (configurable via `_getEpsAddLiquidity()`) defines "close enough." If `sizeNumerator` is within `eps` fraction below `cashNumerator`, the split is accepted. The mint will slightly over-contribute cash (user gets marginally more LP than strictly proportional), which is harmless.

### Why Not Just Solve Analytically?

The equation `netSizeOut × ammCash_postSwap = cashRemaining × ammSize_postSwap` is:

```
(bookSize + ammSwap) × (ammCash + swapView(ammSwap) × t/Y) = (totalCash − costs(bookSize, ammSwap)) × (ammSize − ammSwap)
```

where `swapView(ammSwap)` is a nonlinear function of the AMM's constant-product curve (involving exponentiation), and `costs()` includes multiple fee terms. This equation has no closed-form solution in general. Numerical methods (binary search with tolerance) are the standard approach.

### Main Algorithm — `approxSwapToAddLiquidity`

**Phase 1 — Tick sweep:**

Same `TickSweepState` pattern as SwapMath and the bot math libs, but with a three-way decision:

```
For each tick batch:
  1. Compute tmpWithAMM = calcSwapAMMToBookTick(lastTick)
  2. Compute tmpWithBook = accumulated book size
  3. Compute tmpBookCost = accumulated book cost
  4. res = _trySwap(tmpWithAMM, tmpWithBook, tmpBookCost)
  5. SATISFIED → return immediately
     SWAP_MORE_SIZE → accept tick, transitionUp
     SWAP_LESS_SIZE → transitionDown
```

**Phase 2 — Binary search refinement** (`_calcFinalLiquidity`):

After finding the boundary tick, binary search for the exact split:

```
_getBinSearchParams:
  if FOUND_STOP:
    bookRate = rate at boundary tick
    maxAbsMoreWithAMM = calcSwapAMMToBookTick(boundaryTick) − curWithAMM
    guessMax = maxAbsMoreWithAMM + tickSize
  if SWEPT_ALL:
    bookRate = 0            // no more book ticks available
    maxAbsMoreWithAMM = |ammSize| − |curWithAMM|
    guessMax = maxAbsMoreWithAMM
```

The binary search variable `guess` represents additional size to swap (beyond what the sweep accumulated). It's distributed between AMM and book:

```
absMoreWithAMM = min(guess, maxAbsMoreWithAMM)     // AMM gets priority
moreWithBook = guess − absMoreWithAMM               // book gets remainder
tmpWithAMM = curWithAMM + absMoreWithAMM × sign(userSide)
tmpWithBook = curWithBook + moreWithBook × sign(userSide)
tmpBookCost = curBookCost + moreWithBook × bookRate  // approximate: uses boundary tick rate
```

For each iteration, `_trySwap` is called. If SATISFIED, return. If SWAP_MORE, raise `guessMin`. If SWAP_LESS, lower `guessMax`.

**Termination**: The loop runs for at most `maxIteration` steps. If no SATISFIED state is found, reverts with `"Slippage: APPROX_EXHAUSTED"`. This is a slippage protection — if the market moved too much during the transaction, the approximation can't converge.

### The SWEPT_ALL Case — Why `bookRate = 0`?

When all book ticks are exhausted, there are no more book ticks to fill at. The binary search only varies AMM size:

```
guess ≤ guessMax ≤ maxAbsMoreWithAMM
absMoreWithAMM = min(guess, maxAbsMoreWithAMM) = guess
moreWithBook = guess − guess = 0
```

Setting `bookRate = 0` is safe because `moreWithBook` is always 0 in this path — the book rate is never used. The search adjusts only the AMM amount until the proportionality condition is satisfied.

### Why AMM Gets Priority in the Binary Search

In the `guess` distribution:

```
absMoreWithAMM = min(guess, maxAbsMoreWithAMM)    // AMM first
moreWithBook = guess − absMoreWithAMM              // book gets residual
```

This prioritizes AMM liquidity over book liquidity. The reason is simple: when the AMM implied rate sits between two orderbook ticks (`tick1 < ammRate < tick2`), the AMM offers a better rate than the next book tick. So you fill with AMM first to push the AMM rate toward `tick2`. Once the AMM rate reaches `tick2`, the book becomes equal or better, and you switch to filling from the orderbook. `maxAbsMoreWithAMM` caps the AMM fill at exactly this crossover point.

### Convergence Proof

**Claim**: Binary search converges to SATISFIED within `O(log(maxRange / eps))` iterations.

**Proof sketch**: The proportionality ratio `sizeNumerator / cashNumerator` is monotonically increasing in `guess`:

- More swap size → larger `netSizeOut` → larger `sizeNumerator`
- More swap size → more fees → less remaining cash → smaller `cashNumerator`
- Both effects push the ratio higher

So there exists a unique `guess*` where `sizeNumerator = cashNumerator`. Below `guess*`, the ratio is below 1 (SWAP_MORE). Above `guess*`, the ratio exceeds 1 (SWAP_LESS). The eps-band around `guess*` is the SATISFIED region. Binary search finds this in `⌈log₂(guessMax)⌉` steps.

**Why monotonic?** Let `g = guess` and `f(g) = sizeNumerator(g) / cashNumerator(g)`:

- `netSizeOut(g)` is linear increasing in `g` (more swap → more position)
- `netCashIn(g)` is increasing in `g` (more swap → more cost → less remaining cash for mint)
- `ammSize − ammSwapSize(g)` is decreasing in `g` (AMM gives away more position)
- `ammCash + cashToAMM(g)` is increasing in `g` (AMM receives more cash from swap)

So `sizeNumerator = |netSizeOut × (ammCash + cashToAMM)|` grows faster than `cashNumerator = |(totalCash − netCashIn) × (ammSize − ammSwap)|` shrinks. The ratio is strictly increasing. ∎

---

## Relationship to Bot Math Libraries

SwapMath and LiquidityMath share infrastructure with the bot math libs (see `contracts/bot-math-libs.md`):

| Component | SwapMath | LiquidityMath | LiquidationMath | ArbitrageMath |
|-----------|---------|---------------|-----------------|---------------|
| Tick sweep | TickSweepStateLib | TickSweepStateLib | TickSweepStateLib | TickSweepStateLib |
| Fee conversion | `convertBookTickToBaseRate` → `convertBaseRateToAMMRate` | via SwapMath core | `calcSwapAMMToBookRate` | `convertBookRateToAMMRate` |
| Binary search | Size-level (within boundary tick) | Size-level + proportionality | Size-level (dual constraint) | Size-level (IM + profit) |
| Decision function | `|total| > |target|` | `_trySwap` (proportionality) | `_tryLiquidate` (IM + HR) | `checkEnoughIM` + profit |

All four libraries follow the same two-phase pattern: **tick sweep** (coarse) → **binary search within boundary tick** (fine). The difference is the decision function evaluated at each candidate split.

**SwapBoundMath is NOT used by SwapMath/LiquidityMath** — the router libs directly compute fees and rates from their own params struct. SwapBoundMath is bot-specific because it also captures margin parameters (IM/MM) which the router doesn't need for split computation.

---

## Shared Infrastructure — TickSweepStateLib

All four math libraries (SwapMath, LiquidityMath, LiquidationMath, ArbitrageMath) use `TickSweepStateLib` for adaptive orderbook traversal. The state machine finds the boundary tick where a constraint first fails, then hands off to a size-level binary search within that tick.

### Stage Transitions

```
                    ┌──── transitionUp ────┐
                    │                      ▼
            LOOP_BATCH ──transitionDown──▶ LOOP_SINGLE ──transitionDown──▶ FOUND_STOP
                │                              │
                │ (>4 ticks)                   └──── transitionUp ────▶ (next index)
                │
                └──transitionDown──▶ BINARY_SEARCH ──transitionDown──▶ FOUND_STOP
                                           │
                                           └── transitionUp ──▶ (narrow range)
```

**LOOP_BATCH**: Sweep ticks in batches of `nTicksToTryAtOnce`. Queries `market.getNextNTicks()` for the next batch. When the constraint first fails (transitionDown), enters either LOOP_SINGLE (≤4 ticks) or BINARY_SEARCH (>4 ticks) to find the exact boundary within the batch.

**LOOP_SINGLE**: Linear scan through individual ticks in the current batch. transitionDown → FOUND_STOP. transitionUp → advance to next tick index.

**BINARY_SEARCH**: Binary search over tick indices `[bin_min, bin_max]` within the batch. transitionUp narrows from below (`bin_min = mid + 1`), transitionDown narrows from above (`bin_max = mid`).

**FOUND_STOP**: The last accepted tick is known. The caller performs a secondary binary search within that tick (size-level, not tick-level).

**SWEPT_ALL**: All available ticks were accepted. No boundary found within the book.

### getLastTickAndSumSize Semantics

Returns the last tick being considered and the total available size:

| Stage | Last tick | Sum size |
|-------|-----------|----------|
| LOOP_BATCH | Last tick in current batch | Sum of all tick sizes in batch |
| LOOP_SINGLE | Tick at singleIndex | Size at singleIndex |
| BINARY_SEARCH | Tick at singleIndex | Sum of sizes from bin_min to singleIndex (inclusive) |
| FOUND_STOP | Tick at singleIndex | Size at singleIndex |

### getSumCost Semantics

Returns the total cost (size × rate) for the ticks in the current range, accounting for the correct sign based on trade side.

---

## Fee Structure Summary

| Fee | Paid on | Computation |
|-----|---------|-------------|
| `takerFeeRate` | Book swap notional | `|bookSize| × takerFeeRate × timeToMat / (ONE × YEAR)` |
| `ammOtcFeeRate` | AMM swap notional | `|ammSize| × ammOtcFeeRate × timeToMat / (ONE × YEAR)` |
| `ammInternalFeeRate` | AMM swap (internal) | Built into `IAMM.feeRate()`, part of AMM cost |
| `ammAllInFeeRate` | Combined AMM fee | `ammOtcFeeRate + ammInternalFeeRate` |
| Mint OTC fee | Mint size | `|netSizeOut| × ammOtcFeeRate × timeToMat / (ONE × YEAR)` (LiquidityMath only) |

`getBestFeeRates(user, amm)` returns the best available taker and OTC fee rates for the user-AMM pair, accounting for any fee discounts.
