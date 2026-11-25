"""Game Boy theme: a 4-shade handheld RPG status screen."""

from .. import cfg
from ..base import CH, DMG, GRID_LABELS, HEADER_BL, HEADER_H, M
from ..draw import Canvas, header_layout, logo_baseline, logo_size, rgb, spaced
from ..registry import Theme


# RPG wording of the Game Boy dialog box ("RAFALE IS PLAYING")
GAMEBOY_WORDS = {"boot": "IS BOOTING", "now-playing": "IS PLAYING", "downloading": "IS DOWNLOADING",
                 "installing": "IS INSTALLING", "verifying": "IS VERIFYING", "fossilize_replay": "IS COMPILING",
                 "last-session": "LAST PLAYED", "idle": "IS RESTING", "idle-text": "Zzz"}


# ---------------------------------------------------------------------------------------------------------------------
# Game Boy artwork
# ---------------------------------------------------------------------------------------------------------------------
def render_background_gameboy(title, user):
    c = Canvas()
    dark, mid = DMG[3], DMG[2]
    up_x, _, uptime_chars = header_layout(title)

    # Top line: title, uptime, clock on the bare screen, underlined
    c.label(6, HEADER_BL, title, dark, glow=False)
    if uptime_chars:
        c.label(up_x, HEADER_BL, "UP", mid, glow=False)
    c.d.rectangle((4, HEADER_H + 1, cfg.W - 5, HEADER_H + 2), fill=dark)

    # Party cards: NAME .. TEMP / HP bar .. LOAD% / CLK / chart
    for p, name, subtitle, unit in ((cfg.cpu, "CPU", "ZEN2 6C/12T", "GHZ"), (cfg.gpu, "GPU", "RDNA2 24CU", "MHZ")):
        c.rpg_box(p["box"])
        c.label(p["x0"], p["name_bl"], name, dark, size=M, glow=False)
        c.label(p["x0"] + 3 * CH[M] + 8, p["name_bl"], subtitle, mid, glow=False)
        bx, by, bw, bh = p["bar"]
        c.hp_bar(bx, by, bw, bh, "HP")
        c.label(p["x0"], p["clk_bl"], "CLK", mid, glow=False)
        c.label(p["clk"]["x"] + 4 * CH[M] + 4, p["clk_bl"], unit, mid, glow=False)
        gx, gy, gw, gh = p["graph"]
        c.d.line((gx, gy + gh - 1, gx + gw - 1, gy + gh - 1), fill=mid)  # chart floor

    # ITEMS box: the same cells as the phosphor grid, with RPG menu markers
    c.rpg_box(cfg.GRID, "ITEMS")
    for key, label, sublabel, kind in GRID_LABELS:
        cl = cfg.cells[key]
        c.label(cl["x0"], cl["label_bl"], label.replace("↓ ", "").replace("↑ ", ""), mid, glow=False)
        if sublabel:
            c.label(cl["xr"], cl["label_bl"], sublabel, mid, anchor="rs", glow=False)
        if kind == "bar":
            x, y, w, h = cl["bar"]
            c.d.rectangle((x - 1, y - 1, x + w, y + h), outline=mid)
        else:
            x, y, w, h = cl["spark"]
            c.d.line((x, y + h, x + w - 1, y + h), fill=DMG[1])

    # Dialog box: "RAFALE IS PLAYING" / game name
    c.rpg_box((4, cfg.PROMPT_Y, cfg.W - 5, cfg.H - 3), inner=False)  # no inner line: the text needs the room
    c.label(cfg.PROMPT_X, cfg.PROMPT_LABEL_BL, user.upper(), mid, glow=False)
    return c.finish()


def render_splash_gameboy(title, prompt, logo=True, menu=True):
    sl = cfg.SPLASH_LAYOUT
    c = Canvas()
    dark, mid = DMG[3], DMG[2]
    if logo:
        size = logo_size(cfg.LOGO)
        c.label(cfg.W // 2, logo_baseline(size), cfg.LOGO, dark, anchor="ms", size=size, glow=False)
    if menu:
        c.label(cfg.W // 2, sl["sub_bl"], spaced(cfg.SUBTITLE), mid, anchor="ms", glow=False)
        c.rpg_box(sl["menu"], "SYSTEM CHECK")
        c.label(sl["label_x"], sl["progress_bl"], "LOADING", mid, glow=False)
        x, y, w, h = sl["bar"]
        c.hp_bar(x, y, w, h, "HP" if x > sl["label_x"] + 60 else "")
        c.label(cfg.W // 2, sl["footer_bl"], "PRESS START", mid, anchor="ms", glow=False)
    return c.finish()


def render(out, title, prompt, user):
    """Its artwork, into the theme's folder out."""
    render_background_gameboy(title, user).save(out / "background.png")
    render_splash_gameboy(title, prompt).save(out / "splash.png")
    render_splash_gameboy(title, prompt, logo=False).save(out / "splash_nologo.png")
    render_splash_gameboy(title, prompt, logo=False, menu=False).save(out / "splash_blank.png")


def status_line(user):
    """Its words and colours on the status line (Bc250Prompt)."""
    return {"CMD_WORDS": GAMEBOY_WORDS, "CURSOR": "▼", "LABEL_COLOR": rgb(cfg.SKIN["mid"])}


def boot():
    """Its part of bc250_splash in theme.yaml."""
    return {"STYLE": "gameboy", "IMAGE_BLANK": "splash_blank.png", "LIGHT": rgb(DMG[1])}


THEME = Theme(
    name="gameboy",
    description="4-shade handheld RPG status screen",
    render=render,
    status_line=status_line,
    boot=boot,
    pixel_logo=True,  # BIOS-style boot
)
