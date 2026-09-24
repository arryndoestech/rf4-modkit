"""ATTR tile-attribute knowledge: what each bit of a cell means, how the Paint controls
group them, and the colours the editor draws them in.

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
ATTR_VOID = (24, 24, 28)
ATTR_FLOOR = (70, 74, 82)
ATTR_PALETTE = [
    (120, 90, 60), (60, 110, 130), (110, 70, 110), (90, 120, 70),
    (150, 120, 50), (70, 90, 150), (140, 70, 70), (60, 130, 110),
    (110, 110, 110), (90, 70, 130), (130, 100, 80), (70, 120, 130),
]

# ATTR cell values that occur in >=4 of the 872 stock maps (empirically scanned).
# Used to pre-fill the Paint dropdown so any known tile attribute can be applied.
# Every distinct ATTR cell value that occurs in the 872 shipped maps, measured
# 2026-09-21 over all 3,280,534 cells. The previous list held 60 of these 110.
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


def attr_notes(v):
    """Human-readable annotation of an ATTR cell value.

    The low nibble is **independent flag bits**, NOT a single passability code:
    values like 0x3 and 0x5 occur in 185+/27+ stock maps respectively, which is
    impossible for a single-code interpretation. Each bit is decoded individually.

    IDA-evidenced masks across the codebase (every bit below is read by at least
    one of these functions; names re-checked 2026-09-19 by decompiling all 15
    callers of Tile_GetAttrAt in RF4S.exe):
      Actor_TryMoveWithTileSlide      — char movement,         mask 0x1018F
      MonsterScript_Op16_BlinkTeleportNearTarget — blink landing tile, `&0x21 && !(&0x9E)`
      Npc_TickWanderBehavior          — NPC block,             mask 0xE
      ItemDrop_SpawnInWorld           — bad drop tile,         `&0x1C && !(&1)`
      Item_ApplyThrowVelocity         — abort throw,           mask 0x2 (+0x10 splash)
      Actor_ReleaseHeldEntityAsProjectile — throw launch,      masks 0x18 | 0x400001
      Actor_TickFlyingProjectile_FallAndLand — fly/splash/wall, masks 0x400001 | 0x18 | 0x4
      Player_TickFacingTileActAndTriggers — tile ahead blocks tool/aim, mask 0x14018
      Sakura_PlantFlowerTick (+0x14E510) — gate + write 0x40 on 3×3
      Map_ForceSpawnAtFirstFreeSlot   — spawnable tile gate,   mask 0x20
      Map_TestTileBlockedAtTilePos    — collision iter gate,   mask 0x20
      TileObject_FindAt               — tile-object lookup,    mask 0x20

    Per-bit summary (IDA = mask-evidenced; USER = user-observed; CORPUS = stock-map
    category exclusivity; TENTATIVE = corpus-strong, no IDA mask seen yet):

      - 0x1      = path/walkable (monster blink-teleport landing needs path|tillable) (IDA)
      - 0x2      = block (impassable wall — universal blocker)                (IDA)
      - 0x4      = half-block (blocks chars, projectile-permeable per arrow   (IDA + USER)
                   actors; thrown items still impact per projectile code)
      - 0x8      = water (deep — blocks NPC/monster, splash trigger)          (IDA)
      - 0x10     = water-FX / shallow water (splash trigger + player block)   (IDA + USER)
      - 0x20     = tillable / entity-spawnable (FARM soil)                    (IDA + CORPUS)
      - 0x40     = flower-FX (cleared & re-set by Sakura plant code on 3×3)   (IDA + USER)
      - 0x80     = layer-1 (elevation/passability layer; blocks monsters)     (IDA)
      - 0x100    = layer-2 (elevation/passability layer)                      (IDA)
      - 0x200    = stairs→ — staircase descending RIGHTWARD (top-left,         (USER + CORPUS)
                   bottom-right). Render-only, overlaid on walkable path
                   (value 0x201). MAP_CITY_02's diagonal stairs.
      - 0x400    = stairs← — staircase descending LEFTWARD (top-right,         (USER + CORPUS)
                   bottom-left). Render-only on path. MAP_CITY_00's
                   left-side stairs.
      - 0x40000  = stairs↕ — staircase descending DOWNWARD/vertical (top at    (USER + CORPUS)
                   top, bottom at bottom). Render-only. MAP_CITY_02 narrow
                   vertical band (x66-71), MAP_CITY_00 wide entrance stairs.
                   (The three stair bits give the slope direction: the diagonal
                   arrows → / ← point the way you walk to go DOWN; the vertical
                   stair uses ↕ since it's walked both up and down. Earlier guess
                   "indoor floor" for 0x40000 was wrong.)
      - 0x40000000 = mansion-floor — walkable-floor marker, RENDER-ONLY        (CORPUS, effect TBD)
                   (group D). EXCLUSIVE to the Obsidian Mansion dungeon
                   (MAP_DUNG_C03..C19); 100% on path floor. Sibling of bit 29
                   (0x20000000 = field/town walkable region); they never
                   co-occur. Exact visual effect not yet confirmed.
      - 0x2000   = grass-FX (cleared by Sakura plant code, mutually excl.)    (USER + IDA-corr.)
      - 0x4000   = obstructed/rocky-rough (in player-aim block mask 0x14018)  (IDA)
      - 0x10000  = force-block (overrides any walkable bit)                   (IDA)
      - 0x20000  = snow / cold surface (cleared by Sakura plant code)         (TENTATIVE + IDA-corr.)
      - 0x400000 = elevated / fly-over (projectiles pass overhead in          (IDA + USER)
                   0x400001 mask; paired with 0x400 = step boundary)

    GROUP MODEL (Map_InitImage, re-verified 2026-06-17): the cell DWORD is merged in
    independent bit-groups — A=0x1018F (collision, the ONLY group gameplay reads for
    movement), D=0x6002E040 (FX/surface; only its bit 0x40 flower-fx is read), and
    B=0x1C0E00 / C=0x1000 / F=0x7800000 which NO gameplay reader ever tests → those are
    render/display-only (tile-graphic variant / draw layer). (The merge starts from a
    zeroed cell and ORs leftover bits back, so the stored value loads unchanged.) Any set bit outside the
    named gameplay bits is reported as `render:0x..` so it's visible but flagged as
    non-collision (editing it won't change what blocks the player).
    """
    n = []
    if v & 0x1:      n.append("path")
    if v & 0x2:      n.append("block")
    if v & 0x4:      n.append("half-block")
    if v & 0x8:      n.append("water")
    if v & 0x10:     n.append("water-fx")
    if v & 0x20:     n.append("tillable")
    if v & 0x40:     n.append("flower-fx")
    if v & 0x80:     n.append("layer-1")
    if v & 0x100:    n.append("layer-2")
    if v & 0x200:    n.append("stairs→")     # descend rightward (top-left, bottom-right)
    if v & 0x400:    n.append("stairs←")     # descend leftward  (top-right, bottom-left)
    if v & 0x1000:   n.append("unk:1000")    # zone tag, Sechs Territory + ROOM_06D
    if v & 0x2000:   n.append("grass-fx")
    if v & 0x4000:   n.append("obstructed")
    if v & 0x8000:   n.append("unk:8000")    # zone tag, the lake district
    if v & 0x10000:  n.append("force-block")
    if v & 0x20000:  n.append("snow")
    if v & 0x40000:  n.append("stairs↕")     # descend downward  (top-top, bottom-bottom)
    if v & 0x80000:  n.append("unk:80000")   # zone tag, always on layer-2 tiles
    if v & 0x200000: n.append("unk:200000")  # inert authoring tag, Selphia
    if v & 0x400000: n.append("elevated")
    if v & 0x8000000:  n.append("unk:8000000")   # maze out-of-bounds filler
    if v & 0x10000000: n.append("unk:10000000")  # maze corridor stubs
    if v & 0x20000000: n.append("unk:20000000")  # zone tag, one contiguous walkable region
    if v & 0x40000000: n.append("mansion-floor")  # Obsidian Mansion (DUNG_C) walkable-floor marker
    # Every bit that occurs in a shipped map now has a label above. Anything left is
    # a bit no shipped map uses, so flag it rather than pretend it means something.
    NAMED = 0x786FF7FF
    rest = v & ~NAMED
    if rest:
        n.append("render:0x%X" % rest)
    return ",".join(n) if n else "open"


# ---------------------------------------------------------------------------
# Ctrl-hover help for the Paint ATTR checkboxes.
#
# Each entry is what that bit actually does, and how well that is evidenced.
# "Engine reads it" means at least one function applies a mask containing the bit
# to a value fetched from the tile-attribute grid. Those readers are: the 14
# callers of Tile_GetAttrAt (RF4S.exe+0x1933D0) plus four functions that index the
# grid inline -- Map_IsDeepWaterTileAt (+0x1839C0), Monster_QueryTileBlocked-
# OrReachedTarget (+0x1D2750), ScriptedZone_PickValidScatterPos (+0x1E6AE0) and
# Combat_LineOfSightCheck (+0x1D1C20). Between them they test only 0x4141FF.
#
# SURFACE_FIELD is the loader's group D (0x6002E040 in Map_InitImage,
# RF4S.exe+0x193110). NOTE: at load the merge starts from a zeroed cell and ORs any
# leftover bits back in, so a file's cell value is loaded VERBATIM -- the loader does
# not enforce one-of. The one-of rule is the shipped data's: across every shipped map
# (3,280,534 cells) no cell has two group-D bits set, so the editor keeps it a
# dropdown rather than let a tile carry a combination no shipped map uses.
SURFACE_FIELD = (0x40, 0x2000, 0x4000, 0x8000, 0x20000, 0x20000000, 0x40000000)

# Notes on the bits whose meaning is not known, from a live read of the running game.
# None of them is read by any engine code found, and none was ever seen to change.
#   0x8000000   Sharance Maze F02/F03 only. Tags the solid filler OUTSIDE the
#               playable area -- 2,901 of its 2,960 cells on MAP_DUNG_F02 are the
#               dead border. Also written by Map_SetupBossRoomLayoutPrep.
#   0x10000000  World of Fields + every Sharance Maze floor. Tags the four
#               corridor stubs that radiate from the central arena, covering both
#               their floor and their walls -- the generator's edge-connection
#               regions. The arena itself is untagged.
#   0x200000    Selphia maps. Inert authoring metadata: on Airship Way it sits on
#               exactly the half-block tiles, but on MAP_CITY_07 it covers all
#               6,400 tiles of a fully walkable map, so it correlates with nothing.
#   0x1000      MAP_DUNG_L14/23/26/28 + ROOM_06D.   0x80000  MAP_DUNG_D* / I*.
#   0x8000      The seven lake/river/hill maps around Sercerezo.

# The surface field as a single-choice list: label -> mask. Exactly one may be set,
# so the Paint panel offers these as a dropdown rather than seven checkboxes.
SURFACE_CHOICES = [
    ("(none)",          0),
    ("flower",          0x40),
    ("grass",           0x2000),
    ("water-edge",      0x4000),
    ("unk 8000",        0x8000),
    ("snow",            0x20000),
    ("unk 20000000",    0x20000000),
    ("mansion-floor",   0x40000000),
]
SURFACE_BY_LABEL = {a: b for a, b in SURFACE_CHOICES}
SURFACE_BY_MASK = {b: a for a, b in SURFACE_CHOICES}

# The independent bits, one checkbox each. The surface field is NOT here: it is a
# dropdown, because the loader merges those seven as one mutually-exclusive value.
PAINT_FLAGS = [
    ("path", 0x1), ("block", 0x2), ("half-block", 0x4), ("water", 0x8),
    ("water-fx", 0x10), ("tillable", 0x20),
    ("layer-1", 0x80), ("layer-2", 0x100),
    ("stairs→", 0x200), ("stairs←", 0x400), ("stairs↕", 0x40000),
    ("force-block", 0x10000), ("elevated", 0x400000),
    ("unk 1000", 0x1000), ("unk 80000", 0x80000), ("unk 200000", 0x200000),
    ("unk 8000000", 0x8000000), ("unk 10000000", 0x10000000),
]


def surface_help():
    """Ctrl-hover text for the surface dropdown itself."""
    out = ["The surface field (loader group D).",
           "The loader copies a cell as stored, but no shipped tile carries more",
           "than ONE of these: verified over every shipped map, 3,280,534 cells,",
           "not one with two of them set. That is why this is a dropdown.",
           ""]
    for label, mask in SURFACE_CHOICES:
        if not mask:
            continue
        first = (ATTR_BIT_HELP.get(mask, "") or "").split("\n")[0]
        out.append("  %-14s 0x%-9X %s" % (label, mask, first))
    return "\n".join(out)
_SURFACE_NOTE = ("Surface field (loader group D): a tile may carry only ONE of\n"
                 "flower / grass / obstructed / 0x8000 / snow / 0x20000000 /\n"
                 "mansion-floor. No shipped tile sets two.")

ATTR_BIT_HELP = {
    0x1: "Walkable floor.\n"
         "Engine reads it: the main movement mask, item-drop placement and\n"
         "monster blink-teleport landing all require it.",
    0x2: "Impassable wall. The universal blocker.\n"
         "Engine reads it: movement, NPC wander, tool aiming, scatter placement.\n"
         "Also what an out-of-bounds tile reads as, so a missing grid is solid.",
    0x4: "Half block. Stops walking; arrow actors are allowed through.\n"
         "Engine reads it: movement, item-drop placement, and the projectile\n"
         "code, which tests it separately -- a thrown item still reacts to it.",
    0x8: "Deep water. Blocks NPCs and monsters and triggers the splash.\n"
         "Engine reads it: movement, projectiles, and the deep-water test that\n"
         "fishing uses.",
    0x10: "Shallow water / splash surface.\n"
          "Engine reads it, BUT no shipped map authors it anywhere. It is stamped\n"
          "at runtime from a placed entity's own tile mask, so painting it by hand\n"
          "produces something the shipped maps never contain.",
    0x20: "Farm soil: tillable, and the gate for tile objects and entity spawns.\n"
          "Engine reads it: tile-object lookup, spawn placement, blink landing.",
    0x40: "Flower ground.\n"
          "Engine reads it: the flower-planting tick clears and re-sets it on a\n"
          "3x3 patch.\n" + _SURFACE_NOTE,
    0x80: "Elevation / passability layer 1.\n"
          "Engine reads it as part of the movement mask; blocks monsters.",
    0x100: "Elevation / passability layer 2.\n"
           "Engine reads it as part of the movement mask.",
    0x200: "Marks a staircase descending to the right.\n"
           "NOT read by any engine code. This is an authoring convention seen in\n"
           "the shipped city maps, not behaviour. Painting it changes nothing.",
    0x400: "Marks a staircase descending to the left.\n"
           "NOT read by any engine code. Authoring convention only.",
    0x2000: "Grass ground.\n"
            "NOT read by any engine code found.\n" + _SURFACE_NOTE,
    0x4000: "Rough ground at the water's edge.\n"
            "Engine reads it twice: it blocks tool aiming, and the deep-water test\n"
            "counts it together with water, so it marks the shallow rim around a\n"
            "lake or river.\n" + _SURFACE_NOTE,
    0x10000: "Hard block that overrides any walkable bit.\n"
             "Engine reads it: part of the movement and aiming masks. Often paired\n"
             "with water to seal a lake off (37% of all water tiles carry it).\n"
             "Has a merge group to itself, so it is set and cleared independently.",
    0x20000: "Snow / icy ground.\n"
             "The name is confirmed by the season variants: Selphia's WINTER file\n"
             "sets it on ~1000 walkable tiles that are plain path in the spring,\n"
             "summer and autumn files of the same map. It is not winter-only\n"
             "though -- 97 maps use it, mostly the cold dungeons.\n"
             "NOT read by any engine code, so it is ground appearance only.\n" + _SURFACE_NOTE,
    0x40000: "Marks a staircase descending vertically.\n"
             "NOT read by any engine code. Authoring convention only.",
    0x400000: "Raised ground. Projectiles pass overhead rather than hitting.\n"
              "Engine reads it: projectile release and flight, and defeat cleanup.",

    # ---- bits that occur in shipped maps but whose meaning is NOT known ----
    # Everything below is honest guesswork. No engine code reads any of them, and
    # a live read of the running game never saw one change, so they cannot affect
    # behaviour. What each one IS remains unknown; the reasoning is given so the
    # next person can pick it up rather than start over.
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
            "My reading: I first thought shoreline, and the lake maps support that,\n"
            "but the hill maps break it. A ground material such as sand would fit\n"
            "both -- beach at the lakes, a sandy path on the hill -- and it sits in\n"
            "the surface field with grass and snow, which is consistent. Unproven.\n"
            + _SURFACE_NOTE,
    0x80000: "UNKNOWN.\n"
             "Where: 17 maps, dungeons D and I. 1,351 cells.\n"
             "Shape: the one hard fact here -- every single one of the 1,351 cells\n"
             "is a walkable tile that ALSO carries layer-2 (0x100). 1351 of 1351,\n"
             "no exceptions. It appears as small blobs, 1 to 5 per map, usually in\n"
             "symmetric pairs flanking an elevated walkway.\n"
             "My reading: it annotates particular elevated walkway segments. The\n"
             "perfect layer-2 correlation is real; what it marks about them is not\n"
             "known.",
    0x200000: "UNKNOWN, and probably meaningless.\n"
              "Where: the Selphia maps. Airship Way, Melody Street, Observatory\n"
              "and CITY_07.\n"
              "Shape: it looked like a rule on Airship Way, where it sits on exactly\n"
              "the 1,438 half-block tiles and nowhere else. CITY_07 breaks it: all\n"
              "6,400 tiles of that fully walkable map carry it and none is a\n"
              "half-block.\n"
              "My reading: leftover authoring metadata. It correlates with nothing,\n"
              "no code reads it, and a live read showed it never changes. Of all\n"
              "these bits this is the one I would most expect to be inert.",
    0x8000000: "UNKNOWN, but its role is clear.\n"
               "Where: 3 Sharance Maze floors, MAP_DUNG_F02/F03/F03_SUB.\n"
               "Shape: 2,901 of its 2,960 cells on F02 are the solid filler OUTSIDE\n"
               "the playable area. It is also the value Map_SetupBossRoomLayoutPrep\n"
               "writes.\n"
               "My reading: a structural tag meaning 'not real playable space',\n"
               "used by the dungeon generator. Confirmed by a live read of F02,\n"
               "which matched the shipped template exactly. The name is mine, not\n"
               "the game's.",
    0x10000000: "UNKNOWN, but its role is clear.\n"
                "Where: World of Fields plus every Sharance Maze floor, 12 maps.\n"
                "Shape: on F02 it tags the four corridor stubs radiating from the\n"
                "central arena, covering BOTH their floor and their walls. The arena\n"
                "itself is deliberately untagged.\n"
                "My reading: the generator's edge-connection regions, the places\n"
                "rooms get attached. Confirmed against a live read. Again, the\n"
                "name is mine.",
    0x20000000: "UNKNOWN.\n"
                "Where: 17 maps -- Melody Street, the Obsidian Mansion Theatre,\n"
                "nine FIELD maps and ROOM_25/26. 4,248 cells.\n"
                "Shape: 100% walkable and exactly ONE connected region on all 17.\n"
                "In the Theatre it forms a frame around an open central floor, and\n"
                "half of it there also carries layer-1.\n"
                "My reading: a zone tag on a walkable area, like 0x1000 and 0x8000.\n"
                "The Theatre shape suggests a gallery or raised surround, but the\n"
                "nine field maps do not obviously fit that, so it stays unknown.\n"
                + _SURFACE_NOTE,
    0x40000000: "Marks floor INSIDE the Obsidian Mansion building.\n"
                "On the entrance map (C03) all 1,203 interior tiles carry it and\n"
                "the only walkable tiles that do not are the 58-tile approach\n"
                "corridor leading in from outside. 14 maps, MAP_DUNG_C03 to C19.\n"
                "NOT read by any engine code found, and a live read of C03 showed\n"
                "it is never modified at runtime.\n" + _SURFACE_NOTE,
}


def attr_bit_help(mask):
    """Ctrl-hover text for one Paint ATTR checkbox."""
    body = ATTR_BIT_HELP.get(mask)
    if not body:
        return "0x%X\nNo description recorded for this bit." % mask
    return "0x%X\n%s" % (mask, body)


# ---------------------------------------------------------------------------
# Paint-value helpers (the Paint / Fill / Rectangle tools share one value)
# ---------------------------------------------------------------------------
PAINT_PRESETS = (("open", 0x0), ("path", 0x1), ("block", 0x2), ("water", 0x8),
                 ("path+grass", 0x2001))
_FLAG_MASK = 0
for _n, _m in PAINT_FLAGS:
    _FLAG_MASK |= _m
_SURFACE_MASK = 0
for _m in SURFACE_FIELD:
    _SURFACE_MASK |= _m


def compose_value(base, flags, surface_label):
    """Rebuild a cell value from the checkbox set `flags` and the surface dropdown label,
    keeping every bit of `base` that no control owns."""
    v = base & ~_FLAG_MASK & ~_SURFACE_MASK
    for m in flags:
        v |= m
    return v | SURFACE_BY_LABEL.get(surface_label, 0)


def surface_label(value):
    """The surface dropdown entry for `value`. A hand-typed value can carry two surface
    bits although the game never produces one; the lowest wins here and the decode
    label shows the rest."""
    for m in SURFACE_FIELD:
        if value & m:
            return SURFACE_BY_MASK.get(m, "(none)")
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
    """Colour every distinct value in `cells`: 0 = void, the most common value = floor,
    the rest from ATTR_PALETTE in frequency order. Existing entries in `colors` are kept
    so a value keeps its colour across edits."""
    from collections import Counter
    colors = {} if colors is None else colors
    common = [v for v, _n in Counter(cells).most_common()]
    for v in common:
        if v in colors:
            continue
        if v == 0:
            colors[v] = ATTR_VOID
        elif not any(c == ATTR_FLOOR for c in colors.values()):
            colors[v] = ATTR_FLOOR
        else:
            colors[v] = ATTR_PALETTE[sum(1 for c in colors.values()
                                         if c not in (ATTR_VOID, ATTR_FLOOR)) % len(ATTR_PALETTE)]
    return colors
