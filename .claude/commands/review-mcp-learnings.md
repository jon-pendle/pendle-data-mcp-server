Review fresh MCP telemetry (learning_reports + tool_usage) for bugs and knowledge gaps, then apply actionable fixes.

## Steps

1. **Read the baseline** from memory (`reference_mcp_review_cutoff.md`) to get the last-reviewed timestamps for `learning_reports.reported_at` and `tool_usage.called_at`.

2. **Pull new learning_reports** since cutoff:
   ```
   bq query --project_id=pendle-data --use_legacy_sql=false --format=json \
     'SELECT reported_at, category, source_tool, user_email, model, content, question_context
      FROM `pendle-data.mcp.learning_reports`
      WHERE reported_at > "<learning_cutoff>"
      ORDER BY reported_at DESC'
   ```
   Also get counts and date range. If zero rows and `tool_usage` delta is also small (<100 new run_sql calls in step 3), report "nothing actionable" and stop before touching anything.

3. **Pull tool_usage summary** since cutoff — overall failure rate and top error patterns in `run_sql` (parameters column holds the SQL and self-reported model):
   ```
   SELECT
     COUNT(*) AS calls,
     COUNTIF(bytes_mb=0) AS fails,
     ROUND(SAFE_DIVIDE(COUNTIF(bytes_mb=0), COUNT(*))*100, 1) AS fail_pct,
     COUNTIF(bytes_mb=0 AND REGEXP_CONTAINS(JSON_EXTRACT_SCALAR(parameters,'$.sql'), r'INFORMATION_SCHEMA')) AS info_schema_fishing,
     COUNTIF(bytes_mb=0 AND REGEXP_CONTAINS(JSON_EXTRACT_SCALAR(parameters,'$.sql'), r'pendle-analytics-bf8c0|pendle-analytics\.|pencosystem|pendle_dw|pendle_core')) AS wrong_project
   FROM `pendle-data.mcp.tool_usage`
   WHERE tool_name='run_sql' AND called_at > '<usage_cutoff>'
   ```
   If ≥200 new run_sql calls, also run a per-model failure-rate breakdown (`JSON_EXTRACT_SCALAR(parameters,'$.model')`) — useful for catching newly-onboarded models or client regressions.

4. **Triage** each learning report and each frequent failure pattern into one of:
   - **MCP bug** — fix in `sql_executor.py` / `tool_wrappers.py` / `products/*.py`. Always verify the fix logic with a throwaway script in `/tmp/` before committing.
   - **Knowledge gap** — edit the relevant product catalog description in `mcp_server/products/*.py`.
   - **Data gap** — not fixable here; note it for the user to file upstream.
   - **Noise** (test rows, one-off user error) — ignore.

   Cross-reference: a learning that aligns with a high-frequency failure pattern in `tool_usage` is the highest ROI. A learning with no matching pattern in telemetry may be a one-off.

5. **Present a summary** to the user: each bucket, proposed action per item, and your ROI ranking. **Ask which to apply** before editing any file.

6. **Apply approved changes** as separate commits (the commit rule auto-updates `_CHANGELOG`).

7. **Update the baseline memory** (`reference_mcp_review_cutoff.md`) with the max `reported_at` and max `called_at` observed during this run, the review date, and the commit hashes produced.

8. Remind the user to push so Cloud Build redeploys.
