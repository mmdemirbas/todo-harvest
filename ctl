#!/usr/bin/env bash
#
# ./ctl — one entry point. Bootstraps the venv, then hands the verb to the CLI.
#
#   ./ctl               the verbs, with what each one does
#   ./ctl --list        the same, one `name<TAB>description` per line
#   ./ctl <verb> --list what that verb takes - the service names, mostly
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Check Python is available
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.10+ and try again." >&2
    exit 1
fi

# Check Python version (need 3.10+)
python3 -c "
import sys
if sys.version_info < (3, 10):
    print(f'Error: Python 3.10+ required, found {sys.version}', file=sys.stderr)
    sys.exit(1)
" || exit 1

# Bootstrap the venv when there is not a working one.
#
# By whether its interpreter runs, not by whether the directory exists. A venv
# records the absolute path it was built at, in `bin/activate` and in
# `pyvenv.cfg`, so moving the checkout leaves a directory that is still there
# and no longer works - which is how this script came to fail with
# "exec: python: not found" while `.venv/bin/python` sat there working fine.
if ! "$VENV_DIR/bin/python" -c "" 2>/dev/null; then
    if [ -d "$VENV_DIR" ]; then
        echo "The virtual environment does not run here — rebuilding it..."
        rm -rf "$VENV_DIR"
    else
        echo "First run — setting up virtual environment..."
    fi
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
    "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements-dev.txt"
    echo "Setup complete."
    echo ""
fi

# The venv's own interpreter, by path.
#
# Rather than `source activate` and then bare `python`: activate works by putting
# a hardcoded absolute path on PATH, so it is the part that breaks when the
# checkout moves. VIRTUAL_ENV is still exported, because tools look for it.
export VIRTUAL_ENV="$VENV_DIR"
PATH="$VENV_DIR/bin:$PATH"
export PATH
PYTHON="$VENV_DIR/bin/python"

# `-m src.main` resolves against the import path, so the package has to be on it
# whatever directory the caller is standing in. PYTHONPATH rather than a `cd`,
# so a relative path passed as an argument still means what the caller meant.
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# --- what can be asked for -------------------------------------------------
#
# The verb list is read out of the CLI's own argparse rather than repeated here.
# A list that is repeated is a list that goes stale; this one cannot.

SHELL_VERBS="test	Run the test suite with coverage
setup	Rebuild the virtual environment from requirements"

list_verbs() {
    printf '%s\n' "$SHELL_VERBS"
    "$PYTHON" - <<'PYVERBS'
from src.main import build_parser

for action in build_parser()._subparsers._group_actions:
    for choice in action._choices_actions:
        if choice.dest != "help":
            print(f"{choice.dest}\t{choice.help or ''}")
PYVERBS
}

# A verb's qualifiers: the services for pull/push/sync, the targets for inspect.
list_qualifiers() {
    "$PYTHON" - "$1" <<'PYQUALS'
import sys

from src.config import SOURCES
from src.main import build_parser

verb = sys.argv[1]
if verb in ("pull", "push", "sync"):
    for source in SOURCES:
        print(f"{source}\t")
    sys.exit(0)

for action in build_parser()._subparsers._group_actions:
    sub = action.choices.get(verb)
    if sub is None:
        continue
    for inner in getattr(sub, "_subparsers", None)._group_actions if sub._subparsers else []:
        for choice in inner._choices_actions:
            print(f"{choice.dest}\t{choice.help or ''}")
    sys.exit(0)
sys.exit(1)
PYQUALS
}

usage() {
    echo "todo-harvest — ./ctl <verb> [args]"
    echo ""
    list_verbs | while IFS="$(printf '\t')" read -r name why; do
        printf '  %-9s %s\n' "$name" "$why"
    done
    echo ""
    echo "  What a verb takes:   ./ctl <verb> --list"
    echo "  A verb's own flags:  ./ctl <verb> --help"
}

# --- dispatch --------------------------------------------------------------

cmd="${1:-}"; shift || true

case "$cmd" in
    ''|-h|--help)  usage; exit 0 ;;
    --list)        list_verbs; exit 0 ;;
esac

# First position only: further along it belongs to the CLI.
if [ "${1:-}" = "--list" ]; then
    list_qualifiers "$cmd" || { echo "no qualifiers: $cmd" >&2; exit 1; }
    exit 0
fi

case "$cmd" in
    test)  exec "$PYTHON" -m pytest --cov=src --cov-report=term-missing "$@" ;;
    setup)
        # The bootstrap above only fires when the venv does not run. This forces
        # it, which is what you want after editing requirements.
        rm -rf "$VENV_DIR"
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --quiet --upgrade pip
        "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
        "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements-dev.txt"
        echo "Rebuilt $VENV_DIR"
        exit 0
        ;;
esac

exec "$PYTHON" -m src.main "$cmd" "$@"
