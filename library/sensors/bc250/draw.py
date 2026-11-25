# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing for the widgets this package renders itself: fonts, colours, the theme's palette, heat-coloured
text, bars and graphs; and _attempt, so that one failing source never stops the others."""

import math
import time
from typing import List, Optional

from .base import _is_nan, logger, _push, REPO_DIR


class _Draw:
    enabled = True  # bc250_check.py turns this off: reading sensors there must never talk to the screen
    screen = None  # the _Screen all widgets draw through, once the app has drawn the theme's background
    _repainted = {}
    _fonts = {}
    _backgrounds = {}
    _failed = set()

    @staticmethod
    def theme(cls_name: str) -> dict:
        from library import config
        return config.THEME_DATA["STATS"]["CUSTOM"].get(cls_name, {}) or {}

    @staticmethod
    def color(value, default=(0, 0, 0)):
        if value is None:
            return default
        if isinstance(value, str):
            return tuple(int(c) for c in value.split(","))
        return tuple(value)

    @classmethod
    def font(cls, name: str, size: int):
        from PIL import ImageFont
        key = (name, size)
        if key not in cls._fonts:
            cls._fonts[key] = ImageFont.truetype(str(REPO_DIR / "res" / "fonts" / name), size,
                                                 layout_engine=ImageFont.Layout.BASIC)  # same text on every machine
        return cls._fonts[key]

    @classmethod
    def background_path(cls, name: str) -> str:
        from library import config
        return str(REPO_DIR / "res" / "themes" / config.CONFIG_DATA["config"]["THEME"] / name)

    @classmethod
    def background(cls, name: str):
        from PIL import Image
        if name not in cls._backgrounds:
            cls._backgrounds[name] = Image.open(cls.background_path(name)).convert("RGB")
        return cls._backgrounds[name]

    @classmethod
    def crop(cls, box: dict):
        x, y = box["X"], box["Y"]
        return cls.background(box.get("BACKGROUND_IMAGE", "background.png")).crop(
            (x, y, x + box["WIDTH"], y + box["HEIGHT"]))

    @classmethod
    def show(cls, image, box: dict):
        if cls.screen is not None:  # only the pixels that changed (a blinking cursor: just the cursor)
            import random
            key, now = (box["X"], box["Y"], image.width, image.height), time.monotonic()
            # ...and about once a minute the whole widget, should the screen have lost what it showed: each widget at
            # its own moment, so they never all go out together (a burst would hold up the radar's sweep)
            due = cls._repainted.setdefault(key, now + random.uniform(10, 60))
            full = image.width * image.height <= 20000 and now >= due
            if full:
                cls._repainted[key] = now + random.uniform(55, 65)
            cls.screen.DisplayPILImage(image, box["X"], box["Y"], full=full)
            return
        from library.display import display
        display.lcd.DisplayPILImage(image, box["X"], box["Y"])

    @classmethod
    def safely(cls, what: str, fn, *args):
        # A drawing error must not break the other custom sensors: log it once and carry on
        if not cls.enabled:
            return
        try:
            fn(*args)
        except Exception as e:
            if what not in cls._failed:
                cls._failed.add(what)
                logger.error("BC250: cannot draw %s: %s", what, e)


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class _Palette:
    """Optional fixed palette of the theme (bc250_palette in theme.yaml): None for free colours."""
    _loaded = False
    colors = None
    bg = None

    @classmethod
    def get(cls):
        if not cls._loaded:
            cls._loaded = True
            try:
                from library import config
                spec = (config.THEME_DATA or {}).get("bc250_palette") or {}
            except Exception:
                spec = {}
            if spec.get("COLORS"):
                cls.colors = [_Draw.color(c) for c in spec["COLORS"]]
                cls.bg = _Draw.color(spec.get("BG"), cls.colors[0])
        return cls

    @classmethod
    def snap(cls, color):
        if cls.get().colors is None:
            return color
        return min(cls.colors, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, color)))


def heat_color(value: float, spec: dict):
    """COLD_COLOR up to COLD, fading to HOT_COLOR at HOT, then to ALERT_COLOR at ALERT."""
    cold, hot = float(spec.get("COLD", 40)), float(spec.get("HOT", 70))
    alert = float(spec.get("ALERT", 80))
    cold_c = _Draw.color(spec.get("COLD_COLOR"), (125, 255, 165))
    hot_c = _Draw.color(spec.get("HOT_COLOR"), (255, 140, 30))
    alert_c = _Draw.color(spec.get("ALERT_COLOR"), (255, 60, 40))
    if value >= hot and alert > hot:
        return _Palette.snap(_lerp(hot_c, alert_c, min(1.0, (value - hot) / (alert - hot))))
    t = 0.0 if hot <= cold else max(0.0, min(1.0, (value - cold) / (hot - cold)))
    return _Palette.snap(_lerp(cold_c, hot_c, t))


def _dim(color, k: float):
    """A fainter version of color: towards black, or towards the palette's background when the theme has one."""
    palette = _Palette.get()
    if palette.colors is None:
        return tuple(int(c * k) for c in color)
    return palette.snap(_lerp(palette.bg, color, k))


