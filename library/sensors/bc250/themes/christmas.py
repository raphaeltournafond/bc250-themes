# SPDX-License-Identifier: GPL-3.0-or-later
"""Christmas theme: its boot."""

import math
import time

from ..draw import _attempt, _Draw
from ..splash import _Splash


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


_Splash.STYLES["christmas"] = _ChristmasSplash
