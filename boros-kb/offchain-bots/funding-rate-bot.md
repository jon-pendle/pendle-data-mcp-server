---
description: Offchain funding rate bot (pendle-risks-bot-v3) — fetches CEX funding rates from 3 oracle sources and submits to FundingRateVerifier on-chain
last_updated: 2026-03-17
related:
  - contracts/funding-oracle.md
  - offchain-bots/failsafe-bots.md
  - offchain-bots/overview.md
---

# Offchain Funding Rate Bot

**Source**: `pendle-risks-bot-v3/src/bots/funding-rate/`

**Entry**: `src/bots/funding-rate/funding-rate.ts` | **Three parallel loops** | **HTTP server** for early updates

The most complex failsafe bot. Pushes CEX funding rates on-chain every hour. It calls **FundingRateVerifier** (not FIndexOracle directly) — see `contracts/funding-oracle.md` for the full on-chain pipeline.

```
Offchain Funding Rate Bot
        │
        │  calls updateWithChainlink / updateWithChaosLabs / updateWithPendle
        ▼
FundingRateVerifier (one per market)
        │
        │  validates report, then calls updateFloatingIndex
        ▼
FIndexOracle (one per market)
        │
        │  computes new FIndex, then calls updateFIndex
        ▼
Market
```

---

## Three Loops

| Loop | Interval | Purpose |
|------|----------|---------|
| `detectLoop` | 60s | Discover new markets and verifier contracts |
| `fetchLoop` | 3s (near hour) / 60s (otherwise) | Fetch funding rate data from 3 oracles |
| `executeLoop` | 0.5s | Execute queued updates at target time |

### Detect Loop — Market & Verifier Discovery

1. Fetch MarketFactory from MarketHub, compute market addresses from factory nonce
2. Multicall (100-contract chunks): `market.descriptor()` → latest funding time, maturity; `market.getMarketConfig()` → fIndexOracle address
3. Skip matured markets (`latestFTime === maturity`)
4. For each oracle: `oracle.keeper()` → verifier address
5. For each verifier: check permissions, read `CHAIN_LINK_FEED_ID`, `CHAOS_LABS_UPDATE_TYPE_HASH`, `PENDLE_ORACLE`

### Fetch Loop

1. Multicall batch: descriptor, symbol, config, markRate, nextUpdateTime, balance, oracle IDs, period
2. Skip if: updated recently (< 300s), matured, interval mismatch with CEX data
3. **Critical validation**: funding timestamp must equal `nextUpdateTime`
4. **Rate deviation check**: `|markRate - annualizedFundingRate| <= maxDeviation`
5. Fetch all 3 oracles in parallel
6. **Exact match filter**: `equalFundingRate(fundingData, oracleReport)` — only reports matching the expected rate pass
7. Queue valid updates with targetTime

### Execute Loop

1. Check if within execute window or past max delay
2. Estimate gas per report (per oracle type: `updateWithChainlink(report)`, `updateWithChaosLabs(updateId)`, `updateWithPendle()`)
3. Group into batches respecting `MAX_BATCH_GAS = 16,000,000`
4. Sleep until targetTime if needed
5. Call `fundingRateMulticall.tryAggregate(false, calls)` with 2× gas buffer
6. Decode `TryAggregateCallSucceeded` / `TryAggregateCallFailed` events
7. If any report succeeded for an update: mark done, log with source
8. If all failed: alert `P1_BOTS_DEAD`

---

## `@pendle/funding-rate-feeds` package

**Source**: `/workspace/funding-rate-feeds`

A shared library that the bot depends on for two things:

1. **CEX wrappers**: Unified fetchers for 7 exchanges — Binance, Bybit, OKX, Gate, Bitget, Hyperliquid, Lighter. Each provides `getFundingRate()` (historical) and `getRealtimeFundingRate()` variants, returning a common `FundingRateData` type (`fundingRate: bigint`, `fundingTimestamp`, `epochDuration`). Built-in per-exchange caching (`SingleFlightCache`) and retry logic (`retryUntilFresh()`).

2. **Feed constants**: Pre-configured `FundingRateFeed` objects mapping each market to its exchange symbol and oracle identifiers (`chainlinkFeed`, `chaosLabsFeed`, `pendleOracle`). The bot uses `findFundingRateFeed()` to look up the correct feed from on-chain oracle addresses discovered during the detect loop.

The package also exports `buildFundingRateFetcher()` (creates a cached fetcher with configurable retry per exchange) and `equalFundingRate()` (compares CEX ground truth against oracle reports).

---

## Three Oracle Sources

| Source | Method | Auth |
|--------|--------|------|
| **Chainlink** | HTTP API with `feedId` from verifier | User ID + secret (env vars) |
| **Chaos Labs** | On-chain call to risk oracle contract | None (public) |
| **Pendle** | Direct on-chain call to oracle | None (public) |

All fetched with 3-second timeout, 2 retry attempts. Chainlink + Chaos Labs fetched together (shuffled to ensure equal usage across oracles), Pendle fetched separately.

All oracle reports are compared against the **ground truth funding rate from CEX**. The bot requires at least one oracle source to match the CEX rate via `equalFundingRate()`. If an oracle report disagrees with the CEX ground truth, it is discarded. This prevents a single compromised oracle from pushing a bad rate through the verifier.

---

## Execution Timing

| Market type | Target execution | After hour boundary |
|-------------|-----------------|---------------------|
| Gate markets | 120 seconds | +2 min |
| All others | 30 seconds | +30s |

- fetchLoop sleeps 3s when within 120s of hour start, 60s otherwise
- executeLoop wakes 3s before targetTime (`EXECUTE_WINDOW_s = 3`)
- Force execute after `MAX_FUNDING_UPDATE_DELAY_s = 30` past target

---

## Early Update HTTP Endpoint

Fastify server exposes `POST /allow-early-update` (auth token protected). The backend responder can signal that updates should be submitted early (before maxDelayTime). Accepts: `{ timestamp, disallowedMarketIds? }`.

---

## Oracle Fallback

If no oracle responds for 90 seconds (`NO_ORACLE_WARNING_s`), alerts are sent. Individual oracle failures are logged but don't block — the bot uses whichever oracles return valid, matching data.

---

## Full Call Chain Example

A typical hourly funding rate update:

```
1. Bot detect loop discovers Market #5 → FIndexOracle(0x...) → keeper = FundingRateVerifier(0x...)
2. Bot fetch loop reads Chainlink/ChaosLabs/Pendle at hour boundary
3. All three report fundingRate = 0.0012, fundingTimestamp = 1710680400
4. Bot execute loop calls:
     FundingRateVerifier(0x...).updateWithChainlink(chainlinkReport)
5. ChainlinkVerifierLib validates: feedId ✓, epochDuration == period ✓, sequential ✓
6. FundingRateVerifier forwards:
     FIndexOracle(0x...).updateFloatingIndex(0.0012, 1710680400)
7. FIndexOracle validates: epoch arrived ✓, not matured ✓, correct timestamp ✓
8. FIndexOracle computes new FIndex, calls:
     Market(0x...).updateFIndex(newIndex)
9. Market advances latestFTag — all subsequent user interactions settle against new FIndex
```
