"""Tests for local state management."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from src.local_state import load_local_state, save_local_state, merge_pulled_items
from src.mapping import SyncMapping


@pytest.fixture
def mapping(tmp_path):
    with SyncMapping(tmp_path / "test.db") as m:
        yield m


def _make_item(source: str, source_id: str, title: str = "Task",
               local_id: str = "", **overrides) -> dict:
    item = {
        "id": f"{source}-{source_id}",
        "local_id": local_id,
        "source": source,
        "title": title,
        "description": None,
        "status": "todo",
        "priority": "none",
        "created_date": "2024-01-01T00:00:00Z",
        "due_date": None,
        "updated_date": "2024-01-01T00:00:00Z",
        "tags": [],
        "url": None,
        "category": {"id": None, "name": None, "type": "other"},
        "raw": {},
    }
    item.update(overrides)
    return item


class TestLoadLocalState:
    def test_missing_file_returns_empty(self, tmp_path):
        result = load_local_state(tmp_path / "nonexistent.json")
        assert result == []

    def test_loads_valid_json(self, tmp_path):
        path = tmp_path / "todos.json"
        items = [_make_item("jira", "PROJ-1", local_id="lid-1")]
        path.write_text(json.dumps(items), encoding="utf-8")
        result = load_local_state(path)
        assert len(result) == 1
        assert result[0]["title"] == "Task"

    def test_non_list_returns_empty(self, tmp_path):
        path = tmp_path / "todos.json"
        path.write_text('{"not": "a list"}', encoding="utf-8")
        result = load_local_state(path)
        assert result == []


class TestSaveLocalState:
    def test_creates_file(self, tmp_path):
        path = tmp_path / "output" / "todos.json"
        items = [_make_item("jira", "PROJ-1", local_id="lid-1")]
        save_local_state(items, path)
        assert path.exists()

    def test_sorted_deterministically(self, tmp_path):
        path = tmp_path / "todos.json"
        items = [
            _make_item("notion", "page-1", local_id="lid-2"),
            _make_item("jira", "PROJ-1", local_id="lid-1"),
        ]
        save_local_state(items, path)
        loaded = json.loads(path.read_text("utf-8"))
        assert loaded[0]["source"] == "jira"
        assert loaded[1]["source"] == "notion"

    def test_idempotent(self, tmp_path):
        path = tmp_path / "todos.json"
        items = [_make_item("jira", "PROJ-1", local_id="lid-1")]
        save_local_state(items, path)
        content1 = path.read_text("utf-8")
        save_local_state(items, path)
        content2 = path.read_text("utf-8")
        assert content1 == content2

    def test_utf8_encoding(self, tmp_path):
        path = tmp_path / "todos.json"
        items = [_make_item("jira", "X-1", title="Ünïcödé 日本語", local_id="lid-1")]
        save_local_state(items, path)
        content = path.read_text("utf-8")
        assert "Ünïcödé" in content
        assert "日本語" in content

    def test_atomic_write_preserves_original_on_crash(self, tmp_path, monkeypatch):
        """If json.dump raises mid-write, the original file stays intact and no temp leaks."""
        path = tmp_path / "todos.json"
        save_local_state(
            [_make_item("jira", "PROJ-1", local_id="lid-1", title="ORIGINAL")],
            path,
        )
        original = path.read_text("utf-8")

        def boom(*args, **kwargs):
            raise OSError("simulated disk full")

        monkeypatch.setattr("src.local_state.json.dump", boom)
        with pytest.raises(OSError):
            save_local_state(
                [_make_item("jira", "PROJ-1", local_id="lid-1", title="REPLACED")],
                path,
            )

        assert path.read_text("utf-8") == original
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f".{path.name}.")]
        assert leftovers == [], f"temp file leaked: {leftovers}"

    def test_non_serializable_value_raises_loudly(self, tmp_path):
        """default=str was removed: any non-JSON-serializable value (e.g. a
        datetime injected by accident) must surface as TypeError instead of
        silently round-tripping as a string and drifting the schema."""
        from datetime import datetime
        path = tmp_path / "todos.json"
        item = _make_item("jira", "PROJ-1", local_id="lid-1")
        item["raw"] = {"injected": datetime(2024, 1, 1)}  # not JSON-serializable
        with pytest.raises(TypeError):
            save_local_state([item], path)
        # No partial file left behind (atomic write semantics)
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f".{path.name}.")]
        assert leftovers == []

    def test_atomic_write_creates_no_temp_on_success(self, tmp_path):
        """Successful write leaves no .tmp sibling behind."""
        path = tmp_path / "todos.json"
        save_local_state(
            [_make_item("jira", "PROJ-1", local_id="lid-1")],
            path,
        )
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f".{path.name}.")]
        assert leftovers == []


class TestMergePulledItems:
    def test_new_item_created(self, mapping):
        pulled = [_make_item("jira", "PROJ-1", title="New Task")]
        local, stats = merge_pulled_items([], pulled, mapping, "jira")
        assert stats["created"] == 1
        assert stats["updated"] == 0
        assert stats["skipped"] == 0
        assert len(local) == 1
        assert local[0]["local_id"] != ""
        # Verify mapping was created
        lid = mapping.get_local_id("jira", "PROJ-1")
        assert lid is not None

    def test_existing_item_skipped_when_unchanged(self, mapping):
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "jira", "PROJ-1",
                       source_updated_at="2024-01-01T00:00:00Z")
        mapping.mark_synced(lid, "jira")

        local_item = _make_item("jira", "PROJ-1", title="Same", local_id=lid)
        pulled_item = _make_item("jira", "PROJ-1", title="Same")

        local, stats = merge_pulled_items([local_item], [pulled_item], mapping, "jira")
        assert stats["skipped"] == 1
        assert stats["updated"] == 0

    def test_existing_item_updated_when_source_changed(self, mapping):
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "jira", "PROJ-1",
                       source_updated_at="2024-01-01T00:00:00Z")

        local_item = _make_item("jira", "PROJ-1", title="Old Title", local_id=lid,
                                updated_date="2024-01-01T00:00:00Z")
        pulled_item = _make_item("jira", "PROJ-1", title="New Title",
                                 updated_date="2024-03-01T00:00:00Z")

        local, stats = merge_pulled_items([local_item], [pulled_item], mapping, "jira")
        assert stats["updated"] == 1
        assert local[0]["title"] == "New Title"

    def test_local_wins_when_local_changed_more_recently(self, mapping):
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "jira", "PROJ-1")
        # Set last_synced_at to a known time BEFORE the local edit
        conn = mapping._connect()
        conn.execute(
            "UPDATE sync_map SET last_synced_at = ? WHERE local_id = ? AND source = ?",
            ("2024-02-01T00:00:00Z", lid, "jira"),
        )
        conn.commit()

        local_item = _make_item("jira", "PROJ-1", title="Local Edit", local_id=lid,
                                updated_date="2024-06-01T00:00:00Z")
        pulled_item = _make_item("jira", "PROJ-1", title="Source Title",
                                 updated_date="2024-01-01T00:00:00Z")

        local, stats = merge_pulled_items([local_item], [pulled_item], mapping, "jira")
        assert local[0]["title"] == "Local Edit"

    def test_multiple_items_mixed(self, mapping):
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "jira", "PROJ-1")

        local_items = [_make_item("jira", "PROJ-1", title="Existing", local_id=lid)]
        pulled_items = [
            _make_item("jira", "PROJ-1", title="Existing"),  # unchanged → skip
            _make_item("jira", "PROJ-2", title="Brand New"),  # new → create
        ]

        local, stats = merge_pulled_items(local_items, pulled_items, mapping, "jira")
        assert stats["created"] == 1
        assert stats["skipped"] == 1
        assert len(local) == 2

    def test_deleted_local_item_readded_on_pull(self, mapping):
        """If local item was removed but mapping exists, re-add it."""
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "jira", "PROJ-1")

        pulled = [_make_item("jira", "PROJ-1", title="Restored")]
        local, stats = merge_pulled_items([], pulled, mapping, "jira")
        assert stats["created"] == 1
        assert local[0]["title"] == "Restored"
        assert local[0]["local_id"] == lid

    def test_conflict_counter_incremented(self, mapping):
        """When source and local differ on a field, conflicts stat counts it."""
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "jira", "PROJ-1")

        local_item = _make_item("jira", "PROJ-1", title="Local Title", local_id=lid,
                                status="todo", priority="low")
        pulled_item = _make_item("jira", "PROJ-1", title="Source Title",
                                 status="done", priority="high")

        local, stats = merge_pulled_items([local_item], [pulled_item], mapping, "jira")
        assert stats["conflicts"] >= 3  # title + status + priority differ
        assert stats["updated"] == 1

    def test_empty_pull_returns_local_unchanged(self, mapping):
        local_items = [_make_item("jira", "PROJ-1", local_id="lid-1")]
        local, stats = merge_pulled_items(local_items, [], mapping, "jira")
        assert stats == {"created": 0, "updated": 0, "skipped": 0, "conflicts": 0}
        assert len(local) == 1

    def test_pull_preserves_items_with_empty_local_id(self, mapping):
        """Hand-edited items with local_id='' must survive a merge cycle."""
        orphan = _make_item("notion", "page-1", title="Hand-edited", local_id="")
        del orphan["local_id"]  # also test fully-missing key
        also_orphan = _make_item("jira", "PROJ-X", title="No id", local_id="")

        pulled = [_make_item("vikunja", "1", title="From source")]
        local, _ = merge_pulled_items(
            [orphan, also_orphan], pulled, mapping, "vikunja",
        )

        titles = {item.get("title") for item in local}
        assert "Hand-edited" in titles
        assert "No id" in titles
        assert "From source" in titles

    def test_pull_preserves_items_from_other_sources(self, mapping):
        """Pulling jira items must not lose existing notion items in local state."""
        notion_item = _make_item("notion", "page-1", title="Notion Task", local_id="lid-notion")
        jira_pulled = [_make_item("jira", "PROJ-1", title="Jira Task")]

        local, stats = merge_pulled_items([notion_item], jira_pulled, mapping, "jira")
        assert stats["created"] == 1
        sources = {item["source"] for item in local}
        assert "notion" in sources
        assert "jira" in sources
        assert len(local) == 2

    def test_merge_writes_atomically_per_pull(self, tmp_path, monkeypatch):
        """If merge raises mid-batch, no mapping rows survive — full rollback."""
        from src.mapping import SyncMapping
        db = tmp_path / "rollback.db"
        with SyncMapping(db) as m:
            pulled = [
                _make_item("jira", "PROJ-1"),
                _make_item("jira", "PROJ-2"),
                _make_item("jira", "PROJ-3"),
            ]
            # Make the third upsert blow up
            calls = {"n": 0}
            real_upsert = m.upsert

            def boom(*args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise RuntimeError("simulated DB error mid-merge")
                return real_upsert(*args, **kwargs)

            monkeypatch.setattr(m, "upsert", boom)
            with pytest.raises(RuntimeError):
                merge_pulled_items([], pulled, m, "jira")

        # Reopen and assert nothing committed
        with SyncMapping(db) as m2:
            assert m2.get_local_id("jira", "PROJ-1") is None
            assert m2.get_local_id("jira", "PROJ-2") is None
            assert m2.get_local_id("jira", "PROJ-3") is None

    def test_completed_date_propagates_from_source(self, mapping):
        """Source completing a task must update local completed_date — was missing from _MERGE_FIELDS."""
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "vikunja", "1", source_updated_at="2024-01-01T00:00:00Z")
        mapping.mark_synced(lid, "vikunja")

        local_item = _make_item(
            "vikunja", "1", local_id=lid, status="todo",
            updated_date="2024-01-01T00:00:00Z",
        )
        local_item["completed_date"] = None

        pulled = _make_item(
            "vikunja", "1", status="done",
            updated_date="2024-02-01T00:00:00Z",
        )
        pulled["completed_date"] = "2024-02-01T10:00:00Z"

        local, stats = merge_pulled_items([local_item], [pulled], mapping, "vikunja")
        assert stats["updated"] == 1
        assert local[0]["status"] == "done"
        assert local[0]["completed_date"] == "2024-02-01T10:00:00Z"

    def test_category_propagates_from_source(self, mapping):
        """Source moving a task to a new project must update local category."""
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "vikunja", "1", source_updated_at="2024-01-01T00:00:00Z")
        mapping.mark_synced(lid, "vikunja")

        local_item = _make_item(
            "vikunja", "1", local_id=lid,
            updated_date="2024-01-01T00:00:00Z",
        )
        local_item["category"] = {"id": "1", "name": "OldProj", "type": "project"}

        pulled = _make_item(
            "vikunja", "1",
            updated_date="2024-02-01T00:00:00Z",
        )
        pulled["category"] = {"id": "2", "name": "NewProj", "type": "project"}

        local, stats = merge_pulled_items([local_item], [pulled], mapping, "vikunja")
        assert stats["updated"] == 1
        assert local[0]["category"]["name"] == "NewProj"

    def test_updated_date_reflects_source_after_merge(self, mapping):
        """After source-wins merge, local updated_date must reflect source — feeds next conflict cycle correctly."""
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "vikunja", "1", source_updated_at="2024-01-01T00:00:00Z")
        mapping.mark_synced(lid, "vikunja")

        local_item = _make_item(
            "vikunja", "1", title="Old", local_id=lid,
            updated_date="2024-01-01T00:00:00Z",
        )
        pulled = _make_item(
            "vikunja", "1", title="New",
            updated_date="2024-02-15T00:00:00Z",
        )

        local, _ = merge_pulled_items([local_item], [pulled], mapping, "vikunja")
        assert local[0]["updated_date"] == "2024-02-15T00:00:00Z"

    def test_local_wins_preserves_local_updated_date(self, mapping):
        """When local wins a field conflict, local_item.updated_date must NOT
        be overwritten by source's older value — otherwise next pull would see
        local as 'unchanged since sync' and silently revert the local edit."""
        lid = mapping.generate_local_id()
        mapping.upsert(
            lid, "vikunja", "1",
            source_updated_at="2024-01-01T09:00:00Z",
            local_updated_at="2024-01-01T09:00:00Z",
        )
        conn = mapping._connect()
        conn.execute(
            "UPDATE sync_map SET last_synced_at = ? WHERE local_id = ? AND source = ?",
            ("2024-01-01T10:00:00Z", lid, "vikunja"),
        )
        conn.commit()

        local_item = _make_item(
            "vikunja", "1", title="LocalEdit", local_id=lid,
            updated_date="2024-01-01T11:00:00Z",  # post-sync local edit
        )
        pulled = _make_item(
            "vikunja", "1", title="OldSourceTitle",
            updated_date="2024-01-01T09:00:00Z",  # source unchanged
        )

        local, _ = merge_pulled_items([local_item], [pulled], mapping, "vikunja")

        assert local[0]["title"] == "LocalEdit"
        # The fix: in-item updated_date must stay at the local edit time.
        # The next pull re-reads this from todos.json and feeds it to
        # resolve_conflict — overwriting it here would silently flip future
        # cycles to source-wins.
        assert local[0]["updated_date"] == "2024-01-01T11:00:00Z"

    def test_per_field_diff_preserves_independent_local_and_source_edits(self, mapping):
        """The original bug: timestamp-only resolution declared all fields
        'both changed' if both sides had any edit. Now a snapshot lets us
        diff per-field — local-only edits and source-only edits both survive.

        T0: pull. snapshot stored.
        T1: user edits title locally only.
        T2: source changes priority only.
        T3: pull. Title must stay local; priority must adopt source.
        """
        # T0 baseline pull
        first_pulled = [_make_item(
            "vikunja", "1",
            title="Original", local_id="",
            updated_date="2024-01-01T09:00:00Z",
        )]
        first_pulled[0]["priority"] = "low"
        local, _ = merge_pulled_items([], first_pulled, mapping, "vikunja")
        assert local[0]["title"] == "Original"
        lid = local[0]["local_id"]

        # T1 user edits title locally
        local[0]["title"] = "MyEdit"
        # T2 source independently changes priority
        second_pulled = [_make_item(
            "vikunja", "1",
            title="Original",  # source's title unchanged
            local_id="",
            updated_date="2024-02-01T09:00:00Z",  # source's overall timestamp advanced
        )]
        second_pulled[0]["priority"] = "high"  # source-only change

        # T3 pull
        local, _ = merge_pulled_items(local, second_pulled, mapping, "vikunja")
        item = local[0]
        # Per-field correctness:
        assert item["title"] == "MyEdit", "local-only title edit must survive"
        assert item["priority"] == "high", "source-only priority change must apply"

    def test_per_field_diff_source_wins_on_real_field_conflict(self, mapping):
        """When BOTH sides edit the same field, source still wins (policy)."""
        first_pulled = [_make_item(
            "vikunja", "1", title="Original", local_id="",
            updated_date="2024-01-01T09:00:00Z",
        )]
        local, _ = merge_pulled_items([], first_pulled, mapping, "vikunja")
        local[0]["title"] = "LocalEdit"

        second_pulled = [_make_item(
            "vikunja", "1", title="SourceEdit", local_id="",
            updated_date="2024-02-01T09:00:00Z",
        )]
        local, _ = merge_pulled_items(local, second_pulled, mapping, "vikunja")
        assert local[0]["title"] == "SourceEdit"

    def test_no_winners_advances_updated_date_to_source(self, mapping):
        """When source wins (or no real conflict), in-item updated_date
        adopts source's — needed so the next cycle's last_synced comparison
        works correctly."""
        lid = mapping.generate_local_id()
        mapping.upsert(lid, "vikunja", "1", source_updated_at="2024-01-01T00:00:00Z")
        mapping.mark_synced(lid, "vikunja")

        local_item = _make_item(
            "vikunja", "1", title="Old", local_id=lid,
            updated_date="2024-01-01T00:00:00Z",
        )
        pulled = _make_item(
            "vikunja", "1", title="New",  # source changed
            updated_date="2024-02-15T00:00:00Z",
        )
        local, _ = merge_pulled_items([local_item], [pulled], mapping, "vikunja")
        assert local[0]["title"] == "New"  # source won
        assert local[0]["updated_date"] == "2024-02-15T00:00:00Z"

    def test_corrupt_json_raises(self, tmp_path):
        """Corrupt state file must not be silently swallowed."""
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_local_state(path)
