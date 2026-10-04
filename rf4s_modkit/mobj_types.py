"""MOBJ type_id -> map-object identity table.

A `.rf4m` map's MOBJ chunk holds 64-byte entity records whose first dword is a
`type_id`. RF4S spawns each record through one of four paths (see
`Map_SpawnAllEntities` @ RF4S.exe+0x13FE70), but EVERY path that draws a sprite
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
# g_mapObjTypeInitTable (RF4S.exe+0x4CF530, one handler pointer per actor type
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
    "gmk01_bird":      "critter spawner: birds (type 27, Critter_InitBirdOrDespawn)",
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
    "gmk10_mushroom":  "one-time mushroom pickup (chance roll; drops a Mushroom, items 48..53), sets its flag when taken (type 35)",
    "gmk11_collection":"NPC-event-gated object (type 36, MapObj_InitNpcEventGatedObject)",
    "gmk12_redlight":  "red glow — pulsing light (type 37, MapObj_InitRedLightGlow)",
    "gmk13_bluelight": "blue glow — night light (type 38, MapObj_InitBlueLightGlow)",
    "gmk14_sunlight":  "swaying decoration — light shaft (type 39, MapObj_InitSwayingDecoration)",
    "gmk15_magiclight":"glowing decoration (type 40, MapObj_InitGlowingDecoration)",
    "gmk16_waterlight":"pulsing glow decoration (type 41, MapObj_InitPulsingGlowDecoration)",
    "gmk17_warp_effect":"WARP POINT (type 42, MapObj_InitWarpPoint)",
    "fe100":   "windmill blades / airship propeller by word 8: 0 gmk18_windmill, 1 gmk19_windmill, 2 / 3 the airship's propeller_ship_01 / 02 (type 43)",
    "fe101":   "flag-gated treasure (type 44, Actor_InitFlagGatedTreasure)",
    "fe102":   "colour switch: pillar with a crystal, colour = word 8 & 7 (switch_00..07), frame follows its flag (type 45, Actor_InitFlagGatedRes15289Object)",
    "fe102_2": "floor switch: interacting sets / clears its game flag, texture floor_switch "
               "(frame 1 once the flag is set) (type 46, Actor_InitFlagGatedInteractiveObject)",
    "fe103":   "MONSTER GATE / seal door — barrier closed while the room's monsters live, opens + sets its flag when cleared (type 47)",
    "fe107":   "BARRIER — flag-gated barrier zone, blocks passage until its flag (type 48, MapObj_InitFlagGatedBarrierZone)",
    "fe104":   "ambient particle effect A (type 49)",
    "fe105":   "ambient particle effect B (type 50)",
    "MOBJ_SHIP":           "the airship, shown while its flag allows (type 51, Actor_InitFlagGatedMCSpriteEffect, texture MOBJ_SHIP)",
    "MOBJ_FI_ERUPT_LAVA":  "vent knockback zone (no sprite of its own; placed at the eruption vents): stepping on it staggers the player (hit sound + hit reaction, drops what they "
                           "carry) and walks them off it; no HP damage; puffs smoke (type 52)",
    "MOBJ_BOX":            "breakable crate dropping zone-pool loot: wooden (MOBJ_BOX), or metal (MOBJ_FIELD_METAL02) when word 8 is set (type 53, MapEntity_SpawnTreasure)",
    "MOBJ_FI_ERUPT":       "eruption vent: erupts periodically and damages (word 9 = attack); lava vent MOBJ_FI_ERUPT_LAVA, or stone crater MOBJ_FI_ERUPT when word 10 is set (type 54, MapObj_Init/TickEruptionHazard)",
    "fe106":   "eruption vent (type 55, same handler as type 54)",
    "MOBJ_CHANDELIER":     "chandelier: always sways; with word 8 set it falls once the player or a party member moves within 26 sub-units left / right of it, and hurts (attack 210 + word 9); with word 8 = 0 it never falls and its hitbox stays off (type 56, MapObj_InitDamagingHazardSprite)",
    "MOBJ_FIELD_METAL02":  "portrait (texture portrait): with word 8 set its eyes follow the player left / right (type 57, MapObj_InitMCSpriteEffectRes2225; the MOBJ_FIELD_METAL02 name is only its archive slot)",
    "MOBJ_BOX_WINTER":     "flag-gated TRAVELING NPC spawn (type 58, Npc_InitFlagGatedTraveler)",
    "fe114":   "Wooly doll (texture FURNITURE_21); with word 8 set an invisible proximity trap instead (type 59, MapObj_InitProximityTrapOrEffect)",
    "fe115":   "flag-gated decoration, random rotation (type 60, Actor_InitFlagGatedRandomRotDecoration)",
    "fe116":   "map-wide ambient particles (type 61, MapObj_InitMapWideAmbientParticles)",
    "fe117":   "sakura petal effect (type 62, MapObj_InitSakuraPetalEffect)",
    "fe118":   "flag-gated toggle switch (type 63, Actor_InitFlagGatedToggleSwitch)",
    "fe119":   "theatre furniture: small table, texture FURNITURE_01 (type 64, "
               "MapEntity_InitFlagGatedTreasure; static, removed once its gate flag is set)",
    "fe120":   "theatre furniture: large table, texture FURNITURE_02 (type 65, same handler)",
    "fe121":   "theatre furniture: chair, texture FURNITURE_11 (type 66, same handler)",
    "fe122":   "periodic effect emitter (type 67, MapObj_InitPeriodicEffectEmitter)",
    "fe123": "chimney smoke",   # USER 2026-06-24 + type 68 MapObj_Init/TickChimneySmoke
    "fe124":   "area particle emitter (type 69, MapObj_Init/TickAreaParticleEmitter)",
    "fe125":   "light shafts: sunlight fan mesh with texture RE_VLIGHT2, shape by word 8 (15 kinds, 1 = 0 mirrored); daytime in clear weather only (type 70, Effect_SpawnWorldSpriteByType)",
    "fe126":   "water surface: a flowing waterA mesh, shape by word 8 (22 kinds) (type 71, MapObj_SpawnProceduralMeshEffect)",
    "fe127":   "room overlay mesh: the palace hall drawn over the room with texture F_ROOM00 (word 8 = 1: F_ROOM00_WINTER) (type 72, MapObj_SpawnRotatedMeshEffect)",
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


# Readable names for every map_obj sprite type (2026-09-26): from the sprite itself (each
# type's texture rendered and looked at), the maps it is placed on, and for doors the warp it
# stands at (its destination's in-game name; generic 'House' rooms by their room file).
# Effect / gimmick types 20..81 draw no sprite of their own and are named by what their
# handler does (MOBJ_NOTES has the detail). '(unused)' = no shipped map places the type AND
# no rf3.mc scene spawns it (SpawnMapEntity, op 157): the Sharance Maze entrance (326), for
# one, exists only through its Trophy Room scene.
# mobj_display_name() prefers these; the codenames stay in MOBJ_NAMES for technical views.
MOBJ_DISPLAY: dict[int, str] = {
    20: "street light",  # fe032
    21: "ambient sound",  # fe033
    22: "ambient sound A",  # fe034
    23: "ambient sound B",  # fe035
    24: "fishing spot",  # fe036
    25: "fishing spot 2 (unused)",  # fe037
    26: "eater plant",  # gmk00_eater
    27: "birds",  # gmk01_bird
    28: "butterflies",  # gmk02_butterfly
    29: "storm hazard",  # gmk04_storm
    30: "wind current",  # gmk05_storm
    31: "falling-rock trap",  # gmk06_rock
    32: "quake shake (unused)",  # gmk07_dummy
    33: "rolling boulder (unused)",  # gmk08_roll
    34: "water hazard (unused)",  # gmk09_water
    35: "mushroom pickup",  # gmk10_mushroom
    36: "NPC-event object",  # gmk11_collection
    37: "red glow",  # gmk12_redlight
    38: "blue glow (unused)",  # gmk13_bluelight
    39: "light shaft (unused)",  # gmk14_sunlight
    40: "magic glow (unused)",  # gmk15_magiclight
    41: "water glow (unused)",  # gmk16_waterlight
    42: "warp point",  # gmk17_warp_effect
    43: "windmill / propeller",  # fe100
    44: "treasure chest",  # fe101
    45: "colour switch",  # fe102
    46: "floor switch",  # fe102_2
    47: "seal door",  # fe103
    48: "barrier",  # fe107
    49: "ambient particles A",  # fe104
    50: "ambient particles B",  # fe105
    51: "airship",  # MOBJ_SHIP
    52: "knockback zone",  # MOBJ_FI_ERUPT_LAVA
    53: "crate",  # MOBJ_BOX
    54: "eruption vent (unused)",  # MOBJ_FI_ERUPT
    55: "eruption vent",  # fe106
    56: "chandelier",  # MOBJ_CHANDELIER
    57: "portrait",  # MOBJ_FIELD_METAL02
    58: "travelling NPC",  # MOBJ_BOX_WINTER
    59: "Wooly doll",  # fe114
    60: "pond",  # fe115
    61: "map-wide particles",  # fe116
    62: "sakura petals",  # fe117
    63: "toggle floor switch",  # fe118
    64: "small theatre table",  # fe119
    65: "large theatre table",  # fe120
    66: "theatre chair",  # fe121
    67: "effect emitter",  # fe122
    68: "chimney smoke",  # fe123
    69: "particle emitter",  # fe124
    70: "light shafts",  # fe125
    71: "water surface",  # fe126
    72: "room overlay mesh",  # fe127
    73: "unused slot",  # fe128
    74: "ice patch 1 (placeholder)",  # MOBJ_FI_ICE01_dummy
    75: "ice patch 2 (placeholder)",  # MOBJ_FI_ICE02_dummy
    76: "ice patch 3 (placeholder)",  # MOBJ_FI_ICE03_dummy
    77: "ice patch 4 (placeholder)",  # MOBJ_FI_ICE04_dummy
    78: "Floating Empire walkway edge ↑",  # MOBJ_ROAD_E_UP
    79: "Floating Empire walkway edge →",  # MOBJ_ROAD_E_RIGHT
    80: "Floating Empire walkway edge ↓",  # MOBJ_ROAD_E_DOWN
    81: "Floating Empire walkway edge ←",  # MOBJ_ROAD_E_LEFT
    82: "door: Bell Hotel Lobby",  # DOOR_CITY_00_00
    83: "door: Bell Hotel Lobby (summer)",  # DOOR_CITY_00_00_SUMMER
    84: "door: Bell Hotel Lobby (autumn)",  # DOOR_CITY_00_00_AUTUMN
    85: "door: Bell Hotel Lobby (winter)",  # DOOR_CITY_00_00_WINTER
    86: "door: Porcoline's Kitchen",  # DOOR_CITY_00_01
    87: "door: Porcoline's Kitchen (summer)",  # DOOR_CITY_00_01_SUMMER
    88: "door: Farm (autumn)",  # DOOR_CITY_00_01_AUTUMN
    89: "door: Porcoline's Kitchen (winter)",  # DOOR_CITY_00_01_WINTER
    90: "door: Sainte-Coquille Manor",  # DOOR_CITY_00_02
    91: "door: Sainte-Coquille Manor (summer)",  # DOOR_CITY_00_02_SUMMER
    92: "door: Sainte-Coquille Manor (autumn)",  # DOOR_CITY_00_02_AUTUMN
    93: "door: Sainte-Coquille Manor (winter)",  # DOOR_CITY_00_02_WINTER
    94: "door: Selphia: Observatory",  # DOOR_CITY_00_03
    95: "door: Selphia: Observatory (summer)",  # DOOR_CITY_00_03_SUMMER
    96: "door: Selphia: Observatory (autumn)",  # DOOR_CITY_00_03_AUTUMN
    97: "door: Selphia: Observatory (winter)",  # DOOR_CITY_00_03_WINTER
    98: "door: house (room 10)",  # DOOR_CITY_01_00
    99: "door: house (room 10) (summer)",  # DOOR_CITY_01_00_SUMMER
    100: "door: house (room 10) (autumn)",  # DOOR_CITY_01_00_AUTUMN
    101: "door: house (room 10) (winter)",  # DOOR_CITY_01_00_WINTER
    102: "door: Forte's House",  # DOOR_CITY_01_01
    103: "door: Forte's House (summer)",  # DOOR_CITY_01_01_SUMMER
    104: "door: Forte's House (autumn)",  # DOOR_CITY_01_01_AUTUMN
    105: "door: Forte's House (winter)",  # DOOR_CITY_01_01_WINTER
    106: "door: Blacksmith ”Meanderer”",  # DOOR_CITY_01_02
    107: "door: Blacksmith ”Meanderer” (summer)",  # DOOR_CITY_01_02_SUMMER
    108: "door: Blacksmith ”Meanderer” (autumn)",  # DOOR_CITY_01_02_AUTUMN
    109: "door: Blacksmith ”Meanderer” (winter)",  # DOOR_CITY_01_02_WINTER
    110: "door: Tiny Bandage Clinic",  # DOOR_CITY_01_03
    111: "door: Tiny Bandage Clinic (summer)",  # DOOR_CITY_01_03_SUMMER
    112: "door: Tiny Bandage Clinic (autumn)",  # DOOR_CITY_01_03_AUTUMN
    113: "door: Tiny Bandage Clinic (winter)",  # DOOR_CITY_01_03_WINTER
    114: "door: Sincerity General Store",  # DOOR_CITY_02_00
    115: "door: Sincerity General Store (summer)",  # DOOR_CITY_02_00_SUMMER
    116: "door: Sincerity General Store (autumn)",  # DOOR_CITY_02_00_AUTUMN
    117: "door: Sincerity General Store (winter)",  # DOOR_CITY_02_00_WINTER
    118: "door: Margaret's House",  # DOOR_CITY_02_01
    119: "door: Margaret's House (summer)",  # DOOR_CITY_02_01_SUMMER
    120: "door: Margaret's House (autumn)",  # DOOR_CITY_02_01_AUTUMN
    121: "door: Margaret's House (winter)",  # DOOR_CITY_02_01_WINTER
    122: "door: Carnation's",  # DOOR_CITY_02_02
    123: "door: Carnation's (summer)",  # DOOR_CITY_02_02_SUMMER
    124: "door: Carnation's (autumn)",  # DOOR_CITY_02_02_AUTUMN
    125: "door: Carnation's (winter)",  # DOOR_CITY_02_02_WINTER
    126: "door: house (room 11)",  # DOOR_CITY_02_03
    127: "door: house (room 11) (summer)",  # DOOR_CITY_02_03_SUMMER
    128: "door: house (room 11) (autumn)",  # DOOR_CITY_02_03_AUTUMN
    129: "door: house (room 11) (winter)",  # DOOR_CITY_02_03_WINTER
    130: "door: Selphia: Airship Way",  # DOOR_CITY_03_00
    131: "door: Selphia: Airship Way (summer)",  # DOOR_CITY_03_00_SUMMER
    132: "door: Selphia: Airship Way (autumn)",  # DOOR_CITY_03_00_AUTUMN
    133: "door: Selphia: Airship Way (winter)",  # DOOR_CITY_03_00_WINTER
    134: "door: Dragon Lake 1 (unused)",  # DOOR_CITY_04_00
    135: "door: Dragon Lake 1 (summer, unused)",  # DOOR_CITY_04_00_SUMMER
    136: "door: Dragon Lake 1 (autumn, unused)",  # DOOR_CITY_04_00_AUTUMN
    137: "door: Dragon Lake 1 (winter, unused)",  # DOOR_CITY_04_00_WINTER
    138: "door: Obsidian Mnsn. Theatre",  # DOOR_CITY_04_01
    139: "door: Obsidian Mnsn. Theatre (summer)",  # DOOR_CITY_04_01_SUMMER
    140: "door: Obsidian Mnsn. Theatre (autumn)",  # DOOR_CITY_04_01_AUTUMN
    141: "door: Obsidian Mnsn. Theatre (winter)",  # DOOR_CITY_04_01_WINTER
    142: "door: Castle Gate (unused)",  # DOOR_CITY_05_00
    143: "door: Castle Gate (summer, unused)",  # DOOR_CITY_05_00_SUMMER
    144: "door: Castle Gate (autumn, unused)",  # DOOR_CITY_05_00_AUTUMN
    145: "door: Castle Gate (winter, unused)",  # DOOR_CITY_05_00_WINTER
    146: "door: Butler's Room",  # DOOR_CITY_06_00
    147: "door: Butler's Room (summer)",  # DOOR_CITY_06_00_SUMMER
    148: "door: Butler's Room (autumn)",  # DOOR_CITY_06_00_AUTUMN
    149: "door: Butler's Room (winter)",  # DOOR_CITY_06_00_WINTER
    150: "door: Town Square 2 (unused)",  # DOOR_CITY_06_01
    151: "door: Town Square 2 (summer, unused)",  # DOOR_CITY_06_01_SUMMER
    152: "door: Town Square 2 (autumn, unused)",  # DOOR_CITY_06_01_AUTUMN
    153: "door: Town Square 2 (winter, unused)",  # DOOR_CITY_06_01_WINTER
    154: "door: Your Room",  # DOOR_CITY_06_02
    155: "door: Your Room (summer)",  # DOOR_CITY_06_02_SUMMER
    156: "door: Your Room (autumn)",  # DOOR_CITY_06_02_AUTUMN
    157: "door: Your Room (winter)",  # DOOR_CITY_06_02_WINTER
    158: "door: Bell Bath (and Beyond) 1",  # DOOR_ROOM_06A_00
    159: "door: Bell Bath (and Beyond) 2",  # DOOR_ROOM_06A_01
    160: "door: Bell Hotel Residence",  # DOOR_ROOM_06A_02
    161: "door: Obsidian Mnsn. Entrance",  # DOOR_DUNG_C01_00
    162: "Obsidian Mansion door (C03 → C04)",  # DOOR_DUNG_C03_00
    163: "Obsidian Mansion door (C04 → C05)",  # DOOR_DUNG_C04_00
    164: "Obsidian Mansion door (C04 → C07)",  # DOOR_DUNG_C04_01
    165: "Obsidian Mansion door (C05 → C06)",  # DOOR_DUNG_C05_00
    166: "Obsidian Mansion door (C06 → C05)",  # DOOR_DUNG_C06_00
    167: "Obsidian Mansion door (C07 → C06)",  # DOOR_DUNG_C07_00
    168: "Obsidian Mansion door (C07 → C04)",  # DOOR_DUNG_C07_01
    169: "Obsidian Mansion door (C07 → C08)",  # DOOR_DUNG_C07_02
    170: "Obsidian Mansion door (C08 → C07)",  # DOOR_DUNG_C08_00
    171: "Obsidian Mansion door (C08 → C09)",  # DOOR_DUNG_C08_01
    172: "Obsidian Mansion door (C09 → C10)",  # DOOR_DUNG_C09_00
    173: "Obsidian Mansion door (C09 → C08)",  # DOOR_DUNG_C09_01
    174: "Obsidian Mansion door (C13 → C12)",  # DOOR_DUNG_C13_00
    175: "Obsidian Mansion door (C13 → C14)",  # DOOR_DUNG_C13_01
    176: "Obsidian Mansion door (C14 → C13)",  # DOOR_DUNG_C14_00
    177: "Obsidian Mansion door (C14 → C15)",  # DOOR_DUNG_C14_01
    178: "Obsidian Mansion door (C15 → C16)",  # DOOR_DUNG_C15_00
    179: "Obsidian Mansion door (C15 → C14)",  # DOOR_DUNG_C15_01
    180: "Obsidian Mansion door (C15 → C18)",  # DOOR_DUNG_C15_02
    181: "Obsidian Mansion door (C16 → C17)",  # DOOR_DUNG_C16_00
    182: "Obsidian Mansion door (C17 → C16)",  # DOOR_DUNG_C17_00
    183: "Obsidian Mansion door (C18 → C17)",  # DOOR_DUNG_C18_00
    184: "Obsidian Mansion door (C18 → C15)",  # DOOR_DUNG_C18_01
    185: "door: Rune Prana / ??? entrance",  # DOOR_DUNG_D01_00
    186: "door: field house 1 (unused)",  # MOBJ_DOOR_FIELD_11_00
    187: "door: field house (rooms 15 / 16 / 17)",  # MOBJ_DOOR_FIELD_21_00
    188: "door: field house 3 (unused)",  # MOBJ_DOOR_FIELD_31_00
    189: "door: field house (room 20)",  # MOBJ_DOOR_FIELD_41_00
    190: "Obsidian Mansion door (C19 → Theatre)",  # DOOR_DUNG_C19_00
    191: "door (dummy 2, unused)",  # MOBJ_DOOR_DUMMY02
    192: "door (dummy 3, unused)",  # MOBJ_DOOR_DUMMY03
    193: "door (dummy 4, unused)",  # MOBJ_DOOR_DUMMY04
    194: "water splash 1 (unused)",  # fe_splash01
    195: "water splash 2 (unused)",  # fe_splash02
    196: "water splash 3 (unused)",  # fe_splash03
    197: "mossy rock spire (unused)",  # MOBJ_FI_ROCK01
    198: "sapling",  # MOBJ_FID_TREE_00
    199: "tree 1",  # MOBJ_FI_TREE01
    200: "tree 1 (spring)",  # MOBJ_FI_TREE01_SPRING
    201: "tree 1 (autumn)",  # MOBJ_FI_TREE01_AUTUMN
    202: "tree 1 (winter)",  # MOBJ_FI_TREE01_WINTER
    203: "stump with mushrooms",  # MOBJ_FI_TREE02
    204: "stump with mushrooms (winter)",  # MOBJ_FI_TREE02_WINTER
    205: "tree 3",  # MOBJ_FI_TREE03
    206: "tree 3 (autumn)",  # MOBJ_FI_TREE03_AUTUMN
    207: "tree 3 (winter)",  # MOBJ_FI_TREE03_WINTER
    208: "tree 4",  # MOBJ_FI_TREE04
    209: "tree 4 (autumn)",  # MOBJ_FI_TREE04_AUTUMN
    210: "tree 4 (winter)",  # MOBJ_FI_TREE04_WINTER
    211: "tree stump",  # MOBJ_FI_TREE06
    212: "tree stump (winter)",  # MOBJ_FI_TREE06_WINTER
    213: "pit (dark)",  # MOBJ_FID_CRACK03
    214: "crystal cluster",  # MOBJ_FID_CRYSTAL_M01
    215: "crystal",  # MOBJ_FID_CRYSTAL_S01
    216: "wooden house (unused)",  # MOBJ_FID_HOUSE01
    217: "ruin pillar",  # MOBJ_FID_ISEKI01
    218: "carved floor slab",  # MOBJ_FID_ISEKI02
    219: "stairs down",  # MOBJ_FID_KAIDAN_DOWN02
    220: "stairs up",  # MOBJ_FID_KAIDAN_UP02
    221: "spring pool",  # MOBJ_FID_MIZUBA01
    222: "hot spring (unused)",  # MOBJ_FID_ONSEN01
    223: "cave boulder",  # MOBJ_FID_ROCK01
    224: "glowing crystal rock",  # MOBJ_FID_ROCK02
    225: "rock spire",  # MOBJ_FID_ROCK03
    226: "stalagmite",  # MOBJ_FID_ROCK04
    227: "cave wall ↑",  # MOBJ_FID_WALL_up
    228: "cave wall →",  # MOBJ_FID_WALL_right
    229: "cave wall ↓",  # MOBJ_FID_WALL_down
    230: "cave wall ←",  # MOBJ_FID_WALL_left
    231: "Maya Road ice path 1",  # MOBJ_E05_ROAD01
    232: "Maya Road ice path 2",  # MOBJ_E05_ROAD02
    233: "Maya Road ice path 3",  # MOBJ_E05_ROAD03
    234: "Maya Road ice path 4",  # MOBJ_E05_ROAD04
    235: "ice stone 1",  # MOBJ_FI_STONE01_E05
    236: "ice stone 2",  # MOBJ_FI_STONE02_E05
    237: "ice hole 1 (unused)",  # MOBJ_E05_HOLE03
    238: "ice hole 2 (unused)",  # MOBJ_E05_HOLE04
    239: "ice wall (cracked)",  # OBJ_D_E05_WALL
    240: "ice stairs down",  # MOBJ_FID_KAIDAN_DOWN03
    241: "ice stalagmite",  # MOBJ_FI_ROCK04_E05
    242: "ice boulder",  # MOBJ_FI_ROCK05_E05
    243: "ice rock spire",  # MOBJ_FI_ROCK06_E05
    244: "ice slab",  # MOBJ_FI_ROCK09_E05
    245: "ice rock",  # MOBJ_FI_ROCK10_E05
    246: "ice rock wall",  # RandDungWallUp03_E05
    247: "giant mushroom",  # MOBJ_FI_MUSHROOM01
    248: "giant mushroom (winter)",  # MOBJ_FI_MUSHROOM01_WINTER
    249: "pit",  # MOBJ_FID_CRACK02
    250: "stalagmite (sand)",  # MOBJ_FI_ROCK04
    251: "stalagmite (winter)",  # MOBJ_FI_ROCK04_WINTER
    252: "boulder",  # MOBJ_FI_ROCK05
    253: "boulder (winter)",  # MOBJ_FI_ROCK05_WINTER
    254: "rock spire (sand)",  # MOBJ_FI_ROCK06
    255: "rock spire (winter)",  # MOBJ_FI_ROCK06_WINTER
    256: "stone 1",  # MOBJ_FI_STONE01
    257: "stone 1 (winter)",  # MOBJ_FI_STONE01_WINTER
    258: "stone 2",  # MOBJ_FI_STONE02
    259: "stone 2 (winter)",  # MOBJ_FI_STONE02_WINTER
    260: "mossy rock spire",  # MOBJ_FID_ROCK05
    261: "mossy rock spire 2 (unused)",  # MOBJ_FID_ROCK06
    262: "invisible wall",  # MOBJ_CLEAR_WALL
    263: "inscribed stone",  # MOBJ_SW_WALL_00
    264: "ground crack 1",  # MOBJ_FIELD_HIBI01
    265: "ground crack 2",  # MOBJ_FIELD_HIBI02
    266: "ground crack 3",  # MOBJ_FIELD_HIBI03
    267: "ground crack 4",  # MOBJ_FIELD_HIBI04
    268: "ground crack 5",  # MOBJ_FIELD_HIBI05
    269: "giant mushroom 2 (unused)",  # MOBJ_FI_MUSHROOM02
    270: "giant mushroom 2 (winter)",  # MOBJ_FI_MUSHROOM02_WINTER
    271: "mossy rock on grass",  # MOBJ_FID_GROUND_00
    272: "final boss wall 1 (unused)",  # MOBJ_LAST_BOSS_WALL_0
    273: "final boss wall 2 (unused)",  # MOBJ_LAST_BOSS_WALL_1
    274: "mushroom (unused)",  # MOBJ_FI_MUSHROOM03
    275: "mushroom (winter)",  # MOBJ_FI_MUSHROOM03_WINTER
    276: "lava stone 1",  # MOBJ_FI_STONE01_LAVA
    277: "lava stone 2",  # MOBJ_FI_STONE02_LAVA
    278: "lava stalagmite",  # MOBJ_FI_ROCK04_LAVA
    279: "lava boulder",  # MOBJ_FI_ROCK05_LAVA
    280: "lava rock spire",  # MOBJ_FI_ROCK06_LAVA
    281: "tree 3 (spring)",  # MOBJ_FI_TREE03_SPRING
    282: "tree 4 (spring)",  # MOBJ_FI_TREE04_SPRING
    283: "tree stump 2",  # MOBJ_FI_TREE07
    284: "tree stump 2 (winter)",  # MOBJ_FI_TREE07_WINTER
    285: "snowman",  # MOBJ_FI_SNOWMAN
    286: "red crystal wall",  # RandDungWallUp04
    287: "mossy cliff (unused)",  # MOBJ_FI_ROCK07
    288: "mossy rock slab (unused)",  # MOBJ_FI_ROCK08
    289: "flat rock",  # MOBJ_FI_ROCK09
    290: "rock (unused)",  # MOBJ_FI_ROCK10
    291: "metal pole",  # MOBJ_FIELD_METAL01
    292: "flat rock (cave)",  # MOBJ_FI_ROCK09_DUNG
    293: "rock (cave)",  # MOBJ_FI_ROCK10_DUNG
    294: "airship gangway",  # MOBJ_SHIP_BRIDGE
    295: "carved stone block",  # MOBJ_E01_BLOCK01
    296: "bush (winter)",  # MOBJ_FI_TREE09_WINTER
    297: "ruin pillar (winter)",  # MOBJ_FID_ISEKI01_WINTER
    298: "Floating Empire door",  # OBJ_D_E02_door
    299: "carved stone block (mossy)",  # MOBJ_E01_CENTER
    300: "carved stone block (spiked)",  # MOBJ_E03_CENTER
    301: "fallen log",  # MOBJ_FI_TREE20
    302: "hollow stump",  # MOBJ_FI_TREE21
    303: "fallen tree",  # MOBJ_FI_TREE22
    304: "Leon Karnak pillar (short)",  # MOBJ_DUNG_D_POLE1
    305: "Leon Karnak pillar (tall)",  # MOBJ_DUNG_D_POLE2
    306: "Rune Prana wall (side)",  # RandDungWallSide01
    307: "Rune Prana wall",  # RandDungWallUp01
    308: "pink rock pillar",  # RandDungWallUp03
    309: "Rune Prana door (side)",  # RandDungDoorSide01
    310: "Rune Prana door",  # RandDungDoorUp01
    311: "Rune Prana tree wall (spring)",  # RandDungWall_TREE01_SPRING
    312: "Rune Prana tree wall",  # RandDungWall_TREE01
    313: "Rune Prana tree wall (autumn)",  # RandDungWall_TREE01_AUTUMN
    314: "Rune Prana tree wall (winter)",  # RandDungWallI_TREE01_WINTER
    315: "green stump wall",  # RandDungWallUp05
    316: "pink rock pillar 2",  # RandDung03
    317: "Rune Prana pillar",  # MOBJ_DUNG_D_POLE1_MAGIC
    318: "green stump",  # RandDungWallUp05_2
    319: "green stump (small)",  # RandDungWallSide05
    320: "dungeon gate (green)",  # MOBJ_DA00
    321: "dungeon gate (sand, unused)",  # MOBJ_DB00
    322: "dungeon gate (olive, unused)",  # MOBJ_DC00
    323: "dungeon gate (blue, unused)",  # MOBJ_DD00
    324: "overhanging foliage 1",  # MOBJ_F02_01
    325: "overhanging foliage 2",  # MOBJ_F02_02
    326: "Sharance Maze entrance",  # COLLECTION_76
    327: "unused slot",  # dummy2_038
    328: "unused slot",  # dummy2_039
    329: "unused slot",  # dummy2_040
    330: "unused slot",  # dummy2_041
    331: "unused slot",  # dummy2_042
    332: "unused slot",  # dummy2_043
    333: "unused slot",  # dummy2_044
    334: "unused slot",  # dummy2_045
    335: "unused slot",  # dummy2_011
    336: "painted sign (unused)",  # OBJ_C06_SU_00
    337: "stone rim (unused)",  # OBJ_C06_SU_01
    338: "Dragon Lake bridge",  # MOBJ_BRIDGE_CITY_04_00
    339: "Dragon Lake bridge (summer)",  # MOBJ_BRIDGE_CITY_04_00_SUMMER
    340: "Dragon Lake bridge (autumn)",  # MOBJ_BRIDGE_CITY_04_00_AUTUMN
    341: "Dragon Lake bridge (winter)",  # MOBJ_BRIDGE_CITY_04_00_WINTER
    342: "wooden trestle bridge",  # MOBJ_FID_BRIDGE
    343: "flower (pink)",  # MOBJ_FID_FLOWER_00
    344: "flowers (yellow)",  # MOBJ_FID_FLOWER_01
    345: "grass patch (large, unused)",  # MOBJ_FID_GRASS_00
    346: "grass patch",  # MOBJ_FID_GRASS_01
    347: "forest gate (to Yokmir Forest)",  # MOBJ_GATE_FIELD_07_00
    348: "carved floor panel",  # MOBJ_GIMMICK_DUNG_B17_00
    349: "unused slot",  # dummy2_012
    350: "unused slot",  # dummy2_013
    351: "Floating Empire stairs up",  # MOBJ_ROAD_E_UPSTAIRS
    352: "thatched cottage (unused)",  # MOBJ_FID_HOUSE02
    353: "bridge railing",  # MOBJ_FID_BRIDGE_OVER
    354: "fir tree",  # MOBJ_FI_TREE08
    355: "fir tree (winter, unused)",  # MOBJ_FI_TREE08_WINTER
    356: "unused slot",  # MOBJ_FI_TREE09_WINTER_dummy
    357: "unused slot",  # MOBJ_FI_TREE09_WINTER_dummy2
    358: "bare tree 1 (unused)",  # MOBJ_FI_TREE10
    359: "bare tree 2 (unused)",  # MOBJ_FI_TREE11
    360: "flower patch",  # MOBJ_FIELD_43_FLOWER
    361: "flowers",  # MOBJ_FIELD_44_FLOWER
    362: "metal floor hatch",  # MOBJ_FIELD_METAL03
    363: "metal railing",  # MOBJ_FIELD_METAL04
    364: "cave boulder 1",  # DUNG_C_isi00
    365: "cave boulder 2",  # DUNG_C_isi01
    366: "cave boulder 3",  # DUNG_C_isi02
    367: "cave boulder 4",  # DUNG_C_isi03
    368: "cave boulder 5",  # DUNG_C_isi04
    369: "○ marker",  # MOBJ_CITY_MARU
    370: "✕ marker",  # MOBJ_CITY_BATU
    371: "cave entrance (left)",  # MOBJ_FID_DUNG_LEFT
    372: "cave entrance (left, winter)",  # MOBJ_FID_DUNG_LEFT_WINTER
    373: "cave entrance (right, unused)",  # MOBJ_FID_DUNG_RIGHT
    374: "cave entrance (right, winter)",  # MOBJ_FID_DUNG_RIGHT_WINTER
    375: "cave entrance (bottom)",  # MOBJ_FID_DUNG_DOWN
    376: "cave entrance (bottom, winter, unused)",  # MOBJ_FID_DUNG_DOWN_WINTER
    377: "ice wall backdrop (unused)",  # OBJ_D_E05_WALL_BG
    378: "ice rock wall backdrop",  # RandDungWallUp03_E05_BG
    379: "cave entrance (left, winter, top)",  # MOBJ_FID_DUNG_LEFT_WINTER_UP
    380: "cave entrance (right, winter, top)",  # MOBJ_FID_DUNG_RIGHT_WINTER_UP
    381: "ice patch 1",  # MOBJ_FI_ICE01
    382: "ice patch 2",  # MOBJ_FI_ICE02
    383: "ice patch 3 (unused)",  # MOBJ_FI_ICE03
    384: "ice patch 4 (unused)",  # MOBJ_FI_ICE04
    385: "shadow (unused)",  # MOBJ_FID_SHADOW_00
    386: "fir tree (Cedar Tree)",  # MOBJ_FI_TREE08A
    387: "Floating Empire walkway edge ← (top)",  # MOBJ_ROAD_E_LEFT_OVER
    388: "Floating Empire walkway edge → (top)",  # MOBJ_ROAD_E_RIGHT_OVER
    389: "cave entrance (left, top)",  # MOBJ_FID_DUNG_LEFT_UP
    390: "Dragon Lake house (unused)",  # MOBJ_HOUSE_CITY_04_00
    391: "Dragon Lake house (summer, unused)",  # MOBJ_HOUSE_CITY_04_00_SUMMER
    392: "Dragon Lake house (autumn, unused)",  # MOBJ_HOUSE_CITY_04_00_AUTUMN
    393: "Dragon Lake house (winter, unused)",  # MOBJ_HOUSE_CITY_04_00_WINTER
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


def is_positionless(type_id: int) -> bool:
    """True for the map-parameter records 9..19, whose f14/f15 nothing reads. Every other
    type is placed at (f14, f15) -- (0, 0) included: the game spawns a record there like
    anywhere else (129 shipped records sit exactly at the map origin, among them 33 water /
    light-shaft meshes anchored there)."""
    return 9 <= (type_id & 0xFFFF) <= 19


def mobj_archive_id(type_id: int) -> int:
    """map_obj archive id loaded for this type_id (type_id + 17542).

    Only meaningful for type_id >= 20 (the map_obj sprite-loading range)."""
    return (type_id & 0xFFFF) + MAP_OBJ_ARCHIVE_BASE


def mobj_name(type_id: int) -> str | None:
    """Return the map_obj sprite name for a type_id, or None when the record does not
    load a map_obj sprite (type_id < 20: forage directive / map parameter record)."""
    return MOBJ_NAMES.get(type_id & 0xFFFF)


# The texture each type's handler draws (RF4S.exe MapObj_SetupActorByTypeId +0x147240):
# types 82..196 and the road edges 78..81 load their own map_obj sprite (archive type + 17542),
# like the sprite band above them; types 20..77 get ONLY what their g_mapObjTypeInitTable
# handler loads -- often another archive, sometimes chosen by a record word, and for effects,
# sounds and zones nothing drawable. Checked handler by handler 2026-09-26. The street light
# (20) and red glow (37) are the efc_liteC glow in the handler's tint (MOBJ_TINT; the street
# light only shows 16:00-05:59), the chimney smoke (68) its smoke_ring (08:00-21:59), and
# 70..72 are textured meshes (rf4s_modkit.mobj_meshes). Not drawn here: 3D models (44 chest M26_0, 58 the
# travelling NPC, 60 the ponds), types 38..41 (their handler loads archive = type id, an AI
# file: unused), and every sound / zone / emitter type.
MOBJ_TEXTURE: dict[int, str] = {
    20: "efc_liteC",                        # MapObj_InitStreetLight
    # fishing spots: the fish Fishing_SpawnFishActor swims there (see fish_texture)
    24: "fish", 25: "fish",
    # warp point / knockback zone: MapObj_TickWarpEffectEmitter sends action 164 particles,
    # efc_senkou / efcimg_04 / efc_whirl2 at random -- shown as the white star (efcimg_04)
    42: "efcimg_04", 52: "efcimg_04",
    37: "efc_liteC",                        # MapObj_InitRedLightGlow
    26: "OBJ_KAMITSUKI",
    27: "OBJ_BIRD_BLUE",                    # one of BLUE / BROWN / GREEN / PINK at random
    28: "OBJ_BUTTERFLY_BLUE",               # one of BLUE / LIGHTB / PINK / YELLOW at random
    46: "floor_switch", 51: "MOBJ_SHIP", 56: "MOBJ_CHANDELIER", 57: "portrait",
    63: "floor_switch",                     # its handler wraps type 46's
    64: "FURNITURE_01", 65: "FURNITURE_02", 66: "FURNITURE_11",
    68: "smoke_ring",                       # MapObj_InitChimneySmoke
}
# Tints a handler multiplies its texture by (Sprite_SetTintFromPacked555: R bits 14..10,
# G 9..5, B 4..0, each /31).
MOBJ_TINT: dict[int, int] = {20: 0x5AA8, 37: 0x7DE2}
# Types whose sprite the handler draws with blend state 2 (sprite byte +930; the game's
# 0 opaque / 1 alpha / 2 add / 3 subtract / 4 multiply order): light glows, the warp
# particles, the light shafts and the water. The editor approximates the addition.
MOBJ_ADDITIVE = frozenset({20, 37, 38, 42, 52, 70, 71})
# Types whose handler loads a 3D model instead of a texture: (model name, view). The editor
# renders the .model (rf4s_modkit.model.render) at 2 model units per sub-unit (see
# map_editor.render.MODEL_UNITS_PER_SUBUNIT for the evidence), anchored at its base.
# "field" is the game's camera (the front, looked down on at about 25 degrees; model.VIEWS);
# the flat ponds are seen from the top.
# The chest: Actor_InitFlagGatedTreasure attaches archive 13867 = mons/M26_0 itself (not
# char 143's template model). The M26 models are the game's chests -- rf3NpcParam's model
# column (archive - 12584) gives M26_0 to "Pretty Chest" (char 141) AND to the "Monster Box"
# mimic (104), M26_1 to chest 142 and the "Gobble Box" mimic (105): the mimics borrow them.
MOBJ_MODEL = {44: ("M26_0", "field"), 58: ("NPC_TRAVELER_M", "field")}


def mobj_model(params):
    """(model name, view) a record draws as a 3D model, or None."""
    tid = params[0] & 0xFFFF
    if tid == 60:                           # Actor_InitFlagGatedRandomRotDecoration: f8 = lava
        return ("mobj_pond_lava" if len(params) > 8 and params[8] else "mobj_pond"), "top"
    return MOBJ_MODEL.get(tid)


def fish_texture(attr: int) -> str:
    """The fish a fishing spot shows on a tile with ATTR `attr`: Fishing_SpawnFishActor
    (RF4S.exe) draws "fish" (blue) on water (ATTR 0x8, or 0x4000) and "fish_sand" (orange,
    a fish in sand) anywhere else (Map_IsNonWaterTileAt)."""
    return "fish" if attr & 0x4008 else "fish_sand"


# Drawn smaller than the texture's own quad: particles spawned at a random 0.25..0.75 size;
# fish at half (Fishing_SpawnFishActor scales each by its length, 0.2 .. 1.0)
MOBJ_DRAW_SCALE = {42: 0.5, 52: 0.5, 24: 0.5, 25: 0.5}


def mobj_draw_scale(type_id: int) -> float:
    return MOBJ_DRAW_SCALE.get(type_id & 0xFFFF, 1.0)


# Types 20..195 whose handler reads f6 (scale); the rest of that band ignores it -- the road
# edges 78..81 and the door band 82..195 included (hexrays read sweep of every handler,
# 2026-09-26; re-checked 2026-09-30: every g_mapObjTypeInitTable handler 20..81 scanned for
# record +24 / +28, MapObj_LoadSpriteAndCollision (82..195) reads neither, the shared
# MapObj_SetupActorByTypeId reads only f0 and f14 / f15). Types 196+ (interactive objects,
# decorations) all read it (Map_SpawnInteractiveObject reads +24 scale and +28 frame).
MOBJ_SCALE_READERS = frozenset({20, 37, 38, 39, 40, 41, 44, 47, 48, 60, 64, 65, 66})


def mobj_reads_scale(type_id: int) -> bool:
    """True when the game sizes (and, negative, mirrors) this type by f6."""
    tid = type_id & 0xFFFF
    return tid >= 196 or tid in MOBJ_SCALE_READERS


# f7: an angle for these gimmicks (same sweep); the sprite frame from 196 up; unread otherwise.
MOBJ_ANGLE_READERS = frozenset({29, 30, 31, 33, 34, 42, 47, 48, 67})


def mobj_f7_kind(type_id: int) -> str | None:
    """What f7 is for this type: "angle", "frame", or None when the game ignores it."""
    tid = type_id & 0xFFFF
    if tid >= 196:
        return "frame"
    return "angle" if tid in MOBJ_ANGLE_READERS else None


def mobj_glow(params) -> bool:
    """True when the handler runs Sprite_ApplyEffect_Glow (RF4S.exe+0x1b8e30) on the sprite:
    both wrap modes mirror, UVs and size doubled -- the texture is one corner of the picture,
    drawn mirrored into all four around the object (street light, red glow, and the
    windmills: type 43 modes other than 2 / 3)."""
    tid = params[0] & 0xFFFF
    return tid in (20, 37) or (tid == 43 and (params[8] if len(params) > 8 else 0) not in (2, 3))


def mobj_tint(type_id: int) -> tuple[float, float, float] | None:
    """(r, g, b) factors 0..1 the game multiplies a type's texture by, or None."""
    v = MOBJ_TINT.get(type_id & 0xFFFF)
    return None if v is None else ((v >> 10 & 31) / 31, (v >> 5 & 31) / 31, (v & 31) / 31)
