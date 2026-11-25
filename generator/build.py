"""theme.yaml, shared by all themes (widget positions come from the layout)."""

from . import cfg
from .base import CH, CLOCK_CHARS, FONT, HEADER_BL, M, S
from .draw import bar, header_layout, heat_colors, heat_widget, line, logo_baseline, logo_size, prompt_prefix, rgb, text
from .registry import themes


def build_theme(title, prompt, user):
    _, uptime_x, uptime_chars = header_layout(title)
    net_spark = dict(max_value=10_000_000_000, autoscale=True)
    ram, ssd, pwr, rx, tx, ping = (cfg.cells[k] for k in ("ram", "ssd", "pwr", "rx", "tx", "ping"))
    sl = cfg.SPLASH_LAYOUT
    on_dark = ("gameboy", "videotex", "mission", "halloween", "christmas")
    header_ink = cfg.SKIN["value"] if cfg.SKIN_NAME in on_dark else cfg.SKIN["ink"]  # minecraft: white
    clock_ink = cfg.SKIN["accent"] if cfg.SKIN_NAME in ("videotex", "mission") else header_ink  # the time in yellow / amber
    if cfg.SKIN_NAME in ("halloween", "christmas"):
        clock_ink = cfg.SKIN["mid"]  # pumpkin, gold
    date = {"INTERVAL": 1}
    if cfg.DATE_XR:
        day_format = "'DAY' DDD" if cfg.SKIN_NAME == "mission" else "EEE dd MMM"  # mission clocks: day of the year
        date["DAY"] = {"TEXT": text(cfg.DATE_XR, HEADER_BL, S, 14, header_ink, right=True, FORMAT=day_format)}
    date["HOUR"] = {"TEXT": text(cfg.CLOCK_XR, HEADER_BL, S, CLOCK_CHARS, clock_ink, right=True, FORMAT="HH:mm:ss")}
    prompt_spec = {
        "AREA": {"X": cfg.PROMPT_AREA[0], "Y": cfg.PROMPT_AREA[1], "WIDTH": cfg.PROMPT_AREA[2],
                 "HEIGHT": cfg.PROMPT_AREA[3], "BACKGROUND_IMAGE": "background.png"},
        "FONT": FONT, "BRIGHT": rgb(cfg.SKIN["value"]), "MID": rgb(cfg.SKIN["mid"]), "DIM": rgb(cfg.SKIN["dim"]),
        "AMBER": rgb(cfg.SKIN["accent"]),
        "LABEL_BL": cfg.PROMPT_LABEL_BL, "VALUE_BL": cfg.PROMPT_VALUE_BL,
        "CMD_X": cfg.PROMPT_X + (len(prompt_prefix(user, prompt)) + 1) * CH[S] if prompt_prefix(user, prompt) else cfg.PROMPT_X,
        "TEXT_X": cfg.PROMPT_X,
    }
    own = themes()[cfg.SKIN_NAME]  # what the theme declares (generator/themes/<theme>.py)
    if own.status_line:
        prompt_spec.update(own.status_line(user))
    if cfg.PROMPT_COLS:  # portrait: the name gets the whole row, values go on the row below
        prompt_spec.update({"COLS_BL": cfg.PROMPT_COLS_BL, "COLS": cfg.PROMPT_COLS,
                            "MAX_CHARS": (cfg.PROMPT_XR - cfg.PROMPT_X) // CH[M] - 1,
                            "MAX_CHARS_WIDE": (cfg.PROMPT_XR - cfg.PROMPT_X) // CH[M] - 1})
    else:
        prompt_spec.update({"COL1_XR": cfg.PROMPT_COL1_XR, "COL2_XR": cfg.PROMPT_XR,
                            "MAX_CHARS": (cfg.PROMPT_COL1_XR - 4 * CH[M] - 12 - cfg.PROMPT_X) // CH[M] - 1,
                            "MAX_CHARS_WIDE": (cfg.PROMPT_XR - 5 * CH[M] - 12 - cfg.PROMPT_X) // CH[M] - 1})
    splash = {
        "ENABLED": cfg.SPLASH, "IMAGE": "splash.png", "FONT": FONT, "ALERT": cfg.TEMP_ALERT,
        "BRIGHT": rgb(cfg.SKIN["value"]), "MID": rgb(cfg.SKIN["mid"]), "DIM": rgb(cfg.SKIN["dim"]),
        "AMBER": rgb(cfg.SKIN["accent"]), "ALERT_COLOR": rgb(cfg.SKIN["alert"]),
        "BG": rgb(cfg.SKIN["bg"]), "ROW_BL": sl["row_bl"], "ROW_STEP": sl["row_step"], "ROWS": 7,
        "LABEL_X": sl["label_x"], "VALUE_X": sl["value_x"], "STATUS_XR": sl["status_xr"],
        "VALUE_CHARS": sl["value_chars"],
        "PROGRESS_BL": sl["progress_bl"], "STATUS_BL": sl["status_bl"], "BAR_X": sl["bar"][0],
        "BAR_Y": sl["bar"][1], "BAR_W": sl["bar"][2], "BAR_H": sl["bar"][3],
        "IMAGE_NOLOGO": "splash_nologo.png", "LOGO_TEXT": cfg.LOGO,
    }
    if own.pixel_logo:  # the logo in the pixel font
        splash.update({"LOGO_SIZE": logo_size(cfg.LOGO), "LOGO_BL": logo_baseline(logo_size(cfg.LOGO)),
                       "LOGO_BOX": list(sl["logo_box"])})
    if own.boot:
        splash.update(own.boot())
    load = lambda p: text(p["load"]["x"], p["load"]["bl"], p["load"]["size"], 4, right=p["load"]["right"])
    clock = lambda p, **kw: text(p["clk"]["x"], p["clk"]["bl"], M, 4, right=p["clk"]["right"], **kw)
    theme = {
        "author": "BC-250 Steam Machine",
        # read by sensors_bc250 (not by the app itself): the boot sequence played before the dashboard
        "bc250_splash": splash,
        "display": {"DISPLAY_SIZE": '3.5"', "DISPLAY_ORIENTATION": "portrait" if cfg.PORTRAIT else "landscape",
                    "DISPLAY_RGB_LED": rgb(cfg.SKIN["mid"])},
        "static_images": {"BACKGROUND": {"PATH": "background.png", "X": 0, "Y": 0, "WIDTH": cfg.W, "HEIGHT": cfg.H}},
        "STATS": {
            "CPU": {
                "PERCENTAGE": {"INTERVAL": 1, "TEXT": load(cfg.cpu), "GRAPH": bar(*cfg.cpu["bar"])},
                "FREQUENCY": {"INTERVAL": 2, "TEXT": clock(cfg.cpu, unit=False)},
            },
            "MEMORY": {
                "INTERVAL": 2,
                "VIRTUAL": {
                    "PERCENT_TEXT": text(ram["x0"], ram["value_bl"], M, 4),
                    "USED": text(ram["xr"], ram["value_bl"], S, 8, cfg.SKIN["mid"], right=True),
                    "GRAPH": bar(*ram["bar"]),
                },
            },
            "NET": {
                "INTERVAL": 1,
                "ETH": {
                    "DOWNLOAD": {"TEXT": text(rx["x0"], rx["value_bl"], M, 11),
                                 "LINE_GRAPH": line(*rx["spark"], **net_spark)},
                    "UPLOAD": {"TEXT": text(tx["x0"], tx["value_bl"], M, 11),
                               "LINE_GRAPH": line(*tx["spark"], **net_spark)},
                },
            },
            "PING": {
                "INTERVAL": 5,
                "TEXT": text(ping["x0"], ping["value_bl"], M, 8),
                "LINE_GRAPH": line(*ping["spark"], max_value=200),
            },
            "DATE": date,
            "CUSTOM": {
                "INTERVAL": 1,
                "Bc250CpuTemp": heat_widget(cfg.cpu),
                "Bc250GpuLoad": {"TEXT": load(cfg.gpu), "GRAPH": bar(*cfg.gpu["bar"])},
                "Bc250GpuTemp": heat_widget(cfg.gpu),
                "Bc250GpuClock": {"TEXT": clock(cfg.gpu)},
                "Bc250GameDisk": {"TEXT": text(ssd["x0"], ssd["value_bl"], M, 4), "GRAPH": bar(*ssd["bar"])},
                "Bc250GameDiskFree": {"TEXT": text(ssd["xr"], ssd["value_bl"], S, 7, cfg.SKIN["mid"], right=True)},
                "Bc250ApuPower": dict(heat_colors(cfg.POWER_LOW, (cfg.POWER_LOW + cfg.POWER_HIGH) // 2, cfg.POWER_HIGH), **{
                    "HEAT_TEXT": text(pwr["x0"], pwr["value_bl"], M, 4),
                    "HEAT_BAR": {"X": pwr["bar"][0], "Y": pwr["bar"][1], "WIDTH": pwr["bar"][2],
                                 "HEIGHT": pwr["bar"][3], "MIN_VALUE": 0, "MAX_VALUE": cfg.POWER_BAR_MAX,
                                 "BACKGROUND_IMAGE": "background.png"},
                }),
                "Bc250GpuMem": {"TEXT": text(pwr["xr"], pwr["value_bl"], S, 6, cfg.SKIN["mid"], right=True)},
                # after the temperature widgets: it records their peaks during a game session
                "Bc250Prompt": prompt_spec,
                "Bc250Screen": {"SCREEN": {"DIM_AFTER": cfg.DIM_AFTER, "DIM_BRIGHTNESS": cfg.DIM_BRIGHTNESS,
                                           "NIGHT": cfg.NIGHT, "NIGHT_MODE": cfg.NIGHT_MODE}},
            },
        },
    }
    if cfg.SKIN["palette"]:
        # the sensors module snaps every colour it computes (heat fades, dimmed fills) to these shades
        theme["bc250_palette"] = {"COLORS": [rgb(c) for c in cfg.SKIN["palette"]], "BG": rgb(cfg.SKIN["bg"])}
    if uptime_chars and cfg.SKIN_NAME == "mission":  # mission elapsed time instead of the app's uptime
        theme["STATS"]["CUSTOM"]["Bc250Met"] = {"TEXT": text(uptime_x, HEADER_BL, S, 12, cfg.SKIN["accent"])}
    elif uptime_chars:
        theme["STATS"]["UPTIME"] = {"INTERVAL": 1,
                                    "FORMATTED": {"TEXT": text(uptime_x, HEADER_BL, S, uptime_chars, header_ink)}}
    # keep the original key order (STATS: CPU, MEMORY, NET, PING, DATE, UPTIME, CUSTOM)
    stats = theme["STATS"]
    theme["STATS"] = {k: stats[k] for k in ("CPU", "MEMORY", "NET", "PING", "DATE", "UPTIME", "CUSTOM") if k in stats}
    if "bc250_palette" in theme:
        theme = {k: theme[k] for k in ("author", "bc250_palette", "bc250_splash", "display", "static_images", "STATS")}
    if own.widgets:
        theme = own.widgets(theme, title, user)
    return theme
