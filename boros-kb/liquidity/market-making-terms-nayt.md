---
description: Nayt market maker terms, fee structure, and quoting requirements
last_updated: 2026-03-10
related:
  - liquidity/liquidity-overview.md
  - liquidity/market-makers.yaml
---

# Market Making Terms for Nayt

## Baseline Terms

These are the **baseline quoting terms** defined for **Binance ETH or BTC markets**. For other markets, a **market-specific multiplier** (`marketMultiplier`) will apply to adjust the depth requirement:

- **Adjusted Depth Requirement** for other markets:

$$\text{Adjusted Depth} = \frac{\text{Baseline Depth}}{\text{marketMultiplier}}$$

  Example: If `marketMultiplier = 2`, then the market's required depth is **half** the baseline depth.

### Satisfactory requirements
- An epoch is considered "satisfactory" if the uptime (of satisfying the terms) is >= 95%, or the market share in terms of notional maker volume is >= 50%

---

## 1. Fee and Market Coverage

- **Weekly Fee per Market:** $1,250 * scaleFactor
- There is a default scaleFactor = 1 for all markets

---

## 2. Depth Requirements

### Tier 1
- **Price Range:** R1%
- **Depth per Side (Baseline):**

$$D_1 = \min\left(\frac{600{,}000}{\text{months to maturity}},\ 2{,}000{,}000\right) \times \text{scaleFactor}$$

### Tier 2
- **Price Range:** R2%
- **Depth per Side (Baseline):**

$$D_2 = \min\left(\frac{2000000}{\text{months to maturity}},\ 6000000\right) \times scaleFactor$$

---

## 3. Price Range Interpretation

The quoted range (R1% for Tier 1, R2% for Tier 2) is dynamically scaled based on the **Rate Threshold** of each market:

- If **mid-rate ≥ Rate Threshold**:

$$\text{Range1} = R1\% \times \text{mid-rate}$$

- If **mid-rate < Rate Threshold**:

$$\text{Range1} = R1\% \times \text{Rate Threshold}$$

### Example:
- ETH/BTC markets have Rate Threshold = 6%, R1% = 6.6%

If the market has a mid-rate of 4%:
- Range = 6.6% × 6% = **0.396%** (uses threshold since mid-rate < threshold)

If the mid-rate exceeds the threshold, the range simply becomes R1% of the actual mid-rate.

---

## 4. Spread Validation at Required Depth

For a **depth requirement** $D$ at a certain tier:
- Let $a$ = rate at depth $D$ on the **ask** side
- Let $b$ = rate at depth $D$ on the **bid** side
- Then:

$$a - b \leq \text{Price Range for that tier}$$

This ensures the effective spread across the required depth remains within the tier's defined price bounds.

### Example:
- Tier: 5% range
- Depth: $500,000
- Mid-rate: 4.25%
- **Rate Threshold**: 6%
- Orders:
  - Ask side:
    - 4.4%: $400k short
    - 4.3%: $100k short
  - Bid side:
    - 4.2%: $100k long
    - 3.9%: $1M long
- At $500k ask depth → rate = 4.4%
- At $500k bid depth → rate = 3.9%
- Spread = 4.4% − 3.9% = **0.5%**
- Price range cap = 5% × 6% = 0.3%
- Result: **Fails** the requirement (0.5% > 0.3%)

---

## 5. Market-Specific Parameters

Per-market values for multipliers, rate thresholds, and R1%/R2% are in **`liquidity/market-makers.yaml`** (the source of truth). Key fields per market group:

- `rate_threshold` — the Rate Threshold used for range calculation (§3 above)
- `tier1.r_pct` / `tier2.r_pct` — R1% and R2% for each tier
- `tier1.multiplier` / `tier2.multiplier` — the `marketMultiplier` for depth adjustment

**How to read multipliers:** A multiplier > 1 reduces the required depth vs the BTC/ETH baseline (e.g. multiplier 5 for XAU = required depth divided by 5).

---

## 6. Margin Factors

Whitelisted market makers can have **personal margin factors** (`kIM`, `kMM`) that differ from the global market defaults. This allows tighter or looser margin requirements than regular users.

Effective margin factors for any account can be queried on-chain via [`Market.getMarginFactor()`](../../dev-docs/docs/boros-dev-docs/Contracts/Market.mdx).

> **⚠️ Team input needed:** What are Nayt's actual `kIM`/`kMM` values, if they differ from global defaults?

---

## 7. Near-Maturity Adjustments

To reduce quoting obligations near maturity, requirements are relaxed as follows:

Let's say the normal requirement is a **price range of** $x\%$ and a **depth of** $D$, and there are $s$ settlement intervals remaining.

### Binance (8hr settlements)
- Adjustment starts **5 days** before maturity

- Adjusted **Price Range**:

$$x\% \times \left(\frac{15}{s}\right)^{1/1.9}$$

- Adjusted **Depth**:

$$D \times \left(\frac{s}{15}\right)^{1/1.3}$$

### Hyperliquid (hourly settlements)
- Adjustment starts **3 days** before maturity

- Adjusted **Price Range**:

$$x\% \times \left(\frac{72}{s}\right)^{1/2.4}$$

- Adjusted **Depth**:

$$D \times \left(\frac{s}{72}\right)^{1/1.7}$$

Where $s$ = number of remaining settlement intervals.