def draw_heat_text(spec: dict, box: dict, value: Optional[float], flash: bool, unit: str = "°C"):
    from PIL import ImageDraw
    image = _Draw.crop(box)
    d = ImageDraw.Draw(image)
    font = _Draw.font(box["FONT"], box["FONT_SIZE"])
    text = f"--{unit}" if _is_nan(value) else f"{value:.0f}{unit}"
    color = _dim(heat_color(0, spec), 0.6) if _is_nan(value) else heat_color(value, spec)
    right = box.get("ALIGN") == "right"
    width = d.textlength(text, font=font)
    if flash:
        # inverse video: the value punched out of a solid alert block
        left = box["WIDTH"] - width - 4 if right else 0
        d.rectangle((left, 0, left + width + 3, box["HEIGHT"] - 1),
                    fill=_Draw.color(spec.get("ALERT_COLOR"), (255, 60, 40)))
        color = _Draw.color(spec.get("INK"), (2, 14, 6))
    x = (box["WIDTH"] - (2 if flash else 0)) if right else (1 if flash else 0)
    d.text((x, box.get("BASELINE", box["FONT_SIZE"] * 10 // 12)), text, font=font, fill=color,
           anchor="rs" if right else "ls")
    _Draw.show(image, box)


def draw_heat_bar(spec: dict, bar: dict, value: Optional[float]):
    """Progress bar whose fill is a gradient along its length: each column takes the colour of the value it stands
    for, so the tip of the bar always has the colour of the current value."""
    from PIL import ImageDraw
    image = _Draw.crop(bar)
    if not _is_nan(value):
        d = ImageDraw.Draw(image)
        w, h = bar["WIDTH"], bar["HEIGHT"]
        vmin, vmax = float(bar.get("MIN_VALUE", 0)), float(bar.get("MAX_VALUE", 100))
        filled = round(w * max(0.0, min(1.0, (value - vmin) / (vmax - vmin))))
        for px in range(filled):
            d.line((px, 0, px, h - 1), fill=heat_color(vmin + (px + 0.5) * (vmax - vmin) / w, spec))
    _Draw.show(image, bar)


def draw_alert_tag(spec: dict, tag: dict, flash: bool):
    from PIL import ImageDraw
    image = _Draw.crop(tag)
    if flash:
        d = ImageDraw.Draw(image)
        d.rectangle((0, 0, tag["WIDTH"] - 1, tag["HEIGHT"] - 1), fill=_Draw.color(spec.get("ALERT_COLOR")))
        d.text((tag["WIDTH"] // 2, tag["HEIGHT"] - 3), tag.get("TEXT", "HOT!"), font=_Draw.font(tag["FONT"], tag["FONT_SIZE"]),
               fill=_Draw.color(spec.get("INK"), (2, 14, 6)), anchor="ms")
    _Draw.show(image, tag)


def draw_heat_graph(spec: dict, graph: dict, values: List[float]):
    from PIL import ImageDraw

    w, h = graph["WIDTH"], graph["HEIGHT"]
    vmin, vmax = float(graph.get("MIN_VALUE", 30)), float(graph.get("MAX_VALUE", 90))
    axis_c = _Draw.color(graph.get("AXIS_COLOR"), (46, 170, 88))
    font = _Draw.font(graph["FONT"], graph.get("FONT_SIZE", 12))
    image = _Draw.crop(graph)
    d = ImageDraw.Draw(image)

    if graph.get("STYLE") in ("mosaic", "blocks"):
        # videotex: one column of separated 6x4 blocks per second, each block in the colour of its own height;
        # "blocks" (minecraft): the same with little cubes, lit on top and shaded underneath
        bw, bh = (int(v) for v in graph.get("BLOCK", (6, 4)))
        cubes = graph["STYLE"] == "blocks"
        columns, levels = w // bw, (h - 2) // bh
        recent = values[-columns:]
        for i, v in enumerate(recent):
            if _is_nan(v):
                continue
            x = (columns - len(recent) + i) * bw
            filled = max(1, round((max(vmin, min(vmax, v)) - vmin) / (vmax - vmin) * levels))
            for j in range(filled):
                y = (h - 2) - (j + 1) * bh
                block = heat_color(vmin + (j + 0.5) * (vmax - vmin) / levels, spec)
                d.rectangle((x, y + 1, x + bw - 2, y + bh - 1), fill=block)
                if cubes:
                    d.line((x, y + 1, x + bw - 2, y + 1), fill=_lerp(block, (255, 255, 255), 0.45))
                    d.line((x, y + bh - 1, x + bw - 2, y + bh - 1), fill=_lerp(block, (0, 0, 0), 0.4))
        d.text((0, 0), f"{vmax:.0f}", font=font, fill=axis_c, anchor="la")
        _Draw.show(image, graph)
        return

    def y_of(v):
        v = max(vmin, min(vmax, v))
        return (h - 2) - (v - vmin) * (h - 3) / (vmax - vmin)

    # Samples are placed by their index in the history, so the chart scrolls in from the right
    step = (w - 2) / max(1, len(values) - 1)
    points = [(1 + i * step, y_of(v), v) for i, v in enumerate(values) if not _is_nan(v)]

    # Area under the curve, drawn on every other screen row to match the background scanlines
    for (x1, y1, v1), (x2, y2, v2) in zip(points, points[1:]):
        for px in range(math.ceil(x1), math.floor(x2) + 1):
            t = (px - x1) / (x2 - x1) if x2 > x1 else 0.0
            top, value = y1 + (y2 - y1) * t, v1 + (v2 - v1) * t
            fill = _dim(heat_color(value, spec), 0.32)
            for py in range(math.ceil(top) + 1, h - 1):
                if (graph["Y"] + py) % 2 == 0:
                    image.putpixel((px, py), fill)

    # COLD / HOT threshold guides over the area, labelled at the right end
    for level_key, default in (("COLD", 40), ("HOT", 70)):
        level = float(spec.get(level_key, default))
        if vmin < level < vmax:
            ly = round(y_of(level))
            guide = _dim(heat_color(level, spec), 0.6)
            for gx in range(2, w - 16, 4):
                d.line((gx, ly, gx + 1, ly), fill=guide)
            d.text((w - 2, ly), f"{level:.0f}", font=font, fill=guide, anchor="rm")

    for (x1, y1, v1), (x2, y2, v2) in zip(points, points[1:]):
        d.line((x1, y1, x2, y2), fill=heat_color((v1 + v2) / 2, spec), width=2)

    d.line((0, 0, 0, h - 1), fill=axis_c)
    d.line((0, h - 1, w - 1, h - 1), fill=axis_c)
    d.text((3, 0), f"{vmax:.0f}", font=font, fill=axis_c, anchor="la")
    _Draw.show(image, graph)


class _TempWidget:
    """Base for temperature sensors that draw HEAT_TEXT + HEAT_GRAPH (+ ALERT_TAG) from their theme.yaml entry."""
    last_val: List[float] = []
    value = None
    _tick = 0
    _tag_lit = False

    def read(self) -> Optional[float]:
        raise NotImplementedError

    def as_numeric(self) -> float:
        cls = type(self)
        cls.value = self.read()
        cls._tick += 1
        _push(cls.last_val, cls.value)
        spec = _Draw.theme(cls.__name__)
        alert = not _is_nan(cls.value) and cls.value >= float(spec.get("ALERT", 80))
        flash = alert and cls._tick % 2 == 0
        if "HEAT_TEXT" in spec:
            _Draw.safely(cls.__name__ + " text", draw_heat_text, spec, spec["HEAT_TEXT"], cls.value, flash)
        if "HEAT_GRAPH" in spec:
            _Draw.safely(cls.__name__ + " graph", draw_heat_graph, spec, spec["HEAT_GRAPH"], cls.last_val)
        if "ALERT_TAG" in spec and (flash or cls._tag_lit):
            # Only redrawn while alerting, plus once more to restore the normal tag
            _Draw.safely(cls.__name__ + " tag", draw_alert_tag, spec, spec["ALERT_TAG"], flash)
            cls._tag_lit = flash
        return math.nan if cls.value is None else cls.value

    def as_string(self) -> str:
        return "--°C" if self.value is None else f"{self.value:.0f}°C"

    def last_values(self) -> List[float]:
        return type(self).last_val


def _attempt(what: str, fn, default=None):
    """fn() or default: one failing data source must not freeze the whole prompt line."""
    try:
        return fn()
    except Exception as e:
        if what not in _Draw._failed:
            _Draw._failed.add(what)
            logger.error("BC250: %s failed: %s", what, e)
        return default
