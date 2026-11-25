# SPDX-License-Identifier: GPL-3.0-or-later
"""Paths, logging and small helpers every other module uses."""

import logging
import math
import os
from pathlib import Path
from typing import List, Optional


# Classes follow the CustomDataSource interface (as_numeric / as_string / last_values) without inheriting it:
# sensors_custom.py re-exports this module, so importing it back here would be circular.

SYSFS_ROOT = os.environ.get("BC250_SYSFS_ROOT", "/")
PROC_ROOT = os.environ.get("BC250_PROC_ROOT", "/proc")
REPO_DIR = Path(__file__).resolve().parents[3]

HISTORY_SIZE = 60
APU_POWER_BAR_MAX_W = 250

logger = logging.getLogger("turing.bc250")  # a child of the app's logger: same output (journal), same level


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read().strip()
    except (OSError, ValueError):
        return None


def _read_int(path: Optional[str]) -> Optional[int]:
    if path is None:
        return None
    value = _read(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _push(history: List[float], value: Optional[float]):
    history.append(math.nan if value is None else value)
    del history[:-HISTORY_SIZE]


def _is_nan(value) -> bool:
    return value is None or value != value


def _duration(seconds: Optional[float]) -> str:
    """Unambiguous short duration: 45s, 12m, 1h05."""
    if seconds is None:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds >= 100 * 3600:
        return ">99h"  # keeps every column within 5 characters
    return f"{seconds // 3600}h{seconds // 60 % 60:02d}"


def _compass(bearing: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round(bearing / 45) % 8]
