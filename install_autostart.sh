#!/usr/bin/env bash
# Starts the Turing screen monitor automatically at boot, as a systemd user service.
# Usage: ./install_autostart.sh /path/to/turing-smart-screen-python [--remove]
#
# The service runs as you (needed for the GPU load and Steam widgets), restarts the monitor if it stops (for example
# when the screen is not ready yet at boot), and "lingering" makes it start at boot instead of at login.
# Useful commands afterwards:
#   systemctl --user status turing-monitor        is it running?
#   journalctl --user -u turing-monitor -f         its log, live
#   systemctl --user restart turing-monitor        after re-running install_bc250.sh
set -euo pipefail

SERVICE=turing-monitor
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/$SERVICE.service"

REPO="${1:-}"
if [[ -z "$REPO" || ! -f "$REPO/main.py" ]]; then
  sed -n '3,10p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 1
fi
REPO="$(cd "$REPO" && pwd -P)"

if [[ "${2:-}" == "--remove" ]]; then
  systemctl --user disable --now "$SERVICE" 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "Autostart removed (lingering left as is: 'loginctl disable-linger' to turn it off)."
  exit 0
fi

# The Python that has the monitor's libraries. The service starts the monitor through bc250_python.sh, which checks
# them first: after an upgrade of the system's Python it rebuilds the app's .venv, instead of failing at every boot.
LAUNCHER="$REPO/bc250_python.sh"
if [[ ! -f "$LAUNCHER" ]]; then
  echo "$LAUNCHER is missing: run setup.sh (or install_bc250.sh) first." >&2
  exit 1
fi
PYTHON="$(bash "$LAUNCHER" "$REPO")" || { echo "No Python with the monitor's libraries (see above)." >&2; exit 1; }

# Only one program can talk to the screen at a time
OFFICIAL=turing-smart-screen-python.service  # the system service from the project's wiki (tools/ folder)
if systemctl is-enabled --quiet "$OFFICIAL" 2>/dev/null || systemctl is-active --quiet "$OFFICIAL" 2>/dev/null; then
  echo "The project's own system service ($OFFICIAL) is installed: use one or the other, not both." >&2
  echo "To switch to this one:  sudo systemctl disable --now $OFFICIAL   then re-run this script." >&2
  exit 1
fi
if pgrep -u "$(id -u)" -f "$REPO/main.py|[ ]main.py" >/dev/null 2>&1 && ! systemctl --user is-active --quiet "$SERVICE"; then
  echo "WARNING: a monitor started by hand seems to be running. Close it (Ctrl+C in its terminal), otherwise" >&2
  echo "         it and the service will fight over the screen." >&2
fi

mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=Turing smart screen monitor (BC250-Phosphor)
# keep retrying forever: the screen may appear late at boot or be replugged
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=$REPO
ExecStart=/bin/bash $LAUNCHER $REPO --run
# no desktop tray under systemd
Environment=PYSTRAY_BACKEND=dummy
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
echo "Wrote $UNIT (Python: $PYTHON)"

systemctl --user daemon-reload
systemctl --user enable "$SERVICE"
systemctl --user restart "$SERVICE"  # picks up a changed folder, Python or theme even if it was already running
echo "Service enabled and started."

if loginctl enable-linger "$(id -un)" 2>/dev/null; then
  echo "Lingering enabled: the monitor starts at boot, before you log in."
else
  echo "Could not enable lingering: the monitor will start when you log in (Bazzite logs in automatically)."
  echo "To start it at boot instead: sudo loginctl enable-linger $(id -un)"
fi

sleep 3
if systemctl --user is-active --quiet "$SERVICE"; then
  echo "Running. Log: journalctl --user -u $SERVICE -f"
else
  echo "Not running yet: see  journalctl --user -u $SERVICE -n 30" >&2
fi
