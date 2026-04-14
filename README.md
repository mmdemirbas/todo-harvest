# todo-harvest

Collect TODO items from Microsoft To Do, Jira, and Notion into a single unified view. Exports to JSON and CSV.

## Quick start

```bash
git clone <repo-url> && cd todo-harvest
cp config.example.yaml config.yaml
# Edit config.yaml with your credentials (see sections below)
./harvest
```

The `harvest` script creates a virtual environment on first run and installs all dependencies automatically.

### Usage

```bash
./harvest                          # fetch all configured sources
./harvest --source jira            # single source
./harvest --source msftodo,notion  # multiple sources
./harvest --output-dir ~/exports   # custom output directory
./harvest --test                   # run tests with coverage report
```

### Output

All output goes to `./output/` by default (configurable in config.yaml):

- `todos.json` — all items from all sources, sorted by (source, id)
- `todos.csv` — same data in CSV format, with flattened category fields
- `jira.json`, `notion.json`, `msftodo.json` — per-source files

Re-running overwrites output files cleanly (idempotent).

## Configuration

All configuration lives in `config.yaml`. Copy `config.example.yaml` and fill in your credentials. Only configure the sources you want to use — unconfigured sources are skipped.

```yaml
output:
  dir: ./output

msftodo:
  client_id: "YOUR_CLIENT_ID"
  tenant_id: "consumers"

jira:
  base_url: "https://YOUR_SUBDOMAIN.atlassian.net"
  email: "your@email.com"
  api_token: "YOUR_API_TOKEN"

notion:
  token: "YOUR_INTEGRATION_SECRET"
  database_ids:
    - "DATABASE_ID_1"
```

## Microsoft To Do credentials

1. Go to [Azure Portal — App registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Name: anything (e.g. "todo-harvest")
4. Supported account types: **Personal Microsoft accounts only**
5. Click **Register**
6. Under **Authentication** in the left sidebar:
   - Click **Add a platform** → **Mobile and desktop applications**
   - Check the redirect URI: `https://login.microsoftonline.com/common/oauth2/nativeclient`
   - Scroll down and enable **Allow public client flows** → Yes
   - Click **Save**
7. Copy the **Application (client) ID** from the Overview page → `config.yaml` → `msftodo.client_id`
8. Set `tenant_id` to `"consumers"` (for personal Microsoft accounts)

On first run, the tool prints a device code and URL. Open the URL in your browser, enter the code, and sign in. The token is cached locally for subsequent runs.

## Jira credentials

1. Log in to [Atlassian API token management](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click **Create API token**
3. Label: "todo-harvest" (or anything)
4. Click **Create** and copy the token → `config.yaml` → `jira.api_token`
5. Set `jira.email` to your Atlassian account email
6. Set `jira.base_url` to your Jira instance URL (e.g. `https://yourname.atlassian.net`)

## Notion credentials

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Click **New integration**
3. Name: "todo-harvest"
4. Select your workspace
5. Under **Capabilities**, ensure **Read content** is checked
6. Click **Submit**
7. Copy the **Internal Integration Secret** → `config.yaml` → `notion.token`
8. For each database you want to harvest:
   - Open the database in Notion
   - Click **Share** (top right) → **Invite** → select your "todo-harvest" integration
   - Copy the database ID from the URL: `notion.so/{workspace}/{DATABASE_ID}?v=...`
   - Add it to `config.yaml` → `notion.database_ids`

## Unified schema

Every task is normalized to a common format regardless of source:

| Field          | Type                | Description                              |
|----------------|---------------------|------------------------------------------|
| `id`           | string              | `{source}-{original_id}`                 |
| `source`       | string              | `msftodo`, `jira`, or `notion`           |
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
| `raw`          | object              | Original API payload                     |

### Category mapping

| Source         | Category name         | Category type |
|----------------|-----------------------|---------------|
| Microsoft To Do| Task list name        | `list`        |
| Jira           | Epic summary or project name | `epic` or `project` |
| Notion         | Database title        | `database`    |

## Troubleshooting

### Microsoft To Do

| Error | Fix |
|-------|-----|
| "Failed to initiate device code flow" | Check that `client_id` is correct and the app registration has public client flows enabled |
| "Microsoft authentication failed" | Re-run the tool to get a new device code. Make sure you sign in within the time limit |
| "access forbidden" | Ensure your app registration has the `Tasks.Read` delegated permission |

### Jira

| Error | Fix |
|-------|-----|
| "authentication failed" | Verify `email` and `api_token` in config.yaml. Generate a new token at [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |
| "access forbidden" | Your API token may lack permissions. Ensure you have read access to the projects |
| HTTP 400 "Bad JQL" | This is a bug — please report it |

### Notion

| Error | Fix |
|-------|-----|
| "authentication failed" | Check your integration secret in config.yaml |
| "access forbidden" | The integration is not shared with the database. Open the database → Share → Invite the integration |
| Missing pages | Only pages in databases shared with the integration are returned |

### General

| Error | Fix |
|-------|-----|
| "Config file not found" | Copy `config.example.yaml` to `config.yaml` |
| Network timeout | Check your internet connection. The tool retries up to 3 times with exponential backoff |
| Partial results | If one source fails, others still run. Check the error messages above the summary table |

## Development

```bash
# Run tests with coverage
./harvest --test

# Run specific test file
.venv/bin/python -m pytest tests/test_normalizer.py -v

# Run with coverage report
.venv/bin/python -m pytest --cov=src --cov-report=term-missing
```

### Project structure

```
src/
├── sources/
│   ├── msftodo.py       # Microsoft To Do via MS Graph API
│   ├── jira.py          # Jira via REST API v3
│   └── notion.py        # Notion via official API
├── normalizer.py        # Maps each source → unified schema
├── exporter.py          # Writes JSON and CSV files
├── config.py            # Loads and validates config.yaml
└── main.py              # CLI entry point
```

## Dependencies

**Runtime:** httpx, PyYAML, msal, rich

**Development:** pytest, pytest-cov, pytest-mock, respx
