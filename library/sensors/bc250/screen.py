# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen power: dims when idle, sleeps at night."""

import datetime
import math
import re
import time
from typing import List

from .draw import _Draw
from .steam import _Downloads, _Shaders, _Steam


def _in_window(now: datetime.time, window: str) -> bool:
    """window like "23:30-08:00" (may wrap over midnight); empty means never."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", window or "")
    if not match:
        return False
    h1, m1, h2, m2 = (int(g) for g in match.groups())
    start, end = datetime.time(h1, m1), datetime.time(h2, m2)
    return start <= now < end if start <= end else now >= start or now < end


class Bc250Screen:
    """Brightness manager, configured by SCREEN in theme.yaml:
    DIM_AFTER (minutes without game or download, 0 = never), DIM_BRIGHTNESS (%), NIGHT ("HH:MM-HH:MM", "" = off),
    NIGHT_MODE ("off" or "dim"). A running game always keeps the screen at full brightness."""
    _mode = "on"
    _last_activity = time.monotonic()

    def as_numeric(self) -> float:
        spec = _Draw.theme("Bc250Screen").get("SCREEN", {})
        now = time.monotonic()
        if _Steam.current_game() or _Downloads.active or _Shaders.active:
            Bc250Screen._last_activity = now

        mode = "on"
        dim_after = float(spec.get("DIM_AFTER", 10) or 0)
        if not _Steam.current_game():
            if _in_window(datetime.datetime.now().time(), spec.get("NIGHT", "")):
                # an unquoted `off` in YAML reads as False
                mode = "dim" if str(spec.get("NIGHT_MODE", "off")).lower() == "dim" else "off"
            elif dim_after and now - self._last_activity > dim_after * 60:
                mode = "dim"
        if mode != Bc250Screen._mode:
            _Draw.safely("screen", self._apply, mode, spec)
            Bc250Screen._mode = mode
        return math.nan

    @staticmethod
    def _apply(mode: str, spec: dict):
        from library import config
        from library.display import display
        if mode == "off":
            display.lcd.ScreenOff()
            return
        if Bc250Screen._mode == "off":
            display.lcd.ScreenOn()
        full = int(config.CONFIG_DATA["display"].get("BRIGHTNESS", 20))
        display.lcd.SetBrightness(int(spec.get("DIM_BRIGHTNESS", 5)) if mode == "dim" else full)

    def as_string(self) -> str:
        return " "

    def last_values(self) -> List[float]:
        pass
