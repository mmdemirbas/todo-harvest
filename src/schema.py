"""Unified schema for normalized TODO items.

TypedDict definitions that enforce the contract between normalizers,
local state, mapping, and CLI at type-check time.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Category(TypedDict):
    id: str | None
    name: str | None
    type: str  # "list" | "epic" | "project" | "database" | "label" | "other"


class NormalizedItem(TypedDict):
    id: str              # "{source}-{source_id}"
    local_id: str        # stable UUID, assigned on first pull
    source: str          # "vikunja" | "mstodo" | "jira" | "notion" | "plane"
    title: str
    description: str | None
    status: str          # "todo" | "in_progress" | "done" | "cancelled"
    priority: str        # "critical" | "high" | "medium" | "low" | "none"
    created_date: str | None
    due_date: str | None
    updated_date: str | None
    completed_date: str | None
    tags: list[str]
    url: str | None
    category: Category
    raw: dict[str, Any]


class PushResult(TypedDict):
    created: int
    updated: int
    skipped: int


class MergeStats(TypedDict):
    created: int
    updated: int
    skipped: int
    conflicts: int


# Canonical field order for CSV export — derived from NormalizedItem keys,
# with category flattened and raw excluded.
CSV_COLUMNS: list[str] = [
    "id",
    "local_id",
    "source",
    "title",
    "description",
    "status",
    "priority",
    "created_date",
    "due_date",
    "updated_date",
    "completed_date",
    "tags",
    "url",
    "category_id",
    "category_name",
    "category_type",
]

VALID_STATUSES = {"todo", "in_progress", "done", "cancelled"}
VALID_PRIORITIES = {"critical", "high", "medium", "low", "none"}
VALID_CATEGORY_TYPES = {"list", "epic", "project", "database", "label", "other"}
