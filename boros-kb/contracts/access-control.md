---
description: Access control — PendleAccessController, roles, guard modifiers, agent auth, and bot permissions
last_updated: 2026-03-16
related:
  - contracts/architecture.md
  - contracts/storage-layout.md
---

# Access Control

Boros uses a layered access control system: a central permission controller for admin and bot operations, modifier-based guards on every contract boundary, and an agent delegation system for user-facing interactions.

## PendleAccessController

The `PendleAccessController` is deployed behind a `TransparentUpgradeableProxy` and extends OpenZeppelin's `AccessControlEnumerableUpgradeable`.

### Fine-grained permissions

```
mapping(address target => mapping(bytes4 selector => mapping(address caller => bool))) allowedAddresses
```

This three-dimensional mapping grants per-function permission: a specific `caller` is allowed to call a specific `selector` on a specific `target`. This is more granular than role-based access — it can restrict a bot to calling only `forceCancel()` on MarketHub without granting access to any other function.

### Key functions

| Function | Description |
|----------|-------------|
| `canCall(caller, target, selector)` | Returns `true` if `allowedAddresses[target][selector][caller]` is set, OR if the caller has `DEFAULT_ADMIN_ROLE` |
| `canDirectCallMarketHub(caller)` | Returns `true` if the caller has `_DIRECT_MARKET_HUB_ROLE` |
| `setAllowedAddress(AllowedAddressRequest[])` | Admin batch-sets permissions. Each request specifies `(target, selector, caller, allowed)` |

## Roles (PendleRolesConstants)

| Constant | Value | Purpose |
|----------|-------|---------|
| `_DIRECT_MARKET_HUB_ROLE` | `keccak256("DIRECT_MARKET_HUB_ROLE")` | Allows bypassing Router to call MarketHub directly |
| `_INITIALIZER_ROLE` | `keccak256("INITIALIZER_ROLE")` | One-time initialization permission for setup functions |
| `DEFAULT_ADMIN_ROLE` | `0x00` (from OpenZeppelin) | Full admin — can grant/revoke all roles and permissions |

## PendleRolesPlugin

All contracts that need permission checks inherit `PendleRolesPlugin`, which holds an immutable reference to the `PendleAccessController` instance (`_PERM_CONTROLLER`).

### Modifiers provided

| Modifier | Check |
|----------|-------|
| `onlyAuthorized()` | `_PERM_CONTROLLER.canCall(msg.sender, address(this), msg.sig)` — caller must have explicit `allowedAddresses` permission or `DEFAULT_ADMIN_ROLE` |
| `onlyRole(bytes32 role)` | Caller must have the specified role in the AccessController |

## Guard Modifiers by Contract

### Router modules

No explicit modifiers on Router module functions — the Router's `fallback()` handles dispatch, and individual modules assume they are called via `delegatecall` from the Router.

### MarketHub

| Modifier | Logic | Applied to |
|----------|-------|------------|
| `onlyRouter()` | `msg.sender == ROUTER \|\| canDirectCallMarketHub(msg.sender)` | `orderAndOtc()`, `bulkOrders()`, `cancel()`, `enterMarket()`, `exitMarket()`, `transferCash()`, and other core operations |
| `onlyAuthorized()` | Via PendleRolesPlugin | `forceCancel()`, `forcePurgeOobOrders()`, `forceCancelAllRiskyUser()`, `forceDeleverage()`, `liquidate()`, and admin setter functions |

The dual check in `onlyRouter()` is important: it allows the normal Router path for user transactions while also permitting privileged addresses (e.g., a keeper contract) to call MarketHub directly via `_DIRECT_MARKET_HUB_ROLE`.

### Market

| Modifier | Logic | Applied to |
|----------|-------|------------|
| `onlyMarketHub` | `msg.sender == MARKET_HUB` | All state-changing functions in `MarketOrderAndOtc`, `MarketRiskManagement`, `MarketSetAndView` |

Markets only accept calls from their MarketHub. This enforces the strict Router → MarketHub → Market call hierarchy.

### AMM

| Modifier | Logic | Applied to |
|----------|-------|------------|
| `onlyRouterWithOracleUpdate()` | Verifies Router caller and triggers oracle update | AMM swap and LP operations |

### AMMFactory

