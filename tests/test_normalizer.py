"""Tests for the normalizer — targeting 100% coverage.

Each source has its own test class with edge cases for every field mapping.
"""

import json
import pytest
from pathlib import Path

from src.normalizer import (
    normalize,
    normalize_jira,
    normalize_notion,
    normalize_mstodo,
    _extract_adf_text,
    _strip_html,
    _jira_category,
    _notion_title,
    _notion_select_value,
    _notion_multi_select_values,
    _notion_date_value,
    _notion_rich_text,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestDispatch:
    def test_dispatch_jira(self):
        result = normalize("jira", {
            "key": "X-1", "fields": {"summary": "t", "status": {"statusCategory": {"key": "new"}}}
        })
        assert result["source"] == "jira"

    def test_dispatch_notion(self):
        result = normalize("notion", {"id": "p1", "properties": {}})
        assert result["source"] == "notion"

    def test_dispatch_mstodo(self):
        result = normalize("mstodo", {"id": "t1"})
        assert result["source"] == "mstodo"

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError, match="Unknown source"):
            normalize("github", {})


# ---------------------------------------------------------------------------
# Jira normalizer
# ---------------------------------------------------------------------------
class TestNormalizeJira:
    @pytest.fixture
    def issues(self):
        with open(FIXTURES_DIR / "jira_issues.json") as f:
            return json.load(f)["issues"]

    def test_id_format(self, issues):
        result = normalize("jira", issues[0])
        assert result["id"] == "jira-PROJ-1"

    def test_title(self, issues):
        result = normalize("jira", issues[0])
        assert result["title"] == "Set up CI pipeline"

    def test_description_adf(self, issues):
        result = normalize("jira", issues[0])
        assert result["description"] == "Configure GitHub Actions for build and test."

    def test_description_null(self, issues):
        result = normalize("jira", issues[1])
        assert result["description"] is None

    def test_status_todo(self, issues):
        result = normalize("jira", issues[0])
        assert result["status"] == "todo"

    def test_status_in_progress(self, issues):
        result = normalize("jira", issues[1])
        assert result["status"] == "in_progress"

    def test_status_done(self, issues):
        result = normalize("jira", issues[2])
        assert result["status"] == "done"

    def test_status_cancelled(self, issues):
        result = normalize("jira", issues[3])
        assert result["status"] == "cancelled"

    def test_status_in_review_maps_to_in_progress(self, issues):
        result = normalize("jira", issues[4])
        assert result["status"] == "in_progress"

    def test_priority_high(self, issues):
        result = normalize("jira", issues[0])
        assert result["priority"] == "high"

    def test_priority_medium(self, issues):
        result = normalize("jira", issues[1])
        assert result["priority"] == "medium"

    def test_priority_lowest_maps_to_low(self, issues):
        result = normalize("jira", issues[2])
        assert result["priority"] == "low"

    def test_priority_null(self, issues):
        result = normalize("jira", issues[3])
        assert result["priority"] == "none"

    def test_priority_highest_maps_to_critical(self, issues):
        result = normalize("jira", issues[4])
        assert result["priority"] == "critical"

    def test_created_date(self, issues):
        result = normalize("jira", issues[0])
        assert result["created_date"] == "2024-01-15T10:30:00.000+0000"

    def test_due_date(self, issues):
        result = normalize("jira", issues[0])
        assert result["due_date"] == "2024-03-01"

    def test_due_date_null(self, issues):
        result = normalize("jira", issues[1])
        assert result["due_date"] is None

    def test_updated_date(self, issues):
        result = normalize("jira", issues[0])
        assert result["updated_date"] == "2024-02-01T14:22:00.000+0000"

    def test_tags_from_labels(self, issues):
        result = normalize("jira", issues[0])
        assert result["tags"] == ["devops", "ci"]

    def test_tags_empty(self, issues):
        result = normalize("jira", issues[1])
        assert result["tags"] == []

    def test_url_constructed(self, issues):
        result = normalize("jira", issues[0])
        assert result["url"] == "https://test.atlassian.net/browse/PROJ-1"

    def test_category_epic_parent(self, issues):
        result = normalize("jira", issues[0])
        assert result["category"]["type"] == "epic"
        assert result["category"]["name"] == "Infrastructure Setup"
        assert result["category"]["id"] == "PROJ-100"

    def test_category_project_fallback(self, issues):
        result = normalize("jira", issues[1])
        assert result["category"]["type"] == "project"
        assert result["category"]["name"] == "My Project"
        assert result["category"]["id"] == "PROJ"

    def test_category_epic_link_custom_field(self, issues):
        result = normalize("jira", issues[2])
        assert result["category"]["type"] == "epic"
        assert result["category"]["id"] == "WORK-50"

    def test_unicode_title(self, issues):
        result = normalize("jira", issues[2])
        assert "Ünïcödé" in result["title"]

    def test_raw_preserved(self, issues):
        result = normalize("jira", issues[0])
        assert result["raw"] is issues[0]

    def test_source_field(self, issues):
        result = normalize("jira", issues[0])
        assert result["source"] == "jira"

    def test_missing_self_url(self):
        raw = {"key": "X-1", "fields": {"summary": "t", "status": {"statusCategory": {"key": "new"}}}}
        result = normalize("jira", raw)
        assert result["url"] is None

    def test_empty_fields(self):
        raw = {"id": "999", "fields": {}}
        result = normalize("jira", raw)
        assert result["title"] == ""
        assert result["status"] == "todo"
        assert result["priority"] == "none"


