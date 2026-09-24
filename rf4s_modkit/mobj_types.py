"""MOBJ type_id -> map-object identity table.

A `.rf4m` map's MOBJ chunk holds 64-byte entity records whose first dword is a
`type_id`. RF4S spawns each record through one of four paths (see
`Map_SpawnAllEntities` @ RF4S.exe+0xDFE70), but EVERY path that draws a sprite
loads the same resource:

        map_obj archive id = type_id + 17542          (0x4486)

and that archive id indexes the static filename TOC at RF4S.exe+0x57AD30
(256-byte wide-string stride), which resolves to `rom:/map_obj/<NAME>.bntx`.
So the placed object's identity is simply the `map_obj/<NAME>` sprite.

Dispatch by type_id (the map_obj sprite-loaders are type_id >= 20):
    0..8      forage       Map_HandleSpecialTriggerEntity  -> daily-respawn gatherable
                             spawn directive. Picks a crop/herb KIND via Map_DailyRng_Seeded
                             + weighted pools in the map-tiles struct, writes a 64-B
                             MapEntitySlot_t, sprite via the CROP path (1366 + kind),
                             NOT the map_obj band. (case 0 = 16-pool item, 5 = 32-pool
                             herb/grass, 6/7 = 64-pool, etc.) So type_id here is a
                             pool-selector, not a fixed sprite.
    9..19     mapparam     MAP PARAMETER records: Map_HandleSpecialTriggerEntity returns
                             early for them, but Map_LoadById walks every MOBJ record
                             through MapEvent_GetAtIndex at load and consumes types
                             9 (ground depth), 10 (parallax), 11 (UV scroll), 12 (tint
                             colour), 13 (npc-streaming float), 15 (map flag bit 8); see
                             mobj_params.MAP_PARAMS. Positionless (f14/f15 = 0).
                             (Was "inert / legacy markers" until 2026-09-19 -- type 12
                             is the single most common record in the shipped maps.)
    20..195   actor        category "map_obj_id", task id = type_id+1000
                             20..81  per-type init table (effects "fe*", gimmicks "gmk*")
                             82..195 shared setup MapObj_LoadSpriteAndCollision -> Resource_AttachToTask(type+17542)
    196..335  object       Map_SpawnInteractiveObject       -> nsFileArchive_Load(type+17542)
    >= 336    decoration   MapDecoration_Spawn              -> nsFileArchive_Load(type+17542)

`MAP_OBJ_BAND` below is the literal filename TOC band (archive 17542..17935 ->
type_id 0..393), dumped live from the running game. For type_id >= 20 this IS the
sprite each MOBJ loads; entries 0..19 are the band contents (effect "fe*" sprites)
but are NOT loaded by the trigger path -- `mobj_name()` therefore returns None for
type_id < 20. Names are self-documenting: `MOBJ_FI_TREE01` = field tree 1,
`DOOR_CITY_00_00` = a city warp door, `MOBJ_SHIP`, `MOBJ_BOX` (a breakable crate),
`MOBJ_CHANDELIER`, etc. Seasonal variants share a base name with a
`_SUMMER/_AUTUMN/_WINTER` suffix (the default/no-suffix entry is the spring sprite).
"""
from __future__ import annotations

# Archive-id base shared by every map-object spawn path.
MAP_OBJ_ARCHIVE_BASE = 17542  # 0x4486

# Lowest type_id whose record actually loads a map_obj sprite (= type_id + 17542).
# Below this, records are forage spawn directives (0..8) or load-time map
# parameters (9..19, see mobj_params.MAP_PARAMS).
FIRST_MAP_OBJ_TYPE = 20

