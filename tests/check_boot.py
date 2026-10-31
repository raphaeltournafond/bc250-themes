"""A theme's boot animation on an emulated 3.5" rev A link (160 KB/s, ~1.5 ms a command):
- what reaches the screen is pixel for pixel what the animation meant to show;
- the handoff then leaves exactly the dashboard's background (the radar keeps its scope as the boot left it);
- it lasts at most --limit seconds.
Usage (from the app's folder): python check_boot.py THEME [--portrait] [--limit S] [--gif OUT] [-- generator options]"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import REPO, THEMES, LinkLcd, patch_sensors, report  # noqa: E402

# the self-test lines a BC-250 would show (the machine running the check has other hardware)
BC250_LINES = {"CPU": ("AMD BC-250 6C/12T @ 3.49 GHz", "OK"), "MEMORY": ("14.6 GiB system, GDDR6 shared", "OK"),
               "NETWORK": ("enp4s0 192.168.1.42", "OK"), "STORAGE": ("Steam library 724 GB free (27% used)", "OK")}


def select_theme(theme, portrait, extra):
    args = [sys.executable, os.path.join(REPO, "make_theme.py"), "--app", ".", "--theme", theme]
    subprocess.run(args + (["--portrait"] if portrait else []) + extra, check=True, capture_output=True)
    with open("config.yaml", encoding="utf-8") as f:
        lines = f.read().splitlines()
    lines = [f"  THEME: {THEMES[theme]}" if line.startswith("  THEME:") else line for line in lines]
    with open("config.yaml", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def save_gif(frames, path):
    """Real-time GIF of the recorded updates (at most one frame per 50 ms)."""
    kept, next_t = [], 0.0
    for i, (t, frame) in enumerate(frames):
        if t >= next_t or i == len(frames) - 1:
            kept.append((t, frame))
            next_t = t + 0.05
    durations = [max(20, round((kept[i + 1][0] - kept[i][0]) * 1000)) for i in range(len(kept) - 1)] + [2000]
    # one palette for all frames, from a few of them across the boot (the last one alone, the dashboard, can lack
    # the boot's own colours)
    from PIL import Image
    samples = [kept[round(k * (len(kept) - 1))][1] for k in (0.3, 0.6, 0.85, 1.0)]
    montage = Image.new("RGB", (samples[0].width, samples[0].height * len(samples)))
    for i, frame in enumerate(samples):
        montage.paste(frame, (0, i * frame.height))
    palette = montage.quantize(colors=256)
    frames = [frame.quantize(palette=palette, dither=0) for _, frame in kept]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("theme", choices=sorted(THEMES))
    parser.add_argument("--portrait", action="store_true")
    parser.add_argument("--limit", type=float, default=12.0, help="longest acceptable boot, in seconds")
    parser.add_argument("--gif", help="also save the boot as a GIF (README previews)")
    argv = sys.argv[1:]  # what follows "--" goes to make_theme.py
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    args.extra = extra
    select_theme(args.theme, args.portrait, args.extra)

    import numpy
    from PIL import Image
    from library import config
    import library.sensors.sensors_bc250 as b
    patch_sensors(b)
    real_lines = b._Splash.post_lines
    b._Splash.post_lines = staticmethod(lambda spec: [
        (label,) + BC250_LINES.get(label, (value, status)) for label, value, status in real_lines(spec)])
    b.Bc250Radar.as_numeric = lambda self: None  # the handoff would start the radar's own drawing thread

    background = config.THEME_DATA["static_images"]["BACKGROUND"]
    size = (background["WIDTH"], background["HEIGHT"])
    lcd = LinkLcd(size, config.CONFIG_DATA["display"].get("BRIGHTNESS", 20), record=bool(args.gif))
    intended = Image.new("RGB", size)
    original = b._Screen.DisplayPILImage

    def watched(screen, image, x=0, y=0, *a, **k):
        intended.paste(image.convert("RGB"), (x, y))
        return original(screen, image, x, y, *a, **k)
    b._Screen.DisplayPILImage = watched

    start = time.monotonic()
    screen = b._Splash.play(lcd)
    seconds = time.monotonic() - start
    name = f"{args.theme} {'portrait' if args.portrait else 'landscape'}"
    ok = report(screen is not None, f"{name}: the boot ran")
    if screen is None:
        return False
    differ = int((numpy.asarray(lcd.canvas) != numpy.asarray(intended)).any(axis=2).sum())
    ok &= report(differ == 0, f"{name}: boot pixel-exact on the screen" + (f" ({differ} pixels differ)" if differ else ""))
    ok &= report(seconds <= args.limit, f"{name}: boot took {seconds:.1f} s at 160 KB/s (limit {args.limit:.0f} s), "
                                        f"{lcd.bytes / 1000:.0f} KB in {lcd.commands} commands")

    # the handoff: from the boot's last picture to the dashboard's background, without a full repaint
    handed = b._handoff(screen)
    ok &= report(handed, f"{name}: handoff to the dashboard without the app's full repaint")
    target = numpy.asarray(b._Draw.background(background.get("PATH", "background.png"))).copy()
    shown = numpy.asarray(lcd.canvas).copy()
    radar = b._Draw.theme("Bc250Radar")
    if radar.get("SCOPE"):  # the scope is kept as the boot left it: the sweep takes over from there
        cx, cy, r = (int(v) for v in radar["SCOPE"])
        shown[cy - r - 1:cy + r + 2, cx - r - 1:cx + r + 2] = target[cy - r - 1:cy + r + 2, cx - r - 1:cx + r + 2]
    differ = int((shown != target).any(axis=2).sum())
    ok &= report(differ == 0, f"{name}: after the handoff the screen shows the dashboard's background"
                 + (f" ({differ} pixels differ)" if differ else ""))
    if args.gif:
        save_gif(lcd.frames, args.gif)
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
