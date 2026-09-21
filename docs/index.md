---
title: todo-harvest
eyebrow: Command-line tool · Python
subtitle: Sync tasks between Vikunja, Plane, Jira, Microsoft To Do and Notion through one local state file — pull from all five, push back to the two that take it.
order: 1
summary: What the tool does, the pull/push/sync model, and where to go next.
---

> [!TLDR]
> `./ctl pull` fetches every configured service and merges into `output/todos.json`, newest timestamp winning. `./ctl push vikunja` (or `plane`) writes the resolved state back. `./ctl sync` does both.
>
> - One schema for every task; the service's own payload kept under `raw`
> - Jira, Microsoft To Do and Notion are pull-only; Vikunja and Plane go both ways
> - Nothing runs in the background: every command is one explicit run

## The model {#model}

![Five trackers on the left, the local state file in the middle, the unified schema on the right; pull arrows from every service, push arrows back to Vikunja and Plane](flow.svg)

## The commands {#commands}

```oku-table
{"headers":["Command","Network","Does"],"rows":[["`./ctl pull`","yes","Pull from every configured service and merge into local state"],["`./ctl pull jira mstodo`","yes","Pull from the named services only"],["`./ctl push vikunja`","yes","Push local state to Vikunja (or `plane`)"],["`./ctl sync`","yes","Pull all, then push all"],["`./ctl inspect projects [source]`","no","List project / list / database ids per source — for `default_project_id`"],["`./ctl inspect stats`","no","Task counts, field coverage, date ranges"],["`./ctl inspect fields jira`","no","The unique status, priority and tag values a source uses"],["`./ctl export [--output-dir DIR]`","no","Snapshot local state to JSON and CSV"],["`./ctl help [command]`","no","Grouped overview, or one command in detail"],["`./ctl test`","no","Tests with a coverage report"]]}
```

The driver creates a virtual environment on first run and installs the dependencies. On Windows, `harvest.ps1` takes the same arguments from PowerShell.

## Where to go next {#next}

```oku-compare-grid
{"cards":[{"t":"Setup","b":"config.yaml and a token for each service.","href":"setup.html"},{"t":"How a sync runs","b":"Normalise, map ids, resolve by timestamp, push.","href":"how-it-works.html"},{"t":"The unified schema","b":"Every field, what stays in raw, what pushes back.","href":"schema.html"},{"t":"Troubleshooting","b":"The message each service produces and its fix.","href":"troubleshooting.html"}]}
```
