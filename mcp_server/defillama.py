"""
Self-contained DeFiLlama API helpers.

Replaces the dependency on tools.protocols (which lives in the Discord-bot repo).
"""

import json
import logging
from datetime import datetime
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger("pendle_mcp.defillama")

_TIMEOUT = 15  # seconds


def _get(url: str) -> Any | None:
    """GET a DeFiLlama endpoint, return parsed JSON or None on failure."""
    try:
        r = requests.get(url, headers={"accept": "*/*"}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("DeFiLlama request failed: %s – %s", url, e)
        return None


# ── public async tool functions (same signatures as before) ──────────


async def get_defillama_all_protocols(**kwargs) -> str:
    try:
        data = _get("https://api.llama.fi/protocols")
        if data is None:
            return json.dumps({"error": "Failed to fetch protocols from DeFiLlama API"})

        rows = [{"category": p.get("category"), "slug": p.get("slug"), "name": p.get("name")} for p in data]
        csv_data = pd.DataFrame(rows).to_csv(index=False)
        return json.dumps({"status": "success", "data": csv_data, "count": len(rows)})
    except Exception as e:
        return json.dumps({"error": f"Error fetching protocols: {e}"})


def _tvl_to_csv(items: list, tvl_key: str, aggregation: str) -> str:
    """Shared helper for protocol / chain historical TVL."""
    rows = []
    for item in items[:-1]:
        dt = datetime.fromtimestamp(item.get("date"))
        val = item.get(tvl_key)
        entry = {
            "date": dt.strftime("%Y-%m-%d"),
            "tvl": f"{round(val / 1_000_000, 1)}M" if val is not None else None,
        }
        if aggregation == "daily" or (aggregation == "weekly" and dt.weekday() == 0) or (aggregation == "monthly" and dt.day == 1):
            rows.append(entry)
    return pd.DataFrame(rows).to_csv(index=False)


async def get_defillama_protocol_historical_tvl(slug: str, aggregation: str = "daily", **kwargs) -> str:
    try:
        aggregation = aggregation.lower() if aggregation in ("daily", "weekly", "monthly") else "daily"
        data = _get(f"https://api.llama.fi/protocol/{slug}")
        if data is None:
            return json.dumps({"error": f"Failed to fetch historical TVL for protocol: {slug}"})
        csv_data = _tvl_to_csv(data["tvl"], "totalLiquidityUSD", aggregation)
        return json.dumps({"status": "success", "data": csv_data, "aggregation": aggregation, "count": csv_data.count("\n") - 1})
    except Exception as e:
        return json.dumps({"error": f"Error fetching historical TVL for protocol {slug}: {e}"})


async def get_defillama_chain_historical_tvl(chain_name: str, aggregation: str = "daily", **kwargs) -> str:
    try:
        aggregation = aggregation.lower() if aggregation in ("daily", "weekly", "monthly") else "daily"
        data = _get(f"https://api.llama.fi/v2/historicalChainTvl/{chain_name}")
        if data is None:
            return json.dumps({"error": f"Failed to fetch historical TVL for chain: {chain_name}"})
        csv_data = _tvl_to_csv(data, "tvl", aggregation)
        return json.dumps({"status": "success", "data": csv_data, "aggregation": aggregation, "count": csv_data.count("\n") - 1})
    except Exception as e:
        return json.dumps({"error": f"Error fetching historical TVL for chain {chain_name}: {e}"})
