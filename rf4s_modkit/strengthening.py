"""strengthening.py -- rf3ItemStrengthening.bin (archive 14811, g_itemDatabase->ptr_78):
the 296-byte per-item "strengthening" record behind forging, upgrading, cooked-dish
bonuses and the item detail window.

Layout
------
NLCL header (28 B) then 1150 records of 74 little-endian s32 dwords S[0..73]. Row index is
the item id for 0..1107; rows 1108..1149 are the synthetic LEVEL / QUALITY tier rows that
Item_ComputeStats adds to a piece of equipment as sources 12 and 13.

Who reads what (RF4S.exe, module-relative RVAs; all verified 2026-08-21 .. 2026-09-16)
------------------------------------------------------------------------------------
Item_ComputeStats                 +0x43E60  forged equipment (a trait, an enchantment, a tier
                                            row): S[1..8] core, S[10..12] knobs, S[14..20]
                                            attack status-proc chances, S[21] HP drain on hit,
                                            S[22..24], S[25..31] status resists, S[32] drain
                                            resist, S[33] reach, S[67..73] elements (armor
                                            families only). Each dword is multiplied by the
                                            932/933/131 multiplier and shifted right once per
                                            duplicate among enchantment sources.
Item_ComputeEffectiveStats        +0x422C0  a cooked dish's six embedded ingredients: S[34..37]
                                            heals, S[38] ORed into the effect word, S[40..52]
                                            the while-fed buff, S[53..59] fed resists,
                                            S[60..66] fed attack procs, S[67..73] elements.
Recipe_ComputeRpCostForOneIngredient +0x3D7D0, Recipe_CalculateRpCostForIngredients +0x3D390,
Crafting_AwardUpgradeXP           +0x3EF60  S[0] difficulty (upgrade RP cost / XP, extra cost).
Crafting_CraftFromInputs          +0x3D930  S[38] bit 0x4000: the NON-FOOD marker (an input
                                            with it spoils a dish and is skipped in the
                                            medicine level average).
DetailWindow_RenderRowByKind      +0x394F5  S[0] shown as the item detail "difficulty" row.
S[9], S[13] and S[39] have no reader; S[61..66] (fed seal..faint procs) are summed into the dish
record by Item_ComputeEffectiveStats but are zero in the shipped file. Per ingredient, dish
record dword k-34 += S[k] for k = 34..73 (S[38] is ORed), i.e. the rf3UseItemParam layout.

Units: "int" = plain stat points; "q12" = fixed point, 4096 = 100% (a chance, a resist, or a
multiplier where +2048 means +50%); "flags" = the status word below.
"""
from __future__ import annotations

import csv
import io
import json
import pathlib

from . import nlcl
from .refdata import refdata_path

RECORD_SIZE = 296
DWORDS = 74
ITEM_ROWS = 1108          # rows 0..1107 are items; 1108..1149 are tier rows

