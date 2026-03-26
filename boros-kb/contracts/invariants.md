---
description: Formal system invariants — cash conservation, OI consistency, settlement fairness, margin sufficiency, and more, with enforcement locations
last_updated: 2026-03-17
related:
  - contracts/settlement.md
  - contracts/amm.md
  - contracts/events-errors.md
---

# Invariants

This document enumerates the formal invariants that the Boros contract system maintains. Each invariant lists where it is enforced and what happens when it would be violated.

---

## 1. Cash Conservation

**Statement**: The sum of all `acc[user].cash` across every user plus `cashFeeData[token].treasuryCash` across every token equals the total deposited ERC20 held by MarketHub.

```
sum(acc[user].cash) + sum(cashFeeData[token].treasuryCash) = MarketHub.ERC20Balance
```

**Enforcement**:
- `_processPayFee()` — settlement payment adjusts user cash by the exact pay-fee amount; the fee portion goes to `treasuryCash`. The sum is preserved because the fee is split between user cash reduction and treasury increase.
- `_topUpWithdrawCash()` — withdrawal deducts from user cash and records a matching ERC20 obligation.
- `_transferToTreasury()` — matching debit from user cash and credit to treasury cash.
- `vaultDeposit()` — ERC20 transfer in equals cash credit.
- `finalizeVaultWithdrawal()` — ERC20 transfer out equals the recorded withdrawal amount.

**Violation**: Would indicate a bug in the accounting layer. No single error code guards this — it is a structural invariant maintained by the correctness of every cash-modifying function.

---

## 2. OI Consistency

