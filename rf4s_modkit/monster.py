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

# element affinities (schema fields "<Name> resist"), in attack-flag bit order
ELEMENTS = ["fire", "water", "earth", "wind", "light", "dark", "love", "none"]
# status-proc resists (schema fields "<Name> resist"), in the game's status-bit order (proc
# mask / cure bits / resist skills 26..32): poison, seal, paralysis, sleep, ...
STATUS = ["poison", "seal", "paralysis", "sleep", "fatigue", "cold", "faint", "drain"]


def resist_field(key: str) -> str:
    """The schema field of an ELEMENTS / STATUS key ("none" is the Neutral resist)."""
    return ("Neutral" if key == "none" else key.capitalize()) + " resist"

# Q12 fixed-point unit used by element/resist fields (4096 = 100%)
Q12 = 4096

# char_id -> engine treatment (Actor_SpawnAtPos +0x15A4E0 / Actor_SpawnByCharId +0x15B510)
_RANGES = [
    (0, 47, "villager / person"),
    (48, 199, "field monster"),
    (200, 253, "boss"),
    (254, 348, "event NPC"),
    (349, 358, "monster-script special"),
    (359, 10 ** 9, "gate / warp"),
]


def id_semantics(char_id: int) -> str:
    for lo, hi, label in _RANGES:
        if lo <= char_id <= hi:
            return label
    return "?"


_AI_FILES = None


def ai_file(ai_id: int) -> str:
    """AI script id -> AIBN filename. AI id n is archive n + 1 (Orc ai 0 -> AI_m00.bin), and the
    archive names are not a plain AI_m{n} sequence: the boss and guest scripts sit in between
    (Ambrosia's caterpillar, ai 169 -> AI_mb40_1.bin), so the name comes from
    refdata/ai_files.json (the rom:/AI/ entries of the exe's archive path table, in order)."""
    global _AI_FILES
    if _AI_FILES is None:
        try:
            from .refdata import refdata_path as _rp
            _AI_FILES = json.loads(pathlib.Path(_rp("ai_files.json")).read_text(encoding="utf-8"))["files"]
        except Exception:  # noqa: BLE001 -- the table is optional
            _AI_FILES = []
    if 0 <= ai_id < len(_AI_FILES):
        return _AI_FILES[ai_id]
    return f"AI_m{ai_id:02d}.bin"


# --------------------------------------------------------------------------- #
# reference data (optional; empty if not found so the module runs standalone)
# --------------------------------------------------------------------------- #
def load_species(path=None) -> dict:
    """char_id(int) -> species dict {name, region, boss, tier, ...}. By default the names are
    the game's own (rf3TxtNpc, gamenames) for every character id, over the reference list."""
    from .refdata import refdata_path as _rp
    p = pathlib.Path(path) if path else _rp("monster_species.json")
    out = ({int(k): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
           if p.is_file() else {})
    if not path:
        from . import gamenames
        for cid, name in gamenames.table("characters").items():
            if name:
                out[cid] = {**out.get(cid, {}), "name": name}
    return out


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
        iid = row[f"Drop {slot + 1}"] & 0x7FF
        pm = row[f"Drop {slot + 1} chance"]
        if iid or pm:
            drops.append({
                "slot": slot, "item_id": iid,
                "item": item_names.get(iid, ""), "permille": pm,
            })

    elements = {e: row[resist_field(e)] for e in ELEMENTS}
    resists = {s: row[resist_field(s)] for s in STATUS}
    tot = base_totals(row)

    return {
        "id": char_id,
        "name": species_name(char_id, species),
        "semantics": id_semantics(char_id),
        "tameable": row["Tame chance"] > 0,     # 0 = MonsterTame_RollAttemptWithItem refuses
        "hp": row["HP"], "atk": tot["atk"], "def": tot["def"],
        "mat": tot["mat"], "mdf": tot["mdf"], "kill_xp": row["Kill XP"],
        "str": row["STR"], "int": row["INT"], "vit": row["VIT"],
        "flat_atk": row["ATK bonus"], "flat_def": row["DEF bonus"],
        "flat_mat": row["MAT bonus"], "flat_mdf": row["MDF bonus"],
        "level": row["Level"], "tame_base": row["Tame chance"],
        "ai_script": row["AI script"], "ai_file": ai_file(row["AI script"]),
        "model": row["Model"], "anim": row["Skeleton"],
        "drops": drops, "elements": elements, "resists": resists,
    }


def base_totals(row: dict) -> dict:
    """The template's ATK / DEF / MAT / MDF before level growth, as Actor_RecomputeAllStats
    (+0xAD440) builds them: ATK = ATK bonus + STR, MAT = MAT bonus + INT,
    DEF = DEF bonus + VIT/2, MDF = MDF bonus + VIT/2."""
    half_vit = row["VIT"] >> 1
    return {"atk": row["ATK bonus"] + row["STR"], "def": row["DEF bonus"] + half_vit,
            "mat": row["MAT bonus"] + row["INT"], "mdf": row["MDF bonus"] + half_vit}


def _pct(v: int) -> str:
    """Q12 element/resist value -> signed percent string."""
    return f"{v * 100 / Q12:+.0f}%"


def render(table: nlcl.NlclTable, char_id: int,
           species: dict | None = None, item_names: dict | None = None) -> str:
    m = sheet(table, char_id, species, item_names)
    out = []
    tame = ", tameable" if m["tameable"] else ""
    out.append(f"#{m['id']}  {m['name'] or '???'}   ({m['semantics']}{tame})")
    out.append(f"  HP {m['hp']}   ATK {m['atk']}   DEF {m['def']}   MAT {m['mat']}"
               f"   MDF {m['mdf']}   Kill XP {m['kill_xp']}   Level {m['level']}")
    out.append(f"    ATK = bonus {m['flat_atk']} + STR {m['str']},  MAT = bonus {m['flat_mat']}"
               f" + INT {m['int']},  DEF / MDF = bonus {m['flat_def']} / {m['flat_mdf']}"
               f" + half of VIT {m['vit']}")
    out.append(f"  Tame chance {m['tame_base']}   AI script {m['ai_script']} ({m['ai_file']})"
               f"   Model {m['model']}   Skeleton {m['anim']}")
    if m["drops"]:
        out.append("  drops: " + "  ·  ".join(
            f"{d['item'] or 'item'} ({d['item_id']}) {d['permille'] / 10:g}%" for d in m["drops"]))
    else:
        out.append("  drops: (none)")
    weak = {e: v for e, v in m["elements"].items() if v}
    if weak:
        # positive = resists (Combat_GetElementBonus returns -stat), negative = WEAK
        parts = [f"{e} {_pct(v)}" for e, v in weak.items()]
        out.append("  elements: " + ", ".join(parts) + "   (+ = resist, - = weak)")
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
        out.append(f"{cid:>4}  {nm:<20} {row['HP']:>7} {base_totals(row)['atk']:>6}  "
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
    """Set a named schema field ("HP", "STR", "ATK bonus", "Drop 1", "Fire resist", ... --
    the names in nlcl.FIELD_SCHEMAS['rf3NpcParam']) on a monster record."""
    table.set_field(char_id, field, value, STEM)


def save(table: nlcl.NlclTable, path) -> None:
    pathlib.Path(path).write_bytes(table.build())
