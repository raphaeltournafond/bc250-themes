# SPDX-License-Identifier: GPL-3.0-or-later
"""Videotex (Minitel) theme: its boot."""

import re

from ..draw import _Draw
from ..splash import _Splash


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


_Splash.STYLES["videotex"] = _VideotexSplash
