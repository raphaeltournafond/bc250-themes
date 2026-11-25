# SPDX-License-Identifier: GPL-3.0-or-later
"""Orbit theme: the ISS, computed here from its published orbital elements."""

import datetime
import math
import os
import time
from typing import List, Optional

from ..base import _compass, _duration
from ..draw import _attempt, _Draw
from ..screen import Bc250Screen
from ..splash import _Screen, _Splash


class _IssElements:
    """The ISS's orbital elements (a two-line element set), from CelesTrak or wheretheiss.at: public, no key. They are
    fetched every six hours and kept on disk, so the theme works offline for days; where the ISS is, and when it
    passes over you, is computed here from them. Nothing about this machine or its location is sent. Like the other
    feeds, it stops asking while the screen sleeps."""
    SOURCES = (("CelesTrak", "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"),
               ("wheretheiss.at", "https://api.wheretheiss.at/v1/satellites/25544/tles?format=text"))
    AGENT = "bc250-themes"
    REFRESH, RETRY = 6 * 3600, 15 * 60  # seconds (CelesTrak asks not to fetch the same elements more often)
    TOO_OLD = 14 * 86400  # past this the computed position is too far off to be shown
    elements = None
    source = None
    fetched = None  # when the elements in use were downloaded (time.time())
    error = None
    site = None  # (lat, lon) passes are computed for: from theme.yaml, it stays on this machine
    passes = None  # the coming passes over it, None until computed
    passes_at = 0.0
    _retry_at = 0.0
    _thread = None

    @staticmethod
    def _checksum(line: str) -> bool:
        total = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in line[:68])
        return len(line) >= 69 and line[68].isdigit() and total % 10 == int(line[68])

    @classmethod
    def parse(cls, text: str) -> Optional[dict]:
        """The first valid element set in a TLE text, or None."""
        lines = [line.rstrip() for line in (text or "").splitlines()]
        for one, two in zip(lines, lines[1:]):
            if not (one.startswith("1 ") and two.startswith("2 ") and cls._checksum(one) and cls._checksum(two)):
                continue
            try:
                year, day = int(one[18:20]), float(one[20:32])
                year += 2000 if year < 57 else 1900
                epoch = datetime.datetime(year, 1, 1, tzinfo=datetime.timezone.utc).timestamp() + (day - 1) * 86400
                return {"epoch": epoch, "ndot2": float(one[33:43]), "inclination": float(two[8:16]),
                        "raan": float(two[17:25]), "eccentricity": float("0." + two[26:33].strip()),
                        "perigee": float(two[34:42]), "anomaly": float(two[43:51]), "motion": float(two[52:63]),
                        "revolution": int(two[63:68].strip() or 0)}
            except ValueError:
                continue
        return None

    @staticmethod
    def _saved_path() -> str:
        root = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        return os.path.join(root, "bc250-themes", "iss.tle")

    @classmethod
    def _get(cls, url: str) -> str:
        import urllib.request
        request = urllib.request.Request(url, headers={"User-Agent": cls.AGENT, "Accept": "text/plain"})
        with urllib.request.urlopen(request, timeout=15) as answer:
            return answer.read().decode("ascii", "replace")

    @classmethod
    def fetch(cls) -> dict:
        """Fresh elements from the first source that answers (saved on disk), or an error naming each one's."""
        fixture = os.environ.get("BC250_ISS_FIXTURE")  # tests and previews: saved elements, as if three hours old
        if fixture:
            with open(fixture, encoding="ascii") as f:
                elements = cls.parse(f.read())
            if elements is None:
                raise ValueError("no element set in the fixture")
            elements["epoch"] = time.time() - 3 * 3600
            cls.source = "saved"
            return elements
        errors = []
        for name, url in cls.SOURCES:
            try:
                text = cls._get(url)
                elements = cls.parse(text)
                if elements is None:
                    raise ValueError("no element set in the answer")
                cls.source = name
                _attempt("saving the ISS elements", lambda: cls._save(text))
                return elements
            except Exception as e:
                errors.append(f"{name}: {e}")
        raise OSError("; ".join(errors))

    @classmethod
    def _save(cls, text: str):
        path = cls._saved_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".new", "w", encoding="ascii") as f:
            f.write(text)
        os.replace(path + ".new", path)

    @classmethod
    def _load_saved(cls):
        """The elements saved last time: the theme starts with them, and only asks again once they are due."""
        if os.environ.get("BC250_ISS_FIXTURE"):
            return
        try:
            path = cls._saved_path()
            with open(path, encoding="ascii") as f:
                elements = cls.parse(f.read())
            if elements and time.time() - elements["epoch"] < cls.TOO_OLD:
                cls.elements, cls.source, cls.fetched = elements, "saved", os.path.getmtime(path)
        except (OSError, ValueError):
            pass

    @classmethod
    def usable(cls) -> Optional[dict]:
        elements = cls.elements
        return elements if elements and time.time() - elements["epoch"] < cls.TOO_OLD else None

    @classmethod
    def update_passes(cls):
        elements, site, now = cls.usable(), cls.site, time.time()
        if elements is None or site is None:
            return
        if cls.passes is None or now - cls.passes_at > 600 or (cls.passes and cls.passes[0]["set"] < now):
            cls.passes = _Sky.passes(elements, site[0], site[1], now)
            cls.passes_at = now

    @classmethod
    def start(cls, site=None):
        import threading
        cls.site = site
        if cls.elements is None:
            cls._load_saved()
        if cls._thread is None or not cls._thread.is_alive():
            cls._thread = threading.Thread(target=cls._run, name="BC250 ISS elements", daemon=True)
            cls._thread.start()

    @classmethod
    def _run(cls):
        while True:
            if Bc250Screen._mode == "off":
                time.sleep(5)
                continue
            now = time.time()
            if (cls.fetched is None or now - cls.fetched >= cls.REFRESH) and now >= cls._retry_at:
                try:
                    cls.elements, cls.fetched, cls.error = cls.fetch(), time.time(), None
                    cls.passes = None  # computed again from the new elements
                except Exception as e:
                    cls.error, cls._retry_at = str(e) or type(e).__name__, now + cls.RETRY
            _attempt("ISS passes", cls.update_passes)
            time.sleep(10)


