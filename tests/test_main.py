"""Tests for the CLI entry point."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.main import main, parse_args
from src.sources._http import SourceFetchError


@pytest.fixture
def config_file(tmp_path):
    """Create a valid config.yaml for testing."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
output:
  dir: "{output_dir}"

mapping:
  db_path: "{db_path}"

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
""".format(
        output_dir=str(tmp_path / "output"),
        db_path=str(tmp_path / "mapping.db"),
    ))
    return cfg


# -- Minimal raw items for each source (enough to normalize) --

VIKUNJA_RAW = [{
    "id": 1, "title": "Test Vikunja", "description": "", "done": False,
    "priority": 2, "due_date": "0001-01-01T00:00:00Z",
    "created": "2024-01-01T00:00:00Z", "updated": "2024-01-01T00:00:00Z",
    "labels": [], "_project_id": 1, "_project_title": "Project",
}]
JIRA_RAW = [{
    "key": "TEST-1", "self": "https://test.atlassian.net/rest/api/3/issue/1",
    "fields": {
        "summary": "Test Jira", "description": None,
        "status": {"name": "To Do", "statusCategory": {"key": "new"}},
        "priority": {"name": "Medium", "id": "3"},
        "issuetype": {"name": "Task", "subtask": False},
        "project": {"key": "TEST", "name": "Test"},
        "created": "2024-01-01T00:00:00Z", "updated": "2024-01-01T00:00:00Z",
        "duedate": None, "labels": [], "parent": None,
    },
}]

_ITEMS_BY_SOURCE = {
    "vikunja": VIKUNJA_RAW,
    "jira": JIRA_RAW,
    "notion": [],  # simplify — empty is fine for most tests
    "msftodo": [],
}


@pytest.fixture
def mock_sources():
    """Mock all source pull() via the registry."""
    from src.sources import REGISTRY
    originals = {}
    for name, source_def in REGISTRY.items():
        originals[name] = source_def.pull
        items = _ITEMS_BY_SOURCE.get(name, [])
        source_def.pull = lambda config, console=None, _items=items: list(_items)
    yield
    for name, source_def in REGISTRY.items():
        source_def.pull = originals[name]


class TestParseArgs:
    def test_no_command(self):
        args = parse_args([])
        assert args.command is None

    def test_pull_no_services(self):
        args = parse_args(["pull"])
        assert args.command == "pull"
        assert args.services == []

    def test_pull_with_services(self):
        args = parse_args(["pull", "jira", "vikunja"])
        assert args.command == "pull"
        assert args.services == ["jira", "vikunja"]

    def test_push_with_services(self):
        args = parse_args(["push", "vikunja"])
        assert args.command == "push"
        assert args.services == ["vikunja"]

    def test_sync_no_services(self):
        args = parse_args(["sync"])
        assert args.command == "sync"
        assert args.services == []

    def test_export(self):
        args = parse_args(["export", "--output-dir", "/tmp/out"])
        assert args.command == "export"
        assert args.output_dir == "/tmp/out"

    def test_config_flag(self):
        args = parse_args(["--config", "custom.yaml", "pull"])
        assert args.config == "custom.yaml"
        assert args.command == "pull"


class TestMainCLI:
    def test_no_command_returns_1(self, config_file):
        result = main(["--config", str(config_file)])
        assert result == 1

    def test_missing_config_returns_1(self, tmp_path):
        result = main(["--config", str(tmp_path / "nope.yaml"), "pull"])
        assert result == 1

    def test_unknown_service_returns_1(self, config_file):
        result = main(["--config", str(config_file), "pull", "github"])
        assert result == 1

    def test_no_services_configured(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("output:\n  dir: ./output\n")
        result = main(["--config", str(cfg), "pull"])
        assert result == 1


class TestPull:
    def test_pull_all(self, config_file, mock_sources, tmp_path):
        result = main(["--config", str(config_file), "pull"])
        assert result == 0
        state_path = tmp_path / "output" / "todos.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text("utf-8"))
        assert len(data) >= 2  # vikunja + jira items

    def test_pull_single_service(self, config_file, mock_sources, tmp_path):
        result = main(["--config", str(config_file), "pull", "jira"])
        assert result == 0
        state_path = tmp_path / "output" / "todos.json"
        data = json.loads(state_path.read_text("utf-8"))
        assert all(item["source"] == "jira" for item in data)

    def test_pull_fetch_error_continues(self, config_file, mock_sources, tmp_path):
        from src.sources import REGISTRY
        orig = REGISTRY["jira"].pull
        REGISTRY["jira"].pull = lambda c, con=None: (_ for _ in ()).throw(SourceFetchError("fail"))
        try:
            result = main(["--config", str(config_file), "pull", "jira", "vikunja"])
        finally:
            REGISTRY["jira"].pull = orig
        # jira failed but vikunja succeeded → exit 1 (had_errors) but state file has vikunja items
        assert result == 1
        state_path = tmp_path / "output" / "todos.json"
        data = json.loads(state_path.read_text("utf-8"))
        assert any(item["source"] == "vikunja" for item in data)

    def test_pull_idempotent(self, config_file, mock_sources, tmp_path):
        main(["--config", str(config_file), "pull", "jira"])
        main(["--config", str(config_file), "pull", "jira"])
        state_path = tmp_path / "output" / "todos.json"
        data = json.loads(state_path.read_text("utf-8"))
        # Same items, not duplicated
        jira_items = [item for item in data if item["source"] == "jira"]
        assert len(jira_items) == 1


class TestPush:
    def test_push_no_local_tasks(self, config_file, tmp_path):
        result = main(["--config", str(config_file), "push", "vikunja"])
        assert result == 0  # no error, just nothing to push

    def test_push_unsupported_source_skipped(self, config_file, mock_sources, tmp_path):
        # Pull first to create local state
        main(["--config", str(config_file), "pull", "jira"])
        # Push to notion (pull-only) — should skip gracefully
        result = main(["--config", str(config_file), "push", "notion"])
        assert result == 0


class TestSync:
    def test_sync_runs_pull_then_push(self, config_file, mock_sources, tmp_path):
        result = main(["--config", str(config_file), "sync", "jira"])
        assert result == 0
        state_path = tmp_path / "output" / "todos.json"
        assert state_path.exists()


class TestExport:
    def test_export_no_local_tasks(self, config_file, tmp_path):
        result = main(["--config", str(config_file), "export"])
        assert result == 0

    def test_export_after_pull(self, config_file, mock_sources, tmp_path):
        main(["--config", str(config_file), "pull", "jira"])
        result = main(["--config", str(config_file), "export"])
        assert result == 0
        output_dir = tmp_path / "output"
        assert (output_dir / "todos.csv").exists()

    def test_export_custom_output_dir(self, config_file, mock_sources, tmp_path):
        main(["--config", str(config_file), "pull", "jira"])
        custom = tmp_path / "custom"
        result = main(["--config", str(config_file), "export", "--output-dir", str(custom)])
        assert result == 0
        assert (custom / "todos.json").exists()

    def test_export_filesystem_error(self, config_file, mock_sources, tmp_path):
        main(["--config", str(config_file), "pull", "jira"])
        result = main(["--config", str(config_file), "export", "--output-dir", "/nonexistent/path"])
        assert result == 1
