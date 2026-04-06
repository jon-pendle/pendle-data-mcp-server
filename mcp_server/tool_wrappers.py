"""
MCP tool wrappers.

Registers:
  - Per-product data catalog tools (get_<product_id>_data_catalog)
  - Per-product extra tools (e.g. pool discovery for Pendle)
  - Shared: run_sql, report_learning, get_defillama_*
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from .products import get_all_products, get_all_partition_tables, build_product_index, get_table_detail as _lookup_table_detail
from .sql_executor import execute_sql
from .memory import save_learning
from .usage_tracker import track_tool_call
from .acl_store import check_tool_allowed
from .quota_store import check_and_increment, add_bytes
from .defillama import (
    get_defillama_all_protocols,
    get_defillama_protocol_historical_tvl,
    get_defillama_chain_historical_tvl,
)

logger = logging.getLogger("pendle_mcp")

# ── Return instructions (appended to run_sql results when relevant) ──

_YIELD_FEE_COLUMNS = frozenset({
    "expected_yield_fee", "expected_expire_fee",
    "avg_daily_realized_yield_fee_in_usd",
    "epoch_avg_realized_yield_fee_in_usd",
    "realized_yield_fee",
})

_YIELD_FEE_RETURN_INSTRUCTIONS = (
    "\n\n⚠️ YIELD FEE ANALYSIS — RETURN INSTRUCTIONS:\n"
    "Present BOTH perspectives separately:\n"
    "1. Expected fees (theoretical): what the protocol should earn based on underlying asset yields.\n"
    "   - expected_yield_fee: pre-maturity yield fee portion.\n"
    "   - expected_expire_fee: post-maturity yield fee (all yields collected).\n"
    "   - Unless user explicitly asks to separate expire fees, combine as "
    "\"total expected yield fees\" = expected_yield_fee + expected_expire_fee.\n"
    "2. Realized fees (actual): what has been claimed and settled by users.\n"
    "   - May include accumulated yield from multiple periods.\n\n"
    "CRITICAL RULES:\n"
    "- Expected and realized are FUNDAMENTALLY DIFFERENT metrics — NEVER sum them together.\n"
    "- CORRECT: \"Expected yield fees: $X (yield: $Y + expire: $Z) | Realized yield fees: $W\"\n"
    "- NEVER multiply epoch-averaged realized yield fee by days for weekly/monthly totals "
    "(epoch-based calculation can have multiple values per week).\n"
    "- For aggregated metrics over a date range, use SUM() directly on the daily rows.\n"
)


def _current_user() -> tuple[str, str]:
    """Return (user_email, api_key_hint) from current request context."""
    from .server import current_api_key_hint, current_user_email
    return current_user_email.get("unknown"), current_api_key_hint.get("unknown")


def _track(tool_name: str, **params) -> None:
    """Track a tool call with current user identity context."""
    email, key_hint = _current_user()
    bytes_mb = float(params.pop("bytes_mb", 0.0))
    track_tool_call(tool_name, params, key_hint, email, bytes_mb)


async def _guard(tool_name: str, product_id: str | None = None) -> str | None:
    """
    Run ACL + quota pre-flight checks.
    Returns an error message string if denied, or None if allowed.
    """
    email, _ = _current_user()

    allowed, reason = check_tool_allowed(email, tool_name, product_id)
    if not allowed:
        logger.warning(f"ACL denied: user={email} tool={tool_name} reason={reason}")
        return reason

    allowed, reason = await check_and_increment(email)
    if not allowed:
        logger.warning(f"Quota denied: user={email} tool={tool_name} reason={reason}")
        return reason

    return None


# ── Per-product tool factories ─────────────────────────────────────────

def _register_product_catalog_tool(mcp: FastMCP, product) -> None:
    """Register a get_<product_id>_data_catalog tool that returns the index."""
    index_text = build_product_index(product)
    tool_name = f"get_{product.product_id}_data_catalog"
    product_id = product.product_id

    @mcp.tool(name=tool_name, description=product.tool_description)
    async def _catalog_tool() -> str:
        if err := await _guard(tool_name, product_id=product_id):
            return json.dumps({"error": err, "error_type": "permission"})
        _track(tool_name)
        return index_text


# ── Main registration entry point ────────────────────────────────────

def register_tools(mcp: FastMCP):
    """Register all tools on the MCP server."""

    # ── Per-product catalog tools ────────────────────────────────────
    for product in get_all_products():
        _register_product_catalog_tool(mcp, product)
        if product.register_extra_tools:
            product.register_extra_tools(mcp, _track)

    # ── Shared: Table Detail ─────────────────────────────────────────

    valid_products = ", ".join(p.product_id for p in get_all_products())

    @mcp.tool(
        description=(
            "Full column definitions, aggregation rules, and SQL examples for a table. "
            "Call the relevant data catalog tool first to find table names.\n\n"
            f"product_id: one of [{valid_products}]\n"
            "table_name: short name from the catalog (e.g. 'pool_metrics_daily')"
        )
    )
    async def get_table_detail(product_id: str, table_name: str) -> str:
        if err := await _guard("get_table_detail", product_id=product_id):
            return json.dumps({"error": err, "error_type": "permission"})
        _track("get_table_detail", product_id=product_id, table_name=table_name)
        catalog = _lookup_table_detail(product_id, table_name)
        if catalog is None:
            return json.dumps({
                "error": f"Table '{table_name}' not found in product '{product_id}'.",
                "error_type": "validation",
            })
        return catalog

    # ── Shared: SQL Executor ──────────────────────────────────────────

    partition_tables = ", ".join(sorted(get_all_partition_tables().keys()))

    @mcp.tool(
        description=(
            "Execute a SQL query against BigQuery tables. "
            "Write your SQL based on the schema from the relevant data catalog tool.\n\n"
            "AUDIT (mandatory):\n"
            "- `model`: your model identifier (e.g. claude-sonnet-4, gpt-5).\n"
            "- `task`: the user's original question or goal in one sentence.\n"
            "- `query_purpose`: what THIS specific query does toward that goal. When running multiple queries "
            "for one task, each should explain its role.\n\n"
            "RULES:\n"
            "- Only SELECT/WITH statements allowed.\n"
            f"- Partitioned tables ({partition_tables}) "
            "MUST have a date filter in WHERE.\n"
            "- Tables must be fully qualified with backticks: "
            "`project.dataset.table_name`\n"
            "- Default Limit: Max 500 MB scan, 30s timeout, 10K rows returned. Higher limits available for selected users.\n"
            "- Returns CSV data with row count and bytes processed."
        )
    )
    async def run_sql(
        sql: str,
        model: str = "",
        task: str = "",
        query_purpose: str = "",
    ) -> str:
        """Execute a validated SELECT query against BigQuery."""
        # Require audit fields for traceability
        audit = {"model": model, "task": task, "query_purpose": query_purpose}
        missing = [k for k, v in audit.items() if not v.strip()]
        if missing:
            return json.dumps({
                "error": f"Missing required audit field(s): {', '.join(missing)}. "
                         "All run_sql calls must include model, task, and query_purpose.",
                "error_type": "validation",
            })

        if err := await _guard("run_sql"):
            return json.dumps({"error": err, "error_type": "permission"})

        # Apply per-user SQL limits from ACL (0 = use server default)
        email, _ = _current_user()
        from .acl_store import get_user_permissions, is_api_key_user
        perms = None if is_api_key_user(email) else get_user_permissions(email)
        bytes_mb = 0.0
        returned_rows = 0
        error_type = None
        result = json.dumps({"error": "unexpected", "error_type": "execution"})
        try:
            result = await execute_sql(
                sql,
                max_bytes_mb=perms["query_mb"] if perms else 0,
                max_rows=perms["query_rows"] if perms else 0,
                timeout_s=perms["query_timeout_s"] if perms else 0,
                allowed_products=perms["products"] if perms else None,
            )
            parsed = json.loads(result)
            bytes_mb = parsed.get("metadata", {}).get("bytes_processed_mb", 0.0)
            returned_rows = parsed.get("metadata", {}).get("rows", 0)
            error_type = parsed.get("error_type")
        except Exception as exc:
            error_type = "execution"
            result = json.dumps({"error": str(exc), "error_type": "execution"})
        finally:
            _track(
                "run_sql",
                sql=sql,
                model=model,
                task=task,
                query_purpose=query_purpose,
                returned_rows=returned_rows,
                bytes_mb=bytes_mb,
                error_type=error_type,
            )
            if bytes_mb > 0:
                await add_bytes(email, bytes_mb)

        # Append contextual return instructions when yield fee columns detected
        if error_type is None:
            try:
                parsed_result = json.loads(result)
                csv_header = parsed_result.get("data", "").split("\n", 1)[0].lower()
                if csv_header and _YIELD_FEE_COLUMNS & set(csv_header.split(",")):
                    parsed_result["return_instructions"] = _YIELD_FEE_RETURN_INSTRUCTIONS
                    result = json.dumps(parsed_result)
            except (json.JSONDecodeError, AttributeError):
                pass

        return result

    # ── Shared: Learning Report ───────────────────────────────────────

    @mcp.tool(
        description=(
            "Report a learning for future improvement. "
            "Learnings are shared across all clients — your report helps "
            "every future analysis session avoid the same mistakes.\n\n"
            "AUDIT (mandatory):\n"
            "- `model`: your model identifier (e.g. claude-sonnet-4, gpt-5).\n"
            "- `question_context`: the user's original question that triggered this learning.\n\n"
            "WHEN TO CALL (proactively, don't wait for the end):\n"
            "- IMMEDIATELY when you hit an error, misinterpret data, or need "
            "to retry/correct — report the mistake and the fix.\n"
            "- When you discover a non-obvious data relationship or edge case.\n"
            "- When a specific SQL pattern works well (or fails) for a question type.\n"
            "- When an analysis CANNOT be completed because required data is missing, "
            "unavailable, or not captured in any existing table — report what data "
            "would be needed and why.\n\n"
            "CATEGORIES:\n"
            "- data_semantics: Field meanings, edge cases, non-obvious relationships.\n"
            "- usage_pattern: Effective SQL patterns or query strategies.\n"
            "- methodology: Analysis approaches, errors and fixes.\n"
            "- data_gap: Data that is missing or not available to answer a question type. "
            "Include: what data is needed, which question triggered the gap, "
            "and suggested source if known.\n\n"
            "DO NOT report: analysis results, conclusions, specific numbers, "
            "or user-specific information."
        )
    )
    async def report_learning(
        category: str,
        content: str,
        source_tool: str = "",
        question_context: str = "",
        model: str = "",
    ) -> str:
        """Report a reusable learning about data semantics, usage patterns, or methodology."""
        _track("report_learning", category=category, source_tool=source_tool, model=model)
        return await save_learning(
            category=category,
            content=content,
            source_tool=source_tool,
            question_context=question_context,
            model=model,
        )

    # ── Shared: DeFiLlama tools ───────────────────────────────────────

    @mcp.tool(
        description=(
            "Get list of all DeFi protocols from DeFiLlama with category, slug, "
            "and name. CALL THIS FIRST before querying protocol TVL — never "
            "guess slugs."
        )
    )
    async def get_defillama_all_protocols_tool() -> str:
        if err := await _guard("get_defillama_all_protocols"):
            return json.dumps({"error": err, "error_type": "permission"})
        _track("get_defillama_all_protocols")
        return await get_defillama_all_protocols()

    @mcp.tool(
        description=(
            "Get historical TVL for a DeFi protocol from DeFiLlama. "
            "MUST call get_defillama_all_protocols first to find the correct slug. "
            "Aggregation: 'daily', 'weekly', 'monthly'."
        )
    )
    async def get_defillama_protocol_historical_tvl_tool(
        slug: str,
        aggregation: str = "daily",
    ) -> str:
        if err := await _guard("get_defillama_protocol_historical_tvl"):
            return json.dumps({"error": err, "error_type": "permission"})
        _track("get_defillama_protocol_historical_tvl", slug=slug, aggregation=aggregation)
        return await get_defillama_protocol_historical_tvl(
            slug=slug, aggregation=aggregation
        )

    @mcp.tool(
        description=(
            "Get historical TVL for a blockchain from DeFiLlama. "
            "Common chains: 'ethereum', 'arbitrum', 'bsc', 'polygon'. "
            "Aggregation: 'daily', 'weekly', 'monthly'."
        )
    )
    async def get_defillama_chain_historical_tvl_tool(
        chain_name: str,
        aggregation: str = "daily",
    ) -> str:
        if err := await _guard("get_defillama_chain_historical_tvl"):
            return json.dumps({"error": err, "error_type": "permission"})
        _track("get_defillama_chain_historical_tvl", chain_name=chain_name, aggregation=aggregation)
        return await get_defillama_chain_historical_tvl(
            chain_name=chain_name, aggregation=aggregation
        )

    # ── Shared: QA Knowledge Base tools ──────────────────────────────

    from .qa_client import qa_ask

    @mcp.tool(
        description=(
            "Answer Pendle product questions from the official docs and community knowledge base.\n"
            "Sources: Pendle documentation + curated mod replies from Discord.\n"
            "Use for: PT/YT mechanics, yield markets, pools, vePENDLE, APY/APR, "
            "redemption, liquidity, tokenomics, yield strategies.\n"
            "Do NOT use for: data queries (use run_sql) or developer/API questions "
            "(use ask_pendle_developer)."
        )
    )
    async def ask_pendle(question: str) -> str:
        if err := await _guard("ask_pendle"):
            return json.dumps({"error": err, "error_type": "permission"})
        email, _ = _current_user()
        _track("ask_pendle", question=question[:200])
        return await qa_ask("pendle", question, user_id=email)

    @mcp.tool(
        description=(
            "Answer Boros product questions from the official docs and community knowledge base.\n"
            "Sources: Boros documentation + curated mod replies from Discord.\n"
            "Use for: interest rate swaps, fixed/floating rate, leveraged yield, "
            "margin trading, opening/closing positions, protocol mechanics.\n"
            "Do NOT use for: data queries (use run_sql) or developer/API questions "
            "(use ask_boros_developer)."
        )
    )
    async def ask_boros(question: str) -> str:
        if err := await _guard("ask_boros"):
            return json.dumps({"error": err, "error_type": "permission"})
        email, _ = _current_user()
        _track("ask_boros", question=question[:200])
        return await qa_ask("boros", question, user_id=email)

    @mcp.tool(
        description=(
            "Answer Pendle V2 developer questions from the developer documentation.\n"
            "Sources: Pendle dev docs (SDK reference, API specs, integration guides).\n"
            "Use for: Pendle SDK, Router contract, ABIs, REST API endpoints, "
            "on-chain integration, contract addresses.\n"
            "Do NOT use for: product usage questions (use ask_pendle)."
        )
    )
    async def ask_pendle_developer(question: str) -> str:
        if err := await _guard("ask_pendle_developer"):
            return json.dumps({"error": err, "error_type": "permission"})
        email, _ = _current_user()
        _track("ask_pendle_developer", question=question[:200])
        return await qa_ask("pendle_dev", question, user_id=email)

    @mcp.tool(
        description=(
            "Answer Boros developer questions from the developer documentation.\n"
            "Sources: Boros dev docs (REST API reference, integration guides).\n"
            "Use for: Boros REST API, position management, PnL API, limit orders, "
            "request/response schemas, authentication.\n"
            "Do NOT use for: product usage questions (use ask_boros)."
        )
    )
    async def ask_boros_developer(question: str) -> str:
        if err := await _guard("ask_boros_developer"):
            return json.dumps({"error": err, "error_type": "permission"})
        email, _ = _current_user()
        _track("ask_boros_developer", question=question[:200])
        return await qa_ask("boros_dev", question, user_id=email)

    # ── Shared: Changelog ─────────────────────────────────────────────

    _CHANGELOG = (
        "# MCP Server Changelog (last 10 updates)\n"
        "\n"
        "1. 2026-04-06 — Sync pipeline: add cross_chain_swap_intents_curated table to pendle catalog\n"
        "2. 2026-04-03 — Sync pipeline: add incentive token amount columns to user_eod_position_summary\n"
        "3. 2026-04-03 — Keep both user_stats_per_pool_daily v1 and v2 with use-case guidance\n"
        "4. 2026-04-02 — Sync pipeline: add properties column to frontend_tracking catalogs\n"
        "5. 2026-04-02 — Add user_stats_per_pool_daily_v1 catalog with per-action-type metrics\n"
        "6. 2026-03-31 — Add twitter_engagement product (tweet_engagement_delta_hourly, tweet_basic_infos_latest_hourly)\n"
        "7. 2026-03-31 — Merge per-product table_detail tools into single get_table_detail(product_id, table_name)\n"
        "8. 2026-03-31 — Add yield fee return instructions and improve catalog descriptions\n"
        "9. 2026-03-26 — Add limit_order_ob_depth_hourly and user_aaarr_metrics tables\n"
        "10. 2026-03-25 — Update Boros event types catalog to match latest tracking spec\n"
    )

    @mcp.tool(
        description="Get recent MCP server changelog — the last 10 updates with dates and summaries."
    )
    async def get_changelog() -> str:
        _track("get_changelog")
        return _CHANGELOG

    # ── Shared: Dashboard Metadata ───────────────────────────────────

    import time as _time
    import threading as _threading
    import google.auth
    from googleapiclient.discovery import build as _build_service

    _DASHBOARD_SHEET_ID = "175znrO_VT4pAIApgzcUE9aU_CRiLKqEu4jApKKP7jaU"
    _DASHBOARD_SHEET_NAME = "Dashboard Meta"
    _SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    _DASHBOARD_CACHE_TTL = 300  # 5 minutes

    _dashboard_lock = _threading.Lock()
    _dashboard_cache: "pd.DataFrame | None" = None
    _dashboard_cache_expires: float = 0

    def _fetch_dashboard_df():
        """Fetch dashboard sheet and return a DataFrame (called under lock)."""
        import pandas as pd
        creds, _ = google.auth.default(scopes=_SHEETS_SCOPES)
        service = _build_service("sheets", "v4", credentials=creds, cache_discovery=False)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=_DASHBOARD_SHEET_ID, range=_DASHBOARD_SHEET_NAME)
            .execute()
        )
        values = result.get("values", [])
        if not values or len(values) <= 1:
            return None
        header = values[0]
        rows = [
            (row + [None] * (len(header) - len(row)))[:len(header)]
            for row in values[1:]
        ]
        return pd.DataFrame(rows, columns=header)

    def _get_dashboard_df():
        """Return cached dashboard DataFrame, refreshing if TTL expired."""
        nonlocal _dashboard_cache, _dashboard_cache_expires
        now = _time.monotonic()
        if now < _dashboard_cache_expires and _dashboard_cache is not None:
            return _dashboard_cache
        with _dashboard_lock:
            if now < _dashboard_cache_expires and _dashboard_cache is not None:
                return _dashboard_cache
            try:
                df = _fetch_dashboard_df()
                if df is not None:
                    _dashboard_cache = df
                    _dashboard_cache_expires = now + _DASHBOARD_CACHE_TTL
                    logger.info(f"Refreshed dashboard cache: {len(df)} entries")
                elif _dashboard_cache is not None:
                    _dashboard_cache_expires = now + 60  # retry in 1 min
                    logger.warning("Dashboard fetch failed, keeping stale cache for 60s")
            except Exception as e:
                logger.error(f"Dashboard fetch error: {e}")
                if _dashboard_cache is not None:
                    _dashboard_cache_expires = now + 60
            return _dashboard_cache

    @mcp.tool(
        description=(
            "Get Pendle dashboard metadata — names, descriptions, URLs, and categories.\n"
            "Use to find which dashboards exist and what they cover.\n"
            "Also use when analysis cannot be completed — a dashboard may already cover the topic.\n\n"
            "keyword (optional): filter dashboards by name or description (case-insensitive)."
        )
    )
    async def get_dashboard_meta(keyword: str = "") -> str:
        import pandas as pd

        if err := await _guard("get_dashboard_meta"):
            return json.dumps({"error": err, "error_type": "permission"})
        _track("get_dashboard_meta", keyword=keyword[:100])

        df = _get_dashboard_df()
        if df is None:
            return json.dumps({"error": "No dashboard data found.", "error_type": "execution"})

        total = len(df)
        if keyword.strip():
            kw = keyword.strip().lower()
            mask = pd.Series(False, index=df.index)
            for col in ("Name", "AI Summary"):
                if col in df.columns:
                    mask |= df[col].astype(str).str.lower().str.contains(kw, na=False)
            df = df[mask]

        return json.dumps({
            "filtered_count": len(df),
            "total_count": total,
            "dashboards": df.to_dict("records"),
        })