**Statement**: Open interest is the total one-sided exposure — the positive orderbook's filled size plus all users' standalone long positions (equivalently, the negative orderbook's filled size plus all standalone short positions).

From the whitepaper:
```
OI(t) = s⁺ + Σ_{s_alone > 0} |s_alone_u(t)|
      = s⁻ + Σ_{s_alone < 0} |s_alone_u(t)|
```

Where `s⁺` / `s⁻` are the positive/negative orderbook total filled sizes, and `s_alone_u` is each user's standalone position (after settlement merges filled orders into it).

**Implementation**: To avoid dealing with halves, the contract stores and compares `2 × OI`:
```
stored OI = 2 × OI(t) = s⁺ + s⁻ + Σ_u |s_alone_u(t)|
hardOICap = 2 × S_cap
```

**Enforcement** (in `PendingOIPureUtils.sol`):
- `_updateOIOnNewMatch(absSize)` — new order fill creates a matched pair, increases stored OI by `absSize` (the new entry on one side of the orderbook).
- `_updateOIAndPMOnSwept()` — during settlement, filled orders are swept off the orderbook (decreasing `s⁺`/`s⁻`), reducing stored OI by the swept size.
- `_updateOIOnUserWrite()` — adjusts stored OI by the change in `|s_alone_u|` (standalone position size change after settlement merges swept orders into it): `OI += |signedSize| - |preSettleSize|`.
- `_updateOIAndPMOnPartial()` — partial fill settlement reduces stored OI.
- Hard cap: `_writeMarket()` requires `market.OI ≤ market.origOI || market.OI ≤ hardOICap`. OI can always decrease; it can only increase up to the cap.
- Deleverage and liquidation use `_writeMarketSkipOICheck()` — forced operations must succeed regardless of cap.

**Violation**: `MarketOICapExceeded` prevents exceeding the cap on position-opening operations.

---

## 3. Settlement Fairness

**Statement**: Every position settles at the correct FIndex for its match time. FTag values monotonically increase. `SweptF` arrays are sorted by FTag to ensure chronological processing.

**Enforcement**:
- `FIndexOracle.updateFloatingIndex()` enforces monotonic FTag advancement — each update must target the exact next epoch.
- `addToStorageIfAllowed()` — when a partial fill occurs across FTag boundaries, this function returns `false` if the new FTag does not match the existing order's FTag, forcing settlement of the earlier portion before the new fill.
- Binary search in sweep operations relies on the sorted FTag order — if tags were unsorted, settlement amounts would be incorrect.

**Violation**: `FIndexNotDueForUpdate` and `FIndexInvalidTime` prevent out-of-order FTag updates. If `addToStorageIfAllowed()` returns false, the caller must settle before proceeding.

---

## 4. Margin Sufficiency

**Statement**: After every state-changing operation, either the strict initial margin (IM) check passes or the user is in closing-only mode with a weak check.

```
totalValue + cash >= totalIM   (strict check)
```

**Enforcement**:
- `_processMarginCheck()` is called by MarketHub after every `orderAndOtc`, `bulkOrders`, `liquidate`, cash transfer, and withdrawal request.
- If the check fails, the operation reverts with `MMInsufficientIM`.
- **Exception**: `forceDeleverage` writes positions using `_writeUserNoCheck`, bypassing the margin check. This is necessary because the winner in a deleverage may temporarily have insufficient margin after absorbing the loser's position. The system accepts this temporary imbalance because deleverage is a last-resort mechanism that prevents worse outcomes (bad debt).

**Violation**: `MMInsufficientIM` reverts the transaction. For deleverage, the bypass is intentional.

---

## 5. Order Book Solvency

**Statement**: Order ID priority ordering is maintained — lower raw `uint64` value equals higher match priority. Settled orders always appear at the beginning of the sorted array.

**Enforcement**:
- Order IDs encode tick and sequence information such that natural uint64 ordering reflects price-time priority.
- Settled orders are guaranteed to sort before unsettled orders by construction (tick encoding ensures this).
- Binary search in sweep operations relies on this ordering to efficiently find the boundary between settled and unsettled orders.

**Violation**: Ordering is structural (enforced by ID encoding), not by runtime checks. A bug in ID generation would break this invariant silently.

---

## 6. Position Netting

**Statement**: For every fill, one party goes long and the other goes short by the same absolute size. Net system-wide position is always zero.

```
sum(position.signedSize) = 0   (across all accounts in a market)
```

**Enforcement**:
- `_mergeOTCAft()` uses `trade.opposite()` to ensure the counterparty receives the mirror position.
- Every order match creates symmetric entries: +size for one party, -size for the other.
- Cross-market: no netting between different markets. Each market's positions sum to zero independently.

**Violation**: Structural — enforced by the symmetric construction of every fill. No explicit runtime check sums all positions (that would be too expensive), but the code path guarantees symmetry.

---

## 7. Fee Non-Negativity

**Statement**: All fee rates are unsigned. `PayFee.fees` is `uint128`. Treasury cash only increases (no negative treasury).

**Enforcement**:
- Fee rates are stored as unsigned integers — negative fees are impossible at the type level.
- `_processPayFee()` adds to `treasuryCash`, never subtracts.
- `InvalidFeeRates` reverts if fee configuration is invalid.

**Violation**: `InvalidFeeRates` during configuration. At runtime, unsigned types prevent negative fees by construction.

---

## 8. Agent Security

**Statement**: Agents cannot withdraw funds. No withdrawal-related functions are callable via `agentExecute`. Agent expiry is checked on every `agentExecute` call. Nonces strictly increase, preventing replay.

**Enforcement**:
- `AuthModule.agentExecute()` checks the function selector against an allowlist. Withdrawal selectors (`requestVaultWithdrawal`, `finalizeVaultWithdrawal`) are not in the allowlist. Unauthorized selectors revert with `AuthSelectorNotAllowed`.
- Agent expiry: `AuthAgentExpired` reverts if `block.timestamp > agent.expiry`.
- Nonce: `AuthInvalidNonce` reverts if the provided nonce does not match the expected next nonce. Nonces are per-agent and strictly increasing.

**Violation**: `AuthSelectorNotAllowed`, `AuthAgentExpired`, `AuthInvalidNonce` — each has a dedicated revert. Even if an agent key is compromised, the attacker cannot withdraw funds.

---

## 9. Deleverage Nonce Isolation

**Statement**: Once the deleverage/liquidation nonce is incremented for an AMM account, the AMM enters withdraw-only mode. This prevents compounding bad debt through the AMM.

**Enforcement**:
- `_isWithdrawOnly()` checks `delevLiqNonce != 0`.
- If true, `swapByBorosRouter()` and mint operations revert with `AMMWithdrawOnly`.
- Burns remain allowed for LP exit.

**Violation**: `AMMWithdrawOnly` prevents new deposits and swaps. The nonce is never decremented — once triggered, withdraw-only mode is permanent for that AMM instance.

---

## 10. Rate Bound Enforcement

**Statement**: Taker orders are bounded by `maxRateDeviationFactor` from the mark rate. Maker orders are bounded by slope/constant formulas. Out-of-bounds orders are purged by the purge bot.

**Enforcement**:
- `_checkRateDeviation()` — called on every order submission. Validates that the order rate is within acceptable deviation from the current mark rate.
- `_calcRateBound()` — computes the rate bound for maker orders using configurable slope and constant parameters. The bound widens or narrows based on market conditions.
- Purge bot: `forcePurgeOobOrders()` retroactively removes orders that have drifted out of bounds due to mark rate movement (see `contracts/risk-bots.md`).
- `MarketOrderRateOutOfBound` reverts orders that fail the deviation check at submission time.

**Violation**: `MarketOrderRateOutOfBound` at submission. For orders that become OOB after submission (due to mark rate movement), the purge bot provides asynchronous enforcement.

---

## Cross-Cutting Notes

- Invariants 1, 2, and 6 are **structural** — they hold by construction of every state-modifying function rather than by explicit assertion.
- Invariants 4 and 10 are **enforced by revert** — violations cause transaction failure.
- Invariant 9 is a **one-way latch** — once triggered, it cannot be reversed.
- Invariant 3 depends on the FIndex keeper operating correctly — if the keeper submits incorrect `floatingIndexDelta` values, settlement amounts will be wrong even though the FTag ordering invariant holds. The keeper is a trusted component.
