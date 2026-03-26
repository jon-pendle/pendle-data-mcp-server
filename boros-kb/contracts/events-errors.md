---
description: Comprehensive error catalogue and key events — grouped by domain with trigger conditions and emitting functions
last_updated: 2026-03-17
related:
  - contracts/architecture.md
  - contracts/order-lifecycle.md
  - contracts/settlement.md
---

# Events and Errors

This document catalogues the custom errors defined in `contracts/lib/Errors.sol` and the key events emitted by MarketHub and Market contracts.

---

## Error Catalogue

### Market Errors

Thrown by Market contract functions (`MarketOrderAndOtc`, `MarketRiskManagement`) during order matching, OTC swaps, and position management.

| Error | Trigger |
|-------|---------|
| `MarketMatured` | Any trade attempt after market maturity |
| `MarketOICapExceeded` | New match would push open interest beyond the hard cap |
| `MarketSelfSwap` | A user's order would match against their own order |
| `MarketLiqNotReduceSize` | Liquidation trade does not reduce the violator's position |
| `MarketInvalidLiquidation` | Liquidation parameters fail on-chain validation (e.g., violator is healthy) |
| `MarketInvalidDeleverage` | Deleverage parameters are invalid (see deleverage bot constraints) |
| `MarketOrderNotFound` | Referenced order ID does not exist in the book |
| `MarketOrderFOKNotFilled` | Fill-or-kill order could not be fully filled |
| `MarketOrderALOFilled` | Add-liquidity-only order would immediately match (violates ALO semantics) |
| `MarketInvalidFIndexOracle` | FIndex oracle address is zero or misconfigured |
| `MarketMaxOrdersExceeded` | User has too many open orders in this market |
| `MarketZeroSize` | Order submitted with zero size |
| `MarketDuplicateOTC` | OTC trade with this ID has already been executed |
| `MarketOrderFilled` | Attempted operation on an already-filled order |
| `MarketOrderCancelled` | Attempted operation on a cancelled order |
| `MarketOrderRateOutOfBound` | Order rate outside configured rate deviation bounds |
| `MarketLastTradedRateTooFar` | Last traded rate is too far from mark rate (staleness check) |
| `MarketPaused` | Market is in paused state (set by admin or CLO bot) |
| `MarketCLO` | Market is in close-only mode — only reducing orders accepted |

### FIndex Errors

Thrown by `FIndexOracle.updateFloatingIndex()`.

| Error | Trigger |
|-------|---------|
| `FIndexUpdatedAtMaturity` | Keeper attempts update after market maturity |
| `FIndexNotDueForUpdate` | `desiredTimestamp` does not match the next expected epoch |
| `FIndexInvalidTime` | `desiredTimestamp` is in the future or otherwise invalid |

### Margin / MarketHub Errors

Thrown by MarketHub's margin engine, account management, and vault operations.

| Error | Trigger |
|-------|---------|
| `MMMarketNotEntered` | User tries to trade in a market they have not entered |
| `MMMarketAlreadyEntered` | Duplicate `enterMarket()` call |
| `MMMarketLimitExceeded` | User would exceed the maximum number of entered markets |
| `MMInsufficientIM` | Post-operation initial margin check fails |
| `MMMarketExitDenied` | User tries to exit a market while still holding positions or open orders |
| `MMIsolatedMarketDenied` | Operation not allowed for isolated-margin accounts |
| `MMMarketMismatch` | Isolated account's market does not match the target market |
| `MMTokenMismatch` | Token ID mismatch between accounts in a transfer |
| `MMTransferDenied` | Cash transfer between incompatible account types |
| `MMSimulationOnly` | Function is restricted to simulation context |
| `MMHealthCritical` | Health ratio below critical threshold (triggers forced actions) |
| `MMInsufficientMinCash` | Cash below minimum required amount |
| `MMInvalidCritHR` | Invalid critical health ratio configuration |
| `MMHealthNonRisky` | Force-cancel attempted on a user who is not risky |
| `MHTokenNotExists` | Referenced token ID is not registered |
| `MHTokenExists` | Duplicate `addToken()` call |
| `MHMarketExists` | Duplicate `addMarket()` call |
| `MHTokenLimitExceeded` | Maximum number of registered tokens reached |
| `MHMarketNotExists` | Referenced market ID is not registered |
| `MHMarketNotByFactory` | Market address was not created by the authorized MarketFactory |
| `MHWithdrawNotReady` | Withdrawal cooldown has not elapsed |
| `MHInvalidLiquidator` | Liquidator address is not authorized |

