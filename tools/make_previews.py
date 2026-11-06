"""Regenerates what is committed under res/themes:   python tools/make_previews.py [--files-only] [theme ...]

- each theme's default files (theme.yaml and artwork, as make_theme.py makes them with its default options), which
  tests/check_generator.py compares against;
- the README previews: a dashboard screenshot and the boot animation as a GIF, landscape and portrait, recorded on
  the emulated 3.5" rev A link of the tests (so the GIFs play at the real screen's speed), on the tests' fake BC-250.
Same needs as tests/run.py."""
import argparse
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(REPO, "tests")
sys.path.insert(0, TESTS)
from common import THEMES  # noqa: E402
from run import prepare_app, test_env  # noqa: E402

PREVIEW_OPTIONS = ["--user", "rafale", "--host", "bazzite2"]  # the names the README previews have always shown
PREVIEWS = ("preview.png", "preview_portrait.png", "preview_encounter.png", "splash_preview.gif",
            "splash_preview_portrait.gif")


def horror_encounter(folder):
    """The README's strip for the horror theme: the feed as it gets closer (a screenshot at 23 m shows next to nothing)."""
    import yaml
    from PIL import Image
    with open(os.path.join(folder, "theme.yaml"), encoding="utf-8") as f:
        spec = yaml.safe_load(f)["STATS"]["CUSTOM"]["Bc250Horror"]
    x, y, w, h = spec["FEED"]
    room = Image.open(os.path.join(folder, "background.png")).convert("RGB").crop((x, y, x + w, y + h))
    sprite = Image.open(os.path.join(folder, "figure.png")).convert("RGBA")
    strip = Image.new("RGB", (3 * w + 16, h), (0, 0, 0))
    for n, stage in enumerate(spec["STAGES"][i] for i in (4, 6, 7)):
        _, fx, top, height, light = stage
        art = sprite.resize((max(2, height // 3), max(2, height)), Image.BILINEAR)
        r, g, b, a = art.split()
        art = Image.merge("RGBA", tuple(c.point(lambda v, k=light: int(v * k)) for c in (r, g, b)) + (a,))
        frame = room.copy()
        frame.paste(art, (fx - art.width // 2, top), art)
        strip.paste(frame, (n * (w + 8), 0))
    strip.save(os.path.join(folder, "preview_encounter.png"))


def check(app, env, script, *args):
    result = subprocess.run([sys.executable, os.path.join(TESTS, script), *args], cwd=app, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        print(result.stdout[-2000:] + result.stderr[-2000:])
        raise SystemExit(f"{script} {' '.join(args)} failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("themes", nargs="*", metavar="theme", help=f"some of: {', '.join(THEMES)} (default: all)")
    parser.add_argument("--files-only", action="store_true", help="only the default files, not the previews")
    parser.add_argument("--app", help="an existing turing-smart-screen-python checkout to use (it gets modified)")
    args = parser.parse_args()
    cache = os.path.join(TESTS, ".cache")
    app = os.path.abspath(args.app or os.path.join(cache, "turing-smart-screen-python"))
    prepare_app(app)
    env = test_env(cache)
    for theme in args.themes or list(THEMES):
        folder = THEMES[theme]
        committed = os.path.join(REPO, "res", "themes", folder)
        generated = os.path.join(app, "res", "themes", folder)
        subprocess.run([sys.executable, os.path.join(REPO, "make_theme.py"), "--app", app, "--theme", theme],
                       env=env, check=True, capture_output=True)
        os.makedirs(committed, exist_ok=True)
        for name in os.listdir(committed):  # files the generator no longer makes go away
            if name not in PREVIEWS and not os.path.exists(os.path.join(generated, name)):
                os.remove(os.path.join(committed, name))
        for name in os.listdir(generated):
            shutil.copy(os.path.join(generated, name), committed)
        print(f"{folder}: default files", flush=True)
        if args.files_only:
            continue
        for portrait, suffix in ((False, ""), (True, "_portrait")):
            orientation = ["--portrait"] if portrait else []
            check(app, env, "check_boot.py", theme, *orientation,
                  "--gif", os.path.join(committed, f"splash_preview{suffix}.gif"), "--", *PREVIEW_OPTIONS)
            check(app, env, "check_app.py", theme, *orientation,
                  "--screenshot", os.path.join(committed, f"preview{suffix}.png"), "--", *PREVIEW_OPTIONS)
            print(f"{folder}: previews{' (portrait)' if portrait else ''}", flush=True)
        if theme == "horror":
            horror_encounter(committed)


if __name__ == "__main__":
    main()
