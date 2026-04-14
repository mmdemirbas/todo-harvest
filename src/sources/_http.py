"""Shared HTTP retry logic for all source modules."""

from __future__ import annotations

import time

import httpx

DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
BACKOFF_BASE = 1.0


class SourceAuthError(Exception):
    """Base class for authentication errors from any source."""


class SourceFetchError(Exception):
    """Base class for fetch errors from any source."""


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    auth_error_cls: type[SourceAuthError] = SourceAuthError,
    fetch_error_cls: type[SourceFetchError] = SourceFetchError,
    auth_messages: dict[int, str] | None = None,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP request with retry on transient errors.

    Args:
        client: httpx.Client to use.
        method: HTTP method.
        url: Request URL.
        auth_error_cls: Exception class to raise on 401/403.
        fetch_error_cls: Exception class to raise on other HTTP errors.
        auth_messages: Optional dict mapping status code (401, 403) to error message.
        **kwargs: Passed through to client.request().
    """
    if auth_messages is None:
        auth_messages = {}

    last_exc: BaseException | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            last_exc = exc
            time.sleep(BACKOFF_BASE * (2 ** attempt))
            continue

        if resp.status_code in (401, 403):
            msg = auth_messages.get(
                resp.status_code,
                f"Authentication failed (HTTP {resp.status_code})"
            )
            raise auth_error_cls(msg)

        if resp.status_code in RETRY_STATUS_CODES:
            last_exc = fetch_error_cls(f"HTTP {resp.status_code}: {resp.text[:200]}")
            time.sleep(BACKOFF_BASE * (2 ** attempt))
            continue

        if resp.status_code >= 400:
            raise fetch_error_cls(f"API error {resp.status_code}: {resp.text[:500]}")

        return resp

    raise last_exc  # type: ignore[misc]