### AMM Errors

Thrown by PositiveAMM / NegativeAMM contracts and AMM math libraries.

| Error | Trigger |
|-------|---------|
| `AMMWithdrawOnly` | AMM is in withdraw-only mode (delevLiqNonce != 0) |
| `AMMCutOffReached` | Current time is past `cutOffTimestamp` |
| `AMMInsufficientLiquidity` | Pool does not have enough reserves for the swap |
| `AMMInvalidRateRange` | Swap would push implied rate outside `[minAbsRate, maxAbsRate]` |
| `AMMSignMismatch` | Rate sign mismatch between PositiveAMM and NegativeAMM |
| `AMMInsufficientCashIn` | Cash input below minimum threshold |
| `AMMInsufficientCashOut` | Cash output below minimum threshold |
| `AMMInsufficientLpOut` | LP tokens minted below minimum threshold |
| `AMMInsufficientSizeOut` | Position size returned on burn below minimum |
| `AMMNegativeCash` | Operation would result in negative cash for the AMM account |
| `AMMTotalSupplyCapExceeded` | LP total supply would exceed configured cap |
| `AMMInvalidParams` | Invalid AMM configuration parameters |
| `AMMNotFound` | Referenced AMM ID does not exist |

### Auth Errors

Thrown by `AuthModule` and signature verification.

| Error | Trigger |
|-------|---------|
| `AuthInvalidMessage` | EIP-712 signature verification fails |
| `AuthInvalidConnectionId` | Connection ID mismatch in agent authorization |
| `AuthAgentExpired` | Agent's authorization has expired (timestamp check) |
| `AuthInvalidNonce` | Nonce is not strictly greater than stored value (replay protection) |
| `AuthExpiryInPast` | Agent expiry timestamp is in the past |
| `AuthIntentExecuted` | Intent with this ID has already been executed |
| `AuthIntentExpired` | Intent's expiry timestamp has passed |
| `AuthSelectorNotAllowed` | Agent is not authorized for the requested function selector |

### Module Errors

Thrown by Router modules (TradeModule, OTCModule, ConditionalModule).

| Error | Trigger |
|-------|---------|
| `TradeALOAMMNotAllowed` | ALO order type not allowed for AMM interactions |
| `TradeOnlyMainAccount` | Operation restricted to main (non-sub) accounts |
| `TradeOnlyAMMAccount` | Operation restricted to AMM accounts |
| `TradeOnlyForIsolated` | Operation restricted to isolated-margin accounts |
| `TradeUndesiredRate` | Fill rate worse than the user's specified limit |
| `TradeUndesiredSide` | Fill direction does not match requested side |
| `TradeMarketIdMismatch` | Market ID in trade params does not match target |
| `TradeAMMAlreadySet` | AMM already registered for this market |
| `ConditionalInvalidAgent` | Conditional order's agent is not authorized |
| `ConditionalInvalidValidator` | Validator co-signature is invalid |
| `ConditionalInvalidParams` | Conditional order parameters malformed |
| `ConditionalActionExecuted` | Action has already been executed |
| `ConditionalMessageExpired` | Conditional message's expiry has passed |
| `ConditionalOrderExpired` | Conditional order's expiry has passed |
| `ConditionalOrderNotReduceOnly` | Conditional order flagged reduce-only but would increase position |
| `OTCInvalidAgent` | OTC trade's agent is not authorized |
| `OTCMessageExpired` | OTC message's expiry has passed |
| `OTCRequestExecuted` | OTC request with this ID already executed |
| `InsufficientDepositAmount` | Deposit amount is zero or below minimum |

### Bot / Risk Errors

Thrown by risk management bot contracts and `MarketHubRiskManagement`.

