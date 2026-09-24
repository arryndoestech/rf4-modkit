"""emflags.py -- the RF4 Event Manager flag / register / event symbol table.

The game's global game-state variables (story flags, quest state, marriage, festival
results, etc.) are the **Event Manager** ("EMF_") archive. The release build `em.bin`
(archive 15207) is stripped to numeric ids; the DEBUG build **`emdeb.bin`** carries the
full developer symbol names. This module parses `emdeb.bin` into an authoritative table:

    name (EN + JP)  ->  (bit_offset, bit_width, kind)

`bit_offset` is the variable's position in the runtime packed-flag store
(`g_gameFlagsBuffer`, read via `GameFlags_ReadField(buf, 0, bit_offset, bit_width)`),
i.e. the GameFlags bit-id. Verified: offsets are perfectly sequential
(`offset[i+1] == offset[i] + width[i]`), `REG_MAIN_SCENARIO` = offset 0 / width 9 (the
9-bit main-story register), all `FLG_*` are 1-bit, `REG_*` are multi-bit.

emdeb.bin (magic ``EMDb``) layout used here:
  * header u32[6],[7] = (count=1822, section_off=12248); records begin at section_off+4.
  * each variable = **24 bytes**: (EN_name_ptr u32, f_a u32)(JP_name_ptr u32, **bit_offset u32**)
    (**meta u32** -- byte1 = bit_width)(f_c u32).
  * the name section starts at header u32[13]; strings are NUL-terminated (EN=ASCII, JP=cp932).

NOTE ON SAVE FILES: the bit_offset here is the *runtime* GameFlags bit-id. It does **not**
map linearly to the on-disk save-file story-flag blob (the save uses a different
serialization) -- see `docs`/memory. So this table names/locates flags for the *runtime*
buffer and for the `em.bin` condition system; a save-file editor needs the (separate)
save serialization mapping.
"""
from __future__ import annotations

import os
import struct
from collections import OrderedDict

_MAGIC = b"EMDb"


EXTRA_FILENAME = "emdeb_extra.json"     # sidecar with modder-defined variables
# The packed game-flag store is 832 bytes / 6656 bits in TWO zones (verified in
# ScriptTask_FirstTimeInit, RF4S.exe+0x1EE060): zone 1 = bits 0..4095, which is what
# emdeb.bin names (its 1822 variables end at bit 3017, so 3017..4095 are free), and
# zone 2 = bits 4096..6655, unnamed and reached by adding the base stored at the buffer's
# +0 (GameFlags_TestZone2Bit, RF4S.exe+0x240F50; the calendar's festival-active bits live
# there). New variables are therefore allocated only in the free tail of zone 1.
GAMEFLAGS_BITS = 4096                    # end of zone 1 -- the allocatable region
GAMEFLAGS_BITS_TOTAL = 6656              # full runtime store incl. zone 2 (docs/19 section 3)

