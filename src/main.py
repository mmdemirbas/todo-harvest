"""CLI entry point for todo-harvest."""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.config import ConfigError, load_config, enabled_sources, validate_source, SOURCES
from src.sources import REGISTRY
from src.sources._http import SourceAuthError, SourceFetchError


console = Console()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="todo",
        description="Collect and sync TODO items across services.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config.yaml. Default: config.yaml in project root.",
    )

    sub = parser.add_subparsers(dest="command")

    # pull
    pull_p = sub.add_parser("pull", help="Pull from one or more services into local state.")
    pull_p.add_argument("services", nargs="*", help="Services to pull from. Default: all configured.")

    # push
    push_p = sub.add_parser("push", help="Push local state to one or more services.")
    push_p.add_argument("services", nargs="*", help="Services to push to. Default: all configured.")

    # sync
    sync_p = sub.add_parser("sync", help="Pull all specified services, then push to all.")
    sync_p.add_argument("services", nargs="*", help="Services to sync. Default: all configured.")

    # export (legacy snapshot)
    export_p = sub.add_parser("export", help="Export local state to JSON/CSV files.")
    export_p.add_argument("--output-dir", type=str, default=None, help="Override output directory.")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    command = args.command
    if command is None:
        console.print("[bold yellow]No command specified.[/] Use: pull, push, sync, or export.")
        console.print("Run './todo --help' for usage.")
        return 1

    # Load config
    config_path = Path(args.config) if args.config else None
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        return 1

    if command == "export":
        return _cmd_export(config, args)

    # Resolve services for pull/push/sync
    requested = getattr(args, "services", []) or []
    services, err = _resolve_services(config, requested)
    if err:
        console.print(f"[bold red]{err}[/]")
        return 1

    if not services:
        console.print("[bold yellow]No services configured.[/] Edit config.yaml to add credentials.")
        return 1

    # Banner
    config_display = args.config or "config.yaml"
    console.print(f"[bold]todo-harvest {command}[/] — config: {config_display}")
    console.print(f"Services: {', '.join(services)}")
    console.print()

    if command == "pull":
        return _cmd_pull(config, services)
    elif command == "push":
        return _cmd_push(config, services)
    elif command == "sync":
        return _cmd_sync(config, services)

    return 1


def _resolve_services(config: dict, requested: list[str]) -> tuple[list[str], str | None]:
    """Validate and resolve service names. Returns (services, error_message)."""
    if requested:
        invalid = [s for s in requested if s not in SOURCES]
        if invalid:
            return [], f"Unknown service(s): {', '.join(invalid)}. Valid: {', '.join(SOURCES)}"
        return requested, None
    return enabled_sources(config), None


def _cmd_pull(config: dict, services: list[str]) -> int:
    """Pull from specified services into local state."""
    from src.normalizer import normalize
    from src.local_state import load_local_state, save_local_state, merge_pulled_items
    from src.mapping import SyncMapping

    db_path = config.get("mapping", {}).get("db_path", "mapping.db")
    state_path = Path(config["output"]["dir"]) / "todos.json"

    had_errors = False
    all_stats = []

    with SyncMapping(db_path) as mapping:
        local_items = load_local_state(state_path)

        for service in services:
            errors = validate_source(config, service)
            if errors:
                console.print(f"[bold yellow]Skipping {service}:[/] {'; '.join(errors)}")
                had_errors = True
                continue

            source_def = REGISTRY[service]
            try:
                raw_items = source_def.pull(config[service], console)
            except (SourceAuthError, SourceFetchError) as exc:
                console.print(f"[bold red]{service} failed:[/] {exc}")
                had_errors = True
                continue
            except Exception as exc:
                console.print(f"[bold red]{service} unexpected error (bug):[/] {exc}")
                traceback.print_exc()
                had_errors = True
                continue

            # Normalize
            normalized = []
            for raw in raw_items:
                try:
                    normalized.append(normalize(service, raw, config.get(service, {})))
                except Exception as exc:
                    console.print(f"[yellow]Warning:[/] Failed to normalize {service} item: {exc}")

            # Merge into local state
            local_items, stats = merge_pulled_items(local_items, normalized, mapping, service)
            mapping.log_sync(service, "pull", len(normalized))
            all_stats.append({"service": service, **stats})

        save_local_state(local_items, state_path)

    # Summary
    _print_pull_summary(all_stats, len(local_items))
    return 1 if had_errors else 0


