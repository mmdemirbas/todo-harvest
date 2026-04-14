# Improvement Plan

Consolidated findings from 10 adversarial reviews: security, clean code, performance,
test coverage, modularity, user experience, error resilience, maintainability,
structure, and compatibility.

34 findings total, deduplicated and prioritized into 4 tiers.

## Priority tiers

- **P0 — Correctness/crash bugs.** The tool produces wrong results or hangs.
- **P1 — Robustness gaps.** The tool works on the happy path but breaks on realistic edge cases.
- **P2 — Quality debt.** Slows down future development or degrades maintainability.
- **P3 — Polish.** Minor issues, fix when touching nearby code.

---

## P0 — Correctness / crash bugs

### 1. Notion pagination infinite loop
- **Reviews:** Error Resilience
- **Location:** `src/sources/notion.py` — `_fetch_database_pages`
- **Problem:** If the Notion API returns `has_more: true` with `next_cursor: null`,
  the loop re-sends the first-page request forever. This can happen with API edge
  conditions or non-standard proxies.
- **Fix:** After reading `next_cursor`, if it is `None` while `has_more` is `True`,
  break and log a warning.
- **Tests:** Add a test with `has_more: true, next_cursor: null` asserting the loop
  terminates and returns the partial results.
- **Effort:** Small.

### 2. Filesystem errors crash with raw traceback, data lost
- **Reviews:** Error Resilience, UX
- **Location:** `src/main.py` — `export_all()` call (around line 118)
- **Problem:** No try/except around `export_all()`. Disk full, permission denied, or
  locked file produces a Python traceback. All fetched and normalized data is lost
  with no recovery.
- **Fix:** Wrap `export_all()` in `try/except OSError`. Print a human-readable message
  naming the file and the OS error. Return exit code 1.
- **Tests:** Add a test with a read-only output directory asserting the error message
  and exit code.
- **Effort:** Small.

### 3. Config type mismatch causes cryptic crash
- **Reviews:** Error Resilience, UX
- **Location:** `src/config.py` — `validate_source`
- **Problem:** YAML parses unquoted numbers as integers. `api_token: 12345` passes
  validation (not a string, so the `isinstance(val, str)` empty-check is skipped).
  Then `base_url.rstrip("/")` on an int raises `AttributeError`. User sees traceback.
- **Fix:** In `validate_source`, check `not isinstance(val, str)` for string-typed
  keys and emit "must be a quoted string" error. Coerce or reject.
- **Tests:** Add test for integer and boolean config values.
- **Effort:** Small.

---

## P1 — Robustness gaps

### 4. MSAL token cache: wrong location, wrong permissions, no atomicity
- **Reviews:** Security, Error Resilience, Compatibility, Maintainability
- **Location:** `src/sources/msftodo.py:13`
- **Problem:** Cache stored as a relative path in cwd with default umask. Contains
  access + refresh tokens. Concurrent writes corrupt the file. Not in `.gitignore`
  explicitly.
- **Fix:**
  - Move to `~/.config/todo-harvest/msal_cache.json` (XDG-compliant)
  - Create directory with `0o700`, write file with `0o600`
  - Use atomic write (write to temp file, then `os.replace`)
  - Add old filename to `.gitignore`
  - Migrate old cache on first run if it exists
- **Tests:** Add tests for directory creation, permissions, atomic write, migration.
- **Effort:** Medium.

### 5. Silent partial output on mass normalization failure
- **Reviews:** Error Resilience, UX
- **Location:** `src/main.py` — normalization loop and exit logic
- **Problem:** If all items from a source fail normalization, each prints a warning but
  `main()` returns exit code 0. Downstream scripts treat total failure as success.
- **Fix:** Track normalization error count per source. If errors > 0 and normalized == 0
  for any source, print a distinct "all items failed normalization" warning. If the
  final result has errors, exit with code 2 (partial success).
- **Tests:** Add test where all items fail normalization, assert exit code != 0.
- **Effort:** Small.

### 6. Placeholder config values pass validation
- **Reviews:** UX, Error Resilience
- **Location:** `src/config.py` — `validate_source`
- **Problem:** User copies `config.example.yaml` without editing. `"YOUR_CLIENT_ID"`
  passes the non-empty check. The tool then fails with an opaque OAuth error.
