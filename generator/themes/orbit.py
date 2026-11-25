"""Orbit theme: a ground station tracking the ISS."""

import math

from PIL import Image, ImageDraw

from .. import cfg
from ..base import CH, CLOCK_CHARS, FONT, HEADER_BL, HEADER_H, M, ORBIT_LAYOUT, S, SM_WORLD
from ..draw import Canvas, heat_colors, rgb, text, world_map


# Orbit status line wording ("ON BOARD Hades II"; idle: "STATION KEEPING" / "all systems nominal")
ORBIT_WORDS = {"boot": "ACQUIRING", "now-playing": "ON BOARD", "downloading": "UPLINK", "installing": "DOCKING",
               "verifying": "SYSTEMS CHECK", "fossilize_replay": "CALIBRATING SHADERS", "last-session": "LAST EXPEDITION",
               "idle": "STATION KEEPING", "idle-text": "all systems nominal"}
OB_SEA, OB_LAND, OB_COAST, OB_GRATICULE = (16, 44, 76), (48, 88, 74), (88, 132, 124), (28, 58, 90)
OB_NIGHT = (0.32, 0.38, 0.55)  # what the night leaves of each colour
OB_SKY_RING = (36, 58, 88)
# what the ISS can fly over: SM_WORLD's shapes (in order), the big ones cut further where it makes sense, then the seas
OB_SHAPES = ("NORTH AMERICA", "GREENLAND", "SOUTH AMERICA", "AFRICA", "EURASIA", "AUSTRALIA", "THE BRITISH ISLES",
             "IRELAND", "ICELAND", "JAPAN", "INDONESIA", "BORNEO", "INDONESIA", "INDONESIA", "NEW GUINEA",
             "THE PHILIPPINES", "NEW ZEALAND", "MADAGASCAR", "CUBA", "ANTARCTICA")
OB_REGIONS = ("", "CANADA", "ALASKA", "THE UNITED STATES", "MEXICO", "CENTRAL AMERICA", "GREENLAND", "SOUTH AMERICA",
              "NORTH AFRICA", "AFRICA", "EUROPE", "TURKEY", "RUSSIA", "THE MIDDLE EAST", "CENTRAL ASIA", "INDIA",
              "CHINA", "MONGOLIA", "KOREA", "SOUTHEAST ASIA", "AUSTRALIA", "THE BRITISH ISLES", "IRELAND", "ICELAND",
              "JAPAN", "INDONESIA", "BORNEO", "NEW GUINEA", "THE PHILIPPINES", "NEW ZEALAND", "MADAGASCAR", "CUBA",
              "ANTARCTICA", "THE N. PACIFIC", "THE S. PACIFIC", "THE N. ATLANTIC", "THE S. ATLANTIC",
              "THE INDIAN OCEAN", "THE MEDITERRANEAN", "THE SOUTHERN OCEAN", "THE ARCTIC OCEAN", "THE CARIBBEAN",
              "THE GULF OF MEXICO", "THE BAY OF BENGAL", "THE ARABIAN SEA", "THE SOUTH CHINA SEA")


def ob_land(shape, lon, lat):
    """The name of a point of land, from its shape and where it lies (roughly: the map is coarse too)."""
    if shape == "NORTH AMERICA":
        if lon < -141:
            return "ALASKA"
        if lat >= 49 or (lon > -83 and lat >= 45.5):
            return "CANADA"
        if lat < 18.5 and lon > -94:
            return "CENTRAL AMERICA"
        if (lat < 32.5 and lon <= -106.5) or (lat < 29.5 and lon < -97) or (lat < 21.5 and lon < -86):
            return "MEXICO"
        return "THE UNITED STATES"
    if shape == "AFRICA":
        return "NORTH AFRICA" if lat >= 15 else "AFRICA"
    if shape == "EURASIA":
        if 26 <= lon < 45 and 36 <= lat < 42:
            return "TURKEY"
        if lon < 40 and lat >= 36:
            return "EUROPE"
        if lat >= 50:
            return "RUSSIA"
        if 35 <= lon < 62 and lat < 42:
            return "THE MIDDLE EAST"
        if 67 <= lon < 92 and lat < 30:
            return "INDIA"
        if lon >= 97 and lat < 22:
            return "SOUTHEAST ASIA"
        if 125 <= lon < 131 and 34 <= lat < 43:
            return "KOREA"
        if 88 <= lon < 120 and lat >= 42:
            return "MONGOLIA"
        if lon >= 73 and lat >= 18:
            return "CHINA"
        return "CENTRAL ASIA"
    return shape


