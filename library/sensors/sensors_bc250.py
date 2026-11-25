# SPDX-License-Identifier: GPL-3.0-or-later
#
# BC-250 custom sensors for turing-smart-screen-python: the app's way in to the package library/sensors/bc250/.
#
# sensors_custom.py imports everything from here, and each theme.yaml names its widgets (CUSTOM: Bc250GpuLoad, ...).
# Every name of the package's modules is also here, as when they were all in this one file: bc250_check.py and the
# checks use them through this module.

from library.sensors import bc250 as _bc250

for _module in _bc250.MODULES:
    globals().update({_name: _value for _name, _value in vars(_module).items() if not _name.startswith("__")})
del _module
