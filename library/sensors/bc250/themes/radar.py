# SPDX-License-Identifier: GPL-3.0-or-later
"""Radar theme: live aircraft from free community ADS-B APIs around a point, on a radar scope."""

import math
import os
import re
import time
from typing import List

from ..base import _compass
from ..draw import _attempt, _Draw, _lerp
from ..screen import Bc250Screen
from ..splash import _Screen, _Splash


def _km_per_deg(lat: float):
    """(km per degree of longitude, km per degree of latitude) around a latitude."""
    return 111.32 * math.cos(math.radians(lat)), 110.57


class _RadarFeed:
    """Polls the aircraft around the radar's centre in a thread of its own (a slow or failing API must never hold
    up the screen): adsb.lol, then adsb.fi if it fails. Flight routes come from adsbdb, looked up once per callsign
    and only kept when they make sense for where the aircraft is. Paused while the screen is off."""
    SOURCES = (("adsb.lol", "https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{nm:.0f}"),
               ("adsb.fi", "https://opendata.adsb.fi/api/v2/lat/{lat:.4f}/lon/{lon:.4f}/dist/{nm:.0f}"))
    ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
    AGENT = "bc250-themes radar (turing-smart-screen-python theme)"
    aircraft: List[dict] = []
    fetched = None  # time.time() of the last good answer
    source = None
    error = None
    routes = {}  # callsign -> route dict or None (looked up, nothing usable)
    _thread = None
    _want_routes: List[dict] = []

    @classmethod
    def start(cls, lat: float, lon: float, km: float, refresh: float):
        import threading
        if cls._thread is None or not cls._thread.is_alive():
            cls._thread = threading.Thread(target=cls._run, args=(lat, lon, km, refresh), name="BC250 radar feed",
                                           daemon=True)
            cls._thread.start()

    @classmethod
    def _get(cls, url: str):
        import json
        import urllib.request
        fixture = os.environ.get("BC250_RADAR_FIXTURE")  # tests and previews: a saved answer instead of the network
        if fixture:
            if "adsbdb" in url:
                routes = os.environ.get("BC250_RADAR_ROUTES")
                data = json.load(open(routes, encoding="utf-8")) if routes else {}
                return {"response": data.get(url.rsplit("/", 1)[-1], "unknown callsign")}
            with open(fixture, encoding="utf-8") as f:
                return json.load(f)
        request = urllib.request.Request(url, headers={"User-Agent": cls.AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=8) as answer:
            return json.loads(answer.read().decode("utf-8"))

    @staticmethod
    def _parse(raw: dict, lat0: float, lon0: float) -> List[dict]:
        kx, ky = _km_per_deg(lat0)
        now = time.time()
        planes = []
        for a in raw.get("ac") or raw.get("aircraft") or []:
            alt = a.get("alt_baro", a.get("alt_geom"))
            if a.get("lat") is None or a.get("lon") is None or alt in (None, "ground"):
                continue  # no position, or taxiing: not shown
            seen = float(a.get("seen_pos", a.get("seen", 0)) or 0)
            if seen > 30:
                continue
            planes.append({
                "hex": a.get("hex", "?"),
                "callsign": (a.get("flight") or "").strip() or a.get("r") or a.get("hex", "?").upper(),
                "registration": a.get("r") or "", "type": a.get("t") or "",
                "alt": int(alt), "gs": float(a.get("gs") or 0), "track": float(a.get("track") or 0),
                "rate": float(a.get("baro_rate") or a.get("geom_rate") or 0), "squawk": a.get("squawk") or "",
                "x": (float(a["lon"]) - lon0) * kx, "y": (float(a["lat"]) - lat0) * ky, "time": now - seen,
            })
        return planes

    @staticmethod
    def _plausible(route: dict, plane: dict, lat0: float, lon0: float) -> bool:
        """Community route data can be stale: keep it only if the aircraft is near one end of it or near its path."""
        kx, ky = _km_per_deg(lat0)
        try:
            ends = [((float(p["longitude"]) - lon0) * kx, (float(p["latitude"]) - lat0) * ky)
                    for p in (route["origin"], route["destination"])]
        except (KeyError, TypeError, ValueError):
            return False
        (ax, ay), (bx, by), (px, py) = ends[0], ends[1], (plane["x"], plane["y"])
        near_end = min(math.hypot(px - ax, py - ay), math.hypot(px - bx, py - by)) < 80
        length = math.hypot(bx - ax, by - ay)
        if length < 1:
            return near_end
        t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length ** 2))
        off_path = math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)))
        return near_end or off_path < 250

    @classmethod
    def _route(cls, plane: dict, lat0: float, lon0: float):
        callsign = plane["callsign"]
        if callsign in cls.routes or not re.match(r"^[A-Z]{3}\d[A-Z0-9]*$", callsign):
            return  # done already, or not an airline flight number (private aircraft fly under their registration)
        try:
            answer = cls._get(cls.ROUTE_URL.format(callsign=callsign)).get("response")
            route = answer.get("flightroute") if isinstance(answer, dict) else None
        except Exception:
            return  # network trouble: try again later
        if route and cls._plausible(route, plane, lat0, lon0):
            cls.routes[callsign] = {
                "from": route["origin"].get("iata_code") or route["origin"].get("icao_code") or "?",
                "to": route["destination"].get("iata_code") or route["destination"].get("icao_code") or "?",
                "airline": (route.get("airline") or {}).get("name") or "",
            }
        else:
            cls.routes[callsign] = None
        if len(cls.routes) > 500:
            cls.routes.pop(next(iter(cls.routes)))

    @classmethod
    def _run(cls, lat: float, lon: float, km: float, refresh: float):
        order = list(cls.SOURCES)
        while True:
            if Bc250Screen._mode == "off":
                time.sleep(5)
                continue
            for name, url in list(order):
                try:
                    planes = cls._parse(cls._get(url.format(lat=lat, lon=lon, nm=km / 1.852 + 1)), lat, lon)
                except Exception as e:
                    cls.error = f"{name}: {e}"
                    continue
                cls.aircraft, cls.fetched, cls.source, cls.error = planes, time.time(), name, None
                order.remove((name, url))
                order.insert(0, (name, url))  # keep using the source that answered
                break
            # routes of the flights the panel shows (a couple per round: the lookup service is free too)
            for plane in cls._want_routes[:2]:
                if plane["callsign"] not in cls.routes:
                    cls._route(plane, lat, lon)
            time.sleep(refresh)


