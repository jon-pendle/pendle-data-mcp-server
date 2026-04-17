"""
SQL executor with guardrails for the Pendle MCP server.

Validates and executes SELECT queries against BigQuery with:
- SELECT-only enforcement (no DML)
- Table whitelist — enforced via BigQuery dry-run (handles all reference styles)
- Partition filter requirement (for partitioned tables)
- Byte billing cap (maximum_bytes_billed)
- Timeout control
- Result row limit
"""

import re
import json
import asyncio
import logging
from io import StringIO

import pandas as pd
from google.cloud import bigquery

from .products import (
    get_all_allowed_tables,
    get_all_partition_tables,
    get_all_production_source_tables,
    get_table_to_product_map,
)

logger = logging.getLogger("pendle_mcp")

# ── Server-level guardrail defaults (hard ceiling, overridable downward per user) ──

DEFAULT_MAX_BYTES_MB = 500
DEFAULT_QUERY_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RESULT_ROWS = 10_000

ALLOWED_TABLES = get_all_allowed_tables()
TABLE_TO_PRODUCT = get_table_to_product_map()

# Tables that MUST have a partition filter in WHERE clause
PARTITION_TABLES = get_all_partition_tables()
PRODUCTION_SOURCE_TABLES = get_all_production_source_tables()

# ── Client (lazy init) ───────────────────────────────────────────────

_bq_client: bigquery.Client | None = None


def _get_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project="pendle-data")
    return _bq_client


# ── Static pre-checks (rules BigQuery dry-run cannot enforce) ────────

