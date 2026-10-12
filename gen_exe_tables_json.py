#!/usr/bin/env python3
"""Generate refdata/rf4s_exe_tables.json -- the game tables that live only in RF4S.exe
(no data file carries them), extracted once so the toolkit ships them and never has to read
the exe at run time:

  chest_loot   treasure chests (MOBJ 44): RF4S.exe+0x9EFA60, 190 rows x 4 u16 slots, row =
               the chest's f8; each slot [item id (bits 0-10), 4-bit value (bits 11-14)]
  crate_pools  breakable crates (MOBJ 53): one pool of plain u16 item ids per area group
               (zone = MGRP group bit - 5; see rf4s_modkit.chestloot), a duplicate raising that
               item's odds, 0 = the crate gives nothing; DUNG_E rolls its rare pool 20 % of the
               time. 'default' covers every other zone.
  area_bgm     g_baseMapBgmByFlagBit RF4S.exe+0x4D5710: the base BGM sound id per zone (21)
  encounter_zones  g_encounterArchiveTable RF4S.exe+0x4DB1E0: per zone [first map id, first Gen
               archive id] (24 rows; [0, 0] = no monster gates in that zone). The gate spawner
               loads archive = map id - first map id + first archive (see rf4s_modkit.areagroup)

refdata/rf4s_exe_map_resources.json (build_map_resources) holds the per-map resource rows and
the warps / walls the game adds to maps at run time.

refdata/rf4s_exe_collision.json (build_collision), holds the collision
templates of the interactive objects (MOBJ types 196..335): g_mapEntityTemplates
RF4S.exe+0x4D5030, one pointer per type - 197 (type 196 uses 197's). Each template: +32 i16
depth bias, +64 u16 width, +66 u16 height (tiles), +68 / +70 i16 x / y offset (sub-units),
+72 u32 cells[width * height], the ATTR bits OR-ed into the tiles the object covers.

It also writes refdata/rf4s_exe_sidecars.json -- which per-map side files the game loads
(see build_sidecars):

  search_items  g_searchItemArchiveByMapId RF4S.exe+0x4DD260: the SI_*.bin archive id per map
               id (870 u32, 0 = the map never rolls search items; read by
               SearchItemMng_TickRollAndSpawnDailySpots RF4S.exe+0x231E80)
  gen_archives  the file names of every archive the gate spawner can load (any map id 1..869
               in any zone), from g_fileArchivePathTable RF4S.exe+0x57AD30 (256-byte UTF-16
               paths, basename kept)
  encounter_zone_overrun  the 3 u16 pairs right after the 24-row encounter table: MGRP zones
               24..26 read them (archive half 0 = no gates)
  area_bgm_overrun  the 6 u32 right after the 21-entry area BGM table: the "music" of MGRP
               zones 21..26 (only reachable with bits 26..31)

Every table records its RVA; each file records the exe it came from (size + SHA-256).
Run:  python gen_exe_tables_json.py [--exe PATH] [--out PATH] [--maps-out PATH]
      [--collision-out PATH] [--sidecars-out PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import exetables                          # noqa: E402
from rf4s_modkit.refdata import refdata_path               # noqa: E402

CHEST_RVA, CHEST_ROWS, CHEST_SLOTS = 0x9EFA60, 190, 4
# (zone or "default", label, RVA, entries, share of the rolls) -- MapEntity_SpawnTreasure
# RF4S.exe+0x14B680 switches on the zone and indexes these with a random roll
CRATE_POOLS = [
    (5, "DUNG_B", 0x4CF2A0, 35, 1.0),
    (6, "DUNG_C", 0x4CF410, 44, 1.0),
    (7, "DUNG_D", 0x4CF1B0, 96, 1.0),
    (8, "DUNG_E common", 0x4CF7F0, 51, 0.8),
    (8, "DUNG_E rare", 0x4CD878, 8, 0.2),
    (10, "DUNG_G", 0x4CF150, 44, 1.0),
    (11, "DUNG_H", 0x4CF480, 49, 1.0),
    (13, "DUNG_J", 0x4CF3B0, 47, 1.0),
    (14, "DUNG_K", 0x4BBD38, 28, 1.0),
    (15, "DUNG_L", 0x4CF8A0, 55, 1.0),
    (16, "DUNG_M", 0x4CF300, 85, 1.0),
    ("default", "default", 0x4CF270, 22, 1.0),
]
BGM_RVA, BGM_ENTRIES = 0x4D5710, 21
ENC_RVA, ENC_ROWS = 0x4DB1E0, 24
ENC_OVERRUN_ROWS = 3        # zones 24..26 (MGRP bits 29..31 alone) read past the 24 rows
BGM_OVERRUN = 6             # zones 21..26 (MGRP bits 26..31 alone) read past the 21 BGM ids
SI_RVA, SI_MAPS = 0x4DD260, 870
TOC_RVA, TOC_SLOTS, TOC_STRIDE = 0x57AD30, 18179, 256

ABOUT = ("Tables that exist only in RF4S.exe, extracted by gen_exe_tables_json.py so the "
         "toolkit never reads the exe at run time. chest_loot: treasure chests (MOBJ 44, "
         "Actor_InitFlagGatedTreasure RF4S.exe+0x14B130), row = the chest's f8, 4 slots of "
         "[item id, 4-bit value (bits 11-14, meaning not traced)], item 0 = empty slot. "
         "crate_pools: breakable crates (MOBJ 53, MapEntity_SpawnTreasure RF4S.exe+0x14B680) "
         "roll ONE item per room load from their area group's pool (zone = the lowest MGRP "
         "group bit - 5, Minimap_BuildForMap RF4S.exe+0x13B3F0); item ids, duplicates raise the "
         "odds, 0 = nothing; share = the part of the rolls a pool gets (DUNG_E: roll 0..99 < 20 "
         "-> rare). area_bgm: base BGM sound id per zone (Scene_ApplyContextualBGM). "
         "encounter_zones: per zone [first map id, first Gen archive id] "
         "(Encounter_TickMonsterSpawnSlots RF4S.exe+0x1E6240 loads archive = map id - first map "
         "+ first archive; [0, 0] = the zone spawns no monster gates).")


def build(exe):
    data = exetables.exe_bytes(exe)
    words = exetables.read("H", CHEST_RVA, CHEST_ROWS * CHEST_SLOTS, exe)
    rows = [[[w & 0x7FF, (w >> 11) & 0xF] for w in words[r * CHEST_SLOTS:(r + 1) * CHEST_SLOTS]]
            for r in range(CHEST_ROWS)]
    pools = [{"zone": z, "label": label, "rva": f"0x{rva:X}", "share": share,
              "items": list(exetables.read("H", rva, n, exe))}
             for z, label, rva, n, share in CRATE_POOLS]
    return {
        "_about": ABOUT,
        "source": {"file": "RF4S.exe", "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()},
        "chest_loot": {"rva": f"0x{CHEST_RVA:X}", "rows": rows},
        "crate_pools": pools,
        "area_bgm": {"rva": f"0x{BGM_RVA:X}",
                     "sound_ids": list(exetables.read("I", BGM_RVA, BGM_ENTRIES, exe))},
        "encounter_zones": {"rva": f"0x{ENC_RVA:X}",
                            "rows": [list(exetables.read("H", ENC_RVA + 4 * z, 2, exe))
                                     for z in range(ENC_ROWS)]},
    }


TEMPLATE_RVA, TEMPLATE_FIRST, TEMPLATE_TYPES = 0x4D5030, 197, range(196, 336)
COLLISION_ABOUT = (
    "Collision templates of the interactive objects (MOBJ types 196..335), extracted from "
    "g_mapEntityTemplates RF4S.exe+0x4D5030 by gen_exe_tables_json.py; index = max(0, type - "
    "197), so type 196 uses 197's. Map_SpawnInteractiveObject RF4S.exe+0x143760 stamps a "
    "record's template when its f11 is 0 and it is shown: Map_StampEntityCollisionTiles "
    "+0x195FC0 ORs cell (c, r) into ATTR tile ((f14 + off_x) >> 3) - w / 2 + c, ((f15 + off_y) "
    ">> 3) - h / 2 + r, columns mirrored when f6 < 0; Map_TickEntityArray +0x143FB0 removes / "
    "re-stamps it when the object's flag hides / shows it. by_type: type -> template key "
    "(types without a template are left out). templates: key (the template's RVA) -> w, h "
    "(tiles), off (sub-units), z_bias (added to the object's depth), cells (w * h, row-major).")


def build_collision(exe):
    data = exetables.exe_bytes(exe)
    pe = int.from_bytes(data[0x3C:0x40], "little")
    image_base = int.from_bytes(data[pe + 48:pe + 56], "little")
    ptrs = exetables.read("Q", TEMPLATE_RVA, max(TEMPLATE_TYPES) - TEMPLATE_FIRST + 1, exe)
    by_type, templates = {}, {}
    for t in TEMPLATE_TYPES:
        p = ptrs[max(0, t - TEMPLATE_FIRST)]
        if not p:
            continue
        rva = p - image_base
        key = f"0x{rva:X}"
        if key not in templates:
            z_bias = exetables.read("h", rva + 32, 1, exe)[0]
            w, h, ox, oy = exetables.read("h", rva + 64, 4, exe)
            w, h = w & 0xFFFF, h & 0xFFFF
            templates[key] = {"w": w, "h": h, "off": [ox, oy], "z_bias": z_bias,
                              "cells": list(exetables.read("I", rva + 72, w * h, exe))}
        by_type[str(t)] = key
    return {
        "_about": COLLISION_ABOUT,
        "source": {"file": "RF4S.exe", "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()},
        "table": {"rva": f"0x{TEMPLATE_RVA:X}", "first_type": TEMPLATE_FIRST},
        "by_type": by_type,
        "templates": templates,
    }


def dumps_collision(obj):
    """JSON with one template per line."""
    out = ["{"]
    for k in ("_about", "source", "table", "by_type"):
        out.append(f' {json.dumps(k)}: {json.dumps(obj[k])},')
    out.append(' "templates": {')
    out.append(",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in obj["templates"].items()))
    out.append(" }")
    out.append("}")
    return "\n".join(out) + "\n"


SIDECARS_ABOUT = (
    "Which per-map side files RF4S.exe loads, extracted by gen_exe_tables_json.py so the "
    "toolkit never reads the exe at run time. search_items: g_searchItemArchiveByMapId "
    "RF4S.exe+0x4DD260, the SI_*.bin archive per map id (0 = the map never rolls search "
    "items; ids >= 870 never roll), read by SearchItemMng_TickRollAndSpawnDailySpots "
    "RF4S.exe+0x231E80 with the room's BASE id; names = the archive file names from "
    "first_archive on. gen_archives: file names (basename of g_fileArchivePathTable "
    "RF4S.exe+0x57AD30) of every archive Encounter_TickMonsterSpawnSlots RF4S.exe+0x1E6240 "
    "can load (map id - first map + first archive, for any map id 1..869 in any zone), from "
    "`first` on. encounter_zone_overrun: the u16 pairs right after the 24-row "
    "g_encounterArchiveTable, read for zones 24..26 (archive half 0 = no gates). "
    "area_bgm_overrun: the u32 right after the 21-entry g_baseMapBgmByFlagBit, read by "
    "Scene_ApplyContextualBGM for zones 21..26.")


def toc_name(data, archive):
    """Basename of archive `archive`'s path in g_fileArchivePathTable ('' for an empty slot)."""
    if not 0 <= archive < TOC_SLOTS:
        return ""
    off = exetables.rva_to_offset(data, TOC_RVA + TOC_STRIDE * archive)
    s = data[off:off + TOC_STRIDE].decode("utf-16-le", "replace").split("\0", 1)[0]
    return s.rsplit("/", 1)[-1]


