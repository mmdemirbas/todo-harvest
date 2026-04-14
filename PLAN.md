# Remaining Improvements

Items still to be implemented. See DONE.md for completed items, IGNORED.md for skipped items.

## #12: Unified schema definition

- **Location:** New `src/schema.py`
- **Problem:** The 13-field contract between normalizers, exporter, and main.py
  exists only as implicit convention. A 4th source (Vikunja) can omit fields silently.
- **Fix:** Add `TypedDict` for `NormalizedItem` and `Category`. Have each normalizer
  return typed dicts. Derive `CSV_COLUMNS` from schema fields.
- **Tests:** Formalize `TestUnifiedSchema` to validate against the TypedDict.

## #13: Source registry

- **Location:** `src/sources/__init__.py`, `config.py`, `main.py`, `normalizer.py`
- **Problem:** Three independent string-keyed registries must stay in sync.
  Adding a source requires touching 4+ files.
- **Fix:** Create a source registry in `src/sources/__init__.py`. Each source
  module exposes a standard interface. Config, main, and normalizer read from
  the registry. Adding a source = new file + 1 registry entry.

## #15: pyproject.toml

- **Location:** Project root
- **Problem:** No packaging manifest. No `python_requires`, no centralized
  pytest/coverage config. Dependency pins have no documented upgrade strategy.
- **Fix:** Add `pyproject.toml` with `[project]`, `[tool.pytest.ini_options]`,
  `[tool.coverage]`. Document pin strategy in requirements.txt.

## #16: Jira explicit field list

- **Location:** `src/sources/jira.py`
- **Problem:** `fields=*all` fetches every field. The normalizer uses ~12.
- **Fix:** Replace with explicit field list.

## #25: Remove `task_count` parameter

- **Location:** `src/sources/msftodo.py` — `_fetch_tasks_for_list`
- **Problem:** `task_count` bleeds UI concern into a data-fetching function.
- **Fix:** Remove parameter. Let caller (`fetch_all`) handle progress display.
