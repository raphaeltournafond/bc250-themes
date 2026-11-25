"""Horror theme: a security camera, a corridor, and what moves when the lights go out."""

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .. import cfg
from ..base import CLOCK_CHARS, FONT, HEADER_BL, HEADER_H, M, S
from ..draw import Canvas, heat_colors, rgb, text


# Horror status line wording ("YOU ARE STILL PLAYING Hades II"; idle: "NOBODY IS PLAYING" / "so who is breathing")
HORROR_WORDS = {"boot": "IT WOKE UP", "now-playing": "YOU ARE STILL PLAYING", "downloading": "SOMETHING IS COMING",
                "installing": "IT IS MOVING IN", "verifying": "CHECKING THE LOCKS", "fossilize_replay": "FEEDING IT",
                "last-session": "THE LAST TIME YOU PLAYED", "idle": "NOBODY IS PLAYING", "idle-text": "so who is breathing"}


# ---------------------------------------------------------------------------------------------------------------------
# Horror artwork: a security camera's view of a basement corridor, what stands in it, and its face
# ---------------------------------------------------------------------------------------------------------------------
HORROR_LAYOUT = {  # landscape, portrait: the feed, the console's values and labels, its separators
    False: dict(feed=(4, 18), motion=(322, 188, 156, 88), motion_rows=(200, 240, 256, 270),
                cpu=dict(load=(324, 54), temp=(474, 54), clk=(474, 70)), gpu=dict(load=(324, 116), temp=(474, 116), clk=(474, 132)),
                ram=(324, 178), pwr=(474, 178),
                labels=(("CPU", 324, 30, "ls", "RUN"), ("GHZ", 324, 70, "ls", "EYE"), ("GPU", 324, 92, "ls", "HIDE"),
                        ("MHZ", 324, 132, "ls", "NOW"), ("RAM", 324, 154, "ls", "HELP"), ("APU W", 474, 154, "rs", "BEHIND")),
                lines=((322, 78, 476, 78), (322, 140, 476, 140), (322, 186, 476, 186))),
    True: dict(feed=(4, 18), motion=(164, 336, 148, 84), motion_rows=(348, 388, 402, 416),
               cpu=dict(load=(10, 312), temp=(154, 312), clk=(154, 328)), gpu=dict(load=(166, 312), temp=(310, 312), clk=(310, 328)),
               ram=(10, 372), pwr=(154, 372),
               labels=(("CPU", 10, 288, "ls", "RUN"), ("GHZ", 10, 328, "ls", "EYE"), ("GPU", 166, 288, "ls", "HIDE"),
                       ("MHZ", 166, 328, "ls", "NOW"), ("RAM", 10, 348, "ls", "HELP"), ("APU W", 154, 348, "rs", "BEHIND")),
               lines=((4, 334, 316, 334), (160, 278, 160, 418))),
}
HR_FEED_SIZE = (312, 256)  # the same in both orientations: one corridor, one face
HR_VANISH = (156, 112)  # where the corridor's lines meet, in the feed
HR_FOCAL = 300  # pixels per metre at 1 m
HR_EYE, HR_CEILING, HR_HALF_WIDTH, HR_END = 1.45, 2.6, 1.25, 44.0  # metres: the camera's height, the corridor's size
HR_LAMPS = ((2.5, 0.85), (8.0, 1.0), (14.0, 0.0), (20.0, 0.75), (26.0, 0.0), (32.0, 0.8), (38.0, 0.25))  # (z, power)
HR_DISTANCES = (40, 32, 23, 17, 11, 7, 4.4, 2.7)  # metres from the camera, one for each time the lights go out
HR_FIGURE_SIZE, HR_FIGURE_HEIGHT = (200, 600), 2.25  # the sprite in pixels, and how tall it is in metres
HR_TINT = (0.84, 0.97, 0.86)  # old CCTV: everything a washed-out grey-green


def hr_light(x, y, z):
    """How much light reaches a point of the corridor from its working lamps."""
    total = 0.012
    for lamp_z, power in HR_LAMPS:
        if power:
            total += power / (1 + 0.42 * ((x * x) + (y - HR_CEILING) ** 2 + (z - lamp_z) ** 2))
    return total


