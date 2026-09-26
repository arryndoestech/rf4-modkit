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
    13: ("u16", "scene-flag id, REGION B (abs bit = 4096 + f13; always a flag when read; unread by pure-effect types)"),
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
      (9, 4, "collision half-width (>>4 -> tiles; stamped into tile flags when f11 != 0)"),
      (10, 4, "collision half-height"),
      (11, 4, "0 = register interactable trigger, nonzero = stamp collision instead"),
      (12, 4, "bit flags: 0x1/0x2 -> sprite flags 8/0x10; 0x4 -> flag 0x20 = INVERT the f13 gate (hidden UNTIL set)"),
      (13, 2, "story-flag gate: SET = hidden (f12 bit 0x4 inverts)")],
     "Chests/signs/doors-with-interaction; type 263 diverts to the daily herb spawner "
     "(Map_SpawnDiscoverableHerbOrSpawner_Type263). Field map decoded 2026-08-31 from the "
     "handler (which carries the full IDB annotation)."),
    ((336, 9999), "decoration", "MapDecoration_Spawn",
     [(6, 4, "scale /4096/3 - NEGATIVE mirrors horizontally"),
      (7, 2, "sub-image index (sprite word +124), NOT a rotation"),
      (8, 4, "z bias (z = 2*(f8+f15)+4096)"),
      (9, 4, "flipbook frame duration - multi-frame RES textures animate (word +906)"),
      (10, 4, "nonzero = glow (Sprite_ApplyEffect_Glow)"),
      (13, 2, "story-flag: SET = hidden")],
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
                  "spot only registers while its flag is set (-1 = always). Fields per docs/13 (fishing).",
             params=[(8, 2, "max-fish cap (spot 0's value doubles as the map-wide cap)"),
                     (9, 2, "scatter radius, sub-units"),
                     (10, 2, "fast-swim flag (fish speed 200 su/f)"),
                     (11, 2, "fish_kind_seed: 0 = season/weather column, N = rate column N-1"), _DIS4]),
    25: dict(name="fe037", role="FISHING SPOT (fixed-species variant): forces one species instead of the "
                  "season/weather table. Fields per docs/13 (fishing).",
             params=[(8, 2, "species = f8+985 when f10 == 0"), (9, 2, "scatter radius, sub-units"),
                     (10, 4, "species item id (0 = use f8+985)"), _DIS4]),
    26: dict(name="gmk00_eater", role="Animated 'eater' gimmick (frame-cycling + sfx)",
             params=[(8, 4, "animation length / frame count")]),
    27: dict(name="gmk01_bird", role="Ambient bird (day/night + random)", params=[(8, 4, "spawn / behaviour param")]),
    28: dict(name="gmk02_butterfly", role="Ambient butterfly (day/night + random)", params=[(8, 4, "spawn / behaviour param")]),
    29: dict(name="gmk04_storm", role="Storm hazard — emits particle-attack (Action 0x2B). ALSO read at map "
                  "load (Map_LoadById case 29): f7 = wind angle, f8 << 8 = wind strength -> "
                  "work[+72..+80] map wind vector, which Weather_DayRollAndPick turns into a forced "
                  "windy-weather roll (verified 2026-09-19)",
             params=[(7, 2, "emit angle"), (8, 4, "emit period"),
                     (10, 2, "storm config, packed bits 10..19 of actor+584"),
                     (11, 4, "storm config, packed bits 0..9 of actor+584"), _DIS2]),
    30: dict(name="gmk05_storm", role="Wind / current zone — pushes actors, emits petals (Action 0x2C)",
             params=[(7, 2, "push angle"), (8, 4, "force magnitude"), (9, 4, "zone half-width (sub-units)"),
                     (10, 4, "zone half-height"), (11, 4, "Z flag"), _DIS2]),
    31: dict(name="gmk06_rock", role="Falling-rock ceiling trap — drops damaging rocks on random tiles",
             params=[(7, 2, "facing (cosmetic)"), (8, 2, "fall period (ticks between drops)"),
                     (9, 2, "scatter radius (Q12)"), (10, 4, "damage / attack power"),
                     (11, 2, "initial countdown / phase"), _DIS2]),
    32: dict(name="gmk07_dummy", role="Periodic quake — screen jitter + sfx 0x100225E",
             params=[(8, 2, "period"), (9, 2, "jitter kind / param")]),
    33: dict(name="gmk08_roll", role="Rolling boulder (damages on contact)",
             params=[(7, 2, "roll direction"), (8, 2, "roll period"), (9, 2, "roll distance / radius"),
                     (10, 4, "damage")]),
    34: dict(name="gmk09_water", role="Water hazard — emits water Effect (kind 8) periodically",
             params=[(7, 2, "facing"), (8, 2, "period"), (9, 4, "effect param / damage")]),
    35: dict(name="gmk10_mushroom", role="One-time item pickup (herb/mushroom): rolls a spawn chance, drops "
                  "the item sprite, then SETS its flag so it never respawns "
                  "(Actor_SpawnOneTimeItemAndSetFlag).",
             params=[(8, 4, "spawn chance / 255 (MMIX roll)"),
                     (9, 4, "item kind: 0 = item 48, 1 = 48+rand(0..3), 2 = 48+rand(0..5), 3 = preset"),
                     _DIS4]),
    36: dict(name="gmk11_collection", role="Collection gimmick (npc-linked)", params=[(8, 4, "behaviour param")]),
    37: dict(name="gmk12_redlight", role="Red light — always-on pulsing glow", params=[(6, 4, "light size (scale)")]),
    38: dict(name="gmk13_bluelight", role="Blue light — pulsing glow, ON at night", params=[(6, 4, "light size (scale)")]),
    39: dict(name="gmk14_sunlight", role="Sunlight beam — swaying, day/night gated",
             params=[(6, 4, "beam size (scale)"), (8, 4, "sway param"), (9, 4, "sway param"), (10, 4, "sway param")]),
    40: dict(name="gmk15_magiclight", role="Magic light — pulsing glow", params=[(6, 4, "light size (scale)")]),
    41: dict(name="gmk16_waterlight", role="Water light — pulsing glow",
             params=[(6, 4, "light size (scale)"), (8, 1, "pulse param")]),
    42: dict(name="gmk17_warp_effect", role="WARP POINT: on-step teleport trigger + warp-swirl particles "
                  "(Action 0xA4). Destination params f7/f8/f9/f10 -> actor+576..582, consumed by the "
                  "on-step handler (MapObj_InitWarpPoint).",
             params=[(7, 2, "warp destination param (actor+576 block)"), (8, 2, "destination param"),
                     (9, 2, "destination param"), (10, 2, "destination param"), _DIS2]),
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
                     (9, 4, "'opened' flag offset (flag = f13 + f9; 0 = no sparkle tick)"),
                     (10, 2, "sub-id (stored at actor+322)"), _DIS2]),
    45: dict(name="fe102", role="Colour switch: a pillar with a crystal, 8 colours "
                  "(switch_00..07 = res 15289 + (f8 & 7); Actor_InitFlagGatedRes15289Object).",
             params=[(8, 4, "colour (switch_00..07, f8 & 7)"),
                     (9, 4, "nonzero -> state byte actor+576 = 1"),
                     (10, 4, "state byte actor+577"),
                     (11, 4, "nonzero + secondary flag (gate+1) CLEAR -> hidden/alt tick"), _DIS2]),
    46: dict(name="fe102_2", role="Flag-gated interactive object (res 15218): touch it to SET its flag; "
                  "sprite frame 1 = activated look (Actor_InitFlagGatedInteractiveObject).",
             params=[(8, 4, "nonzero = suppress model + interaction kind 264 (else 1296)"),
                     (9, 1, "state byte actor+576"), (10, 1, "state byte actor+577"),
                     (11, 4, "touch hitbox half-width (default 24)"),
                     (12, 4, "touch hitbox half-height (default 24)"), _DIS2]),
    47: dict(name="fe103", role="MONSTER GATE / seal door: a barrier zone that stamps its rect's ATTR "
                  "cells BLOCKED while the room's encounter has live monsters (skipping the frame if "
                  "the player stands inside, so you can't be sealed in the doorway), then reopens and "
                  "SETS its flag when cleared. Tick chain MonsterGate_TickSealDoorUntilClear -> "
                  "_TickSpawnUntilClearedThenSetFlag; the IDA init name "
                  "Actor_InitFlagGatedDecoration is historical (playtest + tick decompile 2026-09-01).",
             params=[(6, 4, "scale Q12 (actor+584)"), (7, 2, "angle"),
                     (8, 4, "seal zone width (rect, centre = spawn pos)"),
                     (9, 4, "seal zone height"), (10, 4, "nonzero -> starts hidden (bit 4)"), _DIS2]),
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
             params=[(8, 2, "slide param (actor+576)"), (9, 2, "slide param (actor+578)"), _DIS2]),
    53: dict(name="MOBJ_BOX", role="Breakable crate: wooden (MOBJ_BOX), metal (MOBJ_FIELD_METAL02) when f8 is set "
                  "(char 143 'Treasure' actor internally, but in-game it "
                  "is the smashable crate, not a chest): loot rolled from the current zone's treasure "
                  "pool at room load (MapEntity_SpawnTreasure). Grass-wrapped variants need a cutting "
                  "tool (playtest-corrected 2026-09-01).",
             params=[(8, 4, "nonzero = metal crate (res 17599)"), (9, 4, "param (untraced)"),
                     (10, 4, "param (untraced)"),
                     (13, 2, "'collected/broken' flag (region-B; -1 = none/respawns) — the map data "
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
                     (10, 4, "sprite variant: 0 = res 17594, else res 17596"),
                     (11, 4, "initial delay (default: random)"), _DIS4]),
    56: dict(name="MOBJ_CHANDELIER", role="Damaging hazard sprite (falling chandelier; res 17598 with an "
                  "attack hitbox - MapObj_InitDamagingHazardSprite).",
             params=[(8, 1, "mode byte (actor+577)"),
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
             params=[(8, 4, "nonzero = suppress model + interaction kind 264 (else 1296)"),
                     (9, 1, "state byte actor+576"), (10, 1, "state byte actor+577"),
                     (11, 4, "touch hitbox half-width (default 24)"),
                     (12, 4, "touch hitbox half-height (default 24)"), _DIS2]),
    64: dict(name="fe119", role="Theatre table, small (FURNITURE_01); removed once its gate flag is set "
                  "(MapEntity_InitFlagGatedTreasure).",
             params=[(6, 4, "scale"), _DIS2]),
    65: dict(name="fe120", role="Theatre table, large (FURNITURE_02; shares type-64 handler).",
             params=[(6, 4, "scale"), _DIS2]),
    66: dict(name="fe121", role="Theatre chair (FURNITURE_11; shares type-64 handler).",
             params=[(6, 4, "scale"), _DIS2]),
    67: dict(name="fe122", role="Periodic flag-gated effect emitter (MapObj_InitPeriodicEffectEmitter / "
                  "Actor_TickPeriodicEffectEmitterGatedByFlag).",
             params=[(7, 2, "rotation (actor+156/158)"),
                     (8, 4, "attack power/scale (all four attack stat fields)"),
                     (9, 2, "mode (actor+576)"), (10, 4, "period (default 30000)"), _DIS4]),
    68: dict(name="fe123", role="Chimney smoke — day/night gated, random puffs (no record params)", params=[]),
    69: dict(name="fe124", role="Area particle emitter - particle-attack (Action 0xD5) over a rect "
                  "(MapObj_Init/TickAreaParticleEmitter).",
             params=[(8, 2, "emission rect half-width"), (9, 2, "emission rect half-height"),
                     (10, 4, "z-mode")]),
    70: dict(name="fe125", role="One-shot deferred effect spawn (Effect_SpawnWorldSpriteByType, then self-destroys).",
             params=[(8, 4, "effect type id")]),
    71: dict(name="fe126", role="Fire-and-forget procedural mesh effect (MapEffect_SpawnProceduralMeshByKind).",
             params=[(8, 4, "mesh effect kind")]),
    72: dict(name="fe127", role="Fire-and-forget ROTATED procedural mesh effect (MapEffect_SpawnRotatedProceduralMesh).",
             params=[(8, 4, "mesh effect kind")]),
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

# Gatherable kind -> crop sprite basename (archive 1366+kind; file names skip the
# unused kind 25, so minerals shift by one — verified against file_toc.tsv).
def gather_kind_sprite(kind: int) -> str | None:
    k = int(kind)
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
#   +0  u32 kind          gatherable kind 26..37 (selects the rock SPRITE +
#                         the "Mineral" display char 459+kind)
#   +4  u16 deplete_prob  }  ProbRoll_ExtraDrop_FavorsNoSkill bases
#   +8  u16 scrap_prob    }
#   +12/16/20 u16 weight[3]   drop weights for item[0..2]
#   +24/26/28 u16 item[3]     ore item ids (Iron 819, Bronze, ..., gems)
#   +30 u16 rare_item         rare bonus (Small/Big Crystal, Light Ore, ...)
MAPORE_RATE_RECORD = "see mobj_params source — verified layout above"


# Kind semantics decoded from the spawn core (Map_HandleSpecialTriggerEntity) + the
# gathering kind table:
# stone family {1 small rock, 2 big rock, 22 boulder, 24 hard rock}, wood family
# {3 branch, 4 stump, 5 log, 23 = its rare hard node}, 26..37 = ORE ROCKS,
# 0..31 herb/grass band, 38+ = crop range (wild spawns come up fully grown).
# TYPE 0 PLAYTEST-CORRECTED 2026-09-01: it is the ORE spawn point (was
# mislabelled "weeds/grass") — its configs come from the MiningOreCfg table
# (MapOre_Rate) and it alone rolls the daily BIG/SMALL rock size tier.
FORAGE = {
    0: dict(name="ore_rock_spawn", role="ORE / mining-rock spawn point: f10 = MiningOreCfg (MapOre_Rate) "
                 "config index, or a weighted roll over configs 0..15 when f11 != 0 (weights = "
                 "crop-param kinds 26..37 word +12). Only type with the daily BIG/SMALL size-tier "
                 "rolls (counters +7/+8).",
            params=_FOR + [(10, 1, "ore config index (MiningOreCfg row)"),
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
    3: dict(name="wood_spawn", role="Wood family: weighted {3 branch, 4 stump, 5 log} "
                 "(weights 300/110/200).", params=list(_FOR)),
    4: dict(name="stone_spawn", role="Stone family: weighted {1 small rock, 2 big rock, 22 boulder} "
                 "(weights 260/95/170).", params=list(_FOR)),
    5: dict(name="herb_pool32", role="Herb/grass: weighted pick over kinds 0..31 (per-kind crop-param "
                 "weights).", params=list(_FOR)),
    6: dict(name="wild_crop_pool64a", role="Wild CROP: weighted pick over kinds 38+ (64 pool), spawns "
                 "fully grown.", params=list(_FOR)),
    7: dict(name="wild_crop_pool64b", role="Wild CROP: weighted pick over kinds 38+ (64 pool, second "
                 "weight column), spawns fully grown.", params=list(_FOR)),
    8: dict(name="kind_from_f10", role="Gatherable kind taken directly from f10 (crop-range kinds spawn "
                 "grown).",
            params=_FOR + [(10, 4, "gatherable kind index (see docs/22 §1 kind table)")]),
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


def _per_type(tid):
    return GIMMICKS.get(tid) or FORAGE.get(tid) or MAP_PARAMS.get(tid)


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
#     Map_SpawnDiscoverableHerbOrSpawner_Type263 which allocs an Actor (id = 1263) and copies
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
    44: "hazard", 48: "hazard", 52: "hazard", 54: "hazard", 55: "hazard",
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
# MOBJ flag arguments (f13 gates, treasure 'opened' offsets, toggle flags) are
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
