"""
flagusers.py -- who uses each ZONE-2 ("scene") flag: the placed objects and warps of every map,
and the event scripts.

RF4S keeps its flags in one bit array (832 bytes). Zone 1 (bits 0..~3016) holds the story /
event flags that emdeb.bin names. Zone 2 starts at bit 4096 and holds 2,560 unnamed "scene"
bits. Every map-side flag number is a zone-2 number -- the game adds 4096 before it tests the
bit:

* MOBJ f13 on every type that reads a flag (objects, decorations, chests, crates, seal doors,
  doors / walls, herbs, switches, warp points, inscribed stones ...), and a chest's reveal
  flag f13 + (signed byte) f9;
* MAPJ f0, a warp's disable flag;
* script ops 443 (set / clear), 444 (set / clear from an em.bin condition), 445 (test) with
  the id as their first argument, and op 318 with id 1007 + argument (the per-NPC block).

A zone-2 bit has no name in the game data; what it "means" is who sets it and who reads it.
This module collects exactly that, for the flag reference and the Inspector.
"""
from __future__ import annotations

from . import mobj_params, mobj_types, script

ZONE2_BASE = 4096
ZONE2_BITS = 2560


def object_role(rec) -> str | None:
    """What a MOBJ record's f13 flag does for its type, as a short phrase ("set when opened"),
    or None when the type reads no flag (or the record has none)."""
    tid = rec[0] & 0xFFFF
    f13 = rec[13]
    if not mobj_params.reads_flag(tid) or f13 in (-1,) or (f13 == 0 and tid != 263):
        return None
    if tid == 35:
        return "set when the herb is picked"
    if tid == 44:
        return "set when the chest is opened"
    if tid == 46:
        return "set while switched on" if rec[9] & 0xFF else "set while something stands on it"
    if tid == 47:
        return "set when the room is cleared"
    if tid == 53:
        return "set when the crate is broken"
    if tid == 263:
        return "read as 'discovered' (scripts set it)"
    if tid == 42:
        return "gates the warp point"
    if 82 <= tid <= 195:
        return "its collision box is solid while set"
    kind = mobj_types.mobj_kind(tid)
    if kind == "object":
        return "shown only while set" if rec[12] & 4 else "hidden while set"
    if kind == "decoration":
        return "hidden while set"
    return "read by this object"


def object_uses(map_name, mobj_records, mapj_records):
    """[(zone-2 id, use)] for one map's objects and warps. A use is a dict: kind ("object" /
    "warp"), map, index, what (a readable name), role, at ((x, y) tiles)."""
    out = []
    for i, rec in enumerate(mobj_records):
        role = object_role(rec)
        tid = rec[0] & 0xFFFF
        what = mobj_types.mobj_display_name(tid) or f"type {tid}"
        at = (rec[14] >> 3, rec[15] >> 3)
        if role is not None and 0 <= rec[13] < ZONE2_BITS:
            out.append((rec[13], {"kind": "object", "map": map_name, "index": i, "type": tid,
                                  "what": what, "role": role, "at": at}))
        if tid == 44 and rec[9] & 0xFF and rec[13] != -1:
            off = (rec[9] & 0xFF) - 256 if rec[9] & 0x80 else rec[9] & 0xFF
            rel = rec[13] + off
            if 0 <= rel < ZONE2_BITS:
                out.append((rel, {"kind": "object", "map": map_name, "index": i, "type": tid,
                                  "what": what, "role": "the chest appears once it is set",
                                  "at": at}))
    for j, rec in enumerate(mapj_records):
        if rec[0] != -1 and 0 <= rec[0] < ZONE2_BITS:
            out.append((rec[0], {"kind": "warp", "map": map_name, "index": j, "type": None,
                                 "what": "warp", "role": "switches the warp off while set",
                                 "at": (rec[1] >> 3, rec[2] >> 3)}))
    return out


_OP_ROLE = {443: None, 444: "sets / clears it from an em.bin condition", 445: "tests it",
            318: "sets it (packed per-NPC op)"}


def _const(buf, off):
    if not 0 <= off < len(buf):
        return None
    if buf[off] in (3, 4):
        return script._u32(buf, off + 1)
    v, ok = script.eval_expr(buf, off)
    return int(v) if ok and v is not None else None


def script_uses(container, map_file_for=None):
    """[(zone-2 id, use)] for every constant flag id the event scripts pass to ops 318 / 443 /
    444 / 445. A use: kind "script", bank, owner (whose script), entry (scene entry pc), pc, op,
    role. `map_file_for(map id)` names the map a bank belongs to (bank = n_primary + map id)."""
    out = []
    for bi, bank in enumerate(container.banks):
        try:
            scenes = script.disassemble_bank(bank)
        except Exception:  # noqa: BLE001 - an undecodable bank: skipped
            continue
        mid = bi - container.n_primary
        owner = None
        if mid >= 0 and map_file_for is not None:
            name = map_file_for(mid)
            owner = f"{name}'s event script" if name else None
        owner = owner or f"event bank {bi}"
        seen = set()                              # shared code: once, under its first scene
        for sc in scenes:
            for pc, st in sc.stmts.items():
                if st.op not in script.ZONE2_FLAG_OPS or not st.args or pc in seen:
                    continue
                seen.add(pc)
                v = _const(bank.data, st.args[0])
                if v is None:
                    continue
                rel = script.ZONE2_FLAG_OPS[st.op] + v
                if not 0 <= rel < ZONE2_BITS:
                    continue
                role = _OP_ROLE[st.op]
                if role is None:                        # 443: set or clear by its second arg
                    val = _const(bank.data, st.args[1]) if len(st.args) > 1 else None
                    role = ("sets it" if val else "clears it") if val is not None else "sets / clears it"
                out.append((rel, {"kind": "script", "bank": bi, "owner": owner,
                                  "entry": sc.entry_pc, "pc": pc, "op": st.op, "role": role}))
    return out


def index(uses):
    """{zone-2 id: [use, ...]} from (id, use) pairs."""
    out = {}
    for rel, u in uses:
        out.setdefault(rel, []).append(u)
    return out


def describe(u) -> str:
    """One line for a use: 'MAP_DUNG_B06 #0 seal door (5, 12): set when the room is cleared'."""
    if u["kind"] == "script":
        return f"{u['owner']} @0x{u['entry']:04x}: {u['role']} (op {u['op']})"
    if u["kind"] == "warp":
        return f"{u['map']} warp #{u['index']} at {u['at']}: {u['role']}"
    return f"{u['map']} #{u['index']} {u['what']} at {u['at']}: {u['role']}"
