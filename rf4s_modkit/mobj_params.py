"""MOBJ record parameter map — what every field of every MOBJ record means, and its size.

A `.rf4m` MOBJ record is 16 × i32 (64 B) on disk. `field[0]` = type_id, `[14]/[15]` = tile
pos; the rest are per-type parameters. Each spawn handler reads its own subset — and reads
each slot at a specific WIDTH: the on-disk slot is 4 bytes but the game often reads only the
low u16 (e.g. orientation, flag ids) or low u8. Editing the high bits of a u16/u8 field has
no effect in-game.

Every (field, size, meaning) below is VERIFIED against the actual init read in RF4S.exe
(`g_mapObjTypeInitTable[type]` for gimmicks 20-81; the shared lane handlers for the rest).
Sizes are the exact cast width the handler uses. 2026-07-03.

Schema: GIMMICKS[type]["params"] = [(field_index, size_bytes, meaning), …].
"""

# ---- universal field conventions -------------------------------------------------
FIELD_CONVENTION = {
    0:  ("u32", "type_id (dispatch category)"),
    6:  ("u32", "scale — 4096 = 1.0 (visual size / light radius)"),
    7:  ("u16", "orientation / facing angle — 65536 = full turn (low 16 bits)"),
    # f13 VERIFIED 2026-09-01 (hexrays sweep over all 62 gimmick inits + the four
    # lane handlers + the herb spawner): EVERY handler that reads f13 reads it as a
    # GameFlags BIT id — there is no non-flag use anywhere. Semantics vary by type
    # (hide-when-set, register-while-set for fishing spots, toggle for the door
    # band, set-on-clear for gates/pickups), and ~30 pure-effect types (lights,
    # sound emitters, critters, quake/boulder/water hazards, smoke, petals,
    # mesh/particle effects) never read it at all — for those the field is inert.
    # CORRECTED 2026-09-01: type 53 (breakable box, 'collected' flag) and the
    # road tiles 78..81 (gate flag) DO read f13 — the sweep missed them behind
    # custom-named decompiler args ('descriptor', a2[13] array indexing).
    # describe()/the editor only list f13 for types that read it.
    # Every spawner that gates on f13 reads the full signed dword first (`> 0`, `== -1`),
    # so a value is edited and stored as a whole i32 (-1 = no flag); valid ids are 0..2559.
    13: ("u32", "scene-flag id, REGION B (abs bit = 4096 + f13; -1 = none, ids 0..2559; always a flag when read; unread by pure-effect types)"),
    14: ("u32", "tile X (sub-units; <<12 = world)"),
    15: ("u32", "tile Y"),
}
SIZE_NAME = {1: "u8", 2: "u16", 4: "u32", 8: "u64"}

# ---- the 5 dispatch lanes --------------------------------------------------------
# range, label, handler, params=[(field,size,meaning)], note
LANES = [
    ((0, 8), "forage / gatherable spawner", "Map_HandleSpecialTriggerEntity",
     [(8, 4, "spawn probability threshold (daily-RNG gate; 0 = always)"),
      (9, 4, "scatter radius (random placement offset)")],
     "Daily-respawn forage. type_id 0-8 selects the gatherable category (see FORAGE); the "
     "tile-entity kind comes from f10 or a per-map weighted pool. Spawns via the crop/tile-entity "
     "system (Crop_FinalizeWriteState); sprite = 1366+kind, NOT type+17542."),
    ((9, 19), "map parameter record", "Map_LoadById (MapEvent switch, RF4S.exe+0x192BC3)",
     None,
     "type_id 9-19 are NOT placed objects: Map_HandleSpecialTriggerEntity returns early for "
     "them, but Map_LoadById walks EVERY MOBJ record at load (MapEvent_GetCount/GetAtIndex = "
     "the MOBJ pointer array) and applies types 9/10/11/12/13/15 as map-wide settings -- see "
     "MAP_PARAMS. Positionless (f14/f15 = 0 in every shipped record). Verified 2026-09-19."),
    ((20, 81), "gimmick actor", "g_mapObjTypeInitTable[type]", None,
     "Per-type init+tick; each type reads its own fields (see GIMMICKS)."),
    ((82, 195), "door / road / wall", "MapObj_LoadSpriteAndCollision",
     [(8, 4, "collision rect X offset (sub-units, added to tile X)"),
      (9, 4, "collision rect Y offset"),
      (10, 4, "stored in the toggle registry but NEVER stamped (tick writes the literal "
              "SOLID pattern cell & 0xFFFEFE70 | 2; f10 = 1 on every shipped record — "
              "corrected 2026-09-01)"),
      (11, 4, "mode: 1 = translucent overlay (alpha+z 8092), 2 = static, else animated; also biases the rect width"),
      (13, 2, "TOGGLE flag: the zone's collision ATTR toggles with this GameFlag (registry at rva 0xE95C60, 4 slots; tick = MapZone_TickToggleCollisionAttrByFlag)")],
     "Flag-toggled collision sprite: the door/road/wall band. Registers a rect into the 4-slot "
     "collision-toggle registry; when the f13 flag changes, the tick rewrites the zone's ATTR "
     "cells (open/close doors, raise walls). Decoded 2026-08-31 from the handler; the door "
     "WARP itself is the map's MAPJ record, not this object."),
    ((196, 335), "interactive object", "Map_SpawnInteractiveObject",
     [(6, 4, "scale /4096/3 - NEGATIVE mirrors horizontally"),
      (7, 2, "sub-image index (sprite word +124)"),
      (8, 4, "z bias (z = 2*(f8+f15)+4096) + interact word, template-adjusted (g_mapEntityTemplates +0x4D5030 adds a per-type bias)"),
      (9, 4, "solid box width, only with f11 != 0: f9 >> 4 tiles either side of the anchor "
             "tile (so about f9 sub-units in all); 0 = the box collapses onto map column 0"),
      (10, 4, "solid box height, only with f11 != 0 (f10 >> 4 tiles above and below); 0 = "
              "the box collapses onto map row 0"),
      (11, 4, "0 = the type's collision template is stamped into ATTR while the object is "
              "shown, and it can be interacted with; nonzero = no template and not "
              "interactable -- a SOLID f9 x f10 box is stamped instead, even while hidden "
              "(Map_SpawnInteractiveObject RF4S.exe+0x143760)"),
      (12, 4, "bit flags: 0x1/0x2 -> sprite flags 8/0x10 (0x2 also stamps the template into "
              "the pristine ATTR copy); 0x4 = INVERT the f13 gate (hidden UNTIL set)"),
      (13, 4, "story-flag gate: SET = hidden (f12 bit 0x4 inverts); re-checked every frame "
              "(Map_TickEntityArray RF4S.exe+0x143FB0), so the object and its collision appear "
              "and vanish as soon as the flag changes; -1 / 0 = no gate")],
     "Chests/signs/doors-with-interaction; type 263 diverts to the daily herb spawner "
     "(Map_SpawnSwWallDiscoverable_Type263). Field map decoded 2026-08-31 from the "
     "handler (which carries the full IDB annotation)."),
    ((336, 9999), "decoration", "MapDecoration_Spawn",
     [(6, 4, "scale /4096/3 - NEGATIVE mirrors horizontally"),
      (7, 2, "sub-image index (sprite word +124), NOT a rotation"),
      (8, 4, "z bias (z = 2*(f8+f15)+4096)"),
      (9, 4, "flipbook frame duration - multi-frame RES textures animate (word +906)"),
      (10, 4, "nonzero = glow (Sprite_ApplyEffect_Glow)"),
      (13, 4, "story-flag: SET = hidden; re-checked every frame (Map_TickEntityArray "
              "RF4S.exe+0x143FB0); -1 / 0 = no gate")],
     "Static/animated scenery (rocks, trees, grass, houses, bridges). A per-sprite switch adds "
     "special cases (background layers pinned to z 81..92, ATTR stampers for a few bridge/road "
     "sheets). Confirmed 2026-08-31 against the 2026-08-07 IDB annotation; the old 'rotation' "
     "meaning for f7 was wrong."),
]

