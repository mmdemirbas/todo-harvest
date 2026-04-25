"""Export normalized TODO items to JSON and CSV files."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.schema import CSV_COLUMNS


def _sort_key(item: dict) -> tuple:
    return (item.get("source", ""), item.get("id", ""))


def export_json(items: list[dict], path: Path) -> None:
    """Write items to a JSON file, sorted deterministically."""
    sorted_items = sorted(items, key=_sort_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted_items, f, indent=2, ensure_ascii=False)


def export_csv(items: list[dict], path: Path) -> None:
    """Write items to a CSV file, sorted deterministically.

    Flattens category and tags fields. Excludes raw payload.
    """
    sorted_items = sorted(items, key=_sort_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in sorted_items:
            row = {
                "id": item.get("id", ""),
                "local_id": item.get("local_id", ""),
                "source": item.get("source", ""),
                "title": item.get("title", ""),
                "description": item.get("description") or "",
                "status": item.get("status", ""),
                "priority": item.get("priority", ""),
                "created_date": item.get("created_date") or "",
                "due_date": item.get("due_date") or "",
                "updated_date": item.get("updated_date") or "",
                "completed_date": item.get("completed_date") or "",
                "tags": ";".join(item.get("tags", [])),
                "url": item.get("url") or "",
                "category_id": (item.get("category") or {}).get("id") or "",
                "category_name": (item.get("category") or {}).get("name") or "",
                "category_type": (item.get("category") or {}).get("type") or "",
            }
            writer.writerow(row)


def export_source_json(items: list[dict], source: str, output_dir: Path) -> Path:
    """Export items for a single source to output_dir/{source}.json."""
    path = output_dir / f"{source}.json"
    export_json(items, path)
    return path


def export_all(items: list[dict], output_dir: Path) -> list[Path]:
    """Export all items to combined JSON/CSV and per-source JSON files.

    Returns list of created file paths.
    """
    output_dir = Path(output_dir)
    files = []

    # Per-source files
    sources = sorted({item["source"] for item in items})
    for source in sources:
        source_items = [item for item in items if item["source"] == source]
        path = export_source_json(source_items, source, output_dir)
        files.append(path)

    # Combined files
    combined_json = output_dir / "todos.json"
    export_json(items, combined_json)
    files.append(combined_json)

    combined_csv = output_dir / "todos.csv"
    export_csv(items, combined_csv)
    files.append(combined_csv)

    return files
