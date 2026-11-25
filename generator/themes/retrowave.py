"""Retrowave theme: a neon synthwave sunset."""

import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .. import cfg
from ..base import CH, GRID_LABELS, HEADER_BL, HEADER_H, RETRO_LOGO_FONT, RETRO_TAG_FONT, S
from ..draw import Canvas, font, font_file, header_layout, mix, prompt_prefix, rgb, spaced
from ..registry import Theme


# arcade wording of the retrowave prompt ("1UP RAFALE NOW PLAYING", idle: "PRESS START" / "INSERT COIN")
RETRO_WORDS = {"boot": "BOOTING", "now-playing": "NOW PLAYING", "downloading": "DOWNLOADING",
               "installing": "INSTALLING", "verifying": "VERIFYING", "fossilize_replay": "COMPILING",
               "last-session": "LAST GAME", "idle": "PRESS START", "idle-text": "INSERT COIN"}



# ---------------------------------------------------------------------------------------------------------------------
# Retrowave artwork
# ---------------------------------------------------------------------------------------------------------------------
RETRO_SKY = [(0.0, (8, 2, 28)), (0.55, (44, 8, 78)), (1.0, (140, 24, 116))]  # top of the sky .. horizon
RETRO_FLOOR = [(0.0, (46, 6, 70)), (1.0, (10, 0, 24))]  # horizon .. bottom of the screen
RETRO_CHROME = [(0.0, (40, 60, 160)), (0.42, (180, 230, 255)), (0.5, (255, 255, 255)), (0.53, (60, 18, 84)),
                (0.72, (255, 110, 70)), (1.0, (255, 225, 120))]  # top .. bottom of the chrome letters
RETRO_SUN = [(0.0, (255, 236, 110)), (0.55, (255, 120, 90)), (1.0, (255, 40, 150))]


def stops(colors, t):
    """Colour at t (0..1) along [(position, colour), ...]."""
    t = max(0.0, min(1.0, t))
    for (p1, c1), (p2, c2) in zip(colors, colors[1:]):
        if t <= p2:
            return mix(c1, c2, (t - p1) / (p2 - p1) if p2 > p1 else 0.0)
    return colors[-1][1]


def vgradient(c, box, colors):
    x1, y1, x2, y2 = box
    for y in range(y1, y2 + 1):
        c.d.line((x1, y, x2, y), fill=stops(colors, (y - y1) / max(1, y2 - y1)))


def retro_logo(text):
    """Size of the chrome logo (largest that fits) and the box of its letters on the splash."""
    for size in range(64, 15, -4):
        f = font_file(RETRO_LOGO_FONT, size)
        left, top, right, bottom = f.getbbox(text, anchor="mm")
        if right - left <= cfg.SPLASH_LAYOUT["logo_max_w"]:
            break
    cx, cy = cfg.SPLASH_LAYOUT["logo_center"]
    return {"size": size, "font": f,
            "face_box": (max(0, cx + left - 3), max(0, cy + top - 3), min(cfg.W, cx + right + 3), min(cfg.H, cy + bottom + 3))}


def retro_subtitle_font(text):
    """The 80s face when the letter-spaced subtitle fits, the pixel font otherwise."""
    f = font_file(RETRO_TAG_FONT, 14)
    return f if f.getlength(text) <= cfg.W - 24 else font(S)


