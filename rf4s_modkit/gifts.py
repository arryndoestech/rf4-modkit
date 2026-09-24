"""rf4s_modkit/gifts.py -- NPC gift-preference tables (`rf3PresentNpc01..27.bin`) and the shared
gift-category file (`rf3PresentCategory.bin`).  Read + edit + byte-exact rebuild.

Archive ids: rf3PresentNpcNN = 14850 + NN with NN = min(char_id, 27) (so every char_id >= 27 uses
file 27), rf3PresentCategory = 14850.  File <-> character confirmed against the in-game Gift
Preferences UI for Raven (25): loved pendants/ores, hated Skull.

Layout (re-verified 2026-09-19 against the readers `Npc_GetGiftAffinityHashByItemAndCharId`
RF4S.exe+0x22A520 and `GiftTable_FindEntryByItemIdOrRangeOrCrossRef` RF4S.exe+0x22A700 -- an
older version of this docstring cited +0x2DA520, which is an unrelated fixed-point routine):

    +0   "NLCL"    +4  u32 build date (0x20201119 in every shipped file)    +8  u64 0
    +16  u32 section_count = 1 + number of sub-lists present   (NLCLINK section table, see below)
    +20  u32 data_end      = file offset of that section table
    +24  u32 group_count   (all 27 NPC files: 1; the category file: 21)
    +28  per group 3 u32 ABSOLUTE file offsets  [off1, off2, off3]   (0 = no list)
         each -> sub-list  [u32 count][count x u32 entry]
    +data_end  NLCLINK tail, reproduced by build():
         section_count x {u32 0, u32 section_off, u32 n_refs, u32 ref_list_off}  -- section 0
         is the group table at +24 (0 refs); every sub-list is one section with 1 ref --
         followed by the ref lists: one u32 per sub-list = the file offset of the [offN] field
         that points at it.  The reader never touches the tail (it derefs the raw offsets:
         `archive + off`), but it is kept so rebuilt files stay byte-identical to stock.

Entry u32: low16 = target, high16 = code.
  target  0..0x7FF         item id: the reader compares the WHOLE 16-bit target with the
                           gifted `item & 0x7FF`, so 0x800..0x7FFF never match (rejected)
          0x8000..0x800B   item-id RANGE tag; low byte indexes g_itemCategoryRangeTable
                           (RF4S.exe+0x4D5918, 12 u16 [min,max) pairs, vendored in ITEM_RANGE_TABLE);
                           tags 12..255 would index past those 12 pairs (rejected)
          0x8100..         cross-ref: group (target - 0x8100) of rf3PresentCategory; the reader
                           walks that group's off1 list for a DIRECT item-id match only (no nested
                           ranges/xrefs) and returns the CATEGORY entry -- so its code, not the
                           NPC entry's code, is what gets applied. An index >= the category
                           file's group count (21) is skipped silently (bounds-checked there).
  The FP codes of loved/liked entries are applied as SIGNED 16-bit values (-32768..32767).
  The loop counters in the lookup are 8-bit: a sub-list (or a category list) must hold at most
  255 entries or the game spins forever.  build() enforces this.

Which list means what (reader order off3 -> off2 -> off1, first match wins; result low16 = tier
code, high16 = friendship-point delta):
  off3  LOVED     tier 4, FP = the entry code (+15 in every shipped file)
  off2  LIKED     tier 3, FP = the entry code (+9 / +6 in shipped files)
  off1  DISLIKED  code 0xFFF6 -> tier 5 "signature/hated" item (-10 FP, its own dialogue --
                  Raven's Skull, Volkanon's Failed Dish); ANY other code -> tier 2 generic
                  dislike, fixed -5 FP (the stored code is ignored; shipped files use 0xFFFB)
  no match        tier 1 NEUTRAL, +5 FP (not 0: the hash is 0x00050001)
  An item with a rune attached is always tier 2 (-5).
The FP is applied by `Event_GetThrowReactionStyleBits` RF4S.exe+0x228890: it passes the signed
high16 straight to `Npc_AddFriendshipXpAndProcessLevelUp` (+0x225EA0), doubled on the NPC's
birthday; loved/liked/neutral FP is granted once per day per NPC (record bits 0x20000 / 0x10000 /
0x8000), dislikes hit every time.

VERIFIED against the in-game Gift Preferences UI for Raven (file 25): off3 = the 19 LOVED
items, off2 = the 28 LIKED items, off1 = Skull (hated) + 3 generic dislikes + one category.
"""
from __future__ import annotations