# name, dword index, group, unit, description
FIELDS = [
    ("difficulty", 0, "upgrade", "int",
     "upgrade difficulty: Recipe_ComputeRpCostForOneIngredient cost base, upgrade XP, per-extra craft cost; item detail 'difficulty' row"),
    ("atk", 1, "core", "int", "ATK added to gear that carries this material"),
    ("mat", 2, "core", "int", "MAT added"),
    ("def", 3, "core", "int", "DEF added"),
    ("mdf", 4, "core", "int", "MDF added"),
    ("str", 5, "core", "int", "STR added"),
    ("int", 6, "core", "int", "INT added"),
    ("vit", 7, "core", "int", "VIT added"),
    ("hunger", 8, "core", "int", "hunger inflicted on hit (vector +40 -> stats+44 -> AttackInfo+334, clamp 0..500)"),
    ("unused9", 9, "unused", "int", "never read"),
    ("crit", 10, "combat", "q12", "critical-hit chance (vector +44 -> stats+72, clamp 0..4096; Combat_ResolveHit rolls it against a 12-bit random)"),
    ("knockback", 11, "combat", "q12", "knockback the wearer's hits deal (vector +48 -> stats+56; a weapon hit pushes 6 * this, clamp 0..0x4000)"),
    ("stun", 12, "combat", "q12", "hit-stun the wearer's hits deal (vector +52 -> stats+60; adds 30 * this frames of flinch, clamp 0..0x4000)"),
    ("unused13", 13, "unused", "int", "never read"),
    ("proc_poison", 14, "attack_proc", "q12", "chance to poison on hit (weapon vector +56)"),
    ("proc_seal", 15, "attack_proc", "q12", "chance to seal on hit"),
    ("proc_paralysis", 16, "attack_proc", "q12", "chance to paralyse on hit"),
    ("proc_sleep", 17, "attack_proc", "q12", "chance to sleep on hit"),
    ("proc_fatigue", 18, "attack_proc", "q12", "chance to fatigue on hit"),
    ("proc_cold", 19, "attack_proc", "q12", "chance to give a cold on hit"),
    ("proc_faint", 20, "attack_proc", "q12", "chance to faint on hit"),
    ("hp_drain_attack", 21, "attack_proc", "q12", "HP drained on hit (vector +84)"),
    ("will_resist", 22, "resist", "q12", "will/stamina resist (vector +120)"),
    ("crit_res", 23, "combat", "q12", "critical-hit resist (vector +124 -> stats+76: the attacker's crit chance * (4096 - this))"),
    ("knockback_res", 24, "combat", "q12", "knockback resist (vector +128 -> stats+64: knockback taken * (4096 - this))"),
    ("res_poison", 25, "resist", "q12", "poison resist (4096 = immune)"),
    ("res_seal", 26, "resist", "q12", "seal resist"),
    ("res_paralysis", 27, "resist", "q12", "paralysis resist"),
    ("res_sleep", 28, "resist", "q12", "sleep resist"),
    ("res_fatigue", 29, "resist", "q12", "fatigue resist"),
    ("res_cold", 30, "resist", "q12", "cold resist"),
    ("res_faint", 31, "resist", "q12", "faint resist"),
    ("res_drain", 32, "resist", "q12", "HP-drain resist (vector +160)"),
    ("reach_scale", 33, "reach", "q12", "hit reach scale added to vector +168 (reach = 36 * (4096 + this) >> 12; +2048 = +50%)"),
    ("heal_hp", 34, "heal", "int", "dish: HP healed (flat)"),
    ("heal_rp", 35, "heal", "int", "dish: RP healed (flat)"),
    ("heal_hp_pct", 36, "heal", "q12", "dish: HP healed as a share of max"),
    ("heal_rp_pct", 37, "heal", "q12", "dish: RP healed as a share of max"),
    ("status_word", 38, "status", "flags", "ORed into the dish effect word (cures / inflicts / leveliser) + bit 0x4000 NON-FOOD marker"),
    ("unused39", 39, "unused", "int", "never read"),
    ("buff_hp", 40, "fed_buff", "int", "while fed: max HP"),
    ("buff_rp", 41, "fed_buff", "int", "while fed: max RP"),
    ("buff_str", 42, "fed_buff", "int", "while fed: STR"),
    ("buff_int", 43, "fed_buff", "int", "while fed: INT"),
    ("buff_vit", 44, "fed_buff", "int", "while fed: VIT"),
    ("buff_hp_pct", 45, "fed_buff", "q12", "while fed: max HP %"),
    ("buff_rp_pct", 46, "fed_buff", "q12", "while fed: max RP %"),
    ("buff_str_pct", 47, "fed_buff", "q12", "while fed: STR %"),
    ("buff_int_pct", 48, "fed_buff", "q12", "while fed: INT %"),
    ("buff_vit_pct", 49, "fed_buff", "q12", "while fed: VIT %"),
    ("fed_crit", 50, "fed_buff", "q12", "while fed: critical-hit chance (dish +64 -> stats+72)"),
    ("fed_knockback_res", 51, "fed_buff", "q12", "while fed: knockback resist (dish +68 -> stats+64)"),
    ("fed_crit_res", 52, "fed_buff", "q12", "while fed: critical-hit resist (dish +72 -> stats+76)"),
    ("fed_res_poison", 53, "fed_resist", "q12", "while fed: poison resist"),
    ("fed_res_seal", 54, "fed_resist", "q12", "while fed: seal resist"),
    ("fed_res_paralysis", 55, "fed_resist", "q12", "while fed: paralysis resist"),
    ("fed_res_sleep", 56, "fed_resist", "q12", "while fed: sleep resist"),
    ("fed_res_fatigue", 57, "fed_resist", "q12", "while fed: fatigue resist"),
    ("fed_res_cold", 58, "fed_resist", "q12", "while fed: cold resist"),
    ("fed_res_faint", 59, "fed_resist", "q12", "while fed: faint resist"),
    ("fed_proc_poison", 60, "fed_proc", "q12", "while fed: poison on hit"),
    ("fed_proc_seal", 61, "fed_proc", "q12", "while fed: seal on hit (unused in shipped data)"),
    ("fed_proc_paralysis", 62, "fed_proc", "q12", "while fed: paralysis on hit (unused)"),
    ("fed_proc_sleep", 63, "fed_proc", "q12", "while fed: sleep on hit (unused)"),
    ("fed_proc_fatigue", 64, "fed_proc", "q12", "while fed: fatigue on hit (unused)"),
    ("fed_proc_cold", 65, "fed_proc", "q12", "while fed: cold on hit (unused)"),
    ("fed_proc_faint", 66, "fed_proc", "q12", "while fed: faint on hit (unused)"),
    ("el_fire", 67, "element", "q12", "element affinity: fire (armor families / while fed; +4096 = weak)"),
    ("el_water", 68, "element", "q12", "element affinity: water"),
    ("el_earth", 69, "element", "q12", "element affinity: earth"),
    ("el_wind", 70, "element", "q12", "element affinity: wind"),
    ("el_light", 71, "element", "q12", "element affinity: light"),
    ("el_dark", 72, "element", "q12", "element affinity: dark"),
    ("el_love", 73, "element", "q12", "element affinity: love"),
]
assert len(FIELDS) == DWORDS and [f[1] for f in FIELDS] == list(range(DWORDS))

