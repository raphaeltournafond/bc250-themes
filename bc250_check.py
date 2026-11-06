#!/usr/bin/env python3
# BC250-Phosphor pre-flight check. Run it ON the BC-250, from the turing-smart-screen-python folder:
#     python3 bc250_check.py
# It reads every data source the theme uses and tells you what works, what shows "--", and what to put in config.yaml.

import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, WARN, BAD = "\033[92m OK \033[0m", "\033[93mWARN\033[0m", "\033[91mFAIL\033[0m"


def report(status, what, detail=""):
    print(f"[{status}] {what:<28} {detail}")


def _environ(pid: str) -> dict:
    import library.sensors.sensors_bc250 as s250
    try:
        with open(os.path.join(s250.PROC_ROOT, pid, "environ"), "rb") as f:
            pairs = [item.split(b"=", 1) for item in f.read().split(b"\0") if b"=" in item]
        return {k.decode(errors="ignore"): v.decode(errors="ignore") for k, v in pairs}
    except OSError:
        return {}


def _mangohud_config_in_use(env: dict, comm: str) -> str:
    """Which file MangoHud reads: MANGOHUD_CONFIGFILE if set, else the first existing of the per-program files
    and MangoHud.conf (it does not merge them)."""
    if env.get("MANGOHUD_CONFIG") and "read_cfg" not in env["MANGOHUD_CONFIG"]:
        return "(no file: MANGOHUD_CONFIG only)"
    if env.get("MANGOHUD_CONFIGFILE"):
        return env["MANGOHUD_CONFIGFILE"]
    conf_dir = os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME", "~"), ".config"), "MangoHud")
    for name in (f"wine-{comm}.conf", f"{comm}.conf", "MangoHud.conf"):
        if os.path.isfile(os.path.join(conf_dir, name)):
            return os.path.join(conf_dir, name)
    return "(none: built-in defaults)"


# MangoHud loaded in the game itself, logging only. Options in MANGOHUD_CONFIG without read_cfg mean no config file
# is read, which also bypasses the file Steam's Game Mode overlay imposes. The HUD is made invisible with alpha=0,
# NOT no_display: with no_display MangoHud skips its per-frame update, and autostart_log lives in that update, so
# logging would never start.
GAME_MODE_LAUNCH_OPTION = ("MANGOHUD_CONFIG=fps_only,alpha=0,autostart_log=1,log_interval=1000,"
                           "output_folder=~/mangologs mangohud %command%")


def mangohud_diagnosis(game_running: bool):
    """Explains why no MangoHud log is being written, from the MangoHud processes actually running."""
    import library.sensors.sensors_bc250 as s250
    found = []
    for pid in os.listdir(s250.PROC_ROOT):
        if not pid.isdigit():
            continue
        comm = (s250._read(os.path.join(s250.PROC_ROOT, pid, "comm")) or "").strip()
        if comm == "mangoapp":
            found.append((pid, comm, "gamemode"))
            continue
        try:
            with open(os.path.join(s250.PROC_ROOT, pid, "maps"), "r", errors="ignore") as f:
                if "libMangoHud" in f.read():
                    found.append((pid, comm, "layer"))
        except OSError:
            continue

    hint = "        -> "
    if not found:
        print(hint + "No MangoHud is running" + (" for the current game." if game_running else
                                                   " (start a game, then re-run this check)."))
        print(hint + "Set the game's launch options to (works in Game Mode and Desktop mode):")
        print(hint + "    " + GAME_MODE_LAUNCH_OPTION)
        return

    # a game already logging through its launch options makes the Game Mode overlay irrelevant
    layer_ok = any(kind == "layer" and "autostart_log" in _environ(pid).get("MANGOHUD_CONFIG", "")
                   and "no_display" not in _environ(pid).get("MANGOHUD_CONFIG", "").split(",")
                   for pid, _, kind in found)
    for pid, comm, kind in found:
        if kind == "gamemode" and layer_ok:
            continue
        env = _environ(pid)
        config = _mangohud_config_in_use(env, comm)
        content = (s250._read(config) or "") if os.path.isabs(config) else ""
        options = {line.split("=", 1)[0].strip() for line in content.splitlines() if line.strip()}
        print(hint + f"{'mangoapp (Game Mode overlay)' if kind == 'gamemode' else comm + ' (MangoHud layer)'}, "
                     f"pid {pid}: reads {config}")
        env_config = env.get("MANGOHUD_CONFIG", "")
        if "autostart_log" in env_config and "no_display" in env_config.split(","):
            print(hint + f"  MANGOHUD_CONFIG={env_config}")
            print(hint + "  no_display stops MangoHud's per-frame update, so autostart_log never fires.")
            print(hint + "  Use instead: " + GAME_MODE_LAUNCH_OPTION)
            continue
        if env_config:
            if "read_cfg" not in env_config and "autostart_log" in env_config:
                print(hint + f"  MANGOHUD_CONFIG={env_config}  (logging set here, config files skipped: OK)")
                continue
            print(hint + f"  MANGOHUD_CONFIG={env_config}"
                  + ("" if "read_cfg" in env_config else "  (without read_cfg: the file is ignored)"))
        if kind == "gamemode":
            print(hint + "  Game Mode: Steam writes this file itself, so ~/.config/MangoHud/MangoHud.conf")
            print(hint + "  is never read and its overlay cannot log for us. Instead, set the game's launch")
            print(hint + "  options to (logs only, draws nothing, works in Desktop mode too):")
            print(hint + "    " + GAME_MODE_LAUNCH_OPTION)
        else:
            missing = [o for o in ("autostart_log", "log_interval", "output_folder") if o not in options]
            if not config.endswith("MangoHud.conf"):
                print(hint + "  a per-game config wins over MangoHud.conf: add the logging lines to it.")
            if missing:
                print(hint + f"  missing in that file: {', '.join(missing)}")
            elif "no_display" in options:
                print(hint + "  file has no_display: fine for logging, the HUD just stays hidden.")


