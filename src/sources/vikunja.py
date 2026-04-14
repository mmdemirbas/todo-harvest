"""Vikunja API source — pull and push tasks via REST API."""

from __future__ import annotations

import httpx
from rich.console import Console

from src.sources._http import (
    SourceAuthError, SourceFetchError,
    request_with_retry, DEFAULT_TIMEOUT,
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
        page = 1
        while True:
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

            page += 1

    if console:
        console.print(f"  Vikunja: fetched {len(all_tasks)} tasks total.")

    return all_tasks


def push(config: dict, tasks: list[dict], console: Console | None = None) -> dict:
    """Write normalized tasks to Vikunja.

    Creates new tasks or updates existing ones based on mapping.
    Returns a PushResult dict with counts.
    """
    base_url = config["base_url"].rstrip("/")
    headers = {
        "Authorization": f"Bearer {config['api_token']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    created = 0
    updated = 0
    skipped = 0

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        for task in tasks:
            source_id = task.get("_vikunja_id")
            if source_id:
                # Update existing task
                payload = _to_vikunja_payload(task)
                _request(client, "POST", f"{base_url}/api/v1/tasks/{source_id}", json=payload)
                updated += 1
            else:
                # Create new task — needs a project_id
                project_id = task.get("_vikunja_project_id")
                if not project_id:
                    skipped += 1
                    continue
                payload = _to_vikunja_payload(task)
                _request(
                    client, "PUT", f"{base_url}/api/v1/projects/{project_id}/tasks",
                    json=payload,
                )
                created += 1

    if console:
        console.print(f"  Vikunja: {created} created, {updated} updated, {skipped} skipped.")

    return {"created": created, "updated": updated, "skipped": skipped}


def _fetch_projects(client: httpx.Client, base_url: str) -> list[dict]:
    """Fetch all Vikunja projects."""
    projects: list[dict] = []
    page = 1
    while True:
        resp = _request(
            client, "GET", f"{base_url}/api/v1/projects",
            params={"page": page, "per_page": 50},
        )
        batch = resp.json()
        if not batch:
            break
        projects.extend(batch)
        page += 1
    return projects


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
        payload["due_date"] = due_date

    tags = task.get("tags", [])
    if tags:
        payload["labels"] = [{"title": t} for t in tags]

    return payload