NAMES = [f[0] for f in FIELDS]
INDEX = {f[0]: f[1] for f in FIELDS}
UNIT = {f[0]: f[3] for f in FIELDS}
GROUP = {f[0]: f[2] for f in FIELDS}
DOC = {f[0]: f[4] for f in FIELDS}
GROUPS = ("upgrade", "core", "combat", "attack_proc", "resist", "reach", "heal", "status",
          "fed_buff", "fed_resist", "fed_proc", "element", "unused")

# S[38]: the same bit layout as the rf3UseItemParam +16 effect word, plus bit 14.
STATUS_BITS = [
    (0x1, "cures poison"), (0x2, "cures seal"), (0x4, "cures paralysis"),
    (0x8, "cures sleep"), (0x10, "cures fatigue"), (0x20, "cures cold"),
    (0x40, "inflicts poison"), (0x80, "inflicts seal"), (0x100, "inflicts paralysis"),
    (0x200, "inflicts sleep"), (0x400, "inflicts fatigue"), (0x800, "inflicts cold"),
    (0x1000, "inflicts faint"),
    (0x2000, "leveliser: grants a level when eaten"),
    (0x4000, "NON-FOOD: not a cooking ingredient (spoils a dish; skipped in the medicine level average)"),
]
NON_FOOD = 0x4000