def _radar_spec(widget="Bc250Radar"):
    """A data-fed widget's settings in the selected theme, or None when the theme doesn't have it."""
    try:
        import yaml
        with open("config.yaml", encoding="utf-8") as f:
            theme = yaml.safe_load(f)["config"]["THEME"]
        with open(os.path.join("res", "themes", theme, "theme.yaml"), encoding="utf-8") as f:
            return yaml.safe_load(f)["STATS"]["CUSTOM"].get(widget)
    except Exception:
        return None


def main():
    print("\nBC250-Phosphor check\n" + "-" * 60)
    report(OK, "Python", sys.version.split()[0])

    try:
        import psutil
    except ImportError:
        report(BAD, "psutil", "missing: pip install -r requirements.txt")
        return
    try:
        import library.sensors.sensors_bc250 as b
        b._Draw.enabled = False  # read only: the running monitor owns the screen
    except Exception as e:
        report(BAD, "sensors_bc250", f"cannot import ({e}). Run install_bc250.sh first, from the repo root")
        return

    # --- GPU (amdgpu sysfs) ---
    gpu = b._AmdGpu.find()
    if not gpu.device:
        report(BAD, "amdgpu device", "no /sys/class/drm/card*/device with vendor 0x1002")
    else:
        report(OK, "amdgpu device", f"{gpu.device} ({gpu.pci_slot}), hwmon={gpu.hwmon}")

    checks = [
        ("GPU clock", b.Bc250GpuClock, "MHz"),
        ("GPU memory (VRAM+GTT)", b.Bc250GpuMem, "GiB"),
        ("APU power", b.Bc250ApuPower, "W"),
    ]
    for name, cls, unit in checks:
        sensor = cls()
        n = sensor.as_numeric()
        if name == "GPU clock" and n != n and b.core_unlocked():
            report(WARN, name, "the core unlock makes the kernel misread it -> screen shows '--'. To get the real "
                               "clock: fix-freq = true under [gpu-usage] in cyan-skillfish-governor-smu's config")
        elif n is None or n != n:  # NaN
            report(WARN, name, "not available -> screen shows '--'")
        else:
            report(OK, name, f"{n:.1f} {unit}  (screen: '{sensor.as_string().strip()}')")
    # read() only: as_numeric() would also draw on the screen
    for name, cls in (("GPU temperature", b.Bc250GpuTemp), ("CPU temperature", b.Bc250CpuTemp)):
        t = cls().read()
        report(OK if t is not None else WARN, name, f"{t:.0f}°C" if t is not None else "not available -> shows '--°C'")

    load = b.Bc250GpuLoad()
    load.as_numeric()
    time.sleep(1.0)
    n = load.as_numeric()
    clients = len(b.Bc250GpuLoad._prev_clients)
    if n != n:
        report(WARN, "GPU load (fdinfo)", "no drm-engine-gfx counters visible -> shows '--%'. Start a game, and run "
                                          "the monitor as the same user as Steam")
    else:
        report(OK, "GPU load (fdinfo)", f"{n:.0f}% across {clients} GPU client(s)")

    # --- CPU ---
    freq = psutil.cpu_freq()
    report(OK if freq else WARN, "CPU frequency", f"{freq.current / 1000:.2f} GHz" if freq else "unavailable")

    # --- Steam ---
    roots = b._steam_roots()
    report(OK if roots else WARN, "Steam install", ", ".join(roots) or "not found under ~/.local/share/Steam")
    libraries = b._steam_libraries()
    report(OK if libraries else WARN, "Steam libraries", ", ".join(libraries) or "none found")
    usage = b._GameDisk.usage()
    disk = b._GameDisk.path()
    if usage is None:
        report(WARN, "Games SSD", f"cannot read {disk} -> shows '--'. Set BC250_DISK_PATH to your games drive")
    else:
        report(OK, "Games SSD", f"{disk}: {usage.percent:.0f}% used, {usage.free / 1000 ** 3:.0f} GB free")
    game = b._Steam.running_game()
    if game:
        report(OK, "Now playing", f"{b._Steam.app_name(game[0])} (AppId {game[0]}, pid {game[1]})")
    else:
        report(OK, "Now playing", "idle (start a game and re-run to test)")

    # Downloads: start/stop from content_log.txt (StateFlags as fallback), progress from appmanifest + network
    logged = b._Downloads.log_states()
    busy = [f"{b._Steam.app_name(a)} ({st['phase']})" for a, st in logged.items() if st["busy"]]
    content_logs = [os.path.join(r, "logs", "content_log.txt") for r in roots
                    if os.path.isfile(os.path.join(r, "logs", "content_log.txt"))]
    if not b._Steam.client_running():
        report(WARN, "Steam downloads", "Steam client not running: downloads are only shown while it runs")
    elif not content_logs:
        report(WARN, "Steam downloads", "no logs/content_log.txt: falling back to appmanifest StateFlags only")
    b._Downloads.poll()
    time.sleep(2)
    active = b._Downloads.poll()
    if active:
        pct = "--" if active["fraction"] is None else f"{active['fraction'] * 100:.0f}%"
        report(OK, "Steam downloads", f"{active['phase']} {active['name']}: {pct}, "
                                      f"{active['rate'] / 1e6:.1f} MB/s on the network")
    else:
        report(OK, "Steam downloads", "none active" + (f" (log says busy: {', '.join(busy)})" if busy else "")
               + " - start a download and re-run to test")

    # Shader pre-caching
    shader_logs = [os.path.join(r, "logs", "shader_log.txt") for r in roots
                   if os.path.isfile(os.path.join(r, "logs", "shader_log.txt"))]
    entry = b._Shaders.last_log_entry()
    replaying = b._Shaders.replaying_apps()
    if not shader_logs:
        report(WARN, "Shader pre-caching", "no logs/shader_log.txt yet (Steam writes it on the first shader job)")
    elif replaying:
        report(OK, "Shader pre-caching", f"fossilize_replay running for app(s) {replaying}; last log line: {entry}")
    else:
        last = "none" if entry is None else f"app {entry[1]} at {entry[2]}%, {entry[0] / 60:.0f} min ago"
        report(OK, "Shader pre-caching", f"idle; last job seen in {shader_logs[0]}: {last}")

    # MangoHud FPS
    folders = b._MangoHud.folders()
    log = b._MangoHud.latest_log()
    if log:
        report(OK, "MangoHud FPS", f"{b._MangoHud.fps()} fps from {log}")
    else:
        report(WARN, "MangoHud FPS", f"no live log, FPS column hidden. Watched folders: {', '.join(folders) or 'none'}")
        mangohud_diagnosis(game is not None)

    # --- Network: what to put in config.yaml ETH ---
    stats = psutil.net_if_stats()
    candidates = [name for name, s in stats.items() if s.isup and name != "lo" and not name.startswith(("docker", "veth", "br-", "virbr", "tailscale"))]
    report(OK if candidates else WARN, "Network interfaces up", ", ".join(candidates) or "none")
    if candidates:
        print(f"        -> in config.yaml set:  ETH: \"{candidates[0]}\"   (the theme reads the ETH slot, wifi works too)")

    # --- Radar theme: can the flight data be fetched? ---
    radar = _radar_spec()
    if radar:
        lat, lon, km = float(radar["LAT"]), float(radar["LON"]), float(radar["RANGE_KM"])
        for name, url in b._RadarFeed.SOURCES:
            try:
                raw = b._RadarFeed._get(url.format(lat=lat, lon=lon, nm=km / 1.852 + 1))
                report(OK, f"Radar data ({name})", f"{len(b._RadarFeed._parse(raw, lat, lon))} aircraft within {km:.0f} km")
                break
            except Exception as e:
                report(WARN, f"Radar data ({name})", f"no answer ({e}); the radar tries the next source")

    # --- Seismograph theme: can the earthquake feed be fetched? ---
    seismo = _radar_spec("Bc250Seismograph")
    if seismo:
        min_mag = float(seismo.get("MIN_MAG", 2.5))
        url = b._QuakeFeed.URL.format(tier=b._QuakeFeed.tier(min_mag), span="day")
        try:
            report(OK, "Earthquake feed (USGS)", f"{len(b._QuakeFeed._parse(b._QuakeFeed._get(url), min_mag))} quakes of "
                                                 f"M{min_mag:g} or more in the past day")
        except Exception as e:
            report(WARN, "Earthquake feed (USGS)", f"no answer ({e}); the pen keeps writing this machine's own tremor")

    # --- Screen serial port + permissions ---
    ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    report(OK if ports else WARN, "Screen serial port", ", ".join(ports) or "none found: is the screen plugged in?")
    for port in ports:
        if not os.access(port, os.R_OK | os.W_OK):
            import grp  # Unix only
            group = grp.getgrgid(os.stat(port).st_gid).gr_name
            report(BAD, f"Access to {port}", f"permission denied: sudo usermod -aG {group} $USER  (then log out/in)")
    print("-" * 60 + "\nWARN items still render: they just show '--' instead of a value.\n")


if __name__ == "__main__":
    main()
