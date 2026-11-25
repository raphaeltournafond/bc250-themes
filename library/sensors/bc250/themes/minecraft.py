# SPDX-License-Identifier: GPL-3.0-or-later
"""Minecraft theme: its boot."""

import math
import time

from ..draw import _Draw
from ..splash import _Splash


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


_Splash.STYLES["minecraft"] = _MinecraftSplash
