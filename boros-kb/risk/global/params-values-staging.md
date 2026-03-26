---
description: Global parameter values for staging/stress-test environment
last_updated: 2026-03-06
related:
  - risk/global/params-definitions.md
  - risk/global/params-requirements.md
  - risk/global/params-values-production.md
---

# Staging Parameters (Stress Test)

# On-chain parameters

### Core Margin

| Margin params| Value |
| --- | --- |
| kIM | 2/3 | 
| kMM | 1/3 |
| I_threshold | 6% |
| t_threshold | 10 days | 
| critical Health Ratio | 0.4 | 
| no Order Health Ratio | 1 |  


### Order bounds

| Bound params | Value |
| --- | --- | 
| Max rate deviation | 15% | 
| Closing order bound | 10%| 
| Limit Order Upper Const | 0.6% |  
| Limit Order Upper Slope | 1.1 |  
| Limit Order Lower Const | -0.6% |  
| Limit Order Lower Slope | 0.9 | 

### Fees and incentives
| Fee params | Value |
| --- | --- | 
| Taker fee | 0.05% |  
| OTC fee | 0 |  
| Liq fee | 0.05% |  
| Liq incentives base | 0.2 | 
| Liq incentives slope | 0.6 |  
| Settlement fee | 0.2% |  

### Mitigating measures

| Measure params | Value |
| --- | --- |
| (Hard) OI Cap | 6000 ETH/200 BTC |
| Min cash | same as current Beta |
| Market entrance fees | same as current Beta |
| Max open orders | 100 |
| Global cooldown | 1 hour |

### Oracle

| Oracle params | Value |
| --- | --- |
| Max FR deviation factor | 3 |
| Mark rate TWAP duration | 5min |

### AMM

| AMM params | Value |
| --- | --- |
| Fee rate | 0.05% |
| Supply cap | $20000 |
| Oracle Twap duration | 1 min |
| min Rate | 0.5% |
| max Rate | 50% |
| cutoff Timestamp | 3 days before maturity |
| initial Rate | 5% |
| initial size | 48 ETH/ 1.2 BTC |
| flip liquidity | 48 ETH/ 1.2 BTC |
| initial cash | 4 ETH/ 0.1 BTC |

# Off-chain parameters

### Core Margin


| Health Thresholds | Value |
| --- | --- |
| H_f | 0.4 |
| H_d | 0.6 |
| H_c | 0.99 |

### Zone thresholds

| Zone Params | Value |
| --- | --- |
| LC10_high | 8% |
| LC10_low | 2% |
| UV_high | 40ETH/1BTC |
| UV_low | 2ETH/0.05BTC |
| PD_high | 0.05 |
| PD_low | 0.025 |
| dL | 80% |
| dV | 5 |
| t_V | 3min |
| t_L | 3min |
| T | 30m |
| Duration for PD calculation | 10min |

**Note:** Production uses LC35 instead of LC10 for more stable estimates.

### Bot params

| Bot params | Value |
| --- | --- |
| Upper threshold to turn on CLO | 5% below hard cap |
| Lower threshold to turn off CLO | 5.5% below hard cap |
| Large_WD_{TH} | 40 ETH/0.25 BTC |
| Medium_WD_{TH} | 4 ETH/0.05 BTC |
| Withdrawal cooldown for medium withdrawal | 1hr |
| Red zone withdrawal cooldown | 24hr |
| smallMMThreshold (for liq, del, pausing) | 0.001 ETH/0.00003 BTC |
| Minimum profit for liquidation | 0.0003 ETH/ 0.00001 BTC |
| consistency_max_delta | 0.05% |


### Automatic responses
| Response params | Value |
| --- | --- |
| New liquidation incentive base | 50% |
| New liquidation incentive slope | 0 |
| New max rate deviation | 10% |
| New Closing order bound | 6% | 
| New Limit Order Upper Const | 0.36% |  
| New Limit Order Upper Slope | 1.06 |  
| New Limit Order Lower Const | -0.36% |  
| New Limit Order Lower Slope | 0.94 | 

### Alerts related

| Alert params | Value |
| --- | --- |
| D_{rate} | 0.05 |
| T | 1h |
| D_{TVL} | 0.1 |
| H_{TH} | 2/1.8/1.5 |
| AMM_OI_{TH} | 0.3/0.5/0.8 |
| OI_{TH} | 0.3/0.5/0.8 |
| D_{OI} | 0.25 |
| TD_OI_{TH} | 0.3/0.5/0.8 |
| N_trade | 10 |
| short_pos_time | 10min |