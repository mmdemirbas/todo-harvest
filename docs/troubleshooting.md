---
title: Troubleshooting
order: 40
summary: The error messages each service produces and the fix for each.
---

> [!TLDR]
> Almost every failure is a token or a permission; the tables below name the message and the fix.


## Microsoft To Do

| Error | Fix |
|-------|-----|
| "Failed to initiate device code flow" | Check that `client_id` is correct and `allowPublicClient` is `true` in the app manifest |
| "The client application must be marked as mobile" | Set `"allowPublicClient": true` in the app registration's Manifest |
| "Microsoft authentication failed" | Re-run the tool to get a new device code. Make sure you sign in within the time limit |
| "access forbidden" | Ensure your app registration has the `Tasks.Read` delegated permission |

## Jira

| Error | Fix |
|-------|-----|
| "authentication failed" | Verify `email` and `api_token` in config.yaml |
| "access forbidden" | Your API token may lack permissions |
| "Unbounded JQL queries" | Set `jql` in config.yaml (default: `assignee = currentUser()`) |

## Notion

| Error | Fix |
|-------|-----|
| "authentication failed" | Check your integration secret |
| "access forbidden" | The integration is not shared with the database |

## Vikunja

| Error | Fix |
|-------|-----|
| "authentication failed" | Check your API token in config.yaml |
| "access forbidden" | Check your token permissions |
| "tasks skipped: no Vikunja mapping found" | Set `default_project_id` under `vikunja:` in config.yaml — new tasks from other sources are created there |
| "Invalid model provided" on update | Ensure the task is a POST to `/api/v1/tasks/{numeric-id}` — an older bug stored prefixed IDs in mapping.db; `rm mapping.db` and re-pull fixes it |

Password reset:
```bash
docker compose exec vikunja /app/vikunja/vikunja user list
docker compose exec vikunja /app/vikunja/vikunja user reset-password 1 -d
```

## General

| Error | Fix |
|-------|-----|
| "Config file not found" | Copy `config.example.yaml` to `config.yaml` |
| "No command specified" | Use: `./ctl pull`, `./ctl push`, or `./ctl sync` |
| Network timeout | The tool retries up to 3 times with exponential backoff |
