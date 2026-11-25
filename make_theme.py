# BC-250 theme generator for turing-smart-screen-python: renders the artwork and writes theme.yaml of one theme
# from a single layout, so static art and live widgets always line up.
#     python3 make_theme.py --app ~/turing-smart-screen-python [--theme phosphor|gameboy|retrowave|videotex|mission|minecraft|nixie|radar|halloween|christmas|horror|seismograph|orbit|departures|racing] [--portrait] [...]
#     python3 make_theme.py --help
# The theme is written to <app>/res/themes/BC250-<Theme> (fonts are read from <app>/res/fonts).
#
# This file is the command line; the rest is in generator/:
#   - base.py: SKINS (colours of each theme), fonts, the fixed layouts
#   - cfg.py: the options, and set_layout(): every position, one block per theme and orientation
#   - build.py: build_theme(), theme.yaml, shared by all themes (widget positions come from the layout)
#   - draw.py: what every theme draws with (Canvas, text, widget boxes, YAML)
#   - themes/<theme>.py: the artwork of each theme (render_*), its words, its own widgets
#
# Alignment rules used throughout:
#   - every text is placed by its BASELINE, so mixed font sizes on one row sit on the same line
#   - every live text gets a fixed box (WIDTH/HEIGHT) sized for its longest value: the app repaints the whole box on
#     each refresh, so a shorter value never leaves characters of the previous one behind
#   - left-aligned values have no padding (MIN_SIZE 1) so they start exactly under their label; right-side values
#     and labels end on the same edge as the bars and graphs below them

import argparse
from pathlib import Path

from PIL import ImageChops

from generator import cfg
from generator.base import CH, FONT, RETRO_LOGO_FONT, S, SKINS
from generator.build import build_theme
from generator.draw import Canvas, font_file, logo_size, parse_coordinate, spaced, to_yaml
from generator.themes.christmas import render_background_christmas, render_splash_christmas
from generator.themes.departures import render_background_departures
from generator.themes.gameboy import render_background_gameboy, render_splash_gameboy
from generator.themes.halloween import render_background_halloween, render_splash_halloween
from generator.themes.horror import hr_face, hr_figure, render_background_horror, render_splash_horror
from generator.themes.minecraft import render_background_minecraft, render_splash_minecraft
from generator.themes.mission import render_background_mission, render_splash_mission
from generator.themes.nixie import nixie_layout, render_background_nixie, render_splash_nixie
from generator.themes.orbit import ob_regions, render_background_orbit
from generator.themes.phosphor import render_background_phosphor, render_splash_phosphor
from generator.themes.racing import render_background_racing
from generator.themes.radar import radar_map, radar_terrain, render_background_radar
from generator.themes.retrowave import render_background_retrowave, render_splash_retrowave
from generator.themes.seismograph import render_background_seismograph
from generator.themes.videotex import render_background_videotex, render_splash_videotex