class TestExtractAdfText:
    def test_valid_adf(self):
        adf = {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Hello world"},
            ]}]
        }
        assert _extract_adf_text(adf) == "Hello world"

    def test_multiple_text_nodes(self):
        adf = {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "world"},
            ]}]
        }
        assert _extract_adf_text(adf) == "Hello world"

    def test_none_input(self):
        assert _extract_adf_text(None) is None

    def test_non_dict_input(self):
        assert _extract_adf_text("plain string") is None

    def test_empty_content(self):
        assert _extract_adf_text({"content": []}) is None

    def test_no_text_nodes(self):
        adf = {"content": [{"type": "paragraph", "content": [
            {"type": "mention", "attrs": {}}
        ]}]}
        assert _extract_adf_text(adf) is None

    def test_bullet_list_three_levels_deep(self):
        """ADF bulletList -> listItem -> paragraph -> text. Old 2-level walker dropped this."""
        adf = {"type": "doc", "version": 1, "content": [{
            "type": "bulletList",
            "content": [{
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Item one"}],
                }],
            }],
        }]}
        assert _extract_adf_text(adf) == "Item one"

    def test_table_five_levels_deep(self):
        """table -> tableRow -> tableCell -> paragraph -> text."""
        adf = {"type": "doc", "version": 1, "content": [{
            "type": "table",
            "content": [{
                "type": "tableRow",
                "content": [{
                    "type": "tableCell",
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Cell text"}],
                    }],
                }],
            }],
        }]}
        assert _extract_adf_text(adf) == "Cell text"

    def test_panel_with_paragraphs(self):
        adf = {"type": "doc", "version": 1, "content": [{
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Note:"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "details."}]},
            ],
        }]}
        assert _extract_adf_text(adf) == "Note: details."

    def test_mixed_top_level_blocks(self):
        adf = {"type": "doc", "version": 1, "content": [
            {"type": "heading", "content": [{"type": "text", "text": "H1"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "p1"}]},
            {"type": "bulletList", "content": [{
                "type": "listItem", "content": [{
                    "type": "paragraph", "content": [{"type": "text", "text": "li"}],
                }],
            }]},
        ]}
        assert _extract_adf_text(adf) == "H1 p1 li"


class TestJiraCategory:
    def test_epic_parent(self):
        fields = {"parent": {"key": "EP-1", "fields": {
            "summary": "Epic Name", "issuetype": {"name": "Epic"}
        }}}
        cat = _jira_category(fields)
        assert cat == {"id": "EP-1", "name": "Epic Name", "type": "epic"}

    def test_non_epic_parent_falls_through(self):
        fields = {
            "parent": {"key": "P-1", "fields": {
                "summary": "Parent Story", "issuetype": {"name": "Story"}
            }},
            "project": {"key": "PROJ", "name": "My Project"},
        }
        cat = _jira_category(fields)
        assert cat["type"] == "project"

    def test_epic_link_custom_field(self):
        fields = {"customfield_10014": "EPIC-99", "project": {"key": "P", "name": "P"}}
        cat = _jira_category(fields)
        assert cat == {"id": "EPIC-99", "name": "EPIC-99", "type": "epic"}

    def test_project_fallback(self):
        fields = {"project": {"key": "WORK", "name": "Work Tasks"}}
        cat = _jira_category(fields)
        assert cat == {"id": "WORK", "name": "Work Tasks", "type": "project"}

    def test_empty_fields(self):
        cat = _jira_category({})
        assert cat == {"id": None, "name": None, "type": "project"}


