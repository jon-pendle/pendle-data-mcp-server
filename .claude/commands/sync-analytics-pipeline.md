Sync MCP product catalogs with the latest pendle_analytics_pipeline schema changes.

## Steps

1. **Read the baseline** from memory (`reference_pipeline_version.md`) to get the last-synced commit hash and repo path.

2. **Pull and diff** the pipeline repo:
   ```
   cd /home/jon/work/pendle_analytics_pipeline && git pull
   git log --oneline <baseline_commit>..HEAD -- definitions/
   ```
   If no changes, report "already up to date" and stop.

3. **Analyze each changed `.sqlx` file** — read the full diff to identify:
   - New columns added to existing tables
   - New tables created
   - Renamed/removed columns
   - Logic changes (e.g. null handling, joins)

4. **Present a summary** to the user listing each affected MCP product and table, with the specific columns/changes. **Ask the user which changes to apply** before editing any catalog files.

5. **Apply approved changes** to the corresponding catalog files in `mcp_server/products/*.py`:
   - Add new columns to the appropriate section (with correct aggregation type)
   - Add warnings/notes where semantics changed
   - For new tables: create a new catalog string and register it

6. **Update the baseline memory** (`reference_pipeline_version.md`) with the new HEAD commit hash and date.

7. Remind the user to commit (the commit rule will handle changelog update automatically).
