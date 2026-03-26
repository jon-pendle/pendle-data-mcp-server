---
description: Storage layout — EIP-7201 namespaced slots, transient storage, and packed struct layouts
last_updated: 2026-03-16
related:
  - contracts/architecture.md
  - contracts/type-system.md
---

# Storage Layout

Boros uses EIP-7201 namespaced storage to isolate state across modules and avoid slot collisions, along with EIP-1153 transient storage for per-transaction scratch data. This document covers every major storage domain.

## EIP-7201 Namespaced Storage

All module and core contract storage is allocated at deterministic slots derived from a namespace string. The `GeneratedStorageSlots` library provides compile-time constants for each storage location.

Examples:

- `AUTH_MODULE_STORAGE_LOCATION` — slot for `AuthModuleStorage`.
- `CORE_ORDER_IS_ORDER_REMOVE_SLOT` — slot for transient `OrderId` mapping used during cancel operations.

Each storage struct is accessed via an `assembly` block that loads the base pointer from the constant slot, giving each module an isolated region of storage that will never collide with another module even under proxy upgrades.

## AuthModuleStorage

Located at `AUTH_MODULE_STORAGE_LOCATION`. Stores all agent and signer state for the AuthModule.

| Field | Type | Description |
|-------|------|-------------|
| `agentExpiry` | `mapping(Account => mapping(address => uint256))` | Timestamp when an agent's authorization expires for a given Account |
| `signerNonce` | `mapping(address => uint64)` | Strictly increasing nonce per signer, used for EIP-712 PendleSignTx replay protection |
| `accManager` | `mapping(Account => address)` | Account manager address that can approve agents on behalf of the Account holder |
| `allowedRelayer` | `mapping(address => bool)` | Addresses permitted to relay agent-signed transactions |
| `isIntentExecuted` | `mapping(bytes32 => bool)` | Tracks executed OTC/conditional intent hashes to prevent replay |

## TradeStorage

Located at its own named slot. Manages routing state for trade operations.

| Field | Type | Description |
|-------|------|-------------|
| AMMId-to-MarketAcc mapping | `mapping(AMMId => MarketAcc)` | Links AMM identifiers to their corresponding MarketAcc for routing |
| Trade routing state | various | Additional state used during hybrid AMM/CLOB execution |

## MarketHub Storage (Storage.sol)

The MarketHub base contract `Storage` holds the core accounting state for all accounts and markets.

### Primary mappings

| Field | Type | Description |
|-------|------|-------------|
| `acc` | `mapping(MarketAcc => MarketAccData)` | Per-account data including cash balance and market membership |
| `cashFeeData` | `mapping(TokenId => CashFeeData)` | Fee configuration per collateral token |
| `_tokenData` | `TokenData[]` | Array of supported tokens with scaling factors |
| `_marketIdToAddress` | `mapping(MarketId => address)` | Resolved market contract addresses |
| `_strictMarkets` | `mapping(MarketId => bool)` | Markets subject to strict initial margin |
| `_strictMarketsFilter` | `uint128` | Bloom filter for fast strict-market membership check |

### MarketAccData

```
struct MarketAccData {
    int256 cash;
    bool hasEnteredMarketBefore;
    MarketId[] enteredMarkets;
}
```

`cash` is the signed balance (can go negative during settlement). `enteredMarkets` is bounded by the `MAX_ENTERED_MARKETS` immutable.

### CashFeeData

```
struct CashFeeData {
    uint128 treasuryCash;
    uint128 marketEntranceFee;
    uint128 minCashCross;
    uint128 minCashIsolated;
}
```

`minCashCross` and `minCashIsolated` set minimum deposit thresholds for cross-margin and isolated-margin accounts respectively.

### Risk parameters

| Field | Type | Description |
|-------|------|-------------|
| `critHR` | `int128` | Critical health ratio threshold — below this triggers liquidation |
| `riskyThresHR` | `int256` | Risky threshold — below this enables force-cancel of risky users |
| `globalCooldown` | `uint32` | Global cooldown period between withdrawals |
| `_withdrawal` | `mapping(address => mapping(TokenId => Withdrawal))` | Per-user, per-token withdrawal tracking (`Withdrawal` has `uint32 start` + `uint224 unscaled`) |
| `_personalCooldown` | `mapping(address => uint32)` | Per-user cooldown override |

## Market Storage

Each Market contract maintains its own order book and position state.

### Order book

| Field | Type | Description |
|-------|------|-------------|
| Tick mapping | `mapping(int16 => Tick)` | Order book ticks indexed by tick index |
| Bitmap | `uint256[]` | Bitmap of active ticks for efficient traversal |

### AccountData2 (packed uint192)

Per-user position data packed into a single 192-bit slot:

| Bits | Field | Size | Description |
|------|-------|------|-------------|
| 191..64 | `signedSize` | 128 bits | Net position size (signed — positive = long) |
| 63..32 | `fTag` | 32 bits | Last settled funding tag epoch |
| 31..16 | `nLongOrders` | 16 bits | Count of active long resting orders |
| 15..0 | `nShortOrders` | 16 bits | Count of active short resting orders |

A single SLOAD retrieves the full position state, order counts, and settlement epoch for an account.

### PartialData

Tracks deferred partial fills that occur within the same FTag epoch:

| Field | Size | Description |
|-------|------|-------------|
| `sumLongSize` | 128 bits | Accumulated long fill size |
| `sumLongPM` | 128 bits | Accumulated long P&M |
| `sumShortSize` | 128 bits | Accumulated short fill size |
| `sumShortPM` | 128 bits | Accumulated short P&M |
| `fTag` | 32 bits | The epoch these partials belong to |
| `sumCost` | 128 bits | Accumulated cost |

`addToStorageIfAllowed()` returns `false` if the incoming fTag does not match the stored fTag, forcing a settlement before new partials can be accumulated.

### FIndex oracle state

The funding index oracle stores cumulative funding state. See the `FIndex` type in `contracts/type-system.md` for the packed layout.

## Transient Storage (EIP-1153)

Boros uses EIP-1153 `tstore`/`tload` for data that only needs to live within a single transaction. This avoids the 2100-gas cold SSTORE cost entirely — transient slots cost only 100 gas.

### Mark rate cache

The mark rate for a market is cached in transient storage on first access within a transaction. The purpose is to guarantee the mark rate does not change during the transaction — even if the mark rate oracle address is changed mid-transaction, all operations will use the rate that was read at first access.

### OrderId cancel mapping

During cancel operations, an `OrderIdBoolMapping` in transient storage tracks which OrderIds have been flagged for removal in the current transaction. This is stored at the `CORE_ORDER_IS_ORDER_REMOVE_SLOT` location.

### Auth context

The current `Account` being acted upon is stored in transient storage during agent execution. This allows downstream functions to verify the authenticated account without passing it through every call frame.

## Design notes

The combination of EIP-7201 namespaced storage and aggressive struct packing means:

1. **No slot collisions** — each module and contract gets an isolated storage region, safe across proxy upgrades.
2. **Minimal SLOADs** — packed types like `AccountData2` (192 bits), `TickInfo` (256 bits), and `MarketAccData` reduce cold storage reads. At 2100 gas per cold SLOAD, packing 5 fields into one slot (as in `TickInfo`) saves 8400 gas versus 5 separate slots.
3. **Zero-cost transient data** — mark rate caching and cancel tracking via EIP-1153 avoid permanent storage writes for ephemeral state.
