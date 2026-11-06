"""Shared by the checks in this folder (each one runs in a process of its own, from the app's folder).

- THEMES: every theme and its folder
- fake_bc250(): a fake BC-250 for the sensors (sysfs, /proc, Steam, MangoHud), playing Hades II
- LinkLcd: a screen that charges every bitmap the time a 3.5" rev A takes to receive it (measured: 160 KB/s and
  about 1.5 ms per command), and remembers what it shows
- emulate_rev_a(): the same, for the whole app: bitmaps go through the app's queue, one after the other
"""
import os
import random
import shutil
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
THEMES = {"phosphor": "BC250-Phosphor", "gameboy": "BC250-GameBoy", "retrowave": "BC250-Retrowave",
          "videotex": "BC250-Videotex", "mission": "BC250-Mission", "minecraft": "BC250-Minecraft",
          "nixie": "BC250-Nixie", "radar": "BC250-Radar", "halloween": "BC250-Halloween",
          "christmas": "BC250-Christmas"}
LINK_BYTES_PER_S = 160_000
COMMAND_S = 0.0015


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def fake_bc250(root):
    """A BC-250 for the sensors: amdgpu sysfs, a Steam client running Hades II, a MangoHud log, and the radar's
    saved data. Returns the environment variables pointing the sensors at it."""
    if os.path.isdir(root):
        shutil.rmtree(root)
    gpu = os.path.join(root, "sys", "class", "drm", "card1", "device")
    for name, value in (("vendor", "0x1002\n"), ("uevent", "DRIVER=amdgpu\nPCI_SLOT_NAME=0000:01:00.0\n"),
                        ("mem_info_vram_used", "536870912\n"), ("mem_info_gtt_used", "3221225472\n"),
                        ("pp_dpm_sclk", "0: 1000Mhz \n1: 1500Mhz \n2: 2000Mhz *\n"),
                        ("hwmon/hwmon3/temp1_input", "71000\n"), ("hwmon/hwmon3/freq1_input", "1873000000\n"),
                        ("hwmon/hwmon3/power1_average", "148000000\n")):
        write(os.path.join(gpu, name), value)
    proc = os.path.join(root, "proc")
    write(os.path.join(proc, "uptime"), "6400.00 30000.00\n")
    for pid, argv, start in ((1, ["/usr/bin/steam", "-gamepadui"], 100),
                             (4242, ["/home/deck/.local/share/Steam/ubuntu12_32/reaper", "SteamLaunch",
                                     "AppId=1145350", "--", "/home/deck/Hades2.exe"], 100000)):
        write(os.path.join(proc, str(pid), "cmdline"), "\0".join(argv) + "\0")
        write(os.path.join(proc, str(pid), "stat"),
              f"{pid} ({os.path.basename(argv[0])}) S 1 {pid} {pid} 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 {start} 0 0\n")
    steam = os.path.join(root, "steam")
    write(os.path.join(steam, "steamapps", "appmanifest_1145350.acf"),
          '"AppState"\n{\n\t"appid"\t\t"1145350"\n\t"name"\t\t"Hades II"\n\t"StateFlags"\t\t"4"\n}\n')
    write(os.path.join(steam, "logs", "content_log.txt"), "")
    os.makedirs(os.path.join(root, "mangologs"), exist_ok=True)
    # the radar's maps (a few airports and terrain tiles around Paris CDG, the theme's default centre), fresh in a
    # cache folder of their own: the generator re-downloads anything older than 90 days
    cache = os.path.join(root, "cache", "bc250-themes")
    shutil.copytree(os.path.join(FIXTURES, "radar-cache"), cache)
    now = time.time()
    for folder, _, files in os.walk(cache):
        for name in files:
            os.utime(os.path.join(folder, name), (now, now))
    return {"BC250_SYSFS_ROOT": root, "BC250_PROC_ROOT": proc, "BC250_MANGOHUD_DIR": os.path.join(root, "mangologs"),
            "BC250_RADAR_FIXTURE": os.path.join(FIXTURES, "radar_adsb.json"),
            "BC250_RADAR_ROUTES": os.path.join(FIXTURES, "radar_routes.json"),
            "XDG_CACHE_HOME": os.path.join(root, "cache"), "PYSTRAY_BACKEND": "dummy", "BC250_FAKE_ROOT": root}


def patch_sensors(b):
    """In a check's process: the sensors' Steam folder and temperatures from the fake BC-250."""
    root = os.environ["BC250_FAKE_ROOT"]
    steam = os.path.join(root, "steam")
    b._steam_roots_cache.fn = lambda: [steam]
    b._steam_libraries_cache.fn = lambda: [steam]
    b.Bc250CpuTemp.read = lambda self: 64 + random.uniform(-1, 1)
    b.Bc250GpuTemp.read = lambda self: 58 + random.uniform(-1, 1)
    nanoseconds = [0]

    def gpu_sample():  # a game keeping the GPU about 75% busy
        nanoseconds[0] += int(random.uniform(0.6, 0.9) * 1e9)
        return {"7": nanoseconds[0]}
    b.Bc250GpuLoad._sample = staticmethod(gpu_sample)

    log = os.path.join(root, "mangologs", "Hades2.exe_2026-10-09_17-00-00.csv")
    write(log, "os,cpu,gpu,ram,kernel,driver,cpuscheduler\nLinux,BC-250,AMD,16G,6.11,mesa,\n"
               "fps,frametime,cpu_load,cpu_power,gpu_load,cpu_temp,gpu_temp,gpu_core_clock,gpu_mem_clock,"
               "gpu_vram_used,gpu_power,ram_used,swap_used,process_rss,cpu_mhz,elapsed\n")

    def mangohud():
        while True:
            with open(log, "a") as f:
                f.write(f"{random.uniform(108, 118):.1f},8.7,40,0,80,64,58,1873,1750,3.5,0,7.9,0,2.1,3400,"
                        f"{int(time.time() * 1e9)}\n")
            time.sleep(1)
    threading.Thread(target=mangohud, name="fake MangoHud", daemon=True).start()


