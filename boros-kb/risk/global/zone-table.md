---
description: Zone thresholds for White/Yellow/Red risk zones
last_updated: 2026-03-18
related:
  - risk/realtime-response-protocol.md
  - risk/alert-specs.md
  - risk/global/params-values-production.md
  - risk/global/params-definitions.md
---

# Zone Table

Each market is continuously classified into one of three risk zones — White (healthy), Yellow (caution), Red (distressed) — based on four independent metrics. A market's zone is the **worst** of the four metric evaluations.

Production parameter values are sourced from `risk/global/params-values-production.md`. Metric definitions are in `risk/global/params-definitions.md`.

---

## Metric Definitions (summary)

| Metric | What it measures |
|--------|-----------------|
| **LC** | Liquidation Cost: net orderbook + AMM liquidity surplus needed to cascade-liquidate x% of OI. High LC = deep book relative to leverage (healthy). Low LC = thin book, easy to cascade. Windowed average over `lc_window_length` samples. |
| **UV** | Unhealthy Volume: total position value (mark-to-market) of positions whose liquidation rate has been crossed. `UV = max(UV_sell, UV_buy)`. High UV = positions liquidatable but not being liquidated. |
| **PD** | Price Deviation: `t_PD`-th highest instant deviation in the last `T_PD` snapshots. High PD = mark lags reality. |
| **DP** | Deleverage Points: simulated rate at which forced auto-deleverage triggers, accounting for cascading liquidations and orderbook consumption. Closer to mark rate = more dangerous. |

---

## Default Zone Classification

| Metric  | White ✅ | Yellow ⚠️ | Red 🔴 |
|---------|----------|-----------|--------|
| **LC(35%)** | > 10% × total_OI | < 10% × total_OI (with suppression) | |
| **UV** | < min(4,000 USD, 5% × total_OI) | between | > 100,000 USD |
| **PD(t_PD, T_PD)** | < 0.08 | > 0.08 (with suppression) | |
| **DP** | abs(DP − markRate) / markRate⁺ > 2 × k_MD | between | abs(DP − markRate) / markRate⁺ < k_MD |

**Suppression logic**: Yellow zone LC is suppressed if the liquidation threshold rate is far from mark rate. Yellow zone PD is suppressed if all positions' liquidation rates fall outside the recent traded rate range (no positions actually at risk).

---

## Near-Maturity Zone Classification (< 10 days to expiry)

LC, UV, DP thresholds are unchanged. PD thresholds are **tightened** to double sensitivity.

| Metric  | White ✅ | Yellow ⚠️ | Red 🔴 |
|---------|----------|-----------|--------|
| **LC(35%)** | > 10% × total_OI | < 10% × total_OI | |
| **UV** | < min(4,000 USD, 5% × total_OI) | between | > 100,000 USD |
| **PD(t_PD, T_PD)** | < 0.04 | ≥ 0.04 | — (no distinct Red for PD near maturity) |
| **DP** | abs(DP − markRate) / markRate⁺ > 2 × k_MD | between | abs(DP − markRate) / markRate⁺ < k_MD |

---

## Liquidity Drop Alert (separate from zone classification)

In addition to the zone metrics, a liquidity drop trigger fires when liquidity falls sharply within a short window:

| Param | Value | Meaning |
|-------|-------|---------|
| `dL`  | 50%   | Threshold: trigger if recent liquidity is < 50% of reference window liquidity |
| `t_L` | 10 min | Duration of the "recent" liquidity window |
| `T_L` | 30 min | Lookback: reference window starts `T_L` before the recent window |
| `V_min_abs` | 400,000 USD | Minimum absolute volume to consider LC and UV metrics meaningful |

---

> For the raw parameter values behind all thresholds in this table, see `risk/global/params-values-production.md` § Zone thresholds.
