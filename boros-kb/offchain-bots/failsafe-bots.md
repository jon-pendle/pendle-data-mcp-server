---
description: Failsafe bots (pendle-risks-bot-v3) — 3 independent RPC-only processes for pausing, liquidation, and withdrawal policing
last_updated: 2026-03-16
related:
  - offchain-bots/overview.md
  - contracts/risk-bots.md
  - contracts/bots-facets.md
  - contracts/funding-oracle.md
---

# Failsafe Bots — Detailed Reference

Source: `pendle-risks-bot-v3`. Three independent bots runnable as standalone processes. Design philosophy: **minimal dependencies** — RPC-only, no database, file-cached fallback for everything. The funding rate bot is also part of `pendle-risks-bot-v3` but is documented separately in `offchain-bots/funding-rate-bot.md`.

---

## Shared Infrastructure

### Data Fetching

All bots fetch user and market lists from the same two external APIs:
- **Users**: `{baseRisksUrl}/v1/dashboard/all-market-accs` → list of `MarketAcc` identifiers
- **Markets**: `{baseCoreUrl}/v1/markets` → list of active markets with metadata

Fetcher retries 3 times with exponential backoff, 5-second timeout per request.

### File-Based Caching

Every API response is cached to disk at `{API_CACHE_DIR}/users.json` and `markets.json`. On startup, bots load the cache. Fresh API data is merged (union) with cached data and written back atomically (temp file + rename). Lock files prevent concurrent writes. If the API is down, bots continue with cached data indefinitely.

### Batch Multicall

All on-chain reads use `simulateContract` multicalls with a batch size of 256 accounts per call. Multiple batches execute in parallel.

### Explorer Contract

An on-chain `Explorer` contract provides batch health checks: `getUserInfo(marketAcc)` returns `totalCash`, per-position `positionValue`, `initialMargin`, `maintMargin`, and order details. Health is computed off-chain as `totalValue / maintMargin` with safe division (inf/−inf edge cases).

### Transaction Execution

`TransactionHelper` handles gas estimation with 2× buffer, contract writes with error handling, and nonce reset on failures. All bots share this for on-chain execution.

### Alerting

Structured logging with GCP-compatible JSON in production. Custom log channels route to Discord:
- `P1_PAUSE_DELEVERAGE` — pausing events (bypass throttle)
- `P2_SUS_WITHDRAWAL` — withdrawal restrictions (bypass throttle)
- `P3_BOT_ACTIVITIES` — liquidations, routine operations (bypass throttle)
- `P1_BOTS_DEAD` — bot/oracle process failures

### Configuration

`config.yml` defines RPC endpoints (primary + secondaries), API URLs, contract addresses (`explorerAddress`, `botControllerAddress`, `marketHubAddress`, `accessManagerAddress`), and thresholds:

```
thresholds:
  health: { H_f, H_d, H_c, H_l }
  smallMMThreshold: Map<tokenId, threshold>
  minProfitLiquidation: Map<tokenId, amount>
  maxVioHealthRatio: ratio
```

Environment variables: `PRIVATE_KEY`, `API_CACHE_DIR`, plus funding-rate-specific keys.

---

## Pausing Bot

**Entry**: `src/bots/pausing/pausing.ts` | **Cycle**: 5 seconds | **Market cache refresh**: 5 minutes

### Detection

1. Fetch all active users via API (with file-cache fallback)
2. Call `PauserFacet.findRiskyUsers(allMarketAccs)` — batched at 256 per simulation call
3. The on-chain simulation identifies accounts where `totalValue + cash < totalMM × pauseThresHR` and `totalMM >= minTotalMM[tokenId]`
4. Risky users are sorted by tokenId to batch pausing per token

### Execution

For each risky account:
1. Extract `tokenId` via `MarketAccLib.unpack(marketAcc)`
2. Get all markets for that tokenId via `MarketManager`
3. Fetch current market statuses via multicall to `getMarketConfig()`
4. Filter to markets not already `PAUSED`
5. Call `BotController.pauseMarkets(marketAcc, marketIds)` via `PauserFacet`
6. Wait for confirmation, notify `P1_PAUSE_DELEVERAGE` channel with tx link

