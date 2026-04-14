"""Tests for the CLI entry point."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.main import main, parse_args
from src.sources._http import SourceFetchError


@pytest.fixture
def config_file(tmp_path):
    """Create a valid config.yaml for testing."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
output:
  dir: "{output_dir}"

vikunja:
  base_url: "http://localhost:3456"
  api_token: "test-vikunja-token"

jira:
  base_url: "https://test.atlassian.net"
  email: "test@example.com"
  api_token: "test-token"

notion:
  token: "secret_test"
  database_ids:
    - "db-1"

msftodo:
  client_id: "test-client-id"
  tenant_id: "consumers"
""".format(output_dir=str(tmp_path / "output")))
    return cfg


JIRA_ITEMS = [
    {
        "key": "TEST-1",
        "self": "https://test.atlassian.net/rest/api/3/issue/1",
        "fields": {
            "summary": "Test Jira",
            "description": None,
            "status": {"name": "To Do", "statusCategory": {"key": "new"}},
            "priority": {"name": "Medium", "id": "3"},
            "issuetype": {"name": "Task", "subtask": False},
            "project": {"key": "TEST", "name": "Test"},
            "created": "2024-01-01T00:00:00Z",
            "updated": "2024-01-01T00:00:00Z",
            "duedate": None,
            "labels": [],
            "parent": None,
        },
    }
]

NOTION_ITEMS = [
    {
        "id": "page-1",
        "created_time": "2024-01-01T00:00:00Z",
        "last_edited_time": "2024-01-01T00:00:00Z",
        "url": None,
        "_database_id": "db-1",
        "_database_title": "Board",
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": "Test Notion"}],
            },
            "Status": {"type": "select", "select": {"name": "Done"}},
        },
    }
]

MSFTODO_ITEMS = [
    {
        "id": "task-1",
        "title": "Test MS ToDo",
        "body": None,
        "status": "notStarted",
        "importance": "normal",
        "createdDateTime": "2024-01-01T00:00:00Z",
        "lastModifiedDateTime": "2024-01-01T00:00:00Z",
        "dueDateTime": None,
        "categories": [],
        "_list_id": "list-1",
        "_list_name": "Tasks",
    }
]

VIKUNJA_ITEMS = [
    {
        "id": 1,
        "title": "Test Vikunja",
        "description": "",
        "done": False,
        "priority": 2,
        "due_date": "0001-01-01T00:00:00Z",
        "created": "2024-01-01T00:00:00Z",
        "updated": "2024-01-01T00:00:00Z",
        "labels": [],
        "_project_id": 1,
        "_project_title": "Test Project",
    }
]

_ITEMS_BY_SOURCE = {
    "vikunja": VIKUNJA_ITEMS,
    "jira": JIRA_ITEMS,
    "notion": NOTION_ITEMS,
    "msftodo": MSFTODO_ITEMS,
}


@pytest.fixture
def mock_sources():
    """Mock all source pull via the registry."""
    from src.sources import REGISTRY
    originals = {}
    for name, source_def in REGISTRY.items():
        originals[name] = source_def.pull
        items = _ITEMS_BY_SOURCE[name]
        source_def.pull = lambda config, console=None, _items=items: list(_items)
    yield
    for name, source_def in REGISTRY.items():
        source_def.pull = originals[name]


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.source is None
        assert args.output_dir is None
        assert args.config is None

    def test_source_flag(self):
        args = parse_args(["--source", "jira,notion"])
        assert args.source == "jira,notion"

    def test_output_dir_flag(self):
        args = parse_args(["--output-dir", "/tmp/exports"])
        assert args.output_dir == "/tmp/exports"

    def test_config_flag(self):
        args = parse_args(["--config", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"


class TestMain:
    def test_missing_config(self, tmp_path):
        result = main(["--config", str(tmp_path / "nonexistent.yaml")])
        assert result == 1

    def test_all_sources(self, config_file, mock_sources, tmp_path):
        result = main(["--config", str(config_file)])
        assert result == 0
        output_dir = tmp_path / "output"
        assert (output_dir / "todos.json").exists()
        assert (output_dir / "todos.csv").exists()

    def test_single_source(self, config_file, mock_sources, tmp_path):
        result = main(["--config", str(config_file), "--source", "jira"])
        assert result == 0
        output_dir = tmp_path / "output"
        assert (output_dir / "jira.json").exists()

    def test_multiple_sources(self, config_file, mock_sources, tmp_path):
        result = main(["--config", str(config_file), "--source", "jira,notion"])
        assert result == 0

    def test_invalid_source_name(self, config_file):
        result = main(["--config", str(config_file), "--source", "github"])
        assert result == 1

    def test_output_dir_override(self, config_file, mock_sources, tmp_path):
        custom_dir = tmp_path / "custom"
        result = main([
            "--config", str(config_file),
            "--source", "jira",
            "--output-dir", str(custom_dir),
        ])
        assert result == 0
        assert (custom_dir / "todos.json").exists()

    def test_no_sources_configured(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("output:\n  dir: ./output\n")
        result = main(["--config", str(cfg)])
        assert result == 1

    def test_source_validation_error_skips_but_returns_partial_success(self, tmp_path, mock_sources):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("""