# ---- per-gimmick map (types 20-81) — params VERIFIED from init reads --------------
_DIS4 = (13, 4, "disable game-flag id (0 = always on)")
_DIS2 = (13, 2, "disable game-flag id (0 = always on)")
_SND = [(8, 4, "sound id"), (9, 4, "volume"), (10, 4, "range / trigger rate")]
GIMMICKS = {
    20: dict(name="fe032", role="Street light — amber glow, ON 16:00-05:59, pulsing (tint 0x5AA8)",
             params=[(6, 4, "light size (scale)")]),
    21: dict(name="fe033", role="Ambient sound emitter", params=list(_SND)),
    22: dict(name="fe034", role="Ambient sound emitter (delegates to type-21)", params=list(_SND)),
    23: dict(name="fe035", role="Ambient sound emitter (delegates to type-21)", params=list(_SND)),
    24: dict(name="fe036", role="FISHING SPOT (zone): registers into g_fishingMngTask (16 slots); "
                  "spot only registers while its flag is set (-1 = always).",
             params=[(8, 2, "max-fish cap (spot 0's value doubles as the map-wide cap)"),
                     (9, 2, "scatter radius, sub-units"),
                     (10, 2, "fast-swim flag (fish speed 200 su/f)"),
                     (11, 2, "fish_kind_seed: 0 = season/weather column, N = rate column N-1"), _DIS4]),
    25: dict(name="fe037", role="FISHING SPOT (fixed-species variant): forces one species instead of the "
                  "season/weather table.",
             params=[(8, 2, "species = f8+985 when f10 == 0"), (9, 2, "scatter radius, sub-units"),
                     (10, 4, "species item id (0 = use f8+985)"), _DIS4]),
    26: dict(name="gmk00_eater", role="Animated 'eater' gimmick (frame-cycling + sfx)",
             params=[(8, 4, "animation length / frame count")]),
    27: dict(name="gmk01_bird", role="Ambient bird (day/night + random)", params=[(8, 4, "spawn chance in % (0 = always); halved in rain / storm, halved again in winter")]),
    28: dict(name="gmk02_butterfly", role="Ambient butterfly (day/night + random)", params=[(8, 4, "spawn chance in % (0 = always); halved in rain / storm, quartered in winter")]),
    29: dict(name="gmk04_storm", role="Storm hazard — emits particle-attack (Action 0x2B). ALSO read at map "
                  "load (Map_LoadById case 29): f7 = wind angle, f8 << 8 = wind strength -> "
                  "work[+72..+80] map wind vector, which Weather_DayRollAndPick turns into a forced "
                  "windy-weather roll (verified 2026-09-19)",
             params=[(7, 2, "wind direction (65536 = full turn)"),
                     (8, 4, "strength: push speed (f8 + 1) x 512; -1 = random 1..8"),
                     (10, 2, "frames it blows (max 1023; if f10 or f11 is 0 it blows nonstop)"),
                     (11, 4, "frames it pauses between gusts (max 1023; it starts paused)"),
                     (13, 2, "disable game-flag id (0 = always on)")]),
    30: dict(name="gmk05_storm", role="Wind / current zone — pushes actors, emits petals (Action 0x2C)",
             params=[(7, 2, "push angle"), (8, 4, "force magnitude"), (9, 4, "zone half-width (sub-units)"),
                     (10, 4, "zone half-height"), (11, 4, "Z flag"), _DIS2]),
    31: dict(name="gmk06_rock", role="Falling-rock ceiling trap — drops damaging rocks on random tiles",
             params=[(7, 2, "facing (cosmetic)"), (8, 2, "fall period (ticks between drops)"),
                     (9, 2, "scatter radius (Q12)"), (10, 4, "damage / attack power"),
                     (11, 2, "initial countdown / phase"), _DIS2]),
    32: dict(name="gmk07_dummy", role="Periodic quake — screen jitter + sfx 0x100225E",
             params=[(8, 2, "frames between quakes"), (9, 2, "shake strength kind (0-based)")]),
    33: dict(name="gmk08_roll", role="Rolling boulder (damages on contact)",
             params=[(7, 2, "roll direction"), (8, 2, "roll period"), (9, 2, "roll distance / radius"),
                     (10, 4, "damage")]),
    34: dict(name="gmk09_water", role="Water hazard — emits water Effect (kind 8) periodically",
             params=[(7, 2, "facing"), (8, 2, "frames between water bursts"),
                     (9, 4, "attack power of each burst")]),
    35: dict(name="gmk10_mushroom", role="One-time item pickup (mushroom): rolls a spawn chance, drops "
                  "the item (drawn with its item icon, e.g. I_Crop24 for item 48), then SETS its flag so "
                  "it never respawns (Actor_SpawnOneTimeItemAndSetFlag).",
             params=[(8, 4, "spawn chance / 255 (MMIX roll)"),
                     (9, 4, "item kind: 0 = item 48, 1 = 48+rand(0..3), 2 = 48+rand(0..5), 3 = preset"),
                     _DIS4]),
    36: dict(name="gmk11_collection", role="Collection gimmick (npc-linked)", params=[(8, 4, "NPC-event id: exists only once that event is reached; picture COLLECTION_nn "
                           "(a later picture at later event steps)")]),
    37: dict(name="gmk12_redlight", role="Red light — always-on pulsing glow", params=[(6, 4, "light size (scale)")]),
    38: dict(name="gmk13_bluelight", role="Blue light — pulsing glow, ON at night", params=[(6, 4, "light size (scale)")]),
    39: dict(name="gmk14_sunlight", role="Sunlight beam — swaying, day/night gated",
             params=[(6, 4, "scale"), (8, 4, "sprite frame 0..3"), (9, 4, "nonzero = mirrored left-right"),
                     (10, 4, "nonzero = flipped upside down")]),
    40: dict(name="gmk15_magiclight", role="Magic light — pulsing glow", params=[(6, 4, "light size (scale)")]),
    41: dict(name="gmk16_waterlight", role="Water light — pulsing glow",
             params=[(6, 4, "light size (scale)"), (8, 1, "pulse phase offset (frames)")]),
    42: dict(name="gmk17_warp_effect", role="WARP POINT: on-step teleport trigger + warp-swirl particles "
                  "(Action 0xA4). Destination params f7/f8/f9/f10 -> actor+576..582, consumed by the "
                  "on-step handler (MapObj_InitWarpPoint).",
             params=[(7, 2, "fall direction (65536 = full turn)"),
                     (8, 2, "landing X in the destination map (sub-units)"),
                     (9, 2, "landing Y (sub-units)"),
                     (10, 2, "destination map = this map's id + f10 (e.g. +7 / -7 between floors)"),
                     (13, 2, "works only while this flag is set (-1 = always)")]),
    43: dict(name="fe100", role="Windmill blades / airship propeller by mode: 0 gmk18_windmill (+ sfx), 1 "
                  "gmk19_windmill, 2 / 3 the Norad Express propellers (3-frame flipbooks) "
                  "(MapObj_InitEffectSpriteByMode).",
             params=[(8, 4, "mode: 0 / 1 windmills, 2 / 3 propellers")]),
    44: dict(name="fe101", role="TREASURE chest, flag-gated (char 143; gate flag SET = already looted). "
                  "Contents = 4 item slots from the loot table at RF4S.exe+0x9EFA60, row = f8 "
                  "(u16 per slot: low 11 bits item id, high 5 bits count). "
                  "Corrected 2026-08-31 vs Actor_InitFlagGatedTreasure +0x14B130 — the old "
                  "'emits attacks' role was a misread.",
             params=[(6, 4, "scale"), (8, 4, "loot-table row index"),
                     (9, 1, "reveal flag offset (signed byte): with f9 != 0 the chest stays "
                            "hidden until flag f13 + f9 is set (usually a seal door's room-clear "
                            "flag), then appears with a burst; 0 = always there "
                            "(Actor_InitFlagGatedTreasure RF4S.exe+0x14B130, "
                            "Actor_TickTreasureSparkleAndOpen +0x14B450)"),
                     (10, 2, "script event: when the chest is opened and f10 != 0, the game "
                             "runs this map's type-2 scene keyed 1024 + f10 after dropping the "
                             "items (WorldObject_OnBreakDropLoot RF4S.exe+0x1662C0 queues event "
                             "27, NpcAi_TickEventMovementOrFinalize +0x1F3070 looks the key up in "
                             "the map's event bank). Shipped: 44 chests use f10 1..3 (keys "
                             "1025..1027), every empty-row chest among them: 12 scenes give money, "
                             "the others play dialogue; 0 = no scene"),
                     (13, 4, "collected flag: SET = the chest is gone (-1 = none: it is back on "
                             "every visit); set when it is opened")]),
    45: dict(name="fe102", role="Colour switch: a pillar with a crystal, 8 colours "
                  "(switch_00..07 = res 15289 + (f8 & 7); Actor_InitFlagGatedRes15289Object).",
             params=[(8, 4, "colour (switch_00..07, f8 & 7)"),
                     (9, 4, "nonzero: once the flag is set, the interact cursor no longer shows "
                            "over it (WorldCursor_SpawnOrUpdateOverInteractable)"),
                     (10, 4, "kept on the object (actor+577); its own code doesn't read it"),
                     (11, 4, "nonzero: sparkles until flag f13 + 1 is set, then an open burst"),
                     (13, 2, "the flag its frame follows (frame 1 while set)")]),
    46: dict(name="fe102_2", role="Flag-gated interactive object (res 15218): touch it to SET its flag; "
                  "sprite frame 1 = activated look (Actor_InitFlagGatedInteractiveObject).",
             params=[(8, 4, "nonzero = invisible (no sprite; interaction kind 264, else 1296)"),
                     (9, 1, "0 = pressure plate: the flag goes back when nothing stands on it; "
                            "nonzero = stays switched"),
                     (10, 1, "script event: nonzero fires event 1024 + f10 once when touched"),
                     (11, 4, "touch hitbox half-width (default 24)"),
                     (12, 4, "touch hitbox half-height (default 24)"),
                     (13, 2, "the flag this switch drives")]),
    47: dict(name="fe103", role="MONSTER GATE / seal door: a barrier zone that stamps its rect's ATTR "
                  "cells BLOCKED while the room's encounter has live monsters (skipping the frame if "
                  "the player stands inside, so you can't be sealed in the doorway), then reopens and "
                  "SETS its flag when cleared. Tick chain MonsterGate_TickSealDoorUntilClear -> "
                  "_TickSpawnUntilClearedThenSetFlag; the IDA init name "
                  "Actor_InitFlagGatedDecoration is historical (playtest + tick decompile 2026-09-01).",
             params=[(6, 4, "scale Q12 (actor+584)"), (7, 2, "angle"),
                     (8, 4, "seal zone width (rect, centre = spawn pos)"),
                     (9, 4, "seal zone height"), (10, 4, "nonzero -> starts hidden (bit 4)"),
                     (13, 4, "cleared flag: set when the room is cleared (the door then stays "
                             "open). X <= 0 = hidden controller: no barrier, only sets the flag "
                             "on clear (Actor_InitFlagGatedDecoration RF4S.exe+0x14E7C0)")]),
    48: dict(name="fe107", role="BARRIER zone, flag-gated: a rect zone that blocks/repels the player "
                  "with particle hits (Action 0x95) until its gate flag clears — the dungeon "
                  "barrier walls. MapObj_InitFlagGatedBarrierZone +0x14EDC0 / "
                  "MapZone_TickFlagGatedBarrierAndParticles (2026-08-31).",
             params=[(6, 4, "magnitude (/4096)"), (7, 2, "rotation"),
                     (8, 4, "zone half-width"), (9, 4, "zone half-height"), _DIS2]),
    49: dict(name="fe104", role="Static effect (no params)", params=[]),
    50: dict(name="fe105", role="Static effect (no params)", params=[]),
    51: dict(name="MOBJ_SHIP", role="The airship sprite (res 17593 = MOBJ_SHIP), shown per its flag "
                  "(Actor_InitFlagGatedMCSpriteEffect).",
             params=[(8, 1, "mode (0 = animated via delta)"), _DIS4]),
    52: dict(name="MOBJ_FI_ERUPT_LAVA", role="Vent knockback zone (no sprite; puffs smoke): stepping on it staggers the "
                  "player, drops what they carry and walks them off it -- no HP damage "
                  "(Object_OnStepForceAutoWalk). IDA name MapObj_InitWarpPointVariantB is historical.",
             params=[(8, 2, "X of the spot the player is walked to (sub-units)"),
                     (9, 2, "Y of that spot (sub-units)"),
                     (13, 2, "works only while this flag is set (-1 = always)")]),
    53: dict(name="MOBJ_BOX", role="Breakable crate: wooden (MOBJ_BOX), metal (MOBJ_FIELD_METAL02) when f8 is set "
                  "(char 143 'Treasure' actor internally, but in-game it "
                  "is the smashable crate, not a chest): loot rolled from the current zone's treasure "
                  "pool at room load (MapEntity_SpawnTreasure). Grass-wrapped variants need a cutting "
                  "tool (playtest-corrected 2026-09-01).",
             params=[(8, 4, "nonzero = metal crate (res 17599)"), (9, 4, "nonzero = floating crate: lands with a splash and floats (Actor_OnLanded)"),
                     (10, 4, "1 = empty crate (no loot)"),
                     (13, 4, "'collected/broken' flag (region-B; -1 = none/respawns) — the map data "
                             "allocates a globally UNIQUE bit per box (705..968 across all maps; "
                             "-1 only in the random-dungeon J rooms). Read via the custom-named "
                             "'descriptor' arg — the 2026-09-01 f13 sweep missed it (false negative, "
                             "corrected)")]),
    54: dict(name="MOBJ_FI_ERUPT", role="Eruption vent (lava vent, or stone crater with f10) - erupts periodically, Effect kind 0x44 "
                  "(MapObj_Init/TickEruptionHazard).",
             params=[(8, 4, "eruption period (default 120)"),
                     (9, 4, "damage/scale -> the four attack stat fields"),
                     (10, 4, "sprite: 0 = lava vent (17594), else stone crater (17596)"),
                     (11, 4, "initial delay (default: random)"), _DIS4]),
    55: dict(name="fe106", role="Eruption vent - shares type-54's init and tick.",
             params=[(8, 4, "eruption period (default 120)"),
                     (9, 4, "damage/scale -> the four attack stat fields"),
                     (10, 4, "sprite: 0 = lava vent (17594), else stone crater (17596)"),
                     (11, 4, "initial delay (default: random)"), _DIS4]),
    56: dict(name="MOBJ_CHANDELIER", role="Chandelier (res 17598): always sways. With f8 set it falls when the player "
                  "or a party member moves within 26 sub-units left / right of it (up / down "
                  "doesn't count), switching its hitbox on; with f8 = 0 it only sways and "
                  "never hurts (MapObj_InitDamagingHazardSprite + _Tick).",
             params=[(8, 1, "1 = falls when approached, 0 = only sways"),
                     (9, 4, "attack effect id, biased +210 (-> attack+324)")]),
    57: dict(name="MOBJ_FIELD_METAL02", role="Portrait (res 2225 = portrait): with f8 set its eyes follow the player "
                  "(frames 0 / 1 / 2 by the player's x). MapObj_InitMCSpriteEffectRes2225.",
             params=[(8, 1, "nonzero = eyes follow the player")]),
    58: dict(name="MOBJ_BOX_WINTER", role="TRAVELER NPC spawn, flag-gated (actor category 27, res 1253; "
                  "spawns while the flag is CLEAR). Does NOT load the winter-box sprite — the band "
                  "name is a coincidence of archive position. f8 selects the tick mode "
                  "(0/1 story-progress tracking, 2 timed, 3 anim-archive). "
                  "Npc_InitFlagGatedTraveler +0x1500F0 (2026-08-31; was 'Winter box').",
             params=[(8, 4, "tick mode 0..3"), _DIS2]),
    59: dict(name="fe114", role="Wooly doll (res 1120 = FURNITURE_21), or with f8 an invisible proximity "
                  "damage trap (MapObj_InitProximityTrapOrEffect).",
             params=[(8, 4, "mode: nonzero = invisible proximity DAMAGE trap, 0 = the doll"),
                     (9, 4, "attack damage (all four attack stat fields)")]),
    60: dict(name="fe115", role="Flag-gated decoration with RANDOM 3D rotation "
                  "(Actor_InitFlagGatedRandomRotDecoration).",
             params=[(6, 4, "bounding size (actor+136..144)"),
                     (8, 4, "model variant: nonzero = res 1936, 0 = res 1934"), _DIS4]),
    61: dict(name="fe116", role="Effect emitter — emits attack (Action 0xB3), hardcoded (no record params)", params=[]),
    62: dict(name="fe117", role="Sakura petal effect, two modes (MapObj_InitSakuraPetalEffect).",
             params=[(8, 4, "mode: nonzero = per-plant flower spawner, 0 = map-wide petal emitter (singleton)")]),
    63: dict(name="fe118", role="Flag-gated TOGGLE SWITCH: activation CLEARS the flag (vs type 46's "
                  "one-shot SET); sprite frame 0/1 follows the flag "
                  "(Actor_InitFlagGatedToggleSwitch, wraps type 46).",
             params=[(8, 4, "nonzero = invisible (no sprite; interaction kind 264, else 1296)"),
                     (9, 1, "0 = pressure plate: the flag goes back when nothing stands on it; "
                            "nonzero = stays switched"),
                     (10, 1, "script event: nonzero fires event 1024 + f10 once when touched"),
                     (11, 4, "touch hitbox half-width (default 24)"),
                     (12, 4, "touch hitbox half-height (default 24)"),
                     (13, 2, "the flag this switch drives (inverted: stepping on it clears the flag)")]),
    64: dict(name="fe119", role="Theatre table, small (FURNITURE_01); removed once its gate flag is set "
                  "(MapEntity_InitFlagGatedTreasure).",
             params=[(6, 4, "scale"), (13, 4, "flag: SET = removed")]),
    65: dict(name="fe120", role="Theatre table, large (FURNITURE_02; shares type-64 handler).",
             params=[(6, 4, "scale"), (13, 4, "flag: SET = removed")]),
    66: dict(name="fe121", role="Theatre chair (FURNITURE_11; shares type-64 handler).",
             params=[(6, 4, "scale"), (13, 4, "flag: SET = removed")]),
    67: dict(name="fe122", role="Periodic flag-gated effect emitter (MapObj_InitPeriodicEffectEmitter / "
                  "Actor_TickPeriodicEffectEmitterGatedByFlag).",
             params=[(7, 2, "direction of the effect (65536 = full turn)"),
                     (8, 4, "attack power"),
                     (9, 2, "mode 0..8 = interval / effect: 0 120 f / 300, 1-2 120 / 302, "
                            "3 120 / 299, 4 30 / 18, 5 120 / 8, 6 60 / 8, 7 300 / 35, 8 90 / 45"),
                     (10, 4, "starting timer (0 = 30000: the first burst comes at once)"),
                     (13, 4, "emits while this flag is clear (0 = always)")]),
    68: dict(name="fe123", role="Chimney smoke — day/night gated, random puffs (no record params)", params=[]),
    69: dict(name="fe124", role="Area particle emitter - particle-attack (Action 0xD5) over a rect "
                  "(MapObj_Init/TickAreaParticleEmitter).",
             params=[(8, 2, "emission rect half-width"), (9, 2, "emission rect half-height"),
                     (10, 4, "z-mode")]),
    70: dict(name="fe125", role="Light shafts: a sunlight fan mesh (texture RE_VLIGHT2) shown 06:00-17:59 in clear weather (Effect_SpawnWorldSpriteByType, then self-destroys).",
             params=[(8, 4, "shape 0..15 (1 = shape 0 mirrored)")]),
    71: dict(name="fe126", role="Water surface: a waterA mesh whose texture flows (MapEffect_SpawnProceduralMeshByKind).",
             params=[(8, 4, "shape 0..21 (outside 1..21 = shape 0)")]),
    72: dict(name="fe127", role="Room overlay mesh: the palace hall drawn over the room, texture F_ROOM00 (MapEffect_SpawnRotatedProceduralMesh).",
             params=[(8, 4, "1 = winter texture F_ROOM00_WINTER")]),
    73: dict(name="fe128", role="No init (position only)", params=[]),
    74: dict(name="MOBJ_FI_ICE01_dummy", role="No init (position only)", params=[]),
    75: dict(name="MOBJ_FI_ICE02_dummy", role="No init (position only)", params=[]),
    76: dict(name="MOBJ_FI_ICE03_dummy", role="No init (position only)", params=[]),
    77: dict(name="MOBJ_FI_ICE04_dummy", role="No init (position only)", params=[]),
    78: dict(name="MOBJ_ROAD_E_UP", role="Directional road tile — marks ATTR tiles walkable (shared handler; "
                  "f13 read as a2[13] — gate flag, sweep false-negative corrected 2026-09-01)",
             params=[(13, 4, "gate flag (region-B; tested against g_gameFlagsBuffer)")]),
    79: dict(name="MOBJ_ROAD_E_RIGHT", role="Directional road tile — marks ATTR tiles walkable (shared handler)",
             params=[(13, 4, "disable game-flag id (0 = always on)")]),
    80: dict(name="MOBJ_ROAD_E_DOWN", role="Directional road tile — marks ATTR tiles walkable (shared handler)",
             params=[(13, 4, "disable game-flag id (0 = always on)")]),
    81: dict(name="MOBJ_ROAD_E_LEFT", role="Directional road tile — marks ATTR tiles walkable (shared handler)",
             params=[(13, 4, "disable game-flag id (0 = always on)")]),
}


