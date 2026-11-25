"""Drawing and writing shared by every theme: fonts, Canvas, text and widget boxes for theme.yaml, YAML
output, the world map."""

import math
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import cfg
from .base import ASCENT, CH, CLOCK_CHARS, DMG, FONT, M, S, SM_WORLD


def logo_size(text):
    """Largest crisp size (a multiple of the pixel font's 12 px) at which the logo fits its box."""
    for size in (72, 60, 48, 36, 24):
        if len(text) * size // 2 <= cfg.SPLASH_LAYOUT["logo_max_w"]:
            return size
    return 24


def logo_baseline(size):
    return cfg.SPLASH_LAYOUT["logo_center_y"] + size * 8 // 12 // 2  # cap height is 8/12 of the size


def spaced(text):
    """S T E A M   M A C H I N E"""
    return "   ".join(" ".join(word) for word in text.split())


def rgb(c):
    return f"{c[0]}, {c[1]}, {c[2]}"


# ---------------------------------------------------------------------------------------------------------------------
# theme.yaml helpers
# ---------------------------------------------------------------------------------------------------------------------
def text(x, baseline, size, chars, color=None, unit=True, right=False, extra_height=0, **extra):
    """A live text in a fixed box. x is the left edge, or the right edge when right=True."""
    width = chars * CH[size]
    t = {"SHOW": True, "SHOW_UNIT": unit,
         "X": x - width if right else x, "Y": baseline - ASCENT[size],
         "WIDTH": width, "HEIGHT": size + extra_height,
         "FONT": FONT, "FONT_SIZE": size, "FONT_COLOR": rgb(color or cfg.SKIN["value"]),
         "BACKGROUND_IMAGE": "background.png",
         "ALIGN": "right" if right else "left", "ANCHOR": "ra" if right else "la"}
    if not right:
        t["MIN_SIZE"] = 1  # no left padding: value starts exactly at X
    t.update(extra)
    return t


def bar(x, y, w, h, color=None, max_value=100):
    return {"SHOW": True, "X": x, "Y": y, "WIDTH": w, "HEIGHT": h, "MIN_VALUE": 0, "MAX_VALUE": max_value,
            "BAR_COLOR": rgb(color or cfg.SKIN.get("bar") or (cfg.SKIN["mid"] if cfg.SKIN_NAME == "gameboy" else cfg.SKIN["value"])),
            "BAR_OUTLINE": False, "BACKGROUND_IMAGE": "background.png"}


def line(x, y, w, h, max_value=100, history=48, autoscale=False, color=None):
    return {"SHOW": True, "X": x, "Y": y, "WIDTH": w, "HEIGHT": h, "MIN_VALUE": 0, "MAX_VALUE": max_value,
            "HISTORY_SIZE": history, "AUTOSCALE": autoscale,
            "LINE_COLOR": rgb(color or (cfg.SKIN["mid"] if cfg.SKIN_NAME == "videotex" else cfg.SKIN["value"])),
            "LINE_WIDTH": 1, "AXIS": False, "BACKGROUND_IMAGE": "background.png"}


def heat_colors(cold, hot, alert):
    return {"COLD": cold, "HOT": hot, "ALERT": alert, "COLD_COLOR": rgb(cfg.SKIN["cold"]), "HOT_COLOR": rgb(cfg.SKIN["hot"]),
            "ALERT_COLOR": rgb(cfg.SKIN["alert"])}