# ---- zone 2 (absolute bits 4096..6655): the unnamed half -------------------------------------
# emdeb.bin names nothing here and em.bin never references it. Every consumer adds the base
# stored at the buffer's +0 (4096) to a RELATIVE id: MOBJ f13, script ops 318 (+1007 more),
# 443, 444 and 445, and ~60 exe functions. Map recovered 2026-09-23 from an IDA sweep of all 80
# functions that touch g_gameFlagsBuffer (every `zone2_base + k`) plus a census of the shipped
# data (872 maps' MOBJ f13, rf3.mc ops 318/443/445): 797 distinct relative ids in use.
# (lo, hi, name, what it is / who reads and writes it) -- relative ids, inclusive.
ZONE2_BASE = 4096
ZONE2_BLOCKS = [
    (33, 33, "fishing-spot gate", "MOBJ type-24 fishing spot in MAP_CITY_04 / FIELD_58 / FIELD_81"),
    (70, 70, "FIELD_19 bridge", "bridge MOBJs (342/353) on MAP_FIELD_19; cleared by scripts in banks "
             "132-135; Minimap_BuildForMap and Minimap_BuildLocationNameLabel switch on it"),
    (73, 73, "CITY_04 bridge", "bridge MOBJs (338-341) on MAP_CITY_04; cleared by scripts in banks "
             "132-133; Minimap_BuildForMap swaps sheet 12199; Npc_ApplyScheduleState reads it"),
    (134, 134, "FIELD_98 bridge", "bridge MOBJs (342/353) on MAP_FIELD_98; set by bank 220, cleared "
               "by bank 258; Minimap_BuildForMap swaps the sheet on it"),
    (136, 136, "story milestone shown", "set by Story_DrawMilestoneDiorama; gates a tree MOBJ on "
               "MAP_FIELD_04"),
    (56, 56, "scene/event bit", "queried by script op 445 in banks 4 and 44"),
    (69, 647, "scene/event bit", "per-map scene bits: monster gates, switches, herbs, barriers "
              "(MOBJ types 44/45/47/217/263 ...) and script ops 443/445"),
    (705, 739, "breakable box (permanent)", "type-53 boxes whose broken state is never reset"),
    (740, 751, "shop-door open hours", "set/cleared by the clock in Schedule_RefreshTimeGatedFlags; "
               "read by the town door MOBJs (types 82-85, 114-121)"),
    (752, 969, "daily-reset bit", "cleared EVERY DAY by Day_OnAdvance (752..969): breakable boxes "
               "that come back daily (type 53) and type-35 objects"),
    (981, 1004, "NPC story/availability (981 + char)", "per-NPC bit for chars 0..23: "
                "Script_VMOp_SetNpcStoryFlag / ClearPerNpcFlagBase981, the marriage commit, "
                "Npc_IsInCurrentArea, NpcAi_ResolveVillagerBehavior"),
    (1007, 1036, "birthday gift given (1007 + char)", "set when the player gives the NPC a gift ON "
                 "its birthday (NpcAi_OnReceivedThrownItem; script op 318 = 1007 + arg); "
                 "Calendar_IsEventActive tests it for the birthday rows (calendar kind = char id)"),
    (1037, 1060, "NPC hidden (1037 + char)", "Npc_SetHiddenFlag / Npc_IsHidden, chars 0..23; the "
                 "whole range is cleared daily (PackedFlags_ClearRange24 from Day_UpdateNpcDailyFlags)"),
    (1062, 1708, "recipe learned (1062 + recipe_no)", "CraftData_IsRecipeLearned / "
                 "CraftData_LearnRecipeTask; recipe numbers 1..646. 1403 = 1062 + 341, the "
                 "invalid-recipe sentinel's slot, force-set at new game and by op 616 QueryAndSetCraftedItemFlagBit(100000)"),
]


def zone2_label(rel):
    """(name, detail, char/recipe index or None) for a zone-2 RELATIVE id, or None.
    Specific single-bit entries win over the ranges they sit in."""
    try:
        rel = int(rel)
    except (TypeError, ValueError):
        return None
    hits = [b for b in ZONE2_BLOCKS if b[0] <= rel <= b[1]]
    if not hits:
        return None
    lo, hi, name, detail = min(hits, key=lambda b: b[1] - b[0])
    sub = None
    if "+ char" in name:
        sub = rel - int(name.split("(")[1].split("+")[0])
    elif "recipe_no" in name:
        sub = rel - 1062
    return name, detail, sub


def zone2_text(rel):
    """One-line human label for a zone-2 relative id (always returns a string)."""
    try:
        rel = int(rel)
    except (TypeError, ValueError):
        return str(rel)
    hit = zone2_label(rel)
    absb = ZONE2_BASE + rel
    if not (0 <= absb < GAMEFLAGS_BITS_TOTAL):
        # ScriptTask_FirstTimeInit: aligned_malloc(0x3A0) = 16-byte header + 832-byte bit
        # array (the only part it zeroes) + 80 bytes of slack; nothing bounds-checks an id.
        where = ("in the 80 bytes of never-cleared allocation slack" if absb < 7296
                 else "OUTSIDE the flag buffer's allocation")
        return ("zone-2 bit %d (abs %d) -- PAST THE END of the %d-bit flag store; lands %s"
                % (rel, absb, GAMEFLAGS_BITS_TOTAL, where))
    if hit is None:
        return "zone-2 bit %d (abs %d) -- no known block" % (rel, absb)
    name, _detail, sub = hit
    if sub is not None and "char" in name:
        who = _char_name(sub)
        return "%s: char %d%s (zone-2 %d, abs %d)" % (name.split(" (")[0], sub,
                                                       " " + who if who else "", rel, absb)
    if sub is not None:
        return "%s: recipe %d (zone-2 %d, abs %d)" % (name.split(" (")[0], sub, rel, absb)
    return "%s (zone-2 %d, abs %d)" % (name, rel, absb)