# ---- forage spawners (types 0-8) — verified from Map_HandleSpecialTriggerEntity ----
# f8/f9 shared; f10/f11 used by types 0 & 8. type_id selects the gatherable category.
_FOR = [(8, 4, "spawn probability threshold (daily-RNG gate; 0 = always spawn)"),
        (9, 4, "scatter radius (random placement offset from anchor)")]
# ---- gatherable-kind identity tables (2026-09-01) --------------------------------
# The game's own name table: actor char id = 459 + gatherable kind (459 "Nothing
# there.", 460 Stone, 461 Rock, 462 Branch, 463 Stump, 464 Broken Stump,
# 481 Clay Stone (kind 22!), 482 RUNE FLOWER (kind 23), 483 RUNE CRYSTAL (kind 24),
# 485..496 "Mineral" = the 12 ore-rock kinds 26..37, 497+ = crops 38+). This
# OFFICIALLY confirms the playtest identifications of kinds 22..24.
GATHER_KIND_CHAR_BASE = 459
GATHER_KIND_MAX = 138          # char 459 + 139 is "Dummy", then the character list starts
_GATHER_NAMES = None


def gather_kind_name(kind: int) -> str | None:
    """The game's name for gatherable `kind` (char 459 + kind in the game's rf3TxtNpc):
    'Stone', 'Branch', 'Medicinal Herb', 'Mineral' (the ore rocks 26..37), 'Turnip' ..."""
    from . import gamenames
    return gamenames.name("characters", GATHER_KIND_CHAR_BASE + int(kind))


