"""Tests for sql_executor._pre_validate.

Focused on partition-filter detection, since that's where most of the
recent bug fixes have landed:

- 2026-04-16  allow backticked partition col  (`dt` = ...)
- 2026-04-16  accept wrapped partition col    (DATE(col), CAST, EXTRACT, ...)
- 2026-04-17  handle expression partition_col (DATE(hour)) — \b around parens

The production partition registry is loaded at module import (real
PARTITION_TABLES). A fixture asserts the registry still contains the
values these tests assume; if a partition_col is renamed upstream, the
fixture fails loudly so the test gets updated instead of silently drifting.
"""

import pytest

from mcp_server.sql_executor import PARTITION_TABLES, _pre_validate


# Table/partition-col combinations the tests rely on.
_EXPECTED = {
    "limit_order_ob_depth_hourly": "DATE(hour)",       # expression-valued
    "pool_metrics_all_in_one_daily": "dt",              # plain
    "v2_mixpanel_events_enriched": "event_time",        # plain, non-trivial name
    "price_feeds": "date",                              # reserved-word flavoured
}


@pytest.fixture(autouse=True)
def _check_registry():
    for short, col in _EXPECTED.items():
        assert PARTITION_TABLES.get(short) == col, (
            f"Test assumes PARTITION_TABLES[{short!r}] == {col!r}, "
            f"found {PARTITION_TABLES.get(short)!r}. Update this fixture "
            f"if the partition col legitimately changed."
        )


def _ok(sql: str):
    err = _pre_validate(sql)
    assert err is None, f"Expected no error, got:\n  {err}\nFor SQL:\n  {sql}"


def _err(sql: str, *must_contain: str):
    err = _pre_validate(sql)
    assert err is not None, f"Expected an error, got None for SQL:\n  {sql}"
    for frag in must_contain:
        assert frag in err, f"Expected {frag!r} in error:\n  {err}"


# ── Expression-valued partition_col (DATE(hour)) — the 2026-04-17 regression ──

class TestExpressionPartitionCol:
    TBL = "`pendle-data.pendle_api.limit_order_ob_depth_hourly`"

    def test_direct_operator(self):
        _ok(f"SELECT * FROM {TestExpressionPartitionCol.TBL} "
            f"WHERE DATE(hour) >= '2026-04-01'")

    def test_between(self):
        _ok(f"SELECT * FROM {TestExpressionPartitionCol.TBL} "
            f"WHERE DATE(hour) BETWEEN '2026-04-01' AND '2026-04-05'")

    def test_no_space(self):
        _ok(f"SELECT * FROM {TestExpressionPartitionCol.TBL} "
            f"WHERE DATE(hour)='2026-04-01'")

    def test_lowercase(self):
        _ok(f"SELECT * FROM {TestExpressionPartitionCol.TBL} "
            f"WHERE date(hour) >= '2026-04-01'")

    def test_in_cte(self):
        _ok(
            "WITH latest AS ("
            f"SELECT MAX(hour) AS h FROM {TestExpressionPartitionCol.TBL} "
            "WHERE DATE(hour) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
            f") SELECT * FROM {TestExpressionPartitionCol.TBL}, latest"
        )

    def test_missing_filter(self):
        _err(f"SELECT * FROM {TestExpressionPartitionCol.TBL} LIMIT 1",
             "DATE(hour)")

    def test_uses_hour_not_date_hour(self):
        # The registered partition is the expression DATE(hour). Filtering
        # on raw `hour` alone doesn't satisfy the check.
        _err(f"SELECT * FROM {TestExpressionPartitionCol.TBL} "
             f"WHERE hour >= TIMESTAMP('2026-04-01')",
             "DATE(hour)")


# ── Plain partition col (dt) — the common case ──

class TestPlainPartitionCol:
    TBL = "`pendle-data.analytics.pool_metrics_all_in_one_daily`"

    def test_direct(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} WHERE dt >= '2026-04-01'")

    def test_backticked(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} WHERE `dt` = '2026-04-01'")

    def test_wrapped_in_date(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} WHERE DATE(dt) = '2026-04-01'")

    def test_wrapped_in_cast(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} "
            f"WHERE CAST(dt AS DATE) = '2026-04-01'")

    def test_wrapped_in_safe_cast(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} "
            f"WHERE SAFE_CAST(dt AS DATE) = '2026-04-01'")

    def test_wrapped_in_extract(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} "
            f"WHERE EXTRACT(YEAR FROM dt) = 2026")

    def test_wrapped_in_date_trunc(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} "
            f"WHERE DATE_TRUNC(dt, WEEK) >= '2026-04-01'")

    def test_table_alias(self):
        _ok(f"SELECT pm.dt FROM {TestPlainPartitionCol.TBL} pm "
            f"WHERE pm.dt >= '2026-04-01'")

    def test_between(self):
        _ok(f"SELECT * FROM {TestPlainPartitionCol.TBL} "
            f"WHERE dt BETWEEN '2026-04-01' AND '2026-04-05'")

    def test_substring_does_not_satisfy(self):
        # `created_dt` must not count as a filter on `dt` — word boundary enforced
        _err(f"SELECT * FROM {TestPlainPartitionCol.TBL} "
             f"WHERE created_dt = '2026-04-01'",
             "'dt'")

    def test_missing_filter(self):
        _err(f"SELECT * FROM {TestPlainPartitionCol.TBL} LIMIT 1", "'dt'")


# ── DATETIME partition col (event_time) — type-sensitive ──

class TestDatetimePartitionCol:
    TBL = "`pendle-data.frontend_tracking.v2_mixpanel_events_enriched`"

    def test_datetime_literal(self):
        _ok(f"SELECT * FROM {TestDatetimePartitionCol.TBL} "
            f"WHERE event_time >= DATETIME '2026-04-01 00:00:00'")

    def test_date_wrapped(self):
        _ok(f"SELECT * FROM {TestDatetimePartitionCol.TBL} "
            f"WHERE DATE(event_time) >= '2026-04-01'")

    def test_substring_event_time_bucket_does_not_satisfy(self):
        _err(f"SELECT * FROM {TestDatetimePartitionCol.TBL} "
             f"WHERE event_time_bucket = 5",
             "'event_time'")


# ── Reserved-word column ('date') ──

class TestReservedWordCol:
    TBL = "`pendle-data.analytics.price_feeds`"

    def test_backticked_date(self):
        _ok(f"SELECT * FROM {TestReservedWordCol.TBL} WHERE `date` = '2026-04-01'")

    def test_plain_date(self):
        _ok(f"SELECT * FROM {TestReservedWordCol.TBL} WHERE date >= '2026-04-01'")


# ── Pre-validator also enforces SELECT-only; make sure it still does ──

class TestSelectOnlyGuard:
    def test_plain_select(self):
        _ok("SELECT 1")

    def test_with_cte(self):
        _ok("WITH t AS (SELECT 1) SELECT * FROM t")

    def test_non_select_first_keyword_rejected(self):
        # INSERT/UPDATE/DELETE etc. fail the first-keyword check
        _err("INSERT INTO t VALUES (1)", "Only SELECT")
        _err("UPDATE t SET x = 1", "Only SELECT")

    def test_multi_statement_rejected(self):
        _err("SELECT 1; SELECT 2", "Multiple statements")

    def test_drop_keyword_anywhere_rejected(self):
        # DML keyword appearing inside a SELECT (e.g. in a literal) still rejected
        _err("SELECT 'payload: DROP TABLE' AS x", "DROP")
