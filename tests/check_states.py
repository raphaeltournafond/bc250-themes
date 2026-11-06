"""Game detection, play sessions, Steam downloads and the status line's states, against a fake /proc and Steam
folder driven step by step (the clock is faked too). Usage (from the app's folder): python check_states.py"""
import datetime
import math
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402,F401  (the app's folder on the path, os.sysconf on Windows)

tmp = tempfile.mkdtemp()
proc = os.path.join(tmp, "proc")
steam = os.path.join(tmp, "steam")
os.makedirs(proc)
os.makedirs(os.path.join(steam, "steamapps"))
os.makedirs(os.path.join(steam, "logs"))
os.environ["BC250_PROC_ROOT"] = proc
import library.sensors.sensors_bc250 as b

b.PROC_ROOT = proc
b._steam_roots_cache.fn = lambda: [steam]
b._steam_libraries_cache.fn = lambda: [steam]
clock = [10_000.0]
b.time.monotonic = lambda: clock[0]
uptime = [100_000.0]


def tick(seconds=1.0):
    clock[0] += seconds
    uptime[0] += seconds
    with open(os.path.join(proc, "uptime"), "w") as f:
        f.write(f"{uptime[0]:.2f} 0.00\n")


tick(0)


def spawn(pid, argv, age_s=10):
    d = os.path.join(proc, str(pid))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "cmdline"), "wb") as f:
        f.write(b"\0".join(a.encode() for a in argv) + b"\0")
    start_ticks = int((uptime[0] - age_s) * 100)
    with open(os.path.join(d, "stat"), "w") as f:
        f.write(f"{pid} ({os.path.basename(argv[0])}) S 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 {start_ticks} 0 0\n")


def kill(pid):
    shutil.rmtree(os.path.join(proc, str(pid)), ignore_errors=True)


def manifest(app_id, name, flags=4, to_dl=0, dl=0, to_stage=0, staged=0):
    with open(os.path.join(steam, "steamapps", f"appmanifest_{app_id}.acf"), "w") as f:
        f.write(f'"AppState"\n{{\n\t"appid"\t\t"{app_id}"\n\t"name"\t\t"{name}"\n\t"StateFlags"\t\t"{flags}"\n'
                f'\t"BytesToDownload"\t\t"{to_dl}"\n\t"BytesDownloaded"\t\t"{dl}"\n'
                f'\t"BytesToStage"\t\t"{to_stage}"\n\t"BytesStaged"\t\t"{staged}"\n}}\n')
    b._Downloads._manifests.stamp = -1e9  # force re-read


def log(*lines):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(steam, "logs", "content_log.txt"), "a") as f:
        for line in lines:
            f.write(f"[{ts}] {line}\n")


def fresh():
    b._Procs._cache.stamp = -1e9
    b._Steam._game_cache.stamp = -1e9


REAPER = ["/home/deck/.local/share/Steam/ubuntu12_32/reaper", "SteamLaunch"]
PROTON = ["--", "/home/deck/.local/share/Steam/steamapps/common/Proton - Experimental/proton", "waitforexitandrun"]

# ---------------------------------------------------------------- game detection
manifest("1145350", "Hades II")
manifest("2358720", "Black Myth: Wukong")
spawn(1, ["/usr/bin/steam", "-gamepadui"], 5000)
fresh(); assert b._Steam.running_game() is None, "no game"

spawn(10, REAPER + ["AppId=2358720"] + PROTON + ["/x/iscriptevaluator.exe", "--get-current-step", "2358720"])
spawn(11, REAPER + ["AppId=228980"] + PROTON + ["/x/redist/vc_redist.x64.exe"])
spawn(12, ["grep", "SteamLaunch"])
spawn(13, ["bash", "-c", "reaper SteamLaunch AppId=1145350 -- game"])
fresh(); assert b._Steam.running_game() is None, "install script / redist / grep / bash -c are not games"

