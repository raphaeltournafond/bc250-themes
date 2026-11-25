"""What never changes: each theme's colours (SKINS), fonts, character sizes, and the fixed layouts and data
several modules share."""


# --- Colours ----------------------------------------------------------------------------------------------------------
DMG = [(155, 188, 15), (139, 172, 15), (48, 98, 48), (15, 56, 15)]  # Game Boy DMG: lightest .. darkest
# videotex: the 8 flat colours (black, red, green, yellow, blue, magenta, cyan, white), a touch softer than pure RGB
VT = dict(k=(0, 0, 0), r=(230, 40, 40), g=(40, 200, 70), y=(250, 220, 50), b=(40, 80, 220), m=(220, 60, 210),
          c=(50, 210, 230), w=(245, 245, 245))
SKINS = {
    # P1 phosphor terminal: bright green on near-black
    "phosphor": dict(folder="BC250-Phosphor", bg=(2, 9, 4), dim=(18, 78, 38), mid=(46, 170, 88),
                     value=(125, 255, 165), accent=(255, 176, 40), cold=(125, 255, 165), hot=(255, 140, 30),
                     alert=(255, 60, 40), ink=(2, 14, 6), grid_dot=(8, 34, 16), palette=None),
    # Game Boy DMG: four shades only, darkest on lightest; heat is shown by darker shades and the HOT! flash
    "gameboy": dict(folder="BC250-GameBoy", bg=DMG[0], dim=DMG[1], mid=DMG[2], value=DMG[3], accent=DMG[2],
                    cold=DMG[2], hot=DMG[3], alert=DMG[3], ink=DMG[0], grid_dot=DMG[1], palette=DMG),
    # Retrowave: neon pink and cyan on a purple night, heat going cyan -> hot pink -> sunset orange
    "retrowave": dict(folder="BC250-Retrowave", bg=(16, 4, 36), dim=(96, 40, 140), mid=(255, 70, 190),
                      value=(90, 235, 255), accent=(255, 176, 60), cold=(90, 235, 255), hot=(255, 60, 190),
                      alert=(255, 96, 36), ink=(24, 4, 40), grid_dot=(54, 20, 84), palette=None),
    # Videotex: 8 flat colours only (every computed colour snaps to them), heat in green -> yellow -> red steps
    "videotex": dict(folder="BC250-Videotex", bg=VT["k"], dim=VT["b"], mid=VT["c"], value=VT["w"], accent=VT["y"],
                     cold=VT["g"], hot=VT["y"], alert=VT["r"], ink=VT["k"], grid_dot=VT["b"], bar=VT["g"],
                     palette=list(VT.values())),
    # Mission Control 1969: white telemetry and amber labels in black CRT windows set in a grey console
    "mission": dict(folder="BC250-Mission", bg=(6, 8, 8), console=(58, 60, 62), dim=(92, 94, 96),
                    mid=(255, 176, 40), value=(232, 232, 220), accent=(255, 176, 40), cold=(232, 232, 220),
                    hot=(255, 176, 40), alert=(240, 60, 50), ink=(10, 10, 10), grid_dot=(34, 38, 38),
                    bar=(255, 176, 40), green=(70, 220, 100), palette=None),
    # Minecraft-inspired: light grey inventory panels on dark dirt, dark grey text, XP-green bars,
    # heat in the game's chat colours (dark green -> gold -> red)
    "minecraft": dict(folder="BC250-Minecraft", bg=(40, 29, 21), dim=(120, 120, 120), mid=(63, 63, 63),
                      value=(63, 63, 63), accent=(255, 170, 0), cold=(0, 150, 0), hot=(230, 140, 0),
                      alert=(200, 30, 30), ink=(255, 255, 255), grid_dot=(150, 150, 150), bar=(110, 220, 30),
                      palette=None),
    # Nixie: neon-orange tubes and amber readouts on a black instrument front with brass engraving
    "nixie": dict(folder="BC250-Nixie", bg=(10, 9, 8), dim=(120, 95, 58), mid=(190, 150, 85), value=(255, 150, 60),
                  accent=(255, 110, 40), cold=(255, 150, 60), hot=(255, 100, 30), alert=(255, 50, 40), ink=(10, 9, 8),
                  grid_dot=(40, 32, 26), palette=None),
    # Radar: a military green PPI scope with a turning sweep, targets in shades of green by altitude
    "radar": dict(folder="BC250-Radar", bg=(2, 9, 4), dim=(50, 120, 70), mid=(90, 190, 110), value=(200, 255, 210),
                  accent=(230, 255, 120), cold=(120, 255, 140), hot=(255, 190, 60), alert=(255, 70, 60), ink=(2, 9, 4),
                  grid_dot=(14, 70, 28), palette=None),
    # Halloween: pumpkin-orange labels and bone-white values on a purple night, ectoplasm green, heat going
    # slime green -> pumpkin -> blood red
    "halloween": dict(folder="BC250-Halloween", bg=(10, 6, 14), dim=(84, 48, 104), mid=(255, 122, 24),
                      value=(238, 230, 206), accent=(150, 235, 70), cold=(150, 235, 70), hot=(255, 122, 24),
                      alert=(236, 24, 40), ink=(10, 6, 14), grid_dot=(40, 24, 52), bar=(255, 122, 24), palette=None),
    # Christmas: gold labels and snow-white values on a midnight blue night, pine-green frames, heat going
    # ice blue -> gold -> holly red
    "christmas": dict(folder="BC250-Christmas", bg=(8, 14, 28), dim=(44, 104, 80), mid=(255, 205, 96),
                      value=(244, 248, 255), accent=(255, 150, 60), cold=(130, 205, 255), hot=(255, 190, 70),
                      alert=(240, 44, 54), ink=(8, 14, 28), grid_dot=(24, 44, 50), bar=(78, 190, 104),
                      green=(96, 214, 120), palette=None),
    # Horror: a security console, the washed-out grey-green of old CCTV, and red only when something is wrong
    "horror": dict(folder="BC250-Horror", bg=(5, 7, 6), dim=(82, 96, 86), mid=(134, 152, 138), value=(206, 216, 202),
                   accent=(214, 40, 36), cold=(170, 190, 174), hot=(226, 170, 104), alert=(240, 36, 32), ink=(5, 7, 6),
                   grid_dot=(30, 38, 32), bar=(134, 152, 138), palette=None),
    # Seismograph: an observatory's instrument, dark enamel and brass around a sheet of cream paper
    "seismograph": dict(folder="BC250-Seismograph", bg=(18, 20, 20), dim=(112, 116, 104), mid=(200, 168, 100),
                        value=(234, 228, 208), accent=(220, 70, 48), cold=(156, 196, 156), hot=(236, 176, 84),
                        alert=(240, 54, 44), ink=(18, 20, 20), grid_dot=(40, 44, 42), bar=(200, 168, 100), palette=None),
    # Orbit: a ground station's tracking display, deep navy, sky blue and the amber of the ISS's solar wings
    "orbit": dict(folder="BC250-Orbit", bg=(7, 12, 22), dim=(86, 108, 134), mid=(122, 172, 222), value=(226, 236, 246),
                  accent=(255, 190, 70), cold=(120, 200, 170), hot=(240, 170, 80), alert=(240, 64, 56), ink=(7, 12, 22),
                  grid_dot=(24, 38, 58), bar=(122, 172, 222), palette=None),
    # Departures: a station's split-flap board, white and yellow letters on black leaves, an amber LED band under it
    "departures": dict(folder="BC250-Departures", bg=(18, 18, 20), dim=(120, 120, 124), mid=(252, 204, 64),
                       value=(238, 236, 226), accent=(255, 176, 48), cold=(200, 214, 200), hot=(255, 150, 40),
                       alert=(240, 60, 50), ink=(18, 18, 20), grid_dot=(44, 44, 48), bar=(252, 204, 64), palette=None),
    # Racing: a single-seater's steering wheel display, on carbon, green, red and blue shift lights
    "racing": dict(folder="BC250-Racing", bg=(14, 14, 16), dim=(110, 112, 118), mid=(255, 210, 40), value=(240, 240, 240),
                   accent=(255, 210, 40), cold=(40, 210, 90), hot=(255, 170, 40), alert=(240, 40, 40), ink=(14, 14, 16),
                   grid_dot=(52, 52, 58), bar=(40, 220, 90), palette=None),
}