def heat_widget(p):
    """Temperature drawn by sensors_bc250: value and history shaded from cold to hot, flashing HOT! from ALERT."""
    graph, temp = p["graph"], p["temp"]
    widget = heat_colors(cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT)
    widget.update({
        "INK": rgb(cfg.SKIN["ink"]),
        "HEAT_TEXT": text(temp["x"], temp["bl"], M, 5, right=temp["right"]),
        "ALERT_TAG": {"X": p["tag"][0], "Y": p["tag"][1], "WIDTH": p["tag"][2], "HEIGHT": p["tag"][3],
                      "FONT": FONT, "FONT_SIZE": S,
                      "BACKGROUND_IMAGE": "background.png"},
        "HEAT_GRAPH": {"X": graph[0], "Y": graph[1], "WIDTH": graph[2], "HEIGHT": graph[3],
                       "MIN_VALUE": cfg.TEMP_GRAPH_MIN, "MAX_VALUE": cfg.TEMP_GRAPH_MAX, "AXIS_COLOR": rgb(cfg.SKIN["mid"]),
                       "FONT": FONT, "FONT_SIZE": S, "BACKGROUND_IMAGE": "background.png"},
    })
    if cfg.SKIN_NAME == "videotex":  # history as a bar chart of separated mosaic blocks
        widget["HEAT_GRAPH"]["STYLE"] = "mosaic"
    if cfg.SKIN_NAME == "mission":
        widget["ALERT_TAG"]["TEXT"] = "ALARM"
    if cfg.SKIN_NAME == "halloween":
        widget["ALERT_TAG"]["TEXT"] = "BOO!"
    if cfg.SKIN_NAME == "christmas":
        widget["ALERT_TAG"]["TEXT"] = "MELT"
    if cfg.SKIN_NAME == "minecraft":  # history as a column of little blocks
        widget["HEAT_GRAPH"].update({"STYLE": "blocks", "BLOCK": [6, 6]})
    return widget


def _needs_quotes(v):
    """Whether a string would not read back as the same string unquoted: options like --logo and --user end up in
    theme.yaml, and a text such as "[RIG]", "& CO", "2024" or "~" would otherwise break it or change type."""
    return (any(c in v for c in ":#\"@'\n\t") or v != v.strip() or v == "" or v[0] in "[]{}&*!|>%`,?-"
            or v.lower() in ("on", "off", "yes", "no", "true", "false", "null", "~")
            or re.fullmatch(r"[-+]?(\d[\d_]*(\.\d*)?|\.\d+)([eE][-+]?\d+)?|0x[\da-fA-F_]+|0o[0-7_]+"
                            r"|[-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN)", v) is not None)


def to_yaml(data, indent=0):
    out = []
    for k, v in data.items():
        pad = "  " * indent
        if isinstance(v, dict):
            out.append(f"{pad}{k}:")
            out.append(to_yaml(v, indent + 1))
        elif isinstance(v, bool):
            out.append(f"{pad}{k}: {v}")
        elif isinstance(v, str) and _needs_quotes(v):
            if '"' not in v and "\\" not in v:
                out.append(f'{pad}{k}: "{v}"')
            else:  # single quotes: no escapes inside, a ' is written twice
                out.append(f"{pad}{k}: '" + v.replace("'", "''") + "'")
        else:
            out.append(f"{pad}{k}: {v}")
    return "\n".join(out)


