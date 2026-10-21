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

# >>> ajans runtime 3 >>>
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

# Reads ajans.toml with awk. Modes: list [verb], keys.
#
# awk and bash ship with the OS, so the listing and the check need nothing
# a package manager can move: version 2 looked for a python3 with tomllib,
# and one Homebrew upgrade was enough to lose it. /usr/bin/awk first, so a
# Homebrew gawk ahead of it on PATH is not what runs.
#
# It reads TOML as manifests are written - each operation an
# [operations.<key>] table, its summary a one-line string - and steps over
# every other value, multi-line ones included. A manifest written otherwise
# (dotted operation keys, inline operation tables, a multi-line summary) is
# refused with its line rather than read wrong.
_ajans_toml() {
	local awk=/usr/bin/awk
	if [[ ! -x "$awk" ]]; then awk="awk"; fi
	if [[ ! -f "$_ajans_root/ajans.toml" ]]; then
		printf '✗ no ajans.toml beside %s\n' "$_ajans_root/ctl" >&2
		return 66
	fi
	# shellcheck disable=SC2016 # the program is awk: its $ are fields, not expansions
	_AJANS_MODE="$1" _AJANS_VERB="${2:-}" LC_ALL=C "$awk" '
BEGIN { SQ = "\047"; DQ = "\""; mode = ENVIRON["_AJANS_MODE"]; verb = ENVIRON["_AJANS_VERB"] }
function fail(why) { if (BAD == "") BAD = "ajans.toml:" NR ": " why; exit }
function ws() { while (P <= length(L) && index(" \t", substr(L, P, 1))) P++ }
function at(s) { return substr(L, P, length(s)) == s }
function hex(h,   i, d, v) {
	for (i = 1; i <= length(h); i++) {
		d = index("0123456789abcdef", tolower(substr(h, i, 1)))
		if (d == 0) fail("an escape that is not hex: \\u" h)
		v = v * 16 + d - 1
	}
	return v
}
function utf8(c) {
	if (c < 128) return sprintf("%c", c)
	if (c < 2048) return sprintf("%c%c", 192 + int(c / 64), 128 + c % 64)
	if (c < 65536) return sprintf("%c%c%c", 224 + int(c / 4096), 128 + int(c / 64) % 64, 128 + c % 64)
	return sprintf("%c%c%c%c", 240 + int(c / 262144), 128 + int(c / 4096) % 64, 128 + int(c / 64) % 64, 128 + c % 64)
}
# A one-line "basic" string from P, its escapes decoded into S.
function basic(   c, n) {
	S = ""
	for (P++; P <= length(L); P++) {
		c = substr(L, P, 1)
		if (c == DQ) { P++; return }
		if (c != "\\") { S = S c; continue }
		c = substr(L, ++P, 1)
		if (c == "u" || c == "U") {
			n = c == "u" ? 4 : 8
			if (length(substr(L, P + 1, n)) < n) fail("a \\" c " escape cut short")
			S = S utf8(hex(substr(L, P + 1, n)))
			P += n
		} else if (index("btnfr" DQ "\\", c) == 0) fail("an escape TOML does not have: \\" c)
		else S = S (c == "b" ? "\b" : c == "t" ? "\t" : c == "n" ? "\n" : c == "f" ? "\f" : c == "r" ? "\r" : c)
	}
	fail("a string that does not end on its line")
}
# A one-line literal string from P into S.
function literal(   e) {
	e = index(substr(L, P + 1), SQ)
	if (e == 0) fail("a string that does not end on its line")
	S = substr(L, P + 1, e - 1)
	P += e + 1
}
# One key: bare, "basic" or literal, into S. 0 when there is none.
function part(   s) {
	ws()
	if (at(DQ)) { basic(); return 1 }
	if (at(SQ)) { literal(); return 1 }
	for (s = P; P <= length(L) && substr(L, P, 1) ~ /[A-Za-z0-9_-]/; P++);
	S = substr(L, s, P - s)
	return P > s
}
# A dotted key into K[1..KN].
function path() {
	KN = 0
	if (!part()) return 0
	K[++KN] = S
	for (ws(); at("."); ws()) {
		P++
		if (!part()) return 0
		K[++KN] = S
	}
	return 1
}
# Past a value, or to the end of its line when it goes on: ML (a multi-line
# string still open) and DEPTH (arrays and tables still open) carry on to the
# next line, where no key or header can begin.
function skip(   c) {
	while (P <= length(L)) {
		if (ML != "") {
			if (ML == DQ && at("\\")) { P += 2; continue }
			if (!at(ML ML ML)) { P++; continue }
			for (P += 3; at(ML); P++);
			ML = ""
			if (DEPTH == 0) return
			continue
		}
		c = substr(L, P, 1)
		if (at(DQ DQ DQ) || at(SQ SQ SQ)) { ML = c; P += 3; continue }
		if (c == DQ || c == SQ) {
			if (c == DQ) basic(); else literal()
			if (DEPTH == 0) return
			continue
		}
		if (c == "#") return
		if (c == "[" || c == "{") DEPTH++
		else if (c == "]" || c == "}") { if (--DEPTH == 0) { P++; return } }
		else if (DEPTH == 0 && index(" \t,", c)) return
		P++
	}
}
# A summary: a one-line string.
function text() {
	if (at(DQ DQ DQ) || at(SQ SQ SQ)) fail("a multi-line string; a summary is read on one line")
	if (at(DQ)) basic()
	else if (at(SQ)) literal()
	else fail("a summary that is not a string")
	return S
}
function header(   arrays) {
	P++
	arrays = at("[")
	if (arrays) P++
	if (!path()) fail("a table header it cannot read")
	ws()
	if (!at(arrays ? "]]" : "]")) fail("a table header with no closing bracket")
	if (K[1] != "operations" && K[1] != "verbs") { TABLE = "other"; return }
	if (arrays) fail("an array of tables; each operation is its own [operations.<key>] table")
	if (K[1] == "verbs" && KN > 1) fail("a table under [verbs]; each verb there is a string")
	if (KN == 1) { TABLE = K[1]; return }
	if (!(K[2] in SEEN)) { SEEN[K[2]] = 1; OPS[++N] = K[2] }
	OP = K[2]
	TABLE = KN == 2 ? "op" : "below"
}
function keyval() {
	if (!path()) fail("a line that is neither a [table] nor key = value")
	ws()
	if (!at("=")) fail("a key with no = after it")
	P++
	ws()
	if (TABLE == "op" && KN == 1 && K[1] == "summary") SUMMARY[OP] = text()
	else if (TABLE == "verbs" && KN == 1) VERBS[K[1]] = text()
	else if (TABLE == "operations" || TABLE == "verbs" || (TABLE == "" && (K[1] == "operations" || K[1] == "verbs")))
		fail("operations written as dotted keys or inline tables; each is read as its own [operations.<key>] table")
	else skip()
}
{
	L = $0
	sub(/\r$/, "", L)
	P = 1
	if (ML != "" || DEPTH > 0) { skip(); next }
	ws()
	if (P > length(L) || at("#")) next
	if (at("[")) header()
	else keyval()
}
END {
	if (BAD == "" && (ML != "" || DEPTH > 0)) BAD = "ajans.toml: a value that never ends"
	if (BAD != "") { printf "✗ %s\n", BAD > "/dev/stderr"; exit 65 }
	for (i = 1; i <= N; i++) {
		key = OPS[i]
		cut = index(key, " ")
		head = cut ? substr(key, 1, cut - 1) : key
		if (mode == "keys") { gsub(/[ .-]/, "_", key); print "op_" key }
		else if (verb != "") { if (head == verb && cut && cut < length(key)) print substr(key, cut + 1) "\t" SUMMARY[key] }
		else if (!(head in LISTED)) { LISTED[head] = 1; print head "\t" ((head in SEEN) ? SUMMARY[head] : VERBS[head]) }
	}
}' "$_ajans_root/ajans.toml"
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
