# SPDX-License-Identifier: GPL-3.0-or-later
"""Halloween theme: its boot."""

import math
import time

from ..draw import _attempt, _Draw
from ..splash import _Splash


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


_Splash.STYLES["halloween"] = _HalloweenSplash
