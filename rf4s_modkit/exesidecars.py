"""exesidecars.py -- which per-map side files the game loads, by map id.

The game never looks a map's search-item (SI_*.bin) or monster-gate (Gen*.bin) file up by
name: both come from tables in RF4S.exe, keyed by the room's BASE map id (a seasonal
variant counts as its base map). The toolkit ships those tables in
refdata/rf4s_exe_sidecars.json (extracted by gen_exe_tables_json.py, which records the exe's
SHA-256), so nothing reads the exe at run time.

SEARCH ITEMS: SearchItemMng_TickRollAndSpawnDailySpots (RF4S.exe+0x231E80) loads archive
g_searchItemArchiveByMapId[map id] (RF4S.exe+0x4DD260, 870 u32). 0 = the map never rolls
search items -- 565 of the 870 ids, and every id from 870 up. Most archives are named
SI_ + the map's name, but not all: MAP_CITY_05 loads SI_CITY_06.bin, MAP_CITY_06 loads
nothing, MAP_FIELD_A0 / A2 / A3 load SI_FIELD_101 / 103 / 104.bin, and SI_DUNG_E45.bin is
never loaded (MAP_DUNG_E45's entry is 0). A new archive id cannot be added without patching
the exe, so a map without an entry can never get search items.

MONSTER GATES: the archive is map id - first map + first archive of the map's zone (see
rf4s_modkit.areagroup.gen_archive); archive_name() names it.
"""
from __future__ import annotations

import json

from .refdata import refdata_path

TABLE_FILE = "rf4s_exe_sidecars.json"
SI_MAP_IDS = 870            # g_searchItemArchiveByMapId's size: ids from 870 up never roll

_TABLES = None


class SidecarTableError(Exception):
    pass


def tables():
    """refdata/rf4s_exe_sidecars.json, loaded once."""
    global _TABLES
    if _TABLES is None:
        p = refdata_path(TABLE_FILE)
        try:
            _TABLES = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SidecarTableError(f"{p.name} missing or unreadable ({e}); run "
                                    f"gen_exe_tables_json.py")
    return _TABLES


# ---- search items ------------------------------------------------------------------------ #
def si_archive(map_id):
    """The SI archive id the game loads for this (base) map id, or None: the map never rolls
    search items."""
    if map_id is None or not 0 <= map_id < SI_MAP_IDS:
        return None
    return tables()["search_items"]["archives"][map_id] or None


def si_name(map_id):
    """The SI_*.bin file the game loads for this (base) map id, or None."""
    arc = si_archive(map_id)
    if arc is None:
        return None
    si = tables()["search_items"]
    k = arc - si["first_archive"]
    return si["names"][k] if 0 <= k < len(si["names"]) else None


def si_maps(name):
    """Every map id whose search items come from SI file `name` (case-insensitive)."""
    si = tables()["search_items"]
    want = str(name).lower()
    return [m for m, a in enumerate(si["archives"])
            if a and 0 <= a - si["first_archive"] < len(si["names"])
            and si["names"][a - si["first_archive"]].lower() == want]


def si_files():
    """The names of every SI archive the table can load."""
    si = tables()["search_items"]
    return sorted({si["names"][a - si["first_archive"]] for a in si["archives"] if a})


# ---- monster gates ----------------------------------------------------------------------- #
def archive_name(archive):
    """The file name of a monster-gate archive id (any archive the gate spawner can reach),
    or None outside that range."""
    if archive is None:
        return None
    ga = tables()["gen_archives"]
    k = archive - ga["first"]
    return (ga["names"][k] or None) if 0 <= k < len(ga["names"]) else None


def zone_overrun_rows():
    """[(first map, first archive)] for zones 24..26, read past the 24-row encounter table."""
    return [tuple(r) for r in tables()["encounter_zone_overrun"]["rows"]]


def area_bgm_overrun(zone):
    """The sound id Scene_ApplyContextualBGM reads for MGRP zones 21..26 -- past the end of the
    21-entry area BGM table (0 = no sound id; zone 26 reads 0xFFFCFFFC), or None for other
    zones."""
    ids = tables()["area_bgm_overrun"]["sound_ids"]
    return ids[zone - 21] if zone is not None and 21 <= zone < 21 + len(ids) else None