def hr_corridor():
    """The corridor, ray by ray: tiled floor, panelled walls, doors (one of them open on the dark), lamps in pools of
    light with dead ones between them, something dragged along the floor. The grain never changes: the screen only
    receives what moves."""
    w, h = HR_FEED_SIZE
    vx, vy = HR_VANISH
    rnd = random.Random(666)
    image = Image.new("RGB", (w, h))
    px = image.load()
    blotch = [(rnd.uniform(0, 44), rnd.uniform(-1.2, 1.2), rnd.uniform(0.2, 1.1)) for _ in range(40)]
    for j in range(h):
        dy = (j - vy + 0.5) / HR_FOCAL
        for i in range(w):
            dx = (i - vx + 0.5) / HR_FOCAL
            t = HR_END
            surface = "end"
            if dy > 0 and HR_EYE / dy < t:
                t, surface = HR_EYE / dy, "floor"
            if dy < 0 and (HR_CEILING - HR_EYE) / -dy < t:
                t, surface = (HR_CEILING - HR_EYE) / -dy, "ceiling"
            if dx and HR_HALF_WIDTH / abs(dx) < t:
                t, surface = HR_HALF_WIDTH / abs(dx), "wall"
            x, y, z = dx * t, HR_EYE - dy * t, t
            albedo = 0.5
            if surface == "floor":
                tile = (int(x / 0.5 + 100) + int(z / 0.5)) % 2
                albedo = 0.42 if tile else 0.3
                if abs(abs(x + 0.1 * math.sin(z * 0.6)) - 0.15) < 0.022 and 3 < z < 30 and math.sin(z * 1.7) > -0.8:
                    albedo *= 0.35  # two thin tracks: something's heels, dragged
            elif surface == "ceiling":
                albedo = 0.3
                if abs(x) < 0.16 and any(power and abs(z - lamp) < 0.5 for lamp, power in HR_LAMPS):
                    albedo = 3.2  # a lamp that works
                elif abs(x) < 0.16 and any(not power and abs(z - lamp) < 0.5 for lamp, power in HR_LAMPS):
                    albedo = 0.08  # one that doesn't
            elif surface == "wall":
                albedo = 0.44 if y > 1.15 else 0.28  # paint above, grime below
                if abs(y - 1.15) < 0.035:
                    albedo = 0.14
                if int(z / 1.6) % 2 and abs(z % 1.6) < 0.03:
                    albedo = 0.16  # panel joints
                side = 1 if x > 0 else -1
                for door_side, door_z, door_open in ((-1, 5.2, False), (1, 10.8, True), (-1, 17.0, False), (1, 23.5, False)):
                    if side == door_side and door_z < z < door_z + 1.25 and y < 2.05:
                        albedo = 0.012 if door_open else 0.2  # the open one: nothing in there, nothing lit
                    elif side == door_side and (abs(z - door_z) < 0.05 or abs(z - door_z - 1.25) < 0.05) and y < 2.1:
                        albedo = 0.08
                for bz, by, size in blotch:
                    if abs(z - bz) < size * 0.3 and y < 2.4 - by * 0.5 + 0.5 * math.sin(z * 5 + bz):
                        albedo *= 0.86  # damp, running down from above
            else:
                albedo = 0.05
            v = albedo * hr_light(x, y, z) * math.exp(-z / 42)
            v = 255 * min(1.0, v ** 0.8 * 1.15)
            v += rnd.uniform(-5, 5)  # the camera's grain
            r = math.hypot((i - w / 2) / (w / 2), (j - h / 2) / (h / 2))
            v *= (1 - 0.32 * r ** 2.2) * (0.86 if j % 2 else 1.0)  # dark corners, scanlines
            v = max(0, min(255, v))
            px[i, j] = tuple(round(v * k) for k in HR_TINT)
    return image


