"""ATTR tile-attribute knowledge: what each bit of a cell means, who can walk on it, how the
Paint controls group the bits, and the colours the editor draws them in.

Every claim here is evidenced against RF4S.exe or the shipped maps; the bits whose meaning
is unknown say so (see ATTR_BIT_HELP)."""
from __future__ import annotations

CAT_COLOR = {
    "forage": "#ffb020", "trigger": "#cccccc", "mapparam": "#cccccc", "actor": "#ff4040",
    "object": "#4080ff", "decoration": "#40c040",
}
# Entity kinds that share the "triggers" layer toggle (forage spawn points draw as dots;
# map parameter records 9..19 are positionless and never drawn, but share the key).
TRIGGER_KINDS = ("forage", "trigger", "mapparam")
ATTR_EMPTY = (150, 150, 138)     # value 0: empty ground everyone walks on (not a void)
ATTR_FLOOR = (70, 74, 82)
ATTR_PALETTE = [
    (120, 90, 60), (60, 110, 130), (110, 70, 110), (90, 120, 70),
    (150, 120, 50), (70, 90, 150), (140, 70, 70), (60, 130, 110),
    (110, 110, 110), (90, 70, 130), (130, 100, 80), (70, 120, 130),
]

# Every distinct ATTR cell value that occurs in the 872 shipped maps, measured
# 2026-09-21 over all 3,280,534 cells. Used to pre-fill the Paint dropdown.
KNOWN_ATTR_VALUES = [
    0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x8, 0x9, 0xA, 0xC, 0x21, 0x41, 0x81, 0x82, 0x83, 0x101,
    0x181, 0x201, 0x202, 0x281, 0x381, 0x401, 0x402, 0x403, 0x404, 0x481, 0x501, 0x581, 0x1001,
    0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2081, 0x4000, 0x4001, 0x400A, 0x8001, 0x10001,
    0x10004, 0x10008, 0x10009, 0x1000B, 0x1000C, 0x14001, 0x14002, 0x14008, 0x14009, 0x15001,
    0x20001, 0x20002, 0x20003, 0x20004, 0x20081, 0x20201, 0x20401, 0x20481, 0x40000, 0x40001,
    0x40002, 0x40003, 0x40004, 0x40081, 0x40181, 0x60001, 0x60181, 0x80000, 0x80101, 0x200001,
    0x200004, 0x400001, 0x400002, 0x400003, 0x400004, 0x400005, 0x400008, 0x400081, 0x400104,
    0x400404, 0x402001, 0x402004, 0x402005, 0x420001, 0x420005, 0x440001, 0x440004, 0x600004,
    0x8000002, 0x8000003, 0x10000001, 0x10000002, 0x1000000A, 0x10004001, 0x1000400A,
    0x10020001, 0x20000001, 0x20000002, 0x20000003, 0x20000081, 0x20000082, 0x20000083,
    0x20000201, 0x20000401, 0x20040001, 0x40000001, 0x40000003, 0x40000081, 0x40000083,
]

# ---------------------------------------------------------------------------
# Who can walk where.
#
# Actor_TryMoveWithTileSlide (RF4S.exe+0x1937B0) -- and Monster_QueryTileBlockedOrReached-
# Target (+0x1D2750) the same way -- blocks a move when
#
#     cell & ~actor_mask & 0x1018F
#
# is nonzero: only the bits 0x1 0x2 0x4 0x8 0x80 0x100 0x10000 can block, and each actor
# ignores the ones in its own mask (actor+0xDC):
MOVE_BITS = 0x1018F
ACTOR_MASKS = (
    # (who, ignore mask, where the game sets it)
    ("player", 0x101A1, "Player_ApplyEquippedItemStats +0xB1B7C"),
    ("player with water boots", 0x101B9, "+0xB1BFA"),
    ("party members / mounts", 0x101A1, "Companion_FinalizeInPartyAllocStatsAndGauge +0x15AC0E"),
    ("monsters / other actors", 0x10021, "Actor_SpawnAtPos +0x15A64D"),
    ("event NPCs", 0x10121, "Npc_SpawnCharEventActor +0x15CF06"),
    ("knock-back slide", 0x21, "Actor_OnHitClearHeldEntityAndCollideSlide +0xEA113"),
)
# So the player is blocked only by 0x2 / 0x4 / 0x8 (0x8 not with water boots), monsters
# also by 0x80 and 0x100, event NPCs also by 0x80, and 0x10000 stops only the knock-back.
# 0x1 is in every mask: it never blocks and walking never needs it.
_WALK_SHORT = (("player", 0x101A1), ("boots", 0x101B9), ("monsters", 0x10021),
               ("NPCs", 0x10121), ("knock-back", 0x21))


