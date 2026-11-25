# SPDX-License-Identifier: GPL-3.0-or-later
"""Steam (libraries, the running game, downloads, shader pre-caching), the game disk and MangoHud's FPS."""

import datetime
import glob
import math
import os
import re
import time
from typing import List, Optional

from . import base
from .base import _read


class _Cache:
    """Tiny time-based memo: value of fn() recomputed at most every ttl seconds."""

    def __init__(self, ttl: float, fn):
        self.ttl, self.fn, self.stamp, self.value = ttl, fn, -1e9, None

    def get(self):
        now = time.monotonic()
        if now - self.stamp >= self.ttl:
            self.value, self.stamp = self.fn(), now
        return self.value


def _find_steam_roots() -> List[str]:
    homes = [os.path.expanduser("~")] + glob.glob("/home/*") + ["/root"]
    roots = []
    for home in homes:
        for rel in (".local/share/Steam", ".steam/steam", ".var/app/com.valvesoftware.Steam/.local/share/Steam"):
            path = os.path.realpath(os.path.join(home, rel))
            if os.path.isdir(path) and path not in roots:
                roots.append(path)
    return roots


def _find_steam_libraries() -> List[str]:
    libraries = []
    for root in _steam_roots():
        vdf = _read(os.path.join(root, "steamapps", "libraryfolders.vdf")) or ""
        for library in [root] + re.findall(r'"path"\s+"([^"]+)"', vdf):
            library = os.path.realpath(library)
            if library not in libraries and os.path.isdir(os.path.join(library, "steamapps")):
                libraries.append(library)
    return libraries


_steam_roots_cache = _Cache(60, _find_steam_roots)
_steam_libraries_cache = _Cache(30, _find_steam_libraries)


def _steam_roots() -> List[str]:
    return _steam_roots_cache.get()


def _steam_libraries() -> List[str]:
    return _steam_libraries_cache.get()


def _acf_fields(text: str) -> dict:
    return dict(re.findall(r'^\s*"(\w+)"\s+"([^"]*)"', text, re.MULTILINE))


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class _Procs:
    """One /proc scan per refresh shared by every widget: [(pid, argv)]."""

    @staticmethod
    def _scan() -> List[tuple]:
        procs = []
        for pid in os.listdir(base.PROC_ROOT):
            if not pid.isdigit():
                continue
            try:
                with open(os.path.join(base.PROC_ROOT, pid, "cmdline"), "rb") as f:
                    argv = [a.decode(errors="ignore") for a in f.read().split(b"\0") if a]
            except OSError:
                continue
            if argv:
                procs.append((pid, argv))
        return procs

    _cache = _Cache(0.5, None)

    @classmethod
    def all(cls) -> List[tuple]:
        if cls._cache.fn is None:
            cls._cache.fn = cls._scan
        try:
            return cls._cache.get() or []
        except OSError:
            return []


