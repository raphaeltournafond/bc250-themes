#!/usr/bin/env bash
# BC250-Phosphor: one-command setup and update, run on the BC-250.
#
#   bash setup.sh                    install, or update with the options used last time
#   bash setup.sh --night 23:30-08:00 --logo "RAFALE'S RIG"    install/update with new options (remembered)
#   bash setup.sh --uninstall        stop the autostart and switch the app back to its default theme
#
# Other flags: --app PATH (where turing-smart-screen-python is), --no-autostart, --reset-options, --help.
# Theme options: see the README or install_bc250.sh.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/bc250-themes"
OLD_STATE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/bc250-phosphor"  # name before the repo was renamed
[[ -d "$OLD_STATE_DIR" && ! -e "$STATE_DIR" ]] && mv "$OLD_STATE_DIR" "$STATE_DIR"  # keeps saved options
OPTIONS_FILE="$STATE_DIR/options"
APP_FILE="$STATE_DIR/app_path"
APP_URL="https://github.com/mathoudebine/turing-smart-screen-python"
SERVICE=turing-monitor
REQUIRED_MODULES="serial yaml psutil PIL babel requests ping3 uptime numpy usb Crypto"

say()  { printf '\033[92m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[93m!! \033[0m %s\n' "$*" >&2; }
fail() { printf '\033[91mxx \033[0m %s\n' "$*" >&2; exit 1; }
ask()  { # ask "question" -> 0 for yes (default), 1 for no; non-interactive runs answer yes
  [[ -t 0 ]] || return 0
  local reply; read -r -p "$1 [Y/n] " reply
  [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

# --- arguments --------------------------------------------------------------------------------------------------------
APP="" AUTOSTART=1 UNINSTALL=0 RESET_OPTIONS=0
THEME_OPTS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app) APP="${2:?--app needs a path}"; shift 2 ;;
    --no-autostart) AUTOSTART=0; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --reset-options) RESET_OPTIONS=1; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --no-splash|--portrait|--no-jumpscare) THEME_OPTS+=("$1"); shift ;;
    --*) THEME_OPTS+=("$1" "${2:?$1 needs a value}"); shift 2 ;;
    *) fail "Unexpected argument: $1 (see --help)" ;;
  esac
done
mkdir -p "$STATE_DIR"

# --- 1. find turing-smart-screen-python: --app, else last time's, else next to this folder or in your home ---------
is_app() { [[ -f "$1/main.py" && -f "$1/library/sensors/sensors_custom.py" ]]; }

if [[ -z "$APP" && -f "$APP_FILE" ]] && is_app "$(cat "$APP_FILE")"; then
  APP="$(cat "$APP_FILE")"
fi
if [[ -z "$APP" ]]; then
  for candidate in "$SRC"/../turing-smart-screen-python* "$HOME"/turing-smart-screen-python*; do
    is_app "$candidate" && { APP="$candidate"; break; }
  done
fi
[[ -n "$APP" ]] || fail "turing-smart-screen-python not found. Put it next to this folder, or run with --app PATH.
    To get it:  git clone --depth 1 --branch 3.10.0 $APP_URL ~/turing-smart-screen-python"
is_app "$APP" || fail "$APP is not a turing-smart-screen-python folder (no main.py / library/sensors)"
APP="$(cd "$APP" && pwd -P)"
echo "$APP" > "$APP_FILE"
say "App: $APP"

# --- uninstall ----------------------------------------------------------------------------------------------------------
if [[ "$UNINSTALL" == 1 ]]; then
  bash "$SRC/install_autostart.sh" "$APP" --remove || true
  sed -i 's/^\(  THEME:\).*/\1 3.5inchTheme2/' "$APP/config.yaml"
  sed -i '/# BC250-Phosphor theme sensors/d; /sensors_bc250 import/d' "$APP/library/sensors/sensors_custom.py"
  rm -rf "$APP"/res/themes/BC250-* "$APP/library/sensors/sensors_bc250.py" "$APP/bc250_check.py"
  say "Uninstalled: the app is back on its default theme (your options stay in $STATE_DIR)."
  exit 0
fi

