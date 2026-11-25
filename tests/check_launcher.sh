#!/usr/bin/env bash
# Checks bc250_python.sh, the monitor's launcher, through an upgrade of the system's Python, with real installs and the
# real app (turing-smart-screen-python 3.10.0, on its simulated display: no screen needed).
# Usage (Linux, needs git and the network):  bash tests/check_launcher.sh OLD_PYTHON NEW_PYTHON
#   for example  bash tests/check_launcher.sh python3.14 python3.15
# 1. fresh install on OLD: the app's .venv gets every library, and only its path is printed
# 2. the system's python3 becomes NEW, as when Bazzite upgrades it, and install_bc250.sh is run: .venv is rebuilt for
#    NEW before the theme is generated with it
# 3. a library is missing (GPUtil, as on the BC-250 after 3.15): .venv is completed, not rebuilt
# 4. --run starts the app although its release refuses a Python that new, and it keeps running
# 5. everything in place: the path comes at once, nothing installed
set -uo pipefail

usage() { sed -n '4,5p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
if ! OLD="$(command -v "${1:-}")" || ! NEW="$(command -v "${2:-}")"; then usage; fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
APP="$WORK/app" BIN="$WORK/bin"
VENV_PYTHON="$APP/.venv/bin/python"
FAILED=0

mkdir -p "$BIN"
git -c advice.detachedHead=false clone --quiet --depth 1 --branch 3.10.0 \
  https://github.com/mathoudebine/turing-smart-screen-python "$APP" || { echo "FAIL could not fetch the app"; exit 1; }
# its release refuses any Python newer than it was tested with: make that every Python, so --run's bypass is always
# exercised; and no screen here
sed -i 's/^MAX_PYTHON = .*/MAX_PYTHON = (3, 9)/' "$APP/library/pythoncheck.py"
sed -i 's/^\(  REVISION:\).*/\1 SIMU/' "$APP/config.yaml"

check() {  # check "what" COMMAND...
  local what="$1"; shift
  if "$@"; then echo "PASS $what"; else echo "FAIL $what"; FAILED=1; fi
}
system_python() { ln -sf "$1" "$BIN/python3"; }  # what python3 is on this system
launcher() { PATH="$BIN:$PATH" bash "$REPO/bc250_python.sh" "$APP" 2>>"$WORK/log"; }  # --print
version() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }
imports() { "$1" -c "import $2" 2>/dev/null; }
logged() { grep -q "$1" "$WORK/log"; }
show_log() { sed 's/^/    /' "$WORK/log"; : > "$WORK/log"; }
OLD_V="$(version "$OLD")" NEW_V="$(version "$NEW")"
ALL="serial, yaml, psutil, PIL, babel, requests, ping3, uptime, numpy, usb, Crypto, GPUtil"
echo "Launcher: Python $OLD_V, then the system moves to $NEW_V"

# 1. fresh install
system_python "$OLD"
out="$(launcher)"
check "fresh install on $OLD_V: prints the path of the app's .venv, nothing else" test "$out" = "$VENV_PYTHON"
check "fresh install on $OLD_V: .venv runs Python $OLD_V" test "$(version "$VENV_PYTHON")" = "$OLD_V"
check "fresh install on $OLD_V: every library imports" imports "$VENV_PYTHON" "$ALL"
show_log

# 2. the system's Python is upgraded under the venv, then the theme is (re)installed
system_python "$NEW"
stranded() { [[ "$(version "$VENV_PYTHON")" == "$NEW_V" ]] && ! imports "$VENV_PYTHON" PIL; }
check "after the upgrade, .venv runs $NEW_V without its libraries (the BC-250's case)" stranded
PATH="$BIN:$PATH" bash "$REPO/install_bc250.sh" "$APP" --theme phosphor --user tester --host ci >>"$WORK/log" 2>&1
check "install_bc250.sh after the upgrade: .venv rebuilt first" logged "rebuilding it"
check "install_bc250.sh after the upgrade: the theme generated with it" logged "Wrote BC250-Phosphor"
check "install_bc250.sh after the upgrade: no fallback to the default artwork" bash -c "! grep -q WARNING '$WORK/log'"
check "upgrade to $NEW_V: .venv runs $NEW_V with every library" imports "$VENV_PYTHON" "$ALL"
show_log

# 3. one library missing: completed in place
"$VENV_PYTHON" -m pip uninstall --quiet --yes GPUtil >/dev/null 2>&1
touch "$APP/.venv/kept"  # a rebuild (venv --clear) would remove it
out="$(launcher)"
check "GPUtil missing: installed again" imports "$VENV_PYTHON" GPUtil
check "GPUtil missing: .venv completed, not rebuilt" test -e "$APP/.venv/kept"
check "GPUtil missing: the log says so" logged "completing"
show_log

# 4. --run: the real app with the theme, on a Python its release refuses; still running after 30 s
PATH="$BIN:$PATH" PYSTRAY_BACKEND=dummy timeout -k 5 30 bash "$REPO/bc250_python.sh" "$APP" --run >"$WORK/run" 2>&1
status=$?
check "--run: the app was still running after 30 s (exit $status, 124 = stopped by the check)" test "$status" = 124
check "--run: started on Python $NEW_V although its release refuses it" grep -q "starting anyway" "$WORK/run"
check "--run: no Python error" bash -c "! grep -qE 'Traceback|Import error|is not supported by this program' '$WORK/run'"
head -c 4000 "$WORK/run" | sed 's/^/    /'

# 5. already working: nothing installed, quick
start=$SECONDS
out="$(launcher)"
quiet() { [[ "$out" == "$VENV_PYTHON" && $((SECONDS - start)) -lt 15 && ! -s "$WORK/log" ]]; }
check "working .venv: path printed at once, nothing installed" quiet
show_log

if [[ "$FAILED" == 0 ]]; then echo "ALL PASSED: launcher"; else echo "FAILED: launcher"; fi
exit "$FAILED"
