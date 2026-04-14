"""Tests for Microsoft To Do source module."""

import json
import pytest
import httpx
import respx
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.sources.msftodo import (
    fetch_all,
    _fetch_lists,
    _fetch_tasks_for_list,
    _get_token,
    MsftodoAuthError,
    MsftodoFetchError,
    GRAPH_BASE,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"
LISTS_URL = f"{GRAPH_BASE}/me/todo/lists"

MSFTODO_CONFIG = {
    "client_id": "test-client-id",
    "tenant_id": "consumers",
}


@pytest.fixture
def lists_fixture():
    with open(FIXTURES_DIR / "msftodo_lists.json") as f:
        return json.load(f)


@pytest.fixture
def tasks_fixture():
    with open(FIXTURES_DIR / "msftodo_tasks.json") as f:
        return json.load(f)


def _mock_get_token(monkeypatch):
    """Patch _get_token to return a fake token without MSAL interaction."""
    monkeypatch.setattr(
        "src.sources.msftodo._get_token", lambda *a, **kw: "fake-access-token"
    )


class TestGetToken:
    def test_silent_acquisition(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.msftodo.TOKEN_CACHE_FILE", tmp_path / "cache.json")

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "user@test.com"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "cached-token"}

        with patch("src.sources.msftodo.msal.PublicClientApplication", return_value=mock_app):
            token = _get_token("client-id", "consumers")

        assert token == "cached-token"
        mock_app.acquire_token_silent.assert_called_once()

    def test_device_code_flow(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.msftodo.TOKEN_CACHE_FILE", tmp_path / "cache.json")

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {
            "user_code": "ABC123",
            "verification_uri": "https://microsoft.com/devicelogin",
        }
        mock_app.acquire_token_by_device_flow.return_value = {
            "access_token": "new-token"
        }

        with patch("src.sources.msftodo.msal.PublicClientApplication", return_value=mock_app):
            token = _get_token("client-id", "consumers")

        assert token == "new-token"

    def test_device_code_flow_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.msftodo.TOKEN_CACHE_FILE", tmp_path / "cache.json")

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {
            "user_code": "ABC123",
            "verification_uri": "https://microsoft.com/devicelogin",
        }
        mock_app.acquire_token_by_device_flow.return_value = {
            "error": "authorization_declined",
            "error_description": "User declined",
        }

        with patch("src.sources.msftodo.msal.PublicClientApplication", return_value=mock_app):
            with pytest.raises(MsftodoAuthError, match="User declined"):
                _get_token("client-id", "consumers")

    def test_initiate_flow_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.msftodo.TOKEN_CACHE_FILE", tmp_path / "cache.json")

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {
            "error_description": "Application not found",
        }

        with patch("src.sources.msftodo.msal.PublicClientApplication", return_value=mock_app):
            with pytest.raises(MsftodoAuthError, match="Application not found"):
                _get_token("client-id", "consumers")

    def test_cache_persistence(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr("src.sources.msftodo.TOKEN_CACHE_FILE", cache_path)

        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = '{"cached": true}'

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "u"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "tok"}

        with patch("src.sources.msftodo.msal.PublicClientApplication", return_value=mock_app), \
             patch("src.sources.msftodo.msal.SerializableTokenCache", return_value=mock_cache):
            _get_token("client-id", "consumers")

        assert cache_path.read_text() == '{"cached": true}'


class TestFetchLists:
    @respx.mock
    def test_single_page(self, lists_fixture):
        respx.get(LISTS_URL).mock(
            return_value=httpx.Response(200, json=lists_fixture)
        )
        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            lists = _fetch_lists(client)
        assert len(lists) == 3
        assert lists[0]["displayName"] == "Personal"

    @respx.mock
    def test_pagination(self, lists_fixture):
        page1 = {
            "value": lists_fixture["value"][:1],
            "@odata.nextLink": f"{LISTS_URL}?$skip=1",
        }
        page2 = {
            "value": lists_fixture["value"][1:],
        }
        route = respx.get(url__startswith=LISTS_URL)
        route.side_effect = [
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]

        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            lists = _fetch_lists(client)
        assert len(lists) == 3
        assert route.call_count == 2


class TestFetchTasksForList:
    @respx.mock
    def test_fetches_tasks(self, tasks_fixture):
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-001/tasks").mock(
            return_value=httpx.Response(200, json=tasks_fixture)
        )
        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            tasks = _fetch_tasks_for_list(client, "list-001")
        assert len(tasks) == 5

    @respx.mock
    def test_pagination(self, tasks_fixture):
        task_url = f"{GRAPH_BASE}/me/todo/lists/list-001/tasks"
        page1 = {
            "value": tasks_fixture["value"][:2],
            "@odata.nextLink": f"{task_url}?$skip=2",
        }
        page2 = {
            "value": tasks_fixture["value"][2:],
        }
        route = respx.get(url__startswith=task_url)
        route.side_effect = [
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]

        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            tasks = _fetch_tasks_for_list(client, "list-001")
        assert len(tasks) == 5
        assert route.call_count == 2


class TestFetchAll:
    @respx.mock
    def test_fetches_all_lists_and_tasks(self, lists_fixture, tasks_fixture, monkeypatch):
        _mock_get_token(monkeypatch)

        respx.get(LISTS_URL).mock(
            return_value=httpx.Response(200, json=lists_fixture)
        )
        # Each list returns the same tasks for simplicity
        empty_tasks = {"value": []}
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-001/tasks").mock(
            return_value=httpx.Response(200, json=tasks_fixture)
        )
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-002/tasks").mock(
            return_value=httpx.Response(200, json={"value": [tasks_fixture["value"][0]]})
        )
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-003/tasks").mock(
            return_value=httpx.Response(200, json=empty_tasks)
        )

        tasks = fetch_all(MSFTODO_CONFIG)
        assert len(tasks) == 6  # 5 + 1
        assert tasks[0]["_list_name"] == "Personal"
        assert tasks[0]["_list_id"] == "list-001"
        assert tasks[5]["_list_name"] == "Work Tasks"

    @respx.mock
    def test_auth_error_on_lists(self, monkeypatch):
        _mock_get_token(monkeypatch)
        respx.get(LISTS_URL).mock(
            return_value=httpx.Response(401, json={"error": {"message": "Unauthorized"}})
        )
        with pytest.raises(MsftodoAuthError, match="authentication failed"):
            fetch_all(MSFTODO_CONFIG)

    @respx.mock
    def test_empty_lists(self, monkeypatch):
        _mock_get_token(monkeypatch)
        respx.get(LISTS_URL).mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        tasks = fetch_all(MSFTODO_CONFIG)
        assert tasks == []


