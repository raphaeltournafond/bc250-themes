"""Departures theme: a station's split-flap departures board."""

from .. import cfg
from ..base import FONT, M
from ..draw import Canvas, rgb


# Departures LED band wording ("EN VOIE 1 Hades II"; idle: "QUAI LIBRE" / "aucun départ prévu")
DEPARTURES_WORDS = {"boot": "MISE EN SERVICE", "now-playing": "EN VOIE 1", "downloading": "EN APPROCHE",
                    "installing": "EN FORMATION", "verifying": "CONTRÔLE", "fossilize_replay": "PRÉPARATION SHADERS",
                    "last-session": "DERNIER DÉPART", "idle": "QUAI LIBRE", "idle-text": "aucun départ prévu"}


# ---------------------------------------------------------------------------------------------------------------------
# Departures artwork: a station's split-flap board (blank flaps: the sensors turn them) over an LED information band
# ---------------------------------------------------------------------------------------------------------------------
DEPARTURES_LAYOUT = {  # landscape, portrait. Cells: width, height, font size; columns of 3, 4, 4 and 9 cells
    False: dict(cell=(20, 30, 24), pitch=22, gap=10, x0=9, rows=tuple(64 + 35 * i for i in range(6)), headings_bl=58,
                heading=(10, 31), subtitle=(10, 45), clock=dict(x=375, y=8, w=20, h=30, size=24, pitch=22, colon=10),
                captions=False),
    True: dict(cell=(13, 32, 24), pitch=14, gap=10, x0=7, rows=tuple(82 + 56 * i for i in range(6)), headings_bl=76,
               heading=(8, 33), subtitle=(8, 50), clock=dict(x=196, y=10, w=26, h=40, size=36, pitch=28, colon=10),
               captions=True),
}
DP_COLUMNS = (("TRAIN", 3, "TRAIN"), ("LOAD", 4, "CHARGE"), ("OTHER", 4, "DÉTAIL"), ("REMARK", 9, "INFORMATION"))
DP_CAPTIONS = ("PROCESSEUR · CHARGE, TEMPÉRATURE", "GRAPHIQUE · CHARGE, TEMPÉRATURE", "PUCE · PUISSANCE, HORLOGE GPU",
               "MÉMOIRE · OCCUPÉE, EN GO", "BIBLIOTHÈQUE STEAM · OCCUPÉE, LIBRE", "RÉSEAU · RÉCEPTION, ÉMISSION")
DP = dict(BOARD=(18, 18, 20), FLAP_TOP=(46, 46, 48), FLAP_BOTTOM=(38, 38, 40), HINGE=(10, 10, 12), TEXT=(238, 236, 226),
          TRAIN=(252, 204, 64), INFO=(200, 214, 200), ORANGE=(255, 150, 40), RED=(240, 60, 50), DIM=(120, 120, 124),
          LED=(255, 176, 48), LED_DIM=(170, 110, 36))
DP_LED_PANEL, DP_LED_DOT = (12, 9, 6), (26, 18, 10)


def departures_columns():
    """x of every cell of each column, left to right."""
    dl = DEPARTURES_LAYOUT[cfg.PORTRAIT]
    columns, x = {}, dl["x0"]
    for key, cells, _ in DP_COLUMNS:
        columns[key] = [x + i * dl["pitch"] for i in range(cells)]
        x = columns[key][-1] + dl["cell"][0] + dl["gap"]
    return columns


def departures_clock():
    c = DEPARTURES_LAYOUT[cfg.PORTRAIT]["clock"]
    xs = [c["x"], c["x"] + c["pitch"], c["x"] + 2 * c["pitch"] + c["colon"], c["x"] + 3 * c["pitch"] + c["colon"]]
    return xs, (xs[1] + c["w"] + xs[2]) // 2  # the cells, and where the colon goes


