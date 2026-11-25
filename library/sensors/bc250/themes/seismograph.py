# SPDX-License-Identifier: GPL-3.0-or-later
"""Seismograph theme: real earthquakes, written by a pen on a paper roll."""

import math
import os
import time
from typing import List

from ..base import _duration
from ..draw import _attempt, _Draw
from ..hardware import Bc250GpuLoad
from ..prompt import _Session
from ..screen import Bc250Screen
from ..splash import _Screen, _screen_level, _Splash
from ..steam import _Steam


class _QuakeFeed:
    """The world's earthquakes, from the USGS's public feeds (no key, updated every minute): the past day when it
    starts and every hour, the past hour every minute. It only reads a public list: nothing about this machine or its
    location is sent. Like the radar, it stops asking while the screen sleeps."""
    URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{tier}_{span}.geojson"
    AGENT = "bc250-themes"
    KEEP = 24 * 3600  # seconds
    FRESH = 3600  # a quake older than this that shows up late goes on the map, but isn't played
    quakes = {}  # id -> quake
    arrivals = []  # the ones still to be played
    fetched = None
    error = None
    _thread = None

    @staticmethod
    def tier(min_mag: float) -> str:
        return "1.0" if min_mag < 2.5 else "2.5" if min_mag < 4.5 else "4.5"

    @classmethod
    def _get(cls, url: str):
        import json
        import urllib.request
        fixture = os.environ.get("BC250_QUAKE_FIXTURE")  # tests and previews: a saved answer instead of the network
        if fixture:
            with open(fixture, encoding="utf-8") as f:
                raw = json.load(f)
            for feature in raw["features"]:  # its times count back from now
                if (feature["properties"].get("time") or 0) < 0:
                    feature["properties"]["time"] += time.time() * 1000
            return raw
        request = urllib.request.Request(url, headers={"User-Agent": cls.AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=15) as answer:
            return json.loads(answer.read().decode("utf-8"))

    @staticmethod
    def _parse(raw: dict, min_mag: float) -> List[dict]:
        quakes = []
        for feature in raw.get("features") or []:
            try:
                p = feature["properties"]
                lon, lat, depth = feature["geometry"]["coordinates"][:3]
                if p.get("type") != "earthquake" or p.get("mag") is None or p["mag"] < min_mag:
                    continue  # (the feed also lists quarry blasts and the like)
                quakes.append({"id": str(feature["id"]), "mag": float(p["mag"]), "place": p.get("place") or "unknown place",
                               "time": float(p["time"]) / 1000, "lat": float(lat), "lon": float(lon),
                               "depth": float(depth or 0)})
            except (KeyError, TypeError, ValueError):
                continue  # one odd entry must not lose the others
        return quakes

    @classmethod
    def ingest(cls, raw: dict, min_mag: float, first: bool = False):
        """Takes in an answer. The first one fills the map, and only its latest quake is played: the page shouldn't
        stay blank until the next one."""
        now = time.time()
        new = [q for q in cls._parse(raw, min_mag) if q["id"] not in cls.quakes]
        for quake in new:
            cls.quakes[quake["id"]] = quake
        if first:
            cls.arrivals = sorted(new, key=lambda q: q["time"])[-1:]
        else:
            cls.arrivals = (cls.arrivals + sorted((q for q in new if now - q["time"] < cls.FRESH),
                                                  key=lambda q: q["time"]))[-5:]
        for key in [k for k, q in cls.quakes.items() if now - q["time"] > cls.KEEP]:
            del cls.quakes[key]

    @classmethod
    def start(cls, min_mag: float):
        import threading
        if cls._thread is None or not cls._thread.is_alive():
            cls._thread = threading.Thread(target=cls._run, args=(min_mag,), name="BC250 quake feed", daemon=True)
            cls._thread.start()

    @classmethod
    def _run(cls, min_mag: float):
        tier, first, rounds = cls.tier(min_mag), True, 0
        while True:
            if Bc250Screen._mode == "off":
                time.sleep(5)
                continue
            span = "day" if first or rounds % 60 == 0 else "hour"
            try:
                cls.ingest(cls._get(cls.URL.format(tier=tier, span=span)), min_mag, first)
                cls.fetched, cls.error, first = time.time(), None, False
            except Exception as e:
                cls.error = str(e)
            rounds += 1
            time.sleep(60)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1.0, math.sqrt(h)))