# Item-id keyed behaviour inside Item_ComputeStats (+0x43E60) and the readers of the
# resulting weapon ability word; these are NOT in the row, they key on the id itself.
FORGE_SPECIALS = {
    872: "sets weapon element FIRE (bit 0x1)",
    870: "sets weapon element WATER (bit 0x2)",
    839: "sets weapon element EARTH (bit 0x4); +20 knockback power at the hit-window open",
    862: "sets weapon element WIND (bit 0x8)",
    880: "sets weapon element LIGHT (bit 0x10)",
    881: "sets weapon element DARK (bit 0x20)",
    882: "LOVE toggle (bit 0x40): strips any element, sets love only when none was present",
    887: "ability bit 0x10000 (no reader found in RF4S.exe)",
    930: "ability bit 0x20000 (no reader found)",
    1019: "ability bit 0x40000 (no reader found; NOT the Rosary's 0x40000, which is the accessory special_bits field op 148 tests)",
    94: "ability bit 0x80000: drop-rate up, -100 on the drop-roll baseline (ActorDrop_RollItemDropFromSlot +0x966C0)",
    95: "ability bit 0x80000: drop-rate up (as 94)",
    929: "ability bit 0x100000: on a spouse or child only, buffed ATK/DEF doubled, damage taken halved, element weakness halved",
    937: "ability bit 0x200000: attack flag, damage forced to 1 (Combat_ComputeDamage, from an earlier pass; not re-read)",
    931: "ability bit 0x400000: attack flag, the defender's element resistance is softened by half (Combat_ComputeDamage, from an earlier pass; not re-read)",
    41: "ability bit 0x800000: a fainted enemy may drop Cabbage",
    43: "ability bit 0x1000000: a fainted enemy may drop Pumpkin",
    45: "ability bit 0x2000000: a fainted enemy may drop Potato",
    47: "ability bit 0x4000000: a fainted enemy may drop Turnip / Pink Turnip",
    752: "ability bit 0x8000000: the search-spot cursor behaves as if the Magnifying Glass were held",
    899: "ability bit 0x20000000 lightweight: a shield keeps working with dual blades / fists at half value",
    900: "ability bit 0x20000000 lightweight",
    969: "ability bit 0x20000000 lightweight",
    979: "ability bit 0x20000000 lightweight", 980: "ability bit 0x20000000 lightweight",
    981: "ability bit 0x20000000 lightweight", 982: "ability bit 0x20000000 lightweight",
    983: "ability bit 0x20000000 lightweight",
    892: "ability bit 0x20000000 lightweight",
    932: "MULTIPLIER x2: as an enchantment (source 4+) it doubles the PREVIOUS source's row instead of adding its own",
    933: "MULTIPLIER x8: as an enchantment (source 4+) it multiplies the PREVIOUS source's row by 8",
    131: "NEGATES the current multiplier for every following source until the next Object X",
    921: "one of the four Cores: all four on an armor-family item add +409 love affinity",
    922: "one of the four Cores (see 921)", 923: "one of the four Cores (see 921)",
    924: "one of the four Cores (see 921)",
    936: "Light Ore: OBJECT MODE at craft time, a Forging recipe accepts any weapon or tool (cat 15..32) as its base",
}


def tier_row_name(i: int) -> str:
    """Name of a synthetic tier row (1108..1149), '' for ordinary items."""
    if 1108 <= i <= 1112:
        return "level tier >= %d, weapon families (+ATK/+MAT)" % ((30, 60, 90, 120, 150)[i - 1108])
    if 1113 <= i <= 1117:
        return "level tier >= %d, armor families (+DEF/+MDF)" % ((30, 60, 90, 120, 150)[i - 1113])
    q = (25, 50, 75, 100, 125, 150, 175, 200)
    if 1118 <= i <= 1125:
        return "quality tier >= %d, ATK family" % q[i - 1118]
    if 1126 <= i <= 1133:
        return "quality tier >= %d, MAT family" % q[i - 1126]
    if 1134 <= i <= 1141:
        return "quality tier >= %d, DEF family" % q[i - 1134]
    if 1142 <= i <= 1149:
        return "quality tier >= %d, MDF family" % q[i - 1142]
    return ""


def load_item_names() -> dict:
    """{item id -> name}: the game's rf3TxtItem (gamenames), else the built-in list."""
    from . import gamenames
    return dict(gamenames.table("items"))


def q12_text(v: int) -> str:
    return "%d (%+.1f%%)" % (v, v * 100.0 / 4096)


def value_text(name: str, v: int) -> str:
    u = UNIT[name]
    if u == "q12":
        return q12_text(v)
    if u == "flags":
        return "0x%X" % v
    return str(v)


def decode_status(word: int) -> list:
    out = [text for bit, text in STATUS_BITS if word & bit]
    rest = word & ~sum(b for b, _ in STATUS_BITS)
    if rest:
        out.append("unknown bits 0x%X" % rest)
    return out


class Row:
    """One 74-dword record. Fields by attribute (r.atk) or by name (r['def'])."""
    __slots__ = ("id", "values")

    def __init__(self, rid: int, values):
        self.id = rid
        self.values = list(values)

    def __getitem__(self, name: str) -> int:
        return self.values[INDEX[name]]

    def __getattr__(self, name: str) -> int:
        if name in INDEX:
            return self.values[INDEX[name]]
        raise AttributeError(name)

    def nonzero(self, group: str | None = None) -> list:
        return [(n, self.values[INDEX[n]]) for n in NAMES
                if self.values[INDEX[n]] and (group is None or GROUP[n] == group)]

    @property
    def status_word(self) -> int:
        return self.values[38]

    def status_flags(self) -> list:
        return decode_status(self.values[38])

    @property
    def is_non_food(self) -> bool:
        return bool(self.values[38] & NON_FOOD)

    @property
    def is_tier_row(self) -> bool:
        return self.id >= ITEM_ROWS

    def as_dict(self) -> dict:
        return {n: self.values[INDEX[n]] for n in NAMES}


