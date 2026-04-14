# todo-harvest

Sync TODO items between Vikunja, Jira, Microsoft To Do, and Notion via a local state file. Bidirectional for Vikunja; pull-only for Notion.

## Quick start

```bash
git clone <repo-url> && cd todo-harvest
cp config.example.yaml config.yaml
# Edit config.yaml with your credentials (see sections below)
./todo pull
```

The `todo` script creates a virtual environment on first run and installs all dependencies automatically.

### Usage

```bash
./todo pull                       # pull from all configured services
./todo pull jira mstodo           # pull from specific services
./todo push vikunja               # push local state to vikunja
./todo sync                       # pull all, then push all
./todo sync jira vikunja          # sync between jira and vikunja
./todo export                     # export local state to JSON/CSV
./todo export --output-dir ~/out  # export to custom directory
./todo --test                     # run tests with coverage report
```

### Local state

After pulling, your tasks live in `./output/todos.json` (the local source of truth) and `./mapping.db` (ID tracking across services).

Re-running `pull` merges new data using timestamp-based conflict resolution. Re-running `push` sends resolved local state to the target services.

## Configuration

All configuration lives in `config.yaml`. Copy `config.example.yaml` and fill in your credentials. Only configure the services you want to use — unconfigured ones are skipped.

```yaml
output:
  dir: ./output

mapping:
  db_path: ./mapping.db

vikunja:
  base_url: "http://localhost:3456"
  api_token: "YOUR_API_TOKEN"

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

### Custom mappings

Jira and Notion support config-driven mappings for status names, priority names, and (Notion only) column names. This is useful when your instance uses non-English or custom values.

**Jira:** `status_map` overrides the built-in status-category mapping. `priority_map` overrides priority name matching. `jql` customizes the search query (must be bounded — the default is `assignee = currentUser() ORDER BY created DESC`).

**Notion:** `field_map` maps your database column names to unified fields (`status`, `priority`, `due_date`, `tags`, `category`, `description`). Both `select` and `status` property types are supported. `status_map` and `priority_map` override the built-in value matching.

## Vikunja credentials

1. Open your Vikunja instance (e.g., `http://localhost:3456`)
2. Go to Settings -> API Tokens
3. Create a new token with read/write permissions
4. Copy the token -> `config.yaml` -> `vikunja.api_token`
5. Set `vikunja.base_url` to your Vikunja instance URL

## Microsoft To Do credentials

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

## Jira credentials

1. Log in to [Atlassian API token management](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click **Create API token**
3. Label: "todo-harvest" (or anything)
4. Click **Create** and copy the token -> `config.yaml` -> `jira.api_token`
5. Set `jira.email` to your Atlassian account email
6. Set `jira.base_url` to your Jira instance URL (e.g. `https://yourname.atlassian.net`)

## Notion credentials

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

## Unified schema

Every task is normalized to a common format regardless of source:

| Field          | Type                | Description                              |
|----------------|---------------------|------------------------------------------|
| `id`           | string              | `{source}-{source_id}`                   |
| `local_id`     | string              | Stable UUID assigned on first pull        |
| `source`       | string              | `vikunja`, `mstodo`, `jira`, or `notion` |
| `title`        | string              | Task title                               |
| `description`  | string or null      | Task description/body                    |
| `status`       | string              | `todo`, `in_progress`, `done`, `cancelled` |
| `priority`     | string              | `critical`, `high`, `medium`, `low`, `none` |
| `created_date` | ISO8601 or null     | Creation timestamp                       |
| `due_date`     | ISO8601 or null     | Due date                                 |
| `updated_date` | ISO8601 or null     | Last modification timestamp              |
| `tags`         | list of strings     | Labels, categories, list names           |
| `url`          | string or null      | Link back to the original item           |
| `category`     | object              | Organizational container (see below)     |
| `raw`          | object              | Original API payload (all source fields) |

### Source-specific data in `raw`

The `raw` field preserves the complete API response for each task, including source-specific fields:

- **MS To Do:** `body` (notes), `checklistItems` (steps), `reminderDateTime`, `isReminderOn`, `completedDateTime`
- **Jira:** `description` (ADF), `comment`, `assignee`, `resolution`, `customfield_*`
- **Notion:** all database properties in their native types
- **Vikunja:** `description`, `labels`, `attachments`, `reminders`

### Bidirectional field support

| Field       | vikunja | jira       | mstodo | notion    |
|-------------|---------|------------|---------|-----------|
| title       | rw      | rw         | rw      | pull only |
| description | rw      | rw         | rw      | pull only |
| status      | rw      | rw         | rw      | pull only |
| priority    | rw      | rw         | rw      | pull only |
| due_date    | rw      | rw         | rw      | pull only |
| tags/labels | rw      | rw         | rw      | pull only |
| category    | rw      | pull only  | pull only | pull only |

## Troubleshooting

### Microsoft To Do

| Error | Fix |
|-------|-----|
| "Failed to initiate device code flow" | Check that `client_id` is correct and `allowPublicClient` is `true` in the app manifest |
| "The client application must be marked as mobile" | Set `"allowPublicClient": true` in the app registration's Manifest |
| "Microsoft authentication failed" | Re-run the tool to get a new device code. Make sure you sign in within the time limit |
| "access forbidden" | Ensure your app registration has the `Tasks.Read` delegated permission |

### Jira

| Error | Fix |
|-------|-----|
| "authentication failed" | Verify `email` and `api_token` in config.yaml |
| "access forbidden" | Your API token may lack permissions |
| "Unbounded JQL queries" | Set `jql` in config.yaml (default: `assignee = currentUser()`) |

### Notion

| Error | Fix |
|-------|-----|
| "authentication failed" | Check your integration secret |
| "access forbidden" | The integration is not shared with the database |

### Vikunja

| Error | Fix |
|-------|-----|
| "authentication failed" | Check your API token in config.yaml |
| "access forbidden" | Check your token permissions |

### General

| Error | Fix |
|-------|-----|
| "Config file not found" | Copy `config.example.yaml` to `config.yaml` |
| "No command specified" | Use: `./todo pull`, `./todo push`, or `./todo sync` |
| Network timeout | The tool retries up to 3 times with exponential backoff |

## Development

```bash
./todo --test                                              # run tests
.venv/bin/python -m pytest tests/test_normalizer.py -v        # specific test
.venv/bin/python -m pytest --cov=src --cov-report=term-missing  # coverage
```

## Dependencies

**Runtime:** httpx, PyYAML, msal, rich

**Development:** pytest, pytest-cov, pytest-mock, respx
