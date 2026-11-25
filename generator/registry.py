"""Every theme, as its module in generator/themes/ declares it (THEME = Theme(...)). make_theme.py, theme.yaml (build.py),
the checks and the README previews all read it here: a new theme is a new module, nothing to add to a list."""
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class Theme:
    name: str  # --theme NAME
    description: str  # what it is, in theme.yaml's first line after its folder's name
    render: Callable  # render(out, title, prompt, user): writes its artwork into the folder out
    title: str = "{LOGO}::{USER}"  # the default header text
    status_line: Optional[Callable] = None  # status_line(user): its words and colours for Bc250Prompt
    boot: Optional[Callable] = None  # boot(): its part of bc250_splash (its own boot animation: STYLE)
    pixel_logo: bool = False  # the boot's logo drawn in the pixel font, at the layout's logo_box
    widgets: Optional[Callable] = None  # widgets(theme, title, user): adds the widgets only it has to theme.yaml
    portrait_app: bool = False  # checks: the whole app in portrait too (it has a layout and threads of its own)
    app_variants: tuple = ()  # checks: the whole app again with each of these make_theme.py option lists
    preview_options: tuple = ()  # tools/make_previews.py: make_theme.py options for its README pictures

    @property
    def folder(self) -> str:
        from .base import SKINS
        return SKINS[self.name]["folder"]


def themes() -> dict:
    """{name: Theme}: phosphor (the default) first, then by name."""
    from . import themes as package
    found = {}
    for module in pkgutil.iter_modules(package.__path__):
        theme = getattr(importlib.import_module(f"{package.__name__}.{module.name}"), "THEME", None)
        if theme is not None:
            found[theme.name] = theme
    return dict(sorted(found.items(), key=lambda item: (item[0] != "phosphor", item[0])))