def build_sidecars(exe):
    """refdata/rf4s_exe_sidecars.json: the SI archive per map id and the Gen archive names."""
    data = exetables.exe_bytes(exe)
    si = list(exetables.read("I", SI_RVA, SI_MAPS, exe))
    used = [a for a in si if a]
    si_first, si_last = min(used), max(used)
    zones = [tuple(exetables.read("H", ENC_RVA + 4 * z, 2, exe)) for z in range(ENC_ROWS)]
    overrun = [list(exetables.read("H", ENC_RVA + 4 * (ENC_ROWS + z), 2, exe))
               for z in range(ENC_OVERRUN_ROWS)]
    reach = [(1 - first + arc, 869 - first + arc) for first, arc in zones if arc]
    g_first, g_last = min(a for a, _b in reach), max(b for _a, b in reach)
    return {
        "_about": SIDECARS_ABOUT,
        "source": {"file": "RF4S.exe", "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()},
        "search_items": {"rva": f"0x{SI_RVA:X}", "archives": si, "first_archive": si_first,
                         "names": [toc_name(data, a) for a in range(si_first, si_last + 1)]},
        "gen_archives": {"toc_rva": f"0x{TOC_RVA:X}", "first": g_first,
                         "names": [toc_name(data, a) for a in range(g_first, g_last + 1)]},
        "encounter_zone_overrun": {"rva": f"0x{ENC_RVA + 4 * ENC_ROWS:X}", "rows": overrun},
        "area_bgm_overrun": {"rva": f"0x{BGM_RVA + 4 * BGM_ENTRIES:X}",
                             "sound_ids": list(exetables.read("I", BGM_RVA + 4 * BGM_ENTRIES,
                                                              BGM_OVERRUN, exe))},
    }


def dumps_sidecars(obj):
    """JSON with the long lists wrapped at ~100 columns (small diffs when the exe changes)."""
    def wrapped(key, lst):
        parts, line = [], []
        for v in lst:
            line.append(json.dumps(v))
            if sum(len(x) + 2 for x in line) > 96:
                parts.append(", ".join(line))
                line = []
        if line:
            parts.append(", ".join(line))
        return f'  "{key}": [\n   ' + ",\n   ".join(parts) + "\n  ]"
    si, ga = obj["search_items"], obj["gen_archives"]
    out = ["{",
           f' "_about": {json.dumps(obj["_about"])},',
           f' "source": {json.dumps(obj["source"])},',
           f' "search_items": {{"rva": {json.dumps(si["rva"])}, '
           f'"first_archive": {si["first_archive"]},',
           wrapped("archives", si["archives"]) + ",",
           wrapped("names", si["names"]),
           " },",
           f' "gen_archives": {{"toc_rva": {json.dumps(ga["toc_rva"])}, "first": {ga["first"]},',
           wrapped("names", ga["names"]),
           " },",
           f' "encounter_zone_overrun": {json.dumps(obj["encounter_zone_overrun"])},',
           f' "area_bgm_overrun": {json.dumps(obj["area_bgm_overrun"])}',
           "}"]
    return "\n".join(out) + "\n"


def dumps(obj):
    """JSON with one table row per line (small diffs when the exe changes)."""
    out = ["{"]
    out.append(f' "_about": {json.dumps(obj["_about"])},')
    out.append(f' "source": {json.dumps(obj["source"])},')
    cl = obj["chest_loot"]
    out.append(f' "chest_loot": {{"rva": {json.dumps(cl["rva"])}, "rows": [')
    out.append(",\n".join("  " + json.dumps(r) for r in cl["rows"]))
    out.append(" ]},")
    out.append(' "crate_pools": [')
    out.append(",\n".join("  " + json.dumps(p) for p in obj["crate_pools"]))
    out.append(" ],")
    out.append(f' "area_bgm": {json.dumps(obj["area_bgm"])},')
    out.append(f' "encounter_zones": {json.dumps(obj["encounter_zones"])}')
    out.append("}")
    return "\n".join(out) + "\n"


# ---- refdata/rf4s_exe_map_resources.json -------------------------------------------------- #
# Per-map tables the map editor needs, all indexed by map id (0..871):
#   map_resources   g_mapResourceTable RF4S.exe+0x9F9D10, 4 archive ids per map: [+0] the .rf4m,
#                   [+1] ground tile 0 (layer 0), [+2] overlay tile 0 (layer 1; 0 = no overlay),
#                   [+3] over-model (0 = none). Map_SpawnEntity (RF4S.exe+0x194140) loads the
#                   MTXN chunk j = 0 layer from +1 and every j >= 1 from +2. Shipped as the file
#                   basenames from the exe's archive path table (RF4S.exe+0x57AD30, 256 B UTF-16
#                   per archive id), extension dropped.
#   map_type_attrib g_mapTypeAttribTable RF4S.exe+0x4D4290, one u32 per map id. Map_PostLoad
#                   (RF4S.exe+0x193FB0) picks the night tint default 181,214,214 instead of
#                   148,214,247 when bit 0x10 is set (indexed by the REQUESTED id, i.e. the base
#                   id of a seasonal map).
#   runtime_spawns  Map_SpawnProgressWarpsAndWalls RF4S.exe+0x144A50: warp zones
#                   (Map_SpawnRuntimeWarpZone RF4S.exe+0x144840) and blocker walls
#                   (Map_SpawnBlockerWall RF4S.exe+0x1525B0) the game adds to a map at load, gated
#                   on progress. Hand-decoded from the function's code (its immediates are
#                   spread over shared tails and register reuse, so a byte scan cannot read them);
#                   keyed by the map id the game passes (the base id of a seasonal map).
MAPRES_RVA, MAP_ROWS = 0x9F9D10, 872
MAPATTR_RVA = 0x4D4290
TOC_RVA, TOC_STRIDE = 0x57AD30, 256
SPAWNS_RVA = 0x144A50

MAPRES_ABOUT = (
    "Per-map tables that exist only in RF4S.exe, extracted by gen_exe_tables_json.py. "
    "map_resources: g_mapResourceTable (4 archive ids per map id) as file basenames: "
    "[rf4m, ground tile 0 (layer 0), overlay tile 0 (layer 1) or null, over-model or null]; "
    "Map_SpawnEntity RF4S.exe+0x194140 loads the 1st MTXN chunk's layer from the ground id and "
    "every later chunk's from the overlay id (none when it is 0). map_type_attrib: "
    "g_mapTypeAttribTable, one u32 per map id; bit 0x10 makes Map_PostLoad RF4S.exe+0x193FB0 "
    "default the night tint to 181,214,214 instead of 148,214,247. runtime_spawns: warp zones "
    "and blocker walls Map_SpawnProgressWarpsAndWalls RF4S.exe+0x144A50 adds at load, keyed by "
    "the (base) map id; boxes are [x0, y0, x1, y1] in sub-units (8 per tile), a warp's arrival "
    "[x, y] in the destination map; a wall is a pg_wall sprite (archive id for spring; on the "
    "farm +20 summer / +10 autumn / +30 winter, by the map's MGRP season) that sets the tiles "
    "of its box to blocked (0x2); 'when' says what gates it.")


def _toc_name(data, arc):
    """Basename (no extension) of archive `arc` in the exe's path table, or None for id 0."""
    if not arc:
        return None
    off = exetables.rva_to_offset(data, TOC_RVA + TOC_STRIDE * arc)
    s = data[off:off + TOC_STRIDE].decode("utf-16-le", "replace").split("\0", 1)[0]
    base = s.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0] if base else None