def neon_frame(c, box, title=None, subtitle=None):
    """Glowing pink tube with cyan corners; the title (80s face) and subtitle sit in a gap of the top line."""
    x1, y1, x2, y2 = box
    clean = c.img.crop((x1, y1 - 7, x2 + 1, y1 + 8))
    c.d.rounded_rectangle(box, radius=3, outline=cfg.SKIN["mid"])
    c.g.rounded_rectangle(box, radius=3, outline=mix(cfg.SKIN["mid"], (0, 0, 0), 0.35))
    for cx, cy, sx, sy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        for d in (c.d, c.g):
            d.line((cx + 3 * sx, cy, cx + 10 * sx, cy), fill=cfg.SKIN["value"])
            d.line((cx, cy + 3 * sy, cx, cy + 10 * sy), fill=cfg.SKIN["value"])
    if title:
        tf = font_file(RETRO_TAG_FONT, 14)
        end = x1 + 12 + round(tf.getlength(title))
        if subtitle:
            end += 6 + len(subtitle) * CH[S]
        c.img.paste(clean.crop((6, 0, end - x1 + 4, clean.height)), (x1 + 6, y1 - 7))
        c.glow.paste((0, 0, 0), (x1 + 6, y1 - 7, end + 4, y1 + 8))
        c.d.text((x1 + 10, y1 + 5), title, font=tf, fill=cfg.SKIN["value"], anchor="ls")
        c.g.text((x1 + 10, y1 + 5), title, font=tf, fill=mix(cfg.SKIN["value"], (0, 0, 0), 0.5), anchor="ls")
        if subtitle:
            c.label(x1 + 16 + round(tf.getlength(title)), y1 + 4, subtitle, (190, 130, 230), glow=False)