FONT = "fusion-pixel/fusion-pixel-12px-monospaced-zh_hans.otf"  # pixel font: use multiples of 12 only
RETRO_LOGO_FONT = "racespace/RACESPACESTRIPE-Extended.otf"  # retrowave logo (in the app since 3.10)
RETRO_TAG_FONT = "racespace/RACESPACEREGULAR-Extended.otf"  # retrowave panel names and subtitle
S, M, L = 12, 24, 36  # 1x / 2x / 3x
CH = {S: 6, M: 12, L: 18}  # monospace advance per size
ASCENT = {S: 10, M: 20, L: 30}  # font ascent per size (ImageFont.getmetrics)

HEADER_H = 16
HEADER_BL = 12
CLOCK_CHARS = 8  # "HH:mm:ss"


# ---------------------------------------------------------------------------------------------------------------------
# Layout: every position lives here
# ---------------------------------------------------------------------------------------------------------------------
RADAR_LAYOUT = {  # landscape, portrait
    False: dict(scope=(158, 168, 148), card=(314, 22, 474, 132), card_rows=[32, 52, 68, 90, 106], card_style="tall",
                list=(314, 138, 474, 206), list_bl=162, list_rows=4, list_columns=1, count=(416, 12, 90),
                stats=[(314, 228, 346, 474), (314, 252, 346, 474)], prompt_line=(310, 257, 476)),
    True: dict(scope=(160, 164, 140), card=(8, 310, 312, 380), card_rows=[30, 50, 66], card_style="wide",
               list=(8, 382, 312, 410), list_bl=394, list_rows=2, list_columns=2, count=(258, 12, 90),
               stats=[(8, 430, 34, 150), (164, 430, 190, 312)], prompt_line=(4, 431, 316)),
}
RADAR_SPLASH = {  # the boot runs on the dashboard itself: its log takes the flight card and the list
    False: dict(log=(314, 22, 474, 206), row_bl=0, row_step=0, label_x=314, value_x=362, status_xr=474, status_bl=0),
    True: dict(log=(8, 310, 312, 410), row_bl=0, row_step=0, label_x=8, value_x=56, status_xr=312, status_bl=0),
}


