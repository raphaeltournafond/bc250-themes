"""Runs every check of the themes:   python tests/run.py [--quick] [--only NAME[,NAME]] [theme ...]

- generator: the committed theme files are what make_theme.py generates; layouts have no overlaps
- states:    game detection, sessions, downloads and the status line, on a fake /proc and Steam folder
- boot:      each boot animation on an emulated 3.5" rev A link: pixel-exact, quick enough, clean handoff
- app:       the whole app per theme on that link: the screen is right, nothing stalls

Needs git and a Python with the app's libraries (pip install -r tests/requirements.txt). The app is fetched into
tests/.cache (release 3.10.0, the one setup.sh installs) unless --app points at a checkout; it runs on the app's
simulated display, never a real screen. --quick: landscape only, and the full-app check for the radar only."""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
APP_URL, APP_RELEASE = "https://github.com/mathoudebine/turing-smart-screen-python", "3.10.0"
sys.path.insert(0, HERE)
from common import THEMES, fake_bc250  # noqa: E402


def prepare_app(path):
    """A checkout of the app with this repo's sensors, on its simulated display and stub sensors."""
    if not os.path.isfile(os.path.join(path, "main.py")):
        print(f"Fetching turing-smart-screen-python {APP_RELEASE} into {path}", flush=True)
        subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", APP_RELEASE, APP_URL, path], check=True)
    shutil.copy(os.path.join(REPO, "library", "sensors", "sensors_bc250.py"), os.path.join(path, "library", "sensors"))
    shutil.copy(os.path.join(REPO, "bc250_check.py"), path)
    custom = os.path.join(path, "library", "sensors", "sensors_custom.py")
    with open(custom, encoding="utf-8") as f:
        text = f.read()
    if "sensors_bc250" not in text:
        with open(custom, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n\n# BC250 theme sensors\nfrom library.sensors.sensors_bc250 import *  # noqa: E402,F401,F403\n")
    config = os.path.join(path, "config.yaml")
    with open(config, encoding="utf-8") as f:
        text = f.read()
    for key, value in (("REVISION", "SIMU"), ("HW_SENSORS", "STUB"), ("BRIGHTNESS", "20")):
        text = re.sub(rf"^(\s+{key}:).*$", rf"\1 {value}", text, count=1, flags=re.M)
    with open(config, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def test_env(cache):
    """The environment of every check: the fake BC-250 (rebuilt each run)."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    env.update(fake_bc250(os.path.join(cache, "fake-bc250")))
    return env


def run(app, env, script, *args):
    """One check in its own process: its PASS/FAIL lines are shown; a crash shows its last lines."""
    command = [sys.executable, os.path.join(HERE, script), *args]
    started = time.monotonic()
    result = subprocess.run(command, cwd=app, env=env, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=600)
    lines = result.stdout.splitlines()
    verdicts = [line for line in lines if line.startswith(("PASS ", "FAIL "))]
    for line in verdicts:
        print("  " + line, flush=True)
    failed = result.returncode != 0 or any(line.startswith("FAIL ") for line in verdicts)
    if result.returncode != 0 and not any(line.startswith("FAIL ") for line in verdicts):
        print(f"  FAIL {script} {' '.join(args)} stopped (exit {result.returncode}):", flush=True)
        for line in (lines + result.stderr.splitlines())[-15:]:
            print("    " + line, flush=True)
    print(f"  ({script} {' '.join(args)}: {time.monotonic() - started:.0f} s)", flush=True)
    return not failed, len(verdicts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("themes", nargs="*", metavar="theme", help=f"some of: {', '.join(THEMES)} (default: all)")
    parser.add_argument("--app", help="an existing turing-smart-screen-python checkout to use (it gets modified)")
    parser.add_argument("--quick", action="store_true", help="landscape only, full-app check for the radar only")
    parser.add_argument("--only", help="comma-separated: generator,states,boot,app")
    args = parser.parse_args()
    unknown = set(args.themes) - set(THEMES)
    if unknown:
        parser.error(f"unknown theme(s): {', '.join(sorted(unknown))}")
    themes = args.themes or list(THEMES)
    only = set((args.only or "generator,states,boot,app").split(","))
    cache = os.path.join(HERE, ".cache")
    app = os.path.abspath(args.app or os.path.join(cache, "turing-smart-screen-python"))
    prepare_app(app)
    env = test_env(cache)

    results = []
    if "generator" in only:
        print("Generator", flush=True)
        results.append(run(app, env, "check_generator.py", *themes))
    if "states" in only:
        print("States", flush=True)
        results.append(run(app, env, "check_states.py"))
    if "boot" in only:
        print("Boot animations", flush=True)
        for theme in themes:
            for portrait in ([False] if args.quick else [False, True]):
                results.append(run(app, env, "check_boot.py", theme, *(["--portrait"] if portrait else [])))
    if "app" in only:
        print("Whole app", flush=True)
        for theme in themes:
            if args.quick and theme != "radar":
                continue
            results.append(run(app, env, "check_app.py", theme))
        for theme in ("radar", "horror"):  # layouts of their own, with a thread drawing on them
            if theme in themes and not args.quick:
                results.append(run(app, env, "check_app.py", theme, "--portrait"))
        if "horror" in themes and not args.quick:
            results.append(run(app, env, "check_app.py", "horror", "--", "--no-jumpscare"))

    passed = sum(1 for ok, _ in results if ok)
    checks = sum(n for _, n in results)
    print(f"\n{'ALL PASSED' if passed == len(results) else 'FAILED'}: {passed}/{len(results)} runs, {checks} checks")
    return passed == len(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
