---
description: Overall risk management philosophy and framework
related:
  - risk/realtime-response-protocol.md
  - risk/alert-specs.md
  - risk/global/params-definitions.md
  - risk/global/params-values-production.md
  - risk/market-params/market-params-overview.md
  - mechanics/risk-control-mechanisms.md
---

# Risk Management in Boros

## Index
- This document: high-level risk management approach in Boros
- `realtime-response-protocol.md`: realtime response protocol (zones, bots)
- `alert-specs.md`: alert levels and escalation protocols
- `global/params-requirements.md`: mathematical invariants for on-chain parameters
- `global/params-values-production.md`: global param values for production
- `global/params-values-staging.md`: global param values for staging
- `global/params-definitions.md`: definitions of all parameters
- `global/zone-table.md`: zone threshold tables (White/Yellow/Red)
- `market-params/market-params-overview.md`: per-market TOML schema and directory

## Overview of Boros’ risk management approach

We have two main objectives for Boros’ risk management:
- 1. The **bottom line**: zero bad debt or loss of funds
- 2. Mitigate all risks affecting the stability and fairness of the system. This is achieved by:
    - 2a. Limiting risks through risk parameters settings
    - 2b. **Real time response protocol:** automatic and manual responses to abnormal scenarios

Protective on-chain mechanisms referenced throughout this document are detailed in `mechanics/risk-control-mechanisms.md`.

## 1. The bottom line: zero bad debt or loss of funds

We do three things to make sure of this:

- Firstly, in terms of the system design:
    - We have on-chain restriction on the actions users could do:
        - Max rate deviation: users can’t execute a market trade at a rate too far away from the current Mark Rate. See `mechanics/risk-control-mechanisms.md` §Max Rate Deviation.
        - Limit order bounds: users can’t long at too high a rate, or short at too low a rate (relative to the mark rate). See `mechanics/risk-control-mechanisms.md` §Max Bounds on Limit Orders.
    - We have “nuclear buttons” that we can push to derisk the system only in the most extreme scenarios:
        - Auto-deleverage:
        - Pausing: pause the system when there are something super extreme happening
        - Note that these nuclear buttons are **only the last resorts**. We will do everything we can in section 2b (Real time response protocol) to not have to use “nuclear buttons” at all.
    - We run bots to automatically push these “nuclear buttons” when necessary
    - **We have done a Mathematical proof on the system design:**
        - **Assuming** the on-chain restrictions we set, and we could run the bots to always push the “nuclear buttons” fast enough within certain conservative assumptions
        - **Then**, the system is **guaranteed to be solvent with zero bad debt**
        - We got Spearbit to verify the Mathematical proof
        - Proof paper is in ../mechanics/boros-proofs.tex
- Secondly, we make sure that our contract implementation of the system design is air tight
    - Similar to Pendle V2, we take contract security very seriously, with thorough testing, internal auditing and external auditing.
    - We got the two best audit firms (Spearbit and Chain Security) to audit our contract system, on top of our retainers (WatchPug)
    - Link to audit reports: https://github.com/pendle-finance/boros-core-public/tree/main/audits
- Thirdly, we have a withdrawal cooldown to prevent any potential exploits.
    - Basically, a user must wait for 15min to withdraw their funds. This renders all in-a-transaction attacks impossible (especially those involving flash loans).
    - If malicious activities are detected for a certain account, the withdrawal cooldown will be automatically increased or even paused.

## 2a. Limiting risks through risk parameters settings

We have multiple risk parameters to limit risks of the system. The most notable ones are:
1. Max leverage (from kIM)
2. TWAP duration of the Mark Rate
3. Max rate deviation and Limit Order bounds (as already mentioned in section 1)
4. I_threshold and T_threshold

The setting of these parameters is mostly about balancing the trade-off between risks to the system (and users) vs pushing for better user benefits and UX. For example, setting a super high max leverage will allow users to trade with very high capital efficiency. However, it might lead to significant risks and instability for the system like cascading liquidations leading to auto-deleveraging or market pausing, especially if the market is not mature enough.

Our general approach to setting these parameters is to **start very conservatively** and **scale things up very carefully** with the maturity level of the markets. Some important factors that contribute to the maturity level of the markets:

- The absolute size of the Boros markets (in total OI)
- The liquidity level of the markets (both in terms of absolute sizes in the orderbook as well as the distribution among the different users)
- The number of market participants and the distribution/concentration of their position sizes
- The stability of our own risk management system in dealing with extreme market events over time

By observing these different factors and doing deep dive studies on historical data, we will develop methodologies for adjusting the parameters to ensure that the risk controls are appropriate for the corresponding maturity level of the market.

## **2b. Real time response protocol:** automatic and manual responses to abnormal scenarios
- The exact mechanics is in realtime-response-protocol.md
- There are four parts to the realtime response protocol:
    - Firstly, we developed Risk Metrics to gauge how healthy/normal the market is. Without going into too much details, here are the brief description of some important metrics:
        - Liquidation Cost: metric to measure how good liquidity is, compared to the level of leverage in the market
        - Deleverage point: at what rate will a deleverage happen in the market
        - Price Deviation: Metric to measure how volatile the market is
        - Unhealthy volume: Metric to measure the amount of unhealthy positions
    - Secondly, we have “Cooling measures” we can push to cool down the market if necessary:
        - Close Only Mode: only allow users to close existing positions. This will stop any further market manipulation from happening (through opening new positions) if any
        - Lower max rate deviation: lower how far user can trade away from the current mark rate, which will slow down market movements
    - Thirdly, we have a “Zone-based” system for automatic responses to abnormal scenarios:
        - There are three zones: White Zone, Yellow Zone and Red Zone, which are determined by thresholds of the different Risk Metrics
        - Some “Cooling measures” will be automatically pushed when a market hits certain zones
        - Red Zone:
            - Once a Red Zone is hit, the max rate deviation for the market will be lowered, and “Close Only Mode” will be automatically turned on, which will help cool down the market
    - Lastly, we have a comprehensive alerting and on-call system to notify and call our team members whenever there are important risk events (for example, a Red zone), to make sure everything is good and do manual actions if necessary to protect the system.