| Error | Trigger |
|-------|---------|
| `CLOInvalidThreshold` | CLO threshold configuration is invalid |
| `CLOThresholdNotMet` | OI has not reached the CLO activation threshold |
| `CLOMarketInvalidStatus` | Market status does not allow CLO state change |
| `DeleveragerAMMNotAllowed` | Cannot deleverage the AMM account via this path |
| `DeleveragerDuplicateMarketId` | Duplicate market ID in deleverage batch |
| `DeleveragerHealthNonRisky` | Loser's health ratio is above deleverage threshold |
| `DeleveragerLoserHealthier` | Loser is healthier than winner (wrong direction) |
| `DeleveragerLoserInBadDebt` | Loser is in bad debt (should use different mechanism) |
| `DeleveragerWinnerInBadDebt` | Winner is in bad debt (invalid counterparty) |
| `DeleveragerIncomplete` | Deleverage did not fully resolve the position |
| `OrderCancellerDuplicateMarketId` | Duplicate market ID in force-cancel batch |
| `OrderCancellerDuplicateOrderId` | Duplicate order ID in force-cancel batch |
| `OrderCancellerInvalidOrder` | Order does not exist or already cancelled |
| `OrderCancellerNotRisky` | User is not risky enough for force-cancel |
| `PauserNotRisky` | Market conditions do not warrant pausing |
| `PauserTokenMismatch` | Token mismatch in pause operation |
| `WithdrawalPoliceAlreadyRestricted` | User already has restricted withdrawal cooldown |
| `WithdrawalPoliceInvalidCooldown` | Invalid cooldown value |
| `WithdrawalPoliceInvalidThreshold` | Invalid threshold configuration |
| `WithdrawalPoliceUnsatCondition` | Withdrawal restriction condition not met |
| `ZoneGlobalCooldownAlreadyIncreased` | Global cooldown already raised for this zone event |
| `ZoneMarketInvalidStatus` | Market status invalid for zone transition |
| `ZoneInvalidGlobalCooldown` | Invalid global cooldown configuration |
| `ZoneInvalidLiqSettings` | Invalid liquidation settings for zone |
| `ZoneInvalidRateDeviationConfig` | Rate deviation config invalid for zone |

### Executor Errors

Thrown by BotController executor facets.

| Error | Trigger |
|-------|---------|
| `InsufficientProfit` | Bot execution did not meet minimum profit threshold |
| `ProfitMismatch` | Reported profit does not match actual profit |
| `LiquidationAMMNotAllowed` | Cannot liquidate the AMM account |
| `ZeroArbitrageSize` | Arbitrage attempt with zero size |

### Cross-Chain Portal Errors

| Error | Trigger |
|-------|---------|
| `PortalMessengerNotSet` | OFT messenger not configured for this token |
| `PortalInvalidMessenger` | Messenger address is invalid |

### Funding Rate Oracle Errors

Thrown by `FundingRateOracle` and verification libraries.

| Error | Trigger |
|-------|---------|
| `FundingRateOutOfBound` | Submitted funding rate exceeds max deviation |
| `FundingTimestampNotIncreasing` | Funding timestamp is not after previous update |

### General Errors

| Error | Trigger |
|-------|---------|
| `Unauthorized` | Caller does not have required permission |
| `InvalidLength` | Array length mismatch or zero-length input |
| `InvalidFeeRates` | Fee rate configuration is invalid |
| `InvalidObservationWindow` | AMM oracle window is zero or too large |
| `InvalidNumTicks` | Tick count parameter is invalid |
| `InvalidTokenId` | Token ID is zero or unregistered |
| `InvalidMaturity` | Maturity timestamp is invalid |
| `InvalidAMMId` | AMM ID is zero or unregistered |
| `InvalidAMMAcc` | AMM account identifier is invalid |
| `SimulationOnly` | Function is restricted to simulation mode |
| `MathOutOfBounds` | Math operation overflow or underflow |
| `MathInvalidExponent` | Exponentiation with invalid exponent |

---

## Key Events

### Limit Order Events (IMarket)

| Event | Signature | Description |
|-------|-----------|-------------|
| `LimitOrderPlaced` | `(MarketAcc maker, OrderId[] orderIds, uint256[] sizes)` | Limit orders placed on the book. One event per batch of orders from the same maker |
| `LimitOrderCancelled` | `(OrderId[] orderIds)` | Orders voluntarily cancelled by the maker |
| `LimitOrderForcedCancelled` | `(OrderId[] orderIds)` | Orders force-cancelled by the OrderCanceller bot (user is risky) |
| `LimitOrderPartiallyFilled` | `(OrderId orderId, uint256 filledSize)` | Order partially filled during a book match |
| `LimitOrderFilled` | `(OrderId from, OrderId to)` | Range of order IDs fully filled in a single match sweep |
| `OobOrdersPurged` | `(OrderId from, OrderId to)` | Out-of-bound orders purged after rate deviation config change |

