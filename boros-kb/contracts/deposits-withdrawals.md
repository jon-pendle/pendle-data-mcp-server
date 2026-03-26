---
description: Deposit, withdrawal, and cash transfer flows — 18-decimal normalization, 3-step withdrawal with cooldown, DepositBox, treasury operations
last_updated: 2026-03-16
related:
  - contracts/architecture.md
  - contracts/storage-layout.md
  - contracts/access-control.md
---

# Deposits and Withdrawals

All collateral in Boros flows through MarketHub. Deposits add to a user's `cash` balance; withdrawals remove from it after a mandatory cooldown. Internal cash transfers move funds between accounts without touching the underlying ERC20.

---

## Deposit Flow

### Standard Deposit

The root wallet calls via Router into `DepositModule.deposit()`. The module calls:

```
MarketHubEntry.vaultDeposit(acc, unscaled)
```

This function:

1. Transfers the ERC20 token from the Router to MarketHub.
2. Scales the amount to 18 decimals: `scaled = unscaled × scalingFactor`.
3. Adds `scaled` to `acc[user].cash`.

The deposit is immediately available for trading — there is no lock-up period on the deposit side.

### DepositBox

**Source**: `DepositBoxFactory` deploys per-user deterministic contracts via CREATE2.

Each user gets a unique `DepositBox` contract at a deterministic address (derived from the user's root address and a `boxId`). The DepositBox supports:

- **`approveAndCall()`**: Allows token swaps via an external DEX before depositing. The DepositBox approves a DEX router, executes the swap, then deposits the output token into Boros. This enables depositing from any token, not just the collateral token.
- **Manager-controlled withdrawals**: The DepositBox manager (set at deployment) controls withdrawal permissions.
- **`boxId` tracking**: Multiple boxes per user are possible, each with a unique `boxId`.

The `DepositModule.depositFromBox()` function pulls funds from the user's DepositBox into their Boros account.

---

## 18-Decimal Normalization

All internal accounting uses 18 decimal places regardless of the underlying token's decimals.

| Function | Formula | Path |
|----------|---------|------|
| `_toScaled()` | `unscaled × scalingFactor` | Deposit (external → internal) |
| `_toUnscaled()` | `scaled / scalingFactor` | Withdrawal (internal → external) |

Where `scalingFactor = 10^(18 - tokenDecimals)`, stored in `TokenData` at token registration time.

For example, USDC (6 decimals) has `scalingFactor = 10^12`. Depositing 1,000 USDC (1,000 × 10^6 raw) becomes 1,000 × 10^18 internally.

This normalization ensures that margin calculations, position sizing, and fee computations work uniformly regardless of token precision.

---

## Withdrawal Flow (3-Step)

Withdrawals use a request-wait-finalize pattern to prevent front-running of liquidations and to give the risk system time to react.

### Step 1: Request — `requestVaultWithdrawal`

```
requestVaultWithdrawal(root, tokenId, unscaled)
```

Called by the root wallet via Router.

1. Converts `unscaled` to `scaled` via `_toScaled()`.
2. Deducts `scaled` from the user's `cash` balance.
3. Records a `Withdrawal` struct: `{start: block.timestamp, unscaled: accumulated}`. If a pending withdrawal already exists for this `(root, tokenId)` pair, the new amount accumulates onto the existing request and the `start` timestamp resets.
4. **Runs IM check** after deduction — if the user's remaining cash is insufficient to meet initial margin, the request reverts with `MMInsufficientIM`.

### Step 2: Wait — Cooldown Period

The user must wait for the cooldown to elapse before finalizing.

**`_getPersonalCooldown(root)`** returns:
- The user's personal cooldown if set (stored as bitwise-NOT `~t` to distinguish zero-cooldown from unset).
- Otherwise, the `globalCooldown` (configured by admin).

Both personal and global cooldowns are configurable. The personal cooldown allows the admin to impose stricter waiting periods on specific users (e.g., if a user has been flagged by `WithdrawalPolice`). The `WithdrawalPoliceFacet` sets a `restrictedCooldown` (distinct from infinite — PR #341) that is longer than the global cooldown but not permanent, allowing flagged users to still withdraw after a longer delay.

### Step 3: Finalize — `finalizeVaultWithdrawal`

```
finalizeVaultWithdrawal(root, tokenId)
```

**Callable by anyone** — not restricted to the root wallet. This is intentional: it allows bots or relayers to finalize on behalf of users.

1. Checks that `block.timestamp >= withdrawal.start + cooldown`.
2. Transfers the ERC20 amount (`withdrawal.unscaled`) to the `root` address.
3. Clears the withdrawal record.

If the cooldown has not elapsed, reverts with `MHWithdrawNotReady`.

### Cancel — `cancelVaultWithdrawal`

```
cancelVaultWithdrawal(root, tokenId)
```

Called by the root wallet via Router. Returns the pending withdrawal amount back to the user's `cash` balance. The withdrawal record is cleared. This is useful if the user changes their mind or needs the collateral for margin.

---

## Cash Transfers

**Source**: `MarketHubEntry.cashTransfer()`

Cash transfers move funds between `MarketAcc` accounts that share the same token, without any ERC20 movement.

### Allowed Transfer Paths

- **Cross account to cross-sub account** (and vice versa)
- **Cross account to isolated account** (and vice versa)
- **AMM exception**: The AMM's `MarketAcc` (`SELF_ACC`) can transfer with any same-asset `MarketAcc`. This is Router-only — used internally for AMM operations.

### Margin Check

The **payer** always gets an IM check after the transfer. If the transfer would leave the payer below initial margin, it reverts with `MMInsufficientIM`. The receiver is not checked — receiving cash can only improve margin.

---

## Treasury Operations

### `payTreasury`

```
payTreasury(root, tokenId, unscaled)
```

User pays from their `cash` balance to the treasury. The amount is deducted from `acc[user].cash` and added to `cashFeeData[tokenId].treasuryCash`. Used for gas balance top-ups in the agent system (agents need gas to execute on behalf of users).

### `vaultPayTreasury`

```
vaultPayTreasury(root, tokenId, unscaled)
```

Deposits ERC20 directly to the treasury, bypassing the user's cash balance. The token is transferred from the Router to MarketHub, scaled, and added to `treasuryCash`.

### Fee Collection

Fees accumulate in `cashFeeData[tokenId].treasuryCash` through:

- Settlement fee payments (`_processPayFee()`)
- Explicit `payTreasury` / `vaultPayTreasury` calls

The admin can collect accumulated treasury funds via a dedicated admin function. Treasury cash is tracked separately per token.

---

## Invariant

The cash conservation invariant guarantees:

```
sum(acc[user].cash for all users) + sum(cashFeeData[token].treasuryCash for all tokens)
    = total ERC20 held by MarketHub
```

Every deposit increases both the left side (user cash) and the right side (ERC20 balance) by the same scaled amount. Every withdrawal decreases both sides equally. Transfers and fee payments move value between terms on the left side without affecting the total. See `contracts/invariants.md` for the full invariant list.
