---
description: AMM design — PositiveAMM and NegativeAMM variants, constant-product-like invariant, LP mint/burn, oracle, and withdraw-only mode
last_updated: 2026-03-18
related:
  - contracts/architecture.md
  - contracts/rate-oracles.md
  - contracts/settlement.md
---

# AMM

Boros provides on-chain liquidity through two AMM variants: **PositiveAMM** (for positive funding rates) and **NegativeAMM** (for negative rates). NegativeAMM mirrors PositiveAMM via a rate-space transformation so the same math applies in both regimes. Each AMM instance is bound to a single market and token pair and is created by `AMMFactory`.

---

## Intuition: How the AMM Formula Is Derived

The AMM formula isn't arbitrary — it's built up from a few key observations about interest rate swaps.

### Abstract token model

A rate swap can be decomposed into two abstract streams:
- **Float stream token**: right to receive floating interest on 1 ETH until maturity
- **Fixed stream token**: right to receive 1% APR on 1 ETH until maturity (so at 1 year to maturity, 1 Fixed stream token ≈ 0.01 ETH)

In Boros, when a user opens a swap, the fixed stream is converted into collateral immediately. So each participant (including the AMM) effectively holds Float stream tokens + collateral (≈ Fixed stream tokens). This means the AMM is just a two-token spot AMM trading Float tokens ↔ Fixed tokens, and the "price" of 1 Float token in Fixed tokens gives us the **Implied APR**.

### Why xy = k doesn't quite work

Applying Uniswap V2's `xy = k` to these abstract tokens works initially, but Float stream tokens can have a **negative price** (negative rates), so the AMM could be pushed into a state where it holds an unbounded long position and gets liquidated. Two mitigations:
1. **Min/max rate bounds** (`minAbsRate`, `maxAbsRate`) cap the AMM's exposure
2. **Buffer**: total Fixed stream supply is split into a tradable portion `y` and a buffer `B` reserved to protect the AMM against negative rate scenarios

### Why time-weighting

As time passes, the value of 1 Fixed stream token shrinks (less time to accrue interest), but the AMM's collateral is physical ETH — it doesn't shrink. So the equivalent Fixed stream token count grows over time, breaking the 50:50 balance. At 6 months to maturity, a pool that started 50:50 becomes 1:2 (Float:Fixed by value). The time-weighted exponent `t` corrects for this, keeping the implied rate stable when no trades occur: `x^t × y = L^(t+1)`.

### Why the curve is shifted (the `a` parameter)

Shifting the curve left by `a` lets `totalFloatAmount` go negative — meaning the AMM flips from long to short. This improves capital efficiency: the AMM can be more aggressive in selling Float tokens because it has room to go short. The **Flip APR** is where the AMM holds zero position. In practice, Flip APR is set high enough that the AMM rarely flips short, avoiding liquidation risk on the short side.

### Negative rate AMM

A position of size `x` at rate `-r` is equivalent to position `-x` at rate `r`. So NegativeAMM is just PositiveAMM with `x` negated: `(-x + a)^t × y = L^(t+1)`.

---

## AMMState Struct

Every AMM stores an `AMMState` with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `totalFloatAmount` | uint256 | Float reserve — one side of the two-reserve pool |
| `normFixedAmount` | uint256 | Normalized fixed reserve — the other side |
| `totalLp` | uint256 | Total LP token supply (BOROS20) |
| `latestFTime` | uint40 | Timestamp of the last oracle/interaction update |
| `maturity` | uint40 | Market maturity timestamp |
| `seedTime` | uint40 | AMM creation / seed timestamp |
| `minAbsRate` | uint128 | Lower bound of the allowed implied rate |
| `maxAbsRate` | uint128 | Upper bound of the allowed implied rate |
| `cutOffTimestamp` | uint40 | After this timestamp, swaps and mints are blocked |

---

## Core Invariant (PositiveAMMMath)

The AMM uses a time-weighted constant-product invariant (derived from the abstract token model above):

