"""Tests for Notion source module."""

import json
import pytest
import httpx
import respx
from pathlib import Path

from src.sources.notion import (
    pull,
    _fetch_database_title,
    _fetch_database_pages,
    NotionAuthError,
    NotionFetchError,
    API_BASE,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"

NOTION_CONFIG = {
    "token": "secret_test_token",
    "database_ids": ["db-abc-123"],
}


@pytest.fixture
def db_fixture():
    with open(FIXTURES_DIR / "notion_database.json") as f:
        return json.load(f)


@pytest.fixture
def pages_fixture():
    with open(FIXTURES_DIR / "notion_pages.json") as f:
        return json.load(f)


class TestFetchDatabaseTitle:
    @respx.mock
    def test_fetches_title(self, db_fixture):
        respx.get(f"{API_BASE}/databases/db-abc-123").mock(
            return_value=httpx.Response(200, json=db_fixture)
        )
        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            title = _fetch_database_title(client, "db-abc-123")
        assert title == "Task Board"

    @respx.mock
    def test_empty_title(self):
        respx.get(f"{API_BASE}/databases/db-empty").mock(
            return_value=httpx.Response(200, json={"title": []})
        )
        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            title = _fetch_database_title(client, "db-empty")
        assert title is None


class TestFetchDatabasePages:
    @respx.mock
    def test_single_page(self, pages_fixture):
        respx.post(f"{API_BASE}/databases/db-abc-123/query").mock(
            return_value=httpx.Response(200, json=pages_fixture)
        )
        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            pages = _fetch_database_pages(client, "db-abc-123")
        assert len(pages) == 5

    @respx.mock
    def test_pagination(self, pages_fixture):
        page1 = {
            "results": pages_fixture["results"][:2],
            "has_more": True,
            "next_cursor": "cursor_abc",
        }
        page2 = {
            "results": pages_fixture["results"][2:],
            "has_more": False,
            "next_cursor": None,
        }
        route = respx.post(f"{API_BASE}/databases/db-abc-123/query")
        route.side_effect = [
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            pages = _fetch_database_pages(client, "db-abc-123")
        assert len(pages) == 5
        assert route.call_count == 2


    @respx.mock
    def test_has_more_true_but_no_cursor_terminates(self, pages_fixture):
        """Guard against infinite loop when API returns has_more=True but no cursor."""
        broken_response = {
            "results": pages_fixture["results"][:2],
            "has_more": True,
            "next_cursor": None,
        }
        route = respx.post(f"{API_BASE}/databases/db-abc-123/query")
        route.mock(return_value=httpx.Response(200, json=broken_response))

        with httpx.Client(headers={"Authorization": "Bearer test"}) as client:
            pages = _fetch_database_pages(client, "db-abc-123")

        assert len(pages) == 2
        assert route.call_count == 1  # Must not loop


class TestFetchAll:
    @respx.mock
    def test_fetches_from_single_database(self, db_fixture, pages_fixture):
        respx.get(f"{API_BASE}/databases/db-abc-123").mock(
            return_value=httpx.Response(200, json=db_fixture)
        )
        respx.post(f"{API_BASE}/databases/db-abc-123/query").mock(
            return_value=httpx.Response(200, json=pages_fixture)
        )
        pages = pull(NOTION_CONFIG)
        assert len(pages) == 5
        assert pages[0]["_database_id"] == "db-abc-123"
        assert pages[0]["_database_title"] == "Task Board"

    @respx.mock
    def test_fetches_from_multiple_databases(self, db_fixture, pages_fixture):
        config = {**NOTION_CONFIG, "database_ids": ["db-1", "db-2"]}

        db2_fixture = {**db_fixture, "id": "db-2", "title": [
            {"type": "text", "text": {"content": "Second DB"}, "plain_text": "Second DB"}
        ]}
        pages2 = {
            "results": [pages_fixture["results"][0]],
            "has_more": False,
            "next_cursor": None,
        }

        respx.get(f"{API_BASE}/databases/db-1").mock(
            return_value=httpx.Response(200, json=db_fixture)
        )
        respx.post(f"{API_BASE}/databases/db-1/query").mock(
            return_value=httpx.Response(200, json=pages_fixture)
        )
        respx.get(f"{API_BASE}/databases/db-2").mock(
            return_value=httpx.Response(200, json=db2_fixture)
        )
        respx.post(f"{API_BASE}/databases/db-2/query").mock(
            return_value=httpx.Response(200, json=pages2)
        )

        pages = pull(config)
        assert len(pages) == 6
        assert pages[5]["_database_title"] == "Second DB"

    @respx.mock
    def test_auth_error_401(self):
        respx.get(f"{API_BASE}/databases/db-abc-123").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        with pytest.raises(NotionAuthError, match="authentication failed"):
            pull(NOTION_CONFIG)

    @respx.mock
    def test_auth_error_403(self):
        respx.get(f"{API_BASE}/databases/db-abc-123").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        with pytest.raises(NotionAuthError, match="access forbidden"):
            pull(NOTION_CONFIG)

    @respx.mock
    def test_client_error(self):
        respx.get(f"{API_BASE}/databases/db-abc-123").mock(
            return_value=httpx.Response(400, json={"message": "Bad request"})
        )
        with pytest.raises(NotionFetchError, match="400"):
            pull(NOTION_CONFIG)


class TestRetryLogic:
    @respx.mock
    def test_retry_on_429(self, db_fixture, pages_fixture, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route_db = respx.get(f"{API_BASE}/databases/db-abc-123")
        route_db.side_effect = [
            httpx.Response(429, text="Rate limited"),
            httpx.Response(200, json=db_fixture),
        ]
        respx.post(f"{API_BASE}/databases/db-abc-123/query").mock(
            return_value=httpx.Response(200, json=pages_fixture)
        )
        pages = pull(NOTION_CONFIG)
        assert len(pages) == 5
        assert route_db.call_count == 2

    @respx.mock
    def test_retry_exhausted(self, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(f"{API_BASE}/databases/db-abc-123")
        route.side_effect = [
            httpx.Response(503, text="Down"),
            httpx.Response(503, text="Down"),
            httpx.Response(503, text="Down"),
        ]
        with pytest.raises(NotionFetchError):
            pull(NOTION_CONFIG)

    @respx.mock
    def test_retry_on_network_error(self, db_fixture, pages_fixture, monkeypatch):
        monkeypatch.setattr("src.sources._http.BACKOFF_BASE", 0.0)
        route = respx.get(f"{API_BASE}/databases/db-abc-123")
        route.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.Response(200, json=db_fixture),
        ]
        respx.post(f"{API_BASE}/databases/db-abc-123/query").mock(
            return_value=httpx.Response(200, json=pages_fixture)
        )
        pages = pull(NOTION_CONFIG)
        assert len(pages) == 5


class TestFixtureData:
    @pytest.fixture
    def pages(self, pages_fixture):
        return pages_fixture["results"]

    def test_page_with_all_fields(self, pages):
        page = pages[0]
        assert page["properties"]["Name"]["title"][0]["plain_text"] == "Write project proposal"
        assert page["properties"]["Status"]["select"]["name"] == "Not Started"
        assert page["properties"]["Priority"]["select"]["name"] == "High"
        assert page["properties"]["Due Date"]["date"]["start"] == "2024-02-01"

    def test_page_with_null_selects(self, pages):
        page = pages[1]
        assert page["properties"]["Priority"]["select"] is None
        assert page["properties"]["Due Date"]["date"] is None

    def test_unicode_title(self, pages):
        page = pages[2]
        assert "Ünïcödé" in page["properties"]["Name"]["title"][0]["plain_text"]
        assert "日本語" in page["properties"]["Name"]["title"][0]["plain_text"]

    def test_empty_title(self, pages):
        page = pages[3]
        assert page["properties"]["Name"]["title"] == []

    def test_multi_select_tags(self, pages):
        page = pages[0]
        tags = [t["name"] for t in page["properties"]["Tags"]["multi_select"]]
        assert tags == ["writing", "planning"]

    def test_category_property(self, pages):
        page = pages[2]
        assert page["properties"]["Category"]["select"]["name"] == "Archive"

    def test_project_multi_select(self, pages):
        page = pages[4]
        assert page["properties"]["Project"]["multi_select"][0]["name"] == "Release v2"

    def test_null_url(self, pages):
        page = pages[3]
        assert page["url"] is None
