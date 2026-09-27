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

Every table records its RVA; the file records the exe it came from (size + SHA-256).

A second file, refdata/rf4s_exe_collision.json (build_collision), holds the collision
templates of the interactive objects (MOBJ types 196..335): g_mapEntityTemplates
RF4S.exe+0x4D5030, one pointer per type - 197 (type 196 uses 197's). Each template: +32 i16
depth bias, +64 u16 width, +66 u16 height (tiles), +68 / +70 i16 x / y offset (sub-units),
+72 u32 cells[width * height], the ATTR bits OR-ed into the tiles the object covers.

Run:  python gen_exe_tables_json.py [--exe PATH] [--out PATH] [--collision-out PATH]
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
# RF4S.exe+0x14B680 switches on the zone and indexes these with an MMIX roll
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exe", help="RF4S.exe to read (default: the selected game folder's)")
    ap.add_argument("--out", default=str(refdata_path("rf4s_exe_tables.json")))
    ap.add_argument("--collision-out", default=str(refdata_path("rf4s_exe_collision.json")))
    a = ap.parse_args(argv)
    obj = build(a.exe)
    text = dumps(obj)
    json.loads(text)                            # the hand-laid-out JSON must parse
    pathlib.Path(a.out).write_text(text, encoding="utf-8")
    print(f"wrote {a.out}: {len(obj['chest_loot']['rows'])} chest rows, "
          f"{len(obj['crate_pools'])} crate pools, {len(obj['area_bgm']['sound_ids'])} BGM ids, "
          f"{len(obj['encounter_zones']['rows'])} encounter zones "
          f"(RF4S.exe sha256 {obj['source']['sha256'][:12]}...)")
    col = build_collision(a.exe)
    text = dumps_collision(col)
    json.loads(text)
    pathlib.Path(a.collision_out).write_text(text, encoding="utf-8")
    print(f"wrote {a.collision_out}: {len(col['templates'])} collision templates for "
          f"{len(col['by_type'])} object types")


if __name__ == "__main__":
    main()