def hr_stage(distance):
    """Where the figure stands at a distance: [x, top, height, how much light it gets]."""
    per_metre = HR_FOCAL / distance
    foot = HR_VANISH[1] + HR_EYE * per_metre
    height = HR_FIGURE_HEIGHT * per_metre
    light = min(1.0, hr_light(0, 1.2, distance) ** 0.8 * 1.6)
    return [HR_VANISH[0] + round(0.1 * per_metre), round(foot - height), round(height), round(max(0.1, light), 3)]


HR_FACE_POS = (0.56, 0.05)  # the head in the sprite
HR_FACE_TILT = 26  # degrees, its head tipped over to one side
HR_EYE_OFFSETS = ((-0.044, -0.01), (0.044, -0.01))  # the eyes from the head's centre, in 0-1 of the sprite


def hr_figure_eyes():
    """Where its eyes catch the light, in 0-1 of the sprite (they show even where the rest is lost in the dark)."""
    w, h = HR_FIGURE_SIZE
    angle = math.radians(HR_FACE_TILT)
    eyes = []
    for ex, ey in HR_EYE_OFFSETS:
        dx, dy = ex * w, ey * h
        eyes.append([round(HR_FACE_POS[0] + (dx * math.cos(angle) - dy * math.sin(angle)) / w, 4),
                     round(HR_FACE_POS[1] + (dx * math.sin(angle) + dy * math.cos(angle)) / h, 4)])
    return eyes


def hr_figure():
    """What stands in the corridor: too tall, too thin, arms past its knees. A shape nearly as dark as the dark behind
    it, except for pale fingers and a small pale face tipped over to one side. Drawn large (the last steps show it
    close) from x, y in 0-1 of the sprite."""
    w, h = HR_FIGURE_SIZE
    k = 3  # supersampled
    W_, H_ = w * k, h * k
    body, pale, hollow = (30, 33, 30, 255), (178, 186, 170, 255), (2, 2, 2, 255)
    art = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)

    def limb(points, widths, fill=body):
        for (x1, y1), (x2, y2), a, b in zip(points, points[1:], widths, widths[1:]):
            ax, ay, bx, by = x1 * W_, y1 * H_, x2 * W_, y2 * H_
            nx, ny = ay - by, bx - ax
            length = math.hypot(nx, ny) or 1
            nx, ny = nx / length, ny / length
            d.polygon([(ax + nx * a * W_, ay + ny * a * W_), (bx + nx * b * W_, by + ny * b * W_),
                       (bx - nx * b * W_, by - ny * b * W_), (ax - nx * a * W_, ay - ny * a * W_)], fill=fill)
            d.ellipse((bx - b * W_, by - b * W_, bx + b * W_, by + b * W_), fill=fill)

    limb([(0.43, 0.5), (0.4, 0.74), (0.37, 0.985)], [0.06, 0.034, 0.02])  # legs
    limb([(0.6, 0.5), (0.63, 0.74), (0.67, 0.985)], [0.06, 0.034, 0.02])
    d.polygon([(0.27 * W_, 0.17 * H_), (0.76 * W_, 0.15 * H_), (0.68 * W_, 0.36 * H_), (0.65 * W_, 0.52 * H_),
               (0.37 * W_, 0.52 * H_), (0.35 * W_, 0.36 * H_)], fill=body)  # the chest, sunken at the belly
    limb([(0.29, 0.18), (0.12, 0.4), (0.09, 0.69)], [0.05, 0.03, 0.02])  # arms, too long
    limb([(0.74, 0.16), (0.92, 0.38), (0.88, 0.68)], [0.05, 0.03, 0.02])
    for hand_x, hand_y in ((0.09, 0.69), (0.88, 0.68)):  # the fingers, longer still, and pale
        for n, spread in enumerate((-0.055, -0.022, 0.012, 0.045)):
            limb([(hand_x, hand_y), (hand_x + spread * 0.8, hand_y + 0.045), (hand_x + spread, hand_y + 0.1 + n * 0.008)],
                 [0.013, 0.008, 0.003], pale)
    limb([(0.53, 0.165), (0.56, 0.08)], [0.042, 0.03])  # the neck, leaning
    head = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    hd = ImageDraw.Draw(head)
    hx, hy = HR_FACE_POS[0] * W_, HR_FACE_POS[1] * H_
    hw, hh = 0.1 * W_, 0.056 * H_
    hd.ellipse((hx - hw, hy - hh, hx + hw, hy + hh), fill=pale)
    for ex, ey in HR_EYE_OFFSETS:  # hollow eyes, the mouth a long slack hole
        x, y = hx + ex * W_, hy + ey * H_
        hd.ellipse((x - 0.026 * W_, y - 0.01 * H_, x + 0.026 * W_, y + 0.01 * H_), fill=hollow)
    hd.ellipse((hx - 0.018 * W_, hy + 0.012 * H_, hx + 0.018 * W_, hy + 0.05 * H_), fill=hollow)
    head = head.rotate(-HR_FACE_TILT, center=(hx, hy), resample=Image.BICUBIC)
    art.alpha_composite(head)
    art = art.convert("RGBa").resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.1)).convert("RGBA")
    rnd = random.Random(13)  # the camera's grain on it too
    out = art.load()
    for j in range(h):
        for i in range(w):
            r, g, b, a = out[i, j]
            n = rnd.uniform(0.82, 1.1)  # drawn for every pixel: one edge pixel more or less (Pillow 12 and 13 resize
            if a:                       # edges a little differently) must not shift the grain of all the ones after
                out[i, j] = (min(255, int(r * n)), min(255, int(g * n)), min(255, int(b * n)), a)
    return art


