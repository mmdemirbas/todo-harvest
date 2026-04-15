# todo-harvest

> This file documents the codebase for AI coding assistants. Human contributors can ignore it — see `README.md` for usage and `CONTRIBUTING.md` for how to add a source.

Personal CLI tool that syncs TODO items between Vikunja, Jira, Microsoft To Do, Notion, and Plane via a local state file.

## Architecture

```
                          LOCAL STATE
                     (todos.json / mapping.db)
                /       |        |        |        \
           pull/push  pull/push  pull/push  pull-only  pull/push
              /         |          |          |          \
          Vikunja      Jira     MS Todo    Notion       Plane
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
    plane.py       — Plane self-hosted REST API v1 (pull + push)
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

**Pull:** service API → source `pull()` → raw dicts → `normalize(source, raw, source_config)` → `merge_pulled_items()` → `save_local_state()` → todos.json

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

### Config-driven mappings

Normalizers accept an optional `source_config` dict from config.yaml. Supported keys:

- **Jira:** `jql` (search query), `status_map`, `priority_map`
- **Notion:** `field_map` (column name → unified field), `status_map`, `priority_map`
- **Plane:** `status_map` (state name → unified status), `priority_map` (Plane priority → unified priority)
- **Vikunja/MS To Do:** `source_config` accepted but not currently used (hardcoded maps suffice)

Config maps override built-in maps; unmapped values fall through to built-in logic.

### API versions

- **Jira:** `POST /rest/api/3/search/jql` (cursor-based pagination)
- **Vikunja:** `GET /api/v1/tasks` (offset pagination)
- **MS To Do:** MS Graph v1.0, `$expand=checklistItems`
- **Notion:** API version `2022-06-28`
- **Plane:** self-hosted `/api/v1/`, `X-API-Key` header, cursor pagination (`next_cursor`/`next_page_results`)

## Known limitations (deferred by design)

- Package named `src/` (not `todo_harvest/`) — no PyPI publishing planned
- No parallel database/list fetching (sequential, network-bound)
- Push not yet implemented for Jira and MS To Do (stubs raise NotImplementedError)
- Notion is pull-only by design
- Notion page content (blocks) not fetched — only database properties (would require N API calls for N pages)
- Plane push writes only title, description_html, priority, and target_date. State (status) and labels are not synced — new issues land in the project's default state, and updates never change state or labels
