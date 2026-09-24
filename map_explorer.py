#!/usr/bin/env python3
r"""
map_explorer.py -- a full interactive map EDITOR for RF4S, built on rf4s_modkit.

The editor core lives in `MapEditorPanel`, an embeddable widget that renders an `.rf4m`
map and edits it. It is hosted two ways:
  * `MapExplorer`  -- a standalone window (map list + panel), via `python map_explorer.py`
  * inside `rf4mod_gui.py` -- as the "Map (edit)" tab of the main GUI's .rf4m view

`MapEditorPanel` renders the ATTR collision/attribute grid as a coloured image and
overlays placed MOBJ entities at their true tile position (`pos >> 3`, verified vs
`Tile_GetAttrAt`; 1 tile = 8 sub-units), coloured by category, plus MAPJ transition
zones. The "object sprites" layer draws each object as its real 2D billboard sprite
(resolved `type_id -> map_obj sprite -> .texture`, decoded to RGBA) instead of a dot --
structural objects (doors/walls/props) show their art; effects/triggers keep the dot.
It shows map metadata (dimensions, seasons, room/resource id from
`rf4s_rooms.csv`, and the linked `Gen*.bin` monster roster).

EDITOR tools: Select & move (click a dot to select + highlight, drag to move), Add
(click an empty tile to place a new entity of a chosen type_id), and Paint ATTR cells.
Once an entity is selected its type can be changed by NAME via the "Type" dropdown
(no need to know the numeric id); the 16 raw fields apply automatically on edit
(focus-out / Enter) — no Apply button — and "Delete selected entity" (or the Delete
key) removes it. Undo/redo are 40-deep (Ctrl+Z / Ctrl+Y); a Validate button flags warps
to unknown maps and objects/zones off the grid; the Search-items tab edits the map's
`SI_*.bin` daily-pickup spots (move via field or canvas drag, add/delete spots, edit drop
pools, Save SI file…). Save map… writes the edited `.rf4m`. All edits route
through the verified rf4m writers (`add/delete_mobj_record`, `set_mobj_record`,
`set_attr_cell`) and re-emit a byte-valid map. An optional `on_change(bytes)` callback
lets a host (the main GUI) keep its own working copy in sync.

Run:
    python map_explorer.py                 # browse all maps under Bundle/
    python map_explorer.py MAP_DUNG_A04    # open one map

Dependencies: Tkinter (stdlib). Pillow recommended for the rendered grid.
"""
from __future__ import annotations

import csv
import pathlib
import queue
import re
import struct
import sys
import threading
import tkinter as tk
from collections import Counter, OrderedDict
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import rf4m, gen, search_items, textdb, mobj_types, mapground, texture  # noqa: E402
from rf4s_modkit import mobj_params  # noqa: E402  (per-type MOBJ field legend, shown on select)
from rf4s_modkit import map_names  # noqa: E402
from rf4s_modkit import script  # noqa: E402  (rf3.mc event-script disasm — NPC-spawn overlay)

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
BUNDLE_DIR = REPO / "Bundle"
EXTRACTED = (BUNDLE_DIR / "extracted") if (BUNDLE_DIR / "extracted").is_dir() else BUNDLE_DIR
from rf4s_modkit.refdata import refdata_path as _refdata_path
ITEM_NAMES = _refdata_path("rf4s_item_names.json")   # vendored in modding/refdata/
ROOMS_CSV_CANDIDATES = [
    REPO / "tools" / "rf4s_rooms.csv",
    pathlib.Path.home() / ".claude" / "projects"
    / "C--Users-arryn-Documents" / "memory" / "rf4s_rooms.csv",
]

CAT_COLOR = {
    "forage": "#ffb020", "trigger": "#cccccc", "mapparam": "#cccccc", "actor": "#ff4040",
    "object": "#4080ff", "decoration": "#40c040",
}
# Entity kinds that ride the "trig" layer toggle (forage spawn points draw as dots; map
# parameter records 9..19 are positionless and never drawn, but share the key).
_TRIGGER_KINDS = ("forage", "trigger", "mapparam")
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
      Sakura_PlantFlowerTick (+0x18E510) — gate + write 0x40 on 3×3
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
    render/display-only (tile-graphic variant / draw layer). Any set bit outside the
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


def attr_choice(v, in_map=False):
    """Display string for the Paint combobox; value is always the first token."""
    s = "0x%X  %s" % (v, attr_notes(v))
    return s + "   • in this map" if in_map else s


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
# RF4S.exe+0x193110). The loader replaces the whole group at once, so a tile can
# carry at most ONE of these. Verified across every shipped map: 3,280,534 cells,
# zero of them with two group-D bits set. Ticking two here makes a tile the game
# itself can never produce.
SURFACE_FIELD = (0x40, 0x2000, 0x4000, 0x8000, 0x20000, 0x20000000, 0x40000000)

# Bits that occur in shipped maps but have no checkbox here yet, with what a live
# read of the running game showed each one to be. None of them is read by any
# engine code found, and none was ever seen to change at runtime.
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
UNLISTED_BITS = ()   # every occurring bit now has a control in the Paint panel

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
           "The loader replaces this whole group at once, so a tile carries at",
           "most ONE of these. Verified over every shipped map: 3,280,534 cells,",
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


def _load_item_names():
    try:
        import json
        d = json.loads(ITEM_NAMES.read_text(encoding="utf-8"))
        return lambda i: d.get(str(i), "")
    except Exception:
        return lambda i: ""


_EXTRACTED_INDEX = None


def extracted_index():
    """{lower-case basename: [Path, ...]} of every file under EXTRACTED, built once (os.walk, ~0.2 s
    for the ~38k extracted files). Every map load used to rglob() the whole tree two or
    three times to find its SI_/Gen sidecars (~0.5 s per map click). First hit in sorted
    walk order wins, which is the order the old rglob() calls returned."""
    global _EXTRACTED_INDEX
    if _EXTRACTED_INDEX is None:
        idx = {}
        if EXTRACTED.is_dir():
            import os
            for dirpath, dirnames, filenames in os.walk(EXTRACTED):
                dirnames.sort()
                for fn in sorted(filenames):
                    idx.setdefault(fn.lower(), []).append(pathlib.Path(dirpath) / fn)
        _EXTRACTED_INDEX = idx
    return _EXTRACTED_INDEX


def find_extracted(name):
    """Path of an extracted file by basename (case-insensitive), or None."""
    hits = extracted_index().get(str(name).lower())
    return hits[0] if hits else None


def find_extracted_all(name):
    """Every extracted file with this basename (several bundles can carry one), sorted."""
    return list(extracted_index().get(str(name).lower(), ()))


_ROOMS = None


