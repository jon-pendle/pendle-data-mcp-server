---
description: Risk bot system — BotController diamond proxy, all facets, MarkRatePusher, and math libraries
last_updated: 2026-03-18
related:
  - contracts/bots-facets.md
  - contracts/access-control.md
  - contracts/liquidation.md
  - contracts/invariants.md
  - contracts/funding-oracle.md
---

# Risk Bots

Boros bots are permissioned contracts that maintain system health: executing liquidations, cancelling risky orders, managing OI caps, pushing mark rates, and responding to crises. Bot addresses are listed in `known-addresses.yaml` at the KB root.

---

## Bot Security Design Principles

Two principles minimise what a compromised bot can do:

1. **Do as much on-chain as possible.** The offchain bot should only _trigger_ actions — all critical calculations happen inside the contract. Liquidation is the prime example: the bot just calls `liquidate(violator, size)` and the contract computes sizing, incentive, health checks, and margin validation entirely on-chain. A compromised bot cannot fabricate incorrect liquidation parameters because the contract re-derives everything from on-chain state. This also enables **independent failsafe bots** that depend only on RPCs — no backend database required. Because all state and logic lives on-chain, a simple process with just an RPC endpoint and private key can replicate the full bot functionality (see `offchain-bots/failsafe-bots.md`).

2. **Pre-set configs, not arbitrary values.** For bots that change protocol settings (e.g., zone response), the new configuration is stored on the contract first (by admin), and the bot can only switch _to_ that pre-set config. ZoneResponder is the prime example: admin calls `setRedLiqSettings(marketId, settings)` to store the red-zone config on-chain, then the bot can only call `increaseLiquidationIncentive(marketId)` which applies the stored value. The bot never passes arbitrary parameters — it can only toggle between pre-approved red/white configurations.

---

## BotController Architecture

**Source**: `contracts/bots/base/BotController.sol`

The bot system uses a **diamond proxy pattern**. `BotController` extends OpenZeppelin's `Proxy` and overrides `_implementation()` to look up `msg.sig` in a `mapping(bytes4 => address)` to find the responsible facet, then `delegatecall`s it.

**Storage**: `BotControllerStorage.sol` uses EIP-7201 namespaced storage (`GeneratedStorageSlots.BOT_CONTROLLER_STORAGE_LOCATION`) to hold the selector-to-facet mapping. Facets are registered via `MiscFacet.setSelectorToFacets()`.

**Shared base**: All facets inherit from `Base.sol`, which provides:
- `onlyAuthorized` — permission check via `PendleAccessController`
- `onlySimulation` — `tx.origin == address(0)` guard for off-chain RPC simulation calls
- Lazy market cache (`MarketCache`): market address, tokenId, maturity, tickStep per MarketId
- Helper methods: `swapWithAMM()`, `swapWithBook()` (FOK orders with worst-case rates), `cashTransfer()` between cross/isolated accounts, `enterMarket()`, `getActiveMarkets()`
- `numTicksToTryAtOnce` config for tick sweep depth — stored in common BotController storage (shared across all facets)

---

## Facet Inventory

### Execution facets

| Facet | Entry point | Purpose |
|-------|-------------|---------|
| **LiquidationExecutorFacet** | `executeLiquidation(params)` | Liquidate violator → optionally hedge via AMM and/or book → validate profit |
| **ArbitrageExecutorFacet** | `executeArbitrage(params)` | Exploit AMM vs book mispricing → sweep ticks → profit |

### Risk facets

| Facet | Entry points | Purpose |
|-------|--------------|---------|
| **OrderCancellerFacet** | `forcePurgeOobOrders()`, `forceCancelAllRiskyUser()`, `forceCancelAllHealthJump()` | Out-of-bound purge, risky-user cancel, and proactive health-jump cancel |
| **DeleveragerFacet** | `manualDeleverage()`, `deleverageToHealth()` | Last-resort position transfer with bad debt handling |
| **CLOSetterFacet** | `toggleCLO()`, `setCLOThreshold()` | Toggle Close-Only mode based on OI thresholds |
| **PauserFacet** | `pauseMarkets()`, `findRiskyUsers()` | Pause entire markets when large accounts become dangerously risky |
| **WithdrawalPoliceFacet** | `restrictWithdrawalUnconditionally()`, `restrictLargeWithdrawal()`, `disallowWithdrawal()`, `resetPersonalCooldown()` | Withdrawal rate-limiting and emergency freezes |

### Infrastructure

| Facet | Entry points | Purpose |
|-------|--------------|---------|
| **MiscFacet** | `deposit()`, `withdraw()`, `setSelectorToFacets()`, `multicall()` | Fund management, facet registration, batch operations |

### Standalone contracts (not facets)

| Contract | Entry point | Purpose |
|----------|-------------|---------|
| **MarkRatePusher** | `pushMarkRate(marketId, ammId)` | Push mark rate toward AMM implied rate using dual-forwarder self-crossing |
| **ZoneResponder** | `increaseGlobalCooldown()`, `increaseLiquidationIncentive()`, `decreaseRateDeviationBound()`, `turnOnCLO()`, `turnOnStrictHealthCheck()` + white-zone resets | Red/white zone crisis response system with 5 configurable levers |

---

## Math Libraries

