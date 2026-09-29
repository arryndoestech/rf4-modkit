"""rf3NpcParam.bin — monster / character template editor (archive 14812).

A "monster" in RF4S is simply a **char_id**: the numeric id indexes the 392x308-byte
template DB `rf3NpcParam.bin`, and the engine hard-codes what each id RANGE means
(villager / field monster / boss / event NPC / gate). The record is the IDB's CharTemplate_t,
copied per char id by Char_GetTemplate (RF4S.exe+0x1C63B0) and read by Actor_RecomputeAllStats
(+0xAD440) / Actor_LoadBaseStatsFromTemplate (+0xAF940).

This module layers name/drop/AI resolution and the "new monster" workflow on top of the
generic `nlcl` reader:
  * `sheet()`  - full decoded monster record (stats, drops, elements, resists, model/AI)
  * `render()` - human-readable monster sheet
  * `render_list()` - one-line-per-monster roster
  * `id_semantics()` - the engine's id-range meaning (spawn router)
  * `free_slots()` - the unused `???` ids (cut monsters) usable for a data-only new monster
  * `clone_record()` - copy a base monster's 308 bytes into a target slot
  * `set_field()` / `save()` - edit + write back

Field offsets are IDA-verified (Actor_RecomputeAllStats / Actor_LoadBaseStatsFromTemplate)
and live-cross-checked; they live in `nlcl.FIELD_SCHEMAS['rf3NpcParam']`.
"""
from __future__ import annotations

import json
import pathlib

from . import nlcl

STEM = "rf3NpcParam"
RECORD_SIZE = 308
NUM_RECORDS = 392

# element-affinity field suffixes (schema fields elem_<name>), in attack-flag bit order
ELEMENTS = ["fire", "water", "earth", "wind", "light", "dark", "love", "none"]
# status-proc resist field suffixes (schema fields res_<name>), in the game's status-bit
# order (proc mask / cure bits / resist skills 26..32): poison, seal, paralysis, sleep, ...
STATUS = ["poison", "seal", "paralysis", "sleep", "fatigue", "cold", "faint", "drain"]

# Q12 fixed-point unit used by element/resist fields (4096 = 100%)
Q12 = 4096

# char_id -> engine treatment (Actor_SpawnAtPos +0x15A4E0 / Actor_SpawnByCharId +0x15B510)
_RANGES = [
    (0, 47, "villager / human NPC"),
    (48, 199, "field monster (char_monster)"),
    (200, 253, "boss monster (char_boss)"),
    (254, 348, "event NPC"),
    (349, 358, "monster-script special"),
    (359, 10 ** 9, "gate / warp"),
]


def id_semantics(char_id: int) -> str:
    for lo, hi, label in _RANGES:
        if lo <= char_id <= hi:
            return label
    return "?"


def ai_file(ai_id: int) -> str:
    """AI script id -> AIBN filename. The AIBN archive id = ai_id + 1 (Orc ai 0 -> AI_m00)."""
    return f"AI_m{ai_id:02d}.bin"


# --------------------------------------------------------------------------- #
# reference data (optional; empty if not found so the module runs standalone)
# --------------------------------------------------------------------------- #
def _refdata_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent / "rf4_refdata"


def load_species(path=None) -> dict:
    """char_id(int) -> species dict {name, tameable, region, boss, tier, ...}."""
    from .refdata import refdata_path as _rp
    p = pathlib.Path(path) if path else _rp("monster_species.json")
    if not p.is_file():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def load_item_names(path=None) -> dict:
    """item_id(int) -> name: `path` (a JSON {id: name}), else the game's rf3TxtItem."""
    if not path:
        from . import gamenames
        return dict(gamenames.table("items"))
    p = pathlib.Path(path)
    if not p.is_file():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def species_name(char_id: int, species: dict | None) -> str:
    if species and char_id in species:
        return species[char_id].get("name", "") or ""
    return ""


# --------------------------------------------------------------------------- #
# decode
# --------------------------------------------------------------------------- #
def sheet(table: nlcl.NlclTable, char_id: int,
          species: dict | None = None, item_names: dict | None = None) -> dict:
    """Full decoded monster record as a structured dict."""
    row = table.row(char_id, STEM)
    item_names = item_names or {}

    drops = []
    for slot in range(4):
        iid = row[f"drop{slot}_id"] & 0x7FF
        pm = row[f"drop{slot}_pm"]
        if iid or pm:
            drops.append({
                "slot": slot, "item_id": iid,
                "item": item_names.get(iid, ""), "permille": pm,
            })

    elements = {e: row[f"elem_{e}"] for e in ELEMENTS}
    resists = {s: row[f"res_{s}"] for s in STATUS}
    tot = base_totals(row)

    return {
        "id": char_id,
        "name": species_name(char_id, species),
        "semantics": id_semantics(char_id),
        "tameable": bool(species.get(char_id, {}).get("tameable")) if species else None,
        "hp": row["hp"], "atk": tot["atk"], "def": tot["def"],
        "mat": tot["mat"], "mdf": tot["mdf"], "kill_xp": row["kill_xp"],
        "str": row["str"], "int": row["int"], "vit": row["vit"],
        "flat_atk": row["flat_atk"], "flat_def": row["flat_def"],
        "flat_mat": row["flat_mat"], "flat_mdf": row["flat_mdf"],
        "level": row["base_level"], "tame_base": row["tame_base"],
        "ai_script": row["ai_script"], "ai_file": ai_file(row["ai_script"]),
        "model": row["model"], "anim": row["anim"],
        "drops": drops, "elements": elements, "resists": resists,
    }