# ---------------------------------------------------------------------------
# Notion normalizer
# ---------------------------------------------------------------------------
class TestNormalizeNotion:
    @pytest.fixture
    def pages(self):
        with open(FIXTURES_DIR / "notion_pages.json") as f:
            data = json.load(f)
        pages = data["results"]
        for p in pages:
            p["_database_id"] = "db-abc-123"
            p["_database_title"] = "Task Board"
        return pages

    def test_id_format(self, pages):
        result = normalize("notion", pages[0])
        assert result["id"] == "notion-page-001"

    def test_title(self, pages):
        result = normalize("notion", pages[0])
        assert result["title"] == "Write project proposal"

    def test_empty_title(self, pages):
        result = normalize("notion", pages[3])
        assert result["title"] == ""

    def test_description(self, pages):
        result = normalize("notion", pages[0])
        assert result["description"] == "Draft the proposal document for review."

    def test_description_empty_rich_text(self, pages):
        result = normalize("notion", pages[1])
        assert result["description"] is None

    def test_description_missing(self, pages):
        result = normalize("notion", pages[3])
        assert result["description"] is None

    def test_status_not_started(self, pages):
        result = normalize("notion", pages[0])
        assert result["status"] == "todo"

    def test_status_in_progress(self, pages):
        result = normalize("notion", pages[1])
        assert result["status"] == "in_progress"

    def test_status_done(self, pages):
        result = normalize("notion", pages[2])
        assert result["status"] == "done"

    def test_status_null_defaults_to_todo(self, pages):
        result = normalize("notion", pages[3])
        assert result["status"] == "todo"

    def test_status_cancelled(self, pages):
        result = normalize("notion", pages[4])
        assert result["status"] == "cancelled"

    def test_priority_high(self, pages):
        result = normalize("notion", pages[0])
        assert result["priority"] == "high"

    def test_priority_null(self, pages):
        result = normalize("notion", pages[1])
        assert result["priority"] == "none"

    def test_priority_low(self, pages):
        result = normalize("notion", pages[2])
        assert result["priority"] == "low"

    def test_priority_critical(self, pages):
        result = normalize("notion", pages[4])
        assert result["priority"] == "critical"

    def test_due_date(self, pages):
        result = normalize("notion", pages[0])
        assert result["due_date"] == "2024-02-01"

    def test_due_date_null(self, pages):
        result = normalize("notion", pages[1])
        assert result["due_date"] is None

    def test_due_date_with_time(self, pages):
        result = normalize("notion", pages[4])
        assert result["due_date"] == "2024-03-05T14:00:00.000Z"

    def test_created_date(self, pages):
        result = normalize("notion", pages[0])
        assert result["created_date"] == "2024-01-10T08:00:00.000Z"

    def test_updated_date(self, pages):
        result = normalize("notion", pages[0])
        assert result["updated_date"] == "2024-01-15T12:00:00.000Z"

    def test_tags_from_multi_select(self, pages):
        result = normalize("notion", pages[0])
        assert "writing" in result["tags"]
        assert "planning" in result["tags"]

    def test_tags_from_epic_property(self, pages):
        result = normalize("notion", pages[0])
        assert "Q1 Goals" in result["tags"]

    def test_tags_from_category_property(self, pages):
        result = normalize("notion", pages[2])
        assert "Archive" in result["tags"]

    def test_tags_from_project_multi_select(self, pages):
        result = normalize("notion", pages[4])
        assert "Release v2" in result["tags"]

    def test_tags_empty(self, pages):
        result = normalize("notion", pages[1])
        assert result["tags"] == []

    def test_tags_deduplicated(self):
        """If Tags multi-select and Epic select have the same value, no duplicate."""
        raw = {
            "id": "p-dedup", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "t"}]},
                "Tags": {"type": "multi_select", "multi_select": [
                    {"name": "Q1 Goals"}
                ]},
                "Epic": {"type": "select", "select": {"name": "Q1 Goals"}},
            },
        }
        result = normalize("notion", raw)
        assert result["tags"].count("Q1 Goals") == 1

    def test_url(self, pages):
        result = normalize("notion", pages[0])
        assert result["url"] == "https://www.notion.so/Task-Board-page001"

    def test_url_null(self, pages):
        result = normalize("notion", pages[3])
        assert result["url"] is None

    def test_category_database(self, pages):
        result = normalize("notion", pages[0])
        assert result["category"] == {
            "id": "db-abc-123",
            "name": "Task Board",
            "type": "database",
        }

    def test_unicode_title(self, pages):
        result = normalize("notion", pages[2])
        assert "Ünïcödé" in result["title"]
        assert "日本語" in result["title"]

    def test_raw_preserved(self, pages):
        result = normalize("notion", pages[0])
        assert result["raw"] is pages[0]


