"""
Shared learning memory for MCP server.

Write-only from MCP tools. Periodically reviewed by humans and
promoted into instructions/domain knowledge.

Storage: BigQuery table pendle-data.mcp.learning_reports
Uses streaming insert (only needs bigquery.tables.updateData permission).
"""

import logging
import datetime

from google.cloud import bigquery

logger = logging.getLogger("pendle_mcp")

BQ_TABLE = "pendle-data.mcp.learning_reports"

# Valid categories — enforced at tool level
VALID_CATEGORIES = {"data_semantics", "usage_pattern", "methodology", "data_gap"}

# Lazy-init client
_bq_client: bigquery.Client | None = None


def _get_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project="pendle-data")
    return _bq_client


async def save_learning(
    category: str,
    content: str,
    source_tool: str = "",
    question_context: str = "",
    model: str = "",
) -> str:
    """Append a learning report to BigQuery via streaming insert."""
    if category not in VALID_CATEGORIES:
        return f"Error: category must be one of {VALID_CATEGORIES}"

    if not content.strip():
        return "Error: content cannot be empty"

    # Get API key hint and user email from contextvars (set by APIKeyMiddleware)
    from .server import current_api_key_hint, current_user_email
    api_key_hint = current_api_key_hint.get("unknown")
    user_email = current_user_email.get("unknown")

    row = {
        "reported_at": datetime.datetime.utcnow().isoformat(),
        "category": category,
        "content": content.strip(),
        "source_tool": source_tool,
        "question_context": question_context.strip(),
        "api_key_hint": api_key_hint,
        "user_email": user_email,
        "model": model,
    }

    try:
        client = _get_client()
        errors = client.insert_rows_json(BQ_TABLE, [row])
        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
            return "Learning save failed. Logged for review."
        logger.info(f"Learning reported: [{category}] key=...{api_key_hint} {content[:80]}...")
        return "Learning saved."
    except Exception as e:
        logger.error(f"Failed to save learning: {e}")
        return "Learning save failed. Logged for review."
