"""
Application-layer ACL for MCP users, backed by Google Sheets tab "UserACL".

Sheet columns: email, products, daily_calls, daily_mb, query_mb, query_rows, query_timeout_s, active, notes
  - products: comma-separated product IDs, or "*" for all
  - daily_calls: max tool calls per day (0 = unlimited)
  - daily_mb: max BigQuery MB scanned per day (0 = unlimited)
  - query_mb: max MB billed per single SQL query (0 = use server default 500 MB)
  - query_rows: max rows returned per SQL query (0 = use server default 10000)
  - query_timeout_s: query timeout in seconds (0 = use server default 30s)
  - active: TRUE/FALSE

Changes take effect within CACHE_TTL_SECONDS without restarting the server.

API key users (non-OAuth) get a synthetic entry with unrestricted access,
preserving backward compatibility.

Special default-quota row (required for Pendle-domain fallback):
  - Set email to "__pendle_default_quota__"
  - daily_calls / daily_mb define default quota for Pendle-domain users
  - notes can optionally include:
      domains=pendle.finance,pendle.com
    If omitted, no fallback domains are configured.
"""

import time
import logging
import threading

import google.auth
from googleapiclient.discovery import build

logger = logging.getLogger("pendle_mcp")

SHEET_ID = "1KsHzScoI1N4QGVy91S6X9w8EL-aWaiFgZZYH2TbQ-Bo"
ACL_SHEET_NAME = "UserACL"
CACHE_TTL_SECONDS = 300  # 5 minutes

_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

SPECIAL_DEFAULT_QUOTA_EMAIL = "__pendle_default_quota__"

# email -> {products: set[str] | None, daily_calls: int, daily_mb: float}
# products=None means unrestricted ("*")
_lock = threading.Lock()
_cache: dict[str, dict] = {}
_cache_expires_at: float = 0


def _parse_default_quota_notes(notes_raw: str) -> set[str]:
    """
    Parse optional domains from notes field.

    Expected format:
      domains=pendle.finance,pendle.com
    """
    if not notes_raw:
        return set()
    parts = [p.strip() for p in notes_raw.split(";") if p.strip()]
    for part in parts:
        if not part.lower().startswith("domains="):
            continue
        raw_domains = part.split("=", 1)[1]
        return {d.strip().lower() for d in raw_domains.split(",") if d.strip()}
    return set()


def _fetch_acl() -> dict[str, dict]:
    """Fetch ACL from Google Sheet. Returns {email: permission_dict}."""
    try:
        creds, _ = google.auth.default(scopes=_SHEETS_SCOPES)
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SHEET_ID, range=ACL_SHEET_NAME)
            .execute()
        )
        values = result.get("values", [])
        if len(values) <= 1:
            return {}

        header = [h.strip().lower() for h in values[0]]
        try:
            email_idx = header.index("email")
            products_idx = header.index("products")
            calls_idx = header.index("daily_calls")
            mb_idx = header.index("daily_mb")
            active_idx = header.index("active")
        except ValueError as e:
            logger.error(f"UserACL sheet missing required columns: {e}")
            return {}

        # Optional per-query limit columns (fall back to server defaults if absent)
        query_mb_idx = header.index("query_mb") if "query_mb" in header else None
        query_rows_idx = header.index("query_rows") if "query_rows" in header else None
        query_timeout_idx = header.index("query_timeout_s") if "query_timeout_s" in header else None
        notes_idx = header.index("notes") if "notes" in header else None

        def _cell(row: list, idx: int | None) -> str:
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        def _int(val: str, default: int = 0) -> int:
            try:
                return int(val) if val else default
            except ValueError:
                return default

        def _float(val: str, default: float = 0.0) -> float:
            try:
                return float(val) if val else default
            except ValueError:
                return default

        acl: dict[str, dict] = {}
        for row in values[1:]:
            if len(row) <= max(email_idx, products_idx, calls_idx, mb_idx, active_idx):
                continue
            active = row[active_idx].strip().upper()
            if active != "TRUE":
                continue

            email = row[email_idx].strip().lower()
            if not email:
                continue

            products_raw = row[products_idx].strip()
            if products_raw == "*":
                products = None  # unrestricted
            else:
                products = {p.strip() for p in products_raw.split(",") if p.strip()}

            entry = {
                "products": products,
                "daily_calls": _int(row[calls_idx].strip() if calls_idx < len(row) else ""),
                "daily_mb": _float(row[mb_idx].strip() if mb_idx < len(row) else ""),
                # Per-query limits (0 = use server default)
                "query_mb": _int(_cell(row, query_mb_idx)),
                "query_rows": _int(_cell(row, query_rows_idx)),
                "query_timeout_s": _int(_cell(row, query_timeout_idx)),
            }
            if email == SPECIAL_DEFAULT_QUOTA_EMAIL:
                entry["default_domains"] = _parse_default_quota_notes(_cell(row, notes_idx))

            acl[email] = entry

        logger.info(f"Refreshed UserACL: {len(acl)} entries")
        return acl

    except Exception as e:
        logger.error(f"Failed to fetch UserACL from sheet: {e}")
        return {}


