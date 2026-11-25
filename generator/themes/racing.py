"""Racing theme: a single-seater's steering wheel display."""

from .. import cfg
from ..base import FONT
from ..draw import Canvas, rgb
from ..registry import Theme


# Racing status line wording ("ON TRACK Hades II"; idle: "PARC FERME" / "engine off")
RACING_WORDS = {"boot": "WARM-UP", "now-playing": "ON TRACK", "downloading": "PIT STOP", "installing": "IN THE GARAGE",
                "verifying": "SCRUTINEERING", "fossilize_replay": "TYRE WARMERS ON", "last-session": "CHEQUERED FLAG",
                "idle": "PARC FERME", "idle-text": "engine off"}


# ---------------------------------------------------------------------------------------------------------------------
# Racing artwork: a single-seater's steering wheel display on carbon (the sensors light it)
# ---------------------------------------------------------------------------------------------------------------------
RACING_LAYOUT = {  # landscape, portrait
    False: dict(leds=(30, 30, 22, 10), housing=(6, 8, 473, 36), title=(240, 49), gear=(190, 56, 290, 186), gear_size=96,
                left=(8, 56, 182, 186), right=(298, 56, 472, 186),
                labels=(("DELTA", 18, 72), ("FPS", 18, 140), ("LAP", 96, 140), ("THR", 12, 219), ("ERS", 12, 255)),
                texts={"DELTA": (18, 112, 36, "ls"), "FPS": (18, 168, 24, "ls"), "LAP": (96, 168, 24, "ls"),
                       "THR": (472, 222, 24, "rs"), "ERS": (472, 258, 24, "rs")},
                tyres=((318, 64, 44, 52), (408, 64, 44, 52), (318, 126, 44, 52), (408, 126, 44, 52)),
                bars={"THR": (48, 204, 400, 222, 28), "ERS": (48, 240, 400, 258, 28)},
                start=((40, 66, 440, 176), 26, tuple((80 + 80 * i, 121) for i in range(5)))),
    True: dict(leds=(20, 20, 20, 7), housing=(6, 8, 313, 32), title=(160, 49), gear=(116, 56, 204, 176), gear_size=96,
               left=(6, 56, 110, 176), right=(210, 56, 314, 176),
               labels=(("DELTA", 14, 72), ("FPS", 14, 140), ("LAP", 220, 72), ("THR", 8, 365), ("ERS", 8, 401)),
               texts={"DELTA": (14, 112, 36, "ls"), "FPS": (14, 166, 24, "ls"), "LAP": (220, 100, 24, "ls"),
                      "THR": (312, 368, 24, "rs"), "ERS": (312, 404, 24, "rs")},
               tyres=((40, 194, 60, 64), (220, 194, 60, 64), (40, 266, 60, 64), (220, 266, 60, 64)),
               bars={"THR": (44, 352, 250, 370, 20), "ERS": (44, 388, 250, 406, 20)},
               start=((10, 70, 310, 160), 22, tuple((40 + 60 * i, 115) for i in range(5)))),
}
RC = dict(GREEN=(40, 220, 90), RED=(240, 40, 40), BLUE=(60, 130, 255), YELLOW=(255, 210, 40), WHITE=(240, 240, 240),
          DIM=(110, 112, 118), LED_OFF=(30, 30, 34), LED_RIM=(62, 62, 68), TYRE=(24, 24, 28), TYRE_COLD=(60, 130, 255),
          TYRE_OK=(40, 210, 90), TYRE_HOT=(255, 170, 40), TYRE_ALERT=(240, 40, 40), PANEL=(9, 9, 11),
          SEG_OFF=(36, 36, 40))
RC_TYRES = (("cpu_t", "CPU°"), ("gpu_t", "GPU°"), ("pwr", "APU W"), ("ram", "RAM%"))


def racing_leds():
    x0, step, y, r = RACING_LAYOUT[cfg.PORTRAIT]["leds"]
    return [[x0 + step * i, y] for i in range(15)], r


def racing_segments(x1, x2, n, gap=2):
    """The cells of a segmented bar, [x1, x2] each."""
    return [[x1 + round(i * (x2 - x1 + gap) / n), x1 + round((i + 1) * (x2 - x1 + gap) / n) - gap - 1] for i in range(n)]