```
Liquidity = totalFloatAmount^t × normFixedAmount
```

where:

```
t = normalizedTime = (maturity - latestFTime) / (maturity - seedTime)
```

`t` ranges from 1 (at seed) to 0 (at maturity). At `t = 1` this is standard `xy = k`. As `t` approaches 0 the curve flattens, concentrating liquidity near the current rate — this compensates for the growing Fixed stream token count as collateral's time-value shrinks toward maturity.

The **implied rate** at any point is:

```
impliedRate = normFixedAmount / totalFloatAmount
```

This is the "price" of Float tokens in Fixed tokens — i.e., the APR the market prices floating interest at.

---

## Swap — `calcSwapOutput`

Given a `floatOut` amount (float tokens leaving the pool), the function computes the `fixedIn` required to maintain the invariant.

1. Compute current `liquidity = totalFloatAmount^t × normFixedAmount`.
2. Derive `newTotalFloat = totalFloatAmount - floatOut`.
3. Compute `newNormFixed = liquidity / newTotalFloat^t`.
4. **Rate bounds check**: the new implied rate `newNormFixed / newTotalFloat` must lie within `[minAbsRate, maxAbsRate]`. Reverts with `AMMInvalidRateRange` otherwise.
5. `normFixedIn = newNormFixed - normFixedAmount`.
6. **Un-normalize**: `fixedIn = normFixedIn / normalizedTime`. This converts from the normalized space back to actual fixed amounts. The division by `t` means that as maturity approaches, the same normalized change requires a larger actual fixed payment.

The AMM does not execute the trade itself. Instead, `AMM.swapByBorosRouter()` computes the rate and the Router places a corresponding OTC trade in the Market contract on behalf of the AMM's own account.

---

## Mint — `calcMintOutput`

Minting LP tokens is proportional to the minter's contribution relative to the existing pool.

- **If the AMM has no existing position (size == 0)**: the LP share is proportional to the cash contributed.
- **If the AMM has an existing position (size != 0)**: the LP share is proportional to the size contribution. Direction-aware rounding applies — if the position value is positive, the contribution is floored; if negative, it is ceiled. This prevents rounding exploits where an LP could extract fractional value.

Both reserves (`totalFloatAmount` and `normFixedAmount`) scale proportionally with the new LP share.

---

## Burn — `calcBurnOutput`

Burning LP tokens withdraws a proportional share of both reserves.

- **Before maturity**: the burner receives proportional cash and size (position).
- **After maturity**: the burner receives only cash — no size is returned. This is because all positions have settled at maturity.

Size output uses direction-aware rounding: positive value is floored, negative value is ceiled. This ensures the AMM is never left holding fractional dust in an unfavorable direction.

---

## `calcSwapSize` — Reverse Swap

Given a **target rate**, `calcSwapSize` computes the largest swappable size such that the resulting implied rate is not worse than `targetRate`. This uses power math (exponentiation by `t`) and is the inverse of `calcSwapOutput`. Used by the Router to size AMM trades when routing against a desired rate.