GRID_LABELS = [("ram", "RAM", "USED", "bar"), ("ssd", "GAMES SSD", "FREE", "bar"), ("pwr", "APU PWR", "GPU MEM", "bar"),
               ("rx", "↓ DOWNLOAD", None, "spark"), ("tx", "↑ UPLOAD", None, "spark"), ("ping", "PING", None, "spark")]


# ---------------------------------------------------------------------------------------------------------------------
# Seismograph artwork: a helicorder's paper (the pen writes line after line on it, like the drums in observatories,
# so only the new ink has to reach the screen), and a world map
# ---------------------------------------------------------------------------------------------------------------------
SEISMO_LAYOUT = {  # landscape, portrait
    False: dict(paper=(4, 18, 472, 168), rows=7, map=(4, 191, 168, 84), card=(176, 190, 146, 86),
                labels=(("CPU", 326, 210, "ls"), ("GPU", 326, 236, "ls"), ("RAM", 326, 262, "ls")),
                cpu=((352, 212), (474, 212)), gpu=((352, 238), (474, 238)), ram=(352, 264), pwr=(474, 264),
                lines=((324, 190, 324, 276), (174, 190, 174, 276))),
    True: dict(paper=(4, 18, 312, 208), rows=8, map=(4, 230, 156, 78), card=(166, 229, 150, 86),
               labels=(("CPU", 8, 328, "ls"), ("GPU", 166, 328, "ls"), ("RAM", 8, 376, "ls"), ("APU W", 166, 376, "ls")),
               cpu=((8, 352), (154, 352)), gpu=((166, 352), (312, 352)), ram=(8, 400), pwr=(312, 400),
               lines=((160, 316, 160, 416), (4, 318, 316, 318))),
}
# the continents, roughly: (longitude, latitude). Coarse is fine at this size, and the quakes draw the plates' edges
SM_WORLD = (
    ((-168, 66), (-156, 71), (-140, 70), (-125, 70), (-110, 68), (-95, 72), (-85, 70), (-82, 66), (-94, 60), (-92, 57),
     (-82, 52), (-79, 55), (-78, 62), (-70, 62), (-65, 60), (-56, 52), (-66, 50), (-60, 46), (-70, 43), (-75, 38), (-81, 31),
     (-80, 25), (-82, 29), (-90, 29), (-97, 26), (-97, 20), (-90, 18), (-87, 21), (-88, 16), (-83, 15), (-83, 10), (-78, 9),
     (-80, 7), (-85, 10), (-92, 14), (-100, 17), (-106, 22), (-110, 24), (-115, 31), (-120, 34), (-124, 40), (-124, 48),
     (-130, 54), (-140, 60), (-150, 60), (-158, 57), (-165, 54), (-160, 59), (-165, 62)),  # North America
    ((-43, 60), (-52, 65), (-55, 70), (-70, 77), (-60, 82), (-30, 83), (-18, 78), (-22, 70), (-32, 68)),  # Greenland
    ((-78, 9), (-72, 12), (-62, 10), (-52, 5), (-50, 0), (-35, -6), (-39, -14), (-41, -22), (-48, -26), (-53, -34),
     (-58, -38), (-65, -42), (-68, -50), (-69, -55), (-74, -52), (-74, -42), (-71, -30), (-70, -18), (-76, -14), (-81, -5),
     (-80, 1), (-77, 7)),  # South America
    ((-6, 35), (10, 37), (11, 33), (20, 31), (25, 32), (34, 31), (37, 22), (43, 12), (51, 12), (47, 4), (40, -3), (40, -15),
     (35, -20), (33, -27), (26, -34), (18, -34), (13, -18), (12, -5), (9, 4), (-5, 5), (-12, 8), (-17, 14), (-16, 22),
     (-10, 30)),  # Africa
    ((-9, 37), (-9, 43), (-2, 44), (-4, 48), (3, 51), (8, 54), (9, 57), (12, 54), (20, 55), (24, 59), (30, 60), (22, 60),
     (18, 60), (17, 57), (12, 56), (10, 59), (5, 60), (8, 63), (15, 69), (25, 71), (40, 67), (45, 68), (60, 69), (68, 72),
     (80, 73), (105, 77), (115, 74), (130, 72), (140, 73), (160, 70), (180, 68), (178, 62), (170, 60), (163, 58), (160, 52),
     (156, 57), (155, 60), (143, 59), (136, 54), (140, 48), (130, 42), (127, 35), (125, 39), (121, 40), (118, 38), (122, 31),
     (120, 26), (110, 21), (106, 18), (109, 12), (105, 9), (100, 13), (103, 2), (98, 8), (97, 16), (92, 22), (88, 22), (80, 15),
     (78, 8), (73, 18), (72, 21), (67, 25), (58, 25), (57, 27), (49, 30), (52, 24), (56, 25), (59, 22), (52, 16), (43, 13),
     (39, 21), (35, 28), (36, 36), (28, 37), (26, 40), (23, 37), (20, 40), (18, 40), (16, 38), (13, 44), (10, 44), (3, 43),
     (0, 39), (-5, 36)),  # Eurasia
    ((114, -22), (122, -18), (130, -12), (136, -12), (140, -17), (145, -15), (153, -26), (150, -37), (144, -39), (138, -35),
     (130, -32), (116, -35)),  # Australia
    ((-5, 50), (1, 51), (-2, 57), (-6, 58), (-3, 54)), ((-10, 52), (-6, 52), (-6, 55), (-10, 54)),  # Britain, Ireland
    ((-24, 65), (-14, 66), (-15, 63), (-22, 63)),  # Iceland
    ((130, 31), (136, 34), (141, 36), (142, 42), (145, 44), (141, 45), (139, 38), (132, 35)),  # Japan
    ((95, 5), (105, -5), (102, -4), (97, 2)), ((109, 1), (117, 7), (118, 1), (115, -4), (110, -3)),  # Sumatra, Borneo
    ((105, -6), (115, -8), (105, -8)), ((120, 1), (124, 1), (122, -5), (120, -4)),  # Java, Sulawesi
    ((131, -1), (141, -3), (150, -10), (140, -9), (134, -4)), ((120, 18), (122, 18), (126, 7), (122, 7)),  # New Guinea, Philippines
    ((173, -35), (178, -38), (170, -46), (167, -45)), ((49, -12), (50, -16), (47, -25), (44, -24), (44, -17)),  # New Zealand, Madagascar
    ((-85, 22), (-75, 20), (-80, 23)),  # Cuba
    ((-180, -72), (-120, -74), (-60, -66), (-30, -76), (30, -69), (90, -66), (150, -68), (180, -72), (180, -90), (-180, -90)),  # Antarctica
)