# ---------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a BC-250 theme for turing-smart-screen-python")
    parser.add_argument("--app", required=True, help="turing-smart-screen-python folder (fonts are read, theme written)")
    parser.add_argument("--theme", choices=sorted(SKINS), default="phosphor", help="which theme (default: %(default)s)")
    parser.add_argument("--portrait", action="store_true", help="portrait 320x480 layout (default: landscape)")
    parser.add_argument("--user", default=cfg.PROMPT_USER, help="user shown in the prompt (default: %(default)s)")
    parser.add_argument("--host", default=cfg.PROMPT_HOST, help="host shown in the prompt (default: %(default)s)")
    parser.add_argument("--title", default=cfg.TITLE, help='header text (default: "<LOGO>::<USER>")')
    parser.add_argument("--logo", default=cfg.LOGO, help="big title of the boot splash (default: %(default)s)")
    parser.add_argument("--subtitle", default=cfg.SUBTITLE, help="line under it (default: %(default)s)")
    parser.add_argument("--cold", type=int, default=cfg.TEMP_COLD, help="fully cold at/below this °C (default: %(default)s)")
    parser.add_argument("--hot", type=int, default=cfg.TEMP_HOT, help="fully hot at/above this °C (default: %(default)s)")
    parser.add_argument("--alert", type=int, default=cfg.TEMP_ALERT, help="flashing HOT! from this °C (default: %(default)s)")
    parser.add_argument("--pwr-low", type=int, default=cfg.POWER_LOW,
                        help="APU power fully cold at/below this W (default: %(default)s)")
    parser.add_argument("--pwr-high", type=int, default=cfg.POWER_HIGH,
                        help="APU power fully hot at/above this W (default: %(default)s)")
    parser.add_argument("--dim-after", type=int, default=cfg.DIM_AFTER,
                        help="minutes without game/download before dimming, 0 = never (default: %(default)s)")
    parser.add_argument("--dim-brightness", type=int, default=cfg.DIM_BRIGHTNESS,
                        help="brightness %% when dimmed (default: %(default)s)")
    parser.add_argument("--night", default=cfg.NIGHT,
                        help='hours when the screen sleeps unless a game runs, e.g. "23:30-08:00" (default: off)')
    parser.add_argument("--no-splash", action="store_true", help="skip the boot screen")
    parser.add_argument("--seismo-lat", help="seismograph theme: your latitude, to show each quake's distance from you (optional)")
    parser.add_argument("--seismo-lon", help="seismograph theme: your longitude (optional)")
    parser.add_argument("--seismo-min-mag", type=float, default=cfg.SEISMO_MIN_MAG,
                        help="seismograph theme: the smallest quake it records (default: %(default)s)")
    parser.add_argument("--orbit-lat", help="orbit theme: your latitude, to show when the ISS passes over you (optional)")
    parser.add_argument("--orbit-lon", help="orbit theme: your longitude (optional)")
    parser.add_argument("--no-jumpscare", action="store_true",
                        help="horror theme: no sudden face or bright flash when it reaches the camera")
    parser.add_argument("--radar-lat", default=str(cfg.RADAR_LAT),
                        help='radar theme: latitude of the centre, 48.86 or 48°51\'30"N (default: Paris CDG)')
    parser.add_argument("--radar-lon", default=str(cfg.RADAR_LON),
                        help="radar theme: longitude of the centre, 2.29 or 2°17'40\"E (default: Paris CDG)")
    parser.add_argument("--radar-range", type=float, default=cfg.RADAR_RANGE, help="radar theme: range in km (default: %(default)s)")
    parser.add_argument("--night-mode", choices=("off", "dim"), default=cfg.NIGHT_MODE,
                        help="turn the screen off or just dim it at night (default: %(default)s)")
    args = parser.parse_args()
    cfg.FONTS_DIR = Path(args.app).expanduser().resolve() / "res" / "fonts"
    if not (cfg.FONTS_DIR / FONT).is_file():
        parser.error(f"{cfg.FONTS_DIR / FONT} not found: is --app a turing-smart-screen-python folder?")
    if args.theme == "retrowave" and not (cfg.FONTS_DIR / RETRO_LOGO_FONT).is_file():
        parser.error(f"{cfg.FONTS_DIR / RETRO_LOGO_FONT} not found: the retrowave theme needs release 3.10 or newer")
    cfg.set_layout(args.portrait, args.theme)
    THEME_DIR = cfg.FONTS_DIR.parent / "themes" / cfg.SKIN["folder"]
    THEME_DIR.mkdir(parents=True, exist_ok=True)
    cfg.TEMP_COLD, cfg.TEMP_HOT, cfg.TEMP_ALERT = args.cold, args.hot, args.alert
    cfg.SPLASH = not args.no_splash
    # control characters would make theme.yaml unloadable
    printable = lambda text: "".join(ch for ch in (text or "") if ch.isprintable()).strip()
    args.user, args.host = printable(args.user) or cfg.PROMPT_USER, printable(args.host) or cfg.PROMPT_HOST
    args.title = printable(args.title) or None
    cfg.LOGO, cfg.SUBTITLE = printable(args.logo), printable(args.subtitle)
    if not cfg.LOGO:
        parser.error("--logo cannot be empty")
    max_w = cfg.SPLASH_LAYOUT["logo_max_w"]
    if len(cfg.LOGO) * logo_size(cfg.LOGO) // 2 > max_w:
        cut = cfg.LOGO[:max_w // 12]
        cfg.LOGO = cut.rsplit(" ", 1)[0] if " " in cut.strip() else cut  # at a word boundary when possible
        print(f"note: --logo shortened to '{cfg.LOGO}' to fit the splash")
    if cfg.SKIN_NAME == "retrowave":
        while len(cfg.LOGO) > 1 and font_file(RETRO_LOGO_FONT, 16).getlength(cfg.LOGO) > max_w:
            cfg.LOGO = cfg.LOGO[:-1].rstrip()
    if len(spaced(cfg.SUBTITLE)) > (cfg.W - 12) // CH[S]:
        cfg.SUBTITLE = cfg.SUBTITLE[:(cfg.W - 12) // CH[S] // 2]
        print(f"note: --subtitle shortened to '{cfg.SUBTITLE}' to fit the splash")
    cfg.POWER_LOW, cfg.POWER_HIGH = args.pwr_low, args.pwr_high
    cfg.DIM_AFTER, cfg.DIM_BRIGHTNESS, cfg.NIGHT, cfg.NIGHT_MODE = args.dim_after, args.dim_brightness, args.night, args.night_mode

    if cfg.SKIN_NAME == "seismograph":
        if bool(args.seismo_lat) != bool(args.seismo_lon):
            parser.error("--seismo-lat and --seismo-lon go together")
        if args.seismo_lat:
            try:
                cfg.SEISMO_STATION = (parse_coordinate(args.seismo_lat), parse_coordinate(args.seismo_lon))
            except ValueError:
                parser.error("--seismo-lat / --seismo-lon: use decimal degrees, e.g. 48.86 and 2.29")
            if not (-90 <= cfg.SEISMO_STATION[0] <= 90 and -180 <= cfg.SEISMO_STATION[1] <= 180):
                parser.error("seismograph: latitude -90..90, longitude -180..180")
        cfg.SEISMO_MIN_MAG = args.seismo_min_mag
    if cfg.SKIN_NAME == "orbit":
        if bool(args.orbit_lat) != bool(args.orbit_lon):
            parser.error("--orbit-lat and --orbit-lon go together")
        if args.orbit_lat:
            try:
                cfg.ORBIT_SITE = (parse_coordinate(args.orbit_lat), parse_coordinate(args.orbit_lon))
            except ValueError:
                parser.error("--orbit-lat / --orbit-lon: use decimal degrees, e.g. 48.86 and 2.29")
            if not (-90 <= cfg.ORBIT_SITE[0] <= 90 and -180 <= cfg.ORBIT_SITE[1] <= 180):
                parser.error("orbit: latitude -90..90, longitude -180..180")
    if cfg.SKIN_NAME == "radar":
        try:
            center = (parse_coordinate(args.radar_lat), parse_coordinate(args.radar_lon))
        except ValueError:
            parser.error("--radar-lat / --radar-lon: use decimal degrees, e.g. 48.86 and 2.29")
        if not (-90 <= center[0] <= 90 and -180 <= center[1] <= 180) or not 5 <= args.radar_range <= 400:
            parser.error("radar: latitude -90..90, longitude -180..180, range 5..400 km")
        cfg.RADAR.update(center=center, km=args.radar_range, map=radar_map(*center, args.radar_range))
        cfg.RADAR["terrain"] = radar_terrain(*center, args.radar_range, cfg.RADAR["scope"][2])
    title = (args.title or {"videotex": f"P250 {cfg.LOGO}", "mission": f"MCC {cfg.LOGO}", "radar": f"{cfg.LOGO} RADAR",
                            "halloween": f"HAUNTED {cfg.LOGO}", "christmas": f"MERRY {cfg.LOGO}",
                            "horror": "CAM 04  SUB-LEVEL B2", "seismograph": f"STATION {cfg.LOGO}",
                            "orbit": f"{cfg.LOGO} GROUND STATION", "departures": f"GARE {cfg.LOGO}",
                            "racing": f"{cfg.LOGO} RACING"}.get(cfg.SKIN_NAME)
             or f"{cfg.LOGO}::{args.user.upper()}")[:28]
    prompt = f"{args.user}@{args.host}:~$"[:40]

    if cfg.SKIN_NAME == "gameboy":
        render_background_gameboy(title, args.user).save(THEME_DIR / "background.png")
        render_splash_gameboy(title, prompt).save(THEME_DIR / "splash.png")
        render_splash_gameboy(title, prompt, logo=False).save(THEME_DIR / "splash_nologo.png")
        render_splash_gameboy(title, prompt, logo=False, menu=False).save(THEME_DIR / "splash_blank.png")
    elif cfg.SKIN_NAME == "radar":
        render_background_radar(title).save(THEME_DIR / "background.png")
        for old in ("splash.png", "splash_blank.png"):  # the boot now runs on background.png
            (THEME_DIR / old).unlink(missing_ok=True)
    elif cfg.SKIN_NAME == "nixie":
        nixie_layout(cfg.PORTRAIT)  # here: it needs the --alert and power options
        render_background_nixie(title).save(THEME_DIR / "background.png")
        render_splash_nixie(prompt).save(THEME_DIR / "splash.png")
    elif cfg.SKIN_NAME == "minecraft":
        render_background_minecraft(title).save(THEME_DIR / "background.png")
        render_splash_minecraft().save(THEME_DIR / "splash.png")
    elif cfg.SKIN_NAME == "halloween":
        render_background_halloween(title).save(THEME_DIR / "background.png")
        full, nologo = render_splash_halloween(), render_splash_halloween(logo=False)
        cfg.HW_REVEAL_BOX = ImageChops.difference(full, nologo).getbbox() or (0, 0, 1, 1)
        full.save(THEME_DIR / "splash.png")
        nologo.save(THEME_DIR / "splash_nologo.png")
    elif cfg.SKIN_NAME == "seismograph":
        render_background_seismograph(title).save(THEME_DIR / "background.png")
    elif cfg.SKIN_NAME == "orbit":
        render_background_orbit(title).save(THEME_DIR / "background.png")
        ob_regions().save(THEME_DIR / "regions.png")
    elif cfg.SKIN_NAME == "departures":
        render_background_departures(title).save(THEME_DIR / "background.png")
    elif cfg.SKIN_NAME == "racing":
        render_background_racing(title).save(THEME_DIR / "background.png")
    elif cfg.SKIN_NAME == "horror":
        cfg.HR_TITLE, cfg.HR_JUMPSCARE = title, not args.no_jumpscare
        render_background_horror(title).save(THEME_DIR / "background.png")
        render_splash_horror().save(THEME_DIR / "splash.png")
        hr_figure().save(THEME_DIR / "figure.png")
        hr_face().save(THEME_DIR / "face.png")
    elif cfg.SKIN_NAME == "christmas":
        render_background_christmas(title).save(THEME_DIR / "background.png")
        full, nologo = render_splash_christmas(), render_splash_christmas(logo=False)
        cfg.CM_REVEAL_BOX = ImageChops.difference(full, nologo).getbbox() or (0, 0, 1, 1)
        full.save(THEME_DIR / "splash.png")
        nologo.save(THEME_DIR / "splash_nologo.png")
    elif cfg.SKIN_NAME == "mission":
        render_background_mission(title).save(THEME_DIR / "background.png")
        render_splash_mission().save(THEME_DIR / "splash.png")
    elif cfg.SKIN_NAME == "videotex":
        render_background_videotex(title).save(THEME_DIR / "background.png")
        render_splash_videotex(title, "full").save(THEME_DIR / "splash.png")
        render_splash_videotex(title, "blank").save(THEME_DIR / "splash_blank.png")
    elif cfg.SKIN_NAME == "retrowave":
        render_background_retrowave(title, args.user).save(THEME_DIR / "background.png")
        full, nologo = render_splash_retrowave("full"), render_splash_retrowave("nologo")
        cfg.RETRO_REVEAL_BOX = ImageChops.difference(full, nologo).getbbox() or (0, 0, 1, 1)
        full.save(THEME_DIR / "splash.png")
        nologo.save(THEME_DIR / "splash_nologo.png")
        render_splash_retrowave("blank").save(THEME_DIR / "splash_blank.png")
    else:
        render_background_phosphor(title, prompt).save(THEME_DIR / "background.png")
        render_splash_phosphor(title, prompt).save(THEME_DIR / "splash.png")
        render_splash_phosphor(title, prompt, logo=False).save(THEME_DIR / "splash_nologo.png")
        Canvas().finish().save(THEME_DIR / "splash_blank.png")
    names = {"phosphor": "BC250-Phosphor - retro P1 phosphor terminal",
             "gameboy": "BC250-GameBoy - 4-shade handheld RPG status screen",
             "retrowave": "BC250-Retrowave - neon synthwave sunset",
             "videotex": "BC250-Videotex - 40-column, 8-colour videotex pages",
             "mission": "BC250-Mission - 1969 mission control console",
             "minecraft": "BC250-Minecraft - blocky inventory screen (fan theme, not affiliated with Mojang)",
             "nixie": "BC250-Nixie - Nixie tube instrument panel",
             "radar": "BC250-Radar - live aircraft around a point (free community ADS-B data)",
             "halloween": "BC250-Halloween - pumpkins, cobwebs and a graveyard under the full moon",
             "christmas": "BC250-Christmas - snow, a lit tree and Santa's sleigh on a silent night",
             "horror": "BC250-Horror - a security camera, a corridor, and what moves when the lights go out",
             "seismograph": "BC250-Seismograph - your machine's tremors and the world's real earthquakes on one drum",
             "orbit": "BC250-Orbit - a ground station tracking the ISS, and when it passes over you",
             "departures": "BC250-Departures - a station's split-flap departures board",
             "racing": "BC250-Racing - a single-seater's steering wheel display, shift lights and start lights"}
    header = (f"# {names[cfg.SKIN_NAME]} for an AMD BC-250 Steam Machine\n"
              f"# Turing 3.5\" {'portrait' if cfg.PORTRAIT else 'landscape'}. GENERATED by make_theme.py: "
              "edit the script or its options and re-run it.\n"
              "# Needs library/sensors/sensors_bc250.py (GPU via amdgpu sysfs, no pyamdgpuinfo needed).\n---\n")
    (THEME_DIR / "theme.yaml").write_text(header + to_yaml(build_theme(title, prompt, args.user)) + "\n",
                                          encoding="utf-8", newline="\n")
    print(f"Wrote {cfg.SKIN['folder']}: {'portrait' if cfg.PORTRAIT else 'landscape'}, title '{title}', "
          f"prompt '{prompt}', logo '{cfg.LOGO}' / '{cfg.SUBTITLE}', temps {cfg.TEMP_COLD}/{cfg.TEMP_HOT}/{cfg.TEMP_ALERT}°C, "
          f"power {cfg.POWER_LOW}-{cfg.POWER_HIGH}W, dim after {cfg.DIM_AFTER} min, night '{cfg.NIGHT or 'off'}'")