def _load_rooms():
    """{MAP_* base name: (map id, resource id | None)} for every map (parsed once, cached;
    callers treat it as read-only).

    Prefers the optional rf4s_rooms.csv (it also carries the .rf4m archive/resource
    id); otherwise falls back to the modkit's own vendored map-id table
    (map_names.map_file, the g_mapResourceTable order), which has the same
    name <-> id pairs for all 872 maps (checked 2026-09-19). Before the fallback a
    missing CSV silently emptied the dest-map dropdown, the NPC-spawn overlay, the
    map-id line and made Validate flag every warp as unknown."""
    global _ROOMS
    if _ROOMS is not None:
        return _ROOMS
    for p in ROOMS_CSV_CANDIDATES:
        if p.is_file():
            out = {}
            with p.open(encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    try:
                        out[row["name"]] = (int(row["mapId"]), int(row["resourceId"]))
                    except (KeyError, ValueError):
                        pass
            if out:
                _ROOMS = out
                return out
    out = {}
    for mid in range(map_names.map_count() + 1):
        fn = map_names.map_file(mid)
        if fn:
            out[fn] = (mid, None)
    _ROOMS = out
    return out


def gen_file_for_map(map_name: str):
    """MAP_DUNG_X## -> GenX##.bin ; MAP_FIELD_## -> GenField##.bin (docs/15 §6)."""
    m = re.search(r"DUNG_([A-Z]+)(\d+)", map_name) or re.search(r"(FIELD)_?(\d+)", map_name)
    if not m:
        return None
    area, num = m.group(1), int(m.group(2))
    name = f"GenField{num:02d}.bin" if area == "FIELD" else f"Gen{area}{num:02d}.bin"
    return find_extracted(name)


def si_file_for_map(map_name: str):
    """MAP_DUNG_X## -> SI_DUNG_X##.bin ; MAP_FIELD_## -> SI_FIELD_##.bin ;
    MAP_CITY_## -> SI_CITY_##.bin. Strips seasonal suffixes (_SUMMER/_AUTUMN/_WINTER)
    because all 4 seasonal variants of a map share one SI file (per
    g_searchItemArchiveByMapId). Returns the Path or None."""
    base = re.sub(r"\.rf4m$", "", map_name.replace("\\", "/").rsplit("/", 1)[-1],
                  flags=re.I)
    base = re.sub(r"_(SUMMER|AUTUMN|WINTER)$", "", base, flags=re.I)
    # MAP_DUNG_B15 -> SI_DUNG_B15.bin ; MAP_CITY_01 -> SI_CITY_01.bin
    m = re.match(r"^MAP_(.+)$", base, re.I)
    if not m:
        return None
    return find_extracted(f"SI_{m.group(1)}.bin")


_ITEM_NAME_CACHE = None


def load_item_name_cache():
    """Lazy-load the rf3TxtItem English name table for SI tooltip labels."""
    global _ITEM_NAME_CACHE
    if _ITEM_NAME_CACHE is not None:
        return _ITEM_NAME_CACHE
    hit = find_extracted("rf3TxtItem_split2_1.eng")
    if hit is None:
        _ITEM_NAME_CACHE = {}
        return _ITEM_NAME_CACHE
    try:
        arc = textdb.TextArchive.load(hit)
        _ITEM_NAME_CACHE = {i: e.decode("utf-8", "replace")
                            for i, e in enumerate(arc.entries) if e}
    except Exception:
        _ITEM_NAME_CACHE = {}
    return _ITEM_NAME_CACHE


_RF3MC_CACHE = {"c": False}      # False = not tried yet; None = tried & missing
_CHAR_NAMES = None


def _rf3mc_container():
    """Lazy-load + cache the rf3.mc MYCF event-script container (prefers a bundlePatch
    copy, since patches override bundleMain). Returns a script.Container or None."""
    if _RF3MC_CACHE["c"] is not False:
        return _RF3MC_CACHE["c"]
    cont = None
    try:
        hits = find_extracted_all("rf3.mc")
        patch = [h for h in hits if "patch" in str(h).lower()]
        path = (patch or hits)[0] if hits else None
        if path is not None:
            cont = script.Container(path.read_bytes())
    except Exception:
        cont = None
    _RF3MC_CACHE["c"] = cont
    return cont


def _char_name(cid):
    """Resolve a character id -> display name from rf4_refdata/char_names.json (cached)."""
    global _CHAR_NAMES
    if _CHAR_NAMES is None:
        import json
        _CHAR_NAMES = {}
        try:
            p = _refdata_path("char_names.json")
            _CHAR_NAMES = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _CHAR_NAMES = {}
    return _CHAR_NAMES.get(str(cid))


# --------------------------------------------------------------------------- #
# Embeddable editor panel
# --------------------------------------------------------------------------- #
class MapEditorPanel:
    """A self-contained map render+edit widget built into `parent`. Operates on an
    rf4m.Rf4mMap; call set_map() to (re)load. on_change(bytes) fires after every edit."""

    def __init__(self, parent, mapobj=None, name="", status_fn=None, on_change=None,
                 tex_reader=None, on_navigate=None, on_open_scene=None):
        self.parent = parent
        self.status_fn = status_fn or (lambda s: None)
        self.on_change = on_change
        self.tex_reader = tex_reader      # read(filename)->bytes|None for ground tiles
        self.on_navigate = on_navigate    # on_navigate(map_name) -> host loads that .rf4m (Ctrl+click a warp)
        self.on_open_scene = on_open_scene  # on_open_scene(bank_index, entry_pc, pc) -> open cutscene editor
        self.itemname = _load_item_names()
        self.rooms = _load_rooms()
        self.map = None
        self.map_name = ""
        self.map_base = ""
        self.cellpx = 6
        self.grid = None
        self.objs = []
        self._bg_img = None
        # Ground textures are BC7 and slow to decode (~0.3-0.4 s/map), so we (a) keep an
        # LRU of decoded grounds for instant re-visits and (b) decode off the UI thread
        # (one worker) so a map's ATTR/objects appear immediately while the texture fills
        # in. Keyed by (map_base, tex_layer selection).
        self._ground_cache = OrderedDict()
        # Smaller now that the decoded TILES are cached in mapground — re-stitching an
        # evicted ground from cached tiles is cheap (~0.1 s, no BC7 decode).
        self._GROUND_CACHE_MAX = 8
        self._ground_gen = 0
        self._ground_q = queue.Queue()        # worker -> main: (key, img, gen)
        self._ground_req = queue.Queue()      # main -> worker: (map_base, sel, w, h, gen)
        self._ground_worker = None
        self._ground_polling = False
        self._ground_pending = 0
        self._om_dirty = False
        self._om_cache = OrderedDict()        # over-model set name -> (n_cards, [decoded cards])
        # MOBJ sprite overlay: decoded RGBA billboard per type_id (None = no sprite / undecodable),
        # then a scaled PhotoImage per (type_id, size). Objects are 2D sprites in-game, so this shows
        # each placed object's real appearance instead of a coloured dot.
        self._sprite_pil = {}                 # type_id -> PIL RGBA | None (decoded once)
        self._sprite_photo = OrderedDict()    # (type_id, size) -> ImageTk.PhotoImage (scaled per zoom)
        self._ent_items = {}
        self._si_spots = []
        self._si_items = {}
        self._si_file = None        # editable SearchItemFile for this map (or None)
        self._si_path = None        # its on-disk SI_*.bin path (for save)
        self._spawns = []           # EventSpawnNpc placements from this map's event bank
        self._spawns_loaded = False  # lazy: only parse rf3.mc when the layer is first shown
        self._spawn_bare = ""       # this map's bare filename (for the lazy spawn load)
        self._spawn_bank_index = None  # this map's event bank index (n_primary + mapId)
        self._spawn_items = {}      # canvas-item id -> spawn dict (click -> its script line)
        self._gen = None            # editable GenTable (this map's Gen*.bin encounters, or None)
        self._gen_path = None       # its on-disk Gen*.bin path
        self._gen_gate = None       # selected (pattern_i, entry_i) gate
        self._gen_spawn = None       # selected spawn index within the gate
        self._actor_name_fn = None  # lazy monster/gate id -> name resolver
        self._gate_markers = []     # draggable gate markers [{off, tx, ty}] (off = Gen byte offset)
        self._gen_mon_pts = []      # monster-spawn marker tiles (static overlay)
        self._gate_items = {}       # canvas item id -> gate marker (hit-testing)
        self._gate_drag = None      # gate marker being dragged
        self._gate_moved = False
        self._gate_sel = None       # selected gate marker (for the selection ring)
        self._si_sel = None         # selected spot index
        self._si_drag = None        # spot index being dragged on the canvas
        self._value_colors = {}
        self._undo = []
        self._redo = []
        self._drag_idx = None
        self._drag_moved = False
        self._edit_idx = None
        # Unified selection: exactly one of MOBJ / SI spot / warp is selected at a
        # time. `_sel_kind` in {None,'mobj','si','warp'} is the active kind; the
        # per-kind index lives in `_edit_idx` / `_si_sel` / `_sel_warp`.
        self._sel_kind = None
        self._sel_warp = None
        self._warp_drag = None       # (warp_idx, mode, anchor, orig_tiles) while dragging
        self._warp_started = False
        self._warp_handles = {}      # mode -> (px,py) of the selected warp's grab handles
        self._build()
        if mapobj is not None:
            self.set_map(mapobj, name)

    # ---- widgets --------------------------------------------------------- #
    def _build(self):
        from guiutil import Paned
        # No live relayout while a sash is dragged (the settings column is ~150 native
        # widgets; repainting them per pixel froze the window), and the settings column
        # keeps its width when the window changes size -- the map canvas takes the slack.
        paned = Paned(self.parent, orient="horizontal")
        paned.pack(fill="both", expand=True)

        mid = ttk.Frame(paned); paned.add(mid, weight=4, minsize=200)
        hbar = ttk.Scrollbar(mid, orient="horizontal")
        vbar = ttk.Scrollbar(mid, orient="vertical")
        self.canvas = tk.Canvas(mid, bg="#101014", xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        hbar.config(command=self.canvas.xview); vbar.config(command=self.canvas.yview)
        hbar.pack(side="bottom", fill="x"); vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<Control-Button-1>", self._on_ctrl_press)   # Ctrl+click warp -> go to dest map
        self.canvas.bind("<Double-Button-1>", self._on_double_click)  # double-click warp -> go to dest map
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-(e.delta // 120), "units"))
        self.canvas.bind("<Motion>", self._on_hover)
        self.canvas.bind("<Leave>", lambda _e: self._hide_tip())
        # Delete / Backspace removes the selected entity (canvas takes focus on click).
        self.canvas.bind("<Delete>", lambda _e: self._delete_selected())
        self.canvas.bind("<BackSpace>", lambda _e: self._delete_selected())
        self.canvas.bind("<Control-z>", lambda _e: self._undo_op())
        self.canvas.bind("<Control-y>", lambda _e: self._redo_op())
        self.canvas.bind("<Control-Shift-Z>", lambda _e: self._redo_op())
        self._tip = None  # hover tooltip (created lazily)

        right = ttk.Frame(paned); paned.add(right, weight=0, minsize=280)
        # Row 1: file/edit actions.  Row 2: zoom.  (Kept on separate lines so the
        # zoom buttons don't crowd PNG/Save/Validate/Undo/Redo.)
        act = ttk.Frame(right); act.pack(fill="x", padx=4, pady=(2, 0))
        ttk.Button(act, text="PNG…", command=self._export_png).pack(side="left", padx=2)
        ttk.Button(act, text="Save…", command=self._save_map).pack(side="left", padx=2)
        ttk.Button(act, text="Validate", command=self._validate_map).pack(side="left", padx=2)
        ttk.Button(act, text="Undo", command=self._undo_op).pack(side="left", padx=2)
        ttk.Button(act, text="Redo", command=self._redo_op).pack(side="left", padx=2)
        ctl = ttk.Frame(right); ctl.pack(fill="x", padx=4, pady=2)
        ttk.Label(ctl, text="Zoom:").pack(side="left")
        for px in (3, 4, 6, 8, 12):
            ttk.Button(ctl, text=f"{px}", width=2, command=lambda p=px: self._set_zoom(p)).pack(side="left")

        nb = ttk.Notebook(right); nb.pack(fill="both", expand=True)
        self._nb = nb
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._build_tab_edit(nb)
        self._build_tab_info(nb)
        self._build_tab_props(nb)
        self._build_tab_entities(nb)
        self._build_tab_warps(nb)
        self._build_tab_si(nb)
        self._build_tab_gates(nb)
        self._build_tab_overmodel(nb)
        self._build_tab_chunks(nb)

    # ---- unified selection (one of MOBJ / SI / warp at a time) ----------- #
    def _select(self, kind, idx=None):
        """Make `kind` the sole selection (clearing the other kinds' state +
        listbox highlights). `kind` is None to clear everything, or one of
        'mobj' / 'si' / 'warp'. Does not redraw; callers refresh as needed."""
        self._sel_kind = kind
        if kind != "mobj":
            self._edit_idx = None
            if hasattr(self, "ent_list"):
                self.ent_list.selection_clear(0, "end")
            if hasattr(self, "detail"):
                self.detail.delete("1.0", "end")
            for v in getattr(self, "ent_fields", []):
                v.set("")
            if hasattr(self, "ent_type_pick"):
                self.ent_type_pick.set("")
        if kind != "si":
            self._si_sel = None
            if hasattr(self, "si_list"):
                self.si_list.selection_clear(0, "end")
        if kind != "warp":
            self._sel_warp = None
            if hasattr(self, "warp_list"):
                self.warp_list.selection_clear(0, "end")
        if kind != "gate":
            self._gate_sel = None

    def _show_tab(self, title):
        """Bring the notebook tab with the given label to the front."""
        nb = getattr(self, "_nb", None)
        if nb is None:
            return
        for i in range(nb.index("end")):
            if nb.tab(i, "text") == title:
                nb.select(i)
                return

    def set_status(self, s):
        self.status_fn(s)

    def suspend(self):
        """The host is hiding this panel (rf4mod_gui keeps ONE panel and reuses it for every
        map): drop any queued/in-flight ground decode so it stops competing with the UI.
        set_map() / _request_ground() resume normally."""
        self._ground_gen += 1

    # ---- unsaved-changes tracking ---------------------------------------- #
    def dirty_parts(self):
        """Which of the three files this panel edits differ from their last load/save:
        a subset of ['map', 'search items', 'encounters']. Byte comparison, so an edit
        that was undone (or re-typed back) does not count."""
        out = []
        if self.map is not None and self.map.build() != getattr(self, "_saved_map", None):
            out.append("map")
        if self._si_file is not None and self._si_file.build() != getattr(self, "_si_saved", None):
            out.append("search items")
        if self._gen is not None and self._gen.build() != getattr(self, "_gen_saved", None):
            out.append("encounters")
        return out

    def is_dirty(self):
        return bool(self.dirty_parts())

    def confirm_discard(self, action="continue"):
        """Ask before throwing edits away (switching map, closing, navigating a warp).
        Returns True when it is OK to proceed. Yes = save first (each file through its own
        Save dialog), No = discard, Cancel = stay. Hosts that manage saving themselves
        (rf4mod_gui keeps the map in its working copy) can pass the map bytes through
        on_change and still call this for the SI / Gen sidecar files."""
        parts = self.dirty_parts()
        if not parts:
            return True
        ans = messagebox.askyesnocancel(
            "Unsaved changes",
            f"Unsaved changes to this map's {', '.join(parts)}.\n\n"
            f"Save before you {action}?\n(Yes = save, No = discard, Cancel = stay here)")
        if ans is None:
            return False
        if ans:
            if "map" in parts and not self._save_map():
                return False
            if "search items" in parts and not self._si_save():
                return False
            if "encounters" in parts and not self._gen_save():
                return False
        return True

    # ---- tab builders ---------------------------------------------------- #
    def _build_tab_edit(self, nb):
        # The Edit tab holds more controls than fit in a short window, so wrap the
        # whole thing in a vertically-scrollable canvas. Without this the bottom
        # controls (the entity fields + Delete button) get clipped off-screen.
        outer = ttk.Frame(nb); nb.add(outer, text="Edit")
        ecanvas = tk.Canvas(outer, highlightthickness=0, width=300)
        evsb = ttk.Scrollbar(outer, orient="vertical", command=ecanvas.yview)
        ecanvas.configure(yscrollcommand=evsb.set)
        evsb.pack(side="right", fill="y")
        ecanvas.pack(side="left", fill="both", expand=True)
        f = ttk.Frame(ecanvas)
        ewin = ecanvas.create_window((0, 0), window=f, anchor="nw")
        f.bind("<Configure>", lambda e: ecanvas.configure(scrollregion=ecanvas.bbox("all")))
        _ew = {"w": None}

        def _sync_edit_width(e):
            if e.width != _ew["w"]:
                _ew["w"] = e.width
                ecanvas.itemconfigure(ewin, width=e.width)
        ecanvas.bind("<Configure>", _sync_edit_width)
        # Mouse-wheel scrolling, scoped to while the cursor is over this tab. Coalesced:
        # every scroll step moves the column's ~140 native child windows (~150-200 ms to
        # repaint on Windows), so notches arriving in a burst are summed and applied as ONE
        # scroll instead of queueing a repaint each; 2 units per notch so the bottom of the
        # column is a couple of notches away.
        _wheel = {"n": 0, "pending": False}

        def _flush_wheel():
            n, _wheel["n"], _wheel["pending"] = _wheel["n"], 0, False
            if n:
                ecanvas.yview_scroll(n, "units")

        def _ewheel(e):
            _wheel["n"] += -2 * (e.delta // 120)
            if not _wheel["pending"]:
                _wheel["pending"] = True
                ecanvas.after(15, _flush_wheel)
        ecanvas.bind("<Enter>", lambda e: ecanvas.bind_all("<MouseWheel>", _ewheel))
        ecanvas.bind("<Leave>", lambda e: ecanvas.unbind_all("<MouseWheel>"))

        tools = ttk.LabelFrame(f, text="Tool"); tools.pack(fill="x", padx=4, pady=4)
        self.tool = tk.StringVar(value="select")
        for key, label in (("select", "Select & move (click to select, drag to move)"),
                           ("add", "Add entity (click empty tile)"),
                           ("paint", "Paint ATTR cell")):
            ttk.Radiobutton(tools, text=label, value=key, variable=self.tool).pack(anchor="w", padx=6)
        ar = ttk.Frame(tools); ar.pack(fill="x", padx=6, pady=1)
        ttk.Label(ar, text="Add type_id:").pack(side="left")
        self.add_type = tk.StringVar(value="28")
        ttk.Entry(ar, textvariable=self.add_type, width=6).pack(side="left", padx=2)
        # Name-aware picker: choosing a "<id>  <name>" entry fills add_type. The list is
        # the full map_obj table (type_id -> rom:/map_obj/<name>.bntx). Entries carry the
        # human note when one is known (e.g. "68  fe123 — chimney smoke"). The id stays
        # first so split()[0] still recovers it.
        # Forage lane 0..8 first (daily gatherable/mining spawn POINTS — no map_obj
        # sprite, identity from the params registry), then the sprite band.
        self._mobj_choices = [self._fmt_choice(tid, mobj_params.FORAGE[tid]["name"])
                              for tid in sorted(mobj_params.FORAGE)]
        # then the load-time map parameter records 9..19 (tint colour, UV scroll, ...)
        self._mobj_choices += [self._fmt_choice(tid, mobj_params.MAP_PARAMS[tid]["name"])
                               for tid in sorted(mobj_params.MAP_PARAMS)]
        self._mobj_choices += [self._fmt_choice(tid, nm)
                               for tid, nm in sorted(mobj_types.MOBJ_NAMES.items())]
        self.add_type_pick = tk.StringVar(value="")
        cb = ttk.Combobox(ar, textvariable=self.add_type_pick, values=self._mobj_choices,
                          width=34, height=24, state="readonly")
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>",
                lambda _e: self.add_type.set(self.add_type_pick.get().split()[0]))
        self.add_type_name = ttk.Label(ar, text="", foreground="#3a7", font=("Segoe UI", 8))
        self.add_type_name.pack(side="left", padx=4)

        def _sync_add_name(*_a):
            try:
                tid = int(self.add_type.get().strip(), 0)
            except ValueError:
                self.add_type_name.config(text=""); return
            self.add_type_name.config(text=mobj_types.mobj_label(tid))
        self.add_type.trace_add("write", _sync_add_name)
        _sync_add_name()

        # ---- Paint ATTR: toggle named flags instead of a huge value dropdown ----
        # ATTR cells are a bitfield, so the natural UI is per-bit checkboxes. The raw
        # hex value stays editable (and preserves any render-only bits not shown as a
        # toggle). Presets cover the common whole-cell values.
        pf = ttk.LabelFrame(f, text="Paint ATTR (used by the Paint tool)")
        pf.pack(fill="x", padx=4, pady=4)
        self.paint_val = tk.StringVar(value="0x1")
        vrow = ttk.Frame(pf); vrow.pack(fill="x", padx=4, pady=2)
        ttk.Label(vrow, text="value:").pack(side="left")
        pe = ttk.Entry(vrow, textvariable=self.paint_val, width=10)
        pe.pack(side="left", padx=2)
        pe.bind("<Return>", lambda _e: self._paint_sync_from_entry())
        pe.bind("<FocusOut>", lambda _e: self._paint_sync_from_entry())
        self.paint_decode = ttk.Label(vrow, text="", foreground="#3a7", font=("Segoe UI", 8))
        self.paint_decode.pack(side="left", padx=6)

        # Independent bits get a checkbox each. The seven surface bits do NOT: the
        # loader merges them as one mutually-exclusive field (see SURFACE_FIELD), so
        # they get a single dropdown and it is impossible to pick two.
        self.paint_bit_vars = {}   # mask -> BooleanVar
        fg = ttk.Frame(pf); fg.pack(fill="x", padx=4)
        for i, (nm, mask) in enumerate(PAINT_FLAGS):
            bv = tk.BooleanVar(); self.paint_bit_vars[mask] = bv
            cb = ttk.Checkbutton(fg, text=nm, variable=bv,
                                 command=self._paint_sync_from_bits)
            cb.grid(row=i // 3, column=i % 3, sticky="w", padx=3, pady=0)
            self._bind_attr_help(cb, mask)

        srow = ttk.Frame(pf); srow.pack(fill="x", padx=4, pady=(3, 0))
        slab = ttk.Label(srow, text="surface:")
        slab.pack(side="left")
        self.paint_surface = tk.StringVar(value=SURFACE_CHOICES[0][0])
        self.surface_combo = ttk.Combobox(
            srow, textvariable=self.paint_surface, width=17, state="readonly",
            values=[c[0] for c in SURFACE_CHOICES])
        self.surface_combo.pack(side="left", padx=3)
        self.surface_combo.bind("<<ComboboxSelected>>",
                                lambda _e: self._paint_sync_from_bits())
        ttk.Label(srow, text="(one only — the loader merges these as one field)",
                  font=("Segoe UI", 7), foreground="#888").pack(side="left", padx=4)
        self._bind_attr_help(self.surface_combo, None)
        self._bind_attr_help(slab, None)

        ttk.Label(pf, text="hold Ctrl and hover a box for what it does",
                  font=("Segoe UI", 7), foreground="#888").pack(anchor="w", padx=6)
        prow = ttk.Frame(pf); prow.pack(fill="x", padx=4, pady=(2, 3))
        ttk.Label(prow, text="presets:", font=("Segoe UI", 8)).pack(side="left")
        for label, val in (("open", 0), ("path", 0x1), ("block", 0x2),
                           ("water", 0x8), ("path+grass", 0x2001)):
            ttk.Button(prow, text=label, width=9,
                       command=lambda v=val: self._paint_set(v)).pack(side="left", padx=1)
        self._paint_sync_from_entry()  # init decode + checkboxes from default

        lay = ttk.LabelFrame(f, text="Layers"); lay.pack(fill="x", padx=4, pady=4)
        self.layer_vars = {}
        row = ttk.Frame(lay); row.pack(fill="x")
        for n, (key, label) in enumerate((("attr", "ATTR"), ("grid", "grid"),
                           ("trigger", "trig"), ("actor", "actor"),
                           ("object", "obj"), ("decoration", "deco"),
                           ("mapj", "warp"), ("si", "search"), ("dest", "dests"),
                           ("gates", "gates"))):
            v = tk.BooleanVar(value=(key != "grid")); self.layer_vars[key] = v
            ttk.Checkbutton(row, text=label, variable=v,
                            command=self._redraw).grid(row=n // 4, column=n % 4, sticky="w", padx=3)
        trow = ttk.Frame(lay); trow.pack(fill="x", pady=(3, 0))
        # Ground texture (in-game look) is governed entirely by this dropdown:
        # "off" hides it, "all" composites every draw layer, or pick one layer.
        ttk.Label(trow, text="ground texture:").pack(side="left", padx=(3, 2))
        self.tex_layer = tk.StringVar(value="all")
        self.layer_combo = ttk.Combobox(trow, textvariable=self.tex_layer, width=12,
                                        state="readonly", values=["off", "all"])
        self.layer_combo.pack(side="left", padx=2)
        self.layer_combo.bind("<<ComboboxSelected>>",
                              lambda e: (self._redraw(), self._request_ground()))

        # Ground-texture replacement. Export stitches the selected layer to one PNG;
        # import splits an edited PNG back onto the same grid, keeping every tile's
        # own size and format. See docs/47-map-ground-textures.md for the rules.
        grow = ttk.Frame(lay); grow.pack(fill="x", pady=(3, 0))
        ttk.Button(grow, text="Export PNG", width=11,
                   command=self._ground_export).pack(side="left", padx=(3, 2))
        ttk.Button(grow, text="Import PNG", width=11,
                   command=self._ground_import).pack(side="left", padx=2)
        # Export/import act on THIS layer, not on whatever the display dropdown shows.
        # Keeping them separate means "all"/"off" on the display never silently decides
        # which layer gets written.
        ttk.Label(grow, text="layer:").pack(side="left", padx=(6, 2))
        self.ground_layer = tk.StringVar(value="0 ground")
        self.ground_layer_combo = ttk.Combobox(
            grow, textvariable=self.ground_layer, width=10, state="readonly",
            values=["0 ground"])
        self.ground_layer_combo.pack(side="left")
        grow2 = ttk.Frame(lay); grow2.pack(fill="x", pady=(2, 0))
        ttk.Label(grow2, text="format:").pack(side="left", padx=(3, 2))
        self.ground_fmt = tk.StringVar(value="keep")
        ttk.Combobox(grow2, textvariable=self.ground_fmt, width=8, state="readonly",
                     values=list(texture.ENCODE_FORMATS)).pack(side="left")
        self.ground_status = ttk.Label(lay, text="", font=("Segoe UI", 8),
                                       foreground="#3a7", wraplength=340, justify="left")
        self.ground_status.pack(anchor="w", padx=6)

        # ATTR-over-texture controls: opacity (when texture is on, the fixed 43%
        # alpha used to wash out the overlay) + edges toggle (bold contours where
        # ATTR value changes between neighboring cells — crisp visibility without
        # obscuring texture).
        arow = ttk.Frame(lay); arow.pack(fill="x", pady=(3, 0))
        ttk.Label(arow, text="ATTR opacity:").pack(side="left", padx=(3, 4))
        self.attr_alpha = tk.IntVar(value=180)
        ttk.Scale(arow, from_=0, to=255, orient="horizontal", length=140,
                  variable=self.attr_alpha,
                  command=lambda _v: self._redraw()).pack(side="left")
        self.layer_vars["edges"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(arow, text="cell edges", variable=self.layer_vars["edges"],
                        command=self._redraw).pack(side="left", padx=(8, 3))
        # Draw each placed object as its real 2D sprite (billboard) instead of a coloured dot.
        # Off by default (decodes textures on first use); triggers/effects with no sprite keep the dot.
        self.layer_vars["sprites"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(arow, text="object sprites", variable=self.layer_vars["sprites"],
                        command=self._redraw).pack(side="left", padx=(8, 3))
        # These two overlay toggles get their OWN row: the ATTR row above (opacity slider +
        # 'cell edges' + 'object sprites') overflows a narrow panel and clips trailing items.
        orow = ttk.Frame(lay); orow.pack(fill="x", pady=(3, 0))
        ttk.Label(orow, text="overlays:").pack(side="left", padx=(3, 4))
        # Label every interactive object's kind (door/trigger/fish/gather/actor/…) on the map.
        self.layer_vars["triglabels"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(orow, text="trigger labels", variable=self.layer_vars["triglabels"],
                        command=self._redraw).pack(side="left", padx=(3, 3))
        # Mark actors the EVENT SCRIPT spawns (EventSpawnNpc) — NPCs + interactibles like char
        # 269 "Search"; not in the .rf4m, loaded lazily from rf3.mc on first toggle.
        self.layer_vars["spawns"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(orow, text="NPC spawns", variable=self.layer_vars["spawns"],
                        command=self._redraw).pack(side="left", padx=(8, 3))
        ttk.Label(lay, text="Tip: hold Ctrl and hover a tile to inspect its ATTR value",
                  font=("Segoe UI", 7), foreground="#888").pack(anchor="w", padx=6, pady=(2, 1))

        det = ttk.LabelFrame(f, text="Selected entity (click one on the map)")
        det.pack(fill="x", padx=4, pady=4)
        # Friendly type picker: change the selected entity's type by NAME (sets f0).
        trow = ttk.Frame(det); trow.pack(fill="x", padx=4, pady=(3, 0))
        ttk.Label(trow, text="Type:").pack(side="left")
        self.ent_type_pick = tk.StringVar(value="")
        self.ent_type_combo = ttk.Combobox(trow, textvariable=self.ent_type_pick,
                                            values=self._mobj_choices, width=30, height=24,
                                            state="readonly")
        # width=30 is only the MINIMUM: fill+expand stretches the box to the
        # panel's full row so long identified names aren't clipped mid-word.
        self.ent_type_combo.pack(side="left", padx=3, fill="x", expand=True)
        self.ent_type_combo.bind("<<ComboboxSelected>>", self._on_ent_type_pick)
        # The complete type label (mobj_label: name + kind + identification note),
        # wrapped over as many lines as it needs — the combobox can't show it all.
        # wraplength tracks the live width so it re-wraps when the panel resizes.
        self.ent_type_full = ttk.Label(det, text="", font=("Segoe UI", 8),
                                       foreground="#3a7", justify="left",
                                       wraplength=420)
        self.ent_type_full.pack(fill="x", padx=6, pady=(1, 2))
        def _rewrap(e):
            wl = max(200, e.width - 8)
            if abs(wl - int(self.ent_type_full.cget("wraplength") or 0)) >= 12:
                self.ent_type_full.config(wraplength=wl)
        self.ent_type_full.bind("<Configure>", _rewrap)

        grid = ttk.Frame(det); grid.pack(fill="x", padx=4, pady=2)
        self.ent_fields = []
        labels16 = ["f0 type", "f1", "f2", "f3", "f4", "f5", "f6 scale", "f7 rot",
                    "f8", "f9", "f10", "f11", "f12", "f13", "f14 x", "f15 y"]
        for i, lab in enumerate(labels16):
            cell = ttk.Frame(grid); cell.grid(row=i // 4, column=i % 4, padx=1, pady=1)
            ttk.Label(cell, text=lab, font=("Segoe UI", 7)).pack()
            v = tk.StringVar(); self.ent_fields.append(v)
            en = ttk.Entry(cell, textvariable=v, width=8)
            en.pack()
            # Apply on change: commit when a field loses focus or Enter is pressed.
            # (Programmatic .set() during _show_entity doesn't move focus, so this
            # never fires spuriously while loading a record.)
            en.bind("<FocusOut>", lambda _e: self._apply_entity(silent=True))
            en.bind("<Return>", lambda _e: self._apply_entity(silent=True))
        btnrow = ttk.Frame(det); btnrow.pack(fill="x", pady=2)
        ttk.Button(btnrow, text="Delete selected entity",
                   command=self._delete_selected_entity).pack(side="left", padx=2)
        ttk.Label(btnrow, text="(edits apply automatically)",
                  font=("Segoe UI", 7), foreground="#888").pack(side="left", padx=4)
        self.detail = tk.Text(det, height=3, width=38, font=("Consolas", 8), wrap="word")
        self.detail.pack(fill="x", padx=2, pady=2)
        # per-type parameter legend (the green text that used to live in the MOBJ tab):
        # what each field means for the selected entity's type_id, with IDA-verified sizes.
        self.param_legend = tk.Text(det, height=9, width=38, font=("Consolas", 8),
                                    wrap="word", foreground="#0a6")
        self.param_legend.pack(fill="x", padx=2, pady=(0, 2))
        self.param_legend.configure(state="disabled")
        ttk.Button(det, text="Flag reference… (find a flag's id)",
                   command=self._open_flag_reference).pack(anchor="w", padx=4, pady=(0, 3))

    def _build_tab_info(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Info")
        self.info = tk.Text(f, height=18, width=38, font=("Consolas", 9), wrap="word")
        self.info.pack(fill="both", expand=True, padx=2, pady=2)
        self.info.configure(state="disabled")

    def _build_tab_overmodel(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Over-model")
        self.om_label = ttk.Label(f, text="", font=("Segoe UI", 8), foreground="#aab",
                                  wraplength=270, justify="left")
        self.om_label.pack(fill="x", padx=4, pady=(4, 2))
        cw = ttk.Frame(f); cw.pack(fill="both", expand=True, padx=4, pady=2)
        vb = ttk.Scrollbar(cw, orient="vertical")
        self.om_canvas = tk.Canvas(cw, bg="#202024", highlightthickness=0, yscrollcommand=vb.set)
        vb.config(command=self.om_canvas.yview)
        vb.pack(side="right", fill="y")
        self.om_canvas.pack(side="left", fill="both", expand=True)
        self.om_canvas.bind("<MouseWheel>",
                            lambda e: self.om_canvas.yview_scroll(-(e.delta // 120), "units"))
        ttk.Label(f, justify="left", foreground="#888", font=("Segoe UI", 7),
                  text="The map's over-model (g_mapResourceTable[+3]): pre-rendered 3D scenery\n"
                       "billboards (stairs / fences / trees / structures) drawn over the ground.\n"
                       "A multi-card BC3 BNTX, often shared and sometimes an empty placeholder.\n"
                       "NOT aligned to the ATTR grid — a texture preview, not an in-place overlay.").pack(
            fill="x", padx=4, pady=(0, 4))
        self._om_photo = None

    def _om_montage(self, cards, box_w=248, box_h=200, gap=6):
        """Stack decoded over-model cards vertically (each fit to box_w×box_h) on a
        dark background for the scrollable preview."""
        scaled = []
        for im in cards:
            s = min(box_w / im.width, box_h / im.height)
            nw, nh = max(1, int(im.width * s)), max(1, int(im.height * s))
            scaled.append(im.resize((nw, nh), Image.NEAREST if s > 1 else Image.BILINEAR))
        w = max((i.width for i in scaled), default=box_w)
        h = sum(i.height for i in scaled) + gap * (len(scaled) + 1)
        mont = Image.new("RGBA", (w, h), (34, 34, 40, 255))
        y = gap
        for im in scaled:
            mont.alpha_composite(im, ((w - im.width) // 2, y))
            y += im.height + gap
        return mont

    def _refresh_overmodel(self):
        if not hasattr(self, "om_canvas"):
            return
        c = self.om_canvas
        c.delete("all")
        self._om_photo = None
        c.configure(scrollregion=(0, 0, 0, 0))
        setname = mapground.overmodel_for(self.map_base) if self.map_base else None
        if not setname:
            self.om_label.config(text="Over-model: none — this map has no +3 over-model.")
            return
        shared = "  (shared)" if setname != self.map_base else ""
        if not (HAS_PIL and self.tex_reader):
            self.om_label.config(text=f"Over-model: {setname}.model{shared}  (Pillow needed to preview)")
            return
        data = self.tex_reader(setname + ".model")
        if data is None:
            self.om_label.config(text=f"Over-model: {setname}.model{shared}  (not found in source)")
            return
        cached = self._om_cache.get(setname)
        if cached is not None:
            self._om_cache.move_to_end(setname)
            n, cards = cached
        else:
            try:
                n = len(texture.bntx_textures(data))
                cards = []
                for i in range(n):
                    im = texture.decode_bntx(data, i)
                    if im is not None and im.split()[3].getextrema() != (0, 0):
                        cards.append(im)
            except Exception as e:
                self.om_label.config(text=f"Over-model: {setname}.model{shared}  (decode error: {e})")
                return
            # Cache the decoded cards by set name — over-models are heavily shared
            # (e.g. MAP_FIELD_43's is reused by 164 maps), so re-viewing is instant.
            self._om_cache[setname] = (n, cards)
            self._om_cache.move_to_end(setname)
            while len(self._om_cache) > 16:
                self._om_cache.popitem(last=False)
        if n == 0:
            self.om_label.config(text=f"Over-model: {setname}.model{shared}  (unsupported BNTX)")
            return
        if not cards:
            self.om_label.config(text=f"Over-model: {setname}.model{shared}\n"
                                      f"{n} card(s), all EMPTY (transparent placeholder — no decoration)")
            return
        self.om_label.config(text=f"Over-model: {setname}.model{shared}\n"
                                  f"{len(cards)} of {n} card(s) have content — BC3 scenery billboards")
        mont = self._om_montage(cards)
        self._om_photo = ImageTk.PhotoImage(mont)
        c.create_image(0, 0, image=self._om_photo, anchor="nw")
        c.configure(scrollregion=(0, 0, mont.width, mont.height))

    # ---- ore/mineral configs (MapOre_Rate) for type-0 spawn resolution ---- #
    def _ore_configs(self):
        """Cached MapOre_Rate rows [(kind, deplete, scrap, [(item,weight)x3], rare)].
        Loaded through the bundle reader; [] when unavailable."""
        if getattr(self, "_ore_cfg", None) is not None:
            return self._ore_cfg
        self._ore_cfg = []
        try:
            import struct as _st
            d = self.tex_reader("MapOre_Rate.bin") if self.tex_reader else None
            if d and d[:4] == b"NLCL":
                cnt = _st.unpack_from("<I", d, 24)[0]
                for i in range(min(cnt, 64)):
                    q = 28 + 32 * i
                    kind = _st.unpack_from("<I", d, q)[0]
                    dep = _st.unpack_from("<H", d, q + 4)[0]
                    scr = _st.unpack_from("<H", d, q + 8)[0]
                    iw = [(_st.unpack_from("<H", d, q + 24 + 2 * j)[0],
                           _st.unpack_from("<H", d, q + 12 + 4 * j)[0]) for j in range(3)]
                    rare = _st.unpack_from("<H", d, q + 30)[0]
                    self._ore_cfg.append((kind, dep, scr, iw, rare))
        except Exception:
            self._ore_cfg = []
        return self._ore_cfg

    def _ore_config_text(self, idx):
        """Human line for ore config `idx` (a type-0 record's f10)."""
        cfg = self._ore_configs()
        if not (0 <= idx < len(cfg)):
            return None
        kind, dep, scr, iw, rare = cfg[idx]
        nm = _load_item_names()                      # returns a lookup FUNCTION
        ores = ", ".join(f"{nm(it) or it}({w})" for it, w in iw if it)
        r = (nm(rare) or rare) if rare else None
        s = f"mineral kind {kind} ({mobj_params.gather_kind_sprite(kind)}): {ores or '(empty row)'}"
        if r:
            s += f"  rare={r}"
        return s

    # ---- placed-object (MOBJ) sprite overlay ----------------------------- #
    def _mobj_sprite_name(self, type_id):
        """Resolve a placed-object `type_id` to its extracted sprite texture filename, or None.
        type_id < FIRST_MAP_OBJ_TYPE (20) are invisible triggers/warps/system objects with no
        sprite. For a real map_obj, the in-game path is `rom:/map_obj/<name>.bntx`; the extractor
        writes it as `<name>.texture` or `MOBJ_<name>.texture`, so we try both."""
        if type_id is None or not self.tex_reader:
            return None
        # Forage lane previews: fixed-kind spawns show their gatherable's crop
        # sprite (1 rune flower, 2 rune crystal; 3/4 a family representative).
        # Type 0 (ore) varies per record via f10 — resolved in the legend text.
        if type_id < mobj_types.FIRST_MAP_OBJ_TYPE:
            fixed = {1: "crop_023", 2: "crop_024", 3: "crop_003", 4: "crop_001"}
            base = fixed.get(type_id)
            if base and self.tex_reader(base + ".texture") is not None:
                return base + ".texture"
            return None
        fn = mobj_types.mobj_filename(type_id)
        if not fn:
            return None
        base = fn.split("/")[-1].rsplit(".", 1)[0]
        for cand in (base + ".texture", "MOBJ_" + base + ".texture"):
            if self.tex_reader(cand) is not None:
                return cand
        return None

    def _mobj_sprite_photo(self, type_id, size):
        """A scaled `ImageTk.PhotoImage` for `type_id`'s sprite (longest side ~`size` px), or None
        when the object has no available sprite. Two-level cache: decoded RGBA PIL per type_id
        (with a cached negative), then a scaled PhotoImage per (type_id, size)."""
        if not (HAS_PIL and self.tex_reader):
            return None
        pkey = (type_id, size)
        if pkey in self._sprite_photo:
            self._sprite_photo.move_to_end(pkey)
            return self._sprite_photo[pkey]
        if type_id not in self._sprite_pil:                  # decode once (incl. negative -> None)
            pil = None
            name = self._mobj_sprite_name(type_id)
            if name:
                try:
                    im = texture.decode_to_image(self.tex_reader(name))
                    pil = im.convert("RGBA") if im is not None else None
                except Exception:
                    pil = None
            self._sprite_pil[type_id] = pil
        pil = self._sprite_pil[type_id]
        if pil is None:
            return None
        w, h = pil.size
        sc = size / max(w, h, 1)
        im = pil.resize((max(1, int(w * sc)), max(1, int(h * sc))))
        photo = ImageTk.PhotoImage(im)
        self._sprite_photo[pkey] = photo
        self._sprite_photo.move_to_end(pkey)
        while len(self._sprite_photo) > 256:
            self._sprite_photo.popitem(last=False)
        return photo

    def _build_tab_props(self, nb):
        # Header chunks, labelled by what Map_LoadById / Map_PostLoad actually do with
        # them (verified 2026-09-19): MSEA is stored but never read; MGRP is a bitfield
        # (season override / no-weather / area group) the loader dereferences
        # unconditionally; MLIG holds the day/evening/night tile tints as 0x00BBGGRR
        # with 0 = engine default; MTXN's VALUE is never read -- its chunk COUNT is the
        # number of display layers the loader spawns.
        f = ttk.Frame(nb); nb.add(f, text="Props")
        self.prop_vars = {}
        rows = [("Season tag (MSEA)", "msea",
                 "0 spring/none · 1 summer · 2 autumn · 3 winter · 4 house/barn/system rooms. "
                 "Nothing in the game reads it."),
                ("Group bits (MGRP)", "mgrp",
                 "hex. bits 0-3 fix the ambience season (spring..winter), bit 4 = no weather, "
                 "one of bits 5-25 = area group (BGM track, minimap). Required."),
                ("Day tint (MLIG 0)", "mlig0", "R,G,B — blank = engine default 255,255,255"),
                ("Evening tint (MLIG 1)", "mlig1", "blank = default 247,214,197"),
                ("Night tint (MLIG 2)", "mlig2",
                 "blank = default 148,214,247 (181,214,214 on snow maps)"),
                ("MTXN value", "mtxn", "never read by the game")]
        for i, (label, key, hint) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=2)
            v = tk.StringVar(); self.prop_vars[key] = v
            ttk.Entry(f, textvariable=v, width=14).grid(row=i, column=1, padx=4)
            ttk.Label(f, text=hint, font=("Segoe UI", 7), foreground="#888",
                      wraplength=190, justify="left").grid(row=i, column=2, sticky="w", padx=2)
        r = len(rows)
        self.mgrp_decode = ttk.Label(f, text="", font=("Segoe UI", 8), foreground="#3a7",
                                     wraplength=320, justify="left")
        self.mgrp_decode.grid(row=r, column=0, columnspan=3, sticky="w", padx=4)
        self.prop_vars["mgrp"].trace_add("write", lambda *_a: self._sync_mgrp_decode())
        lrow = ttk.Frame(f); lrow.grid(row=r + 1, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 0))
        self.mtxn_layers = ttk.Label(lrow, text="", font=("Segoe UI", 8))
        self.mtxn_layers.pack(side="left")
        ttk.Button(lrow, text="+ layer", width=7, command=lambda: self._mtxn_change(+1)).pack(side="left", padx=2)
        ttk.Button(lrow, text="− layer", width=7, command=lambda: self._mtxn_change(-1)).pack(side="left", padx=2)
        ttk.Label(f, text="Display layers = MTXN chunk count: 1 draws the ground textures only, "
                          "2 adds the overlay set (g_mapResourceTable[+2], only where the map id "
                          "has one). 0 would draw no ground at all.",
                  font=("Segoe UI", 7), foreground="#888", wraplength=330,
                  justify="left").grid(row=r + 2, column=0, columnspan=3, sticky="w", padx=4)
        brow = ttk.Frame(f); brow.grid(row=r + 3, column=0, columnspan=3, pady=6)
        ttk.Button(brow, text="Apply properties", command=self._apply_props).pack(side="left", padx=3)
        ttk.Button(brow, text="Resize grid…", command=self._open_resize_dialog).pack(side="left", padx=3)
        ttk.Label(f, text="Tip: every stock map leaves MLIG at the defaults and sets its lighting "
                          "with three type-12 'tint_color' MOBJ records instead (Entities tab). "
                          "Both end up in the same three tint slots; type-12 records win because "
                          "they are applied after MLIG.",
                  font=("Segoe UI", 7), foreground="#888", wraplength=330,
                  justify="left").grid(row=r + 4, column=0, columnspan=3, sticky="w", padx=4)

    # ---- resize the ATTR grid (with the derived-artefact report) ---------- #
    def _open_resize_dialog(self):
        """Resize the ATTR grid. Preview runs rf4m.Rf4mMap.resize_attr_grid as a dry run and
        lists everything the resize invalidates (ground-atlas re-layout, tiles to author,
        entities / warps falling off the grid, the minimap record, seasonal siblings) BEFORE
        anything changes; Resize applies it as one undoable step."""
        if not (self.map and self.grid):
            messagebox.showinfo("Resize grid", "This map has no ATTR grid."); return
        W, H, _ = self.grid
        win = tk.Toplevel(self.parent); win.title(f"Resize grid — {self.map_base}")
        win.transient(self.parent.winfo_toplevel())
        frm = ttk.Frame(win); frm.pack(fill="x", padx=8, pady=6)
        vars_ = {}
        for col, (key, label, val) in enumerate((("w", "width", W), ("h", "height", H),
                                                 ("ox", "origin x", 0), ("oy", "origin y", 0),
                                                 ("fill", "fill", "0x2"))):
            ttk.Label(frm, text=label).grid(row=0, column=col, padx=3)
            v = tk.StringVar(value=str(val)); vars_[key] = v
            ttk.Entry(frm, textvariable=v, width=8).grid(row=1, column=col, padx=3)
        shift = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="move entities + warps with the terrain", variable=shift).grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))
        ttk.Label(win, text=f"current grid {W}x{H} tiles. origin = where the old (0,0) lands "
                            f"(pads left/top); fill = value of new cells (0x2 = solid wall).",
                  font=("Segoe UI", 8), foreground="#888", wraplength=520, justify="left").pack(
            fill="x", padx=8)
        out = tk.Text(win, height=16, width=86, font=("Consolas", 9), wrap="word")
        out.pack(fill="both", expand=True, padx=8, pady=4)

        def args():
            return (int(vars_["w"].get(), 0), int(vars_["h"].get(), 0),
                    dict(fill=int(vars_["fill"].get(), 0),
                         origin=(int(vars_["ox"].get(), 0), int(vars_["oy"].get(), 0)),
                         shift_entities=shift.get(), ground_reader=self.tex_reader,
                         map_name=self.map_base or None))

        def show(rep_):
            out.delete("1.0", "end")
            a = rep_["atlas"]
            out.insert("end", f"ATTR {rep_['old_size'][0]}x{rep_['old_size'][1]} -> "
                              f"{rep_['new_size'][0]}x{rep_['new_size'][1]}   ground tiles "
                              f"{a['old_grid'][0]}x{a['old_grid'][1]} -> {a['new_grid'][0]}x{a['new_grid'][1]}"
                              + ("   (column count changes)" if a["reindexed"] else "") + "\n\n")
            out.insert("end", "Derived artefacts to fix:\n" if rep_["todo"] else "Nothing derived needs fixing.\n")
            for t in rep_["todo"]:
                out.insert("end", f"  • {t}\n")
            if rep_["findings"]:
                out.insert("end", "\nvalidate() at the new size:\n")
                for f_ in rep_["findings"]:
                    out.insert("end", f"  {f_}\n")

        def preview():
            try:
                w, h, kw = args()
                show(self.map.resize_attr_grid(w, h, dry_run=True, **kw))
            except (ValueError, rf4m.Rf4mError) as e:
                out.delete("1.0", "end"); out.insert("end", f"error: {e}")

        def apply():
            try:
                w, h, kw = args()
                before = self.map.build()
                rep_ = self.map.resize_attr_grid(w, h, **kw)
            except (ValueError, rf4m.Rf4mError) as e:
                messagebox.showerror("Resize grid", str(e), parent=win); return
            if not self._commit(before):
                show(rep_); return
            self.grid = self.map.attr_grid()
            for v in set(self.grid[2]):
                self._value_colors.setdefault(v, ATTR_PALETTE[len(self._value_colors) % len(ATTR_PALETTE)])
            self._invalidate_ground()          # the atlas crop/scale depends on the grid size
            self._select(None)
            self._reload_after_chunk_edit()
            self._refresh_entities()
            self._request_ground()
            show(rep_)
            self.set_status(f"Resized grid to {w}x{h} — {len(rep_['todo'])} derived item(s) listed; "
                            f"Undo reverts it — Save…")

        brow = ttk.Frame(win); brow.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(brow, text="Preview", command=preview).pack(side="left", padx=3)
        ttk.Button(brow, text="Resize", command=apply).pack(side="left", padx=3)
        ttk.Button(brow, text="Close", command=win.destroy).pack(side="right", padx=3)
        preview()
        return win

    def _sync_mgrp_decode(self):
        try:
            v = int(self.prop_vars["mgrp"].get().strip(), 0)
        except ValueError:
            self.mgrp_decode.config(text=""); return
        self.mgrp_decode.config(text=rf4m.mgrp_notes(v))

    def _mtxn_change(self, delta):
        """Add (+1: duplicate the last MTXN chunk right after it) or remove (-1: the last
        MTXN chunk) a display layer."""
        if not self.map:
            return
        idxs = [i for i, c in enumerate(self.map.chunks) if c.tag == b"MTXN"]
        if delta > 0:
            self._snapshot()
            src = self.map.chunks[idxs[-1]].payload if idxs else b"\x00\x00\x00\x00"
            self.map.add_chunk("MTXN", src, at=(idxs[-1] + 1) if idxs else 0)
        elif idxs:
            self._snapshot()
            self.map.delete_chunk(idxs[-1])
        else:
            return
        self._reload_after_chunk_edit()
        self.set_status(f"{len(self.map.find(b'MTXN'))} MTXN chunk(s) / display layer(s) — Save…")

    def _build_tab_warps(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Warps")
        self.warp_list = tk.Listbox(f, height=6, exportselection=False)
        self.warp_list.pack(fill="x", padx=4, pady=2)
        self.warp_list.bind("<<ListboxSelect>>", lambda _e: self._warp_selected())
        ttk.Label(f, text="Tip: Ctrl+click or double-click a warp on the map to jump to its destination map.",
                  font=("Segoe UI", 7), foreground="#888").pack(anchor="w", padx=4)
        form = ttk.Frame(f); form.pack(fill="x", padx=4, pady=2)
        self.warp_vars = {}
        # Field order matches the on-disk MAPJ record (see rf4m.MAPJ_FIELDS): f0 disable
        # flag, f1..f4 zone x/y/w/h in sub-units, f5 dest map, f6/f7 arrival x/y, f8
        # arrival facing in degrees. All nine verified 2026-09-19 against the consumers
        # (Map_SpawnEntityByCategoryAndIdx category 1000, Widget_UpdateBit20FromGameFlag,
        # Cutscene_StartDeathSequence = the shared major-transition entry). Earlier
        # versions called f0 a "-1 sentinel" and f8 "unknown".
        wf = [("zone x", "x"), ("zone y", "y"), ("zone w", "w"), ("zone h", "h")]
        # id-by-id list of every known map ("<id> - <name>") for the dest-map
        # dropdown. Sort numerically so the combobox scrolls through map ids in
        # order; users can also type a bare id and it'll be parsed on Apply.
        self._roomsById = {mid: name for name, (mid, _rid) in self.rooms.items()}
        room_choices = [self._format_map_choice(i) for i in sorted(self._roomsById)]
        # Grid layout: 4-column zone xywh on row 0/1, full-width dest_map combo
        # on row 2/3, then arrival x / arrival y / facing / off-flag on row 4/5.
        for key in ("x", "y", "w", "h", "dm", "dx", "dy", "u8", "flag"):
            self.warp_vars[key] = tk.StringVar()
        for col, (label, key) in enumerate(wf):
            ttk.Label(form, text=label, font=("Segoe UI", 7)).grid(row=0, column=col, padx=1)
            ttk.Entry(form, textvariable=self.warp_vars[key], width=8).grid(row=1, column=col, padx=1)
        ttk.Label(form, text="dest map (pick or type id)",
                  font=("Segoe UI", 7)).grid(row=2, column=0, columnspan=4, sticky="w", padx=1)
        ttk.Combobox(form, textvariable=self.warp_vars["dm"], values=room_choices)\
            .grid(row=3, column=0, columnspan=4, sticky="we", padx=1)
        for col, (label, key) in enumerate((("arrival x", "dx"), ("arrival y", "dy"),
                                            ("facing °", "u8"), ("off-flag", "flag"))):
            ttk.Label(form, text=label, font=("Segoe UI", 7)).grid(row=4, column=col, padx=1)
            ttk.Entry(form, textvariable=self.warp_vars[key], width=8).grid(row=5, column=col, padx=1)
        bb = ttk.Frame(f); bb.pack(fill="x", padx=4, pady=4)
        ttk.Button(bb, text="Apply", command=self._warp_apply).pack(side="left", padx=2)
        ttk.Button(bb, text="Add", command=self._warp_add).pack(side="left", padx=2)
        ttk.Button(bb, text="Delete", command=self._warp_delete).pack(side="left", padx=2)
        ttk.Label(f, text="zone x/y/w/h are sub-units (÷8 = tile); the player triggers the warp "
                          "inside that box. Arrival x/y are sub-units in the destination map, "
                          "facing is the arrival direction in degrees (0 = keep). Off-flag: "
                          "per-map scene-flag id that DISABLES the warp while set (-1 = always "
                          "on; e.g. the castle exits use flag 632).",
                  font=("Segoe UI", 7), foreground="#888", wraplength=300).pack(padx=4)

    def _format_map_choice(self, mid):
        """Combobox label for a map id (e.g. 31 -> '31 - MAP_CITY_01_WINTER',
        or '999 - <unknown>' for an id that's not in rf4s_rooms.csv)."""
        return f"{mid} - {self._roomsById.get(mid, '<unknown>')}"

    @staticmethod
    def _parse_map_choice(text):
        """Extract the leading integer from a combobox choice or bare digits.
        Accepts '31', '31 - MAP_CITY_01_WINTER', and '0x1F'. Returns None on junk."""
        text = (text or "").strip()
        if not text:
            return None
        head = text.split()[0]
        try:
            return int(head, 0)
        except ValueError:
            return None

    def _build_tab_entities(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Entities")
        el = ttk.Frame(f); el.pack(fill="both", expand=True, padx=4, pady=2)
        self.ent_list = tk.Listbox(el, height=12, exportselection=False)
        self.ent_list.pack(side="left", fill="both", expand=True)
        ebar = ttk.Scrollbar(el, command=self.ent_list.yview); ebar.pack(side="right", fill="y")
        self.ent_list.config(yscrollcommand=ebar.set)
        self.ent_list.bind("<<ListboxSelect>>", lambda _e: self._ent_list_select())
        self.ent_list.bind("<Double-Button-1>", lambda _e: self._show_tab("Edit"))
        bb = ttk.Frame(f); bb.pack(fill="x", padx=4, pady=2)
        ttk.Button(bb, text="Add (Edit tab)…", command=lambda: self._show_tab("Edit")).pack(side="left", padx=2)
        ttk.Button(bb, text="Delete", command=self._delete_selected_entity).pack(side="left", padx=2)
        ttk.Label(f, justify="left", foreground="#888", font=("Segoe UI", 7), wraplength=300,
                  text="Every placed MOBJ in the map. Click to select + highlight it on the map; "
                       "the Edit tab edits its 16 fields. Double-click jumps to Edit. Unplaced "
                       "(pos 0,0) entities are flagged.").pack(fill="x", padx=4, pady=(0, 4))

    def _refresh_entities(self):
        if not hasattr(self, "ent_list"):
            return
        keep = self.ent_list.curselection()
        self.ent_list.delete(0, "end")
        for i, o in enumerate(self.objs):
            tid = o["type_id"] & 0xFFFF
            nm = mobj_types.mobj_display_name(tid) or f"type {o['type_id']}"
            if o["category"] == "mapparam":
                loc = "(map-wide)"          # load-time parameter record, no position
            elif o["pos_x"] == 0 and o["pos_y"] == 0:
                loc = "(unplaced)"
            else:
                loc = f"tile ({o['pos_x']>>3},{o['pos_y']>>3})"
            self.ent_list.insert("end", f"#{i}  {nm}  [{o['category']}]  {loc}")
        if self._sel_kind == "mobj" and self._edit_idx is not None and self._edit_idx < self.ent_list.size():
            self.ent_list.selection_set(self._edit_idx)
        elif keep and keep[0] < self.ent_list.size():
            self.ent_list.selection_set(keep[0])

    def _ent_list_select(self):
        s = self.ent_list.curselection()
        if s and s[0] < len(self.objs):
            self._show_entity(s[0])

    def _build_tab_chunks(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Chunks")
        self.chunk_tree = ttk.Treeview(f, columns=("tag", "size"), show="headings", height=8)
        self.chunk_tree.heading("tag", text="tag"); self.chunk_tree.column("tag", width=70)
        self.chunk_tree.heading("size", text="bytes"); self.chunk_tree.column("size", width=80, anchor="e")
        self.chunk_tree.pack(fill="x", padx=4, pady=2)
        self.chunk_tree.bind("<<TreeviewSelect>>", lambda _e: self._chunk_selected())
        self.chunk_hex = tk.Text(f, height=8, width=38, font=("Consolas", 8), wrap="char")
        self.chunk_hex.pack(fill="both", expand=True, padx=4, pady=2)
        bb = ttk.Frame(f); bb.pack(fill="x", padx=4, pady=2)
        ttk.Button(bb, text="Apply hex", command=self._chunk_apply).pack(side="left", padx=2)
        ttk.Button(bb, text="Delete chunk", command=self._chunk_delete).pack(side="left", padx=2)
        addf = ttk.Frame(f); addf.pack(fill="x", padx=4, pady=2)
        ttk.Label(addf, text="New tag:").pack(side="left")
        self.new_chunk_tag = tk.StringVar(value="MOBJ")
        ttk.Entry(addf, textvariable=self.new_chunk_tag, width=6).pack(side="left", padx=2)
        ttk.Button(addf, text="Add empty chunk", command=self._chunk_add).pack(side="left", padx=2)

    # ---- (re)load a map -------------------------------------------------- #
    def set_map(self, mapobj, name):
        self.map = mapobj
        self.map_name = name
        # Bare basename (no directory, no extension), suitable for save/export
        # dialog initialfile. Handles BOTH separators: bundle entries use '/'
        # (e.g. "bundleMain/MAP_CITY_02.rf4m") but a Windows-style "\" can also
        # show up if the caller passes one. (Earlier we tried r"[\\/]" as a regex
        # split — modern Python's regex parser doesn't treat it the obvious way
        # so we just normalise separators by hand.)
        bare = name.replace("\\", "/").rsplit("/", 1)[-1]
        self.map_base = re.sub(r"\.rf4m$", "", bare, flags=re.I)
        self._ground_gen += 1   # cancel any in-flight ground decode for the previous map
        self._refresh_layers()
        # Static "_UV" maps (the procedural/space dungeons — Floating Empire E*,
        # Delirium Lava Ruins H*, Sharance Maze F*, …) now render their backdrop the
        # way the GAME does: g_mapResourceTable[+1] resolves (via the remap-special
        # ids, e.g. E01's 7741 -> 7759 = MAP_DUNG_E02_UV) to a single full-screen
        # sprite that the engine stretches across the map bounds (Map_SpawnEntity sets
        # work[+884]=1 + Sprite_SetQuadVertsAndUVFromExtents builds one 1x1 quad).
        # _bg_composite stretches that _UV sprite to the ATTR extent and draws the ATTR
        # fill semi-transparently on top. We DON'T force the texture off any more —
        # the backdrop is what the map actually looks like. (It is NOT cell-aligned to
        # the ATTR grid by design: the real floor is ATTR + over-model + MOBJ; the _UV
        # is ambiance. Use the layer dropdown's "off" to hide it while editing ATTR.)
        self.grid = mapobj.attr_grid()
        self.objs = mapobj.decode_mobj()
        self._si_spots = self._load_si_spots(bare)
        self._si_items = {}  # canvas-item id -> spot dict (for click tooltips)
        self._spawn_bare = bare        # (lazy) NPC-spawn overlay parses rf3.mc on first toggle
        self._spawns = []
        self._spawns_loaded = False
        self._si_refresh_list()
        self._load_gen(bare)   # load this map's Gen*.bin encounter table into the Gates tab
        self._value_colors = {}
        if self.grid:
            common = [v for v, _ in Counter(self.grid[2]).most_common()]
            floor = common[0] if common else None
            pi = 0
            for v in common:
                if v == 0:
                    self._value_colors[v] = ATTR_VOID
                elif v == floor:
                    self._value_colors[v] = ATTR_FLOOR
                else:
                    self._value_colors[v] = ATTR_PALETTE[pi % len(ATTR_PALETTE)]; pi += 1
            # Default the paint value to this map's most common non-void cell, then
            # reflect it in the flag checkboxes / decode label.
            default = next((v for v in common if v not in (0,)), common[0] if common else 1)
            self.paint_val.set("0x%X" % default)
            if hasattr(self, "paint_bit_vars"):
                self._paint_sync_from_entry()
        self._undo = []
        self._redo = []
        self._saved_map = mapobj.build()      # dirty-tracking baseline (see is_dirty)
        self._edit_idx = None
        self._sel_kind = None
        self._sel_warp = None
        self._warp_drag = None
        for v in getattr(self, "ent_fields", []):
            v.set("")
        if hasattr(self, "detail"):
            self.detail.delete("1.0", "end")
        self._refresh_props()
        self._refresh_entities()
        self._refresh_warps()
        self._refresh_chunks()
        self._om_dirty = True       # over-model decoded lazily, only when its tab is viewed
        self._fill_info()
        self._redraw()
        self._on_tab_changed()      # refresh the over-model now only if its tab is open
        self._request_ground()      # decode ground off-thread; canvas fills in when ready

    def _changed(self):
        self.objs = self.map.decode_mobj()
        self._refresh_entities()
        self._redraw()
        if self.on_change:
            try:
                self.on_change(self.map.build())
            except Exception:
                pass

    # ---- script-spawned NPC / interactible overlay (EventSpawnNpc) ------ #
    def _load_spawns(self, bare):
        """Scan THIS map's event bank (rf3.mc tail bank = n_primary + mapId) for
        EventSpawnNpc calls and fill self._spawns with
        [{char_id, name, instance, x, y, tile_x, tile_y}, ...]. These are actors the
        EVENT SCRIPT places (NPCs + interactibles like char 269 'Search' = search spots) --
        they are NOT in the .rf4m, so the map file never shows them. Coords are
        8-sub-units/tile (>>3), same space as MOBJ positions. Parses only the one bank."""
        self._spawns = []
        self._spawns_loaded = True
        self._spawn_bank_index = None
        stem = re.sub(r"\.rf4m$", "", bare.replace("\\", "/").rsplit("/", 1)[-1], flags=re.I)
        cands = [stem]
        m = re.match(r"^(.*)_(SUMMER|AUTUMN|WINTER|SPRING)$", stem, re.I)
        if m:
            cands.append(m.group(1))            # seasonal variants share one event bank
        mid = next((self.rooms[c][0] for c in cands if c in self.rooms), None)
        if mid is None:
            return
        cont = _rf3mc_container()
        if cont is None:
            return
        bi = cont.n_primary + mid
        if not (0 <= bi < len(cont.banks)):
            return
        self._spawn_bank_index = bi
        bank = cont.banks[bi]
        try:
            scenes = script.disassemble_bank(bank)
        except Exception:
            return
        for sc in scenes:
            for pc, st in sc.stmts.items():
                if st.op >= 0xFFF0 or script.opcode_mnemonic(st.op) != "EventSpawnNpc":
                    continue
                try:
                    v = [int(script.arg_repr(bank.data, a), 0) for a in st.args[:4]]
                except (ValueError, TypeError):
                    continue                    # skip calls whose args are computed exprs
                if len(v) < 4:
                    continue
                cid, inst, x, y = v[0], v[1], v[2], v[3]
                self._spawns.append({"char_id": cid, "instance": inst,
                                     "name": _char_name(cid) or ("char#%d" % cid),
                                     "x": x, "y": y, "tile_x": x >> 3, "tile_y": y >> 3,
                                     "entry_pc": sc.entry_pc, "pc": pc})

    def _open_spawn_scene(self, sp):
        """Click a spawn marker -> open the cutscene editor at the exact EventSpawnNpc line
        (this map's event bank, scene @entry_pc, statement @pc)."""
        if self.on_open_scene is None or self._spawn_bank_index is None:
            self.set_status("spawn %s: no cutscene-editor hook available" % sp["name"])
            return "break"
        bi, epc, pc = self._spawn_bank_index, sp["entry_pc"], sp["pc"]
        self.set_status("%s (inst %d) -> event bank %d, scene @0x%04x, line @0x%04x"
                        % (sp["name"], sp["instance"], bi, epc, pc))
        self.canvas.after_idle(lambda: self.on_open_scene(bi, epc, pc))
        return "break"

    # ---- SI (search-item spot) overlay loader --------------------------- #
    def _load_si_spots(self, map_filename: str):
        """Locate this map's SI_*.bin sidecar and return a list of spot dicts:
        [{tile_x, tile_y, raw_x, raw_y, pool: [{item_id, item_name, weight}, ...]}, ...].
        Returns [] if no SI file (most maps don't have one — only ~288 of 872 do).
        Records hold positions in 8-sub-units-per-tile (see Tile_GetAttrAt: `>>3`)."""
        self._si_file = None
        self._si_sel = None
        self._si_path = si_file_for_map(map_filename)
        if self._si_path:
            try:
                self._si_file = search_items.SearchItemFile.load(self._si_path)
            except Exception:
                self._si_file = None
        self._si_saved = self._si_file.build() if self._si_file is not None else None
        return self._si_dicts()

    def _si_dicts(self):
        """Draw/tooltip dicts from the editable self._si_file. Each carries its spot
        'idx'; positions are sub-units (tile = >>3); ids/weights are the effective
        (engine-used) values."""
        if not self._si_file:
            return []
        names = load_item_name_cache()
        out = []
        for idx, spot in enumerate(self._si_file.spots):
            pool = [{"item_id": e.effective_item_id,
                     "item_name": names.get(e.effective_item_id, f"item_{e.effective_item_id}"),
                     "weight": e.effective_weight} for e in spot.pool.entries]
            out.append({"idx": idx, "tile_x": spot.tile_x, "tile_y": spot.tile_y,
                        "raw_x": spot.x, "raw_y": spot.y, "pool": pool})
        return out

    # ---- render ---------------------------------------------------------- #
    def _set_zoom(self, px):
        self.cellpx = px
        self._redraw()

    # ---- ground-texture layer ------------------------------------------- #
    def _invalidate_ground(self):
        # Drop all cached grounds and cancel in-flight decodes. (Ground textures never
        # change during ATTR/MOBJ editing, so this isn't needed on map switch — the LRU
        # key includes map_base — but it's here if a caller ever needs a hard refresh.)
        self._ground_cache.clear()
        self._ground_gen += 1

    _LAYER_NAMES = {0: "0 ground", 1: "1 overlay"}

    def _refresh_layers(self):
        """Populate the layer dropdown: 'all' (composite) + each draw layer present."""
        layers = []
        if HAS_PIL and self.tex_reader and self.map_base:
            try:
                from rf4s_modkit import mapground
                layers = mapground.available_layers(self.tex_reader, self.map_base)
            except Exception:
                layers = []
        if hasattr(self, "layer_combo"):
            vals = ["off", "all"] + [self._LAYER_NAMES.get(ly, str(ly)) for ly in layers]
            self.layer_combo["values"] = vals
            if self.tex_layer.get() not in vals:
                self.tex_layer.set("all" if layers else "off")
        # the export/import picker offers only real layers, so it can never name one
        # the map does not have
        if hasattr(self, "ground_layer_combo"):
            gvals = [self._LAYER_NAMES.get(ly, str(ly)) for ly in layers]
            self.ground_layer_combo["values"] = gvals or ["0 ground"]
            if self.ground_layer.get() not in gvals:
                self.ground_layer.set(gvals[0] if gvals else "0 ground")
            self.ground_layer_combo.config(
                state="readonly" if len(gvals) > 1 else "disabled")
            # Always selectable so the user can turn the texture off; when no atlas
            # exists only "off"/"all" are offered (and "all" simply renders nothing).
            self.layer_combo.config(state="readonly")

    # ---- ground-texture replacement -------------------------------------- #
    def _ground_layer_choice(self):
        """Which draw layer the export/import buttons act on.

        Read from the export/import layer picker, which is deliberately independent of
        the display dropdown -- that one also offers "off" and "all", neither of which
        names a layer. Returns (layer, note) or (None, reason)."""
        if not (HAS_PIL and self.tex_reader and self.map_base):
            return None, "no map or no texture reader"
        try:
            layers = mapground.available_layers(self.tex_reader, self.map_base)
        except Exception as e:
            return None, "cannot list layers: %s" % e
        if not layers:
            return None, "this map ships no ground atlas"
        sel = (self.ground_layer.get() or "").strip()
        if sel and sel[0].isdigit():
            n = int(sel.split()[0])
            if n in layers:
                return n, ""
            return None, "this map has no layer %d (it has %s)" % (
                n, ", ".join(str(x) for x in layers))
        return layers[0], "layer %d" % layers[0]

    def _ground_info(self, layer):
        """Grid geometry for one layer, for the status line and for validation."""
        g = self.map.attr_grid() if self.map else None
        aspect = (g[0], g[1]) if g else None
        lay = mapground.tile_layout(self.tex_reader, self.map_base, layer, aspect)
        if lay is None:
            raise ValueError("layer %d has no atlas" % layer)
        lay["aspect"] = aspect
        lay["expect"] = lay["crop"] or lay["canvas"]
        return lay

    def _ground_export_to(self, path, layer):
        """Stitch one layer and write it as a PNG. Returns the info dict."""
        lay = self._ground_info(layer)
        res = mapground.stitch(self.tex_reader, self.map_base, layer, aspect=lay["aspect"])
        if not res:
            raise ValueError("layer %d produced no image" % layer)
        img = res[0]
        img.save(path)
        lay["saved"] = str(path)
        lay["image_size"] = img.size
        return lay

    def _ground_import_from(self, png_path, outdir, layer, fmt="keep"):
        """Split an edited PNG back into per-tile .texture files. Returns the names."""
        from PIL import Image
        import pathlib as _pl
        lay = self._ground_info(layer)
        img = Image.open(png_path)
        tiles = mapground.unstitch(self.tex_reader, self.map_base, img, layer,
                                   aspect=lay["aspect"],
                                   fmt=(None if fmt == "keep" else fmt))
        out = _pl.Path(outdir)
        out.mkdir(parents=True, exist_ok=True)
        for name, data in tiles:
            (out / name).write_bytes(data)
        return [n for n, _d in tiles]

    def _ground_export(self):
        layer, note = self._ground_layer_choice()
        if layer is None:
            messagebox.showinfo("Ground texture", "Cannot export: %s." % note)
            return
        try:
            lay = self._ground_info(layer)
        except Exception as e:
            messagebox.showerror("Ground texture", str(e)); return
        path = filedialog.asksaveasfilename(
            title="Export ground layer %d" % layer, defaultextension=".png",
            initialfile="%s_L%d.png" % (lay["set"], layer),
            filetypes=[("PNG image", "*.png")])
        if not path:
            return
        try:
            lay = self._ground_export_to(path, layer)
        except Exception as e:
            messagebox.showerror("Ground texture", str(e)); return
        self.ground_status.config(
            text="exported set %s layer %d — %d tiles, %d x %d grid, image %dx%d. "
                 "Edit it at exactly this size, then Import."
                 % (lay["set"], layer, len(lay["tiles"]), lay["cols"], lay["rows"],
                    lay["image_size"][0], lay["image_size"][1]))

    def _ground_import(self):
        layer, note = self._ground_layer_choice()
        if layer is None:
            messagebox.showinfo("Ground texture", "Cannot import: %s." % note)
            return
        png = filedialog.askopenfilename(title="Edited ground PNG",
                                         filetypes=[("PNG image", "*.png")])
        if not png:
            return
        outdir = filedialog.askdirectory(title="Write .texture files into")
        if not outdir:
            return
        try:
            names = self._ground_import_from(png, outdir, layer, self.ground_fmt.get())
        except Exception as e:
            # unstitch reports the exact size it wanted, which is the usual mistake
            messagebox.showerror("Ground texture", str(e)); return
        self.ground_status.config(
            text="wrote %d .texture files to %s — install them as loose overrides "
                 "(rf4mod install) or repack." % (len(names), outdir))

    def _decode_ground(self, map_base, sel, w, h):
        """Decode + stitch the ground for (map_base, sel) → PIL RGBA or None.
        PURE: no cache writes, no Tk calls — safe to run on the worker thread.
        'all' composites every draw layer; a single selection renders just that layer."""
        try:
            if sel == "all":
                res = mapground.stitch_composite(self.tex_reader, map_base, aspect=(w, h))
            else:
                res = mapground.stitch(self.tex_reader, map_base, int(sel.split()[0]), aspect=(w, h))
            return res[0] if res else None
        except Exception:
            return None

    def _cache_ground(self, key, img):
        self._ground_cache[key] = img
        self._ground_cache.move_to_end(key)
        while len(self._ground_cache) > self._GROUND_CACHE_MAX:
            self._ground_cache.popitem(last=False)

    def _ground_image(self, decode=False):
        """Decoded ground for the current (map, layer). NON-BLOCKING by default — returns
        the cached image or None (the async loader fills the cache, so the canvas can show
        ATTR/objects instantly). With ``decode=True`` it decodes synchronously if not yet
        cached (used by PNG export, which must block)."""
        if not (HAS_PIL and self.tex_reader and self.grid):
            return None
        key = (self.map_base, self.tex_layer.get())
        if key in self._ground_cache:
            self._ground_cache.move_to_end(key)
            return self._ground_cache[key]
        if not decode:
            return None
        w, h, _ = self.grid
        img = self._decode_ground(self.map_base, self.tex_layer.get(), w, h)
        self._cache_ground(key, img)
        return img

    def _request_ground(self):
        """Kick a background decode of the current ground (unless cached) so the map's
        ATTR/objects show instantly while the texture loads in. One serial worker (BC7
        decode is GIL-bound; a single thread also avoids concurrent bundle reads)."""
        if not (HAS_PIL and self.tex_reader and self.grid):
            return
        sel = self.tex_layer.get()
        if sel == "off" or (self.map_base, sel) in self._ground_cache:
            return
        w, h, _ = self.grid
        if self._ground_worker is None:
            self._ground_worker = threading.Thread(target=self._ground_worker_loop, daemon=True)
            self._ground_worker.start()
        self._ground_pending += 1
        self._ground_req.put((self.map_base, sel, w, h, self._ground_gen))
        if not self._ground_polling:
            self._ground_polling = True
            self.canvas.after(25, self._poll_ground)

    def _ground_worker_loop(self):
        while True:
            mb, sel, w, h, gen = self._ground_req.get()
            # Skip the decode entirely if the map already changed (stale request).
            img = None if gen != self._ground_gen else self._decode_ground(mb, sel, w, h)
            self._ground_q.put(((mb, sel), img, gen))

    def _poll_ground(self):
        redraw = False
        try:
            while True:
                key, img, gen = self._ground_q.get_nowait()
                self._ground_pending = max(0, self._ground_pending - 1)
                if gen != self._ground_gen:
                    continue                      # result for a map we've since left
                self._cache_ground(key, img)
                if key == (self.map_base, self.tex_layer.get()):
                    redraw = True
        except queue.Empty:
            pass
        if redraw:
            self._redraw()
        if self._ground_pending > 0:
            self.canvas.after(25, self._poll_ground)
        else:
            self._ground_polling = False

    def _on_tab_changed(self, _e=None):
        """Decode the over-model lazily — only when its tab is actually viewed (it can be
        a dozen-plus BC3 cards, wasted work on every map load if you never open the tab)."""
        try:
            if (getattr(self, "_nb", None) and self._om_dirty
                    and self._nb.tab(self._nb.select(), "text") == "Over-model"):
                self._om_dirty = False
                self._refresh_overmodel()
        except Exception:
            pass

    def _bg_composite(self, w, h, cells, cp, decode=False):
        """PIL RGBA background = ground texture (if enabled) under the ATTR fill,
        with optional bold edges drawn at the boundaries where ATTR cell values
        change. Returns None if PIL is missing or no layer is active.

        - When the texture is OFF, the ATTR fill is fully opaque (slider is
          ignored).
        - When the texture is ON, the ATTR fill uses the user-controlled alpha
          slider (default 180 ≈ 70 %, vs. the previous fixed 110 ≈ 43 %).
        - The "cell edges" overlay paints a thin contrasting line at every
          inter-cell boundary where the ATTR value differs — visible even when
          the fill alpha is low.
        """
        if not HAS_PIL:
            return None
        tex_on = self.tex_layer.get() != "off"
        attr_on = bool(self.layer_vars["attr"].get())
        edges_on = bool(self.layer_vars.get("edges") and self.layer_vars["edges"].get())
        base = None
        if tex_on:
            g = self._ground_image(decode=decode)
            if g is not None:
                # The texture scaled to the canvas only changes with the texture or the zoom;
                # re-scaling it on every redraw (layer toggles, selection, drags) was ~45 ms
                # of a ~60 ms redraw. Keyed on the source image object itself (held, so its
                # identity can't be reused) and the target size.
                size = (w * cp, h * cp)
                if getattr(self, "_scaled_src", None) is not g or self._scaled_size != size:
                    self._scaled_ground = g.resize(size, Image.BILINEAR).convert("RGBA")
                    self._scaled_src, self._scaled_size = g, size
                base = self._scaled_ground
        if attr_on:
            alpha = int(self.attr_alpha.get()) if base is not None else 255
            alpha = max(0, min(255, alpha))
            ov = Image.new("RGBA", (w, h)); opx = ov.load()
            for y in range(h):
                row = y * w
                for x in range(w):
                    c = self._value_colors.get(cells[row + x], ATTR_FLOOR)
                    opx[x, y] = (c[0], c[1], c[2], alpha)
            ov = ov.resize((w * cp, h * cp), Image.NEAREST)
            base = ov if base is None else Image.alpha_composite(base, ov)
        if edges_on and attr_on:
            base = self._draw_attr_edges(base, w, h, cells, cp, over_texture=tex_on)
        if base is not None and base is getattr(self, "_scaled_ground", None):
            base = base.copy()          # callers (PNG export) draw onto the result
        return base

    @staticmethod
    def _draw_attr_edges(base, w, h, cells, cp, *, over_texture):
        """Paint a thin line on every inter-cell boundary where the ATTR value
        changes. The line color/width adapts to whether we're drawing over the
        texture (bright + thicker for visibility) or just over the ATTR fill
        (dark + thinner). Costs O(w·h) — same scale as the fill loop."""
        from PIL import ImageDraw
        line = (255, 255, 0, 230) if over_texture else (0, 0, 0, 200)
        width = max(1, cp // 6) if over_texture else 1
        d = ImageDraw.Draw(base)
        # vertical boundaries (between cell (x, y) and (x+1, y))
        for y in range(h):
            row = y * w
            for x in range(w - 1):
                if cells[row + x] != cells[row + x + 1]:
                    X = (x + 1) * cp
                    d.line([(X, y * cp), (X, (y + 1) * cp)], fill=line, width=width)
        # horizontal boundaries (between cell (x, y) and (x, y+1))
        for y in range(h - 1):
            row = y * w
            nrow = row + w
            for x in range(w):
                if cells[row + x] != cells[nrow + x]:
                    Y = (y + 1) * cp
                    d.line([(x * cp, Y), ((x + 1) * cp, Y)], fill=line, width=width)
        return base

    def _redraw(self):
        self.canvas.delete("all")
        self._ent_items = {}
        if not self.grid:
            self.canvas.create_text(20, 20, anchor="nw", fill="#aaa", text="(no ATTR grid)")
            return
        w, h, cells = self.grid
        cp = self.cellpx
        bg = self._bg_composite(w, h, cells, cp)
        if bg is not None:
            self._bg_img = ImageTk.PhotoImage(bg)
            self.canvas.create_image(0, 0, anchor="nw", image=self._bg_img)
        elif not HAS_PIL and self.layer_vars["attr"].get():
            for y in range(h):
                for x in range(w):
                    c = self._value_colors.get(cells[y * w + x], ATTR_FLOOR)
                    self.canvas.create_rectangle(x * cp, y * cp, x * cp + cp, y * cp + cp,
                                                 fill="#%02x%02x%02x" % c, width=0)
        if self.layer_vars["grid"].get() and cp >= 4:
            for x in range(w + 1):
                self.canvas.create_line(x * cp, 0, x * cp, h * cp, fill="#2a2a30")
            for y in range(h + 1):
                self.canvas.create_line(0, y * cp, w * cp, y * cp, fill="#2a2a30")
        self._warp_handles = {}
        if self.layer_vars["mapj"].get():
            for j, (x0, y0, x1, y1) in enumerate(self._mapj_rects()):
                rx0, ry0 = x0 * cp, y0 * cp
                rx1, ry1 = max(x1 * cp, x0 * cp + cp), max(y1 * cp, y0 * cp + cp)
                sel = (self._sel_kind == "warp" and j == self._sel_warp)
                self.canvas.create_rectangle(rx0, ry0, rx1, ry1,
                                             outline=("#00e5ff" if sel else "#ffd040"),
                                             width=(3 if sel else 2))
                if sel:
                    # 8 grab handles (4 corners + 4 edge midpoints) for drag-resize.
                    hs = max(3, cp // 2)
                    mx, my = (rx0 + rx1) // 2, (ry0 + ry1) // 2
                    for mode, (hx, hy) in (("nw", (rx0, ry0)), ("n", (mx, ry0)), ("ne", (rx1, ry0)),
                                           ("w", (rx0, my)), ("e", (rx1, my)),
                                           ("sw", (rx0, ry1)), ("s", (mx, ry1)), ("se", (rx1, ry1))):
                        self.canvas.create_rectangle(hx - hs, hy - hs, hx + hs, hy + hs,
                                                     fill="#00e5ff", outline="#002b33", width=1)
                        self._warp_handles[mode] = (hx, hy)
        r = max(3, cp // 2 + 1)
        sprites_on = bool(self.layer_vars.get("sprites") and self.layer_vars["sprites"].get())
        labels_on = bool(self.layer_vars.get("triglabels") and self.layer_vars["triglabels"].get())
        # sprite footprint ~3 tiles tall, capped; scaled by the object's own scale field
        spr_base = max(12, min(180, int(cp * 3))) if sprites_on else 0
        for i, o in enumerate(self.objs):
            cat = o["category"]
            # "forage" dots share the trigger toggle (both go through the trigger handler).
            toggle_key = "trigger" if cat in _TRIGGER_KINDS else cat
            if not self.layer_vars.get(toggle_key, tk.BooleanVar(value=True)).get():
                continue
            if o["pos_x"] == 0 and o["pos_y"] == 0:
                continue
            cx, cy = (o["pos_x"] >> 3) * cp, (o["pos_y"] >> 3) * cp
            photo = None
            if sprites_on:
                _sz = max(8, min(256, int(spr_base * (o.get("scale") or 1.0))))
                photo = self._mobj_sprite_photo(o.get("type_id"), _sz)
            if photo is not None:
                # billboard: anchor the sprite's BASE at the object's tile (stands on its position)
                item = self.canvas.create_image(cx, cy, image=photo, anchor="s")
            else:
                item = self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                               fill=CAT_COLOR.get(cat, "#fff"), outline="#000", width=1)
            self._ent_items[item] = i
            # Trigger-labels overlay: name each INTERACTIVE object (skip pure ambient/decoration
            # FX) so the map's trigger/interaction points are readable without hovering each dot.
            if labels_on and cat not in ("ambient", "decoration"):
                self.canvas.create_text(cx, cy - r - 1, anchor="s", text=cat, fill="#ffe000",
                                        font=("Segoe UI", max(6, cp // 3)))
        if self.layer_vars.get("si") and self.layer_vars["si"].get():
            self._si_items = {}
            sr = max(5, cp // 2 + 3)  # slightly larger than entity dots
            for i, sp in enumerate(self._si_spots):
                cx, cy = sp["tile_x"] * cp + cp // 2, sp["tile_y"] * cp + cp // 2
                if self._sel_kind == "si" and sp.get("idx") == self._si_sel:   # selected-spot ring
                    self.canvas.create_oval(cx - sr - 5, cy - sr - 5, cx + sr + 5, cy + sr + 5,
                                            outline="#00e5ff", width=3)
                # Two-tone marker: white halo + bright yellow core, easy to spot
                # over both texture and ATTR fills.
                self.canvas.create_oval(cx - sr - 1, cy - sr - 1, cx + sr + 1, cy + sr + 1,
                                        outline="#ffffff", width=2)
                it = self.canvas.create_oval(cx - sr, cy - sr, cx + sr, cy + sr,
                                             fill="#ffe000", outline="#a06000", width=2)
                # Small index label so the user can correlate to the SI file's
                # spot index when there are multiple.
                self.canvas.create_text(cx, cy, text=str(i),
                                        fill="#000", font=("Segoe UI", max(7, cp // 3)))
                self._si_items[it] = sp
        # Script-spawned NPCs / interactibles (EventSpawnNpc in the map's event bank) -- placed
        # by the EVENT SCRIPT, not the .rf4m (e.g. char 269 "Search" = search spots). Lazy-loaded
        # from rf3.mc the first time the layer is shown for this map.
        if self.layer_vars.get("spawns") and self.layer_vars["spawns"].get():
            if not self._spawns_loaded:
                self._load_spawns(self._spawn_bare)
            sr = max(4, cp // 2)
            self._spawn_items = {}
            for sp in self._spawns:
                cx, cy = sp["tile_x"] * cp + cp // 2, sp["tile_y"] * cp + cp // 2
                it = self.canvas.create_oval(cx - sr, cy - sr, cx + sr, cy + sr,
                                             fill="#c060ff", outline="#2a0640", width=1)
                lb = self.canvas.create_text(cx, cy - sr - 1, anchor="s", text=sp["name"],
                                             fill="#e6b3ff", font=("Segoe UI", max(6, cp // 3)))
                # Click a marker -> jump to its EventSpawnNpc line in the cutscene editor.
                for _mk in (it, lb):
                    self._spawn_items[_mk] = sp
                    self.canvas.tag_bind(_mk, "<Button-1>",
                                         lambda _e, s=sp: self._open_spawn_scene(s))
                    self.canvas.tag_bind(_mk, "<Enter>",
                                         lambda _e: self.canvas.config(cursor="hand2"))
                    self.canvas.tag_bind(_mk, "<Leave>",
                                         lambda _e: self.canvas.config(cursor=""))
        # Encounter GATES (from the area's Gen*.bin): where the monster-spawning gates are
        # placed (orange diamond "G") + where their monsters appear (pink dots). Positions
        # decoded from the Gen sub-blocks (see gen.gate_positions/monster_positions).
        if self.layer_vars.get("gates") and self.layer_vars["gates"].get():
            self._gate_items = {}
            for (tx, ty) in getattr(self, "_gen_mon_pts", []):
                cx, cy = tx * cp + cp // 2, ty * cp + cp // 2
                self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                                        fill="#ff5aa0", outline="#000", width=1)
            gr = max(6, cp // 2 + 2)
            for mk in getattr(self, "_gate_markers", []):
                cx, cy = mk["tx"] * cp + cp // 2, mk["ty"] * cp + cp // 2
                if self._gate_sel is mk:      # selection ring on the active gate
                    self.canvas.create_oval(cx - gr - 5, cy - gr - 5, cx + gr + 5, cy + gr + 5,
                                            outline="#00e5ff", width=3)
                it = self.canvas.create_polygon(cx, cy - gr, cx + gr, cy, cx, cy + gr, cx - gr, cy,
                                                fill="#ff8c1a", outline="#000", width=2)
                self.canvas.create_text(cx, cy, text="G", fill="#000",
                                        font=("Segoe UI", max(7, cp // 3), "bold"))
                self._gate_items[it] = mk
        # Warp DESTINATION names. This labels each MAPJ warp with where it LEADS (via
        # rf3TxtMapName). NOTE: these are NOT the in-game shop signboards -- those are
        # separate shop objects ("shop_balloon"), spawned by the shop system and NOT stored
        # in the .rf4m. But building-entrance warps sit next to their shop, so labelling the
        # destination (e.g. "Bell Hotel Lobby") is a handy proxy for "which building is here".
        if self.layer_vars.get("dest") and self.layer_vars["dest"].get():
            mapj = self.map.mapj_records()
            for j, (x0, y0, x1, y1) in enumerate(self._mapj_rects()):
                if j >= len(mapj):
                    break
                name, _is_bld = map_names.describe_destination(mapj[j][5])
                if not name:
                    continue
                mx = int((x0 + x1) / 2 * cp)
                ty = int(y0 * cp - 2)
                # consistent style for EVERY warp: plain yellow destination text, no background
                self.canvas.create_text(mx, ty, text=name, anchor="s",
                                        fill="#ffd040", font=("Segoe UI", max(7, cp // 2)))
        self.canvas.config(scrollregion=(0, 0, w * cp, h * cp))
        self._highlight_selected()

    def _mapj_rects(self):
        """MAPJ trigger-zone rectangles in THIS map, as (x0,y0,x1,y1) tiles.

        Record layout (9 i32, every field verified in RF4S.exe 2026-09-19 — see
        rf4m.MAPJ_FIELDS / Rf4mMap.decode_mapj):
          [0]    = disable-flag: per-map scene-flag id; the warp is dead while it is
                   SET, -1 = always active (Widget_UpdateBit20FromGameFlag)
          [1..4] = zone x, y, w, h in sub-units (>>3 = tiles): the collision box of
                   the "m_move_obj" widget Map_SpawnEntityByCategoryAndIdx builds
          [5]    = destination map id
          [6]    = arrival X in the TARGET map (sub-units)
          [7]    = arrival Y in the target map
          [8]    = arrival facing in degrees (0 = keep; Cutscene_StartDeathSequence,
                   the shared map-transition entry, stores it x182 as a Q16 angle)
        """
        out = []
        for rec in self.map.mapj_records():
            x, y, w, hh = rec[1], rec[2], rec[3], rec[4]
            out.append((x >> 3, y >> 3, (x + w) >> 3, (y + hh) >> 3))
        return out

    # ---- editor interaction --------------------------------------------- #
    def _click_tile(self, e):
        if not self.grid:
            return None
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        w, h, _ = self.grid
        tx, ty = int(cx // self.cellpx), int(cy // self.cellpx)
        return (tx, ty) if 0 <= tx < w and 0 <= ty < h else None

    def _entity_under(self, e):
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        for item in reversed(self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)):
            if item in self._ent_items:
                return self._ent_items[item]
        return None

    # ---- hover tooltip: reveal the MOBJ identity under the cursor -------- #
    def _hide_tip(self):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _show_tip(self, e, text):
        self._hide_tip()
        self._tip = tk.Toplevel(self.canvas)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{e.x_root + 12}+{e.y_root + 12}")
        tk.Label(self._tip, text=text, justify="left", bg="#222", fg="#eee",
                 font=("Consolas", 8), bd=1, relief="solid", padx=4, pady=2).pack()

    def _bind_attr_help(self, widget, mask):
        """Ctrl-hover help on one Paint ATTR checkbox.

        Same gesture the canvas already uses for the tile inspector: hold Ctrl and
        hover. Motion carries the modifier state, so this also fires if Ctrl goes
        down while the pointer is already sitting on the box.
        """
        def _motion(e, _m=mask):
            if e.state & 0x0004:            # Ctrl held
                self._show_tip(e, surface_help() if _m is None else attr_bit_help(_m))
            else:
                self._hide_tip()
        widget.bind("<Motion>", _motion, add="+")
        widget.bind("<Leave>", lambda _e: self._hide_tip(), add="+")

    def _show_attr_tip(self, e):
        """ATTR inspector: tooltip with the hovered tile's raw value + flag decode."""
        t = self._click_tile(e)
        if not t or not self.grid:
            self._hide_tip()
            return
        w, _h, cells = self.grid
        tx, ty = t
        val = cells[ty * w + tx]
        self._show_tip(e, f"tile ({tx}, {ty})   ATTR = 0x{val:X}\n{attr_notes(val)}")

    def _on_hover(self, e):
        # Hold Ctrl to inspect the tile's ATTR value instead of entity info.
        if e.state & 0x0004:
            self._show_attr_tip(e)
            return
        idx = self._entity_under(e)
        if idx is not None and idx < len(self.objs):
            o = self.objs[idx]
            tid = o["type_id"] & 0xFFFF
            note = mobj_types.mobj_note(tid)
            # identified types: the note leads with the readable identity (and
            # carries the codename-free description); others show the sprite name
            head = note or mobj_types.mobj_name(tid) or f"type {o['type_id']} (no sprite)"
            self._show_tip(e, f"#{idx}  {head}\n{o['category']}  "
                              f"tile ({o['pos_x']>>3},{o['pos_y']>>3})")
            return
        sp = self._si_spot_under(e)
        if sp is not None:
            self._show_tip(e, f"SI spot ({sp['tile_x']},{sp['tile_y']})  "
                              f"{len(sp['pool'])} drops")
            return
        self._hide_tip()

    def _si_spot_under(self, e):
        """Return the SI spot dict under the cursor, or None."""
        if not getattr(self, "_si_items", None):
            return None
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        for item in reversed(self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)):
            if item in self._si_items:
                return self._si_items[item]
        return None

    def _gate_under(self, e):
        """Return the encounter-gate marker dict under the cursor, or None."""
        if not getattr(self, "_gate_items", None):
            return None
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        for item in reversed(self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)):
            if item in self._gate_items:
                return self._gate_items[item]
        return None

    def _show_si_spot(self, sp):
        """Pop the spot's drop pool into the Info text area for quick read."""
        if not hasattr(self, "info"):
            self.set_status(
                f"SI spot @ tile ({sp['tile_x']},{sp['tile_y']}) "
                f"raw ({sp['raw_x']},{sp['raw_y']}) — {len(sp['pool'])} drops")
            return
        total = sum(e["weight"] for e in sp["pool"]) or 1
        lines = [
            f"SI search-item spot",
            f"  tile      = ({sp['tile_x']}, {sp['tile_y']})",
            f"  raw pos   = ({sp['raw_x']}, {sp['raw_y']})  (= tile * 8)",
            f"  spawn pos = ({sp['raw_x'] - 4}, {sp['raw_y'] - 8}) << 12  (Q12 world)",
            f"  drop pool ({len(sp['pool'])} entries, total weight {total}):",
        ]
        for e in sp["pool"]:
            pct = 100.0 * e["weight"] / total
            lines.append(f"    #{e['item_id']:4d}  w={e['weight']:3d} ({pct:4.1f}%)  "
                         f"{e['item_name']}")
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", "\n".join(lines))
        self.info.configure(state="disabled")

    def _snapshot(self):
        if self.map:
            self._push_undo(self.map.build())

    def _push_undo(self, before):
        """Record `before` (serialized map bytes) as one undo step."""
        self._undo.append(before)
        if len(self._undo) > 40:
            self._undo.pop(0)
        self._redo.clear()           # a fresh edit invalidates the redo stack

    def _commit(self, before):
        """Finish a form-driven edit that mutated self.map in place: record ONE undo step
        if the bytes changed, nothing otherwise. Returns True when something changed.
        (The Apply buttons used to snapshot unconditionally, so every no-op Apply --
        and every Apply that then failed validation -- left a junk undo step.)"""
        if self.map.build() == before:
            return False
        self._push_undo(before)
        return True

    def _rollback(self, before):
        """Undo a half-applied form edit (e.g. MSEA set, then MGRP failed to parse)."""
        self.map = rf4m.Rf4mMap.parse(before)

    def _restore_map(self, data):
        """Parse + install a serialized map snapshot and refresh the view."""
        self.map = rf4m.Rf4mMap.parse(data)
        self.objs = self.map.decode_mobj()
        # The ATTR renderer draws from this cached grid, not from self.map, so it has
        # to be re-read here. Without it an undo restored the map but kept painting
        # the pre-undo cells until the next paint refreshed the cache by itself.
        self.grid = self.map.attr_grid()
        if self.grid:
            for v in set(self.grid[2]):
                if v not in self._value_colors:
                    self._value_colors[v] = ATTR_PALETTE[len(self._value_colors) % len(ATTR_PALETTE)]
        # Indices can shift across an undo/redo, and the entity fields still hold the
        # pre-undo values: a later focus-out would run _apply_entity and write the undone
        # edit straight back. So drop the whole selection, fields included.
        self._select(None)
        self._edit_idx = None
        self._sel_warp = None
        self._warp_drag = None
        self._drag_idx = None
        self._refresh_entities()
        self._refresh_warps()
        self._refresh_props()
        self._redraw()
        if self.on_change:
            self.on_change(self.map.build())

    def _undo_op(self):
        if not self._undo:
            self.set_status("Nothing to undo"); return
        self._redo.append(self.map.build())     # remember current for redo
        self._restore_map(self._undo.pop())
        self.set_status(f"Undo  ({len(self._undo)} undo / {len(self._redo)} redo)")

    def _redo_op(self):
        if not self._redo:
            self.set_status("Nothing to redo"); return
        self._undo.append(self.map.build())     # current becomes undoable again
        self._restore_map(self._redo.pop())
        self.set_status(f"Redo  ({len(self._undo)} undo / {len(self._redo)} redo)")

    # ---- validation ------------------------------------------------------ #
    def _validate_map(self):
        """Check the map against what the game's loader does (rf4m.Rf4mMap.validate):
        unknown chunk tags (the loader stops there), missing MGRP/ATTR/MTXN, the fixed
        pointer-array capacities (10 MAPJ / 40 MOBJ / 6 MTXN chunks), multi-record
        chunks (only the first record is read), MOBJ types past the sprite band,
        objects / warp zones off the grid, warps to unknown maps, bad facing/flags.

        When the ground tiles are reachable it also checks the ATLAS against the ATTR
        grid -- the engine derives its tile count from ATTR alone and loads tile i as
        archive id base+i, so a map whose grid outgrew its atlas asks for tiles that do
        not exist and silently draws the next set's files instead."""
        if not self.map:
            messagebox.showinfo("Validate", "No map loaded."); return
        rooms = getattr(self, "_roomsById", None) or {
            mid: name for name, (mid, _r) in self.rooms.items()}
        issues = self.map.validate(known_maps=set(rooms), ground_reader=self.tex_reader,
                                   map_name=self.map_base or self.map_name or None)
        W, H = (self.grid[0], self.grid[1]) if self.grid else (0, 0)
        params = sum(1 for o in self.objs if o["category"] == "mapparam")
        unplaced = sum(1 for o in self.objs
                       if o["category"] != "mapparam" and o["pos_x"] == 0 and o["pos_y"] == 0)
        warps = self.map.mapj_records()
        summary = (f"{W}×{H} grid · {len(self.objs)} MOBJ records ({params} map parameters, "
                   f"{unplaced} unplaced) · {len(warps)} warps · "
                   f"{len(self.map.find(b'MTXN'))} display layer(s)")
        n_err = sum(1 for s in issues if s.startswith("ERROR"))
        if not issues:
            messagebox.showinfo("Validate", f"No problems found.\n\n{summary}")
        else:
            shown = "\n".join("• " + s for s in issues[:30])
            more = "" if len(issues) <= 30 else f"\n…and {len(issues) - 30} more"
            (messagebox.showerror if n_err else messagebox.showwarning)(
                "Validate", f"{len(issues)} issue(s), {n_err} fatal:\n\n{shown}{more}\n\n{summary}")
        self.set_status(f"Validate: {len(issues)} issue(s), {n_err} fatal")

    def _on_ctrl_press(self, e):
        """Ctrl+click a warp -> navigate to its destination map. This is bound to
        <Control-Button-1> (more specific than <Button-1>), so it fires instead of
        _on_press when Ctrl is held; a plain click still selects."""
        self.canvas.focus_set()
        if self.map is None or not self.layer_vars["mapj"].get():
            return
        wi = self._warp_under(e)
        if wi is not None:
            self._warp_goto(wi)

    def _on_double_click(self, e):
        """Double-click a warp zone -> open its destination map (same target as Ctrl+click).
        Bound to <Double-Button-1>; the two preceding single clicks just (re)select the warp,
        then this navigates. Requires the MAPJ (warp) layer to be visible."""
        self.canvas.focus_set()
        if self.map is None or not self.layer_vars["mapj"].get():
            return
        wi = self._warp_under(e)
        if wi is not None:
            self._warp_goto(wi)
            return "break"   # swallow the double-click so no other handler also fires

    # A press only becomes a drag once the pointer has travelled this many pixels (the
    # Windows drag threshold is 4). Without it a click on an entity or warp near a tile
    # edge jittered one pixel into the next tile and moved it a whole tile.
    DRAG_THRESHOLD_PX = 4

    def _past_drag_threshold(self, e):
        px = getattr(self, "_press_xy", None)
        if px is None:
            return True
        if getattr(self, "_dragging", False):
            return True
        if abs(e.x - px[0]) >= self.DRAG_THRESHOLD_PX or abs(e.y - px[1]) >= self.DRAG_THRESHOLD_PX:
            self._dragging = True
            return True
        return False

    def _on_press(self, e):
        self.canvas.focus_set()      # so <Delete>/<BackSpace> reach the canvas
        self._press_xy = (e.x, e.y)
        self._dragging = False
        tool = self.tool.get()
        if tool == "add":
            t = self._click_tile(e)
            if t:
                try:                        # parse BEFORE snapshotting so a bad type isn't a no-op undo
                    typ = int(self.add_type.get(), 0)
                except ValueError:
                    return
                self._snapshot()
                if 9 <= (typ & 0xFFFF) <= 19:
                    # map parameter records are positionless: the game never reads f14/f15
                    px = py = 0
                    where = " (map-wide parameter record, no position — set f8.. in Edit)"
                else:
                    px, py = (t[0] << 3) + 4, (t[1] << 3) + 4
                    where = f" at tile {t}"
                idx = self.map.add_mobj_record([typ, -1, -1, -1, -1, -1, 4096, 0,
                                                0, 0, 0, 0, 0, -1, px, py])
                self._changed(); self._show_entity(idx)
                self.set_status(f"Added entity type {typ}{where} — Save…")
        elif tool == "paint":
            if self._click_tile(e) is not None:   # skip snapshot on out-of-grid no-op clicks
                self._snapshot(); self._paint(e)
        else:  # "select": click selects, drag moves/resizes (one selection at a time)
            # 1) A grab handle of the already-selected warp takes priority (resize).
            if (self._sel_kind == "warp" and self._sel_warp is not None
                    and self.layer_vars["mapj"].get()):
                mode = self._warp_handle_at(e)
                if mode:
                    rec = self.map.mapj_records()[self._sel_warp]
                    self._warp_drag = (self._sel_warp, mode, self._click_edge(e),
                                       [rec[1], rec[2], rec[3], rec[4]])   # sub-units
                    self._warp_started = False
                    return
            # 2) MOBJ entity dot.
            idx = self._entity_under(e)
            if idx is not None:
                self._show_entity(idx); self._show_tab("Edit")
                self._drag_idx = idx
                self._drag_moved = False
                return
            self._drag_idx = None
            # 2.5) Encounter gate marker (Gen*.bin) -> select + begin move.
            gm = self._gate_under(e)
            if gm is not None:
                self._select("gate")
                self._gate_sel = gm
                self._gate_drag = gm
                self._gate_moved = False
                self._show_tab("Gates")
                self._redraw()
                return
            # 3) SI search-item spot.
            sp = self._si_spot_under(e)
            if sp is not None:
                self._select("si")
                self._si_sel = sp.get("idx")
                self._si_drag = self._si_sel
                self._si_moved = False
                if self._si_sel is not None and self._si_sel < self.si_list.size():
                    self.si_list.selection_set(self._si_sel); self.si_list.see(self._si_sel)
                self._si_show_selected()
                self._show_si_spot(sp)
                self._show_tab("Search items")
                self._redraw()
                return
            # 4) Warp interior -> select + begin move.
            if self.layer_vars["mapj"].get():
                wi = self._warp_under(e)
                if wi is not None:
                    self.warp_list.selection_clear(0, "end")
                    self.warp_list.selection_set(wi); self.warp_list.see(wi)
                    self._warp_selected(); self._show_tab("Warps")
                    rec = self.map.mapj_records()[wi]
                    self._warp_drag = (wi, "move", self._click_tile(e),
                                       [rec[1], rec[2], rec[3], rec[4]])   # sub-units
                    self._warp_started = False
                    return
            # 5) Empty space -> clear the selection.
            if self._sel_kind is not None:
                self._select(None)
                self._redraw()

    def _on_drag(self, e):
        tool = self.tool.get()
        if tool == "select" and not self._past_drag_threshold(e):
            return                   # still a click: nothing moves yet
        if tool == "paint":
            self._paint(e)
        elif tool == "select" and self._drag_idx is not None:
            t = self._click_tile(e)
            if not t:
                return
            rec = list(self.map.mobj_records()[self._drag_idx])
            if not self._drag_moved:
                # A click always jitters a pixel or two. Until the pointer leaves the
                # entity's OWN tile this is a click, not a move -- otherwise merely
                # selecting an entity snapped its exact position to the tile centre.
                if t == (rec[14] >> 3, rec[15] >> 3):
                    return
                self._snapshot(); self._drag_moved = True   # snapshot once, at the first real move
            rec[14], rec[15] = (t[0] << 3) + 4, (t[1] << 3) + 4
            self.map.set_mobj_record(self._drag_idx, rec)
            self._changed()
            self._show_entity(self._drag_idx)
        elif tool == "select" and self._si_drag is not None:
            t = self._click_tile(e)
            if t and self._si_file is not None and self._si_drag < len(self._si_file.spots):
                sp = self._si_file.spots[self._si_drag]
                sp.x, sp.y = (t[0] << 3) + 4, (t[1] << 3) + 4
                self.si_x.set(str(sp.x)); self.si_y.set(str(sp.y))
                self._si_moved = True
                self._si_spots = self._si_dicts()
                self._redraw()
        elif tool == "select" and self._gate_drag is not None:
            t = self._click_tile(e)
            if t and self._gen is not None:
                x, y = (t[0] << 3) + 4, (t[1] << 3) + 4     # tile centre, sub-units (like MOBJ)
                self._gen.set_position(self._gate_drag["off"], x, y)
                self._gate_drag["tx"], self._gate_drag["ty"] = t[0], t[1]
                self._gate_moved = True
                self._redraw()
        elif tool == "select" and self._warp_drag is not None:
            self._warp_drag_to(e)

    def _on_release(self, e):
        if self.tool.get() == "select" and self._drag_idx is not None and self._drag_moved:
            self.set_status(f"Moved entity #{self._drag_idx} — Save…")
            self._show_entity(self._drag_idx)
        if (self.tool.get() == "select" and self._si_drag is not None
                and getattr(self, "_si_moved", False)):
            self._si_sel = self._si_drag
            self._si_after_edit()
            self.set_status(f"Moved SI spot #{self._si_drag} — Save SI file…")
        if (self.tool.get() == "select" and self._gate_drag is not None
                and getattr(self, "_gate_moved", False)):
            self.set_status(f"Moved gate to tile ({self._gate_drag['tx']},{self._gate_drag['ty']}) "
                            f"— 'Save Gen file…' (Gates tab) to persist")
        if self.tool.get() == "select" and self._warp_drag is not None and self._warp_started:
            widx = self._warp_drag[0]
            self._refresh_warps()
            self.warp_list.selection_clear(0, "end")
            if widx < self.warp_list.size():
                self.warp_list.selection_set(widx); self.warp_list.see(widx)
            self.set_status(f"Warp #{widx} moved/resized — Save…")
        self._warp_drag = None
        self._warp_started = False
        self._si_drag = None
        self._si_moved = False
        self._gate_drag = None
        self._gate_moved = False
        self._drag_idx = None
        self._drag_moved = False
        self._press_xy = None
        self._dragging = False

    # ---- entity list + selection highlight ------------------------------ #
    @staticmethod
    def _fmt_choice(tid, name):
        """Format a type dropdown entry: '<id>  <readable name>'. Identified types
        show their readable identity instead of the fe*/gmk* codename
        (e.g. '68  chimney smoke', '48  BARRIER'); the id stays first, and it is
        what keeps same-named entries (the three treasure types) distinct."""
        return f"{tid}  {mobj_types.mobj_display_name(tid) or name}"

    def _mobj_choice_for(self, tid):
        """The dropdown entry for a type_id, or '' when it has no identity at all
        (unused parameter ids 14/16..19, unknown ids). Forage 0..8 and the map
        parameter records 9..19 resolve via the
        display-name fallback like everything else."""
        n = mobj_types.mobj_display_name(tid)
        return self._fmt_choice(tid, n) if n else ""

    def _on_ent_type_pick(self, _e):
        """Type dropdown changed -> set f0 to the chosen type_id and apply."""
        if self._edit_idx is None:
            return
        s = self.ent_type_pick.get()
        if not s:
            return
        try:
            tid = int(s.split()[0])
        except ValueError:
            return
        self.ent_fields[0].set(str(tid))
        self._apply_entity(silent=True)
        if self._edit_idx is not None:
            self._show_entity(self._edit_idx)   # refresh detail + dropdown label

    def _delete_selected(self):
        """Route Delete/BackSpace to the right delete action for the current selection kind
        (previously only MOBJ was handled; a selected warp or SI spot ignored the key)."""
        if self._sel_kind == "warp":
            self._warp_delete()          # listbox is kept in sync with the map warp selection
        elif self._sel_kind == "si":
            self._si_del_spot()          # uses self._si_sel (set by the map click)
        else:
            self._delete_selected_entity()

    def _delete_selected_entity(self):
        if self._edit_idx is None:
            self.set_status("No entity selected to delete.")
            return
        idx = self._edit_idx
        self._snapshot()
        self.map.delete_mobj_record(idx)
        self._edit_idx = None
        self.detail.delete("1.0", "end")
        for v in self.ent_fields:
            v.set("")
        self._changed()
        self.set_status(f"Deleted entity #{idx} — Save…")

    def _highlight_selected(self):
        """Draw a highlight ring around the currently-selected entity dot."""
        self.canvas.delete("selmark")
        if self._sel_kind != "mobj" or self._edit_idx is None or self._edit_idx >= len(self.objs):
            return
        o = self.objs[self._edit_idx]
        if o["pos_x"] == 0 and o["pos_y"] == 0:
            return
        cp = self.cellpx
        cx, cy = (o["pos_x"] >> 3) * cp, (o["pos_y"] >> 3) * cp
        rr = max(6, cp // 2 + 4)
        self.canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                                outline="#00e5ff", width=3, tags="selmark")

    # ---- Paint ATTR flag-panel sync ------------------------------------- #
    def _paint_cur_val(self):
        """Current paint value as int, or None if the entry is junk."""
        txt = self.paint_val.get().strip()
        try:
            return int(txt.split()[0], 0) if txt else 0
        except ValueError:
            return None

    def _paint_update_decode(self, val):
        self.paint_decode.config(text=attr_notes(val))

    def _paint_sync_from_bits(self):
        """Checkbox toggled -> rebuild value (preserving any render-only bits that
        aren't represented by a checkbox)."""
        named = 0
        for mask in self.paint_bit_vars:
            named |= mask
        surf_all = 0
        for m in SURFACE_FIELD:
            surf_all |= m
        cur = self._paint_cur_val() or 0
        val = cur & ~named & ~surf_all          # keep anything we do not control
        for mask, bv in self.paint_bit_vars.items():
            if bv.get():
                val |= mask
        # the surface field contributes at most one bit, so two can never be set
        val |= SURFACE_BY_LABEL.get(self.paint_surface.get(), 0)
        self.paint_val.set("0x%X" % val)
        self._paint_update_decode(val)

    def _paint_sync_from_entry(self):
        """Raw value edited -> set each checkbox + the surface choice + decode."""
        val = self._paint_cur_val()
        if val is None:
            self.paint_decode.config(text="(bad value)")
            return
        for mask, bv in self.paint_bit_vars.items():
            bv.set(bool(val & mask))
        # a hand-typed value could carry two surface bits even though the game
        # never produces one; show the lowest and let the decode label expose the rest
        chosen = "(none)"
        for m in SURFACE_FIELD:
            if val & m:
                chosen = SURFACE_BY_MASK.get(m, "(none)")
                break
        if hasattr(self, "paint_surface"):
            self.paint_surface.set(chosen)
        self._paint_update_decode(val)

    def _paint_set(self, val):
        """Preset button -> set value + checkboxes + decode."""
        self.paint_val.set("0x%X" % val)
        self._paint_sync_from_entry()

    def _paint(self, e):
        t = self._click_tile(e)
        if not t:
            return
        txt = self.paint_val.get().strip()
        if not txt:
            return
        try:
            val = int(txt.split()[0], 0)
        except ValueError:
            return
        self.map.set_attr_cell(t[0], t[1], val)
        self.grid = self.map.attr_grid()
        if val not in self._value_colors:
            self._value_colors[val] = ATTR_PALETTE[len(self._value_colors) % len(ATTR_PALETTE)]
        # Route the painted cell through the same composite path as every other
        # cell so it honours the ATTR opacity slider, the cell-edges toggle, and
        # the texture layer. (A previous fast-path canvas.create_rectangle drew
        # the cell as a fully-opaque solid colour on top of the texture, which
        # ignored all three settings.)
        self._redraw()
        if self.on_change:
            self.on_change(self.map.build())

    def _show_entity(self, idx):
        o = self.objs[idx]
        self._edit_idx = idx
        self._select("mobj", idx)           # sole selection: clears any SI / warp
        if hasattr(self, "ent_list") and idx < self.ent_list.size():
            self.ent_list.selection_clear(0, "end")
            self.ent_list.selection_set(idx); self.ent_list.see(idx)
        rec = self.map.mobj_records()[idx]
        for k, v in enumerate(self.ent_fields):
            v.set(str(rec[k]))
        tid = rec[0] & 0xFFFF
        name = mobj_types.mobj_name(tid)
        note = mobj_types.mobj_note(tid)
        if name:
            ident = f"{name}  (map_obj/{name}.bntx, archive {mobj_types.mobj_archive_id(tid)})"
            if note:
                ident += f"\n  = {note}"
        else:
            # forage spawn points and the positionless map-parameter records 9..19
            ident = mobj_types.mobj_label(tid)
        where = ("(map-wide, no position)" if o["category"] == "mapparam"
                 else f"tile ({o['pos_x']>>3}, {o['pos_y']>>3})")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", f"entity #{idx}  [{o['category']}]  {where}\n{ident}")
        self._show_param_legend(tid, rec)
        self._highlight_selected()
        # Reflect the current type in the friendly Type dropdown (blank for
        # forage/trigger/unknown types that have no map_obj name).
        if hasattr(self, "ent_type_pick"):
            self.ent_type_pick.set(self._mobj_choice_for(tid))
        if hasattr(self, "ent_type_full"):
            self.ent_type_full.config(text=mobj_types.mobj_label(tid))

    def _show_param_legend(self, tid, rec):
        """Fill the green 'parameter legend' box under Selected entity: the per-type
        field meanings + IDA-verified sizes (the green text that used to live in the
        standalone MOBJ tab). Defensive — any decode hiccup just blanks the box rather
        than breaking entity selection."""
        pl = getattr(self, "param_legend", None)
        if pl is None:
            return
        try:
            role, rows = mobj_params.describe(tid)
            interact = mobj_params.interaction_summary(tid, rec[13])
            SZ = mobj_params.SIZE_NAME
            lines = [f"type {tid}: {role}", f"   ⇒ interaction: {interact}"]
            for fi, sz, mean in rows:
                eff = rec[fi] & ((1 << (8 * sz)) - 1)
                extra = "  (raw 0x%X, only low %s used)" % (rec[fi] & 0xFFFFFFFF, SZ[sz]) \
                    if (rec[fi] & 0xFFFFFFFF) != eff else ""
                # flag-typed fields: MOBJ flags are per-map REGION-B scene bits.
                # The most useful resolution is WITHIN the map: list the other
                # placed entities sharing this id (a boss barrier's flag is set
                # by the encounter carrying the same id; a switch's flag opens
                # the door band wired to it).
                # type-0 ore spawns: resolve f10 to its MapOre_Rate config
                if tid == 0 and fi == 10:
                    ot = self._ore_config_text(eff)
                    if ot:
                        extra += "  -> " + ot
                if "flag" in mean.lower() and eff not in (0, 0xFFFF):
                    fl = mobj_params.flag_label(eff)
                    if fl:
                        extra += f"  = {fl}"
                    shared = []
                    for oi, oo in enumerate(self.objs):
                        if oi == self._edit_idx:
                            continue
                        orec = self.map.mobj_records()[oi]
                        otid = orec[0] & 0xFFFF
                        for pf, ps, pm in mobj_params.params_for(otid):
                            if pf == 13 and "flag" in pm.lower()                                     and (orec[13] & 0xFFFF) == eff:
                                shared.append(
                                    f"#{oi} {mobj_types.mobj_display_name(otid) or otid}")
                                break
                    if shared:
                        extra += "  · shared with " + ", ".join(shared[:4])
                lines.append(f"   f{fi} [{SZ[sz]}] = {eff}   ({mean}){extra}")
            if not rows:
                lines.append("   (position + type only — no tunable per-instance params)")
            text = "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            text = f"(parameter legend unavailable: {e})"
        pl.configure(state="normal")
        pl.delete("1.0", "end")
        pl.insert("end", text)
        pl.configure(state="disabled")

    def _open_flag_reference(self):
        """Searchable emdeb (REGION-A) GameFlag reference: name/jp/id filter over
        ~1800 FLG_/REG_ variables. NOTE: MOBJ f13 ids are NOT these — they are
        per-map REGION-B scene bits (abs 4096+id, set by scripts / boss defeats /
        switches); for those, use the parameter legend's 'shared with' cross-ref
        to see which entities in the map are wired to the same bit. This dialog
        is for the region-A ids used by scripts and GameFlags_ReadField."""
        t = mobj_params._emflag_table()
        if not t:
            messagebox.showinfo("Flag reference",
                                "emdeb.bin not found — the named-flag table is unavailable.")
            return
        # MapEditorPanel is a plain builder object, not a Tk widget — parent the
        # dialog on the frame it builds into (playtest crash: 'no attribute tk').
        win = tk.Toplevel(self.parent)
        win.title("GameFlag reference (emdeb)")
        win.geometry("560x480")
        q = tk.StringVar()
        row = ttk.Frame(win); row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="Filter:").pack(side="left")
        ent = ttk.Entry(row, textvariable=q); ent.pack(side="left", fill="x", expand=True, padx=4)
        hint = ttk.Label(
            win, justify="left", font=("Segoe UI", 8), foreground="#888",
            text=("These ids are ABSOLUTE GameFlags bit ids - what GameFlags_ReadField and the\n"
                  "em.bin condition system look up directly (one bit buffer: 0..3016 = these named\n"
                  "flags, 4096..6655 = unnamed per-map scene bits). Conversions for other consumers:\n"
                  "  MOBJ f13                 = absolute - 4096   (scene bits only; no named flags)\n"
                  "  MC script op 443/445 arg = absolute - 4096\n"
                  "  MC script op 318 arg     = absolute - 4096 - 1007\n"
                  "em ENTRY/QUERY ids in condition scripts are separate index spaces, not bit ids.\n"
                  "Double-click a row to copy its absolute id."))
        hint.pack(anchor="w", padx=8)
        lb = tk.Listbox(win, font=("Consolas", 9))
        sb = ttk.Scrollbar(win, orient="vertical", command=lb.yview)
        lb.config(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        sb.pack(side="right", fill="y", pady=4)
        rows = [(v.bit_offset, v.name, v.bit_width, v.jp_name or "") for v in t.variables]

        def refill(*_a):
            needle = q.get().strip().lower()
            lb.delete(0, "end")
            for off, name, w, jp in rows:
                if needle and needle not in name.lower() and needle not in jp.lower() \
                        and needle != str(off):
                    continue
                tag = f"[w{w}]" if w > 1 else ""
                lb.insert("end", f"{off:5}  {name} {tag}  {jp}")

        def copy_id(_e):
            s = lb.curselection()
            if not s:
                return
            fid = lb.get(s[0]).split()[0]
            win.clipboard_clear(); win.clipboard_append(fid)
            hint.config(text=f"copied bit id {fid} — paste it into a flag field (e.g. f13)")

        q.trace_add("write", refill)
        lb.bind("<Double-Button-1>", copy_id)
        refill()
        ent.focus_set()

    def _apply_entity(self, silent=False):
        """Commit the 16 field entries to the selected record. Called automatically
        when a field loses focus / Enter is pressed (silent=True): a no-op or an
        incomplete/garbage edit is ignored quietly so partial typing never errors."""
        if self._edit_idx is None:
            if not silent:
                messagebox.showinfo("No entity", "Select an entity first.")
            return
        idx = self._edit_idx
        try:
            rec = [int(v.get().strip(), 0) for v in self.ent_fields]
        except (ValueError, AttributeError):
            return  # mid-edit / blank field — wait for a valid value
        if rec == list(self.map.mobj_records()[idx]):
            return  # unchanged — avoid snapshot/redraw churn on every focus-out
        self._snapshot()
        try:
            self.map.set_mobj_record(idx, rec)
        except Exception as e:
            if not silent:
                messagebox.showerror("Apply failed", str(e))
            return
        self._changed()
        self.set_status(f"Applied entity #{idx} — Save…")

    # ---- properties tab -------------------------------------------------- #
    def _refresh_props(self):
        def first(tag, signed=True):
            vals = self.map.get_ints(tag, signed=signed)
            return vals[0] if vals else None
        msea = first("MSEA")
        self.prop_vars["msea"].set("" if msea is None else str(msea))
        mgrp = first("MGRP", signed=False)
        self.prop_vars["mgrp"].set("" if mgrp is None else "0x%X" % mgrp)
        for i, col in enumerate(self.map.mlig_colors()):
            self.prop_vars[f"mlig{i}"].set("" if col is None else "%d,%d,%d" % col)
        mt = first("MTXN", signed=False)
        self.prop_vars["mtxn"].set("" if mt is None else str(mt))
        if hasattr(self, "mtxn_layers"):
            n = len(self.map.find(b"MTXN"))
            what = {0: "NO ground drawn", 1: "ground only", 2: "ground + overlay"}.get(
                n, f"{n} (only 2 are used)")
            self.mtxn_layers.config(text=f"display layers: {n} MTXN chunk(s) → {what}")

    @staticmethod
    def _parse_rgb(text):
        """'r,g,b' (or 'r g b') -> (r, g, b); blank -> None (engine default)."""
        s = text.strip().replace(";", ",").replace(" ", ",")
        if not s:
            return None
        parts = [p for p in s.split(",") if p != ""]
        if len(parts) != 3:
            raise ValueError(f"tint needs three numbers r,g,b (got {text!r})")
        vals = [int(p, 0) for p in parts]
        if any(not 0 <= v <= 255 for v in vals):
            raise ValueError(f"tint channels must be 0..255 (got {text!r})")
        return tuple(vals)

    def _apply_props(self):
        """Commit the Props tab. Only fields whose value differs from the map are written
        (Apply used to rewrite MLIG every time, which silently ADDED an MLIG chunk to maps
        without one), a half-applied edit is rolled back on a bad value, and an undo step
        is recorded only when the bytes changed."""
        before = self.map.build()

        def cur(tag, signed=True):
            vals = self.map.get_ints(tag, signed=signed)
            return vals[0] if vals else None
        try:
            s = self.prop_vars["msea"].get().strip()
            if s != "" and int(s, 0) != cur("MSEA"):
                self.map.set_ints("MSEA", [int(s, 0)])
            s = self.prop_vars["mgrp"].get().strip()
            if s != "" and int(s, 0) != cur("MGRP", signed=False):
                self.map.set_ints("MGRP", [int(s, 0)], signed=False)
            # MTXN: one u32 per chunk, never read by the game; only the first chunk's
            # value is exposed (set_ints touches only the first chunk).
            mt = self.prop_vars["mtxn"].get().strip()
            if mt != "" and int(mt, 0) != cur("MTXN", signed=False):
                self.map.set_ints("MTXN", [int(mt, 0)], signed=False)
            cols = [self._parse_rgb(self.prop_vars[f"mlig{i}"].get()) for i in range(3)]
            if cols != self.map.mlig_colors():
                self.map.set_mlig_colors(cols)
        except (ValueError, OverflowError, rf4m.Rf4mError) as e:
            self._rollback(before)
            messagebox.showerror("Bad value", str(e)); return
        if not self._commit(before):
            self.set_status("Map properties unchanged.")
            return
        if self.on_change:
            self.on_change(self.map.build())
        self._refresh_props()
        self._fill_info()
        self.set_status("Applied map properties — Save…")

    # ---- warps tab ------------------------------------------------------- #
    def _refresh_warps(self):
        self.warp_list.delete(0, "end")
        for j, rec in enumerate(self.map.mapj_records()):
            dest_name = self._roomsById.get(rec[5])
            tail = f"map {rec[5]} ({dest_name})" if dest_name else f"map {rec[5]}"
            if rec[8]:
                tail += f" face {rec[8]}°"
            if rec[0] != -1:
                tail += f" [off while flag {rec[0]}]"
            self.warp_list.insert("end", f"warp {j}: zone ({rec[1]>>3},{rec[2]>>3}) "
                                          f"{rec[3]>>3}x{rec[4]>>3} -> {tail}")

    def _warp_set_fields(self, rec):
        """Populate the Warps-tab entry fields from a MAPJ record."""
        for key, idx in (("flag", 0), ("x", 1), ("y", 2), ("w", 3), ("h", 4),
                         ("dx", 6), ("dy", 7), ("u8", 8)):
            self.warp_vars[key].set(str(rec[idx]))
        # dest-map: show "id - name" if known, else just the id (handles modder-
        # custom map ids that aren't in rf4s_rooms.csv).
        self.warp_vars["dm"].set(self._format_map_choice(rec[5])
                                 if rec[5] in self._roomsById else str(rec[5]))

    def _warp_selected(self):
        s = self.warp_list.curselection()
        if not s:
            return
        self._sel_warp = s[0]
        self._select("warp", s[0])          # sole selection: clears MOBJ / SI
        self._warp_set_fields(self.map.mapj_records()[s[0]])
        self._redraw()                      # show the cyan outline + grab handles

    def _warp_goto(self, wi):
        """Ctrl+click navigation: open the map this warp leads to (rec[5] = dest map id)."""
        recs = self.map.mapj_records()
        if wi >= len(recs):
            return
        dest = recs[wi][5]
        name = self._roomsById.get(dest)
        if not name:
            self.set_status(f"warp → map id {dest} (no known .rf4m for it)")
            return
        # Loading rebuilds/destroys THIS panel — unsafe to do from inside its own click
        # handler, so defer to the next idle tick (after this event finishes).
        nav = self.on_navigate or self._navigate_local
        if not self.confirm_discard(f"open {name}"):
            return
        self.set_status(f"→ {name}")

        def _do(n=name):
            try:
                nav(n)
            except Exception as ex:  # noqa: BLE001 - surface the failure instead of a silent trace
                self.set_status(f"navigate to {n} failed: {ex}")
        self.canvas.after_idle(_do)

    def _navigate_local(self, name):
        """Fallback navigation with no host callback: load {name}.rf4m from EXTRACTED directly."""
        hit = find_extracted(f"{name}.rf4m")
        hits = [hit] if hit else []
        if not hits:
            self.set_status(f"{name}.rf4m not found under {EXTRACTED}")
            return
        try:
            m = rf4m.Rf4mMap.load(hits[0])
        except Exception as ex:  # noqa: BLE001 - report a load failure without crashing
            self.set_status(f"load failed: {ex}")
            return
        d = hits[0].parent
        self.tex_reader = lambda fn, d=d: (d / fn).read_bytes() if (d / fn).is_file() else None
        self.set_map(m, name)
        self.set_status(f"→ {name}")

    def _warp_apply(self):
        s = self.warp_list.curselection()
        if not s:
            return
        before = self.map.build()
        try:
            rec = list(self.map.mapj_records()[s[0]])
            for key, idx in (("flag", 0), ("x", 1), ("y", 2), ("w", 3), ("h", 4),
                             ("dx", 6), ("dy", 7), ("u8", 8)):
                rec[idx] = int(self.warp_vars[key].get(), 0)
            # dest map: accept either a combobox choice ("31 - MAP_CITY_…") or a
            # bare id (decimal or 0x hex).
            dm = self._parse_map_choice(self.warp_vars["dm"].get())
            if dm is None:
                raise ValueError("dest map: pick from the dropdown or enter a numeric id")
            rec[5] = dm
            self.map.set_mapj_record(s[0], rec)
        except Exception as e:
            self._rollback(before)
            messagebox.showerror("Apply failed", str(e)); return
        if not self._commit(before):
            self.set_status(f"Warp #{s[0]} unchanged.")
            return
        self._refresh_warps(); self._redraw()
        if self.on_change:
            self.on_change(self.map.build())
        self.set_status(f"Applied warp #{s[0]} — Save…")

    def _warp_add(self):
        self._snapshot()
        # Default: always-on 4x4-tile zone at tile (1,1) that warps to THIS map (so a
        # half-edited warp never sends the player somewhere random), arriving at
        # tile (2,2), facing kept.
        here = self.rooms.get(self.map_base, (0, None))[0]
        idx = self.map.add_mapj_record([-1, 8, 8, 32, 32, here, 20, 20, 0])
        self._refresh_warps(); self._redraw()
        if self.on_change:
            self.on_change(self.map.build())
        self.warp_list.selection_set(idx); self._warp_selected()
        self.set_status(f"Added warp #{idx} — edit fields + Save…")

    def _warp_delete(self):
        s = self.warp_list.curselection()
        if not s:
            return
        self._snapshot()
        self.map.delete_mapj_record(s[0])
        self._refresh_warps(); self._redraw()
        if self.on_change:
            self.on_change(self.map.build())
        self.set_status("Deleted warp — Save…")

    def _warp_under(self, e):
        t = self._click_tile(e)
        if not t:
            return None
        for j, (x0, y0, x1, y1) in enumerate(self._mapj_rects()):
            if x0 <= t[0] <= max(x1, x0) and y0 <= t[1] <= max(y1, y0):
                return j
        return None

    def _warp_handle_at(self, e):
        """Resize-handle mode ('nw'/'n'/'ne'/'w'/'e'/'sw'/'s'/'se') under the cursor, or None."""
        if not self._warp_handles:
            return None
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        hit = max(7, self.cellpx)
        best, bestd = None, hit * hit
        for mode, (hx, hy) in self._warp_handles.items():
            d = (x - hx) ** 2 + (y - hy) ** 2
            if d <= bestd:
                bestd, best = d, mode
        return best

    def _click_edge(self, e):
        """Tile-boundary coordinate under the cursor in 0..W / 0..H (for warp resize)."""
        if not self.grid:
            return None
        cp = self.cellpx
        w, h, _ = self.grid
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        return (max(0, min(w, round(cx / cp))), max(0, min(h, round(cy / cp))))

    def _warp_drag_to(self, e):
        """Apply a warp move/resize drag to the active warp.

        Works in SUB-UNITS on the original record: a move shifts the zone by whole tiles
        but keeps its exact sub-tile offset and size, and a resize moves only the dragged
        edge(s) onto the tile boundary under the cursor. Nothing happens (no undo step,
        no rewrite) until the pointer actually crosses a tile / edge -- previously a plain
        click re-snapped the whole zone to tiles, e.g. (278,132,63,63) -> (272,128,56,56)."""
        if not (self.grid and self._warp_drag):
            return
        widx, mode, anchor, orig = self._warp_drag
        W, H, _ = self.grid
        Ws, Hs = W * 8, H * 8
        ox, oy, ow, oh = orig
        if mode == "move":
            ct = self._click_tile(e)
            if not ct or anchor is None:
                return
            dx, dy = (ct[0] - anchor[0]) * 8, (ct[1] - anchor[1]) * 8
            # keep it inside the grid, but never pull a zone that already sits partly
            # outside (edge warps) further than where it started
            nx = max(min(0, ox), min(max(Ws - ow, ox), ox + dx))
            ny = max(min(0, oy), min(max(Hs - oh, oy), oy + dy))
            nw, nh = ow, oh
        else:
            ce = self._click_edge(e)
            if not ce:
                return
            ex, ey = ce[0] * 8, ce[1] * 8
            x0, y0, x1, y1 = ox, oy, ox + ow, oy + oh
            if "w" in mode:
                x0 = max(min(0, ox), min(ex, x1 - 8))
            if "e" in mode:
                x1 = min(max(Ws, ox + ow), max(ex, x0 + 8))
            if "n" in mode:
                y0 = max(min(0, oy), min(ey, y1 - 8))
            if "s" in mode:
                y1 = min(max(Hs, oy + oh), max(ey, y0 + 8))
            nx, ny, nw, nh = x0, y0, x1 - x0, y1 - y0
        rec = list(self.map.mapj_records()[widx])
        if [nx, ny, nw, nh] == rec[1:5]:
            return                       # still a click (or no net change): leave it alone
        if not self._warp_started:
            self._snapshot(); self._warp_started = True
        rec[1], rec[2], rec[3], rec[4] = nx, ny, nw, nh
        self.map.set_mapj_record(widx, rec)
        self._warp_set_fields(rec)
        self._changed()

    # ---- search-item spots tab (SI_*.bin editing) ----------------------- #
    def _build_tab_si(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Search items")
        self.si_status = ttk.Label(f, text="", font=("Segoe UI", 8), foreground="#aab",
                                   wraplength=270, justify="left")
        self.si_status.pack(fill="x", padx=4, pady=(4, 2))
        sl = ttk.Frame(f); sl.pack(fill="x", padx=4)
        self.si_list = tk.Listbox(sl, height=5, exportselection=False)
        self.si_list.pack(side="left", fill="x", expand=True)
        self.si_list.bind("<<ListboxSelect>>", lambda _e: self._si_select())
        sbar = ttk.Scrollbar(sl, command=self.si_list.yview); sbar.pack(side="right", fill="y")
        self.si_list.config(yscrollcommand=sbar.set)
        sb = ttk.Frame(f); sb.pack(fill="x", padx=4, pady=2)
        ttk.Button(sb, text="Add spot", command=self._si_add_spot).pack(side="left", padx=2)
        ttk.Button(sb, text="Delete spot", command=self._si_del_spot).pack(side="left", padx=2)
        pf = ttk.Frame(f); pf.pack(fill="x", padx=4, pady=2)
        ttk.Label(pf, text="pos (sub-units; ÷8 = tile):", font=("Segoe UI", 7)).grid(
            row=0, column=0, columnspan=5, sticky="w")
        self.si_x = tk.StringVar(); self.si_y = tk.StringVar()
        ttk.Label(pf, text="x").grid(row=1, column=0)
        ttk.Entry(pf, textvariable=self.si_x, width=7).grid(row=1, column=1)
        ttk.Label(pf, text="y").grid(row=1, column=2)
        ttk.Entry(pf, textvariable=self.si_y, width=7).grid(row=1, column=3)
        ttk.Button(pf, text="Apply pos", command=self._si_apply_pos).grid(row=1, column=4, padx=4)
        ttk.Label(f, text="drop pool (item id : weight):", font=("Segoe UI", 7)).pack(
            anchor="w", padx=4, pady=(6, 0))
        self.si_pool = tk.Listbox(f, height=6, exportselection=False)
        self.si_pool.pack(fill="x", padx=4)
        self.si_pool.bind("<<ListboxSelect>>", lambda _e: self._si_pool_select())
        ef = ttk.Frame(f); ef.pack(fill="x", padx=4, pady=2)
        self.si_item = tk.StringVar(); self.si_wt = tk.StringVar()
        ttk.Label(ef, text="item").grid(row=0, column=0)
        e1 = ttk.Entry(ef, textvariable=self.si_item, width=7); e1.grid(row=0, column=1)
        e1.bind("<KeyRelease>", lambda _e: self._si_item_name())
        ttk.Label(ef, text="weight").grid(row=0, column=2)
        ttk.Entry(ef, textvariable=self.si_wt, width=5).grid(row=0, column=3)
        self.si_itemname = ttk.Label(ef, text="", font=("Segoe UI", 7), foreground="steelblue",
                                     width=40, anchor="w")
        self.si_itemname.grid(row=1, column=0, columnspan=4, sticky="w")
        pb = ttk.Frame(f); pb.pack(fill="x", padx=4, pady=2)
        ttk.Button(pb, text="Apply item", command=self._si_pool_apply).pack(side="left", padx=2)
        ttk.Button(pb, text="Add item", command=self._si_pool_add).pack(side="left", padx=2)
        ttk.Button(pb, text="Remove item", command=self._si_pool_del).pack(side="left", padx=2)
        ttk.Button(f, text="Save SI file…", command=self._si_save).pack(padx=4, pady=(6, 2))
        ttk.Label(f, justify="left", foreground="#888", font=("Segoe UI", 7),
                  text="Daily ground-pickup spots (≤2 spawn/day, deterministic; sleep rerolls).\n"
                       "item = entry & 0x7FF, weight = byte (pool sum wraps at 256). Click a spot\n"
                       "marker on the map to select; drag to move. Save writes a loose SI_*.bin\n"
                       "(overrides the bundle). Stock files share one pool across spots; editing\n"
                       "here splits them — that's fine.").pack(fill="x", padx=4, pady=(0, 4))

    def _si_item_name(self):
        try:
            iid = int(self.si_item.get(), 0) & 0x7FF
        except ValueError:
            self.si_itemname.config(text=""); return
        self.si_itemname.config(text=load_item_name_cache().get(iid, "?"))

    def _si_refresh_list(self):
        if not hasattr(self, "si_list"):
            return
        self.si_list.delete(0, "end")
        for d in self._si_spots:
            self.si_list.insert("end", f"spot {d['idx']}: tile ({d['tile_x']},{d['tile_y']}) — "
                                       f"{len(d['pool'])} item(s)")
        if self._si_file is None:
            self.si_status.config(text="No SI file for this map. 'Add spot' starts one.")
        else:
            nm = self._si_path.name if self._si_path else "SI_*.bin"
            self.si_status.config(text=f"{nm}: {len(self._si_file.spots)} spot(s)")

    def _si_select(self):
        s = self.si_list.curselection()
        if s:
            self._select("si")              # sole selection: clears MOBJ / warp
            self._si_sel = s[0]
            self.si_list.selection_set(s[0])
            self._si_show_selected()
            self._redraw()

    def _si_show_selected(self):
        self.si_pool.delete(0, "end")
        if (self._si_file is None or self._si_sel is None
                or self._si_sel >= len(self._si_file.spots)):
            self.si_x.set(""); self.si_y.set(""); return
        sp = self._si_file.spots[self._si_sel]
        self.si_x.set(str(sp.x)); self.si_y.set(str(sp.y))
        names = load_item_name_cache()
        for e in sp.pool.entries:
            iid = e.effective_item_id
            self.si_pool.insert("end", f"{iid}  {names.get(iid, '?')}  (w{e.effective_weight})")

    def _si_after_edit(self):
        if self._si_sel is not None:
            self._select("si")          # the edited SI spot is now the sole selection
        self._si_spots = self._si_dicts()
        self._si_refresh_list()
        if self._si_sel is not None and self._si_sel < self.si_list.size():
            self.si_list.selection_clear(0, "end")
            self.si_list.selection_set(self._si_sel); self.si_list.see(self._si_sel)
        self._si_show_selected()
        self._redraw(); self._fill_info()
        self.set_status("SI edited — 'Save SI file…' to persist")

    def _si_apply_pos(self):
        if self._si_file is None or self._si_sel is None:
            return
        try:
            x = int(self.si_x.get(), 0) & 0xFFFF
            y = int(self.si_y.get(), 0) & 0xFFFF
        except ValueError:
            return
        self._si_file.spots[self._si_sel].x = x
        self._si_file.spots[self._si_sel].y = y
        self._si_after_edit()

    def _si_add_spot(self):
        if self._si_file is None:
            self._si_file = search_items.SearchItemFile()
        W, H = (self.grid[0], self.grid[1]) if self.grid else (8, 8)
        sp = search_items.SearchSpot(x=((W // 2) << 3) + 4, y=((H // 2) << 3) + 4,
                                     pool=search_items.DropPool(entries=[]))
        self._si_file.spots.append(sp)
        self._si_sel = len(self._si_file.spots) - 1
        self._si_after_edit()
        self.set_status(f"Added SI spot #{self._si_sel} — edit + Save SI file…")

    def _si_del_spot(self):
        if self._si_file is None or self._si_sel is None:
            return
        del self._si_file.spots[self._si_sel]
        self._si_sel = None
        self._si_after_edit()
        self.set_status("Deleted SI spot — Save SI file…")

    def _si_pool_select(self):
        s = self.si_pool.curselection()
        if s and self._si_file is not None and self._si_sel is not None:
            e = self._si_file.spots[self._si_sel].pool.entries[s[0]]
            self.si_item.set(str(e.effective_item_id)); self.si_wt.set(str(e.effective_weight))
            self._si_item_name()

    def _si_pool_apply(self):
        s = self.si_pool.curselection()
        if not (s and self._si_file is not None and self._si_sel is not None):
            return
        try:
            iid = int(self.si_item.get(), 0) & 0x7FF
            wt = int(self.si_wt.get(), 0) & 0xFF
        except ValueError:
            return
        e = self._si_file.spots[self._si_sel].pool.entries[s[0]]
        e.item_id, e.weight = iid, wt
        sel = s[0]
        self._si_after_edit()
        if sel < self.si_pool.size():
            self.si_pool.selection_set(sel)

    def _si_pool_add(self):
        if self._si_file is None or self._si_sel is None:
            self.set_status("Select a spot first."); return
        try:
            iid = int(self.si_item.get(), 0) & 0x7FF
            wt = (int(self.si_wt.get(), 0) & 0xFF) or 1
        except ValueError:
            iid, wt = 0, 1
        self._si_file.spots[self._si_sel].pool.entries.append(
            search_items.DropEntry(item_id=iid, weight=wt))
        self._si_after_edit()

    def _si_pool_del(self):
        s = self.si_pool.curselection()
        if s and self._si_file is not None and self._si_sel is not None:
            del self._si_file.spots[self._si_sel].pool.entries[s[0]]
            self._si_after_edit()

    def _si_save(self):
        """Save the search-item spots through a Save dialog, like the map and Gen saves.
        It used to write silently over the loaded SI_*.bin -- the game's own extracted
        file, which seasonal variants share and other tools read as the vanilla copy.
        Returns True when a file was written."""
        if self._si_file is None:
            messagebox.showinfo("Save SI", "No search-item spots to save."); return False
        base = re.sub(r"_(SUMMER|AUTUMN|WINTER)$", "", self.map_base or "MAP", flags=re.I)
        m = re.match(r"^MAP_(.+)$", base, re.I)
        default = (self._si_path.name if self._si_path else
                   (f"SI_{m.group(1)}.bin" if m else "SI_MAP.bin"))
        p = filedialog.asksaveasfilename(defaultextension=".bin", initialfile=default,
                                         filetypes=[("SI bin", "*.bin")])
        if not p:
            return False
        try:
            self._si_file.save(pathlib.Path(p))
        except Exception as ex:
            messagebox.showerror("Save SI failed", str(ex)); return False
        self._si_saved = self._si_file.build()
        self.set_status(f"Saved {p}")
        return True

    # ---- gates / encounters tab (edits the map's Gen*.bin, a SEPARATE file) --- #
    def _build_tab_gates(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Gates")
        self.gen_status = ttk.Label(f, text="", font=("Segoe UI", 8), foreground="#aab",
                                    wraplength=270, justify="left")
        self.gen_status.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(f, text="gates in this area's encounter table:",
                  font=("Segoe UI", 7)).pack(anchor="w", padx=4)
        gl = ttk.Frame(f); gl.pack(fill="x", padx=4)
        self.gen_gate_list = tk.Listbox(gl, height=6, exportselection=False)
        self.gen_gate_list.pack(side="left", fill="x", expand=True)
        self.gen_gate_list.bind("<<ListboxSelect>>", lambda _e: self._gen_gate_select())
        gs = ttk.Scrollbar(gl, command=self.gen_gate_list.yview); gs.pack(side="right", fill="y")
        self.gen_gate_list.config(yscrollcommand=gs.set)
        gf2 = ttk.Frame(f); gf2.pack(fill="x", padx=4, pady=2)
        self.gen_kind = tk.StringVar(); self.gen_weight = tk.StringVar()
        ttk.Label(gf2, text="gate kind").grid(row=0, column=0)
        ge = ttk.Entry(gf2, textvariable=self.gen_kind, width=7); ge.grid(row=0, column=1)
        ge.bind("<KeyRelease>", lambda _e: self._gen_kind_name())
        ttk.Label(gf2, text="weight").grid(row=0, column=2)
        ttk.Entry(gf2, textvariable=self.gen_weight, width=5).grid(row=0, column=3)
        ttk.Button(gf2, text="Apply gate", command=self._gen_apply_gate).grid(row=0, column=4, padx=4)
        self.gen_kindname = ttk.Label(gf2, text="", font=("Segoe UI", 7), foreground="steelblue",
                                      width=40, anchor="w")
        self.gen_kindname.grid(row=1, column=0, columnspan=5, sticky="w")
        gb = ttk.Frame(f); gb.pack(fill="x", padx=4, pady=(0, 2))
        ttk.Button(gb, text="Add gate (copy of selected)", command=self._gen_add_gate).pack(side="left", padx=2)
        ttk.Button(gb, text="Remove gate", command=self._gen_remove_gate).pack(side="left", padx=2)
        ttk.Label(f, text="monsters this gate spawns (id : level):",
                  font=("Segoe UI", 7)).pack(anchor="w", padx=4, pady=(6, 0))
        self.gen_mon_list = tk.Listbox(f, height=6, exportselection=False)
        self.gen_mon_list.pack(fill="x", padx=4)
        self.gen_mon_list.bind("<<ListboxSelect>>", lambda _e: self._gen_spawn_select())
        mf = ttk.Frame(f); mf.pack(fill="x", padx=4, pady=2)
        self.gen_mid = tk.StringVar(); self.gen_lvl = tk.StringVar()
        ttk.Label(mf, text="monster").grid(row=0, column=0)
        mcb = ttk.Combobox(mf, textvariable=self.gen_mid, width=22, values=self._monster_choices())
        mcb.grid(row=0, column=1)
        mcb.bind("<<ComboboxSelected>>", lambda _e: self._gen_monster_name())
        mcb.bind("<KeyRelease>", lambda _e: self._gen_monster_name())
        ttk.Label(mf, text="level").grid(row=0, column=2)
        ttk.Entry(mf, textvariable=self.gen_lvl, width=5).grid(row=0, column=3)
        ttk.Button(mf, text="Apply monster", command=self._gen_apply_monster).grid(row=0, column=4, padx=4)
        self.gen_monname = ttk.Label(mf, text="", font=("Segoe UI", 7), foreground="seagreen",
                                     width=40, anchor="w")
        self.gen_monname.grid(row=1, column=0, columnspan=5, sticky="w")
        mb = ttk.Frame(f); mb.pack(fill="x", padx=4, pady=(0, 2))
        ttk.Button(mb, text="Add monster", command=self._gen_add_monster).pack(side="left", padx=2)
        ttk.Button(mb, text="Remove monster", command=self._gen_remove_monster).pack(side="left", padx=2)
        ttk.Button(f, text="Save Gen file…", command=self._gen_save).pack(padx=4, pady=(6, 2))
        ttk.Label(f, justify="left", foreground="#888", font=("Segoe UI", 7),
                  text="Gates show on the map as orange ◆'G' markers (pink dots = monster spawn\n"
                       "points); toggle the 'gates' layer on the Edit tab. DRAG a 'G' with the\n"
                       "Select tool to move it, then Save below. This is the area's\n"
                       "Gen*.bin encounter table (a separate file from the .rf4m). Each\n"
                       "GATE (kind 359-390) is picked by weight; its roster lists the monsters it\n"
                       "spawns (id 48-254) at a level, each with one weight per monster spawn\n"
                       "point. Retune a gate or monster in place, add a gate (a private copy of\n"
                       "the selected one) or remove one, add/remove roster monsters, then\n"
                       "'Save Gen file…' writes a loose Gen*.bin (overrides the bundle). Gates\n"
                       "often share one roster: a monster added to one shows up in all of them."
                  ).pack(fill="x", padx=4, pady=(0, 4))

    def _actorname(self, i):
        """Monster / gate id -> name via rf4s_actor_names.json (lazy-loaded)."""
        if self._actor_name_fn is None:
            p = _refdata_path("rf4s_actor_names.json")
            try:
                self._actor_name_fn = gen.load_actor_names(p) if p.is_file() else (lambda _i: "")
            except Exception:
                self._actor_name_fn = (lambda _i: "")
        return self._actor_name_fn(i)

    def _load_gen(self, map_filename):
        """Locate + load this map's Gen*.bin encounter table (or None if the map has no
        random encounters). Populates the Gates tab. The Gen file is edited/saved
        INDEPENDENTLY of the .rf4m (it's a separate archive)."""
        self._gen = None
        self._gen_path = gen_file_for_map(map_filename)
        self._gen_gate = None
        self._gen_spawn = None
        if self._gen_path:
            try:
                self._gen = gen.GenTable.load(self._gen_path)
            except Exception:
                self._gen = None
        self._gen_saved = self._gen.build() if self._gen is not None else None
        self._gen_reload_markers()
        self._gen_refresh()

    def _gen_reload_markers(self):
        """Decode gate + monster-spawn positions for the canvas overlay (deduped by
        sub-block since a pattern's gates usually share one position table). Called on
        load and after every structural Gen edit (offsets move when blocks are added or
        removed). The in-bounds filter hides points outside this map's grid."""
        self._gate_markers = []
        self._gen_mon_pts = []
        self._gate_sel = None
        if not self._gen:
            return
        W, H = (self.grid[0], self.grid[1]) if self.grid else (0, 0)

        def _inb(tx, ty):
            return (0 <= tx < W and 0 <= ty < H) if (W and H) else True
        seen_g, seen_m = set(), set()
        for _pi, _ei, e in self._gen.all_entries():
            if id(e.gate_pos) not in seen_g:
                seen_g.add(id(e.gate_pos))
                for (ro, x, y) in self._gen.gate_positions_off(e):
                    if _inb(x >> 3, y >> 3):
                        self._gate_markers.append({"off": ro, "tx": x >> 3, "ty": y >> 3})
            if id(e.mon_pos) not in seen_m:
                seen_m.add(id(e.mon_pos))
                self._gen_mon_pts += [(x >> 3, y >> 3) for x, y in self._gen.monster_positions(e)
                                      if _inb(x >> 3, y >> 3)]

    # ---- structural Gen edits (add / remove gates and monsters) ---------- #
    def _gen_add_gate(self):
        """Append a gate that is a private copy of the selected one (same kind, weight,
        positions and roster), ready to be retuned independently."""
        if self._gen is None or self._gen_gate is None:
            self.set_status("Select a gate to clone first."); return
        pi, ei = self._gen_gate
        src = self._gen.patterns[pi][ei]
        self._gen.add_entry(pi, src.gate_kind, src.weight, clone=src, share=False)
        self._gen_reload_markers(); self._gen_refresh()
        self._gen_reselect(self.gen_gate_list.size() - 1)
        self._redraw(); self._fill_info()
        self.set_status("Added a gate (private copy of the selected one) — 'Save Gen file…'")

    def _gen_remove_gate(self):
        if self._gen is None or self._gen_gate is None:
            self.set_status("Select a gate first."); return
        pi, ei = self._gen_gate
        if len(self._gen.patterns[pi]) == 1 and not messagebox.askyesno(
                "Remove gate", "This is the last gate: the area would spawn nothing. Remove it?"):
            return
        self._gen.remove_entry(pi, ei)
        self._gen_gate = None; self._gen_spawn = None
        self._gen_reload_markers(); self._gen_refresh(); self._redraw(); self._fill_info()
        self.set_status("Removed gate — 'Save Gen file…'")

    def _gen_add_monster(self):
        """Add the monster/level typed in the fields to the selected gate's roster (one
        weight of 10 per monster position, like the stock files)."""
        e = self._gen_selected_entry()
        if e is None:
            self.set_status("Select a gate first."); return
        try:
            mid = self._gen_monster_id() & 0xFFFF
        except (ValueError, IndexError):
            mid = 48
        try:
            lvl = int(self.gen_lvl.get(), 0) & 0xFFFF
        except ValueError:
            lvl = 1
        shared = sum(1 for _p, _e, o in self._gen.all_entries() if o.roster is e.roster) > 1
        self._gen.add_spawn(e, mid, lvl)
        gsel = self.gen_gate_list.curselection()
        self._gen_refresh(); self._gen_reselect(gsel[0] if gsel else None, len(e.spawns) - 1)
        self._fill_info()
        self.set_status(f"Added monster {mid} lv{lvl}"
                        + (" (this roster is shared with other gates)" if shared else "")
                        + " — 'Save Gen file…'")

    def _gen_remove_monster(self):
        e = self._gen_selected_entry()
        if e is None or self._gen_spawn is None:
            self.set_status("Select a monster first."); return
        self._gen.remove_spawn(e, self._gen_spawn)
        gsel = self.gen_gate_list.curselection()
        self._gen_spawn = None
        self._gen_refresh(); self._gen_reselect(gsel[0] if gsel else None); self._fill_info()
        self.set_status("Removed monster — 'Save Gen file…'")

    def _gen_gates(self):
        """Flat [(pattern_i, entry_i, Entry), ...] backing the gate listbox (stable order)."""
        return list(self._gen.all_entries()) if self._gen else []

    def _gen_refresh(self):
        if not hasattr(self, "gen_gate_list"):
            return
        self.gen_gate_list.delete(0, "end")
        self.gen_mon_list.delete(0, "end")
        self.gen_kind.set(""); self.gen_weight.set(""); self.gen_kindname.config(text="")
        self.gen_mid.set(""); self.gen_lvl.set(""); self.gen_monname.config(text="")
        gates = self._gen_gates()
        for _pi, _ei, e in gates:
            nm = self._actorname(e.gate_kind)
            nmon = sum(1 for s in e.spawns if gen.MONSTER_LO <= s.monster_id <= gen.MONSTER_HI)
            self.gen_gate_list.insert(
                "end", f"gate {e.gate_kind}{' ' + nm if nm else ''}  w{e.weight}  — {nmon} mon")
        if self._gen is None:
            self.gen_status.config(text="No encounter table for this map "
                                        "(only dungeon / field maps have one).")
        else:
            self.gen_status.config(text=f"{self._gen_path.name}: {len(gates)} gate(s)")

    def _gen_selected_entry(self):
        if self._gen is None or self._gen_gate is None:
            return None
        pi, ei = self._gen_gate
        try:
            return self._gen.patterns[pi][ei]
        except (IndexError, TypeError):
            return None

    def _gen_gate_select(self):
        s = self.gen_gate_list.curselection()
        gates = self._gen_gates()
        if not s or s[0] >= len(gates):
            return
        pi, ei, e = gates[s[0]]
        self._gen_gate = (pi, ei)
        self._gen_spawn = None
        self.gen_kind.set(str(e.gate_kind)); self.gen_weight.set(str(e.weight))
        self._gen_kind_name()
        self._gen_show_roster(e)

    def _gen_show_roster(self, e):
        self.gen_mon_list.delete(0, "end")
        self.gen_mid.set(""); self.gen_lvl.set(""); self.gen_monname.config(text="")
        for s in e.spawns:
            nm = self._actorname(s.monster_id)
            tail = "" if gen.MONSTER_LO <= s.monster_id <= gen.MONSTER_HI else "  (non-monster slot)"
            self.gen_mon_list.insert("end", f"{s.monster_id}  {nm or '?'}  lv{s.level}  "
                                            f"w{s.weights}{tail}")

    def _gen_spawn_select(self):
        s = self.gen_mon_list.curselection()
        e = self._gen_selected_entry()
        if not s or e is None or s[0] >= len(e.spawns):
            return
        self._gen_spawn = s[0]
        sp = e.spawns[s[0]]
        nm = self._actorname(sp.monster_id)
        self.gen_mid.set(f"{sp.monster_id}  {nm}" if nm else str(sp.monster_id))
        self.gen_lvl.set(str(sp.param))
        self._gen_monster_name()

    def _gen_kind_name(self):
        try:
            self.gen_kindname.config(text=self._actorname(int(self.gen_kind.get(), 0)) or "?")
        except ValueError:
            self.gen_kindname.config(text="")

    def _monster_choices(self):
        """Dropdown values 'id  name' for the bestiary range (48..254, named ones only). The
        combobox is editable, so a raw id can still be typed for an unnamed slot."""
        out = []
        for i in range(48, 255):
            nm = self._actorname(i)
            if nm:
                out.append(f"{i}  {nm}")
        return out

    def _gen_monster_id(self):
        """Parse the selected monster id from the combobox value ('52  Goblin' -> 52)."""
        return int(self.gen_mid.get().split()[0], 0)

    def _gen_monster_name(self):
        try:
            self.gen_monname.config(text=self._actorname(self._gen_monster_id()) or "?")
        except (ValueError, IndexError):
            self.gen_monname.config(text="")

    def _gen_reselect(self, gate_idx, mon_idx=None):
        """Reselect by index after a refresh. Safe because gate/roster order is stable under
        in-place edits (no add/remove), unlike a delete which would shift indices."""
        if gate_idx is None or gate_idx >= self.gen_gate_list.size():
            return
        self.gen_gate_list.selection_clear(0, "end")
        self.gen_gate_list.selection_set(gate_idx); self.gen_gate_list.see(gate_idx)
        self._gen_gate_select()
        if mon_idx is not None and mon_idx < self.gen_mon_list.size():
            self.gen_mon_list.selection_set(mon_idx); self.gen_mon_list.see(mon_idx)
            self._gen_spawn_select()

    def _gen_apply_gate(self):
        if self._gen is None or self._gen_gate is None:
            return
        pi, ei = self._gen_gate
        try:
            kind = int(self.gen_kind.get(), 0) & 0xFFFF
            weight = int(self.gen_weight.get(), 0) & 0xFFFF
        except ValueError:
            messagebox.showerror("Bad value", "gate kind and weight must be integers"); return
        gsel = self.gen_gate_list.curselection()
        self._gen.set_gate_kind(pi, ei, kind)
        self._gen.set_weight(pi, ei, weight)
        self._gen_refresh()
        self._gen_reselect(gsel[0] if gsel else None)
        self._fill_info()
        self.set_status("Gate edited — 'Save Gen file…' to persist")

    def _gen_apply_monster(self):
        e = self._gen_selected_entry()
        if e is None or self._gen_spawn is None or self._gen_spawn >= len(e.spawns):
            return
        try:
            mid = self._gen_monster_id() & 0xFFFF
            lvl = int(self.gen_lvl.get(), 0) & 0xFFFF
        except (ValueError, IndexError):
            messagebox.showerror("Bad value", "pick a monster and enter an integer level"); return
        gsel = self.gen_gate_list.curselection()
        msel = self._gen_spawn
        self._gen.set_spawn_monster(e.spawns[msel], mid)
        self._gen.set_spawn_param(e.spawns[msel], lvl)
        self._gen_refresh()
        self._gen_reselect(gsel[0] if gsel else None, msel)
        self._fill_info()
        self.set_status("Monster edited — 'Save Gen file…' to persist")

    def _gen_save(self):
        if self._gen is None:
            messagebox.showinfo("Save Gen", "No encounter table loaded for this map."); return False
        default = self._gen_path.name if self._gen_path else "Gen.bin"
        p = filedialog.asksaveasfilename(defaultextension=".bin", initialfile=default,
                                         filetypes=[("Gen bin", "*.bin"), ("All", "*.*")])
        if not p:
            return False
        try:
            self._gen.save(pathlib.Path(p))
        except Exception as ex:
            messagebox.showerror("Save Gen failed", str(ex)); return False
        self._gen_saved = self._gen.build()
        self.set_status(f"Saved {p}")
        return True

    # ---- chunks tab (raw edit of ANY chunk) ------------------------------ #
    def _refresh_chunks(self):
        self.chunk_tree.delete(*self.chunk_tree.get_children())
        for i, c in enumerate(self.map.chunks):
            self.chunk_tree.insert("", "end", iid=str(i),
                                   values=(c.tag.decode("latin1"), len(c.payload)))
        self.chunk_hex.delete("1.0", "end")

    def _chunk_selected(self):
        s = self.chunk_tree.selection()
        if not s:
            return
        i = int(s[0])
        self.chunk_hex.delete("1.0", "end")
        self.chunk_hex.insert("end", self.map.chunks[i].payload.hex())

    def _chunk_apply(self):
        s = self.chunk_tree.selection()
        if not s:
            return
        i = int(s[0])
        try:
            payload = bytes.fromhex("".join(self.chunk_hex.get("1.0", "end").split()))
        except ValueError as ex:
            messagebox.showerror("Bad hex", str(ex)); return
        before = self.map.build()
        self.map.set_chunk_payload(i, payload)
        problem = self._unreadable_reason()
        if problem:
            self._rollback(before)
            messagebox.showerror("Chunk not applied", problem); return
        if not self._commit(before):
            self.set_status(f"Chunk #{i} unchanged.")
            return
        self._reload_after_chunk_edit()
        self.set_status(f"Applied chunk #{i} ({self.map.chunks[i].tag.decode('latin1')}) — Save…")

    def _chunk_delete(self):
        s = self.chunk_tree.selection()
        if not s:
            return
        self._snapshot()
        self.map.delete_chunk(int(s[0]))
        self._reload_after_chunk_edit()
        self.set_status("Deleted chunk — Save…")

    def _chunk_add(self):
        tag = self.new_chunk_tag.get().strip()
        if len(tag) != 4 or not tag.isascii():
            messagebox.showerror("Tag", "Chunk tag must be exactly 4 ASCII characters."); return
        self._snapshot()
        self.map.add_chunk(tag, b"")
        self._reload_after_chunk_edit()
        self.set_status(f"Added empty {tag} chunk — edit hex + Apply + Save…")

    def _unreadable_reason(self):
        """Why the current map can no longer be displayed/edited, or None. A raw chunk
        edit can truncate ATTR (every renderer and hit-test needs the grid) or leave
        MOBJ/MAPJ records short; those used to crash the editor mid-reload."""
        a = self.map.find(b"ATTR")
        if a:
            body = a[0].payload
            if len(body) < 8:
                return "ATTR must start with an 8-byte width/height header."
            w, h = struct.unpack_from("<II", body, 0)
            if w == 0 or h == 0 or len(body) != 8 + 4 * w * h:
                return (f"ATTR payload is {len(body)} bytes but its {w}x{h} header needs "
                        f"{8 + 4 * w * h}. Edit the cells, not the size -- use "
                        f"`rf4mod map resize-attr` to change the grid size.")
        try:
            self.map.decode_mobj()
            self.map.mapj_records()
        except Exception as ex:  # noqa: BLE001 - report instead of crashing the editor
            return f"the map no longer decodes: {ex}"
        return None

    def _reload_after_chunk_edit(self):
        # a raw chunk edit can touch any aspect -> re-derive everything
        self.grid = self.map.attr_grid()
        self.objs = self.map.decode_mobj()
        self._refresh_chunks(); self._refresh_warps(); self._refresh_props()
        self._fill_info(); self._redraw()
        if self.on_change:
            self.on_change(self.map.build())

    # ---- metadata -------------------------------------------------------- #
    def _fill_info(self):
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        m, name = self.map, self.map_name
        lines = [name, ""]
        if self.grid:
            lines.append(f"ATTR grid : {self.grid[0]} x {self.grid[1]} tiles")
        cats = Counter(o["category"] for o in self.objs)
        lines.append(f"MOBJ      : {len(self.objs)}  {dict(cats)}")
        lines.append(f"MAPJ      : {len(m.mapj_records())} transitions")
        lines.append("chunks    : " + m.summary())
        # Ground texture set comes from g_mapResourceTable, NOT the map name (only
        # 121/872 maps are name-matched). Flag remapped / static-backdrop maps so the
        # texture-vs-ATTR relationship is clear.
        if self.map_base:
            ts = mapground.texture_set_for(self.map_base)
            if ts and ts[1]:
                lines.append(f"ground tex: {ts[0]}  ⚠ static backdrop (does NOT align with ATTR;")
                lines.append("            procedural map — platforms are separate entities)")
            elif ts and ts[0] != self.map_base:
                lines.append(f"ground tex: {ts[0]}  (remapped from name)")
            elif ts:
                lines.append(f"ground tex: {ts[0]}")
        rk = self.map_base if self.map_base in self.rooms else name
        if rk in self.rooms:
            mid, rid = self.rooms[rk]
            lines.append(f"map id    : {mid}" + (f"   resource id: {rid}" if rid is not None else ""))
        g = m.mgrp()
        if g is not None:
            lines.append(f"MGRP      : 0x{g:X}  ({rf4m.mgrp_notes(g)})")
        nl = len(m.find(b"MTXN"))
        lines.append("layers    : %d MTXN chunk(s) -> %s" % (
            nl, {0: "NO ground drawn", 1: "ground only", 2: "ground + overlay"}.get(nl, "2 used")))
        gf = gen_file_for_map(name)
        if gf:
            try:
                g = gen.GenTable.load(gf)
                roster = ", ".join(f"{self._actorname(i) or i}" for i, _ in g.roster().most_common())
                lines += ["", f"encounters ({gf.name}):", "  " + (roster or "(none)")]
            except Exception:
                pass
        # SI sidecar summary
        if getattr(self, "_si_spots", None):
            sf = si_file_for_map(name)
            lines += ["", f"search spots ({sf.name if sf else 'SI_*.bin'}): "
                          f"{len(self._si_spots)} spot(s)"]
            for i, sp in enumerate(self._si_spots):
                drops = ", ".join(f"{e['item_name']}({e['weight']})"
                                  for e in sp["pool"][:4])
                more = "" if len(sp["pool"]) <= 4 else f", +{len(sp['pool'])-4}"
                lines.append(f"  [{i}] tile ({sp['tile_x']},{sp['tile_y']}): {drops}{more}")
        elif si_file_for_map(name):
            lines += ["", "search spots: (SI file found but empty?)"]
        self.info.insert("end", "\n".join(lines))

        # ---- entity legend (colored swatches) ----
        self.info.insert("end", "\n\nEntities (MOBJ dots):\n")
        for cat in ("forage", "actor", "object", "decoration"):
            self._legend_swatch(CAT_COLOR[cat], f" {cat}\n")
        self.info.insert("end", "  (map parameter records, types 9-19, have no\n"
                                "  position: tint colours, UV scroll, depth ... see\n"
                                "  the Entities list)\n")
        self.info.insert("end", "  every MOBJ sprite = rom:/map_obj/<name>.bntx\n"
                                "  at archive (type_id + 17542). Hover a dot for\n"
                                "  its name; monsters spawn from the encounter\n"
                                "  table (the Gate), not MOBJ.\n")
        # ---- per-type breakdown: which actual objects are placed ----
        named = Counter(mobj_types.mobj_display_name(o["type_id"] & 0xFFFF)
                        or f"type {o['type_id']} ({o['category']})"
                        for o in self.objs)
        if named:
            self.info.insert("end", "\nPlaced map_obj sprites:\n")
            for nm, c in named.most_common():
                self.info.insert("end", f"  {c:>3} x {nm}\n")

        # ---- ATTR value legend ----
        if self.grid:
            cells = self.grid[2]
            cnt = Counter(cells)
            top = cnt.most_common(1)[0][0] if cnt else None
            self.info.insert("end", "\nATTR values (collision mask 0x1018F):\n")
            for v, c in cnt.most_common(16):
                rgb = self._value_colors.get(v, ATTR_FLOOR)
                self._legend_swatch("#%02x%02x%02x" % rgb,
                                    f" 0x{v:X} ({c}){self._attr_bits(v)}"
                                    f"{'  «most common»' if v == top else ''}\n")
        self.info.configure(state="disabled")

    @staticmethod
    def _attr_bits(v):
        return "  [" + attr_notes(v) + "]"

    def _legend_swatch(self, color, label):
        """Insert a colored square + label into the info Text widget."""
        tag = "sw_" + color.lstrip("#")
        self.info.tag_configure(tag, background=color)
        self.info.insert("end", "  ")
        self.info.insert("end", "  ", tag)
        self.info.insert("end", label)

    # ---- export / save --------------------------------------------------- #
    @staticmethod
    def _pil_font(size):
        """Best-effort font for PNG export text (canvas uses Segoe UI)."""
        from PIL import ImageFont
        try:
            return ImageFont.truetype("segoeui.ttf", size)
        except Exception:
            try:
                return ImageFont.load_default(size)      # Pillow >= 10.1
            except Exception:
                return ImageFont.load_default()

    @staticmethod
    def _pil_text(dr, xy, s, fill, font, anchor):
        """ImageDraw.text with anchor, falling back for bitmap fonts (no anchor
        support): emulate via textbbox offsets."""
        try:
            dr.text(xy, s, fill=fill, font=font, anchor=anchor)
        except (TypeError, ValueError):
            l, t, r, b = dr.textbbox((0, 0), s, font=font)
            tw, th = r - l, b - t
            x, y = xy
            if anchor[0] == "m":
                x -= tw / 2
            if anchor[1] == "m":
                y -= th / 2
            elif anchor[1] == "s":
                y -= th
            dr.text((x, y), s, fill=fill, font=font)

    @staticmethod
    def _hex_rgb(spec, default=(255, 255, 255)):
        s = spec.lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        try:
            return tuple(int(s[k:k + 2], 16) for k in (0, 2, 4))
        except ValueError:
            return default

    def render_to_image(self, scale=None):
        """WYSIWYG snapshot of the map view as a PIL image: rendered at the
        CURRENT zoom (or an explicit `scale` = cell pixels) with exactly the
        overlays that are enabled in the Layers panel -- mirrors _redraw():
        texture/ATTR fill/cell edges (via _bg_composite), grid lines, MAPJ warp
        zones, entity dots (per-category toggles, forage rides the trigger
        toggle), SI daily-pickup spots with indices, and warp destination
        labels. Selection highlights/handles are intentionally NOT exported.

        The export is RGBA and PRESERVES TRANSPARENCY: a lone texture draw-layer
        (e.g. "1 overlay") keeps its own alpha where it has no pixels, and when
        NO base layer is enabled at all (texture off + ATTR fill off) the
        overlays are drawn on a fully transparent canvas -- either way the PNG
        can be composited over an external render."""
        if not (self.grid and HAS_PIL):
            return None
        from PIL import ImageDraw
        w, h, cells = self.grid
        cp = scale or self.cellpx
        bg = self._bg_composite(w, h, cells, cp, decode=True)   # export must block for the texture
        if bg is None:                       # overlay-only export: transparent canvas
            img = Image.new("RGBA", (w * cp, h * cp), (0, 0, 0, 0))
        else:
            img = bg if bg.mode == "RGBA" else bg.convert("RGBA")
        dr = ImageDraw.Draw(img)
        if self.layer_vars["grid"].get() and cp >= 4:           # tile grid
            gcol = (42, 42, 48)
            for x in range(w + 1):
                dr.line([(x * cp, 0), (x * cp, h * cp)], fill=gcol)
            for y in range(h + 1):
                dr.line([(0, y * cp), (w * cp, y * cp)], fill=gcol)
        if self.layer_vars["mapj"].get():                       # warp trigger zones
            for x0, y0, x1, y1 in self._mapj_rects():
                dr.rectangle([x0 * cp, y0 * cp, max(x1 * cp, x0 * cp + cp), max(y1 * cp, y0 * cp + cp)],
                             outline=(255, 208, 64), width=2)
        r = max(3, cp // 2 + 1)                                 # placed entities
        for o in self.objs:
            cat = o["category"]
            toggle_key = "trigger" if cat in _TRIGGER_KINDS else cat  # forage rides the trigger toggle
            if not self.layer_vars.get(toggle_key, tk.BooleanVar(value=True)).get():
                continue
            if o["pos_x"] == 0 and o["pos_y"] == 0:
                continue
            cx, cy = (o["pos_x"] >> 3) * cp, (o["pos_y"] >> 3) * cp
            dr.ellipse([cx - r, cy - r, cx + r, cy + r],
                       fill=self._hex_rgb(CAT_COLOR.get(cat, "#fff")), outline=(0, 0, 0))
        if self.layer_vars.get("si") and self.layer_vars["si"].get():   # SI daily-pickup spots
            sr = max(5, cp // 2 + 3)
            sfont = self._pil_font(max(7, cp // 3))
            for i, sp in enumerate(self._si_spots):
                cx, cy = sp["tile_x"] * cp + cp // 2, sp["tile_y"] * cp + cp // 2
                dr.ellipse([cx - sr - 1, cy - sr - 1, cx + sr + 1, cy + sr + 1],
                           outline=(255, 255, 255), width=2)
                dr.ellipse([cx - sr, cy - sr, cx + sr, cy + sr],
                           fill=(255, 224, 0), outline=(160, 96, 0), width=2)
                self._pil_text(dr, (cx, cy), str(i), (0, 0, 0), sfont, "mm")
        if self.layer_vars.get("gates") and self.layer_vars["gates"].get():   # encounter gates
            for (tx, ty) in getattr(self, "_gen_mon_pts", []):
                cx, cy = tx * cp + cp // 2, ty * cp + cp // 2
                dr.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 90, 160), outline=(0, 0, 0))
            gr = max(6, cp // 2 + 2)
            gfont = self._pil_font(max(7, cp // 3))
            for mk in getattr(self, "_gate_markers", []):
                cx, cy = mk["tx"] * cp + cp // 2, mk["ty"] * cp + cp // 2
                dr.polygon([(cx, cy - gr), (cx + gr, cy), (cx, cy + gr), (cx - gr, cy)],
                           fill=(255, 140, 26), outline=(0, 0, 0))
                self._pil_text(dr, (cx, cy), "G", (0, 0, 0), gfont, "mm")
        if self.layer_vars.get("dest") and self.layer_vars["dest"].get():   # warp destination labels
            mapj = self.map.mapj_records()
            dfont = self._pil_font(max(7, cp // 2))
            for j, (x0, y0, x1, y1) in enumerate(self._mapj_rects()):
                if j >= len(mapj):
                    break
                name, _is_bld = map_names.describe_destination(mapj[j][5])
                if not name:
                    continue
                mx, ty = int((x0 + x1) / 2 * cp), int(y0 * cp - 2)
                self._pil_text(dr, (mx, ty), name, (255, 208, 64), dfont, "ms")
        return img

    def _export_png(self):
        img = self.render_to_image()
        if img is None:
            messagebox.showinfo("Export", "Need Pillow + an ATTR grid to export."); return
        f = filedialog.asksaveasfilename(defaultextension=".png",
                                         initialfile=(self.map_base or "map") + ".png",
                                         filetypes=[("PNG", "*.png")])
        if f:
            img.save(f); self.set_status(f"Exported {f}")

    def _save_map(self):
        """Save the .rf4m through a Save dialog. Runs the loader validation first and asks
        before writing a map with fatal findings (the game would crash, drop data or draw
        nothing). Returns True when a file was written."""
        if not self.map:
            return False
        try:
            issues = self.map.validate()
        except Exception:  # noqa: BLE001 - validation must never block a save
            issues = []
        fatal = [x for x in issues if x.startswith("ERROR")]
        if fatal and not messagebox.askyesno(
                "Map has fatal problems",
                "The game's loader would choke on this map:\n\n"
                + "\n".join("• " + x[7:] for x in fatal[:6])
                + ("\n…" if len(fatal) > 6 else "") + "\n\nSave anyway?"):
            return False
        f = filedialog.asksaveasfilename(defaultextension=".rf4m",
                                         initialfile=(self.map_base or "map") + ".rf4m",
                                         filetypes=[("rf4m", "*.rf4m")])
        if not f:
            return False
        try:
            self.map.save(f)
        except Exception as ex:  # noqa: BLE001 - e.g. permission denied: report it
            messagebox.showerror("Save failed", str(ex)); return False
        self._saved_map = self.map.build()
        self.set_status(f"Saved {f}")
        return True


# --------------------------------------------------------------------------- #
# Standalone window: map list + one embedded panel
# --------------------------------------------------------------------------- #
class MapExplorer:
    def __init__(self, root, initial=None):
        self.root = root
        root.title("RF4S Map Editor")
        root.geometry("1340x860")
        bar = ttk.Frame(root); bar.pack(fill="x")
        ttk.Button(bar, text="Open folder…", command=self._pick_dir).pack(side="left", padx=2, pady=3)
        ttk.Button(bar, text="Open .rf4m…", command=self._pick_file).pack(side="left", padx=2)
        self.status = ttk.Label(bar, text="", anchor="e"); self.status.pack(side="right", padx=8)

        from guiutil import Paned
        paned = Paned(root, orient="horizontal"); paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned); paned.add(left, weight=0, minsize=140)
        ttk.Label(left, text="Maps").pack(anchor="w", padx=4, pady=(4, 0))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refresh_list())
        ttk.Entry(left, textvariable=self.filter_var).pack(fill="x", padx=4)
        lf = ttk.Frame(left); lf.pack(fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(lf); sb.pack(side="right", fill="y")
        self.listbox = tk.Listbox(lf, yscrollcommand=sb.set, exportselection=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_pick_map)

        host = ttk.Frame(paned); paned.add(host, weight=5)
        self.panel = MapEditorPanel(host, status_fn=lambda s: self.status.config(text=s),
                                    on_navigate=self._open)   # Ctrl+click a warp -> open that map

        self._all_maps = sorted(EXTRACTED.rglob("*.rf4m"))
        self._refresh_list()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.status.config(text=f"{len(self._all_maps)} maps   "
                                f"{'Pillow' if HAS_PIL else 'no Pillow'}")
        if initial:
            self._open(initial)

    def _refresh_list(self):
        flt = self.filter_var.get().lower()
        self.listbox.delete(0, "end")
        self._listed = [p for p in self._all_maps if flt in p.stem.lower()]
        for p in self._listed:
            self.listbox.insert("end", p.stem)

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Folder of .rf4m maps",
                                    initialdir=str(EXTRACTED if EXTRACTED.is_dir() else REPO))
        if d:
            self._all_maps = sorted(pathlib.Path(d).rglob("*.rf4m")); self._refresh_list()

    def _pick_file(self):
        f = filedialog.askopenfilename(title="Open .rf4m", filetypes=[("rf4m", "*.rf4m")])
        if f:
            self._load(pathlib.Path(f))

    def _on_pick_map(self, _e):
        sel = self.listbox.curselection()
        if sel:
            self._load(self._listed[sel[0]])

    def _open(self, arg):
        p = pathlib.Path(arg)
        if p.is_file():
            self._load(p); return
        hit = find_extracted(arg if arg.endswith(".rf4m") else arg + ".rf4m")
        hits = [hit] if hit else []
        if hits:
            self._load(hits[0])

    def _on_close(self):
        if self.panel.confirm_discard("close the editor"):
            self.root.destroy()

    def _load(self, path):
        if not self.panel.confirm_discard(f"open {pathlib.Path(path).stem}"):
            return
        try:
            m = rf4m.Rf4mMap.load(path)
        except Exception as e:
            messagebox.showerror("Load failed", str(e)); return
        d = pathlib.Path(path).parent
        self.panel.tex_reader = lambda fn, d=d: (d / fn).read_bytes() if (d / fn).is_file() else None
        self.panel.set_map(m, path.stem)
        self.status.config(text=f"{path.stem}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    MapExplorer(root, initial=argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
