"""Radar theme: live aircraft around a point, on a radar scope."""

import math
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw

from .. import cfg
from ..base import CLOCK_CHARS, FONT, HEADER_BL, HEADER_H, M, S
from ..draw import Canvas, heat_colors, rgb, text
from ..registry import Theme


# Radar status line wording
RADAR_WORDS = {"boot": "STARTING", "now-playing": "NOW PLAYING", "downloading": "DOWNLOADING", "installing": "INSTALLING",
               "verifying": "VERIFYING", "fossilize_replay": "SHADERS", "last-session": "LAST GAME", "idle": "STANDBY",
               "idle-text": "on watch"}
RD_DISC, RD_RIM, RD_RING, RD_TICK = (2, 16, 6), (40, 140, 60), (14, 66, 28), (40, 130, 60)
RD_LINE = (10, 42, 18)  # separators
RD_COLOURS = dict(SWEEP=(150, 255, 160), LOW=(230, 255, 110), MID=(110, 255, 140), HIGH=(60, 205, 165),
                  EMERGENCY=(255, 70, 60), TEXT=(200, 255, 210), LABEL=(90, 190, 110), DIM=(50, 120, 70),
                  ROUTE=(230, 255, 110))
OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/{}.csv"


def radar_map(lat, lon, km):
    """Airports (large and medium with their runways, small ones as dots) within range, from OurAirports (public
    domain), downloaded once into ~/.cache/bc250-themes. Without network the scope just has no map."""
    import csv
    import urllib.request
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "bc250-themes"
    kx, ky = 111.32 * math.cos(math.radians(lat)), 110.57
    tables = {}
    for name in ("airports", "runways"):
        path = cache / f"{name}.csv"
        try:
            if not path.is_file() or time.time() - path.stat().st_mtime > 90 * 86400:
                cache.mkdir(parents=True, exist_ok=True)
                print(f"Downloading OurAirports {name} (once, for the radar map)...")
                request = urllib.request.Request(OURAIRPORTS.format(name), headers={"User-Agent": "bc250-themes"})
                with urllib.request.urlopen(request, timeout=60) as answer:
                    path.write_bytes(answer.read())
            with open(path, encoding="utf-8") as f:
                tables[name] = list(csv.DictReader(f))
        except Exception as e:
            print(f"note: no radar map ({name}: {e})")
            return [], []
    near = lambda la, lo: ((float(lo) - lon) * kx, (float(la) - lat) * ky)
    airports, runways, shown = [], [], {}
    for a in tables["airports"]:
        if a["type"] not in ("large_airport", "medium_airport", "small_airport"):
            continue
        try:
            x, y = near(a["latitude_deg"], a["longitude_deg"])
        except ValueError:
            continue
        if math.hypot(x, y) <= km:
            label = a["iata_code"] or a["ident"]
            airports.append((x, y, label, a["type"]))
            shown[a["ident"]] = a["type"]
    for r in tables["runways"]:
        if shown.get(r["airport_ident"]) not in ("large_airport", "medium_airport") or r["closed"] == "1":
            continue
        try:
            runways.append((near(r["le_latitude_deg"], r["le_longitude_deg"]), near(r["he_latitude_deg"], r["he_longitude_deg"])))
        except ValueError:
            continue
    return airports, runways


TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def radar_terrain(lat, lon, km, r):
    """A faint relief map for the scope: hillshade lit from the north-west plus contour lines, in the scope's dark
    greens, as an RGB image of (2r+1)^2 pixels. Elevation from the public Terrain Tiles on AWS (no key), downloaded
    once into ~/.cache/bc250-themes/terrain; None without network."""
    import io
    import urllib.request
    import numpy
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "bc250-themes" / "terrain"
    km_per_px = km / r
    zoom = max(3, min(11, math.ceil(math.log2(40075 * math.cos(math.radians(lat)) / 256 / km_per_px))))
    n = 2 ** zoom

    # the latitude / longitude under every pixel of the scope (same flat projection as the radar's blips)
    kx, ky = 111.32 * math.cos(math.radians(lat)), 110.57
    offsets = (numpy.arange(2 * r + 1) - r) * km_per_px
    lons = lon + offsets[None, :] / kx
    lats = lat - offsets[:, None] / ky
    gx = (lons + 180) / 360 * n * 256  # Web Mercator pixel coordinates of the tile pyramid
    gy = (1 - numpy.arcsinh(numpy.tan(numpy.radians(lats))) / math.pi) / 2 * n * 256
    gx, gy = numpy.broadcast_to(gx, (2 * r + 1, 2 * r + 1)), numpy.broadcast_to(gy, (2 * r + 1, 2 * r + 1))
    tx0, tx1 = int(gx.min() // 256), int(gx.max() // 256)
    ty0, ty1 = int(gy.min() // 256), int(gy.max() // 256)

    mosaic = numpy.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), numpy.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            path = cache / f"{zoom}_{tx % n}_{ty}.png"
            try:
                if not path.is_file():
                    cache.mkdir(parents=True, exist_ok=True)
                    request = urllib.request.Request(TERRAIN_TILES.format(z=zoom, x=tx % n, y=ty),
                                                     headers={"User-Agent": "bc250-themes"})
                    with urllib.request.urlopen(request, timeout=30) as answer:
                        path.write_bytes(answer.read())
                rgb_ = numpy.asarray(Image.open(path).convert("RGB"), numpy.float32)
            except Exception as e:
                print(f"note: no terrain on the radar ({e})")
                return None
            elevation = rgb_[..., 0] * 256 + rgb_[..., 1] + rgb_[..., 2] / 256 - 32768  # "terrarium" encoding
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = elevation
    # bilinear sampling of the mosaic under each scope pixel
    fx, fy = gx - tx0 * 256, gy - ty0 * 256
    x0 = numpy.clip(numpy.floor(fx).astype(int), 0, mosaic.shape[1] - 2)
    y0 = numpy.clip(numpy.floor(fy).astype(int), 0, mosaic.shape[0] - 2)
    ax, ay = numpy.clip(fx - x0, 0, 1), numpy.clip(fy - y0, 0, 1)
    elev = (mosaic[y0, x0] * (1 - ax) * (1 - ay) + mosaic[y0, x0 + 1] * ax * (1 - ay)
            + mosaic[y0 + 1, x0] * (1 - ax) * ay + mosaic[y0 + 1, x0 + 1] * ax * ay)
    elev = numpy.maximum(elev, 0)  # the sea stays flat
    for _ in range(2):  # a light blur: smoother contours, no speckle from the data's noise
        padded = numpy.pad(elev, 1, mode="edge")
        elev = sum(padded[dy:dy + elev.shape[0], dx:dx + elev.shape[1]] for dy in range(3) for dx in range(3)) / 9

    # hillshade: light from the north-west, relief exaggerated so gentle hills still show
    spacing = km_per_px * 1000
    exaggeration = 4.0
    dz_east = numpy.gradient(elev, axis=1) / spacing * exaggeration
    dz_north = -numpy.gradient(elev, axis=0) / spacing * exaggeration
    light = numpy.array([-0.5, 0.5, 0.707]) / numpy.linalg.norm([-0.5, 0.5, 0.707])
    shade = (-dz_east * light[0] - dz_north * light[1] + light[2]) / numpy.sqrt(dz_east ** 2 + dz_north ** 2 + 1)
    relief = numpy.clip((shade - light[2]) * 2.2, -1, 1)  # -1 in shadow .. 0 flat .. 1 facing the light
    height = (elev - elev.min()) / max(1.0, float(elev.max() - elev.min()))

    base = numpy.array(RD_DISC, numpy.float32)
    lit, dark = numpy.array((6, 50, 18), numpy.float32), numpy.array((-2, -12, -5), numpy.float32)
    colour = (base + numpy.where(relief[..., None] > 0, relief[..., None] * lit, -relief[..., None] * dark)
              + height[..., None] * numpy.array((1, 8, 3), numpy.float32))

    # contour lines, every 5th one a little brighter, as on a topographic chart
    span = float(elev.max() - elev.min())
    interval = next((v for v in (50, 100, 200, 250, 500, 1000) if span / v <= 6), 1000)
    band = numpy.floor(elev / interval).astype(int)
    edge = numpy.zeros(band.shape, bool)
    edge[:, :-1] |= band[:, :-1] != band[:, 1:]
    edge[:-1, :] |= band[:-1, :] != band[1:, :]
    major = edge & (numpy.maximum(band, numpy.roll(band, -1, 1)) % 5 == 0)
    colour[edge] = (6, 40, 16)
    colour[major] = (10, 58, 24)
    return Image.fromarray(numpy.clip(colour, 0, 255).astype(numpy.uint8), "RGB")


def nice_step(km):
    return next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200) if km / s <= 5)