# The literal filename TOC band: archive (17542 + type_id) -> map_obj sprite name
# (no "rom:/map_obj/" prefix, no ".bntx" suffix). Dumped from RF4S.exe.
MAP_OBJ_BAND: dict[int, str] = {
    0: "fe023", 1: "fe024", 2: "fe025", 3: "fe026", 4: "fe027", 5: "fe028",
    6: "fe029", 7: "fe030", 8: "fe031", 9: "fe031_00", 10: "fe031_01",
    11: "fe031_02", 12: "fe031_03", 13: "fe031_04", 14: "fe031_05",
    15: "fe031_06", 16: "fe031_07", 17: "fe031_08", 18: "fe031_09",
    19: "fe031_10", 20: "fe032", 21: "fe033", 22: "fe034", 23: "fe035",
    24: "fe036", 25: "fe037", 26: "gmk00_eater", 27: "gmk01_bird",
    28: "gmk02_butterfly", 29: "gmk04_storm", 30: "gmk05_storm",
    31: "gmk06_rock", 32: "gmk07_dummy", 33: "gmk08_roll", 34: "gmk09_water",
    35: "gmk10_mushroom", 36: "gmk11_collection", 37: "gmk12_redlight",
    38: "gmk13_bluelight", 39: "gmk14_sunlight", 40: "gmk15_magiclight",
    41: "gmk16_waterlight", 42: "gmk17_warp_effect", 43: "fe100", 44: "fe101",
    45: "fe102", 46: "fe102_2", 47: "fe103", 48: "fe107", 49: "fe104",
    50: "fe105", 51: "MOBJ_SHIP", 52: "MOBJ_FI_ERUPT_LAVA", 53: "MOBJ_BOX",
    54: "MOBJ_FI_ERUPT", 55: "fe106", 56: "MOBJ_CHANDELIER",
    57: "MOBJ_FIELD_METAL02", 58: "MOBJ_BOX_WINTER", 59: "fe114", 60: "fe115",
    61: "fe116", 62: "fe117", 63: "fe118", 64: "fe119", 65: "fe120",
    66: "fe121", 67: "fe122", 68: "fe123", 69: "fe124", 70: "fe125",
    71: "fe126", 72: "fe127", 73: "fe128", 74: "MOBJ_FI_ICE01_dummy",
    75: "MOBJ_FI_ICE02_dummy", 76: "MOBJ_FI_ICE03_dummy",
    77: "MOBJ_FI_ICE04_dummy", 78: "MOBJ_ROAD_E_UP", 79: "MOBJ_ROAD_E_RIGHT",
    80: "MOBJ_ROAD_E_DOWN", 81: "MOBJ_ROAD_E_LEFT", 82: "DOOR_CITY_00_00",
    83: "DOOR_CITY_00_00_SUMMER", 84: "DOOR_CITY_00_00_AUTUMN",
    85: "DOOR_CITY_00_00_WINTER", 86: "DOOR_CITY_00_01",
    87: "DOOR_CITY_00_01_SUMMER", 88: "DOOR_CITY_00_01_AUTUMN",
    89: "DOOR_CITY_00_01_WINTER", 90: "DOOR_CITY_00_02",
    91: "DOOR_CITY_00_02_SUMMER", 92: "DOOR_CITY_00_02_AUTUMN",
    93: "DOOR_CITY_00_02_WINTER", 94: "DOOR_CITY_00_03",
    95: "DOOR_CITY_00_03_SUMMER", 96: "DOOR_CITY_00_03_AUTUMN",
    97: "DOOR_CITY_00_03_WINTER", 98: "DOOR_CITY_01_00",
    99: "DOOR_CITY_01_00_SUMMER", 100: "DOOR_CITY_01_00_AUTUMN",
    101: "DOOR_CITY_01_00_WINTER", 102: "DOOR_CITY_01_01",
    103: "DOOR_CITY_01_01_SUMMER", 104: "DOOR_CITY_01_01_AUTUMN",
    105: "DOOR_CITY_01_01_WINTER", 106: "DOOR_CITY_01_02",
    107: "DOOR_CITY_01_02_SUMMER", 108: "DOOR_CITY_01_02_AUTUMN",
    109: "DOOR_CITY_01_02_WINTER", 110: "DOOR_CITY_01_03",
    111: "DOOR_CITY_01_03_SUMMER", 112: "DOOR_CITY_01_03_AUTUMN",
    113: "DOOR_CITY_01_03_WINTER", 114: "DOOR_CITY_02_00",
    115: "DOOR_CITY_02_00_SUMMER", 116: "DOOR_CITY_02_00_AUTUMN",
    117: "DOOR_CITY_02_00_WINTER", 118: "DOOR_CITY_02_01",
    119: "DOOR_CITY_02_01_SUMMER", 120: "DOOR_CITY_02_01_AUTUMN",
    121: "DOOR_CITY_02_01_WINTER", 122: "DOOR_CITY_02_02",
    123: "DOOR_CITY_02_02_SUMMER", 124: "DOOR_CITY_02_02_AUTUMN",
    125: "DOOR_CITY_02_02_WINTER", 126: "DOOR_CITY_02_03",
    127: "DOOR_CITY_02_03_SUMMER", 128: "DOOR_CITY_02_03_AUTUMN",
    129: "DOOR_CITY_02_03_WINTER", 130: "DOOR_CITY_03_00",
    131: "DOOR_CITY_03_00_SUMMER", 132: "DOOR_CITY_03_00_AUTUMN",
    133: "DOOR_CITY_03_00_WINTER", 134: "DOOR_CITY_04_00",
    135: "DOOR_CITY_04_00_SUMMER", 136: "DOOR_CITY_04_00_AUTUMN",
    137: "DOOR_CITY_04_00_WINTER", 138: "DOOR_CITY_04_01",
    139: "DOOR_CITY_04_01_SUMMER", 140: "DOOR_CITY_04_01_AUTUMN",
    141: "DOOR_CITY_04_01_WINTER", 142: "DOOR_CITY_05_00",
    143: "DOOR_CITY_05_00_SUMMER", 144: "DOOR_CITY_05_00_AUTUMN",
    145: "DOOR_CITY_05_00_WINTER", 146: "DOOR_CITY_06_00",
    147: "DOOR_CITY_06_00_SUMMER", 148: "DOOR_CITY_06_00_AUTUMN",
    149: "DOOR_CITY_06_00_WINTER", 150: "DOOR_CITY_06_01",
    151: "DOOR_CITY_06_01_SUMMER", 152: "DOOR_CITY_06_01_AUTUMN",
    153: "DOOR_CITY_06_01_WINTER", 154: "DOOR_CITY_06_02",
    155: "DOOR_CITY_06_02_SUMMER", 156: "DOOR_CITY_06_02_AUTUMN",
    157: "DOOR_CITY_06_02_WINTER", 158: "DOOR_ROOM_06A_00",
    159: "DOOR_ROOM_06A_01", 160: "DOOR_ROOM_06A_02", 161: "DOOR_DUNG_C01_00",
    162: "DOOR_DUNG_C03_00", 163: "DOOR_DUNG_C04_00", 164: "DOOR_DUNG_C04_01",
    165: "DOOR_DUNG_C05_00", 166: "DOOR_DUNG_C06_00", 167: "DOOR_DUNG_C07_00",
    168: "DOOR_DUNG_C07_01", 169: "DOOR_DUNG_C07_02", 170: "DOOR_DUNG_C08_00",
    171: "DOOR_DUNG_C08_01", 172: "DOOR_DUNG_C09_00", 173: "DOOR_DUNG_C09_01",
    174: "DOOR_DUNG_C13_00", 175: "DOOR_DUNG_C13_01", 176: "DOOR_DUNG_C14_00",
    177: "DOOR_DUNG_C14_01", 178: "DOOR_DUNG_C15_00", 179: "DOOR_DUNG_C15_01",
    180: "DOOR_DUNG_C15_02", 181: "DOOR_DUNG_C16_00", 182: "DOOR_DUNG_C17_00",
    183: "DOOR_DUNG_C18_00", 184: "DOOR_DUNG_C18_01", 185: "DOOR_DUNG_D01_00",
    186: "MOBJ_DOOR_FIELD_11_00", 187: "MOBJ_DOOR_FIELD_21_00",
    188: "MOBJ_DOOR_FIELD_31_00", 189: "MOBJ_DOOR_FIELD_41_00",
    190: "DOOR_DUNG_C19_00", 191: "MOBJ_DOOR_DUMMY02", 192: "MOBJ_DOOR_DUMMY03",
    193: "MOBJ_DOOR_DUMMY04", 194: "fe_splash01", 195: "fe_splash02",
    196: "fe_splash03", 197: "MOBJ_FI_ROCK01", 198: "MOBJ_FID_TREE_00",
    199: "MOBJ_FI_TREE01", 200: "MOBJ_FI_TREE01_SPRING",
    201: "MOBJ_FI_TREE01_AUTUMN", 202: "MOBJ_FI_TREE01_WINTER",
    203: "MOBJ_FI_TREE02", 204: "MOBJ_FI_TREE02_WINTER", 205: "MOBJ_FI_TREE03",
    206: "MOBJ_FI_TREE03_AUTUMN", 207: "MOBJ_FI_TREE03_WINTER",
    208: "MOBJ_FI_TREE04", 209: "MOBJ_FI_TREE04_AUTUMN",
    210: "MOBJ_FI_TREE04_WINTER", 211: "MOBJ_FI_TREE06",
    212: "MOBJ_FI_TREE06_WINTER", 213: "MOBJ_FID_CRACK03",
    214: "MOBJ_FID_CRYSTAL_M01", 215: "MOBJ_FID_CRYSTAL_S01",
    216: "MOBJ_FID_HOUSE01", 217: "MOBJ_FID_ISEKI01", 218: "MOBJ_FID_ISEKI02",
    219: "MOBJ_FID_KAIDAN_DOWN02", 220: "MOBJ_FID_KAIDAN_UP02",
    221: "MOBJ_FID_MIZUBA01", 222: "MOBJ_FID_ONSEN01", 223: "MOBJ_FID_ROCK01",
    224: "MOBJ_FID_ROCK02", 225: "MOBJ_FID_ROCK03", 226: "MOBJ_FID_ROCK04",
    227: "MOBJ_FID_WALL_up", 228: "MOBJ_FID_WALL_right",
    229: "MOBJ_FID_WALL_down", 230: "MOBJ_FID_WALL_left", 231: "MOBJ_E05_ROAD01",
    232: "MOBJ_E05_ROAD02", 233: "MOBJ_E05_ROAD03", 234: "MOBJ_E05_ROAD04",
    235: "MOBJ_FI_STONE01_E05", 236: "MOBJ_FI_STONE02_E05", 237: "MOBJ_E05_HOLE03",
    238: "MOBJ_E05_HOLE04", 239: "OBJ_D_E05_WALL", 240: "MOBJ_FID_KAIDAN_DOWN03",
    241: "MOBJ_FI_ROCK04_E05", 242: "MOBJ_FI_ROCK05_E05", 243: "MOBJ_FI_ROCK06_E05",
    244: "MOBJ_FI_ROCK09_E05", 245: "MOBJ_FI_ROCK10_E05", 246: "RandDungWallUp03_E05",
    247: "MOBJ_FI_MUSHROOM01", 248: "MOBJ_FI_MUSHROOM01_WINTER",
    249: "MOBJ_FID_CRACK02", 250: "MOBJ_FI_ROCK04", 251: "MOBJ_FI_ROCK04_WINTER",
    252: "MOBJ_FI_ROCK05", 253: "MOBJ_FI_ROCK05_WINTER", 254: "MOBJ_FI_ROCK06",
    255: "MOBJ_FI_ROCK06_WINTER", 256: "MOBJ_FI_STONE01", 257: "MOBJ_FI_STONE01_WINTER",
    258: "MOBJ_FI_STONE02", 259: "MOBJ_FI_STONE02_WINTER", 260: "MOBJ_FID_ROCK05",
    261: "MOBJ_FID_ROCK06", 262: "MOBJ_CLEAR_WALL", 263: "MOBJ_SW_WALL_00",
    264: "MOBJ_FIELD_HIBI01", 265: "MOBJ_FIELD_HIBI02", 266: "MOBJ_FIELD_HIBI03",
    267: "MOBJ_FIELD_HIBI04", 268: "MOBJ_FIELD_HIBI05", 269: "MOBJ_FI_MUSHROOM02",
    270: "MOBJ_FI_MUSHROOM02_WINTER", 271: "MOBJ_FID_GROUND_00",
    272: "MOBJ_LAST_BOSS_WALL_0", 273: "MOBJ_LAST_BOSS_WALL_1",
    274: "MOBJ_FI_MUSHROOM03", 275: "MOBJ_FI_MUSHROOM03_WINTER",
    276: "MOBJ_FI_STONE01_LAVA", 277: "MOBJ_FI_STONE02_LAVA",
    278: "MOBJ_FI_ROCK04_LAVA", 279: "MOBJ_FI_ROCK05_LAVA", 280: "MOBJ_FI_ROCK06_LAVA",
    281: "MOBJ_FI_TREE03_SPRING", 282: "MOBJ_FI_TREE04_SPRING", 283: "MOBJ_FI_TREE07",
    284: "MOBJ_FI_TREE07_WINTER", 285: "MOBJ_FI_SNOWMAN", 286: "RandDungWallUp04",
    287: "MOBJ_FI_ROCK07", 288: "MOBJ_FI_ROCK08", 289: "MOBJ_FI_ROCK09",
    290: "MOBJ_FI_ROCK10", 291: "MOBJ_FIELD_METAL01", 292: "MOBJ_FI_ROCK09_DUNG",
    293: "MOBJ_FI_ROCK10_DUNG", 294: "MOBJ_SHIP_BRIDGE", 295: "MOBJ_E01_BLOCK01",
    296: "MOBJ_FI_TREE09_WINTER", 297: "MOBJ_FID_ISEKI01_WINTER",
    298: "OBJ_D_E02_door", 299: "MOBJ_E01_CENTER", 300: "MOBJ_E03_CENTER",
    301: "MOBJ_FI_TREE20", 302: "MOBJ_FI_TREE21", 303: "MOBJ_FI_TREE22",
    304: "MOBJ_DUNG_D_POLE1", 305: "MOBJ_DUNG_D_POLE2", 306: "RandDungWallSide01",
    307: "RandDungWallUp01", 308: "RandDungWallUp03", 309: "RandDungDoorSide01",
    310: "RandDungDoorUp01", 311: "RandDungWall_TREE01_SPRING",
    312: "RandDungWall_TREE01", 313: "RandDungWall_TREE01_AUTUMN",
    314: "RandDungWallI_TREE01_WINTER", 315: "RandDungWallUp05", 316: "RandDung03",
    317: "MOBJ_DUNG_D_POLE1_MAGIC", 318: "RandDungWallUp05_2", 319: "RandDungWallSide05",
    320: "MOBJ_DA00", 321: "MOBJ_DB00", 322: "MOBJ_DC00", 323: "MOBJ_DD00",
    324: "MOBJ_F02_01", 325: "MOBJ_F02_02", 326: "COLLECTION_76",
    327: "dummy2_038", 328: "dummy2_039", 329: "dummy2_040", 330: "dummy2_041",
    331: "dummy2_042", 332: "dummy2_043", 333: "dummy2_044", 334: "dummy2_045",
    335: "dummy2_011", 336: "OBJ_C06_SU_00", 337: "OBJ_C06_SU_01",
    338: "MOBJ_BRIDGE_CITY_04_00", 339: "MOBJ_BRIDGE_CITY_04_00_SUMMER",
    340: "MOBJ_BRIDGE_CITY_04_00_AUTUMN", 341: "MOBJ_BRIDGE_CITY_04_00_WINTER",
    342: "MOBJ_FID_BRIDGE", 343: "MOBJ_FID_FLOWER_00", 344: "MOBJ_FID_FLOWER_01",
    345: "MOBJ_FID_GRASS_00", 346: "MOBJ_FID_GRASS_01", 347: "MOBJ_GATE_FIELD_07_00",
    348: "MOBJ_GIMMICK_DUNG_B17_00", 349: "dummy2_012", 350: "dummy2_013",
    351: "MOBJ_ROAD_E_UPSTAIRS", 352: "MOBJ_FID_HOUSE02", 353: "MOBJ_FID_BRIDGE_OVER",
    354: "MOBJ_FI_TREE08", 355: "MOBJ_FI_TREE08_WINTER",
    356: "MOBJ_FI_TREE09_WINTER_dummy", 357: "MOBJ_FI_TREE09_WINTER_dummy2",
    358: "MOBJ_FI_TREE10", 359: "MOBJ_FI_TREE11", 360: "MOBJ_FIELD_43_FLOWER",
    361: "MOBJ_FIELD_44_FLOWER", 362: "MOBJ_FIELD_METAL03", 363: "MOBJ_FIELD_METAL04",
    364: "DUNG_C_isi00", 365: "DUNG_C_isi01", 366: "DUNG_C_isi02", 367: "DUNG_C_isi03",
    368: "DUNG_C_isi04", 369: "MOBJ_CITY_MARU", 370: "MOBJ_CITY_BATU",
    371: "MOBJ_FID_DUNG_LEFT", 372: "MOBJ_FID_DUNG_LEFT_WINTER",
    373: "MOBJ_FID_DUNG_RIGHT", 374: "MOBJ_FID_DUNG_RIGHT_WINTER",
    375: "MOBJ_FID_DUNG_DOWN", 376: "MOBJ_FID_DUNG_DOWN_WINTER",
    377: "OBJ_D_E05_WALL_BG", 378: "RandDungWallUp03_E05_BG",
    379: "MOBJ_FID_DUNG_LEFT_WINTER_UP", 380: "MOBJ_FID_DUNG_RIGHT_WINTER_UP",
    381: "MOBJ_FI_ICE01", 382: "MOBJ_FI_ICE02", 383: "MOBJ_FI_ICE03",
    384: "MOBJ_FI_ICE04", 385: "MOBJ_FID_SHADOW_00", 386: "MOBJ_FI_TREE08A",
    387: "MOBJ_ROAD_E_LEFT_OVER", 388: "MOBJ_ROAD_E_RIGHT_OVER",
    389: "MOBJ_FID_DUNG_LEFT_UP", 390: "MOBJ_HOUSE_CITY_04_00",
    391: "MOBJ_HOUSE_CITY_04_00_SUMMER", 392: "MOBJ_HOUSE_CITY_04_00_AUTUMN",
    393: "MOBJ_HOUSE_CITY_04_00_WINTER",
}

