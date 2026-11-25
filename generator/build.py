"""theme.yaml, shared by all themes (widget positions come from the layout)."""

from . import cfg
from .base import CH, CLOCK_CHARS, DMG, FONT, HEADER_BL, M, RETRO_LOGO_FONT, S, VT
from .draw import bar, header_layout, heat_colors, heat_widget, line, logo_baseline, logo_size, prompt_prefix, rgb, text
from .themes.christmas import CHRISTMAS_WORDS, CM_HOLLY, CM_SNOW, sleigh_shapes, tree_lights
from .themes.departures import departures_theme, DEPARTURES_WORDS, DP
from .themes.gameboy import GAMEBOY_WORDS
from .themes.halloween import BAT_SHAPE, HALLOWEEN_WORDS, HW_CANDLE, HW_GROUND, pumpkin_face
from .themes.horror import horror_theme, HORROR_WORDS
from .themes.minecraft import MINECRAFT_SPLASHES, MINECRAFT_WORDS
from .themes.mission import MISSION_WORDS
from .themes.nixie import NIXIE_FONT, nixie_theme, NIXIE_WORDS, NX_BRASS, NX_LAMP_LABELS
from .themes.orbit import orbit_theme, ORBIT_WORDS
from .themes.racing import racing_theme, RACING_WORDS, RC
from .themes.radar import nice_step, radar_theme, RADAR_WORDS
from .themes.retrowave import retro_logo, RETRO_WORDS
from .themes.seismograph import seismo_theme, SEISMO_WORDS
from .themes.videotex import videotex_code, VIDEOTEX_WORDS


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
    if cfg.SKIN_NAME == "gameboy":
        prompt_spec.update({"CMD_WORDS": GAMEBOY_WORDS, "CURSOR": "▼", "LABEL_COLOR": rgb(cfg.SKIN["mid"])})
    if cfg.SKIN_NAME == "retrowave":
        prompt_spec.update({"CMD_WORDS": RETRO_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["accent"])})
    if cfg.SKIN_NAME == "nixie":
        prompt_spec.update({"CMD_WORDS": NIXIE_WORDS, "LABEL_COLOR": rgb(NX_BRASS)})
    if cfg.SKIN_NAME == "radar":
        prompt_spec.update({"CMD_WORDS": RADAR_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["mid"]), "SMALL_FALLBACK": True,
                            "COL_WORDS": {"SESSION": "TIME", "PEAK C/G": "PEAK", "SHADERS": "DONE"}})
    if cfg.SKIN_NAME == "minecraft":  # white and yellow on the dark chat box
        prompt_spec.update({"CMD_WORDS": dict(MINECRAFT_WORDS, **{"idle-text": f"{user} is AFK"}),
                            "BRIGHT": rgb((255, 255, 255)), "LABEL_COLOR": rgb((255, 255, 85)),
                            "COL_WORDS": {"SESSION": "PLAYTIME", "TIME": "PLAYTIME"}})
    if cfg.SKIN_NAME == "halloween":  # a seance is a session too
        prompt_spec.update({"CMD_WORDS": HALLOWEEN_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["mid"]),
                            "COL_WORDS": {"SESSION": "SEANCE", "TIME": "SEANCE"}})
    if cfg.SKIN_NAME == "christmas":
        prompt_spec.update({"CMD_WORDS": CHRISTMAS_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["mid"])})
    if cfg.SKIN_NAME == "seismograph":
        prompt_spec.update({"CMD_WORDS": SEISMO_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["mid"]),
                            "COL_WORDS": {"SESSION": "DURATION", "TIME": "DURATION"}})
    if cfg.SKIN_NAME == "orbit":  # mission elapsed time
        prompt_spec.update({"CMD_WORDS": ORBIT_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["mid"]),
                            "COL_WORDS": {"SESSION": "MET", "TIME": "MET"}})
    if cfg.SKIN_NAME == "racing":
        prompt_spec.update({"CMD_WORDS": RACING_WORDS, "LABEL_COLOR": rgb(RC["YELLOW"]),
                            "COL_WORDS": {"SESSION": "RACE", "TIME": "RACE"}})
    if cfg.SKIN_NAME == "departures":  # amber LEDs, in French like the board
        prompt_spec.update({"CMD_WORDS": DEPARTURES_WORDS, "BRIGHT": rgb(DP["LED"]), "MID": rgb((230, 150, 40)),
                            "DIM": rgb(DP["LED_DIM"]), "AMBER": rgb((255, 120, 40)), "LABEL_COLOR": rgb(DP["LED_DIM"]),
                            "COL_WORDS": {"DONE": "FAIT", "ETA": "RESTE", "RATE": "DÉBIT", "SESSION": "TRAJET",
                                          "TIME": "TRAJET", "PEAK C/G": "PIC C/G"}})
    if cfg.SKIN_NAME == "horror":
        prompt_spec.update({"CMD_WORDS": HORROR_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["mid"]),
                            "COL_WORDS": {"SESSION": "YOU STAYED", "TIME": "YOU STAYED"}})
    if cfg.SKIN_NAME == "mission":
        prompt_spec.update({"CMD_WORDS": MISSION_WORDS, "LABEL_COLOR": rgb(cfg.SKIN["accent"]),
                            "COL_WORDS": {"SESSION": "FLT TIME", "TIME": "FLT TIME", "PEAK C/G": "PEAK THRM"}})
    if cfg.SKIN_NAME == "videotex":
        prompt_spec.update({"CMD_WORDS": dict(VIDEOTEX_WORDS, **{"idle-text": videotex_code(cfg.LOGO)}),
                            "LABEL_COLOR": rgb(cfg.SKIN["accent"]), "PROGRESS_STYLE": "mosaic",
                            "COL_WORDS": {"DONE": "FAIT", "ETA": "RESTE", "RATE": "DÉBIT", "SESSION": "DURÉE",
                                          "TIME": "DURÉE", "PEAK C/G": "PIC C/G"}})
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
    if cfg.SKIN_NAME not in ("retrowave", "videotex", "mission", "minecraft", "nixie", "radar", "halloween",
                         "christmas", "horror", "seismograph", "orbit", "departures", "racing"):  # pixel-font logo
        splash.update({"LOGO_SIZE": logo_size(cfg.LOGO), "LOGO_BL": logo_baseline(logo_size(cfg.LOGO)),
                       "LOGO_BOX": list(sl["logo_box"])})
    if cfg.SKIN_NAME == "phosphor":  # the dark tube the warm-up starts from: only the text has to be sent after it
        splash["IMAGE_BLANK"] = "splash_blank.png"
    if cfg.SKIN_NAME == "gameboy":
        splash.update({"STYLE": "gameboy", "IMAGE_BLANK": "splash_blank.png", "LIGHT": rgb(DMG[1])})
    if cfg.SKIN_NAME == "retrowave":
        logo = retro_logo(cfg.LOGO)
        splash.update({"STYLE": "retrowave", "IMAGE_BLANK": "splash_blank.png", "LOGO_FONT": RETRO_LOGO_FONT,
                       "LOGO_SIZE": logo["size"], "LOGO_CENTER": list(sl["logo_center"]),
                       "LOGO_BOX": list(logo["face_box"]), "REVEAL_BOX": list(cfg.RETRO_REVEAL_BOX),
                       "HORIZON": sl["horizon"], "PANEL": list(sl["panel"]), "GRID_COLOR": rgb(cfg.SKIN["mid"]),
                       "GRID_SPACING": cfg.W // 8, "FOOTER_BL": sl.get("footer_bl", 0)})
    if cfg.SKIN_NAME == "radar":
        cx, cy, r = cfg.RADAR["scope"]
        step = nice_step(cfg.RADAR["km"])
        rings = [round(ring * r / cfg.RADAR["km"]) for ring in range(step, int(cfg.RADAR["km"]) + 1, step)]
        splash.update({"STYLE": "radar", "IMAGE": "background.png", "LOG": list(sl["log"]),
                       "RINGS": [v for v in rings if v < r - 3] + [r - 1],
                       "MAP_COUNT": sum(1 for a in cfg.RADAR["map"][0] if a[3] != "small_airport")})
    if cfg.SKIN_NAME == "nixie":
        splash.update({"STYLE": "nixie", "NIXIE_FONT": NIXIE_FONT, "TUBE_XS": sl["tube_xs"], "TUBE_Y": sl["tube_y"],
                       "TUBE_W": sl["tube"][0], "TUBE_H": sl["tube"][1], "COLONS": sl["colons"], "LAMPS": sl["lamps"],
                       "LAMP_NAMES": list(NX_LAMP_LABELS), "TEXT_BL": sl["text_bl"], "GLOW": rgb((255, 90, 18)),
                       "CORE": rgb((255, 196, 120)), "LAMP_ON": rgb((255, 60, 30))})
    if cfg.SKIN_NAME == "minecraft":
        splash.update({"STYLE": "minecraft", "SPLASH_TEXTS": MINECRAFT_SPLASHES, "SPLASH_AT": list(sl["splash_at"]),
                       "GREEN": rgb((0, 150, 0)), "TEXT": rgb(cfg.SKIN["value"]), "WHITE": rgb((255, 255, 255)),
                       "TITLE_BL": sl["title_bl"]})
    if cfg.SKIN_NAME == "halloween":
        splash.update({"STYLE": "halloween", "LOGO_BOX": list(cfg.HW_REVEAL_BOX), "SKY": [0, 0, cfg.W, sl["horizon"]],
                       "MOON": list(sl["moon"]), "PUMPKINS": [pumpkin_face(*p) for p in sl["pumpkins"]],
                       "BAT": [list(p) for p in BAT_SHAPE], "TEXT": rgb(cfg.SKIN["value"]), "GREEN": rgb(cfg.SKIN["accent"]),
                       "CANDLE": rgb(HW_CANDLE), "SILHOUETTE": rgb(HW_GROUND), "CAPTION": list(sl["caption"])})
    if cfg.SKIN_NAME == "christmas":
        splash.update({"STYLE": "christmas", "LOGO_BOX": list(cfg.CM_REVEAL_BOX), "SKY": [0, 0, cfg.W, sl["horizon"]],
                       "LIGHTS": tree_lights(*sl["tree"]), "SLEIGH": sleigh_shapes(), "TEXT": rgb(cfg.SKIN["value"]),
                       "GREEN": rgb(cfg.SKIN["green"]), "SNOW": rgb(CM_SNOW), "HOLLY": rgb(CM_HOLLY),
                       "CAPTION": list(sl["caption"])})
    if cfg.SKIN_NAME == "mission":
        splash.update({"STYLE": "mission", "IMAGE_BLANK": "splash.png", "GREEN": rgb(cfg.SKIN["green"]),
                       "COUNT_BOX": list(sl["count_box"]), "COUNT_BL": sl["count_bl"], "HEAD_BL": sl["head_bl"],
                       "LIFTOFF_BL": sl["liftoff_bl"]})
    if cfg.SKIN_NAME == "videotex":
        splash.update({"STYLE": "videotex", "IMAGE_BLANK": "splash_blank.png", "CODE": videotex_code(cfg.LOGO),
                       "GREEN": rgb(VT["g"]), "BLUE": rgb(VT["b"]), "STATUS_CELL": [cfg.W - 18, 2, 12, 13],
                       "DIAL_X": sl["dial_x"], "DIAL_BL": list(sl["dial_bl"]), "FOOTER": list(sl["footer"])})
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
    if cfg.SKIN_NAME == "nixie":
        theme = nixie_theme(theme, title)
    if cfg.SKIN_NAME == "radar":
        theme = radar_theme(theme)
    if cfg.SKIN_NAME == "horror":
        theme = horror_theme(theme, user)
    if cfg.SKIN_NAME == "seismograph":
        theme = seismo_theme(theme, title)
    if cfg.SKIN_NAME == "orbit":
        theme = orbit_theme(theme, title)
    if cfg.SKIN_NAME == "departures":
        theme = departures_theme(theme)
    if cfg.SKIN_NAME == "racing":
        theme = racing_theme(theme)
    return theme