### Trade Events (IMarket)

| Event | Signature | Description |
|-------|-----------|-------------|
| `MarketOrdersFilled` | `(MarketAcc user, Trade totalTrade, uint256 totalFees)` | Aggregate result of book matching for a user in a single batch. `Trade` contains net size and cost |
| `OtcSwap` | `(MarketAcc user, MarketAcc counterParty, Trade trade, int256 cashToCounter, uint256 otcFee)` | OTC trade executed — also used for AMM swaps where one side is the AMM account |
| `Liquidate` | `(MarketAcc liq, MarketAcc vio, Trade liqTrade, uint256 liqFee)` | Liquidation executed. `liqFee` is the fee charged to the liquidator |
| `ForceDeleverage` | `(MarketAcc win, MarketAcc lose, Trade delevTrade)` | Forced deleveraging — resolves underwater positions by closing against a winning counterparty |

### Settlement Events (IMarket)

| Event | Signature | Description |
|-------|-----------|-------------|
| `FIndexUpdated` | `(FIndex newIndex, FTag newFTag)` | New funding index pushed from FIndexOracle — triggers settlement for all users on next interaction |
| `FTagUpdatedOnPurge` | `(FIndex newIndex, FTag newFTag)` | FTag updated during order purge after FIndex change |
| `PaymentFromSettlement` | `(MarketAcc user, uint256 lastFTime, uint256 latestFTime, int256 payment, uint256 fees)` | Settlement payment applied. `payment` is net (positive = received). `lastFTime`→`latestFTime` is the settled epoch range |

### MarketHub Events (IMarketHub)

| Event | Signature | Description |
|-------|-----------|-------------|
| `EnterMarket` | `(MarketAcc user, MarketId marketId, uint256 entranceFee)` | User enters a market, enabling trading. `entranceFee` deducted from cash |
| `ExitMarket` | `(MarketAcc user, MarketId marketId)` | User exits a market after closing all positions and orders |
| `VaultDeposit` | `(MarketAcc acc, uint256 unscaledAmount)` | ERC20 deposited and credited to user cash |
| `VaultWithdrawalRequested` | `(address root, TokenId tokenId, uint32 start, uint256 totalUnscaledAmount)` | Withdrawal request created or accumulated. `start` is cooldown start timestamp |
| `VaultWithdrawalCanceled` | `(address root, TokenId tokenId, uint256 totalUnscaledAmount)` | Pending withdrawal returned to cash |
| `VaultWithdrawalFinalized` | `(address root, TokenId tokenId, uint256 totalUnscaledAmount)` | Withdrawal cooldown elapsed, ERC20 transferred out |
| `PersonalCooldownSet` | `(address root, uint32 cooldown)` | User sets personal withdrawal cooldown |
| `CashTransfer` | `(MarketAcc from, MarketAcc to, int256 amount)` | Internal cash movement between accounts |
| `PayTreasury` | `(MarketAcc user, uint256 amount)` | User pays to treasury from cash |
| `TokenAdded` | `(TokenId indexed tokenId, address indexed tokenAddress)` | New collateral token registered |
| `MarketAdded` | `(MarketId indexed marketId, address indexed marketAddress)` | New market registered in MarketHub |
| `CollectFee` | `(TokenId indexed tokenId, uint256 amount)` | Treasury fee collected for a token |

### Market Config Events (IMarket)