def _runtime_spawns():
    """{base map id: [spawn, ...]} -- the hand-decoded body of RF4S.exe+0x144A50."""
    out = {}

    def warp(m, dest, ax, ay, x0, y0, x1, y1, when=None):
        out.setdefault(m, []).append({"kind": "warp", "dest": dest, "arrive": [ax, ay],
                                      "box": [x0, y0, x1, y1], "when": when or "always"})

    def wall(m, sprite, x, y, x0, y0, x1, y1, when=None):
        out.setdefault(m, []).append({"kind": "wall", "sprite": sprite, "at": [x, y],
                                      "box": [x0, y0, x1, y1], "when": when or "always"})

    lv = "farm expansion level (packed flag 9202)"
    # the farm (4) and its four fields (8, 12, 16, 20)
    walls = {15242: (96, 48, 72, 48, 144, 64), 15243: (256, 422, 214, 408, 292, 468),
             15244: (96, 422, 44, 408, 128, 468), 15245: (422, 422, 384, 408, 458, 468),
             15246: (24, 332, 0, 320, 16, 400), 15247: (480, 300, 488, 312, 500, 392),
             15248: (28, 136, 36, 120, 40, 160), 15249: (240, 32, 214, 32, 292, 64),
             15250: (422, 48, 392, 48, 448, 64), 15251: (488, 136, 472, 120, 500, 168)}
    w = lambda m, s, when=None: wall(m, s, *walls[s], when=when)     # noqa: E731
    warp(4, 8, 452, 144, 0, 320, 20, 392, f"{lv} >= 1")
    w(4, 15246, f"{lv} < 1")
    warp(4, 12, 56, 136, 490, 320, 512, 392, f"{lv} >= 2")
    w(4, 15247, f"{lv} < 2")
    warp(4, 16, 468, 356, 0, 96, 24, 160, f"{lv} >= 3")
    w(4, 15248, f"{lv} < 3")
    warp(4, 20, 48, 352, 488, 96, 512, 180, f"{lv} >= 4")
    w(4, 15251, f"{lv} < 4")
    warp(8, 4, 48, 352, 488, 96, 512, 180)
    for s in (15246, 15247, 15248, 15243, 15244, 15245, 15249):
        w(8, s)
    wall(8, 15242, 96, 24, 72, 48, 144, 64)          # this one call places the sprite at y 24
    warp(8, 16, 424, 400, 390, 0, 440, 52, f"{lv} >= 3")
    w(8, 15250, f"{lv} < 3")
    warp(12, 4, 468, 356, 0, 96, 24, 160)
    for s in (15246, 15247, 15251, 15243, 15244, 15245, 15249, 15250):
        w(12, s)
    warp(12, 20, 92, 400, 64, 0, 120, 52, f"{lv} >= 4")
    w(12, 15242, f"{lv} < 4")
    warp(16, 4, 56, 136, 490, 320, 512, 392)
    warp(16, 8, 418, 92, 380, 424, 462, 460)
    for s in (15246, 15251, 15248, 15243, 15244, 15249, 15242, 15250):
        w(16, s)
    warp(20, 4, 452, 144, 0, 320, 20, 392)
    warp(20, 12, 94, 88, 48, 424, 132, 460)
    for s in (15251, 15248, 15247, 15243, 15245, 15249, 15242, 15250):
        w(20, s)
    # barn doors on each farm map: left barn 77 + 10f, right barn 82 + 10f
    for f, m in enumerate((4, 8, 12, 16, 20)):
        warp(m, 77 + 10 * f, 172, 290, 150, 56, 186, 86,
             f"the farm's left barn is built (packed flag {9010 + 6 * f})")
        warp(m, 82 + 10 * f, 172, 290, 314, 56, 346, 86,
             f"the farm's right barn is built (packed flag {9013 + 6 * f})")
    # Selphia: Dragon Lake -> MAP_ROOM_12; Selphia Plain -> MAP_ROOM_19 (Prince Points unlocks)
    warp(40, 146, 252, 345, 121, 312, 174, 351, "the Prince Points order Magic merchant (effect 20, unlocks bit 0x20000) is bought")
    warp(164, 153, 252, 343, 160, 60, 200, 100, "the Prince Points order Clothing merchant (effect 17, unlocks bit 0x4000) is bought")
    # the farmhouse rooms 64..73, by the house upgrade level (packed flag 9205)
    hl = "house upgrade level (packed flag 9205)"
    wall(64, 0x3B74, 226, 102, 190, 120, 260, 136, f"{hl} = 0")
    warp(64, 67, 78, 228, 388, 214, 440, 270, f"{hl} >= 2")
    wall(64, 0x3B73, 399, 209, 360, 180, 400, 300, f"{hl} < 2")
    wall(64, 0x3B75, 44, 126, 0, 62, 83, 194, "save option flag 0x40 is set")
    stairs_up = (216, 88, 192, 128, 232, 136)        # 0x3B78 / 0x3B7C
    side_door = (357, 192, 336, 216, 344, 248)       # 0x3B79
    wall(66, 0x3B77, 75, 192, 72, 216, 88, 248)
    warp(66, 69, 216, 348, 172, 72, 260, 128, f"{hl} >= 4")
    wall(66, 0x3B78, *stairs_up, when=f"{hl} < 4")
    warp(66, 68, 78, 228, 368, 200, 400, 250, f"{hl} >= 3")
    wall(66, 0x3B79, *side_door, when=f"{hl} < 3")
    wall(67, 0x3B76, 216, 344, 192, 342, 240, 360)
    warp(67, 64, 340, 235, 40, 214, 72, 250)
    warp(67, 68, 216, 348, 172, 72, 260, 128, f"{hl} >= 3")
    wall(67, 0x3B78, *stairs_up, when=f"{hl} < 3")
    warp(67, 72, 78, 228, 368, 200, 400, 250, f"{hl} >= 5")
    wall(67, 0x3B79, *side_door, when=f"{hl} < 5")
    warp(68, 67, 216, 188, 172, 352, 260, 388)
    warp(68, 66, 340, 235, 40, 214, 72, 250)
    wall(68, 0x3B78, *stairs_up)
    wall(68, 0x3B79, *side_door)
    warp(69, 66, 216, 188, 172, 352, 260, 388)
    wall(69, 0x3B77, 75, 192, 72, 216, 88, 248)
    wall(69, 0x3B78, *stairs_up)
    wall(69, 0x3B79, *side_door)
    wall(70, 0x3B7A, 216, 345, 192, 342, 240, 360)
    warp(70, 71, 340, 235, 40, 214, 72, 250)
    wall(70, 0x3B7C, *stairs_up)
    warp(71, 70, 88, 228, 368, 214, 400, 250)
    warp(71, 73, 340, 235, 40, 214, 72, 250)
    wall(71, 0x3B7A, 216, 345, 192, 342, 240, 360)
    wall(71, 0x3B7C, *stairs_up)
    wall(72, 0x3B76, 216, 344, 192, 342, 240, 360)
    wall(72, 0x3B78, *stairs_up)
    wall(72, 0x3B79, *side_door)
    warp(73, 71, 88, 228, 368, 214, 400, 250)
    wall(73, 0x3B7A, 216, 345, 192, 342, 240, 360)
    wall(73, 0x3B7B, 74, 192, 72, 216, 88, 248)
    wall(73, 0x3B7C, *stairs_up)
    # the 50 barn rooms 77..126: 10 barns (farm f = n // 2, left/right = n & 1) x 5 rooms;
    # the barn's level is packed flag 9010 + 3n (the same flag that opens its door)
    bw = {0x3BB2: (88, 46, 64, 64, 112, 80), 0x3BB3: (248, 46, 224, 64, 272, 80),
          0x3BB4: (16, 224, 16, 232, 24, 272), 0x3BB5: (320, 224, 310, 232, 330, 272),
          0x3BB6: (88, 332, 64, 312, 112, 332), 0x3BB8: (248, 332, 224, 312, 272, 332)}
    left, right = (0, 232, 28, 272), (312, 232, 340, 272)
    up_l, up_r = (64, 24, 112, 72), (224, 24, 272, 72)
    dn_l, dn_r = (64, 322, 112, 364), (224, 322, 272, 364)
    for n in range(10):
        e = 77 + 5 * n
        bl = f"barn level (packed flag {9010 + 3 * n})"
        b = lambda m, s, when=None: wall(m, s, *bw[s], when=when)     # noqa: E731
        warp(e, e + 1, 284, 252, *left)
        warp(e, e + 2, 48, 252, *right)
        warp(e, e + 3, 248, 304, *up_l)
        warp(e, e + 4, 88, 304, *up_r)
        warp(e, 4 * (n // 2) + 4, 332 if n & 1 else 168, 100, 144, 322, 192, 364)
        b(e, 0x3BB4, f"{bl} < 2")
        b(e, 0x3BB5, f"{bl} < 3")
        b(e, 0x3BB2, f"{bl} < 4")
        b(e, 0x3BB3, f"{bl} < 5")
        b(e, 0x3BB6)
        b(e, 0x3BB8)
        warp(e + 1, e, 48, 252, *right)
        warp(e + 1, e + 3, 88, 304, *up_r)
        b(e + 1, 0x3BB3, f"{bl} < 4")
        for s in (0x3BB4, 0x3BB6, 0x3BB8, 0x3BB2):
            b(e + 1, s)
        warp(e + 2, e, 284, 252, *left)
        warp(e + 2, e + 4, 248, 304, *up_l)
        b(e + 2, 0x3BB2, f"{bl} < 5")
        for s in (0x3BB5, 0x3BB6, 0x3BB8, 0x3BB3):
            b(e + 2, s)
        warp(e + 3, e + 4, 48, 252, *right)
        warp(e + 3, e + 1, 248, 92, *dn_l)
        warp(e + 3, e, 88, 92, *dn_r)
        b(e + 3, 0x3BB5, f"{bl} < 5")
        for s in (0x3BB4, 0x3BB2, 0x3BB3):
            b(e + 3, s)
        warp(e + 4, e + 3, 284, 252, *left)
        warp(e + 4, e, 248, 92, *dn_l)
        warp(e + 4, e + 2, 88, 92, *dn_r)
        for s in (0x3BB5, 0x3BB2, 0x3BB3):
            b(e + 4, s)
    return out


def build_map_resources(exe):
    data = exetables.exe_bytes(exe)
    ids = exetables.read("I", MAPRES_RVA, 4 * MAP_ROWS, exe)
    rows = [[_toc_name(data, a) for a in ids[4 * m:4 * m + 4]] for m in range(MAP_ROWS)]
    return {
        "_about": MAPRES_ABOUT,
        "source": {"file": "RF4S.exe", "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()},
        "map_resources": {"rva": f"0x{MAPRES_RVA:X}", "rows": rows},
        "map_type_attrib": {"rva": f"0x{MAPATTR_RVA:X}",
                            "values": list(exetables.read("I", MAPATTR_RVA, MAP_ROWS, exe))},
        "runtime_spawns": {"rva": f"0x{SPAWNS_RVA:X}",
                           "maps": {str(k): v for k, v in sorted(_runtime_spawns().items())}},
    }


def dumps_map_resources(obj):
    out = ["{"]
    out.append(f' "_about": {json.dumps(obj["_about"])},')
    out.append(f' "source": {json.dumps(obj["source"])},')
    mr = obj["map_resources"]
    out.append(f' "map_resources": {{"rva": {json.dumps(mr["rva"])}, "rows": [')
    out.append(",\n".join("  " + json.dumps(r) for r in mr["rows"]))
    out.append(" ]},")
    out.append(f' "map_type_attrib": {json.dumps(obj["map_type_attrib"])},')
    rs = obj["runtime_spawns"]
    out.append(f' "runtime_spawns": {{"rva": {json.dumps(rs["rva"])}, "maps": {{')
    out.append(",\n".join(f"  {json.dumps(k)}: [\n"
                          + ",\n".join("   " + json.dumps(s) for s in v) + "]"
                          for k, v in rs["maps"].items()))
    out.append(" }}")
    out.append("}")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exe", help="RF4S.exe to read (default: the selected game folder's)")
    ap.add_argument("--out", default=str(refdata_path("rf4s_exe_tables.json")),
                    help="chest loot, crate pools, area BGM, encounter zones")
    ap.add_argument("--maps-out", default=str(refdata_path("rf4s_exe_map_resources.json")),
                    help="per-map resources and run-time warps / walls")
    ap.add_argument("--collision-out", default=str(refdata_path("rf4s_exe_collision.json")),
                    help="collision templates of the interactive objects")
    ap.add_argument("--sidecars-out", default=str(refdata_path("rf4s_exe_sidecars.json")),
                    help="search-item and Gen archives per map")
    a = ap.parse_args(argv)
    obj = build(a.exe)
    text = dumps(obj)
    json.loads(text)                            # the hand-laid-out JSON must parse
    pathlib.Path(a.out).write_text(text, encoding="utf-8")
    print(f"wrote {a.out}: {len(obj['chest_loot']['rows'])} chest rows, "
          f"{len(obj['crate_pools'])} crate pools, {len(obj['area_bgm']['sound_ids'])} BGM ids, "
          f"{len(obj['encounter_zones']['rows'])} encounter zones "
          f"(RF4S.exe sha256 {obj['source']['sha256'][:12]}...)")
    mobj = build_map_resources(a.exe)
    mtext = dumps_map_resources(mobj)
    json.loads(mtext)
    pathlib.Path(a.maps_out).write_text(mtext, encoding="utf-8")
    print(f"wrote {a.maps_out}: {len(mobj['map_resources']['rows'])} maps, "
          f"{sum(len(v) for v in mobj['runtime_spawns']['maps'].values())} runtime warps/walls")
    col = build_collision(a.exe)
    text = dumps_collision(col)
    json.loads(text)
    pathlib.Path(a.collision_out).write_text(text, encoding="utf-8")
    print(f"wrote {a.collision_out}: {len(col['templates'])} collision templates for "
          f"{len(col['by_type'])} object types")
    side = build_sidecars(a.exe)
    text = dumps_sidecars(side)
    if json.loads(text) != side:
        raise SystemExit("rf4s_exe_sidecars.json does not round-trip")
    pathlib.Path(a.sidecars_out).write_text(text, encoding="utf-8")
    print(f"wrote {a.sidecars_out}: {sum(1 for x in side['search_items']['archives'] if x)} "
          f"maps with search items, {len(side['gen_archives']['names'])} archive names from "
          f"{side['gen_archives']['first']}")


if __name__ == "__main__":
    main()