- **Fix:** Check string values against known placeholder prefixes (`YOUR_`, `DATABASE_ID`).
  If matched, emit "looks like you haven't replaced the placeholder in config.yaml."
- **Tests:** Add test with placeholder values asserting the error message.
- **Effort:** Small.

### 7. Broad exception handling masks programming errors
- **Reviews:** Security (original), Error Resilience
- **Location:** `src/main.py` — fetch and normalize loops
- **Problem:** Bare `except Exception` catches both expected API errors and unexpected
  bugs (`TypeError`, `KeyError`). Both are logged as warnings, not bugs.
- **Fix:** Import known exception types from each source. Catch those specifically.
  Let unexpected exceptions propagate with traceback and a "this is a bug" message.
- **Tests:** Add test confirming unexpected errors are surfaced differently from
  expected source errors.
- **Effort:** Small.

### 8. HTML body content passed through without stripping
- **Reviews:** Test Coverage, Error Resilience
- **Location:** `src/normalizer.py` — `_normalize_msftodo`, lines 305-308
- **Problem:** MS Graph API returns `contentType: html` with actual HTML markup.
  The normalizer returns it verbatim. The test fixture has `contentType: html` but
  stores plain prose, so coverage reports "covered" while the real behavior is untested.
- **Fix:** Strip HTML tags from body content when `contentType == "html"`. Use a simple
  regex or `html.parser` (stdlib). Update fixture with actual HTML markup.
- **Tests:** Add fixture with `<p>Some <b>text</b></p>`, assert tags are stripped.
- **Effort:** Small.

### 9. Python 3.10+ required but not declared
- **Reviews:** Compatibility, Structure
- **Location:** All source files (type annotations), no `pyproject.toml`
- **Problem:** `X | Y` union syntax in annotations breaks on Python 3.9 with
  `TypeError` at import time. No packaging manifest declares the requirement.
- **Fix:** Add `from __future__ import annotations` to every module. This defers
  annotation evaluation and works back to Python 3.7. Also add a `pyproject.toml`
  with `requires-python = ">= 3.10"` as a safety net.
- **Tests:** No test change needed. Verify import works after adding the future import.
- **Effort:** Small.

### 10. `harvest` script breaks on Windows
- **Reviews:** Compatibility
- **Location:** `harvest`
- **Problem:** Bash-only. Hardcoded `bin/` venv paths (Windows uses `Scripts/`).
  No Python version check. No `.bat` or `.ps1` alternative.
- **Fix:** Add a `harvest.bat` or `harvest.ps1` for Windows. Add a Python version
  check to the bash script (`python3 -c "import sys; assert sys.version_info >= (3,10)"`).
- **Tests:** Not directly testable in CI without Windows runners. Document in README.
- **Effort:** Medium.

---

## P2 — Quality debt

### 11. Triplicated `_request_with_retry`
- **Reviews:** Clean Code, Modularity, Maintainability
- **Location:** `jira.py:28-62`, `notion.py:24-55`, `msftodo.py:76-108`
- **Problem:** Nearly identical retry logic copy-pasted. Already diverged: `jira.py`
  has a stale `import time as _t`. Changing retry strategy requires editing 3 files.
- **Fix:** Extract to `src/sources/_http.py` with parameterized auth/fetch error classes.
  Each source passes its error classes and calls the shared function.
- **Tests:** Move retry tests to a shared test file. Source tests focus on their
  specific behavior.
- **Effort:** Medium.

### 12. No unified schema definition
- **Reviews:** Maintainability, Modularity
- **Location:** `src/normalizer.py`, `src/exporter.py`
- **Problem:** The 13-field contract exists only as implicit convention. `CSV_COLUMNS`
  in exporter is a second manual restatement. A new source can omit fields silently.
- **Fix:** Add a `TypedDict` (or `dataclass`) for `NormalizedItem` and `Category` in
  `src/schema.py`. Have each normalizer return it. Exporter derives `CSV_COLUMNS`
  from the schema fields.
- **Tests:** Schema tests validate that all normalizers produce valid `NormalizedItem`.
  (The `TestUnifiedSchema` parametrized tests already do this informally — formalize.)
- **Effort:** Medium.

### 13. Adding a 4th source requires touching 5 files
- **Reviews:** Modularity, Maintainability
- **Location:** `config.py`, `main.py`, `normalizer.py`, plus the new source
- **Problem:** Three independent string-keyed registries (`SOURCES`, `_fetch_source`,
  `normalizers` dict) must stay in sync manually.
