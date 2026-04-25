"""CLI entry point for todo-harvest."""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src import __version__
from src.config import ConfigError, load_config, enabled_sources, validate_source, SOURCES
from src.sources import REGISTRY
from src.sources._http import SourceAuthError, SourceFetchError


console = Console()


INSPECT_TARGETS = ("projects", "stats", "fields")


# Color scheme (rich markup):
#   section titles  → bold cyan
#   command names   → bold green
#   arg placeholders→ yellow
#   option flags    → bold
#   examples/notes  → dim
#   values/services → magenta
_TOP_LEVEL_HELP = """[bold]Usage:[/] [bold green]todo[/] [bold]\\[--config PATH][/] [yellow]<command>[/] [yellow]\\[args...][/]

Collect, sync, and inspect TODO items across Vikunja, Jira, MS To Do, Notion, and Plane.

[bold cyan]Sync commands[/] [dim](network I/O)[/]:
  [bold green]pull[/]    [yellow]\\[services...][/]       Fetch tasks from services into local state
  [bold green]push[/]    [yellow]\\[services...][/]       Write local state back to services
  [bold green]sync[/]    [yellow]\\[services...][/]       Pull, then push, the same set of services

[bold cyan]Local commands[/] [dim](no network)[/]:
  [bold green]inspect[/] [yellow]<target> \\[args][/]     Inspect local data. Targets: [magenta]projects[/], [magenta]stats[/], [magenta]fields[/]
  [bold green]export[/]  [yellow]\\[--output-dir][/]      Snapshot local state to JSON/CSV files

[bold cyan]Help[/]:
  [bold green]help[/]    [yellow]\\[command][/]           Show detailed help for a command

[bold cyan]Global options[/]:
  [bold]--config PATH[/]            Path to [magenta]config.yaml[/] [dim](default: ./config.yaml)[/]
  [bold]-V, --version[/]            Show version and exit
  [bold]-h, --help[/]               Show this message

[dim]Services:[/] [magenta]vikunja[/], [magenta]jira[/], [magenta]mstodo[/], [magenta]notion[/], [magenta]plane[/]
[dim]Run [/][bold green]'todo help <command>'[/][dim] for command-specific arguments and examples.[/]
"""


# Per-command colored help. Used by both `todo help <cmd>` and `todo <cmd> --help`.
_SUB_HELP: dict[str, str] = {}


def _sync_cmd_help(cmd: str, verb: str) -> str:
    return f"""[bold]Usage:[/] [bold green]todo[/] [bold green]{cmd}[/] [yellow]\\[service...][/]

{verb}

[bold cyan]Arguments[/]:
  [yellow]service[/]              Service(s) to [bold green]{cmd}[/]. Omit to use every configured service.
                       [dim]Choices: [/][magenta]vikunja[/], [magenta]jira[/], [magenta]mstodo[/], [magenta]notion[/], [magenta]plane[/]

[bold cyan]Options[/]:
  [bold]-h, --help[/]           Show this message

[bold cyan]Examples[/]:
  [bold green]todo {cmd}[/]                          [dim]# all configured services[/]
  [bold green]todo {cmd}[/] [magenta]jira[/] [magenta]notion[/]              [dim]# only these services[/]
"""


_SUB_HELP["pull"] = _sync_cmd_help("pull", "Fetch tasks from services into local state.")
_SUB_HELP["push"] = _sync_cmd_help("push", "Write local state back to services.")
_SUB_HELP["sync"] = _sync_cmd_help("sync", "Pull, then push, the same set of services.")

_SUB_HELP["export"] = """[bold]Usage:[/] [bold green]todo[/] [bold green]export[/] [bold]\\[--output-dir DIR][/]

Snapshot local state to JSON and CSV files.

[bold cyan]Options[/]:
  [bold]--output-dir DIR[/]     Directory to write snapshot files.
                       [dim](default: [/][magenta]output.dir[/][dim] from config.yaml)[/]
  [bold]-h, --help[/]           Show this message

[bold cyan]Examples[/]:
  [bold green]todo export[/]
  [bold green]todo export[/] [bold]--output-dir[/] [magenta]~/snapshots[/]
"""