import struct
from collections import namedtuple

GROUP_OFF = 24
MAGIC = b"NLCL"
DEFAULT_BUILD_DATE = 0x20201119
SIGNATURE_DISLIKE_CODE = 0xFFF6   # in off1 (disliked): the ONE item with unique dialogue, -10 FP
GENERIC_DISLIKE_CODE = 0xFFFB     # what shipped files store for the other dislikes (-5, code ignored)
DEFAULT_FP = {"loved": 15, "liked": 9}
NEUTRAL_FP = 5                    # unlisted item: +5 (once per day)
MAX_LIST_ENTRIES = 255            # u8 loop counters in GiftTable_FindEntryByItemIdOrRangeOrCrossRef
MAX_ITEM_ID = 0x7FF               # the gifted item is masked to 11 bits before the compare
RANGE_TAGS = 12                   # g_itemCategoryRangeTable holds 12 [min, max) pairs

Entry = namedtuple("Entry", "kind value code")   # kind: item|category|xref

TIERS = ("loved", "liked", "disliked")   # game UI order; "neutral" = anything unlisted
# tier -> which of the 3 per-group offsets holds it (off1 = index 0)
TIER_SLOT = {"disliked": 0, "liked": 1, "loved": 2}
_SLOT_TIER = ("disliked", "liked", "loved")


class GiftError(ValueError):
    pass


def _decode_target(raw: int) -> tuple[str, int]:
    # 0x0000..0x7FFF = item id ; 0x8000..0x80FF = item-id RANGE tag (g_itemCategoryRangeTable,
    # low byte) ; 0x8100..0xFFFF = cross-ref into the 21-group rf3PresentCategory (archive 14850),
    # idx = (raw + 0x7F00) & 0xFFFF = raw - 0x8100 (GiftTable_FindEntryByItemIdOrRangeOrCrossRef).
    if raw < 0x8000:
        return ("item", raw)
    if raw < 0x8100:
        return ("category", raw & 0xFF)
    return ("xref", raw - 0x8100)


def encode_target(kind: str, value: int) -> int:
    """Inverse of _decode_target."""
    value = int(value)
    if kind == "item":
        if not (0 <= value <= MAX_ITEM_ID):
            raise GiftError(f"item id {value} out of range (0..{MAX_ITEM_ID}: the game compares "
                            f"the entry with the 11-bit gifted item id)")
        return value
    if kind == "category":
        if not (0 <= value < RANGE_TAGS):
            raise GiftError(f"range tag {value} out of range (0..{RANGE_TAGS - 1}: "
                            f"g_itemCategoryRangeTable has {RANGE_TAGS} entries)")
        return 0x8000 | value
    if kind == "xref":
        if not (0 <= value <= 0xFFFF - 0x8100):
            raise GiftError(f"category xref {value} out of range")
        return 0x8100 + value
    raise GiftError(f"unknown entry kind {kind!r}")


def encode_entry(e: Entry) -> int:
    return encode_target(e.kind, e.value) | ((int(e.code) & 0xFFFF) << 16)


def _sublist(data: bytes, off: int) -> list[Entry]:
    if not (0 < off < len(data) - 4):
        return []
    n = struct.unpack_from("<I", data, off)[0]
    out = []
    for k in range(n):
        p = off + 4 + k * 4
        if p + 4 > len(data):
            break
        raw = struct.unpack_from("<I", data, p)[0]
        kind, val = _decode_target(raw & 0xFFFF)
        out.append(Entry(kind, val, (raw >> 16) & 0xFFFF))
    return out


