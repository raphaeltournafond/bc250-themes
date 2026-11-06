# SPDX-License-Identifier: GPL-3.0-or-later
#
# BC-250 custom sensors for turing-smart-screen-python (theme: BC250-Phosphor)
#
# The AMD BC-250 (Cyan Skillfish APU) does not expose gpu_busy_percent, and pyamdgpuinfo has no wheels for
# Python > 3.12, so the stock GPU sensors are unreliable on it. These classes read amdgpu sysfs / procfs directly:
#   - GPU clock       hwmon freq1_input, falling back to the active level of pp_dpm_sclk
#   - GPU temperature hwmon temp1_input
#   - GPU load        derived from per-process DRM fdinfo counters (drm-engine-gfx), the same source nvtop uses
#   - GPU memory      mem_info_vram_used + mem_info_gtt_used (the BC-250 shares its 16 GB GDDR6)
#   - APU power       hwmon power1_average / power1_input
#   - Game disk       usage of the drive holding the Steam library ("/" is a read-only image on Bazzite/SteamOS)
#
# Some widgets are drawn by this module rather than by the app, from their own keys in theme.yaml:
#   - Bc250CpuTemp / Bc250GpuTemp (HEAT_TEXT, HEAT_GRAPH, ALERT_TAG): temperature and 60 s history coloured from
#     COLD_COLOR to HOT_COLOR between COLD and HOT, turning ALERT_COLOR and flashing "HOT!" from ALERT
#   - Bc250Prompt (PROMPT): the bottom line. boot check, then the game being played (with MangoHud FPS and session
#     time), a Steam download or shader pre-caching job with its progress / ETA, or the last session with its peak
#     temperatures
#   - Bc250ApuPower (HEAT_TEXT, HEAT_BAR): watts and bar on the same green -> orange -> red scale (COLD / HOT / ALERT)
#   - boot splash (bc250_splash in theme.yaml): a BIOS-style POST with live values, played once before the
#     dashboard is drawn (hooked onto the app's display_static_images, no change to the app itself)
#   - bc250_palette in theme.yaml (Game Boy theme): every colour computed here snaps to its shades, and "dim"
#     means towards its background (lighter on a Game Boy, darker on the phosphor terminal)
#   - Bc250Screen (SCREEN): dims the display after DIM_AFTER minutes without game or download, sleeps at NIGHT
#
# Every sensor degrades to "--" when its source is missing: a custom sensor that raises would stop all the
# following custom sensors from refreshing (see stats.Custom.stats).
#
# Environment overrides: BC250_SYSFS_ROOT / BC250_PROC_ROOT (fake trees for testing), BC250_DISK_PATH (games drive),
# BC250_MANGOHUD_DIR (MangoHud log folder).

import datetime
import glob
import logging
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional

# Classes follow the CustomDataSource interface (as_numeric / as_string / last_values) without inheriting it:
# sensors_custom.py re-exports this module, so importing it back here would be circular.

SYSFS_ROOT = os.environ.get("BC250_SYSFS_ROOT", "/")
PROC_ROOT = os.environ.get("BC250_PROC_ROOT", "/proc")
REPO_DIR = Path(__file__).resolve().parents[2]

HISTORY_SIZE = 60
APU_POWER_BAR_MAX_W = 250

logger = logging.getLogger("turing.bc250")  # a child of the app's logger: same output (journal), same level


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read().strip()
    except (OSError, ValueError):
        return None


def _read_int(path: Optional[str]) -> Optional[int]:
    if path is None:
        return None
    value = _read(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _push(history: List[float], value: Optional[float]):
    history.append(math.nan if value is None else value)
    del history[:-HISTORY_SIZE]


def _is_nan(value) -> bool:
    return value is None or value != value


def _duration(seconds: Optional[float]) -> str:
    """Unambiguous short duration: 45s, 12m, 1h05."""
    if seconds is None:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds >= 100 * 3600:
        return ">99h"  # keeps every column within 5 characters
    return f"{seconds // 3600}h{seconds // 60 % 60:02d}"


# ---------------------------------------------------------------------------------------------------------------------
# Drawing helpers for the widgets this module renders itself
# ---------------------------------------------------------------------------------------------------------------------
class _Draw:
    enabled = True  # bc250_check.py turns this off: reading sensors there must never talk to the screen
    screen = None  # the _Screen all widgets draw through, once the app has drawn the theme's background
    _repainted = {}
    _fonts = {}
    _backgrounds = {}
    _failed = set()

    @staticmethod
    def theme(cls_name: str) -> dict:
        from library import config
        return config.THEME_DATA["STATS"]["CUSTOM"].get(cls_name, {}) or {}

    @staticmethod
    def color(value, default=(0, 0, 0)):
        if value is None:
            return default
        if isinstance(value, str):
            return tuple(int(c) for c in value.split(","))
        return tuple(value)

    @classmethod
    def font(cls, name: str, size: int):
        from PIL import ImageFont
        key = (name, size)
        if key not in cls._fonts:
            cls._fonts[key] = ImageFont.truetype(str(REPO_DIR / "res" / "fonts" / name), size,
                                                 layout_engine=ImageFont.Layout.BASIC)  # same text on every machine
        return cls._fonts[key]

    @classmethod
    def background_path(cls, name: str) -> str:
        from library import config
        return str(REPO_DIR / "res" / "themes" / config.CONFIG_DATA["config"]["THEME"] / name)

    @classmethod
    def background(cls, name: str):
        from PIL import Image
        if name not in cls._backgrounds:
            cls._backgrounds[name] = Image.open(cls.background_path(name)).convert("RGB")
        return cls._backgrounds[name]

    @classmethod
    def crop(cls, box: dict):
        x, y = box["X"], box["Y"]
        return cls.background(box.get("BACKGROUND_IMAGE", "background.png")).crop(
            (x, y, x + box["WIDTH"], y + box["HEIGHT"]))

    @classmethod
    def show(cls, image, box: dict):
        if cls.screen is not None:  # only the pixels that changed (a blinking cursor: just the cursor)
            import random
            key, now = (box["X"], box["Y"], image.width, image.height), time.monotonic()
            # ...and about once a minute the whole widget, should the screen have lost what it showed: each widget at
            # its own moment, so they never all go out together (a burst would hold up the radar's sweep)
            due = cls._repainted.setdefault(key, now + random.uniform(10, 60))
            full = image.width * image.height <= 20000 and now >= due
            if full:
                cls._repainted[key] = now + random.uniform(55, 65)
            cls.screen.DisplayPILImage(image, box["X"], box["Y"], full=full)
            return
        from library.display import display
        display.lcd.DisplayPILImage(image, box["X"], box["Y"])

    @classmethod
    def safely(cls, what: str, fn, *args):
        # A drawing error must not break the other custom sensors: log it once and carry on
        if not cls.enabled:
            return
        try:
            fn(*args)
        except Exception as e:
            if what not in cls._failed:
                cls._failed.add(what)
                logger.error("BC250: cannot draw %s: %s", what, e)


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class _Palette:
    """Optional fixed palette of the theme (bc250_palette in theme.yaml): None for free colours."""
    _loaded = False
    colors = None
    bg = None

    @classmethod
    def get(cls):
        if not cls._loaded:
            cls._loaded = True
            try:
                from library import config
                spec = (config.THEME_DATA or {}).get("bc250_palette") or {}
            except Exception:
                spec = {}
            if spec.get("COLORS"):
                cls.colors = [_Draw.color(c) for c in spec["COLORS"]]
                cls.bg = _Draw.color(spec.get("BG"), cls.colors[0])
        return cls

    @classmethod
    def snap(cls, color):
        if cls.get().colors is None:
            return color
        return min(cls.colors, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, color)))


def heat_color(value: float, spec: dict):
    """COLD_COLOR up to COLD, fading to HOT_COLOR at HOT, then to ALERT_COLOR at ALERT."""
    cold, hot = float(spec.get("COLD", 40)), float(spec.get("HOT", 70))
    alert = float(spec.get("ALERT", 80))
    cold_c = _Draw.color(spec.get("COLD_COLOR"), (125, 255, 165))
    hot_c = _Draw.color(spec.get("HOT_COLOR"), (255, 140, 30))
    alert_c = _Draw.color(spec.get("ALERT_COLOR"), (255, 60, 40))
    if value >= hot and alert > hot:
        return _Palette.snap(_lerp(hot_c, alert_c, min(1.0, (value - hot) / (alert - hot))))
    t = 0.0 if hot <= cold else max(0.0, min(1.0, (value - cold) / (hot - cold)))
    return _Palette.snap(_lerp(cold_c, hot_c, t))


def _dim(color, k: float):
    """A fainter version of color: towards black, or towards the palette's background when the theme has one."""
    palette = _Palette.get()
    if palette.colors is None:
        return tuple(int(c * k) for c in color)
    return palette.snap(_lerp(palette.bg, color, k))


