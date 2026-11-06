"""The whole app with a theme, on an emulated 3.5" rev A (simulated display; bitmaps queued and paid for at 160 KB/s
and ~1.5 ms a command), on a fake BC-250 playing Hades II:
- after the boot and some dashboard time, the screen shows pixel for pixel what every widget meant to draw;
- the dashboard takes over from the boot without the app repainting the whole screen;
- radar: the sweep starts as the boot ends and never stalls.
Usage (from the app's folder): python check_app.py THEME [--portrait] [--seconds S] [--screenshot OUT] [-- options]"""
import argparse
import os
import runpy
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import COMMAND_S, LINK_BYTES_PER_S, RevA, patch_sensors, report  # noqa: E402
from check_boot import BC250_LINES, select_theme  # noqa: E402
from common import THEMES  # noqa: E402

OTHERS_MS_PER_S = 130  # today ~75; the old once-a-second stall (status line resent whole) was ~190


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("theme", choices=sorted(THEMES))
    parser.add_argument("--portrait", action="store_true")
    parser.add_argument("--seconds", type=float, default=24, help="how long to run (boot included)")
    parser.add_argument("--screenshot", help="also save the final screen (README previews)")
    argv = sys.argv[1:]  # what follows "--" goes to make_theme.py
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    args.extra = extra
    if args.theme == "seismograph":  # some of the page written in a few seconds, not twenty minutes
        os.environ["BC250_SEISMO_SPEED"] = "70" if args.screenshot else "300"
    if args.theme == "horror" and not args.screenshot:  # the whole encounter in a few seconds, not ten minutes
        os.environ["BC250_HORROR_FAST"] = "1"
        args.seconds = max(args.seconds, 40)
    select_theme(args.theme, args.portrait, args.extra)
    name = f"{args.theme} {'portrait' if args.portrait else 'landscape'}"

    rev_a = RevA()
    rev_a.install()
    import library.lcd.lcd_simulated as simulated  # the app's repaint loads the background from its file
    repaints = [0]
    from_file = simulated.LcdSimulated.DisplayBitmap

    def counted(self, *args, **kwargs):
        repaints[0] += 1
        return from_file(self, *args, **kwargs)
    simulated.LcdSimulated.DisplayBitmap = counted
    import library.sensors.sensors_bc250 as b
    patch_sensors(b)
    rev_a.watch_screen(b)
    real_lines = b._Splash.post_lines
    b._Splash.post_lines = staticmethod(lambda spec: [
        (label,) + BC250_LINES.get(label, (value, status)) for label, value, status in real_lines(spec)])

    def verdict():
        time.sleep(args.seconds)
        ok = True
        try:
            differ = rev_a.settled_difference()
            ok &= report(differ == 0, f"{name}: the screen shows what every widget meant to draw"
                         + (f" ({differ} pixels differ)" if differ else ""))
            ok &= report(repaints[0] == 0, f"{name}: the dashboard took over from the boot without the app's full "
                                           f"repaint ({repaints[0]} repaints)")
            boot = [t for t, x, y, w, h, who in rev_a.log if who == "MainThread"]
            sweep = [t for t, x, y, w, h, who in rev_a.log if who == "BC250 radar"]
            if b._Draw.theme("Bc250Radar"):
                handoff_gap = (sweep[0] - boot[-1]) if sweep and boot else float("inf")
                ok &= report(handoff_gap < 0.5, f"{name}: the sweep starts as the boot ends ({handoff_gap:.2f} s later)")
                starts = [t for i, t in enumerate(sweep) if i == 0 or t - sweep[i - 1] > 0.04]
                gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
                worst = max(gaps) if gaps else float("inf")
                seconds = max(1e-3, starts[-1] - starts[0])
                per_minute = 60 * sum(1 for gap in gaps if gap > 0.2) / seconds
                # what holds the sweep back is the link time the other widgets take each second: measured on the
                # emulated link (bytes and commands), it doesn't depend on how fast the machine running the check is
                others = {}
                for t, x, y, w, h, who in rev_a.log:
                    if who != "BC250 radar" and t > boot[-1] + 3:
                        others[int(t)] = others.get(int(t), 0) + w * h * 2 / LINK_BYTES_PER_S + COMMAND_S
                # averaged over the run: a slow machine can bunch two seconds of updates into one
                average = 1000 * sum(others.values()) / max(1, max(others, default=0) - min(others, default=0) + 1)
                ok &= report(average <= OTHERS_MS_PER_S, f"{name}: other widgets take {average:.0f} ms of link a second "
                                                         f"(limit {OTHERS_MS_PER_S}): the sweep keeps its pace")
                # wall-clock smoothness depends on the machine too: shown, and only a gross stall fails
                ok &= report(worst < 1.0, f"{name}: sweep {len(starts) / seconds:.1f} frames/s, {per_minute:.0f} pauses "
                                          f"over 200 ms a minute, longest {worst * 1000:.0f} ms")
            if args.theme == "seismograph" and not args.screenshot:
                ok &= report(b._Seismo.played >= 1 and b._Seismo.rows_started >= 3 and len(b._QuakeFeed.quakes) >= 5,
                             f"{name}: the pen wrote {b._Seismo.rows_started} lines and played {b._Seismo.played} quake, "
                             f"{len(b._QuakeFeed.quakes)} on the map")
            if args.theme == "horror" and not args.screenshot:
                gentle = "--no-jumpscare" in args.extra
                ok &= report(b._Horror.moves >= 3 and b._Horror.whispers >= 1 and (b._Horror.scares == 0) == gentle,
                             f"{name}: the encounter ran ({b._Horror.moves} blackouts, {b._Horror.scares} scare, "
                             f"{b._Horror.whispers} whispers)" + (" with --no-jumpscare" if gentle else ""))
            if args.screenshot:
                with rev_a.lock:
                    rev_a.screen.save(args.screenshot)
        except Exception as e:
            ok = report(False, f"{name}: {e!r}")
        sys.stdout.flush()
        os._exit(0 if ok else 1)

    threading.Thread(target=verdict, name="verdict", daemon=True).start()
    sys.argv = ["main.py"]
    runpy.run_path("main.py", run_name="__main__")


if __name__ == "__main__":
    main()
