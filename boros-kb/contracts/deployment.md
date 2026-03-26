---
description: Contract deployment order, proxy patterns, CREATE3 deterministic addressing, market creation, AMM seeding, bot setup, zone config, and upgrade paths
last_updated: 2026-03-17
related:
  - contracts/architecture.md
  - contracts/access-control.md
  - contracts/amm.md
  - contracts/risk-bots.md
  - contracts/cross-chain.md
---

# Deployment

Source: `contracts-v3-deployment/`. Hardhat + viem deployment framework targeting Arbitrum (chainId 42161). Uses CREATE3 for deterministic addresses, EIP-7702 for batch execution, and four distinct proxy patterns.

---

## Proxy Patterns

### Transparent Proxy (ERC1967)

Standard OpenZeppelin pattern. ProxyAdmin stored at ERC1967 admin slot. Used for: AccessController, MarketFactory, MarketHub, AdminModule, Explorer, ZoneResponder, MarkRatePusher, DepositBoxFactory.

Upgrade: `proxyAdmin.upgradeAndCall(proxy, newImpl, calldata)`

### Diamond Pattern (Dynamic Facet Routing)

BotController uses this. Function selectors mapped to facet addresses in a storage mapping. No single implementation — calls dispatch to the appropriate facet.

Upgrade: `botController.setSelectorToFacets([[{facet, selectors}]])`

### Beacon Proxy

Used for DepositBox instances. All boxes share one UpgradeableBeacon that points to a single implementation. Upgrading the beacon upgrades every box atomically.

Upgrade: `beacon.upgradeTo(newImpl)`

### Market Facet Pattern

Markets use a diamond-like approach: `MarketEntry` dispatches to 4 facets (MarketOrderAndOtc, MarketRiskManagement, MarketSetAndView, MarketOffView). Facet addresses are updatable by admin.

### CREATE3 Deterministic Addressing

Uses CreateX (`0xba5Ed099633D3B314e4D5F7bdc1305d3c28ba5Ed`). Salt format (32 bytes):

```
[0:20]  deployer address
[20]    chain redeploy protection flag (0x00 or 0x01)
[21:32] randomness (11 bytes)
```

Guard salt with chain protection: `keccak256(abi.encode(deployer, chainId, salt))`. Allows pre-computing addresses before deployment.

---

## Phase 1: Core Protocol Deployment

Script: `scripts/deploy_core/deploy_core.ts`

### Step 1: PendleAccessController (CREATE3)

```
Address: 0x2080808080262c1706598c9DBDD3a0cD3601e5ea
initialize(admin)
grantRole(INITIALIZER_ROLE, deployer)
```

Deployed as TransparentUpgradeableProxy via CREATE3. All subsequent contracts reference this for authorization.

### Step 2: Router (CREATE3)

```
Address: 0x8080808080daB95eFED788a9214e400ba552DEf6
```

Modules deployed first as standalone contracts (AMMModule, AuthModule, MiscModule, TradeModule, DepositModule, OTCModule, ConditionalModule), then the Router proxy is deployed with all module addresses as immutable constructor params. `RouterFacetLib` is a generated library with embedded module addresses.

Post-deploy: `initialize('Pendle Boros Router', '1.0', 5)`

### Step 3: AMMFactory (Transparent Proxy)

Requires two "creation code contracts" deployed first — wraps PositiveAMM and NegativeAMM bytecode for later instantiation via `deployCreationCode()`.

### Step 4: MarketFactory (CREATE3)

```
Address: 0x3080808080Ee6a795c1a6Ff388195Aa5F11ECeE0
```

Market implementation facets deployed first: MarketSetAndView, MarketOrderAndOtc, MarketRiskManagement, MarketEntry. `INITIALIZER_ROLE` granted to MarketFactory address (it needs to call init functions on newly created markets).

### Step 5: MarketHub (CREATE3)

```
Address: 0x1080808080f145b14228443212e62447C112ADaD
constructor(accessController, marketFactory, router, treasury, maxEnteredMarkets=10)
```

MarketHubRiskManagement deployed as a separate contract (referenced by MarketHubEntry). Initialization: `initialize(60 * 3600)` (3-hour timestamp threshold).

### Step 6: AdminModule (Transparent Proxy)

```
constructor(ammFactory, marketHub, accessController)
```

Granted `DIRECT_MARKET_HUB_ROLE` to call MarketHub directly (bypassing Router).

### Step 7: Explorer (CREATE3)

```
Address: 0x40808080804111c374c8f1dc78b13fb57df93197
constructor(accessController, marketFactory, marketHub, router)
```

After each step, `env.writeToFile()` persists all addresses to `deployments/core.json`.

---

## Phase 2: Bot System Deployment

Script: `scripts/deploy_core/deploy_bots.ts`

The bot system has its **own AccessController**, separate from the core protocol's.

### Bot AccessController (CREATE3)

```
Address: 0xB080808080d11B4132e793a8249cb15d00B5dB2C
```

### 8 Facets

Each deployed with `(botAccessController, router, marketHub)`:

