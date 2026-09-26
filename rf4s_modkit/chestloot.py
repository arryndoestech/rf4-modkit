"""chestloot.py -- what treasure chests and breakable crates give.

Neither table is in a game data file: both live in RF4S.exe, and the toolkit ships them in
refdata/rf4s_exe_tables.json (extracted by gen_exe_tables_json.py, which records the exe's
SHA-256), so nothing reads the exe at run time.

CHESTS (MOBJ type 44, Actor_InitFlagGatedTreasure RF4S.exe+0x14B130) -- fixed contents:

    RF4S.exe+0x9EFA60   190 rows x 4 u16 (0x5F0 bytes, ends at RF4S.exe+0x9F0030)
    row = the chest's f8; each u16 slot is one item:
        bits 0..10   item id (0 = empty slot)
        bits 11..14  a 4-bit value the chest copies next to the item (drop_quality's low
                     nibble); what it does when the chest is looted is not traced
    f8 < 0 (one shipped chest) = no contents.

The 4 slots are single items: three Recovery Potions are three slots of item 127. Past
row 189 the words are float data (0x3F80 = the high half of 1.0), not items. 186 shipped
chests use rows 0..181; rows 182..189 (one Recovery Potion each) and 161 are unused.

CRATES (MOBJ type 53, MapEntity_SpawnTreasure RF4S.exe+0x14B680) -- ONE random item, rolled
each time the room loads, from a pool picked by the map's area group (its MGRP value; see
zone_of_mgrp). Pools are plain u16 item ids, a duplicate raising that item's odds; every pool
holds two 0 entries (the crate gives nothing). DUNG_E rolls 0..99 first: < 20 the rare pool
(Platinum x4, Gold, Silver, Bronze), else the common one. f10 == 1 makes the crate empty.
An item of category 46 (upgrade material) also gets a random quality tier 1..4.
"""
from __future__ import annotations

import json
from collections import Counter

from .refdata import refdata_path

TABLE_FILE = "rf4s_exe_tables.json"
TABLE_RVA = 0x9EFA60
ROWS = 190
SLOTS = 4

_TABLES = None


class ChestLootError(Exception):
    pass


def tables():
    """refdata/rf4s_exe_tables.json, loaded once."""
    global _TABLES
    if _TABLES is None:
        p = refdata_path(TABLE_FILE)
        try:
            _TABLES = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ChestLootError(f"{p.name} missing or unreadable ({e}); run gen_exe_tables_json.py")
    return _TABLES


def load():
    """[[(item_id, value4), x4] per row]."""
    return [[tuple(s) for s in r] for r in tables()["chest_loot"]["rows"]]


def row(index):
    """The 4 slots of row `index` ([] for a negative row, None past the table)."""
    if index < 0:
        return []
    rows = tables()["chest_loot"]["rows"]
    return [tuple(s) for s in rows[index]] if index < len(rows) else None


def summary(slots, item_name=str):
    """'3x Recovery Potion, Spear' for a row's slots; '(empty)' when it has none. A slot's
    non-zero 4-bit value is shown in brackets: 'Iron [2]'."""
    order, count = [], {}
    for item, v in slots or ():
        if not item:
            continue
        k = (item, v)
        if k not in count:
            order.append(k)
            count[k] = 0
        count[k] += 1
    if not order:
        return "(empty)"
    out = []
    for item, v in order:
        n = count[(item, v)]
        out.append((f"{n}x " if n > 1 else "") + str(item_name(item)) + (f" [{v}]" if v else ""))
    return ", ".join(out)


# ---- crates ----------------------------------------------------------------------------- #
def zone_of_mgrp(mgrp):
    """The area-group index the game derives from a map's MGRP value (Minimap_BuildForMap
    RF4S.exe+0x13B3F0 -> the minimap task's byte +52, read by the crate spawner and the
    monster-gate spawner): the lowest set bit of (MGRP >> 5) -- i.e. MGRP group bit - 5 --
    and 0 when MGRP < 0x20. None without an MGRP."""
    if mgrp is None:
        return None
    v = (mgrp & 0xFFFFFFFF) & ~0x1F
    b = v >> 5 if v >= 0x20 else 5
    return next((i for i in range(26) if b >> i & 1), 26)


def crate_pools(zone):
    """The pools ({zone, label, rva, share, items}) the crate spawner rolls from in `zone`."""
    pools = tables()["crate_pools"]
    own = [p for p in pools if p["zone"] == zone]
    return own or [p for p in pools if p["zone"] == "default"]


def crate_odds(zone):
    """[(item_id, chance 0..1)] of one crate in `zone`, most likely first (item 0 = the crate
    gives nothing)."""
    odds = Counter()
    for p in crate_pools(zone):
        n = len(p["items"])
        for item, c in Counter(p["items"]).items():
            odds[item] += p["share"] * c / n
    return sorted(odds.items(), key=lambda t: (-t[1], t[0]))


def area_bgm(zone):
    """The base BGM sound id of area group `zone`, or None."""
    ids = tables()["area_bgm"]["sound_ids"]
    return ids[zone] if zone is not None and 0 <= zone < len(ids) else None
