# todo-harvest — review and fix log

14 commits on top of `1e6592d`. Test suite: **504 → 541 passing** (37 new). All hooks clean. Branch: `main`.

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

### Vikunja (verified against v2.3)

**12. Labels actually sync; payload no longer carries dead fields** — `e19348e`
End-to-end probe confirmed Vikunja silently ignores `labels` on task POST/PUT — the existing `payload["labels"]=...` did nothing. Local tag changes never propagated. Also confirmed `done_at` is server-managed (auto-stamped on `done=true`).

Dropped `labels` and `done_at` from `_to_vikunja_payload`. Added `_fetch_all_labels` (workspace index, paginated), `_ensure_label` (cache + create-if-missing), and `_sync_task_labels` (diff current vs desired, attach via `PUT /tasks/{id}/labels`, detach via `DELETE`). Push pre-fetches the label index once.

### Packaging

**13. `pip install .` works** — `7baeaee`
Pinned `[tool.setuptools].packages = ["src", "src.sources"]` so setuptools doesn't try to auto-discover (the unusual `src/` layout would otherwise fail). Added `[project.scripts] todo-harvest = "src.main:main"` console script and `[build-system]` requires.

## Findings deferred (not actioned)

- **Plane URL uses UUID, not sequence_id** — Plane's web URL format varies by version (UUID-based vs identifier+sequence_id). Needs a real Plane instance to verify and fix correctly. Deferred per user (Plane not priority).
- **Vikunja: no "cancelled" state** — Vikunja v2.3 only has `done` boolean. Pulled cancelled tasks don't exist; pushed cancelled tasks become `done=true` (one-way). Documented in `_VIKUNJA_STATUS_TO_BOOL` already.

## Findings since shipped

- **`json.dump(..., default=str)` silent type coercion** — removed in `b1bb4d1`. Now raises `TypeError` on non-serializable values instead of one-shot string coercion that drifts the schema.
- **`_merge_fields` item-level timestamp** — replaced with per-field snapshot diff in `ffa87e2`. mapping.db now stores `last_pulled_fields` JSON; conflict resolution diffs current local and current source against the snapshot per field. Local-only edits and source-only edits both survive even when the other side touched something unrelated.
- **P2-4 inspect column "Has completed" was misleading** — renamed to "Has comp date" in `5d8fe9b`. Actual done counts already in the Status distribution table.

## Healthy (verified clean)

`yaml.safe_load`; SQLite parameterized everywhere; MSAL cache 0o700/0o600; no `verify=False`; no `eval`/`exec`/`shell=True`; auth errors don't trigger retries; tempfile lives next to final path (atomic-rename safe); `REGISTRY` is the single source of truth — `config.SOURCES` derives from it; `mapping.py` has no HTTP imports.

---

## Round 3 — post-fix deep review (2026-04-25)

Fresh review against the 14-fix branch. New issues only — does not repeat already-shipped or already-deferred items.

**Status:** C1, P2-1, P2-2, P2-3, T1 shipped (commits `0368674`, `18212fe`, `37cfeb7`, `97622ea`, `253d325`). P2-4 deferred — design call. T2/T3/T4/T5 covered by the new tests in those commits.

### Critical

**C1 — `_SOURCE_AUTHORITATIVE_FIELDS` clobbers `local_item["updated_date"]` before `upsert` reads it; local-wins lasts exactly one pull cycle** [SHIPPED `0368674`]
`src/local_state.py` `_merge_fields` writes `local_item["updated_date"] = pulled["updated_date"]` because `updated_date` is in `_SOURCE_AUTHORITATIVE_FIELDS`. Then `merge_pulled_items` calls `mapping.upsert(..., local_updated_at=local_item.get("updated_date"))` — which is now the source's older timestamp, not the actual local edit time. On the NEXT pull, `local_dt` ≤ `last_synced_at`, so `local_changed = False`; source wins and overwrites the local edit. Local edits visible for one cycle, then silently reverted.
**Fix:** Don't overwrite `updated_date` when local won any field. Compute `local_won_any` in the merge loop; only adopt source's `updated_date` when `local_won_any is False`.
**Confidence:** 95%

### P2 — correctness

**P2-1 — `SourceDef.push` `except TypeError` swallows real bugs and silently drops `mapping=`** [SHIPPED `18212fe`]
`src/sources/__init__.py:66-70` retries `push()` without `mapping=` if any `TypeError` is raised — including a `TypeError` raised from inside push for an unrelated reason. The retry then runs without mapping, so newly created items aren't recorded in `mapping.db` and become orphans on the next push.
**Fix:** Inspect the push function's signature once at module-load time (`inspect.signature`) and remember whether it accepts `mapping=`. Drop the broad except.

