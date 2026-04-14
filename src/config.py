"""Load and validate config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_OUTPUT_DIR = "./output"

SOURCES = ("msftodo", "jira", "notion")

REQUIRED_KEYS = {
    "msftodo": ["client_id", "tenant_id"],
    "jira": ["base_url", "email", "api_token"],
    "notion": ["token", "database_ids"],
}


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""


def load_config(path: Path | None = None) -> dict:
    """Load config.yaml from the given path, or the default location.

    Returns the parsed config dict with defaults applied.
    Raises ConfigError with a human-readable message on problems.
    """
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"Config file not found: {path}\n"
            "Copy config.example.yaml to config.yaml and fill in your credentials."
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a YAML mapping, got {type(raw).__name__}")

    # Apply defaults
    output_cfg = raw.get("output", {})
    if not isinstance(output_cfg, dict):
        raise ConfigError("'output' must be a mapping")
    raw["output"] = {"dir": output_cfg.get("dir", DEFAULT_OUTPUT_DIR)}

    return raw


def validate_source(config: dict, source: str) -> list[str]:
    """Validate that all required keys for a source are present and non-empty.

    Returns a list of error messages (empty if valid).
    """
    errors = []
    section = config.get(source)
    if section is None:
        errors.append(f"Section '{source}' is missing from config.yaml")
        return errors

    if not isinstance(section, dict):
        errors.append(f"Section '{source}' must be a mapping, got {type(section).__name__}")
        return errors

    list_keys = {"database_ids"}

    for key in REQUIRED_KEYS.get(source, []):
        val = section.get(key)
        if val is None:
            errors.append(f"'{source}.{key}' is missing in config.yaml")
        elif key in list_keys:
            if not isinstance(val, list):
                errors.append(f"'{source}.{key}' must be a list in config.yaml")
            elif len(val) == 0:
                errors.append(f"'{source}.{key}' is an empty list in config.yaml")
        else:
            if not isinstance(val, str):
                errors.append(
                    f"'{source}.{key}' must be a string (use quotes around the value)"
                )
            elif not val.strip():
                errors.append(f"'{source}.{key}' is empty in config.yaml")
            elif _is_placeholder(val):
                errors.append(
                    f"'{source}.{key}' looks like a placeholder — "
                    "replace it with your actual credential"
                )

    return errors


_PLACEHOLDER_PREFIXES = ("YOUR_", "DATABASE_ID", "CHANGE_ME", "TODO", "FIXME")


def _is_placeholder(val: str) -> bool:
    """Detect common placeholder values left over from config.example.yaml."""
    upper = val.strip().upper()
    return any(upper.startswith(p) for p in _PLACEHOLDER_PREFIXES)


def enabled_sources(config: dict) -> list[str]:
    """Return the list of sources that are present and have all required keys."""
    return [s for s in SOURCES if not validate_source(config, s)]
