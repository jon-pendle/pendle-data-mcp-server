---
description: Fixed return cash and carry strategy using Boros + perp hedging
last_updated: 2026-03-07
related:
  - user-acquisition/user-acquisition-overview.md
  - user-acquisition/fixed-return-funding-rate-arbitrage.md
  - markets/market-overview.md
---

# Strategy: Fixed return cash and carry

- Example in use:
    - Binance ETHUSDT Perp
    - Market on Boros:
        - Expiry: 27 Feb 2026
- Setup:
    - Leg 1: hold 1000 ETH spot
    - Leg 2: Short 1000 ETH on Binance ETHUSDT Perp
    - Leg 3: Short Funding Rate on Boros’ market for Binance ETHUSDT Perp (27 Feb 2026), with a size of 1000ETH Notional, at a rate of x% (depending on the Implied Rate being traded on Boros. For the sake of example, x = 7%)
- Explanation:
    - Holding a FR short of 1000 ETH on Boros, at 7%, means you are:
        - Paying the floating FR on Binance on 1000 ETH every 8 hours
        - Receiving the fixed 7% APR on 1000 ETH every 8 hours
    - Holding the 1000 ETH short on Binance’s ETHUSDT Perp means that you are:
        - Receiving the floating FR on Binance on 1000 ETH every 8 hours
    - This means that combining the 3 legs together:
        - You are delta neutral (from Leg 1 + Leg 2)
        - You are funding rate neutral (the floating FR is offset between Leg 2 and Leg 3)
        - In total, you are getting a fixed 7% on 1000ETH, until the maturity