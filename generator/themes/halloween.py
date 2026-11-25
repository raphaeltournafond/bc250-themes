"""Halloween theme: pumpkins, cobwebs and a graveyard under the full moon."""

import math
import random

from PIL import Image, ImageDraw

from .. import cfg
from ..base import CH, GRID_LABELS, HEADER_BL, HEADER_H, S
from ..draw import Canvas, font, header_layout, mix


# Halloween status line wording ("HAUNTING Hades II"; idle: "SLUMBERING" / "the crypt is quiet")
HALLOWEEN_WORDS = {"boot": "RISING", "now-playing": "HAUNTING", "downloading": "SUMMONING", "installing": "CONJURING",
                   "verifying": "EXORCISING", "fossilize_replay": "BREWING SHADERS", "last-session": "LAST HAUNT",
                   "idle": "SLUMBERING", "idle-text": "the crypt is quiet"}


# ---------------------------------------------------------------------------------------------------------------------
# Halloween artwork
# ---------------------------------------------------------------------------------------------------------------------
HW_BAND = (32, 15, 42)  # the header band: dusk purple, dripping
HW_SKY_TOP, HW_SKY_LOW = (46, 18, 64), (16, 8, 24)
HW_MOON, HW_MOON_SHADE = (238, 230, 198), (196, 186, 160)
HW_GROUND, HW_STONE, HW_STONE_EDGE = (7, 3, 9), (44, 34, 56), (70, 58, 84)
HW_BLOOD, HW_BLOOD_DARK = (200, 18, 32), (112, 6, 16)
HW_PUMPKIN, HW_PUMPKIN_RIB, HW_STEM = (236, 108, 18), (150, 58, 8), (74, 112, 40)
HW_CARVED, HW_CANDLE = (36, 12, 4), (255, 214, 96)  # the face, unlit and lit
# a bat, wings spread, in units of its scale: scalloped wings, two ears
BAT_SHAPE = ((-8, -2), (-6, -4), (-4, -3), (-2, -4), (-1, -2), (-1, -4), (0, -3), (1, -4), (1, -2), (2, -4),
             (4, -3), (6, -4), (8, -2), (6, -1), (5, 0), (4, -1), (2, 0), (1, 1), (0, 2), (-1, 1), (-2, 0), (-4, -1),
             (-5, 0), (-6, -1))


def drips(c, x1, x2, y, color, seed, longest=5, skip=None):
    """Drops hanging from a horizontal edge at y: every few pixels a thin trickle, the longer ones with a drop at the
    end. `skip` = (xa, xb): leave that stretch dry (a tag sits there)."""
    rnd = random.Random(seed)
    x = x1 + rnd.randrange(3, 9)
    while x < x2 - 3:
        if not (skip and skip[0] - 2 <= x <= skip[1] + 2):
            n = rnd.randrange(1, longest + 1)
            c.d.line((x, y + 1, x, y + n), fill=color)
            if rnd.random() < 0.4:
                c.d.line((x + 1, y + 1, x + 1, y + max(1, n - 2)), fill=color)
            if n >= 3:
                c.d.rectangle((x, y + n, x + 1, y + n + 1), fill=color)
        x += rnd.randrange(5, 16)


def cobweb(c, x, y, sx, sy, r, color):
    """A cobweb in a corner (x, y), opening towards (sx, sy): five threads fanning out, joined by sagging rings."""
    angles = [math.radians(a) for a in (0, 22.5, 45, 67.5, 90)]
    for a in angles:
        c.d.line((x, y, x + sx * r * math.cos(a), y + sy * r * math.sin(a)), fill=color)
    for k in (0.38, 0.68, 0.98):
        points = [(x + sx * r * k * math.cos(a), y + sy * r * k * math.sin(a)) for a in angles]
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            mx, my = (ax + bx) / 2, (ay + by) / 2
            mx, my = x + (mx - x) * 0.86, y + (my - y) * 0.86  # sagging towards the corner
            c.d.line((ax, ay, mx, my), fill=color)
            c.d.line((mx, my, bx, by), fill=color)


