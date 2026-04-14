# Completed Improvements

Items from the adversarial review that have been implemented and merged.

## P0 — Correctness / crash bugs

### 1. Notion pagination infinite loop — `33adc3d`
Guard `_fetch_database_pages` against `has_more=true` with `next_cursor=null`.

### 2. Filesystem errors crash with raw traceback — `33adc3d`
Wrapped `export_all()` in `try/except OSError` with human-readable message.

### 3. Config type mismatch causes cryptic crash — `33adc3d`
Reject non-string config values (int, bool) with clear "must be a string" error.

## P1 — Robustness gaps

### 4. MSAL token cache: wrong location, wrong permissions, no atomicity — `e3b604c`
Moved to `~/.config/todo-harvest/msal_cache.json`, `0o700` dir / `0o600` file,
atomic write via tempfile + os.replace, old cache auto-migrated.

### 5. Silent partial output on mass normalization failure — `c285c0f`
Exit code 1 when any source has errors. Distinct message when all items fail normalization.

### 6. Placeholder config values pass validation — `c285c0f`
Detect YOUR_*, DATABASE_ID*, CHANGE_ME, TODO, FIXME prefixes in config values.

### 7. Broad exception handling masks programming errors — `c285c0f`
Catch known source errors specifically. Unexpected errors show traceback with bug-report message.

### 8. HTML body content passed through without stripping — `d48162b`
Strip HTML tags from MS To Do body when `contentType == "html"`. Fixture updated with real markup.

### 9. Python 3.10+ required but not declared — `d48162b`
Added `from __future__ import annotations` to all modules. Python version check in harvest script.

### 10. `harvest` script breaks on Windows — `d48162b`
Added `harvest.ps1` for PowerShell. Added Python version check to bash script.

## P2 — Quality debt

### 11. Triplicated `_request_with_retry` — `6b5d34f`
Extracted to `src/sources/_http.py` with `SourceAuthError`/`SourceFetchError` base classes.

### 18. `_get_token` silent-acquisition failure path untested — `26683a2`
Added test for `acquire_token_silent` returning `None` → device code fallback.

### 19. Notion tag deduplication missing — `30f129f`
Deduplicate via `dict.fromkeys()` preserving order.

### 20. Missing test fixtures for edge-case mappings — `26683a2`
Added tests for `waitingOnOthers`/`deferred`, `Notes`/`Due`/`Deadline` fallbacks, null status.

### 21. Console progress path untested — `26683a2`
Added console-path test for Jira `fetch_all`.

### 22. `test_normalize_error_skips_item` is fragile — `26683a2`
Fixed to use `ValueError` side effect instead of brittle module-level patch.

## P3 — Polish

### 23. Unused `import json` in msftodo.py — `e0c3666`
Removed during msftodo.py rewrite.

### 24. f-strings with no interpolation — `d48162b`
Fixed during msftodo.py rewrite.

### 26. Inconsistent None-guard idiom — `30f129f`
Standardized to `(x or {}).get()` pattern in Jira normalizer.

### 27. Magic string `customfield_10014` — `30f129f`
Extracted to `_JIRA_EPIC_LINK_FIELD` constant with Jira Classic/Next-gen comment.

### 28. `normalizers` dict rebuilt on every call — `30f129f`
Moved to module-level `_NORMALIZERS` dict.

### 29. Redundant `tests/fixtures/.gitkeep` — `e0c3666`
Deleted.

### 30. No `conftest.py` — `26683a2`
Added `tests/conftest.py` with shared fixture loaders.

### 32. Duplicate entry point — `c285c0f`
Removed `if __name__ == "__main__"` from `main.py` (redundant with `__main__.py`).

### 33. Stale `import time as _t` in jira.py — `6b5d34f`
Removed during retry extraction.