class Debt:
    """Sleeps off link time in chunks: Windows sleeps in ~15 ms steps, which would inflate small transfers."""

    def __init__(self):
        self.owed = 0.0

    def pay(self, seconds):
        self.owed += seconds
        if self.owed >= 0.03:
            start = time.perf_counter()
            time.sleep(self.owed)
            self.owed -= time.perf_counter() - start


class LinkLcd:
    """A screen for the boot animation alone: each bitmap costs its transfer time, the picture is kept, and every
    update is recorded (time, brightness-applied picture) for previews."""

    def __init__(self, size, brightness, record=False):
        from PIL import Image
        self.canvas, self.target, self.level = Image.new("RGB", size), brightness, brightness
        self.t0, self.frames, self.record = time.monotonic(), [], record
        self.bytes, self.commands, self.debt = 0, 0, Debt()

    def snap(self):
        if self.record:
            from PIL import ImageEnhance
            self.frames.append((time.monotonic() - self.t0,
                                ImageEnhance.Brightness(self.canvas).enhance(self.level / self.target)))

    def DisplayPILImage(self, image, x=0, y=0, *args, **kwargs):
        size = image.width * image.height * 2
        self.bytes += size
        self.commands += 1
        self.debt.pay(size / LINK_BYTES_PER_S + COMMAND_S)
        self.canvas.paste(image, (x, y))
        self.snap()

    def SetBrightness(self, level):
        self.debt.pay(COMMAND_S)
        self.commands += 1
        self.level = level
        self.snap()


class RevA:
    """The whole app on an emulated rev A: every bitmap goes through the app's queue and its queue thread pays the
    transfer. Keeps two pictures: what reached the screen, and what was meant to be on it (every image drawn,
    whole, at the moment it was asked for), to prove that sending only changed pixels never leaves anything wrong."""

    def __init__(self):
        self.log = []  # (time the transfer ended, x, y, w, h, thread that asked)
        self.t0 = time.monotonic()
        self.lock = threading.RLock()
        self.screen = self.intended = None
        self.pending = 0
        self.debt = Debt()

    def install(self):
        import library.lcd.lcd_simulated as simulated
        import library.scheduler as scheduler
        rev_a = self

        def display(lcd, image, x=0, y=0, image_width=0, image_height=0):
            from PIL import Image
            from library import config
            image = image.convert("RGB").copy()
            who = threading.current_thread().name
            with rev_a.lock:
                if rev_a.screen is None:
                    rev_a.screen = Image.new("RGB", (lcd.get_width(), lcd.get_height()))
                    rev_a.intended = rev_a.screen.copy()
                rev_a.intended.paste(image, (x, y))  # (a piece of an image already pasted changes nothing)
                rev_a.pending += 1

                def transfer():
                    rev_a.debt.pay(image.width * image.height * 2 / LINK_BYTES_PER_S + COMMAND_S)
                    with rev_a.lock:
                        rev_a.screen.paste(image, (x, y))
                        rev_a.pending -= 1
                        rev_a.log.append((time.monotonic() - rev_a.t0, x, y, image.width, image.height, who))
                with lcd.update_queue_mutex:
                    config.update_queue.put((transfer, []))

        simulated.LcdSimulated.DisplayPILImage = display

        def queue_handler():  # like the app's queue thread on Linux: items back to back
            from library import config

            def run():
                while True:
                    function, args = config.update_queue.get()
                    function(*args)
            threading.Thread(target=run, name="Queue_Handler", daemon=True).start()
        scheduler.QueueHandler = queue_handler

    def watch_screen(self, b):
        """The changed-pixels sender: the whole image a caller wants goes into the intended picture, atomically with
        the pieces it sends."""
        original = b._Screen.DisplayPILImage
        rev_a = self

        def display(screen, image, x=0, y=0, *args, **kwargs):
            with rev_a.lock:
                if rev_a.intended is not None:
                    rev_a.intended.paste(image.convert("RGB"), (x, y))
                return original(screen, image, x, y, *args, **kwargs)
        b._Screen.DisplayPILImage = display

    def settled_difference(self, timeout=10):
        """Pixels that differ between the screen and what was meant, once nothing is in flight."""
        import numpy
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.pending == 0 and self.screen is not None:
                    return int((numpy.asarray(self.screen) != numpy.asarray(self.intended)).any(axis=2).sum())
            time.sleep(0.01)
        raise TimeoutError("the screen never settled")


def report(ok, message):
    print(("PASS " if ok else "FAIL ") + message, flush=True)
    return ok


if not hasattr(os, "sysconf"):  # the app's sensors call it; Windows has none
    os.sysconf = lambda name: 100
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