class GiftTable:
    """One rf3PresentNpcNN / rf3PresentCategory file: `groups[g][tier]` is a list of Entry, or
    None when that group has no such list (offset 0 -- the category file's off2/off3)."""

    def __init__(self, groups: list[dict], build_date: int = DEFAULT_BUILD_DATE):
        self.groups = groups
        self.build_date = build_date

    # ---- parse ----------------------------------------------------------- #
    @classmethod
    def parse(cls, data: bytes) -> "GiftTable":
        if data[:4] != MAGIC:
            raise GiftError(f"not an NLCL gift table (magic={data[:4]!r})")
        build_date = struct.unpack_from("<I", data, 4)[0]
        count = struct.unpack_from("<I", data, GROUP_OFF)[0]
        if not (0 < count < 64):
            raise GiftError(f"implausible group count {count}")
        groups = []
        for i in range(count):
            base = GROUP_OFF + 4 + i * 12
            offs = struct.unpack_from("<III", data, base)
            g = {}
            for slot, off in enumerate(offs):
                g[_SLOT_TIER[slot]] = _sublist(data, off) if off else None
            groups.append(g)
        return cls(groups, build_date)

    # ---- query ----------------------------------------------------------- #
    def tier(self, tier: str, group: int = 0) -> list[Entry]:
        lst = self.groups[group].get(tier)
        return [] if lst is None else lst

    def find(self, kind: str, value: int) -> list[tuple[int, str, int]]:
        """[(group, tier, index)] of every entry with that target."""
        hits = []
        for gi, g in enumerate(self.groups):
            for tier in TIERS:
                lst = g.get(tier) or []
                for k, e in enumerate(lst):
                    if e.kind == kind and e.value == value:
                        hits.append((gi, tier, k))
        return hits

    def tier_of(self, item_id: int, group: int = 0) -> str:
        """loved / liked / disliked / neutral for a DIRECT item entry (ranges/xrefs not expanded)."""
        for tier in TIERS:
            if any(e.kind == "item" and e.value == item_id for e in self.tier(tier, group)):
                return tier
        return "neutral"

    # ---- edit ------------------------------------------------------------ #
    def remove(self, kind: str, value: int, group: int | None = None) -> int:
        """Drop every entry with that target (from all groups, or one). Returns the count."""
        n = 0
        for gi, g in enumerate(self.groups):
            if group is not None and gi != group:
                continue
            for tier in TIERS:
                lst = g.get(tier)
                if lst is None:
                    continue
                keep = [e for e in lst if not (e.kind == kind and e.value == value)]
                n += len(lst) - len(keep)
                g[tier] = keep
        return n

    def add(self, tier: str, entry: Entry, group: int = 0) -> None:
        """Append an entry to a tier (the same target is first removed from every tier of the
        group so an item can never sit in two lists)."""
        if tier not in TIERS:
            raise GiftError(f"tier must be one of {TIERS}, not {tier!r}")
        if not (-0x8000 <= int(entry.code) <= 0xFFFF):
            raise GiftError(f"entry code {entry.code} does not fit 16 bits")
        encode_target(entry.kind, entry.value)          # validate before touching the lists
        self.remove(entry.kind, entry.value, group)
        g = self.groups[group]
        if g.get(tier) is None:
            g[tier] = []
        g[tier].append(Entry(entry.kind, int(entry.value), int(entry.code) & 0xFFFF))

    def set_item(self, item_id: int, tier: str, fp: int | None = None,
                 signature: bool = False, group: int = 0) -> Entry | None:
        """Move an item to loved/liked/disliked/neutral.  fp = friendship points for loved/liked
        (default 15 / 9, the stock values); disliked entries get the signature code (0xFFF6, -10)
        when `signature` else the generic code (0xFFFB, -5).  neutral = remove from every list."""
        if tier == "neutral":
            self.remove("item", item_id, group)
            return None
        if tier == "disliked":
            code = SIGNATURE_DISLIKE_CODE if signature else GENERIC_DISLIKE_CODE
        elif tier in DEFAULT_FP:
            code = DEFAULT_FP[tier] if fp is None else int(fp)
            if not (-0x8000 <= code <= 0x7FFF):
                raise GiftError(f"fp {code} out of range: the game applies the code as a "
                                f"signed 16-bit friendship delta (-32768..32767)")
        else:
            raise GiftError(f"tier must be loved/liked/disliked/neutral, not {tier!r}")
        e = Entry("item", int(item_id), code & 0xFFFF)
        self.add(tier, e, group)
        return e

    def set_signature(self, item_id: int, group: int = 0, demote_others: bool = True) -> None:
        """Make `item_id` the signature/hated (-10) dislike; other 0xFFF6 entries of the group
        become generic dislikes when demote_others (the game does not require uniqueness, the
        gift UI just shows one)."""
        g = self.groups[group]
        if demote_others and g.get("disliked"):
            g["disliked"] = [Entry(e.kind, e.value, GENERIC_DISLIKE_CODE)
                             if e.code == SIGNATURE_DISLIKE_CODE else e for e in g["disliked"]]
        self.set_item(item_id, "disliked", signature=True, group=group)

    # ---- build ----------------------------------------------------------- #
    def build(self) -> bytes:
        n = len(self.groups)
        out = bytearray(GROUP_OFF + 4 + 12 * n)
        sections = []                                   # (sub-list offset, referencing field)
        for gi, g in enumerate(self.groups):
            for slot, tier in enumerate(_SLOT_TIER):
                lst = g.get(tier)
                field = GROUP_OFF + 4 + 12 * gi + 4 * slot
                if lst is None:
                    continue
                if len(lst) > MAX_LIST_ENTRIES:
                    raise GiftError(f"group {gi} {tier}: {len(lst)} entries, the game's lookup "
                                    f"loop is 8-bit (max {MAX_LIST_ENTRIES})")
                off = len(out)
                out += struct.pack("<I", len(lst))
                for e in lst:
                    out += struct.pack("<I", encode_entry(e))
                struct.pack_into("<I", out, field, off)
                sections.append((off, field))
        data_end = len(out)
        nsec = 1 + len(sections)
        ref_base = data_end + 16 * nsec
        out += struct.pack("<IIII", 0, GROUP_OFF, 0, 0)
        for i, (off, _field) in enumerate(sections):
            out += struct.pack("<IIII", 0, off, 1, ref_base + 4 * i)
        for _off, field in sections:
            out += struct.pack("<I", field)
        struct.pack_into("<4sIQII", out, 0, MAGIC, self.build_date, 0, nsec, data_end)
        struct.pack_into("<I", out, GROUP_OFF, n)
        return bytes(out)


