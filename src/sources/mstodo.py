"""Microsoft To Do source via MS Graph API with MSAL device code auth."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import httpx
import msal
from rich.console import Console

from src.sources._http import (
    SourceAuthError, SourceFetchError,
    request_with_retry, DEFAULT_TIMEOUT,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Tasks.Read"]
_OLD_CACHE_FILENAME = ".todo_harvest_msal_cache.json"


def _get_cache_dir() -> Path:
    """Return the XDG-compliant cache directory for todo-harvest."""
    return Path.home() / ".config" / "todo-harvest"


def _get_cache_path() -> Path:
    return _get_cache_dir() / "msal_cache.json"


class MstodoAuthError(SourceAuthError):
    """Raised when Microsoft authentication fails."""


class MstodoFetchError(SourceFetchError):
    """Raised when MS Graph API returns an unexpected error."""


_AUTH_MESSAGES = {
    401: (
        "Microsoft Graph authentication failed. Your token may have expired.\n"
        "Re-run to trigger a new device code login."
    ),
    403: "Microsoft Graph access forbidden. Check your app permissions (Tasks.Read scope).",
}


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    return request_with_retry(
        client, method, url,
        auth_error_cls=MstodoAuthError,
        fetch_error_cls=MstodoFetchError,
        auth_messages=_AUTH_MESSAGES,
        **kwargs,
    )


def _get_token(client_id: str, tenant_id: str, console: Console | None = None) -> str:
    """Acquire an access token via device code flow with persistent cache."""
    cache_path = _get_cache_path()
    _migrate_old_cache(cache_path)

    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.PublicClientApplication(
        client_id, authority=authority, token_cache=cache,
    )

    # Try silent acquisition first (cached token)
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache, cache_path)
            return result["access_token"]

    # Fall back to device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise MstodoAuthError(
            f"Failed to initiate device code flow: {flow.get('error_description', 'unknown error')}"
        )

    if console:
        console.print("\n[bold]Microsoft login required.[/]")
        console.print(f"  Open: {flow['verification_uri']}")
        console.print(f"  Enter code: [bold cyan]{flow['user_code']}[/]")
        console.print("  Waiting for authentication...\n")
    else:
        print(f"Open {flow['verification_uri']} and enter code: {flow['user_code']}")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown error"))
        raise MstodoAuthError(f"Microsoft authentication failed: {error}")

    _save_cache(cache, cache_path)
    return result["access_token"]


def _migrate_old_cache(new_path: Path) -> None:
    """Move the old cwd-relative cache file to the new XDG location."""
    old_path = Path(_OLD_CACHE_FILENAME)
    if old_path.exists() and not new_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        old_path.rename(new_path)
        os.chmod(new_path, 0o600)


def _save_cache(cache: msal.SerializableTokenCache, cache_path: Path) -> None:
    """Write cache atomically: write to temp file, then rename."""
    if not cache.has_state_changed:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_path = tempfile.mkstemp(
        dir=cache_path.parent, prefix=".msal_cache_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cache.serialize())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, cache_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _fetch_lists(client: httpx.Client) -> list[dict]:
    """Fetch all To Do task lists."""
    lists: list[dict] = []
    url: str | None = f"{GRAPH_BASE}/me/todo/lists"

    while url:
        resp = _request(client, "GET", url)
        data = resp.json()
        lists.extend(data.get("value", []))
        url = data.get("@odata.nextLink")

    return lists


def _fetch_tasks_for_list(client: httpx.Client, list_id: str) -> list[dict]:
    """Fetch all tasks (including completed) from a single list."""
    tasks: list[dict] = []
    url: str | None = f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks"

    while url:
        resp = _request(client, "GET", url)
        data = resp.json()
        tasks.extend(data.get("value", []))
        url = data.get("@odata.nextLink")

    return tasks


def pull(config: dict, console: Console | None = None) -> list[dict]:
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
            tasks = _fetch_tasks_for_list(client, list_id)

            for task in tasks:
                task["_list_id"] = list_id
                task["_list_name"] = list_name

            all_tasks.extend(tasks)

            if console:
                console.print(
                    f"  Microsoft To Do: fetched {len(all_tasks)} tasks...",
                    end="\r",
                )

    if console:
        console.print(f"  Microsoft To Do: fetched {len(all_tasks)} tasks total.")

    return all_tasks


def push(config: dict, tasks: list[dict], console: Console | None = None) -> dict:
    """Write normalized tasks to Microsoft To Do. Not yet implemented."""
    raise NotImplementedError("Push not yet implemented for mstodo")
