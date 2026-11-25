# SPDX-License-Identifier: GPL-3.0-or-later
"""Departures theme: a split-flap station board."""

import math
import time
from typing import List

from ..draw import _attempt, _Draw
from ..readings import _Readings
from ..screen import Bc250Screen
from ..splash import _Screen, _Splash


def _flap(d, x: int, y: int, w: int, h: int, colors):
    """One blank flap, drawn the same way on the background by make_theme.py: a lighter upper leaf, the lower one,
    rounded corners. colors: (upper, lower, hinge, board)."""
    upper, lower, _, board = colors
    d.rectangle((x, y, x + w - 1, y + h // 2 - 1), fill=upper)
    d.rectangle((x, y + h // 2, x + w - 1, y + h - 1), fill=lower)
    for cx, cy in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
        d.point((cx, cy), fill=board)


def _flap_hinge(d, x: int, y: int, w: int, h: int, colors):
    """The gap between the two leaves, across the letter too."""
    d.line((x, y + h // 2, x + w - 1, y + h // 2), fill=colors[2])


class _FlapBoard:
    """A split-flap board: every cell is a drum of flaps that can only turn forward, one letter after the other, so
    going from 3 to 7 shows 4, 5 and 6 on the way; each flip shows the new letter's upper half over the old one's lower
    half first. Cells turn independently, a little apart, which gives the board its cascade. Only the cells that change
    reach the screen (the board is sent through the changed-pixels sender)."""
    DRUM = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.'-/:%°"
    FRAME = 0.05  # seconds per half flip
    flips = 0  # (read by the tests)
    shared = None  # the board the boot leaves: the dashboard carries on from it

    def __init__(self, spec: dict, lcd, base):
        self.spec, self.lcd, self.base = spec, lcd, base
        self.bx, self.by, self.bw, self.bh = (int(v) for v in spec["BOARD"])
        self.image = base.crop((self.bx, self.by, self.bx + self.bw, self.by + self.bh))
        colors = spec["COLORS"]
        self.flap_colors = tuple(_Draw.color(colors[k]) for k in ("FLAP_TOP", "FLAP_BOTTOM", "HINGE", "BOARD"))
        self.cells = {}  # (x, y) -> {"char", "fill", "geometry", "queue": [phase...], "due"}
        self._glyphs = {}
        self.dirty = False

    @classmethod
    def letter(cls, char: str) -> str:
        """What a flap can show: capitals without accents, digits and a few signs."""
        import unicodedata
        char = unicodedata.normalize("NFD", char.upper())[:1] or " "
        return char if char in cls.DRUM else " "

    def glyph(self, char: str, fill, w: int, h: int, size: int):
        key = (char, fill, w, h, size)
        if key not in self._glyphs:
            from PIL import Image, ImageDraw
            image = Image.new("RGB", (w, h), self.flap_colors[3])
            d = ImageDraw.Draw(image)
            _flap(d, 0, 0, w, h, self.flap_colors)
            if char.strip():
                d.text((w // 2, h // 2), char, font=_Draw.font(self.spec["FONT"], size), fill=fill, anchor="mm")
            _flap_hinge(d, 0, 0, w, h, self.flap_colors)
            self._glyphs[key] = image
        return self._glyphs[key]

    def write(self, xs, y: int, geometry, text: str, fill, steps: int = 4, spread: float = 0.25):
        """Turns the cells at xs (on the row at y) to text. A cell goes through at most `steps` letters to get there
        (the last ones before it on the drum), and starts within `spread` seconds of the others."""
        import random
        now, n = time.monotonic(), len(self.DRUM)
        text = text.ljust(len(xs))[:len(xs)]
        for x, char in zip(xs, text):
            char = self.letter(char)
            cell = self.cells.setdefault((int(x), int(y)), {"char": " ", "fill": fill, "queue": [], "due": 0.0})
            cell["geometry"] = geometry
            last_char, last_fill = (cell["queue"][-1][1], cell["queue"][-1][3]) if cell["queue"] else \
                (cell["char"], cell["fill"])
            if (last_char, last_fill) == (char, fill):
                continue
            i, j = self.DRUM.index(last_char), self.DRUM.index(char)
            path = [self.DRUM[(i + k) % n] for k in range(1, (j - i) % n + 1)][-steps:] or [char]
            if not cell["queue"]:
                cell["due"] = now + random.uniform(0, spread)
            previous, previous_fill = last_char, last_fill
            for step in path:
                cell["queue"] += [("half", step, previous, fill, previous_fill), ("full", step, None, fill, None)]
                previous, previous_fill = step, fill

    def tick(self, now: float) -> bool:
        """Turns every cell whose next half flip is due; whether any cell still has flaps to turn."""
        busy = False
        for (x, y), cell in self.cells.items():
            if not cell["queue"]:
                continue
            busy = True
            if now < cell["due"]:
                continue
            kind, char, previous, fill, previous_fill = cell["queue"].pop(0)
            w, h, size = cell["geometry"]
            image = self.glyph(char, fill, w, h, size)
            if kind == "half":
                image = image.copy()
                image.paste(self.glyph(previous, previous_fill, w, h, size).crop((0, h // 2, w, h)), (0, h // 2))
            else:
                cell["char"], cell["fill"] = char, fill
                _FlapBoard.flips += 1
            self.image.paste(image, (x - self.bx, y - self.by))
            cell["due"] = now + self.FRAME
            self.dirty = True
        return busy

    def send(self):
        if self.dirty:
            self.lcd.DisplayPILImage(self.image, self.bx, self.by)
            self.dirty = False

    def settle(self, seconds: float, limit: float = 4.0):
        """The boot: keeps turning for `seconds`, and on until every cell has stopped (`limit` at most)."""
        start = time.monotonic()
        while True:
            now = time.monotonic()
            busy = self.tick(now)
            self.send()
            _Splash._wait(0)
            if (not busy and now - start >= seconds) or now - start >= limit:
                return
            time.sleep(self.FRAME)


class _Departures:
    """The departures theme: one train per part of the machine, its load and its other reading, and the remark a
    station gives: A L'HEURE, RETARD 4' when it runs hot (a minute per degree), SUPPRIME at the alert temperature,
    AFFLUENCE and COMPLET when the memory or the disk fill up, EN ROUTE while data comes in. The clock is flaps too."""
    TRAINS = ("CPU", "GPU", "APU", "RAM", "SSD", "NET")

    def __init__(self, spec: dict, board: _FlapBoard):
        self.spec, self.board = spec, board
        self.col_ = {k: _Draw.color(v) for k, v in spec["COLORS"].items()}
        self.readings = _Readings().read

    # -- what the flaps say ------------------------------------------------------------------------------------------
    @staticmethod
    def percent(v):
        return "--" if v is None else f"{max(0, min(100, round(v)))}%"

    @staticmethod
    def degrees(v):
        return "--" if v is None else f"{round(v)}°C" if v < 99.5 else f"{min(999, round(v))}°"

    @staticmethod
    def amount(v, units=("G", "T")):
        """4 characters at most: 7.9G, 724G, 1.2T."""
        if v is None:
            return "--"
        for unit in units:
            if v < 9.95:
                return f"{v:.1f}{unit}"
            if v < 999.5 or unit == units[-1]:
                return f"{min(999, round(v))}{unit}"
            v /= 1000
        return "--"

    def rows(self, r: dict) -> List[tuple]:
        """(train, load, other reading, remark, remark colour) for each row."""
        hot, alert = float(self.spec.get("HOT", 70)), float(self.spec.get("ALERT", 80))

        def heat(t):
            if t is None:
                return "SANS INFO", "DIM"
            if t >= alert:
                return "SUPPRIME", "RED"
            if t >= hot:
                return f"RETARD {min(9, max(1, math.ceil(t - hot)))}'", "ORANGE"
            return "A L'HEURE", "INFO"

        def level(v, busy, full, busy_word="AFFLUENCE"):
            if v is None:
                return "SANS INFO", "DIM"
            return ("COMPLET", "ORANGE") if v >= full else (busy_word, "ORANGE") if v >= busy else ("A L'HEURE", "INFO")

        power = r["pwr"]
        free = r["ssd_free"]
        return [
            ("CPU", self.percent(r["cpu"]), self.degrees(r["cpu_t"]), *heat(r["cpu_t"])),
            ("GPU", self.percent(r["gpu"]), self.degrees(r["gpu_t"]), *heat(r["gpu_t"])),
            ("APU", "--" if power is None else f"{min(999, round(power))}W",
             "--" if r["clk"] is None else f"{min(9999, round(r['clk']))}",
             *(("SANS INFO", "DIM") if power is None else ("RETARD", "ORANGE")
               if power >= float(self.spec.get("POWER_HIGH", 200)) else ("A L'HEURE", "INFO"))),
            ("RAM", self.percent(r["ram"]), self.amount(r["ram_gb"]), *level(r["ram"], 80, 92)),
            ("SSD", self.percent(r["ssd"]), self.amount(free),
             *(("SANS INFO", "DIM") if free is None else ("COMPLET", "ORANGE") if free < 50 else ("A L'HEURE", "INFO"))),
            ("NET", self.amount(r["rx"], ("B", "K", "M", "G")), self.amount(r["tx"], ("B", "K", "M", "G")),
             *(("SANS INFO", "DIM") if r["rx"] is None else ("EN ROUTE", "INFO") if r["rx"] > 500_000
               else ("A QUAI", "INFO"))),
        ]

    def write_row(self, index: int, row: tuple, steps: int = 4, spread: float = 0.3):
        y, columns = int(self.spec["ROW_YS"][index]), self.spec["COLUMNS"]
        geometry = tuple(int(v) for v in self.spec["CELL"])
        train, load, other, remark, colour = row
        for key, words, fill, right in (("TRAIN", train, "TRAIN", False), ("LOAD", load, "TEXT", True),
                                        ("OTHER", other, "TEXT", True), ("REMARK", remark, colour, False)):
            xs = columns[key]
            self.board.write(xs, y, geometry, words.rjust(len(xs)) if right else words, self.col_[fill], steps, spread)

    def clock(self, steps: int = 4):
        spec = self.spec["CLOCK"]
        self.board.write(spec["XS"], int(spec["Y"]), (int(spec["W"]), int(spec["H"]), int(spec["SIZE"])),
                         time.strftime("%H%M"), self.col_["TEXT"], steps, 0.1)

    def update(self, steps: int = 4):
        for index, row in enumerate(self.rows(self.readings())):
            self.write_row(index, row, steps)
        self.clock(steps)


class Bc250Departures:
    """Departures theme: starts the board's thread (once), from its theme.yaml entry. The readings come from the other
    BC-250 widgets listed before it (sampled by the app), psutil and sysfs."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        board = _FlapBoard.shared
        if board is None or _Draw.screen is None or board.lcd is not _Draw.screen:  # no boot to carry on from
            board = _FlapBoard(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
            if _Draw.screen is not None:
                board.lcd = _Draw.screen
            else:
                import numpy
                board.lcd = _Screen(display.lcd, *board.base.size)
                board.lcd.shadow = numpy.asarray(board.base).copy()  # the app has just drawn the background
            _FlapBoard.shared = board
        board.lcd.TILE = int(spec.get("TILE", 10))
        departures, due = _Departures(spec, board), 0.0
        while True:
            if Bc250Screen._mode == "off":
                time.sleep(1)
                continue
            now = time.monotonic()
            if now >= due:
                _attempt("departures update", departures.update)
                due = now + float(spec.get("REFRESH", 2))
            busy = _attempt("departures frame", lambda: board.tick(time.monotonic()), False)
            _attempt("departures send", board.send)
            _Splash._wait(0)  # let the queue drain: the flaps never hold up the other widgets
            time.sleep(board.FRAME if busy else 0.2)

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Departures")
        if spec and _Draw.enabled and (Bc250Departures._thread is None or not Bc250Departures._thread.is_alive()):
            Bc250Departures._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 departures",
                                                       daemon=True)
            Bc250Departures._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


_Splash.takes_over(Bc250Departures, "BOARD", kept=lambda: _FlapBoard.shared is not None)  # flaps keep turning


class _DeparturesSplash:
    """Departures boot, on the board itself: the clock turns to the time, then the station's checks run on the LED band
    under the board while the trains come up one row after the other, every cell turning to its first reading. The
    board stays as it is: the dashboard carries on turning from there."""
    STATUS = {"OK": ("OK", "LED"), "WAIT": ("ATTENTE", "LED_DIM"), "WARN": ("PANNE", "RED"), "HOT!": ("CHAUD", "RED")}

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import ImageDraw
        base = _Draw.background(spec.get("IMAGE", "background.png"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        board = _FlapBoard(spec, lcd, base)
        departures = _Departures(spec, board)
        departures.readings()  # (the first CPU and network readings only start the count)
        col = departures.col_
        small, big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 24)
        x, y, w, h = (int(v) for v in spec["LED"])
        label_bl, value_bl = int(spec["LED_LABEL_BL"]), int(spec["LED_VALUE_BL"])

        def led(label, value, word=None, key="LED_DIM"):
            strip = base.crop((x, y, x + w, y + h))
            d = ImageDraw.Draw(strip)
            d.text((8, label_bl - y), label, font=small, fill=col["LED_DIM"], anchor="ls")
            if word:
                d.text((w - 8, label_bl - y), word, font=small, fill=col[key], anchor="rs")
            d.text((8, value_bl - y), _Splash.fit(value, (w - 16) // 12), font=big, fill=col["LED"], anchor="ls")
            lcd.DisplayPILImage(strip, x, y)

        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)  # the one full frame (~2 s on a rev A), sent in the dark: the board, blank
        _Splash._animate(0.5, lambda p: lcd.SetBrightness(round(target * p)))
        departures.clock(steps=3)
        board.settle(0.3)

        lines = _Splash.post_lines(spec)
        rows = departures.rows(departures.readings())
        for i, (label, value, status) in enumerate(lines):
            led(f"CONTRÔLE {label}", value)
            if i < len(rows):
                departures.write_row(i, rows[i], steps=3, spread=0.15)
            board.settle(_Splash.STEP * 0.9)
            word, key = cls.STATUS.get(status, ("OK", "LED"))
            led(f"CONTRÔLE {label}", value, word, key)
            board.settle(_Splash.STEP * 0.3)
        led("MISE EN SERVICE TERMINÉE", f"{spec.get('LOGO_TEXT', 'BC-250')}  BON VOYAGE", "OK", "LED")
        board.settle(0.6)
        _FlapBoard.shared = board


_Splash.STYLES["departures"] = _DeparturesSplash
