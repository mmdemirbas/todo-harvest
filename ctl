#!/usr/bin/env bash
#
# ./ctl — one entry point. Each operation is an op_ function below and
# ajans.toml says what each one does; the ajans block at the end prints the
# list from it and dispatches (contract: ajans/docs/project-contract.md).
#
#   ./ctl                 the operations, one `name<TAB>description` per line
#   ./ctl <verb> --list   what that verb takes - the service names, mostly
#   ./ctl <verb> --help   a verb's own flags
#   ./ctl --config <path> <verb> ...   the CLI's own options go in front
#   ./ctl --version       the CLI's version
#   ./ctl --check         whether ajans.toml and this file agree
#
# Listing reads ajans.toml only: it no longer builds the venv or runs Python
# from the project.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
# The venv's own interpreter, by path.
#
# Rather than `source activate` and then bare `python`: activate works by putting
# a hardcoded absolute path on PATH, so it is the part that breaks when the
# checkout moves.
PYTHON="$VENV_DIR/bin/python"

need_python() {
    if ! command -v python3 &>/dev/null; then
        echo "Error: python3 not found. Install Python 3.10+ and try again." >&2
        exit 1
    fi
    python3 -c "
import sys
if sys.version_info < (3, 10):
    print(f'Error: Python 3.10+ required, found {sys.version}', file=sys.stderr)
    sys.exit(1)
" || exit 1
}

build_venv() {
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
    "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements-dev.txt"
}

# Bootstrap the venv when there is not a working one, then put it in use.
#
# By whether its interpreter runs, not by whether the directory exists. A venv
# records the absolute path it was built at, in `bin/activate` and in
# `pyvenv.cfg`, so moving the checkout leaves a directory that is still there
# and no longer works - which is how this script came to fail with
# "exec: python: not found" while `.venv/bin/python` sat there working fine.
use_venv() {
    need_python
    if ! "$PYTHON" -c "" 2>/dev/null; then
        if [ -d "$VENV_DIR" ]; then
            echo "The virtual environment does not run here — rebuilding it..."
            rm -rf "$VENV_DIR"
        else
            echo "First run — setting up virtual environment..."
        fi
        build_venv
        echo "Setup complete."
        echo ""
    fi
    # VIRTUAL_ENV is still exported, because tools look for it.
    export VIRTUAL_ENV="$VENV_DIR"
    PATH="$VENV_DIR/bin:$PATH"
    export PATH
    # `-m src.main` resolves against the import path, so the package has to be
    # on it whatever directory the caller is standing in. PYTHONPATH rather than
    # a `cd`, so a relative path passed as an argument still means what the
    # caller meant.
    export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
}

# The CLI's own commands (src/main.py). Every one of them is an operation
# below; tests/test_ctl.py fails when a command, ajans.toml and this file stop
# naming the same set.
cli() {
    use_venv
    exec "$PYTHON" -m src.main ${CLI_OPTS[@]+"${CLI_OPTS[@]}"} "$@"
}

# Options in front of the operation are the CLI's own: `./ctl --config
# other.yaml pull`, `./ctl --version`. The ajans block below dispatches on the
# first word, so they are taken off here and cli() puts them back in front of
# the command; with no operation after them they go to the CLI as they are.
# tests/test_ctl.py holds this list to the parser's top-level options.
CLI_OPTS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            if [[ $# -lt 2 ]]; then
                echo "Error: --config needs a path." >&2
                exit 64
            fi
            CLI_OPTS+=("$1" "$2")
            shift 2
            ;;
        --config=* | -V | --version)
            CLI_OPTS+=("$1")
            shift
            ;;
        *) break ;;
    esac