# Sprite names valid as MOBJ identities (type_id >= 20 only). The 0..19 entries in
# MAP_OBJ_BAND are not loaded by the trigger path, so they are excluded here.
MOBJ_NAMES: dict[int, str] = {t: n for t, n in MAP_OBJ_BAND.items()
                              if t >= FIRST_MAP_OBJ_TYPE}

# Human-readable descriptions for sprites whose names are opaque (mostly the "fe*"
# effect emitters and "gmk*" gimmicks). Keyed by sprite NAME so observations are easy
# to add. Sources: in-game observation (USER) + the ENGINE's per-type init table —
# g_mapObjTypeInitTable (RF4S.exe+0x228F530, one handler pointer per actor type
# 20..81, dispatched by MapObj_SetupActorByTypeId +0x147240; dumped 2026-08-31).
# Each entry cites its actor type id; the handler name is the identification.
MOBJ_NOTES: dict[str, str] = {
    # fe032 (type 20): street lamp. RE'd 2026-07-03 (MapObj_Init/TickStreetLight): warm-amber
    # glow (archive 2053), ON at night (16:00-05:59) with pulsing brightness, OFF in daytime.
    # Only per-instance param is f6=scale; no colour/angle/flag fields.
    "fe032": "street light (amber glow, on at night 16:00-05:59) — only param f6=scale",
    "fe033": "ambient sound emitter (type 21, MapObj_InitSoundEmitter)",
    "fe034": "ambient sound emitter, variant A (type 22)",
    "fe035": "ambient sound emitter, variant B (type 23)",
    "fe036": "FISHING SPOT — flag-gated fish spawn (type 24, Fishing_RegisterMapSpotIfFlagSet)",
    "fe037": "FISHING SPOT variant 1 — flag-gated (type 25, Fishing_RegisterMapSpotVariant1IfFlagSet)",
    "gmk00_eater":     "animated eater gimmick (type 26, Init/TickAnimatedEater)",
    "gmk01_bird":      "critter spawner: birds (type 27, Critter_TickAndSpawn_TypeA)",
    "gmk02_butterfly": "critter spawner: butterflies (type 28, Critter_TickAndSpawn_TypeB)",
    "gmk04_storm":     "storm hazard, damaging (type 29, MapObj_InitStormHazard)",
    "gmk05_storm":     "wind current zone — pushes the player (type 30, MapObj_InitWindCurrentZone)",
    # gmk06_rock (type 31): ceiling falling-rock trap that damages the player. RE'd 2026-07-02
    # (MapObj_Init/TickFallingRockHazard). Per-instance record fields: f7=facing (cosmetic),
    # f8=fall period, f9=scatter radius, f10=damage, f11=initial countdown/phase, f13=disable
    # game-flag id (0=always on). f1-6,f12 unused.
    "gmk06_rock": "falling-rock trap (dmg) — f8=period f9=radius f10=damage f11=start-delay f13=disable-flag",
    "gmk07_dummy":     "quake jitter — position shake (type 32, MapObj_InitQuakeJitter)",
    "gmk08_roll":      "rolling boulder hazard (type 33, MapObj_InitRollingBoulder)",
    "gmk09_water":     "water hazard, damaging (type 34, MapObj_InitWaterHazard)",
    "gmk10_mushroom":  "one-time item pickup (chance roll, herb/mushroom family), sets its flag when taken (type 35)",
    "gmk11_collection":"NPC-event-gated object (type 36, MapObj_InitNpcEventGatedObject)",
    "gmk12_redlight":  "red glow — pulsing light (type 37, MapObj_InitRedLightGlow)",
    "gmk13_bluelight": "blue glow — night light (type 38, MapObj_InitBlueLightGlow)",
    "gmk14_sunlight":  "swaying decoration — light shaft (type 39, MapObj_InitSwayingDecoration)",
    "gmk15_magiclight":"glowing decoration (type 40, MapObj_InitGlowingDecoration)",
    "gmk16_waterlight":"pulsing glow decoration (type 41, MapObj_InitPulsingGlowDecoration)",
    "gmk17_warp_effect":"WARP POINT (type 42, MapObj_InitWarpPoint)",
    "fe100":   "effect sprite by mode; modes 2/3 = the Norad Express airship propellers (type 43)",
    "fe101":   "flag-gated treasure (type 44, Actor_InitFlagGatedTreasure)",
    "fe102":   "flag-gated object, res 15289 (type 45, Actor_InitFlagGatedRes15289Object)",
    "fe102_2": "flag-gated interactive object (type 46, Actor_InitFlagGatedInteractiveObject)",
    "fe103":   "MONSTER GATE / seal door — barrier closed while the room's monsters live, opens + sets its flag when cleared (type 47)",
    "fe107":   "BARRIER — flag-gated barrier zone, blocks passage until its flag (type 48, MapObj_InitFlagGatedBarrierZone)",
    "fe104":   "ambient particle effect A (type 49)",
    "fe105":   "ambient particle effect B (type 50)",
    "MOBJ_SHIP":           "flag-gated large sprite effect, flowing-water/overlay style (type 51; the ship name is its sheet)",
    "MOBJ_FI_ERUPT_LAVA":  "CONVEYOR / forced-slide zone with the warp-swirl visual (type 52; the handler pushes, it does not teleport)",
    "MOBJ_BOX":            "breakable box — smashable crate dropping zone-pool loot (type 53; char 143 'Treasure' internally)",
    "MOBJ_FI_ERUPT":       "eruption hazard (type 54, MapObj_Init/TickEruptionHazard)",
    "fe106":   "eruption hazard (type 55, same handler as type 54)",
    "MOBJ_CHANDELIER":     "damaging hazard sprite — falling chandelier (type 56, MapObj_InitDamagingHazardSprite)",
    "MOBJ_FIELD_METAL02":  "MC sprite effect, res 2225 (type 57, MapObj_InitMCSpriteEffectRes2225)",
    "MOBJ_BOX_WINTER":     "flag-gated TRAVELING NPC spawn (type 58, Npc_InitFlagGatedTraveler)",
    "fe114":   "proximity trap / effect (type 59, MapObj_InitProximityTrapOrEffect)",
    "fe115":   "flag-gated decoration, random rotation (type 60, Actor_InitFlagGatedRandomRotDecoration)",
    "fe116":   "map-wide ambient particles (type 61, MapObj_InitMapWideAmbientParticles)",
    "fe117":   "sakura petal effect (type 62, MapObj_InitSakuraPetalEffect)",
    "fe118":   "flag-gated toggle switch (type 63, Actor_InitFlagGatedToggleSwitch)",
    "fe119":   "flag-gated treasure (type 64, MapEntity_InitFlagGatedTreasure)",
    "fe120":   "flag-gated treasure (type 65, same handler)",
    "fe121":   "flag-gated treasure (type 66, same handler)",
    "fe122":   "periodic effect emitter (type 67, MapObj_InitPeriodicEffectEmitter)",
    "fe123": "chimney smoke",   # USER 2026-06-24 + type 68 MapObj_Init/TickChimneySmoke
    "fe124":   "area particle emitter (type 69, MapObj_Init/TickAreaParticleEmitter)",
    "fe125":   "deferred effect spawn request (type 70, Effect_DeferredSpawnRequest_Tick)",
    "fe126":   "procedural mesh effect (type 71, MapObj_SpawnProceduralMeshEffect)",
    "fe127":   "rotated mesh effect (type 72, MapObj_SpawnRotatedMeshEffect)",
    "fe128":   "inert — no init handler (type 73)",
    # types 74..77 (MOBJ_FI_ICE0x_dummy): no handler — inert placeholders.
    "MOBJ_ROAD_E_UP":    "decoration spawn trigger, road edge up (type 78, Decoration_OnSpawnTrigger)",
    "MOBJ_ROAD_E_RIGHT": "decoration spawn trigger, road edge right (type 79)",
    "MOBJ_ROAD_E_DOWN":  "decoration spawn trigger, road edge down (type 80)",
    "MOBJ_ROAD_E_LEFT":  "decoration spawn trigger, road edge left (type 81)",
    # fe023..fe031_10 (band slots 0..19) are effect-band SPRITES only: MOBJ type ids
    # 0..19 never load the map_obj band (forage directives / map parameters), so those sheets
    # are pulled by id from other systems, not by placed map objects.
}


