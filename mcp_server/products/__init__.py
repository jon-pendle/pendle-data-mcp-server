"""
Product registry for the MCP server.

Each product defines its own tables, catalog, and optional extra tools.
The registry aggregates all products for shared guardrails (run_sql whitelist).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@dataclass(frozen=True)
class TableSpec:
    """One queryable BigQuery table."""

    fq_table: str
    partition_col: str | None = None
    require_production_source: bool = False
    description: str = ""     # short summary + key metrics (for index)
    catalog: str = ""         # full schema, rules, SQL examples (for detail)

    @property
    def table_name(self) -> str:
        return self.fq_table.split(".")[-1]


@dataclass(frozen=True)
class ProductSpec:
    """Complete specification for one data product."""

    product_id: str
    display_name: str
    tables: tuple[TableSpec, ...]
    context: str              # product-level business rules (returned with index)
    tool_description: str     # description for get_<product_id>_data_catalog
    table_detail_description: str = ""  # description for get_<product_id>_table_detail
    register_extra_tools: Callable[["FastMCP", Callable], None] | None = None


# ── Registry ──────────────────────────────────────────────────────────

_PRODUCTS: dict[str, ProductSpec] = {}


def register_product(spec: ProductSpec) -> None:
    """Register a product. Called at import time by product modules."""
    if spec.product_id in _PRODUCTS:
        raise ValueError(f"Duplicate product_id: {spec.product_id}")
    _PRODUCTS[spec.product_id] = spec


def get_all_products() -> list[ProductSpec]:
    """Return all registered products (stable insertion order)."""
    return list(_PRODUCTS.values())


def get_product(product_id: str) -> ProductSpec:
    """Return a single product by ID."""
    return _PRODUCTS[product_id]


# ── Aggregated guardrails (consumed by sql_executor) ──────────────────

def get_all_allowed_tables() -> set[str]:
    """Aggregate allowed fully-qualified table names across all products."""
    return {
        t.fq_table
        for p in _PRODUCTS.values()
        for t in p.tables
    }


def get_all_partition_tables() -> dict[str, str]:
    """Aggregate {table_name: partition_col} across all products."""
    result: dict[str, str] = {}
    for p in _PRODUCTS.values():
        for t in p.tables:
            if t.partition_col:
                result[t.table_name] = t.partition_col
    return result


def get_table_to_product_map() -> dict[str, str]:
    """Map fully-qualified table name → product_id."""
    return {
        t.fq_table: p.product_id
        for p in _PRODUCTS.values()
        for t in p.tables
    }


def get_all_production_source_tables() -> set[str]:
    """Aggregate tables that must enforce data_source='production'."""
    return {
        t.fq_table
        for p in _PRODUCTS.values()
        for t in p.tables
        if t.require_production_source
    }


# ── Index & detail helpers ─────────────────────────────────────────────

def build_product_index(product: ProductSpec) -> str:
    """Build the compact index for a product: context + table summaries."""
    lines = [product.context.rstrip(), "", "## Tables", ""]
    for t in product.tables:
        partition = f" | partition: `{t.partition_col}`" if t.partition_col else ""
        lines.append(f"### `{t.table_name}`{partition}")
        if t.description:
            lines.append(t.description)
        lines.append("")
    lines.append(
        f"Call get_table_detail(product_id=\"{product.product_id}\", table_name=...) "
        "for full column definitions and SQL examples."
    )
    return "\n".join(lines)


def get_table_detail(product_id: str, table_name: str) -> str | None:
    """Look up a table's full catalog within a specific product. Returns None if not found."""
    if product_id not in _PRODUCTS:
        return None
    for t in _PRODUCTS[product_id].tables:
        if t.table_name == table_name or t.fq_table == table_name:
            return t.catalog or None
    return None


def get_all_table_names() -> list[str]:
    """Return all registered table short names (for error messages)."""
    return [t.table_name for p in _PRODUCTS.values() for t in p.tables]


# ── Auto-register product modules ────────────────────────────────────

from .pendle import SPEC as _pendle  # noqa: E402
register_product(_pendle)
from .boros import SPEC as _boros  # noqa: E402
register_product(_boros)
from .market_funding_rate import SPEC as _market_funding_rate  # noqa: E402
register_product(_market_funding_rate)
from .frontend_tracking import SPEC as _frontend_tracking  # noqa: E402
register_product(_frontend_tracking)
from .twitter_engagement import SPEC as _twitter_engagement  # noqa: E402
register_product(_twitter_engagement)
