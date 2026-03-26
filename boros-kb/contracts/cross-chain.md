---
description: Cross-chain architecture — hub-spoke model, CrossChainPortal, DepositBox on spoke chains, LayerZero OFT bridges, full deposit flow
last_updated: 2026-03-17
related:
  - contracts/deposits-withdrawals.md
  - contracts/deployment.md
  - contracts/architecture.md
---

# Cross-Chain Architecture

Boros uses a hub-and-spoke model for cross-chain deposits. All trading happens on Arbitrum (the hub). Users on other chains deposit via spoke-chain DepositBoxes that bridge tokens through LayerZero OFT to the hub.

---

## Hub-Spoke Model

**Hub chain**: Arbitrum (chainId 42161, LayerZero EID 30110)
- All trading, settlement, and margin accounting happens here
- MarketHub, Router, Markets, AMMs — everything lives on Arbitrum
- DepositBox.MANAGER = Router

**Spoke chains**: Base, BSC, HyperEVM, Bera, Sonic, Mantle, Optimism, Plasma
- Only deposit infrastructure exists on spokes
- CrossChainPortal orchestrates bridging
- DepositBox.MANAGER = CrossChainPortal

### Key Addresses (Same on All Chains)

| Contract | Address |
|----------|---------|
| DepositBox Beacon | `0xDEB0BEA8882Baf5adb3B24b55D80e5610206C99D` |
| DepositBox Factory | `0xDEB0FAC888C33E3E7394c095FE3c4E3de760E12c` |

### Spoke-Only Contracts

| Contract | Address |
|----------|---------|
| CrossChainPortal | `0x370BCBDDc24dec593E26892a1a9A178bBD7c044E` |
| AccessController (spoke) | `0x2080808080262c1706598c9DBDD3a0cD3601e5ea` |

---

## DepositBox

Source: `contracts/deposit/DepositBox.sol`

Per-user deterministic contract deployed via CREATE2 from DepositBoxFactory. Address is derived from `keccak256(abi.encode(root, boxId))` — same `(root, boxId)` produces the same address on every chain.

### Properties

```
MANAGER: address (immutable)  // Router on hub, CrossChainPortal on spoke
OWNER: address                // User's root wallet
BOX_ID: uint32                // Box identifier (multiple boxes per user)
```

### `approveAndCall(call, nativeRefund)`

Executes an arbitrary call with token approval:
1. Approve `call.token` to `call.approveTo` for `call.amount`
2. Execute `call.callTo` with `call.data` (+ native value if applicable)
3. Clear approval
4. Refund excess native to `nativeRefund`

Used for both DEX swaps (before depositing) and OFT bridging (on spoke chains).

### Manager Split

The MANAGER controls who can call `approveAndCall()` and `withdrawTo()`:
- **Hub (Arbitrum)**: MANAGER = Router. The Router pulls tokens from the box into MarketHub on user request
- **Spoke chains**: MANAGER = CrossChainPortal. The Portal initiates OFT bridging from the box

This enforces that cross-chain deposits can only flow through the Portal → OFT → Router pipeline.

---

## CrossChainPortal

Source: `contracts/cross-chain/CrossChainPortal.sol`. Lives only on spoke chains.

### `bridgeOFT(root, boxId, token, amount, nativeFee)`

Bridges tokens from a user's DepositBox on the spoke chain to the same user's DepositBox on Arbitrum:

1. Look up OFT messenger for the token: `oftMessenger[token]`
2. Construct LayerZero `SendParam`:
   - `dstEid = 30110` (Arbitrum)
   - `to = bytes32(DepositBox address on hub)` — same deterministic address
   - `amountLD = amount`
3. Build an `ApprovedCall`:
   - Approve token to OFT messenger
   - Call `IOFT.send(sendParam, sendFee, nativeRefund)`
4. Execute via `DepositBox.approveAndCall(call, nativeRefund)`
5. OFT burns/locks tokens on spoke, mints/releases on hub