def blocks(value, mask):
    """True when a cell of `value` stops an actor with the ignore `mask` (ACTOR_MASKS)."""
    return bool(value & ~mask & MOVE_BITS)


def walk_readout(value):
    """'walk: player yes · boots yes · monsters no · NPCs no · knock-back no'."""
    return "walk: " + " · ".join(f"{who} {'no' if blocks(value, m) else 'yes'}"
                                  for who, m in _WALK_SHORT)


def walk_help():
    """The mask table as text, for the hover help."""
    out = ["A tile stops an actor when  cell & ~mask & 0x1018F  is nonzero:"]
    for who, m, _src in ACTOR_MASKS:
        stop = [f"0x{b:X}" for b in (0x2, 0x4, 0x8, 0x80, 0x100, 0x10000) if b & ~m & MOVE_BITS]
        out.append("  %-24s mask 0x%-6X blocked by %s" % (who, m, ", ".join(stop)))
    return "\n".join(out)


def attr_notes(v):
    """Human-readable annotation of an ATTR cell value: one short name per set bit.

    The cell is a set of independent bits in six merge groups (Map_SetAttrTileFlags
    RF4S.exe+0x193430): A = 0x1018F (walking / placement), B = 0x1C0E00 (stairs and
    0x80000; one at most), C = 0x1000, D = 0x6002E040 (the surface; one at most),
    E = 0x10000, F = 0x7800000. Map_InitImage (+0x193110) loads a file's cells verbatim.
    Readers (the callers of Tile_GetAttrAt +0x1933D0 and the functions that index the grid
    inline):
      Actor_TryMoveWithTileSlide     -- walking, cell & ~actor mask & 0x1018F (walk_help)
      MonsterScript_Op16_Blink...    -- blink landing needs 0x21 set and none of 0x9E
      Companion_TickAnimation        -- monster spawn scatter needs 0x21
      Npc_TickWanderBehavior         -- NPC wander, mask 0xE
      ItemDrop_SpawnInWorld          -- bad drop tile: 0x1C set and 0x1 clear
      projectile code                -- 0x2, 0x18, 0x4, 0x400001
      Player_TickFacingTileActAndTriggers -- tile ahead & 0x14018 (the fishing-rod cast)
      Map_IsNonWaterTileAt           -- 0x4008 = water
      Sakura_PlantFlowerTick         -- rewrites 0x40 on a 3x3 patch
      tile-object / spawn gates      -- 0x20
    """
    n = []
    if v & 0x1:      n.append("spawn-ok")
    if v & 0x2:      n.append("block")
    if v & 0x4:      n.append("half-block")
    if v & 0x8:      n.append("water")
    if v & 0x10:     n.append("splash")
    if v & 0x20:     n.append("tillable")
    if v & 0x40:     n.append("flower")
    if v & 0x80:     n.append("layer-1")
    if v & 0x100:    n.append("layer-2")
    if v & 0x200:    n.append("stairs→")     # descend rightward (top-left, bottom-right)
    if v & 0x400:    n.append("stairs←")     # descend leftward  (top-right, bottom-left)
    if v & 0x1000:   n.append("unk:1000")    # zone tag, Sechs Territory + ROOM_06D
    if v & 0x2000:   n.append("grass")
    if v & 0x4000:   n.append("fishable-water")
    if v & 0x8000:   n.append("unk:8000")    # zone tag, the lake district
    if v & 0x10000:  n.append("knockback-block")
    if v & 0x20000:  n.append("snow")
    if v & 0x40000:  n.append("stairs↕")     # descend downward  (top-top, bottom-bottom)
    if v & 0x80000:  n.append("unk:80000")   # zone tag, always on layer-2 tiles
    if v & 0x200000: n.append("unk:200000")  # inert authoring tag, Selphia
    if v & 0x400000: n.append("elevated")
    if v & 0x8000000:  n.append("footprint")      # object footprint marker (stamped at load)
    if v & 0x10000000: n.append("unk:10000000")   # maze corridor stubs
    if v & 0x20000000: n.append("gangway")        # the airship gangway's stamp bit
    if v & 0x40000000: n.append("mansion-floor")  # Obsidian Mansion (DUNG_C) walkable-floor marker
    # Every bit that occurs in a shipped map has a label above; anything left is a bit no
    # shipped map uses, so flag it rather than pretend it means something.
    NAMED = 0x786FF7FF
    rest = v & ~NAMED
    if rest:
        n.append("unk:0x%X" % rest)
    return ",".join(n) if n else "empty (walkable)"