def parse(data: bytes) -> list[dict]:
    """Return per-group {loved, liked, disliked} lists of Entry (missing lists -> [])."""
    try:
        t = GiftTable.parse(data)
    except GiftError:
        return []
    return [{tier: (g.get(tier) or []) for tier in TIERS} for g in t.groups]


CATEGORY_ARCHIVE = 14850   # rf3PresentCategory = the shared cross-ref / gift-category table

# g_itemCategoryRangeTable (baked into the EXE at RF4S.exe+0x4D5918, 12 u16 pairs, re-read
# 2026-09-19): the item-id RANGE wildcards used by target 0x8000..0x80FF (tag = low byte).
# Half-open [min, max). A gift entry of this kind matches ANY item whose id falls in the range.
# tag -> (min, max_exclusive, label).
ITEM_RANGE_TABLE = {
    0:  (134, 300, "sashimi & prepared fish"),
    1:  (985, 1017, "raw fish"),
    2:  (1, 55, "vegetables / crops"),
    3:  (134, 159, "sashimi"),
    4:  (180, 211, "salted fish"),
    5:  (607, 677, "accessories / rings"),
    6:  (48, 55, "mushrooms"),
    7:  (831, 1102, "materials / monster drops"),
    8:  (819, 825, "ores / metals"),
    9:  (318, 327, "medicine & cooking bread"),
    10: (826, 830, "gems"),
    11: (73, 81, "grasses"),
}


