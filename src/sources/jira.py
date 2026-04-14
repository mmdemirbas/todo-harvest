"""Jira REST API v3 source — fetches all issues with pagination and retry."""

import base64
import httpx
from rich.console import Console

DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
PAGE_SIZE = 100
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
BACKOFF_BASE = 1.0


class JiraAuthError(Exception):
    """Raised when Jira authentication fails."""


class JiraFetchError(Exception):
    """Raised when Jira API returns an unexpected error."""


def _build_auth_header(email: str, api_token: str) -> str:
    credentials = f"{email}:{api_token}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def _request_with_retry(
    client: httpx.Client, method: str, url: str, **kwargs
) -> httpx.Response:
    """Make an HTTP request with retry on transient errors."""
    import time

    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            last_exc = exc
            time.sleep(BACKOFF_BASE * (2 ** attempt))
            continue

        if resp.status_code == 401:
            raise JiraAuthError(
                "Jira authentication failed. Check your email and API token.\n"
                "Generate a token at: https://id.atlassian.com/manage-profile/security/api-tokens"
            )
        if resp.status_code == 403:
            raise JiraAuthError(
                "Jira access forbidden. Your API token may lack the required permissions."
            )
        if resp.status_code in RETRY_STATUS_CODES:
            last_exc = JiraFetchError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            import time as _t
            _t.sleep(BACKOFF_BASE * (2 ** attempt))
            continue
        if resp.status_code >= 400:
            raise JiraFetchError(f"Jira API error {resp.status_code}: {resp.text[:500]}")

        return resp

    raise last_exc  # type: ignore[misc]


def fetch_all(config: dict, console: Console | None = None) -> list[dict]:
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
    start_at = 0

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        while True:
            params = {
                "jql": "ORDER BY created DESC",
                "maxResults": PAGE_SIZE,
                "startAt": start_at,
                "fields": "*all",
            }
            resp = _request_with_retry(
                client, "GET", f"{base_url}/rest/api/3/search", params=params
            )
            data = resp.json()

            batch = data.get("issues", [])
            issues.extend(batch)

            if console:
                console.print(f"  Jira: fetched {len(issues)} issues...", end="\r")

            total = data.get("total", 0)
            start_at += len(batch)
            if start_at >= total or not batch:
                break

    if console:
        console.print(f"  Jira: fetched {len(issues)} issues total.")

    return issues
