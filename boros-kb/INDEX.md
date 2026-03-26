# Boros Knowledge Base Index

> Read this file first to find the right context files for your task.
> For protocol mechanics and architecture, prefer the **Dev Docs** section below — those are the canonical source. KB files cover internal/operational knowledge not found in dev docs.

## Overview
- `overview/overview.md` — High-level overview of the Boros platform

## Mechanics
- `mechanics/litePaper.md` — Lite paper: high-level, user-centric explanation of how Boros works
- `mechanics/whitepaper.tex` — Whitepaper: formal definitions and formulas (LaTeX)
- `mechanics/boros-proofs.tex` — Mathematical solvency proofs (LaTeX)
- `mechanics/risk-control-mechanisms.md` — Risk control mechanisms (OI cap, CLO mode, max rate deviation, limit order bounds)

## Risk
- `risk/risk-overview.md` — Risk management philosophy, framework, and index of all risk docs

## Markets
- `markets/market-overview.md` — Market structure, listing criteria
- `markets/markets.yaml` — All currently listed markets

## Liquidity
- `liquidity/liquidity-overview.md` — How market making works on Boros
- `liquidity/market-makers.yaml` — Market makers, assigned markets, terms
- `liquidity/market-making-terms-nayt.md` — Nayt MM terms and SLAs

## User Acquisition
- `user-acquisition/user-acquisition-overview.md` — Overview of use cases and user acquisition in Boros
- `user-acquisition/fixed-return-funding-rate-arbitrage.md` — Fixed return funding rate arbitrage strategy
- `user-acquisition/fixed-return-cash-and-carry.md` — Fixed return cash and carry strategy

## Contracts (Internal — Implementation-Level)
> Deep-dive into Boros smart contract internals. Source of truth for how the Solidity actually works.

### Architecture & Foundation
- `contracts/architecture.md` — Router dispatch (7 modules), MarketHub proxy, Market facets, full call-flow diagram
- `contracts/storage-layout.md` — EIP-7201 namespaced slots, transient storage (tstore/tload), mapping structures, AccountData2 packing
- `contracts/access-control.md` — PendleAccessController, role hierarchy, guard modifiers, agent auth (EIP-712), bot permissions matrix
- `contracts/type-system.md` — All packed types with bit layouts: Account, MarketAcc, OrderId (XOR encoding), Trade, PayFee, VMResult, FIndex, FTag, TickInfo, NodeData, PartialData

### Core Mechanics (Code-Level)
- `contracts/order-lifecycle.md` — 5-phase orderAndOtc flow, QIT data structure, tick bitmap, OrderId priority, rate bounds, TIF enforcement
- `contracts/settlement.md` — Sweep-process pipeline, FTag epochs, FIndex retrieval (TickNonce/binary search), PartialData handling
- `contracts/margin-engine.md` — MarginViewUtils walkthrough: PM/IM/MM formulas, piecewise MM, strict vs closing-only checks, cross-market aggregation
- `contracts/liquidation.md` — Liquidation incentive formula, force deleverage with bad debt sharing, force cancel, OOB purge

### Subsystems
- `contracts/amm.md` — PositiveAMM/NegativeAMM math (X^t × Y = k), BOROS20 LP token, withdraw-only mode, AMM oracle
- `contracts/rate-oracles.md` — Mark rate source selection, transient caching, AMM TWAP oracle
- `contracts/funding-oracle.md` — Funding rate pipeline: offchain bot → FundingRateVerifier (3-source validation) → FIndexOracle → Market settlement
- `contracts/deposits-withdrawals.md` — Deposit/DepositBox flow, 18-decimal normalization, 3-step withdrawal cooldown, cash transfers
- `contracts/cross-chain.md` — Hub-spoke cross-chain architecture: CrossChainPortal, DepositBox on spoke chains, LayerZero OFT bridges, full deposit flow from spoke to Arbitrum hub

### Reference
- `contracts/events-errors.md` — Complete error catalogue (Errors.sol) and key events, grouped by domain
- `contracts/risk-bots.md` — BotController diamond proxy architecture, all facets inventory, MarkRatePusher, ZoneResponder, math libraries
- `contracts/bots-facets.md` — Detailed per-facet reference: parameters, logic flows, error cases for all 10 facets
- `contracts/bot-math-libs.md` — Bot math libraries: LiquidationMath (sizing, incentive, dual-constraint), ArbitrageMath (AMM-book spread), SettleSimMath (settlement projection), SwapBoundMath (margin primitives)
- `contracts/router-math-libs.md` — Router math libraries: SwapMath (optimal book-AMM trade splitting, fee-adjusted rate conversion), LiquidityMath (single-sided liquidity addition via iterative proportionality approximation)
- `contracts/invariants.md` — 10 formal system invariants with code enforcement points
- `contracts/deployment.md` — Deployment procedures: CREATE3 deterministic addressing, 4 proxy patterns, core/bot/market/AMM deployment, zone config, EIP-7702 batch execution, upgrade paths
- `contracts/testing.md` — Testing infrastructure: Foundry test suite (82 files), fuzz/invariant testing, comparison testing (Solidity vs TypeScript), test helpers, mock contracts, execution scripts

