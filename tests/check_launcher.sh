#!/usr/bin/env bash
# Checks bc250_python.sh, the monitor's launcher, through an upgrade of the system's Python, with real installs.
# Usage (Linux, needs git and the network):  bash tests/check_launcher.sh OLD_PYTHON NEW_PYTHON
#   for example  bash tests/check_launcher.sh python3.14 python3.15
# 1. fresh install on OLD: the app's .venv gets every library, and only its path is printed
# 2. the system's python3 becomes NEW, as when Bazzite upgrades it: .venv is rebuilt for NEW
# 3. a library is missing (GPUtil, as on the BC-250 after 3.15): .venv is completed, not rebuilt
# 4. --run starts the app although its release refuses a Python that new
# The app is a stand-in that says which Python ran it: the real one would look for the screen.
set -uo pipefail

usage() { sed -n '3,4p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
if ! OLD="$(command -v "${1:-}")" || ! NEW="$(command -v "${2:-}")"; then usage; fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
APP="$WORK/app" BIN="$WORK/bin"
VENV_PYTHON="$APP/.venv/bin/python"
FAILED=0

mkdir -p "$APP/library" "$BIN"
cat > "$APP/library/pythoncheck.py" <<'EOF'
import sys
MIN_PYTHON = (3, 9)
MAX_PYTHON = (3, 9)  # older than any Python this runs with: the launcher must start the app anyway


def check_python_version():
    if sys.version_info[:2] > MAX_PYTHON:
        print("Python %d.%d is not supported by this program" % sys.version_info[:2])
        sys.exit(0)
EOF
cat > "$APP/main.py" <<'EOF'
from library.pythoncheck import check_python_version
check_python_version()
import sys, GPUtil, PIL, numpy, yaml, serial  # noqa: E401,F401
print("STARTED with Python %d.%d" % sys.version_info[:2])
EOF
# the app's own line for GPUtil, which the launcher reads
echo 'GPUtil @ git+https://github.com/mathoudebine/gputil.git@1.4.1-py3.13 ; python_version >= "3.12"' \
  > "$APP/requirements.txt"

check() {  # check "what" COMMAND...
  local what="$1"; shift
  if "$@"; then echo "PASS $what"; else echo "FAIL $what"; FAILED=1; fi
}
system_python() { ln -sf "$1" "$BIN/python3"; }  # what python3 is on this system
launcher() { PATH="$BIN:$PATH" bash "$REPO/bc250_python.sh" "$APP" "$@" 2>>"$WORK/log"; }
version() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }
imports() { "$1" -c "import $2" 2>/dev/null; }
logged() { grep -q "$1" "$WORK/log"; }
show_log() { sed 's/^/    /' "$WORK/log"; : > "$WORK/log"; }
OLD_V="$(version "$OLD")" NEW_V="$(version "$NEW")"
echo "Launcher: Python $OLD_V, then the system moves to $NEW_V"

# 1. fresh install
system_python "$OLD"
out="$(launcher)"
check "fresh install on $OLD_V: prints the path of the app's .venv, nothing else" test "$out" = "$VENV_PYTHON"
check "fresh install on $OLD_V: .venv runs Python $OLD_V" test "$(version "$VENV_PYTHON")" = "$OLD_V"
check "fresh install on $OLD_V: GPUtil and Pillow import" imports "$VENV_PYTHON" "GPUtil, PIL, numpy"
show_log

# 2. the system's Python is upgraded under the venv
system_python "$NEW"
stranded() { [[ "$(version "$VENV_PYTHON")" == "$NEW_V" ]] && ! imports "$VENV_PYTHON" PIL; }
check "after the upgrade, .venv runs $NEW_V without its libraries (the BC-250's case)" stranded
out="$(launcher)"
check "upgrade to $NEW_V: .venv rebuilt, its path printed" test "$out" = "$VENV_PYTHON"
check "upgrade to $NEW_V: the log says it rebuilt .venv" logged "rebuilding it"
check "upgrade to $NEW_V: every library imports" imports "$VENV_PYTHON" "GPUtil, PIL, numpy, yaml, serial, psutil, usb"
show_log

# 3. one library missing: completed in place
"$VENV_PYTHON" -m pip uninstall --quiet --yes GPUtil >/dev/null 2>&1
touch "$APP/.venv/kept"  # a rebuild (venv --clear) would remove it
out="$(launcher)"
check "GPUtil missing: installed again" imports "$VENV_PYTHON" GPUtil
check "GPUtil missing: .venv completed, not rebuilt" test -e "$APP/.venv/kept"
check "GPUtil missing: the log says so" logged "completing"
show_log

# 4. --run on a Python newer than the app's release accepts
out="$(launcher --run)"
check "--run: the app starts on Python $NEW_V although it refuses it" grep -q "STARTED with Python $NEW_V" <<< "$out"
check "--run: the log says it started anyway" grep -q "starting anyway" <<< "$out"
printf '%s\n' "$out" | sed 's/^/    /'

# 5. already working: nothing installed, quick
start=$SECONDS
out="$(launcher)"
quiet() { [[ "$out" == "$VENV_PYTHON" && $((SECONDS - start)) -lt 15 && ! -s "$WORK/log" ]]; }
check "working .venv: path printed at once, nothing installed" quiet
show_log

[[ "$FAILED" == 0 ]] && echo "ALL PASSED: launcher" || echo "FAILED: launcher"
exit "$FAILED"