def header_layout(title):
    """x of the "UP" label, x of the uptime value and its width in characters (0 = no room for it)."""
    up_x = 6 + len(title) * CH[S] + 12
    uptime_x = up_x + 3 * CH[S]
    room_right = (cfg.DATE_XR - 14 * CH[S]) if cfg.DATE_XR else (cfg.CLOCK_XR - CLOCK_CHARS * CH[S])
    chars = min(20, (room_right - 8 - uptime_x) // CH[S])
    return up_x, uptime_x, (chars if chars >= 8 else 0)


def prompt_prefix(user, prompt):
    """What precedes the live command word in the prompt's label row."""
    return {"gameboy": user.upper(), "retrowave": f"1UP {user.upper()}", "videotex": "", "mission": "",
            "minecraft": "", "nixie": "", "radar": "", "halloween": "", "christmas": "", "horror": "", "seismograph": "",
            "orbit": "", "departures": "", "racing": ""}.get(cfg.SKIN_NAME, prompt)


# ---------------------------------------------------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------------------------------------------------
def font(size):
    return font_file(FONT, size)


def font_file(name, size):
    # the basic layout engine everywhere: with libraqm (Linux) kerning would change text widths, so the themes
    # would come out differently than on a machine without it
    return ImageFont.truetype(str(cfg.FONTS_DIR / name), size, layout_engine=ImageFont.Layout.BASIC)


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Canvas:
    def __init__(self):
        self.img = Image.new("RGB", (cfg.W, cfg.H), cfg.SKIN["bg"])
        self.glow = Image.new("RGB", (cfg.W, cfg.H), (0, 0, 0))  # what gets the phosphor bloom
        self.d, self.g = ImageDraw.Draw(self.img), ImageDraw.Draw(self.glow)
        self.crt = []  # mission control: the boxes that get scanlines (the console itself doesn't)

    def label(self, x, baseline, s, color=None, anchor="ls", size=S, glow=True):
        color = color or cfg.SKIN["mid"]
        self.d.text((x, baseline), s, font=font(size), fill=color, anchor=anchor)
        if glow:
            self.g.text((x, baseline), s, font=font(size), fill=color, anchor=anchor)

    def tag(self, x, y, title, subtitle=None):
        """Inverse-video tag centred on a frame's top line, e.g. [CPU] ZEN2 6C/12T"""
        w = len(title) * CH[S] + 8
        self.d.rectangle((x, y - 6, x + w - 1, y + 6), fill=cfg.SKIN["mid"])
        self.label(x + 4, y + 4, title, cfg.SKIN["ink"], glow=False)
        if subtitle:
            sx = x + w + 4
            self.d.rectangle((sx - 3, y - 6, sx + len(subtitle) * CH[S] + 2, y + 6), fill=cfg.SKIN["bg"])
            self.label(sx, y + 4, subtitle)

    def frame(self, box, title=None, subtitle=None):
        x1, y1, x2, y2 = box
        self.d.rectangle(box, outline=cfg.SKIN["dim"])
        for cx, cy, sx, sy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
            self.d.line((cx, cy, cx + 8 * sx, cy), fill=cfg.SKIN["mid"])  # brighter HUD corners
            self.d.line((cx, cy, cx, cy + 8 * sy), fill=cfg.SKIN["mid"])
        if title:
            self.tag(x1 + 8, y1, title, subtitle)

    def rpg_box(self, box, title=None, inner=True):
        """Game Boy RPG menu box: thick darkest outline with cut corners, thin inner line, optional title tab."""
        x1, y1, x2, y2 = box
        dark, mid, bg = DMG[3], DMG[2], cfg.SKIN["bg"]
        self.d.rectangle((x1 + 2, y1, x2 - 2, y1 + 1), fill=dark)
        self.d.rectangle((x1 + 2, y2 - 1, x2 - 2, y2), fill=dark)
        self.d.rectangle((x1, y1 + 2, x1 + 1, y2 - 2), fill=dark)
        self.d.rectangle((x2 - 1, y1 + 2, x2, y2 - 2), fill=dark)
        for cx, cy in ((x1 + 1, y1 + 1), (x2 - 1, y1 + 1), (x1 + 1, y2 - 1), (x2 - 1, y2 - 1)):
            self.d.point((cx, cy), fill=dark)  # rounded pixel corners
        if inner:
            self.d.rectangle((x1 + 4, y1 + 4, x2 - 4, y2 - 4), outline=mid)
        if title:
            tw = len(title) * CH[S] + 8
            self.d.rectangle((x1 + 10, y1 - 1, x1 + 10 + tw, y1 + 5), fill=bg)
            self.label(x1 + 14, y1 + 5, title, dark, glow=False)

    def hp_bar(self, x, y, w, h, label="HP"):
        """Track of an RPG HP bar: small label, then a capsule outline the app fills."""
        dark = DMG[3]
        self.d.rectangle((x - 2, y - 2, x + w + 1, y + h + 1), outline=dark)
        self.d.rectangle((x - 1, y - 1, x + w, y + h), fill=cfg.SKIN["bg"])
        self.label(x - 4 - len(label) * CH[S], y + h, label, dark, glow=False)

    def bar_track(self, x, y, w, h, ticks=True):
        for px in range(x, x + w, 2):
            self.d.point((px, y + h // 2), fill=cfg.SKIN["dim"])
        if ticks:
            for i in range(5):
                tx = x + round(i * (w - 1) / 4)
                self.d.line((tx, y + h + 1, tx, y + h + 2), fill=cfg.SKIN["dim"])

    def graph_grid(self, x, y, w, h):
        for gy in range(y, y + h, 8):
            for gx in range(x, x + w, 4):
                self.d.point((gx, gy), fill=cfg.SKIN["grid_dot"])
        for gx in range(x, x + w, 32):
            for gy in range(y, y + h, 2):
                self.d.point((gx, gy), fill=cfg.SKIN["grid_dot"])

    def dotted_hline(self, x1, x2, y):
        for sx in range(x1, x2, 3):
            self.d.point((sx, y), fill=cfg.SKIN["dim"])

    def dotted_vline(self, x, y1, y2):
        for sy in range(y1, y2, 3):
            self.d.point((x, sy), fill=cfg.SKIN["dim"])

    def finish(self):
        if cfg.SKIN_NAME == "gameboy":
            return self.lcd_grid(self.img)
        if cfg.SKIN_NAME in ("videotex", "minecraft", "nixie", "radar", "horror", "seismograph", "orbit",
                         "departures", "racing"):  # flat colours
            return self.img
        if cfg.SKIN_NAME in ("halloween", "christmas"):  # candle-lit text and dark corners, no scanlines
            img = ImageChops.add(self.img, self.glow.filter(ImageFilter.GaussianBlur(2)).point(lambda v: int(v * 0.4)))
            px = img.load()
            cx, cy = cfg.W / 2, cfg.H / 2
            max_r = math.hypot(cx, cy)
            for y in range(cfg.H):
                for x in range(cfg.W):
                    k = 1.0 - 0.42 * (math.hypot(x - cx, y - cy) / max_r) ** 2.4
                    r, g, b = px[x, y]
                    px[x, y] = (int(r * k), int(g * k), int(b * k))
            return img
        if cfg.SKIN_NAME == "mission":  # soft glow of the text, scanlines on the CRT glass only
            img = ImageChops.add(self.img, self.glow.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.45)))
            shade = Image.new("L", (cfg.W, cfg.H), 255)
            sd = ImageDraw.Draw(shade)
            for x1, y1, x2, y2 in self.crt:
                for y in range(y1 + 1, y2):
                    if y % 2:
                        sd.line((x1 + 1, y, x2 - 1, y), fill=212)
            return ImageChops.multiply(img, shade.convert("RGB"))
        retro = cfg.SKIN_NAME == "retrowave"  # neon: stronger bloom, lighter scanlines and vignette
        bloom = self.glow.filter(ImageFilter.GaussianBlur(3))
        img = ImageChops.add(self.img, bloom.point(lambda v: int(v * (0.7 if retro else 0.55))))
        # vignette + scanlines (dark rows are the odd ones: sensors_bc250 draws its chart fills on even rows)
        px = img.load()
        cx, cy = cfg.W / 2, cfg.H / 2
        max_r = math.hypot(cx, cy)
        dark_row, vignette = (0.86, 0.3) if retro else (0.78, 0.45)
        for y in range(cfg.H):
            scan = dark_row if y % 2 else 1.0
            for x in range(cfg.W):
                k = scan * (1.0 - vignette * (math.hypot(x - cx, y - cy) / max_r) ** 2.2)
                r, g, b = px[x, y]
                px[x, y] = (int(r * k), int(g * k), int(b * k))
        return img

    @staticmethod
    def lcd_grid(img):
        """The DMG's visible pixel grid: every 3rd row and column of the bare background a touch darker."""
        px = img.load()
        bg, line_color = cfg.SKIN["bg"], mix(DMG[0], DMG[1], 0.45)
        for y in range(cfg.H):
            for x in range(cfg.W):
                if (x % 3 == 2 or y % 3 == 2) and px[x, y] == bg:
                    px[x, y] = line_color
        return img


def world_map(w, h, project, sea, land, coast, graticule, k=4):
    """The continents of SM_WORLD on a grid every 30 degrees, drawn k times larger then reduced. project(lon, lat)
    gives the point in the large picture."""
    image = Image.new("RGB", (w * k, h * k), sea)
    d = ImageDraw.Draw(image)
    for lon in range(-150, 180, 30):
        d.line((project(lon, 90), project(lon, -90)), fill=graticule, width=k // 2)
    for lat in range(-60, 90, 30):
        d.line((project(-180, lat), project(180, lat)), fill=graticule, width=k // 2)
    for shape in SM_WORLD:
        points = [project(*p) for p in shape]
        d.polygon(points, fill=land)
        d.line(points + points[:1], fill=coast, width=k)
    return image.resize((w, h), Image.LANCZOS)


def parse_coordinate(text):
    """48.86 or 48°51'30"N style: decimal degrees (S and W negative)."""
    text = text.strip().upper()
    match = re.match(r"^([\d.]+)\s*[°D]\s*(?:([\d.]+)\s*['M′])?\s*(?:([\d.]+)\s*(?:\"|''|S|″)?)?\s*([NSEW])?$", text)
    if match and ("°" in text or "D" in text):
        degrees = float(match.group(1)) + float(match.group(2) or 0) / 60 + float(match.group(3) or 0) / 3600
        return -degrees if match.group(4) in ("S", "W") else degrees
    return float(text)