## Offchain Bots
> Offchain bot systems that monitor the protocol and execute risk actions. Separate from onchain BotController docs (see `contracts/risk-bots.md`).

- `offchain-bots/overview.md` — Architecture overview: failsafe vs backend bot systems, design philosophies, comparison matrix
- `offchain-bots/failsafe-bots.md` — Failsafe bots (pendle-risks-bot-v3): pausing, liquidation, withdrawal police — RPC-only, file-cached, independent processes
- `offchain-bots/backend-triggerers.md` — Backend triggerers (pendle-backend-v3): 6 event-driven handlers detecting health, OI, withdrawal, APR drift, health-jump, and trading anomalies
- `offchain-bots/backend-responders.md` — Backend responders (pendle-backend-v3): 8 handlers executing on-chain actions — pauser, deleverager, liquidator, zone responder, CLO, suspicious trader, order cancellation
- `offchain-bots/funding-rate-bot.md` — Funding rate bot (pendle-risks-bot-v3): 3-loop architecture (detect/fetch/execute), multi-oracle validation, hourly CEX rate submission to FundingRateVerifier

## Other
- `known-addresses.yaml` — All tracked addresses (MMs, bots, internal, external)

## Dev Docs Reference
> Canonical source for protocol mechanics and architecture. Lives in the `dev-docs/` git submodule (pinned to `pendle-finance/documentation`). Path prefix: `dev-docs/docs/boros-dev-docs/`

### Core Concepts
- `dev-docs/docs/boros-dev-docs/LitePaper.mdx` — User-facing lite paper (authoritative public version)
- `dev-docs/docs/boros-dev-docs/HighLevelArchitecture.mdx` — Contract architecture: Router, MarketHub, Market, AMM, FIndex Oracle, Deposit Box, bots
- `dev-docs/docs/boros-dev-docs/FAQ.mdx` — Common questions: accounts, margin, trading, withdrawals, gas, fees
- `dev-docs/docs/boros-dev-docs/Backend/1. glossary.mdx` — Key terms: Mark Rate, Mid Rate, AMM Implied Rate, Settlement, CLO, tick, APR format (decimal fraction), account types, TIF types

### Protocol Mechanics
- `dev-docs/docs/boros-dev-docs/Mechanics/Margin.mdx` — Cross/isolated margin, initial & maintenance margin formulas, health ratio, liquidation, forced deleverage, risk management actions
- `dev-docs/docs/boros-dev-docs/Mechanics/OrderBook.mdx` — CLOB structure, tick/rate conversion, TIF types, rate bounds ("Large Rate Deviation" vs "Rate too far off"), TWAP mark rate oracle
- `dev-docs/docs/boros-dev-docs/Mechanics/Settlement.mdx` — Upfront fixed cost, floating rate payments, lazy settlement algorithm, settlement timing
- `dev-docs/docs/boros-dev-docs/Mechanics/Fees.mdx` — Taker/OTC/settlement/entrance/liquidation fees, formulas, per-asset entrance amounts, discounts

### Contracts
- `dev-docs/docs/boros-dev-docs/Contracts/Router.mdx` — Router contract reference
- `dev-docs/docs/boros-dev-docs/Contracts/MarketHub.mdx` — MarketHub contract reference (MarketAcc, cross vs isolated margin IDs)
- `dev-docs/docs/boros-dev-docs/Contracts/Market.mdx` — Market contract reference
- `dev-docs/docs/boros-dev-docs/Contracts/CustomTypes.mdx` — Custom types: OrderStatus, TimeInForce, MarketStatus, LiqSettings, FIndex

### Backend / Integration
- `dev-docs/docs/boros-dev-docs/Backend/0. overview.mdx` — SDK & API overview, base URL, NPM packages
- `dev-docs/docs/boros-dev-docs/Backend/2. agent.mdx` — Agent system: delegated EVM wallet for trading, root wallet for deposits/withdrawals, agent permissions (agents cannot withdraw), agent address whitelisting on CLO
- `dev-docs/docs/boros-dev-docs/Backend/3. api.mdx` — REST API reference
- `dev-docs/docs/boros-dev-docs/Backend/4. websocket.mdx` — WebSocket streaming
- `dev-docs/docs/boros-dev-docs/Backend/5. best-practices.mdx` — Integration best practices (bulk orders, isolated-only markets, market exit)
- `dev-docs/docs/boros-dev-docs/Backend/6. stop-orders.mdx` — Stop/TP/SL orders via Stop Order Service

## Meta
- `CLAUDE.md` — Instructions for Claude + KB conventions
- `changelog/CHANGELOG.md` — Log of significant KB updates
