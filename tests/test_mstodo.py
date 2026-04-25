"""Tests for Microsoft To Do source module."""

import json
import os
import pytest
import httpx
import respx
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.sources.mstodo import (
    pull,
    _fetch_lists,
    _fetch_tasks_for_list,
    _get_token,
    _save_cache,
    _migrate_old_cache,
    _get_cache_path,
    MstodoAuthError,
    MstodoFetchError,
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
    with open(FIXTURES_DIR / "mstodo_lists.json") as f:
        return json.load(f)


@pytest.fixture
def tasks_fixture():
    with open(FIXTURES_DIR / "mstodo_tasks.json") as f:
        return json.load(f)


def _mock_get_token(monkeypatch):
    """Patch _get_token to return a fake token without MSAL interaction."""
    monkeypatch.setattr(
        "src.sources.mstodo._get_token", lambda *a, **kw: "fake-access-token"
    )


def _patch_cache_path(monkeypatch, tmp_path):
    """Redirect cache to a temp directory to avoid touching real XDG dirs."""
    cache_dir = tmp_path / ".config" / "todo-harvest"
    monkeypatch.setattr("src.sources.mstodo._get_cache_dir", lambda: cache_dir)
    monkeypatch.setattr("src.sources.mstodo._get_cache_path", lambda: cache_dir / "msal_cache.json")
    return cache_dir / "msal_cache.json"


class TestGetToken:
    def test_silent_acquisition(self, tmp_path, monkeypatch):
        _patch_cache_path(monkeypatch, tmp_path)

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "user@test.com"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "cached-token"}

        with patch("src.sources.mstodo.msal.PublicClientApplication", return_value=mock_app):
            token = _get_token("client-id", "consumers")

        assert token == "cached-token"
        mock_app.acquire_token_silent.assert_called_once()

    def test_silent_acquisition_failure_falls_through_to_device_code(self, tmp_path, monkeypatch):
        """When acquire_token_silent returns None, device code flow is used."""
        _patch_cache_path(monkeypatch, tmp_path)

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "user@test.com"}]
        mock_app.acquire_token_silent.return_value = None
        mock_app.initiate_device_flow.return_value = {
            "user_code": "XYZ789",
            "verification_uri": "https://microsoft.com/devicelogin",
        }
        mock_app.acquire_token_by_device_flow.return_value = {
            "access_token": "device-token"
        }

        with patch("src.sources.mstodo.msal.PublicClientApplication", return_value=mock_app):
            token = _get_token("client-id", "consumers")

        assert token == "device-token"
        mock_app.initiate_device_flow.assert_called_once()

    def test_device_code_flow(self, tmp_path, monkeypatch):
        _patch_cache_path(monkeypatch, tmp_path)

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {
            "user_code": "ABC123",
            "verification_uri": "https://microsoft.com/devicelogin",
        }
        mock_app.acquire_token_by_device_flow.return_value = {
            "access_token": "new-token"
        }

        with patch("src.sources.mstodo.msal.PublicClientApplication", return_value=mock_app):
            token = _get_token("client-id", "consumers")

        assert token == "new-token"

    def test_device_code_flow_failure(self, tmp_path, monkeypatch):
        _patch_cache_path(monkeypatch, tmp_path)

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

        with patch("src.sources.mstodo.msal.PublicClientApplication", return_value=mock_app):
            with pytest.raises(MstodoAuthError, match="User declined"):
                _get_token("client-id", "consumers")

    def test_initiate_flow_failure(self, tmp_path, monkeypatch):
        _patch_cache_path(monkeypatch, tmp_path)

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.initiate_device_flow.return_value = {
            "error_description": "Application not found",
        }

        with patch("src.sources.mstodo.msal.PublicClientApplication", return_value=mock_app):
            with pytest.raises(MstodoAuthError, match="Application not found"):
                _get_token("client-id", "consumers")

    def test_cache_persistence(self, tmp_path, monkeypatch):
        cache_path = _patch_cache_path(monkeypatch, tmp_path)

        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = '{"cached": true}'

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [{"username": "u"}]
        mock_app.acquire_token_silent.return_value = {"access_token": "tok"}

        with patch("src.sources.mstodo.msal.PublicClientApplication", return_value=mock_app), \
             patch("src.sources.mstodo.msal.SerializableTokenCache", return_value=mock_cache):
            _get_token("client-id", "consumers")

        assert cache_path.exists()
        assert cache_path.read_text() == '{"cached": true}'


