---
description: Log of significant KB updates
last_updated: 2026-03-18
related: []
---

# Changelog

## 2026-03-18

- Design notes added to 6 contract docs: agent UX (`access-control.md`), LP non-transferability (`amm.md`), FIndex = Floating Index not Funding Index (`funding-oracle.md`), monolithic `orderAndOtc` for gas (`order-lifecycle.md`), deleverage winner check in DeleveragerFacet (`liquidation.md`), `maximizeProfit=false` pushes AMM rate to book rate (`bot-math-libs.md`)
- New `contracts/router-math-libs.md` — SwapMath and LiquidityMath with full derivations

## 2026-03-17

- `contracts/bot-math-libs.md` full rewrite as mathematical proof document (HR monotonicity, liqAllInRate derivation, piecewise MM, TickSweepState)
- PR review pass: synced 50 PRs into 5 docs (OTCModule, ConditionalModule, DepositModule, calcSwapSize, restrictedCooldown, etc.)
- New `contracts/testing.md` — 82-file Foundry test suite documentation
- Rewritten `contracts/deployment.md` — 7-phase deployment, 4 proxy patterns, CREATE3, EIP-7702 batching
- New `contracts/cross-chain.md` — hub-spoke model, CrossChainPortal, LayerZero OFT bridges

## 2026-03-16

- New `contracts/bot-math-libs.md` — 4 math libraries (SwapBoundMath, LiquidationMath, ArbitrageMath, SettleSimMath) with formula derivations
- 4 offchain bot docs: `offchain-bots-overview.md`, `offchain-failsafe-bots.md`, `offchain-backend-triggerers.md`, `offchain-backend-responders.md`
- Initial 16 contract docs created (architecture, storage, access control, types, order lifecycle, settlement, margin, liquidation, AMM, oracles, deposits, events/errors, bots, invariants, deployment). Merged deprecated docs from `pendle-core-v3` documentation branch

---

## 2026-03-14 (dev-docs sync — PRs #223 and #226)

### Notable additions in dev-docs (no KB duplication needed — references updated)

- **Bot Infrastructure** now publicly documented in `HighLevelArchitecture.mdx`: Liquidation Bot (health ≤ 1.0), Force-Cancel Bot (risky accounts + out-of-bound rates), CLO Bot (toggles CLO on OI cap).
- **CLO `exemptCLOCheck` flag** documented in `Margin.mdx` — whitelisted accounts are exempt from CLO restrictions.
- **Personal margin factors for MMs** documented in `Margin.mdx` — whitelisted MMs can have custom `kIM`/`kMM` queryable via `Market.getMarginFactor()`.
- **Rate bound errors** clarified in `OrderBook.mdx`: "Large Rate Deviation" (taker fills) vs "Rate too far off" (maker limit orders).
- **TWAP mark rate oracle** section added to `OrderBook.mdx`.
- **Error handling table + retry strategy** added to `best-practices.mdx`.
- **Settlement timing** (hourly cadence, ~30s after the hour) confirmed correct in `Settlement.mdx`.

### KB updates triggered by dev-docs sync

- **`realtime-response-protocol.md`**: bot note updated — Liquidation/Force-Cancel/CLO bots now have public docs; remaining 4 bots still internal-only.
- **`params-values-production.md`**: CLO Whitelist section now explains the `exemptCLOCheck` flag mechanism with a reference to `Margin.mdx`.
- **`market-making-terms-nayt.md`**: added §6 Margin Factors — documents that whitelisted MMs can have custom `kIM`/`kMM`; flags Nayt's actual values as still needing team input.

### Still absent from dev-docs (suggested additions)

- Market maturity / expiry lifecycle (what happens to positions and orders at maturity)
- AMM mechanics page
- FIndex Oracle explainer (how funding rates get on-chain)
- End-to-end P&L worked example

---

## 2026-03-14 (PR #2 merge + follow-up fixes)

### Resolved via PR #2 (vtd12)

