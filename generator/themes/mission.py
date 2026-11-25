"""Mission theme: a 1969 mission control console."""

from .. import cfg
from ..base import CH, CLOCK_CHARS, HEADER_BL, L, M, S
from ..draw import Canvas, header_layout


# mission wording ("FLIGHT: Hades II"; idle: "HOLDING" / "AWAITING GO")
MISSION_WORDS = {"boot": "COUNTDOWN", "now-playing": "FLIGHT:", "downloading": "UPLINK:", "installing": "INSTALL:",
                 "verifying": "CHECKOUT:", "fossilize_replay": "PRE-FLIGHT:", "last-session": "SPLASHDOWN:",
                 "idle": "HOLDING", "idle-text": "AWAITING GO"}


# ---------------------------------------------------------------------------------------------------------------------
# Mission Control artwork
# ---------------------------------------------------------------------------------------------------------------------
MC_STAGES = (("STAGE 1", "ZEN2 6C/12T", "FREQ GHZ"), ("STAGE 2", "RDNA2 24CU", "FREQ MHZ"))
MC_LABELS = {"ram": ("MEM", "USED"), "ssd": ("STORAGE", "FREE"), "pwr": ("PWR BUS", "GPU MEM"),
             "rx": ("↓ COMM RX", None), "tx": ("↑ COMM TX", None), "ping": ("PING", None)}
MC_PLATE = (196, 196, 184)  # engraved nameplates
MC_ENGRAVED = (24, 24, 24)


def crt_window(c, box):
    """A black CRT window sunk into the console: dark bevel top/left, light bevel bottom/right."""
    x1, y1, x2, y2 = box
    c.d.rectangle((x1 - 2, y1 - 2, x2 + 2, y2 + 2), fill=(36, 38, 40))
    c.d.line((x1 - 2, y2 + 2, x2 + 2, y2 + 2), fill=(104, 106, 108))
    c.d.line((x2 + 2, y1 - 2, x2 + 2, y2 + 2), fill=(104, 106, 108))
    c.d.rounded_rectangle(box, radius=4, fill=cfg.SKIN["bg"])
    c.crt.append(box)


def nameplate(c, x, y, title, subtitle=None):
    """An engraved plate on the console, its top-left at (x, y), 12 px high; the subtitle engraved beside it."""
    w = len(title) * CH[S] + 12
    c.d.rectangle((x, y, x + w - 1, y + 11), fill=MC_PLATE)
    c.d.line((x, y + 11, x + w - 1, y + 11), fill=(120, 120, 112))
    c.label(x + 6, y + 10, title, MC_ENGRAVED, glow=False)
    if subtitle:
        c.label(x + w + 6, y + 10, subtitle, (170, 170, 160), glow=False)
    return w


def window_behind(c, x1, x2, baseline):
    """A small black readout window behind one line of header text."""
    c.d.rectangle((x1 - 3, baseline - 11, x2 + 2, baseline + 3), fill=cfg.SKIN["bg"])


def render_background_mission(title):
    c = Canvas()
    c.d.rectangle((0, 0, cfg.W, cfg.H), fill=cfg.SKIN["console"])
    up_x, uptime_x, uptime_chars = header_layout(title)

    # header: console title, then readouts: MET, day of the year, time
    c.label(6, HEADER_BL, title, MC_PLATE, glow=False)
    if uptime_chars:
        c.label(uptime_x - 5, HEADER_BL, "MET", (170, 170, 160), anchor="rs", glow=False)
        window_behind(c, uptime_x, uptime_x + 12 * CH[S], HEADER_BL)
    if cfg.DATE_XR:
        window_behind(c, cfg.DATE_XR - 7 * CH[S], cfg.DATE_XR, HEADER_BL)
    window_behind(c, cfg.CLOCK_XR - CLOCK_CHARS * CH[S], cfg.CLOCK_XR, HEADER_BL)

    for p, (name, subtitle, clk) in zip((cfg.cpu, cfg.gpu), MC_STAGES):
        x1, y1, x2, y2 = p["box"]
        crt_window(c, (x1, y1 + 6, x2, y2))
        nameplate(c, x1 + 8, y1 - 6, name, subtitle)
        c.label(p["col_a"], p["label_bl"], "THERMAL")
        c.label(p["xr"], p["label_bl"], clk, anchor="rs")
        c.bar_track(*p["bar"])
        c.graph_grid(*p["graph"])
        if p["graph"][3] >= 50:
            c.label(p["xr"] - 2, p["graph"][1] + 10, "THERMAL 60s", cfg.SKIN["dim"], anchor="rs", glow=False)

    gx1, gy1, gx2, gy2 = cfg.GRID
    crt_window(c, (gx1, gy1 + 6, gx2, gy2))
    nameplate(c, gx1 + 8, gy1 - 6, "SYSTEMS", "MEM / STORAGE / COMM")
    for key, (label, sublabel) in MC_LABELS.items():
        cl = cfg.cells[key]
        c.label(cl["x0"], cl["label_bl"], label)
        if sublabel:
            c.label(cl["xr"], cl["label_bl"], sublabel, cfg.SKIN["dim"], anchor="rs", glow=False)
        if key in ("ram", "ssd", "pwr"):
            c.bar_track(*cl["bar"], ticks=False)
        else:
            c.graph_grid(*cl["spark"])
    for col in range(1, len(cfg.GRID_COLS)):
        c.dotted_vline(cfg.GRID_COLS[col] - (cfg.CELL_GAP + 1) // 2, cfg.GRID[1] + 10, cfg.GRID[3] - 4)

    crt_window(c, (4, cfg.PROMPT_Y + 1, cfg.W - 5, cfg.H - 3))  # the flight status line, written live by Bc250Prompt
    return c.finish()


def render_splash_mission():
    """The console the boot runs on: nameplate with the logo, the countdown clock, the poll CRT. Everything in the
    windows (poll, lamps, countdown) is drawn live by sensors_bc250."""
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    c.d.rectangle((0, 0, cfg.W, cfg.H), fill=cfg.SKIN["console"])
    px1, py1, px2, py2 = sl["plate"]
    c.label(px1 + 4, py1 + 11, "MISSION CONTROL CENTER", cfg.SKIN["accent"], glow=False)
    size = L if len(cfg.LOGO) * CH[L] <= px2 - px1 - 8 else M
    c.label(px1 + 4, py2 - 6, cfg.LOGO, cfg.SKIN["value"], size=size)
    sub_x = px1 + 4 + len(cfg.LOGO) * CH[size] + 10
    if sub_x + len(cfg.SUBTITLE) * CH[S] <= px2:
        c.label(sub_x, py2 - 6, cfg.SUBTITLE, (170, 170, 160), glow=False)
    crt_window(c, sl["count_box"])
    bx1, by1, bx2, by2 = sl["count_box"]
    c.label(bx1 + 6, by1 + 13, "COUNTDOWN", cfg.SKIN["dim"], glow=False)
    crt_window(c, sl["crt"])
    return c.finish()
