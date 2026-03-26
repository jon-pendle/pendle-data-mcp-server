---
description: High-level overview on Boros platform
last_updated: 2026-03-10
related:
  - mechanics/litePaper.md
  - user-acquisition/user-acquisition-overview.md
  - markets/market-overview.md
---

# What is Boros

Boros is an onchain trading platform for **interest rate swaps on funding rates**, running on Arbitrum. Users deposit collateral and take a position (long or short) on the funding rate of a particular perpetual market, held until a fixed maturity date.

- **Long Rate (pay fixed / receive floating):** You pay a fixed cost upfront and receive the floating funding rate over time. Profitable if the actual funding rate exceeds your fixed rate.
- **Short Rate (pay floating / receive fixed):** You receive a fixed amount and pay the floating funding rate. Profitable if the funding rate stays below your fixed rate.

Positions are settled periodically (floating payments every ~8 hours, aligned with perp funding intervals) and at maturity.

## Key concepts

| Term | Meaning |
|------|---------|
| **Market** | A specific perp funding rate (e.g. ETHUSDT on Binance) with a fixed maturity |
| **Mark Rate** | TWAP of recent trades on the Boros order book; used for margin and liquidation calculations |
| **Trading Zone** | Cross-margin or isolated-margin collateral zone grouping markets by base asset |
| **Health Ratio** | Total position value / maintenance margin; falls below 1.0 triggers liquidation |
| **Maturity** | All current markets expire 2026-03-27 00:00 UTC (last Friday of month) |

## Where to go next

- **Mechanics (user-facing):** `mechanics/litePaper.md`
- **Mechanics (formal):** `dev-docs/docs/boros-dev-docs/Mechanics/` (margin, orderbook, settlement, fees)
- **Currently listed markets:** `markets/markets.yaml`
- **Risk framework:** `risk/risk-overview.md`
- **User acquisition strategies:** `user-acquisition/user-acquisition-overview.md`
