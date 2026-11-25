# SPDX-License-Identifier: GPL-3.0-or-later
"""Game Boy theme: its boot."""

from ..draw import _Draw
from ..splash import _Splash


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


_Splash.STYLES["gameboy"] = _GameBoySplash
