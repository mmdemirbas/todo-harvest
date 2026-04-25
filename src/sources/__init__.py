"""Source registry for todo-harvest.

Each source module exposes:
- pull(config, console) -> list[dict]   — fetch raw API payloads
- push(config, tasks, console) -> dict  — write tasks to service (or NotImplementedError)

Normalization functions (normalize_vikunja, normalize_jira, etc.) live in
src/normalizer.py and are dispatched through SourceDef.normalize().

To add a new source: create the module, add a normalize function to
normalizer.py, then add one entry to REGISTRY below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any
    from src.schema import NormalizedItem


class SourceDef:
    """Lazy-loaded source definition — avoids importing all sources at import time."""

    def __init__(
        self,
        module_path: str,
        normalize_module: str,
        normalize_fn: str,
        required_keys: list[str],
        push_supported: bool = True,
    ):
        self._module_path = module_path
        self._normalize_module = normalize_module
        self._normalize_fn = normalize_fn
        self.required_keys = required_keys
        self.push_supported = push_supported
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

    def pull(self, config: dict, console: Any = None) -> list[dict]:
        mod = self._load()
        return mod.pull(config, console)

    def push(
        self,
        config: dict,
        tasks: list[dict],
        console: Any = None,
        mapping: Any = None,
    ) -> dict:
        mod = self._load()
        try:
            return mod.push(config, tasks, console, mapping=mapping)
        except TypeError:
            # Backwards-compat: source's push() doesn't accept mapping
            return mod.push(config, tasks, console)

    def normalize(self, raw: dict, source_config: dict | None = None) -> NormalizedItem:
        mod = self._load_normalizer()
        return getattr(mod, self._normalize_fn)(raw, source_config or {})

    def migrate(self, mapping: Any, raw_items: list[dict]) -> None:
        """Apply source-specific mapping-table migrations (legacy id formats etc).

        No-op when the source module defines no `migrate_legacy_mappings`.
        """
        mod = self._load()
        fn = getattr(mod, "migrate_legacy_mappings", None)
        if fn is not None:
            fn(mapping, raw_items)


# The single source of truth for available sources.
# To add a new source: add one entry here + create the module + add normalize function.
REGISTRY: dict[str, SourceDef] = {
    "vikunja": SourceDef(
        module_path="src.sources.vikunja",
        normalize_module="src.normalizer",
        normalize_fn="normalize_vikunja",
        required_keys=["base_url", "api_token"],
        push_supported=True,
    ),
    "jira": SourceDef(
        module_path="src.sources.jira",
        normalize_module="src.normalizer",
        normalize_fn="normalize_jira",
        required_keys=["base_url", "email", "api_token"],
        push_supported=False,  # stub only
    ),
    "mstodo": SourceDef(
        module_path="src.sources.mstodo",
        normalize_module="src.normalizer",
        normalize_fn="normalize_mstodo",
        required_keys=["client_id", "tenant_id"],
        push_supported=False,  # stub only
    ),
    "notion": SourceDef(
        module_path="src.sources.notion",
        normalize_module="src.normalizer",
        normalize_fn="normalize_notion",
        required_keys=["token", "database_ids"],
        push_supported=False,
    ),
    "plane": SourceDef(
        module_path="src.sources.plane",
        normalize_module="src.normalizer",
        normalize_fn="normalize_plane",
        required_keys=["base_url", "api_token", "workspace_slug"],
        push_supported=True,
    ),
}

SOURCE_NAMES: tuple[str, ...] = tuple(REGISTRY.keys())
