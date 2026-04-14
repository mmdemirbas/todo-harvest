"""Source registry for todo-harvest.

Each source module exposes:
- fetch_all(config, console) -> list[dict]  — raw API payloads
- normalize(raw) -> NormalizedItem           — unified schema
- REQUIRED_CONFIG_KEYS: list[str]            — keys needed in config.yaml
- AuthError, FetchError                      — exception classes

To add a new source: create the module, then add one entry to REGISTRY below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable
    from rich.console import Console
    from src.schema import NormalizedItem


class SourceDef:
    """Lazy-loaded source definition — avoids importing all sources at import time."""

    def __init__(
        self,
        module_path: str,
        normalize_module: str,
        normalize_fn: str,
        required_keys: list[str],
    ):
        self._module_path = module_path
        self._normalize_module = normalize_module
        self._normalize_fn = normalize_fn
        self.required_keys = required_keys
        self._module = None
        self._norm_module = None

    def _load(self):
        if self._module is None:
            import importlib
            self._module = importlib.import_module(self._module_path)
        return self._module

    def _load_normalizer(self):
        if self._norm_module is None:
            import importlib
            self._norm_module = importlib.import_module(self._normalize_module)
        return self._norm_module

    def fetch_all(self, config: dict, console: Any = None) -> list[dict]:
        mod = self._load()
        return mod.fetch_all(config, console)

    def normalize(self, raw: dict) -> NormalizedItem:
        mod = self._load_normalizer()
        return getattr(mod, self._normalize_fn)(raw)



# The single source of truth for available sources.
# To add a new source: add one entry here + create the module.
REGISTRY: dict[str, SourceDef] = {
    "msftodo": SourceDef(
        module_path="src.sources.msftodo",
        normalize_module="src.normalizer",
        normalize_fn="normalize_msftodo",
        required_keys=["client_id", "tenant_id"],
    ),
    "jira": SourceDef(
        module_path="src.sources.jira",
        normalize_module="src.normalizer",
        normalize_fn="normalize_jira",
        required_keys=["base_url", "email", "api_token"],
    ),
    "notion": SourceDef(
        module_path="src.sources.notion",
        normalize_module="src.normalizer",
        normalize_fn="normalize_notion",
        required_keys=["token", "database_ids"],
    ),
}

SOURCE_NAMES: tuple[str, ...] = tuple(REGISTRY.keys())