def neon_floor(c, y0, y1, color, spacing, near=1.0):
    """Static perspective grid from a horizon at y0 down to y1, fading into the distance."""
    fh = y1 - y0
    for i in range(-14, 15):
        xb = cfg.W / 2 + i * spacing
        for t in range(1, 8):  # brighter towards the viewer: drawn in 7 segments
            ya, yb = y0 + fh * (t - 1) / 7, y0 + fh * t / 7
            fx = lambda y: cfg.W / 2 + (xb - cfg.W / 2) * (y - y0) / fh
            c.d.line((fx(ya), ya, fx(yb), yb), fill=mix(c.img.getpixel((cfg.W // 2, min(cfg.H - 1, round(yb)))),
                                                         color, near * (0.25 + 0.75 * t / 7)))
    z = 1.0
    while True:
        y = y0 + fh * 0.9 / z
        if y - y0 < 2:
            break
        if y < y1:
            c.d.line((0, round(y), cfg.W, round(y)), fill=mix(c.img.getpixel((cfg.W // 2, round(y))), color,
                                                           near * (0.25 + 0.75 * (y - y0) / fh)))
        z += 1.0


def render_background_retrowave(title, user):
    c = Canvas()
    up_x, _, uptime_chars = header_layout(title)
    floor_y = cfg.PROMPT_Y

    # night sky over the panels, a neon floor under the prompt
    vgradient(c, (0, 0, cfg.W - 1, floor_y), [(0.0, (12, 3, 30)), (1.0, (34, 6, 58))])
    vgradient(c, (0, floor_y, cfg.W - 1, cfg.H - 1), RETRO_FLOOR)
    neon_floor(c, floor_y, cfg.H, (150, 40, 170), cfg.W // 8, near=0.55)

    # header band: a sunset from orange to violet
    for x in range(cfg.W):
        c.d.line((x, 0, x, HEADER_H), fill=stops([(0.0, (255, 150, 60)), (0.5, (255, 60, 160)),
                                                   (1.0, (150, 60, 230))], x / (cfg.W - 1)))
    c.g.rectangle((0, 0, cfg.W, HEADER_H), fill=(90, 20, 70))
    c.label(6, HEADER_BL, title, cfg.SKIN["ink"], glow=False)
    if uptime_chars:
        c.label(up_x, HEADER_BL, "UP", (110, 20, 80), glow=False)

    for p, name, subtitle, clk in ((cfg.cpu, "CPU", "ZEN2 6C/12T", "CLK GHZ"), (cfg.gpu, "GPU", "RDNA2 24CU", "CLK MHZ")):
        neon_frame(c, p["box"], name, subtitle)
        c.label(p["col_a"], p["label_bl"], "TEMP", glow=False)
        c.label(p["xr"], p["label_bl"], clk, anchor="rs", glow=False)
        c.bar_track(*p["bar"])
        c.graph_grid(*p["graph"])
        if p["graph"][3] >= 50:
            c.label(p["xr"] - 2, p["graph"][1] + 10, "°C 60s", cfg.SKIN["dim"], anchor="rs", glow=False)

    neon_frame(c, cfg.GRID, "SYS", "MEM / STORAGE / NET")
    for key, label, sublabel, kind in GRID_LABELS:
        cl = cfg.cells[key]
        c.label(cl["x0"], cl["label_bl"], label, glow=False)
        if sublabel:
            c.label(cl["xr"], cl["label_bl"], sublabel, cfg.SKIN["dim"], anchor="rs", glow=False)
        if kind == "bar":
            c.bar_track(*cl["bar"], ticks=False)
        else:
            c.graph_grid(*cl["spark"])
    for col in range(1, len(cfg.GRID_COLS)):
        c.dotted_vline(cfg.GRID_COLS[col] - (cfg.CELL_GAP + 1) // 2, cfg.GRID[1] + 8, cfg.GRID[3] - 4)

    # the horizon under the panels, then "1UP RAFALE" (the arcade wording is drawn live by Bc250Prompt)
    c.d.line((0, floor_y, cfg.W, floor_y), fill=(255, 110, 220))
    c.g.line((0, floor_y, cfg.W, floor_y), fill=(200, 40, 150))
    c.label(cfg.PROMPT_X, cfg.PROMPT_LABEL_BL, prompt_prefix(user, ""), glow=False)
    return c.finish()


def render_splash_retrowave(layer="full"):
    """layer: "blank" (sky, sun and an empty floor), "nologo" (+ the POST panel) or "full" (+ logo and subtitle).
    The scrolling grid on the floor is drawn live by sensors_bc250."""
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    horizon = sl["horizon"]
    vgradient(c, (0, 0, cfg.W - 1, horizon), RETRO_SKY)
    vgradient(c, (0, horizon, cfg.W - 1, cfg.H - 1), RETRO_FLOOR)
    rnd = random.Random(250)  # same stars on every run
    for _ in range(cfg.W * horizon // 900):
        x, y = rnd.randrange(cfg.W), rnd.randrange(int(horizon * 0.7))
        c.d.point((x, y), fill=mix(c.img.getpixel((x, y)), (255, 230, 255), rnd.uniform(0.3, 0.9)))

    # the sun: warm gradient, cut by widening bands towards the horizon
    sx, sy, r = sl["sun"]
    sun = Image.new("RGB", (2 * r + 1, 2 * r + 1))
    mask = Image.new("L", sun.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * r, 2 * r), fill=255)
    sd, md = ImageDraw.Draw(sun), ImageDraw.Draw(mask)
    for y in range(2 * r + 1):
        sd.line((0, y, 2 * r, y), fill=stops(RETRO_SUN, y / (2 * r)))
    y, gap = r - r // 6, 1.0
    while y < 2 * r:
        md.rectangle((0, round(y), 2 * r, round(y + gap) - 1), fill=0)
        y += gap + 6
        gap += 0.9
    md.rectangle((0, horizon - (sy - r), 2 * r, 2 * r), fill=0)  # set behind the horizon
    c.img.paste(sun, (sx - r, sy - r), mask)
    c.glow.paste(sun.point(lambda v: v // 2), (sx - r, sy - r), mask)

    c.d.line((0, horizon, cfg.W, horizon), fill=(255, 120, 230))
    c.g.line((0, horizon, cfg.W, horizon), fill=(255, 60, 190))

    if layer != "blank":
        c.d.rectangle(sl["panel"], fill=(14, 2, 30))
        c.g.rectangle(sl["panel"], fill=(0, 0, 0))
        neon_frame(c, sl["panel"], "SYSTEM CHECK")
        c.label(sl["label_x"], sl["progress_bl"], "LOADING", glow=False)
        x, y, w, h = sl["bar"]
        c.d.rectangle((x - 2, y - 2, x + w + 1, y + h + 1), outline=cfg.SKIN["dim"])

    if layer == "full":
        logo = retro_logo(cfg.LOGO)
        cx, cy = sl["logo_center"]
        face = Image.new("L", (cfg.W, cfg.H), 0)
        ImageDraw.Draw(face).text((cx, cy), cfg.LOGO, font=logo["font"], fill=255, anchor="mm")
        rim = face.filter(ImageFilter.MaxFilter(5))
        shadow = Image.new("L", (cfg.W, cfg.H), 0)
        shadow.paste(rim, (3, 3))
        c.img.paste(cfg.SKIN["ink"], (0, 0, cfg.W, cfg.H), shadow)
        c.img.paste(cfg.SKIN["mid"], (0, 0, cfg.W, cfg.H), rim)
        c.glow.paste(mix(cfg.SKIN["mid"], (0, 0, 0), 0.2), (0, 0, cfg.W, cfg.H), rim)
        chrome = Image.new("RGB", (cfg.W, cfg.H))
        top, bottom = face.getbbox()[1], face.getbbox()[3]
        cd = ImageDraw.Draw(chrome)
        for y in range(top, bottom + 1):
            cd.line((0, y, cfg.W, y), fill=stops(RETRO_CHROME, (y - top) / max(1, bottom - top)))
        c.img.paste(chrome, (0, 0), face)
        c.glow.paste((0, 0, 0), (0, 0, cfg.W, cfg.H), face)  # the letters stay crisp, only the rim glows

        sub = spaced(cfg.SUBTITLE)
        f = retro_subtitle_font(sub)
        c.d.text((cfg.W // 2, sl["sub_bl"]), sub, font=f, fill=cfg.SKIN["value"], anchor="ms",
                 stroke_width=2, stroke_fill=cfg.SKIN["ink"])
        c.g.text((cfg.W // 2, sl["sub_bl"]), sub, font=f, fill=mix(cfg.SKIN["value"], (0, 0, 0), 0.5), anchor="ms")
    return c.finish()


def render(out, title, prompt, user):
    """Its artwork, into the theme's folder out."""
    render_background_retrowave(title, user).save(out / "background.png")
    full, nologo = render_splash_retrowave("full"), render_splash_retrowave("nologo")
    cfg.RETRO_REVEAL_BOX = ImageChops.difference(full, nologo).getbbox() or (0, 0, 1, 1)
    full.save(out / "splash.png")
    nologo.save(out / "splash_nologo.png")
    render_splash_retrowave("blank").save(out / "splash_blank.png")


def status_line(user):
    """Its words and colours on the status line (Bc250Prompt)."""
    return {"CMD_WORDS": RETRO_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["accent"])}


def boot():
    """Its part of bc250_splash in theme.yaml."""
    sl = cfg.SPLASH_LAYOUT
    logo = retro_logo(cfg.LOGO)
    return {"STYLE": "retrowave", "IMAGE_BLANK": "splash_blank.png", "LOGO_FONT": RETRO_LOGO_FONT,
            "LOGO_SIZE": logo["size"], "LOGO_CENTER": list(sl["logo_center"]),
            "LOGO_BOX": list(logo["face_box"]), "REVEAL_BOX": list(cfg.RETRO_REVEAL_BOX),
            "HORIZON": sl["horizon"], "PANEL": list(sl["panel"]), "GRID_COLOR": rgb(cfg.SKIN["mid"]),
            "GRID_SPACING": cfg.W // 8, "FOOTER_BL": sl.get("footer_bl", 0)}


THEME = Theme(
    name="retrowave",
    description="neon synthwave sunset",
    render=render,
    status_line=status_line,
    boot=boot,
)
