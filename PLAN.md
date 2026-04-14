# Symmetric Architecture Refactor

## Design decision

Local state (todos.json + mapping.db) is the single source of truth.
All external services — Vikunja, Jira, MS Todo, Notion — are symmetric peers.
No service is special or authoritative.

## Terminology (enforced everywhere)

- `pull`  = fetch from external service → merge into local state
- `push`  = read from local state → write to external service
- `sync`  = pull all specified, then push all specified

## File-by-file change map

### New files

| File | Purpose |
|------|---------|
| `src/mapping.py` | SQLite sync_map + sync_log, conflict resolution, local_id generation |
| `src/local_state.py` | Read/write todos.json as the local state file |
| `src/sources/vikunja.py` | Vikunja API client: pull() + push() |
| `tests/test_mapping.py` | Conflict resolution, upsert, all four winner cases |
| `tests/test_local_state.py` | Read/write/merge of todos.json |
| `tests/test_vikunja.py` | Pull/push with mocked httpx |
| `tests/test_sync.py` | Full sync flow: pull → resolve → push |
| `tests/test_cli.py` | Positional arg parsing for pull/push/sync |
| `tests/fixtures/vikunja_tasks.json` | Realistic Vikunja API responses |

### Modified files

| File | What changes |
|------|-------------|
| `src/schema.py` | Add `PushResult` TypedDict. Add `local_id` to `NormalizedItem`. |
| `src/sources/__init__.py` | `SourceDef` gains `pull`/`push` methods. `fetch_all` renamed to `pull`. Add `push_supported` flag. Add vikunja to REGISTRY. |
| `src/sources/jira.py` | Rename `fetch_all` → `pull`. Add `push()` stub. |
| `src/sources/notion.py` | Rename `fetch_all` → `pull`. Add `push()` → raises `NotImplementedError`. |
| `src/sources/msftodo.py` | Rename `fetch_all` → `pull`. Add `push()` stub. |
| `src/sources/_http.py` | No change (already shared). |
| `src/normalizer.py` | Add `normalize_vikunja()`. |
| `src/config.py` | Remove hardcoded SOURCES/REQUIRED_KEYS — already using registry. Add `mapping.db_path` default. |
| `src/main.py` | Complete rewrite: subcommands (pull/push/sync), positional service args, new summary table format. |
| `src/exporter.py` | Keep as-is. Export is now a subset of push — called from `local_state.py`. |
| `harvest` | Pass positional args through (already does via `"$@"`). Remove `--source`. |
| `config.example.yaml` | Add vikunja section + mapping section. |
| `README.md` | Update CLI usage, add Vikunja credentials section. |
| `CLAUDE.md` | Reflect new architecture, new source contract. |
| `pyproject.toml` | No change. |
| `requirements.txt` | No new deps (SQLite is stdlib). |

### Deleted files

| File | Why |
|------|-----|
| (none) | No files deleted. exporter.py stays — useful for CSV/JSON snapshots. |

## Source module interface (new contract)

```python
def pull(config: dict, console: Console | None = None) -> list[dict]:
    """Fetch all items from this service. Return raw payloads."""

def push(config: dict, tasks: list[NormalizedItem], console: Console | None = None) -> PushResult:
    """Write normalized tasks to this service. Return counts."""
```

For Notion: `push()` raises `NotImplementedError("Notion is pull-only")`.
For Jira/msftodo: `push()` is a stub initially — `raise NotImplementedError("Push not yet implemented for {source}")`.
For Vikunja: full `pull()` + `push()`.

## Schema additions

```python
class PushResult(TypedDict):
    created: int
    updated: int
    skipped: int

# NormalizedItem gains:
#   local_id: str   — stable UUID, assigned on first pull
```

## mapping.py design

```python
class SyncMapping:
    """SQLite-backed ID mapping and conflict resolution."""

    def __init__(self, db_path: Path):
        ...

    def get_local_id(self, source: str, source_id: str) -> str | None:
        """Look up local_id for a (source, source_id) pair."""

    def upsert(self, local_id: str, source: str, source_id: str,
               source_updated_at: str | None) -> None:
        """Insert or update a mapping entry."""

    def resolve_conflict(self, field: str,
                         local_value, local_updated_at: str | None,
                         source_value, source_updated_at: str | None,
                         last_synced_at: str | None) -> tuple[Any, str]:
        """Return (winning_value, 'local' | 'source')."""

    def mark_synced(self, local_id: str, source: str) -> None:
        """Update last_synced_at to now."""

    def log_sync(self, source: str, action: str, item_count: int) -> None:
        """Append to sync_log."""
```

## local_state.py design

```python
def load_local_state(path: Path) -> list[NormalizedItem]:
    """Read todos.json. Return [] if file doesn't exist."""

def save_local_state(items: list[NormalizedItem], path: Path) -> None:
    """Write todos.json sorted deterministically."""

def merge_pulled_items(
    local_items: list[NormalizedItem],
    pulled_items: list[NormalizedItem],
    mapping: SyncMapping,
    source: str,
) -> tuple[list[NormalizedItem], MergeStats]:
    """Merge pulled items into local state using conflict resolution.
    Returns updated local items + stats (created/updated/skipped/conflicts)."""
```

## CLI structure

```
./harvest pull [service ...]
./harvest push [service ...]
./harvest sync [service ...]
./harvest export [--output-dir DIR]    # legacy: write JSON/CSV snapshots
```

`export` subcommand preserves the current behavior for ad-hoc snapshots.

## main.py flow

### pull
```
for each service:
    raw = registry[service].pull(config[service])
    normalized = [normalize(service, item) for item in raw]
    local_items, stats = merge_pulled_items(local, normalized, mapping, service)
save_local_state(local_items)
print_pull_summary(stats_per_service)
```

### push
```
local_items = load_local_state()
for each service:
    items_for_service = filter_items_for_push(local_items, mapping, service)
    result = registry[service].push(config[service], items_for_service)
    mapping.mark_synced(...)
print_push_summary(results_per_service)
```

### sync
```
pull(services)
push(services)
```

## Implementation order (commits)

1. **Schema + mapping.py + local_state.py + tests** — foundation, no source changes
2. **Source interface rename: fetch_all → pull, add push stubs** — registry update
3. **vikunja.py + normalize_vikunja + tests** — new source module
4. **main.py rewrite: subcommands + new flow** — CLI wiring
5. **harvest script + config.example.yaml** — driver updates
6. **README.md + CLAUDE.md** — documentation
7. **Full test suite pass + coverage verification** — final gate

## Out of scope for this refactor

- Actual push implementation for Jira and msftodo (stubs only — raise NotImplementedError)
- Parallel fetching
- CSV export on push (exporter.py stays for ad-hoc snapshots only)