- **Fix:** Create a source registry in `src/sources/__init__.py`. Each source module
  exposes a standard interface (`fetch_all`, `normalize`, `REQUIRED_CONFIG_KEYS`).
  `config.py`, `main.py`, and `normalizer.py` all read from the registry.
  Adding a source = adding one file + one registry entry.
- **Tests:** Add a test asserting registry keys match across all consumers.
- **Effort:** Large (refactor touches 5+ files). Defer until actually adding a 4th source.

### 14. Package named `src`
- **Reviews:** Structure, Compatibility
- **Location:** `src/` directory, `harvest` script
- **Problem:** Generic name conflicts with other projects. Can't `pip install -e .`.
- **Fix:** Rename to `todo_harvest/`. Update `harvest` script, `__main__.py`, and all
  internal imports. Add `pyproject.toml` with proper package metadata.
- **Tests:** Update all import paths in tests.
- **Effort:** Large (mechanical but touches every file). Best done alongside #9 and #15.

### 15. No `pyproject.toml`
- **Reviews:** Structure, Maintainability
- **Location:** Project root
- **Problem:** Can't install as package, no `console_scripts`, no Python version pin,
  no pytest/coverage config in one place.
- **Fix:** Add `pyproject.toml` with `[project]`, `[tool.pytest.ini_options]`,
  `[tool.coverage]`. Keep `requirements.txt` for venv bootstrapping.
- **Tests:** No test change.
- **Effort:** Small if done standalone, or combine with #14.

### 16. Jira `fields=*all` fetches unnecessary data
- **Reviews:** Performance
- **Location:** `src/sources/jira.py:88`
- **Problem:** Requests every field. The normalizer uses only ~12. Response payloads
  are 2-5x larger than necessary with many custom fields.
- **Fix:** Replace `"fields": "*all"` with an explicit field list:
  `summary,status,priority,labels,description,created,updated,duedate,parent,project,issuetype,customfield_10014`.
- **Tests:** Update mock response expectations if field filtering changes response shape.
- **Effort:** Small.

### 17. Sequential source/database fetching
- **Reviews:** Performance
- **Location:** `notion.py:119`, `msftodo.py:165`
- **Problem:** Multiple databases/lists fetched in serial. Network latency dominates.
  5 databases × 3 pages = 15 sequential round-trips.
- **Fix:** Use `concurrent.futures.ThreadPoolExecutor` to fetch databases/lists in
  parallel. Each thread gets its own `httpx.Client`.
- **Tests:** Existing tests use respx mocks which work per-thread. Add a test with
  2+ databases verifying parallel execution (or at least correct results).
- **Effort:** Medium.

### 18. `_get_token` silent-acquisition failure path untested
- **Reviews:** Test Coverage
- **Location:** `tests/test_msftodo.py`
- **Problem:** When `acquire_token_silent` returns `None` or `{"error": ...}`, the
  fallback to device code flow is exercised but no test covers this transition.
- **Fix:** Add test where `acquire_token_silent` returns `None`, assert device code
  flow is invoked.
- **Effort:** Small.

### 19. Notion tag deduplication missing
- **Reviews:** Test Coverage, Error Resilience
- **Location:** `src/normalizer.py:190-197`
- **Problem:** If Tags multi-select and Epic select both contain "Q1 Goals", the
  output tags list has the value twice. msftodo has dedup; Notion doesn't.
- **Fix:** Deduplicate tags while preserving order (use `dict.fromkeys`).
- **Tests:** Add test with overlapping tag values.
- **Effort:** Small.

### 20. Missing test fixtures for edge-case status/property mappings
- **Reviews:** Test Coverage
- **Location:** `tests/fixtures/msftodo_tasks.json`, `tests/fixtures/notion_pages.json`
- **Problem:** `waitingOnOthers`/`deferred` MS To Do statuses, `Notes`/`Due`/`Deadline`
  Notion property names, and Jira `status: null` are all handled in code but have
  no fixture or test coverage. A typo in the mapping would go undetected.
- **Fix:** Add fixture entries and corresponding test assertions for each.
- **Effort:** Small.