def bat(draw, cx, cy, scale, color):
    draw.polygon([(cx + px * scale, cy + py * scale) for px, py in BAT_SHAPE], fill=color)


def pumpkin_face(cx, cy, r):
    """The carved holes of a jack-o'-lantern (eyes, nose, toothy grin) as polygons: the boot fills them with the
    flickering candle light."""
    rx, ry = r * 1.2, r

    def poly(*points):
        return [[round(cx + px * rx), round(cy + py * ry)] for px, py in points]
    return [poly((-0.62, -0.02), (-0.16, -0.02), (-0.4, -0.46)),  # eyes
            poly((0.16, -0.02), (0.62, -0.02), (0.4, -0.46)),
            poly((-0.09, 0.16), (0.09, 0.16), (0, -0.02)),  # nose
            poly((-0.7, 0.26), (-0.42, 0.36), (-0.32, 0.27), (-0.2, 0.37), (0.2, 0.37), (0.32, 0.27), (0.42, 0.36),
                 (0.7, 0.26), (0.5, 0.6), (0.2, 0.7), (-0.2, 0.7), (-0.5, 0.6))]  # grin with two teeth


def pumpkin(c, cx, cy, r, face=HW_CARVED):
    """A jack-o'-lantern: ribbed orange body, a stem, the carved face."""
    rx, ry = r * 1.2, r
    c.d.rectangle((cx - 2, cy - ry - 5, cx + 2, cy - ry + 2), fill=HW_STEM)
    c.d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=HW_PUMPKIN, outline=HW_PUMPKIN_RIB)
    for k in (0.45, 0.8):  # the ribs
        c.d.arc((cx - rx * k, cy - ry, cx + rx * k, cy + ry), 100, 260, fill=HW_PUMPKIN_RIB)
        c.d.arc((cx - rx * k, cy - ry, cx + rx * k, cy + ry), -80, 80, fill=HW_PUMPKIN_RIB)
    for hole in pumpkin_face(cx, cy, r):
        c.d.polygon([tuple(p) for p in hole], fill=face)


def moon(c, cx, cy, r, sky=HW_SKY_TOP):
    """A full moon with a pale halo and a few darker seas."""
    for i, k in enumerate((0.1, 0.18, 0.28)):
        rr = r + 9 - 3 * i
        c.d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=mix(sky, HW_MOON, k))
    c.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=HW_MOON)
    for dx, dy, rr in ((-0.35, -0.2, 0.28), (0.25, 0.3, 0.22), (0.3, -0.38, 0.14), (-0.1, 0.45, 0.12)):
        x, y, s = cx + dx * r, cy + dy * r, rr * r
        c.d.ellipse((x - s, y - s, x + s, y + s), fill=HW_MOON_SHADE)