def hr_face():
    """What is on the camera when it gets there. Fills the feed: sunken black eyes with a point of light far inside
    them, a jaw hanging open far too wide, grain, and a picture that can barely hold together."""
    w, h = HR_FEED_SIZE
    k = 2
    W_, H_ = w * k, h * k
    rnd = random.Random(1408)
    base = Image.new("L", (W_, H_), 0)
    d = ImageDraw.Draw(base)
    cx = W_ // 2 + 6 * k
    d.ellipse((cx - 0.46 * W_, -0.38 * H_, cx + 0.46 * W_, 1.18 * H_), fill=214)
    base = base.filter(ImageFilter.GaussianBlur(14 * k))  # a head too close, its edges lost in the dark
    d = ImageDraw.Draw(base)
    for _ in range(26):  # veins and cracks
        x, y = rnd.uniform(0.12, 0.88) * W_, rnd.uniform(0.02, 0.62) * H_
        points = [(x, y)]
        for _ in range(rnd.randrange(4, 9)):
            x += rnd.uniform(-22, 22) * k
            y += rnd.uniform(-14, 18) * k
            points.append((x, y))
        d.line(points, fill=rnd.randrange(84, 150), width=k)
    shadow = Image.new("L", (W_, H_), 0)
    sd = ImageDraw.Draw(shadow)
    for ex, tilt in ((-0.2, 0.012), (0.2, -0.016)):  # the sockets, a shadow around them
        sd.ellipse((cx + (ex - 0.15) * W_, (0.2 + tilt) * H_, cx + (ex + 0.15) * W_, (0.52 + tilt) * H_), fill=255)
    sd.polygon([(cx - 0.05 * W_, 0.46 * H_), (cx + 0.05 * W_, 0.46 * H_), (cx + 0.02 * W_, 0.3 * H_), (cx - 0.02 * W_, 0.3 * H_)], fill=170)
    sd.ellipse((cx - 0.3 * W_, 0.5 * H_, cx + 0.3 * W_, 1.3 * H_), fill=255)  # around the mouth
    shadow = shadow.filter(ImageFilter.GaussianBlur(11 * k))
    base = Image.composite(Image.new("L", (W_, H_), 6), base, shadow)
    d = ImageDraw.Draw(base)
    holes = Image.new("L", (W_, H_), 0)
    hd = ImageDraw.Draw(holes)
    for ex, tilt in ((-0.2, 0.012), (0.2, -0.016)):
        hd.ellipse((cx + (ex - 0.105) * W_, (0.25 + tilt) * H_, cx + (ex + 0.105) * W_, (0.47 + tilt) * H_), fill=255)
    hd.polygon([(cx - 0.035 * W_, 0.5 * H_), (cx - 0.008 * W_, 0.5 * H_), (cx - 0.012 * W_, 0.43 * H_)], fill=255)  # nostrils
    hd.polygon([(cx + 0.035 * W_, 0.5 * H_), (cx + 0.008 * W_, 0.5 * H_), (cx + 0.012 * W_, 0.43 * H_)], fill=255)
    mouth = [(cx - 0.2 * W_, 0.6 * H_), (cx - 0.09 * W_, 0.57 * H_), (cx + 0.09 * W_, 0.57 * H_), (cx + 0.2 * W_, 0.6 * H_),
             (cx + 0.24 * W_, 0.82 * H_), (cx + 0.16 * W_, 1.08 * H_), (cx - 0.16 * W_, 1.08 * H_), (cx - 0.24 * W_, 0.82 * H_)]
    hd.polygon(mouth, fill=255)
    holes = holes.filter(ImageFilter.GaussianBlur(2 * k))
    base = Image.composite(Image.new("L", (W_, H_), 0), base, holes)
    d = ImageDraw.Draw(base)
    for n in range(11):  # teeth: long, uneven, too many
        x = cx + (-0.2 + 0.4 * n / 10) * W_
        top = (0.585 - 0.02 * math.cos((n - 5) / 5 * 1.5)) * H_
        d.polygon([(x - 0.019 * W_, top), (x + 0.019 * W_, top), (x + rnd.uniform(-0.006, 0.006) * W_, top + rnd.uniform(0.06, 0.13) * H_)],
                  fill=rnd.randrange(170, 226))
    for n in range(9):
        x = cx + (-0.17 + 0.34 * n / 8) * W_
        d.polygon([(x - 0.019 * W_, 1.0 * H_), (x + 0.019 * W_, 1.0 * H_), (x + rnd.uniform(-0.006, 0.006) * W_, (1.0 - rnd.uniform(0.08, 0.14)) * H_)],
                  fill=rnd.randrange(150, 206))
    for ex, tilt in ((-0.2, 0.012), (0.2, -0.016)):  # a point of light, far inside each eye
        x, y = cx + ex * W_, (0.36 + tilt) * H_
        d.ellipse((x - 2 * k, y - 2 * k, x + 2 * k, y + 2 * k), fill=255)
    face = base.resize((w, h), Image.LANCZOS).convert("RGB")
    px = face.load()
    # the feed struggling to hold it: grain, scanlines, rows torn sideways, a red cast
    tears = {}
    y = 0
    while y < h:
        band = rnd.randrange(2, 22)
        shift = rnd.choice((0, 0, 0, 0, 3, -3, 7, -9, 16, -24))
        for row in range(y, min(h, y + band)):
            tears[row] = shift
        y += band
    source = face.copy().load()
    for j in range(h):
        for i in range(w):
            v = source[(i - tears[j]) % w, j][0]
            v = v + rnd.uniform(-20, 20)
            v *= 0.82 if j % 2 else 1.0
            v = max(0, min(255, v))
            px[i, j] = (round(v), round(v * 0.84), round(v * 0.8))
    return face


