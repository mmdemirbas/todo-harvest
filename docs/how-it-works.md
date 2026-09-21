---
title: How a sync runs
order: 20
summary: Pull normalises each service into the unified schema and merges by timestamp; the mapping database ties one local id to each service's id; push sends the resolved state back.
---

> [!TLDR]
> Local state is the source of truth. A pull never overwrites a newer local edit; a push never invents a task on a service that has no mapping unless a default project is set.

## Pull {#pull}

```oku-step-flow
{"steps":[{"t":"Fetch","b":"Each configured source is queried through its own client — REST with retries (3 attempts, exponential backoff). Jira uses the configured JQL; Notion, the listed databases; Plane, the listed or all projects."},{"t":"Normalise","b":"Every item becomes the unified record: status and priority mapped to the common values (`status_map` / `priority_map` override the built-ins), the source's full payload kept under `raw`."},{"t":"Map ids","b":"`mapping.db` assigns a stable `local_id` on first sight and remembers which id the task has on each service."},{"t":"Merge","b":"An incoming task with a newer `updated_date` than the local copy replaces it; an older one is ignored. The result is written to `output/todos.json`."}]}
```

## Push {#push}

```oku-step-flow
{"steps":[{"t":"Select","b":"Tasks with a mapping on the target service are updated in place. Tasks from other sources are created there only if `default_project_id` is set for the target; otherwise they are reported as skipped."},{"t":"Translate","b":"Unified fields go back to the service's own names and values — Vikunja takes title, description, status, priority, due date, labels and project; Plane takes title, description, priority and due date."},{"t":"Record","b":"A newly created task's service id is written to `mapping.db`, so the next pull recognises it."}]}
```

## What lives where {#files}

```oku-table
{"headers":["File","Holds","Commit it?"],"rows":[["`config.yaml`","Tokens and per-service options","No — it is in `.gitignore`; `config.example.yaml` is the template"],["`output/todos.json`","Every task in the unified schema, the local source of truth","Your call; it is your task list"],["`mapping.db`","SQLite: local id ↔ service id per source","Keep it with `todos.json`; deleting it makes the next pull re-map everything"],["`output/*.csv`, `output/*.json` from export","Snapshots for spreadsheets or other tools","No"]]}
```
