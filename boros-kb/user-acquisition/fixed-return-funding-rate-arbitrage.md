---
description: Fixed return funding rate arbitrage strategy across venues via Boros
last_updated: 2026-03-07
related:
  - user-acquisition/user-acquisition-overview.md
  - user-acquisition/fixed-return-cash-and-carry.md
  - markets/market-overview.md
---

# Strategy: Fixed Return Funding Rate Arbitrage
- Example in use:
    - Hyperliquid ETHUSDT Perp and OKX ETHUSDT Perp
    - Market on Boros:
        - Hyperliquid ETHUSDT Perp (27 Feb 2026 maturity): Implied Rate trades at 8%
        - OKX ETHUSDT Perp (27 Feb 2026 maturity): Implied Rate trades at 3%
- Setup:
    - Leg 1: Short 1000 ETH on Hyperliquid ETHUSDT Perp
    - Leg 2: Long 1000 ETH on OKX ETHUSDT Perp
    - Leg 3: Short FR on Boros’ Hyperliquid ETHUSDT Perp (27 Feb 2026 maturity) at 8%
    - Leg 4: Long FR on Boros’ OKX ETHUSDT Perp (27 Feb 2026 maturity) at 3%
- Explanation:
    - It’s delta neutral (from Leg 1 + Leg 2)
    - It’s funding rate neutral:
        - Floating FR on Hyperliquid is offset between Leg 1 + Leg 3
        - Floating FR on OKX is offset between Leg 2 + Leg 4
    - In total, you are getting a fixed return of (8%-3%)= 5% APR on 1000 ETH
        - If your capital is 1000 ETH, you can use 500ETH as collateral each on Hyperliquid and OKX (2x leverage), and a bit of collateral on Boros ⇒ Your return on capital is fixed 5%
        - If you increase the leverage used on the two Perps, you can increase the return on capital. For example, if you use 8x leverage on both Perps, you will get around 4 x (5% gap) = 20% fixed on this strategy