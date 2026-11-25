"""Minecraft theme: a blocky inventory screen."""

import random

from PIL import Image, ImageDraw

from .. import cfg
from ..base import CH, HEADER_BL, HEADER_H, S
from ..draw import Canvas, font, header_layout, mix, rgb
from ..registry import Theme


# Minecraft-style wording of the status line ("PLAYING Hades II"; idle: "AFK" / "rafale is AFK")
MINECRAFT_WORDS = {"boot": "LOADING WORLD", "now-playing": "PLAYING", "downloading": "DOWNLOADING TERRAIN",
                   "installing": "BUILDING TERRAIN", "verifying": "CHECKING CHUNKS",
                   "fossilize_replay": "GENERATING SHADERS", "last-session": "LAST WORLD", "idle": "AFK"}
MINECRAFT_SPLASHES = ["Ex-mining rig!", "Now with RDNA2!", "6 cores, 12 threads!", "GDDR6 for everyone!",
                      "Steam powered!", "100% blocky!", "Runs Bazzite!", "Not a Steam Deck!", "Survival mode!",
                      "Also try Phosphor!", "Mined, then crafted!", "Zen 2 inside!"]


# ---------------------------------------------------------------------------------------------------------------------
# Minecraft-inspired artwork (all drawn here: no game assets)
# ---------------------------------------------------------------------------------------------------------------------
MCR_PANEL, MCR_LIGHT, MCR_SHADE = (198, 198, 198), (255, 255, 255), (85, 85, 85)
MCR_SLOT, MCR_SLOT_DARK = (139, 139, 139), (55, 55, 55)
MCR_DIRT = [(134, 96, 67), (121, 85, 58), (150, 108, 74), (108, 76, 50), (96, 67, 45), (140, 102, 70)]
MCR_STONE = [(128, 128, 128), (118, 118, 118), (140, 140, 140), (108, 108, 108), (124, 124, 124)]
MCR_LABELS = {"ram": ("RAM", "USED"), "ssd": ("GAMES SSD", "FREE"), "pwr": ("APU PWR", "GPU MEM"),
              "rx": ("↓ DOWNLOAD", None), "tx": ("↑ UPLOAD", None), "ping": ("PING", None)}


def dirt(c, darkness):
    """The menu background: 16x16 dirt texels, 2 px each, darkened."""
    rnd = random.Random(250)
    tile = Image.new("RGB", (16, 16))
    tile.putdata([mix(rnd.choice(MCR_DIRT), (0, 0, 0), darkness) for _ in range(256)])
    tile = tile.resize((32, 32), Image.NEAREST)
    for y in range(0, cfg.H, 32):
        for x in range(0, cfg.W, 32):
            c.img.paste(tile, (x, y))


def gui_panel(c, box):
    """An inventory panel: black outline with notched corners, white top/left and dark bottom/right bevels."""
    x1, y1, x2, y2 = box
    c.d.rectangle((x1 + 1, y1, x2 - 1, y2), fill=(0, 0, 0))
    c.d.rectangle((x1, y1 + 1, x2, y2 - 1), fill=(0, 0, 0))
    c.d.rectangle((x1 + 1, y1 + 1, x2 - 1, y2 - 1), fill=MCR_PANEL)
    c.d.rectangle((x1 + 1, y1 + 1, x2 - 3, y1 + 2), fill=MCR_LIGHT)
    c.d.rectangle((x1 + 1, y1 + 1, x1 + 2, y2 - 3), fill=MCR_LIGHT)
    c.d.rectangle((x1 + 3, y2 - 2, x2 - 1, y2 - 1), fill=MCR_SHADE)
    c.d.rectangle((x2 - 2, y1 + 3, x2 - 1, y2 - 1), fill=MCR_SHADE)


def slot(c, box):
    """A sunken inventory slot: dark top/left edge, white bottom/right edge."""
    x1, y1, x2, y2 = box
    c.d.rectangle((x1, y1, x2, y2), fill=MCR_SLOT)
    c.d.line((x1, y1, x2, y1), fill=MCR_SLOT_DARK)
    c.d.line((x1, y1, x1, y2), fill=MCR_SLOT_DARK)
    c.d.line((x1, y2, x2, y2), fill=MCR_LIGHT)
    c.d.line((x2, y1, x2, y2), fill=MCR_LIGHT)


