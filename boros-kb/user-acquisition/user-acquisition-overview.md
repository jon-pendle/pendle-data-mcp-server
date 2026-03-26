---
description: Context on use cases and user acquisition for Boros
last_updated: 2026-03-10
related:
  - overview/overview.md
  - markets/market-overview.md
  - user-acquisition/fixed-return-cash-and-carry.md
  - user-acquisition/fixed-return-funding-rate-arbitrage.md
---

# User Acquisition Overview

There are two main use cases for Boros: **hedging** and **speculation**. Hedging is mainly for bigger players and institutions; speculation is mainly for retail users.

## Hedging strategies (institutional / sophisticated)

Both strategies lock in a **fixed return** by neutralising exposure to the actual funding rate level:

- **Fixed return cash & carry** (`user-acquisition/fixed-return-cash-and-carry.md`): Hold spot + short perp + long Boros FR. Delta neutral, FR neutral, fixed yield until maturity.
- **Fixed return funding rate arbitrage** (`user-acquisition/fixed-return-funding-rate-arbitrage.md`): Pair two venues (e.g. Hyperliquid at 8% vs OKX at 3%) — short FR on the high venue, long FR on the low venue. Locks in the spread (5%) as fixed return, scalable with leverage.

## Speculation strategies (retail)

Retail users take directional views on funding rates:

- **Long rate**: Bet that funding rates will rise above the current fixed price. Pay fixed upfront, receive floating over time.
- **Short rate**: Bet that funding rates will fall. Receive fixed upfront, pay floating over time.
- **Cross-venue plays**: Position on relative funding rate movements between two exchanges without needing to execute the full hedging structure.