| Facet | Address |
|-------|---------|
| MiscFacet | `0xe560EB6b...` |
| ArbitrageExecutorFacet | `0xBAF13F14...` |
| LiquidationExecutorFacet | `0x103E9945...` |
| CLOSetterFacet | `0x48993212...` |
| DeleveragerFacet | `0x0AbF9170...` |
| OrderCancellerFacet | `0xB2Dba49b...` |
| PauserFacet | `0xF155E6Bc...` |
| WithdrawalPoliceFacet | `0xE0d256De...` |

### BotController (CREATE3 Diamond)

```
Address: 0xB180808080e0544f77261CDeCc9a2540104682F6
constructor(miscFacet)
```

Constructed with only MiscFacet. Remaining facets registered via single `setSelectorToFacets()` call — extracts all function selectors from each facet's ABI and maps them.

### Standalone Contracts

**ZoneResponder** (Transparent Proxy + CREATE3):
```
Address: 0xB28080808028fB733E0Bb6bDBd36f556f1185f3f
constructor(botAccessController, marketHub)
```

**MarkRatePusher** (Transparent Proxy + CREATE3):
```
Address: 0xB380808080966f09E3d26cc32756D56fd454930D
constructor(botAccessController, router, marketHub)
initialize(parseEther('0.0005'))  // mark rate threshold
```

### Post-Deploy Bot Config

```
deleverager.setDeleverageThresHR(0.7e18)
orderCanceller.setHealthJumpCancelThresHR(0.95e18)
```

Output: `deployments/bots.json`

---

## Phase 3: Deposit Box Deployment

Script: `scripts/deploy_core/deploy_deposit_box.ts`

Three-tier beacon proxy:

1. **BeaconProxy Creation Code** (CREATE2) — wraps BeaconProxy bytecode
2. **DepositBox Implementation** (CREATE3) — the logic contract
3. **UpgradeableBeacon** (CREATE3) at `0xDEB0BEA8882Baf5adb3B24b55D80e5610206C99D` — points to implementation
4. **DepositBoxFactory Implementation** (CREATE3) — knows beacon + creation code
5. **DepositBoxFactory Proxy** (Transparent + CREATE3) at `0xDEB0FAC888C33E3E7394c095FE3c4E3de760E12c`

All DepositBox instances share the beacon. Upgrading the beacon upgrades every box.

---

## Phase 4: Market Deployment

Script: `scripts/deploy_market/1.deploy_markets.ts`

### Market Address Determinism

Market addresses are nonce-based from MarketFactory (not CREATE3):

```
marketAddress = getContractAddress({ from: marketFactory, nonce: marketId })
```

### Oracle Deployment

Per market, a sub-deployer deploys:
1. **FundingRateVerifier** — verifies funding rate reports from 3 oracle sources (Chainlink feed ID, ChaosLabs update type hash, Pendle oracle)
2. **FIndexOracle** — stores funding rate epochs, configured with `updatePeriod` (typically 3600s) and `maxUpdateDelay` (typically 600s)

### Market Creation Batch

Uses EIP-7702 batch execution. Per market:

```
marketFactory.create(name, symbol, isolated, maturity, tokenId, tickStep, iTickThresh, config)
zoneResponder.setRedLiqSettings(marketId, { base: 0.5, slope: 0, feeRate: 0.0005 })
zoneResponder.setWhiteLiqSettings(marketId, { base: 0.25, slope: 0.5, feeRate: 0.0005 })
zoneResponder.setRedRateDeviationConfig(marketId, { maxMD: 0.1, CO: 0.06, slopes: (1.025, 0.975) })
zoneResponder.setWhiteRateDeviationConfig(marketId, { maxMD: 0.3, CO: 0.1, slopes: (1.05, 0.95) })
```

Markets are created in `CLO` (Closing-Only) status initially.

### Typical Market Config Values

```
maxOpenOrders: 100
takerFee: 0.05% (5e14)
otcFee: 0.05%
liqSettings: { base: 25%, slope: 50%, feeRate: 0.05% }
kIM: ~0.476 (47.6%)
kMM: ~0.333 (33.3%)
tThresh: 259200 (3 days)
maxRateDeviationFactorBase1e4: 5000 (50%)
closingOrderBoundBase1e4: 1000 (10%)
loUpperSlopeBase1e4: 10500 (5% above mark)
loLowerSlopeBase1e4: 9500 (5% below mark)
```

---

## Phase 5: AMM Deployment & Seeding

Script: `scripts/deploy_market/6.deploy_amms.ts`

AMM addresses are nonce-based from AMMFactory.

### Per-Market Batch

```
market.setGlobalStatus(GOOD)
market.setPersonalExemptCLOCheck(seederAcc, true)
market.setPersonalExemptCLOCheck(ammAcc, true)
adminModule.newAMM(isPositive, createParams, seedParams)
```

**Seed parameters** from TOML config: `minAbsRate`, `maxAbsRate`, `initialAbsRate`, `initialSize`, `flipLiquidity`, `initialCash`, `cutOffTimestamp = maturity - updatePeriod - 300`.

**Seeder safety check**: `absLiquidationRate >= maxAbsRate / 2` must hold — prevents the seeder from being immediately liquidatable.

