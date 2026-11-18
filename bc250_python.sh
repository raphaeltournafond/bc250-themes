#!/usr/bin/env bash
# The Python the monitor runs with, kept working when the system's Python is upgraded.
# Usage: bash bc250_python.sh APP_DIR [--print | --run]
#   --print (default)  make sure there is a Python with the monitor's libraries, and print its path
#   --run              the same, then start the monitor with it (the autostart service's command)
#
# An upgrade of the system's Python (Bazzite going from 3.14 to 3.15, say) breaks the monitor twice: the app's .venv
# points at the new interpreter with the libraries installed for the old one, and the app refuses a Python newer than
# its release was tested with. This rebuilds .venv for the Python there is now, with the newest version of each library
# that has a ready-made package for it (the app's requirements.txt pins versions that may not exist yet for a brand new
# Python, and Bazzite has no compiler to build them), and --run lets the app start on it. Nothing is installed
# system-wide.
set -uo pipefail

APP="${1:-}"
MODE="${2:---print}"
if [[ -z "$APP" || ! -f "$APP/main.py" ]]; then
  sed -n '3,5p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
fi
VENV="$APP/.venv"
MODULES="serial yaml psutil PIL babel requests ping3 uptime numpy usb Crypto GPUtil"  # what the monitor must import
PACKAGES="pyserial PyYAML psutil Pillow babel requests ping3 uptime numpy pyusb pycryptodome ruamel.yaml pystray"
# GPUtil (Nvidia, imported even without one) from where the app takes it: the PyPI release broke with Python 3.12
GPUTIL="$(sed -n 's/^\(GPUtil @ [^ ;]*\).*/\1/p' "$APP/requirements.txt" 2>/dev/null | head -1)"
GPUTIL="${GPUTIL:-GPUtil @ git+https://github.com/mathoudebine/gputil.git@1.4.1-py3.13}"

log() { echo "bc250_python: $*" >&2; }
works() { [[ -n "$1" && -x "$1" ]] && "$1" -c "import importlib, sys; [importlib.import_module(m) for m in sys.argv[1:]]" \
          $MODULES >/dev/null 2>&1; }

find_python() {  # the app's venv first, then the system's Python if the libraries were installed for it
  local candidate
  for candidate in "$VENV/bin/python" "$APP/venv/bin/python" "$(command -v python3 || true)"; do
    if works "$candidate"; then echo "$candidate"; return 0; fi
  done
  return 1
}

build_venv() {
  local system
  system="$(command -v python3)" || { log "no python3 on this system"; return 1; }
  if "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then  # a venv of this Python, a library missing: complete it
    log "completing the monitor's Python libraries in $VENV"
  else
    if [[ -e "$VENV" ]]; then
      log "$VENV can't run the monitor with $("$system" --version 2>&1) (its libraries were installed for another" \
          "Python): rebuilding it"
    else
      log "installing the monitor's Python libraries in $VENV (private to the app, nothing system-wide)"
    fi
    "$system" -m venv --clear "$VENV" || { log "python3 -m venv failed"; return 1; }
    "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip || true
  fi
  # --prefer-binary: a slightly older release with a ready-made package rather than a newer one to compile
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --prefer-binary $PACKAGES "$GPUTIL" \
    || { log "pip could not install the libraries (see above)"; return 1; }
  works "$VENV/bin/python" || { log "the libraries are still incomplete in $VENV: $(missing "$VENV/bin/python")"; return 1; }
}

missing() {  # the modules a Python can't import
  "$1" -c "
import importlib, sys
gone = []
for m in sys.argv[1:]:
    try:
        importlib.import_module(m)
    except Exception:
        gone.append(m)
print(' '.join(gone))" $MODULES 2>&1
}

PYTHON="$(find_python)" || { build_venv >&2 && PYTHON="$VENV/bin/python"; } || {  # (stdout: only the path)
  if [[ "$MODE" == "--run" ]]; then
    log "the monitor can't start without its libraries; trying again in a minute (offline at boot?)"
    sleep 60  # the service then restarts and tries again
  fi
  exit 1
}

if [[ "$MODE" == "--run" ]]; then
  cd "$APP" || exit 1
  # The app refuses a Python newer than its release was tested with ("Python 3.15 is not supported by this program"),
  # and Bazzite moves to each new Python soon after it comes out: let it start, and say so in the log.
  exec "$PYTHON" -c '
import runpy, sys
import library.pythoncheck as check
if sys.platform != "win32" and sys.version_info[:2] > tuple(check.MAX_PYTHON):
    print("[BC250] Python %d.%d is newer than this release of the app was tested with (up to %d.%d): starting anyway"
          % (sys.version_info[:2] + tuple(check.MAX_PYTHON)), flush=True)
    check.MAX_PYTHON = sys.version_info[:2]
sys.argv = ["main.py"]
runpy.run_path("main.py", run_name="__main__")
'
fi
echo "$PYTHON"