def _clean_sql(sql: str) -> str:
    """Strip markdown fences, SQL comments, and whitespace."""
    s = sql.strip()
    if s.startswith("```"):
        s = re.sub(r"^```\w*\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    s = re.sub(r"^(\s*--[^\n]*\n)+", "", s)
    return s.strip()


def _pre_validate(sql: str) -> str | None:
    """
    Static checks that run before dry-run.

    Only covers rules that BigQuery itself won't enforce:
    - SELECT-only (no DML)
    - No multiple statements
    - Partition column filter requirement
    - data_source = 'production' filter for restricted tables
    """
    stripped = _clean_sql(sql)

    # 1. SELECT-only
    first_keyword = re.match(r"^\s*(\w+)", stripped, re.IGNORECASE)
    if not first_keyword or first_keyword.group(1).upper() not in ("SELECT", "WITH"):
        return "Only SELECT queries are allowed (query must start with SELECT or WITH)."

    without_trailing = stripped.rstrip(";").strip()
    if ";" in without_trailing:
        return "Multiple statements are not allowed."

    upper = stripped.upper()
    for kw in ("CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT", "REVOKE",
                "INSERT", "DELETE", "MERGE"):
        if re.search(rf"\b{kw}\b", upper):
            return f"Statement type '{kw}' is not allowed. Only SELECT is permitted."

    # 2. Partition filter check — partition column must be referenced somewhere.
    # Accepts wrapped forms like DATE(col), CAST(col AS DATE), DATE_TRUNC(col, WEEK),
    # EXTRACT(YEAR FROM col), `col`, t.col, etc. BigQuery's byte cap (enforced on
    # dry-run via maximum_bytes_billed) catches queries that mention the col but
    # don't actually prune partitions — this check is only for early UX feedback.
    for table_name, partition_col in PARTITION_TABLES.items():
        if table_name in stripped:
            escaped = re.escape(partition_col)
            # Use word boundaries only for plain column names; partition_col may
            # be an expression like "DATE(hour)" where \b around parens fails.
            pattern = rf"\b{escaped}\b" if re.fullmatch(r"\w+", partition_col) else escaped
            if not re.search(pattern, stripped, re.IGNORECASE):
                return (
                    f"Query references '{table_name}' but does not filter on "
                    f"partition column '{partition_col}'. Add a WHERE condition on "
                    f"'{partition_col}' to control query cost."
                )

    # 3. Required production-source filter (text-based, same reason)
    backtick_refs = re.findall(r"`([^`]+)`", stripped)
    for ref in backtick_refs:
        if ref in PRODUCTION_SOURCE_TABLES:
            if not re.search(r"\bdata_source\b\s*=\s*'production'", stripped, re.IGNORECASE):
                return (
                    f"Query references '{ref}' and must filter with "
                    "data_source = 'production'."
                )

    return None


_INFORMATION_SCHEMA_VIEWS = frozenset({
    "TABLES", "COLUMNS", "PARTITIONS", "TABLE_OPTIONS",
    "COLUMN_FIELD_PATHS", "TABLE_STORAGE", "VIEWS",
})


def _dry_run_validate(sql: str, effective_bytes_mb: int, allowed_products: set[str] | None = None) -> str | None:
    """
    Submit a dry-run to BigQuery and validate referenced tables against the whitelist.

    BigQuery resolves all reference styles (backtick variants, INFORMATION_SCHEMA, etc.)
    and returns the canonical table list — no regex required.

    All tables are checked uniformly against ALLOWED_TABLES:
    - Regular tables:     project.dataset.table
    - INFORMATION_SCHEMA: project.dataset.INFORMATION_SCHEMA  (all views share one key)

    To allow INFORMATION_SCHEMA on a dataset, add "project.dataset.INFORMATION_SCHEMA"
    to the product's table list explicitly.

    Returns an error string if denied, None if allowed.
    """
    client = _get_client()
    job_config = bigquery.QueryJobConfig(
        dry_run=True,
        use_legacy_sql=False,
        maximum_bytes_billed=effective_bytes_mb * 1024 * 1024,
    )
    try:
        job = client.query(sql, job_config=job_config)
    except Exception as e:
        err = str(e)
        if "exceeded" in err.lower() and "bytes" in err.lower():
            return (
                f"Query exceeds byte limit ({effective_bytes_mb} MB). "
                "Narrow your date range or add more filters."
            )
        return f"Query syntax error: {err}"

    if not job.referenced_tables:
        return "Query must reference at least one allowed table."

    for table in job.referenced_tables:
        # Normalize INFORMATION_SCHEMA views to a single canonical key
        # so any view (TABLES, COLUMNS, etc.) is controlled by one whitelist entry.
        if table.table_id.upper() in _INFORMATION_SCHEMA_VIEWS:
            ref = f"{table.project}.{table.dataset_id}.INFORMATION_SCHEMA"
        else:
            ref = f"{table.project}.{table.dataset_id}.{table.table_id}"

        if ref not in ALLOWED_TABLES:
            return f"Table '{ref}' is not in the allowed table list."

        # Product-level access check
        if allowed_products is not None:
            product_id = TABLE_TO_PRODUCT.get(ref)
            if product_id and product_id not in allowed_products:
                return (
                    f"Access denied: table '{ref}' belongs to product '{product_id}'. "
                    f"Your access is limited to: {', '.join(sorted(allowed_products))}."
                )

    return None


# ── Execution ────────────────────────────────────────────────────────

async def execute_sql(
    sql: str,
    max_bytes_mb: int = 0,
    max_rows: int = 0,
    timeout_s: int = 0,
    allowed_products: set[str] | None = None,
) -> str:
    """Validate and execute a SELECT query against BigQuery.

    Validation flow:
    1. _pre_validate: fast static checks (SELECT-only, partition filter, etc.)
    2. _dry_run_validate: BigQuery resolves all table refs; we whitelist-check them.
    3. Execute the real query with the same job config.

    Returns JSON string with either:
    - {"data": csv_string, "metadata": {...}} on success
    - {"error": "...", "error_type": "validation|execution|timeout|quota"} on failure
    """
    effective_bytes_mb = (
        min(max_bytes_mb, DEFAULT_MAX_BYTES_MB) if max_bytes_mb > 0 else DEFAULT_MAX_BYTES_MB
    )
    effective_max_rows = (
        min(max_rows, DEFAULT_MAX_RESULT_ROWS) if max_rows > 0 else DEFAULT_MAX_RESULT_ROWS
    )
    effective_timeout = (
        min(timeout_s, DEFAULT_QUERY_TIMEOUT_SECONDS) if timeout_s > 0 else DEFAULT_QUERY_TIMEOUT_SECONDS
    )

    sql = _clean_sql(sql)

    # Stage 1: static pre-checks
    error = _pre_validate(sql)
    if error:
        return json.dumps({"error": error, "error_type": "validation"})

    # Stage 2: dry-run whitelist check (runs in executor to stay non-blocking)
    loop = asyncio.get_event_loop()
    error = await loop.run_in_executor(
        None, lambda: _dry_run_validate(sql, effective_bytes_mb, allowed_products)
    )
    if error:
        return json.dumps({"error": error, "error_type": "validation"})

    # Stage 3: real execution
    try:
        client = _get_client()
        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=effective_bytes_mb * 1024 * 1024,
        )

        query_job = await loop.run_in_executor(
            None, lambda: client.query(sql, job_config=job_config)
        )

        result = await loop.run_in_executor(
            None, lambda: query_job.result(timeout=effective_timeout)
        )

        df = result.to_dataframe()
        truncated = False
        if len(df) > effective_max_rows:
            df = df.head(effective_max_rows)
            truncated = True

        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(str)
            elif hasattr(df[col].dtype, "name") and "date" in df[col].dtype.name.lower():
                df[col] = df[col].astype(str)

        for col in df.select_dtypes(include=["float64"]).columns:
            df[col] = df[col].round(4)

        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()

        bytes_processed = query_job.total_bytes_processed or 0
        metadata = {
            "rows": len(df),
            "bytes_processed_mb": round(bytes_processed / (1024 * 1024), 2),
            "truncated": truncated,
        }

        return json.dumps({"data": csv_data, "metadata": metadata})

    except Exception as e:
        err_str = str(e)

        if "exceeded" in err_str.lower() and "bytes" in err_str.lower():
            return json.dumps({
                "error": f"Query exceeds byte limit ({effective_bytes_mb} MB). "
                         "Narrow your date range or add more filters.",
                "error_type": "quota",
            })

        if "timeout" in err_str.lower() or "deadline" in err_str.lower():
            return json.dumps({
                "error": "Query timed out. Simplify the query or narrow the date range.",
                "error_type": "timeout",
            })

        logger.error(f"SQL execution error: {err_str}")

        # Sanitize: strip BigQuery job metadata and don't echo user-controlled
        # ERROR() content verbatim (prevents reflected content injection).
        clean_err = re.sub(r"\n\nLocation:.*", "", err_str, flags=re.DOTALL)
        # Strip HTTP status prefix (e.g. "400 POST https://...")
        clean_err = re.sub(r"^\d{3}\s+(GET|POST|PUT|DELETE)\s+https?://\S+:\s*", "", clean_err)
        return json.dumps({
            "error": f"Query execution failed: {clean_err}",
            "error_type": "execution",
        })
