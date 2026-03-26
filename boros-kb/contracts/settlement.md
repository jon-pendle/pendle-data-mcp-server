---
description: Settlement implementation — sweep-process pipeline, FTag epochs, FIndex retrieval optimizations, and partial fill handling
last_updated: 2026-03-16
related:
  - contracts/order-lifecycle.md
  - contracts/margin-engine.md
  - contracts/liquidation.md
---

# Settlement

Settlement calculates the PayFee (floating payment minus fixed cost) for filled orders and updates user positions accordingly. It is **lazy** — deferred until the user next interacts with the system. Every position-changing operation triggers settlement first to ensure margin checks operate on current state.

---

## Two-phase settlement pipeline

Settlement runs via `SweepProcessUtils` in two phases: sweep and process.

### Phase 1: Sweep — `__sweepFOneSide()`

Identifies which of a user's resting orders have been filled and extracts their settlement information.

**Binary search optimization:**

OrderIds within a user's `longIds` / `shortIds` arrays are sorted by priority (lower raw `uint64` = higher priority). Because matching consumes orders in priority order, there exists a **partition point** — the highest-priority order that has NOT yet been settled. Every order before this point is settled; every order after it is not.

Rather than sorting the full array to find this boundary, the implementation uses a **randomized partition algorithm** seeded with `block.number` as the PRNG source. This avoids O(n log n) worst-case sorting while achieving efficient partitioning in practice.

The output is a `SweptF` array for each side (long and short), containing the settlement info (size, cost, FTag) for each filled order.

### Phase 2: Process — `_processF()` in `ProcessMergeUtils`

Iterates through the `SweptF` arrays (long + short) in chronological order by FTag. At each FTag epoch:

1. **Floating payment calculation**: `Pay.calcSettlement(signedSize, userIndex, thisIndex)` computes the funding payment owed based on the user's position size and the difference between the user's last-settled index and the current index.
2. **Upfront fixed cost**: For newly filled orders, the fixed cost agreed at match time is applied.
3. **Position update**: The user's `signedSize` is updated to reflect new fills at this epoch.

Processing continues until `user.fTag == market.latestFTag`, at which point the user is fully settled.

---

## FTag epoch system

FTag is a `uint32` counter that tracks the progression of settlement epochs within a market.

### Parity convention

| FTag parity | Event type |
|-------------|------------|
| **Odd** | FIndex update — new funding rate data has arrived |
| **Even** | Purge event — out-of-bound orders were removed |

### Lifecycle

- Each FIndex update (new funding rate data, typically every 4-8 hours aligned with perp funding intervals) advances the FTag by 1 (to the next odd value).
- Each purge event (out-of-bound order removal) also advances FTag by 1 (to the next even value).
- When an order is matched, it records the current FTag at match time.
- During settlement, fills are processed in FTag order. This ensures that funding payments between position changes are calculated correctly — a fill at FTag 5 must have FTags 1-4 applied to the pre-fill position before the fill's size change takes effect.

---

## FIndex retrieval optimizations

Retrieving the correct FIndex for a given order requires mapping from the order's match time to the funding index at that time. Several optimizations minimize storage reads.

### MatchEvent storage

Each match creates a `MatchEvent` record containing `(headIndex, fTag)`. Given an order, a binary search over MatchEvents finds the fTime (funding time) applicable to that order.

### TickNonce segmentation

Orders inserted during the same tick state share a `tickNonce`. Nodes with the same tickNonce are contiguous in the MatchEvent array.

`TickNonceData` stores `firstEventId` and `lastEventId` for each tickNonce, which **narrows the binary search range** from the full MatchEvent array down to the segment relevant to that tickNonce.

### Active tickNonce tracking

Not every tickNonce corresponds to a new FIndex update. FIndex updates happen every 4-8 hours, while matches happen constantly. The system tracks **active tickNonces** — those during which a new FIndex was published.

Each node stores a `refTickNonce`, which is the active tickNonce at the time the node was inserted. With high probability, the fTime stored at the `refTickNonce`'s `lastEvent` is the correct answer. This yields the correct FIndex in a **single storage read** in the common case, avoiding binary search entirely.

### MatchEvent deduplication

Consecutive MatchEvents that share the same fTime are deduplicated — only one is stored. This reduces storage costs during periods of high trading activity between FIndex updates.

---

## Partial fill handling — `PartialData`

When a maker order is only partially filled, the system creates a `PartialData` record to track the partial execution until the maker is next settled.

### PartialData fields

| Field | Description |
|-------|-------------|
| `sumLongSize` | Accumulated long fill size |
| `sumLongPM` | Accumulated long payment |
| `sumShortSize` | Accumulated short fill size |
| `sumShortPM` | Accumulated short payment |
| `fTag` | FTag at which these partial fills occurred |
| `sumCost` | Accumulated fixed cost |

### Accumulation — `addToStorageIfAllowed()`

When a new partial fill arrives for the same maker:

- **Same FTag**: The fill is accumulated into the existing PartialData (sizes and costs are summed). This is the fast path — no settlement required.
- **Different FTag**: Returns `false`. The caller (Phase 3 of `orderAndOtc`) must perform a full init-and-settle cycle on the partial maker before creating new PartialData. This ensures funding payments between the old and new FTags are correctly applied to the intermediate position size.

### Settlement integration

During settlement, PartialData is **merged before** processing the SweptF arrays. This ensures partial fills are incorporated into the position before the sweep-process pipeline runs, maintaining correct chronological ordering of position changes and funding applications.

---

## Settlement triggers

Settlement occurs automatically before any of the following operations:

- Placing a new order (`orderAndOtc` Phase 1 — settlement runs inside `_initUser()`)
- Liquidation (both violator and liquidator are settled)
- Force deleverage (both parties settled)
- Any margin or health ratio query

The lazy design means that a user who does not interact with the system accumulates unsettled fills. Their on-chain position and cash balance remain stale until the next interaction, at which point all pending epochs are processed in a single transaction.
