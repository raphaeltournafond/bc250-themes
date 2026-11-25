"""Christmas theme: snow, a lit tree and Santa's sleigh on a silent night."""

import math
import random

from .. import cfg
from ..base import CH, GRID_LABELS, HEADER_BL, HEADER_H, S
from ..draw import Canvas, header_layout, mix
from .halloween import logo_blocks, moon


# Christmas status line wording ("UNWRAPPING Hades II"; idle: "ALL IS CALM" / "all is bright")
CHRISTMAS_WORDS = {"boot": "WAKING THE ELVES", "now-playing": "UNWRAPPING", "downloading": "DELIVERING",
                   "installing": "ASSEMBLING", "verifying": "CHECKING TWICE", "fossilize_replay": "BAKING SHADERS",
                   "last-session": "LAST GIFT", "idle": "ALL IS CALM", "idle-text": "all is bright"}


# ---------------------------------------------------------------------------------------------------------------------
# Christmas artwork
# ---------------------------------------------------------------------------------------------------------------------
CM_BAND = (150, 24, 36)  # the header band: holly red
CM_HOLLY, CM_HOLLY_DARK = (214, 36, 48), (112, 14, 26)
CM_SNOW, CM_SNOW_SHADE = (236, 243, 252), (168, 190, 222)
CM_SKY_TOP, CM_SKY_LOW = (10, 18, 54), (40, 62, 112)
CM_GROUND = (20, 30, 58)  # the snow in the shade, under the hills
CM_PINE, CM_PINE_DARK = (26, 104, 62), (14, 66, 44)
CM_GOLD = (255, 205, 96)
CM_BULBS = ((240, 54, 60), (255, 205, 80), (90, 220, 110), (90, 170, 255))  # red, gold, green, blue


def snow_cap(c, x1, x2, y, seed, skip=None, height=3):
    """Snow piled on a horizontal edge at y, in soft lumps. `skip` = (xa, xb): none on that stretch (a tag sits there)."""
    rnd = random.Random(seed)
    a, b = rnd.uniform(0, 6.28), rnd.uniform(0, 6.28)
    for x in range(x1, x2 + 1):
        if skip and skip[0] <= x <= skip[1]:
            continue
        n = round(height * (0.55 + 0.3 * math.sin(x / 9 + a) + 0.25 * math.sin(x / 3.7 + b)))
        if n > 0:
            c.d.line((x, y - n, x, y - 1), fill=mix(c.img.getpixel((x, y - n)), CM_SNOW, 0.72))


def light_string(c, x1, x2, y, seed, skip=None):
    """A string of coloured bulbs hanging under a horizontal edge at y."""
    i, x = random.Random(seed).randrange(4), x1 + 8
    while x < x2 - 6:
        if not (skip and skip[0] - 3 <= x <= skip[1] + 3):
            c.d.point((x, y + 1), fill=cfg.SKIN["dim"])
            c.d.rectangle((x - 1, y + 2, x + 1, y + 4), fill=CM_BULBS[i % 4])
            i += 1
        x += 15


def star_points(cx, cy, r):
    """A five-pointed star."""
    return [(cx + (r if k % 2 == 0 else r * 0.42) * math.sin(k * math.pi / 5),
             cy - (r if k % 2 == 0 else r * 0.42) * math.cos(k * math.pi / 5)) for k in range(10)]


def tree_lights(cx, top, base, half):
    """Where the Christmas tree's bulbs are, and their colours: [[x, y, [r, g, b]]...], along the tree's tiers."""
    rnd, lights = random.Random(25), []
    height = base - top
    for row, f in enumerate((0.24, 0.38, 0.52, 0.66, 0.8, 0.92)):
        y = top + f * height
        width = half * f * 0.9
        count = 2 + row
        for k in range(count):
            x = cx - width + 2 * width * (k + 0.5) / count + rnd.uniform(-1.5, 1.5)
            lights.append([round(x), round(y), list(CM_BULBS[(row + k) % 4])])
    return lights


