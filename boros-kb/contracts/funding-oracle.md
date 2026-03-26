---
description: Funding rate pipeline — offchain bot fetches CEX rates, FundingRateVerifier validates against 3 oracle sources, FIndexOracle stores and advances settlement
last_updated: 2026-03-17
related:
  - contracts/settlement.md
  - contracts/rate-oracles.md
  - offchain-bots/failsafe-bots.md
---

# Funding Oracle

The funding rate pipeline feeds CEX funding rates on-chain so that positions can settle against them. The architecture is a three-stage pipeline:

```
Offchain Funding Rate Bot (pendle-risks-bot-v3)
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

The bot does **not** call FIndexOracle directly. FundingRateVerifier is the keeper of FIndexOracle, and the bot is authorized to call FundingRateVerifier.

---

## FundingRateVerifier

**Source**: `contracts/verifier/FundingRateVerifier.sol`

One FundingRateVerifier is deployed per market. It validates funding rate data from one of three oracle sources before forwarding to FIndexOracle. Note the separation: FIndexOracle (and Boros) is designed to work with any interest rate expressible as a cumulative index — "FIndex" stands for **Floating Index**, not Funding Index. FundingRateVerifier is just one adapter that converts funding rate oracle data into the generic index format that FIndexOracle consumes.

### Entry Points

| Function | Source | Input |
|----------|--------|-------|
| `updateWithChainlink(bytes report)` | Chainlink Data Streams | Raw Chainlink report bytes |
| `updateWithChaosLabs(uint256 updateId)` | ChaosLabs Risk Oracle | Update ID to look up on-chain |
| `updateWithPendle()` | Pendle oracle | No input — reads `latestUpdate()` from configured oracle |
| `manualUpdate(int112 fundingRate, uint32 fundingTimestamp)` | Admin override | Direct rate + timestamp |

All entry points are guarded by `onlyAuthorized` via `PendleAccessController`. The offchain bot must be whitelisted for each selector it needs to call.

Each entry point follows the same pattern:
1. Call the source-specific verification library
2. Receive validated `(int112 fundingRate, uint32 fundingTimestamp)`
3. Forward to `IFIndexOracle(FINDEX_ORACLE).updateFloatingIndex(fundingRate, fundingTimestamp)`

### Immutable Configuration (set at construction)

| Parameter | Description |
|-----------|-------------|
| `FINDEX_ORACLE` | Target FIndexOracle address this verifier feeds |
| `CHAIN_LINK_ORACLE` | Chainlink VerifierProxy address |
| `CHAIN_LINK_FEED_ID` | Chainlink feed identifier (bytes32) |
| `CHAOS_LABS_ORACLE` | ChaosLabs Risk Oracle address |
| `CHAOS_LABS_UPDATE_TYPE_HASH` | Hash of the expected update type string |
| `CHAOS_LABS_MARKET` | ChaosLabs market reference address |
| `PENDLE_ORACLE` | Pendle funding rate oracle address |

### Mutable Configuration

| Parameter | Description |
|-----------|-------------|
| `maxVerificationFee` | Maximum fee Chainlink can charge for report verification |
| `period` | Expected epoch duration in seconds (must match FIndexOracle's `updatePeriod`) |

---

## Verification Libraries

Each oracle source has a dedicated verification library in `contracts/verifier/lib/`.

### ChainlinkVerifierLib (`lib/Chainlink.sol`)

```
verifyFundingRateReport(report, chainlink, expectedFeedId, maxVerificationFee, period, lastUpdatedTime)
  → (int112 fundingRate, uint32 fundingTimestamp)
```

Validation:
1. Extract report version, calculate verification fee from Chainlink FeeManager
2. Verify `fee <= maxVerificationFee`
3. Call `IVerifierProxy(chainlink).verify{value: fee}()` to get verified report
4. Decode into `ReportFundingRate` struct
5. Validate `feedId == expectedFeedId`
6. Validate `epochDuration == period`
7. Validate `lastUpdatedTime + period == fundingTimestamp` (correct sequence, no skipping)

### ChaosLabsVerifierLib (`lib/ChaosLabs.sol`)

```
verifyFundingRateReport(updateId, riskOracle, expectedUpdateTypeHash, expectedMarket, period, lastUpdatedTime)
  → (int112 fundingRate, uint32 fundingTimestamp)
```

Validation:
1. Retrieve `RiskParameterUpdate` from ChaosLabs oracle by `updateId`
2. Validate `keccak256(updateType) == expectedUpdateTypeHash`
3. Validate `market == expectedMarket`
4. ABI-decode `newValue` to extract raw rate, exponent, timestamp (ms), epoch duration (ms)
5. Convert: `fundingRate = rawFundingRate × 10^(18 - exponent)`
6. Convert milliseconds to seconds
7. Validate `epochDuration == period`
8. Validate `lastUpdatedTime + period == fundingTimestamp`

### PendleVerifierLib (`lib/Pendle.sol`)

```
verifyFundingRateReport(oracle, period, lastUpdatedTime)
  → (int112 fundingRate, uint32 fundingTimestamp)