output:
  dir: "{output_dir}"
jira:
  base_url: "https://test.atlassian.net"
  email: "test@example.com"
  api_token: "test-token"
notion:
  token: ""
  database_ids: []
""".format(output_dir=str(tmp_path / "output")))
        result = main(["--config", str(cfg), "--source", "jira,notion"])
        assert result == 1
        assert (tmp_path / "output" / "jira.json").exists()

    def test_fetch_error_continues_with_other_sources(self, config_file, tmp_path, mock_sources):
        from src.sources import REGISTRY
        orig = REGISTRY["jira"].pull
        def raise_fetch_error(config, console=None):
            raise SourceFetchError("Connection failed")
        REGISTRY["jira"].pull = raise_fetch_error
        try:
            result = main(["--config", str(config_file), "--source", "jira,msftodo"])
        finally:
            REGISTRY["jira"].pull = orig
        assert result == 1

    def test_unexpected_fetch_error_shows_traceback(self, config_file, tmp_path, mock_sources):
        from src.sources import REGISTRY
        orig = REGISTRY["jira"].pull
        def raise_bug(config, console=None):
            raise TypeError("unexpected bug")
        REGISTRY["jira"].pull = raise_bug
        try:
            result = main(["--config", str(config_file), "--source", "jira"])
        finally:
            REGISTRY["jira"].pull = orig
        assert result == 1

    def test_all_normalize_errors_returns_1(self, config_file, tmp_path, mock_sources):
        with patch("src.normalizer.normalize", side_effect=ValueError("bad field")):
            result = main(["--config", str(config_file), "--source", "jira"])
        assert result == 1

    def test_no_items_collected_clean(self, config_file, tmp_path):
        from src.sources import REGISTRY
        orig = REGISTRY["jira"].pull
        REGISTRY["jira"].pull = lambda config, console=None: []
        try:
            result = main(["--config", str(config_file), "--source", "jira"])
        finally:
            REGISTRY["jira"].pull = orig
        assert result == 0

    def test_export_filesystem_error_returns_1(self, config_file, mock_sources, tmp_path):
        result = main([
            "--config", str(config_file),
            "--source", "jira",
            "--output-dir", "/nonexistent/readonly/path",
        ])
        assert result == 1

    def test_output_files_content(self, config_file, mock_sources, tmp_path):
        main(["--config", str(config_file), "--source", "jira"])
        output_dir = tmp_path / "output"
        data = json.loads((output_dir / "todos.json").read_text("utf-8"))
        assert len(data) == 1
        assert data[0]["source"] == "jira"
        assert data[0]["title"] == "Test Jira"