# ---------------------------------------------------------------------------
# Hover help for the Paint ATTR controls.
#
# SURFACE_FIELD is the loader's group D (0x6002E040) and STAIR_FIELD its group B
# (0x1C0E00 -- the stair bits and 0x80000). The loader copies a file's cell verbatim, but
# Map_SetAttrTileFlags replaces a whole group when the game writes one, and no shipped cell
# (3,280,534 checked) carries two bits of either group, so each is a single-choice
# dropdown rather than checkboxes.
SURFACE_FIELD = (0x40, 0x2000, 0x4000, 0x8000, 0x20000, 0x20000000, 0x40000000)
STAIR_FIELD = (0x200, 0x400, 0x40000, 0x80000)

# Notes on the bits whose meaning is not known, from a live read of the running game.
# None of them is read by any engine code found, and none was ever seen to change.
#   0x10000000  World of Fields + every Sharance Maze floor: the four corridor stubs that
#               radiate from the central arena (the generator's edge-connection regions).
#   0x200000    Selphia maps. Inert authoring metadata.
#   0x1000      MAP_DUNG_L14/23/26/28 + ROOM_06D.   0x80000  MAP_DUNG_D* / I*.
#   0x8000      The seven lake/river/hill maps around Sercerezo.

# The surface field as a single-choice list: label -> mask.
SURFACE_CHOICES = [
    ("(none)",          0),
    ("flower",          0x40),
    ("grass",           0x2000),
    ("fishable water",  0x4000),
    ("unk 8000",        0x8000),
    ("snow",            0x20000),
    ("gangway",         0x20000000),
    ("mansion-floor",   0x40000000),
]
SURFACE_BY_LABEL = {a: b for a, b in SURFACE_CHOICES}
SURFACE_BY_MASK = {b: a for a, b in SURFACE_CHOICES}

# The stair field (group B) as a single-choice list.
STAIR_CHOICES = [
    ("(none)",          0),
    ("stairs→",         0x200),
    ("stairs←",         0x400),
    ("stairs↕",         0x40000),
    ("unk 80000",       0x80000),
]
STAIR_BY_LABEL = {a: b for a, b in STAIR_CHOICES}
STAIR_BY_MASK = {b: a for a, b in STAIR_CHOICES}

# The independent bits, one checkbox each (the two fields above are dropdowns).
PAINT_FLAGS = [
    ("spawn-ok", 0x1), ("block", 0x2), ("half-block", 0x4), ("water", 0x8),
    ("splash", 0x10), ("tillable", 0x20),
    ("layer-1", 0x80), ("layer-2", 0x100),
    ("knockback-block", 0x10000), ("elevated", 0x400000),
    ("unk 1000", 0x1000), ("unk 200000", 0x200000),
    ("footprint", 0x8000000), ("unk 10000000", 0x10000000),
]


def _field_help(title, choices, note):
    out = [title, note, ""]
    for label, mask in choices:
        if not mask:
            continue
        first = (ATTR_BIT_HELP.get(mask, "") or "").split("\n")[0]
        out.append("  %-15s 0x%-9X %s" % (label, mask, first))
    return "\n".join(out)


def surface_help():
    """Hover text for the surface dropdown itself."""
    return _field_help("Surface (one per tile).", SURFACE_CHOICES,
                       "The loader copies a cell as stored, but no shipped tile carries more\n"
                       "than ONE of these: verified over every shipped map, 3,280,534 cells,\n"
                       "not one with two of them set. That is why this is a dropdown.")


