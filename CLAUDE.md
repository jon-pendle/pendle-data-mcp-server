# CLAUDE.md

## Project Overview

Pendle Data MCP Server — a Model Context Protocol (MCP) tool server for Pendle protocol data analysis. Deployed as a Cloud Run service, it exposes tools for querying BigQuery tables, DeFiLlama APIs, and product knowledge bases.

## Running

```bash
# Local dev
python -m mcp_server --transport streamable-http

# Docker
docker build -t pendle-mcp-server .
docker run -p 8080:8080 pendle-mcp-server
```

Deployed via Cloud Build → Cloud Run (see `cloudbuild.yaml`).

## Architecture

```
pendle-data-mcp-server/
├── mcp_server/           # Python package
│   ├── server.py         # FastMCP server, auth, routing
│   ├── tool_wrappers.py  # All tool registrations
│   ├── products/         # Per-product data catalogs (pendle, boros, market_funding_rate, frontend_tracking)
│   ├── sql_executor.py   # BigQuery query runner with validation
│   ├── defillama.py      # DeFiLlama API helpers
│   ├── qa_client.py      # QA knowledge base client (calls Cloud Run QA service)
│   ├── google_oauth.py   # OAuth 2.0 provider (Google login)
│   ├── acl_store.py      # Per-user access control (Google Sheets-backed)
│   ├── quota_store.py    # Per-user quota tracking (Firestore)
│   ├── key_store.py      # API key validation (Google Sheets-backed)
│   ├── memory.py         # Learning report storage (BigQuery)
│   └── usage_tracker.py  # Tool call tracking (BigQuery)
├── boros-kb/             # Boros knowledge base files (mounted in Docker)
├── Dockerfile
├── cloudbuild.yaml
└── requirements.txt
```

### Key Patterns
- Products defined in `products/*.py` as `ProductSpec` dataclasses with index + per-table detail catalogs
- All tools registered via `register_tools(mcp)` in `tool_wrappers.py`
- ACL/quota checks via `_guard()` helper before each tool call
- Usage tracked via `_track()` helper after each tool call

## Commit Rules

- **MCP Changelog**: When committing changes, update the `_CHANGELOG` string in `mcp_server/tool_wrappers.py`. Prepend the new entry and remove the oldest entry to keep exactly 10 items. Use the format: `N. YYYY-MM-DD — <commit message>`

## Testing

```bash
python -m pytest
```
