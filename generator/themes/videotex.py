"""Videotex theme: 40-column, 8-colour Minitel pages."""

from PIL import Image, ImageDraw

from .. import cfg
from ..base import CH, HEADER_BL, M, S, VT
from ..draw import Canvas, font, header_layout, rgb, spaced
from ..registry import Theme


# videotex ticker wording ("EN COURS : Hades II"; idle: "EN VEILLE" / "3615 <CODE>")
VIDEOTEX_WORDS = {"boot": "CONNEXION", "now-playing": "EN COURS :", "downloading": "TÉLÉCHARGEMENT :",
                  "installing": "INSTALLATION :", "verifying": "VÉRIFICATION :", "fossilize_replay": "SHADERS :",
                  "last-session": "DERNIÈRE PARTIE :", "idle": "EN VEILLE"}


def videotex_code(logo):
    """The service code of the boot screen: 3615 + the logo's letters and digits."""
    return "3615 " + ("".join(ch for ch in logo.upper() if ch.isalnum())[:12] or "BC250")


# ---------------------------------------------------------------------------------------------------------------------
# Videotex artwork
# ---------------------------------------------------------------------------------------------------------------------
VT_PAGES = ((VT["b"], "CPU", "ZEN2 6C/12T", "FREQ GHZ"), (VT["m"], "GPU", "RDNA2 24CU", "FREQ MHZ"))
VT_LABELS = {"ram": ("MÉMOIRE", "UTIL."), "ssd": ("DISQUE JEUX", "LIBRE"), "pwr": ("PUISS. APU", "MEM GPU"),
             "rx": ("↓ RÉCEPTION", None), "tx": ("↑ ÉMISSION", None), "ping": ("PING", None)}