class StrengtheningTable:
    def __init__(self, data: bytes):
        self.t = nlcl.NlclTable(data)
        if self.t.record_size != RECORD_SIZE:
            raise nlcl.NlclError("not rf3ItemStrengthening: record size %d, expected %d"
                                 % (self.t.record_size, RECORD_SIZE))

    @classmethod
    def load(cls, path) -> "StrengtheningTable":
        return cls(pathlib.Path(path).read_bytes())

    def __len__(self) -> int:
        return self.t.entry_count

    def row(self, rid: int) -> Row:
        return Row(rid, self.t.record_dwords(rid))

    def rows(self):
        for i in range(self.t.entry_count):
            yield self.row(i)

    def set(self, rid: int, name: str, value: int):
        if name not in INDEX:
            raise nlcl.NlclError("unknown field %r (names: %s)" % (name, ", ".join(NAMES)))
        self.t.set(rid, 4 * INDEX[name], int(value), "s32")

    def build(self) -> bytes:
        return self.t.build()

    def save(self, path):
        self.t.save(path)

    # ---- reports -------------------------------------------------------- #
    def label(self, rid: int, names: dict | None) -> str:
        if rid >= ITEM_ROWS:
            return tier_row_name(rid) or "(tier row)"
        return (names or {}).get(rid, "")

    def render(self, rid: int, names: dict | None = None) -> str:
        r = self.row(rid)
        out = ["#%d %s" % (rid, self.label(rid, names))]
        nz = r.nonzero()
        if not nz:
            out.append("  (all zero: no forge, dish or upgrade effect)")
        out.append("  difficulty %d   (upgrade RP cost base and XP; item detail row)" % r.difficulty)
        by_group = {}
        for n, v in nz:
            by_group.setdefault(GROUP[n], []).append((n, v))
        titles = {
            "core": "forged into gear (Item_ComputeStats): core stats",
            "combat": "forged into gear: crit / knockback / stun",
            "attack_proc": "forged into a weapon: on-hit procs",
            "resist": "forged into gear: resists",
            "reach": "forged into a weapon: reach",
            "element": "element affinity (armor families when forged; any dish while fed)",
            "heal": "eaten as an ingredient of a dish: heals",
            "fed_buff": "while fed: stat buff",
            "fed_resist": "while fed: resists",
            "fed_proc": "while fed: on-hit procs",
        }
        for g in GROUPS:
            if g in ("status", "unused", "upgrade") or g not in by_group:
                continue
            out.append("  " + titles[g] + ":")
            for n, v in by_group[g]:
                out.append("    %-20s %s" % (n, value_text(n, v)))
        flags = r.status_flags()
        if flags:
            out.append("  status word 0x%X:" % r.status_word)
            for f in flags:
                out.append("    " + f)
        else:
            out.append("  status word 0: food-class item (cookable), no cure / inflict bits")
        if rid in FORGE_SPECIALS:
            out.append("  id-keyed forge behaviour: " + FORGE_SPECIALS[rid])
        if rid < ITEM_ROWS and rid <= 47:
            out.append("  id-keyed forge behaviour: ability bit 0x10000000 (id <= 47; no reader found)")
        for n, v in by_group.get("unused", []):
            out.append("  NOTE unused dword %s = %d" % (n, v))
        return "\n".join(out)

    def render_list(self, names: dict | None = None, nonzero: bool = True,
                    field: str | None = None, group: str | None = None,
                    flag: str | None = None, limit: int = 0) -> str:
        if field and field not in INDEX:
            raise nlcl.NlclError("unknown field %r" % field)
        lines = []
        shown = 0
        for r in self.rows():
            if flag == "nonfood" and not r.is_non_food:
                continue
            if flag == "food" and (r.is_non_food or r.id >= ITEM_ROWS):
                continue
            if field is not None:
                v = r[field]
                if nonzero and not v:
                    continue
                lines.append("%5d  %-28s %s" % (r.id, self.label(r.id, names)[:28], value_text(field, v)))
            else:
                nz = r.nonzero(group)
                if nonzero and not nz:
                    continue
                body = ", ".join("%s=%s" % (n, value_text(n, v) if UNIT[n] != "q12" else str(v)) for n, v in nz)
                lines.append("%5d  %-28s %s" % (r.id, self.label(r.id, names)[:28], body))
            shown += 1
            if limit and shown >= limit:
                lines.append("  ... (limit %d)" % limit)
                break
        return "\n".join(lines) if lines else "(nothing matched)"

    def flag_report(self, names: dict | None = None, category_fn=None) -> str:
        """Histogram of the status word plus the non-food marker split by item category."""
        from collections import Counter
        hist = Counter()
        nonfood = []
        for r in self.rows():
            if r.id >= ITEM_ROWS:
                continue
            hist[r.status_word] += 1
            if r.is_non_food:
                nonfood.append(r.id)
        out = ["status word (S[38]) histogram over item rows 0..%d:" % (ITEM_ROWS - 1)]
        for word, cnt in sorted(hist.items(), key=lambda kv: -kv[1]):
            desc = "; ".join(decode_status(word)) if word else "0 (plain food-class item)"
            out.append("  0x%04X  x%4d  %s" % (word, cnt, desc))
        out.append("")
        out.append("NON-FOOD marker (bit 0x4000): %d ids" % len(nonfood))
        if category_fn:
            bycat = Counter(category_fn(i) for i in nonfood)
            out.append("  by rf3ItemList category: " + ", ".join(
                "cat %s x%d" % (c, n) for c, n in sorted(bycat.items(), key=lambda kv: (kv[0] is None, kv[0]))))
            # exceptions worth knowing: equipment without the flag, materials with it missing
            eq_unflagged = [i for i in range(ITEM_ROWS)
                            if category_fn(i) is not None and 15 <= category_fn(i) <= 37 and not self.row(i).is_non_food]
            if eq_unflagged:
                out.append("  equipment WITHOUT the marker (cookable): " + ", ".join(
                    "%d %s" % (i, (names or {}).get(i, "")) for i in eq_unflagged))
            mat_unflagged = [i for i in range(ITEM_ROWS)
                             if category_fn(i) == 51 and not self.row(i).is_non_food]
            if mat_unflagged:
                out.append("  cat-51 materials WITHOUT the marker (cookable): " + ", ".join(
                    "%d %s" % (i, (names or {}).get(i, "")) for i in mat_unflagged))
        return "\n".join(out)

    def render_specials(self, names: dict | None = None) -> str:
        out = ["id-keyed forge behaviour (Item_ComputeStats +0x43E60 and its readers):"]
        for rid in sorted(FORGE_SPECIALS):
            out.append("  %5d %-24s %s" % (rid, (names or {}).get(rid, "")[:24], FORGE_SPECIALS[rid]))
        out.append("  ids 1..47                     ability bit 0x10000000 (no reader found)")
        return "\n".join(out)

    def to_csv(self, names: dict | None = None) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "name"] + NAMES + ["status_flags"])
        for r in self.rows():
            w.writerow([r.id, self.label(r.id, names)] + r.values + ["; ".join(r.status_flags())])
        return buf.getvalue()

    def to_json(self, names: dict | None = None, nonzero: bool = True) -> str:
        rows = []
        for r in self.rows():
            d = {"id": r.id, "name": self.label(r.id, names)}
            d.update({n: v for n, v in (r.nonzero() if nonzero else r.as_dict().items())})
            if r.status_word:
                d["status_flags"] = r.status_flags()
            if rid_special := FORGE_SPECIALS.get(r.id):
                d["forge_special"] = rid_special
            rows.append(d)
        return json.dumps(rows, ensure_ascii=False, indent=1)


def render_field_reference() -> str:
    out = ["rf3ItemStrengthening record: 74 x s32, index -> name (group, unit): description"]
    for n, k, g, u, d in FIELDS:
        out.append("  S[%2d] +%-3d %-20s (%s, %s): %s" % (k, 4 * k, n, g, u, d))
    out.append("")
    out.append("status word bits:")
    for bit, text in STATUS_BITS:
        out.append("  0x%04X  %s" % (bit, text))
    return "\n".join(out)
