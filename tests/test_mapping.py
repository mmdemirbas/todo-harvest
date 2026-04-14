"""Tests for the sync mapping module."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.mapping import SyncMapping


@pytest.fixture
def mapping(tmp_path):
    db_path = tmp_path / "test_mapping.db"
    with SyncMapping(db_path) as m:
        yield m


class TestLocalIdMapping:
    def test_get_local_id_missing(self, mapping):
        assert mapping.get_local_id("jira", "PROJ-1") is None

    def test_upsert_and_get(self, mapping):
        mapping.upsert("lid-1", "jira", "PROJ-1")
        assert mapping.get_local_id("jira", "PROJ-1") == "lid-1"

    def test_get_source_id(self, mapping):
        mapping.upsert("lid-1", "jira", "PROJ-1")
        assert mapping.get_source_id("lid-1", "jira") == "PROJ-1"

    def test_get_source_id_missing(self, mapping):
        assert mapping.get_source_id("lid-999", "jira") is None

    def test_upsert_idempotent(self, mapping):
        mapping.upsert("lid-1", "jira", "PROJ-1", source_updated_at="2024-01-01T00:00:00Z")
        mapping.upsert("lid-1", "jira", "PROJ-1", source_updated_at="2024-02-01T00:00:00Z")
        assert mapping.get_local_id("jira", "PROJ-1") == "lid-1"

    def test_same_local_id_different_sources(self, mapping):
        """One local item can be tracked in multiple sources."""
        mapping.upsert("lid-1", "jira", "PROJ-1")
        mapping.upsert("lid-1", "vikunja", "42")
        assert mapping.get_source_id("lid-1", "jira") == "PROJ-1"
        assert mapping.get_source_id("lid-1", "vikunja") == "42"

    def test_generate_local_id_is_uuid(self, mapping):
        lid = mapping.generate_local_id()
        assert len(lid) == 36  # UUID format
        assert lid.count("-") == 4

    def test_generate_local_id_unique(self, mapping):
        ids = {mapping.generate_local_id() for _ in range(100)}
        assert len(ids) == 100


class TestMarkSynced:
    def test_mark_synced(self, mapping):
        mapping.upsert("lid-1", "jira", "PROJ-1")
        assert mapping.get_last_synced_at("lid-1", "jira") is None
        mapping.mark_synced("lid-1", "jira")
        synced = mapping.get_last_synced_at("lid-1", "jira")
        assert synced is not None
        assert "T" in synced  # ISO format

    def test_mark_synced_no_mapping(self, mapping):
        """Marking a nonexistent mapping does nothing (no error)."""
        mapping.mark_synced("lid-999", "jira")
        assert mapping.get_last_synced_at("lid-999", "jira") is None


class TestConflictResolution:
    def test_equal_values_returns_local(self):
        val, winner = SyncMapping.resolve_conflict(
            "title", "Same", "2024-02-01T00:00:00Z",
            "Same", "2024-03-01T00:00:00Z",
            "2024-01-01T00:00:00Z",
        )
        assert val == "Same"
        assert winner == "local"

    def test_only_local_changed_after_sync(self):
        """Local changed, source didn't → local wins."""
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Local Edit", "2024-03-01T00:00:00Z",
            "Old Source", "2024-01-01T00:00:00Z",
            "2024-02-01T00:00:00Z",
        )
        assert val == "Local Edit"
        assert winner == "local"

    def test_only_source_changed_after_sync(self):
        """Source changed, local didn't → source wins."""
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Old Local", "2024-01-01T00:00:00Z",
            "Source Edit", "2024-03-01T00:00:00Z",
            "2024-02-01T00:00:00Z",
        )
        assert val == "Source Edit"
        assert winner == "source"

    def test_both_changed_source_wins(self):
        """Both changed after last sync → source wins (tie-breaker)."""
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Local Edit", "2024-03-01T00:00:00Z",
            "Source Edit", "2024-03-02T00:00:00Z",
            "2024-02-01T00:00:00Z",
        )
        assert val == "Source Edit"
        assert winner == "source"

    def test_no_timestamps_source_wins(self):
        """No timestamps → source wins (prefer fresh data)."""
        val, winner = SyncMapping.resolve_conflict(
            "status", "todo", None, "done", None, None,
        )
        assert val == "done"
        assert winner == "source"

    def test_no_last_synced_source_wins(self):
        """Has timestamps but no last_synced → source wins."""
        val, winner = SyncMapping.resolve_conflict(
            "priority",
            "low", "2024-01-01T00:00:00Z",
            "high", "2024-02-01T00:00:00Z",
            None,
        )
        assert val == "high"
        assert winner == "source"


class TestSyncLog:
    def test_log_and_retrieve(self, mapping):
        mapping.log_sync("jira", "pull", 42, "test details")
        log = mapping.get_sync_log()
        assert len(log) == 1
        assert log[0]["source"] == "jira"
        assert log[0]["action"] == "pull"
        assert log[0]["item_count"] == 42
        assert log[0]["details"] == "test details"

    def test_log_ordering(self, mapping):
        mapping.log_sync("jira", "pull", 10)
        mapping.log_sync("notion", "pull", 20)
        log = mapping.get_sync_log()
        assert log[0]["source"] == "notion"  # Most recent first
        assert log[1]["source"] == "jira"

    def test_log_limit(self, mapping):
        for i in range(10):
            mapping.log_sync("jira", "pull", i)
        log = mapping.get_sync_log(limit=3)
        assert len(log) == 3


class TestContextManager:
    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "ctx.db"
        with SyncMapping(db_path) as m:
            m.upsert("lid-1", "jira", "PROJ-1")
        # Reopen to verify data was persisted
        with SyncMapping(db_path) as m:
            assert m.get_local_id("jira", "PROJ-1") == "lid-1"
