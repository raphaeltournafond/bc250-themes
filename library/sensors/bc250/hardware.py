# SPDX-License-Identifier: GPL-3.0-or-later
"""The BC-250's own readings: GPU clock, temperature, load and memory from amdgpu sysfs, APU power, CPU
temperature."""

import glob
import math
import os
import re
import time
from typing import List, Optional

from . import base
from .base import APU_POWER_BAR_MAX_W, HISTORY_SIZE, _read, _read_int
from .draw import _Draw, draw_heat_bar, draw_heat_text, _TempWidget


class _AmdGpu:
    """Locates the amdgpu device once and caches its sysfs paths."""
    _searched = False
    device: Optional[str] = None
    hwmon: Optional[str] = None
    pci_slot: Optional[str] = None

    @classmethod
    def find(cls):
        if cls._searched:
            return cls
        cls._searched = True
        for card in sorted(glob.glob(os.path.join(base.SYSFS_ROOT, "sys/class/drm/card[0-9]*"))):
            if "-" in os.path.basename(card):  # connectors e.g. card0-HDMI-A-1
                continue
            device = os.path.join(card, "device")
            if _read(os.path.join(device, "vendor")) != "0x1002":
                continue
            cls.device = device
            hwmons = sorted(glob.glob(os.path.join(device, "hwmon", "hwmon*")))
            cls.hwmon = hwmons[0] if hwmons else None
            uevent = _read(os.path.join(device, "uevent")) or ""
            match = re.search(r"PCI_SLOT_NAME=(\S+)", uevent)
            cls.pci_slot = match.group(1) if match else None
            break
        return cls

    @classmethod
    def path(cls, *parts) -> Optional[str]:
        cls.find()
        return os.path.join(cls.device, *parts) if cls.device else None

    @classmethod
    def hwmon_path(cls, name) -> Optional[str]:
        cls.find()
        return os.path.join(cls.hwmon, name) if cls.hwmon else None


UNLOCKED_MIN_GPU_MHZ = 200  # the clock never really goes this low; the misread value after a core unlock stays under


def cpu_threads() -> Optional[int]:
    """How many threads the kernel sees ("0-11" on a stock BC-250), None if it can't be told."""
    present = _read(os.path.join(base.SYSFS_ROOT, "sys/devices/system/cpu/present")) or ""
    match = re.fullmatch(r"0-(\d+)", present.strip())
    return int(match.group(1)) + 1 if match else None


def core_unlocked() -> bool:
    """Whether the board's two extra CPU cores were unlocked (8C/16T instead of 6C/12T)."""
    return (cpu_threads() or 0) > 12


def gpu_clock_mhz() -> Optional[float]:
    """The GPU clock. With the core unlock the kernel misreads it (a value between 0 and 100 MHz, whatever the real
    clock): there, a reading that low is not shown at all. cyan-skillfish-governor's fix-freq option replaces
    freq1_input with the real clock, which then shows as usual."""
    mhz = None
    hz = _read_int(_AmdGpu.hwmon_path("freq1_input"))
    if hz:
        mhz = hz / 1_000_000
    else:
        # pp_dpm_sclk lines look like "1: 2000Mhz *", the star marking the active level
        for line in (_read(_AmdGpu.path("pp_dpm_sclk") or "") or "").splitlines():
            match = re.search(r"(\d+)\s*Mhz\s*\*", line, re.IGNORECASE)
            if match:
                mhz = float(match.group(1))
                break
    if mhz is not None and mhz < UNLOCKED_MIN_GPU_MHZ and core_unlocked():
        return None
    return mhz


class Bc250GpuClock:
    value = None

    def as_numeric(self) -> float:
        Bc250GpuClock.value = gpu_clock_mhz()
        return math.nan if self.value is None else self.value

    def as_string(self) -> str:
        return "----" if self.value is None else f"{self.value:.0f}"

    def last_values(self) -> List[float]:
        pass


class Bc250GpuTemp(_TempWidget):
    last_val = [math.nan] * HISTORY_SIZE

    def read(self) -> Optional[float]:
        millideg = _read_int(_AmdGpu.hwmon_path("temp1_input"))
        return millideg / 1000 if millideg is not None else None


