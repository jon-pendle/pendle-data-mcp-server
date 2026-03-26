"""
Minimal instruction helpers retained for DeFiLlama tool results.

Most domain knowledge has migrated to products/ package.
"""

GUIDE_DEFILLAMA_PROTOCOLS = (
    "FIELD GUIDE: "
    "List of all DeFi protocols tracked by DeFiLlama. "
    "Use the 'slug' field as input to get_defillama_protocol_historical_tvl. "
    "Never guess slugs — always look them up from this list first."
)

GUIDE_DEFILLAMA_TVL = (
    "FIELD GUIDE: "
    "Historical TVL data from DeFiLlama. TVL values formatted as 'NNN.NM' (millions). "
    "Aggregation parameter controls data density: "
    "daily (all points), weekly (Mondays only), monthly (1st of month only)."
)
