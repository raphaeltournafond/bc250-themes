# SPDX-License-Identifier: GPL-3.0-or-later
"""Racing theme: the display of a single-seater's steering wheel."""

import math
import time
from typing import List, Optional

from ..draw import _attempt, _Draw, _lerp
from ..prompt import _Session
from ..readings import _Readings
from ..screen import Bc250Screen
from ..splash import _Screen, _Splash
from ..steam import _MangoHud


def _racing_led(d, x: int, y: int, r: int, fill):
    """A lit shift light (the unlit ones are on the background)."""
    d.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=_lerp(fill, (255, 255, 255), 0.45))
    d.point((x - r // 3, y - r // 3), fill=_lerp(fill, (255, 255, 255), 0.75))


class _Wheel:
    """The racing theme: a single-seater's wheel display. The shift lights follow the GPU's load like revs (green,
    red, then blue; all blue and flashing at the limiter), the gear follows the CPU's load and shifts one gear at a
    time (the revs drop on an upshift; N when nothing runs). The delta compares the FPS with the session's average,
    the lap time is the session's, the four tyres are coloured by their temperature (CPU, GPU, APU power, memory),
    and the throttle and ERS bars are the CPU load and the APU power."""
    LEDS = ("GREEN",) * 5 + ("RED",) * 5 + ("BLUE",) * 5
    frames = shifts = 0  # (read by the tests)

    def __init__(self, spec: dict, lcd, base):
        self.spec, self.lcd, self.base = spec, lcd, base
        self.dx, self.dy, self.dw, self.dh = (int(v) for v in spec["DASH"])
        self.dash = base.crop((self.dx, self.dy, self.dx + self.dw, self.dy + self.dh))
        self.col_ = {k: _Draw.color(v) for k, v in spec["COLORS"].items()}
        self.readings, self.r = _Readings(), {}
        self.next_read = 0.0
        self.rpm, self.gear, self.shifted = 0.0, 0, 0.0
        self.game, self.fps, self.fps_total, self.fps_count = None, None, 0.0, 0

    # -- what the car does -------------------------------------------------------------------------------------------
    def sample(self):
        self.r = self.readings.read()
        game = _Session.app_id
        if game != self.game:  # a new session: a new average
            self.game, self.fps_total, self.fps_count = game, 0.0, 0
        self.fps = _attempt("racing fps", _MangoHud.fps) if game else None
        if self.fps:
            self.fps_total, self.fps_count = self.fps_total + self.fps, self.fps_count + 1

    def revs(self) -> float:
        return max(0.0, min(1.0, (self.r.get("gpu") or 0.0) / 100))

    def wanted_gear(self) -> int:
        cpu, gpu = self.r.get("cpu") or 0.0, self.r.get("gpu") or 0.0
        if _Session.app_id is None and cpu < 5 and gpu < 5:
            return 0  # neutral
        return 1 + min(7, int(cpu / 12.5))

    def drive(self, now: float):
        """One frame: the revs move towards the GPU's load (with a little life), the gear shifts if it should."""
        import random
        target = self.revs()
        self.rpm += (target - self.rpm) * 0.3 + (random.uniform(-0.015, 0.015) if target > 0.05 else 0.0)
        self.rpm = max(0.0, min(1.0, self.rpm))
        wanted = self.wanted_gear()
        if wanted != self.gear and now - self.shifted >= 0.5:
            up = wanted > self.gear
            self.gear += 1 if up else -1
            self.shifted = now
            _Wheel.shifts += 1
            if up and self.gear > 1:
                self.rpm *= 0.72  # the revs drop as the next gear bites

    # -- the display -------------------------------------------------------------------------------------------------
    @staticmethod
    def heat(value, cold, hot, alert, col):
        if value is None:
            return col["DIM"]
        if value >= alert:
            return col["TYRE_ALERT"]
        if value < cold:
            return col["TYRE_COLD"]
        return _lerp(col["TYRE_OK"], col["TYRE_HOT"], max(0.0, min(1.0, (value - cold) / max(1.0, hot - cold))))

    def frame(self, now: float, revs: Optional[float] = None):
        """The display now (revs: the boot's light test)."""
        from PIL import ImageDraw
        spec, col, r = self.spec, self.col_, self.r
        image = self.dash.copy()
        d = ImageDraw.Draw(image)
        ox, oy = self.dx, self.dy
        font = lambda size: _Draw.font(spec["FONT"], size)
        limiter = revs is None and self.revs() >= 0.97
        lit = round((self.rpm if revs is None else revs) * len(spec["LEDS"]))
        radius = int(spec["LED_R"])
        for i, (x, y) in enumerate(spec["LEDS"]):
            if limiter:
                if int(now * 10) % 2 == 0:
                    _racing_led(d, int(x) - ox, int(y) - oy, radius, col["BLUE"])
            elif i < lit:
                _racing_led(d, int(x) - ox, int(y) - oy, radius, col[self.LEDS[i * len(self.LEDS) // len(spec["LEDS"])]])
        gx, gy = (int(v) for v in spec["GEAR"])
        gear = "N" if self.gear == 0 else str(self.gear)
        fill = col["BLUE"] if limiter else col["YELLOW"] if now - self.shifted < 0.25 else col["WHITE"]
        d.text((gx - ox, gy - oy), gear, font=font(int(spec["GEAR_SIZE"])), fill=fill, anchor="mm")

        def put(slot, words, fill):
            x, bl, size, anchor = spec["TEXTS"][slot]
            d.text((int(x) - ox, int(bl) - oy), words, font=font(int(size)), fill=fill, anchor=anchor)

        average = self.fps_total / self.fps_count if self.fps_count else None
        if self.fps and average:
            delta = self.fps - average
            put("DELTA", f"{delta:+.1f}", col["GREEN"] if delta >= 0 else col["RED"])
        else:
            put("DELTA", "--", col["DIM"])
        put("FPS", f"{self.fps:.0f}" if self.fps else "--", col["WHITE"] if self.fps else col["DIM"])
        lap = int(_Session.seconds) if _Session.app_id and _Session.seconds else None
        put("LAP", f"{lap // 3600}:{lap // 60 % 60:02d}:{lap % 60:02d}" if lap else "-:--:--",
            col["WHITE"] if lap else col["DIM"])
        for x, y, w, h, source, label in spec["TYRES"]:
            x, y, w, h = int(x) - ox, int(y) - oy, int(w), int(h)
            value = r.get(source)
            colour = self.heat(value, *spec["TYRE_SCALES"][source], col)
            d.rectangle((x, y, x + w - 1, y + h - 1), outline=colour, fill=_lerp(col["TYRE"], colour, 0.35))
            d.text((x + w // 2, y + 14), label, font=font(12), fill=col["WHITE"], anchor="ms")
            d.text((x + w // 2, y + h // 2 + 7), "--" if value is None else f"{min(999, round(value))}", font=font(24),
                   fill=col["WHITE"] if value is not None else col["DIM"], anchor="mm")
        for key, value, maximum, colour, words in (
                ("THR", r.get("cpu"), 100, col["GREEN"], "--" if r.get("cpu") is None else f"{round(r['cpu'])}%"),
                ("ERS", r.get("pwr"), float(spec.get("POWER_MAX", 250)), col["YELLOW"],
                 "--" if r.get("pwr") is None else f"{round(r['pwr'])}W")):
            segments, y1, y2 = spec["BARS"][key]
            filled = 0 if value is None else round(len(segments) * max(0.0, min(1.0, value / maximum)))
            for x1, x2 in segments[:filled]:
                d.rectangle((int(x1) - ox, int(y1) - oy, int(x2) - ox, int(y2) - oy), fill=colour)
            put(key, words, col["WHITE"] if value is not None else col["DIM"])
        return image

    def step(self):
        now = time.monotonic()
        if now >= self.next_read:
            self.sample()
            self.next_read = now + 1
        self.drive(now)
        self.lcd.DisplayPILImage(self.frame(now), self.dx, self.dy)
        _Wheel.frames += 1


class Bc250Racing:
    """Racing theme: starts the wheel display's thread (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        wheel = _Wheel(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            wheel.lcd = _Draw.screen  # shared with the other widgets: it knows what the screen shows
        else:
            import numpy
            wheel.lcd = _Screen(display.lcd, *wheel.base.size)
            wheel.lcd.shadow = numpy.asarray(wheel.base).copy()  # the app has just drawn the background
        wheel.lcd.TILE = int(spec.get("TILE", 10))
        frame = 1 / float(spec.get("FPS", 12))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                continue
            _attempt("racing frame", wheel.step)
            _Splash._wait(0)  # let the queue drain: the wheel never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Racing")
        if spec and _Draw.enabled and (Bc250Racing._thread is None or not Bc250Racing._thread.is_alive()):
            Bc250Racing._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 racing", daemon=True)
            Bc250Racing._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


_Splash.takes_over(Bc250Racing, "DASH")  # the wheel's display carries on


class _RacingSplash:
    """Racing boot, on the wheel itself: the radio check runs on the band under it while the shift lights test, one
    pair at a time; then the start lights come on one by one, hold, and go out. Race start: the wheel takes over."""
    STATUS = {"OK": ("OK", "GREEN"), "WAIT": ("WAIT", "YELLOW"), "WARN": ("FAIL", "RED"), "HOT!": ("HOT", "RED")}

    @classmethod
    def play(cls, lcd, spec: dict):
        import random
        from library import config
        from PIL import ImageDraw
        base = _Draw.background(spec.get("IMAGE", "background.png"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        wheel = _Wheel(spec, lcd, base)
        wheel.sample()  # (the first CPU and network readings only start the count)
        col = wheel.col_
        small, big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 24)
        x, y, w, h = (int(v) for v in spec["BAND"])
        label_bl, value_bl = int(spec["BAND_LABEL_BL"]), int(spec["BAND_VALUE_BL"])

        def band(label, value, word=None, key="DIM"):
            strip = base.crop((x, y, x + w, y + h))
            d = ImageDraw.Draw(strip)
            d.text((8, label_bl - y), label, font=small, fill=col["DIM"], anchor="ls")
            if word:
                d.text((w - 8, label_bl - y), word, font=small, fill=col[key], anchor="rs")
            d.text((8, value_bl - y), _Splash.fit(value, (w - 16) // 12), font=big, fill=col["WHITE"], anchor="ls")
            lcd.DisplayPILImage(strip, x, y)

        show = lambda image: lcd.DisplayPILImage(image, wheel.dx, wheel.dy)
        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)  # the one full frame (~2 s on a rev A), sent in the dark
        _Splash._animate(0.5, lambda p: lcd.SetBrightness(round(target * p)))

        # the radio check, the shift lights tested a little more at each line
        lines = _Splash.post_lines(spec)
        wheel.sample()
        for i, (label, value, status) in enumerate(lines):
            band(f"RADIO CHECK  {label}", value)
            show(wheel.frame(time.monotonic(), revs=(i + 1) / len(lines)))
            _Splash._wait(_Splash.STEP * 0.45)
            word, key = cls.STATUS.get(status, ("OK", "GREEN"))
            band(f"RADIO CHECK  {label}", value, word, key)
            _Splash._wait(_Splash.STEP * 0.3)
        show(wheel.frame(time.monotonic(), revs=0))

        # the start lights: on one by one, a hold nobody can guess, then out
        lights, radius = [[int(v) for v in p] for p in spec["START"]], int(spec["START_R"])
        px1, py1, px2, py2 = (int(v) for v in spec["START_PANEL"])
        band("FORMATION LAP COMPLETE", "ON THE GRID")

        def gantry(on: int):
            image = wheel.frame(time.monotonic(), revs=0)
            d = ImageDraw.Draw(image)
            d.rectangle((px1 - wheel.dx, py1 - wheel.dy, px2 - wheel.dx, py2 - wheel.dy), fill=col["PANEL"],
                        outline=col["DIM"])
            for n, (lx, ly) in enumerate(lights):
                box = (lx - radius - wheel.dx, ly - radius - wheel.dy, lx + radius - wheel.dx, ly + radius - wheel.dy)
                d.ellipse(box, fill=col["RED"] if n < on else col["LED_OFF"], outline=col["DIM"])
            show(image)

        for on in range(len(lights) + 1):
            gantry(on)
            _Splash._wait(0.4 if on < len(lights) else random.uniform(0.4, 0.9))
        gantry(0)
        band("LIGHTS OUT", "RACE START", "GO", "GREEN")
        _Splash._wait(0.25)
        show(wheel.frame(time.monotonic()))
        _Splash._wait(0.4)


_Splash.STYLES["racing"] = _RacingSplash
