# SPDX-License-Identifier: GPL-3.0-or-later
"""The bottom prompt line: boot, the game being played, a download, or the last session."""

import math
from typing import List

from .base import _duration, _is_nan
from .draw import _attempt, _dim, _Draw
from .hardware import _AmdGpu, Bc250CpuTemp, Bc250GpuTemp
from .steam import _Downloads, _MangoHud, _Shaders, _Steam, _steam_roots


class _Session:
    """The game being played, its peak temperatures, and the last finished session.

    A session shorter than MIN_SECONDS is not remembered: launches that fail or quit at once leave no trace."""
    MIN_SECONDS = 60
    app_id = None
    name = None
    pid = None
    seconds = None
    peak_cpu = None
    peak_gpu = None
    last = None  # {"name", "seconds", "peak_cpu", "peak_gpu"} of the previous game

    @classmethod
    def update(cls, game):
        if cls.app_id is not None and (game is None or game[0] != cls.app_id):
            cls._finish()
        if game is None:
            return
        if cls.app_id is None:
            cls.app_id, cls.name = game[0], _Steam.app_name(game[0])
            cls.peak_cpu = cls.peak_gpu = None
        cls.pid = game[1]
        cls.seconds = _Steam.seconds_running(game[1])
        for attr, temp in (("peak_cpu", Bc250CpuTemp.value), ("peak_gpu", Bc250GpuTemp.value)):
            if not _is_nan(temp):
                setattr(cls, attr, max(getattr(cls, attr) or temp, temp))

    @classmethod
    def _finish(cls):
        if (cls.seconds or 0) >= cls.MIN_SECONDS:
            cls.last = {"name": cls.name, "seconds": cls.seconds, "peak_cpu": cls.peak_cpu, "peak_gpu": cls.peak_gpu}
        cls.app_id = cls.name = cls.pid = cls.seconds = None


def _rate(bps: float) -> str:
    for unit in ("B", "K", "M", "G"):
        if bps < 1000 or unit == "G":
            return f"{bps:.0f}{unit}/s" if unit == "B" else f"{bps:.1f}{unit}/s"
        bps /= 1000
    return "--"


def _peaks(cpu, gpu) -> str:
    fmt = lambda t: "--" if t is None else f"{t:.0f}"
    return f"{fmt(cpu)}/{fmt(gpu)}°"


