# SPDX-License-Identifier: GPL-3.0-or-later
"""Mission Control theme: mission elapsed time, and its boot."""

import math
import time
from typing import List

from ..draw import _Draw
from ..splash import _Splash


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


_Splash.STYLES["mission"] = _MissionSplash
