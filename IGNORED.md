# Ignored / Out of Scope

Items from the adversarial review that were evaluated and deliberately skipped.

## Ignored — wrong threat model for a personal CLI

- **SSRF validation on Jira URL** — user controls their own config
- **Path traversal on --output-dir** — user controls their own CLI args
- **API error message sanitization** — personal tool, personal logs
- **TLS pinning, rate limiting, audit logging** — overengineering

## Ignored — unnecessary complexity

### 14. Rename package `src/` to `todo_harvest/`
Not needed. The `src/` convention works fine for a personal tool that isn't
published to PyPI. All imports are consistent.

### 31. Nested test directory (`tests/sources/`)
Mirroring `src/sources/` adds navigation overhead for zero benefit with 3 source
files. Flat `tests/` is simpler.

## Deferred — implement when the need arises

### 17. Parallel database/list fetching
Sequential is fine for current scale (<500 items per source). Adds threading
complexity. Revisit if fetch times become a pain point.