def param_choices(type_id, field):
    """[(value, label)] for a field whose values have names (the editor's dropdown), else []."""
    tid = type_id & 0xFFFF
    if tid == 8 and field == 10:
        out = []
        for k in range(GATHER_KIND_MAX + 1):
            nm = gather_kind_name(k) or "kind %d" % k
            if 26 <= k <= 37:
                nm += " (ore rock)"
            out.append((k, "%d  %s" % (k, nm)))
        return out
    if tid == 35 and field == 9:                    # one-time pickup: which item it drops
        return [(0, "0  Mushroom (item 48)"), (1, "1  one of items 48..51 (Mushroom)"),
                (2, "2  one of items 48..53 (Mushroom)"), (3, "3  none (reads an unset value)")]
    if tid == 24 and field == 11:                   # fishing spot: which fish-table column
        from .nlcl import FIELD_SCHEMAS
        cols = [n for n, _o, _t in FIELD_SCHEMAS["Fishing_rate_fish_Spring"]["fields"]][:21]
        return [(0, "0  by season and weather")] + [(k + 1, "%d  %s" % (k + 1, nm)) for k, nm in enumerate(cols)]
    return []

# ---- item icons (a dropped item's picture) --------------------------------------------
# Item_SpawnVisualTask (RF4S.exe+0x129A20) draws a dropped item with its icon, archive
# item id + 16432 (items 48..53, the mushrooms, are rom:/item/I_Crop24..29). The path comes
# from the exe's archive path table, so no file name is guessed here.
ITEM_ICON_ARCHIVE_BASE = 16432
_ITEM_ICONS: dict = {}


def item_icon_texture(item_id: int):
    """The .texture stem of an item's icon ('I_Crop24' for item 48), or None when the game
    folder's RF4S.exe is not available."""
    item_id = int(item_id)
    if item_id not in _ITEM_ICONS:
        stem = None
        try:
            import re
            from . import exetables, magicnames
            aid = ITEM_ICON_ARCHIVE_BASE + item_id
            path = magicnames.archive_paths(exetables.exe_bytes(), aid, aid).get(aid, "")
            m = re.fullmatch(r"rom:/.*/([^/]+)\.bntx", path)
            stem = m.group(1) if m else None
        except Exception:
            stem = None
        _ITEM_ICONS[item_id] = stem
    return _ITEM_ICONS[item_id]