**P2-2 — `_inspect_stats` lex-compares mixed-format ISO timestamps for date range display** [SHIPPED `37cfeb7`]
`src/main.py` `_inspect_stats` uses `min(created)`/`max(updated)` on raw ISO strings. Same bug as the original `resolve_conflict` issue (`Z` vs `+0000` sorts inconsistently). Display-only — produces wrong "earliest/latest" dates when sources are mixed.
**Fix:** Compare the `[:10]` (YYYY-MM-DD) prefix, or parse via `_parse_iso_ts` from `mapping.py`.

**P2-3 — `migrate_legacy_mappings` runs OUTSIDE `transaction()` — N fsyncs on first migration** [SHIPPED `97622ea`]
`src/main.py` `_cmd_pull` calls `source_def.migrate(mapping, raw_items)` before the `with mapping.transaction():` block in `merge_pulled_items`. Each `relabel_source_id` issues its own commit. For a 500-issue Plane workspace migrating from legacy IDs, that's ~500 fsyncs vs 1.
**Fix:** Wrap the migrate call site (or the body of `SourceDef.migrate`) in `mapping.transaction()`.

**P2-4 — `status` and `completed_date` can drift apart with no repair path** [DEFERRED — design call]
`_SOURCE_AUTHORITATIVE_FIELDS` always copies `completed_date` from source without checking against `status`. Notion always emits `completed_date=None` even when `status=done`; older Vikunja tasks may have `done=true` but `done_at` zero-date sentinel (which normalizes to None). Result: `{status: done, completed_date: null}` persists. `_inspect_stats` then mis-reports completion coverage.
**Fix (optional, design call):** post-merge, if `status == "done"` and `completed_date is None`, fall back to `updated_date`. If `status != "done"` and `completed_date` is set, clear it. Or document as expected.

### Test gaps

- **T1** — `TestUnifiedSchema` parametrize at `tests/test_normalizer.py` excludes `"plane"`. Schema conformance for `normalize_plane` is uncovered. [SHIPPED `253d325`]
- **T2** — No test that `SourceDef.push` lets a real `TypeError` from inside push propagate. [SHIPPED with `18212fe` — `test_typeerror_inside_push_propagates`]
- **T3** — No test for `_inspect_stats` date range with mixed-format ISO inputs. [SHIPPED with `37cfeb7` — `test_inspect_stats_date_range_handles_mixed_iso_formats`]
- **T4** — No regression test for C1: local-wins must preserve local edit timestamp. [SHIPPED with `0368674` — `test_local_wins_preserves_local_updated_date`]
- **T5** — No test that the migration runs inside a transaction. [SHIPPED with `97622ea` — `test_migrate_via_sourcedef_uses_transaction`]

---

## Round 4 — snapshot-diff focused review (2026-04-25)

Tightly scoped to commits `ffa87e2` (per-field snapshot) and `b1bb4d1` (default=str removal). Reviewer traced the snapshot correctness manually and confirmed it stores source's last-seen value (not merged result), which is the right design. No data-correctness bugs in the core diff. End-to-end smoke against Vikunja v2.3 verified: independent local + source edits both survive (T0–T5 sequence).

### P1 — semantics

**P1-1 — `conflicts` counter counts any field difference, not bilateral conflicts**
`src/local_state.py` `_merge_fields` increments `conflicts += 1` whenever `local_val != source_val`, including pure source-only updates. After a routine pull where source changed 50 statuses and local was untouched, the summary reports `conflicts: 50` even though zero bilateral conflicts occurred. Pre-existing semantic, but the snapshot path makes it more conspicuous because every source-only change now flows through the conflict path explicitly.

### P2 — test polish

**P2-1 — `test_merge_writes_atomically_per_pull` upsert-count assumption silently brittle**
`tests/test_local_state.py` patches the 3rd `upsert` to raise. Works today because all three items are new (1 upsert each). Pre-existing items would now also call upsert (skip path was changed in `ffa87e2`), so adding a mixed-case scenario to this test would mis-target the failure. Doc-comment fix.

### Test gaps

**T1 — Snapshot content not asserted after merge**
Existing per-field tests check the merged item state but don't read `get_last_pulled_fields` to confirm the snapshot was written with source's values. If `new_snapshot` were accidentally built from `local_item`, the per-field tests still pass (local wins → correct field), but the bug would surface only on the third pull.

**T2 — `export_json` not tested for `TypeError` on non-serializable values**
`save_local_state` has the test (`test_non_serializable_value_raises_loudly`); `export_json` doesn't. Same `default=str` removal applies to both.