spawn(20, REAPER + ["AppId=1145350"] + PROTON + ["/games/Hades II/Ship/Hades2.exe"], age_s=400)
fresh(); assert b._Steam.running_game() == ("1145350", "20"), b._Steam.running_game()
spawn(21, REAPER + ["AppId=2358720"] + PROTON + ["/games/wukong/b1.exe"], age_s=30)
fresh(); assert b._Steam.running_game()[0] == "2358720", "newest launch wins"
kill(21)
spawn(22, REAPER + ["AppId=3000000123"] + ["--", "/opt/emu/emulator"], age_s=5)
fresh(); assert b._Steam.running_game()[0] == "3000000123" and b._Steam.app_name("3000000123") == "non-Steam game"
kill(22)
print("PASS states: game detection", flush=True)

# ---------------------------------------------------------------- sessions
S = b._Session
S.last = None
kill(20); kill(10); kill(11)
spawn(30, REAPER + ["AppId=2358720"] + PROTON + ["/games/wukong/b1.exe"], age_s=8)
fresh(); S.update(b._Steam.running_game())
kill(30); fresh(); S.update(b._Steam.running_game())
assert S.last is None, "an 8 s launch is not a session"

spawn(31, REAPER + ["AppId=1145350"] + PROTON + ["/games/Hades2.exe"], age_s=5400)
b.Bc250CpuTemp.value, b.Bc250GpuTemp.value = 77.0, 64.0
fresh(); S.update(b._Steam.running_game())
kill(31)
spawn(32, REAPER + ["AppId=2358720"] + PROTON + ["/games/wukong/b1.exe"], age_s=1)
fresh(); S.update(b._Steam.running_game())
assert S.last and S.last["name"] == "Hades II" and S.last["seconds"] >= 5400 and S.last["peak_cpu"] == 77.0, S.last
assert S.app_id == "2358720", "switching straight to another game records the first one"
kill(32); fresh(); S.update(b._Steam.running_game())
assert S.last["name"] == "Hades II", "the 1 s Wukong launch did not overwrite it"
print("PASS states: sessions", flush=True)

# ---------------------------------------------------------------- downloads
rx = [5_000_000_000]
b._network_rx = lambda: rx[0]
D = b._Downloads
manifest("2358720", "Black Myth: Wukong", flags=1026, to_dl=100_000_000_000, dl=20_000_000_000)
log("AppID 2358720 state changed : Update Required,Update Queued,",
    "AppID 2358720 update started : download 0/100000000000, store 0/0, reuse 0/0, staged 0/0",
    "AppID 2358720 state changed : Update Required,Update Running,Update Started,",
    "AppID 2358720 update changed : Running Update,Downloading,Staging,")
first = D.poll()
assert first and first["phase"] == "downloading" and abs(first["fraction"] - 0.20) < 0.001, first
fractions = []
for _ in range(5):
    tick(1); rx[0] += 50_000_000  # 50 MB/s on the wire, manifest not rewritten
    fractions.append(D.poll()["fraction"])
assert all(x < y for x, y in zip(fractions, fractions[1:])), f"progress moves every second: {fractions}"
assert abs(fractions[-1] - 0.2025) < 0.001, fractions[-1]
eta = D.poll()["eta"]
assert eta and 1400 < eta < 1700, eta  # 79.75 GB left at ~50 MB/s
manifest("2358720", "Black Myth: Wukong", flags=1026, to_dl=100_000_000_000, dl=30_000_000_000)
tick(4)
assert abs(D.poll()["fraction"] - 0.30) < 0.001, "resyncs on Steam's own counter"

log("AppID 2358720 update changed : Running Update,Staging,Committing,")
manifest("2358720", "Black Myth: Wukong", flags=1026, to_dl=100_000_000_000, dl=100_000_000_000,
         to_stage=50_000_000_000, staged=40_000_000_000)
tick(4)
r = D.poll(); assert r["phase"] == "installing" and abs(r["fraction"] - 0.8) < 0.001, r

log("AppID 2358720 state changed : Update Required,Update Paused,")
tick(4); assert D.poll() is None, "paused"
log("AppID 2358720 state changed : Update Required,Update Running,Update Started,",
    "AppID 2358720 update changed : Running Update,Verifying,")
