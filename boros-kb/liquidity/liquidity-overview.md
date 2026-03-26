---
description: How market making works on Boros, obligations, onboarding
related:
  - liquidity/market-makers.yaml
  - liquidity/market-making-terms-nayt.md
  - markets/markets.yaml
---

# Liquidity Overview
- There are four sources of liquidity that we want to keep improving on:
  - Internal market makers
  - External market makers
  - AMM liquidity
  - Organic limit orders

# Internal market makers
- **_PathInD** and **_PathD** (see `known-addresses.yaml`) are Boros' internal MMs and cover **all listed markets**.
- They do not have formal per-market terms in `market-makers.yaml` — they operate under internal guidelines.
- Markets with `market_makers: []` in `markets.yaml` are covered by internal MMs only.

# External market makers
- Active external MM: **Nayt** (terms in `market-making-terms-nayt.md`, per-market assignments in `market-makers.yaml`).
- Former external MMs: Flowdesk, Riverside — addresses retained in `known-addresses.yaml` for historical monitoring.
- We want to monitor and make sure the market makers are quoting according to their terms

# Liquidity score
- For each market, there is a Liquidity Score to measure how much liquidity we have on that market:

$$\text{Liquidity Score} = 5 \times \min(\text{bid depth}_{tier1},\ \text{ask depth}_{tier1}) + \min(\text{bid depth}_{tier2},\ \text{ask depth}_{tier2})$$

- **ls-tier1**: depth measured at ±25% of the market's max rate deviation from mid-rate
- **ls-tier2**: depth measured at ±100% of the market's max rate deviation from mid-rate
- The score is always the minimum of bid and ask depth at each tier (tightest side determines quality)


