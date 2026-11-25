"""The theme being generated: the options (make_theme.py sets them from its command line) and its layout
(set_layout: every position, one block per theme and orientation). Other modules read them as cfg.NAME,
so they always see the current values."""

from .base import (CH, CLOCK_CHARS, L, M, nixie_splash_layout, ORBIT_LAYOUT, RADAR_LAYOUT, RADAR_SPLASH, S,
                   SEISMO_LAYOUT, SKINS)


FONTS_DIR = None  # <app>/res/fonts, set from --app

# --- Settings (overridable from the command line) ---------------------------------------------------------------------
PROMPT_USER = "steam"  # steam@bc250:~$
PROMPT_HOST = "bc250"
TITLE = None  # header text; None = "<LOGO>::<USER>"
LOGO = "BC-250"  # big title of the boot splash
SUBTITLE = "STEAM MACHINE"  # under it, letter-spaced
TEMP_COLD = 40  # °C at or below which temperatures are fully "cold"
TEMP_HOT = 70  # °C at or above which temperatures are fully "hot"
TEMP_ALERT = 80  # °C from which temperatures flash "HOT!"
POWER_LOW = 100  # W at or below which APU power is "cold"
POWER_HIGH = 200  # W at or above which APU power is fully "hot"
POWER_BAR_MAX = 250  # W for a full bar
TEMP_GRAPH_MIN, TEMP_GRAPH_MAX = 30, 90
DIM_AFTER = 10  # minutes without game or download before dimming (0 = never)
DIM_BRIGHTNESS = 5  # % when dimmed
NIGHT = ""  # e.g. "23:30-08:00": screen off (or dimmed) during these hours unless a game is running
NIGHT_MODE = "off"  # "off" or "dim"
SPLASH = True  # boot screen played before the dashboard
RADAR_LAT, RADAR_LON = 49.0097, 2.5479  # radar theme: centre of the scope (default: Paris CDG airport, a public place)
RADAR_RANGE = 50  # km
SEISMO_STATION = None  # seismograph theme: (lat, lon) to show each quake's distance from, kept on the machine
SEISMO_MIN_MAG = 2.5  # seismograph theme: the smallest quake it records
ORBIT_SITE = None  # orbit theme: (lat, lon) to work out the ISS's passes over, kept on the machine
SKIN_NAME = "phosphor"
SKIN = SKINS[SKIN_NAME]


def phosphor_panel(x1, y1, x2, y2, col_a_offset):
    """A CPU/GPU panel of the phosphor theme: LOAD (big) | TEMP | CLK on one row, bar, chart."""
    x0, xr = x1 + 10, x2 - 10
    value_bl = y1 + 40
    return {
        "box": (x1, y1, x2, y2),
        "x0": x0,
        "xr": xr,  # right edge shared by bar, graph and right column
        "col_a": x0 + col_a_offset,  # left-anchored middle column (TEMP)
        "label_bl": y1 + 18,  # small labels above values
        "load": dict(x=x0, bl=value_bl, size=L, right=False),
        "temp": dict(x=x0 + col_a_offset, bl=value_bl, right=False),
        "clk": dict(x=xr, bl=value_bl, right=True),
        "tag": (x1 + 8, y1 - 6, 32, 13),  # where HOT! flashes (x, y, w, h): over the panel's name tag
        "bar": (x0, y1 + 48, xr - x0, 8),
        "graph": (x0, y1 + 66, xr - x0, (y2 - y1) - 74),
    }


