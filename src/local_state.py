"""Local state management — todos.json as the source of truth.

Reads, writes, and merges normalized items into the local state file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.mapping import SyncMapping
from src.schema import MergeStats, NormalizedItem


DEFAULT_STATE_PATH = Path("todos.json")


def _sort_key(item: dict) -> tuple:
    return (item.get("source", ""), item.get("id", ""))


def load_local_state(path: Path = DEFAULT_STATE_PATH) -> list[dict]:
    """Read todos.json. Return [] if file doesn't exist."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


def save_local_state(items: list[dict], path: Path = DEFAULT_STATE_PATH) -> None:
    """Write todos.json sorted deterministically by (source, id), atomically.

    Writes to a sibling temp file then os.replace's into place so a crash mid-
    write leaves the previous file intact rather than truncating it.
    """
    sorted_items = sorted(items, key=_sort_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sorted_items, f, indent=2, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def merge_pulled_items(
    local_items: list[dict],
    pulled_items: list[dict],
    mapping: SyncMapping,
    source: str,
) -> tuple[list[dict], MergeStats]:
    """Merge pulled items into local state using conflict resolution.

    For each pulled item:
    - If no local_id mapping exists: assign local_id, add to local state (created).
    - If mapping exists and local item found: resolve field-by-field conflicts (updated/skipped).
    - If mapping exists but local item missing: re-add to local state (created).

    Returns (updated_local_items, stats).
    """
    stats: MergeStats = {"created": 0, "updated": 0, "skipped": 0, "conflicts": 0}

    # Index local items by local_id for O(1) lookup. Items missing a local_id
    # (hand-edited, imported, malformed) are preserved verbatim so a merge
    # cycle never silently deletes them.
    local_by_id: dict[str, dict] = {}
    orphans_no_id: list[dict] = []
    for item in local_items:
        lid = item.get("local_id")
        if lid:
            local_by_id[lid] = item
        else:
            orphans_no_id.append(item)

    source_prefix = f"{source}-"
    # Batch all per-item mapping writes into one SQLite commit instead of
    # 2-3 per item. For 1000 items this is the difference between ~3000 fsyncs
    # and 1, and rolls back cleanly if any item raises mid-merge.
    with mapping.transaction():
        for pulled in pulled_items:
            # Strip source prefix so mapping stores the raw external ID
            # (e.g. "1", not "vikunja-1") — push round-trips via the source API.
            normalized_id = pulled["id"]
            source_id = (
                normalized_id[len(source_prefix):]
                if normalized_id.startswith(source_prefix)
                else normalized_id
            )
            local_id = mapping.get_local_id(source, source_id)

            if local_id is None:
                # New item — assign local_id, add to local state
                local_id = mapping.generate_local_id()
                pulled["local_id"] = local_id
                mapping.upsert(
                    local_id, source, source_id,
                    source_updated_at=pulled.get("updated_date"),
                    local_updated_at=pulled.get("updated_date"),
                )
                mapping.mark_synced(local_id, source)
                local_by_id[local_id] = pulled
                stats["created"] += 1
            else:
                # Existing item — resolve conflicts field by field
                pulled["local_id"] = local_id
                local_item = local_by_id.get(local_id)

                if local_item is None:
                    # Mapping exists but local item was deleted — re-add
                    mapping.upsert(
                        local_id, source, source_id,
                        source_updated_at=pulled.get("updated_date"),
                        local_updated_at=pulled.get("updated_date"),
                    )
                    mapping.mark_synced(local_id, source)
                    local_by_id[local_id] = pulled
                    stats["created"] += 1
                else:
                    # Merge fields
                    changed, field_conflicts = _merge_fields(local_item, pulled, mapping, local_id, source)
                    stats["conflicts"] += field_conflicts
                    if changed:
                        mapping.upsert(
                            local_id, source, source_id,
                            source_updated_at=pulled.get("updated_date"),
                            local_updated_at=local_item.get("updated_date"),
                        )
                        mapping.mark_synced(local_id, source)
                        stats["updated"] += 1
                    else:
                        mapping.mark_synced(local_id, source)
                        stats["skipped"] += 1

    return list(local_by_id.values()) + orphans_no_id, stats


# User-mutable fields that participate in conflict resolution during merge.
# Local edits are preserved per resolve_conflict's policy.
_MERGE_FIELDS = ("title", "description", "status", "priority", "due_date", "tags")

# Source-owned metadata: copied straight from the pulled item. The local copy
# cannot legitimately diverge from source for these (they're set by the remote
# system on its own clock), so source always wins.
_SOURCE_AUTHORITATIVE_FIELDS = (
    "created_date",
    "updated_date",
    "completed_date",
    "category",
    "raw",
    "url",
)


def _merge_fields(
    local_item: dict,
    pulled_item: dict,
    mapping: SyncMapping,
    local_id: str,
    source: str,
) -> tuple[bool, int]:
    """Merge individual fields from pulled_item into local_item.

    Returns (changed, conflict_count).
    A conflict is when both local and source differ and resolution picks a winner.
    """
    last_synced = mapping.get_last_synced_at(local_id, source)
    changed = False
    conflicts = 0

    for field in _MERGE_FIELDS:
        local_val = local_item.get(field)
        source_val = pulled_item.get(field)

        if local_val == source_val:
            continue

        winner_val, winner = mapping.resolve_conflict(
            field,
            local_val, local_item.get("updated_date"),
            source_val, pulled_item.get("updated_date"),
            last_synced,
        )

        # Count as conflict whenever values differ (resolution was needed)
        conflicts += 1

        if winner_val != local_val:
            local_item[field] = winner_val
            changed = True

    for field in _SOURCE_AUTHORITATIVE_FIELDS:
        if field not in pulled_item:
            continue
        new_val = pulled_item.get(field)
        if new_val != local_item.get(field):
            local_item[field] = new_val
            changed = True

    return changed, conflicts
