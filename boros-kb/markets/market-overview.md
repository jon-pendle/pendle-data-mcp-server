---
description: How markets are structured and listing criteria
related:
  - markets/markets.yaml
  - risk/market-params/market-params-overview.md
  - user-acquisition/fixed-return-funding-rate-arbitrage.md
  - user-acquisition/fixed-return-cash-and-carry.md
---

# Market Overview
- The master list of markets is in `markets/markets.yaml`, with their risk parameters in `risk/market-params/` (per-market TOMLs) and `risk/global/` (global params)

### Market listing operations
- Maturities are always 0:00UTC on the last Friday of a month
- We typically list markets on Wednesday morning (Singapore time)
- We list one month maturities for most markets, quarterly maturities for more actively traded markets and potentially next-quarter maturities for the most actively traded markets

### Market listing strategy
- We list markets to "feed" on the inefficiencies across funding rates on Perp:
  - List pair of markets on the same coin with the biggest and most consistent difference in funding rates, to enable the Fixed return funding rate arbitrage (mentioned in user-acquisition/fixed-return-funding-rate-arbitrage.md)
  - List markets with the highest funding rate, to enable the Fixed rate cash and carry strategy (mentioned in user-acquisition/fixed-return-cash-and-carry.md)