def stairs_help():
    """Hover text for the stairs dropdown."""
    return _field_help("Stairs (one per tile).", STAIR_CHOICES,
                       "No shipped tile carries two of these, so a tile has one at most.")


_SURFACE_NOTE = ("A tile may carry only ONE of\n"
                 "flower / grass / fishable water / 0x8000 / snow / gangway /\n"
                 "mansion-floor. No shipped tile sets two.")
_STAIR_NOTE = ("A tile may carry only ONE of the three\n"
               "stair directions and 0x80000. No shipped tile sets two.")
_WALK_NOTE = "\n\n" + walk_help()

ATTR_BIT_HELP = {
    0x1: "Marks a spot where things may be placed: monster spawns, landing spots.\n"
         "It is NOT needed for walking and never blocks: every actor ignores it\n"
         "(see below). What reads it: the monster spawn scatter and the blink\n"
         "landing (both want 0x21), companions placed after a warp, item drops\n"
         "(a 0x1C tile without 0x1 is a bad drop spot) and boss-room setup." + _WALK_NOTE,
    0x2: "Impassable wall. Blocks every walker and the knock-back slide.\n"
         "Also NPC wander, thrown items and scatter placement. What an out-of-\n"
         "bounds tile reads as, so a missing grid is solid.",
    0x4: "Half block. Stops walking (everyone); arrows and other projectile\n"
         "actors pass, though a thrown item still reacts to it.",
    0x8: "Deep water. Blocks the player too (unless water boots are equipped),\n"
         "party members, monsters and NPCs; triggers the splash and counts as\n"
         "water for fishing (like 0x4000).",
    0x10: "Splash surface.\n"
          "Never blocks walking (it is outside the 0x1018F movement group). It is\n"
          "read only by the projectile masks (0x18: a thrown item splashes) and by\n"
          "the tile-ahead mask 0x14018. No shipped map authors it, and no placed\n"
          "object's collision template contains it.",
    0x20: "Farm soil: tillable, and the gate for tile objects and entity spawns.\n"
          "Tilling also needs the map to have a farm field (it fails on a map\n"
          "without one, whatever the tile says). Only MAP_FARM_00..04 and\n"
          "MAP_FIELD_A0..A3 have one. Removing 0x20 from a farm tile\n"
          "makes the game drop the\n"
          "crop on it when the farm display is rebuilt.",
    0x40: "Flower ground.\n"
          "Engine reads it: the flower-planting tick clears and re-sets it on a\n"
          "3x3 patch.\n" + _SURFACE_NOTE,
    0x80: "Elevation layer 1. Blocks monsters and event NPCs, not the player or\n"
          "the party (they ignore it).",
    0x100: "Elevation layer 2. Blocks monsters only (the player, the party and\n"
           "event NPCs ignore it).",
    0x200: "Marks a staircase descending to the right.\n"
           "NOT read by any engine code. This is an authoring convention seen in\n"
           "the shipped city maps, not behaviour. Painting it changes nothing.\n" + _STAIR_NOTE,
    0x400: "Marks a staircase descending to the left.\n"
           "NOT read by any engine code. Authoring convention only.\n" + _STAIR_NOTE,
    0x2000: "Grass ground.\n"
            "NOT read by any engine code found.\n" + _SURFACE_NOTE,
    0x4000: "Fishable water.\n"
            "The game counts it as water, like 0x8,\n"
            "and a tile ahead with it (mask 0x14018) lets the player's charged tool\n"
            "action go ahead (the fishing-rod cast). It never blocks walking.\n" + _SURFACE_NOTE,
    0x10000: "Stops only the knock-back slide.\n"
             "The player, the party, monsters and NPCs all ignore it when walking\n"
             "(it is in their masks); only a hit's knock-back slide (mask 0x21)\n"
             "stops at it. Often paired with water to keep a knocked-back actor out\n"
             "of a lake. Also in the tile-ahead mask 0x14018. Has a merge group to\n"
             "itself, so it is set and cleared independently." + _WALK_NOTE,
    0x20000: "Snow / icy ground.\n"
             "The name is confirmed by the season variants: Selphia's WINTER file\n"
             "sets it on ~1000 walkable tiles that are plain path in the spring,\n"
             "summer and autumn files of the same map. It is not winter-only\n"
             "though -- 97 maps use it, mostly the cold dungeons.\n"
             "NOT read by any engine code, so it is ground appearance only.\n" + _SURFACE_NOTE,
    0x40000: "Marks a staircase descending vertically.\n"
             "NOT read by any engine code. Authoring convention only.\n" + _STAIR_NOTE,
    0x400000: "Raised ground. Projectiles pass overhead rather than hitting.\n"
              "Engine reads it: projectile release and flight, and defeat cleanup.\n"
              "The stone templates stamp it together with 0x4.",
    0x8000000: "Object footprint marker.\n"
               "Placed objects stamp it into the grid when the room loads: the\n"
               "collision of trees, rocks, stumps and stones carries it (0x8000002 on\n"
               "trees), and the Sharance Maze writes it onto its filler tiles.\n"
               "Not normally painted -- the View tab's 'object collision' layer shows\n"
               "where the objects put it. No reader of the bit itself was found.",
    0x20000000: "Gangway.\n"
                "The airship gangway (object 294) stamps 0x20000001 when the\n"
                "room loads. Shipped maps also carry it\n"
                "as one connected walkable region on 17 maps (Melody Street, the\n"
                "Obsidian Mansion Theatre, nine FIELD maps, ROOM_25/26). No reader of\n"
                "the bit was found.\n" + _SURFACE_NOTE,
    0x40000000: "Marks floor INSIDE the Obsidian Mansion building.\n"
                "On the entrance map (C03) all 1,203 interior tiles carry it and\n"
                "the only walkable tiles that do not are the 58-tile approach\n"
                "corridor leading in from outside. 14 maps, MAP_DUNG_C03 to C19.\n"
                "NOT read by any engine code found, and a live read of C03 showed\n"
                "it is never modified at runtime.\n" + _SURFACE_NOTE,

    # ---- bits that occur in shipped maps but whose meaning is NOT known ----
    # No engine code reads any of them, and a live read of the running game never saw one
    # change, so they cannot affect behaviour. The reasoning is given so the next person
    # can pick it up rather than start over.
    0x1000: "UNKNOWN.\n"
            "Where: 5 maps only -- Sechs Territory MAP_DUNG_L14/23/26/28 and\n"
            "MAP_ROOM_06D. 2,251 cells.\n"
            "Shape: 100% on walkable tiles, and on 4 of the 5 maps it is ONE\n"
            "connected blob filling the open interior, set in from the edges.\n"
            "My reading: a zone tag the level authors put on a whole area, not a\n"
            "property of the ground. An encounter or music region would fit the\n"
            "shape, but nothing reads it, so that is a guess and no more.",
    0x8000: "UNKNOWN.\n"
            "Where: 7 maps, all the Sercerezo/lake district -- Keeno Lake, Silver\n"
            "Lake x2, Sercerezo Lake, Sercerezo Hill, Autumn River, Autumn Road.\n"
            "1,264 cells.\n"
            "Shape: 100% walkable, and exactly ONE connected region on all 7.\n"
            "On the lakes it hugs the shoreline; on Sercerezo Hill and Autumn Road\n"
            "(one shared geometry) it runs through the middle of the island instead.\n"
            "My reading: a ground material such as sand would fit both -- beach at\n"
            "the lakes, a sandy path on the hill -- and it sits in the surface field\n"
            "with grass and snow, which is consistent. Unproven.\n"
            + _SURFACE_NOTE,
    0x80000: "UNKNOWN.\n"
             "Where: 17 maps, dungeons D and I. 1,351 cells.\n"
             "Shape: the one hard fact here -- every single one of the 1,351 cells\n"
             "is a walkable tile that ALSO carries layer-2 (0x100). 1351 of 1351,\n"
             "no exceptions. It appears as small blobs, 1 to 5 per map, usually in\n"
             "symmetric pairs flanking an elevated walkway.\n"
             "My reading: it annotates particular elevated walkway segments. The\n"
             "perfect layer-2 correlation is real; what it marks about them is not\n"
             "known.\n" + _STAIR_NOTE,
    0x200000: "UNKNOWN, and probably meaningless.\n"
              "Where: the Selphia maps. Airship Way, Melody Street, Observatory\n"
              "and CITY_07.\n"
              "Shape: it looked like a rule on Airship Way, where it sits on exactly\n"
              "the 1,438 half-block tiles and nowhere else. CITY_07 breaks it: all\n"
              "6,400 tiles of that fully walkable map carry it and none is a\n"
              "half-block.\n"
              "My reading: leftover authoring metadata. It correlates with nothing,\n"
              "no code reads it, and a live read showed it never changes.",
    0x10000000: "UNKNOWN, but its role is clear.\n"
                "Where: World of Fields plus every Sharance Maze floor, 12 maps.\n"
                "Shape: on F02 it tags the four corridor stubs radiating from the\n"
                "central arena, covering BOTH their floor and their walls. The arena\n"
                "itself is deliberately untagged.\n"
                "My reading: the generator's edge-connection regions, the places\n"
                "rooms get attached. Confirmed against a live read. The name is mine.",
}


