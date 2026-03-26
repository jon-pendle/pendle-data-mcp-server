---
description: Full order lifecycle through MarketOrderAndOtc, order book internals, tick bitmap, and QIT data structures
last_updated: 2026-03-16
related:
  - contracts/settlement.md
  - contracts/margin-engine.md
  - mechanics/risk-control-mechanisms.md
---

# Order lifecycle

This document traces a single order from entry point through execution, covering every phase in `MarketOrderAndOtc.orderAndOtc()`, bulk order handling, and the underlying order book data structures.

---

## Entry point — `orderAndOtc()`

`MarketOrderAndOtc.orderAndOtc()` is the main entry point for all individual orders. The monolithic design is intentional for gas optimization — batching cancel + match + OTC + margin check into one function lets MMs perform complex actions (cancel stale quotes, place new ones, settle) in a single call with a single state read and single margin check, rather than paying for each separately.

It executes five sequential phases:

### Phase 1: Read & Settle — `_readMarket()`, `_initUser()`

Loads the current `MarketMem` struct from storage into memory. Key fields:

- **rMark** — current mark rate (TWAP of recent order book trades)
- **timeToMat** — seconds remaining until maturity
- **latestFTag** — the most recent funding tag (settlement epoch)
- **k_tickStep** — minimum tick spacing for the market
- **k_maturity** — maturity timestamp

This read is performed once and the resulting `MarketMem` is threaded through all subsequent phases to avoid redundant storage reads.

Then `_initUser()` loads the user's on-chain state (position, cash, open order IDs, fTag) and immediately runs `_sweepProcess()` — the sweep-and-process settlement pipeline (see `settlement.md` for full details) — to incorporate any filled orders into the user's position and cash balance. Settlement is embedded in this phase, not a separate step.

This ensures the margin check in Phase 5 operates on an up-to-date snapshot.

### Phase 2: Cancel — `_coreRemoveAft()`

Removes specified orders from the book before placing new ones.

- The caller provides an array of order IDs to cancel.
- **Transient storage tracking**: An `OrderIdBoolMapping` (transient storage bitmap) marks which order IDs should be removed. This avoids repeated storage writes and enables O(1) membership checks.
- The function iterates through the user's `longIds` and `shortIds` arrays, checking each against the transient bitmap. Matching orders are removed from the book and the user's open order list.
- **Force-cancel variant**: `_coreRemoveAllAft()` removes all of a user's orders in the market. Used by the risk management system (see `liquidation.md`).

### Phase 3: Match — `_bookMatch()`

The core matching engine. Returns:

- **Trade** — the matched portion (signedSize + signedCost)
- **Fill** — partial fill details
- **partialMaker** — address of the maker whose order was partially filled
- **lastMatchedTick** — the tick at which the last match occurred

After matching, three checks run:

#### Self-trade prevention — `_hasSelfFilledAfterMatch()`

Detects whether any of the user's own resting orders on the opposite side were filled during matching. If so, the protocol handles it according to market configuration (typically reverts or adjusts).

#### Rate deviation check — `_checkRateDeviation()`

Ensures the matched rate does not stray too far from the mark rate:

```
|rMark - lastMatchedRate| <= maxRateDeviationFactor * max(k_iThresh, |rMark|)
```

This prevents trades at economically unreasonable rates caused by thin liquidity at extreme ticks.

#### Implied rate oracle update

After a valid match, the mark rate oracle is updated with the new trade data to keep rMark current.

#### Partial fill handling

When a maker order is only partially filled, `_squashPartial()` attempts to merge the partial fill into an existing `PartialData` entry. Merging is allowed only when the existing PartialData shares the same FTag (settlement epoch). If the FTags differ, the protocol performs a full init-and-settle cycle on the partial maker's account before creating new PartialData. This guarantees correct settlement ordering.

### Phase 3 (continued): Add — `_coreAdd()`

Places any unmatched remainder of the order onto the book.

- Checks **maxOpenOrders** (configurable per market) — reverts if the user would exceed this limit.
- **`_shouldPlaceOnBook()`** enforces Time-In-Force (TIF) rules:

| TIF | Behavior |
|-----|----------|
| **GTC** (Good-Til-Cancel) | Remainder placed on book |
| **IOC** (Immediate-Or-Cancel) | Remainder silently discarded |
| **FOK** (Fill-Or-Kill) | Reverts if order was not fully filled |
| **ALO** (Add-Liquidity-Only) | Reverts if any portion was matched (taker fill) |
| **SOFT_ALO** | Silently skips any matched ticks without reverting; remainder placed on book |

### Phase 4: OTC — `_otc()`

If OTC trades are included in the request, they are executed after order matching. See `architecture.md` for OTCModule details.

### Phase 5: Write — `_writeUser()`, `_writeMarket()`

Persists the user's updated state and runs the margin check.

- Calls `_checkMargin()` which determines whether to apply a strict initial-margin (IM) check or a relaxed closing-only check (see `margin-engine.md` for the full decision tree).
- If the margin check fails, the entire transaction reverts.

---

## Bulk orders — `MarketHubEntry.bulkOrders()`

For multi-market order submission:

1. Accepts a `BulkOrder[]` array, each specifying a market and order parameters.
2. Loops through the array, calling `IMarket.orderAndOtc()` for each entry.
3. Performs a **single cross-market margin check** at the end, rather than per-order. This allows positions in one market to offset margin requirements in another.
4. Bulk orders are placed directly on the book — no AMM matching occurs.

---

## Order book internals

### Tick bitmap

The order book spans 2^16 possible ticks. These are represented as bits across 256 `uint256` words (256 * 256 = 65536 ticks).

- Each bit indicates whether a tick has at least one resting order.
- A **word-level bitmap** (a single `uint256`) tracks which of the 256 words contain at least one active bit.
- Finding the next active tick is O(1): check the word-level bitmap to locate the relevant word, then find the first set bit within that word using bitwise operations.

### Quaternary Indexed Tree (QIT)

Within each active tick, orders are managed by a base-4 indexed tree (QIT). This structure supports efficient order addition, removal, and matching.

**Tree properties:**

- Height is capped at 10 levels.
- `coverLength(i) = 4^(count of trailing 3s in the base-4 representation of i)`.
- 75% of nodes have `coverLength = 1`, so `subtreeSum` is only stored for the remaining 25% of nodes that actually aggregate children. This reduces storage costs significantly.

**Complexity:**

| Operation | Cost |
|-----------|------|
| **Add** | O(1) amortized warm writes |
| **Remove** | O(h) warm writes (h = tree height) |
| **Match** | O(k * h) search + O(h) update, where k = number of matched orders |

### OrderId priority encoding

OrderIds are raw `uint64` values where **lower value = higher priority**. XOR encoding ensures correct priority ordering across both sides:

- **LONG orders**: Higher ticks (better rate for the maker) produce lower encoded values, so they are matched first.
- **SHORT orders**: Lower ticks (better rate for the maker) produce lower encoded values, so they are matched first.
- **Within the same tick**: Lower `orderIndex` (earlier insertion) yields a lower encoded value, giving time priority.

### Rate bounds enforcement

Maker orders must satisfy rate bounds computed by `_calcRateBound()`:

- When `|rMark| >= k_iThresh`: bounds are `loUpperSlope` / `loLowerSlope` (slope-based, scales with mark rate).
- When `|rMark| < k_iThresh`: bounds are `loUpperConst` / `loLowerConst` (constant bounds).

Taker rate deviation is checked separately via `_checkRateDeviation()` (Phase 4).
