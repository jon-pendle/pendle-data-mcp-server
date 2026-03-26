---
description: Alert levels and escalation protocols for risk events
related:
  - risk/risk-overview.md
  - risk/realtime-response-protocol.md
  - risk/global/zone-table.md
---

# Specs for Real Time Alerts on Different Channels

> ⚠️ **Partially outdated** — escalation contacts and some trigger conditions may be stale. The alert level structure, trigger formulas (Lv2 params, zone conditions), and near-maturity protocol remain valid. Do not rely on the named contacts (Vu/Duong/Long/Hiep) without verifying current on-call rotation.

## Level 0: Most extreme conditions, must observe to make sure everything is good.
### Trigger Condition
1. Red Zone triggered.
2. Pausing transactions. 
3. Deleveraging transactions.
4. Potential Pausing after settlement.

### Protocol
1. Call Vu/Duong/Long/Hiep simultaneously.
2. What to do immediately:
  - Most of the cases: observe and check that bots are liquidating/deleveraging/pausing as expected.
  - If necessary, proactively deleverage big positions with low health.
  - If really necessary, manually pause.

## Level 1: Some concerning signs that need to be observed closely in real time, potential to get to Level 0 if continued.
### Trigger Condition
1. Yellow Zone triggered.
2. Zone-setting transactions.
3. Bots are inactive.
4. Deleverage expected at/after the next settlement.

### Protocol
1. Call Duong/Vu.
2. What to do immediately:
  - Most of the cases: observe and check that all signs are within expectation, and note down insights if any.
  - If metrics are not improving: Improve the metrics by internal actions, such as placing orders, ...

## Level 1.1: Skipped Funding Rate
### Trigger Condition
1. Skipped funding rate.
### Protocol
1. Call Duong/Vu.
2. Manual update if safe.

## Level 1.2: Deleverage Before Settlement
### Trigger Condition
1. User's health after settlement drop below 0.7.
### Protocol
1. Delay the settlement.
2. Deleverage this user before the settlement.
3. Settle when user's health after the settlement is above 0.7.

## Level 1.3: Sus user withdrawal
### Trigger Condition
Triggered when a sus trader's withdrawal exceeds the daily quota. A trader is flagged as sus if they meet any one of the following criteria:
1. OI > max(`TD_OI_TH`*`total_OI`, SUS_OI_FLOOR). 
2. Number of all time trades > `N_trade` and Avg position of all time < `short_pos_time`.
3. Number of all time trades > `N_trade` and 90% of the all trades are done less than `short_pos_time` away from FR payments. 
4. Health < `H_f`.
### Protocol
1. Review upon triggered. Review again upon withdrawal request.
2. Call protocol: bot calls Duong/Vu if not acknowledged within 1 hr, retry every 30'.

## Level 2: Notable events that affect overall risks to the system
### Trigger Condition
#### S. Soft version of Zone threshold
1. Volume setting: 
V(now-t_V, now) > dV * max(V(now-t_V -T_V, now - T_V), V_minFactor * total_OI, V_min_abs)
2. Liquidity setting with (t_L, T_L, dL) = (t_LSoft, T_LSoft, dLSoft) = (3 min, 30 min, 50%):
L(now-t_L, now) > dL * L(now - t_L - T_L, now - T_L)
3. PD(T_PD_soft) > PD_Soft.
#### A. AMM 
1. $\frac{|AMM_{rate}-Last_{Trade}|}{Last_{Trade}^+}$ > D_rate (Last trade price on order book vs the implied rate of the AMM).
2. $\frac{|TVL_{t-T}-TVL_t|}{TVL_t}$ > `D_TVL` (TVL in term of number of LP token). 
3. AMM’s Health < `H_TH`.
4. AMM’s OI > `AMM_OI_TH`* `total OI`.
#### B. OI
1. Total OI > `OI_TH` * `OI_Cap`. 
2. $\frac{|OI_{t-T}-OI_t |}{OI_t}$ > `D_OI`. 
#### E. Selected bot activities
1. Withdrawal police bot activities.
2. CLO bot activities. 
3. Failed Liquidation bots.
#### F. New sus user identified
1. New sus user.

### Protocol
1. Risk team members (Vu/Duong/Minh) to take a look within a day.
2. No call protocol.

## Level 3
### Trigger Condition
1. Liquidations
2. Health-jump order cancel
3. Generic order cancel
4. Arbitrage transactions with profit > $10
### Protocol
1. Review upon triggered.
2. No call protocol.

## Near to maturity
### Trigger Condition
1. time_to_maturity < t_threshold  *(per-market config from the market's TOML `[Margin]` section)*
### Protocol
2. Adjust zone threshold according to `risk/global/zone-table.md`.
3. liquidation_base *= time_to_maturity/t_threshold.
