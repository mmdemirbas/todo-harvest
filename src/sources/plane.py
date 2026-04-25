"""Plane (self-hosted) source — pull and push issues via REST API v1.

Plane is workspace-scoped. Issues live inside projects. State (status) and
labels are stored as UUIDs that reference per-project collections, so we
fetch those lookup tables during pull and attach resolved names/groups to
each raw issue for the normalizer.

Docs: https://developers.plane.so/api-reference/
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from rich.console import Console

if TYPE_CHECKING:
    from src.mapping import SyncMapping

from src.sources._http import (
    SourceAuthError, SourceFetchError,
    request_with_retry, DEFAULT_TIMEOUT,
)


class PlaneAuthError(SourceAuthError):
    """Raised when Plane authentication fails."""


class PlaneFetchError(SourceFetchError):
    """Raised when Plane API returns an unexpected error."""


_AUTH_MESSAGES = {
    401: "Plane authentication failed. Check your X-API-Key token.",
    403: "Plane access forbidden. Check your API token workspace permissions.",
}

_PER_PAGE = 100


def _headers(token: str) -> dict[str, str]:
    return {
        "X-API-Key": token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    return request_with_retry(
        client, method, url,
        auth_error_cls=PlaneAuthError,
        fetch_error_cls=PlaneFetchError,
        auth_messages=_AUTH_MESSAGES,
        **kwargs,
    )


def _paginate(client: httpx.Client, url: str, params: dict | None = None) -> list[dict]:
    """Fetch all pages from a Plane list endpoint.

    Plane returns either:
      - a dict with `results`, `next_cursor`, `next_page_results`
      - a bare list (some endpoints)
    """
    params = dict(params or {})
    params.setdefault("per_page", _PER_PAGE)
    out: list[dict] = []
    cursor: str | None = None
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        resp = _request(client, "GET", url, params=page_params)
        body = resp.json()
        if isinstance(body, list):
            out.extend(body)
            return out
        if not isinstance(body, dict):
            return out
        out.extend(body.get("results", []))
        if not body.get("next_page_results") or not body.get("next_cursor"):
            return out
        cursor = body["next_cursor"]


def pull(config: dict, console: Console | None = None) -> list[dict]:
    """Fetch all issues from the configured Plane workspace.

    Each returned issue dict is augmented with:
      - `_project_id`, `_project_name`
      - `_state_name`, `_state_group`
      - `_label_names` (list[str])
      - `_workspace_slug`, `_base_url` (for URL construction)
    """
    base_url = config["base_url"].rstrip("/")
    token = config["api_token"]
    workspace = config["workspace_slug"]
    project_filter = config.get("project_ids")  # optional list
    headers = _headers(token)

    ws_url = f"{base_url}/api/v1/workspaces/{workspace}"
    all_issues: list[dict] = []

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        projects = _paginate(client, f"{ws_url}/projects/")
        project_map = {str(p["id"]): p for p in projects if p.get("id")}

        target_ids = (
            [str(pid) for pid in project_filter]
            if project_filter
            else list(project_map.keys())
        )

        for pid in target_ids:
            project = project_map.get(pid)
            if project is None:
                if console:
                    console.print(
                        f"  [yellow]Plane:[/] project {pid} not found in workspace, skipping"
                    )
                continue

            state_map = _fetch_state_map(client, ws_url, pid)
            label_map = _fetch_label_map(client, ws_url, pid)

            issues = _paginate(client, f"{ws_url}/projects/{pid}/issues/")
            for issue in issues:
                state_id = issue.get("state")
                state = state_map.get(str(state_id)) if state_id else None
                label_ids = issue.get("labels") or []
                issue["_project_id"] = pid
                issue["_project_name"] = project.get("name")
                issue["_state_name"] = (state or {}).get("name")
                issue["_state_group"] = (state or {}).get("group")
                issue["_label_names"] = [
                    label_map[str(lid)]["name"]
                    for lid in label_ids
                    if str(lid) in label_map and label_map[str(lid)].get("name")
                ]
                issue["_workspace_slug"] = workspace
                issue["_base_url"] = base_url

            all_issues.extend(issues)
            if console:
                console.print(
                    f"  Plane: fetched {len(all_issues)} issues...", end="\r"
                )

    if console:
        console.print(f"  Plane: fetched {len(all_issues)} issues total.")

    return all_issues


def _fetch_state_map(
    client: httpx.Client, ws_url: str, project_id: str
) -> dict[str, dict]:
    states = _paginate(client, f"{ws_url}/projects/{project_id}/states/")
    return {str(s["id"]): s for s in states if s.get("id")}


def _fetch_label_map(
    client: httpx.Client, ws_url: str, project_id: str
) -> dict[str, dict]:
    labels = _paginate(client, f"{ws_url}/projects/{project_id}/labels/")
    return {str(l["id"]): l for l in labels if l.get("id")}


def push(
    config: dict,
    tasks: list[dict],
    console: Console | None = None,
    mapping: "SyncMapping | None" = None,
) -> dict:
    """Write normalized tasks to Plane.

    For each task:
      - If mapping.db has a Plane source_id (`project_id:issue_id`) → PATCH
      - Else → POST into config['default_project_id']

    Known limitations:
      - `state` (status) is not synced. New issues land in the project's
        default state; updates never change state.
      - Labels are not synced (requires per-project UUID lookups).
    """
    base_url = config["base_url"].rstrip("/")
    token = config["api_token"]
    workspace = config["workspace_slug"]
    default_project_id = config.get("default_project_id")
    headers = _headers(token)

    ws_url = f"{base_url}/api/v1/workspaces/{workspace}"

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

            existing = None
            if mapping is not None:
                existing = mapping.get_source_id(local_id, "plane")

            payload = _to_plane_payload(task)

            try:
                if existing and ":" in existing:
                    project_id, issue_id = existing.split(":", 1)
                    _request(
                        client, "PATCH",
                        f"{ws_url}/projects/{project_id}/issues/{issue_id}/",
                        json=payload,
                    )
                    updated += 1
                else:
                    if not default_project_id:
                        skipped_no_project += 1
                        continue
                    project_id = str(default_project_id)
                    resp = _request(
                        client, "POST",
                        f"{ws_url}/projects/{project_id}/issues/",
                        json=payload,
                    )
                    new_issue = resp.json()
                    new_id = str(new_issue.get("id", ""))
                    if mapping is not None and new_id:
                        mapping.upsert(local_id, "plane", f"{project_id}:{new_id}")
                    created += 1
            except (PlaneAuthError, PlaneFetchError) as exc:
                errors += 1
                if console:
                    console.print(
                        f"[red]  Plane:[/] failed on '{task.get('title', '')[:40]}': {exc}"
                    )

    skipped = skipped_no_project + skipped_no_local_id

    if console:
        console.print(
            f"  Plane: {created} created, {updated} updated, "
            f"{skipped} skipped, {errors} errors."
        )
        if skipped_no_project > 0:
            console.print(
                f"  [yellow]{skipped_no_project} tasks skipped:[/] no Plane mapping found "
                f"and no 'plane.default_project_id' set in config.yaml."
            )
        if skipped_no_local_id > 0:
            console.print(
                f"  [yellow]{skipped_no_local_id} tasks skipped:[/] missing local_id "
                f"(run pull first to assign local_ids)."
            )

    return {"created": created, "updated": updated, "skipped": skipped}


def migrate_legacy_mappings(
    mapping: "SyncMapping", raw_issues: list[dict]
) -> None:
    """Upgrade pre-fix mapping rows from 'project_id-sequence_id' to 'project_id:UUID'.

    Older normalize_plane stored the human-readable sequence_id; push later
    expected the API UUID and silently fell through to CREATE on every run,
    duplicating issues. Walk the pulled raw issues, find any legacy mapping
    rows for the same (project, sequence), and rewrite them to the UUID form.
    Idempotent.
    """
    for issue in raw_issues:
        project_id = issue.get("_project_id")
        sequence_id = issue.get("sequence_id")
        issue_uuid = issue.get("id")
        if not (project_id and sequence_id is not None and issue_uuid):
            continue
        legacy = f"{project_id}-{sequence_id}"
        modern = f"{project_id}:{issue_uuid}"
        if legacy == modern:
            continue
        if mapping.get_local_id("plane", legacy) is None:
            continue
        mapping.relabel_source_id("plane", legacy, modern)


_UNIFIED_PRIORITY_TO_PLANE = {
    "none": "none",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "urgent",
}


def _to_plane_payload(task: dict) -> dict:
    payload: dict = {"name": task.get("title", "")}

    desc = task.get("description")
    if desc is not None:
        # Plane stores HTML; wrap plain text defensively.
        payload["description_html"] = desc if "<" in desc else f"<p>{desc}</p>"

    priority = task.get("priority", "none")
    payload["priority"] = _UNIFIED_PRIORITY_TO_PLANE.get(priority, "none")

    due = task.get("due_date")
    if due:
        # Plane target_date is a date (YYYY-MM-DD). Trim datetimes.
        payload["target_date"] = due[:10]

    return payload
