---
description: Mathematical invariants that on-chain parameters must satisfy
last_updated: 2026-03-06
related:
  - risk/global/params-definitions.md
  - risk/global/params-values-production.md
---

# Parameter Requirements

## Health threshold
(Refer to Assumption 8.1)
1. H_c_theoretical - H_d_theoretical >= (1+kMM)*(30s/5m).
2. H_d_theoretical - H_f_theoretical >= (1+kMM)*(30s/5m).
3. H_c >= H_c_theoretical.

## Margin
(Refer to Definition 8.1)
k_CO <= k_MD <= k_MM < k_IM

## Orderbound
(Refer to Definition 5.1)
1. LIMIT_ORDER_UPPER_SLOPE <= 2 * (1 - kMM * H_c_theoretical)/(2 - kMM *H_c_theoretical - min(1,kIM))
2. LIMIT_ORDER_LOWER_SLOPE >= 2 * (1 + kMM * H_c_theoretical)/(2 + kMM *H_c_theoretical + min(1,kIM))
3. LIMIT_ORDER_UPPER_CONST <= (min(1,kIM)-kMM * H_c_theoretical)*I_threshold/2
4. |LIMIT_ORDER_LOWER_CONST| <= (min(1,kIM)-kMM * H_c_theoretical)*I_threshold/2

## Other
(Refer to Definition 7.1)
1. k_CO >= (LIMIT_ORDER_UPPER_SLOPE - 1)
2. k_CO >= (1 - LIMIT_ORDER_LOWER_SLOPE)
3. k_CO * I_threshold >= LIMIT_ORDER_UPPER_CONST
4. k_CO * I_threshold >= |LIMIT_ORDER_LOWER_CONST|
5. k_MM(new) <= k_MM(old)
