---
description: Packed type system — bit layouts, encoding schemes, and design rationale
last_updated: 2026-03-16
related:
  - contracts/architecture.md
  - contracts/storage-layout.md
---

# Type System

Boros aggressively packs data into fixed-width types to minimize storage reads. A single SLOAD costs 2100 gas cold / 100 gas hot, so packing multiple fields into one slot has significant gas impact. This document covers every packed type with exact bit layouts.

## Identity Types

### Account (bytes21 = 168 bits)

Encodes a user address and subaccount ID into a single value.

| Bits | Field | Size |
|------|-------|------|
| 167..8 | `address` | 160 bits |
| 7..0 | `accountId` | 8 bits |

Constants:
- `MAIN_ACCOUNT_ID = 0` — the default subaccount.
- `AMM_ACCOUNT_ID = 255` — reserved for AMM positions.

Functions: `root()` extracts the address, `accountId()` extracts the subaccount, `isMain()` checks `accountId == 0`, `isAMM()` checks `accountId == 255`, `toMain()` replaces accountId with 0, `toAMM()` replaces accountId with 255.

### MarketAcc (bytes26 = 208 bits)

Extends Account with token and market identifiers. This is the key type for MarketHub's `acc` mapping.

| Bits | Field | Size |
|------|-------|------|
| 207..48 | `address` | 160 bits |
| 47..40 | `accountId` | 8 bits |
| 39..24 | `tokenId` | 16 bits |
| 23..0 | `marketId` | 24 bits |

Constants:
- `CROSS` marketId = `2^24 - 1 = 16777215` — the sentinel value for cross-margin.

Functions: `root()`, `account()` (returns the Account portion), `tokenId()`, `marketId()`, `isCross()` checks `marketId == CROSS`, `toCross()` replaces marketId with CROSS. Equality comparison uses the `==` operator directly on the bytes26 value.

Cross-margin accounts use `CROSS` as marketId. Isolated-margin accounts use the specific MarketId of the market they are isolated to.

### Identifier types

| Type | Size | Notes |
|------|------|-------|
| `TokenId` | `uint16` | Collateral token identifier, indexes into `_tokenData[]` |
| `MarketId` | `uint24` | Market identifier, `CROSS = 2^24 - 1` reserved |
| `AMMId` | `uint24` | AMM pool identifier |

## Order Book Types

### OrderId (uint64)

Encodes order identity and priority into a single comparable value.

| Bits | Field | Size |
|------|-------|------|
| 63 | `initialized` | 1 bit |
| 62 | `side` | 1 bit |
| 61..46 | `encodedTick` | 16 bits |
| 45..0 | `orderIndex` | 40 bits |

`INITIALIZED_MARKER = 1 << 63` — set on all valid OrderIds.

**Tick encoding**: The raw tick index (int16) is encoded to enable correct ordering via unsigned comparison:

```
encoded = uint16(tickIndex) ^ (1 << 15)
```

For LONG side orders (which sweep ticks top-down), the encoded tick is complemented:

```
encoded = ~encoded  // for LONG
```

This XOR + complement scheme ensures that a **lower raw uint64 OrderId = higher execution priority**. Settled orders (which should be processed first) naturally sort to the beginning of any sorted array of OrderIds.

### TickInfo (uint256 packed + overflow)

Packs five fields into a single storage slot, with overflow handling for two fields.

| Bits | Field | Size | Notes |
|------|-------|------|-------|
| 255..128 | `tickSum` | 128 bits | Sum of all order sizes at this tick |
| 127..88 | `headIndex` | 40 bits | Index of the first active order |
| 87..60 | `numActive` | 28 bits | Number of active orders (overflows at threshold) |
| 59..20 | `tickNonce` | 40 bits | Monotonically increasing tick event counter |
| 19..0 | `activeNonceOffset` | 20 bits | Offset for active nonce calculation (overflows at threshold) |

When `numActive` or `activeNonceOffset` exceed their bit-width thresholds, the values are stored in separate `unpackedNumActive` and `unpackedActiveNonceOffset` fields outside the packed slot. This keeps the common case (moderate-sized ticks) in a single SLOAD while handling edge cases correctly.

### TickNonceData (uint256)

Links a tick nonce to a range of MatchEvents for binary search optimization.

| Bits | Field | Size |
|------|-------|------|
| 255..184 | `lastEvent` | 72 bits (MatchEvent) |
| 183..144 | `firstEventId` | 40 bits |
| 143..104 | `lastEventId` | 40 bits |
| 103..64 | `nextActiveNonce` | 40 bits |

### NodeData (uint256)

Per-order node in the order book linked list.

