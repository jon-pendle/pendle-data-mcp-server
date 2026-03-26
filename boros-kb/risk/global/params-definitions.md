---
description: Definitions of all on-chain and off-chain risk parameters
last_updated: 2026-03-06
related:
  - risk/global/params-requirements.md
  - risk/global/params-values-production.md
---

# Parameter Definitions

# On-chain parameters

## Margin

### k_CO
The closing order bound.

### k_MD
The Max rate deviation.

### k_IM

The constant used to calculate Initial Margin.

### k_MM

The constant used to calculate Maintenance Margin.

### I_threshold

The constant used to calculate the capped mark rate.

### t_threshold

The constant used to calculate the capped time to maturity.

### t_delta

The time interval between 2 consecutive settlements.

## Order bounds

### Max rate deviation

The coefficient to calculate the upper/lower bounds of long/short orders’ price.

Example: When the capped mark rate is 5% and this coefficient is 20%, then the upper bound for long orders’ price is $5\% + 20\%\times5\% = 6\%$ , and the lower bound for short orders’ price is $5\% + 20\%\times5\% = 4\%$ .

### Closing order bound

The coefficient to calculate the upper/lower bounds of closing long/short orders’ price under risky condition (does not have enough Initial margin).

### Limit Order Upper/Lower Const/Slope

The constants used to calculate the limit order bounds (those stay on the order book after transaction).

## Fee and Incentives

## **Mitigating measures**

### Hard OI Cap

The total OI of the market can not exceed this cap.

### Global Cooldown

The amount of time that a general user needs to wait to withdraw their fund from the system.

## Oracle

### Max FR deviation factor

The coefficient to calculate the bound for the funding rate from Oracle. 

Example: Suppose the capped market rate is 5% and the coefficient is 5, then only the funding rate within the range $[5\%-5\times 5\%,5\%+5\times 5\%] =[-20\%, 30\%]$ are accepted automatically. Otherwise, this funding rate settlement is skipped.

### Mark rate TWAP duration

This duration parameter is used to calculate the mark rate as a TWAP of the traded price. 

## AMM

Refer to AMM paper.

# Off-chain parameters

## Health thresholds

### H_c

The health threshold where all of user’s orders are cancelled.

### H_d

The health threshold where user is deleveraged. 

### H_f

The health threshold where the system is paused.

## **Zone thresholds**

### total_OI

The total OI of the current opening position in the system (single count).

### L

The total liquidity on the order book and AMM within `[r_m -k_{MM}*Liq_incentives_base*(r_m+),r_m + k_{MM}*Liq_incentives_base*(r_m+)]`.

`L(a,b)` is the average of this liquidity value from time `a` to `b`.

`t_L` is the duration between time `a` and `b`  mentioned above.

`dL` is the threshold for diagnosing a risky implication from a significant drop in the previous quantity.

`T_L` is the duration to compare the average liquidity.

Example: Suppose `t_L=5 min` and `T_L = 10 min`, and now is 18:30. Then we compare the average liquidity from 18:25 to 18:30 vs the average liquidity from 18:15 to 18:20.

### V

`V(a,b)` is the total volume from time `a` to `b` (single count).

`t_V` is the duration between time `a`  and `b` mentioned above.

`dV` is the threshold for diagnosing a risky implication from a significant surge in the previous quantity.

`T_V` is the duration to compare the average volume.

### Liquidation Volume

The total amount of volume to be liquidated when price reaches a certain threshold.

### LC(x%) Long/Short

The net orderbook + AMM liquidity surplus needed so that x% of total OI can be liquidated via cascading liquidations. Computed per side, final LC = `min(longLC, shortLC)`, expressed as fraction of total OI. Windowed average over `lc_window_length` samples.

See `risk/realtime-response-protocol.md` for the full algorithm.

**Example:**

Ask orderbook (non-cumulative): 8%: 5 YU, 7%: 4 YU, 6%: 3 YU, 5%: 2 YU

Liquidation volume: 8%: 7 YU, 7%: 2 YU, 6%: 1 YU

Total OI = 10 YU. To liquidate 10% (1 YU), push price to 6% → costs 2 YU. To liquidate 30% (3 YU), push price to 7% → costs 4 YU (not 5), because 1 YU is liquidated at 6% and sold into the book, offsetting part of the cost.

### Unhealthy Volume (UV)

Total position value (mark-to-market) of positions whose liquidation rate has been crossed by the current mark rate. `UV = max(UV_sell, UV_buy)`. Measured in position value, not raw notional size.

### Price Deviation PD(t_PD, T_PD)

For each 1-minute snapshot, the instant deviation is:

```
ID = max(|tradedRate − markedRate|) / max(|markedRate|, iThresh)
```

where the max is taken over all trades in that minute. `PD(t_PD, T_PD) = ID₍t_PD₎` — the `t_PD`-th highest instant deviation across the last `T_PD` snapshots. This filters out brief spikes while catching sustained deviation.

See `risk/realtime-response-protocol.md` for AMM override, no-trade handling, and suppression logic.

**Example 1:** Price goes down from 10% to 5% (I_threshold = 10%), last traded price goes from 9% to 4% → PD ≈ 0.1.

**Example 2:** Price fluctuates around 5%, last traded price goes around 3% to 7% → PD ≈ 0% (deviations cancel out).

### Deleverage Points (DP)

Simulated rate at which forced auto-deleverage triggers, computed separately for long and short sides. Runs a full cascade liquidation simulation against the current orderbook.

See `risk/realtime-response-protocol.md` for the full simulation algorithm and zone thresholds.