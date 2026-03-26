---
description: Testing infrastructure — Foundry test suite, 82 test files, fuzz/invariant testing, comparison testing, test helpers, and execution
last_updated: 2026-03-17
related:
  - contracts/architecture.md
  - contracts/margin-engine.md
  - contracts/order-lifecycle.md
  - contracts/settlement.md
  - contracts/risk-bots.md
  - contracts/amm.md
---

# Testing Infrastructure

Source: `contract-v3-tests/`. Foundry-based test suite with 82 Solidity test files covering unit, fuzz, invariant, integration, and comparison tests across all protocol components.

---

## Framework

**Primary**: Foundry (Forge) with Solidity 0.8.19 + 0.8.28 (Cancun EVM).

**Secondary**: Hardhat + viem for TypeScript tests. Foundry cannot test EIP-712 type hashes, so Hardhat is mainly used for that.

**Configuration** (`foundry.toml`):
```
optimizer_runs = 1,000,000
evm_version = "cancun"
ffi = true
fuzz.seed = 0x8888
invariant.fail_on_revert = true
```

---

## Running Tests

```bash
# Full suite (excludes benchmarks/coverage)
./run_all_tests.sh
# = forge test --no-match-contract '(Benchmark|Coverage)'

# Quick (excludes fuzz/invariant/math)
./run_quick_tests.sh
# = forge test --no-match-contract '(Benchmark|Coverage|Fuzz|Invariant|TickMath|LiquidityMath|SwapMath|ArbitrageMath)'

# Coverage (LCOV format, generates HTML via genhtml)
./run_coverage.sh

# Tick benchmark
./run_tick_benchmark.sh
```

---

## Test Organization

```
test/
├── core/
│   ├── router/              # one dir per module
│   │   ├── AMMModule/
│   │   ├── AuthModule/
│   │   ├── ConditionalModule/
│   │   ├── DepositModule/
│   │   ├── MiscModule/
│   │   ├── OTCModule/
│   │   ├── TradeModule/
│   │   └── math/            # LiquidityMath.fuzz, SwapMath.fuzz
│   ├── markethub/           # cross-market integration
│   ├── market/              # per-market logic
│   │   ├── core/            # CoreOrderUtils fuzz
│   │   ├── fuzz/            # Market invariant/fuzz
│   │   ├── orderbook/       # OrderBook fuzz tests
│   │   └── settle/          # settlement tests
│   ├── amm/                 # AMM logic
│   ├── bots/                # bot executor tests
│   │   ├── liquidation/
│   │   ├── arbitrage/
│   │   └── risk/
│   ├── factory/             # MarketFactory, AMMFactory
│   └── roles/               # AccessController roles
├── cross-chain/             # CrossChainPortal tests
├── lib/                     # Library math tests
├── types/                   # Type packing/unpacking tests
├── verifier/                # Funding rate verifier tests
├── offchain-helpers/        # Offchain helper tests
└── BorosTestBase.sol        # Base test contract
```

---

## Base Test Setup — `BorosTestBase`

Base contract that deploys the entire protocol in `setUp()`. All test files inherit from it.

### What It Deploys

1. **Access control**: PendleAccessController (transparent proxy) + role grants
2. **Core protocol**: MarketHub (transparent proxy via CREATE3), MarketFactory, Router (transparent proxy with all 7 modules), AdminModule, MarketHubRiskManagement
3. **One market**: `market0` with `market0Id`, FIndexOracle, MockRateOracle
4. **AMM**: AMMFactory (transparent proxy)
5. **Deposit**: DepositBox + DepositBoxBeacon + DepositBoxFactory
6. **Tokens**: MockToken (collateral asset)
7. **Test accounts**: `admin`, `treasury`, `fIndexOracleUpdater`, `ELSE_WHERE` via `makeAddr()`. Users created dynamically via `makeUserWithCash()` and `makeUserWithCashAndEnterMarket0()`

### Key Helper Functions

**State manipulation:**
- `forwardOneEpoch(delta, oracle)` — advance block.timestamp by one settlement period + update FIndex oracle
- `setHealthRatio(acc, hr)` — directly manipulate cash to achieve target health ratio
- `setMarkRate(rateOracle, rate)` — set mark rate via MockRateOracle

**Read helpers:**
- `getTotalIM(acc)` / `getTotalMM(acc)` — aggregate margin across all markets
- `getTotalValue(acc)` — mark-to-market position value after settlement
- `getHealth(acc)` / `getHealthRatio(acc)` — health ratio

**Assertions** (`SharedAssertions.sol`):
- Domain-specific assertions for Trade, VMResult, PayFee types

---

## Test Categories

### Unit Tests

Standard `test_*` functions testing individual operations in isolation.

### Fuzz Tests

Pattern: `*.fuzz.t.sol`. Foundry generates random inputs to test properties.

**Math fuzz tests:**
- `AMMMath.fuzz.t.sol` — AMM swap/liquidity math with random reserves, rates, sizes
- `LiquidityMath.fuzz.t.sol` — Router liquidity calculations
- `SwapMath.fuzz.t.sol` — Router swap calculations
- `TickBitmap.fuzz.t.sol` — Tick bitmap operations
- `LibOrderIdSort.fuzz.t.sol` — Order ID sorting correctness
- `StoredOrderIdArr.fuzz.t.sol` — Order ID array operations

**Protocol fuzz tests:**
- `Market.fuzz.t.sol` — Random market operations (orders, cancels, settlements)
- `CoreOrderUtils.fuzz.t.sol` — Core order add/remove/match sequences
- `OrderBookUtils.fuzz.t.sol` — Orderbook state transitions