# One-time item pickup (type 35, Actor_SpawnOneTimeItemAndSetFlag): f9 = 0 -> item 48, 1 -> one
# of 48..51, 2 -> one of 48..53 (all "Mushroom"); 3 reads an unset local (no fixed item).
PICKUP_KIND_ITEMS = {0: (48,), 1: (48, 49, 50, 51), 2: (48, 49, 50, 51, 52, 53)}


# Gatherable kind -> crop sprite basename (archive 1366+kind; file names skip the
# unused kind 25, so minerals shift by one — verified against file_toc.tsv).
_CROP_SPRITES = {}


def gather_kind_sprite(kind: int) -> str | None:
    """The crop sprite basename of a gatherable kind: archive 1366 + kind in the game's file
    table (crop_050_1 ... from kind 38 on, crop_024_0 for kind 25); without RF4S.exe the old
    formula, which holds for kinds 1-24 and 26-37."""
    k = int(kind)
    if not _CROP_SPRITES:
        try:
            import re
            from . import exetables, magicnames
            for aid, path in magicnames.archive_paths(exetables.exe_bytes(), 1366, 1366 + 200).items():
                mm = re.fullmatch(r"rom:/crop/([^/]+)\.bntx", path or "")
                if mm:
                    _CROP_SPRITES[aid - 1366] = mm.group(1)
        except Exception:  # noqa: BLE001 -- no exe: the formula below
            _CROP_SPRITES[-1] = None
    if k in _CROP_SPRITES:
        return _CROP_SPRITES[k]
    if 1 <= k <= 24:
        return "crop_%03d" % k
    if 26 <= k <= 37:
        return "crop_%03d" % (k - 1)
    if k >= 38:
        return "crop_%03d" % (k - 1)   # crops continue after the same gap
    return None

# MapOre_Rate.bin — the ore/mineral CONFIG table indexed by a type-0 spawn's f10.
# VERIFIED layout (TileObject_ApplyToolHit's reads at
# RF4S.exe+0x18B100/+0x18B32A) — replaces the older guessed schema:
#   +0  u8  rock kind     gatherable kind 26..37 (low 7 bits; selects the rock SPRITE +
#                         the "Mineral" display char 459+kind)
#   +4  s16 break chance  }  ProbRoll_ExtraDrop_FavorsNoSkill bases, out of 256
#   +8  s16 scrap chance  }  (Scrap Metal 818 instead of the ore)
#   +12/16/20 u16 item weights   drop weights for items 1..3
#   +24/26/28 u16 items 1..3     ore item ids (Iron 819, Bronze, ..., gems)
#   +30 u16 rare item            rare replacement drop (Small/Big Crystal, Light Ore, ...)
MAPORE_RATE_RECORD = "see mobj_params source — verified layout above"


# Kind semantics decoded from the spawn core (Map_HandleSpecialTriggerEntity) + the
# gathering kind table:
# stone family {1 Stone, 2 Rock, 22 Clay Stone}, wood family {3 Branch, 4 Stump,
# 5 Broken Stump} (the game's names, char 459 + kind), 23 Rune Flower, 24 Rune Crystal,
# 26..37 = ORE ROCKS,
# 0..31 herb/grass band, 38+ = crop range (wild spawns come up fully grown).
# TYPE 0 PLAYTEST-CORRECTED 2026-09-01: it is the ORE spawn point (was
# mislabelled "weeds/grass") — its configs come from the MiningOreCfg table
# (MapOre_Rate) and it alone rolls the daily BIG/SMALL rock size tier.
FORAGE = {
    0: dict(name="ore_rock_spawn", role="ORE / mining-rock spawn point: f10 = MiningOreCfg (MapOre_Rate) "
                 "config index, or a weighted roll over configs 0..15 when f11 != 0 (weights = "
                 "crop-param kinds 26..37 word +12). Only type with the daily BIG/SMALL size-tier "
                 "rolls (counters +7/+8).",
            params=_FOR + [(10, 1, "ore config index (MiningOreCfg row): the game keeps only "
                                   "the low 6 bits (f10 & 63) and the shipped MapOre_Rate has "
                                   "25 rows (0..24)"),
                           (11, 4, "nonzero = weighted roll over configs 0..15 instead of f10")]),
    1: dict(name="rune_flower_spawn", role="Fixed kind 23 — the wild RUNE FLOWER (sprite crop_023, blue "
                 "flower): NOT hand-pickable — destroyed with a sword or sickle, releasing RUNE "
                 "ENERGY (the orb that refills RP on pickup). Playtest-verified 2026-09-01; the "
                 "engine-side release law is not yet traced (no MINING_KIND define; earlier "
                 "'hard stump' guess was wrong).",
            params=list(_FOR)),
    2: dict(name="rune_crystal_spawn", role="Fixed kind 24 — the RUNE CRYSTAL node (blue crystal cluster, "
                 "sprite crop_024; HP 1, hammer): drops NO stone; hammer tier >= 2 rolls item 920 "
                 "'Rune Crystal' at 1/128 (t2) / 1/64 (t3) / 1/32 (t4+). Playtest-corrected "
                 "2026-09-01 — the RE's neutral 'hard rock' label hid its identity.",
            params=list(_FOR)),
    3: dict(name="wood_spawn", role="Wood family: each day a weighted pick of Branch (kind 3), "
                 "Stump (4) or Broken Stump (5) (weights 300/110/200).", params=list(_FOR)),
    4: dict(name="stone_spawn", role="Stone family: each day a weighted pick of Stone (kind 1), "
                 "Rock (2) or Clay Stone (22) (weights 260/95/170).", params=list(_FOR)),
    5: dict(name="herb_pool32", role="Herb/grass: weighted pick over kinds 0..31 (per-kind crop-param "
                 "weights).", params=list(_FOR)),
    6: dict(name="wild_crop_pool64a", role="Wild CROP: weighted pick over kinds 38+ (64 pool), spawns "
                 "fully grown.", params=list(_FOR)),
    7: dict(name="wild_crop_pool64b", role="Wild CROP: weighted pick over kinds 38+ (64 pool, second "
                 "weight column), spawns fully grown.", params=list(_FOR)),
    8: dict(name="gatherable", role="Spawns one chosen gatherable: the kind in f10 (a stone, stump, "
                 "herb, ore rock, crop ...; crop-range kinds spawn grown).",
            params=_FOR + [(10, 4, "gatherable kind (0..138; its name is the game's char 459 + kind)")]),
}