class TestNotionHelpers:
    def test_title_multiple_parts_joined(self):
        props = {"Name": {"type": "title", "title": [
            {"plain_text": "Part 1 "},
            {"plain_text": "Part 2"},
        ]}}
        assert _notion_title(props) == "Part 1 Part 2"

    def test_rich_text_multiple_parts_joined(self):
        props = {"Description": {"type": "rich_text", "rich_text": [
            {"plain_text": "Hello "},
            {"plain_text": "world"},
        ]}}
        assert _notion_rich_text(props, "Description") == "Hello world"

    def test_title_no_title_property(self):
        assert _notion_title({"Name": {"type": "rich_text", "rich_text": []}}) == ""

    def test_select_value_wrong_type(self):
        assert _notion_select_value({"S": {"type": "number", "number": 5}}, "S") is None

    def test_select_value_null_select(self):
        assert _notion_select_value({"S": {"type": "select", "select": None}}, "S") is None

    def test_select_value_missing_prop(self):
        assert _notion_select_value({}, "Missing") is None

    def test_multi_select_values_wrong_type(self):
        assert _notion_multi_select_values({"T": {"type": "select"}}, "T") == []

    def test_multi_select_values_missing(self):
        assert _notion_multi_select_values({}, "Missing") == []

    def test_date_value_wrong_type(self):
        assert _notion_date_value({"D": {"type": "number"}}, "D") is None

    def test_date_value_null_date(self):
        assert _notion_date_value({"D": {"type": "date", "date": None}}, "D") is None

    def test_date_value_missing(self):
        assert _notion_date_value({}, "Missing") is None

    def test_rich_text_wrong_type(self):
        assert _notion_rich_text({"N": {"type": "select"}}, "N") is None

    def test_rich_text_empty(self):
        assert _notion_rich_text({"N": {"type": "rich_text", "rich_text": []}}, "N") is None

    def test_rich_text_missing(self):
        assert _notion_rich_text({}, "Missing") is None