```

Validation:
1. Call `IFundingRateOracle(oracle).latestUpdate()`
2. Validate `epochDuration == period`
3. Validate `lastUpdatedTime + period == fundingTimestamp`

### Common Validation Across All Sources

The three automated entry points (`updateWithChainlink`, `updateWithChaosLabs`, `updateWithPendle`) all enforce two critical invariants via their verification libraries:
- **Epoch duration match**: The source's reported epoch duration must equal the verifier's configured `period`
- **Sequential updates**: `lastUpdatedTime + period == fundingTimestamp` — no epoch can be skipped

`manualUpdate` bypasses both checks — the admin provides the rate and timestamp directly with no verification library involved.

### Missed Epoch Recovery

If the bot misses an epoch (e.g., bot is down and `maxUpdateDelay` has passed), the epoch cannot be submitted late via the normal bot path. The `_calcUpdateTime` logic uses `max(lastUpdateTime, blockTimestamp - maxUpdateDelay)` to find the next valid epoch — once `maxUpdateDelay` expires, the missed epoch's timestamp is no longer reachable, and `nextUpdateTimestamp` advances to a later epoch.

Recovery uses `manualUpdate` to submit a **merged** delta covering multiple epochs in a single update.

Example for an 8-hour market with epochs at 0:00, 8:00, 16:00 and `maxUpdateDelay` = 15 min:
- Normal: push rate for 0:00→8:00 at 8:00, then rate for 8:00→16:00 at 16:00
- Bot dies at 8:00, 15-min grace period expires at 8:15: the 8:00 epoch is now unreachable
- `nextUpdateTimestamp` advances to 16:00 (the next epoch boundary after `max(0:00, now - 15min)`)
- At 16:00, admin calls `manualUpdate` with `desiredTimestamp = 16:00` and `floatingIndexDelta` = sum of funding rates for both 0:00→8:00 and 8:00→16:00

The FIndexOracle sees a single update from 0:00 to 16:00. The intermediate 8:00 epoch is effectively merged — no epoch is "skipped" from the oracle's perspective, the delta just covers a longer period.

---

## FIndexOracle

**Source**: `contracts/core/market/findexOracle/FIndexOracle.sol`

One FIndexOracle is deployed per market. Its **keeper is the FundingRateVerifier** (not the bot directly).

### `updateFloatingIndex(int112 floatingIndexDelta, uint32 desiredTimestamp)`

Called only by the keeper (FundingRateVerifier). Proceeds as follows:

1. **Epoch calculation**: Update endpoints have the form `maturity - k × period`, where `period` is the configurable `updatePeriod`. Updates must arrive at these exact epoch boundaries.

2. **Validation**:
   - `lastUpdateTime < maturity` — cannot update after market maturity (reverts `FIndexUpdatedAtMaturity`)
   - `nextUpdateTimestamp <= block.timestamp` — the epoch must have actually arrived (reverts `FIndexNotDueForUpdate`)
   - `desiredTimestamp == nextUpdateTimestamp` — prevents skipping epochs (reverts `FIndexInvalidTime`)

3. **Index computation**:
   - `newFloatingIndex = oldFloatingIndex + floatingIndexDelta`
   - `newFeeIndex = PaymentLib.calcNewFeeIndex(oldFeeIndex, settleFeeRate, timeDelta)` — fee index grows proportionally to elapsed time and the configured settle fee rate

4. **Market notification**: Calls `IMarket(market).updateFIndex(newIndex)`, which advances the Market's `latestFTag`. This enables lazy settlement — positions settle against the latest FTag when users next interact.

5. **Storage**: Stores `latestAnnualizedRate` for external reference (front-end display, analytics).

### FIndex Data Structure

An `FIndex` is packed as `bytes26`:

| Field | Description |
|-------|-------------|
| `fTime` | Timestamp of this update |
| `floatingIndex` | Cumulative floating index value |
| `feeIndex` | Cumulative fee index value |

### Configuration

| Parameter | Description |
|-----------|-------------|
| `updatePeriod` | Interval between epoch boundaries (e.g., 1 hour) |
| `maxUpdateDelay` | Grace period — allows catch-up if an update was delayed. Missed epochs can be submitted sequentially within this window |
| `settleFeeRate` | Fee rate applied to fee index growth per unit time |
| `maturity` | Market maturity timestamp — no updates after this point |
| `keeper` | Permissioned address — set via `setKeeper()`. This is the FundingRateVerifier address |

---

## Offchain Funding Rate Bot

See `offchain-bots/funding-rate-bot.md` for the offchain bot that drives this pipeline (detect/fetch/execute loops, multi-oracle validation, execution timing).