def graveyard(c, horizon, seed):
    """Night sky down to the horizon, then black hills with tombstones, crosses and a dead tree in silhouette."""
    for y in range(horizon):
        c.d.line((0, y, cfg.W, y), fill=mix(HW_SKY_TOP, HW_SKY_LOW, y / horizon))
    rnd = random.Random(seed)
    hills = [(x, horizon - 6 + round(3 * math.sin(x / 37) + 2 * math.sin(x / 13))) for x in range(0, cfg.W + 8, 8)]
    c.d.polygon(hills + [(cfg.W, horizon + 2), (0, horizon + 2)], fill=HW_GROUND)
    c.d.rectangle((0, horizon, cfg.W, horizon + 2), fill=HW_GROUND)
    x = rnd.randrange(4, 20)
    while x < cfg.W - 20:
        ground = horizon - 6 + round(3 * math.sin(x / 37) + 2 * math.sin(x / 13))
        kind = rnd.choice(("stone", "stone", "cross", "slab"))
        h = rnd.randrange(10, 19)
        if kind == "cross":
            c.d.rectangle((x + 4, ground - h, x + 6, ground), fill=HW_STONE)
            c.d.rectangle((x, ground - h + 3, x + 10, ground - h + 5), fill=HW_STONE)
            x += 18
        else:
            w = rnd.randrange(9, 15) if kind == "stone" else rnd.randrange(14, 20)
            h = h if kind == "stone" else h // 2 + 3
            top = ground - h
            c.d.rectangle((x, top + w // 2, x + w, ground), fill=HW_STONE)
            if kind == "stone":
                c.d.pieslice((x, top, x + w, top + w), 180, 360, fill=HW_STONE)
                c.d.arc((x, top, x + w, top + w), 200, 340, fill=HW_STONE_EDGE)
            else:
                c.d.rectangle((x, top, x + w, top + w // 2), fill=HW_STONE)
                c.d.line((x, top, x + w, top), fill=HW_STONE_EDGE)
            x += w + rnd.randrange(8, 30)
    # the dead tree, its branches forking twice
    tx = cfg.W // 8 if seed % 2 else cfg.W - cfg.W // 8

    def branch(x0, y0, angle, length, depth):
        x1, y1 = x0 + length * math.cos(angle), y0 - length * math.sin(angle)
        c.d.line((x0, y0, x1, y1), fill=HW_GROUND, width=max(1, depth))
        if depth > 0:
            for turn in (-0.45, 0.4):
                branch(x1, y1, angle + turn + rnd.uniform(-0.15, 0.15), length * 0.68, depth - 1)
    branch(tx, horizon - 4, math.pi / 2, min(28, horizon // 4), 3)


def logo_blocks(text, center, max_w):
    """The pixel font blown up into square blocks: (the blocks that are on, left, top, block size, width in blocks),
    or None for an empty logo."""
    mask = Image.new("L", (len(text) * CH[S] + 4, 16), 0)
    ImageDraw.Draw(mask).text((1, 1), text, font=font(S), fill=255)
    box = mask.getbbox()
    if not box:
        return None
    mask = mask.crop(box)
    gw, gh = mask.size
    b = next((v for v in (7, 6, 5, 4, 3, 2) if gw * v + 4 <= max_w), 2)
    x0, y0 = center[0] - gw * b // 2, center[1] - gh * b // 2
    return {(i, j) for j in range(gh) for i in range(gw) if mask.getpixel((i, j)) > 127}, x0, y0, b, gw


def drip_logo(c, text, center, max_w):
    """The logo in blood: the pixel font blown up into blocks, a dark edge, and drops running down from it."""
    blocks = logo_blocks(text, center, max_w)
    if not blocks:
        return
    on, x0, y0, b, gw = blocks
    for i, j in on:  # the dark edge, down and to the right
        c.d.rectangle((x0 + i * b + 1, y0 + j * b + 1, x0 + i * b + b, y0 + j * b + b), fill=HW_BLOOD_DARK)
    for i, j in on:
        c.d.rectangle((x0 + i * b, y0 + j * b, x0 + i * b + b - 1, y0 + j * b + b - 1), fill=HW_BLOOD)
    rnd = random.Random(31)
    for i in range(gw):  # drops run down from the lowest block of a column, now and then
        low = max((j for (ci, j) in on if ci == i), default=None)
        if low is None or rnd.random() > 0.42:
            continue
        x, y = x0 + i * b + rnd.randrange(0, max(1, b - 2)), y0 + (low + 1) * b
        n = rnd.randrange(b, 4 * b)
        wd = max(2, b // 2)
        c.d.rectangle((x, y, x + wd - 1, y + n), fill=HW_BLOOD)
        c.d.ellipse((x - 1, y + n - 1, x + wd, y + n + wd), fill=HW_BLOOD)


def render_background_halloween(title):
    c = Canvas()
    up_x, _, uptime_chars = header_layout(title)
    c.d.rectangle((0, 0, cfg.W, HEADER_H), fill=HW_BAND)
    drips(c, 0, cfg.W, HEADER_H, HW_BAND, seed=13, longest=3)
    c.label(6, HEADER_BL, title, cfg.SKIN["mid"])
    if uptime_chars:
        c.label(up_x, HEADER_BL, "UP", cfg.SKIN["dim"], glow=False)

    for p, name, subtitle, clk, seed in ((cfg.cpu, "CPU", "ZEN2 6C/12T", "CLK GHZ", 1), (cfg.gpu, "GPU", "RDNA2 24CU", "CLK MHZ", 2)):
        x1, y1, x2, y2 = p["box"]
        tag_end = x1 + 8 + len(name) * CH[S] + 8 + 4 + len(subtitle) * CH[S] + 3
        drips(c, x1 + 1, x2, y1, cfg.SKIN["dim"], seed, skip=(x1 + 6, tag_end))
        c.frame(p["box"], name, subtitle)
        cobweb(c, x2 - 1, y1 + 1, -1, 1, 9, cfg.SKIN["dim"])
        c.label(p["col_a"], p["label_bl"], "TEMP")
        c.label(p["xr"], p["label_bl"], clk, anchor="rs")
        c.bar_track(*p["bar"])
        c.graph_grid(*p["graph"])
        if p["graph"][3] >= 50:
            c.label(p["xr"] - 2, p["graph"][1] + 10, "°C 60s", cfg.SKIN["dim"], anchor="rs", glow=False)

    x1, y1, x2, y2 = cfg.GRID
    drips(c, x1 + 1, x2, y1, cfg.SKIN["dim"], 3, skip=(x1 + 6, x1 + 8 + 5 * CH[S] + 12 + 19 * CH[S] + 3))
    c.frame(cfg.GRID, "CRYPT", "MEM / STORAGE / NET")
    cobweb(c, x2 - 1, y1 + 1, -1, 1, 9, cfg.SKIN["dim"])
    for key, label, sublabel, kind in GRID_LABELS:
        cl = cfg.cells[key]
        c.label(cl["x0"], cl["label_bl"], label)
        if sublabel:
            c.label(cl["xr"], cl["label_bl"], sublabel, cfg.SKIN["dim"], anchor="rs", glow=False)
        if kind == "bar":
            c.bar_track(*cl["bar"], ticks=False)
        else:
            c.graph_grid(*cl["spark"])
    for col in range(1, len(cfg.GRID_COLS)):
        c.dotted_vline(cfg.GRID_COLS[col] - (cfg.CELL_GAP + 1) // 2, cfg.GRID[1] + 8, cfg.GRID[3] - 4)

    c.dotted_hline(4, cfg.W - 4, cfg.PROMPT_Y)  # the status line, written live by Bc250Prompt
    return c.finish()


def render_splash_halloween(logo=True):
    """The graveyard, the moon, the bats and the logo above; the seance panel, its bar and the jack-o'-lanterns
    (unlit) below. The rows, the candle light, the flying bats and the lightning are drawn live."""
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    graveyard(c, sl["horizon"], seed=7 if cfg.PORTRAIT else 8)
    moon(c, *sl["moon"])
    mx, my, mr = sl["moon"]
    bat(c.d, mx - mr - 30, my + 6, 1.5, HW_GROUND)  # two already out, by the moon
    bat(c.d, mx + mr // 2, my - mr // 3, 1.2, HW_GROUND)
    if logo:
        drip_logo(c, cfg.LOGO, sl["logo_center"], sl["logo_max_w"])
    px1, py1, px2, py2 = sl["panel"]
    drips(c, px1 + 1, px2, py1, cfg.SKIN["dim"], 5, longest=6)
    c.frame(sl["panel"])
    cobweb(c, px1 + 1, py1 + 1, 1, 1, 12, cfg.SKIN["dim"])
    cobweb(c, px2 - 1, py1 + 1, -1, 1, 12, cfg.SKIN["dim"])
    title = f"Summoning the {cfg.SUBTITLE.lower()}..."
    c.label(sl["label_x"] + 14, sl["title_bl"], title[:(sl["status_xr"] - sl["label_x"] - 28) // CH[S]], cfg.SKIN["accent"])
    x, y, w, h = sl["bar"]
    c.d.rectangle((x - 2, y - 2, x + w + 1, y + h + 1), outline=cfg.SKIN["dim"])
    for p in sl["pumpkins"]:
        pumpkin(c, *p)
    return c.finish()
