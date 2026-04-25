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

    def test_neither_side_changed_after_sync_source_wins(self):
        """Both timestamps before last_synced, values differ → source wins."""
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Old Local", "2024-01-01T00:00:00Z",
            "Old Source", "2024-01-15T00:00:00Z",
            "2024-06-01T00:00:00Z",  # last synced well after both
        )
        assert val == "Old Source"
        assert winner == "source"

    def test_mixed_iso_formats_for_same_instant_treated_equal(self):
        """Jira (+0000) and Vikunja (Z) for the same instant must not trigger spurious local-wins."""
        # Same instant: 2024-02-01T00:00:00 UTC
        # last_synced exactly matches both — neither changed → source wins (fall-through)
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Local", "2024-02-01T00:00:00Z",
            "Source", "2024-02-01T00:00:00.000+0000",
            "2024-02-01T00:00:00+00:00",
        )
        assert val == "Source"
        assert winner == "source"

    def test_naive_timestamp_treated_as_utc(self):
        """MS Todo emits naive timestamps; parser treats as UTC and avoids aware-vs-naive crash.

        Source unchanged (before last_synced), local changed after — local must win.
        """
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Local", "2024-02-15T10:00:00",  # naive (MS Todo) — assumed UTC
            "Source", "2024-01-01T00:00:00Z",  # before last_synced → unchanged
            "2024-02-01T00:00:00Z",
        )
        assert val == "Local"
        assert winner == "local"

    def test_seven_digit_fractional_seconds(self):
        """MS Graph emits 7-digit fractional seconds; parser truncates, doesn't crash."""
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Local", "2024-02-15T10:00:00.1234567",
            "Source", "2024-01-01T00:00:00.0000000Z",
            "2024-02-01T00:00:00Z",
        )
        assert val == "Local"
        assert winner == "local"

    def test_malformed_timestamps_fall_through_to_source(self):
        """Garbage timestamps → source wins (don't crash, don't lex-compare)."""
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Local", "not-a-date",
            "Source", "also garbage",
            "2024-02-01T00:00:00Z",
        )
        assert val == "Source"

    def test_lexicographic_format_quirk_no_longer_breaks_comparison(self):
        """Regression: '2024-01-15T10:30:00Z' lex-compared to '2024-01-15T10:30:00.000+0000'
        previously gave wrong sort because '.' < 'Z'. Both represent same instant; should
        not detect a local change."""
        val, winner = SyncMapping.resolve_conflict(
            "title",
            "Same", "2024-01-15T10:30:00Z",
            "Same", "2024-01-15T10:30:00.000+0000",
            "2024-01-10T00:00:00Z",
        )
        # Equal values short-circuit early; this asserts no exception either way.
        assert val == "Same"

    def test_upsert_changes_local_id_on_remap(self, mapping):
        """Re-mapping a (source, source_id) to a new local_id works."""
        mapping.upsert("lid-1", "jira", "PROJ-1")
        assert mapping.get_local_id("jira", "PROJ-1") == "lid-1"
        mapping.upsert("lid-2", "jira", "PROJ-1")
        assert mapping.get_local_id("jira", "PROJ-1") == "lid-2"


class TestTransaction:
    def test_writes_visible_within_block(self, mapping):
        with mapping.transaction():
            mapping.upsert("lid-1", "jira", "PROJ-1")
            assert mapping.get_local_id("jira", "PROJ-1") == "lid-1"

    def test_committed_after_block_exits(self, tmp_path):
        db = tmp_path / "txn.db"
        with SyncMapping(db) as m:
            with m.transaction():
                m.upsert("lid-1", "jira", "PROJ-1")
        with SyncMapping(db) as m2:
            assert m2.get_local_id("jira", "PROJ-1") == "lid-1"

    def test_rolls_back_on_exception(self, tmp_path):
        db = tmp_path / "txn.db"
        with SyncMapping(db) as m:
            m.upsert("lid-stable", "jira", "PROJ-Z")  # committed pre-block
            with pytest.raises(RuntimeError):
                with m.transaction():
                    m.upsert("lid-1", "jira", "PROJ-1")
                    m.upsert("lid-2", "jira", "PROJ-2")
                    raise RuntimeError("boom")
            assert m.get_local_id("jira", "PROJ-1") is None
            assert m.get_local_id("jira", "PROJ-2") is None
            assert m.get_local_id("jira", "PROJ-Z") == "lid-stable"

    def test_reentrant_transactions_dont_double_commit(self, mapping):
        """Inner transaction is a no-op; outer governs commit/rollback."""
        with mapping.transaction():
            mapping.upsert("lid-1", "jira", "PROJ-1")
            with mapping.transaction():
                mapping.upsert("lid-2", "jira", "PROJ-2")
        assert mapping.get_local_id("jira", "PROJ-1") == "lid-1"
        assert mapping.get_local_id("jira", "PROJ-2") == "lid-2"

    def test_inner_exception_rolls_back_outer_too(self, tmp_path):
        """Inner re-entrant transaction is a no-op, so an exception inside it
        propagates and the outer block rolls back everything."""
        db = tmp_path / "txn.db"
        with SyncMapping(db) as m:
            with pytest.raises(RuntimeError):
                with m.transaction():
                    m.upsert("lid-1", "jira", "PROJ-1")
                    with m.transaction():
                        m.upsert("lid-2", "jira", "PROJ-2")
                        raise RuntimeError("boom inner")
            assert m.get_local_id("jira", "PROJ-1") is None
            assert m.get_local_id("jira", "PROJ-2") is None


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