class TestSaveCache:
    def test_creates_directory_and_file(self, tmp_path):
        cache_path = tmp_path / "subdir" / "cache.json"
        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = '{"token": "data"}'

        _save_cache(mock_cache, cache_path)

        assert cache_path.exists()
        assert cache_path.read_text() == '{"token": "data"}'

    def test_file_permissions_are_restrictive(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.return_value = "{}"

        _save_cache(mock_cache, cache_path)

        mode = os.stat(cache_path).st_mode & 0o777
        assert mode == 0o600

    def test_no_write_when_cache_unchanged(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        mock_cache = MagicMock()
        mock_cache.has_state_changed = False

        _save_cache(mock_cache, cache_path)

        assert not cache_path.exists()

    def test_atomic_write_cleans_up_on_error(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        mock_cache = MagicMock()
        mock_cache.has_state_changed = True
        mock_cache.serialize.side_effect = RuntimeError("serialize failed")

        with pytest.raises(RuntimeError, match="serialize failed"):
            _save_cache(mock_cache, cache_path)

        assert not cache_path.exists()
        # No temp files left behind
        assert list(tmp_path.iterdir()) == []


class TestMigrateOldCache:
    def test_migrates_old_cache_to_new_location(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        old_path = tmp_path / ".todo_harvest_msal_cache.json"
        old_path.write_text('{"old": true}')

        new_path = tmp_path / "new" / "cache.json"
        _migrate_old_cache(new_path)

        assert not old_path.exists()
        assert new_path.exists()
        assert new_path.read_text() == '{"old": true}'

    def test_skips_migration_when_new_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        old_path = tmp_path / ".todo_harvest_msal_cache.json"
        old_path.write_text('{"old": true}')

        new_path = tmp_path / "new" / "cache.json"
        new_path.parent.mkdir(parents=True)
        new_path.write_text('{"new": true}')

        _migrate_old_cache(new_path)

        assert old_path.exists()  # Old file NOT deleted
        assert new_path.read_text() == '{"new": true}'  # New file NOT overwritten

    def test_skips_migration_when_old_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        new_path = tmp_path / "new" / "cache.json"
        _migrate_old_cache(new_path)
        assert not new_path.exists()


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

    @respx.mock
    def test_pagination_repeated_nextlink_raises(self, tasks_fixture):
        """Buggy server returning the same @odata.nextLink must not infinite-loop."""
        from src.sources.mstodo import MstodoFetchError
        task_url = f"{GRAPH_BASE}/me/todo/lists/list-001/tasks"
        cycling_link = f"{task_url}?$skip=2"
        page = {
            "value": tasks_fixture["value"][:1],
            "@odata.nextLink": cycling_link,
        }
        respx.get(url__startswith=task_url).mock(
            side_effect=[httpx.Response(200, json=page), httpx.Response(200, json=page)]
        )
        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            with pytest.raises(MstodoFetchError, match="repeated nextLink"):
                _fetch_tasks_for_list(client, "list-001")


class TestFetchAll:
    @respx.mock
    def test_fetches_all_lists_and_tasks(self, lists_fixture, tasks_fixture, monkeypatch):
        _mock_get_token(monkeypatch)

        respx.get(LISTS_URL).mock(
            return_value=httpx.Response(200, json=lists_fixture)
        )
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

        tasks = pull(MSFTODO_CONFIG)
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
        with pytest.raises(MstodoAuthError, match="authentication failed"):
            pull(MSFTODO_CONFIG)

    @respx.mock
    def test_empty_lists(self, monkeypatch):
        _mock_get_token(monkeypatch)
        respx.get(LISTS_URL).mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        tasks = pull(MSFTODO_CONFIG)
        assert tasks == []


class TestRetryLogic:
    @respx.mock
    def test_retry_on_429(self, lists_fixture, monkeypatch):
        _mock_get_token(monkeypatch)
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
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
        tasks = pull(MSFTODO_CONFIG)
        assert route.call_count == 2

    @respx.mock
    def test_retry_exhausted(self, monkeypatch):
        _mock_get_token(monkeypatch)
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(LISTS_URL)
        route.side_effect = [
            httpx.Response(500, text="Error"),
            httpx.Response(500, text="Error"),
            httpx.Response(500, text="Error"),
        ]
        with pytest.raises(MstodoFetchError):
            pull(MSFTODO_CONFIG)


class TestPush:
    def test_push_raises_not_implemented(self):
        from src.sources.mstodo import push
        with pytest.raises(NotImplementedError, match="not yet implemented for mstodo"):
            push({}, [])


class TestPullWithConsole:
    @respx.mock
    def test_pull_with_console_does_not_crash(self, lists_fixture, tasks_fixture, monkeypatch):
        from rich.console import Console
        _mock_get_token(monkeypatch)
        respx.get(LISTS_URL).mock(return_value=httpx.Response(200, json=lists_fixture))
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-001/tasks").mock(
            return_value=httpx.Response(200, json=tasks_fixture))
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-002/tasks").mock(
            return_value=httpx.Response(200, json={"value": []}))
        respx.get(f"{GRAPH_BASE}/me/todo/lists/list-003/tasks").mock(
            return_value=httpx.Response(200, json={"value": []}))
        tasks = pull(MSFTODO_CONFIG, console=Console(quiet=True))
        assert len(tasks) == 5


class TestCachePath:
    def test_get_cache_path_returns_xdg_location(self):
        path = _get_cache_path()
        assert str(path).endswith(".config/todo-harvest/msal_cache.json")


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
