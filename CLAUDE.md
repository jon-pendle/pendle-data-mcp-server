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

## Deployment

**Push-to-main is the deploy.** A GitHub-side Cloud Build trigger watches the
`main` branch — every merge fires a build via `cloudbuild.yaml` that:

1. Initializes the `boros-kb/` submodule (deploy key in Secret Manager).
2. Builds the Docker image and tags it with the commit `$SHORT_SHA`.
3. Pushes to Artifact Registry
   (`asia-southeast1-docker.pkg.dev/pendle-data/cloud-run/pendle-mcp-server`).
4. Rolls out a new Cloud Run revision in `asia-southeast1`.

So the deploy workflow is just:

```bash
git push origin main      # this is the deploy
```

**Do NOT** run `gcloud builds submit --config cloudbuild.yaml` manually as the
deploy — it bypasses the trigger model, can fail on bucket permissions, and
creates a `storageSource` build that doesn't carry the commit metadata.
Manual `gcloud builds submit` is only appropriate for one-off ad-hoc rebuilds
when the trigger is broken or for testing changes from a branch other than
`main` that you don't want to land yet.

Verifying a deploy: most ergonomic check is the Cloud Run service revision
list in the GCP console (or `gcloud run services describe ...` if you have
the role). The build trigger and the `gcloud builds list` views may be hidden
behind IAM roles the everyday SA on dev VMs doesn't hold — silence isn't
proof the build didn't run.

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