| Modifier | Logic | Applied to |
|----------|-------|------------|
| `onlyAuthorized()` | Via PendleRolesPlugin | `create()` — AMM creation is permissioned (PR #373) |

### FIndexOracle

| Modifier | Logic | Applied to |
|----------|-------|------------|
| `onlyKeeper()` | Restricted to authorized keeper addresses | Funding index updates |

### AuthBase

| Modifier | Logic | Applied to |
|----------|-------|------------|
| `onlyRelayer()` | `allowedRelayer[msg.sender]` must be true | Agent execution relay functions |

## Agent Authentication

The agent system allows users to delegate trading authority to an agent address (typically a backend service or bot) without sharing private keys. This is used heavily by the Boros UI to create a seamless CEX-like UX — users just click buttons without needing to sign wallet transactions each time. Under the hood, the UI signs operations with the user's pre-approved agent key.

### Core data structures (AuthStorage)

- `agentExpiry[Account][agentAddress]` — Unix timestamp after which the agent can no longer act for this Account. Set via `approveAgent()`, cleared via `revokeAgent()`.
- `signerNonce[signerAddress]` — Strictly increasing `uint64` nonce per signer for replay protection.
- `accManager[Account]` — Optional account manager that can approve/revoke agents on behalf of the Account holder.

### Agent execution flow (agentExecute)

1. The agent constructs the desired calldata (e.g., a `placeSingleOrder` call).
2. The agent signs an EIP-712 `PendleSignTx` struct: `{nonce, account, connectionId}`.
   - `connectionId` = hash of the intended calldata, binding the signature to the exact operation.
   - `nonce` must be strictly greater than `signerNonce[agent]` (gaps are allowed — e.g., skipping from 5 to 100 is valid).
3. A relayer (checked via `onlyRelayer()`) submits the signed transaction to `agentExecute()`.
4. `AuthBase` verifies:
   - The EIP-712 signature is valid.
   - The nonce is correct and increments it.
   - `agentExpiry[account][agent]` has not passed.
   - The `connectionId` matches the hash of the provided calldata.
5. The Router executes the calldata in the context of the specified Account.

### Account manager flow

An Account can designate an `accManager` via `setAccManager()`. The account manager can then call the `approveAgent(ApproveAgentReq)` overload directly (checked via `msg.sender == accManager`) or sign an `ApproveAgentMessage` submitted through a relayer. This enables custody solutions where the user delegates account management to a trusted entity.

## Intent System (OTC and Conditional Modules)

For OTC and conditional orders, Boros uses an intent pattern with replay protection:

1. **OTC intents**: The user (or agent) signs an EIP-712 intent describing the desired OTC trade parameters. A validator co-signs the intent to confirm it meets system requirements. The `isIntentExecuted[intentHash]` mapping prevents replay.
2. **Conditional intents**: The validator signs a condition (e.g., "mark rate crosses X"). When the condition is met, the conditional order executes. Expiry is checked to ensure stale conditions are rejected.

Both modules verify two signatures per operation (agent + validator), providing a dual-authorization guarantee.

## Bot Permissions Matrix

### MarketHub bots

These bots call MarketHub functions gated by `onlyAuthorized()`, meaning they need explicit `allowedAddresses` entries in PendleAccessController.

| Bot | Target Function | Modifier | Additional Check |
|-----|----------------|----------|-----------------|
| **Liquidation bot** | `MarketHubEntry.liquidate()` | `onlyAuthorized()` | `msg.sender == liq.root` — the liquidator must be the root address of the liquidation struct |
| **Force-cancel bot** | `MarketHubRiskManagement.forceCancel()` | `onlyAuthorized()` | — |
| **Force-cancel-all bot** | `MarketHubRiskManagement.forceCancelAllRiskyUser()` | `onlyAuthorized()` | — |
| **Purge bot** | `MarketHubRiskManagement.forcePurgeOobOrders()` | `onlyAuthorized()` | — |
| **Deleverage bot** | `MarketHubRiskManagement.forceDeleverage()` | `onlyAuthorized()` | — |

To grant a bot permission, the admin calls `PendleAccessController.setAllowedAddress()` with the bot address, MarketHub address, and the target function selector.

### BotController bots

The BotController is a diamond proxy with its own AccessController. Its facets call Market contracts directly (bypassing MarketHub) for operations that don't need cross-market settlement. See `contracts/risk-bots.md` and `contracts/bots-facets.md` for full facet reference.

| Bot | Facet | Target | On-Chain Call |
|-----|-------|--------|--------------|
| **CLO bot** | `CLOSetterFacet` | Market | `Market.setGlobalStatus()` — toggles CLO mode based on OI thresholds |
| **Liquidation executor** | `LiquidationExecutorFacet` | MarketHub | `MarketHub.liquidate()` via multicall |
| **Arbitrage executor** | `ArbitrageExecutorFacet` | Router | AMM swap + book trade to capture spread |
| **Deleverager** | `DeleveragerFacet` | MarketHub | `MarketHub.forceDeleverage()` |
| **Pauser** | `PauserFacet` | Market | `Market.setGlobalStatus(PAUSED)` |
| **Order canceller** | `OrderCancellerFacet` | MarketHub | `MarketHub.forceCancelAllRiskyUser()`, `forceCancel()` |
| **Withdrawal police** | `WithdrawalPoliceFacet` | MarketHub | `MarketHub.setPersonalCooldown()` |
| **Mark rate pusher** | `MarkRatePusher` (standalone) | Market | Pushes mark rates from offchain oracles |
| **Zone responder** | `ZoneResponder` (standalone) | Market | Adjusts liq settings, rate bounds, cooldowns per zone |