def gameboy_card(x1, y1, x2, y2):
    """A CPU/GPU 'party card' of the Game Boy theme: NAME .. TEMP / HP bar .. LOAD% / CLK / chart."""
    x0, xr = x1 + 12, x2 - 12
    if (y2 - y1) >= 130:  # tall card: LOAD% at the end of the HP bar, under the temperature
        name_bl, hp_bl, clk_bl = y1 + 28, y1 + 52, y1 + 76
        load = dict(x=xr, bl=hp_bl, size=M, right=True)
        bar_box = (x0 + 22, hp_bl - 8, (xr - 58) - (x0 + 22), 6)
    else:  # short card: no room for a value on the HP row, so LOAD% sits on the name row, left of the temperature
        name_bl, hp_bl, clk_bl = y1 + 24, y1 + 38, y1 + 60
        load = dict(x=xr - 70, bl=name_bl, size=M, right=True)
        bar_box = (x0 + 22, hp_bl - 6, xr - (x0 + 22), 6)
    graph_y = clk_bl + 10
    return {
        "box": (x1, y1, x2, y2),
        "x0": x0,
        "xr": xr,
        "name_bl": name_bl,
        "hp_bl": hp_bl,
        "clk_bl": clk_bl,
        "load": load,
        "temp": dict(x=xr, bl=name_bl, right=True),
        "clk": dict(x=x0 + 30, bl=clk_bl, right=False),
        "tag": (x0 - 3, name_bl - 19, 3 * CH[M] + 6, 22),  # HOT! flashes over the card's name
        "bar": bar_box,
        "graph": (x0, graph_y, xr - x0, (y2 - 8) - graph_y),
    }


def videotex_page(x1, y1, x2, y2, col_a_offset):
    """A CPU/GPU videotex "page": a coloured double-height title band, LOAD (big) | TEMP | CLK, bar, mosaic chart."""
    x0, xr = x1 + 12, x2 - 12
    return {
        "box": (x1, y1, x2, y2),
        "band": (x1, y1, x2, y1 + 24),
        "x0": x0,
        "xr": xr,
        "col_a": x0 + col_a_offset,
        "label_bl": y1 + 36,
        "load": dict(x=x0, bl=y1 + 60, size=L, right=False),
        "temp": dict(x=x0 + col_a_offset, bl=y1 + 60, right=False),
        "clk": dict(x=xr, bl=y1 + 60, right=True),
        "tag": (xr - 36, y1 + 5, 36, 14),  # HOT! flashes at the right end of the title band
        "bar": (x0, y1 + 66, xr - x0, 8),
        "graph": (x0, y1 + 80, xr - x0, (y2 - 4) - (y1 + 80)),
    }


def cell(x0, y0, width):
    """A system-grid cell: label row, value row, then a bar or a sparkline."""
    return {"x0": x0, "xr": x0 + width, "y0": y0,
            "label_bl": y0 + 10, "value_bl": y0 + 32,
            "bar": (x0, y0 + 37, width, 6),
            "spark": (x0, y0 + 37, width, 9)}


