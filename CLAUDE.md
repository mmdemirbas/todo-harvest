# todo-harvest

Personal CLI tool that collects TODO items from Microsoft To Do, Jira, and Notion into unified JSON/CSV exports.

## Architecture

```
src/
  sources/
    __init__.py    — Source registry (REGISTRY, SourceDef)
    _http.py       — Shared HTTP retry logic (request_with_retry)
    jira.py        — Jira REST API v3 client
    notion.py      — Notion API v1 client
    msftodo.py     — MS Graph API + MSAL device code auth
  schema.py        — TypedDict definitions (NormalizedItem, Category, CSV_COLUMNS)
  normalizer.py    — Pure functions: raw payload → unified schema
  exporter.py      — JSON + CSV output with deterministic sorting
  config.py        — YAML config loading and validation
  main.py          — CLI entry point, orchestration
```

### Data flow

`config.yaml` → `main.py` dispatches to source `fetch_all()` → raw dicts → `normalize()` → unified schema → `export_all()` → output files.

### Source contract

Each source module exposes:
- `fetch_all(config: dict, console: Console | None) -> list[dict]` — returns raw API payloads
- `*AuthError` and `*FetchError` — both inherit from `SourceAuthError`/`SourceFetchError` in `_http.py`

The normalizer reads source-specific injected keys (`_list_id`, `_database_title`, etc.) that each source's `fetch_all` attaches to raw dicts.

### Source registry

`src/sources/__init__.py` contains `REGISTRY` — the single source of truth for available sources. Each entry maps a source name to its module path, normalize function, and required config keys.

To add a new source, create the module and add one entry to `REGISTRY`.

### Schema types

`src/schema.py` defines `NormalizedItem` and `Category` as `TypedDict`. All normalizers produce this shape. `CSV_COLUMNS` is derived from the schema and used by the exporter.

## Conventions

### Python version
- Minimum: Python 3.10 (uses `X | Y` union syntax in annotations)
- All modules use `from __future__ import annotations` for 3.9 tolerance
- `pyproject.toml` declares `requires-python = ">= 3.10"`

### Error handling
- Known source errors (auth, fetch) are caught specifically in main.py
- Unexpected errors propagate with traceback + bug-report message
- Config validation rejects non-string values and placeholder text
- Exit code 0 = clean success, 1 = any error (partial or total)

### Testing
- pytest + respx for HTTP mocking. No real network calls.
- Fixtures in `tests/fixtures/` — realistic JSON payloads
- Normalizer target: 100% line coverage
- Shared fixtures in `tests/conftest.py`
- Run: `.venv/bin/python -m pytest --cov=src --cov-report=term-missing`

### Adding a new source

1. Create `src/sources/newsource.py` — implement `fetch_all()`, error classes inheriting from `_http.py`
2. Add `normalize_newsource()` to `src/normalizer.py`
3. Add one entry to `REGISTRY` in `src/sources/__init__.py`

Config validation and CLI dispatch are automatic via the registry.

### Token cache
- MSAL cache lives at `~/.config/todo-harvest/msal_cache.json`
- Created with `0o700` dir, `0o600` file permissions
- Atomic writes via tempfile + os.replace
- Old cwd-relative cache auto-migrated on first run

### Retry logic
- Shared in `src/sources/_http.py`
- 3 retries with exponential backoff on 429/5xx/network errors
- 30-second timeout per request
- Source-specific auth messages via `auth_messages` parameter

## Known limitations (deferred by design)

- Package named `src/` (not `todo_harvest/`) — no PyPI publishing planned
- No parallel database/list fetching (sequential, network-bound)
