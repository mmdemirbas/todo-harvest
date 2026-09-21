# todo-harvest

**Sync tasks between Vikunja, Plane, Jira, Microsoft To Do and Notion through one local state
file — pull from all five, push back to the two that take it.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Documentation](https://mmdemirbas.github.io/todo-harvest/) ·
[Source](https://github.com/mmdemirbas/todo-harvest) ·
[Changelog](CHANGELOG.md) ·
[Project page](https://mdemirbas.com/en/projects/todo-harvest/)

![Five trackers on the left, the local state file in the middle, the unified schema on the right](docs/flow.svg)

Work is in Jira, the team board is in Plane, the family list is in Microsoft To Do, notes with
checkboxes are in Notion, and the self-hosted Vikunja was supposed to replace them all. It never
does. todo-harvest pulls every one into one file in one schema, resolves conflicts by
timestamp, and pushes the result back to the services that accept writes — no daemon, no
account, one command at a time.

- **One schema** — id, title, status, priority, dates, tags, category, url; the service's own
  payload kept under `raw`
- **Pull from five** — Vikunja, Plane, Jira, Microsoft To Do, Notion; **push to two** —
  Vikunja and Plane
- **Custom mappings** — `status_map`, `priority_map` and Notion `field_map` for instances with
  their own vocabulary
- **Explicit runs** — nothing polls; `pull`, `push` and `sync` do exactly what they say, and
  `inspect` and `export` never touch the network

## Quick start

```bash
git clone https://github.com/mmdemirbas/todo-harvest.git && cd todo-harvest
cp config.example.yaml config.yaml    # fill in the services you use
./ctl pull                            # everything into output/todos.json
./ctl push vikunja                    # local state back to Vikunja
./ctl sync                            # pull all, then push all
```

`./ctl` creates a virtual environment on first run and installs the dependencies. On Windows,
`harvest.ps1` takes the same arguments from PowerShell.

## Commands

| Command | Network | Does |
|---|---|---|
| `./ctl pull [source…]` | yes | Pull from every configured service, or the named ones, and merge |
| `./ctl push vikunja` / `plane` | yes | Push local state to one target |
| `./ctl sync` | yes | Pull all, then push all |
| `./ctl inspect projects [source]` | no | Project / list / database ids — for `default_project_id` |
| `./ctl inspect stats` | no | Task counts, field coverage, date ranges |
| `./ctl inspect fields jira` | no | The status, priority and tag values a source uses |
| `./ctl export [--output-dir DIR]` | no | Snapshot local state to JSON and CSV |
| `./ctl help [command]` | no | Grouped overview, or one command in detail |
| `./ctl test` | no | Tests with a coverage report |

## How it works

1. **Pull** fetches each configured service (REST, three retries with backoff), normalises every
   item into the unified schema, assigns a stable `local_id` in `mapping.db` on first sight,
   and merges: a newer `updated_date` replaces the local copy, an older one is ignored.
2. **Push** updates tasks that have a mapping on the target, creates the rest there when
   `default_project_id` is set, and records the new ids so the next pull recognises them.

Local state lives in `output/todos.json` and `mapping.db`; `config.yaml` holds the tokens and
is git-ignored. The full picture — setup for each service, the schema field by field, which
fields push back, and the error messages — is in the
[documentation](https://mmdemirbas.github.io/todo-harvest/).

## Development

```bash
./ctl test                                                    # tests
.venv/bin/python -m pytest tests/test_normalizer.py -v        # one file
.venv/bin/python -m pytest --cov=src --cov-report=term-missing
```

Runtime: httpx, PyYAML, msal, rich. Development: pytest, pytest-cov, pytest-mock, respx.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