class _Steam:
    # Things Steam starts through its game launcher that are not games: Steamworks Common Redistributables and the
    # Steam Linux Runtime containers. Install scripts (iscriptevaluator) run under the game's own AppId after an
    # install or update, so they are recognised by their command line instead.
    TOOL_APPS = {"228980", "1070560", "1391110", "1628350"}
    NOT_A_GAME = ("iscriptevaluator", "installscript")
    _names = {}

    @classmethod
    def app_name(cls, app_id: str) -> str:
        if app_id in cls._names:
            return cls._names[app_id]
        name = None
        for library in _steam_libraries():
            manifest = _read(os.path.join(library, "steamapps", f"appmanifest_{app_id}.acf"))
            name = _acf_fields(manifest or "").get("name")
            if name:
                break
        if not name and _int(app_id) >= 2 ** 31:
            name = "non-Steam game"  # shortcuts get a generated id with the high bit set
        cls._names[app_id] = name or f"app {app_id}"
        return cls._names[app_id]

    @classmethod
    def running_game(cls) -> Optional[tuple]:
        """(app_id, pid) of the game Steam launched, if any: the newest `reaper SteamLaunch AppId=N -- ...`
        process that is not a tool or an install script."""
        best = None
        for pid, argv in _Procs.all():
            if "SteamLaunch" not in argv:  # exact argument, not a substring of some other command
                continue
            app_id = next((a[6:] for a in argv if a.startswith("AppId=") and a[6:].isdigit()), None)
            if app_id is None or app_id in cls.TOOL_APPS:
                continue
            command = " ".join(argv).lower()
            if any(word in command for word in cls.NOT_A_GAME):
                continue
            age = cls.seconds_running(pid)
            if best is None or (age is not None and (best[2] is None or age < best[2])):
                best = (app_id, pid, age)
        return best[:2] if best else None

    _game_cache = _Cache(0.5, None)

    @classmethod
    def current_game(cls) -> Optional[tuple]:
        """running_game() cached for one refresh, as several widgets need it."""
        if cls._game_cache.fn is None:
            cls._game_cache.fn = cls.running_game
        return cls._game_cache.get()

    @staticmethod
    def client_running() -> bool:
        return any(os.path.basename(argv[0]) in ("steam", "steamwebhelper") for _, argv in _Procs.all())

    @staticmethod
    def seconds_running(pid: str) -> Optional[int]:
        # Field 22 of /proc/<pid>/stat is the start time in clock ticks since boot
        stat = _read(os.path.join(base.PROC_ROOT, pid, "stat"))
        uptime = _read(os.path.join(base.PROC_ROOT, "uptime"))
        if not stat or not uptime:
            return None
        try:
            start_ticks = int(stat.rsplit(")", 1)[1].split()[19])
            return max(0, int(float(uptime.split()[0]) - start_ticks / os.sysconf("SC_CLK_TCK")))
        except (ValueError, IndexError, AttributeError, OSError):
            return None


def _network_rx() -> Optional[int]:
    try:
        import psutil
        return sum(c.bytes_recv for nic, c in psutil.net_io_counters(pernic=True).items() if nic != "lo")
    except Exception:
        return None


