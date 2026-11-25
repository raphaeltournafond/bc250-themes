# SPDX-License-Identifier: GPL-3.0-or-later
"""Retrowave theme: its boot."""

import math
import time

from ..draw import _dim, _Draw, _lerp
from ..splash import _Splash


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


_Splash.STYLES["retrowave"] = _RetrowaveSplash
