---
description: Router → MarketHub → Market contract architecture and data flow
last_updated: 2026-03-17
related:
  - contracts/storage-layout.md
  - contracts/access-control.md
  - contracts/type-system.md
---

# Contract Architecture

Boros uses a three-layer architecture: **Router** (auth and dispatch) → **MarketHub** (cash management and cross-market margin) → **Market** (order book and positions). Every user-facing call enters through the Router, which delegates to one of seven modules, each of which calls into MarketHub, which in turn calls into the appropriate Market contract.

## Router

**Source**: `contracts/core/router/Router.sol`

The Router is a diamond-like proxy. Its `fallback()` function dispatches every incoming call by looking up `msg.sig` via `RouterFacetLib.resolveRouterFacet()`, then `delegatecall`ing the resolved module address. `RouterFacetLib` is a generated library that contains a pure mapping from every known function selector to the module address that implements it.

The constructor takes seven immutable module addresses:

| Module | Purpose |
|--------|---------|
| `TradeModule` | Order placement, cancellation, market entry/exit, cash transfers |
| `AuthModule` | Agent approval, EIP-712 signed execution, account managers |
| `AMMModule` | LP add/remove liquidity, AMM swap routing |
| `DepositModule` | DepositBox integration with optional DEX token swap |
| `OTCModule` | OTC trades with validator co-signatures |
| `ConditionalModule` | Conditional order execution with validator-signed conditions |
| `MiscModule` | Aggregated calls, simulation helpers, relayer and AMM config |

The Router itself is wrapped in a `TransparentUpgradeableProxy`, so the admin can upgrade the Router implementation (and therefore the set of module addresses) without changing the proxy address.

### TradeModule

Entry point for order placement and lifecycle management. Key functions:

- `placeSingleOrder()` / `bulkOrders()` — place one or many orders. Calls `MarketHub.orderAndOtc()` and `MarketHub.bulkOrders()` respectively.
- `bulkCancels()` — cancel existing orders via `MarketHub.cancel()`.
- `enterExitMarkets()` — manage which markets an account participates in.
- `cashTransfer()` — move cash between subaccounts.
- `subaccountTransfer()` — transfer between cross and isolated accounts.
- `vaultDeposit()` / `requestVaultWithdrawal()` / `cancelVaultWithdrawal()` — deposit and withdrawal flows.
- `vaultPayTreasury()` / `payTreasury()` — treasury fee payments.

### AuthModule

Manages the agent delegation system. An agent is an address authorized to act on behalf of an Account.

- `approveAgent(ApproveAgentMessage, signature)` — relayer-submitted approval signed by the account manager.
- `approveAgent(ApproveAgentReq)` — direct call by account manager (`msg.sender == accManager`).
- `revokeAgent()` — revoke agent access (both relayer-submitted and direct call overloads).
- `setAccManager()` — designate an account manager that can approve/revoke agents on behalf of the user.
- `agentExecute()` — core agent flow. Accepts an EIP-712 signed `PendleSignTx` containing (nonce, account, connectionId). The `connectionId` is a hash of the intended calldata, binding the signature to a specific action. Uses `AuthBase` for signature verification with strictly increasing nonces.

### AMMModule

Handles automated market making operations:

- `swapWithAmm()` — execute a swap via the AMM.
- `addLiquidityDualToAmm()` / `addLiquiditySingleCashToAmm()` — add liquidity (dual-asset or cash-only).
- `removeLiquidityDualFromAmm()` / `removeLiquiditySingleCashFromAmm()` — remove liquidity.

### DepositModule