class Bc250Prompt:
    BOOT_TICKS = 4
    _tick = 0

    @staticmethod
    def _state(tick: int) -> dict:
        """What the prompt shows: cmd word, main text, two right columns (label, value), progress fraction."""
        if tick <= Bc250Prompt.BOOT_TICKS:
            gpu = _AmdGpu.find().device
            lines = ["POST bc250 sensors..",
                     "amdgpu " + ("ok" if gpu else "MISSING"),
                     "steam  " + ("ok" if _steam_roots() else "MISSING"),
                     "ready"]
            return {"cmd": "boot", "text": lines[min(tick, len(lines)) - 1], "cols": [], "progress": None}

        game = _attempt("game detection", _Steam.current_game)
        _attempt("session", lambda: _Session.update(game))
        # polled every refresh even while playing, so their rates and progress stay current
        download = _attempt("downloads", _Downloads.poll)
        shaders = _attempt("shaders", _Shaders.poll)

        if game:
            fps = _attempt("mangohud", _MangoHud.fps)
            cols = [("FPS", f"{fps:.0f}")] if fps is not None else []
            cols.append(("SESSION", _duration(_Session.seconds)))
            return {"cmd": "now-playing", "text": _Session.name or _Steam.app_name(game[0]), "cols": cols,
                    "progress": None}

        if download:
            fraction = download["fraction"]
            if fraction is None:  # verifying, or no byte counts yet
                cols = [("RATE", _rate(download["rate"]))] if download["rate"] > 1000 else []
            else:
                cols = [("DONE", f"{fraction * 100:.0f}%"), ("ETA", _duration(download["eta"]))]
            return {"cmd": download["phase"], "text": download["name"], "cols": cols, "progress": fraction}

        if shaders:
            pct = shaders["percent"]
            return {"cmd": "fossilize_replay", "text": shaders["name"],
                    "cols": [("SHADERS", "--%" if pct is None else f"{pct}%"),
                             ("ETA", "STALL" if shaders["stalled"] else _duration(shaders["eta"]))],
                    "progress": None if pct is None else pct / 100, "accent": "AMBER",
                    "alert_col": shaders["stalled"]}

        last = _Session.last
        if last:
            return {"cmd": "last-session", "text": last["name"],
                    "cols": [("TIME", _duration(last["seconds"])),
                             ("PEAK C/G", _peaks(last["peak_cpu"], last["peak_gpu"]))],
                    "progress": None}
        return {"cmd": "idle", "text": "idle", "cols": [], "progress": None}

    @staticmethod
    def draw(spec: dict, state: dict, cursor: bool):
        from PIL import ImageDraw
        area = spec["AREA"]
        image = _Draw.crop(area)
        d = ImageDraw.Draw(image)
        ox, oy = area["X"], area["Y"]
        small, big = _Draw.font(spec["FONT"], 12), _Draw.font(spec["FONT"], 24)
        bright, mid, dim = (_Draw.color(spec.get(k)) for k in ("BRIGHT", "MID", "DIM"))
        accent = _Draw.color(spec.get(state.get("accent", "MID")), mid)
        label_bl, value_bl = spec["LABEL_BL"] - oy, spec["VALUE_BL"] - oy
        label_c = _Draw.color(spec["LABEL_COLOR"]) if spec.get("LABEL_COLOR") else dim
        cmd, text = state["cmd"], state["text"] or ""
        words = spec.get("CMD_WORDS")
        if words:  # e.g. Game Boy: "IS PLAYING", idle shown as "IS RESTING" / "Zzz"
            if cmd == "idle":
                text = words.get("idle-text", text)
            cmd = words.get(cmd, cmd.upper())
        elif cmd == "idle":
            cmd = "now-playing"

        if state["progress"] is not None and spec.get("PROGRESS_STYLE") == "mosaic":
            # videotex: a row of separated blocks along the top of the band (the rows below are all text)
            right = round(area["WIDTH"] * state["progress"])
            for bx in range(0, right - 4, 6):
                d.rectangle((bx + 1, 1, bx + 5, 4), fill=accent)
        elif state["progress"] is not None:
            # progress bar filling the value row behind the text, on the bright scanlines
            right = round(area["WIDTH"] * state["progress"])
            for py in range(label_bl + 4, area["HEIGHT"] - 2):
                if (oy + py) % 2 == 0:
                    d.line((0, py, right, py), fill=_dim(accent, 0.45))
            d.line((0, area["HEIGHT"] - 2, right, area["HEIGHT"] - 2), fill=accent)

        d.text((spec["CMD_X"] - ox, label_bl), cmd, font=small, fill=label_c, anchor="ls")

        amber = _Draw.color(spec.get("AMBER"))
        col_words = spec.get("COL_WORDS") or {}  # e.g. videotex: DONE -> FAIT
        state = dict(state, cols=[(col_words.get(label, label), value) for label, value in state["cols"]])
        if "COLS_BL" in spec:
            # portrait: values on a row of their own, small label on the left of each half, value on the right
            cols_bl = int(spec["COLS_BL"]) - oy
            for i, ((label, value), (xl, xr)) in enumerate(zip(state["cols"], spec["COLS"])):
                warn = i == len(state["cols"]) - 1 and state.get("alert_col")  # e.g. a stalled shader job
                d.text((xl - ox, cols_bl), label, font=small, fill=label_c, anchor="ls")
                fits = d.textlength(label, font=small) + d.textlength(value, font=big) + 6 <= xr - xl
                d.text((xr - ox, cols_bl), value, font=big if fits else small, fill=amber if warn else bright,
                       anchor="rs")  # a narrow column: the small font rather than over its label
        else:
            # landscape: columns on the value row, laid out from the right edge
            right_edges = [spec["COL2_XR"] - ox, spec["COL1_XR"] - ox]
            for i, ((label, value), xr) in enumerate(zip(reversed(state["cols"]), right_edges)):
                d.text((xr, label_bl), label, font=small, fill=label_c, anchor="rs")
                warn = i == 0 and state.get("alert_col")  # e.g. a stalled shader job
                d.text((xr, value_bl), value, font=big, fill=amber if warn else bright, anchor="rs")

        room = spec["MAX_CHARS"] if len(state["cols"]) > 1 else spec["MAX_CHARS_WIDE"]
        mark = spec.get("CURSOR", "_")
        if len(text) > room and spec.get("SMALL_FALLBACK"):
            # a narrow box: the small font, on two lines if needed, rather than cutting the name
            per_line = room * 2
            words, lines = text.split(), [""]
            for word in words:
                if len(lines[-1]) + len(word) + (1 if lines[-1] else 0) <= per_line:
                    lines[-1] += (" " if lines[-1] else "") + word
                elif len(lines) < 2:
                    lines.append(word[:per_line])
                else:
                    lines[-1] = (lines[-1] + " " + word)[:per_line - 1] + "~"
                    break
            lines = [line[:per_line] for line in lines]
            tops = [value_bl - 11, value_bl] if len(lines) == 2 else [value_bl - 4]
            for i, (line, bl) in enumerate(zip(lines, tops)):
                d.text((spec["TEXT_X"] - ox, bl), line + (mark if cursor and i == len(lines) - 1 else ""),
                       font=small, fill=bright, anchor="ls")
        else:
            if len(text) > room:
                text = text[:room - 1] + "~"
            d.text((spec["TEXT_X"] - ox, value_bl), text + (mark if cursor else ""), font=big, fill=bright,
                   anchor="ls")
        _Draw.show(image, area)

    def as_numeric(self) -> float:
        Bc250Prompt._tick += 1
        spec = _Draw.theme("Bc250Prompt")
        state = _attempt("prompt state", lambda: self._state(Bc250Prompt._tick),
                         {"cmd": "now-playing", "text": "idle", "cols": [], "progress": None})
        if "AREA" in spec:
            _Draw.safely("prompt", self.draw, spec, state, Bc250Prompt._tick % 2 == 0)
        return math.nan

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass
