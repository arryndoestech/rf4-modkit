"""collisionstamp.py -- the ATTR tiles the interactive objects (MOBJ types 196..335) stamp
when a map loads, which the map file itself does not contain.

Map_SpawnInteractiveObject (RF4S.exe+0x143760) does one of two things per record:

* f11 == 0 and the object is shown (its flag gate open): Map_StampEntityCollisionTiles
  (+0x195FC0) writes the type's collision template (g_mapEntityTemplates +0x4D5030, shipped as
  refdata/rf4s_exe_collision.json) into ATTR, around the anchor tile ((f14 + off_x) >> 3,
  (f15 + off_y) >> 3), mirrored left-right when f6 < 0. Trees and rocks get 0x8000002
  (solid + the footprint marker), stones 0x8400004, the invisible wall 262 0x8000002.
  Every type's template is OR-ed in (it can only ADD blocking bits) -- except the airship
  gangway 294: Map_SpawnInteractiveObject passes use_attr_api = (archive id == 0x45AC =
  17542 + 294), which routes its 0x20000001 through Map_SetAttrTileFlags (+0x193430). That
  merges per bit group: a value with any walking bit (group 0x1018F) REPLACES the tile's
  whole walking group, so the wall / half-block tiles under the gangway become walkable path
  (0x1) with the gangway surface 0x20000000 (group 0x6002E040, replaced likewise).
  Map_TickEntityArray (+0x143FB0) removes and re-stamps it whenever the flag hides / shows
  the object, every frame (hidden, the tiles go back to what the file says).
* f11 != 0: no template; instead every tile of the rectangle (f14 >> 3) +- (f9 >> 4) x
  (f15 >> 3) +- (f10 >> 4) becomes SOLID (cell & 0xFFFEFE70 | 2), whether or not the object is
  shown. A zero f9 (f10) collapses the x (y) range onto map column (row) 0 -- all 134 shipped
  f11 != 0 records have f9 = f10 = 0 and so stamp tile (0, 0).

Type 263 is handed to its own spawner and is not stamped here. Cells outside the grid are
dropped, as the game clips them.
"""
from __future__ import annotations

import json

from . import flagstate
from .refdata import refdata_path

SOLID = 0x2                       # the f11 != 0 rectangle: cell & 0xFFFEFE70 | 2
SOLID_CLEAR = 0x1018F             # the bits that rectangle clears first
# the types whose template goes through Map_SetAttrTileFlags (group-wise replace), not an OR:
# the airship gangway (Map_SpawnInteractiveObject tests its archive id, 0x45AC)
REPLACE_TYPES = frozenset({294})
# Map_SetAttrTileFlags's merge groups, in its order: a group present in the new value replaces
# that group in the cell; bits in no group are OR-ed
ATTR_GROUPS = (0x1018F, 0x1C0E00, 0x1000, 0x6002E040, 0x10000, 0x7800000)
_TABLE = None


def table() -> dict:
    """The shipped template table (refdata/rf4s_exe_collision.json)."""
    global _TABLE
    if _TABLE is None:
        with open(refdata_path("rf4s_exe_collision.json"), encoding="utf-8") as f:
            _TABLE = json.load(f)
    return _TABLE


def template(type_id: int) -> dict | None:
    """{w, h, off, z_bias, cells} of a type's collision template, or None."""
    t = table()
    key = t["by_type"].get(str(type_id & 0xFFFF))
    return t["templates"].get(key) if key else None


def set_attr_flags(cell: int, value: int) -> int:
    """Map_SetAttrTileFlags (RF4S.exe+0x193430) on one cell: each ATTR_GROUPS group that
    `value` touches replaces the cell's bits of that group; the rest of `value` is OR-ed."""
    for g in ATTR_GROUPS:
        if value & g:
            cell = (cell & ~g) | (value & g)
            value &= ~g
    return (cell | value) & 0xFFFFFFFF


def result(cell: int, mode: str, bits: int) -> int:
    """The cell after one stamp of `mode` ("template", "replace", "box") with `bits`."""
    if mode == "box":
        return cell & ~SOLID_CLEAR | SOLID
    if mode == "replace":
        return set_attr_flags(cell, bits)
    return cell | bits


def _asr3(v: int) -> int:
    return v >> 3                 # Python >> floors like the game's arithmetic shift


def stamp(rec, W: int, H: int, state=None) -> tuple[str, dict]:
    """(mode, {(tx, ty): bits}) one MOBJ record stamps on a W x H grid: mode "template"
    (OR-ed in), "replace" (the gangway: merged by Map_SetAttrTileFlags, see result()), "box"
    (f11 != 0) or "" (nothing). `state` (flagstate.FlagState or None = every object
    shown) decides whether a flag-gated template is stamped."""
    tid = rec[0] & 0xFFFF
    if not 196 <= tid <= 335 or tid == 263:
        return "", {}
    out = {}
    if rec[11] == 0:
        obj = {"type_id": rec[0], "params": list(rec)}
        if flagstate.no_flag_inverted(obj) or flagstate.hidden(obj, state):
            return "", {}
        tp = template(tid)
        if tp is None:
            return "", {}
        w, h = tp["w"], tp["h"]
        ox = ((_asr3(rec[14] + tp["off"][0]) + 0x8000) & 0xFFFF) - 0x8000   # the game's i16 cast
        oy = ((_asr3(rec[15] + tp["off"][1]) + 0x8000) & 0xFFFF) - 0x8000
        mirror = rec[6] < 0
        cells = tp["cells"]
        for r in range(h):
            ty = oy - (h >> 1) + r
            if not 0 <= ty < H:
                continue
            for c in range(w):
                v = cells[r * w + (w - 1 - c if mirror else c)]
                tx = ox - (w >> 1) + c
                if v and 0 <= tx < W:
                    out[(tx, ty)] = v
        return ("replace" if tid in REPLACE_TYPES else "template"), out
    x0 = x1 = y0 = y1 = 0
    if rec[9]:
        x0, x1 = _asr3(rec[14]) - (rec[9] >> 4), _asr3(rec[14]) + (rec[9] >> 4)
    if rec[10]:
        y0, y1 = _asr3(rec[15]) - (rec[10] >> 4), _asr3(rec[15]) + (rec[10] >> 4)
    if x1 < x0 or y1 < y0 or x1 < 0 or y1 < 0 or x0 >= W or y0 >= H:
        return "box", {}
    for ty in range(max(0, y0), min(H - 1, y1) + 1):
        for tx in range(max(0, x0), min(W - 1, x1) + 1):
            out[(tx, ty)] = SOLID
    return "box", out


def stamps(recs, W: int, H: int, state=None) -> list[tuple[int, str, dict]]:
    """[(record index, mode, {(tx, ty): bits})] for every record that stamps something."""
    out = []
    for i, rec in enumerate(recs):
        mode, cells = stamp(rec, W, H, state)
        if cells:
            out.append((i, mode, cells))
    return out


def apply(cells: list, W: int, H: int, recs, state=None) -> list:
    """A copy of the flat ATTR `cells` with every stamp applied the way the game applies it
    at load (templates OR-ed in, the gangway merged, boxes made solid) -- the grid the player
    actually walks on."""
    out = list(cells)
    for _i, mode, st in stamps(recs, W, H, state):
        for (tx, ty), v in st.items():
            k = ty * W + tx
            out[k] = result(out[k], mode, v)
    return out