_SUB_HELP["inspect"] = """[bold]Usage:[/] [bold green]todo[/] [bold green]inspect[/] [yellow]<target>[/] [yellow]\\[args...][/]

Inspect local data without hitting any service.

[bold cyan]Targets[/]:
  [magenta]projects[/] [yellow]\\[source][/]    List project/list/database IDs and names.
                       [dim]Use this to discover IDs (e.g. for [/][bold yellow]vikunja.default_project_id[/][dim]).[/]
  [magenta]stats[/]               Counts, field coverage, date ranges, status distribution.
  [magenta]fields[/] [yellow]\\[source][/]      Unique status/priority values + top tags.
                       [dim]Useful for finding values that need mapping in config.yaml.[/]

[bold cyan]Arguments[/]:
  [yellow]source[/]              [dim]Optional.[/] Filter to one source.
                       [dim]Choices: [/][magenta]vikunja[/], [magenta]jira[/], [magenta]mstodo[/], [magenta]notion[/], [magenta]plane[/]

[bold cyan]Examples[/]:
  [bold green]todo inspect projects[/]                      [dim]# all sources[/]
  [bold green]todo inspect projects[/] [magenta]vikunja[/]             [dim]# just Vikunja projects + IDs[/]
  [bold green]todo inspect stats[/]
  [bold green]todo inspect fields[/] [magenta]jira[/]                  [dim]# spot unmapped statuses/priorities[/]
"""

_SUB_HELP["help"] = """[bold]Usage:[/] [bold green]todo[/] [bold green]help[/] [yellow]\\[command][/]

Show detailed help for a command, or top-level help if no command is given.

[bold cyan]Arguments[/]:
  [yellow]command[/]             [dim]Optional.[/] Command to show help for.
                       [dim]Choices: [/][bold green]pull[/], [bold green]push[/], [bold green]sync[/], [bold green]inspect[/], [bold green]export[/], [bold green]help[/]

[bold cyan]Examples[/]:
  [bold green]todo help[/]                          [dim]# top-level overview[/]
  [bold green]todo help[/] [bold green]pull[/]                     [dim]# detailed pull help[/]
  [bold green]todo help[/] [bold green]inspect[/]                  [dim]# detailed inspect help[/]
"""


def _print_colored(markup_text: str) -> None:
    """Render a rich-markup help string to the console."""
    console.print(markup_text, end="", highlight=False)


class _TodoParser(argparse.ArgumentParser):
    """Top-level parser with a custom colored grouped help."""

    def format_help(self) -> str:  # type: ignore[override]
        return _TOP_LEVEL_HELP  # kept for tests that call format_help()

    def print_help(self, file=None) -> None:  # type: ignore[override]
        _print_colored(_TOP_LEVEL_HELP)


class _ColoredSubParser(argparse.ArgumentParser):
    """Subparser that prints a pre-formatted colored help instead of argparse default."""

    def print_help(self, file=None) -> None:  # type: ignore[override]
        markup = _SUB_HELP.get(self.prog.split()[-1])
        if markup is not None:
            _print_colored(markup)
        else:
            super().print_help(file)


