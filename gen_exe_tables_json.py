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
Run:  python gen_exe_tables_json.py [--exe PATH] [--out PATH] [--sidecars-out PATH]
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--exe", help="RF4S.exe to read (default: the selected game folder's)")
    ap.add_argument("--out", default=str(refdata_path("rf4s_exe_tables.json")))
    ap.add_argument("--sidecars-out", default=str(refdata_path("rf4s_exe_sidecars.json")))
    a = ap.parse_args(argv)
    obj = build(a.exe)
    text = dumps(obj)
    json.loads(text)                            # the hand-laid-out JSON must parse
    pathlib.Path(a.out).write_text(text, encoding="utf-8")
    print(f"wrote {a.out}: {len(obj['chest_loot']['rows'])} chest rows, "
          f"{len(obj['crate_pools'])} crate pools, {len(obj['area_bgm']['sound_ids'])} BGM ids, "
          f"{len(obj['encounter_zones']['rows'])} encounter zones "
          f"(RF4S.exe sha256 {obj['source']['sha256'][:12]}...)")
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