def mobj_kind(type_id: int) -> str:
    """Spawn-dispatch class for a MOBJ type_id (see Map_SpawnAllEntities)."""
    t = type_id & 0xFFFF
    if t < 9:
        return "forage"       # Map_HandleSpecialTriggerEntity daily gatherable directive
    if t < 20:
        return "mapparam"     # load-time map parameter (Map_LoadById's MapEvent switch)
    if t < 196:
        return "actor"        # category map_obj_id, task id = type_id+1000
    if t < 336:
        return "object"       # Map_SpawnInteractiveObject
    return "decoration"       # MapDecoration_Spawn


def mobj_archive_id(type_id: int) -> int:
    """map_obj archive id loaded for this type_id (type_id + 17542).

    Only meaningful for type_id >= 20 (the map_obj sprite-loading range)."""
    return (type_id & 0xFFFF) + MAP_OBJ_ARCHIVE_BASE


def mobj_name(type_id: int) -> str | None:
    """Return the map_obj sprite name for a type_id, or None when the record does not
    load a map_obj sprite (type_id < 20: forage directive / map parameter record)."""
    return MOBJ_NAMES.get(type_id & 0xFFFF)


def mobj_filename(type_id: int) -> str | None:
    """Return the full `rom:/map_obj/<NAME>.bntx` path, or None if no map_obj sprite."""
    n = mobj_name(type_id)
    return f"rom:/map_obj/{n}.bntx" if n else None