# ---------------------------------------------------------------------------
# Microsoft To Do normalizer
# ---------------------------------------------------------------------------
class TestNormalizeMstodo:
    @pytest.fixture
    def tasks(self):
        with open(FIXTURES_DIR / "mstodo_tasks.json") as f:
            data = json.load(f)
        tasks = data["value"]
        for t in tasks:
            t["_list_id"] = "list-001"
            t["_list_name"] = "Personal"
        return tasks

    def test_id_format(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["id"] == "mstodo-task-001"

    def test_title(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["title"] == "Buy groceries"

    def test_description(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["description"] == "Milk, eggs, bread"

    def test_description_empty(self, tasks):
        result = normalize("mstodo", tasks[1])
        assert result["description"] is None

    def test_description_null_body(self, tasks):
        result = normalize("mstodo", tasks[3])
        assert result["description"] is None

    def test_status_not_started(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["status"] == "todo"

    def test_status_in_progress(self, tasks):
        result = normalize("mstodo", tasks[1])
        assert result["status"] == "in_progress"

    def test_status_completed(self, tasks):
        result = normalize("mstodo", tasks[2])
        assert result["status"] == "done"

    def test_priority_high(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["priority"] == "high"

    def test_priority_normal_maps_to_medium(self, tasks):
        result = normalize("mstodo", tasks[1])
        assert result["priority"] == "medium"

    def test_priority_low(self, tasks):
        result = normalize("mstodo", tasks[2])
        assert result["priority"] == "low"

    def test_created_date(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["created_date"] == "2024-01-10T08:00:00.0000000Z"

    def test_updated_date(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["updated_date"] == "2024-01-15T10:00:00.0000000Z"

    def test_due_date(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["due_date"] == "2024-01-20T00:00:00.0000000"

    def test_due_date_null(self, tasks):
        result = normalize("mstodo", tasks[1])
        assert result["due_date"] is None

    def test_tags_from_categories(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert "personal" in result["tags"]
        assert "shopping" in result["tags"]

    def test_tags_include_list_name(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert "Personal" in result["tags"]

    def test_tags_null_categories(self, tasks):
        result = normalize("mstodo", tasks[3])
        # Should still have list name
        assert result["tags"] == ["Personal"]

    def test_tags_no_duplicate_list_name(self):
        raw = {"id": "t1", "categories": ["Personal"], "_list_id": "l1", "_list_name": "Personal"}
        result = normalize("mstodo", raw)
        assert result["tags"].count("Personal") == 1

    def test_url_always_none(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["url"] is None

    def test_category_list(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["category"] == {
            "id": "list-001",
            "name": "Personal",
            "type": "list",
        }

    def test_unicode_title(self, tasks):
        result = normalize("mstodo", tasks[2])
        assert "Ünïcödé" in result["title"]

    def test_raw_preserved(self, tasks):
        result = normalize("mstodo", tasks[0])
        assert result["raw"] is tasks[0]

    def test_html_body_stripped(self, tasks):
        result = normalize("mstodo", tasks[4])
        assert result["description"] == "Review notes from cancelled meeting."
        assert "<" not in result["description"]

    def test_plain_text_body_not_stripped(self):
        raw = {
            "id": "t", "body": {"content": "Plain <text> content", "contentType": "text"},
            "_list_id": "l", "_list_name": "L",
        }
        result = normalize("mstodo", raw)
        assert result["description"] == "Plain <text> content"

    def test_empty_raw(self):
        result = normalize("mstodo", {})
        assert result["title"] == ""
        assert result["status"] == "todo"
        assert result["priority"] == "none"
        assert result["description"] is None
        assert result["tags"] == []


class TestMstodoStatusMappingGaps:
    """Cover status values in _MSFTODO_STATUS_MAP that had no fixture coverage."""

    def test_waiting_on_others(self):
        raw = {"id": "t", "status": "waitingOnOthers", "_list_id": "l", "_list_name": "L"}
        result = normalize("mstodo", raw)
        assert result["status"] == "in_progress"

    def test_deferred(self):
        raw = {"id": "t", "status": "deferred", "_list_id": "l", "_list_name": "L"}
        result = normalize("mstodo", raw)
        assert result["status"] == "todo"

    def test_unknown_status_defaults_to_todo(self):
        raw = {"id": "t", "status": "someNewStatus", "_list_id": "l", "_list_name": "L"}
        result = normalize("mstodo", raw)
        assert result["status"] == "todo"

    def test_unknown_importance_defaults_to_none(self):
        raw = {"id": "t", "importance": "urgent", "_list_id": "l", "_list_name": "L"}
        result = normalize("mstodo", raw)
        assert result["priority"] == "none"


class TestNotionPropertyNameFallbacks:
    """Cover Notion property name fallbacks that had no fixture."""

    def test_notes_property_as_description(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Notes": {"type": "rich_text", "rich_text": [
                    {"plain_text": "Some notes here"}
                ]},
            },
        }
        result = normalize("notion", raw)
        assert result["description"] == "Some notes here"

    def test_due_property_as_date(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Due": {"type": "date", "date": {"start": "2024-06-15"}},
            },
        }
        result = normalize("notion", raw)
        assert result["due_date"] == "2024-06-15"

    def test_deadline_property_as_date(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Deadline": {"type": "date", "date": {"start": "2024-12-31"}},
            },
        }
        result = normalize("notion", raw)
        assert result["due_date"] == "2024-12-31"


class TestJiraStatusEdgeCases:
    """Verify status mapping edge cases."""

    def test_resolved_status_maps_to_done_not_cancelled(self):
        raw = {
            "key": "X-1",
            "fields": {
                "summary": "t",
                "status": {"name": "Resolved", "statusCategory": {"key": "done"}},
            },
        }
        result = normalize("jira", raw)
        assert result["status"] == "done"

    def test_null_status_field(self):
        raw = {"key": "X-1", "fields": {"summary": "t", "status": None}}
        result = normalize("jira", raw)
        assert result["status"] == "todo"


class TestCompletedDate:
    """completed_date is captured where the source provides it."""

    def test_vikunja_done_at(self):
        raw = {"id": 1, "title": "t", "done": True, "done_at": "2024-05-01T10:00:00Z"}
        result = normalize("vikunja", raw)
        assert result["completed_date"] == "2024-05-01T10:00:00Z"

    def test_vikunja_zero_done_at_treated_as_null(self):
        raw = {"id": 1, "title": "t", "done_at": "0001-01-01T00:00:00Z"}
        result = normalize("vikunja", raw)
        assert result["completed_date"] is None

    def test_vikunja_missing_done_at(self):
        raw = {"id": 1, "title": "t"}
        result = normalize("vikunja", raw)
        assert result["completed_date"] is None

    def test_jira_resolutiondate(self):
        raw = {
            "key": "X-1",
            "fields": {
                "summary": "t",
                "status": {"statusCategory": {"key": "done"}},
                "resolutiondate": "2024-06-01T12:00:00.000+0000",
            },
        }
        result = normalize("jira", raw)
        assert result["completed_date"] == "2024-06-01T12:00:00.000+0000"

    def test_jira_no_resolution(self):
        raw = {"key": "X-1", "fields": {"summary": "t", "status": {"statusCategory": {"key": "new"}}}}
        result = normalize("jira", raw)
        assert result["completed_date"] is None

    def test_mstodo_completed(self):
        raw = {
            "id": "t1", "status": "completed",
            "completedDateTime": {"dateTime": "2024-04-10T09:00:00Z"},
            "_list_id": "l", "_list_name": "L",
        }
        result = normalize("mstodo", raw)
        assert result["completed_date"] == "2024-04-10T09:00:00Z"

    def test_mstodo_completed_as_string(self):
        raw = {
            "id": "t1", "completedDateTime": "2024-04-10T09:00:00Z",
            "_list_id": "l", "_list_name": "L",
        }
        result = normalize("mstodo", raw)
        assert result["completed_date"] == "2024-04-10T09:00:00Z"

    def test_notion_always_null(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "t"}]},
            },
        }
        result = normalize("notion", raw)
        assert result["completed_date"] is None


class TestConfigDrivenMappings:
    """Verify config-driven status_map, priority_map, and field_map."""

    def test_jira_custom_status_map(self):
        raw = {
            "key": "X-1",
            "fields": {
                "summary": "t",
                "status": {"name": "Ertelendi", "statusCategory": {"key": "new"}},
            },
        }
        cfg = {"status_map": {"Ertelendi": "cancelled"}}
        result = normalize("jira", raw, cfg)
        assert result["status"] == "cancelled"

    def test_jira_custom_priority_map(self):
        raw = {
            "key": "X-1",
            "fields": {
                "summary": "t",
                "status": {"statusCategory": {"key": "new"}},
                "priority": {"name": "Orta"},
            },
        }
        cfg = {"priority_map": {"Orta": "medium"}}
        result = normalize("jira", raw, cfg)
        assert result["priority"] == "medium"

    def test_jira_unmapped_priority_falls_back(self):
        raw = {
            "key": "X-1",
            "fields": {
                "summary": "t",
                "status": {"statusCategory": {"key": "new"}},
                "priority": {"name": "High"},
            },
        }
        cfg = {"priority_map": {"Orta": "medium"}}
        result = normalize("jira", raw, cfg)
        assert result["priority"] == "high"

    def test_notion_field_map_status(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Durum": {"type": "status", "status": {"name": "Done"}},
            },
        }
        cfg = {"field_map": {"status": "Durum"}}
        result = normalize("notion", raw, cfg)
        assert result["status"] == "done"

    def test_notion_status_type_handled(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Status": {"type": "status", "status": {"name": "In Progress"}},
            },
        }
        result = normalize("notion", raw)
        assert result["status"] == "in_progress"

    def test_notion_custom_status_map(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Status": {"type": "status", "status": {"name": "Today"}},
            },
        }
        cfg = {"status_map": {"Today": "in_progress"}}
        result = normalize("notion", raw, cfg)
        assert result["status"] == "in_progress"

    def test_notion_field_map_priority(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Acil": {"type": "select", "select": {"name": "⭐⭐⭐"}},
            },
        }
        cfg = {
            "field_map": {"priority": "Acil"},
            "priority_map": {"⭐⭐⭐": "critical"},
        }
        result = normalize("notion", raw, cfg)
        assert result["priority"] == "critical"

    def test_notion_field_map_due_date(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Tarih": {"type": "date", "date": {"start": "2024-06-01"}},
            },
        }
        cfg = {"field_map": {"due_date": "Tarih"}}
        result = normalize("notion", raw, cfg)
        assert result["due_date"] == "2024-06-01"

    def test_notion_field_map_tags(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Etiket": {"type": "multi_select", "multi_select": [
                    {"name": "Acil"}, {"name": "Kısa"},
                ]},
            },
        }
        cfg = {"field_map": {"tags": "Etiket"}}
        result = normalize("notion", raw, cfg)
        assert result["tags"] == ["Acil", "Kısa"]

    def test_notion_field_map_category(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Epik": {"type": "select", "select": {"name": "Spark"}},
            },
        }
        cfg = {"field_map": {"category": "Epik"}}
        result = normalize("notion", raw, cfg)
        assert result["category"]["name"] == "Spark"

    def test_notion_field_map_description(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Notlar": {"type": "rich_text", "rich_text": [
                    {"plain_text": "Some notes"},
                ]},
            },
        }
        cfg = {"field_map": {"description": "Notlar"}}
        result = normalize("notion", raw, cfg)
        assert result["description"] == "Some notes"

    def test_no_config_uses_defaults(self):
        raw = {
            "id": "p", "_database_id": "db", "_database_title": "DB",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                "Status": {"type": "select", "select": {"name": "Done"}},
                "Priority": {"type": "select", "select": {"name": "High"}},
            },
        }
        result = normalize("notion", raw)
        assert result["status"] == "done"
        assert result["priority"] == "high"


