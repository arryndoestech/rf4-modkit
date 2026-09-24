#!/usr/bin/env python3
"""Generate MOBJ parameter spreadsheets from the IDA-verified mobj_params map.

Writes two CSVs into docs/:
  * mobj_parameters.csv       — offset grid: one row per MOBJ type, one column per BYTE OFFSET
                                in the 64-byte record (0x00, 0x04, ... 0x3C). Each cell says what
                                that field is for that object, with its read width, so a row reads
                                like the record's physical layout.
  * mobj_parameters_long.csv  — tidy: one row per (type, parameter): id,name,field,offset,size,meaning.

A MOBJ record is 16 x i32 (64 B); byte offset of field N = N*4. field 0 (@0x00) = type_id,
f14 (@0x38)/f15 (@0x3C) = tile position (universal). Blank cells = the game doesn't read that slot.
Run:  python gen_mobj_param_csv.py
"""
import csv
import pathlib

from rf4s_modkit import mobj_types as mt, mobj_params as mp

DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"
DOCS.mkdir(parents=True, exist_ok=True)   # create docs/ if the checkout lacks it

ids = [i for i in range(0, 420) if mt.mobj_name(i) or 0 <= i <= 19 or mp.params_for(i)]
maxp = max((len(mp.params_for(i)) for i in ids), default=0)


# ---- offset grid ------------------------------------------------------------------
# One column per byte offset in the 64-byte record: field N -> byte N*4.
OFFSETS = [n * 4 for n in range(16)]            # 0x00, 0x04, ... 0x3C


def cell_for(type_id, field, pmap):
    """What the slot at field `field` is for this object (with read width)."""
    if field == 0:
        return "type_id (u32)"
    if field == 14:
        return "tile X (u32)"
    if field == 15:
        return "tile Y (u32)"
    if field in pmap:
        sz, mn = pmap[field]
        return "%s (%s)" % (mn, mp.SIZE_NAME[sz])
    return ""


wide = DOCS / "mobj_parameters.csv"
with wide.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["mobjName", "mobjID"]
               + ["0x%02X (f%d)" % (off, off // 4) for off in OFFSETS]
               + ["lane", "role"])
    for i in ids:
        name = mt.mobj_name(i) or mp.name_for(i)
        pmap = {fl: (sz, mn) for fl, sz, mn in mp.params_for(i)}
        row = [cell_for(i, off // 4, pmap) for off in OFFSETS]
        w.writerow([name, i] + row + [mp.lane_for(i)[0], mp.role_for(i)])

# ---- long / tidy ------------------------------------------------------------------
long = DOCS / "mobj_parameters_long.csv"
with long.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["mobjID", "mobjName", "lane", "field", "byteOffset", "size", "meaning"])
    for i in ids:
        name = mt.mobj_name(i) or mp.name_for(i)
        lane = mp.lane_for(i)[0]
        for fl, sz, mn in mp.params_for(i):
            w.writerow([i, name, lane, "f%d" % fl, fl * 4, mp.SIZE_NAME[sz], mn])

print("wrote %s (%d types, up to %d params)" % (wide, len(ids), maxp))
print("wrote %s" % long)