# ---- map PARAMETER records (types 9-19) — consumed at load by Map_LoadById ----------
# Map_HandleSpecialTriggerEntity ignores these (a1 >= 9 returns), which is why they were
# filed as "inert" until 2026-09-19. What actually reads them: right after Map_PostLoad,
# Map_LoadById loops i < MapEvent_GetCount() (= the MOBJ chunk count) and copies each
# MOBJ record with MapEvent_GetAtIndex (= MOBJ pointer i), then switches on f0. Each
# case below names the work-buffer field it writes and the code that consumes it
# (offsets are RF4S.exe map-task work-buffer offsets). Type 29 (gmk04_storm) is the
# one placed object that ALSO has a case here (map wind, see GIMMICKS[29]).
MAP_PARAMS = {
    9: dict(name="ground_depth",
            role="Ground-layer depth: work[+992] = 1, work[+996] = (float) f8 (0 keeps the "
                 "default 20.0). WidgetSlot_AllocLoadArchiveAndConfigure places the ground "
                 "tiles at z = f8 + 75 and switches them to the far-backdrop scale above 800.",
            params=[(8, 4, "depth (0 = default 20; > 800 = distant backdrop)")]),
    10: dict(name="parallax_size",
             role="Ground-layer parallax: ratio_x = f8 / (8 * ATTR width), ratio_y = f9 / "
                  "(8 * ATTR height) as Q12 (work[+1000/+1004]; f8/f9 kept at +1008/+1012). "
                  "MapTask_Tick scrolls the ground layer by camera * ratio about the screen "
                  "centre (200,120), so a backdrop smaller than the map moves slower than the "
                  "player.",
             params=[(8, 4, "backdrop width in sub-units (8 per tile)"),
                     (9, 4, "backdrop height in sub-units")]),
    11: dict(name="uv_scroll",
             role="Ground-texture UV scroll: f8/10000 and f9/10000 per frame written to both "
                  "the current (work[+1016/+1020]) and target (+1024/+1028) speeds -- the same "
                  "fields script ops 354/355 set and MapTask_Tick eases; MapDisp_TickTileScroll"
                  "AndTimeTint applies them per tile. Floating Empire sky, airship deck.",
             params=[(8, 4, "X scroll speed x 1/10000 per frame (negative = leftward)"),
                     (9, 4, "Y scroll speed x 1/10000 per frame")]),
    12: dict(name="tint_color",
             role="Tile tint colour: f8 picks the day (0) / evening (1) / night (2) slot -- the "
                  "same three slots the MLIG chunk fills (work[+920..+952]) -- and f9/f10/f11 "
                  "are R/G/B. f12 = 0 writes the slot (Map_PaletteReload re-applies it by time "
                  "of day); f12 = 1 / 2 instead blend the colour into display layer 0 (ground) "
                  "/ 1 (overlay) via Map_PaletteBlend. Three records per map, one per slot, is "
                  "the stock pattern: this is how shipped maps set their lighting (MLIG is "
                  "left at the defaults everywhere).",
             params=[(8, 4, "slot: 0 day (06-15h), 1 evening (16-18h), 2 night (19-05h) -- "
                            "used UNCHECKED as an array index when f12 = 0, so anything "
                            "else writes past the tint slots (rf4m.validate flags it)"),
                     (9, 1, "red"), (10, 1, "green"), (11, 1, "blue"),
                     (12, 4, "0 = set the tint slot; 1 = blend into the ground layer; "
                             "2 = blend into the overlay layer")]),
    13: dict(name="sprite_yaw_base",
             role="Actor sprite billboard yaw base: the NPC-streaming controller's float +44 = "
                  "(float) f8 (default 210.0), added to every actor's model yaw in "
                  "Actor_SyncSceneNodeTransformAndAnim. The Obsidian Mansion floors use 200.",
             params=[(8, 4, "yaw base in degrees (default 210)")]),
    15: dict(name="map_flag_bit8",
             role="Sets map flag bit 8 (work[+1068] |= 8). Scene_FinalizeMajorTransition runs "
                  "its weather-code scene branch only while the bit is clear (24 maps: "
                  "DUNG_C10-12, DUNG_I06/09/10, ...). No parameters.",
             params=[]),
}


# ---- type 263: the interactive band's one special case ------------------------------
# Map_SpawnInteractiveObject hands 263 to Map_SpawnSwWallDiscoverable_Type263, which
# reads only f8 / f9 / f13 (hexrays read sweep 2026-09-26).
SPECIAL = {
    263: dict(name="MOBJ_SW_WALL_00", role="Inscribed stone, a discoverable spot: dim until you or a party member "
                   "comes within 48 sub-units left / right (-16..+72 up / down), then it animates; "
                   "until then its footprint hints on the map (Map_SpawnDiscoverableHerbOrSpawner_"
                   "Type263).",
              params=[(8, 4, "picture variant 0..7 (archive 15297 + f8 & 7)"),
                      (9, 4, "nonzero = inverted flag (discovered while f13 is CLEAR)"),
                      (13, 2, "discovered flag (SET = already found); read as a signed 16-bit "
                              "id with no 'none' value -- -1 tests the last zone-1 story bit, "
                              "so it must be a real id 0..2559")]),
}


# ---- short parameter names (the map editor's field labels) ------------------------
# The meanings above are the explanations (the editor shows them as tooltips); these are
# the few-word names shown next to each field. Keyed by type id, or by a lane's (lo, hi).
_DISABLE = "disable flag"
PARAM_NAMES = {
    (0, 8): {8: "spawn chance", 9: "scatter radius"},
    (82, 195): {8: "collision X offset", 9: "collision Y offset", 10: "collision stamp",
                11: "draw mode", 13: "toggle flag"},
    (196, 335): {6: "scale", 7: "frame", 8: "depth bias", 9: "solid box width",
                 10: "solid box height", 11: "no template (box)", 12: "sprite flags", 13: "hide flag"},
    (336, 9999): {6: "scale", 7: "frame", 8: "depth bias", 9: "frame duration", 10: "glow",
                  13: "hide flag"},
    0: {10: "ore config", 11: "random ore config"},
    8: {10: "kind"},
    9: {8: "depth"},
    10: {8: "backdrop width", 9: "backdrop height"},
    11: {8: "scroll speed X", 9: "scroll speed Y"},
    12: {8: "time slot", 9: "red", 10: "green", 11: "blue", 12: "target"},
    13: {8: "yaw base"},
    20: {6: "light size"},
    21: {8: "sound id", 9: "volume", 10: "range"},
    22: {8: "sound id", 9: "volume", 10: "range"},
    23: {8: "sound id", 9: "volume", 10: "range"},
    24: {8: "max fish", 9: "scatter radius", 10: "fast fish", 11: "fish table", 13: _DISABLE},
    25: {8: "species", 9: "scatter radius", 10: "species item", 13: _DISABLE},
    26: {8: "animation length"},
    27: {8: "spawn chance"},
    28: {8: "spawn chance"},
    29: {7: "wind direction", 8: "strength", 10: "blow time", 11: "pause time", 13: _DISABLE},
    30: {7: "push direction", 8: "force", 9: "zone half-width", 10: "zone half-height",
         11: "Z flag", 13: _DISABLE},
    31: {7: "facing", 8: "drop interval", 9: "scatter radius", 10: "attack power",
         11: "first drop delay", 13: _DISABLE},
    32: {8: "interval", 9: "shake strength"},
    33: {7: "roll direction", 8: "roll interval", 9: "roll distance", 10: "attack power"},
    34: {7: "facing", 8: "interval", 9: "attack power"},
    35: {8: "spawn chance", 9: "item kind", 13: "collected flag"},
    36: {8: "NPC event"},
    37: {6: "light size"},
    38: {6: "light size"},
    39: {6: "scale", 8: "frame", 9: "mirror", 10: "flip"},
    40: {6: "light size"},
    41: {6: "light size", 8: "pulse phase"},
    42: {7: "fall direction", 8: "landing X", 9: "landing Y", 10: "map offset", 13: "active flag"},
    43: {8: "mode"},
    44: {6: "scale", 8: "loot row", 9: "reveal flag offset", 10: "script event", 13: "collected flag"},
    45: {8: "colour", 9: "no cursor when set", 10: "unused value", 11: "sparkle", 13: "flag"},
    46: {8: "invisible", 9: "stays pressed", 10: "script event", 11: "hitbox half-width",
         12: "hitbox half-height", 13: "flag"},
    47: {6: "scale", 7: "angle", 8: "seal width", 9: "seal height", 10: "starts hidden",
         13: "cleared flag"},
    48: {6: "strength", 7: "rotation", 8: "zone half-width", 9: "zone half-height", 13: "flag"},
    51: {8: "mode", 13: "flag"},
    52: {8: "target X", 9: "target Y", 13: "active flag"},
    53: {8: "metal", 9: "floats", 10: "empty", 13: "broken flag"},
    54: {8: "eruption interval", 9: "attack power", 10: "stone crater", 11: "first delay",
         13: _DISABLE},
    55: {8: "eruption interval", 9: "attack power", 10: "stone crater", 11: "first delay",
         13: _DISABLE},
    56: {8: "falls", 9: "attack"},
    57: {8: "eyes follow"},
    58: {8: "mode", 13: "flag"},
    59: {8: "trap mode", 9: "attack power"},
    60: {6: "size", 8: "lava pond", 13: "flag"},
    62: {8: "mode"},
    63: {8: "invisible", 9: "stays pressed", 10: "script event", 11: "hitbox half-width",
         12: "hitbox half-height", 13: "flag"},
    64: {6: "scale", 13: "removed flag"},
    65: {6: "scale", 13: "removed flag"},
    66: {6: "scale", 13: "removed flag"},
    67: {7: "direction", 8: "attack power", 9: "mode", 10: "start timer", 13: "stop flag"},
    69: {8: "area half-width", 9: "area half-height", 10: "z mode"},
    70: {8: "shape"},
    71: {8: "shape"},
    72: {8: "winter"},
    78: {13: "flag"}, 79: {13: "flag"}, 80: {13: "flag"}, 81: {13: "flag"},
    263: {8: "variant", 9: "invert flag", 13: "found flag"},
}
_CONV_NAMES = {0: "type", 6: "scale", 7: "angle", 13: "flag", 14: "X", 15: "Y"}


