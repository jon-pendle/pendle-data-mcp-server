---
description: Margin engine — PM/IM/MM formulas, strict vs closing-only checks, cross-market aggregation, and health ratio
last_updated: 2026-03-17
related:
  - contracts/order-lifecycle.md
  - contracts/settlement.md
  - contracts/liquidation.md
  - risk/global/params-definitions.md
---

# Margin engine

The margin engine lives in `MarginViewUtils.sol` (per-market margin calculations) and `MarginManager.sol` (cross-market aggregation and final checks). It computes three margin tiers — Prescaling Margin (PM), Initial Margin (IM), and Maintenance Margin (MM) — and enforces them through strict or relaxed checks depending on whether the user is opening or closing.

---

## Prescaling Margin (PM) — `_calcPM()`

PM is the base margin layer before time/risk scaling, representing the position's raw rate exposure.

### Position-only PM

```
__calcPMFromRate(absSize, rMark, k_iThresh) = absSize * max(|rMark|, k_iThresh)
```

`k_iThresh` is a per-market floor that prevents PM from vanishing when the mark rate is near zero.

### Combined PM with open orders

Open orders create potential future exposure. The calculation nets orders against the existing position on each side:

**Long-side PM (`pmTotalLong`):**

- If the user has a short position and `longOrderSize <= |shortPosition|`: the long orders are fully hedged by the short position, so `pmTotalLong = 0`.
- If the user has a long position: `pmTotalLong = pmLong + pmAlone` (orders add to existing directional risk).
- If the user has a short position but `longOrderSize > |shortPosition|`: `pmTotalLong = pmLong - pmAlone`, clamped to 0 (orders partially offset by position).

**Short-side PM (`pmTotalShort`):** Mirror logic of the long side.

**Final PM:**

```
PM = max(pmTotalLong, pmTotalShort)
```

The max ensures the margin covers whichever directional scenario is worse.

---

## Initial Margin (IM) — `_calcIM()`

IM is the margin required to open or hold a position. It scales PM by a risk factor and time-to-maturity:

```
IM = PM * kIM * max(timeToMat, tThresh) / (ONE * YEAR)
```

| Parameter | Description |
|-----------|-------------|
| `kIM` | Per-market IM multiplier (higher = more conservative) |
| `tThresh` | Time threshold floor — prevents margin from becoming unreasonably small as maturity approaches |
| `timeToMat` | Seconds until market maturity |
| `ONE` | Fixed-point scaling constant (1e18) |
| `YEAR` | Seconds in a year (365 days) |

### Personalized kIM

`_kIM(userAddr)` supports per-account overrides. Whitelisted accounts (e.g., institutional market makers) can receive a lower kIM, reducing their margin requirements. Non-whitelisted accounts use the market's default kIM.

> **Note**: This feature is implemented for completeness but has never been used in production and there is no intention to use it.

---

## Maintenance Margin (MM) — `_calcMM()`

MM is the lower threshold used for liquidation checks. Falling below MM triggers liquidation eligibility.

### Standard case

Same formula as IM but with `kMM` instead of `kIM`:

```
MM = PM * kMM * max(timeToMat, tThresh) / (ONE * YEAR)
```

Since `kMM < kIM`, the maintenance margin is always less than the initial margin, creating a buffer zone.

### Special piecewise case

A piecewise formula applies when **all three** conditions hold:

1. `|rMark| > k_iThresh` (rate is above the threshold floor)
2. `timeToMat < tThresh * kMM` (close to maturity)
3. Position is "beneficial": `signedSize * rMark > 0` (long position with positive rate, or short position with negative rate)

In this case:

```
MM = absSize * (|rMark| * timeToMat + k_iThresh * (kMM * tThresh - timeToMat)) / (ONE * YEAR)
```

**Why this is needed:** Position value uses actual `timeToMat` (no floor), but the standard MM formula floors `timeToMat` at `tThresh`. As maturity approaches, position value decreases linearly toward zero while MM stays flat at the `tThresh` floor. This means health ratio drops even for perfectly healthy (winning) users — purely an artifact of the floor mismatch.

The piecewise case fixes this by giving MM the same linear slope as position value near maturity, so the two decrease together and health ratio stays stable. The specific formula is chosen to ensure MM is **continuous** at the transition point (`timeToMat = tThresh * kMM`), avoiding any discontinuous jump in margin requirements.

---

## Strict vs closing-only margin check — `_checkMargin()`

### Design goal: avoid expensive cross-market margin calculations

The strict IM check (`_checkIMStrict`) requires settling **all** the user's entered markets to compute cross-market `totalValue` and `totalIM` — this is very gas-expensive. The margin check is designed to avoid this cost whenever possible.

- **Opening a new position**: We must always check strict IM. No way around it.
- **Reducing a position**: We actually _want_ the user to pass even if they don't satisfy the initial margin check (`totalValue >= totalIM`). Hence no IM check. However, we must also ensure the user isn't closing at a terrible rate — hence all the complicated closing-only checks.

### Decision flow (per-market, in `MarginViewUtils._checkMargin()`)

1. **Rate bounds check** (always): If new orders exist, verify they fall within `_calcRateBound()` limits. This applies regardless of opening or closing.

2. **Is the user closing only?** — evaluated by `_isUserClosingOnly()`.

3. **If NOT closing-only** → `isStrictIM = true`. Full cross-market IM check is unavoidable.

