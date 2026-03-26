---
description: Schema documentation for per-market TOML parameter files
last_updated: 2026-03-10
related:
  - risk/risk-overview.md
  - risk/global/params-definitions.md
---

# Per-Market Parameter TOML Schema

This directory contains per-market risk and trading parameters in TOML format, following the `boros-research/MarketParams` structure.

## File Organization

Files are organized by maturity month directories and named with the format:

```
<id>_<PAIR>-<VENUE>-<TYPE>-<EXPIRY>.toml
```

Example: `60_BTCUSDC-HL-$-260327.toml`

## Top-Level Fields

| Field         | Type   | Description                                      |
|---------------|--------|--------------------------------------------------|
| `margin_type` | String | Margin mode: `"Cross"` or `"Isolated"`           |
| `maturity`    | String | Maturity date, e.g. `"Mar 27 2026 00:00 UTC"`   |

## Sections

### `[Margin]`

Margin parameters controlling initial and maintenance margin requirements.

| Field                    | Type   | Required | Description                                                                 |
|--------------------------|--------|----------|-----------------------------------------------------------------------------|
| `kIM`                    | Float  | Yes      | Initial margin factor (e.g. `1/3.2`)                                        |
| `kMM`                    | Float  | Yes      | Maintenance margin factor (e.g. `2/9`)                                      |
| `I_threshold`            | Float  | Yes      | Rate floor for margin calculations (e.g. `0.03` = 3%). Orders below this rate use the floor instead of the actual rate for margin |
| `t_threshold`            | String | Yes      | Time-to-maturity floor for margin calculations (e.g. `"10 days"`)           |
| `critical_health_ratio`  | Float  | No       | Health ratio at which the system can trigger emergency actions (e.g. `0.4`) |
| `no_order_health_ratio`  | Float  | No       | Health ratio below which new orders are blocked (e.g. `0.95`)               |

### `[OrderBounds]`

Bounds on order placement to prevent erroneous or manipulative orders.

| Field                      | Type  | Required | Description                                                       |
|----------------------------|-------|----------|-------------------------------------------------------------------|
| `k_MD`                     | Float | Yes      | Max rate deviation factor for taker fills ("Large Rate Deviation")|
| `k_CO`                     | Float | Yes      | Closing order bound — more lenient bound for position-reducing orders |
| `limit_Order_Upper_Slope`  | Float | Yes      | Slope of upper limit order bound (long orders can't exceed `markRate × slope`) |
| `limit_Order_Lower_Slope`  | Float | Yes      | Slope of lower limit order bound (short orders can't go below `markRate × slope`) |
| `limit_Order_Upper_Const`  | Float | No       | Constant additive term for upper limit order bound near zero rate  |
| `limit_Order_Lower_Const`  | Float | No       | Constant additive term for lower limit order bound near zero rate  |

### `[MitigatingMeasure]`

Hard caps and circuit breakers.

| Field        | Type         | Required | Description                                          |
|--------------|--------------|----------|------------------------------------------------------|
| `hard_OI_cap`| String/Float | Yes      | Maximum one-sided open interest. Format depends on collateral type — see note below. |

**`hard_OI_cap` format note:** Three representations are used across market files:
- **Dollar-shorthand string** (USD-denominated markets): `$20M` — interpreted as $20,000,000 USD
- **Raw integer** (USD-denominated markets, alternate style): `20_000_000` — same value in USD
- **Native token count** (BTC/ETH-collateral markets): `200` for BTC markets (= 200 BTC), `10000` for ETH markets (= 10,000 ETH)

The correct interpretation depends on the market's collateral token, not the numeric format alone.

### `[Oracle]`

Oracle configuration for mark rate and rate deviation.

| Field                       | Type   | Required | Description                                                                 |
|-----------------------------|--------|----------|-----------------------------------------------------------------------------|
| `mark_rate_twap_duration`   | String | Yes      | TWAP window for mark rate calculation (e.g. `"5 min"`)                      |
| `max_FR_deviation_factor`   | Float  | No       | Bound on accepted funding rate from oracle: `[markRate ± factor × markRate]`. Omit to use global default |

### `[AMM]` (optional)

Automated market maker parameters. Not all markets have an AMM — absence of this section means the market operates as a pure CLOB with no AMM. For example, SOL markets (`58_SOLUSDC-HL`, `59_SOLUSDC-LT`) intentionally have no AMM section.

| Field                  | Type   | Required | Description                                                  |
|------------------------|--------|----------|--------------------------------------------------------------|
| `fee_rate`             | Float  | No       | AMM trading fee rate (e.g. `0%` or `0.0005`). Present in most markets; may be omitted. |
| `initial_supply_cap_usd` | String | Yes    | Maximum AMM liquidity supply in USD (e.g. `$15k`)           |
| `oracle_twap_duration` | String | No       | TWAP duration for AMM oracle (e.g. `"1 min"`). Present in most markets; may be omitted. |
| `min_rate`             | Float  | Yes      | Lower bound on AMM rate (e.g. `0.01` = 1%)                  |
| `max_rate`             | Float  | Yes      | Upper bound on AMM rate (e.g. `0.5` = 50%)                  |
| `initial_rate`         | Float  | Yes      | Starting implied rate for AMM (e.g. `0.05` = 5%)            |
| `initial_size`         | Float  | Yes      | Initial position size seeded into AMM                        |
| `flip_liquidity`       | Float  | Yes      | Position size at which AMM liquidity profile flips           |
| `initial_cash`         | Float  | Yes      | Initial cash seeded into AMM                                 |

### `[AutomaticResponses]` (off-chain)

Adjusted parameters automatically applied when the market enters the Red Zone.

| Field                            | Type  | Description                                                       |
|----------------------------------|-------|-------------------------------------------------------------------|
| `new_liquidation_incentive_base` | Float | Override liquidation incentive base in Red Zone                   |
| `new_liquidation_incentive_slope`| Float | Override liquidation incentive slope in Red Zone                  |
| `new_k_MD`                       | Float | Override max rate deviation factor in Red Zone                    |
| `new_k_CO`                       | Float | Override closing order bound in Red Zone                          |
| `new_limit_Order_Upper_Slope`    | Float | Override upper limit order slope in Red Zone                      |
| `new_limit_Order_Lower_Slope`    | Float | Override lower limit order slope in Red Zone                      |
| `new_limit_Order_Upper_Const`    | Float | Override upper limit order constant in Red Zone (if applicable)   |
| `new_limit_Order_Lower_Const`    | Float | Override lower limit order constant in Red Zone (if applicable)   |

### `[MaturityAdjustment]` (off-chain, optional)

Near-maturity parameter overrides that take effect as expiry approaches. Currently only a subset of market files include this section.

> **⚠️ Team input needed (@vtd12):** Should near-maturity adjustments apply to *all* markets? If so, markets without a `[MaturityAdjustment]` block may be missing required configuration.

| Field              | Type  | Description                                                                 |
|--------------------|-------|-----------------------------------------------------------------------------|
| `near_maturity_k_MD` | Float | Overrides `k_MD` (max rate deviation) as maturity approaches — tightens order bounds to reduce risk near expiry. Observed values: `0.35` (BTC/ETH legacy markets), `0.5` (ETHUSDC-HL) |

**Markets using `[MaturityAdjustment]`:** `41_ETHUSDC-HL-T-260327.toml` (`near_maturity_k_MD = 0.5`), `23_BTCUSDT-BN-T-260327.toml` and `24_ETHUSDT-BN-T-260327.toml` (both `near_maturity_k_MD = 0.35`).
