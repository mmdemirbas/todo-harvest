"""Vikunja API source — pull and push tasks via REST API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from rich.console import Console

if TYPE_CHECKING:
    from src.mapping import SyncMapping

from src.sources._http import (
    SourceAuthError, SourceFetchError,
    request_with_retry, DEFAULT_TIMEOUT, MAX_PAGES,
)


class VikunjaAuthError(SourceAuthError):
    """Raised when Vikunja authentication fails."""


class VikunjaFetchError(SourceFetchError):
    """Raised when Vikunja API returns an unexpected error."""


_AUTH_MESSAGES = {
    401: "Vikunja authentication failed. Check your API token.",
    403: "Vikunja access forbidden. Check your API token permissions.",
}


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    return request_with_retry(
        client, method, url,
        auth_error_cls=VikunjaAuthError,
        fetch_error_cls=VikunjaFetchError,
        auth_messages=_AUTH_MESSAGES,
        **kwargs,
    )


def pull(config: dict, console: Console | None = None) -> list[dict]:
    """Fetch all tasks from Vikunja.

    Returns a list of raw Vikunja task dicts, each augmented with
    '_project_id' and '_project_title' for normalization.
    """
    base_url = config["base_url"].rstrip("/")
    headers = {
        "Authorization": f"Bearer {config['api_token']}",
        "Accept": "application/json",
    }

    all_tasks: list[dict] = []

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        # Fetch all projects first
        projects = _fetch_projects(client, base_url)
        project_map = {p["id"]: p.get("title", "Untitled") for p in projects}

        # Fetch tasks from all projects
        for page in range(1, MAX_PAGES + 1):
            resp = _request(
                client, "GET", f"{base_url}/api/v1/tasks",
                params={"page": page, "per_page": 50},
            )
            tasks = resp.json()
            if not tasks:
                break

            for task in tasks:
                project_id = task.get("project_id")
                task["_project_id"] = project_id
                task["_project_title"] = project_map.get(project_id, "Unknown")

            all_tasks.extend(tasks)

            if console:
                console.print(f"  Vikunja: fetched {len(all_tasks)} tasks...", end="\r")
        else:
            raise VikunjaFetchError(
                f"Vikunja tasks pagination exceeded MAX_PAGES={MAX_PAGES}"
            )

    if console:
        console.print(f"  Vikunja: fetched {len(all_tasks)} tasks total.")

    return all_tasks


def push(
    config: dict,
    tasks: list[dict],
    console: Console | None = None,
    mapping: "SyncMapping | None" = None,
) -> dict:
    """Write normalized tasks to Vikunja.

    For each task:
      - If mapping.db has a Vikunja source_id for the local_id → UPDATE
      - Else → CREATE in config['default_project_id'] (or skip with reason)

    Returns a PushResult dict with counts.
    """
    base_url = config["base_url"].rstrip("/")
    default_project_id = config.get("default_project_id")
    headers = {
        "Authorization": f"Bearer {config['api_token']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    created = 0
    updated = 0
    skipped_no_project = 0
    skipped_no_local_id = 0
    errors = 0

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        for task in tasks:
            local_id = task.get("local_id")
            if not local_id:
                skipped_no_local_id += 1
                continue

            # Look up existing Vikunja mapping
            vikunja_id = None
            if mapping is not None:
                vikunja_id = mapping.get_source_id(local_id, "vikunja")

            payload = _to_vikunja_payload(task)

            try:
                if vikunja_id:
                    # Update existing Vikunja task
                    _request(
                        client, "POST", f"{base_url}/api/v1/tasks/{vikunja_id}",
                        json=payload,
                    )
                    updated += 1
                else:
                    # Create new Vikunja task
                    if not default_project_id:
                        skipped_no_project += 1
                        continue
                    resp = _request(
                        client, "PUT",
                        f"{base_url}/api/v1/projects/{default_project_id}/tasks",
                        json=payload,
                    )
                    new_task = resp.json()
                    new_id = str(new_task.get("id", ""))
                    if mapping is not None and new_id:
                        mapping.upsert(local_id, "vikunja", new_id)
                    created += 1
            except (VikunjaAuthError, VikunjaFetchError) as exc:
                errors += 1
                if console:
                    console.print(
                        f"[red]  Vikunja:[/] failed on '{task.get('title', '')[:40]}': {exc}"
                    )

    skipped = skipped_no_project + skipped_no_local_id

    if console:
        console.print(
            f"  Vikunja: {created} created, {updated} updated, "
            f"{skipped} skipped, {errors} errors."
        )
        if skipped_no_project > 0:
            console.print(
                f"  [yellow]{skipped_no_project} tasks skipped:[/] no Vikunja mapping found "
                f"and no 'vikunja.default_project_id' set in config.yaml.\n"
                f"  [dim]Add 'default_project_id: <id>' under vikunja: in config.yaml "
                f"to create new tasks in that project.[/]"
            )
        if skipped_no_local_id > 0:
            console.print(
                f"  [yellow]{skipped_no_local_id} tasks skipped:[/] missing local_id "
                f"(run pull first to assign local_ids)."
            )

    return {"created": created, "updated": updated, "skipped": skipped}


def _fetch_projects(client: httpx.Client, base_url: str) -> list[dict]:
    """Fetch all Vikunja projects."""
    projects: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        resp = _request(
            client, "GET", f"{base_url}/api/v1/projects",
            params={"page": page, "per_page": 50},
        )
        batch = resp.json()
        if not batch:
            return projects
        projects.extend(batch)
    raise VikunjaFetchError(
        f"Vikunja projects pagination exceeded MAX_PAGES={MAX_PAGES}"
    )


# -- Vikunja status/priority mapping (for push) --

_VIKUNJA_STATUS_TO_BOOL = {
    "done": True,
    "cancelled": True,
}

_VIKUNJA_PRIORITY_TO_INT = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _to_rfc3339(value: str) -> str:
    """Vikunja expects RFC3339 datetimes. Promote date-only strings to midnight UTC."""
    import re
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return f"{value}T00:00:00Z"
    return value


def _to_vikunja_payload(task: dict) -> dict:
    """Convert a normalized task to a Vikunja API payload."""
    payload: dict = {
        "title": task.get("title", ""),
    }

    desc = task.get("description")
    if desc is not None:
        payload["description"] = desc

    status = task.get("status", "todo")
    payload["done"] = status in _VIKUNJA_STATUS_TO_BOOL

    priority = task.get("priority", "none")
    payload["priority"] = _VIKUNJA_PRIORITY_TO_INT.get(priority, 0)

    due_date = task.get("due_date")
    if due_date:
        payload["due_date"] = _to_rfc3339(due_date)

    tags = task.get("tags", [])
    if tags:
        payload["labels"] = [{"title": t} for t in tags]

    return payload
