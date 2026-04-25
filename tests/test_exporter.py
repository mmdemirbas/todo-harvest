"""Tests for the exporter module."""

import csv
import json
import pytest
from pathlib import Path

from src.exporter import (
    export_json,
    export_csv,
    export_source_json,
    export_all,
    CSV_COLUMNS,
)


@pytest.fixture
def sample_items():
    return [
        {
            "id": "jira-PROJ-2",
            "source": "jira",
            "title": "Second task",
            "description": "Description B",
            "status": "in_progress",
            "priority": "medium",
            "created_date": "2024-01-20T08:00:00Z",
            "due_date": None,
            "updated_date": "2024-01-25T16:45:00Z",
            "tags": ["bug"],
            "url": "https://test.atlassian.net/browse/PROJ-2",
            "category": {"id": "PROJ", "name": "My Project", "type": "project"},
            "raw": {"key": "PROJ-2"},
        },
        {
            "id": "jira-PROJ-1",
            "source": "jira",
            "title": "First task",
            "description": None,
            "status": "todo",
            "priority": "high",
            "created_date": "2024-01-15T10:30:00Z",
            "due_date": "2024-03-01",
            "updated_date": "2024-02-01T14:22:00Z",
            "tags": ["devops", "ci"],
            "url": "https://test.atlassian.net/browse/PROJ-1",
            "category": {"id": "PROJ-100", "name": "Epic Name", "type": "epic"},
            "raw": {"key": "PROJ-1"},
        },
        {
            "id": "notion-page-001",
            "source": "notion",
            "title": "Ünïcödé task 日本語",
            "description": "Draft proposal",
            "status": "done",
            "priority": "low",
            "created_date": "2024-01-10T08:00:00Z",
            "due_date": "2024-02-01",
            "updated_date": "2024-01-15T12:00:00Z",
            "tags": ["writing", "planning"],
            "url": "https://www.notion.so/page001",
            "category": {"id": "db-1", "name": "Task Board", "type": "database"},
            "raw": {"id": "page-001"},
        },
    ]


class TestExportJson:
    def test_writes_valid_json(self, tmp_path, sample_items):
        path = tmp_path / "output" / "test.json"
        export_json(sample_items, path)
        data = json.loads(path.read_text("utf-8"))
        assert len(data) == 3

    def test_sorted_deterministically(self, tmp_path, sample_items):
        path = tmp_path / "test.json"
        export_json(sample_items, path)
        data = json.loads(path.read_text("utf-8"))
        ids = [item["id"] for item in data]
        # Sorted by (source, id): jira-PROJ-1, jira-PROJ-2, notion-page-001
        assert ids == ["jira-PROJ-1", "jira-PROJ-2", "notion-page-001"]

    def test_unicode_preserved(self, tmp_path, sample_items):
        path = tmp_path / "test.json"
        export_json(sample_items, path)
        content = path.read_text("utf-8")
        assert "Ünïcödé" in content
        assert "日本語" in content

    def test_creates_parent_dirs(self, tmp_path, sample_items):
        path = tmp_path / "deep" / "nested" / "dir" / "test.json"
        export_json(sample_items, path)
        assert path.exists()

    def test_overwrites_existing(self, tmp_path, sample_items):
        path = tmp_path / "test.json"
        path.write_text("old content")
        export_json(sample_items, path)
        data = json.loads(path.read_text("utf-8"))
        assert len(data) == 3

    def test_idempotent(self, tmp_path, sample_items):
        path = tmp_path / "test.json"
        export_json(sample_items, path)
        content1 = path.read_text("utf-8")
        export_json(sample_items, path)
        content2 = path.read_text("utf-8")
        assert content1 == content2

    def test_empty_list(self, tmp_path):
        path = tmp_path / "test.json"
        export_json([], path)
        assert json.loads(path.read_text("utf-8")) == []