### Error Handling

Catches errors in `checkUsers()`, sleeps 5 seconds, retries. Individual pause failures logged at error level.

---

## Liquidation Bot

**Entry**: `src/bots/liquidation/liquidation.ts` | **Cycle**: 5 seconds | **User refresh**: 30 seconds | **Market cache**: 5 minutes

### Detection — Health-Weighted Priority

1. Fetch all cached users, batch-call `Explorer.getUserInfo()` (256 per batch, parallel)
2. Filter to insolvent accounts: `totalValue < maintMargin`
3. **Sort by health severity** (worst first): cross-multiplication comparison `a.totalValue × b.maintMargin < b.totalValue × a.maintMargin` avoids division

### Profit Thresholds

For each position in a liquidatable account:

| Condition | `maxVioHealthRatio` | `minProfit` |
|-----------|-------------------|-------------|
| `maintMargin < smallMMThreshold[tokenId]` | 0 (max liquidation) | 0 |
| `health < H_l` (low health) | config value | 0 (liquidate even at no profit) |
| Normal | config value | `minProfitLiquidation[tokenId]` |

### Execution — Batch Simulation + Multicall

1. For each batch of 50 accounts, for each position (sorted by |size| descending):
   - Create `LiquidationParams { marketId, ammId, violator, maxVioHealthRatio, minProfit }`
   - Simulate via `LiquidationExecutor.simulateBatchLiquidate()` — encoded as `BotMiscFacet.multicall()`
2. Filter to simulation successes
3. Execute in batches of 5 via `BotController.multicall(calls[], allowFailure: true)`
   - Gas-aware batching: each liquidation estimated individually, batched until hitting 16M gas limit
4. Decode `Liquidate` + `LiquidationExecuted` events from receipt
5. Notify `P3_BOT_ACTIVITIES` with liquidation details

### Error Handling

Simulation failures: logged, filtered out, don't block others. Execution reverts: decoded via `TryAggregateCallFailed` events, logged with error selector.

---

## Withdrawal Police Bot

**Entry**: `src/bots/withdrawal-police/withdrawal-police.ts` | **Cycle**: 15 seconds | **Market cache**: 5 minutes

### Detection

1. Fetch all active users, extract unique addresses (cross-market dedup)
2. Get all unique tokenIds from markets, create address × tokenId cartesian product
3. Batch-fetch from MarketHub (256 per batch, parallel):
   - `getPersonalCooldown(address)` → current cooldown per address
   - `getUserWithdrawalStatus(address, tokenId)` → `{ start: timestamp, unscaled: bigint }`
4. Fetch `largeWithdrawalUnscaledThreshold[tokenId]` from WithdrawalPolice contract (cached 5 min via `SingleFlightCache`)

### Violation Conditions

All three must be true:
- `withdrawalStatus.unscaled > largeWithdrawalUnscaledThreshold[tokenId]` — large withdrawal pending
- `withdrawalStatus.start + personalCooldown > now` — cooldown not expired (still in restriction window)
- `personalCooldown < restrictedCooldown` — not already restricted by backend

### Smart Re-Ban Prevention

Tracks `handledWithdrawals`: Map<address, timestamp> in memory.
- If `withdrawal.start <= lastObservedRestricted` → skip (risk team already reviewed and unbanned, don't re-ban)
- Otherwise → add to violations list
- Cache pruned each cycle: entries older than `restrictedCooldown` seconds removed

### Execution

For each violation: call `BotController.restrictLargeWithdrawal(address, tokenId)` via `WithdrawalPoliceFacet`. Notify `P2_SUS_WITHDRAWAL` with tx link.

---

## Deployment

```bash
node dist/main.js --bot=pausing
node dist/main.js --bot=liquidation
node dist/main.js --bot=withdrawal-police
node dist/main.js --bot=funding-rate   # see offchain-bots/funding-rate-bot.md
```

Each bot is fully independent — can run on separate machines with just an RPC endpoint and private key. The only shared dependency is the external API for user/market lists, which degrades gracefully to file cache.
