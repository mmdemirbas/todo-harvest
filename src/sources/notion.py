"""Notion API v1 source — fetches pages from specified databases."""

from __future__ import annotations

import time
import httpx
from rich.console import Console

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
BACKOFF_BASE = 1.0
PAGE_SIZE = 100


class NotionAuthError(Exception):
    """Raised when Notion authentication fails."""


class NotionFetchError(Exception):
    """Raised when Notion API returns an unexpected error."""


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
            raise NotionAuthError(
                "Notion authentication failed. Check your integration secret.\n"
                "Create one at: https://www.notion.so/my-integrations"
            )
        if resp.status_code == 403:
            raise NotionAuthError(
                "Notion access forbidden. Make sure the integration is shared with your database.\n"
                "Open the database in Notion → Share → Invite your integration."
            )
        if resp.status_code in RETRY_STATUS_CODES:
            last_exc = NotionFetchError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            time.sleep(BACKOFF_BASE * (2 ** attempt))
            continue
        if resp.status_code >= 400:
            raise NotionFetchError(f"Notion API error {resp.status_code}: {resp.text[:500]}")

        return resp

    raise last_exc  # type: ignore[misc]


def _fetch_database_title(client: httpx.Client, database_id: str) -> str | None:
    """Fetch the title of a Notion database."""
    resp = _request_with_retry(client, "GET", f"{API_BASE}/databases/{database_id}")
    data = resp.json()
    title_parts = data.get("title", [])
    if title_parts:
        return "".join(part.get("plain_text", "") for part in title_parts)
    return None


def _fetch_database_pages(
    client: httpx.Client,
    database_id: str,
    console: Console | None = None,
) -> list[dict]:
    """Fetch all pages from a single Notion database with pagination."""
    pages: list[dict] = []
    start_cursor = None

    while True:
        body: dict = {"page_size": PAGE_SIZE}
        if start_cursor:
            body["start_cursor"] = start_cursor

        resp = _request_with_retry(
            client, "POST", f"{API_BASE}/databases/{database_id}/query", json=body
        )
        data = resp.json()

        batch = data.get("results", [])
        pages.extend(batch)

        if console:
            console.print(f"  Notion: fetched {len(pages)} pages...", end="\r")

        if not data.get("has_more", False):
            break
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            # API says has_more but gave no cursor — break to avoid infinite loop
            break
        start_cursor = next_cursor

    return pages


def fetch_all(config: dict, console: Console | None = None) -> list[dict]:
    """Fetch all pages from all configured Notion databases.

    Each returned dict is a Notion page object, augmented with
    '_database_id' and '_database_title' for normalization.
    """
    token = config["token"]
    database_ids = config["database_ids"]

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    all_pages: list[dict] = []

    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        for db_id in database_ids:
            db_title = _fetch_database_title(client, db_id)
            pages = _fetch_database_pages(client, db_id, console)

            for page in pages:
                page["_database_id"] = db_id
                page["_database_title"] = db_title

            all_pages.extend(pages)

    if console:
        console.print(f"  Notion: fetched {len(all_pages)} pages total.")

    return all_pages
