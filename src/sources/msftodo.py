"""Microsoft To Do source via MS Graph API with MSAL device code auth."""

import json
import time
from pathlib import Path

import httpx
import msal
from rich.console import Console

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Tasks.Read"]
TOKEN_CACHE_FILE = Path(".todo_harvest_msal_cache.json")
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
BACKOFF_BASE = 1.0


class MsftodoAuthError(Exception):
    """Raised when Microsoft authentication fails."""


class MsftodoFetchError(Exception):
    """Raised when MS Graph API returns an unexpected error."""


def _get_token(client_id: str, tenant_id: str, console: Console | None = None) -> str:
    """Acquire an access token via device code flow with persistent cache."""
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_FILE.exists():
        cache.deserialize(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.PublicClientApplication(
        client_id, authority=authority, token_cache=cache,
    )

    # Try silent acquisition first (cached token)
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]

    # Fall back to device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise MsftodoAuthError(
            f"Failed to initiate device code flow: {flow.get('error_description', 'unknown error')}"
        )

    if console:
        console.print(f"\n[bold]Microsoft login required.[/]")
        console.print(f"  Open: {flow['verification_uri']}")
        console.print(f"  Enter code: [bold cyan]{flow['user_code']}[/]")
        console.print(f"  Waiting for authentication...\n")
    else:
        print(f"Open {flow['verification_uri']} and enter code: {flow['user_code']}")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown error"))
        raise MsftodoAuthError(f"Microsoft authentication failed: {error}")

    _save_cache(cache)
    return result["access_token"]


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_FILE.write_text(cache.serialize(), encoding="utf-8")


def _request_with_retry(
    client: httpx.Client, method: str, url: str, **kwargs
) -> httpx.Response:
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            last_exc = exc
            time.sleep(BACKOFF_BASE * (2 ** attempt))
            continue

        if resp.status_code == 401:
            raise MsftodoAuthError(
                "Microsoft Graph authentication failed. Your token may have expired.\n"
                "Re-run to trigger a new device code login."
            )
        if resp.status_code == 403:
            raise MsftodoAuthError(
                "Microsoft Graph access forbidden. Check your app permissions (Tasks.Read scope)."
            )
        if resp.status_code in RETRY_STATUS_CODES:
            last_exc = MsftodoFetchError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            time.sleep(BACKOFF_BASE * (2 ** attempt))
            continue
        if resp.status_code >= 400:
            raise MsftodoFetchError(
                f"MS Graph API error {resp.status_code}: {resp.text[:500]}"
            )

        return resp

    raise last_exc  # type: ignore[misc]


def _fetch_lists(client: httpx.Client) -> list[dict]:
    """Fetch all To Do task lists."""
    lists: list[dict] = []
    url = f"{GRAPH_BASE}/me/todo/lists"

    while url:
        resp = _request_with_retry(client, "GET", url)
        data = resp.json()
        lists.extend(data.get("value", []))
        url = data.get("@odata.nextLink")

    return lists


def _fetch_tasks_for_list(
    client: httpx.Client,
    list_id: str,
    console: Console | None = None,
    task_count: int = 0,
) -> list[dict]:
    """Fetch all tasks (including completed) from a single list."""
    tasks: list[dict] = []
    url = f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks"

    while url:
        resp = _request_with_retry(client, "GET", url)
        data = resp.json()
        tasks.extend(data.get("value", []))
        if console:
            console.print(
                f"  Microsoft To Do: fetched {task_count + len(tasks)} tasks...",
                end="\r",
            )
        url = data.get("@odata.nextLink")

    return tasks


def fetch_all(config: dict, console: Console | None = None) -> list[dict]:
    """Fetch all tasks from all Microsoft To Do lists.

    Each returned dict is a raw task object, augmented with
    '_list_id' and '_list_name' for normalization.
    """
    token = _get_token(config["client_id"], config["tenant_id"], console)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    all_tasks: list[dict] = []

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        lists = _fetch_lists(client)

        for todo_list in lists:
            list_id = todo_list["id"]
            list_name = todo_list.get("displayName", "Untitled")
            tasks = _fetch_tasks_for_list(client, list_id, console, len(all_tasks))

            for task in tasks:
                task["_list_id"] = list_id
                task["_list_name"] = list_name

            all_tasks.extend(tasks)

    if console:
        console.print(f"  Microsoft To Do: fetched {len(all_tasks)} tasks total.")

    return all_tasks
