"""Nixie theme: a Nixie tube instrument panel."""

import random

from PIL import Image, ImageChops, ImageDraw

from .. import cfg
from ..base import CH, L, M, S
from ..draw import Canvas, font_file, rgb, spaced, text
from ..registry import Theme


# Nixie status line wording
NIXIE_WORDS = {"boot": "WARMING UP", "now-playing": "NOW PLAYING", "downloading": "DOWNLOADING",
               "installing": "INSTALLING", "verifying": "VERIFYING", "fossilize_replay": "COMPILING SHADERS",
               "last-session": "LAST GAME", "idle": "STANDBY", "idle-text": "170 V standing by"}


# ---------------------------------------------------------------------------------------------------------------------
# Nixie artwork and layout
# ---------------------------------------------------------------------------------------------------------------------
NIXIE_FONT = "roboto/Roboto-Light.ttf"  # thin, even strokes: the shape of a Nixie cathode
NX_BRASS, NX_BRASS_DIM, NX_GLASS = (190, 150, 85), (120, 95, 58), (22, 16, 13)
NX_GHOST = (95, 72, 56)  # the unlit cathodes seen through the glass
NIXIE = {}  # set by nixie_layout()


def nixie_layout(portrait):
    """Every position of the Nixie theme: tube displays (with their bar tubes and warning lamps), the clock's colon
    dots, engraved labels and the plain readouts the app draws itself."""
    labels, readouts, displays, boxes = [], {}, [], []

    def tubes(x, n, w, gap):
        return [x + i * (w + gap) for i in range(n)]

    def clock(cx, y, w, h):
        pair_gap, colon_gap = 3, 14
        total = 6 * w + 3 * pair_gap + 2 * colon_gap
        xs, x = [], cx - total // 2
        for i in range(6):
            xs.append(x)
            x += w + (pair_gap if i % 2 == 0 else colon_gap)
        colons = [[xs[i] + w + colon_gap // 2, y + round(h * f)] for i in (1, 3) for f in (0.36, 0.64)]
        displays.append(dict(SOURCE="clock", XS=xs, Y=y, W=w, H=h, FORMAT="{}"))
        return colons

    def stage(box, name, subtitle, src, clk_tubes, clk_fmt, clk_label, w, h, temp_dx):
        x1, y1, x2, y2 = box
        boxes.append(box)
        x0, xr = x1 + 10, x2 - 10
        labels.extend([(x0, y1 + 14, name, "ls", NX_BRASS), (x0 + 6 * CH[S], y1 + 14, subtitle, "ls", NX_BRASS_DIM)])
        ty, pitch = y1 + 20, w + 2
        under = ty + h + 11
        labels.extend([(x0, under, "LOAD %", "ls", NX_BRASS_DIM), (x0 + temp_dx, under, "TEMP °C", "ls", NX_BRASS_DIM),
                       (xr, under, clk_label, "rs", NX_BRASS_DIM)])
        bar_x, bar_w = x0 + 34, xr - (x0 + 34)
        load_bar, temp_bar = under + 9, under + 21
        labels.extend([(x0, load_bar + 6, "LOAD", "ls", NX_BRASS_DIM), (x0, temp_bar + 6, "TEMP", "ls", NX_BRASS_DIM)])
        displays.extend([
            dict(SOURCE=f"{src}_load", XS=tubes(x0, 3, w, 2), Y=ty, W=w, H=h, FORMAT="{:3.0f}",
                 BAR=[bar_x, load_bar, bar_w, 5, 0, 100]),
            dict(SOURCE=f"{src}_temp", XS=tubes(x0 + temp_dx, 2, w, 2), Y=ty, W=w, H=h, FORMAT="{:2.0f}",
                 ALERT=cfg.TEMP_ALERT, LAMP=[xr - 4, y1 + 10, 5], BAR=[bar_x, temp_bar, bar_w, 5, cfg.TEMP_GRAPH_MIN, cfg.TEMP_GRAPH_MAX]),
            dict(SOURCE=f"{src}_clk", XS=tubes(xr - clk_tubes * pitch + 2, clk_tubes, w, 2), Y=ty, W=w, H=h,
                 FORMAT=clk_fmt),
        ])

    def gauge(x, cell_w, label_bl, label, src, maximum, w, h, gap, bar_dx, bar_y, readout):
        labels.append((x, label_bl, label, "ls", NX_BRASS_DIM))
        displays.append(dict(SOURCE=src, XS=tubes(x, 3, w, gap), Y=label_bl + 4, W=w, H=h, FORMAT="{:3.0f}",
                             BAR=[x + bar_dx, bar_y, cell_w - bar_dx, 5, 0, maximum]))
        readouts[readout] = (x + cell_w, label_bl)

    if not portrait:
        title = dict(logo=(12, 30), sub=(12, 48))
        colons = clock(240, 6, 26, 56)
        readouts.update(date=(474, 24), uptime=(474, 44))
        stage((4, 68, 236, 180), "CPU", "ZEN2 6C/12T", "cpu", 3, "{:4.2f}", "CLK GHZ", 17, 38, 73)
        stage((244, 68, 476, 180), "GPU", "RDNA2 24CU", "gpu", 4, "{:4.0f}", "CLK MHZ", 17, 38, 73)
        boxes.append((4, 186, 476, 272))
        for x, label, src, maximum, readout in ((14, "RAM %", "ram", 100, "used"), (170, "SSD %", "ssd", 100, "free"),
                                                (326, "APU W", "pwr", cfg.POWER_BAR_MAX, "gpumem")):
            gauge(x, 140, 200, label, src, maximum, 15, 32, 2, 59, 214, readout)
        for x, label, key in ((14, "↓ DOWN", "rx"), (170, "↑ UP", "tx"), (326, "PING", "ping")):
            labels.append((x, 248, label, "ls", NX_BRASS_DIM))
            readouts[key] = (x, 268, M)
        prompt_box = (4, 276, 476, 318)
    else:
        title = dict(logo=(8, 14), sub=None)
        readouts.update(date=(312, 14))
        colons = clock(160, 22, 30, 62)
        readouts.update(uptime=(8, 100), ping=(312, 100, S))
        stage((4, 106, 316, 210), "CPU", "ZEN2 6C/12T", "cpu", 3, "{:4.2f}", "CLK GHZ", 19, 40, 92)
        stage((4, 214, 316, 318), "GPU", "RDNA2 24CU", "gpu", 4, "{:4.0f}", "CLK MHZ", 19, 40, 92)
        boxes.append((4, 324, 316, 420))
        for x, label, src, maximum, readout in ((14, "RAM %", "ram", 100, "used"), (118, "SSD %", "ssd", 100, "free"),
                                                (222, "APU W", "pwr", cfg.POWER_BAR_MAX, "gpumem")):
            gauge(x, 88, 338, label, src, maximum, 14, 30, 1, 52, 352, readout)
        for x, label, key in ((14, "↓ DOWN", "rx"), (162, "↑ UP", "tx")):
            labels.append((x, 388, label, "ls", NX_BRASS_DIM))
            readouts[key] = (x, 408, M)
        prompt_box = (4, 422, 316, 478)
    NIXIE.clear()
    NIXIE.update(title=title, colons=colons, readouts=readouts, displays=displays, labels=labels, boxes=boxes,
                 prompt_box=prompt_box)


NX_LAMP_LABELS = ("CPU", "MEM", "GPU", "TEMP", "DISK", "NET", "STEAM")


def brushed_panel(c):
    """Black anodised front with a faint horizontal brush."""
    rnd = random.Random(250)
    for y in range(cfg.H):
        v = 9 + rnd.randrange(0, 4)
        c.d.line((0, y, cfg.W, y), fill=(v, v - 1, v - 2))


def brass_frame(c, box):
    x1, y1, x2, y2 = box
    c.d.rounded_rectangle(box, radius=3, outline=NX_BRASS_DIM)
    for sx, sy in ((x1 + 4, y1 + 4), (x2 - 4, y1 + 4), (x1 + 4, y2 - 4), (x2 - 4, y2 - 4)):
        c.d.ellipse((sx - 1, sy - 1, sx + 1, sy + 1), fill=NX_BRASS_DIM)  # screw heads


def nixie_mesh(w, h):
    """The anode mesh in front of the cathodes: a fine diamond grid (sensors_bc250 uses the same pattern)."""
    m = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(m)
    for k in range(-h, w + h, 4):
        d.line((k, 0, k + h, h), fill=200)
        d.line((k, h, k + h, 0), fill=200)
    return m


def unlit_tube(c, x, y, w, h):
    """A Nixie tube switched off: dark glass, the stack of cathodes faintly visible behind the mesh."""
    tube = Image.new("RGB", (w, h), (8, 6, 5))
    d = ImageDraw.Draw(tube)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=max(3, w // 3), fill=NX_GLASS, outline=(64, 50, 40))
    f = font_file(NIXIE_FONT, int(h * 0.82))
    ghost = Image.new("L", (w * 2, h), 0)
    for digit in "0123456789":
        ImageDraw.Draw(ghost).text((w, h // 2 + 1), digit, font=f, fill=46, anchor="mm")
    tube.paste(NX_GHOST, (0, 0, w, h), ghost.resize((w, h)))
    tube = ImageChops.multiply(tube, Image.merge("RGB", [nixie_mesh(w, h)] * 3))
    ImageDraw.Draw(tube).line((2, 4, 2, h - 6), fill=(64, 58, 54))  # glass reflection
    c.img.paste(tube, (x, y))


def bar_tube(c, x, y, w, h):
    """An empty IN-13 style bar tube: a thin dark glass rod."""
    c.d.rounded_rectangle((x - 2, y - 2, x + w + 1, y + h + 1), radius=3, fill=NX_GLASS, outline=(64, 50, 40))


def neon_lamp(c, x, y, r):
    c.d.ellipse((x - r, y - r, x + r, y + r), fill=(40, 22, 18), outline=(70, 52, 42))


def render_background_nixie(title):
    nx = NIXIE
    c = Canvas()
    brushed_panel(c)
    logo_size = M if len(cfg.LOGO) * CH[M] <= 124 else S
    lx, lb = nx["title"]["logo"]
    c.label(lx, lb, cfg.LOGO if nx["title"]["sub"] or len(cfg.LOGO) * CH[logo_size] <= 124 else cfg.LOGO[:20], NX_BRASS,
            size=logo_size if nx["title"]["sub"] else S, glow=False)
    if nx["title"]["sub"]:
        c.label(nx["title"]["sub"][0], nx["title"]["sub"][1], cfg.SUBTITLE[:20], NX_BRASS_DIM, glow=False)
    for box in nx["boxes"]:
        brass_frame(c, box)
    brass_frame(c, nx["prompt_box"])
    for x, bl, text_, anchor, color in nx["labels"]:
        c.label(x, bl, text_, color, anchor=anchor, glow=False)
    for disp in nx["displays"]:
        for x in disp["XS"]:
            unlit_tube(c, x, disp["Y"], disp["W"], disp["H"])
        if "BAR" in disp:
            bar_tube(c, *disp["BAR"][:4])
        if "LAMP" in disp:
            neon_lamp(c, *disp["LAMP"])
    for x, y in nx["colons"]:
        neon_lamp(c, x, y, 2)
    return c.finish()


def render_splash_nixie(prompt):
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    brushed_panel(c)
    size = L if len(cfg.LOGO) * CH[L] <= cfg.W - 24 else M if len(cfg.LOGO) * CH[M] <= cfg.W - 24 else S
    c.label(cfg.W // 2, sl["logo_bl"], cfg.LOGO, NX_BRASS, anchor="ms", size=size, glow=False)
    c.label(cfg.W // 2, sl["sub_bl"], spaced(cfg.SUBTITLE), NX_BRASS_DIM, anchor="ms", glow=False)
    for x in sl["tube_xs"]:
        unlit_tube(c, x, sl["tube_y"], *sl["tube"])
    for x, y in sl["colons"]:
        neon_lamp(c, x, y, 3)
    for (x, y), name in zip(sl["lamps"], NX_LAMP_LABELS):
        neon_lamp(c, x, y, 6)
        c.label(x, sl["lamp_label_bl"], name, NX_BRASS_DIM, anchor="ms", glow=False)
    c.label(cfg.W // 2, sl["footer_bl"], f"NIXIE BOARD  170 V  {prompt}"[:(cfg.W - 16) // CH[S]], NX_BRASS_DIM, anchor="ms",
            glow=False)
    return c.finish()


def nixie_theme(theme, title):
    """Replaces the dashboard widgets of a theme built by build_theme(): the tubes draw almost everything, the app
    keeps the plain readouts (date, uptime, network, ping, small sub-values), the prompt and the screen power."""
    nx, ro = NIXIE, NIXIE["readouts"]
    custom = theme["STATS"]["CUSTOM"]
    amber, dim = cfg.SKIN["value"], NX_BRASS
    spec = {"FONT": NIXIE_FONT, "DISPLAYS": nx["displays"], "COLONS": nx["colons"], "BACKGROUND_IMAGE": "background.png",
            "GLOW": rgb((255, 90, 18)), "CORE": rgb((255, 196, 120)), "LAMP_ON": rgb((255, 60, 30))}
    stats = {
        "MEMORY": {"INTERVAL": 2, "VIRTUAL": {"USED": text(*ro["used"], S, 8, dim, right=True)}},
        "NET": {"INTERVAL": 1, "ETH": {"DOWNLOAD": {"TEXT": text(ro["rx"][0], ro["rx"][1], M, 11, amber)},
                                       "UPLOAD": {"TEXT": text(ro["tx"][0], ro["tx"][1], M, 11, amber)}}},
        "PING": {"INTERVAL": 5, "TEXT": text(ro["ping"][0], ro["ping"][1], ro["ping"][2], 8, amber,
                                             right=ro["ping"][2] == S)},
        "DATE": {"INTERVAL": 1, "DAY": {"TEXT": text(*ro["date"], S, 14, amber, right=True, FORMAT="EEE dd MMM")}},
        "UPTIME": {"INTERVAL": 1, "FORMATTED": {"TEXT": text(*ro["uptime"], S, 20, NX_BRASS_DIM,
                                                             right=ro["uptime"][0] > cfg.W // 2)}},
        "CUSTOM": {
            "INTERVAL": 1,
            # sampled for the tubes (and the session peaks), drawn by nothing else
            # (an empty entry would be written as null, which the app can't read)
            "Bc250CpuTemp": {"ALERT": cfg.TEMP_ALERT}, "Bc250GpuTemp": {"ALERT": cfg.TEMP_ALERT},
            "Bc250GpuLoad": {"SAMPLE_ONLY": True}, "Bc250ApuPower": {"SAMPLE_ONLY": True},
            "Bc250GameDiskFree": {"TEXT": text(*ro["free"], S, 7, dim, right=True)},
            "Bc250GpuMem": {"TEXT": text(*ro["gpumem"], S, 6, dim, right=True)},
            "Bc250Nixie": spec,
            "Bc250Prompt": custom["Bc250Prompt"],
            "Bc250Screen": custom["Bc250Screen"],
        },
    }
    theme["STATS"] = stats
    return theme


def render(out, title, prompt, user):
    """Its artwork, into the theme's folder out."""
    nixie_layout(cfg.PORTRAIT)  # here: it needs the --alert and power options
    render_background_nixie(title).save(out / "background.png")
    render_splash_nixie(prompt).save(out / "splash.png")


def status_line(user):
    """Its words and colours on the status line (Bc250Prompt)."""
    return {"CMD_WORDS": NIXIE_WORDS, "LABEL_COLOR": rgb(NX_BRASS)}


def boot():
    """Its part of bc250_splash in theme.yaml."""
    sl = cfg.SPLASH_LAYOUT
    return {"STYLE": "nixie", "NIXIE_FONT": NIXIE_FONT, "TUBE_XS": sl["tube_xs"], "TUBE_Y": sl["tube_y"],
            "TUBE_W": sl["tube"][0], "TUBE_H": sl["tube"][1], "COLONS": sl["colons"], "LAMPS": sl["lamps"],
            "LAMP_NAMES": list(NX_LAMP_LABELS), "TEXT_BL": sl["text_bl"], "GLOW": rgb((255, 90, 18)),
            "CORE": rgb((255, 196, 120)), "LAMP_ON": rgb((255, 60, 30))}


THEME = Theme(
    name="nixie",
    description="Nixie tube instrument panel",
    render=render,
    status_line=status_line,
    boot=boot,
    widgets=lambda theme, title, user: nixie_theme(theme, title),
)