def draw_heat_text(spec: dict, box: dict, value: Optional[float], flash: bool, unit: str = "°C"):
    from PIL import ImageDraw
    image = _Draw.crop(box)
    d = ImageDraw.Draw(image)
    font = _Draw.font(box["FONT"], box["FONT_SIZE"])
    text = f"--{unit}" if _is_nan(value) else f"{value:.0f}{unit}"
    color = _dim(heat_color(0, spec), 0.6) if _is_nan(value) else heat_color(value, spec)
    right = box.get("ALIGN") == "right"
    width = d.textlength(text, font=font)
    if flash:
        # inverse video: the value punched out of a solid alert block
        left = box["WIDTH"] - width - 4 if right else 0
        d.rectangle((left, 0, left + width + 3, box["HEIGHT"] - 1),
                    fill=_Draw.color(spec.get("ALERT_COLOR"), (255, 60, 40)))
        color = _Draw.color(spec.get("INK"), (2, 14, 6))
    x = (box["WIDTH"] - (2 if flash else 0)) if right else (1 if flash else 0)
    d.text((x, box.get("BASELINE", box["FONT_SIZE"] * 10 // 12)), text, font=font, fill=color,
           anchor="rs" if right else "ls")
    _Draw.show(image, box)


def draw_heat_bar(spec: dict, bar: dict, value: Optional[float]):
    """Progress bar whose fill is a gradient along its length: each column takes the colour of the value it stands
    for, so the tip of the bar always has the colour of the current value."""
    from PIL import ImageDraw
    image = _Draw.crop(bar)
    if not _is_nan(value):
        d = ImageDraw.Draw(image)
        w, h = bar["WIDTH"], bar["HEIGHT"]
        vmin, vmax = float(bar.get("MIN_VALUE", 0)), float(bar.get("MAX_VALUE", 100))
        filled = round(w * max(0.0, min(1.0, (value - vmin) / (vmax - vmin))))
        for px in range(filled):
            d.line((px, 0, px, h - 1), fill=heat_color(vmin + (px + 0.5) * (vmax - vmin) / w, spec))
    _Draw.show(image, bar)


def draw_alert_tag(spec: dict, tag: dict, flash: bool):
    from PIL import ImageDraw
    image = _Draw.crop(tag)
    if flash:
        d = ImageDraw.Draw(image)
        d.rectangle((0, 0, tag["WIDTH"] - 1, tag["HEIGHT"] - 1), fill=_Draw.color(spec.get("ALERT_COLOR")))
        d.text((tag["WIDTH"] // 2, tag["HEIGHT"] - 3), tag.get("TEXT", "HOT!"), font=_Draw.font(tag["FONT"], tag["FONT_SIZE"]),
               fill=_Draw.color(spec.get("INK"), (2, 14, 6)), anchor="ms")
    _Draw.show(image, tag)


def draw_heat_graph(spec: dict, graph: dict, values: List[float]):
    from PIL import ImageDraw

    w, h = graph["WIDTH"], graph["HEIGHT"]
    vmin, vmax = float(graph.get("MIN_VALUE", 30)), float(graph.get("MAX_VALUE", 90))
    axis_c = _Draw.color(graph.get("AXIS_COLOR"), (46, 170, 88))
    font = _Draw.font(graph["FONT"], graph.get("FONT_SIZE", 12))
    image = _Draw.crop(graph)
    d = ImageDraw.Draw(image)

    if graph.get("STYLE") in ("mosaic", "blocks"):
        # videotex: one column of separated 6x4 blocks per second, each block in the colour of its own height;
        # "blocks" (minecraft): the same with little cubes, lit on top and shaded underneath
        bw, bh = (int(v) for v in graph.get("BLOCK", (6, 4)))
        cubes = graph["STYLE"] == "blocks"
        columns, levels = w // bw, (h - 2) // bh
        recent = values[-columns:]
        for i, v in enumerate(recent):
            if _is_nan(v):
                continue
            x = (columns - len(recent) + i) * bw
            filled = max(1, round((max(vmin, min(vmax, v)) - vmin) / (vmax - vmin) * levels))
            for j in range(filled):
                y = (h - 2) - (j + 1) * bh
                block = heat_color(vmin + (j + 0.5) * (vmax - vmin) / levels, spec)
                d.rectangle((x, y + 1, x + bw - 2, y + bh - 1), fill=block)
                if cubes:
                    d.line((x, y + 1, x + bw - 2, y + 1), fill=_lerp(block, (255, 255, 255), 0.45))
                    d.line((x, y + bh - 1, x + bw - 2, y + bh - 1), fill=_lerp(block, (0, 0, 0), 0.4))
        d.text((0, 0), f"{vmax:.0f}", font=font, fill=axis_c, anchor="la")
        _Draw.show(image, graph)
        return

    def y_of(v):
        v = max(vmin, min(vmax, v))
        return (h - 2) - (v - vmin) * (h - 3) / (vmax - vmin)

    # Samples are placed by their index in the history, so the chart scrolls in from the right
    step = (w - 2) / max(1, len(values) - 1)
    points = [(1 + i * step, y_of(v), v) for i, v in enumerate(values) if not _is_nan(v)]

    # Area under the curve, drawn on every other screen row to match the background scanlines
    for (x1, y1, v1), (x2, y2, v2) in zip(points, points[1:]):
        for px in range(math.ceil(x1), math.floor(x2) + 1):
            t = (px - x1) / (x2 - x1) if x2 > x1 else 0.0
            top, value = y1 + (y2 - y1) * t, v1 + (v2 - v1) * t
            fill = _dim(heat_color(value, spec), 0.32)
            for py in range(math.ceil(top) + 1, h - 1):
                if (graph["Y"] + py) % 2 == 0:
                    image.putpixel((px, py), fill)

    # COLD / HOT threshold guides over the area, labelled at the right end
    for level_key, default in (("COLD", 40), ("HOT", 70)):
        level = float(spec.get(level_key, default))
        if vmin < level < vmax:
            ly = round(y_of(level))
            guide = _dim(heat_color(level, spec), 0.6)
            for gx in range(2, w - 16, 4):
                d.line((gx, ly, gx + 1, ly), fill=guide)
            d.text((w - 2, ly), f"{level:.0f}", font=font, fill=guide, anchor="rm")

    for (x1, y1, v1), (x2, y2, v2) in zip(points, points[1:]):
        d.line((x1, y1, x2, y2), fill=heat_color((v1 + v2) / 2, spec), width=2)

    d.line((0, 0, 0, h - 1), fill=axis_c)
    d.line((0, h - 1, w - 1, h - 1), fill=axis_c)
    d.text((3, 0), f"{vmax:.0f}", font=font, fill=axis_c, anchor="la")
    _Draw.show(image, graph)


class _TempWidget:
    """Base for temperature sensors that draw HEAT_TEXT + HEAT_GRAPH (+ ALERT_TAG) from their theme.yaml entry."""
    last_val: List[float] = []
    value = None
    _tick = 0
    _tag_lit = False

    def read(self) -> Optional[float]:
        raise NotImplementedError

    def as_numeric(self) -> float:
        cls = type(self)
        cls.value = self.read()
        cls._tick += 1
        _push(cls.last_val, cls.value)
        spec = _Draw.theme(cls.__name__)
        alert = not _is_nan(cls.value) and cls.value >= float(spec.get("ALERT", 80))
        flash = alert and cls._tick % 2 == 0
        if "HEAT_TEXT" in spec:
            _Draw.safely(cls.__name__ + " text", draw_heat_text, spec, spec["HEAT_TEXT"], cls.value, flash)
        if "HEAT_GRAPH" in spec:
            _Draw.safely(cls.__name__ + " graph", draw_heat_graph, spec, spec["HEAT_GRAPH"], cls.last_val)
        if "ALERT_TAG" in spec and (flash or cls._tag_lit):
            # Only redrawn while alerting, plus once more to restore the normal tag
            _Draw.safely(cls.__name__ + " tag", draw_alert_tag, spec, spec["ALERT_TAG"], flash)
            cls._tag_lit = flash
        return math.nan if cls.value is None else cls.value

    def as_string(self) -> str:
        return "--°C" if self.value is None else f"{self.value:.0f}°C"

    def last_values(self) -> List[float]:
        return type(self).last_val


# ---------------------------------------------------------------------------------------------------------------------
# GPU (amdgpu sysfs)
# ---------------------------------------------------------------------------------------------------------------------
class _AmdGpu:
    """Locates the amdgpu device once and caches its sysfs paths."""
    _searched = False
    device: Optional[str] = None
    hwmon: Optional[str] = None
    pci_slot: Optional[str] = None

    @classmethod
    def find(cls):
        if cls._searched:
            return cls
        cls._searched = True
        for card in sorted(glob.glob(os.path.join(SYSFS_ROOT, "sys/class/drm/card[0-9]*"))):
            if "-" in os.path.basename(card):  # connectors e.g. card0-HDMI-A-1
                continue
            device = os.path.join(card, "device")
            if _read(os.path.join(device, "vendor")) != "0x1002":
                continue
            cls.device = device
            hwmons = sorted(glob.glob(os.path.join(device, "hwmon", "hwmon*")))
            cls.hwmon = hwmons[0] if hwmons else None
            uevent = _read(os.path.join(device, "uevent")) or ""
            match = re.search(r"PCI_SLOT_NAME=(\S+)", uevent)
            cls.pci_slot = match.group(1) if match else None
            break
        return cls

    @classmethod
    def path(cls, *parts) -> Optional[str]:
        cls.find()
        return os.path.join(cls.device, *parts) if cls.device else None

    @classmethod
    def hwmon_path(cls, name) -> Optional[str]:
        cls.find()
        return os.path.join(cls.hwmon, name) if cls.hwmon else None


UNLOCKED_MIN_GPU_MHZ = 200  # the clock never really goes this low; the misread value after a core unlock stays under


def cpu_threads() -> Optional[int]:
    """How many threads the kernel sees ("0-11" on a stock BC-250), None if it can't be told."""
    present = _read(os.path.join(SYSFS_ROOT, "sys/devices/system/cpu/present")) or ""
    match = re.fullmatch(r"0-(\d+)", present.strip())
    return int(match.group(1)) + 1 if match else None


def core_unlocked() -> bool:
    """Whether the board's two extra CPU cores were unlocked (8C/16T instead of 6C/12T)."""
    return (cpu_threads() or 0) > 12


def gpu_clock_mhz() -> Optional[float]:
    """The GPU clock. With the core unlock the kernel misreads it (a value between 0 and 100 MHz, whatever the real
    clock): there, a reading that low is not shown at all. cyan-skillfish-governor's fix-freq option replaces
    freq1_input with the real clock, which then shows as usual."""
    mhz = None
    hz = _read_int(_AmdGpu.hwmon_path("freq1_input"))
    if hz:
        mhz = hz / 1_000_000
    else:
        # pp_dpm_sclk lines look like "1: 2000Mhz *", the star marking the active level
        for line in (_read(_AmdGpu.path("pp_dpm_sclk") or "") or "").splitlines():
            match = re.search(r"(\d+)\s*Mhz\s*\*", line, re.IGNORECASE)
            if match:
                mhz = float(match.group(1))
                break
    if mhz is not None and mhz < UNLOCKED_MIN_GPU_MHZ and core_unlocked():
        return None
    return mhz


class Bc250GpuClock:
    value = None

    def as_numeric(self) -> float:
        Bc250GpuClock.value = gpu_clock_mhz()
        return math.nan if self.value is None else self.value

    def as_string(self) -> str:
        return "----" if self.value is None else f"{self.value:.0f}"

    def last_values(self) -> List[float]:
        pass


class Bc250GpuTemp(_TempWidget):
    last_val = [math.nan] * HISTORY_SIZE

    def read(self) -> Optional[float]:
        millideg = _read_int(_AmdGpu.hwmon_path("temp1_input"))
        return millideg / 1000 if millideg is not None else None


class Bc250GpuLoad:
    # Sums the drm-engine-gfx busy time of every amdgpu DRM client and divides by wall time between two samples
    _prev_clients = {}
    _prev_time = None
    _counters_seen = False
    value = None

    @staticmethod
    def _sample() -> dict:
        clients = {}
        for pid in os.listdir(PROC_ROOT):
            if not pid.isdigit():
                continue
            fd_dir = os.path.join(PROC_ROOT, pid, "fd")
            try:
                fds = os.listdir(fd_dir)
            except OSError:
                continue  # process gone or owned by another user
            for fd in fds:
                try:
                    if not os.readlink(os.path.join(fd_dir, fd)).startswith("/dev/dri/"):
                        continue
                    with open(os.path.join(PROC_ROOT, pid, "fdinfo", fd), "r") as f:
                        info = f.read()
                except OSError:
                    continue
                if "amdgpu" not in info:
                    continue
                pdev = re.search(r"drm-pdev:\s*(\S+)", info)
                if _AmdGpu.pci_slot and pdev and pdev.group(1) != _AmdGpu.pci_slot:
                    continue
                client = re.search(r"drm-client-id:\s*(\d+)", info)
                gfx = re.search(r"drm-engine-gfx:\s*(\d+)\s*ns", info)
                if client and gfx:
                    # Several fds can share one client: keep a single entry per client id
                    clients[client.group(1)] = int(gfx.group(1))
        return clients

    def as_numeric(self) -> float:
        _AmdGpu.find()
        now = time.monotonic()
        try:
            clients = self._sample()
        except OSError:
            clients = {}
        prev, prev_time = Bc250GpuLoad._prev_clients, Bc250GpuLoad._prev_time
        Bc250GpuLoad._prev_clients, Bc250GpuLoad._prev_time = clients, now

        if clients:
            Bc250GpuLoad._counters_seen = True
        if prev_time is None or not (clients or Bc250GpuLoad._counters_seen):
            # No sample yet, or engine counters never seen (old kernel / no permission): unknown rather than 0%
            Bc250GpuLoad.value = None
            return math.nan
        busy_ns = sum(max(0, ns - prev[cid]) for cid, ns in clients.items() if cid in prev)
        elapsed_ns = (now - prev_time) * 1e9
        Bc250GpuLoad.value = max(0.0, min(100.0, busy_ns * 100 / elapsed_ns)) if elapsed_ns > 0 else None
        return math.nan if self.value is None else self.value

    def as_string(self) -> str:
        return "--%" if self.value is None else f"{self.value:.0f}%"

    def last_values(self) -> List[float]:
        pass


class Bc250GpuMem:
    value = None

    def as_numeric(self) -> float:
        vram = _read_int(_AmdGpu.path("mem_info_vram_used"))
        gtt = _read_int(_AmdGpu.path("mem_info_gtt_used"))
        if vram is None and gtt is None:
            Bc250GpuMem.value = None
            return math.nan
        Bc250GpuMem.value = ((vram or 0) + (gtt or 0)) / 1024 ** 3
        return self.value

    def as_string(self) -> str:
        return "--G" if self.value is None else f"{self.value:.1f}G"

    def last_values(self) -> List[float]:
        pass


class Bc250ApuPower:
    value = None

    def as_numeric(self) -> float:
        microwatts = _read_int(_AmdGpu.hwmon_path("power1_average"))
        if microwatts is None:
            microwatts = _read_int(_AmdGpu.hwmon_path("power1_input"))
        Bc250ApuPower.value = microwatts / 1_000_000 if microwatts is not None else None
        spec = _Draw.theme("Bc250ApuPower")
        if "HEAT_TEXT" in spec:
            _Draw.safely("power text", draw_heat_text, spec, spec["HEAT_TEXT"], self.value, False, "W")
        if "HEAT_BAR" in spec:
            _Draw.safely("power bar", draw_heat_bar, spec, spec["HEAT_BAR"], self.value)
        if self.value is None:
            return math.nan
        return max(0.0, min(float(APU_POWER_BAR_MAX_W), self.value))

    def as_string(self) -> str:
        return "--W" if self.value is None else f"{self.value:.0f}W"

    def last_values(self) -> List[float]:
        pass


# ---------------------------------------------------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------------------------------------------------
class _Tube:
    """Lit Nixie digits: the glyph squeezed to a cathode's narrow shape, a neon glow around it, seen through the anode
    mesh (the same diamond pattern as make_theme.py). Drawn additively over the unlit tube of the background, so a
    blank tube is just the background."""
    _cache = {}

    @staticmethod
    def mesh(w, h):
        from PIL import Image, ImageDraw
        m = Image.new("L", (w, h), 255)
        d = ImageDraw.Draw(m)
        for k in range(-h, w + h, 4):
            d.line((k, 0, k + h, h), fill=200)
            d.line((k, h, k + h, 0), fill=200)
        return m

    @classmethod
    def light(cls, font_name, w, h, char, dot, glow_c, core_c, strength=1.0):
        """The lit layer of one tube (RGB, black where unlit)."""
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
        key = (font_name, w, h, char, dot, glow_c, core_c, strength)
        if key not in cls._cache:
            mask = Image.new("L", (w * 2, h), 0)
            if char.strip():
                ImageDraw.Draw(mask).text((w, h // 2 + 1), char, font=_Draw.font(font_name, int(h * 0.82)),
                                          fill=round(255 * strength), anchor="mm")
            mask = mask.resize((w, h))
            if dot:
                ImageDraw.Draw(mask).ellipse((w - 5, h - 9, w - 2, h - 6), fill=round(255 * strength))
            glow = mask.filter(ImageFilter.GaussianBlur(max(2, w // 9))).point(lambda v: min(255, v * 2))
            layer = Image.new("RGB", (w, h), (0, 0, 0))
            layer.paste(glow_c, (0, 0, w, h), glow)
            layer.paste(core_c, (0, 0, w, h), mask.point(lambda v: min(255, v * 3 // 2)))
            cls._cache[key] = ImageChops.multiply(layer, Image.merge("RGB", [cls.mesh(w, h)] * 3))
            if len(cls._cache) > 400:
                cls._cache.pop(next(iter(cls._cache)))
        return cls._cache[key]

    @staticmethod
    def split(text, n):
        """'2.84' on 3 tubes -> [('2', True), ('8', False), ('4', False)], right-aligned, blanks unlit."""
        tubes = []
        for ch in text or "":
            if ch == "." and tubes:
                tubes[-1] = (tubes[-1][0], True)
            elif ch != ".":
                tubes.append((ch, False))
        tubes = tubes[-n:]
        return [(" ", False)] * (n - len(tubes)) + tubes


class Bc250Nixie:
    """Nixie theme: draws every tube display, bar tube, warning lamp and the clock's colon dots from its theme.yaml
    entry. A tube is only redrawn when its digit changes, so most seconds only a handful of small tubes go to the
    screen. Values come from the other BC-250 widgets listed before it, psutil and sysfs."""
    _shown = {}
    _cpu_prev = None
    _tick = 0

    @classmethod
    def _cpu_load(cls):
        import psutil
        t = psutil.cpu_times()
        total = sum(t)
        idle = t.idle + getattr(t, "iowait", 0.0)
        prev, cls._cpu_prev = cls._cpu_prev, (total, idle)
        if prev is None or total <= prev[0]:
            return None
        return max(0.0, min(100.0, 100.0 * (1 - (idle - prev[1]) / (total - prev[0]))))

    @classmethod
    def _source(cls, name):
        import psutil
        if name == "clock":
            return time.strftime("%H%M%S")
        if name == "cpu_load":
            return cls._cpu_load()
        if name == "cpu_clk":
            freq = psutil.cpu_freq()
            return freq.current / 1000 if freq else None
        if name == "ram":
            return psutil.virtual_memory().percent
        if name == "ssd":
            usage = _GameDisk.usage()
            return usage.percent if usage else None
        return {"cpu_temp": lambda: Bc250CpuTemp.value, "gpu_temp": lambda: Bc250GpuTemp.value,
                "gpu_load": lambda: Bc250GpuLoad.value, "gpu_clk": gpu_clock_mhz,
                "pwr": lambda: Bc250ApuPower.value}.get(name, lambda: None)()

    @staticmethod
    def _text(disp, value):
        if value is None or (isinstance(value, float) and _is_nan(value)):
            return None
        if isinstance(value, str):
            return value
        digits = len(disp["XS"])
        value = min(value, 10 ** digits - 1)  # never more digits than tubes
        return disp.get("FORMAT", "{:.0f}").format(value)

    @classmethod
    def draw(cls, spec: dict):
        from PIL import ImageChops, ImageDraw
        cls._tick += 1
        glow_c, core_c = _Draw.color(spec.get("GLOW"), (255, 90, 18)), _Draw.color(spec.get("CORE"), (255, 196, 120))
        lamp_c = _Draw.color(spec.get("LAMP_ON"), (255, 60, 30))
        background = spec.get("BACKGROUND_IMAGE", "background.png")

        def box(x, y, w, h):
            return {"X": int(x), "Y": int(y), "WIDTH": int(w), "HEIGHT": int(h), "BACKGROUND_IMAGE": background}

        def changed(key, state):
            if cls._shown.get(key) == state:
                return False
            cls._shown[key] = state
            return True

        for index, disp in enumerate(spec.get("DISPLAYS", [])):
            value = _attempt("nixie " + disp["SOURCE"], lambda: cls._source(disp["SOURCE"]))
            text = cls._text(disp, value)
            alert = "ALERT" in disp and text is not None and value >= float(disp["ALERT"])
            blink_off = alert and cls._tick % 2 == 0
            w, h = int(disp["W"]), int(disp["H"])
            for i, (char, dot) in enumerate(_Tube.split(text, len(disp["XS"]))):
                state = (" ", False) if blink_off else (char, dot)
                if changed((index, i), state):
                    area = box(disp["XS"][i], disp["Y"], w, h)
                    image = ImageChops.add(_Draw.crop(area), _Tube.light(spec["FONT"], w, h, *state, glow_c, core_c))
                    _Draw.show(image, area)
            if "LAMP" in disp and changed((index, "lamp"), alert):
                lx, ly, r = (int(v) for v in disp["LAMP"])
                area = box(lx - r - 3, ly - r - 3, 2 * r + 7, 2 * r + 7)
                image = _Draw.crop(area)
                if alert:  # a red neon bulb: glow, then the lit disc
                    d = ImageDraw.Draw(image)
                    d.ellipse((0, 0, 2 * r + 6, 2 * r + 6), fill=_lerp(lamp_c, (0, 0, 0), 0.7))
                    d.ellipse((3, 3, 2 * r + 3, 2 * r + 3), fill=lamp_c)
                _Draw.show(image, area)
            if "BAR" in disp:
                bx, by, bw, bh, lo, hi = (float(v) for v in disp["BAR"])
                filled = 0 if text is None else round(bw * max(0.0, min(1.0, (value - lo) / (hi - lo))))
                if changed((index, "bar"), filled):  # an IN-13 bar tube: the glowing column, brighter core
                    area = box(bx, by, bw, bh)
                    image = _Draw.crop(area)
                    if filled:
                        d = ImageDraw.Draw(image)
                        d.rectangle((0, 0, filled - 1, int(bh) - 1), fill=_lerp(glow_c, (0, 0, 0), 0.25))
                        d.line((0, int(bh) // 2, filled - 1, int(bh) // 2), fill=core_c)
                    _Draw.show(image, area)
        # the clock's colon dots blink with the seconds
        lit = int(time.time()) % 2 == 0
        for i, (cx, cy) in enumerate(spec.get("COLONS", [])):
            if changed(("colon", i), lit):
                area = box(int(cx) - 4, int(cy) - 4, 9, 9)
                image = _Draw.crop(area)
                if lit:
                    ImageDraw.Draw(image).ellipse((1, 1, 7, 7), fill=_lerp(glow_c, (0, 0, 0), 0.3))
                    ImageDraw.Draw(image).ellipse((2, 2, 6, 6), fill=core_c)
                _Draw.show(image, area)

    def as_numeric(self) -> float:
        spec = _Draw.theme("Bc250Nixie")
        if spec:
            _Draw.safely("nixie", self.draw, spec)
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


# ---------------------------------------------------------------------------------------------------------------------
# Radar theme: live aircraft from free community ADS-B APIs around a point, on a radar scope
# ---------------------------------------------------------------------------------------------------------------------
def _km_per_deg(lat: float):
    """(km per degree of longitude, km per degree of latitude) around a latitude."""
    return 111.32 * math.cos(math.radians(lat)), 110.57


def _compass(bearing: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round(bearing / 45) % 8]


class _RadarFeed:
    """Polls the aircraft around the radar's centre in a thread of its own (a slow or failing API must never hold
    up the screen): adsb.lol, then adsb.fi if it fails. Flight routes come from adsbdb, looked up once per callsign
    and only kept when they make sense for where the aircraft is. Paused while the screen is off."""
    SOURCES = (("adsb.lol", "https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{nm:.0f}"),
               ("adsb.fi", "https://opendata.adsb.fi/api/v2/lat/{lat:.4f}/lon/{lon:.4f}/dist/{nm:.0f}"))
    ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
    AGENT = "bc250-themes radar (turing-smart-screen-python theme)"
    aircraft: List[dict] = []
    fetched = None  # time.time() of the last good answer
    source = None
    error = None
    routes = {}  # callsign -> route dict or None (looked up, nothing usable)
    _thread = None
    _want_routes: List[dict] = []

    @classmethod
    def start(cls, lat: float, lon: float, km: float, refresh: float):
        import threading
        if cls._thread is None or not cls._thread.is_alive():
            cls._thread = threading.Thread(target=cls._run, args=(lat, lon, km, refresh), name="BC250 radar feed",
                                           daemon=True)
            cls._thread.start()

    @classmethod
    def _get(cls, url: str):
        import json
        import urllib.request
        fixture = os.environ.get("BC250_RADAR_FIXTURE")  # tests and previews: a saved answer instead of the network
        if fixture:
            if "adsbdb" in url:
                routes = os.environ.get("BC250_RADAR_ROUTES")
                data = json.load(open(routes, encoding="utf-8")) if routes else {}
                return {"response": data.get(url.rsplit("/", 1)[-1], "unknown callsign")}
            with open(fixture, encoding="utf-8") as f:
                return json.load(f)
        request = urllib.request.Request(url, headers={"User-Agent": cls.AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=8) as answer:
            return json.loads(answer.read().decode("utf-8"))

    @staticmethod
    def _parse(raw: dict, lat0: float, lon0: float) -> List[dict]:
        kx, ky = _km_per_deg(lat0)
        now = time.time()
        planes = []
        for a in raw.get("ac") or raw.get("aircraft") or []:
            alt = a.get("alt_baro", a.get("alt_geom"))
            if a.get("lat") is None or a.get("lon") is None or alt in (None, "ground"):
                continue  # no position, or taxiing: not shown
            seen = float(a.get("seen_pos", a.get("seen", 0)) or 0)
            if seen > 30:
                continue
            planes.append({
                "hex": a.get("hex", "?"),
                "callsign": (a.get("flight") or "").strip() or a.get("r") or a.get("hex", "?").upper(),
                "registration": a.get("r") or "", "type": a.get("t") or "",
                "alt": int(alt), "gs": float(a.get("gs") or 0), "track": float(a.get("track") or 0),
                "rate": float(a.get("baro_rate") or a.get("geom_rate") or 0), "squawk": a.get("squawk") or "",
                "x": (float(a["lon"]) - lon0) * kx, "y": (float(a["lat"]) - lat0) * ky, "time": now - seen,
            })
        return planes

    @staticmethod
    def _plausible(route: dict, plane: dict, lat0: float, lon0: float) -> bool:
        """Community route data can be stale: keep it only if the aircraft is near one end of it or near its path."""
        kx, ky = _km_per_deg(lat0)
        try:
            ends = [((float(p["longitude"]) - lon0) * kx, (float(p["latitude"]) - lat0) * ky)
                    for p in (route["origin"], route["destination"])]
        except (KeyError, TypeError, ValueError):
            return False
        (ax, ay), (bx, by), (px, py) = ends[0], ends[1], (plane["x"], plane["y"])
        near_end = min(math.hypot(px - ax, py - ay), math.hypot(px - bx, py - by)) < 80
        length = math.hypot(bx - ax, by - ay)
        if length < 1:
            return near_end
        t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length ** 2))
        off_path = math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)))
        return near_end or off_path < 250

    @classmethod
    def _route(cls, plane: dict, lat0: float, lon0: float):
        callsign = plane["callsign"]
        if callsign in cls.routes or not re.match(r"^[A-Z]{3}\d[A-Z0-9]*$", callsign):
            return  # done already, or not an airline flight number (private aircraft fly under their registration)
        try:
            answer = cls._get(cls.ROUTE_URL.format(callsign=callsign)).get("response")
            route = answer.get("flightroute") if isinstance(answer, dict) else None
        except Exception:
            return  # network trouble: try again later
        if route and cls._plausible(route, plane, lat0, lon0):
            cls.routes[callsign] = {
                "from": route["origin"].get("iata_code") or route["origin"].get("icao_code") or "?",
                "to": route["destination"].get("iata_code") or route["destination"].get("icao_code") or "?",
                "airline": (route.get("airline") or {}).get("name") or "",
            }
        else:
            cls.routes[callsign] = None
        if len(cls.routes) > 500:
            cls.routes.pop(next(iter(cls.routes)))

    @classmethod
    def _run(cls, lat: float, lon: float, km: float, refresh: float):
        order = list(cls.SOURCES)
        while True:
            if Bc250Screen._mode == "off":
                time.sleep(5)
                continue
            for name, url in list(order):
                try:
                    planes = cls._parse(cls._get(url.format(lat=lat, lon=lon, nm=km / 1.852 + 1)), lat, lon)
                except Exception as e:
                    cls.error = f"{name}: {e}"
                    continue
                cls.aircraft, cls.fetched, cls.source, cls.error = planes, time.time(), name, None
                order.remove((name, url))
                order.insert(0, (name, url))  # keep using the source that answered
                break
            # routes of the flights the panel shows (a couple per round: the lookup service is free too)
            for plane in cls._want_routes[:2]:
                if plane["callsign"] not in cls.routes:
                    cls._route(plane, lat, lon)
            time.sleep(refresh)


class _Radar:
    """The scope and the flight panel, drawn by a thread of their own at a few frames per second: a sweep turns, each
    aircraft's blip and data tag move when the sweep passes over it, and only the changed pixels go to the screen."""

    def __init__(self, spec: dict, lcd, base):
        from PIL import Image, ImageDraw
        self.spec, self.base = spec, base
        self.cx, self.cy, self.r = (int(v) for v in spec["SCOPE"])
        self.km = float(spec["RANGE_KM"])
        self.box = (self.cx - self.r - 1, self.cy - self.r - 1, self.cx + self.r + 2, self.cy + self.r + 2)
        self.scope = base.crop(self.box)
        self.inside = Image.new("L", self.scope.size, 0)
        ImageDraw.Draw(self.inside).ellipse((1, 1, 2 * self.r + 1, 2 * self.r + 1), fill=255)
        self.period = float(spec.get("PERIOD", 4.0))
        self.small, self.big, self.large = (_Draw.font(spec["FONT"], s) for s in (12, 24, 36))
        colors = spec.get("COLORS") or {}
        self.col = {k: _Draw.color(colors.get(k), (200, 200, 200)) for k in
                    ("SWEEP", "LOW", "MID", "HIGH", "EMERGENCY", "TEXT", "LABEL", "DIM", "ROUTE")}
        self.lcd = _Screen(lcd, *base.size)
        self.memory = {}  # hex -> what the scope shows of it: position, data, when the sweep last passed
        self.angle = None
        self.trail = []
        self.panel_state = None
        self.lcd.TILE = int(spec.get("TILE", 10))  # short tiles hug a thin diagonal line (the sweep) better

    # -- data --------------------------------------------------------------------------------------------------------
    def colour(self, plane):
        if plane["squawk"] in ("7500", "7600", "7700"):
            return self.col["EMERGENCY"]
        return self.col["LOW"] if plane["alt"] < 6000 else self.col["MID"] if plane["alt"] < 20000 else self.col["HIGH"]

    @staticmethod
    def altitude(plane):
        return f"FL{plane['alt'] // 100:03d}" if plane["alt"] >= 6000 else f"{plane['alt']}FT"

    def now_position(self, plane, now):
        """Dead reckoning from the last report: where the aircraft is now (km east, km north)."""
        dt = max(0.0, min(30.0, now - plane["time"]))
        d = plane["gs"] * 1.852 / 3600 * dt
        return (plane["x"] + d * math.sin(math.radians(plane["track"])),
                plane["y"] + d * math.cos(math.radians(plane["track"])))

    def sweep_over(self, now):
        """Moves the blips the sweep passed over since the last frame, and forgets aircraft that are gone."""
        angle = (now / self.period * 360) % 360
        previous, self.angle = self.angle, angle
        self.trail = (self.trail + [angle])[-4:]
        planes = {p["hex"]: p for p in _RadarFeed.aircraft}
        for hex_, plane in planes.items():
            x, y = self.now_position(plane, now)
            if math.hypot(x, y) > self.km:
                self.memory.pop(hex_, None)
                continue
            bearing = math.degrees(math.atan2(x, y)) % 360
            swept = previous is not None and (bearing - previous) % 360 <= (angle - previous) % 360
            if swept or hex_ not in self.memory:
                # first sight: shown bright (no flash), so the dashboard takes over the splash's scope unchanged
                lit = now if swept else now - self.period * (0.1 if previous is None else 0.5)
                self.memory[hex_] = {"x": x, "y": y, "plane": plane, "lit": lit}
        for hex_ in [h for h in self.memory if h not in planes]:
            if now - self.memory[hex_]["lit"] > 2 * self.period:
                del self.memory[hex_]
        return angle

    # -- drawing -----------------------------------------------------------------------------------------------------
    def to_px(self, x, y):
        k = self.r / self.km
        return self.cx + x * k - self.box[0], self.cy - y * k - self.box[1]

    def scope_frame(self, angle, now, focus, limit=None):
        from PIL import Image, ImageDraw
        frame = self.scope.copy()
        layer = Image.new("RGB", frame.size, (0, 0, 0))
        d = ImageDraw.Draw(layer)
        ox, oy = self.cx - self.box[0], self.cy - self.box[1]
        # the sweep line, and its afterglow at the positions of the last frames. A full-radius line costs every row
        # it crosses on the screen's link, so it is 1 px wide and the afterglow is a few lines, not a filled wedge
        trail = self.trail[-1 - int(self.spec.get("TRAIL", 1)):] if angle is not None else []
        for i, a in enumerate(trail):
            level = 1.0 if i == len(trail) - 1 else 0.25 + 0.3 * i / max(1, len(trail) - 1)
            a = math.radians(a)
            d.line((ox, oy, ox + (self.r - 1) * math.sin(a), oy - (self.r - 1) * math.cos(a)),
                   fill=_lerp((0, 0, 0), self.col["SWEEP"], level))
        frame.paste(layer, (0, 0), _mask_of(layer, self.inside))

        d = ImageDraw.Draw(frame)
        tags = []
        ordered = sorted(self.memory.items(), key=lambda kv: (kv[0] != focus, math.hypot(kv[1]["x"], kv[1]["y"])))
        if limit is not None:
            ordered = ordered[:limit]
        for i, (hex_, seen) in enumerate(ordered):
            plane = seen["plane"]
            age = (now - seen["lit"]) / self.period
            fade = 1.0 if age < 0.5 else 0.6  # few steps: each one resends every blip
            colour = _lerp((0, 0, 0), self.colour(plane), fade)
            if age < 0.06:  # the sweep is passing over it: a white flash
                colour = _lerp(self.colour(plane), (255, 255, 255), 0.6)
            px, py = self.to_px(seen["x"], seen["y"])
            # heading vector, longer for faster aircraft
            length = 6 + min(14, plane["gs"] / 40)
            a = math.radians(plane["track"])
            d.line((px, py, px + length * math.sin(a), py - length * math.cos(a)), fill=colour)
            d.rectangle((px - 2, py - 2, px + 2, py + 2), fill=colour)
            if hex_ == focus:
                d.rectangle((px - 6, py - 6, px + 6, py + 6), outline=self.col["TEXT"])
            if i >= int(self.spec.get("TAGS", 8)):
                continue
            words = (plane["callsign"][:8], f"{plane['alt'] // 100:03d} {plane['gs']:.0f}")
            tw = 6 * max(len(w) for w in words)
            for dx, dy in ((7, -22), (7, 4), (-7 - tw, -22), (-7 - tw, 4)):
                box = (px + dx, py + dy, px + dx + tw, py + dy + 22)
                if (box[0] >= 2 and box[2] <= frame.width - 2 and box[1] >= 2 and box[3] <= frame.height - 2
                        and math.hypot((box[0] + box[2]) / 2 - ox, (box[1] + box[3]) / 2 - oy) < self.r - 10
                        and not any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in tags)):
                    tags.append(box)
                    d.text((box[0], box[1] + 10), words[0], font=self.small,
                           fill=self.col["TEXT"] if hex_ == focus else _lerp(self.col["TEXT"], (0, 0, 0), 0.15),
                           anchor="ls")
                    d.text((box[0], box[1] + 21), words[1], font=self.small, fill=self.colour(plane), anchor="ls")
                    break
        return frame

    def panel(self, focus_plane, others):
        """The flight card, the NEXT list and the aircraft count, redrawn only when what they say changes."""
        from PIL import ImageDraw
        spec = self.spec
        count = len(_RadarFeed.aircraft)
        stale = _RadarFeed.fetched is None or time.time() - _RadarFeed.fetched > 60
        route = _RadarFeed.routes.get(focus_plane["callsign"]) if focus_plane else None
        state = (focus_plane and (focus_plane["callsign"], self.altitude(focus_plane), round(focus_plane["gs"] / 5),
                                  focus_plane["type"], round(math.hypot(focus_plane["x"], focus_plane["y"])),
                                  round(focus_plane["rate"] / 500), str(route)),
                 tuple((p["callsign"], self.altitude(p), round(math.hypot(p["x"], p["y"]))) for p in others),
                 count, stale)
        if state == self.panel_state:
            return
        self.panel_state = state

        x1, y1, x2, y2 = (int(v) for v in spec["CARD"])
        card = self.base.crop((x1, y1, x2, y2))
        d = ImageDraw.Draw(card)
        rows = spec["CARD_ROWS"]  # baselines, relative to the card
        if focus_plane is None:
            d.text((0, rows[0]), "NO DATA" if stale else "CLEAR SKY", font=self.big,
                   fill=self.col["EMERGENCY"] if stale else self.col["DIM"], anchor="ls")
            d.text((0, rows[1]), (_RadarFeed.error or "waiting for the first answer")[:(x2 - x1) // 6]
                   if stale else "no aircraft in range", font=self.small, fill=self.col["DIM"], anchor="ls")
        elif spec.get("CARD_STYLE") == "wide":  # portrait: callsign and route on one line, then the numbers
            p, width = focus_plane, x2 - x1
            d.text((0, rows[0]), p["callsign"][:8], font=self.large, fill=self.col["TEXT"], anchor="ls")
            if route:
                d.text((width, rows[0]), f"{route['from']} → {route['to']}", font=self.big, fill=self.col["ROUTE"],
                       anchor="rs")
            else:
                d.text((width, rows[0]), (p["registration"] or "")[:8], font=self.big, fill=self.col["DIM"], anchor="rs")
            trend = "↑" if p["rate"] > 300 else "↓" if p["rate"] < -300 else ""
            d.text((0, rows[1]), self.altitude(p) + trend, font=self.big, fill=self.colour(p), anchor="ls")
            d.text((120, rows[1]), f"{p['gs']:.0f}KT", font=self.big, fill=self.col["TEXT"], anchor="ls")
            if route:
                d.text((width, rows[1]), route["airline"][:(width - 190) // 6], font=self.small,
                       fill=self.col["LABEL"], anchor="rs")
            distance = math.hypot(p["x"], p["y"])
            bearing = math.degrees(math.atan2(p["x"], p["y"])) % 360
            squawk = f"  SQUAWK {p['squawk']}" if self.colour(p) == self.col["EMERGENCY"] else ""
            d.text((0, rows[2]), f"{p['type'] or '----'}  {distance:.0f} km {_compass(bearing)}{squawk}",
                   font=self.small, fill=self.col["LABEL"], anchor="ls")
        else:
            p = focus_plane
            width = x2 - x1
            d.text((0, rows[0]), p["callsign"][:width // 18], font=self.large, fill=self.col["TEXT"], anchor="ls")
            if route:
                d.text((0, rows[1]), f"{route['from']} → {route['to']}", font=self.big, fill=self.col["ROUTE"],
                       anchor="ls")
                d.text((0, rows[2]), route["airline"][:width // 6], font=self.small, fill=self.col["LABEL"], anchor="ls")
            else:
                d.text((0, rows[1]), p["registration"] or p["callsign"], font=self.big, fill=self.col["DIM"],
                       anchor="ls")
            trend = "↑" if p["rate"] > 300 else "↓" if p["rate"] < -300 else ""
            d.text((0, rows[3]), self.altitude(p) + trend, font=self.big, fill=self.colour(p), anchor="ls")
            d.text((width, rows[3]), f"{p['gs']:.0f}KT", font=self.big, fill=self.col["TEXT"], anchor="rs")
            distance = math.hypot(p["x"], p["y"])
            bearing = math.degrees(math.atan2(p["x"], p["y"])) % 360
            squawk = f"  SQUAWK {p['squawk']}" if self.colour(p) == self.col["EMERGENCY"] else ""
            d.text((0, rows[4]), f"{p['type'] or '----'}  {distance:.0f} km {_compass(bearing)}{squawk}"[:width // 6],
                   font=self.small, fill=self.col["LABEL"], anchor="ls")
        self.lcd.DisplayPILImage(card, x1, y1)

        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LIST"])
        listing = self.base.crop((lx1, ly1, lx2, ly2))
        d = ImageDraw.Draw(listing)
        columns = int(spec.get("LIST_COLUMNS", 1))
        col_w = (lx2 - lx1) // columns
        for i, p in enumerate(others[:int(spec.get("LIST_ROWS", 4)) * columns]):
            cx_, row = (i % columns) * col_w, i // columns
            bl = int(spec["LIST_BL"]) + row * int(spec.get("LIST_STEP", 14)) - ly1
            d.text((cx_, bl), p["callsign"][:8], font=self.small, fill=self.col["TEXT"], anchor="ls")
            d.text((cx_ + 54, bl), self.altitude(p), font=self.small, fill=self.colour(p),
                   anchor="ls")
            d.text((cx_ + col_w - 6, bl), f"{math.hypot(p['x'], p['y']):.0f}km", font=self.small,
                   fill=self.col["LABEL"], anchor="rs")
        self.lcd.DisplayPILImage(listing, lx1, ly1)

        hx, hy, hw = (int(v) for v in spec["COUNT"])  # right edge, baseline, width
        strip = self.base.crop((hx - hw, hy - 11, hx, hy + 3))
        ImageDraw.Draw(strip).text((hw, 11), "NO DATA" if stale else f"{count} AIRCRAFT", font=self.small,
                                   fill=self.col["EMERGENCY"] if stale else self.col["LABEL"], anchor="rs")
        self.lcd.DisplayPILImage(strip, hx - hw, hy - 11)

    def step(self):
        """One frame: sweep, blips, then the panel if something it shows changed."""
        now = time.time()
        angle = self.sweep_over(now)
        seen = sorted(self.memory.items(), key=lambda kv: math.hypot(kv[1]["x"], kv[1]["y"]))
        focus = seen[0][0] if seen else None
        self.lcd.DisplayPILImage(self.scope_frame(angle, now, focus), self.box[0], self.box[1])
        planes = [s["plane"] for _, s in seen]
        _RadarFeed._want_routes = planes[:3]
        self.panel(planes[0] if planes else None, planes[1:])


def _mask_of(layer, inside):
    """Where a drawn layer has something, clipped to the scope's disc."""
    from PIL import ImageChops
    return ImageChops.multiply(layer.convert("L").point(lambda v: 255 if v else 0), inside)


class Bc250Radar:
    """Radar theme: starts the feed and the scope's drawing thread (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        radar = _Radar(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            radar.lcd = _Draw.screen  # shared with the other widgets: it knows the screen shows the background
        else:
            import numpy
            radar.lcd.shadow = numpy.asarray(radar.base).copy()  # the app has just drawn the background
        frame = 1 / float(spec.get("FPS", 8))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                continue
            _attempt("radar frame", radar.step)
            _Splash._wait(0)  # let the queue drain: the radar never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Radar")
        if spec and _Draw.enabled:
            _RadarFeed.start(float(spec["LAT"]), float(spec["LON"]), float(spec["RANGE_KM"]),
                             float(spec.get("REFRESH", 6)))
            if Bc250Radar._thread is None or not Bc250Radar._thread.is_alive():
                Bc250Radar._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 radar",
                                                      daemon=True)
                Bc250Radar._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


def _screen_level(lcd, fraction: float):
    """A share of the brightness the screen should have now (the theme's dimming stays in charge)."""
    from library import config
    spec = _Draw.theme("Bc250Screen").get("SCREEN", {})
    target = int(spec.get("DIM_BRIGHTNESS", 5)) if Bc250Screen._mode == "dim" else \
        int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))
    lcd.SetBrightness(max(0, min(100, round(target * fraction))))


class _QuakeFeed:
    """The world's earthquakes, from the USGS's public feeds (no key, updated every minute): the past day when it
    starts and every hour, the past hour every minute. It only reads a public list: nothing about this machine or its
    location is sent. Like the radar, it stops asking while the screen sleeps."""
    URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{tier}_{span}.geojson"
    AGENT = "bc250-themes"
    KEEP = 24 * 3600  # seconds
    FRESH = 3600  # a quake older than this that shows up late goes on the map, but isn't played
    quakes = {}  # id -> quake
    arrivals = []  # the ones still to be played
    fetched = None
    error = None
    _thread = None

    @staticmethod
    def tier(min_mag: float) -> str:
        return "1.0" if min_mag < 2.5 else "2.5" if min_mag < 4.5 else "4.5"

    @classmethod
    def _get(cls, url: str):
        import json
        import urllib.request
        fixture = os.environ.get("BC250_QUAKE_FIXTURE")  # tests and previews: a saved answer instead of the network
        if fixture:
            with open(fixture, encoding="utf-8") as f:
                raw = json.load(f)
            for feature in raw["features"]:  # its times count back from now
                if (feature["properties"].get("time") or 0) < 0:
                    feature["properties"]["time"] += time.time() * 1000
            return raw
        request = urllib.request.Request(url, headers={"User-Agent": cls.AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=15) as answer:
            return json.loads(answer.read().decode("utf-8"))

    @staticmethod
    def _parse(raw: dict, min_mag: float) -> List[dict]:
        quakes = []
        for feature in raw.get("features") or []:
            try:
                p = feature["properties"]
                lon, lat, depth = feature["geometry"]["coordinates"][:3]
                if p.get("type") != "earthquake" or p.get("mag") is None or p["mag"] < min_mag:
                    continue  # (the feed also lists quarry blasts and the like)
                quakes.append({"id": str(feature["id"]), "mag": float(p["mag"]), "place": p.get("place") or "unknown place",
                               "time": float(p["time"]) / 1000, "lat": float(lat), "lon": float(lon),
                               "depth": float(depth or 0)})
            except (KeyError, TypeError, ValueError):
                continue  # one odd entry must not lose the others
        return quakes

    @classmethod
    def ingest(cls, raw: dict, min_mag: float, first: bool = False):
        """Takes in an answer. The first one fills the map, and only its latest quake is played: the page shouldn't
        stay blank until the next one."""
        now = time.time()
        new = [q for q in cls._parse(raw, min_mag) if q["id"] not in cls.quakes]
        for quake in new:
            cls.quakes[quake["id"]] = quake
        if first:
            cls.arrivals = sorted(new, key=lambda q: q["time"])[-1:]
        else:
            cls.arrivals = (cls.arrivals + sorted((q for q in new if now - q["time"] < cls.FRESH),
                                                  key=lambda q: q["time"]))[-5:]
        for key in [k for k, q in cls.quakes.items() if now - q["time"] > cls.KEEP]:
            del cls.quakes[key]

    @classmethod
    def start(cls, min_mag: float):
        import threading
        if cls._thread is None or not cls._thread.is_alive():
            cls._thread = threading.Thread(target=cls._run, args=(min_mag,), name="BC250 quake feed", daemon=True)
            cls._thread.start()

    @classmethod
    def _run(cls, min_mag: float):
        tier, first, rounds = cls.tier(min_mag), True, 0
        while True:
            if Bc250Screen._mode == "off":
                time.sleep(5)
                continue
            span = "day" if first or rounds % 60 == 0 else "hour"
            try:
                cls.ingest(cls._get(cls.URL.format(tier=tier, span=span)), min_mag, first)
                cls.fetched, cls.error, first = time.time(), None, False
            except Exception as e:
                cls.error = str(e)
            rounds += 1
            time.sleep(60)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1.0, math.sqrt(h)))


def _short_place(place: str) -> str:
    """"78 km SSW of Neiafu, Tonga" -> "Neiafu, Tonga"."""
    return place.split(" of ", 1)[1] if " of " in place else place


class _Seismo:
    """The seismograph: a helicorder, the drum recorder observatories use. The paper stays still and the pen writes
    line after line across it, each line in another ink, so only the new ink has to reach the screen and what happened
    stays on the page. The pen trembles with what this machine is doing; a real earthquake from the feed throws it
    across the lines, with the shape a seismogram has (the small fast P waves, then the big S waves, then the long
    decay), writes its name beside it, puts it on the map, and from about magnitude 5.5 makes the backlight shake."""
    SHAKE_MAG, TREMBLE_MAG = 5.0, 5.5
    played = rows_started = 0  # (read by the tests)

    def __init__(self, spec: dict, lcd, base):
        self.spec, self.lcd, self.base = spec, lcd, base
        self.x, self.y, self.w, self.h = (int(v) for v in spec["PAPER"])
        self.rows, self.margin = int(spec["ROWS"]), int(spec["MARGIN"])
        self.row_h = self.h // self.rows
        self.blank = base.crop((self.x, self.y, self.x + self.w, self.y + self.h))
        self.paper = self.blank.copy()
        self.inks = [tuple(c) for c in spec["INKS"]]
        self.col_ = {k: _Draw.color(v) for k, v in spec["COLORS"].items()}
        self.small, self.big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 36)
        self.speed = float(os.environ.get("BC250_SEISMO_SPEED") or spec.get("SPEED", 2.5))  # pixels a second
        self.station = (float(spec["LAT"]), float(spec["LON"])) if "LAT" in spec else None
        self.row = -1
        self.active = None  # the quake being written: {"quake", "start": column count, "length", "height"}
        self.written = 0.0  # columns so far
        self.focus = None
        self.cpu = 0.0
        self.next_cpu = 0.0
        self.game = None
        self.last = time.monotonic()
        self.frame_no = 0
        self.next_row()

    # -- the paper ---------------------------------------------------------------------------------------------------
    def baseline(self) -> int:
        return self.row * self.row_h + self.row_h // 2

    def next_row(self):
        import datetime
        from PIL import ImageDraw
        self.row = (self.row + 1) % self.rows
        top = self.row * self.row_h
        self.paper.paste(self.blank.crop((0, top, self.w, top + self.row_h)), (0, top))  # the oldest line goes
        ImageDraw.Draw(self.paper).text((3, self.baseline() + 4), datetime.datetime.now().strftime("%H:%M"),
                                        font=self.small, fill=self.col_["PAPER_DIM"], anchor="ls")
        self.col = float(self.margin)
        self.pen_y = float(self.baseline())
        _Seismo.rows_started += 1

    def annotate(self, words: str, fill=(168, 34, 30)):
        """A note on the paper, by what the pen is writing."""
        from PIL import ImageDraw
        x = round(self.col) + 3
        room = (self.w - x) // 6
        if room < 6:
            return None
        note = (x, self.baseline() - 3, words[:room], fill)
        ImageDraw.Draw(self.paper).text(note[:2], note[2], font=self.small, fill=fill, anchor="ls")
        return note

    # -- what the pen feels ------------------------------------------------------------------------------------------
    def tremor(self) -> float:
        """This machine's own activity: a pen that barely moves when idle, and shakes under load."""
        import random
        gpu = Bc250GpuLoad.value
        gpu = gpu if isinstance(gpu, (int, float)) and gpu == gpu else 0.0
        size = 0.6 + 0.03 * self.cpu + 0.04 * gpu  # stays within its line: a real quake has to stand out
        return random.uniform(-size, size)

    def quake_signal(self):
        """The quake's waves at this point of the paper, and how far along it is (None when it is over)."""
        import random
        if not self.active:
            return 0.0, None
        p = (self.written - self.active["start"]) / self.active["length"]
        if p >= 1:
            note = self.active.get("note")
            if note:  # written again over the waves, on a clean patch, so that it can be read
                from PIL import ImageDraw
                d = ImageDraw.Draw(self.paper)
                x, y, words, fill = note
                d.rectangle((x - 1, y - 10, x + round(self.small.getlength(words)) + 1, y + 2), fill=(238, 230, 208))
                d.text((x, y), words, font=self.small, fill=fill, anchor="ls")
            self.active = None
            _screen_level(self.lcd, 1)
            return 0.0, None
        height = self.active["height"]
        if p < 0.14:  # P waves: small and fast
            envelope = 0.22 * (0.4 + p / 0.14 * 0.6)
        elif p < 0.26:
            envelope = 0.22 + 0.5 * (p - 0.14)
        elif p < 0.34:  # S waves arrive
            envelope = 0.28 + 0.72 * (p - 0.26) / 0.08
        else:  # and it dies away
            envelope = math.exp(-(p - 0.34) * 4.2)
        return random.uniform(-1, 1) * height * envelope, p

    def play_next(self):
        if self.active or not _QuakeFeed.arrivals:
            return
        quake = _QuakeFeed.arrivals.pop(0)
        mag = quake["mag"]
        self.active = {"quake": quake, "start": self.written, "length": max(10.0, (6 + (mag - 2.5) * 10) * 2.5),
                       "height": min(90.0, max(3.0, 5 * 2 ** ((mag - 2.5) / 0.9 * 0.8)))}
        self.focus = quake
        self.active["note"] = self.annotate(f"M{mag:.1f} {_short_place(quake['place'])}")
        _Seismo.played += 1

    def notice_game(self):
        """A game starting is an event of this machine's own: noted on the paper too."""
        game = _attempt("seismograph game", _Steam.current_game)
        key = game[0] if game else None
        if key != self.game:
            self.game = key
            if key:
                self.annotate(_Session.name or _Steam.app_name(key), self.inks[self.row % len(self.inks)])

    def write(self, seconds: float):
        import random
        from PIL import ImageDraw
        d = ImageDraw.Draw(self.paper)
        advance = seconds * self.speed
        samples = max(1, math.ceil(advance))
        ink = self.inks[self.row % len(self.inks)]
        for _ in range(samples):
            self.col += advance / samples
            self.written += advance / samples
            if self.col >= self.w - 2:
                self.next_row()
                d = ImageDraw.Draw(self.paper)
                ink = self.inks[self.row % len(self.inks)]
            wave, _p = self.quake_signal()
            y = self.baseline() + self.tremor() + wave
            d.line((round(self.col), round(self.pen_y), round(self.col), round(y)), fill=ink)
            self.pen_y = y
        if self.active:
            p = (self.written - self.active["start"]) / self.active["length"]
            if self.active["quake"]["mag"] >= self.TREMBLE_MAG and 0.26 < p < 0.75:
                _screen_level(self.lcd, 1 + random.uniform(-0.3, 0.3))  # the whole screen, for one small command

    def paper_frame(self):
        from PIL import ImageDraw
        frame = self.paper.copy()
        d = ImageDraw.Draw(frame)
        x, y = round(self.col), round(self.pen_y)
        d.line((x, y, x + 9, max(0, y - 15)), fill=(70, 62, 46), width=2)  # the pen's arm
        d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(150, 30, 26))
        return frame

    # -- what is around it -------------------------------------------------------------------------------------------
    def shake(self):
        """How far things are thrown right now."""
        import random
        if not self.active or self.active["quake"]["mag"] < self.SHAKE_MAG:
            return 0, 0
        p = (self.written - self.active["start"]) / self.active["length"]
        if not 0.26 < p < 0.7:
            return 0, 0
        size = 3 if self.active["quake"]["mag"] >= 6.5 else 2
        return random.randint(-size, size), random.randint(-1, 1)

    def latest(self):
        quakes = list(_QuakeFeed.quakes.values())
        return max(quakes, key=lambda q: q["time"]) if quakes else None

    def card(self):
        from PIL import ImageDraw
        x, y, w, h = (int(v) for v in self.spec["CARD"])
        box = (x, y + 14, x + w, y + h)
        strip = self.base.crop(box)
        d = ImageDraw.Draw(strip)
        quake = self.focus or self.latest()
        dx, dy = self.shake()
        top = box[1]
        if quake is None:
            words = "NO ANSWER FROM USGS" if _QuakeFeed.error else "LISTENING..."
            d.text((2, y + 34 - top), words[:w // 6], font=self.small, fill=self.col_["RED" if _QuakeFeed.error else "DIM"], anchor="ls")
        else:
            mag = quake["mag"]
            fill = self.col_["RED"] if mag >= 6 else self.col_["AMBER"] if mag >= 4.5 else self.col_["BRIGHT"]
            d.text((2 + dx, y + 44 - top + dy), f"M{mag:.1f}", font=self.big, fill=fill, anchor="ls")
            d.text((w - 2 + dx, y + 28 - top + dy), f"{quake['depth']:.0f} KM", font=self.small, fill=self.col_["MID"], anchor="rs")
            d.text((w - 2 + dx, y + 42 - top + dy), "DEEP", font=self.small, fill=self.col_["DIM"], anchor="rs")
            lines, line, chars = [], "", w // 6
            for word in _short_place(quake["place"]).split():
                if len(line) + len(word) + 1 > chars and line:
                    lines.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            lines.append(line)
            for n, words in enumerate(lines[:2]):
                d.text((2 + dx, y + 56 + 13 * n - top + dy), words[:chars], font=self.small, fill=self.col_["BRIGHT"], anchor="ls")
            ago = _duration(max(0, time.time() - quake["time"]))
            if self.station:
                far = _distance_km(self.station[0], self.station[1], quake["lat"], quake["lon"])
                note = f"{far:,.0f} KM AWAY  {ago}".replace(",", " ")
            else:
                note = f"{ago} AGO"
            d.text((2 + dx, y + 82 - top + dy), note[:chars], font=self.small, fill=self.col_["MID"], anchor="ls")
        self.lcd.DisplayPILImage(strip, box[0], box[1])
        # how long ago, beside the heading
        return quake

    def world(self):
        from PIL import ImageDraw
        x, y, w, h = (int(v) for v in self.spec["MAP"])
        frame = self.base.crop((x, y, x + w, y + h))
        d = ImageDraw.Draw(frame)
        now = time.time()
        project = lambda lon, lat: ((lon + 180) / 360 * w, (90 - lat) / 180 * h)
        focus = self.focus or self.latest()
        for quake in sorted(_QuakeFeed.quakes.values(), key=lambda q: q["time"]):
            px, py = project(quake["lon"], quake["lat"])
            size = 1 if quake["mag"] < 4.5 else 2 if quake["mag"] < 6 else 3
            fill = self.col_["RED"] if now - quake["time"] < 3600 else self.col_["AMBER"]
            d.ellipse((px - size, py - size, px + size, py + size), fill=fill)
        if focus:  # the one on the card: waves spreading from it
            px, py = project(focus["lon"], focus["lat"])
            radius = 3 + (self.frame_no // 2) % 8
            d.ellipse((px - radius, py - radius, px + radius, py + radius), outline=self.col_["RED"])
        if self.station:
            px, py = project(self.station[1], self.station[0])
            d.line((px - 2, py, px + 2, py), fill=self.col_["BRIGHT"])
            d.line((px, py - 2, px, py + 2), fill=self.col_["BRIGHT"])
        self.lcd.DisplayPILImage(frame, x, y)

    def header(self):
        from PIL import ImageDraw
        x, bl, xr = (int(v) for v in self.spec["HEADER"])
        if xr <= x:
            return
        box = (x, bl - 11, xr, bl + 3)
        strip = self.base.crop(box)
        quakes = list(_QuakeFeed.quakes.values())
        chars = (xr - x) // 6
        if _QuakeFeed.error and not quakes:
            words, fill = "NO ANSWER FROM USGS", self.col_["RED"]
        elif quakes:
            top = max(q["mag"] for q in quakes)
            words = f"{len(quakes)} QUAKES IN 24 H, LARGEST M{top:.1f}"
            words = words if len(words) <= chars else f"{len(quakes)} IN 24H, MAX M{top:.1f}"
            fill = self.col_["DIM"]
        else:
            words, fill = "LISTENING...", self.col_["DIM"]
        ImageDraw.Draw(strip).text((0, bl - box[1]), words[:chars], font=self.small, fill=fill, anchor="ls")
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    def step(self):
        import psutil
        now = time.monotonic()
        seconds, self.last = now - self.last, now
        if now >= self.next_cpu:
            self.next_cpu = now + 1
            self.cpu = _attempt("seismograph load", lambda: psutil.cpu_percent(None)) or 0.0
            self.notice_game()
        self.play_next()
        self.write(min(seconds, 2.0))
        self.lcd.DisplayPILImage(self.paper_frame(), self.x, self.y)
        self.frame_no += 1
        shaking = self.shake() != (0, 0)
        if shaking or self.frame_no % 4 == 0:
            self.card()
            self.world()
        if self.frame_no % 16 == 1:
            self.header()


class Bc250Seismograph:
    """Seismograph theme: starts the feed and the pen's thread (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        pen = _Seismo(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            pen.lcd = _Draw.screen  # shared with the other widgets: it knows the screen shows the background
        else:
            import numpy
            pen.lcd = _Screen(display.lcd, *pen.base.size)
            pen.lcd.shadow = numpy.asarray(pen.base).copy()  # the app has just drawn the background
        pen.lcd.TILE = int(spec.get("TILE", 10))
        frame = 1 / float(spec.get("FPS", 8))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                pen.last = time.monotonic()  # the paper doesn't turn while the screen sleeps
                continue
            _attempt("seismograph frame", pen.step)
            _Splash._wait(0)  # let the queue drain: the pen never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Seismograph")
        if spec and _Draw.enabled:
            _QuakeFeed.start(float(spec.get("MIN_MAG", 2.5)))
            if Bc250Seismograph._thread is None or not Bc250Seismograph._thread.is_alive():
                Bc250Seismograph._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 seismograph",
                                                            daemon=True)
                Bc250Seismograph._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


class _Horror:
    """The horror theme's camera. A corridor, and something standing in it that only ever moves when the lights go
    out: the backlight flickers and dies, and when it comes back the figure is closer and MOTION has counted down.
    When it reaches the camera its face fills the feed; then the corridor is empty, and that is worse. Between those,
    the console talks to you about what it can see (your name, the time, your game, the temperatures), and now and
    then a label is not what it was. Almost free on the link: what moves does so in the dark or in a few small boxes
    (_Screen sends only what changed), and a flicker is one brightness command."""
    NEAR = 7  # metres: from here it is an emergency
    moves = scares = whispers = 0  # (read by the tests)

    def __init__(self, spec: dict, lcd, base):
        import random
        from PIL import Image
        self.spec, self.lcd, self.base = spec, lcd, base
        fast = bool(os.environ.get("BC250_HORROR_FAST"))  # the tests: the whole encounter in a few seconds
        self.speed = 0.03 if fast else 1.0
        self.x, self.y, self.w, self.h = (int(v) for v in spec["FEED"])
        self.room = base.crop((self.x, self.y, self.x + self.w, self.y + self.h))
        self.stages = spec["STAGES"]
        self.eyes = spec["EYES"]
        self.sprite = Image.open(_Draw.background_path(spec["FIGURE"])).convert("RGBA")
        self.small, self.large = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 36)
        self.col = {k: _Draw.color(v) for k, v in spec["COLORS"].items()}
        self.motion = tuple(int(v) for v in spec["MOTION"])
        self.layers = {}
        self.stage = 2  # it is already down there when you first look
        self.last_move = time.monotonic()
        now = time.monotonic()
        self.next_move = now + random.uniform(30, 60) * self.speed
        self.next_whisper = now + 8 * self.speed
        self.next_flicker = now + random.uniform(10, 25) * self.speed
        self.next_glitch = now + random.uniform(20, 50) * self.speed
        self.next_band = now + random.uniform(6, 18) * self.speed
        self.next_blink = now + random.uniform(4, 10)
        self.blinking_until = 0.0
        self.band_start = None
        self.whisper = None  # (lines, when it started)
        self.glitch = None  # (label, until)
        self.queue = []
        self.empty_until = 0.0

    # -- the screen's light ------------------------------------------------------------------------------------------
    def level(self, fraction: float):
        _screen_level(self.lcd, fraction)

    def flicker(self, *steps):
        for fraction, seconds in steps:
            self.level(fraction)
            time.sleep(seconds)

    # -- what it looks like ------------------------------------------------------------------------------------------
    def layer(self, index: int):
        return _Horror.figure_layer(self.sprite, self.stages[index], self.layers, index)

    @staticmethod
    def figure_layer(sprite, stage, cache, index):
        """The figure at a stage: (picture, x, y in the feed), as much light on it as there is where it stands."""
        from PIL import Image
        if index not in cache:
            _, x, top, height, light = stage
            height = int(height)
            art = sprite.resize((max(2, height // 3), max(2, height)), Image.BILINEAR)
            r, g, b, a = art.split()
            shade = lambda v: int(v * float(light))
            cache[index] = (Image.merge("RGBA", (r.point(shade), g.point(shade), b.point(shade), a)),
                            int(x) - art.width // 2, int(top))
        return cache[index]

    def eye_points(self, index: int):
        art, fx, fy = self.layer(index)
        size = 1 if art.height < 200 else 2
        return [(fx + round(ex * art.width), fy + round(ey * art.height), size) for ex, ey in self.eyes]

    def feed(self, stage=None, overlay=True):
        import datetime
        import random
        from PIL import Image, ImageDraw
        now = time.monotonic()
        frame = self.room.copy()
        d = ImageDraw.Draw(frame)
        index = self.stage if stage is None else stage
        if index >= 0:
            art, fx, fy = self.layer(index)
            frame.paste(art, (fx, fy), art)
            if now > self.next_blink:  # it blinks. Not often
                self.blinking_until = now + 0.18
                self.next_blink = now + random.uniform(5, 14)
            if now > self.blinking_until:
                for ex, ey, size in self.eye_points(index):
                    d.rectangle((ex, ey, ex + size - 1, ey + size - 1), fill=(236, 242, 226))
        if not overlay:
            return frame
        if int(time.time() * 2) % 2:
            d.ellipse((8, 7, 14, 13), fill=self.col["RED"])
        d.text((19, 15), "REC", font=self.small, fill=self.col["BRIGHT"], anchor="ls")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        d.text((self.w - 6, 15), stamp, font=self.small, fill=self.col["BRIGHT"], anchor="rs")
        if self.band_start is not None:  # the tape's tracking, rolling down the picture
            p = (now - self.band_start) / 1.1
            if p >= 1:
                self.band_start = None
            else:
                noise = Image.effect_noise((self.w, 5), 110).convert("RGB")
                frame.paste(noise, (0, round(p * (self.h - 5))))
        if self.whisper:
            lines, start = self.whisper
            shown = int((now - start) * 13 / max(self.speed, 0.25))
            total = sum(len(line) for line in lines)
            if now - start > total / 13 * max(self.speed, 0.25) + 5 * self.speed:
                self.whisper = None
            else:
                y = self.h - 8 - 14 * (len(lines) - 1)
                for line in lines:
                    part = line[:max(0, shown)]
                    shown -= len(line)
                    if part:
                        width = round(self.small.getlength(part))
                        d.rectangle(((self.w - width) // 2 - 3, y - 11, (self.w + width) // 2 + 3, y + 3), fill=(0, 0, 0))
                        d.text(((self.w - width) // 2, y), part, font=self.small, fill=(232, 236, 222), anchor="ls")
                    y += 14
        return frame

    def show(self, frame):
        self.lcd.DisplayPILImage(frame, self.x, self.y)

    def panel(self):
        """MOTION: how far it is, what it is doing, how long ago it moved."""
        from PIL import ImageDraw
        mx, my, mw, mh = self.motion
        _, bl_big, bl_a, bl_b = (int(v) for v in self.spec["MOTION_ROWS"])
        top = my + 14
        box = (mx, top, mx + mw, my + mh)
        strip = self.base.crop(box)
        d = ImageDraw.Draw(strip)
        ago = int(time.monotonic() - self.last_move)
        if self.stage < 0:
            big, line_a, line_b, fill = "-- m", "NOT ON CAMERA", "WHERE IS IT", self.col["RED"]
        else:
            metres = float(self.stages[self.stage][0])
            near = metres <= self.NEAR
            big = f"{metres:.0f} m"
            line_a = "DO NOT LOOK AWAY" if metres < 5 else "APPROACHING" if near else "IN THE CORRIDOR"
            line_b = f"MOVED {ago // 60}:{ago % 60:02d} AGO"
            fill = self.col["RED"] if near else self.col["BRIGHT"]
        d.text((2, bl_big - top), big, font=self.large, fill=fill, anchor="ls")
        d.text((2, bl_a - top), line_a, font=self.small, fill=fill, anchor="ls")
        d.text((2, bl_b - top), line_b, font=self.small, fill=self.col["MID"], anchor="ls")
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    def label_glitch(self):
        """A label reads something else, for a moment."""
        import random
        now = time.monotonic()
        if self.glitch and now > self.glitch[1]:
            self.draw_label(self.glitch[0], False)
            self.glitch = None
        if self.glitch is None and now > self.next_glitch:
            self.next_glitch = now + random.uniform(25, 90) * self.speed
            label = random.choice(list(self.spec["LABELS"]) + [None])
            self.glitch = (label, now + 0.35)
            self.draw_label(label, True)

    def draw_label(self, label, wrong: bool):
        from PIL import ImageDraw
        if label is None:  # the camera's name, in the header
            x, bl, word, other = self.spec["TITLE"]
            x, bl = int(x), int(bl)
            box = (x, bl - 11, x + 6 * max(len(word), len(other)) + 2, bl + 3)
            strip = self.base.crop(box)
            if wrong:
                strip.paste((5, 7, 6), (0, 0, strip.width, strip.height))
                ImageDraw.Draw(strip).text((0, bl - box[1]), other, font=self.small, fill=self.col["RED"], anchor="ls")
        else:
            word, x, bl, anchor, other = label
            x, bl = int(x), int(bl)
            width = 6 * max(len(word), len(other)) + 2
            box = (x, bl - 11, x + width, bl + 3) if anchor == "ls" else (x - width, bl - 11, x, bl + 3)
            strip = self.base.crop(box)
            if wrong:
                strip.paste((5, 7, 6), (0, 0, strip.width, strip.height))
                ImageDraw.Draw(strip).text((0 if anchor == "ls" else width, bl - box[1]), other, font=self.small,
                                           fill=self.col["RED"], anchor=anchor)
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    # -- what it says ------------------------------------------------------------------------------------------------
    def lines_to_say(self):
        """What it could say right now, from what the machine actually sees."""
        import datetime
        import psutil
        user = self.spec.get("USER", "YOU")
        now = datetime.datetime.now()
        said = [f"{user}. I CAN SEE YOU.", "IT ONLY MOVES WHEN YOU CAN'T SEE IT.",
                "THE CAMERA IS NOT THE ONLY ONE WATCHING.", "THE DOOR ON THE RIGHT WAS CLOSED BEFORE."]
        said.append(f"IT IS {now:%H:%M}. WHY ARE YOU STILL UP?" if now.hour >= 23 or now.hour < 6 else
                    f"IT IS {now:%H:%M}. IT IS ALWAYS NIGHT DOWN HERE.")
        temp = _attempt("whisper temp", lambda: Bc250CpuTemp().read())
        if temp is not None:
            said.append(f"{temp:.0f}°. IT LIKES THE WARMTH." if temp >= 60 else f"{temp:.0f}°. IT IS COLD DOWN THERE.")
        uptime = _attempt("whisper uptime", lambda: time.time() - psutil.boot_time())
        if uptime:
            said.append(f"AWAKE FOR {_duration(uptime)}. IT DOESN'T SLEEP EITHER.")
        memory = _attempt("whisper memory", psutil.virtual_memory)
        if memory:
            said.append(f"{memory.available / 1024 ** 3:.0f} GB FREE. THERE IS ROOM FOR IT.")
        if _attempt("whisper game", _Steam.current_game):
            name = (_Session.name or "THIS").upper()
            said += [f"{name}. IT WATCHED YOU PLAY THAT.",
                     f"{_duration(_Session.seconds)} IN {name} AND YOU HAVEN'T LOOKED BEHIND YOU ONCE.",
                     "YOU CAN'T HEAR IT OVER THE GAME."]
        else:
            load = _attempt("whisper load", lambda: psutil.cpu_percent(None))
            if load is not None:
                said.append(f"NOBODY IS PLAYING. WHO IS USING {load:.0f}% OF THE CPU?")
        if self.stage >= 0 and float(self.stages[self.stage][0]) <= self.NEAR:
            said = ["DON'T LOOK AT IT.", "IT HEARD THAT.", "TOO LATE TO TURN THE SCREEN OFF.",
                    f"{user}. DON'T MOVE."]
        if self.stage < 0:
            said = ["WHERE DID IT GO?", "CHECK BEHIND THE SCREEN.", "IT KNOWS THE WAY UP NOW.",
                    f"{user}. IS YOUR DOOR CLOSED?"]
        return said

    def say(self, words: str):
        chars = self.w // 6 - 2  # two lines at most, cut at a word
        lines, line = [], ""
        for word in words.split():
            if len(line) + len(word) + 1 > chars and line:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        self.whisper = (lines[:2], time.monotonic())
        _Horror.whispers += 1

    # -- what happens ------------------------------------------------------------------------------------------------
    def lights_out(self):
        """The lights die. When they come back, it is closer."""
        import random
        self.whisper = None
        self.flicker((0.5, 0.06), (0.08, 0.05), (0.8, 0.09), (0.05, 0.07), (0.4, 0.05))
        self.level(0)
        _Horror.moves += 1
        last = self.stage >= len(self.stages) - 1
        if last:
            self.encounter()
            return
        self.stage = 0 if self.stage < 0 else self.stage + 1
        self.show(self.feed())
        self.panel()
        _Splash._wait(0)
        time.sleep(random.uniform(0.5, 1.8) * max(self.speed, 0.3))
        self.last_move = time.monotonic()
        self.flicker((0.3, 0.05), (0.02, 0.07), (0.7, 0.06), (0.15, 0.05))
        self.level(1)
        self.next_move = time.monotonic() + random.uniform(25, 70) * self.speed

    def encounter(self):
        """It has reached the camera."""
        import random
        if self.spec.get("JUMPSCARE", True):
            from PIL import Image
            face = Image.open(_Draw.background_path(self.spec["FACE"])).convert("RGB")
            self.show(face)  # sent in the dark: it takes the link most of a second, and that second is part of it
            _Splash._wait(0)
            time.sleep(0.25)
            self.level(4)  # as bright as the screen goes, for a third of a second
            time.sleep(0.33)
            _Horror.scares += 1
        self.level(0)
        self.stage = -1
        self.show(self.feed())
        self.panel()
        _Splash._wait(0)
        time.sleep(2.2 * max(self.speed, 0.3))
        self.last_move = time.monotonic()
        self.flicker((0.2, 0.08), (0.02, 0.1), (0.5, 0.08), (0.1, 0.12))
        self.level(1)
        self.queue = ["IT ISN'T ON THE CAMERA ANYMORE."]
        self.next_whisper = time.monotonic() + 1.5 * self.speed
        self.next_move = time.monotonic() + random.uniform(150, 330) * self.speed  # the corridor stays empty a while

    def step(self):
        import random
        now = time.monotonic()
        if now >= self.next_move:
            self.lights_out()
            return
        if now >= self.next_flicker:  # only a bad contact... probably
            self.next_flicker = now + random.uniform(15, 55) * self.speed
            self.flicker(*[(random.uniform(0.15, 0.7), random.uniform(0.03, 0.09)) for _ in range(random.randrange(2, 5))])
            self.level(1)
        if now >= self.next_band:
            self.next_band = now + random.uniform(7, 24) * self.speed
            self.band_start = now
        if self.whisper is None and now >= self.next_whisper:
            self.next_whisper = now + random.uniform(22, 55) * self.speed
            words = self.queue.pop(0) if self.queue else random.choice(self.lines_to_say())
            self.say(words)
        self.show(self.feed())
        self.panel()
        self.label_glitch()


class Bc250Horror:
    """Horror theme: starts the camera's thread (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        camera = _Horror(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            camera.lcd = _Draw.screen  # shared with the other widgets: it knows the screen shows the background
        else:
            camera.lcd = _Screen(display.lcd, *camera.base.size)
            import numpy
            camera.lcd.shadow = numpy.asarray(camera.base).copy()  # the app has just drawn the background
        camera.lcd.TILE = int(spec.get("TILE", 10))
        frame = 1 / float(spec.get("FPS", 8))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                continue
            _attempt("horror frame", camera.step)
            _Splash._wait(0)  # let the queue drain: the camera never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Horror")
        if spec and _Draw.enabled and (Bc250Horror._thread is None or not Bc250Horror._thread.is_alive()):
            Bc250Horror._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 horror", daemon=True)
            Bc250Horror._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


class Bc250Met:
    """Mission elapsed time (Mission Control theme): the uptime as DDD:HH:MM:SS."""

    def as_numeric(self) -> float:
        return math.nan

    def as_string(self) -> str:
        import psutil
        t = max(0, int(time.time() - psutil.boot_time()))
        return f"{t // 86400:03d}:{t // 3600 % 24:02d}:{t // 60 % 60:02d}:{t % 60:02d}"

    def last_values(self) -> List[float]:
        pass


class Bc250CpuTemp(_TempWidget):
    last_val = [math.nan] * HISTORY_SIZE

    def read(self) -> Optional[float]:
        try:
            import psutil
            temps = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return None
        for chip in ("k10temp", "zenpower"):
            entries = temps.get(chip) or []
            # Tctl/Tdie is the package temperature; other entries are per-CCD
            for entry in entries:
                if entry.label in ("Tctl", "Tdie"):
                    return entry.current
            if entries:
                return entries[0].current
        return None


# ---------------------------------------------------------------------------------------------------------------------
# Steam: libraries, running game, downloads, game disk
# ---------------------------------------------------------------------------------------------------------------------
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
        for pid in os.listdir(PROC_ROOT):
            if not pid.isdigit():
                continue
            try:
                with open(os.path.join(PROC_ROOT, pid, "cmdline"), "rb") as f:
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
        stat = _read(os.path.join(PROC_ROOT, pid, "stat"))
        uptime = _read(os.path.join(PROC_ROOT, "uptime"))
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


# ---------------------------------------------------------------------------------------------------------------------
# Bottom prompt line: boot / playing / downloading / last session
# ---------------------------------------------------------------------------------------------------------------------
class _Session:
    """The game being played, its peak temperatures, and the last finished session.

    A session shorter than MIN_SECONDS is not remembered: launches that fail or quit at once leave no trace."""
    MIN_SECONDS = 60
    app_id = None
    name = None
    pid = None
    seconds = None
    peak_cpu = None
    peak_gpu = None
    last = None  # {"name", "seconds", "peak_cpu", "peak_gpu"} of the previous game

    @classmethod
    def update(cls, game):
        if cls.app_id is not None and (game is None or game[0] != cls.app_id):
            cls._finish()
        if game is None:
            return
        if cls.app_id is None:
            cls.app_id, cls.name = game[0], _Steam.app_name(game[0])
            cls.peak_cpu = cls.peak_gpu = None
        cls.pid = game[1]
        cls.seconds = _Steam.seconds_running(game[1])
        for attr, temp in (("peak_cpu", Bc250CpuTemp.value), ("peak_gpu", Bc250GpuTemp.value)):
            if not _is_nan(temp):
                setattr(cls, attr, max(getattr(cls, attr) or temp, temp))

    @classmethod
    def _finish(cls):
        if (cls.seconds or 0) >= cls.MIN_SECONDS:
            cls.last = {"name": cls.name, "seconds": cls.seconds, "peak_cpu": cls.peak_cpu, "peak_gpu": cls.peak_gpu}
        cls.app_id = cls.name = cls.pid = cls.seconds = None


def _attempt(what: str, fn, default=None):
    """fn() or default: one failing data source must not freeze the whole prompt line."""
    try:
        return fn()
    except Exception as e:
        if what not in _Draw._failed:
            _Draw._failed.add(what)
            logger.error("BC250: %s failed: %s", what, e)
        return default


def _rate(bps: float) -> str:
    for unit in ("B", "K", "M", "G"):
        if bps < 1000 or unit == "G":
            return f"{bps:.0f}{unit}/s" if unit == "B" else f"{bps:.1f}{unit}/s"
        bps /= 1000
    return "--"


def _peaks(cpu, gpu) -> str:
    fmt = lambda t: "--" if t is None else f"{t:.0f}"
    return f"{fmt(cpu)}/{fmt(gpu)}°"


class Bc250Prompt:
    BOOT_TICKS = 4
    _tick = 0

    @staticmethod
    def _state(tick: int) -> dict:
        """What the prompt shows: cmd word, main text, two right columns (label, value), progress fraction."""
        if tick <= Bc250Prompt.BOOT_TICKS:
            gpu = _AmdGpu.find().device
            lines = ["POST bc250 sensors..",
                     "amdgpu " + ("ok" if gpu else "MISSING"),
                     "steam  " + ("ok" if _steam_roots() else "MISSING"),
                     "ready"]
            return {"cmd": "boot", "text": lines[min(tick, len(lines)) - 1], "cols": [], "progress": None}

        game = _attempt("game detection", _Steam.current_game)
        _attempt("session", lambda: _Session.update(game))
        # polled every refresh even while playing, so their rates and progress stay current
        download = _attempt("downloads", _Downloads.poll)
        shaders = _attempt("shaders", _Shaders.poll)

        if game:
            fps = _attempt("mangohud", _MangoHud.fps)
            cols = [("FPS", f"{fps:.0f}")] if fps is not None else []
            cols.append(("SESSION", _duration(_Session.seconds)))
            return {"cmd": "now-playing", "text": _Session.name or _Steam.app_name(game[0]), "cols": cols,
                    "progress": None}

        if download:
            fraction = download["fraction"]
            if fraction is None:  # verifying, or no byte counts yet
                cols = [("RATE", _rate(download["rate"]))] if download["rate"] > 1000 else []
            else:
                cols = [("DONE", f"{fraction * 100:.0f}%"), ("ETA", _duration(download["eta"]))]
            return {"cmd": download["phase"], "text": download["name"], "cols": cols, "progress": fraction}

        if shaders:
            pct = shaders["percent"]
            return {"cmd": "fossilize_replay", "text": shaders["name"],
                    "cols": [("SHADERS", "--%" if pct is None else f"{pct}%"),
                             ("ETA", "STALL" if shaders["stalled"] else _duration(shaders["eta"]))],
                    "progress": None if pct is None else pct / 100, "accent": "AMBER",
                    "alert_col": shaders["stalled"]}

        last = _Session.last
        if last:
            return {"cmd": "last-session", "text": last["name"],
                    "cols": [("TIME", _duration(last["seconds"])),
                             ("PEAK C/G", _peaks(last["peak_cpu"], last["peak_gpu"]))],
                    "progress": None}
        return {"cmd": "idle", "text": "idle", "cols": [], "progress": None}

    @staticmethod
    def draw(spec: dict, state: dict, cursor: bool):
        from PIL import ImageDraw
        area = spec["AREA"]
        image = _Draw.crop(area)
        d = ImageDraw.Draw(image)
        ox, oy = area["X"], area["Y"]
        small, big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 24)
        bright, mid, dim = (_Draw.color(spec.get(k)) for k in ("BRIGHT", "MID", "DIM"))
        accent = _Draw.color(spec.get(state.get("accent", "MID")), mid)
        label_bl, value_bl = spec["LABEL_BL"] - oy, spec["VALUE_BL"] - oy
        label_c = _Draw.color(spec["LABEL_COLOR"]) if spec.get("LABEL_COLOR") else dim
        cmd, text = state["cmd"], state["text"] or ""
        words = spec.get("CMD_WORDS")
        if words:  # e.g. Game Boy: "IS PLAYING", idle shown as "IS RESTING" / "Zzz"
            if cmd == "idle":
                text = words.get("idle-text", text)
            cmd = words.get(cmd, cmd.upper())
        elif cmd == "idle":
            cmd = "now-playing"

        if state["progress"] is not None and spec.get("PROGRESS_STYLE") == "mosaic":
            # videotex: a row of separated blocks along the top of the band (the rows below are all text)
            right = round(area["WIDTH"] * state["progress"])
            for bx in range(0, right - 4, 6):
                d.rectangle((bx + 1, 1, bx + 5, 4), fill=accent)
        elif state["progress"] is not None:
            # progress bar filling the value row behind the text, on the bright scanlines
            right = round(area["WIDTH"] * state["progress"])
            for py in range(label_bl + 4, area["HEIGHT"] - 2):
                if (oy + py) % 2 == 0:
                    d.line((0, py, right, py), fill=_dim(accent, 0.45))
            d.line((0, area["HEIGHT"] - 2, right, area["HEIGHT"] - 2), fill=accent)

        d.text((spec["CMD_X"] - ox, label_bl), cmd, font=small, fill=label_c, anchor="ls")

        amber = _Draw.color(spec.get("AMBER"))
        col_words = spec.get("COL_WORDS") or {}  # e.g. videotex: DONE -> FAIT
        state = dict(state, cols=[(col_words.get(label, label), value) for label, value in state["cols"]])
        if "COLS_BL" in spec:
            # portrait: values on a row of their own, small label on the left of each half, value on the right
            cols_bl = int(spec["COLS_BL"]) - oy
            for i, ((label, value), (xl, xr)) in enumerate(zip(state["cols"], spec["COLS"])):
                warn = i == len(state["cols"]) - 1 and state.get("alert_col")  # e.g. a stalled shader job
                d.text((xl - ox, cols_bl), label, font=small, fill=label_c, anchor="ls")
                fits = d.textlength(label, font=small) + d.textlength(value, font=big) + 6 <= xr - xl
                d.text((xr - ox, cols_bl), value, font=big if fits else small, fill=amber if warn else bright,
                       anchor="rs")  # a narrow column: the small font rather than over its label
        else:
            # landscape: columns on the value row, laid out from the right edge
            right_edges = [spec["COL2_XR"] - ox, spec["COL1_XR"] - ox]
            for i, ((label, value), xr) in enumerate(zip(reversed(state["cols"]), right_edges)):
                d.text((xr, label_bl), label, font=small, fill=label_c, anchor="rs")
                warn = i == 0 and state.get("alert_col")  # e.g. a stalled shader job
                d.text((xr, value_bl), value, font=big, fill=amber if warn else bright, anchor="rs")

        room = spec["MAX_CHARS"] if len(state["cols"]) > 1 else spec["MAX_CHARS_WIDE"]
        mark = spec.get("CURSOR", "_")
        if len(text) > room and spec.get("SMALL_FALLBACK"):
            # a narrow box: the small font, on two lines if needed, rather than cutting the name
            per_line = room * 2
            words, lines = text.split(), [""]
            for word in words:
                if len(lines[-1]) + len(word) + (1 if lines[-1] else 0) <= per_line:
                    lines[-1] += (" " if lines[-1] else "") + word
                elif len(lines) < 2:
                    lines.append(word[:per_line])
                else:
                    lines[-1] = (lines[-1] + " " + word)[:per_line - 1] + "~"
                    break
            lines = [line[:per_line] for line in lines]
            tops = [value_bl - 11, value_bl] if len(lines) == 2 else [value_bl - 4]
            for i, (line, bl) in enumerate(zip(lines, tops)):
                d.text((spec["TEXT_X"] - ox, bl), line + (mark if cursor and i == len(lines) - 1 else ""),
                       font=small, fill=bright, anchor="ls")
        else:
            if len(text) > room:
                text = text[:room - 1] + "~"
            d.text((spec["TEXT_X"] - ox, value_bl), text + (mark if cursor else ""), font=big, fill=bright,
                   anchor="ls")
        _Draw.show(image, area)

    def as_numeric(self) -> float:
        Bc250Prompt._tick += 1
        spec = _Draw.theme("Bc250Prompt")
        state = _attempt("prompt state", lambda: self._state(Bc250Prompt._tick),
                         {"cmd": "now-playing", "text": "idle", "cols": [], "progress": None})
        if "AREA" in spec:
            _Draw.safely("prompt", self.draw, spec, state, Bc250Prompt._tick % 2 == 0)
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


# ---------------------------------------------------------------------------------------------------------------------
# Screen power: dim when idle, sleep at night
# ---------------------------------------------------------------------------------------------------------------------
def _in_window(now: datetime.time, window: str) -> bool:
    """window like "23:30-08:00" (may wrap over midnight); empty means never."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", window or "")
    if not match:
        return False
    h1, m1, h2, m2 = (int(g) for g in match.groups())
    start, end = datetime.time(h1, m1), datetime.time(h2, m2)
    return start <= now < end if start <= end else now >= start or now < end


class Bc250Screen:
    """Brightness manager, configured by SCREEN in theme.yaml:
    DIM_AFTER (minutes without game or download, 0 = never), DIM_BRIGHTNESS (%), NIGHT ("HH:MM-HH:MM", "" = off),
    NIGHT_MODE ("off" or "dim"). A running game always keeps the screen at full brightness."""
    _mode = "on"
    _last_activity = time.monotonic()

    def as_numeric(self) -> float:
        spec = _Draw.theme("Bc250Screen").get("SCREEN", {})
        now = time.monotonic()
        if _Steam.current_game() or _Downloads.active or _Shaders.active:
            Bc250Screen._last_activity = now

        mode = "on"
        dim_after = float(spec.get("DIM_AFTER", 10) or 0)
        if not _Steam.current_game():
            if _in_window(datetime.datetime.now().time(), spec.get("NIGHT", "")):
                # an unquoted `off` in YAML reads as False
                mode = "dim" if str(spec.get("NIGHT_MODE", "off")).lower() == "dim" else "off"
            elif dim_after and now - self._last_activity > dim_after * 60:
                mode = "dim"
        if mode != Bc250Screen._mode:
            _Draw.safely("screen", self._apply, mode, spec)
            Bc250Screen._mode = mode
        return math.nan

    @staticmethod
    def _apply(mode: str, spec: dict):
        from library import config
        from library.display import display
        if mode == "off":
            display.lcd.ScreenOff()
            return
        if Bc250Screen._mode == "off":
            display.lcd.ScreenOn()
        full = int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))
        display.lcd.SetBrightness(int(spec.get("DIM_BRIGHTNESS", 5)) if mode == "dim" else full)

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


# ---------------------------------------------------------------------------------------------------------------------
# Boot splash: CRT warm-up, BIOS screen, a POST of real values, loading bar, then the dashboard
# ---------------------------------------------------------------------------------------------------------------------
class _Logo3D:
    """BC-250 as an extruded 3D logo, rendered with a real perspective projection into the splash's logo box.

    The logo is a flat text mask placed in 3D and extruded backwards in DEPTH layers; each layer is projected with a
    homography (PIL's PERSPECTIVE transform), drawn far-to-near: dim back face, darker sides, bright front face with a
    sweeping glint, then bloom and scanlines to match the CRT look."""
    DEPTH, LAYERS, CAMERA = 14, 8, 620.0
    POSE = (math.radians(-14), math.radians(12))  # yaw, pitch: turned enough to show the extrusion

    def __init__(self, spec: dict):
        from PIL import Image, ImageDraw
        x, y, w, h = (int(v) for v in spec["LOGO_BOX"])
        self.x, self.y, self.w, self.h = x, y, w, h
        self.bg = _Draw.background(spec.get("IMAGE_NOLOGO", "splash_nologo.png")).crop((x, y, x + w, y + h))
        font = _Draw.font(spec["FONT"], int(spec.get("LOGO_SIZE", 72)))
        text = spec.get("LOGO_TEXT", "BC-250")
        left, top, right, bottom = font.getbbox(text)
        self.mask = Image.new("L", (right - left + 8, bottom - top + 8), 0)
        ImageDraw.Draw(self.mask).text((4 - left, 4 - top), text, font=font, fill=255)
        size = int(spec.get("LOGO_SIZE", 72))
        screen_w = _Draw.background(spec.get("IMAGE", "splash.png")).width
        # where the flat logo sits: centred horizontally, glyph middle half a cap height above the baseline
        self.cx = screen_w / 2 - x
        self.cy = int(spec.get("LOGO_BL", 84)) - size * 8 / 12 / 2 - y
        self.bright = _Draw.color(spec.get("BRIGHT"))
        self.mid = _Draw.color(spec.get("MID"))
        self.dim = _Draw.color(spec.get("DIM"))
        # scanlines in screen space: odd rows darker, as in the background art
        self.scan = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(self.scan)
        for row in range(h):
            if (y + row) % 2:
                draw.line((0, row, w, row), fill=(199, 199, 199))
        self.t0 = time.monotonic()

    def _project(self, px, py, pz, yaw, pitch):
        # object space (centred on the logo), rotated by yaw (Y axis) then pitch (X axis), then perspective
        cy_, sy_ = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        x1, z1 = px * cy_ + pz * sy_, -px * sy_ + pz * cy_
        y2, z2 = py * cp - z1 * sp, py * sp + z1 * cp
        k = self.CAMERA / (self.CAMERA + z2)
        return self.cx + x1 * k, self.cy + y2 * k, z2

    def _layer(self, depth, yaw, pitch):
        """The logo mask projected at a given depth: (L image in box space, distance of its centre)."""
        import numpy
        from PIL import Image
        mw, mh = self.mask.size
        corners = [(0, 0), (mw, 0), (mw, mh), (0, mh)]
        projected = [self._project(u - mw / 2, v - mh / 2, depth, yaw, pitch) for u, v in corners]
        # PIL wants the output -> input mapping: solve the homography from the 4 corner pairs
        rows, rhs = [], []
        for (sx, sy, _), (u, v) in zip(projected, corners):
            rows.append([sx, sy, 1, 0, 0, 0, -u * sx, -u * sy]); rhs.append(u)
            rows.append([0, 0, 0, sx, sy, 1, -v * sx, -v * sy]); rhs.append(v)
        distance = self._project(0, 0, depth, yaw, pitch)[2]
        try:
            coeffs = numpy.linalg.solve(numpy.array(rows, dtype=float), numpy.array(rhs, dtype=float))
        except numpy.linalg.LinAlgError:  # edge-on (90 degrees): nothing visible for this layer
            return Image.new("L", (self.w, self.h), 0), distance
        layer = self.mask.transform((self.w, self.h), Image.PERSPECTIVE, tuple(coeffs), Image.BILINEAR)
        return layer, distance

    def frame(self, yaw: float, pitch: float, glint: float, glow: float = 0.45, glint_strength: int = 150,
              glint_width: int = 26):
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
        canvas = self.bg.copy()
        cache = self.__dict__.setdefault("_layers", {})
        if (yaw, pitch) not in cache:  # the logo holds a pose: project its layers once
            layers = []
            for i in range(self.LAYERS + 1):
                depth = self.DEPTH * i / self.LAYERS
                mask, distance = self._layer(depth, yaw, pitch)
                if i == 0:
                    color = None  # front face, drawn with its own texture below
                elif i == self.LAYERS:
                    color = _dim(self.mid, 0.55)  # back face
                else:
                    color = _dim(self.mid, 0.30 + 0.25 * (1 - i / self.LAYERS))  # extrusion sides, darker deeper
                layers.append((distance, i, mask, color))
            cache.clear()
            cache[(yaw, pitch)] = layers
        layers = cache[(yaw, pitch)]
        front_mask = None
        for distance, i, mask, color in sorted(layers, key=lambda layer: -layer[0]):  # far to near
            if color is None:
                front_mask = mask
                face = Image.new("RGB", (self.w, self.h), self.bright)
                # glint: a slanted band of light sweeping across the front face
                light = Image.new("L", (self.w, self.h), 0)
                gx = glint * (self.w + 120) - 60
                ImageDraw.Draw(light).polygon([(gx, 0), (gx + glint_width, 0), (gx + glint_width - 20, self.h),
                                               (gx - 20, self.h)], fill=glint_strength)
                face = Image.composite(Image.new("RGB", (self.w, self.h), (235, 255, 240)), face,
                                       light.filter(ImageFilter.GaussianBlur(5)))
                canvas.paste(face, (0, 0), mask)
            else:
                canvas.paste(color, (0, 0, self.w, self.h), mask)
        if front_mask is not None:
            glow_level = glow
            glow_image = Image.new("RGB", (self.w, self.h), (0, 0, 0))
            glow_image.paste(self.bright, (0, 0, self.w, self.h), front_mask)
            canvas = ImageChops.add(canvas, glow_image.filter(ImageFilter.GaussianBlur(4))
                                    .point(lambda v: min(255, int(v * glow_level))))
        return ImageChops.multiply(canvas, self.scan)

    def shine(self, lcd):
        """One frame of the idle animation: the logo holds its 3D pose while a band of light sweeps across it every
        1.6 s. Moving the logo itself would resend all of it each frame (a few fps on the screen's link); the sweep
        only changes the band, so it runs smoothly."""
        t = time.monotonic() - self.t0
        k = (t % 1.6) / 0.6 - 0.1
        glint = k if k <= 1.1 else 2.0  # 2.0: off the face
        if glint == 2.0 and getattr(self, "_dark", False):
            return
        self._dark = glint == 2.0
        lcd.DisplayPILImage(self.frame(*self.POSE, glint), self.x, self.y)

    def ignite(self, lcd, flare_level=None):
        """Finale: a strong, wide sweep of light across the letters, then a backlight flare (when flare_level is
        given): both cheap on the link, so the finale is as smooth on the screen as in the preview."""
        _Splash._animate(0.5, lambda t: lcd.DisplayPILImage(
            self.frame(*self.POSE, -0.1 + 1.2 * t, glint_strength=235, glint_width=46), self.x, self.y))
        if flare_level:
            lcd.SetBrightness(min(100, round(flare_level * 1.35)))
            _Splash._wait(0.12)
            lcd.SetBrightness(round(flare_level * 1.1))
            _Splash._wait(0.08)
            lcd.SetBrightness(flare_level)


class _Screen:
    """What the splash draws through: keeps a copy of what is on the screen and sends only the rectangles that really
    changed. The screen gets every pixel over a slow serial link (a full frame takes the better part of a second),
    so a frame's cost is its changed area: a glint moving over a still logo costs a band, not the whole logo.

    The first full-screen image is timed to log the link speed (journalctl --user -u turing-monitor)."""
    COMMAND_PX = 150  # one more command costs about as much link time as this many pixels (rev A: ~1.5 ms, 160 KB/s)
    MAX_RECTS = 48  # above this, the neighbours whose union wastes least are joined
    TILE = 16  # rows: tall changes are cut in tiles, so a vertical line doesn't drag a whole box along

    def __init__(self, lcd, width: int, height: int):
        self.lcd, self.width, self.height = lcd, width, height
        self.shadow = None  # what is on the screen (numpy HxWx3) once a full frame has been sent
        import threading
        self._lock = threading.Lock()  # the radar's thread and the widgets' thread can share one
        self.sent = 0  # bytes

    def SetBrightness(self, level: int):
        self.lcd.SetBrightness(level)

    @classmethod
    def _rects(cls, changed, tile=None):
        """Rectangles (x1, y1, x2, y2) covering the True cells of a 2D mask: bands of changed rows, cut in tiles of
        TILE rows, each split where a wide run of columns is unchanged; runs lined up vertically are joined again."""
        import numpy
        rows = numpy.flatnonzero(changed.any(axis=1))
        if rows.size == 0:
            return []

        def runs(index, gap):
            """Runs of consecutive indexes, joined across holes of up to `gap` (worth sending to save a command)."""
            breaks = numpy.flatnonzero(numpy.diff(index) > gap + 1)
            return list(zip(numpy.r_[index[0], index[breaks + 1]], numpy.r_[index[breaks], index[-1]] + 1))

        bands = runs(rows, cls.COMMAND_PX // changed.shape[1])
        rects, open_rects = [], {}  # open_rects: (x1, x2) -> rect ending on the row where the next tile starts
        for y1, y2 in bands:
            for t1 in range(y1, y2, tile or cls.TILE):
                t2 = min(y2, t1 + (tile or cls.TILE))
                cols = numpy.flatnonzero(changed[t1:t2].any(axis=0))
                if cols.size == 0:
                    continue
                for x1, x2 in runs(cols, cls.COMMAND_PX // (t2 - t1)):
                    above = open_rects.get((x1, x2))
                    if above is not None and above[3] == t1:
                        above[3] = t2
                    else:
                        above = [x1, t1, x2, t2]
                        rects.append(above)
                    open_rects[(x1, x2)] = above
        rects.sort(key=lambda r: (r[1], r[0]))
        # stack rectangles that touch vertically when the pixels the union adds cost less than the command it saves
        # (a steep line otherwise becomes one small rectangle per tile)
        area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
        stacked = []
        for r in rects:
            for m in reversed(stacked[-16:]):
                if m[3] == r[1] and m[0] <= r[2] and r[0] <= m[2]:
                    union = [min(m[0], r[0]), m[1], max(m[2], r[2]), r[3]]
                    if area(union) - area(m) - area(r) < cls.COMMAND_PX:
                        m[:] = union
                        break
            else:
                stacked.append(r)
        rects = sorted(stacked, key=lambda r: (r[1], r[0]))
        if len(rects) > 4 * cls.MAX_RECTS:  # too scattered to sort out cheaply: whole bands
            rects = []
            for y1, y2 in bands:
                cols = numpy.flatnonzero(changed[y1:y2].any(axis=0))
                rects.append((cols[0], y1, cols[-1] + 1, y2))
        rects = [list(r) for r in rects]
        area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
        while len(rects) > cls.MAX_RECTS:  # each command costs too: join the neighbours whose union wastes least
            unions = [[min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                      for a, b in zip(rects, rects[1:])]
            waste = [area(u) - area(a) - area(b) for u, a, b in zip(unions, rects, rects[1:])]
            i = waste.index(min(waste))
            rects[i:i + 2] = [unions[i]]
        return rects

    def _send(self, image, x, y):
        self.lcd.DisplayPILImage(image, x, y)
        self.sent += image.width * image.height * 2

    def DisplayPILImage(self, image, x: int = 0, y: int = 0, *args, full: bool = False, **kwargs):
        with self._lock:
            self._display(image, x, y, full)

    def _display(self, image, x, y, full=False):
        import numpy
        image = image.convert("RGB")
        w, h = min(image.width, self.width - x), min(image.height, self.height - y)
        if w <= 0 or h <= 0:
            return
        if (w, h) != image.size:
            image = image.crop((0, 0, w, h))
        new = numpy.asarray(image)
        if self.shadow is None:
            if (x, y, w, h) != (0, 0, self.width, self.height):
                self._send(image, x, y)  # what is around it is unknown: nothing to compare with yet
                return
            start = time.monotonic()
            self._send(image, 0, 0)
            _Splash._wait(0)
            seconds = time.monotonic() - start
            logger.info("BC250: screen link %.0f KB/s (full frame in %.2f s)", w * h * 2 / 1000 / max(seconds, 1e-3),
                        seconds)
            self.shadow = new.copy()
            return
        old = self.shadow[y:y + h, x:x + w]
        if full:
            self._send(image, x, y)
        else:
            for x1, y1, x2, y2 in self._rects((new != old).any(axis=2), self.TILE):
                self._send(image.crop((x1, y1, x2, y2)), x + x1, y + y1)
        old[...] = new


class _Splash:
    STEP = 0.24  # seconds per POST line
    FRAME = 1 / 30  # shortest time between two animation frames
    _tick_cost = 0.0  # recent duration of a background animation frame, link included

    @staticmethod
    def fit(value: str, chars: int) -> str:
        """Shorten a POST value for narrow screens: drop "(...)" details first, then cut at a word boundary."""
        if len(value) <= chars:
            return value
        value = re.sub(r"\s*\([^)]*\)", "", value)
        if len(value) <= chars:
            return value
        return value[:chars - 1].rsplit(" ", 1)[0] + "~"

    @staticmethod
    def post_lines(spec: dict) -> List[tuple]:
        """(label, value, status) from the live system; status is OK / WARN / WAIT / HOT!"""
        import psutil
        lines = []

        def add(label, fn):
            lines.append((label,) + _attempt("splash " + label, fn, ("unavailable", "WARN")))

        def cpu():
            freq = psutil.cpu_freq()
            top = f" @ {freq.max / 1000:.2f} GHz" if freq and freq.max else ""
            return (f"AMD BC-250 {psutil.cpu_count(False) or '?'}C/{psutil.cpu_count() or '?'}T{top}", "OK")

        def memory():
            return (f"{psutil.virtual_memory().total / 1024 ** 3:.1f} GiB system, GDDR6 shared", "OK")

        def gpu():
            if not _AmdGpu.find().device:
                return ("amdgpu not found", "WARN")
            levels = [int(m) for m in re.findall(r"(\d+)\s*Mhz", _read(_AmdGpu.path("pp_dpm_sclk") or "") or "",
                                                 re.IGNORECASE)]
            top = f" up to {max(levels)} MHz" if levels else ""
            return (f"RDNA2 24CU {os.path.basename(os.path.dirname(_AmdGpu.device))}{top}", "OK")

        def temps():
            cpu_t, gpu_t = Bc250CpuTemp().read(), Bc250GpuTemp().read()
            if cpu_t is None and gpu_t is None:
                return ("no sensor", "WARN")
            fmt = lambda t: "--" if t is None else f"{t:.0f}°C"
            hot = max(t for t in (cpu_t, gpu_t) if t is not None) >= float(spec.get("ALERT", 80))
            return (f"CPU {fmt(cpu_t)}  GPU {fmt(gpu_t)}", "HOT!" if hot else "OK")

        def storage():
            usage = _GameDisk.usage()
            if usage is None:
                return ("Steam library not found", "WARN")
            free = usage.free / 1000 ** 3
            return (f"Steam library {free:.0f} GB free ({usage.percent:.0f}% used)", "OK" if free > 50 else "WARN")

        def network():
            import socket
            stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
            for nic, st in stats.items():
                if st.isup and nic != "lo" and not nic.startswith(("docker", "veth", "br-", "virbr")):
                    ipv4 = next((a.address for a in addrs.get(nic, []) if a.family == socket.AF_INET), None)
                    if ipv4:
                        return (f"{nic} {ipv4}", "OK")
            return ("offline", "WAIT")

        def steam():
            if _Steam.client_running():
                return ("client running", "OK")
            return ("client not started yet", "WAIT") if _steam_roots() else ("not installed", "WARN")

        for label, fn in (("CPU", cpu), ("MEMORY", memory), ("GPU", gpu), ("TEMPS", temps),
                          ("STORAGE", storage), ("NETWORK", network), ("STEAM", steam)):
            add(label, fn)
        return lines[:int(spec.get("ROWS", 7))]

    @staticmethod
    def _wait(seconds: float):
        """Let the app's send queue drain before pacing, so the animation runs at screen speed."""
        from library import config
        queue = getattr(config, "update_queue", None)
        deadline = time.monotonic() + 3
        while queue is not None and not queue.empty() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(seconds)

    @classmethod
    def _run(cls, seconds: float, tick=None):
        """Wait `seconds`, calling tick() (one animation frame) as often as the screen link allows meanwhile."""
        if tick is None:
            cls._wait(seconds)
            return
        end = time.monotonic() + seconds
        while True:
            start = time.monotonic()
            if start + cls._tick_cost > end:  # no time left for another frame: don't overrun, just wait
                cls._tick_cost *= 0.6  # (and trust the estimate less: one slow frame must not stop the animation)
                time.sleep(max(0.0, end - start))
                break
            _attempt("splash animation", tick)
            cls._wait(0)  # drains the send queue first, so frames go at screen speed
            now = time.monotonic()
            cls._tick_cost = 0.5 * cls._tick_cost + 0.5 * (now - start)
            time.sleep(max(0.0, min(end - now, cls.FRAME - (now - start))))

    @classmethod
    def _animate(cls, seconds: float, draw, tick=None):
        """draw(p) with p going from 0 to exactly 1 over `seconds`: on a slow link frames are skipped, the animation
        never gets longer. tick() (a background animation) runs once per frame too."""
        start = time.monotonic()
        while True:
            frame_start = time.monotonic()
            p = min(1.0, (frame_start - start) / seconds)
            _attempt("splash animation", lambda: draw(p))
            if tick:
                _attempt("splash animation", tick)
            cls._wait(0)
            if p >= 1.0:
                return
            time.sleep(max(0.0, cls.FRAME - (time.monotonic() - frame_start)))

    @staticmethod
    def _snow(size, bright, bg, gain=1.0):
        """No-signal raster: phosphor noise on lit scanlines, as a CRT shows before it locks onto a picture."""
        from PIL import Image, ImageChops, ImageDraw
        w, h = size
        noise = Image.effect_noise((w, h), 64).point(lambda v: min(255, int(max(0, v - 120) * 2 * gain)))
        lines = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(lines)
        for y in range(0, h, 2):
            d.line((0, y, w, y), fill=int(26 * gain))
        mask = ImageChops.add(noise, lines)
        return Image.composite(Image.new("RGB", (w, h), bright), Image.new("RGB", (w, h), bg), mask)

    @staticmethod
    def _unfocused(base, bg):
        """The picture as it first locks: out of focus and over-bright (high voltage still low). The dark background
        is left exactly as it is, so the focus snap only has to send the text and lines again, not the whole screen."""
        from PIL import Image, ImageChops, ImageEnhance, ImageFilter
        soft = ImageEnhance.Brightness(base.filter(ImageFilter.GaussianBlur(2.4))).enhance(1.35)
        soft = ImageChops.add(soft, base.filter(ImageFilter.GaussianBlur(7)).point(lambda v: v // 2))
        visible = ImageChops.difference(soft, base).convert("L").point(lambda v: 255 if v > 10 else 0)
        return Image.composite(soft, base, visible)

    @classmethod
    def warm_up(cls, lcd, base, bright, bg, blank=None):
        from library import config
        from PIL import Image, ImageDraw
        import random
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))

        def level(fraction):
            lcd.SetBrightness(max(0, min(100, round(target * fraction))))

        def ramp(start, stop, seconds, steps=8, tick=None):
            # filament warm-up: fast at first, then easing into the target
            for i in range(1, steps + 1):
                t = i / steps
                level(start + (stop - start) * (1 - math.exp(-3 * t)) / (1 - math.exp(-3)))
                cls._run(seconds / steps, tick)

        w, h = base.size
        blank = blank or Image.new("RGB", (w, h), bg)
        snow_start = time.monotonic()
        streaks = []

        def boil():
            # no signal yet: streaks of snow flicker on the dark raster and a bright roll line sweeps down. Each frame
            # clears the previous streaks and draws new ones (full-screen snow would take seconds to clear again)
            for x, y, sw, sh in streaks:
                lcd.DisplayPILImage(blank.crop((x, y, x + sw, y + sh)), x, y)
            streaks.clear()
            for _ in range(3):
                sw, sh = random.randrange(80, 260), random.randrange(3, 9)
                x, y = random.randrange(0, w - sw), random.randrange(0, h - sh)
                lcd.DisplayPILImage(cls._snow((sw, sh), bright, bg, gain=1.4), x, y)
                streaks.append((x, y, sw, sh))
            roll = int(((time.monotonic() - snow_start) * 300) % h)
            line = blank.crop((0, roll, w, min(h, roll + 2)))
            ImageDraw.Draw(line).line((0, 0, w, 0), fill=tuple(c // 2 for c in bright))
            lcd.DisplayPILImage(line, 0, roll)
            streaks.append((0, roll, w, line.height))

        # dark tube (the one full frame, sent with the backlight off), then the streaks while it warms up
        level(0)
        lcd.DisplayPILImage(blank, 0, 0)
        cls._run(0.15, boil)
        # high-voltage kick: a short flash, then dim again
        level(0.55)
        cls._run(0.08, boil)
        level(0.08)
        ramp(0.08, 0.3, 0.45, steps=4, tick=boil)
        for x, y, sw, sh in streaks:
            lcd.DisplayPILImage(blank.crop((x, y, x + sw, y + sh)), x, y)

        # sync lock: the picture locks in from top to bottom behind a bright retrace line, unfocused and small, then
        # rows tear sideways while H-sync settles
        soft = cls._unfocused(base, bg)
        locked = {"rows": 0}

        def lock(p):
            level(0.3 + 0.25 * p)
            rows = round(h * p)
            if rows > locked["rows"]:
                strip = soft.crop((0, locked["rows"], w, min(h, rows + 2)))
                if rows < h:
                    ImageDraw.Draw(strip).line((0, rows - locked["rows"], w, rows - locked["rows"]), fill=bright)
                lcd.DisplayPILImage(strip, 0, locked["rows"])
                locked["rows"] = rows

        cls._animate(0.45, lock)
        rows_with_content = [r for r in range(8, h - 12, 2) if soft.crop((0, r, w, r + 2)).getextrema()[1][1] > 40]
        for burst in range(1):
            torn = []
            for _ in range(3):
                y = random.choice(rows_with_content) if rows_with_content else random.randrange(20, h - 30)
                band = random.randrange(5, 12)
                original = soft.crop((0, y, w, y + band))
                shifted = Image.new("RGB", original.size, bg)
                shifted.paste(original, (random.choice((-1, 1)) * random.randrange(8, 22), 0))
                ImageDraw.Draw(shifted).line((0, 0, w, 0), fill=tuple(c // 2 for c in bright))  # retrace line
                lcd.DisplayPILImage(shifted, 0, y)
                torn.append((y, original))
            cls._wait(0.09)
            for y, original in torn:
                lcd.DisplayPILImage(original, 0, y)
            cls._wait(0.05)
        ramp(0.55, 0.8, 0.25, steps=3)

        # focus snap: sharp and full size, brightness overshoots then settles
        lcd.DisplayPILImage(base, 0, 0)
        level(1.18)
        cls._wait(0.12)
        level(0.95)
        cls._wait(0.08)
        level(1.0)
        cls._wait(0.25)

    @classmethod
    def play(cls, lcd):
        from library import config
        from PIL import Image, ImageDraw
        spec = config.THEME_DATA.get("bc250_splash") or {}
        if not spec.get("ENABLED") or any(a.startswith(("-t", "--theme-screenshots")) for a in sys.argv[1:]):
            return None
        size = _Draw.background(spec.get("IMAGE", "splash.png")).size
        lcd = _Screen(lcd, *size)
        started = time.monotonic()
        try:
            cls._play(lcd, spec)
        finally:
            logger.info("BC250: boot splash %.1f s, %.0f KB sent", time.monotonic() - started, lcd.sent / 1000)
        return lcd  # what the screen shows now: the dashboard can start from it

    @classmethod
    def _play(cls, lcd, spec: dict):
        from library import config
        from PIL import Image, ImageDraw
        if spec.get("STYLE") == "gameboy":
            _GameBoySplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "retrowave":
            _RetrowaveSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "videotex":
            _VideotexSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "mission":
            _MissionSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "minecraft":
            _MinecraftSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "halloween":
            _HalloweenSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "christmas":
            _ChristmasSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "horror":
            _HorrorSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "seismograph":
            _SeismographSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "nixie":
            _NixieSplash.play(lcd, spec)
            return
        if spec.get("STYLE") == "radar":
            _RadarSplash.play(lcd, spec)
            return
        base = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = base.size
        bright, mid, dim, amber, alert, bg = (_Draw.color(spec.get(k)) for k in
                                              ("BRIGHT", "MID", "DIM", "AMBER", "ALERT_COLOR", "BG"))
        small = _Draw.font(spec["FONT"], 12)
        status_color = {"OK": bright, "WARN": amber, "WAIT": _dim(amber, 0.7), "HOT!": alert}

        # 1. CRT warm-up. Fades use the backlight (one tiny command each), so only three full frames are sent
        blank = _attempt("splash blank", lambda: _Draw.background(spec["IMAGE_BLANK"])) if "IMAGE_BLANK" in spec else None
        cls.warm_up(lcd, base, bright, bg, blank)

        # 2. POST: each line typed with "..." then its status
        def row(index, label, value, status=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (6, baseline - 11, w - 6, baseline + 4)
            strip = base.crop(box)
            d = ImageDraw.Draw(strip)
            ox, oy = box[0], box[1]
            d.text((int(spec["LABEL_X"]) - ox, baseline - oy), label, font=small, fill=mid, anchor="ls")
            d.text((int(spec["VALUE_X"]) - ox, baseline - oy), cls.fit(value, int(spec.get("VALUE_CHARS", 52))),
                   font=small, fill=bright, anchor="ls")
            tag = "[ .. ]" if status is None else f"[{status:^4}]"
            d.text((int(spec["STATUS_XR"]) - ox, baseline - oy), tag, font=small,
                   fill=dim if status is None else status_color.get(status, bright), anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        logo = _attempt("3D logo", lambda: _Logo3D(spec)) if "LOGO_BOX" in spec else None
        sway = (lambda: logo.shine(lcd)) if logo else None

        lines = cls.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            cls._run(cls.STEP * 0.55, sway)
            row(i, label, value, status)
            cls._run(cls.STEP * 0.45, sway)

        # 3. loading bar, then the verdict
        x, y, bw, bh = (int(spec[k]) for k in ("BAR_X", "BAR_Y", "BAR_W", "BAR_H"))
        for step in range(1, 9):
            bar = base.crop((x, y, x + bw, y + bh))
            ImageDraw.Draw(bar).rectangle((0, 0, round(bw * step / 8) - 1, bh - 1), fill=mid)
            lcd.DisplayPILImage(bar, x, y)
            cls._run(0.12, sway)
        warnings = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        verdict = "BOOT OK" if not warnings else f"BOOT OK, {warnings} warning{'s' * (warnings > 1)}"
        status_bl = int(spec.get("STATUS_BL", 284))
        box = (6, status_bl - 11, w - 6, status_bl + 4)
        strip = base.crop(box)
        ImageDraw.Draw(strip).text((int(spec["LABEL_X"]) - box[0], status_bl - box[1]),
                                   verdict + " - starting dashboard_", font=small,
                                   fill=amber if warnings else bright, anchor="ls")
        lcd.DisplayPILImage(strip, box[0], box[1])
        if logo:
            target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
            _attempt("3D logo finale", lambda: logo.ignite(lcd, target))
        cls._wait(0.9 if warnings else 0.5)


class _GameBoySplash:
    """Game Boy boot: the logo drops down to the centre on a blank screen, flashes, then a SYSTEM CHECK menu where a
    cursor walks down the same live POST values, an HP-style loading bar fills, and BOOT OK! waits with a blinking
    arrow. Four shades only (from the theme), no backlight tricks: the original had none."""

    @classmethod
    def play(cls, lcd, spec: dict):
        from PIL import ImageDraw
        blank = _Draw.background(spec.get("IMAGE_BLANK", "splash_blank.png"))
        nologo = _Draw.background(spec.get("IMAGE_NOLOGO", "splash_nologo.png"))
        base = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = base.size
        dark, mid, light = (_Draw.color(spec.get(k)) for k in ("BRIGHT", "MID", "LIGHT"))
        small = _Draw.font(spec["FONT"], 12)

        # 1. blank screen, then the logo drops from above to its place, one band of screen per step
        lcd.DisplayPILImage(blank, 0, 0)  # the one full frame (~2 s on a rev A)
        _Splash._wait(0.1)
        lx, ly, lw, lh = (int(v) for v in spec["LOGO_BOX"])
        logo = base.crop((lx, ly, lx + lw, ly + lh))
        drop = {"top": -lh}

        def fall(p):
            top = round(-lh + (ly + lh) * p)  # from fully above the screen to its final place
            band_top, band_bottom = max(0, drop["top"]), min(h, top + lh)
            if band_bottom > band_top:
                band = blank.crop((lx, band_top, lx + lw, band_bottom))
                band.paste(logo, (0, top - band_top))
                lcd.DisplayPILImage(band, lx, band_top)
            drop["top"] = top

        _Splash._animate(0.9, fall)

        # 2. the "chime": the logo flashes lighter twice
        faded = logo.point(lambda v: v)
        faded_px, base_px = faded.load(), logo.load()
        for y in range(lh):
            for x in range(lw):
                if base_px[x, y] == dark:
                    faded_px[x, y] = mid
        for image in (faded, logo, faded, logo):
            lcd.DisplayPILImage(image, lx, ly)
            _Splash._wait(0.09)
        _Splash._wait(0.3)

        # 3. SYSTEM CHECK menu: a cursor walks down the live values
        lcd.DisplayPILImage(base, 0, 0)
        _Splash._wait(0.3)
        status_text = {"OK": "OK", "WARN": "!!", "WAIT": "..", "HOT!": "HOT!"}

        def row(index, label, value, status=None, cursor=False):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (int(spec["LABEL_X"]) - 14, baseline - 11, int(spec["STATUS_XR"]) + 2, baseline + 4)
            strip = nologo.crop(box)
            d = ImageDraw.Draw(strip)
            ox, oy = box[0], box[1]
            if cursor:
                d.text((int(spec["LABEL_X"]) - 12 - ox, baseline - oy), "▶", font=small, fill=dark, anchor="ls")
            d.text((int(spec["LABEL_X"]) - ox, baseline - oy), label, font=small, fill=dark, anchor="ls")
            d.text((int(spec["VALUE_X"]) - ox, baseline - oy), _Splash.fit(value, int(spec.get("VALUE_CHARS", 40))),
                   font=small, fill=mid, anchor="ls")
            if status:
                d.text((int(spec["STATUS_XR"]) - ox, baseline - oy), status_text.get(status, status), font=small,
                       fill=dark, anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            if i:
                row(i - 1, *lines[i - 1], cursor=False)  # the cursor leaves the previous line
            row(i, label, value, cursor=True)
            _Splash._wait(_Splash.STEP * 0.55)
            row(i, label, value, status, cursor=True)
            _Splash._wait(_Splash.STEP * 0.45)

        # 4. HP-style loading bar, then BOOT OK! with the blinking dialog arrow
        x, y, bw, bh = (int(spec[k]) for k in ("BAR_X", "BAR_Y", "BAR_W", "BAR_H"))
        for step in range(1, 11):
            bar = nologo.crop((x, y, x + bw, y + bh))
            ImageDraw.Draw(bar).rectangle((0, 0, round(bw * step / 10) - 1, bh - 1), fill=mid)
            lcd.DisplayPILImage(bar, x, y)
            _Splash._wait(0.05)
        warnings = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        verdict = "BOOT OK!" if not warnings else f"BOOT OK! {warnings} WARNING{'S' * (warnings > 1)}"
        status_bl = int(spec.get("STATUS_BL", 290))
        box = (int(spec["LABEL_X"]) - 14, status_bl - 11, int(spec["STATUS_XR"]) + 2, status_bl + 4)
        for blink in range(4):
            strip = nologo.crop(box)
            d = ImageDraw.Draw(strip)
            d.text((int(spec["LABEL_X"]) - box[0], status_bl - box[1]), verdict, font=small, fill=dark, anchor="ls")
            if blink % 2 == 0:
                d.text((box[2] - box[0] - 4, status_bl - box[1]), "▼", font=small, fill=dark, anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])
            _Splash._wait(0.22)


class _RetrowaveSplash:
    """Retrowave boot: the backlight fades up on a sunset while a neon grid rushes towards the viewer (it keeps
    moving for the whole boot), a laser line scans the chrome logo in, a glint sweeps it, then a SYSTEM CHECK panel
    opens on the floor for the same live POST values, a pink-to-cyan loading bar and a blinking PRESS START.

    The grid is the only full-width motion, so each frame sends just the rows of floor that changed, and once the
    panel is open only the floor around it: cheap enough for the screen's serial link."""
    SPEED = 1.3  # grid lines per second
    PHASES = 24  # precomputed grid positions per line spacing

    @classmethod
    def _grid(cls, w, fh, spacing):
        """One L mask of the floor per phase: lines converging on the vanishing point, fading into the distance."""
        from PIL import Image, ImageChops, ImageDraw
        verticals = Image.new("L", (w, fh), 0)
        d = ImageDraw.Draw(verticals)
        for i in range(-16, 17):
            d.line((w / 2, 0, w / 2 + i * spacing, fh - 1), fill=255)
        fade = Image.linear_gradient("L").resize((w, fh)).point(lambda v: int(40 + 215 * (v / 255) ** 0.8))
        verticals = ImageChops.multiply(verticals, fade)
        masks = []
        for phase in range(cls.PHASES):
            mask = verticals.copy()
            d = ImageDraw.Draw(mask)
            z = 1.0 - phase / cls.PHASES
            while True:
                y = fh * 0.9 / z
                if y < fh * 0.2:  # further away the lines are too close to be seen moving: each one would cost rows
                    break
                if y < fh:
                    d.line((0, round(y), w, round(y)), fill=int(255 * (0.2 + 0.8 * y / fh)), width=2 if y > fh * 0.6 else 1)
                z += 1.0
            masks.append(mask)
        return masks

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
        blank = _Draw.background(spec.get("IMAGE_BLANK", "splash_blank.png"))
        panel = _Draw.background(spec.get("IMAGE_NOLOGO", "splash_nologo.png"))
        full = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = full.size
        bright, mid, dim, amber, alert = (_Draw.color(spec.get(k)) for k in
                                          ("BRIGHT", "MID", "DIM", "AMBER", "ALERT_COLOR"))
        small = _Draw.font(spec["FONT"], 12)
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        horizon = int(spec["HORIZON"])
        px1, py1, px2, py2 = (int(v) for v in spec["PANEL"])
        grid = cls._grid(w, h - horizon, int(spec.get("GRID_SPACING", w // 8)))
        line_color = Image.new("RGB", (w, h - horizon), _Draw.color(spec.get("GRID_COLOR"), mid))
        state = {"open": False, "floor": None, "phase": None, "glint_from": None, "glint_shown": False}
        t0 = time.monotonic()

        def floor(phase):
            source = (panel if state["open"] else blank).crop((0, horizon, w, h))
            return Image.composite(line_color, source, grid[phase])

        def grid_tick():
            phase = int((time.monotonic() - t0) * cls.SPEED * cls.PHASES) % cls.PHASES
            if phase == state["phase"]:
                return
            new = floor(phase)
            boxes = [(0, 0, w, h - horizon)]  # floor coordinates; around the panel once it is open
            if state["open"]:
                top, bottom = py1 - horizon, py2 + 1 - horizon
                boxes = [(0, 0, w, top), (0, top, px1, h - horizon), (px2 + 1, top, w, h - horizon),
                         (px1, bottom, px2 + 1, h - horizon)]
            for box in boxes:  # only the moving lines go out: _Screen sends what changed
                if box[2] > box[0] and box[3] > box[1]:
                    lcd.DisplayPILImage(new.crop(box), box[0], horizon + box[1])
            state["floor"], state["phase"] = new, phase

        # the chrome letters, for the glint: same font, size and anchor as make_theme.py drew them
        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LOGO_BOX"])
        face = Image.new("L", (w, h), 0)
        ImageDraw.Draw(face).text(tuple(int(v) for v in spec["LOGO_CENTER"]), spec.get("LOGO_TEXT", "BC-250"),
                                  font=_Draw.font(spec["LOGO_FONT"], int(spec["LOGO_SIZE"])), fill=255, anchor="mm")
        face = face.crop((lx1, ly1, lx2, ly2))
        logo = full.crop((lx1, ly1, lx2, ly2))
        white = Image.new("RGB", logo.size, (255, 255, 255))

        def glint(position, strength=170, width=30):
            band = Image.new("L", logo.size, 0)
            x = position * (logo.width + 80) - 40
            ImageDraw.Draw(band).polygon([(x, 0), (x + width, 0), (x + width - 24, logo.height),
                                          (x - 24, logo.height)], fill=strength)
            band = ImageChops.multiply(band.filter(ImageFilter.GaussianBlur(4)), face)
            lcd.DisplayPILImage(Image.composite(white, logo, band), lx1, ly1)

        def glint_tick():
            # a sweep every 2.4 s once the logo is in, then one clean frame
            if state["glint_from"] is None:
                return
            k = ((time.monotonic() - state["glint_from"]) % 2.4) / 0.8
            if k <= 1.1:
                glint(k)
                state["glint_shown"] = True
            elif state["glint_shown"]:
                lcd.DisplayPILImage(logo, lx1, ly1)
                state["glint_shown"] = False

        def tick():
            grid_tick()
            glint_tick()

        def level(fraction):
            lcd.SetBrightness(max(0, min(100, round(target * fraction))))

        # 1. dark screen, then the backlight fades up on the sunset while the grid starts rolling
        level(0)
        frame = blank.copy()
        state["phase"] = 0
        state["floor"] = floor(0)
        frame.paste(state["floor"], (0, horizon))
        lcd.DisplayPILImage(frame, 0, 0)
        for i in range(1, 7):
            level((1 - math.exp(-3 * i / 6)) / (1 - math.exp(-3)))
            _Splash._run(0.075, tick)

        # 2. a laser line scans the logo and subtitle in, top to bottom
        rx1, ry1, rx2, ry2 = (int(v) for v in spec["REVEAL_BOX"])
        before, after = blank.crop((rx1, ry1, rx2, ry2)), full.crop((rx1, ry1, rx2, ry2))

        def scan(p):
            line = round((ry2 - ry1) * p)
            strip = before.copy()
            strip.paste(after.crop((0, 0, rx2 - rx1, line)), (0, 0))
            if p < 1.0:
                d = ImageDraw.Draw(strip)
                d.line((0, line, rx2 - rx1, line), fill=(235, 255, 255))
                d.line((0, line + 1, rx2 - rx1, line + 1), fill=bright)
            lcd.DisplayPILImage(strip, rx1, ry1)  # only the rows the line went over change

        _Splash._animate(0.5, scan, grid_tick)

        # 3. a strong glint with a backlight pulse, then the periodic glints start
        pulsed = {"up": False}

        def sweep(t):
            if t > 0.4 and not pulsed["up"]:
                level(1.3)
                pulsed["up"] = True
            glint(-0.1 + 1.2 * t, strength=240, width=48)

        _Splash._animate(0.5, sweep, grid_tick)
        level(1.0)
        lcd.DisplayPILImage(logo, lx1, ly1)
        state["glint_from"] = time.monotonic() + 1.0

        # 4. the SYSTEM CHECK panel opens from its centre
        pw = px2 - px1 + 1

        def open_panel(p):
            region = state["floor"].crop((px1, py1 - horizon, px2 + 1, py2 + 1 - horizon))
            half = max(1, round(pw * p / 2))
            region.paste(panel.crop((px1 + pw // 2 - half, py1, px1 + pw // 2 + half, py2 + 1)), (pw // 2 - half, 0))
            lcd.DisplayPILImage(region, px1, py1)

        _Splash._animate(0.35, open_panel, glint_tick)
        state["open"] = True
        lcd.DisplayPILImage(panel.crop((px1, py1, px2 + 1, py2 + 1)), px1, py1)
        state["phase"] = None  # resend the floor around the panel (its glow changed it)

        status_color = {"OK": bright, "WARN": amber, "WAIT": _dim(amber, 0.7), "HOT!": alert}
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))

        def strip_at(baseline):
            box = (label_x - 4, baseline - 11, status_xr + 4, baseline + 4)
            return box, panel.crop(box)

        # 5. POST: each line typed with [ .. ] then its status
        def row(index, label, value, status=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box, strip = strip_at(baseline)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((label_x - box[0], oy), label, font=small, fill=mid, anchor="ls")
            d.text((value_x - box[0], oy), _Splash.fit(value, int(spec.get("VALUE_CHARS", 40))), font=small,
                   fill=bright, anchor="ls")
            tag = "[ .. ]" if status is None else f"[{status:^4}]"
            d.text((status_xr - box[0], oy), tag, font=small,
                   fill=dim if status is None else status_color.get(status, bright), anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._run(_Splash.STEP * 0.55, tick)
            row(i, label, value, status)
            _Splash._run(_Splash.STEP * 0.45, tick)

        # 6. loading bar, pink to cyan along its length
        x, y, bw, bh = (int(spec[k]) for k in ("BAR_X", "BAR_Y", "BAR_W", "BAR_H"))
        for step in range(1, 11):
            bar = panel.crop((x, y, x + bw, y + bh))
            d = ImageDraw.Draw(bar)
            for px in range(round(bw * step / 10)):
                d.line((px, 0, px, bh - 1), fill=_lerp(mid, bright, px / max(1, bw - 1)))
            lcd.DisplayPILImage(bar, x, y)
            _Splash._run(0.07, tick)

        # 7. the verdict, and PRESS START blinking (on its own row when there is one, else at the end of the verdict's)
        warnings = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        verdict = "BOOT OK" if not warnings else f"BOOT OK, {warnings} warning{'s' * (warnings > 1)}"
        status_bl, footer_bl = int(spec.get("STATUS_BL", 296)), int(spec.get("FOOTER_BL") or 0)
        box, strip = strip_at(status_bl)
        ImageDraw.Draw(strip).text((label_x - box[0], status_bl - box[1]), verdict, font=small,
                                   fill=amber if warnings else bright, anchor="ls")
        lcd.DisplayPILImage(strip, box[0], box[1])
        press_bl = footer_bl or status_bl
        for blink in range(4):
            box, strip = strip_at(press_bl)
            d = ImageDraw.Draw(strip)
            if not footer_bl:
                d.text((label_x - box[0], status_bl - box[1]), verdict, font=small,
                       fill=amber if warnings else bright, anchor="ls")
            if blink % 2 == 0:
                if footer_bl:
                    d.text(((px1 + px2) // 2 - box[0], press_bl - box[1]), "PRESS START", font=small, fill=amber,
                           anchor="ms")
                else:
                    d.text((status_xr - box[0], press_bl - box[1]), "PRESS START", font=small, fill=amber,
                           anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])
            _Splash._run(0.2, tick)

        # 8. last glint and a backlight flash into the dashboard
        state["glint_from"] = None
        _Splash._animate(0.4, lambda t: glint(-0.1 + 1.2 * t, strength=240, width=48), grid_tick)
        level(1.3)
        _Splash._wait(0.12)
        level(1.0)


class _VideotexSplash:
    """Videotex boot: an F in the status corner, the service code typed in, "Connexion..." and the modem handshake
    as text, the corner turns to C, then the 3615 page is drawn row by row the way a videotex terminal did, and the
    self-test fills its table. Flat colours and row-by-row drawing are both cheap on the screen's link."""
    LABELS = {"CPU": "PROCESSEUR", "MEMORY": "MÉMOIRE", "GPU": "GRAPHIQUE", "TEMPS": "TEMPÉRAT.",
              "STORAGE": "STOCKAGE", "NETWORK": "RÉSEAU", "STEAM": "STEAM"}
    VALUES = [(r"^client running$", "client lancé"), (r"^client not started yet$", "client pas encore lancé"),
              (r"^not installed$", "non installé"), (r"^offline$", "hors ligne"), (r"^no sensor$", "pas de capteur"),
              (r"^amdgpu not found$", "amdgpu absent"), (r"^unavailable$", "indisponible"),
              (r"^Steam library not found$", "bibliothèque Steam absente"),
              (r"^Steam library (\d+) GB free \((\d+)% used\)$", r"bibliothèque Steam \1 Go libres (\2% occupés)"),
              (r"^([\d.]+) GiB system, GDDR6 shared$", r"\1 Gio système, GDDR6 partagée"),
              (r" up to (\d+) MHz$", r" jusqu'à \1 MHz")]
    STATUS = {"OK": ("OK", "GREEN"), "WARN": ("ALERTE", "AMBER"), "WAIT": ("ATTENTE", "MID"), "HOT!": ("CHAUD!", "ALERT_COLOR")}

    @classmethod
    def french(cls, value: str) -> str:
        for pattern, replacement in cls.VALUES:
            value = re.sub(pattern, replacement, value)
        return value

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import ImageDraw
        blank = _Draw.background(spec.get("IMAGE_BLANK", "splash_blank.png"))
        page = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = page.size
        color = {k: _Draw.color(spec.get(k)) for k in ("BRIGHT", "MID", "DIM", "AMBER", "ALERT_COLOR", "GREEN", "BG")}
        small, big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 24)
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))

        def put(x, baseline, text, font, fill, source=blank, width=None, cursor=False):
            """One line of text on the given background, in a box as wide as `width` characters."""
            advance = 12 if font is big else 6
            top, bottom = baseline - (20 if font is big else 10), baseline + (4 if font is big else 2)
            right = min(w, x + advance * (width or len(text) + 1))
            strip = source.crop((x, top, right, bottom))
            d = ImageDraw.Draw(strip)
            d.text((0, baseline - top), text, font=font, fill=fill, anchor="ls")
            if cursor:  # the block cursor after the text
                cx = round(d.textlength(text, font=font))
                d.rectangle((cx, 0, cx + advance - 2, bottom - top - 1), fill=color["BRIGHT"])
            lcd.DisplayPILImage(strip, x, top)

        # 1. the terminal: an empty page, F (not connected) in the corner
        lcd.SetBrightness(0)
        lcd.DisplayPILImage(blank, 0, 0)  # the one full frame (~2 s on a rev A), sent with the backlight off
        lcd.SetBrightness(target)
        _Splash._wait(0.2)

        # 2. the service code typed in, then the connection, with the modem handshake written out
        dx, rows = int(spec["DIAL_X"]), [int(v) for v in spec["DIAL_BL"]]
        code = spec.get("CODE", "3615 BC250")
        for i in range(len(code) + 1):
            put(dx, rows[0], code[:i], big, color["AMBER"], width=len(code) + 1, cursor=True)
            _Splash._wait(0.04)
        put(dx, rows[0], code, big, color["AMBER"], width=len(code) + 1)
        for dots in range(4):
            put(dx, rows[1], "Connexion" + "." * dots, small, color["BRIGHT"], width=13, cursor=dots < 3)
            _Splash._wait(0.16)
        for row, (text, key) in zip(rows[2:], (("~ 390 Hz ~ 1300 Hz ~ 2100 Hz ~", "MID"),
                                               ("porteuse V.23   1200/75 bauds", "MID"),
                                               ("CONNECTÉ", "GREEN"))):
            put(dx, row, text, small, color[key])
            _Splash._wait(0.2)
        cx, cy, cw, ch = (int(v) for v in spec["STATUS_CELL"])
        lcd.DisplayPILImage(page.crop((cx, cy, cx + cw, cy + ch)), cx, cy)  # F -> C
        _Splash._wait(0.3)

        # 3. the page arrives row by row (12 px rows, a white cursor on the row being drawn)
        drawn = {"rows": 0}

        def build(p):
            rows_now = min(h, round(h * p / 12) * 12)
            if rows_now <= drawn["rows"]:
                return
            top = max(0, drawn["rows"] - 12)  # from the previous row: that clears its cursor
            strip = page.crop((0, top, w, rows_now))
            if rows_now < h:
                ImageDraw.Draw(strip).rectangle((0, strip.height - 12, 10, strip.height - 2), fill=color["BRIGHT"])
            lcd.DisplayPILImage(strip, 0, top)
            drawn["rows"] = rows_now

        _Splash._animate(1.2, build)

        # 4. the self-test fills the table
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))

        def row(index, label, value, status=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (label_x, baseline - 11, status_xr, baseline + 3)
            strip = page.crop(box)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((0, oy), cls.LABELS.get(label, label), font=small, fill=color["MID"], anchor="ls")
            d.text((value_x - label_x, oy), _Splash.fit(cls.french(value), chars), font=small, fill=color["BRIGHT"],
                   anchor="ls")
            word, key = cls.STATUS.get(status, ("...", "DIM")) if status else ("...", "DIM")
            d.text((status_xr - label_x, oy), word, font=small, fill=color[key], anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._wait(_Splash.STEP * 0.55)
            row(i, label, value, status)
            _Splash._wait(_Splash.STEP * 0.45)

        # 5. the loading bar: blocks lighting up one after the other
        x, y, bw, bh = (int(spec[k]) for k in ("BAR_X", "BAR_Y", "BAR_W", "BAR_H"))
        lit = {"blocks": 0}

        def fill(p):
            blocks = round(bw // 6 * p)
            if blocks > lit["blocks"]:
                strip = page.crop((x + lit["blocks"] * 6, y, x + blocks * 6, y + bh))
                d = ImageDraw.Draw(strip)
                for b in range(blocks - lit["blocks"]):
                    d.rectangle((b * 6, 0, b * 6 + 4, bh - 1), fill=color["GREEN"])
                lcd.DisplayPILImage(strip, x + lit["blocks"] * 6, y)
                lit["blocks"] = blocks

        _Splash._animate(0.6, fill)

        # 6. the verdict, and ENVOI blinking in the footer, as if pressed to open the dashboard
        warnings = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        verdict = "SERVICE PRÊT" + (f" - {warnings} alerte{'s' * (warnings > 1)}" if warnings else "")
        put(label_x, int(spec.get("STATUS_BL", 276)), verdict, small, color["AMBER"] if warnings else color["GREEN"],
            source=page)
        fx1, fy1, fx2, fy2 = (int(v) for v in spec["FOOTER"])
        key_box = (fx2 - 54, fy1 + 3, fx2 - 11, fy2 - 2)
        pressed = page.crop(key_box)
        ImageDraw.Draw(pressed).rectangle((0, 0, pressed.width - 1, pressed.height - 1), fill=color["AMBER"])
        ImageDraw.Draw(pressed).text((pressed.width // 2, pressed.height - 4), "ENVOI", font=small, fill=color["BG"],
                                     anchor="ms")
        for blink in range(4):
            lcd.DisplayPILImage(pressed if blink % 2 == 0 else page.crop(key_box), key_box[0], key_box[1])
            _Splash._wait(0.18)


class _MissionSplash:
    """Mission Control boot: the console lights up, the flight director polls every station (GO / HOLD / NO GO
    lamps from the same live checks), then the countdown clock runs T-10 to IGNITION and LIFTOFF with a backlight
    flash. Almost all text in small windows: cheap on the screen's link."""
    STATIONS = {"CPU": "STAGE 1", "MEMORY": "GUIDANCE", "GPU": "STAGE 2", "TEMPS": "THERMAL", "STORAGE": "STORAGE",
                "NETWORK": "NETWORK", "STEAM": "STEAM"}
    LAMPS = {"OK": ("GO", "GREEN"), "WAIT": ("HOLD", "AMBER"), "WARN": ("NO GO", "ALERT_COLOR"),
             "HOT!": ("NO GO", "ALERT_COLOR")}

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import ImageDraw
        base = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = base.size
        color = {k: _Draw.color(spec.get(k)) for k in ("BRIGHT", "MID", "DIM", "AMBER", "ALERT_COLOR", "GREEN", "BG")}
        small, big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 36)
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))

        def line(baseline, draw, x1=label_x - 4, x2=status_xr + 4):
            strip = base.crop((x1, baseline - 12, x2, baseline + 4))
            draw(ImageDraw.Draw(strip), baseline - (baseline - 12), x1)
            lcd.DisplayPILImage(strip, x1, baseline - 12)

        def text(baseline, value, fill):
            line(baseline, lambda d, oy, ox: d.text((label_x - ox, oy), value, font=small, fill=fill, anchor="ls"))

        cx1, cy1, cx2, cy2 = (int(v) for v in spec["COUNT_BOX"])
        count_bl = int(spec["COUNT_BL"])

        def clock(value, fill):
            strip = base.crop((cx1, cy1, cx2, cy2))
            ImageDraw.Draw(strip).text((cx2 - cx1 - 8, count_bl - cy1), value, font=big, fill=fill, anchor="rs")
            lcd.DisplayPILImage(strip, cx1, cy1)

        # 1. the console lights up (the one full frame is sent in the dark)
        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)
        _Splash._animate(0.3, lambda p: lcd.SetBrightness(round(target * p)))
        clock("HOLD", color["DIM"])

        # 2. the poll, typed out by the flight director
        head = "FLIGHT: GO / NO-GO POLL FOR LAUNCH"
        for n in range(4, len(head) + 4, 4):
            text(int(spec["HEAD_BL"]), head[:n], color["AMBER"])
            _Splash._wait(0.02)

        lamp_w = 42
        chars = int(spec.get("VALUE_CHARS", 40))

        def row(index, label, value, status=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            station = cls.STATIONS.get(label, label)

            def draw(d, oy, ox):
                leader = station + " " + "." * max(0, (value_x - label_x) // 6 - len(station) - 2)
                d.text((label_x - ox, oy), leader, font=small, fill=color["AMBER"], anchor="ls")
                d.text((value_x - ox, oy), _Splash.fit(value, chars), font=small, fill=color["BRIGHT"], anchor="ls")
                word, key = cls.LAMPS.get(status, ("--", "DIM")) if status else ("--", "DIM")
                lit = color[key] if status else (40, 42, 44)
                lx = status_xr - ox - lamp_w
                d.rectangle((lx, oy - 11, lx + lamp_w, oy + 2), fill=lit)
                d.text((lx + lamp_w // 2, oy), word, font=small, fill=color["BG"] if status else color["DIM"],
                       anchor="ms")

            line(baseline, draw)

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._wait(_Splash.STEP * 0.55)
            row(i, label, value, status)
            _Splash._wait(_Splash.STEP * 0.45)

        # 3. the flight director's verdict
        no_go = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        verdict = ("FLIGHT: WE ARE GO FOR LAUNCH" if not no_go
                   else f"FLIGHT: {no_go} NO-GO, WAIVED. PROCEED")
        text(int(spec.get("STATUS_BL", 270)), verdict, color["AMBER"] if no_go else color["GREEN"])
        _Splash._wait(0.35)

        # 4. the countdown clock, ignition, liftoff with a flash of the backlight
        for t in range(10, 0, -1):
            clock(f"T-{t:02d}", color["AMBER"])
            _Splash._wait(0.09)
        clock("IGNITION", color["ALERT_COLOR"])
        _Splash._wait(0.35)
        clock("LIFTOFF", color["GREEN"])
        lcd.SetBrightness(min(100, round(target * 1.4)))
        text(int(spec.get("LIFTOFF_BL", 294)),
             _Splash.fit(f"WE HAVE LIFTOFF. {spec.get('LOGO_TEXT', 'BC-250')} HAS CLEARED THE TOWER",
                         (status_xr - label_x) // 6), color["BRIGHT"])
        _Splash._wait(0.15)
        lcd.SetBrightness(round(target * 1.15))
        _Splash._wait(0.1)
        lcd.SetBrightness(target)
        _Splash._wait(0.6)


class _MinecraftSplash:
    """Minecraft-inspired boot: the stone logo on dirt with a yellow splash line pulsing beside it (a random one each
    boot), the self-test as a "Loading world" list, then "Building terrain" and its bar. The pulse only changes the
    splash line's own pixels, so it stays smooth on the screen's link."""
    STATUS = {"OK": ("OK", "GREEN"), "WAIT": ("WAIT", "AMBER"), "WARN": ("!!", "ALERT_COLOR"),
              "HOT!": ("HOT!", "ALERT_COLOR")}

    @classmethod
    def play(cls, lcd, spec: dict):
        import random
        from library import config
        from PIL import Image, ImageDraw
        base = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = base.size
        color = {k: _Draw.color(spec.get(k)) for k in ("TEXT", "WHITE", "GREEN", "AMBER", "ALERT_COLOR", "DIM")}
        small = _Draw.font(spec["FONT"], 12)
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))

        # the splash line with its dark shadow, scaled and tilted each frame; the box it repaints is just big enough
        # for its largest size, and placed (SPLASH_AT) beside the logo, clear of the self-test panel
        words = random.choice(spec.get("SPLASH_TEXTS") or ["Steam powered!"])
        tw = round(small.getlength(words)) + 2
        flat = Image.new("RGBA", (tw, 13), (0, 0, 0, 0))
        fd = ImageDraw.Draw(flat)
        fd.text((1, 11), words, font=small, fill=(63, 63, 21, 255), anchor="ls")
        fd.text((0, 10), words, font=small, fill=(255, 255, 85, 255), anchor="ls")
        sx, sy = (int(v) for v in spec["SPLASH_AT"])
        biggest = flat.resize((round(flat.width * 1.12), round(flat.height * 1.12))).rotate(15, expand=True)
        rx, ry = biggest.width // 2 + 2, biggest.height // 2 + 2
        sbox = (max(0, sx - rx), max(0, sy - ry), min(w, sx + rx), min(h, sy + ry))
        t0 = time.monotonic()

        def pulse():
            scale = 0.94 + 0.18 * abs(math.sin((time.monotonic() - t0) * math.pi * 1.6))
            art = flat.resize((max(1, round(flat.width * scale)), max(1, round(flat.height * scale))), Image.NEAREST)
            art = art.rotate(15, expand=True, resample=Image.NEAREST)
            frame = base.crop(sbox)
            frame.paste(art, (sx - sbox[0] - art.width // 2, sy - sbox[1] - art.height // 2), art)
            lcd.DisplayPILImage(frame, sbox[0], sbox[1])

        # 1. the title screen lights up (the one full frame is sent in the dark)
        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)
        pulse()
        _Splash._animate(0.3, lambda p: lcd.SetBrightness(round(target * p)), pulse)

        # 2. "Loading world": the self-test rows
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))

        def row(index, label, value, status=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (label_x, baseline - 11, status_xr, baseline + 3)
            strip = base.crop(box)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((0, oy), label if len(label) <= 3 else label.title(), font=small, fill=color["TEXT"], anchor="ls")
            d.text((value_x - label_x, oy), _Splash.fit(value, chars), font=small, fill=color["DIM"], anchor="ls")
            word, key = cls.STATUS.get(status, ("...", "DIM")) if status else ("...", "DIM")
            d.text((status_xr - label_x, oy), word, font=small, fill=color[key], anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._run(_Splash.STEP * 0.55, pulse)
            row(i, label, value, status)
            _Splash._run(_Splash.STEP * 0.45, pulse)

        # 3. "Building terrain" and its bar
        progress_bl = int(spec["PROGRESS_BL"])

        def caption(words_, fill):
            box = (0, progress_bl - 11, w, progress_bl + 3)
            strip = base.crop(box)
            ImageDraw.Draw(strip).text((w // 2, progress_bl - box[1]), words_, font=small, fill=fill, anchor="ms")
            lcd.DisplayPILImage(strip, 0, box[1])

        caption("Building terrain", color["WHITE"])
        x, y, bw, bh = (int(spec[k]) for k in ("BAR_X", "BAR_Y", "BAR_W", "BAR_H"))

        def fill(p):
            bar = base.crop((x, y, x + bw, y + bh))
            ImageDraw.Draw(bar).rectangle((0, 0, max(0, round(bw * p) - 1), bh - 1), fill=color["WHITE"])
            lcd.DisplayPILImage(bar, x, y)

        _Splash._animate(0.8, fill, pulse)

        # 4. joining
        warnings = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        caption("Joining world..." if not warnings else f"Joining world ({warnings} warning{'s' * (warnings > 1)})",
                color["AMBER"] if warnings else color["WHITE"])
        _Splash._run(0.7, pulse)


class _HalloweenSplash:
    """Halloween boot: lightning shows a graveyard under the full moon, the logo bleeds in from the top, then the
    self-test is a seance (ALIVE, STIRRING, CURSED) while the jack-o'-lanterns flicker and two bats cross the sky, and
    the dead are raised. After the first frame (sent in the dark) only small boxes change: cheap on the link."""
    STATUS = {"OK": ("ALIVE", "GREEN"), "WAIT": ("STIRRING", "MID"), "WARN": ("CURSED", "ALERT_COLOR"),
              "HOT!": ("BURNING", "ALERT_COLOR")}

    @classmethod
    def play(cls, lcd, spec: dict):
        import random
        from library import config
        from PIL import ImageDraw
        full = _Draw.background(spec.get("IMAGE", "splash.png"))
        nologo = _attempt("splash nologo", lambda: _Draw.background(spec["IMAGE_NOLOGO"])) or full
        w, h = full.size
        color = {k: _Draw.color(spec.get(k)) for k in ("TEXT", "GREEN", "AMBER", "ALERT_COLOR", "DIM", "MID", "CANDLE",
                                                       "SILHOUETTE")}
        small = _Draw.font(spec["FONT"], 12)
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        scene = {"image": nologo}  # what the screen shows under the bolts, bats and candle light
        sky = [int(v) for v in spec["SKY"]]

        def level(fraction):
            lcd.SetBrightness(max(0, min(100, round(target * fraction))))

        def bolt():
            """A jagged lightning bolt from the top of the sky to the graves; returns its box, to clear it after."""
            x, y = random.randrange(w // 10, w * 9 // 10), 0
            points = [(x, y)]
            while y < sky[3] - 14:
                y += random.randrange(6, 14)
                x += random.randrange(-12, 13)
                points.append((x, y))
            box = (max(0, min(p[0] for p in points) - 3), 0, min(w, max(p[0] for p in points) + 4), min(h, y + 3))
            frame = scene["image"].crop(box)
            d = ImageDraw.Draw(frame)
            moved = [(px - box[0], py) for px, py in points]
            d.line(moved, fill=(150, 120, 230), width=4)
            d.line(moved, fill=(250, 245, 255), width=2)
            lcd.DisplayPILImage(frame, box[0], box[1])
            return box

        def clear(box):
            lcd.DisplayPILImage(scene["image"].crop(box), box[0], box[1])

        # the jack-o'-lanterns: their carved holes filled with candle light that flickers
        pumpkins = []
        for holes in spec.get("PUMPKINS") or []:
            xs = [p[0] for hole in holes for p in hole]
            ys = [p[1] for hole in holes for p in hole]
            pumpkins.append(((min(xs), min(ys), max(xs) + 1, max(ys) + 1), [[tuple(p) for p in hole] for hole in holes]))

        def candles():
            for box, holes in pumpkins:
                flame = tuple(round(c * random.uniform(0.6, 1.0)) for c in color["CANDLE"])
                frame = scene["image"].crop(box)
                d = ImageDraw.Draw(frame)
                for hole in holes:
                    d.polygon([(x - box[0], y - box[1]) for x, y in hole], fill=flame)
                lcd.DisplayPILImage(frame, box[0], box[1])

        # two bats crossing the sky on wavy paths, each redrawn with the box it leaves in one update
        shape = [tuple(p) for p in spec.get("BAT") or []]
        flight_start = {"t": None}
        bats = [dict(scale=1.6, y=sky[3] * 0.32, speed=150, phase=0.0, box=None, flip=False),
                dict(scale=1.2, y=sky[3] * 0.55, speed=110, phase=1.7, box=None, flip=True)]

        def fly():
            if not shape:
                return
            if flight_start["t"] is None:
                flight_start["t"] = time.monotonic()
            t = time.monotonic() - flight_start["t"]
            for b in bats:
                travel = (t * b["speed"]) % (w + 60) - 30
                x = w - travel if b["flip"] else travel
                y = b["y"] + 6 * math.sin(t * 4 + b["phase"])
                flap = 1.0 if int(t * 8 + b["phase"] * 3) % 2 else 0.55  # wings up, wings down
                points = [(x + px * b["scale"], y + py * b["scale"] * (flap if py < 0 else 1)) for px, py in shape]
                box = (int(min(p[0] for p in points)) - 1, int(min(p[1] for p in points)) - 1,
                       int(max(p[0] for p in points)) + 2, int(max(p[1] for p in points)) + 2)
                old = b["box"]
                b["box"] = box
                if old is not None and (old[2] < box[0] or box[2] < old[0]):  # wrapped around: clear where it was
                    old = (max(0, old[0]), max(0, old[1]), min(w, old[2]), min(sky[3], old[3]))
                    if old[2] > old[0] and old[3] > old[1]:
                        clear(old)
                    old = None
                union = box if old is None else (min(box[0], old[0]), min(box[1], old[1]),
                                                 max(box[2], old[2]), max(box[3], old[3]))
                union = (max(0, union[0]), max(0, union[1]), min(w, union[2]), min(sky[3], union[3]))
                if union[2] <= union[0] or union[3] <= union[1]:
                    continue
                frame = scene["image"].crop(union)
                ImageDraw.Draw(frame).polygon([(px - union[0], py - union[1]) for px, py in points],
                                              fill=color["SILHOUETTE"])
                lcd.DisplayPILImage(frame, union[0], union[1])

        def tick():
            candles()
            fly()

        # 1. a storm: the graveyard (sent in the dark) seen in the flashes of lightning, then the dusk light
        level(0)
        lcd.DisplayPILImage(nologo, 0, 0)
        box = bolt()
        level(2.5)
        _Splash._wait(0.06)
        level(0)
        _Splash._wait(0.1)
        level(1.6)
        _Splash._wait(0.05)
        level(0)
        clear(box)
        _Splash._wait(0.3)
        box = bolt()
        level(2.2)
        _Splash._wait(0.08)
        level(0.15)
        clear(box)
        _Splash._animate(0.5, lambda p: level(0.15 + 0.85 * p))

        # 2. the logo bleeds in, from the top down
        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LOGO_BOX"])
        shown = {"row": ly1}

        def bleed(p):
            row = ly1 + round((ly2 - ly1) * p)
            if row > shown["row"]:
                lcd.DisplayPILImage(full.crop((lx1, shown["row"], lx2, row)), lx1, shown["row"])
                shown["row"] = row

        _Splash._animate(0.8, bleed)
        scene["image"] = full

        # 3. the seance: the self-test rows, the candles lit
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))

        def row(index, label, value, status=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box_ = (label_x, baseline - 11, status_xr, baseline + 3)
            strip = full.crop(box_)
            d = ImageDraw.Draw(strip)
            oy = baseline - box_[1]
            d.text((0, oy), label, font=small, fill=color["MID"], anchor="ls")
            d.text((value_x - label_x, oy), _Splash.fit(value, chars), font=small, fill=color["TEXT"], anchor="ls")
            word, key = cls.STATUS.get(status, ("...", "DIM")) if status else ("...", "DIM")
            d.text((status_xr - label_x, oy), word, font=small, fill=color[key], anchor="rs")
            lcd.DisplayPILImage(strip, box_[0], box_[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._run(_Splash.STEP * 0.55, tick)
            row(i, label, value, status)
            _Splash._run(_Splash.STEP * 0.45, tick)

        # 4. raising the dead, and its bar
        progress_bl = int(spec["PROGRESS_BL"])
        cx1, cx2 = (int(v) for v in spec["CAPTION"])

        def caption(words, fill):
            box_ = (cx1, progress_bl - 11, cx2, progress_bl + 3)
            strip = full.crop(box_)
            ImageDraw.Draw(strip).text(((cx2 - cx1) // 2, progress_bl - box_[1]), words, font=small, fill=fill,
                                       anchor="ms")
            lcd.DisplayPILImage(strip, box_[0], box_[1])

        caption("Raising the dead...", color["MID"])
        x, y, bw, bh = (int(spec[k]) for k in ("BAR_X", "BAR_Y", "BAR_W", "BAR_H"))

        def fill(p):
            bar = full.crop((x, y, x + bw, y + bh))
            ImageDraw.Draw(bar).rectangle((0, 0, max(0, round(bw * p) - 1), bh - 1), fill=color["MID"])
            lcd.DisplayPILImage(bar, x, y)

        _Splash._animate(0.8, fill, tick)

        # 5. it's alive! and a last thunderclap
        curses = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        caption("IT'S ALIVE!" if not curses else f"IT'S ALIVE... ({curses} curse{'s' * (curses > 1)})",
                color["MID"] if curses else color["GREEN"])
        level(2.0)
        _Splash._wait(0.06)
        level(1.0)
        _Splash._run(0.7, tick)


class _ChristmasSplash:
    """Christmas boot: a silent snowy night fades in, the logo appears, the tree's lights come on, then the self-test
    is Santa's list (NICE, WRAPPING, NAUGHTY) while the sleigh crosses the sky and a candy-cane bar fills. Snow falls
    all along. Each frame redraws the whole sky, and _Screen sends only what changed: the flakes and bulbs."""
    STATUS = {"OK": ("NICE", "GREEN"), "WAIT": ("WRAPPING", "AMBER"), "WARN": ("NAUGHTY", "ALERT_COLOR"),
              "HOT!": ("MELTING", "ALERT_COLOR")}

    @classmethod
    def play(cls, lcd, spec: dict):
        import random
        from library import config
        from PIL import Image, ImageDraw
        full = _Draw.background(spec.get("IMAGE", "splash.png"))
        nologo = _attempt("splash nologo", lambda: _Draw.background(spec["IMAGE_NOLOGO"])) or full
        w, h = full.size
        color = {k: _Draw.color(spec.get(k)) for k in ("TEXT", "GREEN", "AMBER", "ALERT_COLOR", "DIM", "MID", "SNOW",
                                                       "HOLLY")}
        small = _Draw.font(spec["FONT"], 12)
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        sky = tuple(int(v) for v in spec["SKY"])
        scene = {"image": nologo.copy()}  # the night as it is so far, under the snow, the bulbs and the sleigh

        def level(fraction):
            lcd.SetBrightness(max(0, min(100, round(target * fraction))))

        flakes = [dict(x=random.randrange(w), y=random.uniform(0, sky[3]), speed=random.uniform(14, 40),
                       sway=random.uniform(0, 6.28), big=random.random() < 0.3) for _ in range(w // 18)]
        lights = [(int(x), int(y), tuple(c), random.uniform(0, 6.28), random.uniform(2, 5))
                  for x, y, c in spec.get("LIGHTS") or []]
        shapes = [(tuple(c), [tuple(p) for p in points]) for c, points in spec.get("SLEIGH") or []]
        lit = {"on": False, "all": False}
        flight = {"start": None, "seconds": 3.4}
        t0 = time.monotonic()

        def tick():
            t = time.monotonic() - t0
            frame = scene["image"].crop(sky)
            d = ImageDraw.Draw(frame)
            if lit["on"]:
                for x, y, c, phase, speed in lights:
                    if lit["all"] or math.sin(t * speed + phase) > -0.35:
                        d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=c)
            if flight["start"] is not None:
                p = (time.monotonic() - flight["start"]) / flight["seconds"]
                if p < 1:
                    ox, oy = -90 + (w + 100) * p, 6 + 2 * math.sin(p * 18)
                    for c, points in shapes:
                        d.polygon([(ox + x, oy + y) for x, y in points], fill=c)
            for f in flakes:
                x = (f["x"] + 5 * math.sin(t * 1.4 + f["sway"])) % w
                y = (f["y"] + t * f["speed"]) % sky[3]
                if f["big"]:
                    d.rectangle((x, y, x + 1, y + 1), fill=color["SNOW"])
                else:
                    d.point((x, y), fill=color["SNOW"])
            lcd.DisplayPILImage(frame, sky[0], sky[1])

        # 1. the night (sent in the dark) fades in, snow already falling
        level(0)
        lcd.DisplayPILImage(nologo, 0, 0)
        _Splash._animate(0.9, lambda p: level(p), tick)

        # 2. the logo appears, from left to right
        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LOGO_BOX"])
        shown = {"x": lx1}

        def reveal(p):
            x = lx1 + round((lx2 - lx1) * p)
            if x > shown["x"]:
                scene["image"].paste(full.crop((shown["x"], ly1, x, ly2)), (shown["x"], ly1))
                shown["x"] = x

        _Splash._animate(0.7, reveal, tick)

        # 3. someone switches the tree on
        lit["on"] = lit["all"] = True
        tick()
        level(1.5)
        _Splash._run(0.1, tick)
        level(1.0)
        lit["all"] = False
        _Splash._run(0.2, tick)
        flight["start"] = time.monotonic()

        # 4. Santa's list: the self-test rows
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))

        def row(index, label, value, status=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (label_x, baseline - 11, status_xr, baseline + 3)
            strip = full.crop(box)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((0, oy), label, font=small, fill=color["MID"], anchor="ls")
            d.text((value_x - label_x, oy), _Splash.fit(value, chars), font=small, fill=color["TEXT"], anchor="ls")
            word, key = cls.STATUS.get(status, ("...", "DIM")) if status else ("...", "DIM")
            d.text((status_xr - label_x, oy), word, font=small, fill=color[key], anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._run(_Splash.STEP * 0.55, tick)
            row(i, label, value, status)
            _Splash._run(_Splash.STEP * 0.45, tick)

        # 5. loading the sleigh: a candy-cane bar
        progress_bl = int(spec["PROGRESS_BL"])
        cx1, cx2 = (int(v) for v in spec["CAPTION"])

        def caption(words, fill):
            box = (cx1, progress_bl - 11, cx2, progress_bl + 3)
            strip = full.crop(box)
            ImageDraw.Draw(strip).text(((cx2 - cx1) // 2, progress_bl - box[1]), words, font=small, fill=fill,
                                       anchor="ms")
            lcd.DisplayPILImage(strip, box[0], box[1])

        caption("Loading the sleigh...", color["MID"])
        x, y, bw, bh = (int(spec[k]) for k in ("BAR_X", "BAR_Y", "BAR_W", "BAR_H"))
        cane = Image.new("RGB", (bw, bh), color["SNOW"])
        cd = ImageDraw.Draw(cane)
        for sx in range(-bh, bw, 10):  # slanted red stripes
            cd.polygon([(sx, bh), (sx + bh, 0), (sx + bh + 5, 0), (sx + 5, bh)], fill=color["HOLLY"])

        def fill(p):
            bar = full.crop((x, y, x + bw, y + bh))
            width = round(bw * p)
            if width:
                bar.paste(cane.crop((0, 0, width, bh)), (0, 0))
            lcd.DisplayPILImage(bar, x, y)

        _Splash._animate(0.8, fill, tick)

        # 6. merry Christmas, the whole tree lit
        naughty = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        caption("MERRY CHRISTMAS!" if not naughty else f"MERRY CHRISTMAS! ({naughty} on the naughty list)",
                color["AMBER"] if naughty else color["GREEN"])
        lit["all"] = True
        level(1.5)
        _Splash._run(0.08, tick)
        level(1.0)
        _Splash._run(0.7, tick)


class _SeismographSplash:
    """Seismograph boot, on the dashboard's own paper: the station's log is typed on it, the feed is contacted, the
    instrument draws the calibration pulses every real seismogram starts with, then the sheet is changed and the pen
    takes over at once. Only the ink has to be sent."""
    STATUS = {"OK": ("OK", (26, 104, 62)), "WAIT": ("WAIT", (168, 110, 10)), "WARN": ("FAIL", (168, 34, 30)),
              "HOT!": ("HOT", (168, 34, 30))}
    INK, FAINT = (28, 30, 40), (150, 140, 118)

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import ImageDraw
        base = _Draw.background(spec.get("IMAGE", "background.png"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        small = _Draw.font(spec["FONT"], 12)
        px, py, pw, ph = (int(v) for v in spec["PAPER"])
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))
        _QuakeFeed.start(float(spec.get("MIN_MAG", 2.5)))

        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)  # the one full frame (~2 s on a rev A), sent in the dark
        _Splash._animate(0.5, lambda p: lcd.SetBrightness(round(target * p)))

        def row(index, label, value, word=None, fill=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (label_x, baseline - 11, status_xr, baseline + 3)
            strip = base.crop(box)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((0, oy), label, font=small, fill=cls.FAINT, anchor="ls")
            d.text((value_x - label_x, oy), _Splash.fit(value, chars), font=small, fill=cls.INK, anchor="ls")
            d.text((status_xr - label_x, oy), word or "...", font=small, fill=fill or cls.FAINT, anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._wait(_Splash.STEP * 0.5)
            word, fill = cls.STATUS.get(status, ("OK", cls.STATUS["OK"][1]))
            row(i, label, value, word, fill)
            _Splash._wait(_Splash.STEP * 0.4)

        # the feed (a few seconds at most for its first answer)
        n = len(lines)
        row(n, "USGS", "contacting the feed")
        deadline = time.monotonic() + 3
        while _QuakeFeed.fetched is None and _QuakeFeed.error is None and time.monotonic() < deadline:
            _Splash._wait(0.1)
        if _QuakeFeed.fetched:
            row(n, "USGS", f"{len(_QuakeFeed.quakes)} quakes in the past day", "OK", cls.STATUS["OK"][1])
        else:
            row(n, "USGS", "no answer yet, still listening", "WAIT", cls.STATUS["WAIT"][1])
        _Splash._wait(0.25)

        # the calibration pulses, at the foot of the paper
        y = py + ph - 8
        x0 = px + int(spec.get("MARGIN", 36))
        width = min(180, pw - int(spec.get("MARGIN", 36)) - 8)
        box = (x0, y - 8, x0 + width, y + 2)

        def calibrate(p):
            strip = base.crop(box)
            d = ImageDraw.Draw(strip)
            points, drawn = [(0, 8)], round(width * p)
            for x in range(0, drawn, 30):
                points += [(x, 8), (x, 1), (min(drawn, x + 15), 1), (min(drawn, x + 15), 8), (min(drawn, x + 30), 8)]
            d.line(points, fill=cls.INK)
            lcd.DisplayPILImage(strip, box[0], box[1])

        _Splash._animate(0.7, calibrate)
        _Splash._wait(0.5)


class _HorrorSplash:
    """Horror boot. It starts as the most ordinary thing in the world: a self-test on a black screen, every line OK.
    Then one line too many: OCCUPANTS 2, expected 1. The readings stop being readings, the screen goes dark, one
    sentence, and for a fifth of a second you see the feed with it right there. Then the feed, and it is far away."""
    TURNED = {"CPU": "IT CAN HEAR THE FAN", "MEMORY": "IT REMEMBERS YOU", "GPU": "IT CAN SEE",
              "TEMPS": "IT IS GETTING WARMER", "STORAGE": "THERE IS ROOM DOWN THERE", "NETWORK": "NO ONE WILL HEAR",
              "STEAM": "YOU CAN'T QUIT"}

    @classmethod
    def play(cls, lcd, spec: dict):
        import random
        from library import config
        from PIL import Image, ImageDraw
        black = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = black.size
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        small = _Draw.font(spec["FONT"], 12)
        text, dim, red, mid = (_Draw.color(spec.get(k)) for k in ("TEXT", "DIM", "RED", "MID"))
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))

        def level(fraction):
            lcd.SetBrightness(max(0, min(100, round(target * fraction))))

        def line(y, words, fill, anchor="ls", x=label_x):
            box = (0, y - 11, w, y + 3)
            strip = black.crop(box)
            ImageDraw.Draw(strip).text((x, y - box[1]), words, font=small, fill=fill, anchor=anchor)
            lcd.DisplayPILImage(strip, 0, box[1])

        def row(index, label, value, status, fill=None, status_fill=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (0, baseline - 11, w, baseline + 3)
            strip = black.crop(box)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((label_x, oy), label, font=small, fill=dim, anchor="ls")
            d.text((value_x, oy), _Splash.fit(value, chars), font=small, fill=fill or text, anchor="ls")
            d.text((status_xr, oy), status, font=small, fill=status_fill or dim, anchor="rs")
            lcd.DisplayPILImage(strip, 0, box[1])

        # 1. an ordinary self-test
        level(0)
        lcd.DisplayPILImage(black, 0, 0)
        level(1)
        line(int(spec["ROW_BL"]) - 36, "BC-250 SECURITY CONSOLE  v2.50", dim)
        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value, "...")
            _Splash._wait(0.1)
            row(i, label, value, "OK" if status == "OK" else status, None, red if status in ("WARN", "HOT!") else None)
            _Splash._wait(0.08)

        # 2. one line too many
        extra = len(lines)
        row(extra, "OCCUPANTS", "...", "...")
        _Splash._wait(0.5)
        row(extra, "OCCUPANTS", "2 (expected 1)", "??", text, red)
        _Splash._wait(0.8)

        # 3. the readings stop being readings
        order = list(enumerate(lines))
        random.shuffle(order)
        for i, (label, _, _) in order:
            level(random.uniform(0.3, 1.0))
            row(i, label, cls.TURNED.get(label, "IT IS HERE"), "NO", red, red)
            _Splash._wait(random.uniform(0.06, 0.16))
        level(0.1)
        _Splash._wait(0.08)
        level(1)
        _Splash._wait(0.25)

        # 4. dark, one sentence
        level(0)
        lcd.DisplayPILImage(black, 0, 0)
        words = "it was already running when you pressed the button"
        line(h // 2, words[:(w - 8) // 6], text, "ms", w // 2)
        _Splash._wait(0.5)
        level(0.8)
        _Splash._wait(0.9)
        level(0)

        # 5. a fifth of a second of what is on the camera, close (sent in the dark)
        background = _Draw.background("background.png").copy()
        x, y, fw, fh = (int(v) for v in spec["FEED"])
        sprite = Image.open(_Draw.background_path(spec["FIGURE"])).convert("RGBA")
        stages = spec["STAGES"]
        art, fx, fy = _Horror.figure_layer(sprite, stages[-1], {}, len(stages) - 1)
        close = background.copy()
        feed = close.crop((x, y, x + fw, y + fh))
        feed.paste(art, (fx, fy), art)
        close.paste(feed, (x, y))
        lcd.DisplayPILImage(close, 0, 0)
        _Splash._wait(0.1)
        level(1.6)
        _Splash._wait(0.2)
        level(0)

        # 6. and then it is just a corridor
        lcd.DisplayPILImage(background, 0, 0)
        _Splash._wait(0.2)
        _Splash._animate(0.6, lambda p: level(p * p))


class _NixieSplash:
    """Nixie boot: the tubes strike one by one, spin through their digits like a slot machine (what Nixie clocks do
    to keep their cathodes healthy) and settle on the time; then the seven neon lamps light up one after the other
    for the self-test, its readings typed underneath. Only the tubes and lamps change: cheap on the link."""

    @classmethod
    def play(cls, lcd, spec: dict):
        import random
        from library import config
        from PIL import ImageChops, ImageDraw
        base = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = base.size
        small = _Draw.font(spec["FONT"], 12)
        glow_c, core_c, lamp_c = (_Draw.color(spec.get(k)) for k in ("GLOW", "CORE", "LAMP_ON"))
        amber, brass = _Draw.color(spec.get("BRIGHT")), _Draw.color(spec.get("MID"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        xs, ty = [int(v) for v in spec["TUBE_XS"]], int(spec["TUBE_Y"])
        tw, th = int(spec["TUBE_W"]), int(spec["TUBE_H"])
        font = spec["NIXIE_FONT"]
        shown = {}

        def tube(i, char, strength=1.0):
            if shown.get(i) == (char, strength):
                return
            shown[i] = (char, strength)
            unlit = base.crop((xs[i], ty, xs[i] + tw, ty + th))
            lcd.DisplayPILImage(ImageChops.add(unlit, _Tube.light(font, tw, th, char, False, glow_c, core_c, strength)),
                                xs[i], ty)

        def colons(lit):
            for cx, cy in spec["COLONS"]:
                dot = base.crop((cx - 4, cy - 4, cx + 5, cy + 5))
                if lit:
                    ImageDraw.Draw(dot).ellipse((1, 1, 7, 7), fill=_lerp(glow_c, (0, 0, 0), 0.3))
                    ImageDraw.Draw(dot).ellipse((2, 2, 6, 6), fill=core_c)
                lcd.DisplayPILImage(dot, cx - 4, cy - 4)

        def lamp(i, color):
            lx, ly = (int(v) for v in spec["LAMPS"][i])
            bulb = base.crop((lx - 9, ly - 9, lx + 10, ly + 10))
            if color:
                d = ImageDraw.Draw(bulb)
                d.ellipse((0, 0, 18, 18), fill=_lerp(color, (0, 0, 0), 0.72))
                d.ellipse((3, 3, 15, 15), fill=color)
                d.ellipse((6, 6, 10, 10), fill=_lerp(color, (255, 255, 255), 0.5))
            lcd.DisplayPILImage(bulb, lx - 9, ly - 9)

        def line(baseline, words, fill):
            strip = base.crop((8, baseline - 11, w - 8, baseline + 3))
            ImageDraw.Draw(strip).text((w // 2 - 8, 11), words, font=small, fill=fill, anchor="ms")
            lcd.DisplayPILImage(strip, 8, baseline - 11)

        # 1. the board powers up in the dark, then each tube strikes: a dim flicker, then full glow
        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)
        lcd.SetBrightness(target)
        for i in range(6):
            tube(i, "0", 0.35)
            _Splash._wait(0.05)
            tube(i, "0")
            _Splash._wait(0.04)

        # 2. slot machine: every tube spins through its digits and they stop on the time, left to right
        stops = {}

        def spin(p):
            now = time.strftime("%H%M%S")
            for i in range(6):
                if p >= 0.35 + i * 0.1:
                    stops.setdefault(i, True)
                tube(i, now[i] if i in stops else str(random.randrange(10)))

        _Splash._animate(1.3, spin)
        colons(True)

        # 3. the self-test: a lamp per check, its reading typed under the lamps
        def keep_time():
            now = time.strftime("%H%M%S")
            for i in range(6):
                tube(i, now[i])

        lines = _Splash.post_lines(spec)
        colours = {"OK": glow_c, "WAIT": _lerp(glow_c, (0, 0, 0), 0.5), "WARN": lamp_c, "HOT!": lamp_c}
        text_bl = int(spec.get("TEXT_BL", 246))
        chars = (w - 32) // 6
        for i, (label, value, status) in enumerate(lines[:len(spec["LAMPS"])]):
            lamp(i, _lerp(glow_c, (0, 0, 0), 0.6))
            line(text_bl, _Splash.fit(f"{label}  {value}", chars), amber)
            _Splash._run(_Splash.STEP * 0.55, keep_time)
            lamp(i, colours.get(status, glow_c))
            _Splash._run(_Splash.STEP * 0.45, keep_time)

        # 4. the verdict, then a last quick spin back to the time
        warnings = sum(1 for _, _, st in lines if st in ("WARN", "HOT!"))
        line(text_bl, "", amber)
        line(int(spec.get("STATUS_BL", 274)), "READY" if not warnings else
             f"READY - {warnings} WARNING{'S' * (warnings > 1)}", lamp_c if warnings else amber)
        stops.clear()
        _Splash._animate(0.6, lambda p: [tube(i, time.strftime("%H%M%S")[i] if p >= 0.3 + i * 0.1
                                              else str(random.randrange(10))) for i in range(6)])
        _Splash._run(0.4, keep_time)


class _RadarSplash:
    """Radar boot, on the dashboard's own scope (it is the cover frame, revealed by the backlight): the range rings
    light up one by one, a console log runs the self-test, opens the data link and loads the map in the side panel,
    then the first contacts appear on the scope. No sweep here: the dashboard's sweep starts the moment this ends."""
    STATUS = {"OK": ("OK", "SWEEP"), "WAIT": ("WAIT", "MID"), "WARN": ("FAIL", "EMERGENCY"), "HOT!": ("HOT", "EMERGENCY")}

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import Image, ImageDraw
        base = _Draw.background(spec.get("IMAGE", "background.png"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        _RadarFeed.start(float(spec["LAT"]), float(spec["LON"]), float(spec["RANGE_KM"]), float(spec.get("REFRESH", 6)))
        radar = _Radar(spec, lcd, base)
        radar.lcd = lcd  # the splash's screen: everything below sends only what changes
        small, col = radar.small, radar.col

        # 1. the console in the dark, then the backlight comes up on it
        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)  # the one full frame (~2 s on a rev A)
        _Splash._animate(0.6, lambda p: lcd.SetBrightness(round(target * p)))

        # the console log in the side panel (scrolling when it is full)
        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LOG"])
        rows, chars = (ly2 - ly1) // 14, (lx2 - lx1) // 6
        lines = []

        def show_log():
            image = Image.new("RGB", (lx2 - lx1, ly2 - ly1), _Draw.color(spec.get("BG"), (2, 9, 4)))
            d = ImageDraw.Draw(image)
            for i, (text, colour) in enumerate(lines[-rows:]):
                d.text((0, 11 + 14 * i), text[:chars], font=small, fill=colour, anchor="ls")
            lcd.DisplayPILImage(image, lx1, ly1)

        def log(text, colour, replace=False):
            if replace and lines:
                lines[-1] = (text, colour)
            else:
                lines.append((text, colour))
            show_log()

        def dots(label, word):
            return f"{label} {'.' * max(1, chars - len(label) - len(word) - 2)} {word}"

        # 2. power on: the range rings light up from the centre out
        log("POWER ON", col["TEXT"])
        scope = radar.scope.copy()
        d = ImageDraw.Draw(scope)
        ox, oy = radar.cx - radar.box[0], radar.cy - radar.box[1]
        for radius in spec.get("RINGS", []):
            d.ellipse((ox - radius, oy - radius, ox + radius, oy + radius), outline=_lerp(col["SWEEP"], (0, 0, 0), 0.45))
            lcd.DisplayPILImage(scope, radar.box[0], radar.box[1])
            _Splash._wait(0.08)

        # 3. the self-test
        for label, value, status in _Splash.post_lines(spec):
            log(dots(label, ".."), col["DIM"])
            _Splash._wait(_Splash.STEP * 0.55)
            word, key = cls.STATUS.get(status, ("OK", "SWEEP"))
            log(dots(label, word), col[key], replace=True)
            _Splash._wait(_Splash.STEP * 0.45)

        # 4. the map, then the data link (a few seconds at most for the first answer)
        log(dots("MAP", f"{int(spec.get('MAP_COUNT', 0))} FIELDS"), col["SWEEP"])
        log(dots("DATA LINK", "..."), col["DIM"])
        deadline = time.monotonic() + 3
        while _RadarFeed.fetched is None and _RadarFeed.error is None and time.monotonic() < deadline:
            _Splash._wait(0.1)
        if _RadarFeed.fetched:
            log(dots("DATA LINK", (_RadarFeed.source or "OK").upper()), col["SWEEP"], replace=True)
        else:
            log(dots("DATA LINK", "NO ANSWER"), col["EMERGENCY"], replace=True)

        # 5. the contacts appear, nearest first; the dashboard's sweep then takes over the scope as it is
        now = time.time()
        radar.sweep_over(now)
        count = len(radar.memory)
        batches = min(count, 10)
        for b in range(1, batches + 1):
            frame = radar.scope_frame(None, time.time(), None, limit=round(count * b / batches))
            lcd.DisplayPILImage(frame, radar.box[0], radar.box[1])
            _Splash._wait(0.05)
        log(dots("CONTACTS", str(count)), col["SWEEP"] if count else col["DIM"])
        log("SWEEP ON", col["TEXT"])
        _Splash._wait(0.6)


def _handoff(screen) -> bool:
    """From the splash straight to the dashboard: the splash knows what the screen shows, so only what differs from
    the dashboard's background is sent, instead of the app repainting the whole screen (~2 s on a rev A, with
    nothing moving). The radar keeps its scope as the splash left it and starts sweeping at once."""
    from PIL import Image
    from library import config
    statics = config.THEME_DATA.get("static_images") or {}
    background = statics.get("BACKGROUND") or {}
    if list(statics) != ["BACKGROUND"] or background.get("X", 0) or background.get("Y", 0) or screen.shadow is None:
        return False  # something else to draw: let the app do it
    target = _Draw.background(background.get("PATH", "background.png")).copy()
    if target.size != (screen.width, screen.height):
        return False
    radar = _Draw.theme("Bc250Radar")
    if radar.get("SCOPE"):  # the scope stays as the splash left it: the sweep takes it over from there
        cx, cy, r = (int(v) for v in radar["SCOPE"])
        keep = (cx - r - 1, cy - r - 1, cx + r + 2, cy + r + 2)
        target.paste(Image.fromarray(screen.shadow).crop(keep), keep[:2])
    screen.DisplayPILImage(target, 0, 0)
    screen.TILE = 10
    _Draw.screen = screen
    if radar.get("SCOPE"):
        Bc250Radar().as_numeric()  # start the sweep now, not when the app's widgets get going (~3 s later)
    return True


def _shared_screen(lcd):
    """After the app draws the background: one _Screen for every BC-250 widget, knowing that the screen now shows
    that background. The app's own widgets draw elsewhere, so what it knows of our areas stays true."""
    import numpy
    from library import config
    background = config.THEME_DATA["static_images"]["BACKGROUND"]
    image = _Draw.background(background.get("PATH", "background.png"))
    screen = _Screen(lcd, *image.size)
    screen.shadow = numpy.asarray(image).copy()
    screen.TILE = 10
    _Draw.screen = screen


def _serialize_display(lcd):
    """The app queues a bitmap as a command, then its pixel data, under two separate locks: two threads drawing at
    once can interleave them (the radar draws from a thread of its own). One lock around the whole call fixes it."""
    import threading
    if lcd is None or getattr(type(lcd), "_bc250_serialized", False):
        return
    cls = type(lcd)
    original = cls.DisplayPILImage
    lock = threading.Lock()

    def DisplayPILImage(self, *args, **kwargs):
        with lock:
            return original(self, *args, **kwargs)

    cls.DisplayPILImage = DisplayPILImage
    cls._bc250_serialized = True


def _install_splash_hook():
    """Play the splash right before the app draws the theme background, i.e. after the screen is initialised and
    before any widget starts. Only when the app's display module is loaded: importing it from here would open the
    screen (bc250_check.py imports this module and must stay read-only)."""
    display_module = sys.modules.get("library.display")
    display = getattr(display_module, "display", None)
    if display is None or getattr(type(display), "_bc250_splash", False):
        return
    original = type(display).display_static_images

    def display_static_images(self):
        first = not getattr(type(self), "_bc250_booted", False)
        type(self)._bc250_booted = True
        screen = _attempt("boot splash", lambda: _Splash.play(self.lcd)) if first else None
        if not (screen is not None and _attempt("handoff", lambda: _handoff(screen), False)):
            original(self)
            _attempt("widget screen", lambda: _shared_screen(self.lcd))

    type(display).display_static_images = display_static_images
    type(display)._bc250_splash = True
    _attempt("display lock", lambda: _serialize_display(getattr(display, "lcd", None)))


def _resilient(cls):
    """Wraps a widget's methods so an unexpected error shows "--" instead of escaping: stats.Custom.stats stops at
    the first exception, which would freeze every widget after it."""
    defaults = {"as_numeric": math.nan, "as_string": "--", "last_values": None}
    for method, default in defaults.items():
        original = getattr(cls, method, None)
        if original is None:
            continue

        def guarded(self, _original=original, _default=default, _name=f"{cls.__name__}.{method}"):
            try:
                return _original(self)
            except Exception as e:
                if _name not in _Draw._failed:
                    _Draw._failed.add(_name)
                    logger.error("BC250: %s failed: %s", _name, e)
                return _default
        setattr(cls, method, guarded)
    return cls


for _name, _obj in list(globals().items()):
    if _name.startswith("Bc250") and isinstance(_obj, type):
        _resilient(_obj)

_install_splash_hook()
