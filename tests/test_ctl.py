"""`./ctl`, `ajans.toml` and the CLI name the same commands.

The driver used to hand any verb it did not know to `src.main` and read its
listing out of the parser, so a command added to the CLI could not go missing
from it. Under the ajans contract every operation is declared in `ajans.toml`
and has its own `op_` function in `ctl`; these tests are what notice when the
three stop naming the same set.
"""

import re
from pathlib import Path

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
