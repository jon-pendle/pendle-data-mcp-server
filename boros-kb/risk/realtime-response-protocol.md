---
description: Realtime Response Protocol
last_updated: 2026-03-18
related:
  - risk/risk-overview.md
  - risk/alert-specs.md
  - risk/global/zone-table.md
  - risk/global/params-definitions.md
---

# Realtime Response Protocol

This document describes the off-chain protocol for managing risks and dealing with emergencies in Boros. There are two parts:
- Zone-based triggers and responses
- The bot system


## Zone-based system

Each market is continuously classified into one of three zones: White (healthy), Yellow (caution), Red (distressed). Zone is determined by four independent metrics — the worst of the four applies.

**Source**: `apps/responder/src/responses/zone/zone.service.ts`

### Zone thresholds

See `risk/global/zone-table.md` for White/Yellow/Red classification tables with production values. See `risk/global/params-definitions.md` for parameter definitions.

---

### Liquidation Cost (LC)

**Source**: `libs/risk-monitor/src/liquidation-cost.ts`

Measures how much liquidity surplus exists to absorb cascading liquidations for x% of OI. High LC = deep book relative to leverage (healthy). Low LC = thin book, easy to cascade.

**Algorithm** (`calculateLiquidationCost`):

1. Filter positions by side (long or short). Sort by liquidation rate — closest to current mark rate first (most vulnerable).
2. Walk through positions one by one. For each position at liquidation rate `r`:
   - Accumulate orderbook liquidity at ticks between mark rate and `r` (+ AMM liquidity from `calSwapAMMFromToRate` if AMM is active and not cut off)
   - `c = max(c, orderbookLiquidity + ammLiquidity − cumulativeLiquidatedOI)` — the net liquidity surplus at this rate level
   - Add position size to cumulative OI. Stop when cumulative OI ≥ x% of total OI.
3. Compute for both long and short sides. Final LC = `min(longLC, shortLC)`.
4. LC is windowed: the zone service maintains a rolling window of `lc_window_length` samples and uses the average.
5. LC is expressed as a fraction of total OI: `LC / total_OI`.

**Suppression**: Yellow zone LC is suppressed if the liquidation threshold rate (the rate at which x% OI would be liquidated) is far from mark rate — specifically if `|liquidationThresholdRate − markRate| > kMD × max(iThresh, |markRate|) × lc_suppress_factor`.

---

### Unhealthy Volume (UV)

**Source**: `libs/risk-monitor/src/position-oi.ts`, `zone.service.ts`

Total position value (mark-to-market) of positions whose liquidation rate has been crossed by the current mark rate. High UV = positions liquidatable but not being liquidated.

```
UV_sell = Σ |positionValue(p)| for short positions where liquidationRate > markRate
UV_buy  = Σ |positionValue(p)| for long positions where liquidationRate < markRate
UV = max(UV_sell, UV_buy)
```

Note: UV is measured in position value (notional × rate × timeToMat), not raw notional size.

---

### Price Deviation (PD)

**Source**: `libs/risk-monitor/src/price-deviation.ts`

Measures how far the traded rate deviates from the mark rate over a window of 1-minute snapshots. High PD = mark rate is lagging the real market.

For each 1-minute snapshot, the instant deviation is:

```
ID = max(|tradedRate − markedRate|) / max(|markedRate|, iThresh)
```

where the max in the numerator is taken over all trades in that minute.

**AMM override**: If the AMM is active (not cut off) and its implied rate is within `[minAbsRate + 0.05%, maxAbsRate − 0.05%]`, the AMM implied rate is used as `tradedRate` instead of the last book traded rate. This reflects that the AMM provides continuous pricing even when the book is stale.

**No-trade handling**: If `tradedRate` hasn't changed since the previous snapshot, deviation is set to 0 (no real price movement occurred).

**Selection**: `PD(t_PD, T_PD) = ID₍t_PD₎` — the `t_PD`-th highest instant deviation across the last `T_PD` snapshots. This filters out brief spikes while catching sustained deviation.

**Suppression**: Yellow zone PD is suppressed if all positions' liquidation rates fall outside the recent traded rate range (i.e., no positions are actually at risk from the price movement).

---

### Deleverage Points (DP)

**Source**: `libs/risk-monitor/src/deleverage-points/deleverage-points.ts`, `liquidation-simulator.ts`

The rate at which forced auto-deleverage would trigger, computed separately for long and short sides. This is a simulation-based metric — it runs a full cascade liquidation simulation to find the point where liquidations can no longer proceed and deleverage must kick in.

**Algorithm** (`LiquidationSimulator.simulateLiquidations`):

1. Start from current mark rate, current orderbook (bids/asks), and all positions with their liquidation and deleverage rates (computed via `calcUnhealthyRate` with `desiredHealth = deleverageThresHR`).
2. Repeat:
   a. Take the position closest to liquidation on the given side.
   b. If not yet unhealthy at current simulated mark rate → push mark rate to its liquidation rate (consuming orderbook orders that get filled along the way).
   c. If unhealthy → attempt liquidation: compute `liqAllInRate` (the worst rate at which liquidation is still profitable after incentive, fees, taker fees). Find orderbook orders within that rate.
   d. If orders exist → execute liquidation: consume orderbook liquidity, update position (reduce size, adjust cash for payment and incentive), recalculate unhealthy rates.
   e. If no orders exist → check if orders exist at the deleverage rate. If not → **deleverage point found** (no liquidity to liquidate, deleverage is the only option). If yes → binary search for the mark rate between current and deleverage rate where liquidity first appears, push mark rate there.
3. Stop after 1000 iterations (safety limit) or when all positions are liquidated or deleverage point is found.

**Zone thresholds**: The difference between mark rate and deleverage point is compared against `kMD × max(iThresh, |markRate|) × factor`:
- `deleverage_point_diff_high_factor` (default 3) → Yellow if closer than this
- `deleverage_point_diff_low_factor` (default 1.2) → Red if closer than this

### Zone responses

- **Yellow zone:**
  - Alert in yellow zone channel
- **Red zone:**
  - Decrease max rate deviation bound (tighter order bounds)
  - Turn on CLO (Closing Only) mode — no new position opens
  - Turn on strict health check
  - Increase liquidation incentives

## Bot system

Various bots run continuously to stabilise the system:

| Bot | Role |
|-----|------|
| Pausing bot | Halts the market in extreme scenarios |
| Deleverage bot | Force-closes positions when health ≤ H_d threshold |
| Liquidation bot | Liquidates positions when health ≤ 1 |
| Health-jump order cancel bot | Cancels orders that cause sudden health drops |
| Generic order cancel bot | Cancels orders under general risk conditions |
| Withdrawal police bot | Monitors and flags suspicious withdrawal patterns |
| Closing Only Mode (CLO) bot | Activates/deactivates CLO mode based on OI vs hard cap |
| Mark rate pusher bot | Pushes mark rate on-chain to keep it current |

> **Note:** The Liquidation Bot, Force-Cancel Bot, and CLO Bot are now documented publicly in `dev-docs/docs/boros-dev-docs/HighLevelArchitecture.mdx` § Bot Infrastructure. The Pausing bot, Deleverage bot, Withdrawal police bot, and Mark rate pusher bot are internal-only and not yet fully documented. See `risk/alert-specs.md` for bot-triggered alert levels and escalation paths.