def load_categories(cat_data: bytes) -> list[list[Entry]]:
    """Parse rf3PresentCategory (archive 14850) -> its 21 shared gift-category item lists,
    indexed by cross-ref id. An NPC entry whose target is 0x8100+idx (kind='xref', value=idx)
    resolves to categories[idx]. Each group stores its member items in the first of its 3
    offsets (off2/off3 are 0 in the category file)."""
    try:
        t = GiftTable.parse(cat_data)
    except GiftError:
        return []
    return [g.get("disliked") or [] for g in t.groups]     # slot 0 = off1


def category_items(cat_idx: int, categories: list, _seen=None) -> list[int]:
    """Flatten a category's member item ids (recursing into nested xrefs for display; NOTE the
    game itself only matches DIRECT item ids inside a category list). Cycle-guarded: a
    visited-set breaks A->B->A reference loops that edited category files could contain."""
    if not categories or not (0 <= cat_idx < len(categories)):
        return []
    if _seen is None:
        _seen = set()
    if cat_idx in _seen:
        return []
    _seen.add(cat_idx)
    ids = []
    for e in categories[cat_idx]:
        if e.kind == "item":
            ids.append(e.value)
        elif e.kind == "xref" and e.value != cat_idx:
            ids.extend(x for x in category_items(e.value, categories, _seen) if x not in ids)
    return ids


def entry_fp(e: Entry, tier: str) -> int:
    """Signed friendship-point delta this entry grants when gifted (IDA-verified:
    Npc_GetGiftAffinityHashByItemAndCharId + Event_GetThrowReactionStyleBits).  For a cross-ref
    entry the game applies the CATEGORY entry's code instead -- see category_fp()."""
    if tier == "disliked":
        return -10 if e.code == SIGNATURE_DISLIKE_CODE else -5
    c = e.code
    return c - 0x10000 if c >= 0x8000 else c      # loved/liked: the stored code IS the FP (signed)


def category_fp(cat_idx: int, categories: list) -> list[int]:
    """Distinct FP codes carried by a category's direct item entries (what an xref match pays)."""
    if not categories or not (0 <= cat_idx < len(categories)):
        return []
    seen = []
    for e in categories[cat_idx]:
        if e.kind == "item":
            v = e.code - 0x10000 if e.code >= 0x8000 else e.code
            if v not in seen:
                seen.append(v)
    return seen


def _fmt(e: Entry, name_fn=None, categories=None) -> str:
    if e.kind == "item":
        nm = name_fn(e.value) if name_fn else None
        return f"{e.value}" + (f" {nm}" if nm else "")
    if e.kind == "category":
        rng = ITEM_RANGE_TABLE.get(e.value)
        if rng:
            return f"[all {rng[2]} (ids {rng[0]}..{rng[1] - 1})]"
        return f"[item-range #{e.value}]"
    # cross-ref into rf3PresentCategory -> expand to a preview of the group's items
    if categories:
        ids = category_items(e.value, categories)
        preview = ", ".join((name_fn(i) if name_fn else str(i)) for i in ids[:6])
        more = f", +{len(ids) - 6} more" if len(ids) > 6 else ""
        return f"[category #{e.value}: {preview}{more}]"
    return f"[category #{e.value}]"


def render(data: bytes, name_fn=None, categories=None) -> str:
    groups = parse(data)
    if not groups:
        return "(no gift groups)"
    out = []
    for gi, g in enumerate(groups):
        if len(groups) > 1:
            out.append(f"# group {gi}")
        for tier in TIERS:
            items = g[tier]
            out.append(f"{tier} ({len(items)}):")
            for e in items:
                if e.kind == "xref" and tier != "disliked":
                    codes = category_fp(e.value, categories) if categories else []
                    fp_s = ("/".join(f"{c:+d}" for c in codes) + " FP per category entry"
                            if codes else "FP = category entry code")
                else:
                    fp_s = f"{entry_fp(e, tier):+d} FP"
                mark = "   <- signature/hated" if (tier == "disliked"
                                                   and e.code == SIGNATURE_DISLIKE_CODE) else ""
                out.append(f"    {_fmt(e, name_fn, categories)}  ({fp_s}){mark}")
    out.append(f"neutral (unlisted): {NEUTRAL_FP:+d} FP")
    return "\n".join(out)
