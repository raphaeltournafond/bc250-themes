"""Seismograph theme: the machine's tremors and the world's earthquakes on one drum."""

from .. import cfg
from ..base import CH, CLOCK_CHARS, FONT, HEADER_BL, HEADER_H, M, S, SEISMO_LAYOUT
from ..draw import Canvas, heat_colors, rgb, text, world_map


# Seismograph status line wording ("EPICENTRE Hades II"; idle: "BACKGROUND NOISE" / "all stations quiet")
SEISMO_WORDS = {"boot": "CALIBRATING", "now-playing": "EPICENTRE", "downloading": "INCOMING WAVES", "installing": "SETTLING",
                "verifying": "SURVEYING", "fossilize_replay": "COMPILING STRATA", "last-session": "LAST TREMOR",
                "idle": "BACKGROUND NOISE", "idle-text": "all stations quiet"}
SM_PAPER, SM_RULE, SM_TICK = (238, 230, 208), (222, 212, 188), (206, 194, 168)
SM_INKS = ((28, 30, 40), (168, 34, 30), (28, 62, 150), (26, 104, 62))  # a helicorder changes ink from line to line
SM_MARGIN = 36  # the paper's left margin, where each line's time is written
SM_SEA, SM_LAND, SM_COAST, SM_GRATICULE = (14, 22, 28), (54, 62, 54), (92, 102, 88), (24, 34, 40)


def sm_world(w, h):
    """The world map: a plain latitude and longitude projection, 2:1."""
    k = 4
    return world_map(w, h, lambda lon, lat: ((lon + 180) / 360 * w * k, (90 - lat) / 180 * h * k),
                     SM_SEA, SM_LAND, SM_COAST, SM_GRATICULE, k)


def render_background_seismograph(title):
    """The instrument: the blank sheet with its ruled lines and minute ticks, the map, the labels."""
    sl = SEISMO_LAYOUT[cfg.PORTRAIT]
    c = Canvas()
    c.label(6, HEADER_BL, title, cfg.SKIN["mid"], glow=False)
    c.d.line((0, HEADER_H + 1, cfg.W, HEADER_H + 1), fill=cfg.SKIN["grid_dot"])
    x, y, w, h = sl["paper"]
    c.d.rectangle((x, y, x + w - 1, y + h - 1), fill=SM_PAPER)
    row_h = h // sl["rows"]
    for row in range(sl["rows"]):
        base = y + row * row_h + row_h // 2
        for px in range(x + SM_MARGIN, x + w - 1):
            c.d.point((px, base), fill=SM_RULE)
        for px in range(x + SM_MARGIN, x + w - 1, 75):  # a tick every half a minute
            c.d.line((px, base - 2, px, base + 2), fill=SM_TICK)
    c.d.line((x + SM_MARGIN - 3, y, x + SM_MARGIN - 3, y + h - 1), fill=SM_TICK)
    c.d.rectangle((x - 1, y - 1, x + w, y + h), outline=cfg.SKIN["mid"])
    mx, my, mw, mh = sl["map"]
    c.img.paste(sm_world(mw, mh), (mx, my))
    c.d.rectangle((mx - 1, my - 1, mx + mw, my + mh), outline=cfg.SKIN["grid_dot"])
    cx, cy, _, _ = sl["card"]
    c.label(cx + 2, cy + 12, "LAST QUAKE", cfg.SKIN["dim"], glow=False)
    for word, lx, bl, anchor in sl["labels"]:
        c.label(lx, bl, word, cfg.SKIN["dim"], anchor=anchor, glow=False)
    for line in sl["lines"]:
        c.d.line(line, fill=cfg.SKIN["grid_dot"])
    c.dotted_hline(4, cfg.W - 4, cfg.PROMPT_Y)
    return c.finish()


def seismo_spec(title):
    sl = SEISMO_LAYOUT[cfg.PORTRAIT]
    header_x = 6 + len(title) * CH[S] + 12
    spec = {"PAPER": list(sl["paper"]), "ROWS": sl["rows"], "MARGIN": SM_MARGIN, "MAP": list(sl["map"]), "CARD": list(sl["card"]),
            "HEADER": [header_x, HEADER_BL, cfg.CLOCK_XR - CLOCK_CHARS * CH[S] - 6], "SPEED": 2.5, "FPS": 8, "TILE": 10,
            "MIN_MAG": cfg.SEISMO_MIN_MAG, "FONT": FONT, "BACKGROUND_IMAGE": "background.png",
            "INKS": [list(c) for c in SM_INKS],
            "COLORS": {"BRIGHT": rgb(cfg.SKIN["value"]), "MID": rgb(cfg.SKIN["mid"]), "DIM": rgb(cfg.SKIN["dim"]),
                       "RED": rgb(cfg.SKIN["alert"]), "AMBER": rgb(cfg.SKIN["hot"]), "PAPER_DIM": rgb((150, 140, 118))}}
    if cfg.SEISMO_STATION:
        spec.update({"LAT": round(cfg.SEISMO_STATION[0], 4), "LON": round(cfg.SEISMO_STATION[1], 4)})
    return spec


def seismo_theme(theme, title):
    """The seismograph widget draws the paper, the map and the last quake; the app keeps the clock, the readings, the
    status line and the screen power."""
    sl, custom = SEISMO_LAYOUT[cfg.PORTRAIT], theme["STATS"]["CUSTOM"]
    heat = lambda at: dict(heat_colors(cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT), INK=rgb(cfg.SKIN["ink"]),
                           HEAT_TEXT=text(at[0], at[1], M, 5, right=True))
    load = lambda at: text(at[0], at[1], M, 4)
    power = dict(heat_colors(cfg.POWER_LOW, (cfg.POWER_LOW + cfg.POWER_HIGH) // 2, cfg.POWER_HIGH),
                 HEAT_TEXT=text(sl["pwr"][0], sl["pwr"][1], M, 5, right=True))
    spec = seismo_spec(title)
    theme["STATS"] = {
        "CPU": {"PERCENTAGE": {"INTERVAL": 1, "TEXT": load(sl["cpu"][0])}},
        "MEMORY": {"INTERVAL": 2, "VIRTUAL": {"PERCENT_TEXT": load(sl["ram"])}},
        "DATE": {"INTERVAL": 1, "HOUR": {"TEXT": text(cfg.CLOCK_XR, HEADER_BL, S, CLOCK_CHARS, cfg.SKIN["value"], right=True,
                                                      FORMAT="HH:mm:ss")}},
        "CUSTOM": {
            "INTERVAL": 1,
            "Bc250CpuTemp": heat(sl["cpu"][1]),
            "Bc250GpuTemp": heat(sl["gpu"][1]),
            "Bc250GpuLoad": {"TEXT": load(sl["gpu"][0])},
            "Bc250ApuPower": power,
            "Bc250Seismograph": spec,
            "Bc250Prompt": custom["Bc250Prompt"],
            "Bc250Screen": custom["Bc250Screen"],
        },
    }
    theme["bc250_splash"].update({"STYLE": "seismograph", "IMAGE": "background.png", "PAPER": spec["PAPER"],
                                  "ROWS_ON_PAPER": spec["ROWS"], "INKS": spec["INKS"], "MIN_MAG": spec["MIN_MAG"],
                                  "MARGIN": spec["MARGIN"]})
    return theme