# ---------------------------------------------------------------------------------------------------------------------
# Orbit artwork: a ground station's world map (the sensors put the night, the ISS and its track on it), the cards and
# the chart of the sky passes are drawn on
# ---------------------------------------------------------------------------------------------------------------------
ORBIT_LAYOUT = {  # landscape, portrait. The map is cropped to the latitudes that matter: the ISS flies within 52°
    False: dict(map=(4, 18, 472, 168), lat_top=72, card=(4, 190, 166, 86), card_rows=(40, 54, 67, 80),
                pass_=(176, 190, 146, 86), pass_heading=(244, 202), sky=(208, 241, 28),
                slots=((244, 226, 24, "ls"), (244, 241, 12, "ls"), (244, 255, 12, "ls"), (244, 269, 12, "ls")),
                labels=(("CPU", 326, 210, "ls"), ("GPU", 326, 236, "ls"), ("RAM", 326, 262, "ls")),
                cpu=((352, 212), (474, 212)), gpu=((352, 238), (474, 238)), ram=(352, 264), pwr=(474, 264),
                lines=((324, 190, 324, 276), (172, 190, 172, 276)), log=(4, 190, 476, 276), log_columns=2, log_step=13),
    True: dict(map=(4, 18, 312, 138), lat_top=80, card=(4, 160, 154, 142), card_rows=(40, 58, 74, 90, 106, 122),
               pass_=(162, 160, 154, 142), pass_heading=(164, 172), sky=(239, 222, 36),
               slots=((166, 284, 24, "ls"), (314, 274, 12, "rs"), (314, 288, 12, "rs"), (166, 299, 12, "ls")),
               labels=(("CPU", 8, 324, "ls"), ("GPU", 166, 324, "ls"), ("RAM", 8, 368, "ls"), ("APU W", 166, 368, "ls")),
               cpu=((8, 348), (154, 348)), gpu=((166, 348), (312, 348)), ram=(8, 392), pwr=(312, 392),
               lines=((160, 160, 160, 302), (160, 310, 160, 412), (4, 306, 316, 306)), log=(4, 160, 316, 412),
               log_columns=1, log_step=16),
}


def nixie_splash_layout(portrait):
    if not portrait:
        return dict(logo_bl=40, sub_bl=58, tube=(40, 86), tube_y=72, lamps_y=192, lamps_x=(72, 408), lamp_label_bl=214,
                    text_bl=246, status_bl=274, footer_bl=308)
    return dict(logo_bl=36, sub_bl=56, tube=(40, 86), tube_y=72, lamps_y=196, lamps_x=(40, 280), lamp_label_bl=216,
                text_bl=252, status_bl=282, footer_bl=470)
