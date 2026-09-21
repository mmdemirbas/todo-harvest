---
title: The unified schema
order: 30
summary: The one shape every task is normalised to, what each source keeps in raw, and which fields push back to which service.
---

> [!TLDR]
> Every task becomes the same record — id, title, status, priority, dates, tags, category, url — with the source's full payload kept under `raw`. Vikunja and Plane take pushes; Jira, Microsoft To Do and Notion are pull-only.

## Fields

Every task is normalized to a common format regardless of source:

| Field          | Type                | Description                              |
|----------------|---------------------|------------------------------------------|
| `id`           | string              | `{source}-{source_id}`                   |
| `local_id`     | string              | Stable UUID assigned on first pull        |
| `source`       | string              | `vikunja`, `mstodo`, `jira`, `notion`, or `plane` |
| `title`        | string              | Task title                               |
| `description`  | string or null      | Task description/body                    |
| `status`       | string              | `todo`, `in_progress`, `done`, `cancelled` |
| `priority`     | string              | `critical`, `high`, `medium`, `low`, `none` |
| `created_date` | ISO8601 or null     | Creation timestamp                       |
| `due_date`     | ISO8601 or null     | Due date                                 |
| `updated_date` | ISO8601 or null     | Last modification timestamp              |
| `completed_date` | ISO8601 or null   | When the task was marked done (MS To Do `completedDateTime`, Jira `resolutiondate`, Vikunja `done_at`; null for Notion) |
| `tags`         | list of strings     | Labels, categories, list names           |
| `url`          | string or null      | Link back to the original item           |
| `category`     | object              | Organizational container (see below)     |
| `raw`          | object              | Original API payload (all source fields) |

## Source-specific data in raw

The `raw` field preserves the complete API response for each task, including source-specific fields:

- **MS To Do:** `body` (notes), `checklistItems` (steps), `reminderDateTime`, `isReminderOn`, `completedDateTime`
- **Jira:** `description` (ADF), `comment`, `assignee`, `resolution`, `customfield_*`
- **Notion:** all database properties in their native types
- **Vikunja:** `description`, `labels`, `attachments`, `reminders`

## What pushes back

Legend: `rw` = pull and push wired; `pull` = pull only (push not implemented or not supported by this source).

| Field       | vikunja | jira | mstodo | notion | plane |
|-------------|---------|------|--------|--------|-------|
| title       | rw      | pull | pull   | pull   | rw    |
| description | rw      | pull | pull   | pull   | rw    |
| status      | rw      | pull | pull   | pull   | pull  |
| priority    | rw      | pull | pull   | pull   | rw    |
| due_date    | rw      | pull | pull   | pull   | rw    |
| tags/labels | rw      | pull | pull   | pull   | pull  |
| category    | rw      | pull | pull   | pull   | pull  |

Push is not yet implemented for Jira and Microsoft To Do (the CLI will raise an error if you try). Notion is pull-only by design. For Plane, push writes title, description, priority, and due date; status and labels are not synced.