_WINDMILL = {1: "gmk19_windmill", 2: "propeller_ship_01", 3: "propeller_ship_02"}


def mobj_texture(params) -> str | None:
    """Texture name (without .texture) the game draws for a MOBJ record (its dwords), or
    None when it draws no texture of its own (see MOBJ_TEXTURE)."""
    tid = params[0] & 0xFFFF
    w = lambda k: params[k] if len(params) > k else 0
    if tid >= 78:
        return mobj_name(tid)
    if tid == 36:                           # the NPC-event collection object (+ an event step)
        return f"COLLECTION_{w(8):02d}"
    if tid == 43:                           # MapObj_InitEffectSpriteByMode, by word 8
        return _WINDMILL.get(w(8), "gmk18_windmill")
    if tid == 45:                           # Actor_InitFlagGatedRes15289Object: 8 colours
        return f"switch_{w(8) & 7:02d}"
    if tid in (46, 63) and w(8):
        return None                         # the switch's model is suppressed
    if tid == 53:                           # MapEntity_SpawnTreasure: word 8 = metal crate
        return "MOBJ_FIELD_METAL02" if w(8) else "MOBJ_BOX"
    if tid in (54, 55):                     # MapObj_InitEruptionHazard: word 10 = stone crater
        return "MOBJ_FI_ERUPT" if w(10) else "MOBJ_FI_ERUPT_LAVA"
    if tid in (70, 71, 72):                 # textured meshes: mobj_meshes.mesh_for()
        from . import mobj_meshes
        return mobj_meshes.mesh_for(params)[0]
    if tid == 59:                           # word 8 set: an invisible proximity trap
        return None if w(8) else "FURNITURE_21"
    return MOBJ_TEXTURE.get(tid)


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
    """READABLE name for UI lists: MOBJ_DISPLAY (every sprite type named from its sprite,
    placement and, for doors, its warp); failing that, for identified types the note's
    leading phrase — cut at the earliest of " — " / " (" — so the
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
    shown = MOBJ_DISPLAY.get(type_id & 0xFFFF)
    if shown:
        return shown
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
