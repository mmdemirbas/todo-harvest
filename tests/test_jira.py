"""Tests for Jira source module."""

import json
import pytest
import httpx
import respx
from pathlib import Path

from src.sources.jira import (
    fetch_all,
    _build_auth_header,
    JiraAuthError,
    JiraFetchError,
    PAGE_SIZE,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASE_URL = "https://test.atlassian.net"
SEARCH_URL = f"{BASE_URL}/rest/api/3/search"

JIRA_CONFIG = {
    "base_url": BASE_URL,
    "email": "test@example.com",
    "api_token": "test-token",
}


@pytest.fixture
def jira_fixture():
    with open(FIXTURES_DIR / "jira_issues.json") as f:
        return json.load(f)


class TestBuildAuthHeader:
    def test_builds_basic_auth(self):
        header = _build_auth_header("user@example.com", "token123")
        assert header.startswith("Basic ")
        import base64
        decoded = base64.b64decode(header.split(" ")[1]).decode()
        assert decoded == "user@example.com:token123"


class TestFetchAll:
    @respx.mock
    def test_single_page(self, jira_fixture):
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=jira_fixture)
        )
        issues = fetch_all(JIRA_CONFIG)
        assert len(issues) == 5
        assert issues[0]["key"] == "PROJ-1"

    @respx.mock
    def test_pagination(self, jira_fixture):
        page1_data = {
            "issues": jira_fixture["issues"][:2],
            "startAt": 0,
            "maxResults": 2,
            "total": 5,
        }
        page2_data = {
            "issues": jira_fixture["issues"][2:4],
            "startAt": 2,
            "maxResults": 2,
            "total": 5,
        }
        page3_data = {
            "issues": jira_fixture["issues"][4:],
            "startAt": 4,
            "maxResults": 2,
            "total": 5,
        }

        route = respx.get(SEARCH_URL)
        route.side_effect = [
            httpx.Response(200, json=page1_data),
            httpx.Response(200, json=page2_data),
            httpx.Response(200, json=page3_data),
        ]

        issues = fetch_all(JIRA_CONFIG)
        assert len(issues) == 5
        assert route.call_count == 3

    @respx.mock
    def test_empty_result(self):
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json={
                "issues": [], "startAt": 0, "maxResults": 100, "total": 0
            })
        )
        issues = fetch_all(JIRA_CONFIG)
        assert issues == []

    @respx.mock
    def test_with_console_does_not_crash(self, jira_fixture):
        """Verify that passing a Console object works (covers if console: branches)."""
        from rich.console import Console
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=jira_fixture)
        )
        issues = fetch_all(JIRA_CONFIG, console=Console(quiet=True))
        assert len(issues) == 5

    @respx.mock
    def test_auth_error_401(self):
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        with pytest.raises(JiraAuthError, match="authentication failed"):
            fetch_all(JIRA_CONFIG)

    @respx.mock
    def test_auth_error_403(self):
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        with pytest.raises(JiraAuthError, match="access forbidden"):
            fetch_all(JIRA_CONFIG)

    @respx.mock
    def test_client_error_400(self):
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(400, json={"message": "Bad JQL"})
        )
        with pytest.raises(JiraFetchError, match="400"):
            fetch_all(JIRA_CONFIG)

    @respx.mock
    def test_trailing_slash_in_base_url(self, jira_fixture):
        config = {**JIRA_CONFIG, "base_url": BASE_URL + "/"}
        respx.get(SEARCH_URL).mock(
            return_value=httpx.Response(200, json=jira_fixture)
        )
        issues = fetch_all(config)
        assert len(issues) == 5


class TestRetryLogic:
    @respx.mock
    def test_retry_on_429(self, jira_fixture, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(SEARCH_URL)
        route.side_effect = [
            httpx.Response(429, text="Rate limited"),
            httpx.Response(200, json=jira_fixture),
        ]
        issues = fetch_all(JIRA_CONFIG)
        assert len(issues) == 5
        assert route.call_count == 2

    @respx.mock
    def test_retry_on_500(self, jira_fixture, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(SEARCH_URL)
        route.side_effect = [
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json=jira_fixture),
        ]
        issues = fetch_all(JIRA_CONFIG)
        assert len(issues) == 5

    @respx.mock
    def test_retry_exhausted_raises(self, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(SEARCH_URL)
        route.side_effect = [
            httpx.Response(503, text="Unavailable"),
            httpx.Response(503, text="Unavailable"),
            httpx.Response(503, text="Unavailable"),
        ]
        with pytest.raises(JiraFetchError):
            fetch_all(JIRA_CONFIG)
        assert route.call_count == 3

    @respx.mock
    def test_retry_on_connect_error(self, jira_fixture, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(SEARCH_URL)
        route.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.Response(200, json=jira_fixture),
        ]
        issues = fetch_all(JIRA_CONFIG)
        assert len(issues) == 5

    @respx.mock
    def test_retry_exhausted_on_network_error(self, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(SEARCH_URL)
        route.side_effect = [
            httpx.ConnectError("fail"),
            httpx.ConnectError("fail"),
            httpx.ConnectError("fail"),
        ]
        with pytest.raises(httpx.ConnectError):
            fetch_all(JIRA_CONFIG)


class TestFixtureData:
    """Verify the fixture data has the expected edge cases."""

    @pytest.fixture
    def issues(self, jira_fixture):
        return jira_fixture["issues"]

    def test_issue_with_epic_parent(self, issues):
        issue = issues[0]
        assert issue["fields"]["parent"]["fields"]["issuetype"]["name"] == "Epic"

    def test_issue_without_parent(self, issues):
        issue = issues[1]
        assert issue["fields"]["parent"] is None

    def test_unicode_summary(self, issues):
        issue = issues[2]
        assert "Ünïcödé" in issue["fields"]["summary"]

    def test_null_priority(self, issues):
        issue = issues[3]
        assert issue["fields"]["priority"] is None

    def test_null_description(self, issues):
        issue = issues[1]
        assert issue["fields"]["description"] is None

    def test_null_duedate(self, issues):
        issue = issues[1]
        assert issue["fields"]["duedate"] is None

    def test_old_dates(self, issues):
        issue = issues[2]
        assert issue["fields"]["created"].startswith("2020-")

    def test_epic_link_custom_field(self, issues):
        issue = issues[2]
        assert issue["fields"]["customfield_10014"] == "WORK-50"