def ob_regions():
    """What lies under each degree of the map (360x180, one byte per degree: an index into OB_REGIONS). Land comes
    from the map's own shapes; the oceans are filled from a point in each, with walls where they meet."""
    from collections import deque
    shapes = Image.new("L", (360, 180), 0)
    d = ImageDraw.Draw(shapes)
    for n, shape in enumerate(SM_WORLD, 1):
        d.polygon([(lon + 180, 90 - lat) for lon, lat in shape], fill=n)
    land = shapes.load()
    out = Image.new("L", (360, 180), 0)
    px = out.load()
    centre = lambda i, j: (-179.5 + i, 89.5 - j)
    ocean = {}
    walls = set()
    for lon, lats in ((-6, range(33, 41)), (20, range(-58, -33)), (147, range(-58, -35)), (142, range(-17, -7)),
                      (-68, range(-58, -53))):  # Gibraltar, south of Africa, of Tasmania, Torres Strait, Drake passage
        walls.update((lon + 180, 90 - lat) for lat in lats)
    queue = deque()
    for name, (lon, lat) in (("PACIFIC", (-150, 0)), ("ATLANTIC", (-30, 0)), ("INDIAN", (75, -15)),
                             ("MEDITERRANEAN", (18, 35))):
        queue.append((lon + 180, 90 - lat, name))
    while queue:  # every sea point goes to the ocean that reaches it first
        i, j, name = queue.popleft()
        if not (0 <= j < 180) or land[i % 360, j] or (i % 360, j) in walls or (i % 360, j) in ocean:
            continue
        ocean[(i % 360, j)] = name
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            queue.append(((i + di) % 360, j + dj, name))
    for j in range(180):
        for i in range(360):
            lon, lat = centre(i, j)
            if land[i, j]:
                name = ob_land(OB_SHAPES[land[i, j] - 1], lon, lat)
            elif lat > 66:
                name = "THE ARCTIC OCEAN"
            elif lat < -58:
                name = "THE SOUTHERN OCEAN"
            else:
                sea = ocean.get((i, j), "PACIFIC")
                if 95 <= lon < 130 and -9 <= lat < 25:  # between the islands, and the sea north of them
                    name = "INDONESIA" if lat < 0 else "THE SOUTH CHINA SEA" if lon < 121 else "THE N. PACIFIC"
                elif sea == "ATLANTIC" and 18 <= lat < 31 and -98 <= lon < -81:
                    name = "THE GULF OF MEXICO"
                elif sea == "ATLANTIC" and 9 <= lat < 22 and -88 <= lon < -60:
                    name = "THE CARIBBEAN"
                elif sea == "INDIAN" and 5 <= lat and 78 <= lon < 100:
                    name = "THE BAY OF BENGAL"
                elif sea == "INDIAN" and 5 <= lat and 50 <= lon < 78:
                    name = "THE ARABIAN SEA"
                elif sea in ("PACIFIC", "ATLANTIC"):
                    name = f"THE {'N' if lat >= 0 else 'S'}. {sea}"
                elif sea == "INDIAN":
                    name = "THE INDIAN OCEAN"
                else:
                    name = "THE MEDITERRANEAN"
            px[i, j] = OB_REGIONS.index(name)
    return out


def ob_world(w, h, lat_top):
    k = 4
    s = w * k / 360
    return world_map(w, h, lambda lon, lat: ((lon + 180) * s, (lat_top - lat) * s), OB_SEA, OB_LAND, OB_COAST,
                     OB_GRATICULE, k)


def render_background_orbit(title):
    """The ground station: the map in daylight (the sensors bring the night), the cards' headings, the chart of the
    sky (the horizon round the edge, 30° and 60° up, straight up in the middle, north on top), the readings."""
    ol = ORBIT_LAYOUT[cfg.PORTRAIT]
    c = Canvas()
    c.label(6, HEADER_BL, title, cfg.SKIN["mid"], glow=False)
    c.d.line((0, HEADER_H + 1, cfg.W, HEADER_H + 1), fill=cfg.SKIN["grid_dot"])
    x, y, w, h = ol["map"]
    c.img.paste(ob_world(w, h, ol["lat_top"]), (x, y))
    c.d.rectangle((x - 1, y - 1, x + w, y + h), outline=cfg.SKIN["dim"])
    cx, cy, _, _ = ol["card"]
    c.label(cx + 2, cy + 12, "ISS (ZARYA)", cfg.SKIN["dim"], glow=False)
    c.label(*ol["pass_heading"], "NEXT PASS", cfg.SKIN["dim"], glow=False)
    sx, sy, r = ol["sky"]
    for ring in (r / 3, 2 * r / 3):
        for a in range(0, 360, 15):
            c.d.point((round(sx + ring * math.sin(math.radians(a))), round(sy - ring * math.cos(math.radians(a)))),
                      fill=OB_SKY_RING)
    c.d.ellipse((sx - r, sy - r, sx + r, sy + r), outline=cfg.SKIN["dim"])
    for a in (90, 180, 270):  # east, south, west: a tick; north: its letter
        dx, dy = math.sin(math.radians(a)), -math.cos(math.radians(a))
        c.d.line((round(sx + dx * (r - 3)), round(sy + dy * (r - 3)), round(sx + dx * r), round(sy + dy * r)),
                 fill=cfg.SKIN["dim"])
    c.label(sx, sy - r - 2, "N", cfg.SKIN["dim"], anchor="ms", glow=False)
    c.d.point((sx, sy), fill=cfg.SKIN["dim"])
    for word, lx, bl, anchor in ol["labels"]:
        c.label(lx, bl, word, cfg.SKIN["dim"], anchor=anchor, glow=False)
    for line_ in ol["lines"]:
        c.d.line(line_, fill=cfg.SKIN["grid_dot"])
    c.dotted_hline(4, cfg.W - 4, cfg.PROMPT_Y)
    return c.finish()


