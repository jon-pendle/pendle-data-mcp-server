---
description: Rate oracle subsystems — mark rate sources, transient caching, and AMM implied-rate TWAP
last_updated: 2026-03-17
related:
  - contracts/settlement.md
  - contracts/amm.md
  - contracts/funding-oracle.md
---

# Rate Oracles

Boros uses two rate oracle subsystems documented here: the **mark rate** (drives margin and liquidation) and the **AMM oracle** (smoothed implied rate for AMM interactions).

> For the FIndex Oracle (drives settlement / funding rate), see `contracts/funding-oracle.md`.

---

## Mark Rate

The mark rate is the reference price used for position valuation, margin calculation, liquidation thresholds, OTC trade pricing, and AMM routing.

### Source Selection

Each market has a `useImpliedAsMarkRate` configuration flag:

- **If `true`** (all markets currently): The mark rate equals the **implied rate from the last order book match**. Updated via `_updateImpliedRate()` on every order match.

- **If `false`** (unused, no plan to use): The mark rate would be fetched from an **external `IMarkRateOracle`** contract. This path exists in the code but is not used — all markets use the implied rate as mark rate and there is no intention to change this.

### Transient Caching

Mark rate lookups are cached in **transient storage** during a single transaction via `RateUtils`. The purpose is to ensure the mark rate remains consistent throughout a transaction — even if the mark rate oracle address is changed mid-transaction, all operations will use the rate that was read at first access. The cache is automatically invalidated at the end of the transaction by the EVM's transient storage semantics (EIP-1153).

### Usage Points

The mark rate feeds into:

| Consumer | How it uses mark rate |
|----------|----------------------|
| Margin engine | Position value = size × (markRate - entryRate). Determines IM/MM requirements |
| Liquidation | Checks whether health ratio ≤ 1.0 based on mark-rate-derived position value |
| OTC pricing | OTC trades reference mark rate for fair pricing |
| AMM routing | Router uses mark rate to determine swap direction and size |
| Rate deviation checks | Taker/maker order rates must be within configured deviation from mark rate (`_checkRateDeviation()`) |

---

## AMM Oracle

**Source**: Uses `FixedWindowObservationLib` within each AMM contract.

The AMM oracle provides a **fixed-window TWAP** (time-weighted average price) of the AMM's implied rate. This smoothed rate resists single-block manipulation. It is not currently consumed by other system components but is available for future use.

### Calculation

```
oracleRate = (lastTradedRate × elapsed + prevOracleRate × (window - elapsed)) / window
```

Where:
- `lastTradedRate` is the AMM implied rate after the most recent swap.
- `elapsed` is the time since the last observation.
- `window` is the configurable observation window (e.g., 30 minutes).
- `prevOracleRate` is the oracle rate at the last observation.

This is an exponential moving average approximation — recent trades have proportionally more weight as `elapsed` grows toward `window`.

### Update Trigger

The oracle is updated on **every AMM interaction** via the `onlyRouterWithOracleUpdate` modifier. This means:

- Every swap updates the oracle.
- Every mint updates the oracle.
- Every burn updates the oracle.

The modifier ensures the oracle observation is recorded before the state-changing operation executes, so the oracle always reflects the pre-trade rate.

### Internal Access

`_calcOracleImpliedRateInternal()` computes the current oracle rate on demand without writing a new observation. This is used by read-only view functions and by the Router when it needs the oracle rate for routing decisions.

---

## Oracle Interactions

1. **FIndex Oracle** drives settlement — it determines how much floating payment has accrued. It operates on a fixed schedule controlled by the funding rate pipeline (see `contracts/funding-oracle.md`).

2. **Mark rate** drives real-time risk — it determines whether positions are healthy. It updates on every trade match (if using implied rate) or on external oracle updates.

3. **AMM oracle** provides a manipulation-resistant AMM rate — not currently consumed by other components.

These are independent systems. The FIndex Oracle does not read the mark rate, and the mark rate does not read the FIndex. The AMM oracle is local to each AMM instance.