Located in `contracts/bots/math/`:

| Library | Used by | Purpose |
|---------|---------|---------|
| **LiquidationMathLib** | LiquidationExecutorFacet | Compute liquidation size, AMM/book hedge sizes, expected profit |
| **ArbitrageMathLib** | ArbitrageExecutorFacet | Compute optimal arb size across tick range, fee-adjusted profit |
| **SettleSimMathLib** | OrderCancellerFacet, DeleveragerFacet | Simulate settlement with projected FIndex to predict future health |
| **SwapBoundMathLib** | Multiple facets | Rate bound calculation and swap size validation |

---

## Permission Model

All facets use `onlyAuthorized` from `PendleRolesPlugin`:
```
PendleAccessController.canCall(msg.sender, address(this), msg.sig)
```
Each bot address must be whitelisted for the **specific selectors** it needs on the BotController. `DEFAULT_ADMIN_ROLE` holders bypass all checks.

Exception: `onlySimulation` functions (`findHealthJumpOrders`, `findRiskyUsers`) are callable only via `eth_call` with `tx.origin == address(0)` — used for off-chain discovery.

Special case for liquidation: `MarketHubEntry.liquidate()` requires `liq.root() == msg.sender` — the BotController itself is a Boros user with its own deposited collateral, and it acts as the liquidator account directly.

---

## MarkRatePusher — Standalone

**Source**: `contracts/bots/pusher/MarkRatePusher.sol`

Uses two `CallForwarder` proxy contracts (independent trading accounts) to push the on-chain mark rate toward the AMM's implied rate without self-matching detection.

### Why Two Forwarders?

The Market has self-trade prevention (`MarketSelfSwap` error): if a user's taker order matches their own resting maker order, the trade is blocked. The MarkRatePusher needs to place a maker order and then match it — effectively a self-trade. Using two separate forwarder accounts (each with their own `MarketAcc`) circumvents the self-trade check, because the maker (forwarder1) and taker (forwarder2) are different accounts.

**Flow** (`pushMarkRate()`):
1. Fetch AMM implied rate and current mark rate (last traded rate on book)
2. If `|impliedRate - markRate| <= maxDelta`, skip (no push needed)
3. If rate needs pushing **down**: place LONG at target tick via forwarder1. If no external match, place SHORT via forwarder2 to cross own order
4. If rate needs pushing **up**: place SHORT at target tick via forwarder1, then LONG via forwarder2
5. The matched trade updates the implied rate / mark rate

Orders are minimal size (1-unit) — the goal is to establish a trade at the target rate, not to take meaningful positions.

---

## ZoneResponder — Crisis/Recovery

**Source**: `contracts/bots/risk/ZoneResponder.sol`

ZoneResponder is a standalone contract (not a BotController facet). It inherits `PendleRolesPlugin` directly for access control. Implements a two-zone emergency response system with pre-configured parameter sets:

**Red zone** (crisis): Tighten 5 independent levers —
1. `increaseGlobalCooldown()` — slow withdrawals
2. `increaseLiquidationIncentive(marketId)` — boost LiqSettings.base/slope to attract liquidators
3. `decreaseRateDeviationBound(marketId)` — tighten acceptable rate ranges
4. `turnOnCLO(marketId)` — prevent new position growth
5. `turnOnStrictHealthCheck(marketId)` — enforce enhanced margin validation

**White zone** (recovery): Reset each lever to pre-configured normal values.

Each lever has independently configurable red and white zone targets:
- `_redGlobalCooldown` / `_whiteGlobalCooldown`
- `_redLiqSettings[marketId]` / `_whiteLiqSettings[marketId]`
- `_redDeviationConfig[marketId]` / `_whiteDeviationConfig[marketId]`

Guard rails prevent double-activation (`ZoneGlobalCooldownAlreadyIncreased`) and validate config (`ZoneInvalidLiqSettings`, `ZoneInvalidRateDeviationConfig`).

---

## Quick Reference: What Calls What

```
BotController (diamond proxy)
  ├── LiquidationExecutorFacet → marketHub.liquidate() + router.swapWithAMM/Book
  ├── ArbitrageExecutorFacet   → router.swapWithBook() + router.swapWithAMM()
  ├── OrderCancellerFacet      → marketHub.forcePurgeOobOrders(), forceCancelAllRiskyUser(), forceCancel()
  ├── DeleveragerFacet         → marketHub.forceDeleverage()
  ├── CLOSetterFacet           → IMarket.setGlobalStatus()
  ├── PauserFacet              → IMarket.setGlobalStatus(PAUSED)
  ├── WithdrawalPoliceFacet    → marketHub.setPersonalCooldown()
  └── MiscFacet                → admin + fund management

MarkRatePusher (standalone)
  ├── forwarder1               → router.placeSingleOrder()
  └── forwarder2               → router.placeSingleOrder()

ZoneResponder (standalone)
  └── marketHub.setGlobalCooldown(), IMarket.setGlobalLiquidationSettings(), IMarket.setGlobalRateBoundConfig()
```

> For FIndexOracle and the funding rate pipeline (offchain bot → FundingRateVerifier → FIndexOracle → Market), see `contracts/funding-oracle.md`.

See `contracts/bots-facets.md` for detailed per-facet documentation (parameters, logic flow, error cases).