class _Sky:
    """Where the ISS is, from its elements: Kepler's ellipse, turned by the Earth's bulge (the orbit's plane and its
    perigee drift by a few degrees a day) and lowered by the air's drag, as the classic amateur trackers do it. With
    elements a day old it is a few km off: well under a pixel of the map, and seconds on a pass. The sun's place is
    the almanac's low-precision formula (0.01 degree)."""
    GM, RE, J2, FLAT = 398600.4418, 6378.137, 1.08262668e-3, 1 / 298.257223563
    E2 = FLAT * (2 - FLAT)
    HOURS = 72  # how far ahead passes are looked for
    MIN_EL = 10.0  # a pass that stays lower than this is not worth going out for

    @staticmethod
    def days_j2000(t: float) -> float:
        return t / 86400 + 2440587.5 - 2451545.0

    @classmethod
    def gmst(cls, t: float) -> float:
        """How far the Earth has turned (Greenwich sidereal time, radians) at a Unix time."""
        return math.radians((280.46061837 + 360.98564736629 * cls.days_j2000(t)) % 360)

    @classmethod
    def geodetic(cls, x: float, y: float, z: float):
        """(latitude in degrees, altitude in km) of a point given in km from the Earth's centre."""
        p = math.hypot(x, y)
        lat = math.atan2(z, p * (1 - cls.E2))
        for _ in range(4):  # (n + altitude = p / cos(lat))
            n = cls.RE / math.sqrt(1 - cls.E2 * math.sin(lat) ** 2)
            lat = math.atan2(z, p - cls.E2 * n * math.cos(lat))
        n = cls.RE / math.sqrt(1 - cls.E2 * math.sin(lat) ** 2)
        return math.degrees(lat), p / math.cos(lat) - n

    @classmethod
    def position(cls, el: dict, t: float) -> dict:
        tau = 2 * math.pi
        dt = t - el["epoch"]
        d = dt / 86400
        n0 = el["motion"] * tau / 86400  # rad/s
        a0 = (cls.GM / n0 ** 2) ** (1 / 3)
        n = (el["motion"] + 2 * el["ndot2"] * d) * tau / 86400  # drag lowers the orbit, which speeds it up
        a = (cls.GM / n ** 2) ** (1 / 3)
        e, i = el["eccentricity"], math.radians(el["inclination"])
        k = 1.5 * cls.J2 * (cls.RE / (a0 * (1 - e * e))) ** 2 * n0
        node = math.radians(el["raan"]) - k * math.cos(i) * dt
        perigee = math.radians(el["perigee"]) + k * (2 - 2.5 * math.sin(i) ** 2) * dt
        mean = math.radians(el["anomaly"]) + tau * (el["motion"] * d + el["ndot2"] * d * d)
        ecc = mean
        for _ in range(6):
            ecc -= (ecc - e * math.sin(ecc) - mean) / (1 - e * math.cos(ecc))
        px, py = a * (math.cos(ecc) - e), a * math.sqrt(1 - e * e) * math.sin(ecc)
        co, so, cw, sw, ci, si = (math.cos(node), math.sin(node), math.cos(perigee), math.sin(perigee),
                                  math.cos(i), math.sin(i))
        x = (co * cw - so * sw * ci) * px - (co * sw + so * cw * ci) * py
        y = (so * cw + co * sw * ci) * px + (co * cw * ci - so * sw) * py
        z = sw * si * px + cw * si * py
        r = math.hypot(px, py)
        g = cls.gmst(t)
        xe, ye = math.cos(g) * x + math.sin(g) * y, math.cos(g) * y - math.sin(g) * x
        lat, alt = cls.geodetic(xe, ye, z)
        start = math.radians(el["perigee"] + el["anomaly"])
        return {"eci": (x, y, z), "ecef": (xe, ye, z), "lat": lat, "lon": math.degrees(math.atan2(ye, xe)), "alt": alt,
                "speed": math.sqrt(cls.GM * (2 / r - 1 / a)), "period": tau / n / 60,
                # a new orbit starts at each ascending node (the ISS crossing the equator northwards)
                "orbit": el["revolution"] + math.floor((perigee + mean) / tau) - math.floor(start / tau)}

    @classmethod
    def site(cls, lat: float, lon: float) -> tuple:
        """A place at sea level, in km from the Earth's centre (turning with the Earth)."""
        f, l = math.radians(lat), math.radians(lon)
        n = cls.RE / math.sqrt(1 - cls.E2 * math.sin(f) ** 2)
        return n * math.cos(f) * math.cos(l), n * math.cos(f) * math.sin(l), n * (1 - cls.E2) * math.sin(f)

    @staticmethod
    def look(lat: float, lon: float, site: tuple, sat: tuple):
        """(azimuth, elevation) in degrees of a point seen from a place."""
        f, l = math.radians(lat), math.radians(lon)
        rx, ry, rz = (s - o for s, o in zip(sat, site))
        east = -math.sin(l) * rx + math.cos(l) * ry
        north = -math.sin(f) * math.cos(l) * rx - math.sin(f) * math.sin(l) * ry + math.cos(f) * rz
        up = math.cos(f) * math.cos(l) * rx + math.cos(f) * math.sin(l) * ry + math.sin(f) * rz
        return math.degrees(math.atan2(east, north)) % 360, math.degrees(math.atan2(up, math.hypot(east, north)))

    @classmethod
    def sun(cls, t: float) -> tuple:
        """Direction of the sun, as a unit vector in the frame the ISS's position is in."""
        n = cls.days_j2000(t)
        g = math.radians(357.528 + 0.9856003 * n)
        lam = math.radians(280.460 + 0.9856474 * n + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
        eps = math.radians(23.439 - 4e-7 * n)
        return math.cos(lam), math.cos(eps) * math.sin(lam), math.sin(eps) * math.sin(lam)

    @classmethod
    def subsolar(cls, t: float):
        """(lat, lon) where the sun is overhead."""
        sx, sy, sz = cls.sun(t)
        lon = math.degrees(math.atan2(sy, sx) - cls.gmst(t))
        return math.degrees(math.asin(sz)), (lon + 180) % 360 - 180

    @classmethod
    def sunlit(cls, eci: tuple, sun: tuple) -> bool:
        """Whether a point is in sunlight, out of the Earth's shadow."""
        along = sum(a * b for a, b in zip(eci, sun))
        return along > 0 or math.sqrt(max(0.0, sum(a * a for a in eci) - along * along)) > cls.RE

    @classmethod
    def sun_elevation(cls, lat: float, lon: float, t: float) -> float:
        slat, slon = cls.subsolar(t)
        f, s = math.radians(lat), math.radians(slat)
        sin_el = math.sin(f) * math.sin(s) + math.cos(f) * math.cos(s) * math.cos(math.radians(lon - slon))
        return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))

    @classmethod
    def seen(cls, el: dict, lat: float, lon: float, t: float):
        """(azimuth, elevation, visible): where the ISS is in a place's sky, and whether it can be seen with the eye
        (in sunlight, high enough, against a sky dark enough)."""
        p = cls.position(el, t)
        az, elev = cls.look(lat, lon, cls.site(lat, lon), p["ecef"])
        return az, elev, (elev >= cls.MIN_EL and cls.sun_elevation(lat, lon, t) < -6
                          and cls.sunlit(p["eci"], cls.sun(t)))

    @classmethod
    def passes(cls, el: dict, lat: float, lon: float, start: float, hours: float = None) -> List[dict]:
        """The ISS's passes over a place from `start`, one under way included: rise, set, highest point, the track in
        its sky, and whether it can be seen. Passes lower than MIN_EL are left out."""
        site = cls.site(lat, lon)
        elevation = lambda t: cls.look(lat, lon, site, cls.position(el, t)["ecef"])[1]

        def crossing(t1, t2, rising):  # the moment it crosses the horizon, to a second
            for _ in range(7):
                mid = (t1 + t2) / 2
                if (elevation(mid) > 0) == rising:
                    t2 = mid
                else:
                    t1 = mid
            return (t1 + t2) / 2

        found, rise = [], None
        t = start - 1200  # a pass already under way is found from its beginning
        before = elevation(t)
        while t < start + (hours or cls.HOURS) * 3600:
            after = elevation(t + 60)
            if before <= 0 < after:
                rise = crossing(t, t + 60, True)
            elif before > 0 >= after and rise is not None:
                one = cls._describe(el, lat, lon, site, rise, crossing(t, t + 60, False))
                if one["set"] > start and one["peak_el"] >= cls.MIN_EL:
                    found.append(one)
                rise = None
            t, before = t + 60, after
        return found

    @classmethod
    def _describe(cls, el, lat, lon, site, rise, end):
        track, peak, peak_el, visible = [], rise, -90.0, False
        steps = max(2, int((end - rise) / 10))
        for k in range(steps + 1):
            t = rise + (end - rise) * k / steps
            p = cls.position(el, t)
            az, elev = cls.look(lat, lon, site, p["ecef"])
            track.append((az, elev))
            if elev > peak_el:
                peak, peak_el = t, elev
            if not visible and elev >= cls.MIN_EL and cls.sun_elevation(lat, lon, t) < -6 \
                    and cls.sunlit(p["eci"], cls.sun(t)):
                visible = True
        return {"rise": rise, "set": end, "peak": peak, "peak_el": peak_el, "visible": visible, "track": track}


