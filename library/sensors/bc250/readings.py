# SPDX-License-Identifier: GPL-3.0-or-later
"""The machine's readings for the themes that draw them all themselves (departures, racing)."""

import time

from .base import _is_nan
from .draw import _attempt
from .hardware import Bc250ApuPower, Bc250CpuTemp, Bc250GpuLoad, Bc250GpuTemp, gpu_clock_mhz
from .steam import _GameDisk


class _Readings:
    """The machine's readings for a theme that draws them all itself (departures, racing): the values the app samples
    every second for the other BC-250 widgets, psutil, sysfs, and network rates between two calls."""

    def __init__(self):
        self.net = None  # (time, received, sent)

    def _net(self):
        import psutil
        counters = [c for nic, c in psutil.net_io_counters(pernic=True).items() if nic != "lo"]
        now, rx, tx = time.monotonic(), sum(c.bytes_recv for c in counters), sum(c.bytes_sent for c in counters)
        previous, self.net = self.net, (now, rx, tx)
        if previous is None or now - previous[0] <= 0:
            return None, None
        seconds = now - previous[0]
        return max(0, rx - previous[1]) / seconds, max(0, tx - previous[2]) / seconds

    def read(self) -> dict:
        import psutil

        def first(*sources):
            for source in sources:
                value = _attempt("dashboard reading", source)
                if value is not None and not _is_nan(value):
                    return float(value)
            return None

        memory, disk = _attempt("dashboard memory", psutil.virtual_memory), _attempt("dashboard disk", _GameDisk.usage)
        rx, tx = _attempt("dashboard network", self._net, (None, None))
        return {"cpu": first(lambda: psutil.cpu_percent(None)),
                "cpu_t": first(lambda: Bc250CpuTemp.value, lambda: Bc250CpuTemp().read()),
                # (before the app samples them, at boot, they are read here)
                "gpu": first(lambda: Bc250GpuLoad.value, lambda: Bc250GpuLoad().as_numeric()),
                "gpu_t": first(lambda: Bc250GpuTemp.value, lambda: Bc250GpuTemp().read()),
                "pwr": first(lambda: Bc250ApuPower.value, lambda: Bc250ApuPower().as_numeric()),
                "clk": first(gpu_clock_mhz),
                "ram": memory.percent if memory else None, "ram_gb": memory.used / 1024 ** 3 if memory else None,
                "ssd": disk.percent if disk else None, "ssd_free": disk.free / 1000 ** 3 if disk else None,
                "rx": rx, "tx": tx}