def attr_bit_help(mask):
    """Hover text for one Paint ATTR checkbox."""
    body = ATTR_BIT_HELP.get(mask)
    if not body:
        return "0x%X\nNo description recorded for this bit." % mask
    return "0x%X\n%s" % (mask, body)


# ---------------------------------------------------------------------------
# Paint-value helpers (the Paint / Fill / Rectangle tools share one value)
# ---------------------------------------------------------------------------
PAINT_PRESETS = (("empty", 0x0), ("spawn-ok", 0x1), ("block", 0x2), ("water", 0x8),
                 ("grass", 0x2001))
_FLAG_MASK = 0
for _n, _m in PAINT_FLAGS:
    _FLAG_MASK |= _m
_SURFACE_MASK = 0
for _m in SURFACE_FIELD:
    _SURFACE_MASK |= _m
_STAIR_MASK = 0
for _m in STAIR_FIELD:
    _STAIR_MASK |= _m


def compose_value(base, flags, surface_label, stair_label="(none)"):
    """Rebuild a cell value from the checkbox set `flags` and the surface / stairs dropdown
    labels, keeping every bit of `base` that no control owns."""
    v = base & ~_FLAG_MASK & ~_SURFACE_MASK & ~_STAIR_MASK
    for m in flags:
        v |= m
    return v | SURFACE_BY_LABEL.get(surface_label, 0) | STAIR_BY_LABEL.get(stair_label, 0)