| Bits | Field | Size |
|------|-------|------|
| 255..128 | `orderSize` | 128 bits |
| 127..88 | `makerNonce` | 40 bits |
| 87..48 | `tickNonce` | 40 bits |
| 47..8 | `refTickNonce` | 40 bits |

`refTickNonce` is a shortcut pointer for FIndex retrieval — it allows jumping directly to the relevant funding index without scanning from the beginning.

### MatchEvent (uint72)

Stored per match operation to record execution context.

| Bits | Field | Size |
|------|-------|------|
| 71..32 | `headIndex` | 40 bits |
| 31..0 | `fTag` | 32 bits |

## Trade and Settlement Types

### Trade (uint256)

Represents a trade with signed size and cost.

| Bits | Field | Size |
|------|-------|------|
| 255..128 | `signedSize` | 128 bits (signed) |
| 127..0 | `signedCost` | 128 bits (signed) |

Positive values = long position, negative = short. Functions: `side()`, `absSize()`, `absCost()`, `add()` (combines two trades), `opposite()` (negates both fields), `fromSizeAndRate()`.

### Fill (uint256)

Same bit layout as Trade. Represents a single-tick fill result. Castable to Trade via `toTrade()`.

### PayFee (uint256)

Encodes a payment and its associated fees.

| Bits | Field | Size |
|------|-------|------|
| 255..128 | `payment` | 128 bits (signed) |
| 127..0 | `fees` | 128 bits (unsigned) |

`payment` is the net cash flow (positive = received, negative = paid). `fees` is always non-negative. `total() = payment - fees` gives the net effect on the account's cash balance.

### VMResult (uint256)

Value-and-margin pair used for cross-market aggregation.

| Bits | Field | Size |
|------|-------|------|
| 255..128 | `value` | 128 bits (signed) |
| 127..0 | `margin` | 128 bits (unsigned) |

Aggregatable via `add()` — both fields are summed independently. Used during the MarginManager settlement loop to accumulate IM/MM requirements across all entered markets.

## Funding Types

### FIndex (bytes26 = 208 bits)

Cumulative funding state at a point in time.

| Bits | Field | Size |
|------|-------|------|
| 207..176 | `fTime` | 32 bits |
| 175..64 | `floatingIndex` | 112 bits (signed) |
| 63..0 | `feeIndex` | 64 bits |

### FTag (uint32)

Settlement epoch marker. The parity of the value indicates the event type:

- **Odd values** = FIndex update events (new funding index published).
- **Even values** = purge events (out-of-band order cleanup).

Functions: `isPurge()`, `isFIndexUpdate()`, `nextPurgeTag()`, `nextFIndexUpdateTag()`.

## Position Types

### AccountData2 (uint192)

Per-user position state packed into 192 bits (see also `contracts/storage-layout.md`).

| Bits | Field | Size |
|------|-------|------|
| 191..64 | `signedSize` | 128 bits (signed) |
| 63..32 | `fTag` | 32 bits |
| 31..16 | `nLongOrders` | 16 bits |
| 15..0 | `nShortOrders` | 16 bits |

### PartialData (struct)

Tracks deferred partial fills within the same FTag epoch. See `contracts/storage-layout.md` for field descriptions.

| Field | Size |
|-------|------|
| `sumLongSize` | 128 bits |
| `sumLongPM` | 128 bits |
| `sumShortSize` | 128 bits |
| `sumShortPM` | 128 bits |
| `fTag` | 32 bits |
| `sumCost` | 128 bits |

### MarketStatus (enum)

| Value | Name | Meaning |
|-------|------|---------|
| 0 | `PAUSED` | All operations halted |
| 1 | `CLO` | Closing-only mode — only position reductions allowed |
| 2 | `GOOD` | Normal operation |

## Design Rationale

**Gas optimization through packing**: A single SLOAD for TickInfo retrieves 5 fields (tickSum, headIndex, numActive, tickNonce, activeNonceOffset). Without packing, this would require 5 separate SLOADs at 2100 gas each (cold) = 10,500 gas. Packed, it costs 2100 gas — an 80% reduction.

**OrderId XOR encoding for O(1) priority comparison**: By encoding ticks with XOR and complementing for LONG side, raw `uint64` comparison yields correct execution priority. No decoding needed — the matching engine can compare OrderIds directly.

**VMResult/PayFee aggregation**: Packing value+margin (or payment+fees) into a single uint256 allows the cross-market settlement loop to accumulate results with a single `add()` operation per market, keeping the hot path tight.

**Overflow handling in TickInfo**: The 28-bit `numActive` and 20-bit `activeNonceOffset` fields handle the vast majority of ticks in a single slot. Only unusually large ticks spill to separate storage, keeping the common path to one SLOAD.
