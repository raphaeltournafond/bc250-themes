# SPDX-License-Identifier: GPL-3.0-or-later
"""Nixie theme: the tubes, and its boot."""

import math
import time
from typing import List

from ..base import _is_nan
from ..draw import _attempt, _Draw, _lerp
from ..hardware import Bc250ApuPower, Bc250CpuTemp, Bc250GpuLoad, Bc250GpuTemp, gpu_clock_mhz
from ..splash import _Splash
from ..steam import _GameDisk


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


_Splash.STYLES["nixie"] = _NixieSplash
