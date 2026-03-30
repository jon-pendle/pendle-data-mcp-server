"""
Data MCP Server.

Exposes data analysis tools via MCP (Model Context Protocol)
for use by external clients like Claude Desktop and Cursor.

Usage:
    # Local development (stdio)
    python -m mcp_server.server

    # Production (Streamable HTTP for Cloud Run)
    python -m mcp_server.server --transport streamable-http --port 8080

Authentication (streamable-http mode):
    Two auth methods, checked in order:
    1. OAuth 2.0 (MCP spec) — handled by FastMCP's built-in auth middleware.
       Users authenticate via Google login. Requires GOOGLE_OAUTH_CLIENT_ID,
       GOOGLE_OAUTH_CLIENT_SECRET, and MCP_SERVER_BASE_URL env vars.
    2. API Key fallback — for scripts/automation without a browser.
       Keys managed via Google Sheet (auto-refreshing, 5-min cache).
       Send: X-API-Key: <key>

    stdio transport is never authenticated (local process).
"""

import os
import sys
import argparse
import contextvars
import logging

import uvicorn
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from dotenv import load_dotenv

# Tracks which API key (last 8 chars) made the current request
current_api_key_hint: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_api_key_hint", default="unknown"
)

# Tracks the authenticated user's email (OAuth) or owner name (API key)
current_user_email: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_user_email", default="unknown"
)

# Add project root to path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

# Load .env.mcp (or fallback to .env) before reading any env vars
for _env_name in (".env.mcp", ".env"):
    _env_path = os.path.join(_project_root, _env_name)
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
        break

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .tool_wrappers import register_tools
from .products import get_all_products
from .key_store import validate_key, get_active_keys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("pendle_mcp")


def _oauth_enabled() -> bool:
    """Check if Google OAuth env vars are configured."""
    return bool(
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        and os.environ.get("MCP_SERVER_BASE_URL")
    )


# ── Server instructions (shared between OAuth and non-OAuth modes) ───

def _build_instructions() -> str:
    """Generate server instructions dynamically from registered products."""
    products = get_all_products()
    catalog_lines = "\n".join(
        f"  - {p.display_name}: call get_{p.product_id}_data_catalog()"
        for p in products
    )
    return (
        "Data analysis server. Query BigQuery tables using SQL. "
        "Internal use only.\n\n"
        "AVAILABLE DATA PRODUCTS:\n"
        f"{catalog_lines}\n\n"
        "WORKFLOW:\n"
        "1. Call the relevant data catalog tool to load the product INDEX "
        "(business rules, table summaries with key metrics).\n"
        "2. If the question involves a domain concept (e.g. liquidity, risk, "
        "market making, trading strategy, scoring, zone, parameters), "
        "check the knowledge base FIRST (e.g. get_boros_kb_index → read_boros_kb) "
        "to load the official definition, formula, or methodology BEFORE writing SQL. "
        "Do NOT assume a concept doesn't exist — always check KB first.\n"
        "   If after checking the KB and catalog a metric or concept is still "
        "undefined, has no clear formula, or the required data columns do not exist "
        "in any available table — do NOT guess or improvise. Instead: "
        "state what is missing, ask the user to clarify the definition, "
        "and report_learning(category='data_gap').\n"
        f"3. Call get_<product_id>_table_detail(table_name) "
        "to load full column definitions, aggregation rules, and SQL examples for the table(s) you need.\n"
        "4. Write SQL and execute via run_sql(). Follow the catalog's "
        "aggregation rules.\n"
        "   Do NOT query INFORMATION_SCHEMA — it is not allowed. "
        "Use get_<product_id>_table_detail() for column info instead.\n"
        "   ALWAYS pass `task` (the user's goal) and `query_purpose` "
        "(what this specific query does) to run_sql for audit tracking.\n"
        "5. For DeFiLlama data, use the dedicated get_defillama_* tools.\n"
        "6. For product/usage questions (how to use Pendle/Boros, mechanics, strategies), "
        "use ask_pendle / ask_boros. For developer/API questions, use "
        "ask_pendle_developer / ask_boros_developer. These are knowledge base tools, "
        "not data queries.\n\n"
        "WHEN ANALYSIS CANNOT BE COMPLETED:\n"
        "If a question cannot be answered with available data tables, "
        "call get_dashboard_meta(keyword) to check if an existing dashboard "
        "covers the topic. If a relevant dashboard is found, return its name "
        "and URL to the user. Then call report_learning(category='data_gap') "
        "to log what data was missing.\n\n"
        "WHEN TO CALL report_learning():\n"
        "- IMMEDIATELY when you hit an error or misinterpret data.\n"
        "- After discovering reusable data semantics or SQL patterns.\n"
        "- When analysis cannot be completed due to missing data — report the gap.\n"
        "Report HOW data works, not analysis results."
    )