| Event | Signature | Description |
|-------|-----------|-------------|
| `StatusUpdated` | `(MarketStatus newStatus)` | Market status changed (PAUSED / CLO / GOOD) |
| `MarginConfigUpdated` | `(uint64 newKIM, uint64 newKMM, uint64 newTThresh)` | Margin parameters changed |
| `FeeRatesUpdated` | `(uint64 newTakerFee, uint64 newOtcFee)` | Fee rates changed |
| `OICapUpdated` | `(uint128 newHardOICap)` | Open interest hard cap changed |
| `OracleAddressesUpdated` | `(address newMarkRateOracle, address newFIndexOracle)` | Oracle addresses changed |
| `RateBoundConfigUpdated` | `(uint16 newMaxRateDeviationFactorBase1e4, uint16 newClosingOrderBoundBase1e4)` | Rate deviation bounds changed |
| `LimitOrderConfigUpdated` | `(int16 loUpperConstBase1e4, int16 loUpperSlopeBase1e4, int16 loLowerConstBase1e4, int16 loLowerSlopeBase1e4)` | Limit order rate bound config (Appendix E) |
| `LiquidationSettingsUpdated` | `(LiqSettings newLiqSettings)` | Liquidation incentive parameters changed |
| `MaxOpenOrdersUpdated` | `(uint16 newMaxOpenOrders)` | Max open orders per user per market |
| `ImpliedRateObservationWindowUpdated` | `(uint32 newWindow)` | AMM TWAP observation window changed |
| `PersonalMarginConfigUpdated` | `(MarketAcc indexed user, uint64 newKIM, uint64 newKMM)` | Per-user margin override |
| `PersonalDiscRatesUpdated` | `(MarketAcc indexed user, uint64 newTakerDisc, uint64 newOtcDisc)` | Per-user fee discount |
| `PersonalExemptCLOCheckUpdated` | `(MarketAcc user, bool exemptCLOCheck)` | CLO exemption for market makers |

### MarketHub Config Events (IMarketHub)

| Event | Signature | Description |
|-------|-----------|-------------|
| `CritHRUpdated` | `(int256 newCritHR)` | Critical health ratio threshold changed |
| `RiskyThresHRUpdated` | `(int256 newRiskyThresHR)` | Risky health ratio threshold changed |
| `StrictHealthCheckUpdated` | `(MarketId marketId, bool isEnabled)` | Per-market strict health check toggle |
| `GlobalCooldownSet` | `(uint32 newCooldown)` | Global withdrawal cooldown changed |
| `MinCashCrossAccountsUpdated` | `(TokenId[] tokenIds, uint128[] newMinCash)` | Minimum cash for cross-margin accounts |
| `MinCashIsolatedAccountsUpdated` | `(TokenId[] tokenIds, uint128[] newMinCash)` | Minimum cash for isolated accounts |
| `MarketEntranceFeesUpdated` | `(TokenId[] tokenIds, uint128[] entranceFees)` | Market entrance fees changed |

### Router Events (IRouterEventsAndTypes)

| Event | Signature | Description |
|-------|-----------|-------------|
| `SingleOrderExecuted` | `(MarketAcc indexed user, MarketId indexed marketId, AMMId indexed ammId, TimeInForce tif, Trade matched, uint256 takerOtcFee)` | Single order submitted through router. `tif` is GTC/FOK/ALO |
| `BulkOrdersExecuted` | `(MarketAcc indexed user, MarketId indexed marketId, TimeInForce tif, Trade matched, uint256 takerFee)` | Bulk orders across markets |
| `ConditionalOrderExecuted` | `(MarketAcc indexed user, bytes32 orderHash, MarketId marketId, AMMId ammId, TimeInForce tif, Trade matched, uint256 takerOtcFee)` | Conditional (stop-loss/take-profit) order triggered |
| `OTCTradeExecuted` | `(MarketAcc indexed maker, MarketAcc indexed taker, MarketId indexed marketId, Trade trade, uint256 otcFee)` | OTC trade through router |
| `SwapWithAmm` | `(MarketAcc indexed user, MarketId indexed marketId, AMMId indexed ammId, Trade matched, uint256 otcFee)` | Direct AMM swap |
| `NewAccManagerSet` | `(Account indexed account, address indexed newAccManager)` | Account manager changed |
| `AgentApproved` | `(Account indexed account, address indexed agent, uint64 indexed expiry)` | Agent authorization granted |
| `AgentRevoked` | `(Account indexed account, address indexed agent)` | Agent authorization revoked |
| `DepositFromBox` | `(address indexed root, uint32 boxId, address tokenSpent, uint256 amountSpent, uint8 accountId, TokenId tokenId, MarketId marketId, uint256 depositAmount, uint256 payTreasuryAmount)` | Deposit via Pendle Box (cross-chain) |

### AMM Events (IAMM)

