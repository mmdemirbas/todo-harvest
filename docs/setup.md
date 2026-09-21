---
title: Setup
order: 10
summary: config.yaml, and how to get a token for each of the five services.
---

> [!TLDR]
> Copy `config.example.yaml` to `config.yaml` and fill in only the services you use; the rest are skipped. Each service needs one token, obtained as described below.

## config.yaml

All configuration lives in `config.yaml`. Copy `config.example.yaml` and fill in your credentials. Only configure the services you want to use — unconfigured ones are skipped.

```yaml
output:
  dir: ./output

mapping:
  db_path: ./mapping.db

vikunja:
  base_url: "http://localhost:3456"
  api_token: "YOUR_API_TOKEN"
  # default_project_id: 1      # required to push cross-source tasks into Vikunja

jira:
  base_url: "https://YOUR_SUBDOMAIN.atlassian.net"
  email: "your@email.com"
  api_token: "YOUR_API_TOKEN"
  # jql: "assignee = currentUser() ORDER BY created DESC"
  # status_map:
  #   "Custom Status": "in_progress"
  # priority_map:
  #   "Custom Priority": "high"

mstodo:
  client_id: "YOUR_CLIENT_ID"
  tenant_id: "consumers"

notion:
  token: "YOUR_INTEGRATION_SECRET"
  database_ids:
    - "DATABASE_ID_1"
  # field_map:
  #   status: "Status"
  #   priority: "Priority"
  #   due_date: "Due Date"
  #   tags: "Tags"
  #   category: "Epic"
  #   description: "Notes"
  # status_map:
  #   "Custom Status": "in_progress"
  # priority_map:
  #   "Custom Priority": "high"
```

## Custom mappings

Jira and Notion support config-driven mappings for status names, priority names, and (Notion only) column names. This is useful when your instance uses non-English or custom values.

**Jira:** `status_map` overrides the built-in status-category mapping. `priority_map` overrides priority name matching. `jql` customizes the search query (must be bounded — the default is `assignee = currentUser() ORDER BY created DESC`).

**Notion:** `field_map` maps your database column names to unified fields (`status`, `priority`, `due_date`, `tags`, `category`, `description`). Both `select` and `status` property types are supported. `status_map` and `priority_map` override the built-in value matching.

## Vikunja

1. Open your Vikunja instance (e.g., `http://localhost:3456`)
2. Go to Settings -> API Tokens
3. Create a new token with read/write permissions
4. Copy the token -> `config.yaml` -> `vikunja.api_token`
5. Set `vikunja.base_url` to your Vikunja instance URL

## Microsoft To Do

Requires an Azure AD / Entra ID tenant. If you don't have one, join the [M365 Developer Program](https://developer.microsoft.com/en-us/microsoft-365/dev-program) (free) or sign up for [Azure](https://azure.microsoft.com/free/).

1. Go to [Azure Portal - App registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Name: anything (e.g. "todo-harvest")
4. Supported account types: **Personal Microsoft accounts only**
5. Click **Register**
6. In the app's **Manifest** (left sidebar), set `"allowPublicClient": true` and save
7. Copy the **Application (client) ID** from the Overview page -> `config.yaml` -> `mstodo.client_id`
8. Set `tenant_id` to `"consumers"` (for personal Microsoft accounts)

On first run, the tool prints a device code and URL. Open the URL in your browser, enter the code, and sign in. The token is cached locally for subsequent runs.

## Jira

1. Log in to [Atlassian API token management](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click **Create API token**
3. Label: "todo-harvest" (or anything)
4. Click **Create** and copy the token -> `config.yaml` -> `jira.api_token`
5. Set `jira.email` to your Atlassian account email
6. Set `jira.base_url` to your Jira instance URL (e.g. `https://yourname.atlassian.net`)

## Plane

For self-hosted [Plane](https://plane.so) installations.

1. Log in to your Plane workspace
2. Go to **Workspace Settings** -> **API Tokens** -> **Add API Token**
3. Copy the token -> `config.yaml` -> `plane.api_token`
4. Set `plane.base_url` to your Plane instance URL (e.g. `https://plane.example.com`)
5. Set `plane.workspace_slug` to your workspace slug (from the URL after the domain)
6. To push cross-source tasks into Plane, set `plane.default_project_id` to a project UUID. See `./ctl inspect projects plane`.

## Notion

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Click **New integration**
3. Name: "todo-harvest"
4. Select your workspace
5. Under **Capabilities**, ensure **Read content** is checked
6. Click **Submit**
7. Copy the **Internal Integration Secret** -> `config.yaml` -> `notion.token`
8. For each database you want to harvest:
   - Open the database in Notion
   - Click **Share** (top right) -> **Invite** -> select your "todo-harvest" integration
   - Copy the database ID from the URL: `notion.so/{workspace}/{DATABASE_ID}?v=...`
   - Add it to `config.yaml` -> `notion.database_ids`
