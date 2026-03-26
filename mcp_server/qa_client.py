"""
Async client for the Pendle/Boros QA Cloud Run service.

Simple HTTP POST wrapper with GCP ID Token auth.
"""

import os
import logging

import aiohttp
import google.auth
from google.auth.transport.requests import Request as AuthRequest
from google.oauth2 import id_token

logger = logging.getLogger("pendle_mcp")

QA_SERVICE_URL = os.environ.get("QA_SERVICE_URL", "")

# Product IDs expected by the QA service
PRODUCTS = {
    "pendle": "pp_v3",
    "boros": "bb",
    "pendle_dev": "dev_v2",
    "boros_dev": "boros_dev",
}


def _get_id_token() -> str:
    """Get a GCP ID token for the QA service (IAP-protected Cloud Run)."""
    if not QA_SERVICE_URL:
        return ""
    try:
        return id_token.fetch_id_token(AuthRequest(), QA_SERVICE_URL)
    except Exception as e:
        logger.warning(f"Failed to get ID token for QA service: {e}")
        return ""


async def qa_ask(product_key: str, question: str, user_id: str = "mcp_client") -> str:
    """Call the QA service and return the answer with citations."""
    if not QA_SERVICE_URL:
        return "QA service not configured (QA_SERVICE_URL not set)."

    product_id = PRODUCTS.get(product_key)
    if not product_id:
        return f"Unknown product: {product_key}. Available: {list(PRODUCTS.keys())}"

    token = _get_id_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "question": question,
        "mode": "command",
        "platform": "mcp",
        "user_id": user_id,
        "message_history": [],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{QA_SERVICE_URL}/qa/{product_id}",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data.get("answer", "No response received.")
                    citations = data.get("citations", [])
                    if citations:
                        refs = [
                            f"[{i}] {c['source_url']}"
                            for i, c in enumerate(citations[:3], 1)
                            if c.get("source_url")
                        ]
                        if refs:
                            answer += "\n\n**References:**\n" + "\n".join(refs)
                    return answer
                error_text = await resp.text()
                logger.error(f"QA service {resp.status}: {error_text}")
                return "The QA service is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"QA service error: {e}")
        return "Unable to connect to the QA service. Please try again later."
