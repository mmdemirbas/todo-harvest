"""Notion API v1 source — fetches pages from specified databases."""

from __future__ import annotations

import httpx
from rich.console import Console

from src.sources._http import (
    SourceAuthError, SourceFetchError,
    request_with_retry, DEFAULT_TIMEOUT, MAX_PAGES,
)

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
PAGE_SIZE = 100


class NotionAuthError(SourceAuthError):
    """Raised when Notion authentication fails."""


class NotionFetchError(SourceFetchError):
    """Raised when Notion API returns an unexpected error."""


_AUTH_MESSAGES = {
    401: (
        "Notion authentication failed. Check your integration secret.\n"
        "Create one at: https://www.notion.so/my-integrations"
    ),
    403: (
        "Notion access forbidden. Make sure the integration is shared with your database.\n"
        "Open the database in Notion -> Share -> Invite your integration."
    ),
}


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    return request_with_retry(
        client, method, url,
        auth_error_cls=NotionAuthError,
        fetch_error_cls=NotionFetchError,
        auth_messages=_AUTH_MESSAGES,
        **kwargs,
    )


def _fetch_database_title(client: httpx.Client, database_id: str) -> str | None:
    """Fetch the title of a Notion database."""
    resp = _request(client, "GET", f"{API_BASE}/databases/{database_id}")
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
    seen_cursors: set[str] = set()

    for _ in range(MAX_PAGES):
        body: dict = {"page_size": PAGE_SIZE}
        if start_cursor:
            body["start_cursor"] = start_cursor

        resp = _request(
            client, "POST", f"{API_BASE}/databases/{database_id}/query", json=body
        )
        data = resp.json()

        batch = data.get("results", [])
        pages.extend(batch)

        if console:
            console.print(f"  Notion: fetched {len(pages)} pages...", end="\r")

        if not data.get("has_more", False):
            return pages
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            return pages
        if next_cursor in seen_cursors:
            raise NotionFetchError(
                f"Notion returned a repeated cursor {next_cursor!r}"
            )
        seen_cursors.add(next_cursor)
        start_cursor = next_cursor

    raise NotionFetchError(
        f"Notion pagination exceeded MAX_PAGES={MAX_PAGES}"
    )


def pull(config: dict, console: Console | None = None) -> list[dict]:
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


def push(config: dict, tasks: list[dict], console: Console | None = None) -> dict:
    """Notion is pull-only. Push is not supported."""
    raise NotImplementedError("Notion is pull-only. Push is not supported.")