class _Downloads:
    """Active Steam download / install / verification.

    Whether one runs: logs/content_log.txt, which Steam appends to the moment an app changes state, e.g.
        [2026-10-09 18:02:11] AppID 730 state changed : Update Required,Update Running,Update Started,
        [2026-10-09 18:02:12] AppID 730 update changed : Running Update,Downloading,Staging,
        [2026-10-09 18:09:40] AppID 730 finished update (took 449 seconds)
    falling back to the appmanifest StateFlags (UpdateStarted 0x400 / UpdateRunning 0x100, UpdatePaused 0x200) for
    apps the log tail does not mention. Nothing counts while the Steam client itself is not running.

    Progress: appmanifest BytesDownloaded / BytesToDownload (BytesStaged / BytesToStage while installing). Steam only
    rewrites them now and then, so between rewrites the download is advanced by the bytes received on the network."""
    LOG_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] AppID (\d+) (state changed|update changed|update started|"
                          r"finished update|update canceled|scheduler finished)\b[ :]*(.*)$", re.MULTILINE)
    BUSY_WORDS = ("Downloading", "Staging", "Committing", "Preallocating", "Verifying", "Validating", "Reconfiguring")
    STARTED, RUNNING, PAUSED = 0x400, 0x100, 0x200

    _manifests = _Cache(3, None)
    _anchor = {}  # app_id -> (done bytes, network rx at that moment)
    _counter = {}  # app_id -> (BytesDownloaded, monotonic time, bytes/s it advanced at)
    _net = {"rx": None, "t": None, "bps": 0.0}
    active: Optional[dict] = None

    @staticmethod
    def _read_manifests() -> dict:
        manifests = {}
        for library in _steam_libraries():
            for path in glob.glob(os.path.join(library, "steamapps", "appmanifest_*.acf")):
                fields = _acf_fields(_read(path) or "")
                if fields.get("appid"):
                    manifests[fields["appid"]] = fields
        return manifests

    @classmethod
    def log_states(cls) -> dict:
        """app_id -> {"busy", "phase", "stamp", "total"} from the tail of content_log.txt (latest line wins)."""
        states = {}
        for steam_root in _steam_roots():
            path = os.path.join(steam_root, "logs", "content_log.txt")
            try:
                with open(path, "rb") as f:
                    f.seek(max(0, os.path.getsize(path) - 65536))
                    tail = f.read().decode(errors="ignore")
            except OSError:
                continue
            for m in cls.LOG_LINE.finditer(tail):
                stamp, app_id, event, rest = m.groups()
                state = states.setdefault(app_id, {"busy": False, "phase": "downloading", "total": 0})
                state["stamp"] = stamp
                if event == "update started":
                    state["busy"], state["phase"] = True, "downloading"
                    total = re.search(r"download \d+/(\d+)", rest)
                    state["total"] = int(total.group(1)) if total else 0
                elif event == "update changed":
                    if any(word in rest for word in cls.BUSY_WORDS):
                        state["busy"] = True
                        if "Verifying" in rest or "Validating" in rest:
                            state["phase"] = "verifying"
                        elif ("Committing" in rest or "Staging" in rest) and "Downloading" not in rest:
                            state["phase"] = "installing"
                        else:
                            state["phase"] = "downloading"
                elif event == "state changed":
                    state["busy"] = ("Update Running" in rest or "Update Started" in rest) and "Paused" not in rest
                else:  # finished update / update canceled / scheduler finished
                    state["busy"] = False
            break  # first Steam install with a log
        return states

    @classmethod
    def _network_rate(cls) -> Optional[int]:
        rx, now = _network_rx(), time.monotonic()
        net = cls._net
        if rx is not None and net["rx"] is not None and now > net["t"]:
            instant = max(0, rx - net["rx"]) / (now - net["t"])
            net["bps"] = instant if not net["bps"] else 0.6 * net["bps"] + 0.4 * instant
        net["rx"], net["t"] = rx, now
        return rx

    @classmethod
    def poll(cls) -> Optional[dict]:
        rx = cls._network_rate()
        if cls._manifests.fn is None:
            cls._manifests.fn = cls._read_manifests
        if not _Steam.client_running():
            cls.active = None
            return None
        manifests = cls._manifests.get() or {}
        logged = cls.log_states()

        candidates = []
        for app_id, state in logged.items():
            if state["busy"]:
                candidates.append((state["stamp"], app_id, state["phase"], state["total"]))
        for app_id, fields in manifests.items():
            flags = _int(fields.get("StateFlags"))
            if app_id not in logged and flags & (cls.STARTED | cls.RUNNING) and not flags & cls.PAUSED:
                candidates.append(("", app_id, "downloading", 0))
        if not candidates:
            cls._anchor.clear()
            cls._counter.clear()
            cls.active = None
            return None
        _, app_id, phase, log_total = max(candidates)  # most recent log activity first

        fields = manifests.get(app_id, {})
        to_download, downloaded = _int(fields.get("BytesToDownload")) or log_total, _int(fields.get("BytesDownloaded"))
        to_stage, staged = _int(fields.get("BytesToStage")), _int(fields.get("BytesStaged"))
        fraction, eta = None, None
        if phase == "installing" and to_stage > 0:
            fraction = staged / to_stage
        elif phase == "downloading" and to_download > 0:
            now = time.monotonic()
            done, anchor_rx = cls._anchor.get(app_id, (downloaded, rx))
            if downloaded > done or anchor_rx is None:  # Steam rewrote its counter: resynchronise on it
                done, anchor_rx = downloaded, rx
            cls._anchor[app_id] = (done, anchor_rx)
            # how fast Steam's own counter advances, measured between its rewrites
            last_value, last_time, counter_bps = cls._counter.get(app_id, (downloaded, now, 0.0))
            if downloaded > last_value and now > last_time:
                instant = (downloaded - last_value) / (now - last_time)
                counter_bps = instant if not counter_bps else 0.6 * counter_bps + 0.4 * instant
                last_value, last_time = downloaded, now
            cls._counter[app_id] = (last_value, last_time, counter_bps)

            estimate = done + (rx - anchor_rx if rx is not None and anchor_rx is not None else 0)
            estimate = min(max(estimate, downloaded), int(to_download * 0.995))
            fraction = estimate / to_download
            # the network may carry other traffic and Steam's counter lags: trust whichever is faster
            speed = max(cls._net["bps"], counter_bps)
            if speed > 0:
                eta = (to_download - estimate) / speed
        cls.active = {"app_id": app_id, "name": fields.get("name") or _Steam.app_name(app_id), "phase": phase,
                      "fraction": fraction, "eta": eta, "rate": cls._net["bps"]}
        return cls.active