tick(4); r = D.poll(); assert r["phase"] == "verifying" and r["fraction"] is None, r
log("AppID 2358720 finished update (took 449 seconds)", "AppID 2358720 state changed : Fully Installed,")
manifest("2358720", "Black Myth: Wukong", flags=4)
tick(4); assert D.poll() is None, "finished"

# fallback without a log line for the app: StateFlags
manifest("730", "Counter-Strike 2", flags=1026, to_dl=1_000_000_000, dl=500_000_000)
tick(4); r = D.poll(); assert r and r["app_id"] == "730", r
manifest("730", "Counter-Strike 2", flags=1538, to_dl=1_000_000_000, dl=500_000_000)  # 0x200 paused
tick(4); assert D.poll() is None, "flags say paused"
manifest("730", "Counter-Strike 2", flags=1026, to_dl=1_000_000_000, dl=500_000_000)
kill(1); fresh()
tick(4); assert D.poll() is None, "no download shown while the Steam client is not running"
spawn(1, ["/usr/bin/steam", "-gamepadui"], 5000); fresh()
manifest("730", "Counter-Strike 2", flags=4)
print("PASS states: downloads", flush=True)

# ---------------------------------------------------------------- prompt states and resilience
P = b.Bc250Prompt
manifest("2358720", "Black Myth: Wukong", flags=1026, to_dl=100_000_000_000, dl=20_000_000_000)
log("AppID 2358720 state changed : Update Required,Update Running,Update Started,",
    "AppID 2358720 update changed : Running Update,Downloading,")
tick(4); fresh()
st = P._state(100)
assert st["cmd"] == "downloading" and st["text"] == "Black Myth: Wukong" and st["progress"], st

spawn(40, REAPER + ["AppId=1145350"] + PROTON + ["/games/Hades2.exe"], age_s=120)
b._MangoHud.fps = classmethod(lambda cls: 1 / 0)  # a broken source...
tick(1); fresh()
st = P._state(101)
assert st["cmd"] == "now-playing" and st["text"] == "Hades II" and st["cols"][-1][0] == "SESSION", st
assert b._Downloads.active, "...and downloads keep being tracked while playing"

b._GameDisk.usage = classmethod(lambda cls: 1 / 0)
assert math.isnan(b.Bc250GameDisk().as_numeric()) and b.Bc250GameDisk().as_string() == "--", "guarded widget"
kill(40)
print("PASS states: prompt + resilience", flush=True)

# the GPU clock: a stock board shows whatever it reads, an unlocked one drops the kernel's misread value
sysfs = os.path.join(tmp, "sysfs")
hwmon = os.path.join(sysfs, "gpu", "hwmon0")
os.makedirs(hwmon)
os.makedirs(os.path.join(sysfs, "sys", "devices", "system", "cpu"))


def board(threads, freq_mhz):
    with open(os.path.join(sysfs, "sys", "devices", "system", "cpu", "present"), "w") as f:
        f.write(f"0-{threads - 1}\n")
    with open(os.path.join(hwmon, "freq1_input"), "w") as f:
        f.write(f"{freq_mhz * 1_000_000}\n")


b.SYSFS_ROOT = sysfs
b._AmdGpu._searched, b._AmdGpu.device, b._AmdGpu.hwmon = True, os.path.join(sysfs, "gpu"), hwmon
board(12, 80)
assert b.gpu_clock_mhz() == 80, "stock: unchanged, even low"
board(12, 1873)
assert b.gpu_clock_mhz() == 1873
board(16, 57)
assert b.gpu_clock_mhz() is None, "unlocked: the misread value"
assert math.isnan(b.Bc250GpuClock().as_numeric()) and b.Bc250GpuClock().as_string() == "----"
board(16, 1500)
assert b.gpu_clock_mhz() == 1500, "unlocked with fix-freq: the real clock"
print("PASS states: GPU clock on stock and core-unlocked boards", flush=True)

shutil.rmtree(tmp)
