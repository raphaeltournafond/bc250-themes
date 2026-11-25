# SPDX-License-Identifier: GPL-3.0-or-later
"""BC-250 custom sensors and widgets for turing-smart-screen-python, used through library/sensors/sensors_bc250.py.

The AMD BC-250 (Cyan Skillfish APU) does not expose gpu_busy_percent, and pyamdgpuinfo has no wheels for
Python > 3.12, so the stock GPU sensors are unreliable on it. These classes read amdgpu sysfs / procfs directly:
  - GPU clock       hwmon freq1_input, falling back to the active level of pp_dpm_sclk
  - GPU temperature hwmon temp1_input
  - GPU load        derived from per-process DRM fdinfo counters (drm-engine-gfx), the same source nvtop uses
  - GPU memory      mem_info_vram_used + mem_info_gtt_used (the BC-250 shares its 16 GB GDDR6)
  - APU power       hwmon power1_average / power1_input
  - Game disk       usage of the drive holding the Steam library ("/" is a read-only image on Bazzite/SteamOS)

Some widgets are drawn by this package rather than by the app, from their own keys in theme.yaml:
  - Bc250CpuTemp / Bc250GpuTemp (HEAT_TEXT, HEAT_GRAPH, ALERT_TAG): temperature and 60 s history coloured from
    COLD_COLOR to HOT_COLOR between COLD and HOT, turning ALERT_COLOR and flashing "HOT!" from ALERT
  - Bc250Prompt (PROMPT): the bottom line. boot check, then the game being played (with MangoHud FPS and session
    time), a Steam download or shader pre-caching job with its progress / ETA, or the last session with its peak
    temperatures
  - Bc250ApuPower (HEAT_TEXT, HEAT_BAR): watts and bar on the same green -> orange -> red scale (COLD / HOT / ALERT)
  - boot splash (bc250_splash in theme.yaml): a BIOS-style POST with live values, played once before the
    dashboard is drawn (hooked onto the app's display_static_images, no change to the app itself)
  - bc250_palette in theme.yaml (Game Boy theme): every colour computed here snaps to its shades, and "dim"
    means towards its background (lighter on a Game Boy, darker on the phosphor terminal)
  - Bc250Screen (SCREEN): dims the display after DIM_AFTER minutes without game or download, sleeps at NIGHT
  - each theme's own widgets and boot animation, in themes/ (one module per theme)

Every sensor degrades to "--" when its source is missing: a custom sensor that raises would stop all the
following custom sensors from refreshing (see stats.Custom.stats).

Environment overrides: BC250_SYSFS_ROOT / BC250_PROC_ROOT (fake trees for testing), BC250_DISK_PATH (games drive),
BC250_MANGOHUD_DIR (MangoHud log folder).

Classes follow the CustomDataSource interface (as_numeric / as_string / last_values) without inheriting it:
sensors_custom.py re-exports this package, so importing it back here would be circular."""

import importlib
import pkgutil

from . import base, draw, hardware, steam, prompt, screen, splash, readings, themes

# every module of themes/ (each registers its boot and its widgets as it is imported): a new theme is a new module
THEME_MODULES = tuple(importlib.import_module(f"{themes.__name__}.{module.name}")
                      for module in sorted(pkgutil.iter_modules(themes.__path__), key=lambda module: module.name))
MODULES = (base, draw, hardware, steam, prompt, screen, splash, readings) + THEME_MODULES

for _module in MODULES:  # an error in a widget shows "--" rather than stopping the widgets after it
    for _obj in list(vars(_module).values()):
        if isinstance(_obj, type) and _obj.__name__.startswith("Bc250") and _obj.__module__ == _module.__name__:
            splash._resilient(_obj)

splash._install_splash_hook()
