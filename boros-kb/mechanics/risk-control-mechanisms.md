---
description: Risk control mechanisms — OI cap, closing only mode, max rate deviation
last_updated: 2026-03-07
related:
  - risk/risk-overview.md
  - risk/global/params-definitions.md
  - risk/market-params/market-params-overview.md
---

# Protective mechanisms

There a few mechanisms in place to mitigate risks for the users and Boros' system.

### OI Cap

* There is a hard cap on the OI of any market
* To get the value from market API:
  * OI Cap = **`hardOICap`/`1e18`**

### Closing Only Mode

* When the market dynamics becomes too extreme (for example, abnormally high price volatility or low liquidity), the Closing Only Mode will be automatically turned on
* When Closing Only Mode is on, users will only be able to close existing positions (and not open new positions)

### Max Rate Deviation

* The system disallows any market trade that happens at a rate too far away from the current mark rate.
* If a trade exceeds this limit, an error “Large Rate Deviation” will be displayed on the UI
* The exact requirement is as follows:

$$
|markRate - rateTraded| \leq maxRateDeviationFactor \times max(markRate, RateFloor)
$$

* `maxRateDeviationFactor` = **`maxRateDeviationFactorBase1e4` / `1e4`**
  * where **`maxRateDeviationFactorBase1e4`** is from the market API

### Max Bounds on Limit Order rates

* When placing a limit order, a user can’t long at a rate too high above the mark rate, or short at a rate too low below the mark rate.
* The exact mechanics is this:
  * A long order rate must not exceed *f*<sup>*u*</sup>
  * A short order rate must not be lower than *f*<sup>*l*</sup>

$$
f^u(r\_m) =    \begin{cases}      r\_m\times upperLimitSlope & r\_m \geq I\_{threshold} \      r\_m + upperLimitConstant & 0 \leq r\_m < I\_{threshold} \      -f^l(-r\_m) & r\_m < 0    \end{cases}\    f^l(r\_m) =    \begin{cases}      r\_m\times lowerLimitSlope & r\_m \geq I\_{threshold} \      r\_m + lowerLimitConstant & 0 \leq r\_m < I\_{threshold} \      -f^u(-r\_m) & r\_m < 0    \end{cases}
$$

* To get the variables from the values returned from market API:
  * `upperLimitSlope` = **`loUpperSlopeBase1e4` / 1e4**
  * `upperLimitConstant` = **`loUpperConstBase1e4` / 1e4**
  * `lowerLimitSlope` = **`loLowerSlopeBase1e4` / 1e4**
  * `lowerLimitConstant` = **`loLowerConstBase1e4` / 1e4**