def surface_label(value):
    """The surface dropdown entry for `value`. A hand-typed value can carry two surface
    bits although the game never produces one; the lowest wins here and the decode
    label shows the rest."""
    for m in SURFACE_FIELD:
        if value & m:
            return SURFACE_BY_MASK.get(m, "(none)")
    return "(none)"


def stair_label(value):
    """The stairs dropdown entry for `value` (the lowest stair bit, as surface_label)."""
    for m in STAIR_FIELD:
        if value & m:
            return STAIR_BY_MASK.get(m, "(none)")
    return "(none)"


def parse_value(text):
    """'0x201', '513' or '0x201  path,...' -> int, or None for junk."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        return int(t.split()[0], 0) & 0xFFFFFFFF
    except ValueError:
        return None


def assign_colors(cells, colors=None):
    """Colour every distinct value in `cells`: 0 = empty ground (its own neutral colour),
    the most common other value = floor, the rest from ATTR_PALETTE in frequency order.
    Existing entries in `colors` are kept so a value keeps its colour across edits."""
    from collections import Counter
    colors = {} if colors is None else colors
    common = [v for v, _n in Counter(cells).most_common()]
    for v in common:
        if v in colors:
            continue
        if v == 0:
            colors[v] = ATTR_EMPTY
        elif not any(c == ATTR_FLOOR for c in colors.values()):
            colors[v] = ATTR_FLOOR
        else:
            colors[v] = ATTR_PALETTE[sum(1 for c in colors.values()
                                         if c not in (ATTR_EMPTY, ATTR_FLOOR)) % len(ATTR_PALETTE)]
    return colors
