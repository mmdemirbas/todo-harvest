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

    def test_msftodo_push_stub_raises(self):
        with pytest.raises(NotImplementedError, match="not yet implemented for msftodo"):
            REGISTRY["msftodo"].push({}, [])