Integrates with the external `DepositBox` contract (PR #355). Uses an intent message pattern with salt/expiry (instead of nonce) so intents can be executed out of order — this supports the flow where funds are bridged from other chains and the user signs the intent before the bridge completes.

- `depositFromBox()` — pulls tokens from the DepositBox, optionally swapping via external DEX routers before depositing the resulting tokens into MarketHub.
- `withdrawFromBox()` — withdraw tokens from a DepositBox.

Note: the swap calldata is provided by the user and executed from the DepositBox context — this introduces indirect arbitrary external calls from Router. Safe because Router only manages authentication and the transient storage account is unset during external calls.

### OTCModule

Off-chain negotiated OTC trades between two parties (maker and taker). Uses a four-party signature model (PR #366):

- **Maker/Taker**: each signs `AcceptOTCFullMessage` containing the trade terms (`OTCTradeReq`) plus their account details (accountId, cross, expiry)
- **Validator**: independent trusted party signs `ExecuteOTCTradeMessage` containing both party's message hashes. The validator runs on a secure server separate from the relayer and ensures minimum health after OTC
- **Relayer**: authorized party who submits the transaction with all signatures

Functions:
- `executeOTCTrade()` — execute the OTC trade with all four signatures. Auto-enters market for both parties. Intent hashes tracked (`isOTCTradeExecuted()`) to prevent replay.
- `setOTCTradeValidator()` — configure the single validator address.

### ConditionalModule

Conditional actions: `if CONDITION then ACTION`, where the condition can be off-chain (PR #338). Currently supports stop orders (stop-loss / take-profit).

Three-party security model:
- **Agent**: signs `PlaceConditionalActionMessage(bytes32 actionHash)` where `actionHash` is the hash of the conditional action struct (e.g., `ConditionalOrder`)
- **Validator**: independent whitelisted party who signs to certify conditions were met. Validator message is optional — some conditions can be validated fully on-chain
- **Backend**: monitors conditions, submits proofs to validator, sends transactions through authorized relayer

Functions:
- `executeConditionalOrder()` — execute when condition is met. Validator message can supply info not available when agent signed (e.g., `desiredMatchRate` from mid rate at execution time).
- `setConditionalValidator()` / `isConditionalValidator()` — manage whitelisted validators.
- `isActionExecuted()` — replay protection.

### MiscModule

Aggregation and configuration utilities:

- `tryAggregate()` — batch multiple calls with optional failure tolerance.
- `batchSimulate()` / `batchRevert()` — simulate operations and revert with results (for previewing outcomes without state changes).
- `setAllowedRelayer()` — configure relayer whitelist.
- `setAMMIdToAcc()` — map AMM IDs to their MarketAcc accounts.
- `setNumTicksToTryAtOnce()` / `setMaxIterationAndEps()` — configure order matching parameters.
- `approveMarketHubInf()` — infinite token approval from Router to MarketHub.

## MarketHub

**Source**: `contracts/core/markethub/`

MarketHub manages cash balances and enforces cross-market margin requirements. It is the single point of contact between the Router and all Market contracts.

### Proxy structure

`MarketHubEntry` is itself a proxy that delegates to `MarketHubRiskManagement` for calls not explicitly defined on MarketHubEntry. The most commonly used functions are placed directly on MarketHubEntry (orderAndOtc, bulkOrders, cancel, liquidate, deposit, withdrawal, cash transfer, market entry/exit) to avoid the extra proxy hop. Less frequently called selectors fall through to `_MARKET_HUB_RISK_MANAGEMENT` (forceCancel, forceDeleverage, forcePurgeOobOrders, forceCancelAllRiskyUser, and admin setters).

### Storage (Storage.sol base)

Key state mappings (see `contracts/storage-layout.md` for full layout):

- `acc[MarketAcc]` → `MarketAccData` — per-account cash balance and entered markets list.
- `cashFeeData[TokenId]` → `CashFeeData` — treasury cash, market entrance fee, min cash thresholds.
- `_tokenData[]` — array of `TokenData{token, scalingFactor}`.
- `_marketIdToAddress[MarketId]` — resolved Market contract addresses.
- `_strictMarkets` — array of markets requiring strict IM checks, with `_strictMarketsFilter` as a `uint128` bloom filter for fast pre-screening.

### MarginManager

Runs the settlement loop across all markets an account has entered:

- **Strict vs weak IM checks**: strict initial margin is enforced for markets in `_strictMarkets` (fast-checked via the `_strictMarketsFilter` bloom filter). Weak IM applies otherwise.
- **critHR health checks**: determines liquidation eligibility.

### Access control

- `onlyRouter()` modifier gates most state-changing functions, but also allows callers with `_DIRECT_MARKET_HUB_ROLE`.
- Immutables: `MARKET_FACTORY`, `ROUTER`, `TREASURY`, `MAX_ENTERED_MARKETS`.

### Deterministic market addresses

Market contract addresses are derived deterministically:

```
address market = CreateCompute.compute(MARKET_FACTORY, marketId)
```

This avoids storage lookups for known market IDs.

## Market

**Source**: `contracts/core/market/`

Each Market contract manages a single order book and the positions within it.

### Proxy structure

`MarketEntry` dispatches to three facets based on the function selector, ordered by call frequency:

- `MarketOrderAndOtc` — matched first for `orderAndOtc` selector. The hot path — order matching and OTC settlement on every trade.
- `MarketRiskManagement` — matched for `forceDeleverage` and `forcePurgeOobOrders` selectors. Called only during risk events.
- `MarketSetAndView` — default fallback for all other selectors. Admin configuration and read-only views, called least frequently.

### Versioning

Each Market facet exposes a `VERSION` constant (PR #353) for tracking deployed versions during upgrades.

### Access control

All state-changing functions are gated by the `onlyMarketHub` modifier. Only MarketHub can mutate Market state.

### Core execution flow

When MarketHub calls `IMarket.orderAndOtc()`, the execution follows this sequence:

1. **Read** — load current order book and account state.
2. **Settle** — settle any pending funding index updates for affected accounts.
3. **Cancel** — process any pending cancellations.
4. **Match** — match the incoming order against resting orders on the book.
5. **OTC** — process any OTC component of the trade.
6. **Margin check** — verify the account still meets margin requirements.
7. **Write** — persist all state changes.

## Data flow summary

```
User / Agent
    │
    ▼
Router (auth + selector dispatch)
    │  delegatecall to module
    ▼
MarketHub (cash balances + cross-market margin)
    │  call to deterministic market address
    ▼
Market (order book + position management)
```

Every state-changing path follows this top-down flow. Markets never call back into MarketHub or Router. MarketHub never calls back into Router. This strict call hierarchy simplifies reasoning about reentrancy and state consistency.
