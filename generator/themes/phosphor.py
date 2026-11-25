"""Phosphor theme: the green terminal (the default)."""

from .. import cfg
from ..base import CH, GRID_LABELS, HEADER_BL, HEADER_H, S
from ..draw import Canvas, font, header_layout, logo_baseline, logo_size, spaced


# ---------------------------------------------------------------------------------------------------------------------
# Phosphor artwork
# ---------------------------------------------------------------------------------------------------------------------
def render_background_phosphor(title, prompt):
    c = Canvas()
    up_x, _, uptime_chars = header_layout(title)

    # Header band (inverse video)
    c.d.rectangle((0, 0, cfg.W, HEADER_H), fill=cfg.SKIN["mid"])
    c.g.rectangle((0, 0, cfg.W, HEADER_H), fill=cfg.SKIN["dim"])
    c.label(6, HEADER_BL, title, cfg.SKIN["ink"], glow=False)
    if uptime_chars:
        c.label(up_x, HEADER_BL, "UP", (14, 70, 34), glow=False)

    # CPU / GPU panels: same columns in both, LOAD % | TEMP | CLK
    for p, name, subtitle, clk in ((cfg.cpu, "CPU", "ZEN2 6C/12T", "CLK GHZ"), (cfg.gpu, "GPU", "RDNA2 24CU", "CLK MHZ")):
        c.frame(p["box"], name, subtitle)
        c.label(p["col_a"], p["label_bl"], "TEMP")
        c.label(p["xr"], p["label_bl"], clk, anchor="rs")
        c.bar_track(*p["bar"])
        c.graph_grid(*p["graph"])
        if p["graph"][3] >= 50:  # on short charts it would collide with the threshold labels
            c.label(p["xr"] - 2, p["graph"][1] + 10, "°C 60s", cfg.SKIN["dim"], anchor="rs")

    # System grid
    c.frame(cfg.GRID, "SYS", "MEM / STORAGE / NET")
    for key, label, sublabel, kind in GRID_LABELS:
        cl = cfg.cells[key]
        c.label(cl["x0"], cl["label_bl"], label)
        if sublabel:
            c.label(cl["xr"], cl["label_bl"], sublabel, cfg.SKIN["dim"], anchor="rs")
        if kind == "bar":
            c.bar_track(*cl["bar"], ticks=False)
        else:
            c.graph_grid(*cl["spark"])
    for col in range(1, len(cfg.GRID_COLS)):
        c.dotted_vline(cfg.GRID_COLS[col] - (cfg.CELL_GAP + 1) // 2, cfg.GRID[1] + 8, cfg.GRID[3] - 4)

    # Now playing prompt
    c.dotted_hline(4, cfg.W - 4, cfg.PROMPT_Y)
    c.label(cfg.PROMPT_X, cfg.PROMPT_LABEL_BL, prompt)  # the command word and values are drawn live by Bc250Prompt

    return c.finish()


def render_splash_phosphor(title, prompt, logo=True):
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    bios = "PHOSPHOR BIOS v2.50"
    c.label(14, 14, bios, cfg.SKIN["mid"])
    if 14 + (len(bios) + 2 + len(title)) * CH[S] <= cfg.W - 14:  # the title only when it fits beside it
        c.label(cfg.W - 14, 14, title, cfg.SKIN["dim"], anchor="rs")
    c.dotted_hline(6, cfg.W - 6, 20)

    # Logo: the pixel font at 6x, with a strong bloom (splash_nologo.png leaves it out for the 3D animation)
    if logo:
        size = logo_size(cfg.LOGO)
        c.label(cfg.W // 2, logo_baseline(size), cfg.LOGO, cfg.SKIN["value"], anchor="ms", size=size)
        c.g.text((cfg.W // 2, logo_baseline(size)), cfg.LOGO, font=font(size), fill=cfg.SKIN["value"], anchor="ms")
    c.label(cfg.W // 2, sl["sub_bl"], spaced(cfg.SUBTITLE), cfg.SKIN["accent"], anchor="ms")
    c.dotted_hline(6, cfg.W - 6, sl["sep_y"])

    c.dotted_hline(6, cfg.W - 6, sl["progress_bl"] - 18)
    c.label(14, sl["progress_bl"], "LOADING BC250-PHOSPHOR", cfg.SKIN["mid"])
    x, y, w, h = sl["bar"]
    c.d.rectangle((x - 2, y - 2, x + w + 1, y + h + 1), outline=cfg.SKIN["dim"])

    for fx, fy, side, what in sl["footer"]:
        c.label(fx, fy, "Press DEL to enter SETUP" if what == "press" else prompt, cfg.SKIN["dim"],
                anchor="rs" if side == "right" else "ls")
    return c.finish()
