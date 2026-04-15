"""Tests for Plane source module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from src.normalizer import normalize_plane
from src.sources.plane import (
    pull,
    push,
    _to_plane_payload,
    PlaneAuthError,
    PlaneFetchError,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASE_URL = "https://plane.example.com"
WORKSPACE = "my-ws"
WS_URL = f"{BASE_URL}/api/v1/workspaces/{WORKSPACE}"

PLANE_CONFIG = {
    "base_url": BASE_URL,
    "api_token": "test-token",
    "workspace_slug": WORKSPACE,
}


@pytest.fixture
def projects_fixture():
    return json.loads((FIXTURES_DIR / "plane_projects.json").read_text())


@pytest.fixture
def states_fixture():
    return json.loads((FIXTURES_DIR / "plane_states.json").read_text())


@pytest.fixture
def labels_fixture():
    return json.loads((FIXTURES_DIR / "plane_labels.json").read_text())


@pytest.fixture
def issues_fixture():
    return json.loads((FIXTURES_DIR / "plane_issues.json").read_text())


def _mock_project_endpoints(project_id: str, states_fx, labels_fx, issues_fx):
    """Mock the per-project state/label/issue endpoints."""
    respx.get(f"{WS_URL}/projects/{project_id}/states/").mock(
        return_value=httpx.Response(200, json=states_fx)
    )
    respx.get(f"{WS_URL}/projects/{project_id}/labels/").mock(
        return_value=httpx.Response(200, json=labels_fx)
    )
    respx.get(f"{WS_URL}/projects/{project_id}/issues/").mock(
        return_value=httpx.Response(200, json=issues_fx)
    )


def _empty_page():
    return {"results": [], "next_cursor": "", "next_page_results": False}


class TestPull:
    @respx.mock
    def test_pulls_issues_with_enrichment(
        self, projects_fixture, states_fixture, labels_fixture, issues_fixture
    ):
        respx.get(f"{WS_URL}/projects/").mock(
            return_value=httpx.Response(200, json=projects_fixture)
        )
        # Only project 1 has issues in fixtures; stub project 2 as empty.
        _mock_project_endpoints(
            "proj-uuid-1", states_fixture, labels_fixture, issues_fixture
        )
        _mock_project_endpoints(
            "proj-uuid-2", _empty_page(), _empty_page(), _empty_page()
        )

        issues = pull(PLANE_CONFIG)

        assert len(issues) == 3
        ci = issues[0]
        assert ci["name"] == "Wire up CI"
        assert ci["_project_id"] == "proj-uuid-1"
        assert ci["_project_name"] == "Backend"
        assert ci["_state_name"] == "In Progress"
        assert ci["_state_group"] == "started"
        assert ci["_label_names"] == ["ci"]
        assert ci["_workspace_slug"] == WORKSPACE
        assert ci["_base_url"] == BASE_URL

    @respx.mock
    def test_project_filter_restricts_fetch(
        self, projects_fixture, states_fixture, labels_fixture, issues_fixture
    ):
        respx.get(f"{WS_URL}/projects/").mock(
            return_value=httpx.Response(200, json=projects_fixture)
        )
        _mock_project_endpoints(
            "proj-uuid-1", states_fixture, labels_fixture, issues_fixture
        )
        # proj-uuid-2 endpoints are NOT mocked — respx will fail if pull hits them.

        config = dict(PLANE_CONFIG, project_ids=["proj-uuid-1"])
        issues = pull(config)
        assert len(issues) == 3

    @respx.mock
    def test_auth_error_raised_on_401(self):
        respx.get(f"{WS_URL}/projects/").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        with pytest.raises(PlaneAuthError):
            pull(PLANE_CONFIG)

    @respx.mock
    def test_cursor_pagination(
        self, projects_fixture, states_fixture, labels_fixture, issues_fixture
    ):
        respx.get(f"{WS_URL}/projects/").mock(
            return_value=httpx.Response(200, json=projects_fixture)
        )
        _mock_project_endpoints(
            "proj-uuid-2", _empty_page(), _empty_page(), _empty_page()
        )
        respx.get(f"{WS_URL}/projects/proj-uuid-1/states/").mock(
            return_value=httpx.Response(200, json=states_fixture)
        )
        respx.get(f"{WS_URL}/projects/proj-uuid-1/labels/").mock(
            return_value=httpx.Response(200, json=labels_fixture)
        )
        page1 = {
            "results": issues_fixture["results"][:2],
            "next_cursor": "cursor-2",
            "next_page_results": True,
        }
        page2 = {
            "results": issues_fixture["results"][2:],
            "next_cursor": "",
            "next_page_results": False,
        }
        respx.get(f"{WS_URL}/projects/proj-uuid-1/issues/").mock(
            side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
        )

        issues = pull(PLANE_CONFIG)
        assert len(issues) == 3


class TestNormalizer:
    def test_maps_state_group_to_status(self):
        raw = {
            "id": "i1", "sequence_id": 1, "name": "t", "priority": "medium",
            "_project_id": "p1", "_project_name": "P", "_state_name": "Done",
            "_state_group": "completed", "_label_names": [],
        }
        item = normalize_plane(raw)
        assert item["status"] == "done"

    def test_priority_urgent_maps_to_critical(self):
        raw = {
            "id": "i1", "sequence_id": 1, "name": "t", "priority": "urgent",
            "_state_group": "started",
        }
        assert normalize_plane(raw)["priority"] == "critical"

    def test_strips_html_from_description(self):
        raw = {
            "id": "i1", "sequence_id": 1, "name": "t", "priority": "none",
            "description_html": "<p>hello <b>world</b></p>",
            "_state_group": "unstarted",
        }
        assert normalize_plane(raw)["description"] == "hello world"

    def test_empty_description_becomes_none(self):
        raw = {
            "id": "i1", "sequence_id": 1, "name": "t", "priority": "none",
            "description_html": "",
            "_state_group": "unstarted",
        }
        assert normalize_plane(raw)["description"] is None

    def test_url_constructed_from_workspace_fields(self):
        raw = {
            "id": "issue-uuid", "sequence_id": 9, "name": "t", "priority": "none",
            "_project_id": "proj-1", "_state_group": "unstarted",
            "_workspace_slug": "my-ws", "_base_url": "https://plane.example.com",
        }
        item = normalize_plane(raw)
        assert item["url"] == (
            "https://plane.example.com/my-ws/projects/proj-1/issues/issue-uuid"
        )

    def test_custom_status_map_overrides_group(self):
        raw = {
            "id": "i1", "sequence_id": 1, "name": "t", "priority": "none",
            "_state_name": "Needs Review", "_state_group": "started",
        }
        cfg = {"status_map": {"Needs Review": "todo"}}
        assert normalize_plane(raw, cfg)["status"] == "todo"

    def test_id_uses_project_and_sequence(self):
        raw = {
            "id": "issue-uuid", "sequence_id": 42, "name": "t", "priority": "none",
            "_project_id": "proj-1", "_state_group": "unstarted",
        }
        assert normalize_plane(raw)["id"] == "plane-proj-1-42"


class TestPushPayload:
    def test_basic_fields(self):
        payload = _to_plane_payload(
            {"title": "Hello", "priority": "high", "due_date": "2026-06-01"}
        )
        assert payload["name"] == "Hello"
        assert payload["priority"] == "high"
        assert payload["target_date"] == "2026-06-01"

    def test_critical_maps_to_urgent(self):
        payload = _to_plane_payload({"title": "t", "priority": "critical"})
        assert payload["priority"] == "urgent"

    def test_trims_datetime_to_date(self):
        payload = _to_plane_payload(
            {"title": "t", "priority": "none", "due_date": "2026-06-01T15:30:00Z"}
        )
        assert payload["target_date"] == "2026-06-01"

    def test_plain_description_wrapped_in_paragraph(self):
        payload = _to_plane_payload(
            {"title": "t", "priority": "none", "description": "plain text"}
        )
        assert payload["description_html"] == "<p>plain text</p>"

    def test_html_description_passed_through(self):
        payload = _to_plane_payload(
            {"title": "t", "priority": "none", "description": "<p>hi</p>"}
        )
        assert payload["description_html"] == "<p>hi</p>"

    def test_omits_target_date_when_missing(self):
        payload = _to_plane_payload({"title": "t", "priority": "none"})
        assert "target_date" not in payload


class TestPush:
    @respx.mock
    def test_creates_new_issue_in_default_project(self):
        config = dict(PLANE_CONFIG, default_project_id="proj-uuid-1")
        mapping = MagicMock()
        mapping.get_source_id.return_value = None
        create_url = f"{WS_URL}/projects/proj-uuid-1/issues/"
        route = respx.post(create_url).mock(
            return_value=httpx.Response(201, json={"id": "new-issue-id"})
        )
        tasks = [{
            "local_id": "local-1", "title": "New",
            "status": "todo", "priority": "medium",
        }]
        result = push(config, tasks, mapping=mapping)
        assert result == {"created": 1, "updated": 0, "skipped": 0}
        assert route.called
        mapping.upsert.assert_called_once_with(
            "local-1", "plane", "proj-uuid-1:new-issue-id"
        )

    @respx.mock
    def test_updates_existing_issue_via_mapping(self):
        config = dict(PLANE_CONFIG, default_project_id="proj-uuid-1")
        mapping = MagicMock()
        mapping.get_source_id.return_value = "proj-uuid-1:existing-id"
        patch_url = f"{WS_URL}/projects/proj-uuid-1/issues/existing-id/"
        route = respx.patch(patch_url).mock(
            return_value=httpx.Response(200, json={"id": "existing-id"})
        )
        tasks = [{
            "local_id": "local-1", "title": "Updated",
            "status": "done", "priority": "high",
        }]
        result = push(config, tasks, mapping=mapping)
        assert result == {"created": 0, "updated": 1, "skipped": 0}
        assert route.called
        mapping.upsert.assert_not_called()

    def test_skips_when_no_default_project_and_no_mapping(self):
        mapping = MagicMock()
        mapping.get_source_id.return_value = None
        tasks = [{"local_id": "l-1", "title": "T", "priority": "none"}]
        result = push(PLANE_CONFIG, tasks, mapping=mapping)
        assert result["created"] == 0
        assert result["skipped"] == 1

    def test_skips_tasks_missing_local_id(self):
        mapping = MagicMock()
        tasks = [{"title": "No id", "priority": "none"}]
        result = push(PLANE_CONFIG, tasks, mapping=mapping)
        assert result == {"created": 0, "updated": 0, "skipped": 1}

    @respx.mock
    def test_fetch_error_increments_errors_but_continues(self):
        config = dict(PLANE_CONFIG, default_project_id="proj-uuid-1")
        mapping = MagicMock()
        mapping.get_source_id.return_value = None
        create_url = f"{WS_URL}/projects/proj-uuid-1/issues/"
        respx.post(create_url).mock(
            side_effect=[
                httpx.Response(400, text="bad"),
                httpx.Response(201, json={"id": "id-2"}),
            ]
        )
        tasks = [
            {"local_id": "l1", "title": "bad", "priority": "none"},
            {"local_id": "l2", "title": "good", "priority": "none"},
        ]
        result = push(config, tasks, mapping=mapping)
        assert result["created"] == 1