# --- 2. remember options -------------------------------------------------------------------------------------------------
[[ "$RESET_OPTIONS" == 1 ]] && rm -f "$OPTIONS_FILE"
if [[ ${#THEME_OPTS[@]} -gt 0 ]]; then
  printf '%q ' "${THEME_OPTS[@]}" > "$OPTIONS_FILE"
  say "Options saved for next time: ${THEME_OPTS[*]}"
elif [[ -s "$OPTIONS_FILE" ]]; then
  eval "THEME_OPTS=($(cat "$OPTIONS_FILE"))"
  say "Using your saved options: ${THEME_OPTS[*]}"
fi

# --- 3. Python with the app's libraries ----------------------------------------------------------------------------------
has_modules() { "$1" -c "import importlib, sys; [importlib.import_module(m) for m in sys.argv[1:]]" $REQUIRED_MODULES \
                >/dev/null 2>&1; }
PYTHON=""
for candidate in "$APP/.venv/bin/python" "$APP/venv/bin/python" "$(command -v python3 || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]] && has_modules "$candidate"; then PYTHON="$candidate"; break; fi
done
if [[ -z "$PYTHON" ]]; then
  say "Installing the app's Python libraries in $APP/.venv (private to the app, nothing system-wide)"
  python3 -m venv "$APP/.venv" || fail "python3 -m venv failed"
  "$APP/.venv/bin/python" -m pip install --quiet --upgrade pip || true
  if ! "$APP/.venv/bin/python" -m pip install --quiet -r "$APP/requirements.txt"; then
    warn "Some optional packages failed; installing the ones the monitor needs"
    "$APP/.venv/bin/python" -m pip install --quiet pyserial PyYAML psutil Pillow babel requests ping3 uptime numpy \
      pyusb pycryptodome ruamel.yaml pystray || fail "Could not install the Python libraries (see above)"
  fi
  PYTHON="$APP/.venv/bin/python"
  has_modules "$PYTHON" || fail "The Python libraries are still incomplete in $APP/.venv"
fi
say "Python: $PYTHON"

# --- 4. screen access -------------------------------------------------------------------------------------------------------
shopt -s nullglob
ports=(/dev/ttyACM* /dev/ttyUSB*)
shopt -u nullglob
port="${ports[0]:-}"
if [[ -z "$port" ]]; then
  warn "No screen found on USB (/dev/ttyACM*): plug it in; the monitor will pick it up when it starts."
elif [[ ! -r "$port" || ! -w "$port" ]]; then
  group="$(stat -c %G "$port")"
  warn "Your account cannot talk to the screen ($port belongs to group '$group')."
  fix=""
  # Fedora Atomic (Bazzite, Silverblue...) keeps system groups in /usr/lib/group, usermod needs them in /etc/group
  if ! grep -q "^$group:" /etc/group 2>/dev/null && grep -q "^$group:" /usr/lib/group 2>/dev/null; then
    fix="grep -E '^$group:' /usr/lib/group | sudo tee -a /etc/group >/dev/null && "
  fi
  fix+="sudo usermod -aG $group $(id -un)"
  if ask "Fix it now? (runs: $fix)"; then
    bash -c "$fix" && warn "Done: log out and back in (or reboot) for it to take effect."
  else
    warn "To fix it later: $fix   then log out and back in."
  fi
else
  say "Screen: $port"
fi

# --- 5. theme -------------------------------------------------------------------------------------------------------------
say "Installing the theme"
if ! output="$(bash "$SRC/install_bc250.sh" "$APP" "${THEME_OPTS[@]}" 2>&1)"; then
  printf '%s\n' "$output" >&2
  fail "Theme installation failed (see above)"
fi
# keep its report, minus the "what to do next" lines this script takes care of
printf '%s\n' "$output" | grep -v "^Done\.\|^  cd \|^To start the monitor\|^  'systemctl\|^$" || true
mkdir -p "$HOME/mangologs"  # where the MangoHud launch option below writes the FPS logs

# --- 6. start at boot -------------------------------------------------------------------------------------------------------
if [[ "$AUTOSTART" == 1 ]]; then
  # always rewritten: the app folder or Python may have moved since the service was created
  say "Setting up the monitor to start at boot"
  bash "$SRC/install_autostart.sh" "$APP" || warn "Autostart not set up (see above); the theme is installed anyway."
fi

restarts() { systemctl --user show -p NRestarts --value "$SERVICE" 2>/dev/null || echo 0; }
RESTARTS_BEFORE="$(restarts)"

# --- 7. health check --------------------------------------------------------------------------------------------------------
say "Checking every data source"
(cd "$APP" && "$PYTHON" bc250_check.py) || warn "The check could not run completely (see above)."

# --- 8. make sure the monitor really runs: a crash-looping service still looks "enabled" but leaves the screen dark ---
if [[ "$AUTOSTART" == 1 ]] && systemctl --user cat "$SERVICE" >/dev/null 2>&1; then
  sleep 5  # the check above already took several seconds
  if systemctl --user is-active --quiet "$SERVICE" && [[ "$(restarts)" == "$RESTARTS_BEFORE" ]]; then
    say "Monitor is running"
  else
    warn "The monitor does not stay running. Its last log lines:"
    journalctl --user -u "$SERVICE" -n 40 --no-pager -o cat >&2 || true
    fail "The monitor failed to start (log above). Fix it, or send the log, then run setup again."
  fi
fi

cat <<EOF

$(say "All set.")
  FPS in games: in Steam > game > Properties > Launch Options, paste
      MANGOHUD_CONFIG=fps_only,alpha=0,autostart_log=1,log_interval=1000,output_folder=~/mangologs mangohud %command%
  Update later:  git -C "$SRC" pull && bash "$SRC/setup.sh"
  Log of the monitor:  journalctl --user -u $SERVICE -f
EOF
