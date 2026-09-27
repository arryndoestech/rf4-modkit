"""mapres.py -- per-map tables from RF4S.exe that the map editor needs.

Shipped in refdata/rf4s_exe_map_resources.json (extracted once by gen_exe_tables_json.py, which
records the exe's SHA-256); nothing reads the exe at run time.

* g_mapResourceTable (RF4S.exe+0x9F9D10): four archive ids per map id -- the .rf4m, the ground
  layer's tile 0, the OVERLAY layer's tile 0 (0 = the map has no overlay) and the over-model.
  Map_SpawnEntity (RF4S.exe+0x194140) builds the first MTXN chunk's display layer from the
  ground id and every later chunk's from the overlay id, so the overlay is its own set: on 121
  maps it is not the ground set's ``_1000`` tiles (MAP_FIELD_01's ground is MAP_FIELD_201 but
  its overlay is MAP_FIELD_01_1000), and MAP_DUNG_I04 / I08 have none although their ground
  set ships a ``_1000`` layer. There is no layer 2 or higher.
* g_mapTypeAttribTable (RF4S.exe+0x4D4290): one u32 per map id. Map_PostLoad
  (RF4S.exe+0x193FB0) uses 181,214,214 as the night tint default instead of 148,214,247 when
  bit 0x10 is set. It indexes the table by the id the warp asked for, i.e. the base id of a
  seasonal map.
* Map_SpawnProgressWarpsAndWalls (RF4S.exe+0x144A50): warp zones and blocker walls the game
  adds to the farm, its fields, the farmhouse, the barns and two town maps at load, gated on
  progress (farm / house / barn upgrades, Prince Points unlocks). They are not in the .rf4m.
"""
from __future__ import annotations

import json
import re

from .refdata import refdata_path

TABLE_FILE = "rf4s_exe_map_resources.json"
NIGHT_ALT_BIT = 0x10                   # g_mapTypeAttribTable bit read by Map_PostLoad
NIGHT_DEFAULT = (148, 214, 247)
NIGHT_DEFAULT_BIT10 = (181, 214, 214)
_TILE = re.compile(r"^(.*)_(\d)(\d{3})$")

_TABLES = None
_BY_NAME = None


def tables() -> dict:
    """The shipped JSON, loaded once ({} when it is missing, so callers fall back)."""
    global _TABLES
    if _TABLES is None:
        try:
            _TABLES = json.loads(refdata_path(TABLE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _TABLES = {}
    return _TABLES


def _rows():
    return tables().get("map_resources", {}).get("rows", [])


def row(map_id):
    """[rf4m, ground tile 0, overlay tile 0 | None, over-model | None] of a map id, or None."""
    rows = _rows()
    try:
        mid = int(map_id)
    except (TypeError, ValueError):
        return None
    return rows[mid] if 0 <= mid < len(rows) else None


def map_id(name):
    """Map id of a map file name / path / base name (case-insensitive), or None."""
    global _BY_NAME
    if _BY_NAME is None:
        _BY_NAME = {r[0].upper(): i for i, r in enumerate(_rows()) if r and r[0]}
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower().endswith(".rf4m"):
        base = base[:-5]
    return _BY_NAME.get(base.upper())


def base_id(map_id):
    """The id the game keeps for a map id: ids 4..63 come in seasons (base, _SUMMER, _AUTUMN,
    _WINTER) and the season is added at load, so the base is the multiple of 4."""
    if map_id is None:
        return None
    mid = int(map_id)
    return mid - mid % 4 if 4 <= mid < 64 else mid


def _set_of(tile):
    """('MAP_FIELD_01', 1) for 'MAP_FIELD_01_1000'; None for None."""
    if not tile:
        return None
    m = _TILE.match(tile)
    return (m.group(1), int(m.group(2))) if m else (tile, 0)


def overlay_set(map_name):
    """(known, set) for a map: `known` = the map is in the game's table; `set` = the texture
    set whose ``_1NNN`` tiles are its overlay layer, or None when the game draws no overlay."""
    mid = map_id(map_name)
    r = row(mid) if mid is not None else None
    if r is None:
        return False, None
    s = _set_of(r[2])
    return True, (s[0] if s else None)


def has_overlay(map_id):
    """True / False when the map id is in the table (overlay id != 0), else None."""
    r = row(map_id)
    return None if r is None else bool(r[2])


def type_attrib(map_id):
    vals = tables().get("map_type_attrib", {}).get("values", [])
    mid = base_id(map_id)
    return vals[mid] if mid is not None and 0 <= mid < len(vals) else None


def night_default(map_id):
    """The night tint the game uses for a zero MLIG night slot on this map (base id)."""
    a = type_attrib(map_id)
    return NIGHT_DEFAULT_BIT10 if a is not None and a & NIGHT_ALT_BIT else NIGHT_DEFAULT


def runtime_spawns(map_id):
    """[{kind: 'warp'|'wall', box: [x0, y0, x1, y1], when, dest/arrive | sprite/at}] the game
    adds to this map at load (keyed by the base id); [] for none."""
    mid = base_id(map_id)
    if mid is None:
        return []
    return list(tables().get("runtime_spawns", {}).get("maps", {}).get(str(mid), []))


def wall_cells(box):
    """Tile rectangle (tx0, ty0, tx1, ty1), inclusive, that Map_SpawnBlockerWall
    (RF4S.exe+0x1525B0) sets to blocked: x0 >> 3 .. (x1 + 7) >> 3, the same on y. An all-zero
    box blocks nothing."""
    x0, y0, x1, y1 = box
    if not (x0 or y0 or x1 or y1):
        return None
    return x0 >> 3, y0 >> 3, (x1 + 7) >> 3, (y1 + 7) >> 3