---

## Phase 6: Bot Market Entry

Script: `scripts/deploy_market/5.enter_market_bot.ts`

BotController enters each market via `enterMarketIsolated(marketId)`.

MarkRatePusher uses 2 forwarder accounts. Per market, per forwarder:
1. `cashTransfer(forwarderIndex, marketId, minCash)` — deposit minimum
2. `enterMarket(forwarderIndex, marketId)` — enter market
3. `cashTransfer(forwarderIndex, marketId, -(excess))` — withdraw excess (keep only entrance fee + buffer)

---

## Phase 7: CLO & Zone Configuration

### CLO Thresholds (`8.set_clo_threshold.ts`)

Per market:
```
lowerThres = hardOICap × 93%   // Turn OFF CLO below this
upperThres = hardOICap × 95%   // Turn ON CLO above this
```

### CLO Exemptions (`7.exempt_clo.ts`)

Exempted accounts per market: seeder, BotController, 2 forwarders, 8 maker addresses. Both cross-market and market-specific accounts exempted via `setPersonalExemptCLOCheck(acc, true)`.

---

## EIP-7702 Batch Execution

File: `utils/helpers/batch.ts`

The deployer EOA has EIP-7702 delegation to an `I7702Account` implementation. This enables batching multiple calls in a single transaction:

```typescript
type BatchCall = { target: Address, value: bigint, data: Hex }

executeBatch(deployer, calls[])
```

Used extensively for market creation (market + zone config in one tx) and AMM seeding (status change + exemptions + AMM creation in one tx).

---

## Market Registry

File: `scripts/all_markets.ts`

100+ deployed markets across assets and exchanges:
- **Assets**: BTC, ETH, BNB, HYPE, USDT
- **Exchanges**: Binance, Hyperliquid, Gate, OKX
- **Naming**: `[exchange]-[symbol]-[maturity YYMMDD]`

Example: `btc/hyperliquid-btc-251128` → Hyperliquid BTC market expiring Nov 28, 2025.

### Deployment State Files

```
deployments/
├── core.json              # Core protocol addresses
├── bots.json              # Bot system addresses
├── chainlink.json         # Chainlink oracle config
├── chaosLabs.json         # ChaosLabs oracle config
├── portal.json            # Cross-chain portal config
├── btc/
│   └── hyperliquid-btc-251128/
│       ├── market.json        # Market address, config, fees, margins
│       ├── positive-amm.json  # AMM parameters and state
│       └── verifier.json      # Funding rate verifier config
└── ...
```

---

## Upgrade Procedures

16 upgrade scripts in `scripts/upgrade/`.

### Router Upgrade

1. Redeploy all 7 module contracts
2. Deploy new Router implementation referencing new modules
3. `upgradeTransparentProxy(router, newImpl, data)`

Modules are immutable references — changing any module requires a new Router implementation.

### Market Implementation Upgrade

1. Redeploy facets: MarketSetAndView, MarketOrderAndOtc, MarketRiskManagement, MarketEntry
2. Update MarketFactory to reference new facets
3. Existing markets automatically use new facets (reference pattern, not per-market upgrade)

### Bot Facet Upgrade

1. Deploy new facet contracts
2. Extract function selectors from ABI
3. `botController.setSelectorToFacets([[{facet, selectors}]])` — single tx remaps all selectors

No reinitialization needed — diamond storage persists across facet upgrades.

### MarketHub Upgrade

1. Deploy new MarketHubEntry implementation
2. Optionally deploy new MarketHubRiskManagement
3. `upgradeTransparentProxy(marketHub, newImpl, data)`
4. Storage layout must be preserved (EIP-7201 namespaced storage)

### DepositBox Upgrade

1. Deploy new DepositBox implementation
2. `beacon.upgradeTo(newImpl)` — all boxes upgraded atomically

### Other Components

AccessController, AdminModule, Explorer, AMMFactory, DepositBoxFactory, ZoneResponder, MarkRatePusher — all use transparent proxy, upgraded via `upgradeTransparentProxy()`.

---

## Deployment Checklist

### Initial Deploy
1. Deploy core (AccessController → Router → AMMFactory → MarketFactory → MarketHub → AdminModule → Explorer)
2. Deploy bots (Bot AccessController → 8 facets → BotController → ZoneResponder → MarkRatePusher)
3. Deploy deposit infrastructure (DepositBox beacon + factory)
4. Deploy cross-chain portal (spoke chains only, see `cross-chain.md`)
5. Configure permissions in both AccessControllers
6. Register tokens via `addToken()`

### Per-Market Deploy
1. Deploy FundingRateVerifier + FIndexOracle
2. Create market via MarketFactory (batch with zone config)
3. Deploy AMM (batch with CLO exemptions)
4. Enter market from BotController + MarkRatePusher forwarders
5. Set CLO thresholds (93%/95% of hard OI cap)
6. Set CLO exemptions for seeder, bots, makers
7. Run invariant checks (`scripts/double_check/`)

### Post-Upgrade
1. Verify state consistency via `compare_markets.ts`
2. Run market invariant checks
3. Verify permissions haven't changed
