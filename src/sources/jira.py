"""Jira REST API v3 source — fetches all issues with pagination and retry."""

from __future__ import annotations

import base64
import httpx
from rich.console import Console

from src.sources._http import (
    SourceAuthError, SourceFetchError,
    request_with_retry, DEFAULT_TIMEOUT,
)

PAGE_SIZE = 100

# Only fetch the fields the normalizer actually uses
JIRA_FIELDS = [
    "summary", "description", "status", "priority", "issuetype",
    "project", "created", "updated", "duedate", "labels",
    "parent", "customfield_10014",
]


class JiraAuthError(SourceAuthError):
    """Raised when Jira authentication fails."""


class JiraFetchError(SourceFetchError):
    """Raised when Jira API returns an unexpected error."""


_AUTH_MESSAGES = {
    401: (
        "Jira authentication failed. Check your email and API token.\n"
        "Generate a token at: https://id.atlassian.com/manage-profile/security/api-tokens"
    ),
    403: "Jira access forbidden. Your API token may lack the required permissions.",
}


def _build_auth_header(email: str, api_token: str) -> str:
    credentials = f"{email}:{api_token}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    return request_with_retry(
        client, method, url,
        auth_error_cls=JiraAuthError,
        fetch_error_cls=JiraFetchError,
        auth_messages=_AUTH_MESSAGES,
        **kwargs,
    )


def pull(config: dict, console: Console | None = None) -> list[dict]:
    """Fetch all Jira issues across all projects.

    Returns a list of raw Jira issue dicts.
    """
    base_url = config["base_url"].rstrip("/")
    auth_header = _build_auth_header(config["email"], config["api_token"])

    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
    }

    issues: list[dict] = []
    next_page_token: str | None = None

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        while True:
            body: dict = {
                "jql": "ORDER BY created DESC",
                "maxResults": PAGE_SIZE,
                "fields": list(JIRA_FIELDS),
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token

            resp = _request(
                client, "POST", f"{base_url}/rest/api/3/search/jql",
                json=body,
            )
            data = resp.json()

            batch = data.get("issues", [])
            issues.extend(batch)

            if console:
                console.print(f"  Jira: fetched {len(issues)} issues...", end="\r")

            next_page_token = data.get("nextPageToken")
            if data.get("isLast", True) or not batch:
                break

    if console:
        console.print(f"  Jira: fetched {len(issues)} issues total.")

    return issues


def push(config: dict, tasks: list[dict], console: Console | None = None) -> dict:
    """Write normalized tasks to Jira. Not yet implemented."""
    raise NotImplementedError("Push not yet implemented for jira")
