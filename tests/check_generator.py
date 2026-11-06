"""The generator, for every theme and both orientations:
- the landscape defaults reproduce the files committed in res/themes (theme.yaml exactly, pictures pixel for pixel),
  and nothing else is left over there;
- every live area is on the screen and no two of them overlap (a widget repainting its box would wipe the other).
Usage (from the app's folder): python check_generator.py [theme ...]"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPO, THEMES, report  # noqa: E402

import yaml  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

ANTIALIAS_LEVELS = 8
GENERATED_ONLY = ("preview.png", "preview_portrait.png", "preview_encounter.png", "splash_preview.gif",
                  "splash_preview_portrait.gif")


def generate(theme, portrait):
    args = [sys.executable, os.path.join(REPO, "make_theme.py"), "--app", ".", "--theme", theme]
    result = subprocess.run(args + (["--portrait"] if portrait else []), capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return os.path.join("res", "themes", THEMES[theme])


def same_picture(a, b):
    """Pixels that differ, and the largest difference of one channel."""
    import numpy
    difference = numpy.asarray(ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB")))
    return int(numpy.count_nonzero(difference.any(axis=2))), int(difference.max())


def live_boxes(theme_yaml):
    """Every area a widget draws live: (name, x1, y1, x2, y2)."""
    with open(theme_yaml, encoding="utf-8") as f:
        theme = yaml.safe_load(f)
    boxes = []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        if {"X", "Y", "WIDTH", "HEIGHT"} <= node.keys() and node.get("SHOW", True):
            boxes.append((path, node["X"], node["Y"], node["X"] + node["WIDTH"], node["Y"] + node["HEIGHT"]))
        for key, value in node.items():
            walk(value, f"{path}.{key}" if path else key)
    walk(theme["STATS"], "")
    custom = theme["STATS"].get("CUSTOM", {})
    radar = custom.get("Bc250Radar")
    if radar:
        cx, cy, r = radar["SCOPE"]
        boxes.append(("radar scope", cx - r - 1, cy - r - 1, cx + r + 2, cy + r + 2))
        boxes.append(("radar card", *radar["CARD"]))
        boxes.append(("radar list", *radar["LIST"]))
        xr, bl, w = radar["COUNT"]
        boxes.append(("radar count", xr - w, bl - 11, xr, bl + 3))
    horror = custom.get("Bc250Horror")
    if horror:
        x, y, w, h = horror["FEED"]
        boxes.append(("horror feed", x, y, x + w, y + h))
        mx, my, mw, mh = horror["MOTION"]
        boxes.append(("horror motion", mx, my + 14, mx + mw, my + mh))
    nixie = custom.get("Bc250Nixie")
    if nixie:
        for i, d in enumerate(nixie["DISPLAYS"]):
            boxes += [(f"nixie {d['SOURCE']} tube {j}", x, d["Y"], x + d["W"], d["Y"] + d["H"]) for j, x in enumerate(d["XS"])]
            if "BAR" in d:
                x, y, w, h = d["BAR"][:4]
                boxes.append((f"nixie {d['SOURCE']} bar", x, y, x + w, y + h))
            if "LAMP" in d:
                x, y, r = d["LAMP"]
                boxes.append((f"nixie {d['SOURCE']} lamp", x - r - 3, y - r - 3, x + r + 4, y + r + 4))
        boxes += [(f"nixie colon {i}", x - 4, y - 4, x + 5, y + 5) for i, (x, y) in enumerate(nixie["COLONS"])]
    width, height = (480, 320) if theme["display"]["DISPLAY_ORIENTATION"] == "landscape" else (320, 480)
    return boxes, width, height


def layout_problems(theme_yaml):
    boxes, width, height = live_boxes(theme_yaml)
    problems = [f"{name} is off the screen" for name, x1, y1, x2, y2 in boxes
                if x1 < 0 or y1 < 0 or x2 > width or y2 > height]
    for i, (a, ax1, ay1, ax2, ay2) in enumerate(boxes):
        for b, bx1, by1, bx2, by2 in boxes[i + 1:]:
            if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2 and not allowed(a, b):
                problems.append(f"{a} overlaps {b}")
    return problems


def allowed(a, b):
    """Overlaps that are by design."""
    pair = {a, b}
    # a temperature widget draws its value, chart and alert tag itself, in one go
    return any(all(n.startswith(widget) for n in pair) for widget in ("CUSTOM.Bc250CpuTemp", "CUSTOM.Bc250GpuTemp"))


def main(themes):
    ok = True
    for theme in themes:
        folder = generate(theme, portrait=False)
        committed = os.path.join(REPO, "res", "themes", THEMES[theme])
        for name in sorted(set(os.listdir(committed)) - set(GENERATED_ONLY)):
            if not os.path.isfile(os.path.join(folder, name)):
                ok &= report(False, f"{theme}: res/themes/{THEMES[theme]}/{name} is committed but no longer generated")
            elif name.endswith(".yaml"):
                with open(os.path.join(folder, name), encoding="utf-8") as f1, open(os.path.join(committed, name), encoding="utf-8") as f2:
                    ok &= report(f1.read() == f2.read(), f"{theme}: {name} matches the committed one")
            elif name.endswith(".png"):
                changed, worst = same_picture(os.path.join(folder, name), os.path.join(committed, name))
                # font rasterisers differ slightly between Pillow builds: a few levels of antialiasing are tolerated
                ok &= report(worst <= ANTIALIAS_LEVELS, f"{theme}: {name} matches the committed one"
                             + (f" ({changed} pixels differ, by up to {worst})" if changed else ""))
        for name in sorted(set(os.listdir(folder)) - set(os.listdir(committed))):
            ok &= report(False, f"{theme}: generates {name}, which isn't committed in res/themes/{THEMES[theme]}")
        for portrait in (False, True):
            folder = generate(theme, portrait)
            problems = layout_problems(os.path.join(folder, "theme.yaml"))
            ok &= report(not problems, f"{theme} {'portrait' if portrait else 'landscape'}: layout"
                         + ("" if not problems else ": " + "; ".join(problems[:6])))
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1:] or list(THEMES)) else 1)