class _Shaders:
    """Steam shader pre-caching ("Processing Vulkan shaders"), done by fossilize_replay processes.

    fossilize_replay reports progress to Steam through private shared memory; what is readable is the line Steam
    appends to logs/shader_log.txt about every 10 s, e.g.
        [2025-03-11 07:47:39] Still replaying 2683150 (73%, 26975/36488).
    The percentage is shown as Steam reports it (it can disagree with done/total). A job whose percentage does not
    move for STALL seconds is flagged: replays that never finish are a known Fossilize issue."""
    POLL, FRESH, STALL = 3.0, 15.0, 120.0
    LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (?:Still replaying (\d+) \((\d+)%"
                      r"|Starting processing job for app (\d+))", re.MULTILINE)
    _last_poll = 0.0
    _track = {}  # app_id -> {"pct", "changed": monotonic, "rate": %/s}
    active: Optional[dict] = None

    @staticmethod
    def replaying_apps() -> List[Optional[str]]:
        """App id of every running fossilize_replay (None when its command line has no shadercache path)."""
        apps = []
        for _, argv in _Procs.all():
            if "fossilize_replay" in os.path.basename(argv[0]):
                match = re.search(r"shadercache/(\d+)/", " ".join(argv))
                apps.append(match.group(1) if match else None)
        return apps

    @staticmethod
    def last_log_entry() -> Optional[tuple]:
        """(age in seconds, app_id, percent or None) of the newest job line in shader_log.txt."""
        for root in _steam_roots():
            path = os.path.join(root, "logs", "shader_log.txt")
            try:
                with open(path, "rb") as f:
                    f.seek(max(0, os.path.getsize(path) - 8192))
                    tail = f.read().decode(errors="ignore")
            except OSError:
                continue
            matches = list(_Shaders.LINE.finditer(tail))
            if not matches:
                continue
            m = matches[-1]
            stamp = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            age = (datetime.datetime.now() - stamp).total_seconds()
            if m.group(2):
                return age, m.group(2), int(m.group(3))
            return age, m.group(4), None
        return None

    @classmethod
    def poll(cls) -> Optional[dict]:
        now = time.monotonic()
        if now - cls._last_poll < cls.POLL:
            return cls.active
        cls._last_poll = now
        try:
            apps = cls.replaying_apps()
            entry = cls.last_log_entry()
        except OSError:
            apps, entry = [], None

        fresh = entry is not None and entry[0] < cls.FRESH
        if not apps and not fresh:
            cls.active = None
            return None
        if entry is not None and (fresh or entry[1] in apps):
            app_id, pct = entry[1], entry[2]
        else:
            app_id, pct = next((a for a in apps if a), None), None

        eta, stalled = None, False
        if pct is not None:
            track = cls._track.setdefault(app_id, {"pct": pct, "changed": now, "rate": 0.0})
            if pct > track["pct"]:
                instant = (pct - track["pct"]) / max(now - track["changed"], 1.0)
                track["rate"] = instant if not track["rate"] else 0.6 * track["rate"] + 0.4 * instant
                track["pct"], track["changed"] = pct, now
            elif pct < track["pct"]:  # a new pass over the same game
                track.update(pct=pct, changed=now, rate=0.0)
            stalled = now - track["changed"] > cls.STALL
            eta = (100 - pct) / track["rate"] if track["rate"] > 0 else None
        cls.active = {"name": _Steam.app_name(app_id) if app_id else "shaders", "app_id": app_id,
                      "percent": pct, "eta": eta, "stalled": stalled}
        return cls.active


class _GameDisk:
    _cache = (0.0, None)

    @staticmethod
    def path() -> str:
        forced = os.environ.get("BC250_DISK_PATH")
        if forced:
            return forced
        libraries = _steam_libraries()
        if libraries:
            return libraries[0]
        return os.path.expanduser("~") if os.path.isdir(os.path.expanduser("~")) else "/"

    @classmethod
    def usage(cls):
        stamp, usage = cls._cache
        if time.monotonic() - stamp > 5:
            try:
                import psutil
                usage = psutil.disk_usage(cls.path())
            except (OSError, ImportError):
                usage = None
            cls._cache = (time.monotonic(), usage)
        return usage


class Bc250GameDisk:
    # Used % of the drive that holds the Steam library
    def as_numeric(self) -> float:
        usage = _GameDisk.usage()
        return math.nan if usage is None else usage.percent

    def as_string(self) -> str:
        usage = _GameDisk.usage()
        return "--%" if usage is None else f"{usage.percent:.0f}%"

    def last_values(self) -> List[float]:
        pass


class Bc250GameDiskFree:
    def as_numeric(self) -> float:
        pass

    def as_string(self) -> str:
        usage = _GameDisk.usage()
        if usage is None:
            return "-- G"
        free_gb = usage.free / 1000 ** 3
        return f"{free_gb / 1000:.1f} T" if free_gb >= 1000 else f"{free_gb:.0f} G"

    def last_values(self) -> List[float]:
        pass


# ---------------------------------------------------------------------------------------------------------------------
# MangoHud FPS
# ---------------------------------------------------------------------------------------------------------------------
class _MangoHud:
    """Live FPS from the CSV log MangoHud writes (and flushes) while logging is on.

    Needs in ~/.config/MangoHud/MangoHud.conf: autostart_log=1, log_interval=1000, output_folder=~/mangologs"""
    FRESH = 5.0  # a log not written for this long belongs to a finished session
    _dirs_cache = (0.0, [])
    _fps_col = {}

    @classmethod
    def folders(cls) -> List[str]:
        stamp, folders = cls._dirs_cache
        if time.monotonic() - stamp < 30:
            return folders
        home = os.path.expanduser("~")
        folders = [os.environ.get("BC250_MANGOHUD_DIR", "")]
        for conf in (os.path.join(home, ".config", "MangoHud", "MangoHud.conf"),
                     os.path.join(home, ".config", "MangoHud", "presets.conf")):
            folders += re.findall(r"^\s*output_folder\s*=\s*(.+?)\s*$", _read(conf) or "", re.MULTILINE)
        folders += [os.path.join(home, "mangologs"), home]
        folders = [os.path.expandvars(os.path.expanduser(f)) for f in folders if f]
        cls._dirs_cache = (time.monotonic(), list(dict.fromkeys(f for f in folders if os.path.isdir(f))))
        return cls._dirs_cache[1]

    @classmethod
    def latest_log(cls) -> Optional[str]:
        newest, newest_mtime = None, time.time() - cls.FRESH
        for folder in cls.folders():
            for path in glob.glob(os.path.join(folder, "*.csv")):
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest, newest_mtime = path, mtime
        return newest

    @classmethod
    def fps(cls) -> Optional[float]:
        path = cls.latest_log()
        if not path:
            return None
        try:
            if path not in cls._fps_col:
                with open(path, "r", errors="ignore") as f:
                    head = f.read(2048).splitlines()
                header = next((line.split(",") for line in head if line.startswith("fps,")), None)
                cls._fps_col[path] = header.index("fps") if header else None
            col = cls._fps_col[path]
            if col is None:
                return None
            with open(path, "rb") as f:
                f.seek(max(0, os.path.getsize(path) - 1024))
                lines = f.read().decode(errors="ignore").splitlines()
            for line in reversed(lines[1:]):  # the first line of the tail may be cut
                fields = line.split(",")
                if len(fields) > col:
                    try:
                        return float(fields[col])
                    except ValueError:
                        continue
        except OSError:
            return None
        return None