def render_background_horror(title):
    """The console: the corridor in the feed, the readings' labels beside it, thin lines between them."""
    hl = HORROR_LAYOUT[cfg.PORTRAIT]
    c = Canvas()
    c.label(6, HEADER_BL, title, cfg.SKIN["mid"], glow=False)
    c.d.line((0, HEADER_H + 1, cfg.W, HEADER_H + 1), fill=cfg.SKIN["grid_dot"])
    c.img.paste(hr_corridor(), hl["feed"])
    x, y = hl["feed"]
    c.d.rectangle((x - 1, y - 1, x + HR_FEED_SIZE[0], y + HR_FEED_SIZE[1]), outline=cfg.SKIN["grid_dot"])
    for word, lx, bl, anchor, _ in hl["labels"]:
        c.label(lx, bl, word, cfg.SKIN["dim"], anchor=anchor, glow=False)
    for line in hl["lines"]:
        c.d.line(line, fill=cfg.SKIN["grid_dot"])
    mx, _, _, _ = hl["motion"]
    c.label(mx + 2, hl["motion_rows"][0], "MOTION", cfg.SKIN["accent"], glow=False)
    c.dotted_hline(4, cfg.W - 4, cfg.PROMPT_Y)
    return c.finish()


def render_splash_horror():
    """Nothing: the boot starts as an ordinary self-test on a black screen."""
    return Canvas().finish()