class TestExportCsv:
    def test_writes_valid_csv(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 3

    def test_correct_columns(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == CSV_COLUMNS

    def test_sorted_deterministically(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            ids = [row["id"] for row in reader]
        assert ids == ["jira-PROJ-1", "jira-PROJ-2", "notion-page-001"]

    def test_completed_date_written(self, tmp_path, sample_items):
        """CSV_COLUMNS declares completed_date — make sure the row dict
        actually populates it."""
        # rows are sorted by (source, id); the notion item ends up last.
        for item in sample_items:
            if item["id"] == "notion-page-001":
                item["completed_date"] = "2024-02-15T10:00:00Z"
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        notion_row = next(r for r in rows if r["id"] == "notion-page-001")
        assert notion_row["completed_date"] == "2024-02-15T10:00:00Z"
        # Items without completed_date stay empty.
        jira_row = next(r for r in rows if r["id"] == "jira-PROJ-1")
        assert jira_row["completed_date"] == ""

    def test_tags_semicolon_separated(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # jira-PROJ-1 has tags ["devops", "ci"]
        assert rows[0]["tags"] == "devops;ci"

    def test_null_fields_become_empty(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # jira-PROJ-1 has description=None
        assert rows[0]["description"] == ""

    def test_category_flattened(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["category_id"] == "PROJ-100"
        assert rows[0]["category_name"] == "Epic Name"
        assert rows[0]["category_type"] == "epic"

    def test_unicode_preserved(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        content = path.read_text("utf-8")
        assert "Ünïcödé" in content

    def test_idempotent(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        content1 = path.read_text("utf-8")
        export_csv(sample_items, path)
        content2 = path.read_text("utf-8")
        assert content1 == content2

    def test_empty_list(self, tmp_path):
        path = tmp_path / "test.csv"
        export_csv([], path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert list(reader) == []

    def test_no_raw_column(self, tmp_path, sample_items):
        path = tmp_path / "test.csv"
        export_csv(sample_items, path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert "raw" not in reader.fieldnames


class TestExportSourceJson:
    def test_creates_source_file(self, tmp_path, sample_items):
        path = export_source_json(sample_items, "jira", tmp_path)
        assert path == tmp_path / "jira.json"
        assert path.exists()


class TestExportAll:
    def test_creates_all_files(self, tmp_path, sample_items):
        files = export_all(sample_items, tmp_path)
        names = {f.name for f in files}
        assert "jira.json" in names
        assert "notion.json" in names
        assert "todos.json" in names
        assert "todos.csv" in names

    def test_per_source_files_contain_correct_items(self, tmp_path, sample_items):
        export_all(sample_items, tmp_path)
        jira_data = json.loads((tmp_path / "jira.json").read_text("utf-8"))
        assert all(item["source"] == "jira" for item in jira_data)
        assert len(jira_data) == 2

        notion_data = json.loads((tmp_path / "notion.json").read_text("utf-8"))
        assert all(item["source"] == "notion" for item in notion_data)
        assert len(notion_data) == 1

    def test_combined_json_has_all(self, tmp_path, sample_items):
        export_all(sample_items, tmp_path)
        data = json.loads((tmp_path / "todos.json").read_text("utf-8"))
        assert len(data) == 3

    def test_combined_csv_has_all(self, tmp_path, sample_items):
        export_all(sample_items, tmp_path)
        with open(tmp_path / "todos.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3

    def test_idempotent(self, tmp_path, sample_items):
        export_all(sample_items, tmp_path)
        json1 = (tmp_path / "todos.json").read_text("utf-8")
        csv1 = (tmp_path / "todos.csv").read_text("utf-8")

        export_all(sample_items, tmp_path)
        json2 = (tmp_path / "todos.json").read_text("utf-8")
        csv2 = (tmp_path / "todos.csv").read_text("utf-8")

        assert json1 == json2
        assert csv1 == csv2

    def test_string_output_dir(self, tmp_path, sample_items):
        files = export_all(sample_items, str(tmp_path / "subdir"))
        assert all(f.exists() for f in files)