class TestRetryLogic:
    @respx.mock
    def test_retry_on_429(self, lists_fixture, monkeypatch):
        _mock_get_token(monkeypatch)
        monkeypatch.setattr("src.sources.msftodo.BACKOFF_BASE", 0.0)
        route = respx.get(LISTS_URL)
        route.side_effect = [
            httpx.Response(429, text="Rate limited"),
            httpx.Response(200, json=lists_fixture),
        ]
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-001/tasks").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-002/tasks").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-003/tasks").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        tasks = fetch_all(MSFTODO_CONFIG)
        assert route.call_count == 2

    @respx.mock
    def test_retry_exhausted(self, monkeypatch):
        _mock_get_token(monkeypatch)
        monkeypatch.setattr("src.sources.msftodo.BACKOFF_BASE", 0.0)
        route = respx.get(LISTS_URL)
        route.side_effect = [
            httpx.Response(500, text="Error"),
            httpx.Response(500, text="Error"),
            httpx.Response(500, text="Error"),
        ]
        with pytest.raises(MsftodoFetchError):
            fetch_all(MSFTODO_CONFIG)


class TestFixtureData:
    @pytest.fixture
    def tasks(self, tasks_fixture):
        return tasks_fixture["value"]

    def test_task_with_due_date(self, tasks):
        assert tasks[0]["dueDateTime"]["dateTime"].startswith("2024-01-20")

    def test_task_without_due_date(self, tasks):
        assert tasks[1]["dueDateTime"] is None

    def test_unicode_title(self, tasks):
        assert "Ünïcödé" in tasks[2]["title"]

    def test_null_body(self, tasks):
        assert tasks[3]["body"] is None

    def test_empty_body_content(self, tasks):
        assert tasks[1]["body"]["content"] == ""

    def test_null_categories(self, tasks):
        assert tasks[3]["categories"] is None

    def test_completed_task(self, tasks):
        assert tasks[2]["status"] == "completed"
        assert tasks[2]["completedDateTime"] is not None

    def test_old_dates(self, tasks):
        assert tasks[2]["createdDateTime"].startswith("2020-")

    def test_html_body(self, tasks):
        assert tasks[4]["body"]["contentType"] == "html"

    def test_non_utc_timezone(self, tasks):
        assert tasks[4]["dueDateTime"]["timeZone"] == "Pacific Standard Time"
