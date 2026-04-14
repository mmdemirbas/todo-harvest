"""CLI entry point for todo-harvest."""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from rich.console import Console

from src.config import ConfigError, load_config, enabled_sources, validate_source, SOURCES
from src.sources import REGISTRY
from src.sources._http import SourceAuthError, SourceFetchError


console = Console()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="todo-harvest",
        description="Collect TODO items from Microsoft To Do, Jira, and Notion.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Comma-separated list of sources to fetch (msftodo, jira, notion). Default: all configured.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override the output directory from config.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config.yaml. Default: config.yaml in project root.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Load config
    config_path = Path(args.config) if args.config else None
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        return 1

    # Override output dir if specified
    if args.output_dir:
        config["output"]["dir"] = args.output_dir

    # Determine which sources to run
    if args.source:
        requested = [s.strip() for s in args.source.split(",")]
        invalid = [s for s in requested if s not in SOURCES]
        if invalid:
            console.print(f"[bold red]Unknown source(s):[/] {', '.join(invalid)}")
            console.print(f"Valid sources: {', '.join(SOURCES)}")
            return 1
        sources = requested
    else:
        sources = enabled_sources(config)

    if not sources:
        console.print("[bold yellow]No sources configured.[/] Edit config.yaml to add credentials.")
        return 1

    # Banner
    config_display = args.config or "config.yaml"
    console.print(f"[bold]todo-harvest[/] — config: {config_display}")
    console.print(f"Sources: {', '.join(sources)}")
    console.print()

    from src.normalizer import normalize
    from src.exporter import export_all

    output_dir = Path(config["output"]["dir"])
    all_items = []
    source_stats = []
    had_errors = False

    for source in sources:
        errors = validate_source(config, source)
        if errors:
            console.print(f"[bold yellow]Skipping {source}:[/] {'; '.join(errors)}")
            had_errors = True
            continue

        source_def = REGISTRY[source]
        try:
            raw_items = source_def.pull(config[source], console)
        except (SourceAuthError, SourceFetchError) as exc:
            console.print(f"[bold red]{source} failed:[/] {exc}")
            had_errors = True
            continue
        except Exception as exc:
            console.print(f"[bold red]{source} unexpected error (bug):[/] {exc}")
            traceback.print_exc()
            had_errors = True
            continue

        normalized = []
        normalize_errors = 0
        for raw in raw_items:
            try:
                normalized.append(normalize(source, raw))
            except Exception as exc:
                normalize_errors += 1
                console.print(f"[yellow]Warning:[/] Failed to normalize {source} item: {exc}")

        if normalize_errors > 0 and len(normalized) == 0 and len(raw_items) > 0:
            console.print(
                f"[bold red]{source}:[/] All {len(raw_items)} items failed normalization."
            )
            had_errors = True

        all_items.extend(normalized)

        categories = {item["category"]["name"] for item in normalized if item["category"]["name"]}
        source_stats.append({
            "source": source,
            "items": len(normalized),
            "categories": len(categories),
            "errors": normalize_errors,
        })

    if not all_items:
        console.print("[bold yellow]No items collected from any source.[/]")
        return 1 if had_errors else 0

    # Export
    try:
        files = export_all(all_items, output_dir)
    except OSError as exc:
        console.print(f"[bold red]Failed to write output:[/] {exc}")
        return 1

    # Summary table
    from rich.table import Table

    table = Table(title="Harvest Summary")
    table.add_column("Source", style="bold")
    table.add_column("Items", justify="right")
    table.add_column("Categories", justify="right")

    total_items = 0
    total_categories = 0
    for stat in source_stats:
        table.add_row(stat["source"], str(stat["items"]), str(stat["categories"]))
        total_items += stat["items"]
        total_categories += stat["categories"]

    table.add_section()
    table.add_row("TOTAL", str(total_items), str(total_categories))

    console.print(table)
    console.print()
    for f in files:
        console.print(f"  -> {f}")

    return 1 if had_errors else 0