def _short_place(place: str) -> str:
    """"78 km SSW of Neiafu, Tonga" -> "Neiafu, Tonga"."""
    return place.split(" of ", 1)[1] if " of " in place else place


class _Seismo:
    """The seismograph: a helicorder, the drum recorder observatories use. The paper stays still and the pen writes
    line after line across it, each line in another ink, so only the new ink has to reach the screen and what happened
    stays on the page. The pen trembles with what this machine is doing; a real earthquake from the feed throws it
    across the lines, with the shape a seismogram has (the small fast P waves, then the big S waves, then the long
    decay), writes its name beside it, puts it on the map, and from about magnitude 5.5 makes the backlight shake."""
    SHAKE_MAG, TREMBLE_MAG = 5.0, 5.5
    played = rows_started = 0  # (read by the tests)

    def __init__(self, spec: dict, lcd, base):
        self.spec, self.lcd, self.base = spec, lcd, base
        self.x, self.y, self.w, self.h = (int(v) for v in spec["PAPER"])
        self.rows, self.margin = int(spec["ROWS"]), int(spec["MARGIN"])
        self.row_h = self.h // self.rows
        self.blank = base.crop((self.x, self.y, self.x + self.w, self.y + self.h))
        self.paper = self.blank.copy()
        self.inks = [tuple(c) for c in spec["INKS"]]
        self.col_ = {k: _Draw.color(v) for k, v in spec["COLORS"].items()}
        self.small, self.big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 36)
        self.speed = float(os.environ.get("BC250_SEISMO_SPEED") or spec.get("SPEED", 2.5))  # pixels a second
        self.station = (float(spec["LAT"]), float(spec["LON"])) if "LAT" in spec else None
        self.row = -1
        self.active = None  # the quake being written: {"quake", "start": column count, "length", "height"}
        self.written = 0.0  # columns so far
        self.focus = None
        self.cpu = 0.0
        self.next_cpu = 0.0
        self.game = None
        self.last = time.monotonic()
        self.frame_no = 0
        self.next_row()

    # -- the paper ---------------------------------------------------------------------------------------------------
    def baseline(self) -> int:
        return self.row * self.row_h + self.row_h // 2

    def next_row(self):
        import datetime
        from PIL import ImageDraw
        self.row = (self.row + 1) % self.rows
        top = self.row * self.row_h
        self.paper.paste(self.blank.crop((0, top, self.w, top + self.row_h)), (0, top))  # the oldest line goes
        ImageDraw.Draw(self.paper).text((3, self.baseline() + 4), datetime.datetime.now().strftime("%H:%M"),
                                        font=self.small, fill=self.col_["PAPER_DIM"], anchor="ls")
        self.col = float(self.margin)
        self.pen_y = float(self.baseline())
        _Seismo.rows_started += 1

    def annotate(self, words: str, fill=(168, 34, 30)):
        """A note on the paper, by what the pen is writing."""
        from PIL import ImageDraw
        x = round(self.col) + 3
        room = (self.w - x) // 6
        if room < 6:
            return None
        note = (x, self.baseline() - 3, words[:room], fill)
        ImageDraw.Draw(self.paper).text(note[:2], note[2], font=self.small, fill=fill, anchor="ls")
        return note

    # -- what the pen feels ------------------------------------------------------------------------------------------
    def tremor(self) -> float:
        """This machine's own activity: a pen that barely moves when idle, and shakes under load."""
        import random
        gpu = Bc250GpuLoad.value
        gpu = gpu if isinstance(gpu, (int, float)) and gpu == gpu else 0.0
        size = 0.6 + 0.03 * self.cpu + 0.04 * gpu  # stays within its line: a real quake has to stand out
        return random.uniform(-size, size)

    def quake_signal(self):
        """The quake's waves at this point of the paper, and how far along it is (None when it is over)."""
        import random
        if not self.active:
            return 0.0, None
        p = (self.written - self.active["start"]) / self.active["length"]
        if p >= 1:
            note = self.active.get("note")
            if note:  # written again over the waves, on a clean patch, so that it can be read
                from PIL import ImageDraw
                d = ImageDraw.Draw(self.paper)
                x, y, words, fill = note
                d.rectangle((x - 1, y - 10, x + round(self.small.getlength(words)) + 1, y + 2), fill=(238, 230, 208))
                d.text((x, y), words, font=self.small, fill=fill, anchor="ls")
            self.active = None
            _screen_level(self.lcd, 1)
            return 0.0, None
        height = self.active["height"]
        if p < 0.14:  # P waves: small and fast
            envelope = 0.22 * (0.4 + p / 0.14 * 0.6)
        elif p < 0.26:
            envelope = 0.22 + 0.5 * (p - 0.14)
        elif p < 0.34:  # S waves arrive
            envelope = 0.28 + 0.72 * (p - 0.26) / 0.08
        else:  # and it dies away
            envelope = math.exp(-(p - 0.34) * 4.2)
        return random.uniform(-1, 1) * height * envelope, p

    def play_next(self):
        if self.active or not _QuakeFeed.arrivals:
            return
        quake = _QuakeFeed.arrivals.pop(0)
        mag = quake["mag"]
        self.active = {"quake": quake, "start": self.written, "length": max(10.0, (6 + (mag - 2.5) * 10) * 2.5),
                       "height": min(90.0, max(3.0, 5 * 2 ** ((mag - 2.5) / 0.9 * 0.8)))}
        self.focus = quake
        self.active["note"] = self.annotate(f"M{mag:.1f} {_short_place(quake['place'])}")
        _Seismo.played += 1

    def notice_game(self):
        """A game starting is an event of this machine's own: noted on the paper too."""
        game = _attempt("seismograph game", _Steam.current_game)
        key = game[0] if game else None
        if key != self.game:
            self.game = key
            if key:
                self.annotate(_Session.name or _Steam.app_name(key), self.inks[self.row % len(self.inks)])

    def write(self, seconds: float):
        import random
        from PIL import ImageDraw
        d = ImageDraw.Draw(self.paper)
        advance = seconds * self.speed
        samples = max(1, math.ceil(advance))
        ink = self.inks[self.row % len(self.inks)]
        for _ in range(samples):
            self.col += advance / samples
            self.written += advance / samples
            if self.col >= self.w - 2:
                self.next_row()
                d = ImageDraw.Draw(self.paper)
                ink = self.inks[self.row % len(self.inks)]
            wave, _p = self.quake_signal()
            y = self.baseline() + self.tremor() + wave
            d.line((round(self.col), round(self.pen_y), round(self.col), round(y)), fill=ink)
            self.pen_y = y
        if self.active:
            p = (self.written - self.active["start"]) / self.active["length"]
            if self.active["quake"]["mag"] >= self.TREMBLE_MAG and 0.26 < p < 0.75:
                _screen_level(self.lcd, 1 + random.uniform(-0.3, 0.3))  # the whole screen, for one small command

    def paper_frame(self):
        from PIL import ImageDraw
        frame = self.paper.copy()
        d = ImageDraw.Draw(frame)
        x, y = round(self.col), round(self.pen_y)
        d.line((x, y, x + 9, max(0, y - 15)), fill=(70, 62, 46), width=2)  # the pen's arm
        d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(150, 30, 26))
        return frame

    # -- what is around it -------------------------------------------------------------------------------------------
    def shake(self):
        """How far things are thrown right now."""
        import random
        if not self.active or self.active["quake"]["mag"] < self.SHAKE_MAG:
            return 0, 0
        p = (self.written - self.active["start"]) / self.active["length"]
        if not 0.26 < p < 0.7:
            return 0, 0
        size = 3 if self.active["quake"]["mag"] >= 6.5 else 2
        return random.randint(-size, size), random.randint(-1, 1)

    def latest(self):
        quakes = list(_QuakeFeed.quakes.values())
        return max(quakes, key=lambda q: q["time"]) if quakes else None

    def card(self):
        from PIL import ImageDraw
        x, y, w, h = (int(v) for v in self.spec["CARD"])
        box = (x, y + 14, x + w, y + h)
        strip = self.base.crop(box)
        d = ImageDraw.Draw(strip)
        quake = self.focus or self.latest()
        dx, dy = self.shake()
        top = box[1]
        if quake is None:
            words = "NO ANSWER FROM USGS" if _QuakeFeed.error else "LISTENING..."
            d.text((2, y + 34 - top), words[:w // 6], font=self.small, fill=self.col_["RED" if _QuakeFeed.error else "DIM"], anchor="ls")
        else:
            mag = quake["mag"]
            fill = self.col_["RED"] if mag >= 6 else self.col_["AMBER"] if mag >= 4.5 else self.col_["BRIGHT"]
            d.text((2 + dx, y + 44 - top + dy), f"M{mag:.1f}", font=self.big, fill=fill, anchor="ls")
            d.text((w - 2 + dx, y + 28 - top + dy), f"{quake['depth']:.0f} KM", font=self.small, fill=self.col_["MID"], anchor="rs")
            d.text((w - 2 + dx, y + 42 - top + dy), "DEEP", font=self.small, fill=self.col_["DIM"], anchor="rs")
            lines, line, chars = [], "", w // 6
            for word in _short_place(quake["place"]).split():
                if len(line) + len(word) + 1 > chars and line:
                    lines.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            lines.append(line)
            for n, words in enumerate(lines[:2]):
                d.text((2 + dx, y + 56 + 13 * n - top + dy), words[:chars], font=self.small, fill=self.col_["BRIGHT"], anchor="ls")
            ago = _duration(max(0, time.time() - quake["time"]))
            if self.station:
                far = _distance_km(self.station[0], self.station[1], quake["lat"], quake["lon"])
                note = f"{far:,.0f} KM AWAY  {ago}".replace(",", " ")
            else:
                note = f"{ago} AGO"
            d.text((2 + dx, y + 82 - top + dy), note[:chars], font=self.small, fill=self.col_["MID"], anchor="ls")
        self.lcd.DisplayPILImage(strip, box[0], box[1])
        # how long ago, beside the heading
        return quake

    def world(self):
        from PIL import ImageDraw
        x, y, w, h = (int(v) for v in self.spec["MAP"])
        frame = self.base.crop((x, y, x + w, y + h))
        d = ImageDraw.Draw(frame)
        now = time.time()
        project = lambda lon, lat: ((lon + 180) / 360 * w, (90 - lat) / 180 * h)
        focus = self.focus or self.latest()
        for quake in sorted(_QuakeFeed.quakes.values(), key=lambda q: q["time"]):
            px, py = project(quake["lon"], quake["lat"])
            size = 1 if quake["mag"] < 4.5 else 2 if quake["mag"] < 6 else 3
            fill = self.col_["RED"] if now - quake["time"] < 3600 else self.col_["AMBER"]
            d.ellipse((px - size, py - size, px + size, py + size), fill=fill)
        if focus:  # the one on the card: waves spreading from it
            px, py = project(focus["lon"], focus["lat"])
            radius = 3 + (self.frame_no // 2) % 8
            d.ellipse((px - radius, py - radius, px + radius, py + radius), outline=self.col_["RED"])
        if self.station:
            px, py = project(self.station[1], self.station[0])
            d.line((px - 2, py, px + 2, py), fill=self.col_["BRIGHT"])
            d.line((px, py - 2, px, py + 2), fill=self.col_["BRIGHT"])
        self.lcd.DisplayPILImage(frame, x, y)

    def header(self):
        from PIL import ImageDraw
        x, bl, xr = (int(v) for v in self.spec["HEADER"])
        if xr <= x:
            return
        box = (x, bl - 11, xr, bl + 3)
        strip = self.base.crop(box)
        quakes = list(_QuakeFeed.quakes.values())
        chars = (xr - x) // 6
        if _QuakeFeed.error and not quakes:
            words, fill = "NO ANSWER FROM USGS", self.col_["RED"]
        elif quakes:
            top = max(q["mag"] for q in quakes)
            words = f"{len(quakes)} QUAKES IN 24 H, LARGEST M{top:.1f}"
            words = words if len(words) <= chars else f"{len(quakes)} IN 24H, MAX M{top:.1f}"
            fill = self.col_["DIM"]
        else:
            words, fill = "LISTENING...", self.col_["DIM"]
        ImageDraw.Draw(strip).text((0, bl - box[1]), words[:chars], font=self.small, fill=fill, anchor="ls")
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    def step(self):
        import psutil
        now = time.monotonic()
        seconds, self.last = now - self.last, now
        if now >= self.next_cpu:
            self.next_cpu = now + 1
            self.cpu = _attempt("seismograph load", lambda: psutil.cpu_percent(None)) or 0.0
            self.notice_game()
        self.play_next()
        self.write(min(seconds, 2.0))
        self.lcd.DisplayPILImage(self.paper_frame(), self.x, self.y)
        self.frame_no += 1
        shaking = self.shake() != (0, 0)
        if shaking or self.frame_no % 4 == 0:
            self.card()
            self.world()
        if self.frame_no % 16 == 1:
            self.header()


class Bc250Seismograph:
    """Seismograph theme: starts the feed and the pen's thread (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        pen = _Seismo(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            pen.lcd = _Draw.screen  # shared with the other widgets: it knows the screen shows the background
        else:
            import numpy
            pen.lcd = _Screen(display.lcd, *pen.base.size)
            pen.lcd.shadow = numpy.asarray(pen.base).copy()  # the app has just drawn the background
        pen.lcd.TILE = int(spec.get("TILE", 10))
        frame = 1 / float(spec.get("FPS", 8))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                pen.last = time.monotonic()  # the paper doesn't turn while the screen sleeps
                continue
            _attempt("seismograph frame", pen.step)
            _Splash._wait(0)  # let the queue drain: the pen never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Seismograph")
        if spec and _Draw.enabled:
            _QuakeFeed.start(float(spec.get("MIN_MAG", 2.5)))
            if Bc250Seismograph._thread is None or not Bc250Seismograph._thread.is_alive():
                Bc250Seismograph._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 seismograph",
                                                            daemon=True)
                Bc250Seismograph._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


class _SeismographSplash:
    """Seismograph boot, on the dashboard's own paper: the station's log is typed on it, the feed is contacted, the
    instrument draws the calibration pulses every real seismogram starts with, then the sheet is changed and the pen
    takes over at once. Only the ink has to be sent."""
    STATUS = {"OK": ("OK", (26, 104, 62)), "WAIT": ("WAIT", (168, 110, 10)), "WARN": ("FAIL", (168, 34, 30)),
              "HOT!": ("HOT", (168, 34, 30))}
    INK, FAINT = (28, 30, 40), (150, 140, 118)

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import ImageDraw
        base = _Draw.background(spec.get("IMAGE", "background.png"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        small = _Draw.font(spec["FONT"], 12)
        px, py, pw, ph = (int(v) for v in spec["PAPER"])
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))
        _QuakeFeed.start(float(spec.get("MIN_MAG", 2.5)))

        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)  # the one full frame (~2 s on a rev A), sent in the dark
        _Splash._animate(0.5, lambda p: lcd.SetBrightness(round(target * p)))

        def row(index, label, value, word=None, fill=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (label_x, baseline - 11, status_xr, baseline + 3)
            strip = base.crop(box)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((0, oy), label, font=small, fill=cls.FAINT, anchor="ls")
            d.text((value_x - label_x, oy), _Splash.fit(value, chars), font=small, fill=cls.INK, anchor="ls")
            d.text((status_xr - label_x, oy), word or "...", font=small, fill=fill or cls.FAINT, anchor="rs")
            lcd.DisplayPILImage(strip, box[0], box[1])

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value)
            _Splash._wait(_Splash.STEP * 0.5)
            word, fill = cls.STATUS.get(status, ("OK", cls.STATUS["OK"][1]))
            row(i, label, value, word, fill)
            _Splash._wait(_Splash.STEP * 0.4)

        # the feed (a few seconds at most for its first answer)
        n = len(lines)
        row(n, "USGS", "contacting the feed")
        deadline = time.monotonic() + 3
        while _QuakeFeed.fetched is None and _QuakeFeed.error is None and time.monotonic() < deadline:
            _Splash._wait(0.1)
        if _QuakeFeed.fetched:
            row(n, "USGS", f"{len(_QuakeFeed.quakes)} quakes in the past day", "OK", cls.STATUS["OK"][1])
        else:
            row(n, "USGS", "no answer yet, still listening", "WAIT", cls.STATUS["WAIT"][1])
        _Splash._wait(0.25)

        # the calibration pulses, at the foot of the paper
        y = py + ph - 8
        x0 = px + int(spec.get("MARGIN", 36))
        width = min(180, pw - int(spec.get("MARGIN", 36)) - 8)
        box = (x0, y - 8, x0 + width, y + 2)

        def calibrate(p):
            strip = base.crop(box)
            d = ImageDraw.Draw(strip)
            points, drawn = [(0, 8)], round(width * p)
            for x in range(0, drawn, 30):
                points += [(x, 8), (x, 1), (min(drawn, x + 15), 1), (min(drawn, x + 15), 8), (min(drawn, x + 30), 8)]
            d.line(points, fill=cls.INK)
            lcd.DisplayPILImage(strip, box[0], box[1])

        _Splash._animate(0.7, calibrate)
        _Splash._wait(0.5)


_Splash.STYLES["seismograph"] = _SeismographSplash