def orbit_spec(title):
    ol = ORBIT_LAYOUT[cfg.PORTRAIT]
    header_x = 6 + len(title) * CH[S] + 12
    spec = {"MAP": list(ol["map"]), "LAT_TOP": ol["lat_top"], "NIGHT": list(OB_NIGHT), "REGIONS_IMAGE": "regions.png",
            "REGIONS": list(OB_REGIONS), "CARD": list(ol["card"]), "CARD_ROWS": list(ol["card_rows"]),
            "PASS": list(ol["pass_"]), "SKY": list(ol["sky"]), "PASS_SLOTS": [list(s) for s in ol["slots"]],
            "PASS_CHARS": 12, "HEADER": [header_x, HEADER_BL, cfg.CLOCK_XR - CLOCK_CHARS * CH[S] - 6], "FPS": 4, "TILE": 10,
            "FONT": FONT, "BACKGROUND_IMAGE": "background.png",
            "COLORS": {"BRIGHT": rgb(cfg.SKIN["value"]), "MID": rgb(cfg.SKIN["mid"]), "DIM": rgb(cfg.SKIN["dim"]),
                       "AMBER": rgb(cfg.SKIN["accent"]), "RED": rgb(cfg.SKIN["alert"]), "TRACK": rgb((255, 200, 90)),
                       "PAST": rgb((130, 160, 196)), "FOOTPRINT": rgb((150, 200, 245)), "SUN": rgb((255, 226, 110)),
                       "SITE": rgb((110, 240, 200)), "PANEL": rgb((214, 160, 60)), "RING": rgb((200, 150, 60))}}
    if cfg.ORBIT_SITE:
        spec.update({"LAT": round(cfg.ORBIT_SITE[0], 4), "LON": round(cfg.ORBIT_SITE[1], 4)})
    return spec


def orbit_theme(theme, title):
    """The orbit widget draws the map, the ISS and the two cards; the app keeps the clock, the readings, the status
    line and the screen power."""
    ol, custom = ORBIT_LAYOUT[cfg.PORTRAIT], theme["STATS"]["CUSTOM"]
    heat = lambda at: dict(heat_colors(cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT), INK=rgb(cfg.SKIN["ink"]),
                           HEAT_TEXT=text(at[0], at[1], M, 5, right=True))
    load = lambda at: text(at[0], at[1], M, 4)
    power = dict(heat_colors(cfg.POWER_LOW, (cfg.POWER_LOW + cfg.POWER_HIGH) // 2, cfg.POWER_HIGH),
                 HEAT_TEXT=text(ol["pwr"][0], ol["pwr"][1], M, 5, right=True))
    spec = orbit_spec(title)
    theme["STATS"] = {
        "CPU": {"PERCENTAGE": {"INTERVAL": 1, "TEXT": load(ol["cpu"][0])}},
        "MEMORY": {"INTERVAL": 2, "VIRTUAL": {"PERCENT_TEXT": load(ol["ram"])}},
        "DATE": {"INTERVAL": 1, "HOUR": {"TEXT": text(cfg.CLOCK_XR, HEADER_BL, S, CLOCK_CHARS, cfg.SKIN["value"], right=True,
                                                      FORMAT="HH:mm:ss")}},
        "CUSTOM": {
            "INTERVAL": 1,
            "Bc250CpuTemp": heat(ol["cpu"][1]),
            "Bc250GpuTemp": heat(ol["gpu"][1]),
            "Bc250GpuLoad": {"TEXT": load(ol["gpu"][0])},
            "Bc250ApuPower": power,
            "Bc250Orbit": spec,
            "Bc250Prompt": custom["Bc250Prompt"],
            "Bc250Screen": custom["Bc250Screen"],
        },
    }
    theme["bc250_splash"].update({k: v for k, v in spec.items() if k != "BACKGROUND_IMAGE"})
    theme["bc250_splash"].update({"STYLE": "orbit", "IMAGE": "background.png", "LOG": list(ol["log"]),
                                  "LOG_COLUMNS": ol["log_columns"], "LOG_STEP": ol["log_step"]})
    return theme
