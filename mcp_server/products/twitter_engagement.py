"""
Twitter Engagement product specification.

Covers tweet engagement tracking across two tables:
- tweet_engagement_delta_hourly: hourly engagement increments per tweet
- tweet_basic_infos_latest_hourly: tweet metadata snapshot (author, text, timestamps)
"""

from . import ProductSpec, TableSpec


_CONTEXT = """\
# Twitter Engagement Data Catalog

## Overview

Two tables track tweet engagement metrics. They are complementary and
joinable on `tweet_id`.

| Table (short name) | Role | Grain |
|---|---|---|
| `tweet_engagement_delta_hourly` | Fact — hourly engagement **increments** | `(tweet_id, timestamp)` |
| `tweet_basic_infos_latest_hourly` | Dimension — tweet metadata snapshot | `(tweet_id)` latest |

## CRITICAL: Delta Values Are Increments, NOT Cumulative Totals

`tweet_engagement_delta_hourly` stores the **change** in each metric per hour.
- Values can be **negative** (e.g. unlike, unretweet).
- To get total engagement over a period: `SUM(like_count)`, `SUM(impression_count)`, etc.
- To get current cumulative total: sum ALL deltas for that tweet from the beginning.
- `interpolation_gap`: number of hours since last observation. Filter `interpolation_gap = 1` for continuous data points.

## Typical Join Pattern

```sql
SELECT b.author_name, b.tweet_text,
  SUM(d.like_count) AS likes, SUM(d.impression_count) AS impressions
FROM `pendle-data.twitter_engagement.tweet_engagement_delta_hourly` d
JOIN `pendle-data.twitter_engagement.tweet_basic_infos_latest_hourly` b USING(tweet_id)
WHERE d.timestamp >= TIMESTAMP('2026-03-24')
GROUP BY b.author_name, b.tweet_text
ORDER BY impressions DESC
```
"""


# ── Per-table catalogs ───────────────────────────────────────────────

_ENGAGEMENT_DELTA = """\
## `pendle-data.twitter_engagement.tweet_engagement_delta_hourly`

Hourly engagement increments per tweet. Each row represents the **change**
in engagement metrics during that hour.

- Partition: `timestamp` (DAY) — always filter on `timestamp`.
- Unique key: `(tweet_id, timestamp)`.

### Fields

- `tweet_id` (STRING, REQUIRED): unique tweet identifier
- `timestamp` (TIMESTAMP, REQUIRED): hour of this delta observation
- `retweet_count` (FLOAT): change in retweets this hour
- `reply_count` (FLOAT): change in replies this hour
- `like_count` (FLOAT): change in likes this hour
- `quote_count` (FLOAT): change in quote tweets this hour
- `bookmark_count` (FLOAT): change in bookmarks this hour
- `impression_count` (FLOAT): change in impressions this hour
- `interpolation_gap` (INTEGER): hours since last observation (1 = continuous)

### Important Notes
- All count fields are **deltas** (increments), not cumulative totals.
- Negative values are valid (e.g. unlikes, unretweets).
- Filter `interpolation_gap = 1` for high-quality continuous data points.
- For total engagement in a period, use SUM().

### Examples

```sql
-- Total engagement gained per tweet in the last 7 days
SELECT tweet_id,
  SUM(like_count) AS likes_gained,
  SUM(retweet_count) AS retweets_gained,
  SUM(impression_count) AS impressions_gained
FROM `pendle-data.twitter_engagement.tweet_engagement_delta_hourly`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY tweet_id
ORDER BY impressions_gained DESC
LIMIT 20
```

```sql
-- Hourly engagement trend for a specific tweet
SELECT timestamp,
  like_count, retweet_count, impression_count
FROM `pendle-data.twitter_engagement.tweet_engagement_delta_hourly`
WHERE timestamp >= TIMESTAMP('2026-03-28')
  AND tweet_id = '2034260987197444255'
ORDER BY timestamp
```
"""

_BASIC_INFOS = """\
## `pendle-data.twitter_engagement.tweet_basic_infos_latest_hourly`

Latest snapshot of tweet metadata. One row per tweet with the most
recent observation.

- No partition — table is small (one row per tracked tweet).
- Unique key: `tweet_id`.

### Fields

- `tweet_id` (STRING): unique tweet identifier
- `author_id` (STRING): Twitter user ID of the author
- `author_name` (STRING): author category label (e.g. 'other')
- `tweet_text` (STRING): full tweet text content
- `tweet_created_at` (TIMESTAMP): when the tweet was published
- `tweet_referenced_tweet_ids_str` (STRING): comma-separated IDs of referenced tweets (retweet/quote source), NULL if original
- `tweet_in_reply_to_user_id` (STRING): user ID being replied to, NULL if not a reply
- `latest_update_ts` (TIMESTAMP): when this snapshot was last refreshed

### Examples

```sql
-- Recent tweets with metadata
SELECT tweet_id, author_name, tweet_text,
  tweet_created_at, latest_update_ts
FROM `pendle-data.twitter_engagement.tweet_basic_infos_latest_hourly`
ORDER BY tweet_created_at DESC
LIMIT 20
```

```sql
-- Top tweets by engagement in the last 7 days (join pattern)
SELECT b.tweet_text, b.tweet_created_at, b.author_name,
  SUM(d.like_count) AS likes,
  SUM(d.impression_count) AS impressions,
  SUM(d.retweet_count) AS retweets
FROM `pendle-data.twitter_engagement.tweet_engagement_delta_hourly` d
JOIN `pendle-data.twitter_engagement.tweet_basic_infos_latest_hourly` b USING(tweet_id)
WHERE d.timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY b.tweet_text, b.tweet_created_at, b.author_name
ORDER BY impressions DESC
LIMIT 10
```
"""


SPEC = ProductSpec(
    product_id="twitter_engagement",
    display_name="Twitter Engagement",
    tables=(
        TableSpec(
            "pendle-data.twitter_engagement.tweet_engagement_delta_hourly",
            partition_col="timestamp",
            description=(
                "Hourly engagement increments per tweet (deltas, NOT cumulative). "
                "Grain: (tweet_id, timestamp).\n"
                "Key metrics: like_count, retweet_count, reply_count, quote_count, "
                "bookmark_count, impression_count (all deltas).\n"
                "→ Use for: engagement trends, total engagement over a period (SUM the deltas)."
            ),
            catalog=_ENGAGEMENT_DELTA,
        ),
        TableSpec(
            "pendle-data.twitter_engagement.tweet_basic_infos_latest_hourly",
            description=(
                "Tweet metadata snapshot (one row per tweet, latest state). "
                "No partition.\n"
                "Key fields: tweet_id, author_id, author_name, tweet_text, tweet_created_at.\n"
                "→ Use for: tweet content, authorship, join with delta table on tweet_id."
            ),
            catalog=_BASIC_INFOS,
        ),
    ),
    context=_CONTEXT,
    tool_description=(
        "Returns the Twitter Engagement catalog INDEX: delta vs cumulative rules "
        "(CRITICAL — values are hourly increments, not totals), join patterns, "
        "and table summaries.\n\n"
        "CALL THIS FIRST before querying any tweet engagement table. "
        "Then call get_table_detail(product_id=\"twitter_engagement\", table_name=...) "
        "for full column definitions."
    ),
    table_detail_description=(
        "Full column definitions, aggregation rules, and SQL examples for a "
        "Twitter Engagement table. "
        "Available tables: tweet_engagement_delta_hourly, tweet_basic_infos_latest_hourly."
    ),
    register_extra_tools=None,
)