def horror_spec(user):
    hl = HORROR_LAYOUT[cfg.PORTRAIT]
    stages = [[d] + hr_stage(d) for d in HR_DISTANCES]
    return {"FEED": list(hl["feed"]) + list(HR_FEED_SIZE), "STAGES": stages, "EYES": hr_figure_eyes(),
            "FIGURE": "figure.png", "FACE": "face.png", "USER": user.upper(), "FONT": FONT, "JUMPSCARE": cfg.HR_JUMPSCARE,
            "MOTION": list(hl["motion"]), "MOTION_ROWS": list(hl["motion_rows"]), "FPS": 8, "TILE": 10,
            "LABELS": [list(label) for label in hl["labels"]], "TITLE": [6, HEADER_BL, cfg.HR_TITLE, "CAM 04  BEHIND YOU"],
            "BACKGROUND_IMAGE": "background.png",
            "COLORS": {"BRIGHT": rgb(cfg.SKIN["value"]), "MID": rgb(cfg.SKIN["mid"]), "DIM": rgb(cfg.SKIN["dim"]),
                       "RED": rgb(cfg.SKIN["alert"])}}


def horror_theme(theme, user):
    """The horror widget draws the feed and the motion readout; the app keeps the clock, the readings, the status line
    and the screen power."""
    hl, custom = HORROR_LAYOUT[cfg.PORTRAIT], theme["STATS"]["CUSTOM"]
    heat = lambda xr, bl: dict(heat_colors(cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT), INK=rgb(cfg.SKIN["ink"]),
                               HEAT_TEXT=text(xr, bl, M, 5, right=True))
    load = lambda at: text(at[0], at[1], M, 4)
    clock = lambda at, **kw: text(at[0], at[1], S, 6, cfg.SKIN["mid"], right=True, **kw)
    power = dict(heat_colors(cfg.POWER_LOW, (cfg.POWER_LOW + cfg.POWER_HIGH) // 2, cfg.POWER_HIGH),
                 HEAT_TEXT=text(hl["pwr"][0], hl["pwr"][1], M, 5, right=True))
    theme["STATS"] = {
        "CPU": {"PERCENTAGE": {"INTERVAL": 1, "TEXT": load(hl["cpu"]["load"])},
                "FREQUENCY": {"INTERVAL": 2, "TEXT": clock(hl["cpu"]["clk"], unit=False)}},
        "MEMORY": {"INTERVAL": 2, "VIRTUAL": {"PERCENT_TEXT": load(hl["ram"])}},
        "DATE": {"INTERVAL": 1, "HOUR": {"TEXT": text(cfg.CLOCK_XR, HEADER_BL, S, CLOCK_CHARS, cfg.SKIN["value"], right=True,
                                                      FORMAT="HH:mm:ss")}},
        "CUSTOM": {
            "INTERVAL": 1,
            "Bc250CpuTemp": heat(*hl["cpu"]["temp"]),
            "Bc250GpuTemp": heat(*hl["gpu"]["temp"]),
            "Bc250GpuLoad": {"TEXT": load(hl["gpu"]["load"])},
            "Bc250GpuClock": {"TEXT": clock(hl["gpu"]["clk"])},
            "Bc250ApuPower": power,
            "Bc250Horror": horror_spec(user),
            "Bc250Prompt": custom["Bc250Prompt"],
            "Bc250Screen": custom["Bc250Screen"],
        },
    }
    theme["bc250_splash"].update({"STYLE": "horror", "TEXT": rgb(cfg.SKIN["value"]), "RED": rgb(cfg.SKIN["alert"])})
    theme["bc250_splash"].update({k: v for k, v in horror_spec(user).items() if k in ("FEED", "STAGES", "EYES", "FIGURE", "USER")})
    return theme
