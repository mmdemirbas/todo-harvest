# Contributing

Small, focused PRs are welcome. This is a personal tool, so expect review
to be informal and occasionally slow.

## Running tests

```bash
./todo --test
# or directly:
.venv/bin/python -m pytest -q
```

Tests use `respx` to mock HTTP calls. No real network access is required
or permitted in the test suite.

## Adding a new source

1. Create `src/sources/newsource.py` exposing `pull(config, console)` and
   `push(config, tasks, console)`. Raise `SourceAuthError` /
   `SourceFetchError` (from `src/sources/_http.py`) for expected failures.
2. Add a `normalize_newsource()` entry to `src/normalizer.py` that maps the
   source payload into the unified schema (see `src/schema.py`).
3. Add one row to `REGISTRY` in `src/sources/__init__.py`. That is the
   single source of truth for source name, config key, and push support.
4. Add fixture JSON under `tests/fixtures/` and tests under `tests/` using
   the same structure as existing sources.

## Style

- Match the style of neighboring code.
- Type hints on all public signatures.
- `from __future__ import annotations` at the top of new modules.
- No new runtime dependencies without discussion in an issue first.

## Reporting bugs

Open an issue with: what you ran, what you expected, what happened, and
the relevant snippet of `config.yaml` with credentials redacted.
