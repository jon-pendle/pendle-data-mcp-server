---
description: Global parameter values for production environment
last_updated: 2026-03-10
related:
  - risk/global/params-definitions.md
  - risk/global/params-requirements.md
  - risk/global/params-values-staging.md
---

# Production Parameters

# On-chain parameters

### Mitigating measures

| Measure params | Value |
| --- | --- |
| Min cash |  $10 |
| Market entrance fees | ~$1 (0.000008 BTC for BTC markets; 0.00027 ETH for ETH markets; $1 USDC/USDT for USD-denominated markets) |
| Max open orders | 100 |
| Global cooldown | 15 min |


### Fees and incentives
| Fee params | Value |
| --- | --- | 
| Taker fee | 0.05% |  
| OTC fee | 0.05% |  
| Liq fee | 0.05% |  
| Liq incentives base | 0.25 | 
| Liq incentives slope | 0.5 |  
| Settlement fee | 0.2% |  

### CLO Whitelist

Addresses with the `exemptCLOCheck` flag set — these accounts can continue placing open orders even when the market is in CLO mode. All other accounts are restricted to closing orders only. See `dev-docs/docs/boros-dev-docs/Mechanics/Margin.mdx` § Closing-Only Mode.

| Address | Label |
| --- | --- |
| 0xa24be328cb80b3e4f33466d46130578fc3a214e8 | Caladan1 |
| 0x13b3a35583aa11cf482fe4faf7567e5c1757f17b | Caladan2 |
| 0x3c0993870f01e198860dc9120dd67ca1317e2267 | Caladan3 |
| 0xeefd4a6eab475eaed1ca52f4f6e76a0576482b28 | Caladan4 |
| 0x8624657e19bc67c59d8de0309b5eed63b02e02bd | Caladan5 |
| 0x904636B8922348e187426892a8bC96C3053b7176 | _PathInD |
| 0xB180808080e0544f77261CDeCc9a2540104682F6 | _BotController |
| 0xB380808080966f09E3d26cc32756D56fd454930D | _MarkRatePusher |
| 0xB57c34FbCB272510303675397055942B019eE45A | _Market2AMM |
| 0x48e1e85AB2d717A41Cb7AEAf0DE12321B8C14A0f | _Market3AMM |

# Off-chain parameters

### Bot params

| Bot params | Value |
| --- | --- |
| Upper threshold to turn on CLO | 5% below hard cap |
| Lower threshold to turn off CLO | 7% below hard cap |
| Red zone withdrawal cooldown | 24hr |
| Large_WD_{TH} | $100_000|
| smallMMThreshold (for liq, del, pausing) | $10.00 |
| Minimum profit for liquidation | $1 |
| consistency_max_delta | 0.05% |

### Zone thresholds

| Zone Params | Value |
| --- | --- |
| LC35_high | 15% |
| LC35_low | 5% |
| UV_high | 100_000USD |
| UV_low | 4000USD |
| UV_low_coef | 5% |
| PD_high | 0.08 |
| dL | 50% |
| t_L | 10min |
| T_L | 30m |
| T_PD | 10min |
| t_PD | 5min |
| V_min_abs | 400_000USD |

### NearToMaturity

In the last 72 hours before expiry, `k_MD` is dynamically reduced:

```
k_MD = min(0.5, (k_MM × t_th / t) / (1 + k_MM × t_th / t) × 2)
```

where `t` is time to maturity. This tightens order bounds as the market approaches settlement.

### Lv2 Alerts related

| Alert params | Value |
| --- | --- |
| D_rate | 0.05 |
| T | 1h |
| D_TVL | 0.1 |
| H_TH | 2/1.8/1.5 |
| AMM_OI_TH | 0.3/0.5/0.8 |
| OI_TH | 0.3/0.5/0.8 |
| D_OI | 0.25 |
| TD_OI_TH | 0.3/0.5/0.8 |
| N_trade | 10 |
| short_pos_time | 10min |
| t_V | 3 min |
| T_V | 30 min |
| dV | 5 |
| V_minFactor | 0.016 |
| SUS_OI_FLOOR | 2M USD |

**Note on slash-separated thresholds:** Parameters like `H_TH = "2/1.8/1.5"`, `AMM_OI_TH/OI_TH/TD_OI_TH = "0.3/0.5/0.8"` contain three slash-separated values corresponding to alert levels Lv1/Lv2/Lv3 respectively. An alert fires each time the metric crosses a level — including re-crosses (drops below then rises above again).

### Theory params

These are the minimum design requirements for the health thresholds — the bot-enforced values must be ≥ the theoretical values to guarantee solvency. The bot-enforced (actual runtime) values differ:

| Param | Theoretical (floor) | Bot-enforced (actual) |
| --- | --- | --- |
| H_f (pause) | 0.4 | 0.4 |
| H_d (deleverage) | 0.6 | 0.7 |
| H_c (cancel orders) | 0.8 | 0.8 |

`H_d_theoretical = 0.6` means the proof guarantees solvency as long as the bot deleverages at any health ≤ 0.6. The bot is actually set to trigger at ≤ 0.7 (more conservative), which satisfies the theoretical requirement.

### Cross Markets params

#### OrderBounds

| Param | Value |
| --- | --- |
| k_MD | 0.15 |
| k_CO | 0.1 |
| limit_Order_Upper_Slope | 1.05 |
| limit_Order_Lower_Slope | 0.95 |

#### AutomaticResponses

| Param | Value |
| --- | --- |
| new_liquidation_incentive_base | 0.5 |
| new_liquidation_incentive_slope | 0 |
| new_k_MD | 0.1 |
| new_k_CO | 0.06 |
| new_limit_Order_Upper_Slope | 1.025 |
| new_limit_Order_Lower_Slope | 0.975 |

### Other

| Param | Value |
| --- | --- |
| max_FR_deviation_factor | 0.8 * t_threshold/t_delta * k_MM |

> **Note:** `max_FR_deviation_factor` is not a fixed global constant — it is derived per-market from that market's `t_threshold` (TOML `[Margin]`), `t_delta` (settlement interval), and `k_MM`. Markets that omit `max_FR_deviation_factor` from their TOML use this formula as the default.