### Invariant Tests

Use `InvariantTestHelpers.sol` infrastructure with handler contracts:

**Handler pattern:**
```solidity
modifier captureCall() { numCalls[msg.sig]++; totalCalls++; _; }
modifier invokeWithProbability(uint256 seed, uint256 percentage) { ... }
modifier limitConsecutiveCalls(uint256 maxCallCount) { ... }
```

Foundry calls handler functions randomly, checking invariants after each call sequence. `fail_on_revert = true` ensures unexpected reverts are caught.

**State tracking:**
- `numCalls[bytes4]` — call count by function selector
- `totalCalls` — total operations executed

### Comparison Tests (Solidity vs TypeScript)

Cross-platform correctness validation using file-based I/O:

1. **TypeScript reference** generates test vectors → writes to `test-data/`
2. **Solidity runner** reads test vectors via `FileIO.sol`
3. **Comparison** checks Solidity output matches TypeScript reference

Used for:
- **AMM math** (`scripts/AMMMath/`) — swap output, liquidity calculations, normalized time
- **Order book utils** (`scripts/OrderBookUtils/`) — tick operations, order matching

File I/O helpers: `FileIO.sol`, `FileIOForBorosTypes.sol`, `FileIOForAMMTypes.sol` — serialize/deserialize domain types for cross-platform comparison.

### Integration Tests (Hardhat/TypeScript)

`test-hardhat/` contains TypeScript tests using Hardhat + viem:

- `settle.ts` — settlement scenarios
- `conditional.ts` — conditional order execution
- `orders.ts` — order placement
- `otc.ts` — OTC trades
- `deposit.ts` — deposit flows
- `amm.ts` — AMM operations
- `signing.ts` — EIP-712 type hash verification
- `simulate.ts` — simulation helpers
- `distributor.ts` — distributor tests

EIP-712 type hash verification is a key use case — Foundry cannot test EIP-712 type hashes (computed from struct definitions), so Hardhat is used to verify that the Solidity-side type hashes match the expected EIP-712 encoding.

---

## Bot Executor Tests

Test files covering BotController facets:

| Test File | Facet Tested |
|-----------|-------------|
| `LiquidationExecutor.t.sol` | LiquidationExecutorFacet |
| `ArbitrageExecutor.t.sol` | ArbitrageExecutorFacet |
| `Deleverager.t.sol` | DeleveragerFacet |
| `Pauser.t.sol` | PauserFacet |
| `CLOSetter.t.sol` | CLOSetterFacet |
| `OrderCanceller.t.sol` | OrderCancellerFacet |
| `WithdrawalPolice.t.sol` | WithdrawalPoliceFacet |
| `ZoneResponder.t.sol` | ZoneResponder |
| `MarkRatePusher.t.sol` | MarkRatePusher |
| `MiscFacet.t.sol` | MiscFacet |
| `SettleSimMath.t.sol` | SettleSimMath library |

---

## AMM Tests

`AMMTestBase.t.sol` (730 lines) provides AMM setup with seed parameter calculation (initial liquidity, rates, cash, time normalization). Separate test files: `PositiveAMM.t.sol`, `NegativeAMM.t.sol`, `BOROS20.t.sol`.

Fuzz tests (`AMMMath.fuzz.t.sol`) verify math invariants.

---

## MarketHub Tests

| File | Coverage |
|------|----------|
| `settle.t.sol` | FIndex epoch updates, settlement payment calculation, multi-period settlement |
| `orders.t.sol` | Order placement, matching, partial fills, TIF enforcement |
| `liquidation.t.sol` | Full liquidation flow: detect → simulate → execute → verify health improvement |
| `margin.t.sol` | IM/MM calculation, strict vs closing-only, cross-market aggregation |
| `deleverage.t.sol` | Force deleverage: loser/winner selection, factor calculation, bad debt |
| `enterExit.t.sol` | Market entry/exit, max markets limit |
| `cash.t.sol` | Cash transfers, deposits |
| `checks.t.sol` | Margin and health checks |
| `fees.t.sol` | Fee collection, treasury |
| `isolated.t.sol` | Isolated margin accounts |
| `maturity.t.sol` | Market maturity handling |
| `misc.t.sol` | Miscellaneous MarketHub operations |
| `multiple_orders.t.sol` | Bulk order scenarios |
| `returnValue.t.sol` | Return value verification |

---

## Mock Contracts

| Mock | Purpose |
|------|---------|
| `MockToken` | ERC20 collateral token with mint/burn |
| `MockRateOracle` | Controllable rate oracle for mark rate tests |
| `MarketHubHarness` | Exposes internal MarketHub functions for unit testing |
| `MarketCtxSetter` | Direct storage writes to market context (bypass access control) |
| `TStorer` | Transient storage manipulation helper |
| `RouterWrapper` | Helper library for Router calls |

---

## Test Data Generation

`scripts/` contains TypeScript generators for cross-platform comparison:

- `scripts/AMMMath/` — generates AMM math test vectors
- `scripts/OrderBookUtils/` — generates orderbook test vectors
- `scripts/amm-stress/` — AMM stress test data
- `scripts/tick-benchmark/` — tick operation benchmarks

Additional utility scripts: `getAllFunctionSelectors.ts`, `getCreationCode.ts`, `getRateAtTick.ts`, `parse-order-id.ts`, `parse-trade.ts`.

Generated data stored in `test-data/` and read by Solidity tests via `FileIO.sol`.
