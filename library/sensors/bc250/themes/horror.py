# SPDX-License-Identifier: GPL-3.0-or-later
"""Horror theme: a CCTV corridor, and what walks down it."""

import math
import os
import time
from typing import List

from ..base import _duration
from ..draw import _attempt, _Draw
from ..hardware import Bc250CpuTemp
from ..prompt import _Session
from ..screen import Bc250Screen
from ..splash import _Screen, _screen_level, _Splash
from ..steam import _Steam


class _Horror:
    """The horror theme's camera. A corridor, and something standing in it that only ever moves when the lights go
    out: the backlight flickers and dies, and when it comes back the figure is closer and MOTION has counted down.
    When it reaches the camera its face fills the feed; then the corridor is empty, and that is worse. Between those,
    the console talks to you about what it can see (your name, the time, your game, the temperatures), and now and
    then a label is not what it was. Almost free on the link: what moves does so in the dark or in a few small boxes
    (_Screen sends only what changed), and a flicker is one brightness command."""
    NEAR = 7  # metres: from here it is an emergency
    moves = scares = whispers = 0  # (read by the tests)

    def __init__(self, spec: dict, lcd, base):
        import random
        from PIL import Image
        self.spec, self.lcd, self.base = spec, lcd, base
        fast = bool(os.environ.get("BC250_HORROR_FAST"))  # the tests: the whole encounter in a few seconds
        self.speed = 0.03 if fast else 1.0
        self.x, self.y, self.w, self.h = (int(v) for v in spec["FEED"])
        self.room = base.crop((self.x, self.y, self.x + self.w, self.y + self.h))
        self.stages = spec["STAGES"]
        self.eyes = spec["EYES"]
        self.sprite = Image.open(_Draw.background_path(spec["FIGURE"])).convert("RGBA")
        self.small, self.large = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 36)
        self.col = {k: _Draw.color(v) for k, v in spec["COLORS"].items()}
        self.motion = tuple(int(v) for v in spec["MOTION"])
        self.layers = {}
        self.stage = 2  # it is already down there when you first look
        self.last_move = time.monotonic()
        now = time.monotonic()
        self.next_move = now + random.uniform(30, 60) * self.speed
        self.next_whisper = now + 8 * self.speed
        self.next_flicker = now + random.uniform(10, 25) * self.speed
        self.next_glitch = now + random.uniform(20, 50) * self.speed
        self.next_band = now + random.uniform(6, 18) * self.speed
        self.next_blink = now + random.uniform(4, 10)
        self.blinking_until = 0.0
        self.band_start = None
        self.whisper = None  # (lines, when it started)
        self.glitch = None  # (label, until)
        self.queue = []
        self.empty_until = 0.0

    # -- the screen's light ------------------------------------------------------------------------------------------
    def level(self, fraction: float):
        _screen_level(self.lcd, fraction)

    def flicker(self, *steps):
        for fraction, seconds in steps:
            self.level(fraction)
            time.sleep(seconds)

    # -- what it looks like ------------------------------------------------------------------------------------------
    def layer(self, index: int):
        return _Horror.figure_layer(self.sprite, self.stages[index], self.layers, index)

    @staticmethod
    def figure_layer(sprite, stage, cache, index):
        """The figure at a stage: (picture, x, y in the feed), as much light on it as there is where it stands."""
        from PIL import Image
        if index not in cache:
            _, x, top, height, light = stage
            height = int(height)
            art = sprite.resize((max(2, height // 3), max(2, height)), Image.BILINEAR)
            r, g, b, a = art.split()
            shade = lambda v: int(v * float(light))
            cache[index] = (Image.merge("RGBA", (r.point(shade), g.point(shade), b.point(shade), a)),
                            int(x) - art.width // 2, int(top))
        return cache[index]

    def eye_points(self, index: int):
        art, fx, fy = self.layer(index)
        size = 1 if art.height < 200 else 2
        return [(fx + round(ex * art.width), fy + round(ey * art.height), size) for ex, ey in self.eyes]

    def feed(self, stage=None, overlay=True):
        import datetime
        import random
        from PIL import Image, ImageDraw
        now = time.monotonic()
        frame = self.room.copy()
        d = ImageDraw.Draw(frame)
        index = self.stage if stage is None else stage
        if index >= 0:
            art, fx, fy = self.layer(index)
            frame.paste(art, (fx, fy), art)
            if now > self.next_blink:  # it blinks. Not often
                self.blinking_until = now + 0.18
                self.next_blink = now + random.uniform(5, 14)
            if now > self.blinking_until:
                for ex, ey, size in self.eye_points(index):
                    d.rectangle((ex, ey, ex + size - 1, ey + size - 1), fill=(236, 242, 226))
        if not overlay:
            return frame
        if int(time.time() * 2) % 2:
            d.ellipse((8, 7, 14, 13), fill=self.col["RED"])
        d.text((19, 15), "REC", font=self.small, fill=self.col["BRIGHT"], anchor="ls")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        d.text((self.w - 6, 15), stamp, font=self.small, fill=self.col["BRIGHT"], anchor="rs")
        if self.band_start is not None:  # the tape's tracking, rolling down the picture
            p = (now - self.band_start) / 1.1
            if p >= 1:
                self.band_start = None
            else:
                noise = Image.effect_noise((self.w, 5), 110).convert("RGB")
                frame.paste(noise, (0, round(p * (self.h - 5))))
        if self.whisper:
            lines, start = self.whisper
            shown = int((now - start) * 13 / max(self.speed, 0.25))
            total = sum(len(line) for line in lines)
            if now - start > total / 13 * max(self.speed, 0.25) + 5 * self.speed:
                self.whisper = None
            else:
                y = self.h - 8 - 14 * (len(lines) - 1)
                for line in lines:
                    part = line[:max(0, shown)]
                    shown -= len(line)
                    if part:
                        width = round(self.small.getlength(part))
                        d.rectangle(((self.w - width) // 2 - 3, y - 11, (self.w + width) // 2 + 3, y + 3), fill=(0, 0, 0))
                        d.text(((self.w - width) // 2, y), part, font=self.small, fill=(232, 236, 222), anchor="ls")
                    y += 14
        return frame

    def show(self, frame):
        self.lcd.DisplayPILImage(frame, self.x, self.y)

    def panel(self):
        """MOTION: how far it is, what it is doing, how long ago it moved."""
        from PIL import ImageDraw
        mx, my, mw, mh = self.motion
        _, bl_big, bl_a, bl_b = (int(v) for v in self.spec["MOTION_ROWS"])
        top = my + 14
        box = (mx, top, mx + mw, my + mh)
        strip = self.base.crop(box)
        d = ImageDraw.Draw(strip)
        ago = int(time.monotonic() - self.last_move)
        if self.stage < 0:
            big, line_a, line_b, fill = "-- m", "NOT ON CAMERA", "WHERE IS IT", self.col["RED"]
        else:
            metres = float(self.stages[self.stage][0])
            near = metres <= self.NEAR
            big = f"{metres:.0f} m"
            line_a = "DO NOT LOOK AWAY" if metres < 5 else "APPROACHING" if near else "IN THE CORRIDOR"
            line_b = f"MOVED {ago // 60}:{ago % 60:02d} AGO"
            fill = self.col["RED"] if near else self.col["BRIGHT"]
        d.text((2, bl_big - top), big, font=self.large, fill=fill, anchor="ls")
        d.text((2, bl_a - top), line_a, font=self.small, fill=fill, anchor="ls")
        d.text((2, bl_b - top), line_b, font=self.small, fill=self.col["MID"], anchor="ls")
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    def label_glitch(self):
        """A label reads something else, for a moment."""
        import random
        now = time.monotonic()
        if self.glitch and now > self.glitch[1]:
            self.draw_label(self.glitch[0], False)
            self.glitch = None
        if self.glitch is None and now > self.next_glitch:
            self.next_glitch = now + random.uniform(25, 90) * self.speed
            label = random.choice(list(self.spec["LABELS"]) + [None])
            self.glitch = (label, now + 0.35)
            self.draw_label(label, True)

    def draw_label(self, label, wrong: bool):
        from PIL import ImageDraw
        if label is None:  # the camera's name, in the header
            x, bl, word, other = self.spec["TITLE"]
            x, bl = int(x), int(bl)
            box = (x, bl - 11, x + 6 * max(len(word), len(other)) + 2, bl + 3)
            strip = self.base.crop(box)
            if wrong:
                strip.paste((5, 7, 6), (0, 0, strip.width, strip.height))
                ImageDraw.Draw(strip).text((0, bl - box[1]), other, font=self.small, fill=self.col["RED"], anchor="ls")
        else:
            word, x, bl, anchor, other = label
            x, bl = int(x), int(bl)
            width = 6 * max(len(word), len(other)) + 2
            box = (x, bl - 11, x + width, bl + 3) if anchor == "ls" else (x - width, bl - 11, x, bl + 3)
            strip = self.base.crop(box)
            if wrong:
                strip.paste((5, 7, 6), (0, 0, strip.width, strip.height))
                ImageDraw.Draw(strip).text((0 if anchor == "ls" else width, bl - box[1]), other, font=self.small,
                                           fill=self.col["RED"], anchor=anchor)
        self.lcd.DisplayPILImage(strip, box[0], box[1])

    # -- what it says ------------------------------------------------------------------------------------------------
    def lines_to_say(self):
        """What it could say right now, from what the machine actually sees."""
        import datetime
        import psutil
        user = self.spec.get("USER", "YOU")
        now = datetime.datetime.now()
        said = [f"{user}. I CAN SEE YOU.", "IT ONLY MOVES WHEN YOU CAN'T SEE IT.",
                "THE CAMERA IS NOT THE ONLY ONE WATCHING.", "THE DOOR ON THE RIGHT WAS CLOSED BEFORE."]
        said.append(f"IT IS {now:%H:%M}. WHY ARE YOU STILL UP?" if now.hour >= 23 or now.hour < 6 else
                    f"IT IS {now:%H:%M}. IT IS ALWAYS NIGHT DOWN HERE.")
        temp = _attempt("whisper temp", lambda: Bc250CpuTemp().read())
        if temp is not None:
            said.append(f"{temp:.0f}°. IT LIKES THE WARMTH." if temp >= 60 else f"{temp:.0f}°. IT IS COLD DOWN THERE.")
        uptime = _attempt("whisper uptime", lambda: time.time() - psutil.boot_time())
        if uptime:
            said.append(f"AWAKE FOR {_duration(uptime)}. IT DOESN'T SLEEP EITHER.")
        memory = _attempt("whisper memory", psutil.virtual_memory)
        if memory:
            said.append(f"{memory.available / 1024 ** 3:.0f} GB FREE. THERE IS ROOM FOR IT.")
        if _attempt("whisper game", _Steam.current_game):
            name = (_Session.name or "THIS").upper()
            said += [f"{name}. IT WATCHED YOU PLAY THAT.",
                     f"{_duration(_Session.seconds)} IN {name} AND YOU HAVEN'T LOOKED BEHIND YOU ONCE.",
                     "YOU CAN'T HEAR IT OVER THE GAME."]
        else:
            load = _attempt("whisper load", lambda: psutil.cpu_percent(None))
            if load is not None:
                said.append(f"NOBODY IS PLAYING. WHO IS USING {load:.0f}% OF THE CPU?")
        if self.stage >= 0 and float(self.stages[self.stage][0]) <= self.NEAR:
            said = ["DON'T LOOK AT IT.", "IT HEARD THAT.", "TOO LATE TO TURN THE SCREEN OFF.",
                    f"{user}. DON'T MOVE."]
        if self.stage < 0:
            said = ["WHERE DID IT GO?", "CHECK BEHIND THE SCREEN.", "IT KNOWS THE WAY UP NOW.",
                    f"{user}. IS YOUR DOOR CLOSED?"]
        return said

    def say(self, words: str):
        chars = self.w // 6 - 2  # two lines at most, cut at a word
        lines, line = [], ""
        for word in words.split():
            if len(line) + len(word) + 1 > chars and line:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        self.whisper = (lines[:2], time.monotonic())
        _Horror.whispers += 1

    # -- what happens ------------------------------------------------------------------------------------------------
    def lights_out(self):
        """The lights die. When they come back, it is closer."""
        import random
        self.whisper = None
        self.flicker((0.5, 0.06), (0.08, 0.05), (0.8, 0.09), (0.05, 0.07), (0.4, 0.05))
        self.level(0)
        _Horror.moves += 1
        last = self.stage >= len(self.stages) - 1
        if last:
            self.encounter()
            return
        self.stage = 0 if self.stage < 0 else self.stage + 1
        self.show(self.feed())
        self.panel()
        _Splash._wait(0)
        time.sleep(random.uniform(0.5, 1.8) * max(self.speed, 0.3))
        self.last_move = time.monotonic()
        self.flicker((0.3, 0.05), (0.02, 0.07), (0.7, 0.06), (0.15, 0.05))
        self.level(1)
        self.next_move = time.monotonic() + random.uniform(25, 70) * self.speed

    def encounter(self):
        """It has reached the camera."""
        import random
        if self.spec.get("JUMPSCARE", True):
            from PIL import Image
            face = Image.open(_Draw.background_path(self.spec["FACE"])).convert("RGB")
            self.show(face)  # sent in the dark: it takes the link most of a second, and that second is part of it
            _Splash._wait(0)
            time.sleep(0.25)
            self.level(4)  # as bright as the screen goes, for a third of a second
            time.sleep(0.33)
            _Horror.scares += 1
        self.level(0)
        self.stage = -1
        self.show(self.feed())
        self.panel()
        _Splash._wait(0)
        time.sleep(2.2 * max(self.speed, 0.3))
        self.last_move = time.monotonic()
        self.flicker((0.2, 0.08), (0.02, 0.1), (0.5, 0.08), (0.1, 0.12))
        self.level(1)
        self.queue = ["IT ISN'T ON THE CAMERA ANYMORE."]
        self.next_whisper = time.monotonic() + 1.5 * self.speed
        self.next_move = time.monotonic() + random.uniform(150, 330) * self.speed  # the corridor stays empty a while

    def step(self):
        import random
        now = time.monotonic()
        if now >= self.next_move:
            self.lights_out()
            return
        if now >= self.next_flicker:  # only a bad contact... probably
            self.next_flicker = now + random.uniform(15, 55) * self.speed
            self.flicker(*[(random.uniform(0.15, 0.7), random.uniform(0.03, 0.09)) for _ in range(random.randrange(2, 5))])
            self.level(1)
        if now >= self.next_band:
            self.next_band = now + random.uniform(7, 24) * self.speed
            self.band_start = now
        if self.whisper is None and now >= self.next_whisper:
            self.next_whisper = now + random.uniform(22, 55) * self.speed
            words = self.queue.pop(0) if self.queue else random.choice(self.lines_to_say())
            self.say(words)
        self.show(self.feed())
        self.panel()
        self.label_glitch()


class Bc250Horror:
    """Horror theme: starts the camera's thread (once), from its theme.yaml entry."""
    _thread = None

    @staticmethod
    def _animate(spec: dict):
        from library.display import display
        camera = _Horror(spec, display.lcd, _Draw.background(spec.get("BACKGROUND_IMAGE", "background.png")))
        if _Draw.screen is not None:
            camera.lcd = _Draw.screen  # shared with the other widgets: it knows the screen shows the background
        else:
            camera.lcd = _Screen(display.lcd, *camera.base.size)
            import numpy
            camera.lcd.shadow = numpy.asarray(camera.base).copy()  # the app has just drawn the background
        camera.lcd.TILE = int(spec.get("TILE", 10))
        frame = 1 / float(spec.get("FPS", 8))
        while True:
            start = time.monotonic()
            if Bc250Screen._mode == "off":
                time.sleep(1)
                continue
            _attempt("horror frame", camera.step)
            _Splash._wait(0)  # let the queue drain: the camera never holds up the other widgets
            time.sleep(max(0.0, frame - (time.monotonic() - start)))

    def as_numeric(self) -> float:
        import threading
        spec = _Draw.theme("Bc250Horror")
        if spec and _Draw.enabled and (Bc250Horror._thread is None or not Bc250Horror._thread.is_alive()):
            Bc250Horror._thread = threading.Thread(target=self._animate, args=(spec,), name="BC250 horror", daemon=True)
            Bc250Horror._thread.start()
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass


class _HorrorSplash:
    """Horror boot. It starts as the most ordinary thing in the world: a self-test on a black screen, every line OK.
    Then one line too many: OCCUPANTS 2, expected 1. The readings stop being readings, the screen goes dark, one
    sentence, and for a fifth of a second you see the feed with it right there. Then the feed, and it is far away."""
    TURNED = {"CPU": "IT CAN HEAR THE FAN", "MEMORY": "IT REMEMBERS YOU", "GPU": "IT CAN SEE",
              "TEMPS": "IT IS GETTING WARMER", "STORAGE": "THERE IS ROOM DOWN THERE", "NETWORK": "NO ONE WILL HEAR",
              "STEAM": "YOU CAN'T QUIT"}

    @classmethod
    def play(cls, lcd, spec: dict):
        import random
        from library import config
        from PIL import Image, ImageDraw
        black = _Draw.background(spec.get("IMAGE", "splash.png"))
        w, h = black.size
        target = max(1, min(100, int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))))
        small = _Draw.font(spec["FONT"], 12)
        text, dim, red, mid = (_Draw.color(spec.get(k)) for k in ("TEXT", "DIM", "RED", "MID"))
        label_x, value_x, status_xr = (int(spec[k]) for k in ("LABEL_X", "VALUE_X", "STATUS_XR"))
        chars = int(spec.get("VALUE_CHARS", 40))

        def level(fraction):
            lcd.SetBrightness(max(0, min(100, round(target * fraction))))

        def line(y, words, fill, anchor="ls", x=label_x):
            box = (0, y - 11, w, y + 3)
            strip = black.crop(box)
            ImageDraw.Draw(strip).text((x, y - box[1]), words, font=small, fill=fill, anchor=anchor)
            lcd.DisplayPILImage(strip, 0, box[1])

        def row(index, label, value, status, fill=None, status_fill=None):
            baseline = int(spec["ROW_BL"]) + index * int(spec["ROW_STEP"])
            box = (0, baseline - 11, w, baseline + 3)
            strip = black.crop(box)
            d = ImageDraw.Draw(strip)
            oy = baseline - box[1]
            d.text((label_x, oy), label, font=small, fill=dim, anchor="ls")
            d.text((value_x, oy), _Splash.fit(value, chars), font=small, fill=fill or text, anchor="ls")
            d.text((status_xr, oy), status, font=small, fill=status_fill or dim, anchor="rs")
            lcd.DisplayPILImage(strip, 0, box[1])

        # 1. an ordinary self-test
        level(0)
        lcd.DisplayPILImage(black, 0, 0)
        level(1)
        line(int(spec["ROW_BL"]) - 36, "BC-250 SECURITY CONSOLE  v2.50", dim)
        lines = _Splash.post_lines(spec)
        for i, (label, value, status) in enumerate(lines):
            row(i, label, value, "...")
            _Splash._wait(0.1)
            row(i, label, value, "OK" if status == "OK" else status, None, red if status in ("WARN", "HOT!") else None)
            _Splash._wait(0.08)

        # 2. one line too many
        extra = len(lines)
        row(extra, "OCCUPANTS", "...", "...")
        _Splash._wait(0.5)
        row(extra, "OCCUPANTS", "2 (expected 1)", "??", text, red)
        _Splash._wait(0.8)

        # 3. the readings stop being readings
        order = list(enumerate(lines))
        random.shuffle(order)
        for i, (label, _, _) in order:
            level(random.uniform(0.3, 1.0))
            row(i, label, cls.TURNED.get(label, "IT IS HERE"), "NO", red, red)
            _Splash._wait(random.uniform(0.06, 0.16))
        level(0.1)
        _Splash._wait(0.08)
        level(1)
        _Splash._wait(0.25)

        # 4. dark, one sentence
        level(0)
        lcd.DisplayPILImage(black, 0, 0)
        words = "it was already running when you pressed the button"
        line(h // 2, words[:(w - 8) // 6], text, "ms", w // 2)
        _Splash._wait(0.5)
        level(0.8)
        _Splash._wait(0.9)
        level(0)

        # 5. a fifth of a second of what is on the camera, close (sent in the dark)
        background = _Draw.background("background.png").copy()
        x, y, fw, fh = (int(v) for v in spec["FEED"])
        sprite = Image.open(_Draw.background_path(spec["FIGURE"])).convert("RGBA")
        stages = spec["STAGES"]
        art, fx, fy = _Horror.figure_layer(sprite, stages[-1], {}, len(stages) - 1)
        close = background.copy()
        feed = close.crop((x, y, x + fw, y + fh))
        feed.paste(art, (fx, fy), art)
        close.paste(feed, (x, y))
        lcd.DisplayPILImage(close, 0, 0)
        _Splash._wait(0.1)
        level(1.6)
        _Splash._wait(0.2)
        level(0)

        # 6. and then it is just a corridor
        lcd.DisplayPILImage(background, 0, 0)
        _Splash._wait(0.2)
        _Splash._animate(0.6, lambda p: level(p * p))


_Splash.STYLES["horror"] = _HorrorSplash