The Portal never holds user funds — it orchestrates the DepositBox to approve and send directly.

---

## LayerZero OFT Bridges

### OFT Implementations

| Contract | Chain | Purpose |
|----------|-------|---------|
| `NativeOFTAdapterImpl` | HyperEVM | Wraps native HYPE for bridging |
| `OFTImpl` | Arbitrum | Receives bridged HYPE as ERC20 |
| `NativeOFTAdapterImpl` | BSC | Wraps native BNB for bridging |
| `OFTImpl` | Arbitrum | Receives bridged BNB as ERC20 |

Both use LayerZero endpoint `0x1a44076050125825900e736c501f859c50fE728c`.

### LayerZero Endpoint IDs

| Chain | EID |
|-------|-----|
| Arbitrum (hub) | 30110 |
| Ethereum | 30101 |
| Base | 30184 |
| BSC | 30102 |
| HyperEVM | 30367 |
| Bera | 30362 |
| Sonic | 30332 |
| Mantle | 30181 |
| Optimism | 30111 |
| Plasma | 30383 |

### Transport

Messages routed through LayerZero V2:
- SendUln302 → LayerZero Protocol → ReceiveUln302 → Executor
- DVN validators: Horizen DVN + LayerZeroLabs DVN
- Confirmation: 15 block confirmations
- Max message size: 10,000 bytes

---

## Full Cross-Chain Deposit Flow

### Step 1: DepositBox Creation

User (or anyone) calls `DepositBoxFactory.deployDepositBox(root, boxId)` on the spoke chain. The box is created at a deterministic address. The same address exists (or can be created) on Arbitrum.

### Step 2: Fund the Box

User sends collateral tokens to their DepositBox address on the spoke chain. The tokens sit in the box contract.

### Step 3: Bridge via Portal

Authorized caller invokes `CrossChainPortal.bridgeOFT(root, boxId, token, amount)` with native fee for LayerZero gas:

```
Portal → DepositBox.approveAndCall()
       → OFT.send(dstEid=30110, to=DepositBox_on_Arbitrum)
       → LayerZero transport
```

### Step 4: Receive on Hub

OFT message arrives on Arbitrum. `OFTImpl.lzReceive()` credits tokens to the destination DepositBox address on Arbitrum. The box now holds bridged tokens with MANAGER = Router.

### Step 5: Deposit into MarketHub

User submits a signed `DepositFromBoxMessage`:

```
{
  root, boxId,
  tokenSpent,            // bridged token
  maxAmountSpent,
  accountId,             // target account (0 = primary)
  tokenId,               // MarketHub token ID
  minDepositAmount,      // slippage protection
  payTreasuryAmount,     // optional gas fee to treasury
  swapExtRouter,         // DEX router (if token swap needed)
  swapCalldata,          // DEX call data
  expiry, salt           // replay protection
}
```

A relayer submits this to `Router.depositFromBox()`, which:
1. Pulls tokens from DepositBox via `withdrawTo()` or `approveAndCall()` (if swap needed)
2. Calls `MarketHub.vaultDeposit(acc, amount)`
3. Tokens scaled to 18 decimals, added to user's cash balance

### Step 6: Trade

User can now trade on Boros with their deposited collateral.

---

## Design Rationale

### Why Deterministic Addresses?

Same `(root, boxId)` → same DepositBox address on every chain. The Portal on a spoke chain can compute the hub-side box address without any cross-chain lookup. OFT bridging targets that address directly.

### Why a 2-Step Deposit?

The bridge (Step 3) and the MarketHub deposit (Step 5) are separate operations. This allows:
- Token swaps between bridging and depositing (e.g., bridge USDC, swap to WETH, deposit as ETH collateral)
- Slippage protection on the deposit side
- Treasury fee payment in the same transaction
- Retry on either step independently if one fails

### Why Split MANAGER?

On spoke chains, only the Portal should be able to move box funds (into OFT bridging). On the hub, only the Router should move them (into MarketHub). The MANAGER field enforces this — different implementations for different chain roles.
