# todo-harvest

Personal CLI tool that syncs TODO items between Vikunja, Jira, Microsoft To Do, and Notion via a local state file.

## Architecture

```
                      LOCAL STATE
                 (todos.json / mapping.db)
                /       |        |        \
           pull/push  pull/push  pull/push  pull-only
              /         |          |          \
          Vikunja      Jira     MS Todo      Notion
```

```
src/
  sources/
    __init__.py    — Source registry (REGISTRY, SourceDef)
    _http.py       — Shared HTTP retry logic (request_with_retry)
    vikunja.py     — Vikunja REST API client (pull + push)
    jira.py        — Jira REST API v3 client (pull + push stub)
    mstodo.py     — MS Graph API + MSAL device code auth (pull + push stub)
    notion.py      — Notion API v1 client (pull only)
  schema.py        — TypedDict definitions (NormalizedItem, Category, PushResult, MergeStats)
  normalizer.py    — Pure functions: raw payload → unified schema
  mapping.py       — SQLite sync_map + sync_log, conflict resolution
  local_state.py   — Read/write/merge todos.json (local source of truth)
  exporter.py      — JSON + CSV snapshot output
  config.py        — YAML config loading and validation
  main.py          — CLI entry point (pull/push/sync/export subcommands)
```

### Terminology (enforced everywhere)

- `pull`  = fetch from external service → merge into local state
- `push`  = read from local state → write to external service
- `sync`  = pull all specified services, then push to all

### Data flow

**Pull:** service API → source `pull()` → raw dicts → `normalize()` → `merge_pulled_items()` → `save_local_state()` → todos.json

**Push:** todos.json → `load_local_state()` → source `push()` → service API

**Sync:** pull all → push all

### Source contract

Each source module exposes:
- `pull(config: dict, console: Console | None) -> list[dict]` — raw API payloads
- `push(config: dict, tasks: list[dict], console: Console | None) -> PushResult` — or raises NotImplementedError
- `*AuthError` and `*FetchError` — inherit from `SourceAuthError`/`SourceFetchError` in `_http.py`

### Source registry

`src/sources/__init__.py` contains `REGISTRY` — single source of truth for source names, config keys, push support.

Adding a new source:
1. Create `src/sources/newsource.py` with `pull()` and `push()`
2. Add `normalize_newsource()` to `src/normalizer.py`
3. Add one entry to `REGISTRY` in `src/sources/__init__.py`

### Local state

- `todos.json` — normalized tasks, updated on every pull, read on every push
- `mapping.db` — SQLite tracking local_id ↔ (source, source_id) with timestamps for conflict resolution

### Conflict resolution

On pull, field-by-field comparison using timestamps:
- If only local changed after last sync → local wins
- If only source changed after last sync → source wins
- If both changed → source wins (prefer fresh external data)
- If no timestamps → source wins

## Conventions

### Python version
- Minimum: Python 3.10 (uses `X | Y` union syntax in annotations)
- All modules use `from __future__ import annotations` for 3.9 tolerance
- `pyproject.toml` declares `requires-python = ">= 3.10"`

### Error handling
- Known source errors (auth, fetch) caught specifically in main.py
- Unexpected errors propagate with traceback + bug-report message
- Config validation rejects non-string values and placeholder text
- Exit code 0 = clean success, 1 = any error

### Testing
- pytest + respx for HTTP mocking. No real network calls.
- Fixtures in `tests/fixtures/` — realistic JSON payloads
- Run: `.venv/bin/python -m pytest --cov=src --cov-report=term-missing`

### Token cache
- MSAL cache at `~/.config/todo-harvest/msal_cache.json` (0o700 dir, 0o600 file)
- Atomic writes via tempfile + os.replace

### Retry logic
- Shared in `src/sources/_http.py`
- 3 retries with exponential backoff on 429/5xx/network errors
- 30-second timeout per request

## Known limitations (deferred by design)

- Package named `src/` (not `todo_harvest/`) — no PyPI publishing planned
- No parallel database/list fetching (sequential, network-bound)
- Push not yet implemented for Jira and MS To Do (stubs raise NotImplementedError)
- Notion is pull-only by design