def render_background_racing(title):
    """Carbon, the shift lights' housing and its unlit LEDs, the gear window, the panels, the empty bars, the car's
    outline between its tyres."""
    rl = RACING_LAYOUT[cfg.PORTRAIT]
    c = Canvas()
    px = c.img.load()
    for y in range(cfg.H):  # a twill weave, faint
        for x in range(cfg.W):
            px[x, y] = (20, 20, 23) if ((x + y) // 3 + (x - y) // 3) % 2 else (14, 14, 16)
    panel = lambda box, outline=(52, 52, 58): c.d.rounded_rectangle(box, radius=6, fill=RC["PANEL"], outline=outline)
    panel(rl["housing"])
    leds, r = racing_leds()
    for x, y in leds:
        c.d.ellipse((x - r, y - r, x + r, y + r), fill=RC["LED_OFF"], outline=RC["LED_RIM"])
    c.label(*rl["title"], title, RC["DIM"], anchor="ms", glow=False)
    panel(rl["gear"], (76, 76, 84))
    panel(rl["left"])
    panel(rl["right"])
    for word, x, bl in rl["labels"]:
        c.label(x, bl, word, RC["DIM"], glow=False)
    for x1, y1, x2, y2, n in rl["bars"].values():
        for sx1, sx2 in racing_segments(x1, x2, n):
            c.d.rectangle((sx1, y1, sx2, y2), fill=RC["SEG_OFF"])
    (fx, fy, fw, fh), _, (rx, ry, _, rh) = rl["tyres"][0], rl["tyres"][1], rl["tyres"][2]
    body = ((fx + fw + rl["tyres"][1][0]) // 2, fy + 6, ry + rh - 6)  # the car seen from above, between its tyres
    c.d.rectangle((body[0] - 9, body[1], body[0] + 9, body[2]), outline=RC["LED_RIM"])
    for tx, ty, tw, th in rl["tyres"]:
        c.d.line((tx + tw if tx < body[0] else tx - 1, ty + th // 2, body[0] - 9 if tx < body[0] else body[0] + 9,
                  ty + th // 2), fill=RC["LED_RIM"])
        c.d.rectangle((tx, ty, tx + tw - 1, ty + th - 1), fill=RC["TYRE"], outline=RC["LED_RIM"])
    x, y, w, h = cfg.PROMPT_AREA
    c.d.rectangle((x, y, x + w - 1, y + h - 1), fill=RC["PANEL"])
    return c.finish()


def racing_spec():
    rl = RACING_LAYOUT[cfg.PORTRAIT]
    leds, r = racing_leds()
    gx1, gy1, gx2, gy2 = rl["gear"]
    scales = {"cpu_t": [cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT], "gpu_t": [cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT],
              "pwr": [cfg.POWER_LOW, (cfg.POWER_LOW + cfg.POWER_HIGH) // 2, cfg.POWER_HIGH], "ram": [40, 75, 90]}
    return {"DASH": [0, 0, cfg.W, cfg.PROMPT_Y], "LEDS": leds, "LED_R": r, "GEAR": [(gx1 + gx2) // 2, (gy1 + gy2) // 2],
            "GEAR_SIZE": rl["gear_size"], "TEXTS": {k: list(v) for k, v in rl["texts"].items()},
            "TYRES": [[*box, source, label] for box, (source, label) in zip(rl["tyres"], RC_TYRES)],
            "TYRE_SCALES": scales,
            "BARS": {k: [racing_segments(x1, x2, n), y1, y2] for k, (x1, y1, x2, y2, n) in rl["bars"].items()},
            "POWER_MAX": cfg.POWER_BAR_MAX, "FPS": 12, "TILE": 10, "FONT": FONT, "BACKGROUND_IMAGE": "background.png",
            "COLORS": {k: rgb(v) for k, v in RC.items()}}


def racing_theme(theme):
    """The wheel draws everything above the status line, from the readings the app samples; the app keeps the status
    line and the screen power."""
    rl, custom = RACING_LAYOUT[cfg.PORTRAIT], theme["STATS"]["CUSTOM"]
    spec = racing_spec()
    theme["STATS"] = {"CUSTOM": {
        "INTERVAL": 1,
        # sampled for the wheel (and the session peaks), drawn by nothing else
        "Bc250CpuTemp": {"ALERT": cfg.TEMP_ALERT}, "Bc250GpuTemp": {"ALERT": cfg.TEMP_ALERT},
        "Bc250GpuLoad": {"SAMPLE_ONLY": True}, "Bc250ApuPower": {"SAMPLE_ONLY": True},
        "Bc250Racing": spec,
        "Bc250Prompt": custom["Bc250Prompt"],
        "Bc250Screen": custom["Bc250Screen"],
    }}
    panel, radius, lights = rl["start"]
    theme["bc250_splash"].update({k: v for k, v in spec.items() if k != "BACKGROUND_IMAGE"})
    theme["bc250_splash"].update({"STYLE": "racing", "IMAGE": "background.png", "BAND": list(cfg.PROMPT_AREA),
                                  "BAND_LABEL_BL": cfg.PROMPT_LABEL_BL, "BAND_VALUE_BL": cfg.PROMPT_VALUE_BL,
                                  "START": [list(p) for p in lights], "START_R": radius, "START_PANEL": list(panel)})
    return theme


def render(out, title, prompt, user):
    """Its artwork, into the theme's folder out."""
    render_background_racing(title).save(out / "background.png")


def status_line(user):
    """Its words and colours on the status line (Bc250Prompt)."""
    return {"CMD_WORDS": RACING_WORDS, "LABEL_COLOR": rgb(RC["YELLOW"]),
            "COL_WORDS": {"SESSION": "RACE", "TIME": "RACE"}}


THEME = Theme(
    name="racing",
    description="a single-seater's steering wheel display, shift lights and start lights",
    render=render,
    title="{LOGO} RACING",
    status_line=status_line,
    widgets=lambda theme, title, user: racing_theme(theme),
    portrait_app=True,  # a layout and threads of its own
)