4. **If closing-only** → three further checks to prevent abuse:

   **a) Closing rate bound**: If orders exist, the worst execution rate must not deviate too far from the mark rate:
   ```
   (rMark - rWorst) × sign(size) ≤ max(k_iThresh, |rMark|) × closingOrderBoundBase1e4
   ```
   Fail → `isStrictIM = true` (prevents gaming via off-market closing trades).

   **b) Value/margin deterioration check**:
   ```
   diffValue = v_pre - v_post    (change in position value, including fees)
   diffMargin = mm_pre - mm_post  (change in maintenance margin)
   ```
   If `diffValue > diffMargin × critHR` → `isStrictIM = true`.

   **c) If both pass** → exempt from strict IM. Returns `isStrictIM = false` with MM-based `finalVM`.

### Cross-market enforcement (in `MarginManager._processMarginCheck()`)

After the per-market check, the hub decides what cross-market check to run:

| `isStrictIM` | `isCritHealth` | Action |
|:---:|:---:|---|
| `true` | — | `_checkIMStrict()`: settle all markets, require `totalValue + cash ≥ totalIM` |
| `false` | `true` | `_checkCritHealth()`: settle all markets, require `HR ≥ critHR` |
| `false` | `false` | **No cross-market check** (cheapest path) |

The `isCritHealth` flag is determined by `_hasStrictMarkets()` — it returns `true` if any of the user's entered markets has `_isStrictMarket = true` (a per-market admin toggle called `strictHealthCheck` in the whitepaper). This is normally off and only turned on when necessary, since it's relatively expensive and always passes in normal conditions.

### `_isUserClosingOnly()` criteria

All of the following must hold:

- `|finalSize| ≤ |preSize|` — absolute position size did not increase
- No sign flip — the position did not change direction (e.g., long to short)
- Opposite-side open orders do not exceed the final position size
- New orders only reduce the position (no same-side limit orders)

### Why `critHR` guarantees health ratio improvement

The value/margin deterioration check (`diffValue ≤ diffMargin × critHR`) can be rewritten as:

```
v(t-) - v(t) ≤ critHR × (mm(t-) - mm(t))
```

**Proof**: If `HR(t-) > critHR`, then `v(t-) > critHR × mm(t-)`. Combined with the check above:

```
v(t) ≥ v(t-) - critHR × (mm(t-) - mm(t))
     > critHR × mm(t-) - critHR × mm(t-) + critHR × mm(t)
     = critHR × mm(t)
```

So `HR(t) = v(t) / mm(t) > critHR`. More importantly, the stronger result: `v(t) / mm(t) ≥ v(t-) / mm(t-)` — the health ratio can only increase after a closing-only batch (when all checks pass). This holds because both position value and MM decrease together during closing, and the check bounds the relative rate of decrease.

### The `strictHealthCheck` safety net

The above proof assumes `HR(t-) > critHR`. But what if the user's health ratio is _already_ below `critHR`? In that case, they could execute OTC or market orders that worsen their health. The `strictHealthCheck` flag (per-market `_isStrictMarket`) guards against this:

When enabled, any closing-only user that passes the value/margin check still gets a `_checkCritHealth()` — requiring `HR(t) ≥ critHR` after the batch. This prevents below-`critHR` users from further worsening their health via OTC/market orders. Production `critHR` is set to **0.4**.

---

## Cross-market aggregation — `MarginManager._settleProcess()`

Boros uses cross-margin: a single collateral pool covers positions across multiple markets within a trading zone.

### Aggregation loop

1. Loop through all of the user's `enteredMarkets`.
2. For each market, call `IMarket.settleAndGet(user, req)` where `req` is `GetRequest.IM` or `GetRequest.MM`, which returns a `VMResult` containing:
   - `value` (int128) — mark-to-market position value
   - `margin` (uint128) — IM or MM requirement for that market
3. Aggregate using the `VMResult.+` operator: sums `value` fields (int128 addition) and sums `margin` fields (uint128 addition).
4. Apply final check against the user's cash balance.

### `idToSkip` optimization

When a market's margin check was just computed locally (via `_checkMargin()`), the hub passes that result as `finalVM` and skips re-settling that market during aggregation. This is done via `_settleExcept(user, req, idToSkip)` + adding `finalVM` back:

```
_checkIMStrict(user, marketId, finalVM):
    totalIM = _settleExcept(user, IM, marketId)  // settle all markets EXCEPT this one
    require(totalIM + finalVM + cash >= 0)        // add the already-computed result back
```

This avoids redundant settlement of the market that just changed.

### Final inequality

```
totalValue + cash >= totalMargin
```

Where `totalValue` is the sum of all per-market position values and `totalMargin` is the sum of all per-market margin requirements.

---

## Health checks

Three health check functions serve different purposes:

### `_isEnoughIMStrict()`

Binary pass/fail for initial margin:

```
totalValue + cash >= totalMargin
```

Used after order placement and liquidator validation.

### `_isHRAboveThres(threshold)`

Checks whether the health ratio exceeds a given threshold without division:

```
totalValue + cash >= totalMargin * threshold
```

This avoids division-by-zero when `totalMargin = 0` (no open positions). Used for maintenance margin checks and closing-only exemptions.

### `_calcHR()`

Computes the exact health ratio:

```
HR = (totalValue + cash) / totalMargin
```

Used for liquidation incentive calculations and risk monitoring. Reverts via `SDivWadFailed()` when `totalMargin = 0` — callers must check for zero margin before calling.