def christmas_tree(c, cx, top, base, half):
    """Tiers of pine with snow on their edges, a trunk, a gold star on top, and its bulbs (unlit until the boot's
    switch-on)."""
    height = base - top
    c.d.rectangle((cx - 3, base - 6, cx + 3, base), fill=(70, 44, 30))
    for lo, hi, w in ((0.36, 0.92, 1.0), (0.2, 0.68, 0.76), (0.06, 0.42, 0.5)):  # bottom tier first
        y1, y2, wide = top + lo * height, top + hi * height, half * w
        c.d.polygon([(cx, y1), (cx + wide, y2), (cx - wide, y2)], fill=CM_PINE)
        c.d.line((cx - wide, y2, cx + wide, y2), fill=CM_PINE_DARK)
        c.d.line((cx - wide, y2 - 1, cx - wide * 0.45, y2 - 1), fill=CM_SNOW_SHADE)  # snow on the branch tips
        c.d.line((cx + wide * 0.45, y2 - 1, cx + wide, y2 - 1), fill=CM_SNOW_SHADE)
    for x, y, color in tree_lights(cx, top, base, half):
        c.d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=mix(tuple(color), CM_PINE_DARK, 0.6))
    c.d.polygon(star_points(cx, top + 3, 7), fill=CM_GOLD)


def pine(c, cx, base, h):
    """A little pine on the hills, snow on its top."""
    w = h * 0.36
    c.d.rectangle((cx - 1, base - 2, cx + 1, base), fill=CM_PINE_DARK)
    c.d.polygon([(cx, base - h), (cx + w, base - 2), (cx - w, base - 2)], fill=CM_PINE_DARK)
    c.d.polygon([(cx, base - h), (cx + w * 0.42, base - h * 0.58), (cx - w * 0.42, base - h * 0.58)], fill=CM_SNOW_SHADE)


