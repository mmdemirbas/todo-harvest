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
    @respx.mock
    def test_create_task(self):
        task = {
            "title": "New Task", "description": "Desc", "status": "todo",
            "priority": "high", "due_date": None, "tags": [],
            "_vikunja_id": None, "_vikunja_project_id": 1,
        }
        route = respx.put(f"{BASE_URL}/api/v1/projects/1/tasks")
        route.mock(return_value=httpx.Response(200, json={"id": 99}))

        result = push(VIKUNJA_CONFIG, [task])
        assert result["created"] == 1
        assert result["updated"] == 0
        assert route.call_count == 1

    @respx.mock
    def test_update_task(self):
        task = {
            "title": "Updated Task", "status": "done", "priority": "none",
            "due_date": None, "tags": ["test"], "_vikunja_id": 42,
        }
        route = respx.post(f"{BASE_URL}/api/v1/tasks/42")
        route.mock(return_value=httpx.Response(200, json={"id": 42}))

        result = push(VIKUNJA_CONFIG, [task])
        assert result["updated"] == 1
        assert result["created"] == 0

    @respx.mock
    def test_skip_task_without_project(self):
        task = {
            "title": "Orphan", "status": "todo", "priority": "none",
            "_vikunja_id": None, "_vikunja_project_id": None,
        }
        result = push(VIKUNJA_CONFIG, [task])
        assert result["skipped"] == 1

    @respx.mock
    def test_auth_error_on_push(self):
        task = {"title": "T", "_vikunja_id": 1}
        respx.post(f"{BASE_URL}/api/v1/tasks/1").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        with pytest.raises(VikunjaAuthError):
            push(VIKUNJA_CONFIG, [task])

    @respx.mock
    def test_fetch_error_on_push(self):
        task = {"title": "T", "_vikunja_id": 42}
        respx.post(f"{BASE_URL}/api/v1/tasks/42").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(VikunjaFetchError, match="500"):
            push(VIKUNJA_CONFIG, [task])

    @respx.mock
    def test_push_with_console_does_not_crash(self):
        from rich.console import Console
        task = {"title": "T", "_vikunja_id": None, "_vikunja_project_id": 1}
        respx.put(f"{BASE_URL}/api/v1/projects/1/tasks").mock(
            return_value=httpx.Response(200, json={"id": 10}))
        result = push(VIKUNJA_CONFIG, [task], console=Console(quiet=True))
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
        assert result["tags"] == ["devops", "ci"]

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

    def test_with_tags(self):
        task = {"title": "T", "tags": ["a", "b"]}
        payload = _to_vikunja_payload(task)
        assert payload["labels"] == [{"title": "a"}, {"title": "b"}]

    def test_with_due_date(self):
        task = {"title": "T", "due_date": "2024-03-01"}
        payload = _to_vikunja_payload(task)
        assert payload["due_date"] == "2024-03-01"


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