_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _age(seconds: float) -> str:
    """How old the elements are: "40 MIN", "3 H", "4 DAYS"."""
    if seconds < 3600:
        return f"{max(0, seconds) // 60:.0f} MIN"
    return f"{seconds // 3600:.0f} H" if seconds < 48 * 3600 else f"{seconds // 86400:.0f} DAYS"


def _degrees_text(lat: float, lon: float, digits: int = 2) -> str:
    """"51.42°N 123.45°W"."""
    return f"{abs(lat):.{digits}f}°{'N' if lat >= 0 else 'S'} {abs(lon):.{digits}f}°{'E' if lon >= 0 else 'W'}"


class _Tracker:
    """The orbit theme: the ISS going round a world map where night falls where it is night now, its ground track
    (the orbit it just flew dashed, the next one bright), the circle of the Earth that can see it, and two cards:
    where it is and how fast, and when it next passes over you, drawn on a chart of your sky. Computed every frame from
    the elements _IssElements keeps."""
    TWILIGHT = 12.0  # degrees under the horizon for the sun to be fully set
    frames = 0  # (read by the tests)

    def __init__(self, spec: dict, lcd, base):
        import numpy
        self.spec, self.lcd, self.base = spec, lcd, base
        self.mx, self.my, self.mw, self.mh = (int(v) for v in spec["MAP"])
        self.lat_top, self.scale = float(spec["LAT_TOP"]), self.mw / 360  # pixels per degree
        day = numpy.asarray(base.crop((self.mx, self.my, self.mx + self.mw, self.my + self.mh))).astype(numpy.float32)
        self.day, self.night = day, day * numpy.array(spec.get("NIGHT", [0.3, 0.36, 0.5]), dtype=numpy.float32)
        lats = numpy.radians(self.lat_top - (numpy.arange(self.mh) + 0.5) / self.scale)
        self.sin_lat, self.cos_lat = numpy.sin(lats)[:, None], numpy.cos(lats)[:, None]
        self.lons = numpy.radians(-180 + (numpy.arange(self.mw) + 0.5) / self.scale)[None, :]
        self.shade = (None, None)  # (minute, map with the night on it)
        self.track = (None, [])  # (minute, [(time, lat, lon)])
        self.col_ = {k: _Draw.color(v) for k, v in spec["COLORS"].items()}
        self.small, self.big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 24)
        self.site = (float(spec["LAT"]), float(spec["LON"])) if "LAT" in spec else None
        self.names = list(spec.get("REGIONS") or [])
        self.regions = None
        if spec.get("REGIONS_IMAGE"):
            from PIL import Image
            self.regions = _attempt("orbit regions", lambda: Image.open(_Draw.background_path(spec["REGIONS_IMAGE"]))
                                    .convert("L"))
        self.frame_no = 0

    # -- the map -----------------------------------------------------------------------------------------------------
    def xy(self, lat: float, lon: float):
        return (lon + 180) % 360 * self.scale, (self.lat_top - lat) * self.scale

    def over(self, lat: float, lon: float) -> str:
        """What the ISS is flying over: "THE N. PACIFIC", "EUROPE"..."""
        if self.regions is None:
            return ""
        index = self.regions.getpixel((int(lon + 180) % 360, max(0, min(179, int(90 - lat)))))
        return self.names[index] if index < len(self.names) else ""

    def night_map(self, t: float, sweep: float = 1.0):
        """The map with the night on it. Twilight is a gradient; it moves a pixel every few minutes, so it is computed
        once a minute. sweep < 1: the night has only come over that much of the map, from the east (the boot)."""
        import numpy
        from PIL import Image
        minute = int(t // 60)
        if sweep >= 1 and self.shade[0] == minute:
            return self.shade[1]
        slat, slon = _Sky.subsolar(t)
        s, c = math.sin(math.radians(slat)), math.cos(math.radians(slat))
        sin_el = self.sin_lat * s + self.cos_lat * c * numpy.cos(self.lons - math.radians(slon))
        dark = numpy.clip(-numpy.degrees(numpy.arcsin(numpy.clip(sin_el, -1, 1))) / self.TWILIGHT, 0, 1)
        if sweep < 1:
            dark[:, :round(self.mw * (1 - sweep))] = 0
        picture = Image.fromarray((self.day + (self.night - self.day) * dark[..., None]).round().astype(numpy.uint8))
        if sweep >= 1:
            self.shade = (minute, picture)
        return picture

    def ground_track(self, el: dict, t: float, now: dict):
        """(past, next): the orbit it just flew and the one ahead, as (lat, lon), meeting where the ISS is."""
        minute = int(t // 60)
        if self.track[0] != minute:  # from 50 minutes ago to a whole orbit ahead, a point a minute
            points = []
            for k in range(-50, 97):
                when = minute * 60 + 60 * k
                p = _Sky.position(el, when)
                points.append((when, p["lat"], p["lon"]))
            self.track = (minute, points)
        here = (now["lat"], now["lon"])
        past = [(lat, lon) for when, lat, lon in self.track[1] if when <= t] + [here]
        ahead = [here] + [(lat, lon) for when, lat, lon in self.track[1] if when > t]
        return past, ahead

    def polyline(self, d, points, fill, dashed=False):
        previous = None
        for n, (lat, lon) in enumerate(points):
            x, y = self.xy(lat, lon)
            if previous and abs(x - previous[0]) < self.mw / 2 and not (dashed and n % 2):
                d.line((previous, (x, y)), fill=fill)
            previous = (x, y)

    def footprint(self, d, lat: float, lon: float, alt: float):
        """The edge of the part of the Earth that sees the ISS above its horizon (about 2 200 km around it)."""
        rho = math.acos(_Sky.RE / (_Sky.RE + alt))
        f1, l1 = math.radians(lat), math.radians(lon)
        for bearing in range(0, 360, 5):
            b = math.radians(bearing)
            f2 = math.asin(math.sin(f1) * math.cos(rho) + math.cos(f1) * math.sin(rho) * math.cos(b))
            l2 = l1 + math.atan2(math.sin(b) * math.sin(rho) * math.cos(f1), math.cos(rho) - math.sin(f1) * math.sin(f2))
            d.point(self.xy(math.degrees(f2), math.degrees(l2)), fill=self.col_["FOOTPRINT"])

    def sprite(self, d, x: float, y: float):
        """The ISS: its truss, four pairs of solar wings, the modules in the middle."""
        x, y = round(x), round(y)
        d.line((x - 7, y, x + 7, y), fill=self.col_["MID"])
        for side in (-1, 1):
            for off in (3, 6):
                wx = x + side * off
                d.rectangle((min(wx, wx + side), y - 3, max(wx, wx + side), y - 1), fill=self.col_["PANEL"])
                d.rectangle((min(wx, wx + side), y + 1, max(wx, wx + side), y + 3), fill=self.col_["PANEL"])
        d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=self.col_["BRIGHT"])

    def map_frame(self, t: float, el: Optional[dict], sweep: float = 1.0, drawn: float = 1.0, iss: bool = True,
                  ring: Optional[float] = None):
        """The map now. The boot draws it in steps: the night coming over it (sweep), the next orbit being drawn
        (drawn, iss=False), the ISS acquired (ring: rings closing in on it)."""
        from PIL import ImageDraw
        frame = self.night_map(t, sweep).copy()
        d = ImageDraw.Draw(frame)
        if sweep >= 1:
            sx, sy = self.xy(*_Sky.subsolar(t))
            d.ellipse((sx - 3, sy - 3, sx + 3, sy + 3), fill=self.col_["SUN"])
        if self.site:
            x, y = self.xy(*self.site)
            d.line((x - 3, y, x + 3, y), fill=self.col_["SITE"])
            d.line((x, y - 3, x, y + 3), fill=self.col_["SITE"])
        if el is None:
            return frame
        now = _Sky.position(el, t)
        past, ahead = self.ground_track(el, t, now)
        if iss:
            self.polyline(d, past, self.col_["PAST"], dashed=True)
        self.polyline(d, ahead[:max(1, round(len(ahead) * drawn))], self.col_["TRACK"])
        if iss:
            self.footprint(d, now["lat"], now["lon"], now["alt"])
            x, y = self.xy(now["lat"], now["lon"])
            radius = 6 + 24 * (1 - ring) if ring is not None else 9 + (self.frame_no % 6)
            if ring is None or ring < 1:
                d.ellipse((x - radius, y - radius, x + radius, y + radius), outline=self.col_["RING"])
            self.sprite(d, x, y)
        return frame

    # -- the cards ---------------------------------------------------------------------------------------------------
    def _strip(self, key: str):
        from PIL import ImageDraw
        x, y, w, h = (int(v) for v in self.spec[key])
        box = (x, y + 14, x + w, y + h)  # (the heading is printed on the background)
        strip = self.base.crop(box)
        return box, strip, ImageDraw.Draw(strip)

    def card(self, t: float, el: Optional[dict]):
        """Where the ISS is: its speed, altitude, place, what it flies over, sunlight, its orbit number."""
        box, strip, d = self._strip("CARD")
        w, chars = box[2] - box[0], (box[2] - box[0]) // 6
        rows = [int(self.spec["CARD"][1]) + int(v) - box[1] for v in self.spec["CARD_ROWS"]]
        say = lambda row, words, fill, right=False: row < len(rows) and d.text(
            (w - 2 if right else 2, rows[row]), words[:chars], font=self.small, fill=fill, anchor="rs" if right else "ls")
        if el is None:
            say(1, "NO ORBIT DATA YET", self.col_["RED" if _IssElements.error else "DIM"])
            say(2, "elements: no answer" if _IssElements.error else "fetching the elements", self.col_["DIM"])
        else:
            p = _Sky.position(el, t)
            speed = f"{p['speed'] * 3600:,.0f}".replace(",", " ")
            d.text((2, rows[0]), speed, font=self.big, fill=self.col_["AMBER"], anchor="ls")
            d.text((6 + 12 * len(speed), rows[0]), "KM/H", font=self.small, fill=self.col_["DIM"], anchor="ls")
            say(0, f"{p['alt']:.0f} KM", self.col_["BRIGHT"], right=True)
            d.text((w - 2, rows[0] - 13), "ALTITUDE", font=self.small, fill=self.col_["DIM"], anchor="rs")
            say(1, _degrees_text(p["lat"], p["lon"]), self.col_["BRIGHT"])
            over = self.over(p["lat"], p["lon"])
            say(2, f"OVER {over}" if over else "", self.col_["MID"])
            lit = _Sky.sunlit(p["eci"], _Sky.sun(t))
            say(3, "SUNLIT" if lit else "IN SHADOW", self.col_["AMBER" if lit else "DIM"])
            say(3, f"ORBIT {p['orbit']}", self.col_["MID"], right=True)
            say(4, f"PERIOD {p['period']:.0f} MIN", self.col_["DIM"])
            say(4, f"INCL {el['inclination']:.1f}°", self.col_["DIM"], right=True)
            say(5, f"ELEMENTS {_age(t - el['epoch'])} OLD", self.col_["DIM"])
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    def pass_card(self, t: float, el: Optional[dict]):
        """The next pass over you, on a chart of your sky (the horizon round the edge, straight up in the middle);
        while it is overhead, where to look."""
        box, strip, d = self._strip("PASS")
        cx, cy, r = (int(v) for v in self.spec["SKY"])
        cx, cy = cx - box[0], cy - box[1]
        slots = [(int(x) - box[0], int(bl) - box[1], int(size), anchor) for x, bl, size, anchor in self.spec["PASS_SLOTS"]]
        chars = int(self.spec.get("PASS_CHARS", 12))

        def put(slot, words, fill, big=False):
            x, bl, size, anchor = slots[slot]
            d.text((x, bl), words[:chars], font=self.big if big and size >= 24 else self.small, fill=fill, anchor=anchor)

        def note(*lines, fill="DIM"):
            for slot, words in enumerate(lines):
                put(slot, words, self.col_[fill])

        def sky(az, elev):
            k = r * (90 - max(0.0, elev)) / 90
            return cx + k * math.sin(math.radians(az)), cy - k * math.cos(math.radians(az))

        upcoming = [p for p in (_IssElements.passes or []) if p["set"] > t]
        if self.site is None:
            note("SET YOUR", "PLACE WITH", "--orbit-lat", "--orbit-lon")
        elif el is None:
            note("NO ORBIT", "DATA YET")
        elif _IssElements.passes is None:
            note("WORKING OUT", "THE PASSES")
        elif not upcoming:
            note("NO PASS", f"IN {_Sky.HOURS // 24} DAYS")
        else:
            one = upcoming[0]
            track = [sky(az, elev) for az, elev in one["track"]]
            d.line(track, fill=self.col_["TRACK" if one["visible"] else "PAST"])
            x, y = track[0]
            d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=self.col_["BRIGHT"])  # where it rises
            if one["rise"] <= t:
                az, elev, visible = _Sky.seen(el, self.site[0], self.site[1], t)
                x, y = sky(az, elev)
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=self.col_["AMBER"])
                put(0, "NOW", self.col_["AMBER"], big=True)
                put(1, f"EL {max(0.0, elev):.0f}° {_compass(az)}", self.col_["BRIGHT"])
                put(2, f"SETS IN {_duration(one['set'] - t).upper()}", self.col_["MID"])
                put(3, "LOOK UP!" if visible else "NOT VISIBLE", self.col_["AMBER" if visible else "DIM"])
            else:
                put(0, datetime.datetime.fromtimestamp(one["rise"]).strftime("%H:%M"), self.col_["BRIGHT"], big=True)
                put(1, f"IN {_duration(one['rise'] - t).upper()}", self.col_["MID"])
                peak = f"MAX {one['peak_el']:.0f}°"
                minutes = f" {round((one['set'] - one['rise']) / 60)}MIN"
                put(2, peak + minutes if len(peak + minutes) <= chars else peak, self.col_["MID"])
                put(3, "VISIBLE" if one["visible"] else "NOT VISIBLE", self.col_["AMBER" if one["visible"] else "DIM"])
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    def header(self, t: float, el: Optional[dict]):
        """Beside the title: the next pass you can see, or how old the elements are."""
        from PIL import ImageDraw
        x, bl, xr = (int(v) for v in self.spec["HEADER"])
        if xr <= x:
            return
        box = (x, bl - 11, xr, bl + 3)
        strip = self.base.crop(box)
        chars, short = (xr - x) // 6, None
        fill = self.col_["DIM"]
        if el is None:
            words = "NO ORBIT DATA: CHECK THE NETWORK" if _IssElements.error else "FETCHING THE ORBIT"
            short, fill = "NO ORBIT DATA", self.col_["RED" if _IssElements.error else "DIM"]
        else:
            age = t - el["epoch"]
            upcoming = [p for p in (_IssElements.passes or []) if p["set"] > t and p["visible"]]
            if age > 3 * 86400:
                words, short, fill = f"ELEMENTS {_age(age)} OLD: CHECK THE NETWORK", f"ELEMENTS {_age(age)} OLD", \
                    self.col_["AMBER"]
            elif upcoming and upcoming[0]["rise"] <= t:
                az = _Sky.seen(el, self.site[0], self.site[1], t)[0]
                words, short, fill = f"ISS OVERHEAD: LOOK UP TO THE {_compass(az)}", "LOOK UP!", self.col_["AMBER"]
            elif upcoming:
                rise = datetime.datetime.fromtimestamp(upcoming[0]["rise"])
                when = f"{_WEEKDAYS[rise.weekday()]} {rise:%H:%M}"
                words, short = f"NEXT VISIBLE PASS {when}, MAX {upcoming[0]['peak_el']:.0f}°", f"VISIBLE {when}"
                fill = self.col_["MID"]
            elif self.site and _IssElements.passes is not None:
                words, short = f"NO VISIBLE PASS IN {_Sky.HOURS // 24} DAYS", "NONE VISIBLE SOON"
            else:
                words = f"ELEMENTS {_age(age)} OLD, {(_IssElements.source or '').upper()}"
                short = f"ELEMENTS {_age(age)} OLD"
        if len(words) > chars and short:
            words = short
        ImageDraw.Draw(strip).text((0, bl - box[1]), words[:chars], font=self.small, fill=fill, anchor="ls")
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    def step(self):
        t = time.time()
        el = _IssElements.usable()
        self.lcd.DisplayPILImage(self.map_frame(t, el), self.mx, self.my)
        self.frame_no += 1
        _Tracker.frames += 1
        if self.frame_no % 4 == 1:
            self.card(t, el)
            self.pass_card(t, el)
        if self.frame_no % 40 == 1:
            self.header(t, el)


