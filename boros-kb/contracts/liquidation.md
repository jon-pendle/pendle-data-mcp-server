---
description: Liquidation, force deleverage, force cancel, and out-of-bound purge mechanisms
last_updated: 2026-03-16
related:
  - contracts/margin-engine.md
  - contracts/settlement.md
  - contracts/order-lifecycle.md
  - risk/risk-overview.md
---

# Liquidation and risk enforcement

This document covers all forced position and order actions: liquidation, force deleverage, force cancel, and out-of-bound purge. These mechanisms protect the system from bad debt accumulation and ensure order book hygiene.

---

## Liquidation

**Entry point:** `MarketHubEntry.liquidate()` -> `IMarket.liquidate()`

Liquidation transfers a distressed user's position to a liquidator at an incentivized rate.

### Access control

- Caller must be `onlyAuthorized` (whitelisted bot)
- `liq.root() == msg.sender` — the liquidation root must match the caller, preventing unauthorized front-running of liquidation opportunities

### Flow

1. **Cross-market settlement**: MarketHub settles the violator across all entered markets and computes the aggregate health ratio.
2. **Per-market liquidation**: The market receives `sizeToLiq` (amount to liquidate) and `vioHealthRatio`, then calls `_calcLiqTradeAft()`.

### Liquidation trade calculation — `_calcLiqTradeAft()`

**Prerequisites:**

- `0 <= healthRatio < 1.0` — the violator is below maintenance margin
- `sizeToLiq != 0`

**Incentive calculation:**

The liquidator receives an incentive scaled by the violator's distress level:

```
incentiveFactor = min(base + slope * (1 - HR), HR)
```

- `base` and `slope` are per-market `LiqSettings` parameters.
- The incentive scales **up** as HR decreases (more distressed = more incentive).
- Capped at HR to **prevent extraction beyond the account's remaining value**.

```
deltaMM = MM(violator before) - MM(violator after)
incentive = deltaMM * incentiveFactor
annualizedIncentive = incentive * 365 days / timeToMat
```

**Trade construction:**

```
signedSize = sizeToLiq
signedCost = sizeToLiq * rMark_ceil - annualizedIncentive
```

The liquidator receives the violator's position at the mark rate minus the annualized incentive discount.

### Post-trade processing

1. Both liquidator and violator positions are updated via an OTC-like merge.
2. **Deleverage/liquidation nonce** incremented for the **violator only** via `_incDelevLiqNonce(vioAddr)`. If the violator is an AMM account, this puts it into withdraw-only mode.
3. **Liquidation fee** (`liqFeeRate` from `LiqSettings`) is collected and sent to the treasury.
4. MarketHub processes `PayFee` for both parties and runs a margin check on the liquidator to ensure they can absorb the position.

### Economic properties

**Deleverage at mark rate preserves total value.** When a trade executes at the mark rate, the change in position value exactly equals the upfront cost. Therefore `totalValue = cash + positionValue` is unchanged, while `totalMM` decreases (the position is smaller). Liquidation is simply a deleverage at an **incentivized rate** — the loser trades at a rate worse than mark, and the difference is the incentive paid to the liquidator.

For example, if the violator is LONG, the liquidation executes at a rate **lower** than mark rate. The gap between mark rate and the liquidation rate is the incentive.

**The all-in liquidation rate is a computable constant.** `LiquidationMath` in the bot math libraries pre-computes `liqAllInRate`:

```
liqIncentiveRate = max(|rMark|, iThresh) × kMM × incentiveFactor × max(timeToMat, tThresh) / timeToMat

liqAllInRate =
    if closing LONG:  rMark + liqIncentiveRate - liqFeeRate
    if closing SHORT: rMark - liqIncentiveRate + liqFeeRate
```

This constant determines whether a given book tick or AMM swap is profitable for the liquidator — the bot only takes positions at rates better than `liqAllInRate`.

**Health ratio always increases after liquidation.** Because `incentive = deltaMM × incentiveFactor` and `incentiveFactor ≤ HR` (capped in `_getLiqSettings`), the incentive paid by the violator is at most `deltaMM × HR`. Since `HR = totalValue / totalMM`, losing `deltaMM × HR` from the value while losing `deltaMM` from the margin yields:

```
newHR = (totalValue - deltaMM × HR) / (totalMM - deltaMM)
      = (totalMM × HR - deltaMM × HR) / (totalMM - deltaMM)
      = HR × (totalMM - deltaMM) / (totalMM - deltaMM)
      = HR
```