def _char_name(cid):
    try:
        import json
        from .refdata import refdata_path
        with open(refdata_path("char_names.json"), encoding="utf-8") as f:
            nm = json.load(f).get(str(cid))
        return "Lest/Frey" if cid == 0 else nm
    except Exception:
        return None


class Variable:
    """One Event-Manager variable (a flag or register)."""
    __slots__ = ("name", "jp_name", "bit_offset", "bit_width", "kind", "extra")

    def __init__(self, name, jp_name, bit_offset, bit_width):
        self.name = name
        self.jp_name = jp_name
        self.bit_offset = bit_offset
        self.bit_width = bit_width
        self.kind = name.split("_", 1)[0] if name else "?"
        self.extra = False                   # True for modder-defined (sidecar) variables

    @property
    def is_flag(self):
        return self.bit_width == 1

    def __repr__(self):
        return "Variable(%r, off=%d, w=%d)" % (self.name, self.bit_offset, self.bit_width)


class EmFlagTable:
    """Parsed emdeb.bin: every FLG_/REG_/EV_ variable with its bit position + width."""

    def __init__(self, variables):
        if isinstance(variables, (bytes, bytearray, str)):   # footgun: raw bytes, not a var list
            raise ValueError("EmFlagTable() takes a list of Variable objects, not raw bytes -- "
                             "use EmFlagTable.parse(data) or EmFlagTable.load(path).")
        self.variables = variables                       # list[Variable] in file order
        self.by_name = OrderedDict((v.name, v) for v in variables)
        self._by_offset = None
        self.extra_path = None

    # ---- construction ---------------------------------------------------------
    @classmethod
    def parse(cls, data, extra=None):
        """Parse emdeb.bin bytes. `extra`: sidecar path to merge (None = the default
        sidecar next to the bundle's emdeb.bin when it exists; False = none)."""
        t = cls._parse_raw(data)
        if extra is None:
            extra = find_extra()
        if extra:
            t.merge_extras(extra, missing_ok=True)
        return t

    @classmethod
    def _parse_raw(cls, data):
        if data[:4] != _MAGIC:
            raise ValueError("not an EMDb (emdeb.bin) file: magic %r" % data[:4])
        hdr = struct.unpack_from("<16I", data, 0)
        names_base = hdr[13]
        count, sec_off = hdr[6], hdr[7]
        rec0 = sec_off + 4                               # 4-byte preamble before record 0

        def rd_name(ptr, jp=False):
            if not (names_base <= ptr < len(data)):
                return None
            end = data.index(b"\x00", ptr)
            raw = data[ptr:end]
            if jp:
                for enc in ("cp932", "shift_jis", "utf-8"):
                    try:
                        return raw.decode(enc)
                    except Exception:
                        continue
                return None
            try:
                return raw.decode("ascii")
            except Exception:
                return None

        out = []
        i = 0
        while True:
            base = rec0 + i * 24
            if base + 24 > len(data) or base >= names_base:
                break
            en_ptr, _fa, jp_ptr, bit_off, meta, _fc = struct.unpack_from("<6I", data, base)
            name = rd_name(en_ptr)
            if not name:                                  # ran past the record array
                break
            width = (meta >> 8) & 0xFF
            out.append(Variable(name, rd_name(jp_ptr, jp=True), bit_off, width))
            i += 1
        if not out:
            raise ValueError("emdeb.bin parsed to 0 variables (format drift?)")
        return cls(out)

    @classmethod
    def load(cls, path=None, extra=None):
        """Load from an emdeb.bin path, or auto-find it in the game bundle. Modder-defined
        variables from the sidecar `emdeb_extra.json` next to it (or `extra` = explicit
        path; False = none) are merged in -- see add_variable."""
        if path is None:
            path = find_emdeb()
        with open(path, "rb") as f:
            t = cls.parse(f.read(), extra=False)
        if extra is None:
            extra = os.path.join(os.path.dirname(os.path.abspath(path)), EXTRA_FILENAME)
        if extra:
            t.merge_extras(extra, missing_ok=True)
        return t

    # ---- modder-defined variables (sidecar emdeb_extra.json) -------------------
    # emdeb.bin is a debug symbol table the game never loads; a NEW variable is just
    # an unused bit range of the GameFlags store -- normally zone 1 (bits 3017..4095 are
    # free in the shipped table; the save keeps the whole store, see docs/19 section 3).
    # Zone 2 is allowed explicitly, outside the bits the game uses (docs/19 section 3b).
    # The sidecar records the name so every tool -- the cutscene assembler/disassembler,
    # the em.bin condition grammar, the editors -- resolves it like a vanilla FLG_/REG_.
    def merge_extras(self, path, missing_ok=False):
        """Merge the variables of a sidecar JSON file (list of {name, width, bit_offset,
        jp}). Returns the number merged. Conflicting names/bits raise ValueError."""
        import json
        if not os.path.isfile(path):
            if missing_ok:
                return 0
            raise FileNotFoundError(path)
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, dict):
            items = items.get("variables", [])
        n = 0
        for it in items:
            self.add_variable(it["name"], int(it.get("width", 1)), it.get("jp", "") or "",
                              bit_offset=int(it["bit_offset"]), _from_file=True)
            n += 1
        self.extra_path = path
        return n

    def add_variable(self, name, width=1, jp_name="", bit_offset=None, _from_file=False):
        """Define a NEW variable. `bit_offset` None = allocate the next free bits after
        the highest used one. Validates the name (FLG_/REG_ style identifier, unique),
        the width (1..32), that the bits are free and inside the 6656-bit store, that the
        variable sits wholly in ONE zone (bits 0..4095 or 4096..6655), and that a zone-2
        variable does not overlap a bit the game itself uses (ZONE2_BLOCKS).

        Zone-2 variables work from em.bin (its flag operands carry a 1..4-byte offset) but
        NOT from rf3.mc scripts: a script's packed-variable token keeps the offset in 12
        bits, so Container.pack_var refuses offsets >= 4096.
        Returns the Variable (marked `extra=True`, so save_extras() writes it)."""
        import re
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
            raise ValueError("variable name %r must be an identifier (e.g. FLG_MY_QUEST_DONE)" % (name,))
        if name in self.by_name:
            raise ValueError("variable %r already exists (bit %d)" % (name, self.by_name[name].bit_offset))
        width = int(width)
        if not (1 <= width <= 32):
            raise ValueError("width %d out of range 1..32" % width)
        if bit_offset is None:
            # auto-allocation stays in zone 1 (the region the game's own tables use);
            # zone 2 (>=4096) must always be addressed explicitly.
            bit_offset = max((v.bit_offset + max(1, v.bit_width) for v in self.variables
                               if v.bit_offset < GAMEFLAGS_BITS), default=0)
        bit_offset = int(bit_offset)
        if bit_offset < 0 or bit_offset + width > GAMEFLAGS_BITS_TOTAL:
            raise ValueError("bits %d..%d fall outside the %d-bit GameFlags store"
                             % (bit_offset, bit_offset + width - 1, GAMEFLAGS_BITS_TOTAL))
        if bit_offset < GAMEFLAGS_BITS < bit_offset + width:
            raise ValueError("bits %d..%d straddle the zone-1/zone-2 boundary at bit %d; a "
                             "variable must sit wholly in bits 0..%d or %d..%d"
                             % (bit_offset, bit_offset + width - 1, GAMEFLAGS_BITS,
                                GAMEFLAGS_BITS - 1, GAMEFLAGS_BITS, GAMEFLAGS_BITS_TOTAL - 1))
        if bit_offset >= GAMEFLAGS_BITS:
            lo_rel, hi_rel = bit_offset - ZONE2_BASE, bit_offset + width - 1 - ZONE2_BASE
            for blo, bhi, bname, _d in ZONE2_BLOCKS:
                if blo <= hi_rel and lo_rel <= bhi:
                    raise ValueError("bits %d..%d (zone-2 %d..%d) overlap %r (zone-2 %d..%d), "
                                     "which the game itself reads/writes -- pick bits outside "
                                     "emflags.ZONE2_BLOCKS" % (bit_offset, bit_offset + width - 1,
                                                               lo_rel, hi_rel, bname, blo, bhi))
        for b in range(bit_offset, bit_offset + width):
            other = self.by_offset(b)
            if other is not None:
                raise ValueError("bit %d is already used by %s" % (b, other.name))
        v = Variable(name, jp_name or "", bit_offset, width)
        v.extra = True
        self.variables.append(v)
        self.by_name[name] = v
        if self._by_offset is not None:
            for b in range(bit_offset, bit_offset + width):
                self._by_offset.setdefault(b, v)
        return v

    @property
    def extras(self):
        """The modder-defined variables (added via add_variable / the sidecar)."""
        return [v for v in self.variables if getattr(v, "extra", False)]

    @property
    def free_bits(self):
        """Unused bits left in the zone-1 store after the highest zone-1 allocation
        (zone-2 extras are out of scope for auto-allocation)."""
        return GAMEFLAGS_BITS - max((v.bit_offset + max(1, v.bit_width) for v in self.variables
                                      if v.bit_offset < GAMEFLAGS_BITS), default=0)

    def save_extras(self, path=None):
        """Write the sidecar JSON (all extras). Returns the path written."""
        import json
        path = path or self.extra_path
        if not path:
            raise ValueError("no sidecar path: pass one (e.g. <bundle>/emdeb_extra.json)")
        items = [OrderedDict(name=v.name, width=v.bit_width, bit_offset=v.bit_offset, jp=v.jp_name or "")
                 for v in self.extras]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"_comment": "modder-defined Event-Manager variables (merged by the RF4S "
                                   "modkit into emdeb.bin's table; the game itself never reads names)",
                       "variables": items}, f, ensure_ascii=False, indent=1)
        self.extra_path = path
        return path

    # ---- lookup ---------------------------------------------------------------
    def get(self, name):
        return self.by_name.get(name)

    def find(self, substr):
        """All variables whose name contains `substr` (case-insensitive)."""
        s = substr.upper()
        return [v for v in self.variables if s in v.name.upper()]

    def by_offset(self, bit_offset):
        """The variable occupying `bit_offset` (or None)."""
        if self._by_offset is None:
            self._by_offset = {}
            for v in self.variables:
                for b in range(v.bit_offset, v.bit_offset + max(1, v.bit_width)):
                    self._by_offset.setdefault(b, v)
        return self._by_offset.get(bit_offset)

    @property
    def total_bits(self):
        last = self.variables[-1]
        return last.bit_offset + last.bit_width

    def counts(self):
        c = {}
        for v in self.variables:
            c[v.kind] = c.get(v.kind, 0) + 1
        return c

    # ---- packed-buffer read/write (runtime GameFlags layout) ------------------
    def read_value(self, buf, name_or_var):
        """Read a variable's value from a packed GameFlags buffer. Bits are LSB-first
        WITHIN a byte, but a multi-bit field is assembled **MSB-first**: the bit at
        bit_offset is the value's MSB (IDA-verified: GameFlags_ReadField /
        PackedFlags_ReadField_MSBFirst are MSB-first in both modes; live-checked vs a real
        save: REG_CHILD_ID reads 23=Daughter MSB-first, garbage LSB-first). `buf` =
        bytes/bytearray of the flag store (bit 0 = its byte 0)."""
        v = self._resolve(name_or_var)
        val = 0
        for i in range(v.bit_width):
            b = v.bit_offset + i
            bit = (buf[b >> 3] >> (b & 7)) & 1 if (b >> 3) < len(buf) else 0
            val = (val << 1) | bit                 # MSB-first: first bit = MSB
        return val

    def write_value(self, buf, name_or_var, value):
        """Write a variable's value into a mutable packed GameFlags buffer (bytearray),
        MSB-first (inverse of read_value)."""
        v = self._resolve(name_or_var)
        for i in range(v.bit_width):
            b = v.bit_offset + i
            byte = b >> 3
            if byte >= len(buf):
                raise IndexError("bit offset %d past buffer (%d bytes)" % (b, len(buf)))
            mask = 1 << (b & 7)
            if (value >> (v.bit_width - 1 - i)) & 1:   # MSB-first
                buf[byte] |= mask
            else:
                buf[byte] &= ~mask
        return buf

    def _resolve(self, name_or_var):
        if isinstance(name_or_var, Variable):
            return name_or_var
        v = self.by_name.get(name_or_var)
        if v is None:
            raise KeyError("no Event-Manager variable named %r" % (name_or_var,))
        return v

    # ---- export ---------------------------------------------------------------
    def to_records(self):
        return [OrderedDict(name=v.name, jp=v.jp_name, offset=v.bit_offset,
                            width=v.bit_width, kind=v.kind) for v in self.variables]


def find_extra():
    """The default sidecar path (next to the bundle's emdeb.bin) if it exists, else None."""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(find_emdeb())), EXTRA_FILENAME)
    except FileNotFoundError:
        return None
    return p if os.path.isfile(p) else None


def find_emdeb():
    """Locate emdeb.bin in the game bundle (a few common roots)."""
    cands = [
        r"C:/Users/arryn/Documents/Bundle/bundleMain/emdeb.bin",
        os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "Bundle", "bundleMain", "emdeb.bin"),
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError("emdeb.bin not found; pass an explicit path to EmFlagTable.load()")