def _cmd_push(config: dict, services: list[str]) -> int:
    """Push local state to specified services."""
    from src.local_state import load_local_state
    from src.mapping import SyncMapping

    db_path = config.get("mapping", {}).get("db_path", "mapping.db")
    state_path = Path(config["output"]["dir"]) / "todos.json"
    local_items = load_local_state(state_path)

    if not local_items:
        console.print("[bold yellow]No local tasks to push.[/] Run 'pull' first.")
        return 0

    had_errors = False
    all_results = []

    with SyncMapping(db_path) as mapping:
        for service in services:
            source_def = REGISTRY[service]
            if not source_def.push_supported:
                console.print(f"[yellow]{service}:[/] Push not supported, skipping.")
                continue

            errors = validate_source(config, service)
            if errors:
                console.print(f"[bold yellow]Skipping {service}:[/] {'; '.join(errors)}")
                had_errors = True
                continue

            try:
                result = source_def.push(config[service], local_items, console)
                mapping.log_sync(service, "push", result.get("created", 0) + result.get("updated", 0))
                all_results.append({"service": service, **result})
            except NotImplementedError as exc:
                console.print(f"[yellow]{service}:[/] {exc}")
            except (SourceAuthError, SourceFetchError) as exc:
                console.print(f"[bold red]{service} push failed:[/] {exc}")
                had_errors = True
            except Exception as exc:
                console.print(f"[bold red]{service} unexpected error (bug):[/] {exc}")
                traceback.print_exc()
                had_errors = True

    _print_push_summary(all_results)
    return 1 if had_errors else 0


def _cmd_sync(config: dict, services: list[str]) -> int:
    """Pull all specified services, then push to all."""
    pull_result = _cmd_pull(config, services)
    push_result = _cmd_push(config, services)
    return 1 if (pull_result != 0 or push_result != 0) else 0


def _cmd_export(config: dict, args: argparse.Namespace) -> int:
    """Export local state to JSON/CSV snapshot files."""
    from src.local_state import load_local_state
    from src.exporter import export_all

    state_path = Path(config["output"]["dir"]) / "todos.json"
    output_dir = Path(args.output_dir) if args.output_dir else Path(config["output"]["dir"])

    local_items = load_local_state(state_path)
    if not local_items:
        console.print("[bold yellow]No local tasks to export.[/] Run 'pull' first.")
        return 0

    try:
        files = export_all(local_items, output_dir)
    except OSError as exc:
        console.print(f"[bold red]Failed to write output:[/] {exc}")
        return 1

    console.print(f"Exported {len(local_items)} tasks:")
    for f in files:
        console.print(f"  -> {f}")
    return 0


def _print_pull_summary(stats: list[dict], total_local: int) -> None:
    table = Table(title="PULL")
    table.add_column("Service", style="bold")
    table.add_column("Created", justify="right")
    table.add_column("Updated", justify="right")
    table.add_column("Skipped", justify="right")
    table.add_column("Conflicts", justify="right")

    for s in stats:
        table.add_row(
            s["service"],
            str(s.get("created", 0)),
            str(s.get("updated", 0)),
            str(s.get("skipped", 0)),
            str(s.get("conflicts", 0)),
        )

    console.print(table)
    console.print(f"  local state: {total_local} tasks total")
    console.print()


def _print_push_summary(results: list[dict]) -> None:
    if not results:
        return
    table = Table(title="PUSH")
    table.add_column("Service", style="bold")
    table.add_column("Created", justify="right")
    table.add_column("Updated", justify="right")
    table.add_column("Skipped", justify="right")

    for r in results:
        table.add_row(
            r["service"],
            str(r.get("created", 0)),
            str(r.get("updated", 0)),
            str(r.get("skipped", 0)),
        )

    console.print(table)
    console.print()


if __name__ == "__main__":
    raise SystemExit(main())