def draw_scope(c, rings=True):
    cx, cy, r = cfg.RADAR["scope"]
    c.d.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), fill=(6, 26, 10))
    c.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RD_DISC, outline=RD_RIM, width=2)
    if not rings:
        return
    if cfg.RADAR.get("terrain") is not None:  # the relief, inside the rim
        disc = Image.new("L", cfg.RADAR["terrain"].size, 0)
        ImageDraw.Draw(disc).ellipse((2, 2, 2 * r - 2, 2 * r - 2), fill=255)
        c.img.paste(cfg.RADAR["terrain"], (cx - r, cy - r), disc)
    km, (lat, lon) = cfg.RADAR["km"], cfg.RADAR["center"]
    k = r / km
    step = nice_step(km)
    for ring in range(step, int(km) + 1, step):
        rr = ring * k
        if rr < r - 3:
            c.d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=RD_RING)
            a = math.radians(135)
            c.label(round(cx + rr * math.sin(a)) + 2, round(cy - rr * math.cos(a)) - 2, str(ring), RD_RING, glow=False)
    for deg in range(0, 360, 10):
        a = math.radians(deg)
        inner = r - (7 if deg % 30 == 0 else 3)
        c.d.line((cx + inner * math.sin(a), cy - inner * math.cos(a), cx + (r - 1) * math.sin(a), cy - (r - 1) * math.cos(a)),
                 fill=RD_TICK)
    for deg, letter in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        a = math.radians(deg)
        c.label(round(cx + (r - 15) * math.sin(a)), round(cy - (r - 15) * math.cos(a)) + 4, letter, RD_TICK,
                anchor="ms", glow=False)
    airports, runways = cfg.RADAR["map"]
    for (x1, y1), (x2, y2) in runways:
        c.d.line((cx + x1 * k, cy - y1 * k, cx + x2 * k, cy - y2 * k), fill=(90, 175, 110), width=2)
    for x, y, label, kind in airports:
        px, py = cx + x * k, cy - y * k
        if kind == "small_airport":
            c.d.point((px, py), fill=RD_TICK)
        else:
            c.label(round(px) + 6, round(py) + 12, label, (60, 140, 80), glow=False)
    c.d.line((cx - 4, cy, cx + 4, cy), fill=RD_TICK)  # the radar's position
    c.d.line((cx, cy - 4, cx, cy + 4), fill=RD_TICK)


def render_background_radar(title):
    c = Canvas()
    c.label(6, HEADER_BL, title, cfg.SKIN["value"], glow=False)
    c.d.line((0, HEADER_H + 1, cfg.W, HEADER_H + 1), fill=RD_LINE)
    draw_scope(c)
    rd = cfg.RADAR
    lx1, ly1, lx2, ly2 = rd["list"]
    if rd["list_columns"] == 1:  # (portrait has no room for the heading)
        c.label(lx1, ly1 + 10, "NEXT", RD_COLOURS["DIM"], glow=False)
    c.d.line((rd["card"][0], rd["card"][3] + 2, rd["card"][2], rd["card"][3] + 2), fill=RD_LINE)
    for label, (x, bl, _, _) in zip(("CPU", "GPU"), rd["stats"]):
        c.label(x, bl, label, RD_COLOURS["DIM"], glow=False)
    c.d.line((rd["prompt_line"][0], rd["prompt_line"][1], rd["prompt_line"][2], rd["prompt_line"][1]), fill=RD_LINE)
    return c.finish()