def _get_acl() -> dict[str, dict]:
    """Return cached ACL, refreshing if TTL expired."""
    global _cache, _cache_expires_at
    now = time.monotonic()

    if now < _cache_expires_at:
        return _cache

    with _lock:
        if now < _cache_expires_at:
            return _cache
        acl = _fetch_acl()
        if acl:
            _cache = acl
            _cache_expires_at = now + CACHE_TTL_SECONDS
        elif _cache:
            _cache_expires_at = now + 60
            logger.warning("UserACL fetch failed, keeping stale cache for 60s")
        else:
            _cache_expires_at = now + 30
        return _cache


def get_user_permissions(email: str) -> dict | None:
    """
    Return permission dict for email, or None if not found / not active.

    Permission dict: {
        "products": set[str] | None,  # None = all products allowed
        "daily_calls": int,           # 0 = unlimited
        "daily_mb": float,            # 0 = unlimited
    }
    """
    if not email or email == "unknown":
        return None
    normalized_email = email.lower()
    acl = _get_acl()
    perms = acl.get(normalized_email)
    if perms is not None:
        return perms

    # Fallback: Pendle-domain accounts get baseline access from the special ACL row.
    special = acl.get(SPECIAL_DEFAULT_QUOTA_EMAIL)
    if special is None:
        return None

    default_domains = special.get("default_domains", set())
    default_daily_calls = special.get("daily_calls", 0)
    default_daily_mb = special.get("daily_mb", 0.0)
    domain = normalized_email.split("@")[-1] if "@" in normalized_email else ""
    if domain in default_domains:
        return {
            "products": None,  # unrestricted product access
            "daily_calls": default_daily_calls,
            "daily_mb": default_daily_mb,
            "query_mb": 0,
            "query_rows": 0,
            "query_timeout_s": 0,
        }

    return None


def is_api_key_user(email: str) -> bool:
    """API key users are identified by the synthetic 'apikey:' prefix."""
    return email.startswith("apikey:")


def check_tool_allowed(email: str, tool_name: str, product_id: str | None = None) -> tuple[bool, str]:
    """
    Check if user is allowed to call this tool.

    Returns (allowed: bool, reason: str).
    API key users bypass ACL (backward compatible).
    """
    if is_api_key_user(email):
        return True, ""

    perms = get_user_permissions(email)
    if perms is None:
        return False, f"User '{email}' is not in the access list. Contact an admin."

    # Product-level check: only applies to catalog tools and run_sql table filtering
    # is done separately in sql_executor. Here we gate catalog tool access.
    if product_id is not None and perms["products"] is not None:
        if product_id not in perms["products"]:
            return False, (
                f"User '{email}' does not have access to product '{product_id}'. "
                f"Allowed: {', '.join(sorted(perms['products']))}."
            )

    return True, ""