done
if [[ $# -eq 0 && ${#CLI_OPTS[@]} -gt 0 ]]; then
    cli
fi

# The operations the driver does by itself never reach the CLI; an option in
# front of one is refused rather than dropped.
no_cli_opts() {
    if [[ ${#CLI_OPTS[@]} -gt 0 ]]; then
        echo "Error: '$1' does not take ${CLI_OPTS[*]}; those are the CLI's options." >&2
        exit 64
    fi
}

# --- operations ------------------------------------------------------------

op_test() {
    no_cli_opts test
    use_venv
    exec "$PYTHON" -m pytest --cov=src --cov-report=term-missing "$@"
}

# use_venv only rebuilds a venv that does not run. This forces it, which is
# what you want after editing requirements.
op_setup() {
    no_cli_opts setup
    need_python
    rm -rf "$VENV_DIR"
    build_venv
    echo "Rebuilt $VENV_DIR"
}

op_pull()         { cli pull "$@"; }
op_pull_vikunja() { cli pull vikunja "$@"; }
op_pull_jira()    { cli pull jira "$@"; }
op_pull_mstodo()  { cli pull mstodo "$@"; }
op_pull_notion()  { cli pull notion "$@"; }
op_pull_plane()   { cli pull plane "$@"; }

op_push()         { cli push "$@"; }
op_push_vikunja() { cli push vikunja "$@"; }
op_push_plane()   { cli push plane "$@"; }

op_sync()         { cli sync "$@"; }
op_sync_vikunja() { cli sync vikunja "$@"; }
op_sync_plane()   { cli sync plane "$@"; }

op_export() { cli export "$@"; }

op_inspect_projects() { cli inspect projects "$@"; }
op_inspect_stats()    { cli inspect stats "$@"; }
op_inspect_fields()   { cli inspect fields "$@"; }

op_help() { cli help "$@"; }

# >>> ajans runtime 2 >>>
# Written by `ajans contract sync`; edits here are overwritten. The operations
# are declared in ajans.toml and implemented above as op_<verb>[_<target>].

# Where this file is. A relative path was relative to where ctl was started,
# and the driver may have changed directory since - usually into its own, with
# `cd "$(dirname "$0")"` - so it is tried against here, then against where the
# last cd came from, and failing both the directory the driver changed into.
# A function rather than inline: bash 3.2 cannot parse a `case` inside `$(...)`.
_ajans_where() {
	local src="${BASH_SOURCE[0]}" base
	case "$src" in
		/*) ;;
		*)
			for base in "$PWD" "${OLDPWD:-}"; do
				if [[ -n "$base" && -f "$base/$src" ]]; then
					src="$base/$src"
					break
				fi
			done
			;;
	esac
	case "$src" in
		/*) ;;
		*) src="$PWD/${src##*/}" ;;
	esac
	(cd "$(dirname "$src")" && pwd)
}
_ajans_root="$(_ajans_where)"

_ajans_fn() {
	local name="op_$*"
	name="${name// /_}"
	name="${name//-/_}"
	printf '%s' "${name//./_}"
}

# Reads ajans.toml with the first python3 that has tomllib. Modes: list [verb], keys.
_ajans_toml() {
	local py
	if [[ ! -f "$_ajans_root/ajans.toml" ]]; then
		printf '✗ no ajans.toml beside %s\n' "$_ajans_root/ctl" >&2
		return 66
	fi
	for py in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
		if ! command -v "$py" >/dev/null 2>&1 || ! "$py" -c 'import tomllib' 2>/dev/null; then
			continue
		fi
		"$py" - "$_ajans_root/ajans.toml" "$@" <<'PY'
import re, sys, tomllib
try:
    with open(sys.argv[1], 'rb') as f:
        manifest = tomllib.load(f)
except tomllib.TOMLDecodeError as e:
    sys.exit(f'✗ ajans.toml: {e}')
ops, verbs = manifest.get('operations', {}), manifest.get('verbs', {})
mode, rest = sys.argv[2], sys.argv[3:]
if mode == 'keys':
    for key in ops:
        print('op_' + re.sub(r'[ .-]', '_', key))
elif rest:
    for key, op in ops.items():
        verb, _, target = key.partition(' ')
        if verb == rest[0] and target:
            print(f"{target}\t{op.get('summary', '')}")
else:
    seen = []
    for key in ops:
        verb = key.partition(' ')[0]
        if verb not in seen:
            seen.append(verb)
            print(f"{verb}\t{ops[verb]['summary'] if verb in ops else verbs.get(verb, '')}")
PY
		return
	done
	printf '✗ reading ajans.toml needs python3 3.11 or later (tomllib)\n' >&2
	return 69
}

_ajans_check() {
	local declared defined missing extra fn count noun
	declared="$(_ajans_toml keys)" || return
	declared="$(printf '%s\n' "$declared" | sort)"
	defined="$(declare -F | awk '$3 ~ /^op_/ { print $3 }' | sort)"
	missing="$(comm -23 <(printf '%s\n' "$declared") <(printf '%s\n' "$defined") | sed '/^$/d')"
	extra="$(comm -13 <(printf '%s\n' "$declared") <(printf '%s\n' "$defined") | sed '/^$/d')"
	if [[ -z "$missing" && -z "$extra" ]]; then
		count="$(printf '%s\n' "$declared" | grep -c .)"
		if [[ "$count" == 1 ]]; then noun=operation; else noun=operations; fi
		printf '✓ ajans.toml and ctl agree: %s %s\n' "$count" "$noun"
		return 0
	fi
	if [[ -n "$missing" ]]; then
		while IFS= read -r fn; do printf '✗ declared, no function: %s\n' "$fn" >&2; done <<<"$missing"
	fi
	if [[ -n "$extra" ]]; then
		while IFS= read -r fn; do printf '✗ function, not declared: %s\n' "$fn" >&2; done <<<"$extra"
	fi
	return 1
}

_ajans_main() {
	case "${1:-}" in
	'' | --list | -h | --help)
		_ajans_toml list
		return
		;;
	--check)
		_ajans_check
		return
		;;
	esac
	if [[ "${2:-}" == --list ]]; then
		_ajans_toml list "$1"
		return
	fi
	local fn
	if [[ $# -ge 2 ]]; then
		fn="$(_ajans_fn "$1 $2")"
		if declare -F "$fn" >/dev/null; then
			shift 2
			"$fn" "$@"
			return
		fi
	fi
	fn="$(_ajans_fn "$1")"
	if declare -F "$fn" >/dev/null; then
		shift
		"$fn" "$@"
		return
	fi
	if declare -F | awk -v p="$fn"_ '$3 ~ "^" p { found = 1 } END { exit !found }'; then
		printf '✗ %s needs a target: ./ctl %s --list\n' "$1" "$1" >&2
	else
		printf '✗ %s: not an operation of this project (./ctl --list)\n' "$*" >&2
	fi
	return 64
}

_ajans_main "$@"
# <<< ajans runtime <<<
