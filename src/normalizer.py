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


def normalize(source: str, raw: dict) -> dict:
    """Dispatch to the correct normalizer based on source name."""
    from src.sources import REGISTRY
    source_def = REGISTRY.get(source)
    if source_def is None:
        raise ValueError(f"Unknown source: {source}")
    return source_def.normalize(raw)


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


def normalize_vikunja(raw: dict) -> dict:
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

    # Tags from labels
    labels = raw.get("labels") or []
    tags = [label.get("title", "") for label in labels if label.get("title")]

    # URL
    url = None

    # Category — project
    category = {
        "id": str(raw.get("_project_id", "")),
        "name": raw.get("_project_title"),
        "type": "project",
    }

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


def normalize_jira(raw: dict) -> dict:
    fields = raw.get("fields", {})
    key = raw.get("key", raw.get("id", ""))

    # Status
    status_cat = (fields.get("status") or {}).get("statusCategory", {}).get("key", "")
    status = _JIRA_STATUS_MAP.get(status_cat, "todo")

    # Check for cancelled status name
    status_name = (fields.get("status") or {}).get("name", "").lower()
    if "cancel" in status_name:
        status = "cancelled"

    # Priority
    priority_name = (fields.get("priority") or {}).get("name", "").lower()
    priority = _JIRA_PRIORITY_MAP.get(priority_name, "none")

    # Description — extract plain text from Atlassian Document Format
    description = _extract_adf_text(fields.get("description"))

    # Category — epic parent or project
    category = _jira_category(fields)

    # Tags from labels
    tags = list(fields.get("labels") or [])

    # URL
    self_url = raw.get("self", "")
    base = self_url.rsplit("/rest/", 1)[0] if "/rest/" in self_url else ""
    url = f"{base}/browse/{key}" if base else None

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
        "tags": tags,
        "url": url,
        "category": category,
        "raw": raw,
    }


def _extract_adf_text(doc: dict | None) -> str | None:
    """Extract plain text from an Atlassian Document Format structure."""
    if not doc or not isinstance(doc, dict):
        return None
    parts = []
    for block in doc.get("content", []):
        for inline in block.get("content", []):
            if inline.get("type") == "text":
                parts.append(inline.get("text", ""))
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


def normalize_notion(raw: dict) -> dict:
    props = raw.get("properties", {})

    # Title
    title = _notion_title(props)

    # Description — look for a rich_text property named Description/Notes
    description = _notion_rich_text(props, "Description") or _notion_rich_text(props, "Notes")

    # Status
    status_raw = _notion_select_value(props, "Status")
    status = _NOTION_STATUS_MAP.get((status_raw or "").lower(), "todo") if status_raw else "todo"

    # Priority
    priority_raw = _notion_select_value(props, "Priority")
    priority = _NOTION_PRIORITY_MAP.get((priority_raw or "").lower(), "none") if priority_raw else "none"

    # Due date
    due_date = _notion_date_value(props, "Due Date") or _notion_date_value(props, "Due") or _notion_date_value(props, "Deadline")

    # Tags — from Tags multi-select + any Epic/Category/Project select/multi-select
    tags = _notion_multi_select_values(props, "Tags")
    for actual_name, prop in props.items():
        if actual_name.lower() in _NOTION_TAG_PROPERTIES:
            if prop.get("type") == "select" and prop.get("select"):
                tags.append(prop["select"]["name"])
            elif prop.get("type") == "multi_select":
                tags.extend(ms["name"] for ms in prop.get("multi_select", []))
    # Deduplicate while preserving order
    tags = list(dict.fromkeys(tags))

    # URL
    url = raw.get("url")

    # Category — database
    category = {
        "id": raw.get("_database_id"),
        "name": raw.get("_database_title"),
        "type": "database",
    }

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


def normalize_mstodo(raw: dict) -> dict:
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

    # Tags from categories
    categories = raw.get("categories")
    tags = list(categories) if categories else []

    # Add list name to tags
    list_name = raw.get("_list_name")
    if list_name and list_name not in tags:
        tags.append(list_name)

    # Category — the task list
    category = {
        "id": raw.get("_list_id"),
        "name": list_name,
        "type": "list",
    }

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
        "tags": tags,
        "url": None,
        "category": category,
        "raw": raw,
    }