def param_name(type_id, field):
    """Few-word name of a field for this type ("spawn chance", "landing X"), else
    "word N" for a field nothing names."""
    tid = type_id & 0xFFFF
    n = PARAM_NAMES.get(tid, {}).get(field)
    if n:
        return n
    for key, names in PARAM_NAMES.items():
        if isinstance(key, tuple) and key[0] <= tid <= key[1] and field in names:
            return names[field]
    if field in (0, 14, 15):                # every record: its type, and its X / Y position
        return _CONV_NAMES[field]
    if any(f == field for f, _s, _m in params_for(tid)) and field in _CONV_NAMES:
        return _CONV_NAMES[field]
    return f"word {field}"


def common_field_note(type_id, field):
    """What words 0 / 14 / 15 hold for every MOBJ record, or '' for other fields."""
    tid = type_id & 0xFFFF
    if field == 0:
        return "the object type (the game uses the low 16 bits)"
    if field in (14, 15):
        axis = "X" if field == 14 else "Y"
        if 9 <= tid <= 19:
            return (f"{axis} position -- map-parameter records (types 9..19) are read by the map "
                    f"loader and have no position, so the game does not use it")
        return f"{axis} position in sub-units (8 per tile)"
    return ""


def _per_type(tid):
    return GIMMICKS.get(tid) or FORAGE.get(tid) or MAP_PARAMS.get(tid) or SPECIAL.get(tid)


def lane_for(type_id):
    """Return (label, handler, params, note) for a type_id's dispatch lane."""
    tid = type_id & 0xFFFF
    for (lo, hi), label, handler, params, note in LANES:
        if lo <= tid <= hi:
            return label, handler, params, note
    return "unknown", "", None, ""


def params_for(type_id):
    """Verified [(field, size_bytes, meaning), …] for a type (gimmick/forage or lane default)."""
    tid = type_id & 0xFFFF
    e = _per_type(tid)
    if e is not None:
        return list(e["params"])
    _l, _h, params, _n = lane_for(tid)
    return list(params or [])


def role_for(type_id):
    tid = type_id & 0xFFFF
    e = _per_type(tid)
    return e["role"] if e else lane_for(tid)[0]


def name_for(type_id):
    """Sprite name if any, else the forage / map-parameter name for the unnamed 0-19 range."""
    tid = type_id & 0xFFFF
    e = FORAGE.get(tid) or MAP_PARAMS.get(tid)
    if e:
        return e["name"]
    if tid <= 19:
        return "(unused map-parameter id)" if tid >= 9 else "forage"
    return ""


def field_size(type_id, field):
    """Read width (bytes: 1/2/4) the game uses for a field of this type, or None if unread.
    The on-disk slot is always 4 bytes; the game reads only this many low bytes."""
    for f, s, _m in params_for(type_id):
        if f == field:
            return s
    if field in FIELD_CONVENTION:
        return {"u8": 1, "u16": 2, "u32": 4}[FIELD_CONVENTION[field][0]]
    return None


def field_meaning(type_id, field):
    for f, _s, m in params_for(type_id):
        if f == field:
            return m
    if field in FIELD_CONVENTION:
        return FIELD_CONVENTION[field][1]
    return "unused / behavior param"


def describe(type_id):
    """(role, [(field, size_bytes, meaning), …]) — position (14/15) & type (0) implicit."""
    return role_for(type_id), params_for(type_id)


# ---- interaction classification -------------------------------------------------
# How the player interacts with a placed MOBJ *instance* in-game, and whether it shows
# the floating "H" world-cursor MARKER (WorldCursor_SpawnOrUpdateOverInteractable) that
# precedes a dialog / game-event.
#
# VERIFIED chain (RF4S.exe, 2026-07-03):
#   * Map_SpawnAllEntities routes a MOBJ by type_id. Types 20-195 -> MapObj_SetupActorByTypeId
#     which sets the spawned Actor's id (actor+8) = type_id + 1000. Type 263 ->
#     Map_SpawnSwWallDiscoverable_Type263 which allocs an Actor (id = 1263) and copies
#     record field 13 -> actor.stat_block[+320] = the game-flag / char id.
#   * Player_TickFieldInteraction scans the nearest actor (player_inner+1280); if its flags
#     (+16) mark it interactible it calls WorldCursor_SpawnOrUpdateOverInteractable ("H"
#     cursor, sprite 1946). On the action button, object/NPC interaction ->
#     Npc_OnInteract_QueueEventByStoryGate: sets g_currentInteractionNpc + queues a game event
#     -> the Script VM runs the dialogue, keyed by that char/flag id. The DIALOG TEXT lives in
#     the script banks + text archives, NOT in the .rf4m.
#   * So field 13 (f13) is the object's STATE / event / discovery flag id (-1 = none). For a
#     flag-gated interactible it links the placed object to its persistent state + its dialog.
#
# There is NO separate "interactibles" chunk: the .rf4m only has MOBJ (objects) + MAPJ
# (warps). NPCs (schedule) and monsters (encounter Gate table) are separate runtime systems,
# not stored in the map file.

# category key -> (short label, shows floating "H" marker + dialog?)
INTERACT_CATS = {
    "examine": ("Examine / switch — floating marker, opens a dialog or fires a game event", True),
    "open":    ("Open / break — hit to open for loot (treasure, box, ship)", False),
    "fish":    ("Fishing spot — registers a fishing point", False),
    "gather":  ("Gather / harvest — tool hit or walk-over pickup (forage, tree, herb, mushroom)", False),
    "door":    ("Door / wall — collision; doors transition via the map's MAPJ warps", False),
    "hazard":  ("Hazard — damages the player on contact (not a dialog interactible)", False),
    "ambient": ("Ambient / effect — light, sound, particle (not interactible)", False),
    "decor":   ("Decoration — static/animated scenery (not interactible)", False),
    "param":   ("Map parameter record — a load-time map setting, not an object", False),
}

# per-type category overrides (gimmick band 20-81 + a few interactive-band types).
# Types not listed fall through to the range defaults in interaction_class().
_INTERACT_TYPE = {
    24: "fish", 25: "fish",
    35: "gather",                                   # mushroom gimmick
    51: "open", 53: "open", 58: "open",             # ship / breakable box / winter box
    64: "open", 65: "open", 66: "open",             # treasure spots
    263: "examine",                                 # discoverable herb / switch-wall / spawner
    # damaging gimmicks
    29: "hazard", 30: "hazard", 31: "hazard", 33: "hazard", 34: "hazard",
    44: "open", 48: "hazard", 52: "hazard", 54: "hazard", 55: "hazard",
    59: "hazard", 67: "hazard",
}


def interaction_class(type_id):
    """(category_key, label, shows_marker) — how the player interacts with this type."""
    tid = type_id & 0xFFFF
    if tid in _INTERACT_TYPE:
        cat = _INTERACT_TYPE[tid]
    elif tid <= 8:
        cat = "gather"          # daily forage spawner
    elif tid <= 19:
        cat = "param"           # map parameter record (MAP_PARAMS), consumed by Map_LoadById
    elif tid <= 81:
        cat = "ambient"         # gimmick (overrides above catch the hazards/fish/open)
    elif tid <= 195:
        cat = "door"            # door / road / wall
    elif tid <= 335:
        cat = "gather"          # interactive object — trees/herbs/mushrooms (263 overridden)
    else:
        cat = "decor"
    label, marker = INTERACT_CATS[cat]
    return cat, label, marker


def runtime_actor_id(type_id):
    """Runtime Actor id (actor+8) for a placed MOBJ, or None if it spawns a plain sprite.
    Types 20-195 -> MapObj_SetupActorByTypeId sets id = type+1000; type 263 -> 1263."""
    tid = type_id & 0xFFFF
    if 20 <= tid <= 195 or tid == 263:
        return tid + 1000
    return None


def is_interactible(type_id, f13=None):
    """True if this instance is a marker/dialog interactible the player can talk to / examine
    (category 'examine'), OR any flag-gated instance (f13 set to a real id) of an
    interaction-capable type. Broadly, 'examine'/'open'/'fish'/'gather' are interactible."""
    cat, _label, marker = interaction_class(type_id)
    if marker:
        return True
    if cat in ("open", "fish", "gather") and f13 not in (None, -1, 0):
        return True
    return cat in ("open", "fish")