Key semantics (PR #347):
- Returns 0 (instead of reverting) when cutoff is reached or AMM is withdraw-only. This allows `removeLiquiditySingleCash` to work after cutoff or deleverage.
- Returns 0 when `targetRate` is approximately equal to the current implied rate (EPS = 10), to avoid returning dust sizes from rounding errors.
- Rate clamping is applied to `targetRate` before the approximate equality check (PR #369 fix).

---

## Small Size Snap-to-Zero — `_snapSmallSizeTo0`

For very small position sizes, a tiny change in `sizeIn` can cause disproportionately large changes in the required cash deposit. This is an inherent property of the proportional LP math.

The most extreme case is `size = 1 wei`. Since LP share is proportional to `sizeIn / existingSize`, minting with 1 wei of size contribution would require the minter to deposit cash equal to the **entire cash balance currently in the AMM** — a clearly degenerate outcome that would trap capital.

`_snapSmallSizeTo0` eliminates this by treating sizes below a small threshold as zero. When size is snapped to zero, the mint path falls back to the cash-proportional branch (no position contribution), which behaves normally regardless of how small the amount is.

Without this snap, an attacker could also grief the pool by leaving dust-sized positions that make subsequent LP operations unreasonably expensive.

---

## BOROS20 — Non-Standard ERC20

**Source**: `contracts/core/amm/BOROS20.sol`

BOROS20 is the LP token for AMM pools. It is **not** a standard ERC20:

- **Balances are indexed by `MarketAcc`** (a packed account identifier), not by `address`. This aligns with the rest of Boros where accounts are identified by `MarketAcc`.
- **No `transfer`, `approve`, or `allowance` functions**. LP tokens are non-transferable — each LP token corresponds to an active position in Boros, so transferring LP tokens would effectively be an OTC position transfer. All OTC-like transfers are intentionally blocked.
- **Only `mint` and `burn`** are exposed, callable exclusively by the AMM contract.
- **Events** (`Transfer`) emit `MarketAcc` instead of `address`.
- **Minimum liquidity**: On first mint, `10^6` LP tokens are permanently minted to `ACCOUNT_ONE` (`MarketAcc` wrapping `address(1)`). This prevents the total-supply-equals-zero edge case that plagues Uniswap v2 style pools.

---

## AMM as a Market Participant

The AMM holds a dedicated account in the Market: `SELF_ACC`, a `MarketAcc` constructed with `AMM_ACCOUNT_ID = 255`. This account is treated as a normal market participant — it has positions, receives settlement payments, and is subject to the same accounting rules.

The Router coordinates AMM interactions:

1. User calls `AMMModule.swap()` on the Router.
2. Router calls `AMM.swapByBorosRouter()`, which computes the implied rate change.
3. Router places a corresponding OTC trade in the Market between the user's account and `SELF_ACC`.
4. Market processes the trade, updating both positions.

This design means the AMM's positions are always reflected in Market state, and settlement works identically for AMM and non-AMM accounts.

---

## Withdraw-Only Mode

The function `_isWithdrawOnly()` checks whether `delevLiqNonce != 0`. This nonce is incremented when a liquidation or deleverage event involves the AMM's `SELF_ACC`. Once triggered:

- **No new swaps** — `swapByBorosRouter()` reverts with `AMMWithdrawOnly`.
- **No new mints** — LP minting is blocked.
- **Burns are still allowed** — existing LPs can exit.

This is a safety mechanism. The AMM maintains its own internal state (`totalFloatAmount`, `normFixedAmount`, `totalLp`) which must stay in sync with the AMM's external state in the Market (position size, cash balance). A liquidation or deleverage forcibly changes the external state (reduces position, moves cash) without going through the AMM's own math — the internal reserves no longer reflect reality, and there is no way to resync them cleanly. Allowing further swaps or mints against stale internal state would produce incorrect pricing and LP share calculations. See also invariant #9 in `contracts/invariants.md`.

---

## AMM Oracle

The AMM maintains its own implied rate oracle using `FixedWindowObservationLib`. This provides a **TWAP** (time-weighted average price) of the AMM's implied rate over a configurable window.

The oracle is updated on every Router interaction via the `onlyRouterWithOracleUpdate` modifier. The TWAP calculation is:

```
oracleRate = (lastTradedRate × elapsed + prevOracleRate × (window - elapsed)) / window
```

This smoothed rate is not currently consumed by other system components but is available for future use.

---

## cutOffTimestamp

The `cutOffTimestamp` is a configurable deadline that prevents trading too close to maturity. Once `block.timestamp >= cutOffTimestamp`:

- Swaps revert with `AMMCutOffReached`.
- Mints revert with `AMMCutOffReached`.
- Burns remain allowed so LPs can exit.

This avoids the pathological behavior of the invariant curve when `t` is very close to zero, where tiny float changes produce extreme rate swings.
