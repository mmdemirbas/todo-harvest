# todo-harvest — review and fix log

12 commits on top of `1e6592d`. Test suite: **504 → 533 passing** (29 new). All hooks clean. Branch: `main`.

## Fixes shipped (priority order)

### P0 — data corruption

**1. Atomic `todos.json` writes** — `871dbc1`
`save_local_state` now writes to a sibling temp file, fsyncs, and `os.replace`s. A crash mid-write previously left an empty file; the next pull then re-created every item with new `local_id`s, breaking every mapping.

**2. Source-owned metadata propagates on merge** — `f91e50f`
`completed_date`, `updated_date`, `created_date`, `category` were never copied from pulled items into local state — only fields in `_MERGE_FIELDS` got updated. Source-side completion was permanently invisible. New `_SOURCE_AUTHORITATIVE_FIELDS` direct-copies them (no conflict resolution — local can't legitimately edit these).

**3. Items with empty `local_id` no longer dropped** — `14984c7`
The merge index keyed on truthy `local_id`. Hand-edited or imported items with `""` or missing `local_id` were silently deleted on every pull. They now go through an orphan list that's re-appended after merge.

**4. Plane mapping by UUID, not sequence_id** — `230ae1b`
`normalize_plane` produced `plane-{project}-{seq}`; `push` looked for `:` and tried to PATCH by UUID. Push always fell through to CREATE, **duplicating every issue in Plane on every sync**. New format `plane-{project}:{UUID}`. `SourceDef.migrate` hook + `plane.migrate_legacy_mappings` rewrites old rows in place using the UUID from the freshly-pulled raw payload — idempotent, runs on every pull, no-op once migrated.

**5. ISO timestamps parsed, not lex-compared** — `1b8b779`
`resolve_conflict` compared timestamps with raw string `>`. `2024-01-15T10:30:00Z` vs `2024-01-15T10:30:00.000+0000` (same instant) sorted differently because `.` (46) < `Z` (90), flipping conflict resolution. Round-tripping a Jira task through Vikunja produced spurious local-wins on every pull. New `_parse_iso_ts` handles trailing `Z`, ±HHMM offsets without colon, and >6-digit fractional seconds.

### P1 — correctness

**6. Sync skips push for failed pulls** — `6a987c0`
`_cmd_sync` ran `_cmd_push` unconditionally. If pull from Vikunja failed but pull from Notion succeeded, push to Vikunja then sent stale local data. `_cmd_pull` now returns `(exit_code, succeeded_services)` and `_cmd_sync` scopes push to that list.

**7. Recursive ADF walker** — `642ed59`
`_extract_adf_text` walked exactly two levels (`doc.content[].content[]`), so text inside bullet lists, tables, panels, blockquotes was silently dropped. Replaced with depth-agnostic walk.

**8. Tags sorted in normalizers** — `ea2b01a`
List equality is order-sensitive, so reordered tags registered as conflicts every pull. All five normalizers now `sorted(set(...))`.

**9. Pagination guards** — `67c7a72`
Every source's pagination was `while True`. Added `MAX_PAGES = 1000` cap and per-source cycle detection (Jira tokens, Notion/Plane cursors, MS Graph nextLinks). MS Graph helper consolidated into one `_paginate_graph`.

### P2 — edge cases

**10. `html.parser` replaces strip regex** — `e743b04`
The old `<[^>]+>` regex broke on attributes containing `>` (`<a href="x>y">link</a>` left `y">link` as visible text) and didn't decode entities (`&amp;` survived literally). Now uses `html.parser` with `convert_charrefs=True`. Drops `<script>`/`<style>` content.

### P3 — performance

**11. Batch SQLite commits in merge** — `7eb5fd6`
Per-operation commits meant 2-3 fsyncs per item. `SyncMapping.transaction()` defers commits inside a block to a single commit on exit, rolls back the entire batch on exception, supports re-entry. Mid-pull crash now leaves mapping.db consistent (atomic at the mapping layer).

### Packaging

**12. `pip install .` works** — `7baeaee`
Pinned `[tool.setuptools].packages = ["src", "src.sources"]` so setuptools doesn't try to auto-discover (the unusual `src/` layout would otherwise fail). Added `[project.scripts] todo-harvest = "src.main:main"` console script and `[build-system]` requires.

## Findings deferred (not actioned)

- **Vikunja push label/done_at semantics** — without an API instance to verify Vikunja's update merge-vs-replace behavior, a "fix" could regress working behavior. The deep review flagged it as speculative.
- **Plane URL uses UUID, not sequence_id** — possibly wrong, but Plane's URL format depends on version. Needs a real Plane instance to verify.
- **`json.dump(..., default=str)` silent type coercion** — only affects `raw` field and only if a source returns non-JSON-serializable types. Currently no source does.
- **`_merge_fields` uses item-level timestamp for all fields** — design vs. code mismatch. Documented in CLAUDE.md as "field-by-field" but is actually item-granularity. Real fix requires per-field timestamp columns in mapping.db.

## Healthy (verified clean)

`yaml.safe_load`; SQLite parameterized everywhere; MSAL cache 0o700/0o600; no `verify=False`; no `eval`/`exec`/`shell=True`; auth errors don't trigger retries; tempfile lives next to final path (atomic-rename safe); `REGISTRY` is the single source of truth — `config.SOURCES` derives from it; `mapping.py` has no HTTP imports.