In practice, `incentiveFactor < HR` (the cap rarely binds), so `newHR > HR` — liquidation strictly improves the violator's health ratio.

---

## Force deleverage

**Entry point:** `MarketHubRiskManagement.forceDeleverage()` -> `IMarket.forceDeleverage()`

Force deleverage is the **last resort** mechanism when a position is so distressed that normal liquidation cannot cover the losses. It forcibly pairs the distressed account against a winning counter-party, potentially sharing bad debt.

### Trigger conditions

- HR <= threshold (typically 0.70)
- Called by `onlyAuthorized` bot

### Flow

1. **Validation**: Confirm win/lose accounts are different addresses. Both sides must be reduce-only (the trade reduces both positions).
2. **Cancel all loser orders**: All resting orders for the losing account are force-cancelled to simplify the position.
3. **Calculate deleverage trade** via `_calcDelevTradeAft()`.

### Deleverage trade calculation — `_calcDelevTradeAft()`

**Case 1 — loseValue >= 0 (no bad debt):**

Trade executes at mark rate. The winner takes over the loser's position at fair value. No loss sharing occurs. Because the trade is at mark rate, the loser's total value does not change — only total margin decreases (position is smaller).

**Case 2 — loseValue < 0 (bad debt exists):**

```
lossFactor = alpha * sizeToWin / lose.signedSize
loss = loseValue * lossFactor
```

The trade executes at mark rate minus the annualized loss:

```
signedCost = sizeToWin * rMark - annualized(loss)
```

The **winner absorbs proportional bad debt**. The `alpha` parameter (range 0 to 1) controls what fraction of the bad debt is shared with the winner:

- `alpha = 0`: No bad debt sharing (winner receives position at mark rate).
- `alpha = 1`: Full proportional bad debt sharing.

### Post-deleverage

- No OTC fee is charged.
- **No margin check on either party in MarketHub** — both positions are written directly without validation, since the operation is a forced risk reduction. However, the risk bot contracts (`DeleveragerFacet`) do check that the winner does not end up in bad debt after the deleverage.
- Deleverage nonce incremented for both accounts via `_incDelevLiqNonce()`.

---

## Force cancel

**Entry point:** `MarketHubRiskManagement`

Two variants exist for bots to remove dangerous resting orders.

### `forceCancelAllRiskyUser()`

- **Requirement**: User's health ratio < `riskyThresHR`.
- Cancels **all** resting orders across the specified markets.
- Called by `onlyAuthorized` bot.
- Reduces the user's margin exposure from open orders, potentially restoring their health ratio above the risky threshold.

### `forceCancel()`

- Cancels **specific** orders for a user (by order ID).
- **No health check required** — the bot decides at its discretion which orders to cancel.
- Used for surgical intervention when specific orders are deemed dangerous (e.g., large orders that would dramatically increase exposure if filled).

---

## Out-of-bound purge

**Entry point:** `MarketRiskManagement.forcePurgeOobOrders()`

Purges resting orders whose rates have drifted outside acceptable bounds as the mark rate moves. This keeps the order book clean and prevents stale orders from matching at economically unreasonable rates.

### Rate bounds calculation

Per side (long/short), `_calcRateBound()` determines the acceptable range:

- When `|rMark| >= k_iThresh`: slope-based bounds (`loUpperSlope` / `loLowerSlope`)
- When `|rMark| < k_iThresh`: constant bounds (`loUpperConst` / `loLowerConst`)

### Purge mechanism — `_bookPurgeOob()`

1. Identifies orders on each side that fall outside the computed rate bounds.
2. Marks purged orders with a **purge FTag** (even-valued), distinguishing them from normal fills (odd FTag).
3. The purge FTag is mapped to the current FIndex at purge time.

### Settlement of purged orders

When a user with purged orders is next settled:

- Purged fills resolve to `Trade.ZERO` — the position is effectively cancelled, not filled.
- The user recovers their margin for the cancelled orders.
- Funding payments are correctly applied up to the purge FTag.

### FTag advancement — `_updateFTagOnPurge()`

Each purge event advances the market's FTag to the next even value, creating a new settlement epoch. This ensures purged orders are processed in the correct chronological position relative to FIndex updates.

### Gas limits — `maxNTicksPurgeOneSide`

A per-call limit on the number of ticks that can be purged on each side prevents gas exhaustion. If more ticks need purging than the limit allows, multiple calls are required.