class Bc250Orbit:
    """Orbit theme: starts the elements' thread and the tracker's (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        tracker = _Tracker(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            tracker.lcd = _Draw.screen  # shared with the other widgets: it knows what the screen shows
        else:
            import numpy
            tracker.lcd = _Screen(display.lcd, *tracker.base.size)
            tracker.lcd.shadow = numpy.asarray(tracker.base).copy()  # the app has just drawn the background
        tracker.lcd.TILE = int(spec.get("TILE", 10))
        frame = 1 / float(spec.get("FPS", 4))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                continue
            _attempt("orbit frame", tracker.step)
            _Splash._wait(0)  # let the queue drain: the map never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Orbit")
        if spec and _Draw.enabled:
            _IssElements.start((float(spec["LAT"]), float(spec["LON"])) if "LAT" in spec else None)
            if Bc250Orbit._thread is None or not Bc250Orbit._thread.is_alive():
                Bc250Orbit._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 orbit", daemon=True)
                Bc250Orbit._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


_Splash.takes_over(Bc250Orbit, "MAP")  # the tracker carries on from the boot's map


class _OrbitSplash:
    """Orbit boot, on the dashboard itself: the ground station's console comes up over the cards and runs its checks,
    fetches the ISS's elements, then night falls over the map where it is night now, the next orbit is drawn ahead of
    the ISS, and the station acquires it (AOS) as rings close in on it. The map stays as it is: the dashboard carries on
    from it, and the console gives way to the cards."""
    STATUS = {"OK": ("OK", "BRIGHT"), "WAIT": ("WAIT", "AMBER"), "WARN": ("FAIL", "RED"), "HOT!": ("HOT", "RED")}

    @classmethod
    def play(cls, lcd, spec: dict):
        from library import config
        from PIL import Image, ImageDraw
        base = _Draw.background(spec.get("IMAGE", "background.png"))
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        _IssElements.start((float(spec["LAT"]), float(spec["LON"])) if "LAT" in spec else None)
        tracker = _Tracker(spec, lcd, base)
        col, small = tracker.col_, tracker.small
        mx, my = tracker.mx, tracker.my

        lcd.SetBrightness(0)
        lcd.DisplayPILImage(base, 0, 0)  # the one full frame (~2 s on a rev A), sent in the dark
        _Splash._animate(0.5, lambda p: lcd.SetBrightness(round(target * p)))

        # the console, over the cards: one or two columns of lines
        lx1, ly1, lx2, ly2 = (int(v) for v in spec["LOG"])
        columns, step = int(spec.get("LOG_COLUMNS", 1)), int(spec.get("LOG_STEP", 14))
        rows, col_w = (ly2 - ly1 - 6) // step, (lx2 - lx1) // columns
        chars = (col_w - 16) // 6 - 9 - 5  # (label, then the status word)
        panel = Image.new("RGB", (lx2 - lx1, ly2 - ly1), _Draw.color(spec.get("BG"), (8, 14, 26)))
        pd = ImageDraw.Draw(panel)
        pd.rectangle((0, 0, panel.width - 1, panel.height - 1), outline=col["DIM"])
        lcd.DisplayPILImage(panel, lx1, ly1)

        def line(index, label, value, word=None, key=None):
            column, row = divmod(index, rows)
            if column >= columns:
                return
            x1, bl = column * col_w, 4 + step * row + 10
            pd.rectangle((x1 + 2, bl - 11, x1 + col_w - 3, bl + 3), fill=_Draw.color(spec.get("BG"), (8, 14, 26)))
            pd.text((x1 + 8, bl), label, font=small, fill=col["DIM"], anchor="ls")
            pd.text((x1 + 62, bl), _Splash.fit(value, chars), font=small, fill=col["MID"], anchor="ls")
            pd.text((x1 + col_w - 8, bl), word or "...", font=small, fill=col[key] if key else col["DIM"], anchor="rs")
            lcd.DisplayPILImage(panel, lx1, ly1)  # (only the line that changed is sent)

        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            line(i, label, value)
            _Splash._wait(_Splash.STEP * 0.5)
            word, key = cls.STATUS.get(status, ("OK", "BRIGHT"))
            line(i, label, value, word, key)
            _Splash._wait(_Splash.STEP * 0.4)

        # the ISS's elements (a few seconds at most for the first answer; saved ones do meanwhile)
        n = len(lines)
        line(n, "ELEMENTS", "fetching the ISS's orbit")
        deadline = time.monotonic() + 3
        while _IssElements.fetched is None and _IssElements.error is None and time.monotonic() < deadline:
            _Splash._wait(0.1)
        el = _IssElements.usable()
        if el:
            line(n, "ELEMENTS", f"{_IssElements.source}, {_age(time.time() - el['epoch']).lower()} old", "OK", "BRIGHT")
        else:
            line(n, "ELEMENTS", "no answer yet, retrying", "WAIT", "AMBER")

        # night falls where it is night now, coming from the east
        slat, slon = _Sky.subsolar(time.time())
        line(n + 1, "SUN", f"overhead at {_degrees_text(slat, slon, 0)}", "OK", "BRIGHT")
        _Splash._animate(0.9, lambda p: lcd.DisplayPILImage(tracker.map_frame(time.time(), None, sweep=p), mx, my))
        if el is None:
            line(n + 2, "AOS", "no orbit yet, map only", "WAIT", "AMBER")
            lcd.DisplayPILImage(tracker.map_frame(time.time(), None), mx, my)
            _Splash._wait(0.6)
            return

        # the next orbit, drawn ahead of the ISS; then the station acquires it
        p = _Sky.position(el, time.time())
        line(n + 2, "ORBIT", f"{p['orbit']}, {p['alt']:.0f} km up", "OK", "BRIGHT")
        _Splash._animate(1.2, lambda q: lcd.DisplayPILImage(tracker.map_frame(time.time(), el, drawn=q, iss=False),
                                                             mx, my))
        line(n + 3, "AOS", "ISS acquired, tracking", "OK", "AMBER")
        _Splash._animate(0.7, lambda q: lcd.DisplayPILImage(tracker.map_frame(time.time(), el, ring=q), mx, my))
        _Splash._wait(0.6)


_Splash.STYLES["orbit"] = _OrbitSplash
