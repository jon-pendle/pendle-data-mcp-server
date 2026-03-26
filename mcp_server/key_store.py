"""
Google Sheets-based API key store with TTL cache.

Reads API keys from a Google Sheet. Changes take effect within
the cache TTL (default 5 minutes) without restarting the server.

Sheet columns: key, owner, active, notes
Only rows with active=TRUE are loaded.
"""

import hmac
import time
import logging
import threading

import google.auth
from googleapiclient.discovery import build

logger = logging.getLogger("pendle_mcp")

SHEET_ID = "1KsHzScoI1N4QGVy91S6X9w8EL-aWaiFgZZYH2TbQ-Bo"
SHEET_NAME = "KeyStore"
CACHE_TTL_SECONDS = 300  # 5 minutes

_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Cache state
_lock = threading.Lock()
_cache: dict[str, str] = {}  # key -> owner
_cache_expires_at: float = 0


def _fetch_keys() -> dict[str, str]:
    """Fetch active keys from Google Sheet. Returns {key: owner}."""
    try:
        creds, _ = google.auth.default(scopes=_SHEETS_SCOPES)
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SHEET_ID, range=SHEET_NAME)
            .execute()
        )
        values = result.get("values", [])
        if len(values) <= 1:
            return {}

        header = [h.strip().lower() for h in values[0]]
        try:
            key_idx = header.index("key")
            owner_idx = header.index("owner")
            active_idx = header.index("active")
        except ValueError:
            logger.error("Key sheet missing required columns (key, owner, active)")
            return {}

        keys = {}
        for row in values[1:]:
            if len(row) <= max(key_idx, owner_idx, active_idx):
                continue
            key = row[key_idx].strip()
            owner = row[owner_idx].strip()
            active = row[active_idx].strip().upper()
            if key and active == "TRUE":
                keys[key] = owner
        return keys

    except Exception as e:
        logger.error(f"Failed to fetch API keys from sheet: {e}")
        return {}


def get_active_keys() -> dict[str, str]:
    """Return cached {key: owner} dict, refreshing if TTL expired."""
    global _cache, _cache_expires_at
    now = time.monotonic()

    if now < _cache_expires_at:
        return _cache

    with _lock:
        # Double-check after acquiring lock
        if now < _cache_expires_at:
            return _cache
        keys = _fetch_keys()
        if keys:
            _cache = keys
            _cache_expires_at = now + CACHE_TTL_SECONDS
            logger.info(f"Refreshed API key cache: {len(keys)} active key(s)")
        elif _cache:
            # Keep stale cache if fetch fails (don't lock everyone out)
            _cache_expires_at = now + 60  # retry in 1 minute
            logger.warning("Sheet fetch failed, keeping stale cache for 60s")
        else:
            _cache_expires_at = now + 30  # retry soon if empty
        return _cache


def validate_key(token: str) -> tuple[bool, str]:
    """Check if token is a valid active key. Returns (valid, owner)."""
    keys = get_active_keys()
    for stored_key, owner in keys.items():
        if hmac.compare_digest(token, stored_key):
            return True, owner
    return False, ""
