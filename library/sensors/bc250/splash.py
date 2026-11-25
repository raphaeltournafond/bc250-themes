# SPDX-License-Identifier: GPL-3.0-or-later
"""The boot splash (CRT warm-up, BIOS screen, a POST of real values, loading bar) and the handoff to the
dashboard; _Screen, the changed-pixels sender every self-drawn widget draws through.

A theme with a boot of its own adds it to _Splash.STYLES, and a widget that carries on from what its
boot leaves on the screen says so with _Splash.takes_over."""

import math
import os
import re
import sys
import time
from typing import List

from .base import logger, _read
from .draw import _attempt, _dim, _Draw
from .hardware import _AmdGpu, Bc250CpuTemp, Bc250GpuTemp
from .screen import Bc250Screen
from .steam import _GameDisk, _Steam, _steam_roots


def _screen_level(lcd, fraction: float):
    """A share of the brightness the screen should have now (the theme's dimming stays in charge)."""
    from library import config
    spec = _Draw.theme("Bc250Screen").get("SCREEN", {})
    target = int(spec.get("DIM_BRIGHTNESS", 5)) if Bc250Screen._mode == "dim" else \
        int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))
    lcd.SetBrightness(max(0, min(100, round(target * fraction))))


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
    STYLES = {}  # bc250_splash STYLE in theme.yaml -> the theme's own boot animation (each theme's module adds its own)
    TAKEOVERS = []  # (widget, key of its area in theme.yaml, that area as a box, whether the boot left it there)

    @classmethod
    def takes_over(cls, widget, key, box=lambda a: (a[0], a[1], a[0] + a[2], a[1] + a[3]), kept=lambda: True):
        """A widget that carries on from what its theme's boot animation leaves on the screen: at the handoff that
        area stays as the boot left it (box: from its x, y, w, h by default), and the widget starts at once."""
        cls.TAKEOVERS.append((widget, key, box, kept))

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
        player = cls.STYLES.get(spec.get("STYLE"))
        if player:
            player.play(lcd, spec)
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


def _handoff(screen) -> bool:
    """From the splash straight to the dashboard: the splash knows what the screen shows, so only what differs from
    the dashboard's background is sent, instead of the app repainting the whole screen (~2 s on a rev A, with
    nothing moving). The widgets that carry on from their boot (_Splash.takes_over: the radar's sweep, the orbit's
    map...) keep their area as the boot left it and start at once."""
    from PIL import Image
    from library import config
    statics = config.THEME_DATA.get("static_images") or {}
    background = statics.get("BACKGROUND") or {}
    if list(statics) != ["BACKGROUND"] or background.get("X", 0) or background.get("Y", 0) or screen.shadow is None:
        return False  # something else to draw: let the app do it
    target = _Draw.background(background.get("PATH", "background.png")).copy()
    if target.size != (screen.width, screen.height):
        return False
    starting = []
    for widget, key, box, kept in _Splash.TAKEOVERS:
        area = _Draw.theme(widget.__name__).get(key)
        if not area:
            continue
        starting.append(widget)
        if kept():
            x1, y1, x2, y2 = box([int(v) for v in area])
            target.paste(Image.fromarray(screen.shadow).crop((x1, y1, x2, y2)), (x1, y1))
    screen.DisplayPILImage(target, 0, 0)
    screen.TILE = 10
    _Draw.screen = screen
    for widget in starting:
        widget().as_numeric()  # start now, not when the app's widgets get going (~3 s later)
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