def radar_spec():
    rd = cfg.RADAR
    spec = {"LAT": round(rd["center"][0], 5), "LON": round(rd["center"][1], 5), "RANGE_KM": rd["km"], "REFRESH": 6,
            "PERIOD": 5, "FPS": 8, "TRAIL": 0, "TILE": 10, "TAGS": 8, "FONT": FONT, "SCOPE": list(rd["scope"]), "CARD": list(rd["card"]),
            "CARD_ROWS": rd["card_rows"], "CARD_STYLE": rd["card_style"], "LIST": list(rd["list"]),
            "LIST_BL": rd["list_bl"], "LIST_STEP": 14, "LIST_ROWS": rd["list_rows"], "LIST_COLUMNS": rd["list_columns"],
            "COUNT": list(rd["count"]), "BACKGROUND_IMAGE": "background.png"}
    spec["COLORS"] = {k: rgb(v) for k, v in RD_COLOURS.items()}  # not at the top: the app reads a TEXT key as a widget
    return spec


def radar_theme(theme):
    """The radar widget draws the scope and the flight panel; the app keeps the clock, the CPU/GPU readings, the
    prompt and the screen power."""
    rd, custom = cfg.RADAR, theme["STATS"]["CUSTOM"]
    (cpu_x, cpu_bl, cpu_temp_x, cpu_load_xr), (gpu_x, gpu_bl, gpu_temp_x, gpu_load_xr) = rd["stats"]
    heat = lambda x, bl: dict(heat_colors(cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT), INK=rgb(cfg.SKIN["ink"]),
                              HEAT_TEXT=text(x, bl, M, 5))
    theme["STATS"] = {
        "CPU": {"PERCENTAGE": {"INTERVAL": 1, "TEXT": text(cpu_load_xr, cpu_bl, M, 4, right=True)}},
        "DATE": {"INTERVAL": 1, "HOUR": {"TEXT": text(cfg.CLOCK_XR, HEADER_BL, S, CLOCK_CHARS, cfg.SKIN["value"], right=True,
                                                      FORMAT="HH:mm:ss")}},
        "CUSTOM": {
            "INTERVAL": 1,
            "Bc250CpuTemp": heat(cpu_temp_x, cpu_bl),
            "Bc250GpuTemp": heat(gpu_temp_x, gpu_bl),
            "Bc250GpuLoad": {"TEXT": text(gpu_load_xr, gpu_bl, M, 4, right=True)},
            "Bc250Radar": radar_spec(),
            "Bc250Prompt": custom["Bc250Prompt"],
            "Bc250Screen": custom["Bc250Screen"],
        },
    }
    theme["bc250_splash"].update({k: v for k, v in radar_spec().items() if k != "BACKGROUND_IMAGE"})
    return theme


def render(out, title, prompt, user):
    """Its artwork, into the theme's folder out."""
    render_background_radar(title).save(out / "background.png")
    for old in ("splash.png", "splash_blank.png"):  # the boot now runs on background.png
        (out / old).unlink(missing_ok=True)


def status_line(user):
    """Its words and colours on the status line (Bc250Prompt)."""
    return {"CMD_WORDS": RADAR_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["mid"]), "SMALL_FALLBACK": True,
            "COL_WORDS": {"SESSION": "TIME", "PEAK C/G": "PEAK", "SHADERS": "DONE"}}


def boot():
    """Its part of bc250_splash in theme.yaml."""
    sl = cfg.SPLASH_LAYOUT
    cx, cy, r = cfg.RADAR["scope"]
    step = nice_step(cfg.RADAR["km"])
    rings = [round(ring * r / cfg.RADAR["km"]) for ring in range(step, int(cfg.RADAR["km"]) + 1, step)]
    return {"STYLE": "radar", "IMAGE": "background.png", "LOG": list(sl["log"]),
            "RINGS": [v for v in rings if v < r - 3] + [r - 1],
            "MAP_COUNT": sum(1 for a in cfg.RADAR["map"][0] if a[3] != "small_airport")}


THEME = Theme(
    name="radar",
    description="live aircraft around a point (free community ADS-B data)",
    render=render,
    title="{LOGO} RADAR",
    status_line=status_line,
    boot=boot,
    widgets=lambda theme, title, user: radar_theme(theme),
    portrait_app=True,  # a layout and threads of its own
)
