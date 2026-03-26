"""
Tool usage tracking for MCP server.

Logs every tool call with parameters and API key hint to BigQuery
via streaming insert (fire-and-forget, non-blocking).
"""

import json
import logging
import datetime
import threading

from google.cloud import bigquery

logger = logging.getLogger("pendle_mcp")

BQ_TABLE = "pendle-data.mcp.tool_usage"

_bq_client: bigquery.Client | None = None


def _get_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project="pendle-data")
    return _bq_client


def track_tool_call(
    tool_name: str,
    parameters: dict,
    api_key_hint: str,
    user_email: str = "unknown",
    bytes_mb: float = 0.0,
) -> None:
    """Fire-and-forget: log tool call to BigQuery in a background thread."""
    def _insert():
        try:
            row = {
                "called_at": datetime.datetime.utcnow().isoformat(),
                "tool_name": tool_name,
                "parameters": json.dumps(parameters, default=str),
                "api_key_hint": api_key_hint,
                "user_email": user_email,
                "bytes_mb": bytes_mb,
            }
            errors = _get_client().insert_rows_json(BQ_TABLE, [row])
            if errors:
                logger.error(f"Usage tracking insert errors: {errors}")
        except Exception as e:
            logger.error(f"Usage tracking failed: {e}")

    threading.Thread(target=_insert, daemon=True).start()
