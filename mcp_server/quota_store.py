"""
Daily usage quota enforcement using Firestore atomic counters.

Firestore path: mcp_quota/{YYYYMMDD}/{email}
  Document fields: calls (int), bytes_mb (float)

Quotas are read from acl_store (Google Sheet). Limits of 0 mean unlimited.
The date-keyed structure provides automatic daily reset with no cleanup needed.
"""

import logging
from datetime import datetime, timezone

from google.cloud import firestore

from .acl_store import get_user_permissions, is_api_key_user

logger = logging.getLogger("pendle_mcp")

_GCP_PROJECT = "pendle-data"
_FIRESTORE_DB = "mcp-oauth"
_QUOTA_COLLECTION = "mcp_quota"


def _get_db() -> firestore.AsyncClient:
    if not hasattr(_get_db, "_client"):
        _get_db._client = firestore.AsyncClient(project=_GCP_PROJECT, database=_FIRESTORE_DB)
    return _get_db._client


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _quota_ref(date_key: str, email: str):
    return (
        _get_db()
        .collection(_QUOTA_COLLECTION)
        .document(date_key)
        .collection("users")
        .document(email.replace("@", "_at_").replace(".", "_"))
    )


async def check_and_increment(email: str, bytes_mb: float = 0.0) -> tuple[bool, str]:
    """
    Atomically increment usage counters and check against quota limits.

    Returns (allowed: bool, reason: str).
    Should be called BEFORE tool execution (pre-flight check + increment).
    If the tool call fails, the counter is still incremented (conservative).

    API key users bypass quota (backward compatible).
    """
    if is_api_key_user(email) or not email or email == "unknown":
        return True, ""

    perms = get_user_permissions(email)
    if perms is None:
        return False, f"User '{email}' is not in the access list."

    daily_calls_limit = perms["daily_calls"]
    daily_mb_limit = perms["daily_mb"]

    # If both limits are 0 (unlimited), skip Firestore entirely
    if daily_calls_limit == 0 and daily_mb_limit == 0:
        return True, ""

    date_key = _today_key()
    ref = _quota_ref(date_key, email)

    try:
        # Atomic read-increment transaction
        @firestore.async_transactional
        async def _txn(transaction):
            doc = await ref.get(transaction=transaction)
            data = doc.to_dict() if doc.exists else {"calls": 0, "bytes_mb": 0.0}

            new_calls = data.get("calls", 0) + 1
            new_mb = data.get("bytes_mb", 0.0) + bytes_mb

            # Check limits before writing
            if daily_calls_limit > 0 and new_calls > daily_calls_limit:
                return False, (
                    f"Daily call limit reached ({daily_calls_limit} calls/day). "
                    "Resets at midnight UTC. If you need more quota, contact an admin."
                )
            if daily_mb_limit > 0 and new_mb > daily_mb_limit:
                return False, (
                    f"Daily BigQuery scan limit reached ({daily_mb_limit:.0f} MB/day). "
                    "Resets at midnight UTC. If you need more quota, contact an admin."
                )

            transaction.set(ref, {"calls": new_calls, "bytes_mb": new_mb})
            return True, ""

        transaction = _get_db().transaction()
        allowed, reason = await _txn(transaction)
        return allowed, reason

    except Exception as e:
        logger.error(f"Quota check failed for {email}: {e}")
        return False, "Quota service temporarily unavailable. Please try again shortly."


async def get_usage_today(email: str) -> dict:
    """Return today's usage counters for a user."""
    ref = _quota_ref(_today_key(), email)
    try:
        doc = await ref.get()
        return doc.to_dict() if doc.exists else {"calls": 0, "bytes_mb": 0.0}
    except Exception as e:
        logger.error(f"Failed to get usage for {email}: {e}")
        return {"calls": 0, "bytes_mb": 0.0}


async def add_bytes(email: str, bytes_mb: float) -> None:
    """
    Add scanned bytes to today's counter after SQL execution completes.

    Called post-execution so we know the actual bytes. Non-transactional is
    acceptable here since slight over-counting is better than blocking.
    """
    if is_api_key_user(email) or not email or email == "unknown" or bytes_mb <= 0:
        return

    perms = get_user_permissions(email)
    if perms is None or perms["daily_mb"] == 0:
        return  # No MB limit configured, skip tracking

    ref = _quota_ref(_today_key(), email)
    try:
        await ref.set({"bytes_mb": firestore.Increment(bytes_mb)}, merge=True)
    except Exception as e:
        logger.error(f"Failed to add bytes for {email}: {e}")
