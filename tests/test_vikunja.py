"""Tests for Vikunja source module."""

from __future__ import annotations

import json
import pytest
import httpx
import respx
from pathlib import Path

from src.sources.vikunja import (
    pull,
    push,
    _to_vikunja_payload,
    _fetch_all_labels,
    _ensure_label,
    _sync_task_labels,
    VikunjaAuthError,
    VikunjaFetchError,
)
from src.normalizer import normalize_vikunja


FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASE_URL = "http://localhost:3456"
TASKS_URL = f"{BASE_URL}/api/v1/tasks"
PROJECTS_URL = f"{BASE_URL}/api/v1/projects"

VIKUNJA_CONFIG = {
    "base_url": BASE_URL,
    "api_token": "test-token",
}


@pytest.fixture
def tasks_fixture():
    with open(FIXTURES_DIR / "vikunja_tasks.json") as f:
        return json.load(f)


@pytest.fixture
def projects_fixture():
    with open(FIXTURES_DIR / "vikunja_projects.json") as f:
        return json.load(f)


class TestPull:
    @respx.mock
    def test_single_page(self, tasks_fixture, projects_fixture):
        respx.get(url__startswith=PROJECTS_URL).mock(
            side_effect=[
                httpx.Response(200, json=projects_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        respx.get(url__startswith=TASKS_URL).mock(
            side_effect=[
                httpx.Response(200, json=tasks_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        tasks = pull(VIKUNJA_CONFIG)
        assert len(tasks) == 5
        assert tasks[0]["title"] == "Set up CI pipeline"
        assert tasks[0]["_project_title"] == "Infrastructure"

    @respx.mock
    def test_pagination(self, tasks_fixture, projects_fixture):
        respx.get(url__startswith=PROJECTS_URL).mock(
            side_effect=[
                httpx.Response(200, json=projects_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        respx.get(url__startswith=TASKS_URL).mock(
            side_effect=[
                httpx.Response(200, json=tasks_fixture[:2]),
                httpx.Response(200, json=tasks_fixture[2:]),
                httpx.Response(200, json=[]),
            ]
        )
        tasks = pull(VIKUNJA_CONFIG)
        assert len(tasks) == 5

    @respx.mock
    def test_pagination_max_pages_raises(self, monkeypatch, tasks_fixture, projects_fixture):
        """Vikunja using page-number iteration: hard cap kicks in if API never returns empty."""
        import src.sources.vikunja as vik_mod
        monkeypatch.setattr(vik_mod, "MAX_PAGES", 2)
        respx.get(url__startswith=PROJECTS_URL).mock(
            side_effect=[
                httpx.Response(200, json=projects_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        # API never returns an empty page → infinite loop without the cap
        respx.get(url__startswith=TASKS_URL).mock(
            return_value=httpx.Response(200, json=tasks_fixture[:1])
        )
        with pytest.raises(VikunjaFetchError, match="exceeded MAX_PAGES"):
            pull(VIKUNJA_CONFIG)

    @respx.mock
    def test_empty_result(self, projects_fixture):
        respx.get(url__startswith=PROJECTS_URL).mock(
            side_effect=[
                httpx.Response(200, json=projects_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        respx.get(url__startswith=TASKS_URL).mock(
            return_value=httpx.Response(200, json=[])
        )
        tasks = pull(VIKUNJA_CONFIG)
        assert tasks == []

    @respx.mock
    def test_auth_error_401(self):
        respx.get(url__startswith=PROJECTS_URL).mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        with pytest.raises(VikunjaAuthError, match="authentication failed"):
            pull(VIKUNJA_CONFIG)

    @respx.mock
    def test_auth_error_403(self):
        respx.get(url__startswith=PROJECTS_URL).mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        with pytest.raises(VikunjaAuthError, match="access forbidden"):
            pull(VIKUNJA_CONFIG)

    @respx.mock
    def test_pull_with_console_does_not_crash(self, tasks_fixture, projects_fixture):
        from rich.console import Console
        respx.get(url__startswith=PROJECTS_URL).mock(
            side_effect=[
                httpx.Response(200, json=projects_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        respx.get(url__startswith=TASKS_URL).mock(
            side_effect=[
                httpx.Response(200, json=tasks_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        tasks = pull(VIKUNJA_CONFIG, console=Console(quiet=True))
        assert len(tasks) == 5

    @respx.mock
    def test_pull_with_paginated_projects(self, tasks_fixture):
        """Projects split across two pages — verify project titles resolve."""
        proj_page1 = [{"id": 1, "title": "ProjectA"}]
        proj_page2 = [{"id": 2, "title": "ProjectB"}]

        respx.get(url__startswith=PROJECTS_URL).mock(
            side_effect=[
                httpx.Response(200, json=proj_page1),
                httpx.Response(200, json=proj_page2),
                httpx.Response(200, json=[]),
            ]
        )
        # All tasks from project 2
        tasks_proj2 = [dict(t, project_id=2, _project_id=2) for t in tasks_fixture[:1]]
        respx.get(url__startswith=TASKS_URL).mock(
            side_effect=[
                httpx.Response(200, json=tasks_proj2),
                httpx.Response(200, json=[]),
            ]
        )
        tasks = pull(VIKUNJA_CONFIG)
        assert tasks[0]["_project_title"] == "ProjectB"

    @respx.mock
    def test_trailing_slash_in_base_url(self, tasks_fixture, projects_fixture):
        config = {**VIKUNJA_CONFIG, "base_url": BASE_URL + "/"}
        respx.get(url__startswith=PROJECTS_URL).mock(
            side_effect=[
                httpx.Response(200, json=projects_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        respx.get(url__startswith=TASKS_URL).mock(
            side_effect=[
                httpx.Response(200, json=tasks_fixture),
                httpx.Response(200, json=[]),
            ]
        )
        tasks = pull(config)
        assert len(tasks) == 5


class TestPush:
    def _config(self, default_project_id=None):
        cfg = dict(VIKUNJA_CONFIG)
        if default_project_id is not None:
            cfg["default_project_id"] = default_project_id
        return cfg

    @pytest.fixture(autouse=True)
    def stub_label_sync(self, monkeypatch):
        """Stub label sync — tests in TestLabelSync exercise it directly.
        Avoids each push test mocking GET /labels + GET /tasks + PUT /labels.
        """
        import src.sources.vikunja as vik
        monkeypatch.setattr(vik, "_fetch_all_labels", lambda *a, **kw: {})
        monkeypatch.setattr(vik, "_sync_task_labels", lambda *a, **kw: None)

    @respx.mock
    def test_create_task_via_default_project(self, tmp_path):
        from src.mapping import SyncMapping
        task = {
            "local_id": "abc-123",
            "title": "New Task", "description": "Desc", "status": "todo",
            "priority": "high", "due_date": None, "tags": [],
        }
        route = respx.put(f"{BASE_URL}/api/v1/projects/1/tasks")
        route.mock(return_value=httpx.Response(200, json={"id": 99}))

        with SyncMapping(tmp_path / "m.db") as mapping:
            result = push(self._config(default_project_id=1), [task], mapping=mapping)

        assert result["created"] == 1
        assert result["updated"] == 0
        assert route.call_count == 1

    @respx.mock
    def test_create_records_new_mapping(self, tmp_path):
        from src.mapping import SyncMapping
        task = {"local_id": "abc-123", "title": "New Task"}
        respx.put(f"{BASE_URL}/api/v1/projects/1/tasks").mock(
            return_value=httpx.Response(200, json={"id": 99})
        )
        with SyncMapping(tmp_path / "m.db") as mapping:
            push(self._config(default_project_id=1), [task], mapping=mapping)
            assert mapping.get_source_id("abc-123", "vikunja") == "99"

    @respx.mock
    def test_update_task_from_mapping(self, tmp_path):
        from src.mapping import SyncMapping
        task = {
            "local_id": "abc-123",
            "title": "Updated Task", "status": "done", "priority": "none",
            "due_date": None, "tags": ["test"],
        }
        route = respx.post(f"{BASE_URL}/api/v1/tasks/42")
        route.mock(return_value=httpx.Response(200, json={"id": 42}))

        with SyncMapping(tmp_path / "m.db") as mapping:
            mapping.upsert("abc-123", "vikunja", "42")
            result = push(VIKUNJA_CONFIG, [task], mapping=mapping)

        assert result["updated"] == 1
        assert result["created"] == 0

    @respx.mock
    def test_skip_without_default_project(self, tmp_path):
        from src.mapping import SyncMapping
        task = {"local_id": "abc-123", "title": "Orphan"}
        with SyncMapping(tmp_path / "m.db") as mapping:
            result = push(VIKUNJA_CONFIG, [task], mapping=mapping)
        assert result["skipped"] == 1
        assert result["created"] == 0

    @respx.mock
    def test_skip_without_local_id(self):
        task = {"title": "No Local ID"}
        result = push(self._config(default_project_id=1), [task])
        assert result["skipped"] == 1

    @respx.mock
    def test_error_reported_but_does_not_abort(self, tmp_path):
        from src.mapping import SyncMapping
        task1 = {"local_id": "a", "title": "T1"}
        task2 = {"local_id": "b", "title": "T2"}
        respx.put(f"{BASE_URL}/api/v1/projects/1/tasks").mock(
            side_effect=[
                httpx.Response(500, text="boom"),
                httpx.Response(500, text="boom"),
                httpx.Response(500, text="boom"),  # retries exhausted
                httpx.Response(200, json={"id": 11}),
            ]
        )
        with SyncMapping(tmp_path / "m.db") as mapping:
            result = push(
                self._config(default_project_id=1),
                [task1, task2],
                mapping=mapping,
            )
        # First task fails, second succeeds
        assert result["created"] == 1

    @respx.mock
    def test_push_with_console_does_not_crash(self, tmp_path):
        from rich.console import Console
        from src.mapping import SyncMapping
        task = {"local_id": "abc", "title": "T"}
        respx.put(f"{BASE_URL}/api/v1/projects/1/tasks").mock(
            return_value=httpx.Response(200, json={"id": 10})
        )
        with SyncMapping(tmp_path / "m.db") as mapping:
            result = push(
                self._config(default_project_id=1), [task],
                console=Console(quiet=True), mapping=mapping,
            )
        assert result["created"] == 1


class TestNormalizeVikunja:
    @pytest.fixture
    def tasks(self, tasks_fixture):
        return tasks_fixture

    def test_id_format(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["id"] == "vikunja-1"

    def test_title(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["title"] == "Set up CI pipeline"

    def test_description(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["description"] == "Configure GitHub Actions for automated testing."

    def test_empty_description_is_none(self, tasks):
        result = normalize_vikunja(tasks[1])
        assert result["description"] is None

    def test_null_description_is_none(self, tasks):
        result = normalize_vikunja(tasks[3])
        assert result["description"] is None

    def test_status_todo(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["status"] == "todo"

    def test_status_done(self, tasks):
        result = normalize_vikunja(tasks[2])
        assert result["status"] == "done"

    def test_priority_high(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["priority"] == "high"

    def test_priority_none(self, tasks):
        result = normalize_vikunja(tasks[3])
        assert result["priority"] == "none"

    def test_priority_critical(self, tasks):
        result = normalize_vikunja(tasks[4])
        assert result["priority"] == "critical"

    def test_due_date(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["due_date"] == "2024-03-01T00:00:00Z"

    def test_zero_due_date_is_none(self, tasks):
        result = normalize_vikunja(tasks[1])
        assert result["due_date"] is None

    def test_null_due_date_is_none(self, tasks):
        result = normalize_vikunja(tasks[3])
        assert result["due_date"] is None

    def test_tags_from_labels(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["tags"] == ["ci", "devops"]  # sorted for stable comparison

    def test_tags_empty(self, tasks):
        result = normalize_vikunja(tasks[1])
        assert result["tags"] == []

    def test_null_labels(self, tasks):
        result = normalize_vikunja(tasks[3])
        assert result["tags"] == []

    def test_category_project(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["category"]["name"] == "Infrastructure"
        assert result["category"]["type"] == "project"

    def test_unicode_title(self, tasks):
        result = normalize_vikunja(tasks[2])
        assert "Ünïcödé" in result["title"]

    def test_created_date(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["created_date"] == "2024-01-15T10:30:00Z"

    def test_source_field(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["source"] == "vikunja"

    def test_local_id_empty(self, tasks):
        result = normalize_vikunja(tasks[0])
        assert result["local_id"] == ""


class TestToVikunjaPayload:
    def test_basic_payload(self):
        task = {"title": "Test", "status": "todo", "priority": "high"}
        payload = _to_vikunja_payload(task)
        assert payload["title"] == "Test"
        assert payload["done"] is False
        assert payload["priority"] == 3

    def test_done_status(self):
        task = {"title": "Done", "status": "done", "priority": "none"}
        payload = _to_vikunja_payload(task)
        assert payload["done"] is True
        assert payload["priority"] == 0

    def test_tags_omitted_from_payload(self):
        """Vikunja silently ignores 'labels' on POST/PUT — must not be sent.
        Labels are reconciled separately via _sync_task_labels."""
        task = {"title": "T", "tags": ["a", "b"]}
        payload = _to_vikunja_payload(task)
        assert "labels" not in payload

    def test_done_at_omitted_from_payload(self):
        """Vikunja sets done_at server-side from done; sending it would either
        be ignored or, worse, freeze a stale completion timestamp."""
        task = {"title": "T", "status": "done", "completed_date": "2024-01-01T00:00:00Z"}
        payload = _to_vikunja_payload(task)
        assert "done_at" not in payload

    def test_with_due_date(self):
        task = {"title": "T", "due_date": "2024-03-01"}
        payload = _to_vikunja_payload(task)
        assert payload["due_date"] == "2024-03-01T00:00:00Z"

    def test_with_due_datetime_preserved(self):
        task = {"title": "T", "due_date": "2024-03-01T15:30:00Z"}
        payload = _to_vikunja_payload(task)
        assert payload["due_date"] == "2024-03-01T15:30:00Z"


class TestLabelSync:
    LABELS_URL = f"{BASE_URL}/api/v1/labels"

    @respx.mock
    def test_fetch_all_labels_paginates_into_index(self):
        respx.get(url__startswith=self.LABELS_URL).mock(
            side_effect=[
                httpx.Response(200, json=[{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]),
                httpx.Response(200, json=[{"id": 3, "title": "c"}]),
                httpx.Response(200, json=[]),
            ]
        )
        with httpx.Client() as client:
            cache = _fetch_all_labels(client, BASE_URL)
        assert cache == {"a": 1, "b": 2, "c": 3}

    @respx.mock
    def test_ensure_label_returns_cached(self):
        # Cache hit: no API call.
        with httpx.Client() as client:
            assert _ensure_label(client, BASE_URL, "x", {"x": 7}) == 7

    @respx.mock
    def test_ensure_label_creates_when_missing(self):
        respx.put(self.LABELS_URL).mock(return_value=httpx.Response(200, json={"id": 42}))
        cache: dict[str, int] = {}
        with httpx.Client() as client:
            assert _ensure_label(client, BASE_URL, "newlabel", cache) == 42
        assert cache == {"newlabel": 42}

    @respx.mock
    def test_sync_attaches_missing_labels(self):
        # Existing labels [1]; want [1, 2]. Should attach 2, not detach 1.
        respx.get(f"{BASE_URL}/api/v1/tasks/100").mock(
            return_value=httpx.Response(200, json={"id": 100, "labels": [{"id": 1}]})
        )
        attach = respx.put(f"{BASE_URL}/api/v1/tasks/100/labels")
        attach.mock(return_value=httpx.Response(200, json={}))
        delete = respx.delete(f"{BASE_URL}/api/v1/tasks/100/labels/1")

        with httpx.Client() as client:
            _sync_task_labels(client, BASE_URL, 100, ["a", "b"], {"a": 1, "b": 2})
        # Attached label 2; never deleted label 1.
        assert attach.call_count == 1
        assert delete.call_count == 0

    @respx.mock
    def test_sync_detaches_stale_labels(self):
        respx.get(f"{BASE_URL}/api/v1/tasks/100").mock(
            return_value=httpx.Response(200, json={"id": 100, "labels": [{"id": 1}, {"id": 2}]})
        )
        attach = respx.put(f"{BASE_URL}/api/v1/tasks/100/labels")
        delete = respx.delete(f"{BASE_URL}/api/v1/tasks/100/labels/2").mock(
            return_value=httpx.Response(204, json={})
        )

        with httpx.Client() as client:
            _sync_task_labels(client, BASE_URL, 100, ["a"], {"a": 1, "b": 2})
        assert attach.call_count == 0
        assert delete.call_count == 1

    @respx.mock
    def test_sync_creates_missing_label_then_attaches(self):
        respx.get(f"{BASE_URL}/api/v1/tasks/100").mock(
            return_value=httpx.Response(200, json={"id": 100, "labels": []})
        )
        create = respx.put(self.LABELS_URL).mock(
            return_value=httpx.Response(200, json={"id": 999})
        )
        attach = respx.put(f"{BASE_URL}/api/v1/tasks/100/labels").mock(
            return_value=httpx.Response(200, json={})
        )
        cache: dict[str, int] = {}
        with httpx.Client() as client:
            _sync_task_labels(client, BASE_URL, 100, ["new-label"], cache)
        assert create.call_count == 1
        assert attach.call_count == 1
        assert cache == {"new-label": 999}

    @respx.mock
    def test_sync_skips_get_when_current_provided(self):
        """Create path passes current_label_ids=set() to skip the redundant GET."""
        # No GET task mock — would error if called.
        attach = respx.put(f"{BASE_URL}/api/v1/tasks/100/labels").mock(
            return_value=httpx.Response(200, json={})
        )
        with httpx.Client() as client:
            _sync_task_labels(
                client, BASE_URL, 100, ["a"], {"a": 1}, current_label_ids=set(),
            )
        assert attach.call_count == 1


class TestRetryLogic:
    @respx.mock
    def test_retry_on_429(self, tasks_fixture, projects_fixture, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(url__startswith=PROJECTS_URL)
        route.side_effect = [
            httpx.Response(429, text="Rate limited"),
            httpx.Response(200, json=projects_fixture),
            httpx.Response(200, json=[]),
        ]
        respx.get(url__startswith=TASKS_URL).mock(
            return_value=httpx.Response(200, json=[])
        )
        tasks = pull(VIKUNJA_CONFIG)
        assert tasks == []

    @respx.mock
    def test_retry_exhausted(self, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(url__startswith=PROJECTS_URL)
        route.side_effect = [
            httpx.Response(500, text="Error"),
            httpx.Response(500, text="Error"),
            httpx.Response(500, text="Error"),
        ]
        with pytest.raises(VikunjaFetchError):
            pull(VIKUNJA_CONFIG)