def create_server() -> tuple[FastMCP, "GoogleOAuthProvider | None"]:
    """Create and configure the MCP server.

    Returns (mcp_server, oauth_provider). oauth_provider is None if
    Google OAuth env vars are not set.
    """
    oauth_provider = None
    extra_kwargs = {}

    if _oauth_enabled():
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
        from .google_oauth import GoogleOAuthProvider

        oauth_provider = GoogleOAuthProvider()
        extra_kwargs["auth_server_provider"] = oauth_provider
        server_url = AnyHttpUrl(os.environ["MCP_SERVER_BASE_URL"])
        extra_kwargs["auth"] = AuthSettings(
            issuer_url=server_url,
            resource_server_url=server_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,  # Claude Desktop / Cursor need dynamic registration
                valid_scopes=["read"],
                default_scopes=["read"],
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
        logger.info("OAuth enabled (Google login)")
    else:
        logger.info("OAuth disabled (missing GOOGLE_OAUTH_* env vars), API key only")

    mcp = FastMCP(
        "Pendle Data",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
        instructions=_build_instructions(),
        **extra_kwargs,
    )

    # Mount Google callback route if OAuth is enabled
    if oauth_provider is not None:
        @mcp.custom_route("/google/callback", methods=["GET"])
        async def google_callback(request: Request):
            return await oauth_provider.handle_google_callback(request)

    register_tools(mcp)
    return mcp, oauth_provider


class APIKeyMiddleware:
    """ASGI middleware: API key fallback for requests not authenticated by OAuth.

    When OAuth is enabled, the MCP SDK's built-in BearerAuthBackend handles
    OAuth tokens on /mcp endpoints. This middleware catches requests using
    the X-API-Key header (scripts/automation without a browser).

    When OAuth is disabled, this is the sole authentication layer (same as before).
    """

    OAUTH_PATHS = {
        "/.well-known/oauth-authorization-server",
        "/authorize",
        "/token",
        "/register",
        "/revoke",
        "/google/callback",
    }

    def __init__(self, app, oauth_enabled: bool = False):
        self.app = app
        self.oauth_enabled = oauth_enabled

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        path = scope.get("path", "")
        method = scope.get("method", "")
        host = headers.get("host", "N/A")
        logger.info(f"Request: {method} {path} | Host: {host}")

        # OAuth endpoints are handled by FastMCP's auth routes — pass through
        if self.oauth_enabled and path in self.OAUTH_PATHS:
            await self.app(scope, receive, send)
            return

        # If request has Authorization: Bearer, let FastMCP's OAuth middleware handle it
        auth_header = headers.get("authorization", "")
        if self.oauth_enabled and auth_header.startswith("Bearer "):
            await self.app(scope, receive, send)
            return

        # API Key auth via X-API-Key header
        api_key = headers.get("x-api-key")
        if api_key:
            valid, owner = validate_key(api_key)
            if valid:
                hint = api_key[-8:]
                current_api_key_hint.set(hint)
                current_user_email.set(owner or f"apikey:{hint}")
                logger.info(f"API key auth: owner={owner} key=...{hint}")
                await self.app(scope, receive, send)
                return

        # No valid auth found
        if not self.oauth_enabled:
            # API-key-only mode: reject
            sheet_keys = get_active_keys()
            if not sheet_keys:
                response = PlainTextResponse("No API keys configured", status_code=503)
            else:
                response = PlainTextResponse("Unauthorized — provide X-API-Key header", status_code=401)
            await response(scope, receive, send)
            return

        # OAuth mode: no X-API-Key, no Bearer — let FastMCP return 401
        await self.app(scope, receive, send)


# Module-level server instance (for `mcp run` / `mcp dev` compatibility)
mcp, _oauth_provider = create_server()


def main():
    parser = argparse.ArgumentParser(description="Pendle Data MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8080")),
        help="Port for HTTP transport (default: 8080)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP transport (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        logger.info("Starting Pendle Data MCP Server (stdio)")
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting Pendle Data MCP Server (streamable-http on {args.host}:{args.port})")

        app = mcp.streamable_http_app()
        authenticated_app = APIKeyMiddleware(app, oauth_enabled=_oauth_provider is not None)

        sheet_keys = get_active_keys()
        logger.info(f"API key store: {len(sheet_keys)} active key(s)")

        uvicorn.run(authenticated_app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
