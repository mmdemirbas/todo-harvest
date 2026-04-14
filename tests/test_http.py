"""Tests for shared HTTP retry logic."""

from __future__ import annotations

import pytest
import httpx
import respx

from src.sources._http import (
    request_with_retry,
    SourceAuthError,
    SourceFetchError,
)


class TestRequestWithRetry:
    @respx.mock
    def test_default_auth_message_on_401(self):
        """When no auth_messages provided, uses default fallback text."""
        respx.get("https://api.example.com/test").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        with httpx.Client() as client:
            with pytest.raises(SourceAuthError, match="Authentication failed \\(HTTP 401\\)"):
                request_with_retry(client, "GET", "https://api.example.com/test")

    @respx.mock
    def test_default_auth_message_on_403(self):
        respx.get("https://api.example.com/test").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        with httpx.Client() as client:
            with pytest.raises(SourceAuthError, match="Authentication failed \\(HTTP 403\\)"):
                request_with_retry(client, "GET", "https://api.example.com/test")

    @respx.mock
    def test_custom_auth_messages(self):
        respx.get("https://api.example.com/test").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        with httpx.Client() as client:
            with pytest.raises(SourceAuthError, match="Custom 401 message"):
                request_with_retry(
                    client, "GET", "https://api.example.com/test",
                    auth_messages={401: "Custom 401 message"},
                )

    @respx.mock
    def test_non_retryable_4xx_raises_fetch_error(self):
        respx.get("https://api.example.com/test").mock(
            return_value=httpx.Response(422, text="Unprocessable")
        )
        with httpx.Client() as client:
            with pytest.raises(SourceFetchError, match="422"):
                request_with_retry(client, "GET", "https://api.example.com/test")

    @respx.mock
    def test_success_returns_response(self):
        respx.get("https://api.example.com/test").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        with httpx.Client() as client:
            resp = request_with_retry(client, "GET", "https://api.example.com/test")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @respx.mock
    def test_custom_error_classes(self):
        class MyAuthError(SourceAuthError):
            pass
        class MyFetchError(SourceFetchError):
            pass

        respx.get("https://api.example.com/test").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        with httpx.Client() as client:
            with pytest.raises(MyAuthError):
                request_with_retry(
                    client, "GET", "https://api.example.com/test",
                    auth_error_cls=MyAuthError,
                    fetch_error_cls=MyFetchError,
                )
