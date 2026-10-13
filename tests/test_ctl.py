"""`./ctl`, `ajans.toml` and the CLI name the same commands.

The driver used to hand any verb it did not know to `src.main` and read its
listing out of the parser, so a command added to the CLI could not go missing
from it. Under the ajans contract every operation is declared in `ajans.toml`
and has its own `op_` function in `ctl`; these tests are what notice when the
three stop naming the same set.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.main import build_parser
from src.sources import REGISTRY

ROOT = Path(__file__).resolve().parents[1]

# Operations the driver does by itself, with no CLI command behind them.
SHELL_ONLY = {"test", "setup"}


def _operations() -> set[str]:
    # A pattern rather than tomllib: CI runs on Python 3.10, which has none.
    text = (ROOT / "ajans.toml").read_text(encoding="utf-8")
    keys = re.findall(r'^\[operations\.(?:"([^"]+)"|([\w-]+))\]$', text, re.MULTILINE)
    return {quoted or bare for quoted, bare in keys}


def _targets(verb: str) -> set[str]:
    return {op.split(" ", 1)[1] for op in _operations() if op.startswith(verb + " ")}


def _subcommands(parser) -> dict:
    return {
        name: sub
        for action in parser._subparsers._group_actions
        for name, sub in action.choices.items()
    }


def test_every_command_is_an_operation():
    verbs = {op.split(" ", 1)[0] for op in _operations()} - SHELL_ONLY
    assert verbs == set(_subcommands(build_parser()))


def test_inspect_targets_are_the_clis():
    inspect = _subcommands(build_parser())["inspect"]
    assert _targets("inspect") == set(_subcommands(inspect))


def test_pull_targets_every_service():
    assert _targets("pull") == set(REGISTRY)


def test_push_and_sync_target_the_services_that_take_a_push():
    # The others print "Push not supported, skipping": a target for them would
    # be a button that does nothing.
    pushable = {name for name, source in REGISTRY.items() if source.push_supported}
    assert _targets("push") == pushable
    assert _targets("sync") == pushable


def test_each_operation_runs_its_own_command():
    ctl = (ROOT / "ctl").read_text(encoding="utf-8")
    calls = dict(re.findall(r'^op_(\w+)\(\)\s*\{\s*cli ([\w -]+?) "\$@"; \}$', ctl, re.MULTILINE))
    expected = {re.sub(r"[ .-]", "_", op): op for op in _operations() - SHELL_ONLY}
    assert calls == expected


# Options written in front of the operation are the CLI's own (`./ctl --config
# other.yaml pull`, `./ctl --version`). The ajans block dispatches on the first
# word, so ctl takes them off and puts them back in front of the command.


def _leading_options() -> set[str]:
    ctl = (ROOT / "ctl").read_text(encoding="utf-8")
    loop = ctl.split("\nCLI_OPTS=()\n", 1)[1].split("\ndone\n", 1)[0]
    labels = re.findall(r"^[ \t]+([^()\n]+)\)$", loop, re.MULTILINE)
    return {
        option
        for label in labels
        for option in (part.strip() for part in label.split("|"))
        if option.startswith("-") and not option.endswith("=*")
    }


def test_ctl_takes_off_every_top_level_option_of_the_cli():
    top_level = {
        option
        for action in build_parser()._actions
        if not isinstance(action, argparse._SubParsersAction)
        for option in action.option_strings
    }
    # -h/--help in front of everything is the ajans block's: it lists the operations.
    assert _leading_options() == top_level - {"-h", "--help"}


bash_only = pytest.mark.skipif(sys.platform == "win32", reason="ctl is a bash script")


@pytest.fixture
def ctl_copy(tmp_path: Path) -> Path:
    """ctl and ajans.toml in a scratch directory, with a venv python that prints its arguments."""
    for name in ("ctl", "ajans.toml"):
        shutil.copy2(ROOT / name, tmp_path / name)
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    # `-c ""` is use_venv asking whether the interpreter runs.
    python.write_text(
        '#!/bin/sh\n[ "$1" = -c ] && exit 0\nprintf "%s\\n" "$@"\n', encoding="utf-8"
    )
    python.chmod(0o755)
    return tmp_path


def _run(directory: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(directory / "ctl"), *args], capture_output=True, text=True, check=False
    )


@bash_only
@pytest.mark.parametrize(
    ("args", "cli_args"),
    [
        (["--config", "other.yaml", "pull"], ["--config", "other.yaml", "pull"]),
        (["--config=other.yaml", "pull", "jira"], ["--config=other.yaml", "pull", "jira"]),
        (["--config", "other.yaml", "push", "plane"], ["--config", "other.yaml", "push", "plane"]),
        (["--version"], ["--version"]),
        (["-V"], ["-V"]),
        (["--config", "other.yaml"], ["--config", "other.yaml"]),
        (["pull", "jira", "notion"], ["pull", "jira", "notion"]),
    ],
)
def test_leading_options_reach_the_cli(ctl_copy, args, cli_args):
    result = _run(ctl_copy, *args)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["-m", "src.main", *cli_args]


@bash_only
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--config"], "--config"),
        (["--config", "other.yaml", "test"], "'test'"),
        (["--version", "setup"], "'setup'"),
    ],
)
def test_an_option_with_nowhere_to_go_is_refused(ctl_copy, args, message):
    result = _run(ctl_copy, *args)
    assert result.returncode == 64
    assert message in result.stderr
    assert result.stdout == ""