def base_totals(row: dict) -> dict:
    """The template's ATK / DEF / MAT / MDF before level growth, as Actor_RecomputeAllStats
    (+0xAD440) builds them: ATK = flat_atk + STR, MAT = flat_mat + INT,
    DEF = flat_def + VIT/2, MDF = flat_mdf + VIT/2."""
    half_vit = row["vit"] >> 1
    return {"atk": row["flat_atk"] + row["str"], "def": row["flat_def"] + half_vit,
            "mat": row["flat_mat"] + row["int"], "mdf": row["flat_mdf"] + half_vit}


def _pct(v: int) -> str:
    """Q12 element/resist value -> signed percent string."""
    return f"{v * 100 / Q12:+.0f}%"


def render(table: nlcl.NlclTable, char_id: int,
           species: dict | None = None, item_names: dict | None = None) -> str:
    m = sheet(table, char_id, species, item_names)
    out = []
    tame = " [tameable]" if m["tameable"] else ""
    out.append(f"#{m['id']}  {m['name'] or '???'}{tame}   ({m['semantics']})")
    out.append(f"  HP {m['hp']}   ATK {m['atk']}   DEF {m['def']}   MAT {m['mat']}"
               f"   MDF {m['mdf']}   killXP {m['kill_xp']}   level {m['level']}")
    out.append(f"    = flat ATK {m['flat_atk']} DEF {m['flat_def']} MAT {m['flat_mat']}"
               f" MDF {m['flat_mdf']}  + STR {m['str']} INT {m['int']} VIT {m['vit']}"
               f"   (tame base {m['tame_base']})")
    out.append(f"  AI {m['ai_script']} ({m['ai_file']})   model {m['model']}   anim {m['anim']}")
    if m["drops"]:
        out.append("  drops:")
        for d in m["drops"]:
            nm = f" {d['item']}" if d["item"] else ""
            out.append(f"    slot{d['slot']}: item {d['item_id']}{nm}"
                       f"  @ {d['permille'] / 10:.1f}% ({d['permille']}/1000)")
    else:
        out.append("  drops: (none)")
    weak = {e: v for e, v in m["elements"].items() if v}
    if weak:
        # positive = WEAK (takes more), negative = resists
        parts = [f"{e} {_pct(v)}" for e, v in weak.items()]
        out.append("  elements: " + ", ".join(parts) + "   (+ = weak, - = resist)")
    res = {s: v for s, v in m["resists"].items() if v}
    if res:
        out.append("  resists: " + ", ".join(f"{s} {_pct(v)}" for s, v in res.items()))
    return "\n".join(out)


def render_list(table: nlcl.NlclTable, species: dict | None = None,
                lo: int = 48, hi: int = 253) -> str:
    out = [f"{'id':>4}  {'name':<20} {'HP':>7} {'ATK':>6}  kind"]
    hi = min(hi, table.entry_count - 1)
    for cid in range(lo, hi + 1):
        row = table.row(cid, STEM)
        nm = species_name(cid, species) or "???"
        out.append(f"{cid:>4}  {nm:<20} {row['hp']:>7} {base_totals(row)['atk']:>6}  "
                   f"{id_semantics(cid)}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# new-monster helpers (cut-slot / data-only workflow)
# --------------------------------------------------------------------------- #
#: field-monster ids the shipped game never names or spawns (cut/unused). Verified via the
#: rf3TxtNpc name table (index == char id): only 179/180/181 in the 48..199 band.
KNOWN_CUT_IDS = [179, 180, 181]


def free_slots(table: nlcl.NlclTable, names: dict | None = None) -> list[int]:
    """Field-monster ids (48..199) safe to repurpose for a DATA-ONLY new monster (no EXE
    patch). By default returns the verified-cut ids (179/180/181). Pass `names` = an
    AUTHORITATIVE char_id->name map (from the rf3TxtNpc text archive, NOT the incomplete
    monster_species.json) to compute the unnamed set directly."""
    if not names:
        return list(KNOWN_CUT_IDS)
    free = []
    hi = min(199, table.entry_count - 1)
    for cid in range(48, hi + 1):
        nm = (names.get(cid, "") or "").strip()
        if nm in ("", "???"):
            free.append(cid)
    return free


def clone_record(table: nlcl.NlclTable, src: int, dst: int) -> None:
    """Copy the entire 308-byte template of monster `src` over slot `dst` (in-memory).
    Use to seed a new monster from an existing one, then tweak fields + save()."""
    for r in (src, dst):
        if not (0 <= r < table.entry_count):
            raise nlcl.NlclError(f"record {r} out of range (0..{table.entry_count-1})")
    base = nlcl.HEADER_SIZE
    s = base + src * table.record_size
    d = base + dst * table.record_size
    table.data[d:d + table.record_size] = table.data[s:s + table.record_size]


def set_field(table: nlcl.NlclTable, char_id: int, field: str, value: int) -> None:
    """Set a named schema field (hp/str/int/vit/flat_atk/flat_def/flat_mat/flat_mdf/
    kill_xp/tame_base/base_level/ai_script/model/anim/drop*_id/drop*_pm/elem_*/res_*) on a
    monster record. The retired names atk/def/mat raise with a hint (they named the wrong
    stat: +44/+48/+52 are STR/INT/VIT)."""
    table.set_field(char_id, field, value, STEM)


def save(table: nlcl.NlclTable, path) -> None:
    pathlib.Path(path).write_bytes(table.build())