# ---- GameFlag id -> emdeb name resolver (lazy; emdeb.bin optional) ----------
# MOBJ flag arguments (f13 gates, treasure reveal offsets, toggle flags) are
# GameFlags BIT ids — the same id space emdeb.bin names (see emflags.py). This
# resolves an id to its FLG_/REG_ symbol so the editor can show which flag a
# barrier/door/spot is wired to.
_EMFLAGS = None


def _emflag_table():
    global _EMFLAGS
    if _EMFLAGS is None:
        try:
            from . import emflags
            _EMFLAGS = emflags.EmFlagTable.load() or False
        except Exception:
            _EMFLAGS = False
    return _EMFLAGS or None


MOBJ_FLAG_BASE = 4096   # READ FROM THE INITIALIZER (ScriptTask_FirstTimeInit):
                        #   buf = aligned_malloc(0x3A0); *(u32*)buf = 4096;   <- the base
                        #   *((u32*)buf+1) = 2560;                            <- region-B capacity
                        # Every MOBJ handler tests bit(*(u32*)buf + f13), so f13 ids live in
                        # REGION B: absolute bits 4096..6655 of the ONE flag bit-buffer, a
                        # per-save scene/event space emdeb does not name. The field API
                        # (GameFlags_ReadField / PackedFlags_ReadField_MSBFirst) takes
                        # ABSOLUTE ids with no base — that is where emdeb offsets apply.
                        # MC-script direct ops: 443/445 add 4096; op 318 adds 4096+1007.


def flag_label(flag_id):
    """Truthful label for a MOBJ flag argument (f13-style). These are ZONE-2 ("region B")
    bits: absolute GameFlags bit = 4096 + id, a space emdeb.bin does not name. They are
    NOT emdeb-named zone-1 flags; resolving them against emdeb produced wrong names
    (playtest catch 2026-09-01: a MAP_DUNG_B02 boss barrier labelled with a Nancy flag).
    The known sub-blocks (bridges, breakable boxes, shop-door hours, the daily-reset range,
    per-NPC story / birthday-gift / hidden bits, recipes) come from emflags.ZONE2_BLOCKS.
    None for the <=0 / 0xFFFF sentinels."""
    try:
        fid = int(flag_id)
    except (TypeError, ValueError):
        return None
    if fid <= 0 or fid in (0xFFFF, 0xFFFFFFFF):
        return None
    from . import emflags
    return emflags.zone2_text(fid)


def emdeb_flag_label(bit_offset):
    """emdeb (REGION A) name for an ABSOLUTE GameFlags bit id — the space
    GameFlags_ReadField / the script packed ops use. NOT for MOBJ f13 ids
    (those are region-B; see flag_label)."""
    try:
        fid = int(bit_offset)
    except (TypeError, ValueError):
        return None
    if fid <= 0 or fid in (0xFFFF, 0xFFFFFFFF):
        return None
    t = _emflag_table()
    if not t:
        return None
    v = t.by_offset(fid)
    if not v:
        return None
    if v.bit_width == 1 or fid == v.bit_offset:
        return v.name
    return f"{v.name} (bit {fid - v.bit_offset} of {v.bit_width})"


def interaction_summary(type_id, f13=None):
    """One-line human summary for the editor/CLI, e.g.
    'Examine (shows marker) · runtime actor id 1263 · state/event flag f13=318 = FLG_xxx'."""
    cat, label, marker = interaction_class(type_id)
    parts = [label.split("—")[0].strip() + (" (shows marker)" if marker else "")]
    aid = runtime_actor_id(type_id)
    if aid is not None:
        parts.append(f"runtime actor id {aid}")
    if f13 not in (None, -1):
        role = "state/event flag" if cat in ("examine", "open", "gather", "fish") else "disable flag"
        extra = f" (scene bit, abs {MOBJ_FLAG_BASE + f13})" if isinstance(f13, int) and f13 > 0 else ""
        parts.append(f"{role} f13={f13}{extra}")
    return " · ".join(parts)


# ---- flag ids, one-shot flags, limits the validator checks ------------------------
MOBJ_FLAG_COUNT = 2560     # zone-2 ids 0..2559 (the header's region-B capacity, see MOBJ_FLAG_BASE)


def reads_flag(type_id):
    """True when this type's spawner reads f13 as a flag id."""
    return any(f == 13 for f, _s, _m in params_for(type_id))


# Types whose own code SETS their f13 flag once and keeps it (opened / broken / picked up /
# found / pressed / cleared): two records with one such flag act as one. {type: noun}
ONE_SHOT_FLAG_TYPES = {
    35: "mushroom pickup",  # Actor_SpawnOneTimeItemAndSetFlag RF4S.exe+0x149980: sets it on spawn
    44: "chest",            # Actor_InitFlagGatedTreasure +0x14B130: set when opened
    46: "switch",           # stays switched when f9 != 0 (a pressure plate, f9 = 0, lets go)
    47: "seal door",        # sets it when the room is cleared
    53: "crate",            # MapEntity_SpawnTreasure +0x14B680: set when broken
}
# Not here: type 263 (inscribed stone). Its tick (RF4S.exe+0x14D690) only READS f13 (found
# or not); nothing in its own code sets it, and 25 shipped flags are shared between stones
# on different maps on purpose.


def one_shot_flag(rec):
    """The one-shot flag a record owns (see ONE_SHOT_FLAG_TYPES), or None."""
    tid = rec[0] & 0xFFFF
    if tid not in ONE_SHOT_FLAG_TYPES or rec[13] in (-1, 0):
        return None
    if tid == 46 and rec[9] & 0xFF == 0:
        return None                     # pressure plate: the flag drops when stepped off
    return rec[13]


# Types for which ANY unused id works exactly like the original: the handler treats f13 as a
# plain "already used" bit and nothing else reads it (verified per handler above). A chest
# with a reveal offset (f9 != 0) is left out: its reveal flag is f13 + f9. Duplicate / paste
# give these a fresh id from the block the original sits in; everything else keeps its flag.
FRESH_FLAG_TYPES = frozenset({35, 44, 53})

# Zone-2 id blocks with a fixed meaning a new id must stay in (emflags.ZONE2_BLOCKS):
# Day_OnAdvance (RF4S.exe+0x85A60) clears 752..969 every day -- daily crates and pickups
# come back -- while 705..739 holds the crates that stay broken, and 69..647 the per-map
# scene bits (chests, gates, switches, stones).
FLAG_BLOCKS = ((752, 969, "daily-reset"), (705, 739, "permanent crate"), (69, 647, "scene"))
DEFAULT_FLAG_BLOCK = {35: (752, 969), 44: (69, 647), 53: (752, 969), 263: (69, 647)}


def flag_block(flag, type_id=None):
    """(lo, hi) of the FLAG_BLOCKS entry holding `flag`, else the type's default block for a
    new record (flag None), else None."""
    if flag is not None:
        for lo, hi, _n in FLAG_BLOCKS:
            if lo <= flag <= hi:
                return lo, hi
        return None
    return DEFAULT_FLAG_BLOCK.get(type_id)


# Add-tool starting values that differ from the plain template [type, -1 x5, 4096, 0 .. 0,
# f13 -1]: fields where 0 / -1 does something odd in the game, set to the value most shipped
# records of that type use. (A new chest / crate / herb / inscribed stone also gets an unused
# flag, see DEFAULT_FLAG_BLOCK.)
ADD_DEFAULTS = {
    12: {9: 255, 10: 255, 11: 255},    # tint: white, not black
    13: {8: 210},                      # sprite yaw base: the game's own default
    24: {8: 2, 9: 8},                  # fishing spot: 2 fish, 1-tile scatter
    30: {8: 32, 9: 120, 10: 100},      # wind zone: some force and a zone
    31: {8: 120, 9: 120, 10: 800},     # falling rocks: period, scatter, damage
    35: {9: 2},                        # mushroom pickup: 48 + rand(0..5)
}

MAPORE_RATE_ROWS = 25       # rows of the shipped MapOre_Rate table (type-0 f10 & 63 indexes it)
FORAGE_MAX_SPAWNS = 32      # Map_HandleSpecialTriggerEntity RF4S.exe+0x187A00 spawns at most 32
DOOR_SLOTS = 4              # the door / road / wall collision registry (RF4S.exe+0xE95C60)