def tab(c, x, y, title):
    """A creative-inventory tab standing on a panel's top edge, (x, y) = its top-left."""
    w = len(title) * CH[S] + 10
    c.d.rectangle((x, y, x + w, y + 12), fill=(0, 0, 0))
    c.d.rectangle((x + 1, y + 1, x + w - 1, y + 12), fill=MCR_PANEL)
    c.d.line((x + 1, y + 1, x + w - 1, y + 1), fill=MCR_LIGHT)
    c.label(x + 5, y + 10, title, cfg.SKIN["value"], glow=False)


def xp_track(c, x, y, w, h):
    """The empty XP bar: dark, with notches every 1/18."""
    c.d.rectangle((x - 1, y - 1, x + w, y + h), fill=(0, 0, 0))
    c.d.rectangle((x, y, x + w - 1, y + h - 1), fill=(40, 40, 40))
    for i in range(1, 18):
        nx = x + round(i * w / 18)
        c.d.line((nx, y, nx, y + h - 1), fill=(20, 20, 20))


def chat_box(c, box):
    """The translucent black box behind chat and debug text."""
    region = c.img.crop(box)
    c.img.paste(region.point(lambda v: v * 45 // 100), box[:2])


def stone_letters(c, text, center, max_w):
    """The logo built from stone blocks: each pixel of the pixel font a textured block with a dark 3D side."""
    mask = Image.new("L", (len(text) * CH[S] + 4, 16), 0)
    ImageDraw.Draw(mask).text((1, 1), text, font=font(S), fill=255)
    box = mask.getbbox()
    if not box:
        return
    mask = mask.crop(box)
    gw, gh = mask.size
    b = next((v for v in (8, 7, 6, 5, 4, 3, 2) if gw * v + 4 <= max_w), 2)
    x0, y0 = center[0] - gw * b // 2, center[1] - gh * b // 2
    on = [(i, j) for j in range(gh) for i in range(gw) if mask.getpixel((i, j)) > 127]
    rnd = random.Random(250)
    depth = max(2, b // 2)
    for i, j in on:  # the sides, darkest at the back
        for d in range(depth, 0, -1):
            c.d.rectangle((x0 + i * b + d, y0 + j * b + d, x0 + i * b + b - 1 + d, y0 + j * b + b - 1 + d),
                          fill=mix((70, 70, 70), (25, 25, 25), d / depth))
    for i, j in on:  # the faces: a few texels of stone each, a light top edge
        x, y = x0 + i * b, y0 + j * b
        for ty in range(0, b, 2):
            for tx in range(0, b, 2):
                c.d.rectangle((x + tx, y + ty, x + min(b, tx + 2) - 1, y + min(b, ty + 2) - 1),
                              fill=rnd.choice(MCR_STONE))
        c.d.line((x, y, x + b - 1, y), fill=(170, 170, 170))
    for i, j in on:  # a dark outline where a block has no neighbour
        x, y = x0 + i * b, y0 + j * b
        if (i, j - 1) not in on:
            c.d.line((x, y - 1, x + b - 1, y - 1), fill=(30, 30, 30))
        if (i - 1, j) not in on:
            c.d.line((x - 1, y, x - 1, y + b - 1), fill=(30, 30, 30))


def render_background_minecraft(title):
    c = Canvas()
    dirt(c, 0.62)
    up_x, _, uptime_chars = header_layout(title)
    chat_box(c, (0, 0, cfg.W, HEADER_H + 1))
    c.label(6, HEADER_BL, title, (255, 255, 255), glow=False)
    if uptime_chars:
        c.label(up_x, HEADER_BL, "UP", (170, 170, 170), glow=False)

    for p, name in ((cfg.cpu, "CPU  ZEN2 6C/12T"), (cfg.gpu, "GPU  RDNA2 24CU")):
        x1, y1, x2, y2 = p["box"]
        gui_panel(c, p["box"])
        tab(c, x1 + 8, y1 - 11, name)
        c.label(p["col_a"], p["label_bl"], "TEMP", glow=False)
        c.label(p["xr"], p["label_bl"], "CLK GHZ" if p is cfg.cpu else "CLK MHZ", anchor="rs", glow=False)
        xp_track(c, *p["bar"])
        gx, gy, gw, gh = p["graph"]
        slot(c, (gx - 1, gy - 1, gx + gw, gy + gh))

    gui_panel(c, cfg.GRID)
    for key, (label, sublabel) in MCR_LABELS.items():
        cl = cfg.cells[key]
        c.label(cl["x0"], cl["label_bl"], label, glow=False)
        if sublabel:
            c.label(cl["xr"], cl["label_bl"], sublabel, cfg.SKIN["dim"], anchor="rs", glow=False)
        if key in ("ram", "ssd", "pwr"):
            xp_track(c, *cl["bar"])
        else:
            x, y, w, h = cl["spark"]
            slot(c, (x - 1, y - 1, x + w, y + h))
    for col in range(1, len(cfg.GRID_COLS)):
        x = cfg.GRID_COLS[col] - (cfg.CELL_GAP + 1) // 2
        c.d.line((x, cfg.GRID[1] + 8, x, cfg.GRID[3] - 6), fill=(160, 160, 160))

    chat_box(c, (4, cfg.PROMPT_Y, cfg.W - 4, cfg.H - 2))  # the status line, written live by Bc250Prompt in white and yellow
    return c.finish()


def render_splash_minecraft():
    """Logo, the self-test panel and the terrain bar's frame. The splash text, rows and bar are drawn live."""
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    dirt(c, 0.5)
    stone_letters(c, cfg.LOGO, sl["logo_center"], sl["logo_max_w"])
    gui_panel(c, sl["panel"])
    c.label(sl["label_x"], sl["title_bl"], f"Loading world: {cfg.SUBTITLE.title()}"[:(sl["status_xr"] - sl["label_x"]) // CH[S]],
            cfg.SKIN["value"], glow=False)
    x, y, w, h = sl["bar"]
    c.d.rectangle((x - 2, y - 2, x + w + 1, y + h + 1), outline=(255, 255, 255))
    notice = "fan theme, not by Mojang"
    c.label(cfg.W - 4, sl["footer_bl"], notice, (255, 255, 255), anchor="rs", glow=False)
    edition = f"{cfg.LOGO} Edition"
    if (len(edition) + len(notice) + 2) * CH[S] <= cfg.W - 8:  # the edition line only when it fits beside the notice
        c.label(4, sl["footer_bl"], edition, (255, 255, 255), glow=False)
    return c.finish()


def render(out, title, prompt, user):
    """Its artwork, into the theme's folder out."""
    render_background_minecraft(title).save(out / "background.png")
    render_splash_minecraft().save(out / "splash.png")


def status_line(user):
    """Its words and colours on the status line (Bc250Prompt): white and yellow on the dark chat box."""
    return {"CMD_WORDS": dict(MINECRAFT_WORDS, **{"idle-text": f"{user} is AFK"}),
            "BRIGHT": rgb((255, 255, 255)), "LABEL_COLOR": rgb((255, 255, 85)),
            "COL_WORDS": {"SESSION": "PLAYTIME", "TIME": "PLAYTIME"}}


def boot():
    """Its part of bc250_splash in theme.yaml."""
    sl = cfg.SPLASH_LAYOUT
    return {"STYLE": "minecraft", "SPLASH_TEXTS": MINECRAFT_SPLASHES, "SPLASH_AT": list(sl["splash_at"]),
            "GREEN": rgb((0, 150, 0)), "TEXT": rgb(cfg.SKIN["value"]), "WHITE": rgb((255, 255, 255)),
            "TITLE_BL": sl["title_bl"]}


THEME = Theme(
    name="minecraft",
    description="blocky inventory screen (fan theme, not affiliated with Mojang)",
    render=render,
    status_line=status_line,
    boot=boot,
)