class Bc250GpuLoad:
    # Sums the drm-engine-gfx busy time of every amdgpu DRM client and divides by wall time between two samples
    _prev_clients = {}
    _prev_time = None
    _counters_seen = False
    value = None

    @staticmethod
    def _sample() -> dict:
        clients = {}
        for pid in os.listdir(base.PROC_ROOT):
            if not pid.isdigit():
                continue
            fd_dir = os.path.join(base.PROC_ROOT, pid, "fd")
            try:
                fds = os.listdir(fd_dir)
            except OSError:
                continue  # process gone or owned by another user
            for fd in fds:
                try:
                    if not os.readlink(os.path.join(fd_dir, fd)).startswith("/dev/dri/"):
                        continue
                    with open(os.path.join(base.PROC_ROOT, pid, "fdinfo", fd), "r") as f:
                        info = f.read()
                except OSError:
                    continue
                if "amdgpu" not in info:
                    continue
                pdev = re.search(r"drm-pdev:\s*(\S+)", info)
                if _AmdGpu.pci_slot and pdev and pdev.group(1) != _AmdGpu.pci_slot:
                    continue
                client = re.search(r"drm-client-id:\s*(\d+)", info)
                gfx = re.search(r"drm-engine-gfx:\s*(\d+)\s*ns", info)
                if client and gfx:
                    # Several fds can share one client: keep a single entry per client id
                    clients[client.group(1)] = int(gfx.group(1))
        return clients

    def as_numeric(self) -> float:
        _AmdGpu.find()
        now = time.monotonic()
        try:
            clients = self._sample()
        except OSError:
            clients = {}
        prev, prev_time = Bc250GpuLoad._prev_clients, Bc250GpuLoad._prev_time
        Bc250GpuLoad._prev_clients, Bc250GpuLoad._prev_time = clients, now

        if clients:
            Bc250GpuLoad._counters_seen = True
        if prev_time is None or not (clients or Bc250GpuLoad._counters_seen):
            # No sample yet, or engine counters never seen (old kernel / no permission): unknown rather than 0%
            Bc250GpuLoad.value = None
            return math.nan
        busy_ns = sum(max(0, ns - prev[cid]) for cid, ns in clients.items() if cid in prev)
        elapsed_ns = (now - prev_time) * 1e9
        Bc250GpuLoad.value = max(0.0, min(100.0, busy_ns * 100 / elapsed_ns)) if elapsed_ns > 0 else None
        return math.nan if self.value is None else self.value

    def as_string(self) -> str:
        return "--%" if self.value is None else f"{self.value:.0f}%"

    def last_values(self) -> List[float]:
        pass


class Bc250GpuMem:
    value = None

    def as_numeric(self) -> float:
        vram = _read_int(_AmdGpu.path("mem_info_vram_used"))
        gtt = _read_int(_AmdGpu.path("mem_info_gtt_used"))
        if vram is None and gtt is None:
            Bc250GpuMem.value = None
            return math.nan
        Bc250GpuMem.value = ((vram or 0) + (gtt or 0)) / 1024 ** 3
        return self.value

    def as_string(self) -> str:
        return "--G" if self.value is None else f"{self.value:.1f}G"

    def last_values(self) -> List[float]:
        pass


class Bc250ApuPower:
    value = None

    def as_numeric(self) -> float:
        microwatts = _read_int(_AmdGpu.hwmon_path("power1_average"))
        if microwatts is None:
            microwatts = _read_int(_AmdGpu.hwmon_path("power1_input"))
        Bc250ApuPower.value = microwatts / 1_000_000 if microwatts is not None else None
        spec = _Draw.theme("Bc250ApuPower")
        if "HEAT_TEXT" in spec:
            _Draw.safely("power text", draw_heat_text, spec, spec["HEAT_TEXT"], self.value, False, "W")
        if "HEAT_BAR" in spec:
            _Draw.safely("power bar", draw_heat_bar, spec, spec["HEAT_BAR"], self.value)
        if self.value is None:
            return math.nan
        return max(0.0, min(float(APU_POWER_BAR_MAX_W), self.value))

    def as_string(self) -> str:
        return "--W" if self.value is None else f"{self.value:.0f}W"

    def last_values(self) -> List[float]:
        pass


class Bc250CpuTemp(_TempWidget):
    last_val = [math.nan] * HISTORY_SIZE

    def read(self) -> Optional[float]:
        try:
            import psutil
            temps = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return None
        for chip in ("k10temp", "zenpower"):
            entries = temps.get(chip) or []
            # Tctl/Tdie is the package temperature; other entries are per-CCD
            for entry in entries:
                if entry.label in ("Tctl", "Tdie"):
                    return entry.current
            if entries:
                return entries[0].current
        return None
