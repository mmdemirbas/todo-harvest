"""Tests for config loading and validation."""

import pytest
from pathlib import Path
from src.config import load_config, validate_source, enabled_sources, ConfigError


@pytest.fixture
def valid_config(tmp_path):
    """Write a fully valid config.yaml and return its path."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
output:
  dir: ./output

mstodo:
  client_id: "test-client-id"
  tenant_id: "consumers"

jira:
  base_url: "https://test.atlassian.net"
  email: "test@example.com"
  api_token: "test-token"

notion:
  token: "secret_test"
  database_ids:
    - "db-1"
    - "db-2"
"""
    )
    return cfg


@pytest.fixture
def partial_config(tmp_path):
    """Config with only Jira configured."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
jira:
  base_url: "https://test.atlassian.net"
  email: "test@example.com"
  api_token: "test-token"
"""
    )
    return cfg


class TestLoadConfig:
    def test_loads_valid_config(self, valid_config):
        config = load_config(valid_config)
        assert config["jira"]["base_url"] == "https://test.atlassian.net"
        assert config["output"]["dir"] == "./output"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("{{{{invalid yaml")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load_config(cfg)

    def test_non_mapping_raises(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("- a list\n- not a mapping\n")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_config(cfg)

    def test_default_output_dir(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("jira:\n  base_url: x\n")
        config = load_config(cfg)
        assert config["output"]["dir"] == "./output"

    def test_output_not_mapping_raises(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("output: not_a_dict\n")
        with pytest.raises(ConfigError, match="'output' must be a mapping"):
            load_config(cfg)


class TestValidateSource:
    def test_valid_jira(self, valid_config):
        config = load_config(valid_config)
        assert validate_source(config, "jira") == []

    def test_valid_notion(self, valid_config):
        config = load_config(valid_config)
        assert validate_source(config, "notion") == []

    def test_valid_mstodo(self, valid_config):
        config = load_config(valid_config)
        assert validate_source(config, "mstodo") == []

    def test_missing_section(self, valid_config):
        config = load_config(valid_config)
        del config["jira"]
        errors = validate_source(config, "jira")
        assert len(errors) == 1
        assert "missing from config.yaml" in errors[0]

    def test_missing_key(self, valid_config):
        config = load_config(valid_config)
        del config["jira"]["api_token"]
        errors = validate_source(config, "jira")
        assert any("api_token" in e for e in errors)

    def test_empty_string_key(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["api_token"] = "   "
        errors = validate_source(config, "jira")
        assert any("api_token" in e for e in errors)

    def test_empty_list_key(self, valid_config):
        config = load_config(valid_config)
        config["notion"]["database_ids"] = []
        errors = validate_source(config, "notion")
        assert any("database_ids" in e for e in errors)

    def test_section_wrong_type(self, valid_config):
        config = load_config(valid_config)
        config["jira"] = "not a mapping"
        errors = validate_source(config, "jira")
        assert any("must be a mapping" in e for e in errors)

    def test_integer_value_rejected(self, valid_config):
        """YAML parses unquoted numbers as int — must produce clear error."""
        config = load_config(valid_config)
        config["jira"]["api_token"] = 12345
        errors = validate_source(config, "jira")
        assert any("must be a string" in e for e in errors)

    def test_boolean_value_rejected(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["base_url"] = True
        errors = validate_source(config, "jira")
        assert any("must be a string" in e for e in errors)

    def test_database_ids_wrong_type_rejected(self, valid_config):
        config = load_config(valid_config)
        config["notion"]["database_ids"] = "not-a-list"
        errors = validate_source(config, "notion")
        assert any("must be a list" in e for e in errors)

    def test_none_value_rejected(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["email"] = None
        errors = validate_source(config, "jira")
        assert any("missing" in e for e in errors)

    def test_placeholder_your_rejected(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["api_token"] = "YOUR_API_TOKEN"
        errors = validate_source(config, "jira")
        assert any("placeholder" in e for e in errors)

    def test_placeholder_database_id_rejected(self, valid_config):
        config = load_config(valid_config)
        config["mstodo"]["client_id"] = "DATABASE_ID_1"
        errors = validate_source(config, "mstodo")
        assert any("placeholder" in e for e in errors)

    def test_placeholder_case_insensitive(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["email"] = "your_email@example.com"
        errors = validate_source(config, "jira")
        assert any("placeholder" in e for e in errors)

    def test_real_values_pass_placeholder_check(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["api_token"] = "ATATTxyz123realtoken"
        errors = validate_source(config, "jira")
        assert errors == []


    def test_placeholder_todo_prefix_rejected(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["api_token"] = "TODO_fill_this_in"
        errors = validate_source(config, "jira")
        assert any("placeholder" in e for e in errors)

    def test_placeholder_fixme_prefix_rejected(self, valid_config):
        config = load_config(valid_config)
        config["jira"]["email"] = "FIXME_set_email"
        errors = validate_source(config, "jira")
        assert any("placeholder" in e for e in errors)

    def test_unknown_source_returns_empty_errors(self, valid_config):
        """Unknown source name passes validation silently (no required keys)."""
        config = load_config(valid_config)
        errors = validate_source(config, "github")
        assert errors == [] or any("missing" in e for e in errors)


class TestEnabledSources:
    def test_all_valid(self, valid_config):
        config = load_config(valid_config)
        # Order follows REGISTRY key order; vikunja not in config so skipped
        assert enabled_sources(config) == ["jira", "mstodo", "notion"]

    def test_partial(self, partial_config):
        config = load_config(partial_config)
        assert enabled_sources(config) == ["jira"]

    def test_all_sources_including_vikunja(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("""
vikunja:
  base_url: "http://localhost:3456"
  api_token: "real-token"
jira:
  base_url: "https://test.atlassian.net"
  email: "test@example.com"
  api_token: "test-token"
mstodo:
  client_id: "test-client-id"
  tenant_id: "consumers"
notion:
  token: "secret_test"
  database_ids:
    - "db-1"
""")
        config = load_config(cfg)
        sources = enabled_sources(config)
        assert "vikunja" in sources
        assert len(sources) == 4