def winter_night(c, horizon, tree, seed):
    """A starry sky down to the horizon, then snowy hills with little pines; shaded snow below them."""
    for y in range(horizon):
        c.d.line((0, y, cfg.W, y), fill=mix(CM_SKY_TOP, CM_SKY_LOW, y / horizon))
    c.d.rectangle((0, horizon, cfg.W, cfg.H), fill=CM_GROUND)
    rnd = random.Random(seed)
    for _ in range(cfg.W // 7):
        x, y = rnd.randrange(cfg.W), rnd.randrange(horizon - 14)
        c.d.point((x, y), fill=mix(CM_SKY_TOP, CM_SNOW, rnd.uniform(0.35, 0.95)))
    ground = lambda x: horizon - 9 + round(4 * math.sin(x / 41 + seed) + 2 * math.sin(x / 17))
    c.d.polygon([(x, ground(x)) for x in range(0, cfg.W + 6, 6)] + [(cfg.W, horizon + 2), (0, horizon + 2)], fill=CM_SNOW_SHADE)
    c.d.line([(x, ground(x)) for x in range(0, cfg.W + 6, 6)], fill=CM_SNOW)
    x = rnd.randrange(4, 18)
    while x < cfg.W - 6:
        if not tree[0] - tree[3] - 8 <= x <= tree[0] + tree[3] + 8:
            pine(c, x, ground(x) + 1, rnd.randrange(14, 25))
        x += rnd.randrange(14, 46)


def snowman(c, cx, base, k):
    """A snowman with a top hat, coal buttons and a carrot nose."""
    rs = [10 * k, 7 * k, 5 * k]
    y = base
    centers = []
    for r in rs:
        y -= r
        centers.append(y)
        c.d.ellipse((cx - r, y - r, cx + r, y + r), fill=CM_SNOW, outline=CM_SNOW_SHADE)
        y -= r * 0.7
    head, r = centers[2], rs[2]
    c.d.rectangle((cx - r - 1, head - r - 1, cx + r + 1, head - r), fill=(16, 16, 22))
    c.d.rectangle((cx - r + 1, head - r - 5 * k, cx + r - 1, head - r), fill=(16, 16, 22))
    c.d.point([(cx - 2, head - 1), (cx + 2, head - 1)], fill=(16, 16, 22))
    c.d.polygon([(cx, head), (cx, head + 2), (cx + 5 * k, head + 1)], fill=(255, 140, 40))
    for dy in (-3, 0, 3):
        c.d.point((cx, centers[1] + dy * k), fill=(16, 16, 22))


def present(c, x, y, w, h):
    """A wrapped present with a gold ribbon and a bow."""
    c.d.rectangle((x, y + 5, x + w, y + h), fill=CM_HOLLY, outline=CM_HOLLY_DARK)
    c.d.rectangle((x - 2, y + 2, x + w + 2, y + 7), fill=CM_HOLLY, outline=CM_HOLLY_DARK)
    c.d.rectangle((x + w // 2 - 2, y + 2, x + w // 2 + 2, y + h), fill=CM_GOLD)
    c.d.rectangle((x, y + 13, x + w, y + 16), fill=CM_GOLD)
    c.d.ellipse((x + w // 2 - 9, y - 4, x + w // 2 - 1, y + 3), outline=CM_GOLD)
    c.d.ellipse((x + w // 2 + 1, y - 4, x + w // 2 + 9, y + 3), outline=CM_GOLD)


def sleigh_shapes():
    """The flying sleigh, drawn by the boot: [[[r, g, b], [[x, y]...]]...] going right, x = 0 at the back of the
    sleigh, y = 0 at its top. The first reindeer's nose is the last shape."""
    red, wood, fur, white = list(CM_HOLLY), [226, 180, 80], [150, 104, 64], list(CM_SNOW)
    shapes = [[wood, [[-2, 14], [18, 14], [20, 12], [20, 15], [-2, 15]]],  # the runner
              [red, [[0, 6], [15, 6], [17, 8], [14, 12], [2, 12], [0, 9]]],  # the sleigh
              [red, [[6, 6], [6, 2], [8, 0], [11, 1], [11, 6]]],  # Santa
              [white, [[7, 1], [10, 1], [10, 3], [7, 3]]],
              [[120, 80, 50], [[1, 3], [5, 3], [5, 6], [1, 6]]]]  # the sack
    deer = []
    for n, dx in enumerate((25, 42, 59)):
        deer += [[fur, [[dx, 6], [dx + 9, 6], [dx + 10, 9], [dx, 9]]],  # body
                 [fur, [[dx + 1, 9], [dx + 2, 9], [dx + 2, 13], [dx + 1, 13]]],  # legs
                 [fur, [[dx + 8, 9], [dx + 9, 9], [dx + 9, 13], [dx + 8, 13]]],
                 [fur, [[dx + 9, 7], [dx + 11, 3], [dx + 14, 3], [dx + 14, 5], [dx + 11, 6], [dx + 10, 8]]],  # head
                 [fur, [[dx + 11, 3], [dx + 10, 0], [dx + 11, 0], [dx + 12, 3]]],  # antlers
                 [fur, [[dx + 12, 3], [dx + 13, 0], [dx + 14, 0], [dx + 13, 3]]],
                 [[200, 170, 110], [[dx - 8 if n else 17, 8], [dx, 7], [dx, 8], [dx - 8 if n else 17, 9]]]]  # the reins
    return shapes + deer + [[[255, 40, 40], [[73, 3], [75, 3], [75, 5], [73, 5]]]]  # that nose


def render_background_christmas(title):
    c = Canvas()
    rnd = random.Random(12)
    for _ in range(cfg.W * cfg.H // 900):  # a few faint flakes behind everything
        c.d.point((rnd.randrange(cfg.W), rnd.randrange(HEADER_H + 2, cfg.H)), fill=(30, 42, 66))
    up_x, _, uptime_chars = header_layout(title)
    c.d.rectangle((0, 0, cfg.W, HEADER_H), fill=CM_BAND)
    c.label(6, HEADER_BL, title, CM_SNOW)
    if uptime_chars:
        c.label(up_x, HEADER_BL, "UP", (240, 170, 170), glow=False)

    for p, name, subtitle, clk, seed in ((cfg.cpu, "CPU", "ZEN2 6C/12T", "CLK GHZ", 1), (cfg.gpu, "GPU", "RDNA2 24CU", "CLK MHZ", 2)):
        x1, y1, x2, y2 = p["box"]
        tag_end = x1 + 8 + len(name) * CH[S] + 8 + 4 + len(subtitle) * CH[S] + 3
        c.frame(p["box"], name, subtitle)
        snow_cap(c, x1, x2, y1, seed, skip=(x1 + 6, tag_end))
        light_string(c, tag_end, x2, y1, seed)
        c.label(p["col_a"], p["label_bl"], "TEMP")
        c.label(p["xr"], p["label_bl"], clk, anchor="rs")
        c.bar_track(*p["bar"])
        c.graph_grid(*p["graph"])
        if p["graph"][3] >= 50:
            c.label(p["xr"] - 2, p["graph"][1] + 10, "°C 60s", cfg.SKIN["dim"], anchor="rs", glow=False)

    x1, y1, x2, y2 = cfg.GRID
    tag_end = x1 + 8 + len("WORKSHOP") * CH[S] + 8 + 4 + len("MEM / STORAGE / NET") * CH[S] + 3
    c.frame(cfg.GRID, "WORKSHOP", "MEM / STORAGE / NET")
    snow_cap(c, x1, x2, y1, 3, skip=(x1 + 6, tag_end))
    light_string(c, tag_end, x2, y1, 3)
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
    for x in range(cfg.W):  # a little snowdrift along the bottom edge, behind it
        n = round(1.6 + 1.1 * math.sin(x / 23) + 0.6 * math.sin(x / 7))
        if n > 0:
            c.d.line((x, cfg.H - n, x, cfg.H - 1), fill=(84, 104, 136))
    return c.finish()


def snow_logo(c, text, center, max_w):
    """The logo in holly red: blocks with a dark edge, and snow lying on top of them."""
    blocks = logo_blocks(text, center, max_w)
    if not blocks:
        return
    on, x0, y0, b, _ = blocks
    for i, j in on:
        c.d.rectangle((x0 + i * b + 1, y0 + j * b + 1, x0 + i * b + b, y0 + j * b + b), fill=CM_HOLLY_DARK)
    for i, j in on:
        c.d.rectangle((x0 + i * b, y0 + j * b, x0 + i * b + b - 1, y0 + j * b + b - 1), fill=CM_HOLLY)
    rnd = random.Random(25)
    for i, j in on:
        if (i, j - 1) not in on:
            x, y = x0 + i * b, y0 + j * b
            depth = max(2, b // 2)
            c.d.rectangle((x, y - 1, x + b - 1, y + depth - 2), fill=CM_SNOW)
            for sx in range(x, x + b):  # its lower edge is uneven
                c.d.line((sx, y + depth - 2, sx, y + depth - 2 + rnd.randrange(0, 2)), fill=CM_SNOW)


def render_splash_christmas(logo=True):
    """The winter night, the moon, the tree and the logo above; Santa's list, its bar, a snowman and a present below.
    The rows, the falling snow, the tree's lights and the sleigh are drawn live."""
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    winter_night(c, sl["horizon"], sl["tree"], seed=3 if cfg.PORTRAIT else 4)
    moon(c, *sl["moon"], sky=CM_SKY_TOP)
    christmas_tree(c, *sl["tree"])
    if logo:
        snow_logo(c, cfg.LOGO, sl["logo_center"], sl["logo_max_w"])
    px1, py1, px2, py2 = sl["panel"]
    c.d.rectangle(sl["panel"], fill=cfg.SKIN["bg"])
    c.frame(sl["panel"])
    snow_cap(c, px1, px2, py1, 5, height=4)
    light_string(c, px1, px2, py1, 5)
    title = f"Santa's list: {cfg.SUBTITLE.lower()}"
    c.label(sl["label_x"], sl["title_bl"], title[:(sl["status_xr"] - sl["label_x"]) // CH[S]], cfg.SKIN["mid"])
    x, y, w, h = sl["bar"]
    c.d.rectangle((x - 2, y - 2, x + w + 1, y + h + 1), fill=cfg.SKIN["bg"], outline=CM_SNOW_SHADE)
    for sx in range(cfg.W):  # the snowdrift the snowman and the present stand in
        n = round(5 + 2.5 * math.sin(sx / 29) + 1.5 * math.sin(sx / 11))
        c.d.line((sx, cfg.H - n, sx, cfg.H - 1), fill=CM_SNOW_SHADE)
    snowman(c, *sl["snowman"])
    present(c, *sl["present"])
    return c.finish()