- **Slash-separated thresholds explained** — added note to `params-values-production.md`: values like `H_TH = "2/1.8/1.5"` are Lv1/Lv2/Lv3 thresholds; alert fires on each crossing.
- **LC(10%) vs LC(35%) explained** — added note to `params-values-staging.md`: production uses LC35 for more stable estimates.
- **Markets 23 & 24 TOML files added** — `BTCUSDT-BN-T-260326.toml` and `ETHUSDT-BN-T-260326.toml` renamed and corrected to `23_BTCUSDT-BN-T-260327.toml` and `24_ETHUSDT-BN-T-260327.toml`.
- **`alert-specs.md` substantially updated** — new Level 1.2 (pre-settlement deleverage protocol), Level 1.1 contacts corrected, Level 1.3 trigger clarified, stale `max_FR_deviation_factor /= 3` removed from near-maturity section, list numbering fixed throughout.
- **Cross Markets OrderBounds and AutomaticResponses added** to `params-values-production.md`.
- **`max_FR_deviation_factor` global default documented** — formula: `0.8 * t_threshold/t_delta * k_MM` (per-market derived, not a fixed constant).
- **`t_delta` defined** in `params-definitions.md` — time interval between two consecutive settlements.

### Follow-up fixes (post-merge)

- **UV description re-applied** in `realtime-response-protocol.md` — linter had reverted "liquidate-able but not being liquidated" back to "near liquidation"; corrected again.
- **TOML filenames updated** in `market-params-overview.md` `[MaturityAdjustment]` markets list — now references `23_BTCUSDT-BN-T-260327.toml` and `24_ETHUSDT-BN-T-260327.toml`.
- **Slash-threshold note tightened** — clarified that the three values map to Lv1/Lv2/Lv3 respectively.
- **`max_FR_deviation_factor` note added** — flagged as per-market derived formula, not a fixed global constant.

### Outstanding issues (requires team input)

- **[OPEN — vtd12]** Should `[MaturityAdjustment]` apply to all markets? Currently only 3 markets have it. If it should be universal, the remaining markets are missing required configuration.
- **[OPEN — Duong]** Deleverage points: formal zone-metric definition and White/Yellow/Red thresholds needed for `zone-table.md`.
- **[OPEN]** Core Margin global defaults still undocumented in `params-values-production.md` — `kIM`, `kMM`, `I_threshold`, `t_threshold` global defaults (if they exist) not yet added.
- **[OPEN]** `risk/alert-specs.md` — escalation contacts section may still be stale (Vu/Duong/Long/Hiep/Minh — confirm all still current).
- **[OPEN]** Market listing criteria — process undocumented (`markets/market-overview.md`).

---

## 2026-03-10 (Round 3 fixes)

### Round 5 fixes (team-input items resolved)

- **Riverside and Flowdesk re-categorized** in `known-addresses.yaml` — both moved to "Former external market makers"; no longer active. Flowdesk also removed from `markets.yaml` market 40 `market_makers` field and from `liquidity-overview.md`. Nayt is now the only active external MM.
- **Internal MMs documented** — `_PathInD` and `_PathD` now explicitly noted as covering all markets in `known-addresses.yaml` (section comment), `liquidity/liquidity-overview.md` (new "Internal market makers" section), and `markets/markets.yaml` (header comment clarifying `market_makers` field tracks external MMs only; empty list means internal-only coverage).
- **`H_f` duplicate removed** from `params-values-staging.md` "Alerts related" table — same fix applied to staging as was done to production in Round 4.
- **`t_threshold` in `alert-specs.md` near-maturity** — clarified it refers to the per-market TOML `[Margin]` value; also fixed stale path reference (`Zone_table.md` → `risk/global/zone-table.md`).

### Outstanding issues (requires team input)