### 21. Console progress path untested in all sources
- **Reviews:** Test Coverage
- **Location:** `tests/test_jira.py`, `tests/test_notion.py`, `tests/test_msftodo.py`
- **Problem:** All `fetch_all` test calls omit the `console` argument. The `if console:`
  branches are uncovered. A bug (e.g., undefined variable in print) wouldn't be caught.
- **Fix:** Add one test per source that passes a `Console` and asserts no crash.
- **Effort:** Small.

### 22. `test_normalize_error_skips_item` is fragile
- **Reviews:** Test Coverage
- **Location:** `tests/test_main.py:199`
- **Problem:** Patches `src.normalizer.normalize` but `main.py` does a deferred
  `from src.normalizer import normalize` inside the function. Works now but breaks
  silently if the import moves to module level.
- **Fix:** Patch the normalize function at the call site in main.py instead:
  mock `_fetch_source` to return items, and provide items that genuinely fail
  normalization (e.g., missing required keys) instead of mocking normalize itself.
- **Effort:** Small.

---

## P3 — Polish

### 23. Unused `import json` in msftodo.py
- **Location:** `src/sources/msftodo.py:5`
- **Fix:** Remove the import.

### 24. f-strings with no interpolation
- **Location:** `src/sources/msftodo.py:55,58`
- **Fix:** Remove `f` prefix from strings without `{}`.

### 25. `task_count` parameter bleeds UI into data function
- **Location:** `src/sources/msftodo.py:129`
- **Fix:** Remove parameter. Let caller handle progress display.

### 26. Inconsistent None-guard idiom
- **Location:** `src/normalizer.py` — `(x or {}).get()` vs `if x and isinstance(x, dict)`
- **Fix:** Pick one idiom and apply consistently.

### 27. Magic string `customfield_10014`
- **Location:** `src/normalizer.py:118`
- **Fix:** Extract to `_JIRA_EPIC_LINK_FIELD` constant with a comment explaining
  Jira Classic vs Next-gen differences.

### 28. `normalizers` dict rebuilt on every `normalize()` call
- **Location:** `src/normalizer.py:9-13`
- **Fix:** Move to module-level constant.

### 29. Redundant `tests/fixtures/.gitkeep`
- **Fix:** Delete. Fixture files exist.

### 30. No `conftest.py`
- **Fix:** Add root `conftest.py` with shared fixtures (fixture file loading).

### 31. Flat test directory
- **Fix:** Move source tests to `tests/sources/`. Mirror `src/sources/`.

### 32. Duplicate entry point
- **Location:** `src/__main__.py` and `if __name__ == "__main__"` in `src/main.py`
- **Fix:** Remove the `if __name__` block from `main.py`.

### 33. Stale `import time as _t` in jira.py retry function
- **Location:** `src/sources/jira.py:54`
- **Fix:** Use the already-imported `time` module. Remove the alias.

### 34. Dependency pins with no upgrade strategy
- **Location:** `requirements.txt`
- **Fix:** Add a comment documenting the pinning strategy and last-reviewed date.

---

## Execution plan

**Phase 1 — Crash/correctness bugs (P0):** Items 1, 2, 3
Scope: 3 files changed. One commit.

**Phase 2 — Robustness (P1):** Items 4, 5, 6, 7, 8, 9
Scope: ~8 files changed. Three commits (token cache; validation+errors; HTML+compat).

**Phase 3 — Quick wins from P2/P3:** Items 11, 16, 19, 23-28, 33
Scope: Deduplicate retry logic, fix Jira field list, clean up small issues.
Multiple commits by logical grouping.

**Phase 4 — Structural (P2, deferred):** Items 12, 13, 14, 15
Scope: Package rename, schema definition, source registry, pyproject.toml.
Large refactor, do together. Defer until a 4th source is actually needed or
the project graduates from personal tool to shared tool.

**Phase 5 — Testing gaps (P2):** Items 18, 20, 21, 22
Scope: Test-only changes. One commit.

**Phase 6 — Platform (P1, deferred):** Item 10
Scope: Windows support. Defer until there is a Windows user.

**Phase 7 — Performance (P2, deferred):** Item 17
Scope: Parallel fetching. Defer until fetch times become a pain point.

## Out of scope

- SSRF validation on Jira URL — user controls their own config
- Path traversal on --output-dir — user controls their own CLI args
- API error message sanitization — personal tool, personal logs
- TLS pinning, rate limiting, audit logging — overengineering for a personal CLI