def mosaic_text(c, text, center, color, max_w, shadow=None):
    """Big letters made of separated mosaic blocks, as videotex drew its titles: each pixel of the pixel font
    becomes a block, with a one-pixel gap around it. Returns the block size used."""
    mask = Image.new("L", (len(text) * CH[S] + 4, 16), 0)
    ImageDraw.Draw(mask).text((1, 1), text, font=font(S), fill=255)
    box = mask.getbbox()
    if not box:
        return None
    mask = mask.crop(box)
    gw, gh = mask.size
    bw = next((b for b in (8, 6, 5, 4, 3, 2) if gw * b <= max_w), 2)
    bh = max(2, round(bw * 0.75))
    x0, y0 = center[0] - gw * bw // 2, center[1] - gh * bh // 2
    gap = 1 if bw >= 4 else 0
    for layer, (dx, dy) in ((shadow, (max(1, bw // 3), max(1, bh // 3))), (color, (0, 0))):
        if layer is None:
            continue
        for j in range(gh):
            for i in range(gw):
                if mask.getpixel((i, j)) > 127:
                    x, y = x0 + i * bw + dx, y0 + j * bh + dy
                    c.d.rectangle((x, y, x + bw - 1 - gap, y + bh - 1 - gap), fill=layer)
    return bw, bh


def mosaic_track(c, x, y, w, h, color):
    """The empty track of a bar: a row of separated blocks."""
    for bx in range(x, x + w, 6):
        c.d.rectangle((bx, y, min(bx + 4, x + w - 1), y + h - 1), fill=color)


def render_background_videotex(title):
    c = Canvas()
    up_x, _, uptime_chars = header_layout(title)
    c.label(6, HEADER_BL, title, VT["w"], glow=False)  # the teletext header line: page, service, date, time
    if uptime_chars:
        c.label(up_x, HEADER_BL, "UP", VT["c"], glow=False)

    for p, (band_color, name, subtitle, clk) in zip((cfg.cpu, cfg.gpu), VT_PAGES):
        c.d.rectangle(p["band"], fill=band_color)
        bx1, by1, bx2, by2 = p["band"]
        c.label(p["x0"], by1 + 21, name, VT["w"], size=M, glow=False)  # double height, as videotex titles were
        c.label(p["x0"] + 4 * CH[M], by1 + 16, subtitle, VT["y"], glow=False)
        c.label(p["col_a"], p["label_bl"], "TEMP", VT["c"], glow=False)
        c.label(p["xr"], p["label_bl"], clk, VT["c"], anchor="rs", glow=False)
        mosaic_track(c, *p["bar"], VT["b"])
        gx, gy, gw, gh = p["graph"]
        c.d.line((gx, gy + gh - 1, gx + gw - 1, gy + gh - 1), fill=VT["b"])

    c.d.rectangle((0, cfg.GRID[1] - 8, cfg.W, cfg.GRID[1] + 3), fill=VT["c"])
    c.label(12, cfg.GRID[1] + 2, "SYS  MÉMOIRE / STOCKAGE / RÉSEAU", VT["k"], glow=False)
    for key, (label, sublabel) in VT_LABELS.items():
        cl = cfg.cells[key]
        c.label(cl["x0"], cl["label_bl"], label, VT["c"], glow=False)
        if sublabel:
            c.label(cl["xr"], cl["label_bl"], sublabel, VT["b"], anchor="rs", glow=False)
        if key in ("ram", "ssd", "pwr"):
            mosaic_track(c, *cl["bar"], VT["b"])

    c.d.rectangle((0, cfg.PROMPT_Y, cfg.W, cfg.H), fill=VT["b"])  # the ticker band, written live by Bc250Prompt
    return c.finish()


def render_splash_videotex(title, layer="full"):
    """layer: "blank" (the terminal before connecting: an F in the status corner) or "full" (the 3615 service page,
    which the boot draws row by row; the dialling and the self-test values are drawn live by sensors_bc250)."""
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    sx = cfg.W - 18
    connected = layer == "full"
    c.d.rectangle((sx, 2, sx + 11, 14), fill=VT["g"] if connected else VT["w"])
    c.label(sx + 6, 12, "C" if connected else "F", VT["k"], anchor="ms", glow=False)
    if not connected:
        return c.finish()

    code = videotex_code(cfg.LOGO)
    c.label(6, HEADER_BL, code, VT["w"], glow=False)
    c.d.rectangle(sl["band"], fill=VT["b"])
    mosaic_text(c, cfg.LOGO, sl["logo_center"], VT["y"], sl["logo_max_w"], shadow=VT["r"])
    c.label(cfg.W // 2, sl["sub_bl"], spaced(cfg.SUBTITLE), VT["w"], anchor="ms", glow=False)

    head = sl["head_bl"]
    c.d.rectangle((0, head - 10, cfg.W, head + 3), fill=VT["c"])
    c.label(sl["label_x"], head, "SERVICE", VT["k"], glow=False)
    c.label(sl["status_xr"], head, "ÉTAT", VT["k"], anchor="rs", glow=False)
    c.label(sl["label_x"], sl["progress_bl"], "CHARGEMENT", VT["y"], glow=False)
    mosaic_track(c, *sl["bar"], VT["b"])

    fx1, fy1, fx2, fy2 = sl["footer"]
    c.d.rectangle(sl["footer"], fill=VT["m"])
    c.label(fx1 + 12, fy2 - 5, f"Connecté au {code}"[:(fx2 - fx1 - 80) // CH[S]], VT["w"], glow=False)
    c.d.rectangle((fx2 - 54, fy1 + 3, fx2 - 12, fy2 - 3), fill=VT["w"])
    c.label(fx2 - 33, fy2 - 6, "ENVOI", VT["k"], anchor="ms", glow=False)
    return c.finish()


def render(out, title, prompt, user):
    """Its artwork, into the theme's folder out."""
    render_background_videotex(title).save(out / "background.png")
    render_splash_videotex(title, "full").save(out / "splash.png")
    render_splash_videotex(title, "blank").save(out / "splash_blank.png")


def status_line(user):
    """Its words and colours on the status line (Bc250Prompt)."""
    return {"CMD_WORDS": dict(VIDEOTEX_WORDS, **{"idle-text": videotex_code(cfg.LOGO)}),
            "LABEL_COLOR": rgb(cfg.SKIN["accent"]), "PROGRESS_STYLE": "mosaic",
            "COL_WORDS": {"DONE": "FAIT", "ETA": "RESTE", "RATE": "DÉBIT", "SESSION": "DURÉE",
                          "TIME": "DURÉE", "PEAK C/G": "PIC C/G"}}


def boot():
    """Its part of bc250_splash in theme.yaml."""
    sl = cfg.SPLASH_LAYOUT
    return {"STYLE": "videotex", "IMAGE_BLANK": "splash_blank.png", "CODE": videotex_code(cfg.LOGO),
            "GREEN": rgb(VT["g"]), "BLUE": rgb(VT["b"]), "STATUS_CELL": [cfg.W - 18, 2, 12, 13],
            "DIAL_X": sl["dial_x"], "DIAL_BL": list(sl["dial_bl"]), "FOOTER": list(sl["footer"])}


THEME = Theme(
    name="videotex",
    description="40-column, 8-colour videotex pages",
    render=render,
    title="P250 {LOGO}",
    status_line=status_line,
    boot=boot,
)
