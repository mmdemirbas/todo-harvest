"""Tests for the source registry."""

from __future__ import annotations

import pytest
from src.sources import REGISTRY, SOURCE_NAMES


class TestRegistryConsistency:
    def test_source_names_matches_registry_keys(self):
        assert set(SOURCE_NAMES) == set(REGISTRY.keys())

    def test_all_sources_have_required_keys(self):
        for name, source_def in REGISTRY.items():
            assert isinstance(source_def.required_keys, list), f"{name} missing required_keys"
            assert len(source_def.required_keys) > 0, f"{name} has empty required_keys"

    def test_vikunja_is_push_supported(self):
        assert REGISTRY["vikunja"].push_supported is True

    def test_notion_is_not_push_supported(self):
        assert REGISTRY["notion"].push_supported is False

    def test_jira_push_stub_raises(self):
        with pytest.raises(NotImplementedError, match="not yet implemented for jira"):
            REGISTRY["jira"].push({}, [])

    def test_notion_push_stub_raises(self):
        with pytest.raises(NotImplementedError, match="pull-only"):
            REGISTRY["notion"].push({}, [])

    def test_mstodo_push_stub_raises(self):
        with pytest.raises(NotImplementedError, match="not yet implemented for mstodo"):
            REGISTRY["mstodo"].push({}, [])


class TestPushSignatureDispatch:
    def test_mapping_kwarg_passed_when_push_accepts_it(self, monkeypatch):
        """SourceDef.push must inspect the signature, not catch TypeError —
        otherwise unrelated TypeErrors inside push silently retry without
        the mapping argument."""
        from src.sources import SourceDef
        import types

        captured = {}

        def fake_push(config, tasks, console=None, mapping=None):
            captured["mapping"] = mapping
            return {"created": 0, "updated": 0, "skipped": 0}

        sd = SourceDef("dummy", "dummy", "dummy_norm", required_keys=["x"])
        fake_mod = types.SimpleNamespace(push=fake_push)
        sd._module = fake_mod  # bypass _load
        sentinel = object()
        sd.push({}, [], mapping=sentinel)
        assert captured["mapping"] is sentinel

    def test_mapping_kwarg_dropped_when_push_doesnt_accept_it(self):
        """Backwards-compat: a push() without 'mapping' is called without it,
        with no TypeError leakage."""
        from src.sources import SourceDef
        import types

        def legacy_push(config, tasks, console=None):
            return {"created": 1, "updated": 0, "skipped": 0}

        sd = SourceDef("dummy", "dummy", "dummy_norm", required_keys=["x"])
        sd._module = types.SimpleNamespace(push=legacy_push)
        result = sd.push({}, [], mapping="should-be-dropped")
        assert result["created"] == 1

    def test_typeerror_inside_push_propagates(self):
        """A real TypeError raised by push() must NOT be swallowed by the
        backwards-compat path."""
        from src.sources import SourceDef
        import types

        def buggy_push(config, tasks, console=None, mapping=None):
            raise TypeError("internal bug — wrong argument type used")

        sd = SourceDef("dummy", "dummy", "dummy_norm", required_keys=["x"])
        sd._module = types.SimpleNamespace(push=buggy_push)
        with pytest.raises(TypeError, match="internal bug"):
            sd.push({}, [], mapping=None)