def mobj_note(type_id: int) -> str | None:
    """Return a human description of what this sprite is (e.g. 'chimney smoke'), or
    None if undocumented. Keyed off the sprite name via MOBJ_NOTES."""
    n = mobj_name(type_id)
    return MOBJ_NOTES.get(n) if n else None


def mobj_display_name(type_id: int) -> str | None:
    """READABLE name for UI lists: for identified types (the fe*/gmk* actor band)
    the note's leading phrase — cut at the earliest of " — " / " (" — so the
    opaque sprite codename disappears from displays ("fe107" -> "BARRIER",
    "gmk01_bird" -> "critter spawner: birds"). Unidentified sprites keep their
    (already readable) MOBJ_* name; None when the type loads no map_obj sprite.
    The codename itself stays available via mobj_name() for technical readouts."""
    n = mobj_name(type_id)
    if not n:
        # Forage lane 0..8 loads no map_obj sprite (daily spawn directives; the
        # visible thing comes from the crop archive per day), but it HAS an
        # identity — use the params registry's forage names so editors can show
        # and pick these records like any other type (2026-09-01; they used to
        # fall out of every list). Lazy import: mobj_params imports nothing
        # from this module at top level, so no cycle.
        if 0 <= (type_id & 0xFFFF) <= 8:
            from .mobj_params import FORAGE
            e = FORAGE.get(type_id & 0xFFFF)
            if e:
                return e["name"]
        # Map parameter records 9..19 (tint colours, UV scroll, ...): named in the
        # params registry too (2026-09-19; they used to show as "type N").
        if 9 <= (type_id & 0xFFFF) <= 19:
            from .mobj_params import MAP_PARAMS
            e = MAP_PARAMS.get(type_id & 0xFFFF)
            if e:
                return e["name"]
        return None
    note = MOBJ_NOTES.get(n)
    if not note:
        return n
    cuts = [i for i in (note.find(" — "), note.find(" (")) if i > 0]
    short = note[:min(cuts)] if cuts else note
    short = short.strip().rstrip(",.")
    return short or n


def mobj_label(type_id: int) -> str:
    """Human label combining the identification (readable name / full note) and the
    spawn kind. Identified types lead with their NOTE (which starts with the
    readable identity and carries the type id + handler), not the fe*/gmk*
    codename — that lives in mobj_name() for technical views."""
    n = mobj_name(type_id)
    kind = mobj_kind(type_id)
    if n:
        note = MOBJ_NOTES.get(n)
        return f"{note} [{kind}]" if note else f"{n} [{kind}]"
    if kind == "forage":
        return f"type {type_id} [forage — daily gatherable, sprite via crop pool]"
    if kind == "mapparam":
        from .mobj_params import MAP_PARAMS
        e = MAP_PARAMS.get(type_id & 0xFFFF)
        role = e["role"] if e else "no case in Map_LoadById — ignored"
        return f"type {type_id} [map parameter — {role}]"
    return f"type {type_id} [{kind}]"
