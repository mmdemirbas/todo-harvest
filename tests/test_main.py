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

mstodo:
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
    "mstodo": [],
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


    def test_pull_misconfigured_service_returns_1(self, tmp_path):
        """Service in config but with invalid credentials → skip + exit 1."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text("""
output:
  dir: "{out}"
mapping:
  db_path: "{db}"
jira:
  base_url: "https://test.atlassian.net"
  email: ""
  api_token: "valid-token"
""".format(out=str(tmp_path / "output"), db=str(tmp_path / "test.db")))
        result = main(["--config", str(cfg), "pull", "jira"])
        assert result == 1

    def test_pull_unexpected_exception_returns_1(self, config_file, mock_sources, tmp_path):
        """RuntimeError (not SourceAuthError) still returns 1 with traceback."""
        from src.sources import REGISTRY
        orig = REGISTRY["jira"].pull
        REGISTRY["jira"].pull = lambda c, con=None: (_ for _ in ()).throw(RuntimeError("bug"))
        try:
            result = main(["--config", str(config_file), "pull", "jira"])
        finally:
            REGISTRY["jira"].pull = orig
        assert result == 1


class TestPush:
    def test_push_no_local_tasks(self, config_file, tmp_path):
        result = main(["--config", str(config_file), "push", "vikunja"])
        assert result == 0  # no error, just nothing to push

    def test_push_unsupported_source_skipped(self, config_file, mock_sources, tmp_path):
        main(["--config", str(config_file), "pull", "jira"])
        result = main(["--config", str(config_file), "push", "notion"])
        assert result == 0

    def test_push_auth_error_returns_1(self, config_file, mock_sources, tmp_path):
        """SourceAuthError during push → exit 1."""
        from src.sources import REGISTRY
        from src.sources.vikunja import VikunjaAuthError
        main(["--config", str(config_file), "pull", "vikunja"])
        orig = REGISTRY["vikunja"].push
        REGISTRY["vikunja"].push = lambda c, t, con=None, **kw: (_ for _ in ()).throw(
            VikunjaAuthError("bad token"))
        try:
            result = main(["--config", str(config_file), "push", "vikunja"])
        finally:
            REGISTRY["vikunja"].push = orig
        assert result == 1

    def test_push_unexpected_error_returns_1(self, config_file, mock_sources, tmp_path):
        from src.sources import REGISTRY
        main(["--config", str(config_file), "pull", "vikunja"])
        orig = REGISTRY["vikunja"].push
        REGISTRY["vikunja"].push = lambda c, t, con=None, **kw: (_ for _ in ()).throw(
            RuntimeError("unexpected"))
        try:
            result = main(["--config", str(config_file), "push", "vikunja"])
        finally:
            REGISTRY["vikunja"].push = orig
        assert result == 1

    def test_push_successful_returns_0(self, config_file, mock_sources, tmp_path):
        """Successful push returns 0 and prints summary table."""
        from src.sources import REGISTRY
        main(["--config", str(config_file), "pull", "vikunja"])
        orig = REGISTRY["vikunja"].push
        REGISTRY["vikunja"].push = lambda c, t, con=None, **kw: {"created": 1, "updated": 0, "skipped": 0}
        try:
            result = main(["--config", str(config_file), "push", "vikunja"])
        finally:
            REGISTRY["vikunja"].push = orig
        assert result == 0


class TestSync:
    def test_sync_runs_pull_then_push(self, config_file, mock_sources, tmp_path):
        result = main(["--config", str(config_file), "sync", "jira"])
        assert result == 0
        state_path = tmp_path / "output" / "todos.json"
        assert state_path.exists()

    def test_sync_returns_1_when_pull_fails(self, config_file, mock_sources, tmp_path):
        from src.sources import REGISTRY
        orig = REGISTRY["jira"].pull
        REGISTRY["jira"].pull = lambda c, con=None: (_ for _ in ()).throw(SourceFetchError("down"))
        try:
            result = main(["--config", str(config_file), "sync", "jira"])
        finally:
            REGISTRY["jira"].pull = orig
        assert result == 1


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


class TestHelp:
    def test_help_no_args_returns_0(self):
        assert main(["help"]) == 0

    def test_help_for_known_command_returns_0(self):
        assert main(["help", "pull"]) == 0
        assert main(["help", "push"]) == 0
        assert main(["help", "sync"]) == 0
        assert main(["help", "inspect"]) == 0
        assert main(["help", "export"]) == 0
        assert main(["help", "help"]) == 0

    def test_help_for_unknown_command_returns_1(self):
        assert main(["help", "nosuchcommand"]) == 1

    def test_dash_h_flag(self):
        assert main(["-h"]) == 0

    def test_dash_dash_help_flag(self):
        assert main(["--help"]) == 0

    def test_top_level_help_lists_all_commands(self, capsys):
        main(["help"])
        out = capsys.readouterr().out
        for cmd in ("pull", "push", "sync", "inspect", "export", "help"):
            assert cmd in out

    def test_help_groups_by_function(self, capsys):
        main(["help"])
        out = capsys.readouterr().out
        assert "Sync commands" in out
        assert "Local commands" in out
        assert "Help:" in out

    def test_subcommand_help_shows_arguments(self, capsys):
        main(["help", "pull"])
        out = capsys.readouterr().out
        assert "service" in out
        assert "vikunja" in out  # choices listed


class TestInspect:
    @pytest.fixture
    def populated(self, config_file, mock_sources):
        main(["--config", str(config_file), "pull", "jira", "vikunja"])
        return config_file

    def test_inspect_no_target_returns_1(self, populated):
        result = main(["--config", str(populated), "inspect"])
        assert result == 1

    def test_inspect_projects_all_sources(self, populated):
        result = main(["--config", str(populated), "inspect", "projects"])
        assert result == 0

    def test_inspect_projects_filtered_by_source(self, populated):
        result = main(["--config", str(populated), "inspect", "projects", "vikunja"])
        assert result == 0

    def test_inspect_projects_shows_ids(self, populated, capsys):
        main(["--config", str(populated), "inspect", "projects", "vikunja"])
        out = capsys.readouterr().out
        # Vikunja mock item has _project_id=1, _project_title="Project"
        assert "Project" in out
        assert "1" in out

    def test_inspect_stats(self, populated):
        result = main(["--config", str(populated), "inspect", "stats"])
        assert result == 0

    def test_inspect_stats_contains_status_distribution(self, populated, capsys):
        main(["--config", str(populated), "inspect", "stats"])
        out = capsys.readouterr().out
        assert "Status distribution" in out
        assert "todo" in out

    def test_inspect_fields(self, populated):
        result = main(["--config", str(populated), "inspect", "fields"])
        assert result == 0

    def test_inspect_fields_filtered(self, populated, capsys):
        main(["--config", str(populated), "inspect", "fields", "jira"])
        out = capsys.readouterr().out
        assert "jira" in out
        assert "status:" in out or "status" in out

    def test_inspect_without_local_data_returns_1(self, config_file):
        # No pull done — no todos.json
        result = main(["--config", str(config_file), "inspect", "projects"])
        assert result == 1

    def test_inspect_does_not_need_valid_config(self, tmp_path, monkeypatch):
        # inspect reads only local state, not service credentials.
        # Run in a clean cwd so the real project's ./output doesn't leak in.
        monkeypatch.chdir(tmp_path)
        result = main(["--config", str(tmp_path / "nope.yaml"), "inspect", "stats"])
        assert result == 1  # no local data


class TestStrictCli:
    def test_invalid_subcommand_fails(self, capsys):
        with pytest.raises(SystemExit):
            main(["unknown"])

    def test_multiple_service_args_parse_as_list(self):
        args = parse_args(["pull", "jira", "vikunja", "notion"])
        assert args.services == ["jira", "vikunja", "notion"]

    def test_unknown_service_returns_1(self, config_file):
        result = main(["--config", str(config_file), "pull", "foo"])
        assert result == 1

    def test_inspect_invalid_target_fails(self):
        with pytest.raises(SystemExit):
            main(["inspect", "nosuchtarget"])