class _Radar:
    """The scope and the flight panel, drawn by a thread of their own at a few frames per second: a sweep turns, each
    aircraft's blip and data tag move when the sweep passes over it, and only the changed pixels go to the screen."""

    def __init__(self, spec: dict, lcd, base):
        from PIL import Image, ImageDraw
        self.spec, self.base = spec, base
        self.cx, self.cy, self.r = (int(v) for v in spec["SCOPE"])
        self.km = float(spec["RANGE_KM"])
        self.box = (self.cx - self.r - 1, self.cy - self.r - 1, self.cx + self.r + 2, self.cy + self.r + 2)
        self.scope = base.crop(self.box)
        self.inside = Image.new("L", self.scope.size, 0)
        ImageDraw.Draw(self.inside).ellipse((1, 1, 2 * self.r + 1, 2 * self.r + 1), fill=255)
        self.period = float(spec.get("PERIOD", 4.0))
        self.small, self.big, self.large = (_Draw.font(spec["FONT"], s) for s in (12, 24, 36))
        colors = spec.get("COLORS") or {}
        self.col = {k: _Draw.color(colors.get(k), (200, 200, 200)) for k in
                    ("SWEEP", "LOW", "MID", "HIGH", "EMERGENCY", "TEXT", "LABEL", "DIM", "ROUTE")}
        self.lcd = _Screen(lcd, *base.size)
        self.memory = {}  # hex -> what the scope shows of it: position, data, when the sweep last passed
        self.angle = None
        self.trail = []
        self.panel_state = None
        self.lcd.TILE = int(spec.get("TILE", 10))  # short tiles hug a thin diagonal line (the sweep) better

    # -- data --------------------------------------------------------------------------------------------------------
    def colour(self, plane):
        if plane["squawk"] in ("7500", "7600", "7700"):
            return self.col["EMERGENCY"]
        return self.col["LOW"] if plane["alt"] < 6000 else self.col["MID"] if plane["alt"] < 20000 else self.col["HIGH"]

    @staticmethod
    def altitude(plane):
        return f"FL{plane['alt'] // 100:03d}" if plane["alt"] >= 6000 else f"{plane['alt']}FT"

    def now_position(self, plane, now):
        """Dead reckoning from the last report: where the aircraft is now (km east, km north)."""
        dt = max(0.0, min(30.0, now - plane["time"]))
        d = plane["gs"] * 1.852 / 3600 * dt
        return (plane["x"] + d * math.sin(math.radians(plane["track"])),
                plane["y"] + d * math.cos(math.radians(plane["track"])))

    def sweep_over(self, now):
        """Moves the blips the sweep passed over since the last frame, and forgets aircraft that are gone."""
        angle = (now / self.period * 360) % 360
        previous, self.angle = self.angle, angle
        self.trail = (self.trail + [angle])[-4:]
        planes = {p["hex"]: p for p in _RadarFeed.aircraft}
        for hex_, plane in planes.items():
            x, y = self.now_position(plane, now)
            if math.hypot(x, y) > self.km:
                self.memory.pop(hex_, None)
                continue
            bearing = math.degrees(math.atan2(x, y)) % 360
            swept = previous is not None and (bearing - previous) % 360 <= (angle - previous) % 360
            if swept or hex_ not in self.memory:
                # first sight: shown bright (no flash), so the dashboard takes over the splash's scope unchanged
                lit = now if swept else now - self.period * (0.1 if previous is None else 0.5)
                self.memory[hex_] = {"x": x, "y": y, "plane": plane, "lit": lit}
        for hex_ in [h for h in self.memory if h not in planes]:
            if now - self.memory[hex_]["lit"] > 2 * self.period:
                del self.memory[hex_]
        return angle

    # -- drawing -----------------------------------------------------------------------------------------------------
    def to_px(self, x, y):
        k = self.r / self.km
        return self.cx + x * k - self.box[0], self.cy - y * k - self.box[1]

    def scope_frame(self, angle, now, focus, limit=None):
        from PIL import Image, ImageDraw
        frame = self.scope.copy()
        layer = Image.new("RGB", frame.size, (0, 0, 0))
        d = ImageDraw.Draw(layer)
        ox, oy = self.cx - self.box[0], self.cy - self.box[1]
        # the sweep line, and its afterglow at the positions of the last frames. A full-radius line costs every row
        # it crosses on the screen's link, so it is 1 px wide and the afterglow is a few lines, not a filled wedge
        trail = self.trail[-1 - int(self.spec.get("TRAIL", 1)):] if angle is not None else []
        for i, a in enumerate(trail):
            level = 1.0 if i == len(trail) - 1 else 0.25 + 0.3 * i / max(1, len(trail) - 1)
            a = math.radians(a)
            d.line((ox, oy, ox + (self.r - 1) * math.sin(a), oy - (self.r - 1) * math.cos(a)),
                   fill=_lerp((0, 0, 0), self.col["SWEEP"], level))
        frame.paste(layer, (0, 0), _mask_of(layer, self.inside))

        d = ImageDraw.Draw(frame)
        tags = []
        ordered = sorted(self.memory.items(), key=lambda kv: (kv[0] != focus, math.hypot(kv[1]["x"], kv[1]["y"])))
        if limit is not None:
            ordered = ordered[:limit]
        for i, (hex_, seen) in enumerate(ordered):
            plane = seen["plane"]
            age = (now - seen["lit"]) / self.period
            fade = 1.0 if age < 0.5 else 0.6  # few steps: each one resends every blip
            colour = _lerp((0, 0, 0), self.colour(plane), fade)
            if age < 0.06:  # the sweep is passing over it: a white flash
                colour = _lerp(self.colour(plane), (255, 255, 255), 0.6)
            px, py = self.to_px(seen["x"], seen["y"])
            # heading vector, longer for faster aircraft
            length = 6 + min(14, plane["gs"] / 40)
            a = math.radians(plane["track"])
            d.line((px, py, px + length * math.sin(a), py - length * math.cos(a)), fill=colour)
            d.rectangle((px - 2, py - 2, px + 2, py + 2), fill=colour)
            if hex_ == focus:
                d.rectangle((px - 6, py - 6, px + 6, py + 6), outline=self.col["TEXT"])
            if i >= int(self.spec.get("TAGS", 8)):
                continue
            words = (plane["callsign"][:8], f"{plane['alt'] // 100:03d} {plane['gs']:.0f}")
            tw = 6 * max(len(w) for w in words)
            for dx, dy in ((7, -22), (7, 4), (-7 - tw, -22), (-7 - tw, 4)):
                box = (px + dx, py + dy, px + dx + tw, py + dy + 22)
                if (box[0] >= 2 and box[2] <= frame.width - 2 and box[1] >= 2 and box[3] <= frame.height - 2
                        and math.hypot((box[0] + box[2]) / 2 - ox, (box[1] + box[3]) / 2 - oy) < self.r - 10
                        and not any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in tags)):
                    tags.append(box)
                    d.text((box[0], box[1] + 10), words[0], font=self.small,
                           fill=self.col["TEXT"] if hex_ == focus else _lerp(self.col["TEXT"], (0, 0, 0), 0.15),
                           anchor="ls")
                    d.text((box[0], box[1] + 21), words[1], font=self.small, fill=self.colour(plane), anchor="ls")
                    break
        return frame

    def panel(self, focus_plane, others):
        """The flight card, the NEXT list and the aircraft count, redrawn only when what they say changes."""
        from PIL import ImageDraw
        spec = self.spec
        count = len(_RadarFeed.aircraft)
        stale = _RadarFeed.fetched is None or time.time() - _RadarFeed.fetched > 60
        route = _RadarFeed.routes.get(focus_plane["callsign"]) if focus_plane else None
        state = (focus_plane and (focus_plane["callsign"], self.altitude(focus_plane), round(focus_plane["gs"] / 5),
                                  focus_plane["type"], round(math.hypot(focus_plane["x"], focus_plane["y"])),
                                  round(focus_plane["rate"] / 500), str(route)),
                 tuple((p["callsign"], self.altitude(p), round(math.hypot(p["x"], p["y"]))) for p in others),
                 count, stale)
        if state == self.panel_state:
            return
        self.panel_state = state

        x1, y1, x2, y2 = (int(v) for v in spec["CARD"])
        card = self.base.crop((x1, y1, x2, y2))
        d = ImageDraw.Draw(card)
        rows = spec["CARD_ROWS"]  # baselines, relative to the card
        if focus_plane is None:
            d.text((0, rows[0]), "NO DATA" if stale else "CLEAR SKY", font=self.big,
                   fill=self.col["EMERGENCY"] if stale else self.col["DIM"], anchor="ls")
            d.text((0, rows[1]), (_RadarFeed.error or "waiting for the first answer")[:(x2 - x1) // 6]
                   if stale else "no aircraft in range", font=self.small, fill=self.col["DIM"], anchor="ls")
        elif spec.get("CARD_STYLE") == "wide":  # portrait: callsign and route on one line, then the numbers
            p, width = focus_plane, x2 - x1
            d.text((0, rows[0]), p["callsign"][:8], font=self.large, fill=self.col["TEXT"], anchor="ls")
            if route:
                d.text((width, rows[0]), f"{route['from']} → {route['to']}", font=self.big, fill=self.col["ROUTE"],
                       anchor="rs")
            else:
                d.text((width, rows[0]), (p["registration"] or "")[:8], font=self.big, fill=self.col["DIM"], anchor="rs")
            trend = "↑" if p["rate"] > 300 else "↓" if p["rate"] < -300 else ""
            d.text((0, rows[1]), self.altitude(p) + trend, font=self.big, fill=self.colour(p), anchor="ls")
            d.text((120, rows[1]), f"{p['gs']:.0f}KT", font=self.big, fill=self.col["TEXT"], anchor="ls")
            if route:
                d.text((width, rows[1]), route["airline"][:(width - 190) // 6], font=self.small,
                       fill=self.col["LABEL"], anchor="rs")
            distance = math.hypot(p["x"], p["y"])
            bearing = math.degrees(math.atan2(p["x"], p["y"])) % 360
            squawk = f"  SQUAWK {p['squawk']}" if self.colour(p) == self.col["EMERGENCY"] else ""
            d.text((0, rows[2]), f"{p['type'] or '----'}  {distance:.0f} km {_compass(bearing)}{squawk}",
                   font=self.small, fill=self.col["LABEL"], anchor="ls")
        else:
            p = focus_plane
            width = x2 - x1
            d.text((0, rows[0]), p["callsign"][:width // 18], font=self.large, fill=self.col["TEXT"], anchor="ls")
            if route:
                d.text((0, rows[1]), f"{route['from']} → {route['to']}", font=self.big, fill=self.col["ROUTE"],
                       anchor="ls")
                d.text((0, rows[2]), route["airline"][:width // 6], font=self.small, fill=self.col["LABEL"], anchor="ls")
            else:
                d.text((0, rows[1]), p["registration"] or p["callsign"], font=self.big, fill=self.col["DIM"],
                       anchor="ls")
            trend = "↑" if p["rate"] > 300 else "↓" if p["rate"] < -300 else ""
            d.text((0, rows[3]), self.altitude(p) + trend, font=self.big, fill=self.colour(p), anchor="ls")
            d.text((width, rows[3]), f"{p['gs']:.0f}KT", font=self.big, fill=self.col["TEXT"], anchor="rs")
            distance = math.hypot(p["x"], p["y"])
            bearing = math.degrees(math.atan2(p["x"], p["y"])) % 360
            squawk = f"  SQUAWK {p['squawk']}" if self.colour(p) == self.col["EMERGENCY"] else ""
            d.text((0, rows[4]), f"{p['type'] or '----'}  {distance:.0f} km {_compass(bearing)}{squawk}"[:width // 6],
                   font=self.small, fill=self.col["LABEL"], anchor="ls")
        self.lcd.DisplayPILImage(card, x1, y1)

        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LIST"])
        listing = self.base.crop((lx1, ly1, lx2, ly2))
        d = ImageDraw.Draw(listing)
        columns = int(spec.get("LIST_COLUMNS", 1))
        col_w = (lx2 - lx1) // columns
        for i, p in enumerate(others[:int(spec.get("LIST_ROWS", 4)) * columns]):
            cx_, row = (i % columns) * col_w, i // columns
            bl = int(spec["LIST_BL"]) + row * int(spec.get("LIST_STEP", 14)) - ly1
            d.text((cx_, bl), p["callsign"][:8], font=self.small, fill=self.col["TEXT"], anchor="ls")
            d.text((cx_ + 54, bl), self.altitude(p), font=self.small, fill=self.colour(p),
                   anchor="ls")
            d.text((cx_ + col_w - 6, bl), f"{math.hypot(p['x'], p['y']):.0f}km", font=self.small,
                   fill=self.col["LABEL"], anchor="rs")
        self.lcd.DisplayPILImage(listing, lx1, ly1)

        hx, hy, hw = (int(v) for v in spec["COUNT"])  # right edge, baseline, width
        strip = self.base.crop((hx - hw, hy - 11, hx, hy + 3))
        ImageDraw.Draw(strip).text((hw, 11), "NO DATA" if stale else f"{count} AIRCRAFT", font=self.small,
                                   fill=self.col["EMERGENCY"] if stale else self.col["LABEL"], anchor="rs")
        self.lcd.DisplayPILImage(strip, hx - hw, hy - 11)

    def step(self):
        """One frame: sweep, blips, then the panel if something it shows changed."""
        now = time.time()
        angle = self.sweep_over(now)
        seen = sorted(self.memory.items(), key=lambda kv: math.hypot(kv[1]["x"], kv[1]["y"]))
        focus = seen[0][0] if seen else None
        self.lcd.DisplayPILImage(self.scope_frame(angle, now, focus), self.box[0], self.box[1])
        planes = [s["plane"] for _, s in seen]
        _RadarFeed._want_routes = planes[:3]
        self.panel(planes[0] if planes else None, planes[1:])


def _mask_of(layer, inside):
    """Where a drawn layer has something, clipped to the scope's disc."""
    from PIL import ImageChops
    return ImageChops.multiply(layer.convert("L").point(lambda v: 255 if v else 0), inside)


class Bc250Radar:
    """Radar theme: starts the feed and the scope's drawing thread (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        radar = _Radar(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            radar.lcd = _Draw.screen  # shared with the other widgets: it knows the screen shows the background
        else:
            import numpy
            radar.lcd.shadow = numpy.asarray(radar.base).copy()  # the app has just drawn the background
        frame = 1 / float(spec.get("FPS", 8))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                continue
            _attempt("radar frame", radar.step)
            _Splash._wait(0)  # let the queue drain: the radar never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Radar")
        if spec and _Draw.enabled:
            _RadarFeed.start(float(spec["LAT"]), float(spec["LON"]), float(spec["RANGE_KM"]),
                             float(spec.get("REFRESH", 6)))
            if Bc250Radar._thread is None or not Bc250Radar._thread.is_alive():
                Bc250Radar._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 radar",
                                                      daemon=True)
                Bc250Radar._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


_Splash.takes_over(Bc250Radar, "SCOPE",  # the sweep takes the scope over (its centre x, y and radius)
                   lambda s: (s[0] - s[2] - 1, s[1] - s[2] - 1, s[0] + s[2] + 2, s[1] + s[2] + 2))


class _RadarSplash:
    """Radar boot, on the dashboard's own scope (it is the cover frame, revealed by the backlight): the range rings
    light up one by one, a console log runs the self-test, opens the data link and loads the map in the side panel,
    then the first contacts appear on the scope. No sweep here: the dashboard's sweep starts the moment this ends."""
    STATUS = {"OK": ("OK", "SWEEP"), "WAIT": ("WAIT", "MID"), "WARN": ("FAIL", "EMERGENCY"), "HOT!": ("HOT", "EMERGENCY")}

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import Image, ImageDraw
        base = _Draw.background(spec.get("IMAGE", "background.png"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        _RadarFeed.start(float(spec["LAT"]), float(spec["LON"]), float(spec["RANGE_KM"]), float(spec.get("REFRESH", 6)))
        radar = _Radar(spec, lcd, base)
        radar.lcd = lcd  # the splash's screen: everything below sends only what changes
        small, col = radar.small, radar.col

        # 1. the console in the dark, then the backlight comes up on it
        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)  # the one full frame (~2 s on a rev A)
        _Splash._animate(0.6, lambda p: lcd.SetBrightness(round(target * p)))

        # the console log in the side panel (scrolling when it is full)
        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LOG"])
        rows, chars = (ly2 - ly1) // 14, (lx2 - lx1) // 6
        lines = []

        def show_log():
            image = Image.new("RGB", (lx2 - lx1, ly2 - ly1), _Draw.color(spec.get("BG"), (2, 9, 4)))
            d = ImageDraw.Draw(image)
            for i, (text, colour) in enumerate(lines[-rows:]):
                d.text((0, 11 + 14 * i), text[:chars], font=small, fill=colour, anchor="ls")
            lcd.DisplayPILImage(image, lx1, ly1)

        def log(text, colour, replace=False):
            if replace and lines:
                lines[-1] = (text, colour)
            else:
                lines.append((text, colour))
            show_log()

        def dots(label, word):
            return f"{label} {'.' * max(1, chars - len(label) - len(word) - 2)} {word}"

        # 2. power on: the range rings light up from the centre out
        log("POWER ON", col["TEXT"])
        scope = radar.scope.copy()
        d = ImageDraw.Draw(scope)
        ox, oy = radar.cx - radar.box[0], radar.cy - radar.box[1]
        for radius in spec.get("RINGS", []):
            d.ellipse((ox - radius, oy - radius, ox + radius, oy + radius), outline=_lerp(col["SWEEP"], (0, 0, 0), 0.45))
            lcd.DisplayPILImage(scope, radar.box[0], radar.box[1])
            _Splash._wait(0.08)

        # 3. the self-test
        for label, value, status in _Splash.post_lines(spec):
            log(dots(label, ".."), col["DIM"])
            _Splash._wait(_Splash.STEP * 0.55)
            word, key = cls.STATUS.get(status, ("OK", "SWEEP"))
            log(dots(label, word), col[key], replace=True)
            _Splash._wait(_Splash.STEP * 0.45)

        # 4. the map, then the data link (a few seconds at most for the first answer)
        log(dots("MAP", f"{int(spec.get('MAP_COUNT', 0))} FIELDS"), col["SWEEP"])
        log(dots("DATA LINK", "..."), col["DIM"])
        deadline = time.monotonic() + 3
        while _RadarFeed.fetched is None and _RadarFeed.error is None and time.monotonic() < deadline:
            _Splash._wait(0.1)
        if _RadarFeed.fetched:
            log(dots("DATA LINK", (_RadarFeed.source or "OK").upper()), col["SWEEP"], replace=True)
        else:
            log(dots("DATA LINK", "NO ANSWER"), col["EMERGENCY"], replace=True)

        # 5. the contacts appear, nearest first; the dashboard's sweep then takes over the scope as it is
        now = time.time()
        radar.sweep_over(now)
        count = len(radar.memory)
        batches = min(count, 10)
        for b in range(1, batches + 1):
            frame = radar.scope_frame(None, time.time(), None, limit=round(count * b / batches))
            lcd.DisplayPILImage(frame, radar.box[0], radar.box[1])
            _Splash._wait(0.05)
        log(dots("CONTACTS", str(count)), col["SWEEP"] if count else col["DIM"])
        log("SWEEP ON", col["TEXT"])
        _Splash._wait(0.6)


_Splash.STYLES["radar"] = _RadarSplash