def build_parser() -> argparse.ArgumentParser:
    parser = _TodoParser(prog="todo", add_help=False)
    parser.add_argument("-h", "--help", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "-V", "--version", action="version",
        version=f"todo-harvest {__version__}",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to config.yaml. Default: config.yaml in project root.",
    )

    sub = parser.add_subparsers(
        dest="command", metavar="<command>",
        parser_class=_ColoredSubParser,
    )

    # --- pull / push / sync --------------------------------------------------
    for name, verb in (
        ("pull", "Fetch tasks from services into local state."),
        ("push", "Write local state back to services."),
        ("sync", "Pull, then push, the same set of services."),
    ):
        p = sub.add_parser(
            name,
            help=verb,
            description=verb,
            epilog=(
                f"Examples:\n"
                f"  todo {name}                    # all configured services\n"
                f"  todo {name} jira notion        # only these services\n\n"
                f"Valid services: {', '.join(SOURCES)}"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        p.add_argument(
            "services",
            nargs="*",
            metavar="service",
            help=f"Service(s) to {name}. Choices: {', '.join(SOURCES)}. "
                 "Default: all configured in config.yaml.",
        )

    # --- export --------------------------------------------------------------
    export_p = sub.add_parser(
        "export",
        help="Snapshot local state to JSON/CSV files.",
        description="Snapshot local state to JSON/CSV files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  todo export\n  todo export --output-dir ~/snapshots",
    )
    export_p.add_argument(
        "--output-dir", type=str, default=None,
        help="Directory to write snapshot files (default: output.dir from config.yaml).",
    )

    # --- inspect -------------------------------------------------------------
    inspect_p = sub.add_parser(
        "inspect",
        help="Inspect local data (projects, stats, fields).",
        description="Inspect local data without hitting any service.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Targets:\n"
            "  projects [source]   List project/list/database IDs and names\n"
            "  stats               Counts, field coverage, date ranges per source\n"
            "  fields [source]     Unique values of status, priority, tags\n\n"
            "Examples:\n"
            "  todo inspect projects              all sources\n"
            "  todo inspect projects vikunja      just Vikunja projects + their IDs\n"
            "  todo inspect stats\n"
            "  todo inspect fields jira"
        ),
    )
    inspect_sub = inspect_p.add_subparsers(
        dest="target", metavar="<target>",
        parser_class=_ColoredSubParser,
    )

    projects_p = inspect_sub.add_parser(
        "projects",
        help="List project/list/database IDs and names.",
        description="List the organizational container of each task (project, list, database) "
                    "with its source ID. Useful for discovering IDs (e.g. for "
                    "vikunja.default_project_id).",
    )
    projects_p.add_argument(
        "source", nargs="?", choices=SOURCES,
        help="Filter to a single source. Default: all sources.",
    )

    inspect_sub.add_parser(
        "stats",
        help="Counts, field coverage, and date ranges per source.",
        description="Show a per-source overview: task count, status/priority distribution, "
                    "field coverage (description, due_date, tags, completed_date), and date ranges.",
    )

    fields_p = inspect_sub.add_parser(
        "fields",
        help="Show unique values of enum fields per source.",
        description="List distinct status and priority values observed in local data. "
                    "Useful for finding values that need mapping in config.yaml.",
    )
    fields_p.add_argument(
        "source", nargs="?", choices=SOURCES,
        help="Filter to a single source. Default: all sources.",
    )

    # --- help ----------------------------------------------------------------
    help_p = sub.add_parser(
        "help",
        help="Show help for a command.",
        description="Show detailed help for a specific command.",
    )
    help_p.add_argument(
        "topic", nargs="?",
        help="Command to show help for (e.g. 'pull', 'inspect'). "
             "Default: top-level help.",
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Bare `todo` and `-h/--help` both print top-level help and exit 0.
    if getattr(args, "help", False) or args.command is None:
        _print_colored(_TOP_LEVEL_HELP)
        return 0

    command = args.command
    if command == "help":
        return _cmd_help(parser, args.topic)

    # Commands that don't need config
    if command == "inspect":
        return _cmd_inspect(args)

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
        return _cmd_pull(config, services)[0]
    elif command == "push":
        return _cmd_push(config, services)
    elif command == "sync":
        return _cmd_sync(config, services)

    return 1


def _cmd_help(parser: argparse.ArgumentParser, topic: str | None) -> int:
    """Print top-level help, or help for a specific subcommand."""
    if topic is None:
        _print_colored(_TOP_LEVEL_HELP)
        return 0

    if topic in _SUB_HELP:
        _print_colored(_SUB_HELP[topic])
        return 0

    console.print(f"[red]Unknown command:[/] {topic}")
    console.print("Run [bold green]'todo help'[/] to see available commands.")
    return 1


def _resolve_services(config: dict, requested: list[str]) -> tuple[list[str], str | None]:
    """Validate and resolve service names. Returns (services, error_message)."""
    if requested:
        invalid = [s for s in requested if s not in SOURCES]
        if invalid:
            return [], f"Unknown service(s): {', '.join(invalid)}. Valid: {', '.join(SOURCES)}"
        return requested, None
    return enabled_sources(config), None


def _cmd_pull(config: dict, services: list[str]) -> tuple[int, list[str]]:
    """Pull from specified services into local state."""
    from src.normalizer import normalize
    from src.local_state import load_local_state, save_local_state, merge_pulled_items
    from src.mapping import SyncMapping

    db_path = config.get("mapping", {}).get("db_path", "mapping.db")
    state_path = Path(config["output"]["dir"]) / "todos.json"

    had_errors = False
    all_stats = []
    succeeded: list[str] = []

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

            # Apply per-source mapping migrations (e.g. legacy id formats)
            source_def.migrate(mapping, raw_items)

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
            succeeded.append(service)

        save_local_state(local_items, state_path)

    # Summary
    _print_pull_summary(all_stats, len(local_items))
    return (1 if had_errors else 0), succeeded


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
                result = source_def.push(config[service], local_items, console, mapping=mapping)
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
    """Pull all specified services, then push to those that pulled cleanly.

    A failed pull leaves local state stale for that service; pushing back
    would overwrite remote changes with stale data. Push only to services
    that pulled successfully.
    """
    pull_result, succeeded = _cmd_pull(config, services)
    skipped = [s for s in services if s not in succeeded]
    if skipped:
        console.print(
            f"[yellow]Skipping push for failed pulls:[/] {', '.join(skipped)}"
        )
    if not succeeded:
        console.print("[bold yellow]No services pulled successfully — nothing to push.[/]")
        return 1
    push_result = _cmd_push(config, succeeded)
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


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Inspect local data. Does not hit any service."""
    from src.local_state import load_local_state
    from src.config import load_config as _load

    target = getattr(args, "target", None)
    if target is None:
        console.print("[red]Usage:[/] todo inspect <target> [args]")
        console.print(f"Targets: {', '.join(INSPECT_TARGETS)}")
        console.print("Run 'todo help inspect' for details.")
        return 1

    # Load state file — use config.output.dir if available, else ./output
    try:
        config = _load(Path(args.config) if args.config else None)
        state_dir = Path(config["output"]["dir"])
    except ConfigError:
        state_dir = Path("./output")

    state_path = state_dir / "todos.json"
    items = load_local_state(state_path)
    if not items:
        console.print(
            f"[yellow]No local data at {state_path}.[/] Run 'todo pull' first."
        )
        return 1

    source_filter = getattr(args, "source", None)

    if target == "projects":
        return _inspect_projects(items, source_filter)
    if target == "stats":
        return _inspect_stats(items)
    if target == "fields":
        return _inspect_fields(items, source_filter)

    console.print(f"[red]Unknown inspect target:[/] {target}")
    return 1


def _inspect_projects(items: list[dict], source_filter: str | None) -> int:
    """List unique category (project/list/database) IDs and their task counts."""
    # (source, category_id, category_name, category_type) → count
    counts: dict[tuple, int] = {}
    for item in items:
        src = item.get("source") or ""
        if source_filter and src != source_filter:
            continue
        cat = item.get("category") or {}
        key = (src, cat.get("id"), cat.get("name"), cat.get("type"))
        counts[key] = counts.get(key, 0) + 1

    if not counts:
        msg = f"source '{source_filter}'" if source_filter else "any source"
        console.print(f"[yellow]No categories found for {msg}.[/]")
        return 0

    table = Table(title="Projects / Lists / Databases")
    table.add_column("Source", style="bold")
    table.add_column("Type")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Tasks", justify="right")

    # Sort by source, then tasks desc
    for (src, cid, name, ctype), n in sorted(
        counts.items(), key=lambda kv: (kv[0][0], -kv[1])
    ):
        table.add_row(
            src, ctype or "", str(cid) if cid is not None else "",
            name or "(no name)", str(n),
        )

    console.print(table)
    console.print(
        "[dim]Use 'id' from the Vikunja row as 'vikunja.default_project_id' "
        "in config.yaml to push cross-source tasks there.[/]"
    )
    return 0


def _inspect_stats(items: list[dict]) -> int:
    """Per-source counts, field coverage, and date ranges."""
    by_source: dict[str, list[dict]] = {}
    for item in items:
        by_source.setdefault(item.get("source") or "?", []).append(item)

    table = Table(title="Stats per source")
    table.add_column("Source", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Has desc", justify="right")
    table.add_column("Has due", justify="right")
    table.add_column("Has tags", justify="right")
    # "Has comp date", not "Has completed" — Notion never emits a completion
    # timestamp even when status=done, so this measures the field's presence,
    # not actual completion. Use the Status distribution table for done counts.
    table.add_column("Has comp date", justify="right")
    table.add_column("Oldest created")
    table.add_column("Newest updated")

    for src in sorted(by_source):
        xs = by_source[src]
        n = len(xs)
        has_desc = sum(1 for x in xs if x.get("description"))
        has_due = sum(1 for x in xs if x.get("due_date"))
        has_tags = sum(1 for x in xs if x.get("tags"))
        has_comp = sum(1 for x in xs if x.get("completed_date"))
        # Compare on the YYYY-MM-DD prefix only — full-string min/max would
        # mis-order mixed timezone formats (e.g. "...+0000" sorts before "...Z"
        # for the same instant).
        created = [x["created_date"][:10] for x in xs if x.get("created_date")]
        updated = [x["updated_date"][:10] for x in xs if x.get("updated_date")]
        table.add_row(
            src, str(n),
            f"{has_desc}/{n}", f"{has_due}/{n}",
            f"{has_tags}/{n}", f"{has_comp}/{n}",
            min(created) if created else "—",
            max(updated) if updated else "—",
        )

    console.print(table)

    # Status distribution
    dist = Table(title="Status distribution")
    dist.add_column("Source", style="bold")
    for s in ("todo", "in_progress", "done", "cancelled"):
        dist.add_column(s, justify="right")
    for src in sorted(by_source):
        xs = by_source[src]
        counts = {s: sum(1 for x in xs if x.get("status") == s)
                  for s in ("todo", "in_progress", "done", "cancelled")}
        dist.add_row(src, *[str(counts[s]) for s in ("todo", "in_progress", "done", "cancelled")])
    console.print(dist)

    return 0


def _inspect_fields(items: list[dict], source_filter: str | None) -> int:
    """Show unique status/priority/tag values — useful for spotting unmapped values."""
    by_source: dict[str, list[dict]] = {}
    for item in items:
        src = item.get("source") or "?"
        if source_filter and src != source_filter:
            continue
        by_source.setdefault(src, []).append(item)

    if not by_source:
        msg = f"source '{source_filter}'" if source_filter else "any source"
        console.print(f"[yellow]No data for {msg}.[/]")
        return 0

    for src in sorted(by_source):
        xs = by_source[src]
        statuses = sorted({x.get("status") for x in xs if x.get("status")})
        priorities = sorted({x.get("priority") for x in xs if x.get("priority")})
        tag_counts: dict[str, int] = {}
        for x in xs:
            for t in x.get("tags") or []:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda kv: -kv[1])[:10]

        console.print(f"[bold]{src}[/] ({len(xs)} tasks)")
        console.print(f"  status:    {', '.join(statuses) or '—'}")
        console.print(f"  priority:  {', '.join(priorities) or '—'}")
        if top_tags:
            tag_str = ", ".join(f"{t}×{n}" for t, n in top_tags)
            console.print(f"  top tags:  {tag_str}")
        console.print()

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