def dp_flap(d, x, y, w, h):
    """A blank flap: the same drawing as _flap() and _flap_hinge() in the sensors, so a blank cell sends nothing."""
    d.rectangle((x, y, x + w - 1, y + h // 2 - 1), fill=DP["FLAP_TOP"])
    d.rectangle((x, y + h // 2, x + w - 1, y + h - 1), fill=DP["FLAP_BOTTOM"])
    for cx, cy in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
        d.point((cx, cy), fill=DP["BOARD"])
    d.line((x, y + h // 2, x + w - 1, y + h // 2), fill=DP["HINGE"])


def render_background_departures(title):
    """The board with all its flaps blank, the column headings, the clock's cells, and the LED band under it."""
    dl = DEPARTURES_LAYOUT[cfg.PORTRAIT]
    c = Canvas()
    c.label(*dl["heading"], "DÉPARTS", DP["TRAIN"], size=M, glow=False)
    c.label(*dl["subtitle"], title, cfg.SKIN["dim"], glow=False)
    cw, ch, _ = dl["cell"]
    columns = departures_columns()
    for (key, _, heading) in DP_COLUMNS:
        c.label(columns[key][0], dl["headings_bl"], heading, cfg.SKIN["dim"], glow=False)
    for n, y in enumerate(dl["rows"]):
        for xs in columns.values():
            for x in xs:
                dp_flap(c.d, x, y, cw, ch)
        if dl["captions"]:
            c.label(columns["TRAIN"][0], y + ch + 13, DP_CAPTIONS[n], cfg.SKIN["dim"], glow=False)
    clock = dl["clock"]
    xs, colon = departures_clock()
    for x in xs:
        dp_flap(c.d, x, clock["y"], clock["w"], clock["h"])
    for dy in (-6, 5):
        cy = clock["y"] + clock["h"] // 2 + dy
        c.d.rectangle((colon - 1, cy - 1, colon + 1, cy + 1), fill=DP["TEXT"])
    c.d.line((0, cfg.PROMPT_Y, cfg.W, cfg.PROMPT_Y), fill=cfg.SKIN["grid_dot"])
    x, y, w, h = cfg.PROMPT_AREA  # the LED band: a dark panel and its grid of unlit dots
    c.d.rectangle((x, y, x + w - 1, y + h - 1), fill=DP_LED_PANEL)
    for py in range(y + 1, y + h - 1, 3):
        for px in range(x + 1, x + w - 1, 3):
            c.d.point((px, py), fill=DP_LED_DOT)
    return c.finish()


def departures_spec():
    dl = DEPARTURES_LAYOUT[cfg.PORTRAIT]
    clock = dl["clock"]
    return {"BOARD": [0, 0, cfg.W, cfg.PROMPT_Y], "CELL": list(dl["cell"]), "ROW_YS": list(dl["rows"]),
            "COLUMNS": departures_columns(), "CLOCK": {"XS": departures_clock()[0], "Y": clock["y"], "W": clock["w"],
                                                       "H": clock["h"], "SIZE": clock["size"]},
            "HOT": cfg.TEMP_HOT, "ALERT": cfg.TEMP_ALERT, "POWER_HIGH": cfg.POWER_HIGH, "REFRESH": 2, "TILE": 10, "FONT": FONT,
            "BACKGROUND_IMAGE": "background.png", "COLORS": {k: rgb(v) for k, v in DP.items()}}


def departures_theme(theme):
    """The board draws everything above the LED band, from the readings the app samples; the app keeps the status
    line (in the band) and the screen power."""
    custom = theme["STATS"]["CUSTOM"]
    spec = departures_spec()
    theme["STATS"] = {"CUSTOM": {
        "INTERVAL": 1,
        # sampled for the board (and the session peaks), drawn by nothing else
        "Bc250CpuTemp": {"ALERT": cfg.TEMP_ALERT}, "Bc250GpuTemp": {"ALERT": cfg.TEMP_ALERT},
        "Bc250GpuLoad": {"SAMPLE_ONLY": True}, "Bc250ApuPower": {"SAMPLE_ONLY": True},
        "Bc250Departures": spec,
        "Bc250Prompt": custom["Bc250Prompt"],
        "Bc250Screen": custom["Bc250Screen"],
    }}
    theme["bc250_splash"].update({k: v for k, v in spec.items() if k != "BACKGROUND_IMAGE"})
    theme["bc250_splash"].update({"STYLE": "departures", "IMAGE": "background.png", "LED": list(cfg.PROMPT_AREA),
                                  "LED_LABEL_BL": cfg.PROMPT_LABEL_BL, "LED_VALUE_BL": cfg.PROMPT_VALUE_BL})
    return theme
