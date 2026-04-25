# Deep review — todo-harvest

Four parallel lenses: correctness, security/adversarial, architecture, ship-readiness. De-duplicated and ordered by what to fix first.

---

## P0 — fix today

### 1. Live tokens in working-copy `config.yaml` (security/ship)
File is `.gitignore`'d and not tracked, so `git status` is clean — but the working copy holds real-looking Vikunja, Jira, and Notion tokens. One stray `git add -A` or one shared backup leaks them.

**Fix:** Rotate all three tokens now, then run `git log --all -S '<token-prefix>'` to confirm none were ever committed.

### 2. Non-atomic write to `todos.json` (correctness)
`src/local_state.py:38` opens the file with `"w"` and writes in place. SIGKILL / disk-full mid-write empties the file; next `pull` then re-creates every item with new `local_id`s and breaks all mappings. `mapping.db` is WAL-protected; this isn't.

**Fix:** Write via `tempfile.NamedTemporaryFile(dir=path.parent)` + `os.replace`.

---

## P1 — fix this week

### 3. CSV exporter is broken in two independent ways (architecture + security)
- `src/exporter.py:35-51` — `completed_date` is in `CSV_COLUMNS` but never written to the row dict. Column header always blank.
- Same file, no escaping of cells starting with `= + - @ \t \r`. Hostile remote service → CSV formula injection when the user opens the export in Excel/LibreOffice (`WEBSERVICE`-based exfil, calc spawn, etc.).

**Fix:** Add `completed_date` to row dict; prefix risky cells: `if v and v[0] in "=+-@\t\r": v = "'" + v`.

### 4. SSRF / token exfiltration via `base_url` (security)
`src/sources/{vikunja,jira,plane}.py` send Bearer/Basic/X-API-Key tokens to whatever host `config.yaml` declares. No scheme allowlist. If config ever comes from an untrusted source (templated, shared snippet, attacker write), credentials go to the attacker.

**Fix:** In `src/config.py validate_source`, require `https://` (allow `http://localhost`).

### 5. Auth header echoed in error body (security)
`src/sources/_http.py:67-68` raises with the first 500 bytes of `resp.text`. A WAF or hostile endpoint that reflects the Authorization header puts the Bearer/Basic token onto the terminal and any log capture.

**Fix:** Drop `resp.text` from user-facing errors, or scrub `Bearer …`/`Basic …`/`ATATT…`/`ntn_…` patterns before printing.

### 6. Timestamp comparison is lexicographic, not chronological (correctness)
`src/mapping.py:169-174` compares ISO strings with `>`. Jira returns `…+0000`, Notion `…Z`, Vikunja `…Z` without millis — these don't sort consistently for the same instant. Causes false `local_changed = True`, spurious conflict counts, and field-overwrite churn.

**Fix:** `datetime.fromisoformat(s.replace("Z","+00:00"))` then compare.

### 7. Layering inversion in `normalizer.py` (architecture)
`src/normalizer.py:21` does `from src.sources import REGISTRY` inside the dispatch wrapper — the file is supposed to be pure. Per-source functions are clean; only the dispatcher is dirty.

**Fix:** Move `normalize()` dispatch into `main.py` (which already passes `service`).

---

## P2 — keep on the list

### 8. `push()` contract drift hidden by `try/except TypeError` (architecture)
`src/sources/__init__.py:58-70` calls `push()` and falls back on `TypeError`, papering over the fact that some pushers take `mapping=None` and others don't. That `except` will also swallow real bugs (typos in kwargs).

**Fix:** Add `mapping=None` to every `push()` signature including the `NotImplementedError` stubs; remove the fallback.

### 9. Two-manifest dependency split (ship)
`pyproject.toml` floats with no upper caps; `requirements.txt` last-tested pins. Authority is unclear — `pip install .` reads pyproject, the `todo` script reads requirements.

**Fix:** Pick one as canonical (probably keep both but cap pyproject `<X+1`), or move to `uv` with `uv.lock`.

### 10. Packaging is `src/`, not a real package (ship)
`pip install .` will install `src` as a top-level name and conflict with anything else. CLAUDE.md says no PyPI plan — fine — but `pyproject.toml` still advertises `[project.urls]` and Beta classifier.

**Fix:** Either add a `[tool.setuptools] packages` block + comment "not pip-installable" or rename to `todo_harvest/`.

### 11. CI lacks lint / type-check / hardening (ship)
`.github/workflows/ci.yml` runs pytest on a 3×3 matrix (good), but has no `timeout-minutes`, no `permissions: contents: read`, no ruff, no mypy.

**Fix:** Add the two YAML lines now; defer ruff until you add `[tool.ruff]` config.

### 12. Test gaps (correctness)
- No test for partial-failure of multi-source sync (one source raises → others must still land cleanly).
- No test for malformed payloads in normalizers (e.g. `normalize_jira({"fields": None})`).
- No test for source-deletion behaviour (item disappears from remote → currently kept locally forever; intentional per design but undocumented and untested).
- No test mixing Jira `+0000` and Vikunja `Z` timestamps in `resolve_conflict` (would have caught #6).

---

## P3 — note and move on

- `src/sources/_http.py:72` has `# type: ignore` masking a `raise None` path that's only safe because `MAX_RETRIES >= 1`. Add `if last_exc is None: raise fetch_error_cls(...)`.
- `src/sources/plane.py:283` wraps `description` in raw `<p>` if it contains `<` — stored XSS surface inside Plane's UI. Always `html.escape` before wrapping.
- Source docstrings say "Fetch" though CLAUDE.md enforces "pull" terminology. Trivial.
- `src/schema.py:21` comment lists four sources, missing "plane".
- msal is 8 minors stale (1.28 → 1.36); rich is 2 majors stale (13 → 15). Bump on next release after testing rich's API change.
- `main.py` 712 lines — the `_inspect_*` table renderers (~120 lines) could move to `inspector.py`. Not urgent.

---

## What looks healthy

`yaml.safe_load` used; SQLite parameterized everywhere; MSAL cache perms 0o700/0o600 verified; no `verify=False`; no `eval`/`exec`/`shell=True`; auth errors don't trigger retries; tempfile lives next to final path (atomic-rename safe); `REGISTRY` is the real single source of truth — `config.SOURCES` derives from it; `mapping.py` has no HTTP imports; per-source normalizer functions are pure.