- **[2.2.1 — PARTIAL]** `params-values-production.md` global sections: OrderBounds and AutomaticResponses now added (PR #2). Still missing: Core Margin globals (kIM, kMM, I_threshold, t_threshold) and AMM globals.
- **[RESOLVED via PR #2]** Slash-separated threshold values — explained as Lv1/Lv2/Lv3.
- **[RESOLVED via PR #2]** LC(10%) vs LC(35%) — documented.
- **[RESOLVED via PR #2]** Missing TOMLs for markets 23 & 24 — files added and corrected.
- **[RESOLVED via PR #2]** `alert-specs.md` substantially updated by vtd12.
- **[OPEN]** Flowdesk removed as active MM — addresses retained in `known-addresses.yaml` for historical monitoring.
- **[3.2.6 — OPEN]** Market listing criteria — process/thresholds for listing new markets undocumented.

### Round 4 fact-check fixes

- **[4.1.1 — N/A]** `_Market2AMM` / `_Market3AMM` flagged as missing from `known-addresses.yaml` — confirmed not needed there; those addresses belong only in the CLO whitelist in `params-values-production.md`. CHANGELOG [1.1.7] claim was inaccurate.
- **[4.1.2] Removed duplicate `H_f`** from `params-values-production.md` "Lv2 Alerts related" table — was listed there and in Theory params; removed the redundant Lv2 row.
- **[4.1.3] Updated `liquidity-overview.md`** external MM section — "only Nayt" → lists both Nayt and Flowdesk (Flowdesk terms still pending in `market-makers.yaml`).
- **[4.1.4] Fixed `params-definitions.md` typo** — `### KIM` → `### kIM` to match all TOML files and schema docs.
- **[4.1.5] Removed V2 legacy language from `mechanics/litePaper.md`** — "(underlying APY in V2)" removed; "in Pendle" → "in Boros".
- **[4.1.6] Fixed `market-params-overview.md` AMM schema** — `fee_rate` and `oracle_twap_duration` Required: Yes → No (confirmed optional per HYPE market design).
- **[4.1.7] Aligned CLO Whitelist labels in `params-values-production.md`** — "bot controller (for arbitrage)" → `_BotController`; "markRatePusher" → `_MarkRatePusher`; "Market2 AMM" → `_Market2AMM`; "Market3 AMM" → `_Market3AMM`. Now matches `known-addresses.yaml` tag convention.
- **[4.2.1] Dropped `last_updated` field** from `liquidity/liquidity-overview.md`, `risk/risk-overview.md`, `risk/alert-specs.md`, `markets/market-overview.md` — field gets stale and is no longer maintained.

### Structural improvements (clarity, deduplication, LLM-friendliness)

- **Removed duplicate tables** from `liquidity/market-making-terms-nayt.md` §7/8/9 (multipliers, rate thresholds, R1/R2) — values were duplicated from `market-makers.yaml`; replaced with a §5 reference section pointing to the YAML as source of truth. Fixed missing §5 section number (was jumping §4 → §6).
- **Fixed broken internal paths:** `CLAUDE.md` `risk/params/README.md` → `risk/market-params/market-params-overview.md`; `markets/market-overview.md` `risk/params folder` → `risk/market-params/`; `realtime-response-protocol.md` `global-params/zone-table.md` → `risk/global/zone-table.md`.
- **Fixed vague Mechanics B/C references** in `risk/risk-overview.md` → now point to `mechanics/risk-control-mechanisms.md` sections by name.
- **Replaced TODO in `risk/realtime-response-protocol.md`** zone metrics section with concise definitions + references to `params-definitions.md` and `zone-table.md`. Rewrote bot system section as a proper table. Updated frontmatter `last_updated`.
- **Clarified OUTDATED scope** in `risk/alert-specs.md` — added note that escalation contacts may be stale but trigger formulas and level structure remain valid.
- **Cleaned up Liquidity Score** in `liquidity/liquidity-overview.md` — removed TODO, formatted formula in LaTeX, clarified tier definitions.
- **Expanded `overview/overview.md`** from 3 lines to a useful LLM entry point: added Long/Short explanation, key concepts table, and "where to go next" guide.
- **Expanded `user-acquisition/user-acquisition-overview.md`** — added speculation strategies section (long/short rate, cross-venue plays) so the file is self-contained, not just a pointer.
- **Added Flowdesk note** to `markets/markets.yaml` — Flowdesk appears as MM for market 40 but has no entry in `market-makers.yaml`; flagged for future documentation.

### Round 3 fact-check fixes

- **[3.1.1] Added missing `maturity` field** to `risk/market-params/March2026/40_ETHUSDT-OK-T-260327.toml` and `41_ETHUSDC-HL-T-260327.toml` — both had `margin_type` but no `maturity = "Mar 27 2026 00:00 UTC"`, unlike all other 15 active market TOMLs.
- **[3.1.2] Expanded `hard_OI_cap` schema** in `risk/market-params/market-params-overview.md` — documented all three real-world formats (dollar-shorthand string `$20M`, raw integer `20_000_000`, native-token count `200` BTC / `10000` ETH) with a format note explaining unit interpretation by collateral type.
- **[3.2.1] Documented `[MaturityAdjustment]` schema** in `risk/market-params/market-params-overview.md` — added field table for `near_maturity_k_MD` with observed values and list of markets that use it. Closes **[2.2.2]**.
- **[3.2.2] Populated `risk/global/zone-table.md`** — replaced TODO placeholder with full zone classification tables (Default and Near-Maturity), metric definitions summary, PD soft zone, liquidity drop alert params, and complete production parameter reference table. All values sourced from `params-values-production.md`.
- **[3.2.5] Added `Backend/2.agent.mdx`** to `INDEX.md` Dev Docs Reference under Backend/Integration — covers delegated EVM wallet, root wallet, agent permissions, and CLO whitelisting.

### Also fixed in this round (closing stale open issues)

- **[1.1.6 — CLOSED]** HYPE rate threshold inconsistency in `market-making-terms-nayt.md` — resolved by deduplication rewrite: §3 HYPE example and §8 rate threshold table (which omitted HYPE) were both removed; HYPE has no assigned MM so it no longer appears in the terms doc.
- **[2.2.5 — CLOSED]** `risk/realtime-response-protocol.md` zone metrics TODO — replaced with concise definitions and references to `params-definitions.md` / `zone-table.md`.
- **[3.2.3 — CLOSED]** `liquidity/liquidity-overview.md` Liquidity Score TODO — replaced with LaTeX formula and clarified tier definitions.
- **[3.1.3 — CLOSED]** HYPE TOML `[AMM]` missing fields — confirmed intentional by design.
- **[3.1.4 — CLOSED]** SOL markets no `[AMM]` section — confirmed intentional; schema doc updated.

### Outstanding issues (requires team input)

- **[1.1.5 — CLOSED]** Deleverage threshold ambiguity resolved: `H_d_theoretical = 0.6` is the solvency proof floor; bot-enforced threshold is 0.7 (more conservative, satisfies the theoretical requirement). `params-values-production.md` Theory params section updated with a two-column table and explanatory note.
- **[2.2.1 — OPEN]** `risk/global/params-values-production.md` missing global sections: Core Margin, Oracle, AMM, and AutomaticResponses production values not documented. Needs team input.
- **[3.2.4 — OPEN]** `risk/alert-specs.md` — OUTDATED scope note added; full rewrite still pending team review of current alert spec.
- **[3.2.6 — OPEN]** `markets/market-overview.md` market listing criteria sparse — actual criteria for listing new markets undocumented. Needs team input.
- **[OPEN]** Flowdesk MM terms undocumented — Flowdesk listed as market maker for market 40 (`ETHUSDT-OK-T-260327`) in `markets.yaml` but has no entry in `liquidity/market-makers.yaml`. Needs Flowdesk terms to be added.

## 2026-03-10

### Round 2 fact-check fixes (cross-referenced against dev-docs submodule, staging params, market TOML files)

- **[2.1.1] Fixed cooldown** in `risk/global/params-values-production.md`: Global cooldown 30 min → **15 min** (confirmed correct value).
- **[2.1.2] Rewrote `[Margin]` schema** in `risk/market-params/market-params-overview.md`: removed wrong field `health_ratio_threshold`; added `I_threshold`, `t_threshold`, `critical_health_ratio` (optional), `no_order_health_ratio` (optional). Also corrected `[OrderBounds]` field names (`limit_Order_Upper/Lower_Slope/Const`) and `[AMM]` fields (`initial_supply_cap_usd`, `oracle_twap_duration`, `min_rate`, `max_rate`, `initial_rate`, `initial_size`, `flip_liquidity`, `initial_cash`). Added full `[AutomaticResponses]` field table. Clarified `max_FR_deviation_factor` is optional in `[Oracle]`.
- **[2.1.3] False positive** — `60_BTCUSDC-HL-$-260327.toml` already had `maturity` field. No change needed.
- **[2.1.5] Added disclaimer** to `mechanics/litePaper.md` example section: parameters are illustrative and may not reflect current production values.
- **[2.1.6] Aligned MM naming** in `risk/global/params-values-production.md` CLO whitelist: "Internal MM 1" → `_PathInD` (consistent with `known-addresses.yaml`).
- **[2.1.7] Dropped `launch_date` field** from all 19 markets in `markets/markets.yaml` — field was always `null` and not tracked.

### Round 1 fact-check fixes (cross-referenced against documentation repo dev docs)

- **[1.1.3] Fixed typo** in `overview/overview.md`: "Borow" → "Boros".
- **[1.1.4] Fixed stale product name** in `mechanics/litePaper.md`: "Pendle V3" → "Boros" in Alice/Bob example.
- **[1.1.7] Added missing protocol bot addresses** to `known-addresses.yaml`: `_BotController`, `_MarkRatePusher`, `_Market2AMM`, `_Market3AMM` (sourced from CLO whitelist in `params-values-production.md`).
- **[1.1.8] Expanded market entrance fee** in `risk/global/params-values-production.md` to include per-asset token denominations (0.000008 BTC / 0.00027 ETH / $1 USDC-USDT), sourced from dev docs `Fees.mdx`.

### Missing documentation strategy (1.2)

- **[1.2] Adopted hybrid approach (Option C)** for missing mechanics/architecture documentation. Rather than duplicating dev docs content into KB files, the `INDEX.md` now has a `## Dev Docs Reference` section pointing directly to canonical files in the `dev-docs/` submodule. Topics covered: margin, orderbook, settlement, fees, architecture, contract references, API/SDK, stop orders, FAQ.
- **Added `dev-docs/` as a git submodule** (`pendle-finance/documentation`), replacing the local symlink `local-documentation-repo`. All path references in `INDEX.md` and `CLAUDE.md` updated from `../documentation/docs/boros-dev-docs/` to `dev-docs/docs/boros-dev-docs/`.
- **Updated `CLAUDE.md`** to document the submodule structure (init/update commands), lookup table, and the rule against duplicating dev docs content into the KB.
- No new KB files were created for 1.2 items — all were already covered by dev docs.

### Round 2 additions

- **[2.2.4] Added `Backend/1. glossary.mdx`** to `INDEX.md` Dev Docs Reference under Core Concepts — covers key terms (Mark Rate, Mid Rate, AMM Implied Rate, tick, APR format, account types, TIF types).

### Issues raised in Round 2 (all resolved in Round 3)

- **[1.1.6 — CLOSED]** HYPE rate threshold inconsistency — resolved by §7/8/9 deduplication rewrite.
- **[2.2.2 — CLOSED]** `[MaturityAdjustment]` schema — documented in Round 3 (`near_maturity_k_MD` field table added).
- **[2.2.5 — CLOSED]** `realtime-response-protocol.md` zone metrics TODO — resolved in Round 3 structural improvements.

## 2026-03-06

- **Initial structure created.** Set up directory layout, INDEX.md, CLAUDE.md, and skeleton files for all topics. No content yet — skeletons contain frontmatter and section headers only.
