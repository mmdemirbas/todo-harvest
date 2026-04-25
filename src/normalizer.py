"""Normalize raw payloads from each source into the unified TODO schema.

All functions here are pure — no I/O, no side effects.
"""

from __future__ import annotations

import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags, collapse whitespace."""
    cleaned = _HTML_TAG_RE.sub("", text)
    return " ".join(cleaned.split())


def normalize(source: str, raw: dict, source_config: dict | None = None) -> dict:
    """Dispatch to the correct normalizer based on source name."""
    from src.sources import REGISTRY
    source_def = REGISTRY.get(source)
    if source_def is None:
        raise ValueError(f"Unknown source: {source}")
    return source_def.normalize(raw, source_config or {})


# ---------------------------------------------------------------------------
# Vikunja
# ---------------------------------------------------------------------------

_VIKUNJA_PRIORITY_MAP = {
    0: "none",
    1: "low",
    2: "medium",
    3: "high",
    4: "critical",
}


def normalize_vikunja(raw: dict, source_config: dict | None = None) -> dict:
    cfg = source_config or {}
    task_id = raw.get("id", "")

    # Status: Vikunja uses a 'done' boolean
    done = raw.get("done", False)
    status = "done" if done else "todo"

    # Priority: Vikunja uses 0-4 integer
    priority_int = raw.get("priority", 0)
    priority = _VIKUNJA_PRIORITY_MAP.get(priority_int, "none")

    # Description
    description = raw.get("description") or None

    # Due date
    due_date = raw.get("due_date")
    if due_date == "0001-01-01T00:00:00Z":
        due_date = None

    # Tags from labels — sorted for stable comparison across pulls
    labels = raw.get("labels") or []
    tags = sorted({label.get("title", "") for label in labels if label.get("title")})

    # URL
    url = None

    # Category — project
    category = {
        "id": str(raw.get("_project_id", "")),
        "name": raw.get("_project_title"),
        "type": "project",
    }

    # Completed date (Vikunja sets done_at when 'done' toggles true)
    done_at = raw.get("done_at")
    if done_at == "0001-01-01T00:00:00Z":
        done_at = None

    return {
        "id": f"vikunja-{task_id}",
        "local_id": "",  # assigned by merge_pulled_items
        "source": "vikunja",
        "title": raw.get("title", ""),
        "description": description,
        "status": status,
        "priority": priority,
        "created_date": raw.get("created"),
        "due_date": due_date,
        "updated_date": raw.get("updated"),
        "completed_date": done_at,
        "tags": tags,
        "url": url,
        "category": category,
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------

_JIRA_STATUS_MAP = {
    "new": "todo",
    "indeterminate": "in_progress",
    "done": "done",
}

_JIRA_PRIORITY_MAP = {
    "highest": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "lowest": "low",
}

# Jira Classic "Epic Link" custom field. Next-gen (team-managed) projects
# use parent/child hierarchy instead and this field does not exist.
_JIRA_EPIC_LINK_FIELD = "customfield_10014"


def normalize_jira(raw: dict, source_config: dict | None = None) -> dict:
    cfg = source_config or {}
    custom_status_map = cfg.get("status_map", {})
    custom_priority_map = cfg.get("priority_map", {})

    fields = raw.get("fields", {})
    key = raw.get("key", raw.get("id", ""))

    # Status — config status_map overrides, then category-based fallback
    status_name = (fields.get("status") or {}).get("name", "")
    if status_name in custom_status_map:
        status = custom_status_map[status_name]
    else:
        status_cat = (fields.get("status") or {}).get("statusCategory", {}).get("key", "")
        status = _JIRA_STATUS_MAP.get(status_cat, "todo")
        if "cancel" in status_name.lower():
            status = "cancelled"

    # Priority — config priority_map overrides, then built-in fallback
    priority_raw = (fields.get("priority") or {}).get("name", "")
    if priority_raw in custom_priority_map:
        priority = custom_priority_map[priority_raw]
    else:
        priority = _JIRA_PRIORITY_MAP.get(priority_raw.lower(), "none")

    # Description — extract plain text from Atlassian Document Format
    description = _extract_adf_text(fields.get("description"))

    # Category — epic parent or project
    category = _jira_category(fields)

    # Tags from labels — sorted for stable comparison across pulls
    tags = sorted(set(fields.get("labels") or []))

    # URL
    self_url = raw.get("self", "")
    base = self_url.rsplit("/rest/", 1)[0] if "/rest/" in self_url else ""
    url = f"{base}/browse/{key}" if base else None

    # Jira resolutiondate — set when the issue transitions to a 'done' category
    completed_date = fields.get("resolutiondate")

    return {
        "id": f"jira-{key}",
        "local_id": "",  # assigned by merge_pulled_items
        "source": "jira",
        "title": fields.get("summary", ""),
        "description": description,
        "status": status,
        "priority": priority,
        "created_date": fields.get("created"),
        "due_date": fields.get("duedate"),
        "updated_date": fields.get("updated"),
        "completed_date": completed_date,
        "tags": tags,
        "url": url,
        "category": category,
        "raw": raw,
    }


def _extract_adf_text(doc: dict | None) -> str | None:
    """Extract plain text from an Atlassian Document Format structure.

    ADF nests arbitrarily: paragraphs, bullet lists (3 levels), tables (5),
    panels, blockquotes, headings. Walk recursively so nothing past the first
    inline level is dropped.
    """
    if not doc or not isinstance(doc, dict):
        return None
    parts: list[str] = []

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "text":
            text = node.get("text")
            if text:
                parts.append(text)
            return
        for child in node.get("content") or ():
            walk(child)

    walk(doc)
    return " ".join(parts) if parts else None


def _jira_category(fields: dict) -> dict:
    """Determine the category from epic parent or project."""
    # Check parent issue — if it's an Epic, use it
    parent = fields.get("parent")
    if parent and isinstance(parent, dict):
        parent_fields = parent.get("fields", {})
        parent_type = parent_fields.get("issuetype", {}).get("name", "")
        if parent_type.lower() == "epic":
            return {
                "id": parent.get("key"),
                "name": parent_fields.get("summary"),
                "type": "epic",
            }

    epic_link = fields.get(_JIRA_EPIC_LINK_FIELD)
    if epic_link:
        return {
            "id": str(epic_link),
            "name": str(epic_link),
            "type": "epic",
        }

    # Fall back to project
    project = fields.get("project", {})
    return {
        "id": project.get("key"),
        "name": project.get("name"),
        "type": "project",
    }


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

_NOTION_STATUS_MAP = {
    "not started": "todo",
    "to do": "todo",
    "todo": "todo",
    "backlog": "todo",
    "in progress": "in_progress",
    "doing": "in_progress",
    "active": "in_progress",
    "done": "done",
    "complete": "done",
    "completed": "done",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "archived": "cancelled",
}

_NOTION_PRIORITY_MAP = {
    "critical": "critical",
    "urgent": "critical",
    "high": "high",
    "medium": "medium",
    "normal": "medium",
    "low": "low",
    "none": "none",
}

# Property names that map to tags when they are Select or Multi-select
_NOTION_TAG_PROPERTIES = {"epic", "category", "project"}


def normalize_notion(raw: dict, source_config: dict | None = None) -> dict:
    cfg = source_config or {}
    field_map = cfg.get("field_map", {})
    custom_status_map = cfg.get("status_map", {})
    custom_priority_map = cfg.get("priority_map", {})

    props = raw.get("properties", {})

    # Title — auto-detect title-type property
    title = _notion_title(props)

    # Description — configurable, then fallbacks
    desc_field = field_map.get("description")
    if desc_field:
        description = _notion_rich_text(props, desc_field)
    else:
        description = _notion_rich_text(props, "Description") or _notion_rich_text(props, "Notes")

    # Status — configurable field name, handles both select and status types
    status_field = field_map.get("status", "Status")
    status_raw = _notion_prop_value(props, status_field)
    if status_raw and status_raw in custom_status_map:
        status = custom_status_map[status_raw]
    elif status_raw:
        status = _NOTION_STATUS_MAP.get(status_raw.lower(), "todo")
    else:
        status = "todo"

    # Priority — configurable field name
    priority_field = field_map.get("priority", "Priority")
    priority_raw = _notion_prop_value(props, priority_field)
    if priority_raw and priority_raw in custom_priority_map:
        priority = custom_priority_map[priority_raw]
    elif priority_raw:
        priority = _NOTION_PRIORITY_MAP.get(priority_raw.lower(), "none")
    else:
        priority = "none"

    # Due date — configurable field name
    due_field = field_map.get("due_date")
    if due_field:
        due_date = _notion_date_value(props, due_field)
    else:
        due_date = (
            _notion_date_value(props, "Due Date")
            or _notion_date_value(props, "Due")
            or _notion_date_value(props, "Deadline")
            or _notion_date_value(props, "Tarih")
        )

    # Tags — configurable field name
    tags_field = field_map.get("tags", "Tags")
    tags = _notion_multi_select_values(props, tags_field)
    # Also pull from any Epic/Category/Project select/multi-select not already mapped
    mapped_fields = set(field_map.values()) if field_map else set()
    for actual_name, prop in props.items():
        if actual_name.lower() in _NOTION_TAG_PROPERTIES and actual_name not in mapped_fields:
            if prop.get("type") == "select" and prop.get("select"):
                tags.append(prop["select"]["name"])
            elif prop.get("type") == "multi_select":
                tags.extend(ms["name"] for ms in prop.get("multi_select", []))
    tags = sorted(set(tags))

    # Category — configurable, or database
    cat_field = field_map.get("category")
    if cat_field:
        cat_value = _notion_prop_value(props, cat_field)
        category = {
            "id": raw.get("_database_id"),
            "name": cat_value,
            "type": "database",
        }
    else:
        category = {
            "id": raw.get("_database_id"),
            "name": raw.get("_database_title"),
            "type": "database",
        }

    # URL
    url = raw.get("url")

    return {
        "id": f"notion-{raw.get('id', '')}",
        "local_id": "",
        "source": "notion",
        "title": title,
        "description": description,
        "status": status,
        "priority": priority,
        "created_date": raw.get("created_time"),
        "due_date": due_date,
        "updated_date": raw.get("last_edited_time"),
        "completed_date": None,  # Notion has no universal completed timestamp
        "tags": tags,
        "url": url,
        "category": category,
        "raw": raw,
    }


def _notion_title(props: dict) -> str:
    """Extract the title from Notion properties (looks for any title-type property)."""
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            if title_parts:
                return "".join(part.get("plain_text", "") for part in title_parts)
    return ""


def _notion_prop_value(props: dict, name: str) -> str | None:
    """Get the string value of a select, status, or rich_text property."""
    prop = props.get(name)
    if not prop:
        return None
    ptype = prop.get("type")
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name") if sel and isinstance(sel, dict) else None
    if ptype == "status":
        st = prop.get("status")
        return st.get("name") if st and isinstance(st, dict) else None
    if ptype == "rich_text":
        parts = prop.get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts) if parts else None
    if ptype == "multi_select":
        items = prop.get("multi_select", [])
        return ", ".join(ms.get("name", "") for ms in items) if items else None
    return None


def _notion_select_value(props: dict, name: str) -> str | None:
    """Get the value of a Select property by name."""
    prop = props.get(name)
    if not prop or prop.get("type") != "select":
        return None
    sel = prop.get("select")
    if sel and isinstance(sel, dict):
        return sel.get("name")
    return None


def _notion_multi_select_values(props: dict, name: str) -> list[str]:
    """Get the values of a Multi-select property by name."""
    prop = props.get(name)
    if not prop or prop.get("type") != "multi_select":
        return []
    return [ms.get("name", "") for ms in prop.get("multi_select", [])]


def _notion_date_value(props: dict, name: str) -> str | None:
    """Get the start date from a Date property by name."""
    prop = props.get(name)
    if not prop or prop.get("type") != "date":
        return None
    date_obj = prop.get("date")
    if date_obj and isinstance(date_obj, dict):
        return date_obj.get("start")
    return None


def _notion_rich_text(props: dict, name: str) -> str | None:
    """Get the plain text from a rich_text property by name."""
    prop = props.get(name)
    if not prop or prop.get("type") != "rich_text":
        return None
    parts = prop.get("rich_text", [])
    if parts:
        return "".join(part.get("plain_text", "") for part in parts)
    return None


# ---------------------------------------------------------------------------
# Microsoft To Do
# ---------------------------------------------------------------------------

_MSTODO_STATUS_MAP = {
    "notstarted": "todo",
    "inprogress": "in_progress",
    "completed": "done",
    "waitingonothers": "in_progress",
    "deferred": "todo",
}

_MSTODO_IMPORTANCE_MAP = {
    "high": "high",
    "normal": "medium",
    "low": "low",
}


def normalize_mstodo(raw: dict, source_config: dict | None = None) -> dict:
    task_id = raw.get("id", "")

    # Title
    title = raw.get("title", "")

    # Description — strip HTML if contentType is html
    body = raw.get("body")
    if body and isinstance(body, dict):
        content = body.get("content", "")
        if not content.strip():
            description = None
        elif body.get("contentType") == "html":
            description = _strip_html(content)
        else:
            description = content
    else:
        description = None

    # Status
    status_raw = (raw.get("status") or "").lower().replace(" ", "")
    status = _MSTODO_STATUS_MAP.get(status_raw, "todo")

    # Priority / importance
    importance_raw = (raw.get("importance") or "").lower()
    priority = _MSTODO_IMPORTANCE_MAP.get(importance_raw, "none")

    # Dates
    created_date = raw.get("createdDateTime")
    updated_date = raw.get("lastModifiedDateTime")
    due_date = None
    due_dt = raw.get("dueDateTime")
    if due_dt and isinstance(due_dt, dict):
        due_date = due_dt.get("dateTime")

    # Tags from categories + list name; sorted for stable comparison.
    categories = raw.get("categories") or []
    tag_set = set(categories)
    list_name = raw.get("_list_name")
    if list_name:
        tag_set.add(list_name)
    tags = sorted(tag_set)

    # Category — the task list
    category = {
        "id": raw.get("_list_id"),
        "name": list_name,
        "type": "list",
    }

    # Completion date
    completed_date = raw.get("completedDateTime")
    if isinstance(completed_date, dict):
        completed_date = completed_date.get("dateTime")

    return {
        "id": f"mstodo-{task_id}",
        "local_id": "",
        "source": "mstodo",
        "title": title,
        "description": description,
        "status": status,
        "priority": priority,
        "created_date": created_date,
        "due_date": due_date,
        "updated_date": updated_date,
        "completed_date": completed_date,
        "tags": tags,
        "url": None,
        "category": category,
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# Plane (self-hosted)
# ---------------------------------------------------------------------------

_PLANE_STATE_GROUP_MAP = {
    "backlog": "todo",
    "unstarted": "todo",
    "started": "in_progress",
    "completed": "done",
    "cancelled": "cancelled",
}

_PLANE_PRIORITY_MAP = {
    "urgent": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "none": "none",
}


def normalize_plane(raw: dict, source_config: dict | None = None) -> dict:
    cfg = source_config or {}
    custom_status_map = cfg.get("status_map", {})
    custom_priority_map = cfg.get("priority_map", {})

    issue_id = raw.get("id", "")
    project_id = raw.get("_project_id", "")
    sequence_id = raw.get("sequence_id")

    # Status — state_name check first (user-visible), then fall back to group
    state_name = raw.get("_state_name") or ""
    state_group = (raw.get("_state_group") or "").lower()
    if state_name in custom_status_map:
        status = custom_status_map[state_name]
    else:
        status = _PLANE_STATE_GROUP_MAP.get(state_group, "todo")

    # Priority
    priority_raw = (raw.get("priority") or "none").lower()
    if priority_raw in custom_priority_map:
        priority = custom_priority_map[priority_raw]
    else:
        priority = _PLANE_PRIORITY_MAP.get(priority_raw, "none")

    # Description — strip HTML from description_html (fall back to plain)
    desc_html = raw.get("description_html")
    description = _strip_html(desc_html) if desc_html else raw.get("description")
    if description is not None and not description.strip():
        description = None

    tags = sorted(set(raw.get("_label_names") or []))

    url = None
    base_url = raw.get("_base_url")
    workspace = raw.get("_workspace_slug")
    if base_url and workspace and project_id and issue_id:
        url = (
            f"{base_url}/{workspace}/projects/{project_id}/issues/{issue_id}"
        )

    category = {
        "id": str(project_id) if project_id else None,
        "name": raw.get("_project_name"),
        "type": "project",
    }

    # Use the API UUID (issue_id), not the human-readable sequence_id, so push
    # can address the same record via /projects/{project_id}/issues/{UUID}.
    # Older versions used "{project_id}-{sequence_id}" — see
    # plane.migrate_legacy_mappings() for the one-shot upgrade path.
    if project_id and issue_id:
        id_suffix = f"{project_id}:{issue_id}"
    else:
        id_suffix = str(issue_id or "")

    return {
        "id": f"plane-{id_suffix}",
        "local_id": "",
        "source": "plane",
        "title": raw.get("name", ""),
        "description": description,
        "status": status,
        "priority": priority,
        "created_date": raw.get("created_at"),
        "due_date": raw.get("target_date"),
        "updated_date": raw.get("updated_at"),
        "completed_date": raw.get("completed_at"),
        "tags": tags,
        "url": url,
        "category": category,
        "raw": raw,
    }
