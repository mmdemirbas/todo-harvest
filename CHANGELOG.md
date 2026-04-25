# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `save_local_state` now writes `todos.json` atomically (tempfile +
  `os.replace`). A crash mid-write previously truncated the file and the
  next pull re-created every item with new `local_id`s, breaking every
  mapping.
- `merge_pulled_items` now copies source-owned metadata (`completed_date`,
  `updated_date`, `created_date`, `category`, `raw`, `url`) from the
  pulled item on every merge. Previously these were silently stale —
  source-side completion or category move was permanently invisible in
  local state.
- Items with empty or missing `local_id` are preserved through merge
  instead of being silently dropped.
- Plane mapping rows now key on the API UUID (`{project_id}:{uuid}`),
  not the per-project `sequence_id`. Push previously fell through to
  CREATE on every run, duplicating issues. A one-shot migration
  (`plane.migrate_legacy_mappings`) rewrites legacy rows on first pull
  after upgrade.
- ISO 8601 timestamps in `resolve_conflict` are parsed before comparison.
  Mixed formats (`...Z` vs `...+0000` for the same instant) no longer
  flip conflict resolution by lexicographic accident.
- Sync skips push for any service whose pull failed — pushing back
  stale local state could overwrite remote changes that landed since the
  last successful pull.
- Vikunja push now actually syncs labels via the dedicated
  `/tasks/{id}/labels` endpoints. The `labels` field on task POST/PUT is
  silently ignored by Vikunja (verified against v2.3); the previous code
  thought it was syncing them. Removed `done_at` from the payload —
  Vikunja sets it server-side on `done=true`.
- ADF (Jira) description extractor walks the document tree recursively.
  Previously stopped at depth 2, dropping text inside bullet lists,
  tables, panels, and blockquotes.
- HTML stripper uses `html.parser` instead of a regex. Decodes entities
  (`&amp;`, `&lt;`, `&nbsp;`), drops `<script>`/`<style>` content, and
  tolerates attributes containing `>`.
- Tags lists are sorted+deduped in every normalizer so reordering on the
  source side does not register as a conflict on every pull.
- Pull summary's `conflicts` counter now reports only true bilateral
  conflicts (both sides changed since last pull), not any field
  difference. Pure source-only updates were inflating the metric to
  the field-change count of routine pulls.
- `save_local_state` and `export_json` no longer use `default=str` —
  any non-JSON-serializable value now raises `TypeError` instead of
  silently coercing to a string and drifting the schema across cycles.
- `inspect stats` column "Has completed" renamed to "Has comp date" —
  the column counts the timestamp field's presence (which Notion never
  emits even when `status=done`), not actual completed items. Use the
  Status distribution table for done counts.

### Added

- Per-field conflict resolution. mapping.db gains a `last_pulled_fields`
  JSON snapshot column. `_merge_fields` diffs current local and current
  source against the snapshot per field; local-only edits and
  source-only edits both survive even when the other side made
  unrelated changes. Legacy rows without a snapshot fall back to the
  timestamp comparison until the first new pull populates them.
- Pagination guards in every source: hard cap of 1000 pages per pull,
  plus cursor/token/`@odata.nextLink` cycle detection (Jira, Notion,
  Plane, MS Graph). A buggy or hostile API can no longer infinite-loop
  the CLI.
- `SyncMapping.transaction()` context manager batches per-item writes
  into one commit and rolls back the entire batch on exception.
  `merge_pulled_items` uses it, so a pull is atomic at the mapping
  layer (no half-merged state on a mid-pull crash).
- `SourceDef.migrate` hook — sources can declare an optional
  `migrate_legacy_mappings(mapping, raw_items)` for per-source mapping
  migrations applied between pull and merge.
- `pip install .` works without rename: `[tool.setuptools] packages =
  ["src", "src.sources"]` pins the layout, and a `todo-harvest` console
  script entry point is registered.

## [0.1.0] — 2026-04-15

Initial public release.

### Features

- Pull and merge TODO items from five sources into a local state file:
  Vikunja, Jira, Microsoft To Do, Notion, and Plane (self-hosted).
- Push local state back to Vikunja and Plane. Push is not yet implemented
  for Jira or Microsoft To Do (stubs raise `NotImplementedError`). Notion
  is pull-only by design.
- Unified schema with config-driven status, priority, and field mappings
  for Jira, Notion, and Plane.
- Conflict resolution on pull: field-by-field comparison using timestamps.
- Local inspection commands: `inspect projects`, `inspect stats`,
  `inspect fields`.
- Snapshot export to JSON and CSV.
- Secure MSAL token cache (`~/.config/todo-harvest/msal_cache.json`,
  `0o700` directory, `0o600` file, atomic writes).
- Shared HTTP retry layer with exponential backoff on 429/5xx/network
  errors and a 30-second per-request timeout.
- Bootstrap scripts for macOS/Linux (`./todo`) and Windows (`harvest.ps1`).