def set_layout(portrait: bool, skin: str = "phosphor"):
    global PORTRAIT, SKIN_NAME, SKIN, W, H, CLOCK_XR, DATE_XR, cpu, gpu, GRID, GRID_COLS, CELL_W, CELL_GAP, cells
    global PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL, PROMPT_COLS_BL, PROMPT_X, PROMPT_XR, PROMPT_AREA
    global PROMPT_COL1_XR, PROMPT_COLS, SPLASH_LAYOUT, RADAR
    PORTRAIT, SKIN_NAME, SKIN = portrait, skin, SKINS[skin]
    gameboy, retro, videotex, mission, blocky, nixie, radar, haunted, festive, horror, seismo, orbit, board, wheel = (
        skin == name for name in ("gameboy", "retrowave", "videotex", "mission", "minecraft", "nixie", "radar",
                                  "halloween", "christmas", "horror", "seismograph", "orbit", "departures", "racing"))
    card = gameboy_card if gameboy else (lambda *box: phosphor_panel(*box, col_a_offset=130 if portrait else 100))
    if not portrait:  # 480x320: CPU and GPU side by side, 3x2 grid, one-line prompt
        W, H = 480, 320
        DATE_XR = W - 6 - CLOCK_CHARS * CH[S] - 12
        cpu, gpu = (card(4, 22, 238, 162), card(242, 22, 476, 162)) if gameboy else \
                   (card(4, 26, 237, 162), card(243, 26, 476, 162))
        GRID, CELL_W, CELL_GAP, grid_cols, grid_rows = (4, 170, 476, 274), 142, 13, 3, 2
        order = (("ram", 0, 0), ("ssd", 1, 0), ("pwr", 2, 0), ("rx", 0, 1), ("tx", 1, 1), ("ping", 2, 1))
        PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL, PROMPT_COLS_BL = 278, 290, 314, None
        PROMPT_COL1_XR = 380  # right edge of the first right-hand column (FPS / DONE / TIME)
        if gameboy:
            GRID = (4, 166, 476, 270)
            PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL = 274, 288, 309
            SPLASH_LAYOUT = dict(
                logo_box=(96, 21, 288, 75), logo_center_y=60, sub_bl=104, menu=(6, 116, 474, 300),
                row_bl=144, row_step=17, label_x=30, value_x=96, status_xr=460,
                progress_bl=270, bar=(190, 262, 460 - 190, 8), status_bl=290, footer_bl=314)
        else:
            SPLASH_LAYOUT = dict(
                logo_box=(96, 21, 288, 75), logo_center_y=60, sub_bl=104, sep_y=114,
                row_bl=132, row_step=15, label_x=14, value_x=86, status_xr=466,
                progress_bl=254, bar=(214, 246, 466 - 214, 8), status_bl=284,
                footer=((14, 312, "left", "press"), (466, 312, "right", "prompt")))
        if retro:  # sunset in the sky, neon grid floor from the horizon, POST panel standing on the floor
            SPLASH_LAYOUT = dict(
                horizon=134, sun=(240, 124, 60), logo_center=(240, 62), logo_max_w=330, sub_bl=116,
                panel=(56, 146, 424, 314), row_bl=168, row_step=14, label_x=68, value_x=116, status_xr=412,
                progress_bl=272, bar=(128, 265, 412 - 128, 7), status_bl=296)
        if videotex:  # a 12 px grid: 40 columns; pages side by side, the SYS grid, a ticker band
            cpu, gpu = videotex_page(0, 16, 240, 148, 96), videotex_page(240, 16, 480, 148, 96)
            GRID, CELL_W, CELL_GAP = (2, 156, 478, 268), 144, 12
            PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL = 268, 283, 311
            SPLASH_LAYOUT = dict(
                band=(0, 16, 480, 112), logo_center=(240, 56), logo_max_w=432, sub_bl=104, head_bl=128,
                row_bl=145, row_step=14, label_x=12, value_x=84, status_xr=468, progress_bl=252,
                bar=(96, 244, 468 - 96, 8), status_bl=276, footer=(0, 296, 480, 316), dial_x=48,
                dial_bl=(160, 196, 216, 236, 256))
        if mission:  # nameplate and countdown clock on top, the poll in the big CRT
            SPLASH_LAYOUT = dict(
                plate=(8, 6, 288, 56), count_box=(296, 6, 473, 56), count_bl=49, crt=(8, 62, 472, 312),
                head_bl=82, row_bl=108, row_step=22, label_x=20, value_x=104, status_xr=460,
                status_bl=270, liftoff_bl=294, progress_bl=0, bar=(0, 0, 0, 0))  # no loading bar: the countdown
        if blocky:  # logo and splash text on dirt, the self-test in a panel, the terrain bar under it
            SPLASH_LAYOUT = dict(
                logo_center=(240, 46), logo_max_w=330, splash_at=(404, 62), panel=(30, 90, 450, 254),
                title_bl=106, row_bl=127, row_step=17, label_x=44, value_x=104, status_xr=436,
                progress_bl=272, bar=(140, 280, 200, 6), status_bl=272, footer_bl=313)
        if haunted:  # a graveyard under the moon with the dripping logo, the seance below, two jack-o'-lanterns
            SPLASH_LAYOUT = dict(
                horizon=112, moon=(410, 40, 24), logo_center=(196, 52), logo_max_w=300, panel=(24, 120, 456, 268),
                title_bl=137, row_bl=156, row_step=15, label_x=36, value_x=110, status_xr=444,
                progress_bl=287, caption=(120, 360), bar=(150, 295, 180, 6), status_bl=287,
                pumpkins=((50, 293, 17), (430, 293, 17)))
        if festive:  # a snowy night with the logo and the tree, Santa's list below, a snowman and a present
            SPLASH_LAYOUT = dict(
                horizon=112, moon=(356, 30, 17), logo_center=(196, 58), logo_max_w=300, tree=(428, 14, 108, 32),
                panel=(24, 120, 456, 268), title_bl=137, row_bl=156, row_step=15, label_x=36, value_x=110,
                status_xr=444, progress_bl=287, caption=(90, 390), bar=(150, 295, 180, 6), status_bl=287,
                snowman=(50, 312, 1.0), present=(412, 286, 36, 26))
    else:  # 320x480: panels stacked, 2x3 grid, prompt with its values on a row of their own
        W, H = 320, 480
        DATE_XR = None  # no room for the date in the header
        cpu, gpu = (card(4, 22, 316, 130), card(4, 136, 316, 244)) if gameboy else \
                   (card(4, 26, 316, 138), card(4, 146, 316, 258))
        GRID, CELL_W, CELL_GAP, grid_cols, grid_rows = (4, 266, 316, 418), 140, 12, 2, 3
        order = (("ram", 0, 0), ("ssd", 1, 0), ("pwr", 0, 1), ("ping", 1, 1), ("rx", 0, 2), ("tx", 1, 2))
        PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL, PROMPT_COLS_BL = 422, 434, 455, 476
        PROMPT_COL1_XR = None
        if gameboy:
            GRID = (4, 252, 316, 404)
            PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL, PROMPT_COLS_BL = 408, 423, 445, 467
            SPLASH_LAYOUT = dict(
                logo_box=(16, 26, 288, 90), logo_center_y=71, sub_bl=132, menu=(6, 150, 314, 440),
                row_bl=180, row_step=20, label_x=30, value_x=82, status_xr=300,
                progress_bl=338, bar=(30, 348, 270, 8), status_bl=384, footer_bl=466)
        else:
            SPLASH_LAYOUT = dict(
                logo_box=(16, 26, 288, 90), logo_center_y=71, sub_bl=132, sep_y=142,
                row_bl=166, row_step=20, label_x=14, value_x=70, status_xr=306,
                progress_bl=324, bar=(14, 334, 292, 8), status_bl=372,
                footer=((14, 454, "left", "press"), (14, 470, "left", "prompt")))
        if retro:
            SPLASH_LAYOUT = dict(
                horizon=200, sun=(160, 186, 70), logo_center=(160, 118), logo_max_w=290, sub_bl=178,
                panel=(12, 236, 308, 470), row_bl=262, row_step=18, label_x=26, value_x=74, status_xr=294,
                progress_bl=402, bar=(86, 395, 294 - 86, 7), status_bl=432, footer_bl=456)
        if videotex:
            cpu, gpu = videotex_page(0, 16, 320, 136, 130), videotex_page(0, 136, 320, 256, 130)
            GRID = (0, 264, 320, 420)
            PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL, PROMPT_COLS_BL = 420, 434, 455, 476
            SPLASH_LAYOUT = dict(
                band=(0, 16, 320, 148), logo_center=(160, 70), logo_max_w=296, sub_bl=136, head_bl=166,
                row_bl=186, row_step=18, label_x=12, value_x=84, status_xr=308, progress_bl=334,
                bar=(96, 326, 308 - 96, 8), status_bl=364, footer=(0, 452, 320, 476), dial_x=24,
                dial_bl=(200, 240, 262, 284, 306))
        if mission:
            SPLASH_LAYOUT = dict(
                plate=(8, 6, 312, 58), count_box=(8, 64, 312, 112), count_bl=104, crt=(8, 120, 312, 472),
                head_bl=140, row_bl=168, row_step=26, label_x=18, value_x=84, status_xr=302,
                status_bl=372, liftoff_bl=400, progress_bl=0, bar=(0, 0, 0, 0))  # no loading bar: the countdown
        if blocky:
            SPLASH_LAYOUT = dict(
                logo_center=(160, 52), logo_max_w=290, splash_at=(240, 92), panel=(10, 116, 310, 322),
                title_bl=133, row_bl=158, row_step=24, label_x=22, value_x=82, status_xr=298,
                progress_bl=356, bar=(60, 366, 200, 6), status_bl=356, footer_bl=470)
        if haunted:
            SPLASH_LAYOUT = dict(
                horizon=150, moon=(276, 32, 18), logo_center=(150, 84), logo_max_w=250, panel=(10, 160, 310, 384),
                title_bl=178, row_bl=202, row_step=24, label_x=22, value_x=82, status_xr=298,
                progress_bl=410, caption=(40, 280), bar=(70, 420, 180, 6), status_bl=410,
                pumpkins=((42, 452, 19), (278, 452, 19)))
        if festive:
            SPLASH_LAYOUT = dict(
                horizon=150, moon=(40, 32, 16), logo_center=(138, 92), logo_max_w=230, tree=(278, 22, 146, 34),
                panel=(10, 160, 310, 384), title_bl=178, row_bl=202, row_step=24, label_x=22, value_x=82,
                status_xr=298, progress_bl=410, caption=(10, 310), bar=(70, 420, 180, 6), status_bl=410,
                snowman=(42, 474, 1.3), present=(254, 440, 44, 34))
    if nixie:  # the tubes are laid out by nixie_layout(); this is the boot screen
        SPLASH_LAYOUT = nixie_splash_layout(portrait)
        tw, th = SPLASH_LAYOUT["tube"]
        xs, x = [], W // 2 - (6 * tw + 3 * 4 + 2 * 18) // 2
        for i in range(6):
            xs.append(x)
            x += tw + (4 if i % 2 == 0 else 18)
        ty = SPLASH_LAYOUT["tube_y"]
        lx1, lx2 = SPLASH_LAYOUT["lamps_x"]
        SPLASH_LAYOUT.update(
            tube_xs=xs, colons=[[xs[i] + tw + 9, ty + round(th * f)] for i in (1, 3) for f in (0.36, 0.64)],
            lamps=[[lx1 + i * (lx2 - lx1) // 6, SPLASH_LAYOUT["lamps_y"]] for i in range(7)],
            row_bl=SPLASH_LAYOUT["text_bl"], row_step=0, label_x=16, value_x=16, status_xr=W - 16, progress_bl=0,
            bar=(0, 0, 0, 0))
    CLOCK_XR = W - 6
    GRID_COLS = [GRID[0] + 10 + i * (CELL_W + CELL_GAP) for i in range(grid_cols)]
    grid_rows_y = [GRID[1] + 8 + i * 48 for i in range(grid_rows)]
    cells = {name: cell(GRID_COLS[col], grid_rows_y[row], CELL_W) for name, col, row in order}
    PROMPT_X, PROMPT_XR = (18, W - 18) if gameboy else (12, W - 12) if videotex else (14, W - 14)
    # redrawn as a whole by Bc250Prompt: phosphor = below a dotted line, gameboy = inside the dialog box,
    # videotex = the whole ticker band
    PROMPT_AREA = (6, PROMPT_Y + 3, W - 12, H - PROMPT_Y - 6) if gameboy else (6, PROMPT_Y + 2, W - 12, H - PROMPT_Y - 2)
    if videotex:
        PROMPT_AREA = (0, PROMPT_Y, W, H - PROMPT_Y)
    if blocky:
        for p in (cpu, gpu):  # HOT! flashes over the name on the panel's tab
            p["tag"] = (p["box"][0] + 8, p["box"][1] - 11, 5 * CH[S] + 2, 12)
    if mission:
        for p in (cpu, gpu):  # ALARM (5 letters) over the nameplate instead of HOT!
            p["tag"] = (p["box"][0] + 8, p["box"][1] - 6, 5 * CH[S] + 12, 13)
    # portrait: values on their own row, in two half-width columns (small label left, value right)
    half = (PROMPT_XR - PROMPT_X - CELL_GAP) // 2
    PROMPT_COLS = [[PROMPT_X, PROMPT_X + half], [PROMPT_XR - half, PROMPT_XR]] if portrait else None
    if horror:  # the camera's feed on the left (top in portrait), the console beside (below) it; the boot is a POST
        DATE_XR = None
        SPLASH_LAYOUT = dict(row_bl=64 if not portrait else 84, row_step=16 if not portrait else 22, label_x=14,
                             value_x=86 if not portrait else 74, status_xr=W - 14, progress_bl=0, status_bl=0,
                             bar=(0, 0, 0, 0))
    if seismo:  # the sheet of paper on top, the map, the last quake and the readings under it; the boot writes on the paper
        DATE_XR = None
        px, py, pw, _ = SEISMO_LAYOUT[portrait]["paper"]
        SPLASH_LAYOUT = dict(row_bl=py + (24 if portrait else 20), row_step=22 if portrait else 17, label_x=px + 10,
                             value_x=px + (66 if portrait else 76), status_xr=px + pw - 10, progress_bl=0, status_bl=0,
                             bar=(0, 0, 0, 0))
    if orbit:  # the map on top, the ISS's card, the next pass and the readings under it; the boot's console over them
        DATE_XR = None
        lx1, ly1, lx2, _ = ORBIT_LAYOUT[portrait]["log"]
        col_w = (lx2 - lx1) // ORBIT_LAYOUT[portrait]["log_columns"]
        SPLASH_LAYOUT = dict(row_bl=ly1 + 14, row_step=ORBIT_LAYOUT[portrait]["log_step"], label_x=lx1 + 8,
                             value_x=lx1 + 62, status_xr=lx1 + col_w - 8, progress_bl=0, status_bl=0, bar=(0, 0, 0, 0))
    if board or wheel:  # the board (or the wheel) above, the status line under it; the boot's checks run on that line
        DATE_XR = None
        SPLASH_LAYOUT = dict(row_bl=PROMPT_VALUE_BL, row_step=0, label_x=PROMPT_X, value_x=PROMPT_X,
                             status_xr=PROMPT_XR, progress_bl=0, status_bl=0, bar=(0, 0, 0, 0))
    if radar:  # scope on the left (top in portrait), the flight card, list, CPU/GPU and prompt beside (below) it
        RADAR.update(RADAR_LAYOUT[portrait])
        DATE_XR = None
        if not portrait:
            PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL, PROMPT_COLS_BL = 258, 272, 294, 314
            PROMPT_X, PROMPT_XR, PROMPT_AREA = 314, 474, (312, 260, 166, 60)
            PROMPT_COLS = [[314, 392], [396, 474]]
        else:
            PROMPT_Y, PROMPT_LABEL_BL, PROMPT_VALUE_BL, PROMPT_COLS_BL = 432, 444, 470, None
            PROMPT_X, PROMPT_XR, PROMPT_AREA, PROMPT_COL1_XR = 8, 312, (4, 434, 312, 46), 236
            PROMPT_COLS = None
        SPLASH_LAYOUT = dict(RADAR_SPLASH[portrait], progress_bl=0, bar=(0, 0, 0, 0))
    SPLASH_LAYOUT.setdefault("logo_max_w", 256)  # leaves room in the logo box for the 3D sway and perspective
    SPLASH_LAYOUT["value_chars"] = (SPLASH_LAYOUT["status_xr"] - 6 * CH[S] - 8 - SPLASH_LAYOUT["value_x"]) // CH[S]
    if mission:  # the status is a lamp, wider than a word
        SPLASH_LAYOUT["value_chars"] -= 3
    if haunted or festive:  # STIRRING, BURNING, WRAPPING and NAUGHTY are longer than OK
        SPLASH_LAYOUT["value_chars"] -= 2


set_layout(portrait=False)
RETRO_REVEAL_BOX = (0, 0, 0, 0)  # what the logo and subtitle change on the splash, measured when it is rendered
HW_REVEAL_BOX = (0, 0, 1, 1)  # where the logo is (with its drips), set in main: the boot bleeds it in
CM_REVEAL_BOX = (0, 0, 1, 1)  # where the logo is, set in main: the boot reveals it


# ---------------------------------------------------------------------------------------------------------------------
# Radar artwork, map and theme
# ---------------------------------------------------------------------------------------------------------------------
RADAR = {}  # set by set_layout()