class TestStripHtml:
    def test_strips_basic_tags(self):
        assert _strip_html("<p>Hello</p>") == "Hello"

    def test_strips_nested_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        assert _strip_html("<p>  Hello  </p>  <p>  World  </p>") == "Hello World"

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_no_tags(self):
        assert _strip_html("plain text") == "plain text"

    def test_self_closing_tags(self):
        assert _strip_html("line1<br/>line2") == "line1line2"

    def test_br_with_space(self):
        assert _strip_html("line1 <br/> line2") == "line1 line2"


class TestUnifiedSchema:
    """Verify that all normalizers produce the same schema shape."""

    REQUIRED_KEYS = {
        "id", "local_id", "source", "title", "description", "status", "priority",
        "created_date", "due_date", "updated_date", "completed_date", "tags", "url",
        "category", "raw",
    }
    CATEGORY_KEYS = {"id", "name", "type"}
    VALID_SOURCES = {"vikunja", "jira", "notion", "mstodo"}
    VALID_STATUSES = {"todo", "in_progress", "done", "cancelled"}
    VALID_PRIORITIES = {"critical", "high", "medium", "low", "none"}

    @pytest.fixture(params=["vikunja", "jira", "notion", "mstodo"])
    def sample(self, request):
        source = request.param
        if source == "vikunja":
            with open(FIXTURES_DIR / "vikunja_tasks.json") as f:
                raw = json.load(f)[0]
        elif source == "jira":
            with open(FIXTURES_DIR / "jira_issues.json") as f:
                raw = json.load(f)["issues"][0]
        elif source == "notion":
            with open(FIXTURES_DIR / "notion_pages.json") as f:
                raw = json.load(f)["results"][0]
            raw["_database_id"] = "db-1"
            raw["_database_title"] = "Board"
        else:
            with open(FIXTURES_DIR / "mstodo_tasks.json") as f:
                raw = json.load(f)["value"][0]
            raw["_list_id"] = "l1"
            raw["_list_name"] = "List"
        return normalize(source, raw)

    def test_has_all_keys(self, sample):
        assert set(sample.keys()) == self.REQUIRED_KEYS

    def test_source_valid(self, sample):
        assert sample["source"] in self.VALID_SOURCES

    def test_status_valid(self, sample):
        assert sample["status"] in self.VALID_STATUSES

    def test_priority_valid(self, sample):
        assert sample["priority"] in self.VALID_PRIORITIES

    def test_tags_is_list(self, sample):
        assert isinstance(sample["tags"], list)

    def test_category_has_keys(self, sample):
        assert set(sample["category"].keys()) == self.CATEGORY_KEYS

    def test_id_prefixed(self, sample):
        assert sample["id"].startswith(f"{sample['source']}-")

    def test_raw_is_dict(self, sample):
        assert isinstance(sample["raw"], dict)

    def test_local_id_is_empty_string(self, sample):
        """Normalizers produce empty local_id — assigned later by merge."""
        assert sample["local_id"] == ""