| Event | Signature | Description |
|-------|-----------|-------------|
| `Mint` | `(MarketAcc indexed receiver, uint256 netLpMinted, int256 netCashIn, int256 netSizeIn)` | LP tokens minted (add liquidity) |
| `Burn` | `(MarketAcc indexed payer, uint256 netLpBurned, int256 netCashOut, int256 netSizeOut)` | LP tokens burned (remove liquidity) |
| `Swap` | `(int256 sizeOut, int256 costOut, uint256 fee)` | AMM internal swap |
| `BOROS20Transfer` | `(MarketAcc from, MarketAcc to, uint256 value)` | LP token transfer |
| `AMMConfigUpdated` | `(uint128 minAbsRate, uint128 maxAbsRate, uint32 cutOffTimestamp)` | AMM rate range / cutoff config |
| `TotalSupplyCapUpdated` | `(uint256 newTotalSupplyCap)` | LP supply cap changed |

### Oracle Events

| Event | Signature | Source |
|-------|-----------|--------|
| `FundingRateUpdated` | `(FundingRateUpdate)` | `IFundingRateOracle` — emitted when funding rate is pushed |
| `ConfigUpdated` | `(uint64 newSettleFeeRate, uint32 newUpdatePeriod, uint32 newMaxUpdateDelay)` | `IFIndexOracle` |
| `KeeperUpdated` | `(address newKeeper)` | `IFIndexOracle` |
| `ConfigUpdated` | `(uint256 maxVerificationFee, uint32 period)` | `IFundingRateVerifier` |
| `MaxDeltaSet` | `(uint256 newMaxDelta)` | `IMarkRatePusher` |

### Risk Bot Events

| Event | Signature | Source |
|-------|-----------|--------|
| `LiquidationExecuted` | `(MarketAcc indexed violator, int256 profit)` | `ILiquidationExecutorFacet` |
| `ArbitrageExecuted` | `(AMMId ammId, int256 profit)` | `IArbitrageExecutorFacet` |
| `CLOThresholdSet` | `(MarketId marketId, CLOThreshold newThreshold)` | `ICLOSetterFacet` |
| `DeleverageThresHRSet` | `(int256 newDeleverageThresHR)` | `IDeleveragerFacet` |
| `HealthJumpCancelThresHRSet` | `(int256 newHealthJumpCancelThresHR)` | `IOrderCancellerFacet` |
| `MinTotalMMSet` | `(TokenId tokenId, uint256 newMinTotalMM)` | `IPauserFacet` |

### Withdrawal Police Events (IWithdrawalPoliceFacet)

| Event | Signature | Description |
|-------|-----------|-------------|
| `RestrictWithdrawal` | `(address user, uint32 newCooldown)` | User withdrawal cooldown extended |
| `DisallowWithdrawal` | `(address user)` | User withdrawal blocked entirely |
| `ResetPersonalCooldown` | `(address user)` | Personal cooldown reset to default |
| `LargeWithdrawalUnscaledThresholdSet` | `(TokenId tokenId, uint256 newThreshold)` | Threshold for "large withdrawal" detection |
| `RestrictedCooldownSet` | `(uint32 newRestrictedCooldown)` | Restricted cooldown duration changed |

### Zone Responder Events (IZoneResponder)

| Event | Signature | Description |
|-------|-----------|-------------|
| `RedGlobalCooldownSet` | `(uint32 newGlobalCooldown)` | Red zone: global cooldown set |
| `RedLiqSettingsSet` | `(MarketId marketId, LiqSettings newLiqSettings)` | Red zone: liquidation settings tightened |
| `RedRateDeviationConfigSet` | `(MarketId marketId, RateDeviationConfig newRateDeviationConfig)` | Red zone: rate bounds tightened |
| `WhiteGlobalCooldownSet` | `(uint32 newGlobalCooldown)` | White zone: global cooldown restored |
| `WhiteLiqSettingsSet` | `(MarketId marketId, LiqSettings newLiqSettings)` | White zone: liquidation settings restored |
| `WhiteRateDeviationConfigSet` | `(MarketId marketId, RateDeviationConfig newRateDeviationConfig)` | White zone: rate bounds restored |

### Factory Events

| Event | Signature | Source |
|-------|-----------|--------|
| `MarketCreated` | `(address market, MarketImmutableDataStruct immData, MarketConfigStruct config)` | `IMarketFactory` |
| `AMMCreated` | `(address amm, bool isPositive, AMMCreateParams createParams, AMMSeedParams seedParams)` | `IAMMFactory` |
