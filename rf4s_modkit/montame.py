"""rf4s_modkit/montame.py -- monster taming-food preferences (`rf3MonsterPresent.bin`, archive 14849).

When you give a wild monster an item to tame it, each item that species "prefers" adds a bonus
to the tame-success roll. This table holds those preferences.  Read + edit (in place).

IDA-verified layout (re-read 2026-09-19: `Monster_GetTamePreferenceFromArchive` RF4S.exe+0x96EA0,
consumed by `MonsterTame_RollAttemptWithItem` RF4S.exe+0x96F30):
  - NO header; flat array indexed by **species_id - 48** (the reader rejects species-48 > 0xCD,
    i.e. valid species 48..253; 6688 B = 209 rows).
  - 32 bytes per species = **4 entries** of 8 bytes: `[item_id:u32][tame_bonus:u16][pad:u16]`.
  - Lookup scans the 4 entries in order and returns the FIRST matching item's `tame_bonus`,
    else 0 (neutral). item_id 0 = empty slot (never matches: the reader masks the fed item
    with 0x7FF, so a real item is 1..2047).

How the bonus is used (`MonsterTame_RollAttemptWithItem`, read statically 2026-09-19; the roll
succeeds when `chance >= (rand & 0x7F)`, so HIGHER chance = EASIER):
    chance = 2 * tame_base                    (monster stats+218, from the rf3NpcParam template)
    if pref:  chance = pref + 2 * chance      (pref = this table's bonus for the fed item)
    if the monster is a boss-food monster (actor flags & 0x800) and pref == 0: refuse (-1)
    item CATEGORY (rf3ItemList +4) modifier, applied to ALL species:
        category 4  (Failed Dish 132 / Disastrous Dish 133)       -> chance >>= 1   (HURTS)
        category 5..14 (sashimi, fried, boiled, baked, juices, steamed, salads, rice/chocolate/
                        wine, milk & eggs, seasonings = cooked / prepared food)  -> chance += 32 (HELPS)
        everything else (raw crops, materials, ...)               -> unchanged
    lucky day ((g_dailyRngScrambleAndStateFlags & 0xF) == 5): chance += 32
    chance = (pet_count + 4 * hit_count + item_level + chance) >> min(same_species_tamed, 4), min 1
    level gap (monster level - player level, if > 0, species != 82/113): chance >>= gap >> 1
    roll: chance >= (rand & 0x7F) -> tamed (192), else fail reaction 24..179
So the per-species bonus is **per-species, NOT universal**: an item only helps a monster that
lists it (e.g. Onigiri 295 is listed for Goblin 52 / Hobgoblin 53 only), while the cooked-food
+32 / failed-dish halving applies to every monster.  (The previous docstring had the category
labels backwards -- "cat 4 = cooked food vs 5..14 = raw materials" -- and left the direction
open; both are settled by the category table and the `>=` comparison above.)
"""
from __future__ import annotations

import struct

STRIDE = 32          # bytes per species (4 * 8)
FIRST_SPECIES = 48   # record 0 = species 48
LAST_SPECIES = 253   # game rejects species > 253 (a1-48 > 0xCD)
ENTRIES = 4
ENTRY_SIZE = 8
COOKED_FOOD_CATEGORIES = range(5, 15)   # rf3ItemList +4 categories that add +32 to the roll
FAILED_DISH_CATEGORY = 4                # halves the roll


def species_count(data: bytes) -> int:
    return len(data) // STRIDE


def _base(data_len: int, species_id: int) -> int:
    if not (FIRST_SPECIES <= species_id <= LAST_SPECIES):
        raise IndexError(f"species {species_id} outside {FIRST_SPECIES}..{LAST_SPECIES}")
    base = STRIDE * (species_id - FIRST_SPECIES)
    if base + STRIDE > data_len:
        raise IndexError(f"species {species_id} beyond the end of the table")
    return base


def slots(data: bytes, species_id: int) -> list[tuple[int, int]]:
    """All 4 raw slots [(item_id, tame_bonus)] of a species, empty slots included as (0, x)."""
    try:
        base = _base(len(data), species_id)
    except IndexError:
        return []
    return [struct.unpack_from("<IH", data, base + k * ENTRY_SIZE) for k in range(ENTRIES)]


def prefs(data: bytes, species_id: int) -> list[tuple[int, int]]:
    """[(item_id, tame_bonus)] for a species (48..253); empty slots (item 0) dropped."""
    return [(item, bonus) for item, bonus in slots(data, species_id) if item]


def set_pref(buf: bytearray, species_id: int, slot: int, item_id: int, bonus: int) -> None:
    """Edit one of a species' 4 tame-food slots in place (item 0 = empty)."""
    if not (0 <= slot < ENTRIES):
        raise IndexError("slot out of range (0..3)")
    if not (0 <= int(item_id) <= 0x7FF):
        raise ValueError("item id must be 0..2047 (the reader masks the fed item with 0x7FF)")
    o = _base(len(buf), species_id) + slot * ENTRY_SIZE
    struct.pack_into("<IH", buf, o, int(item_id), int(bonus) & 0xFFFF)   # pad u16 left as-is


def clear_pref(buf: bytearray, species_id: int, slot: int) -> None:
    """Empty one slot (item 0, bonus 0)."""
    set_pref(buf, species_id, slot, 0, 0)


def find_slot(data: bytes, species_id: int, item_id: int) -> int | None:
    """Index of the first slot listing item_id (what the game's lookup returns), else None."""
    for k, (item, _b) in enumerate(slots(data, species_id)):
        if item == item_id:
            return k
    return None


def set_item(buf: bytearray, species_id: int, item_id: int, bonus: int) -> int:
    """Give a species a preference for item_id: reuse its existing slot, else the first empty
    one. Returns the slot used; raises ValueError when all 4 slots are taken."""
    k = find_slot(buf, species_id, item_id)
    if k is None:
        k = find_slot(buf, species_id, 0)
    if k is None:
        raise ValueError(f"species {species_id}: all {ENTRIES} tame-food slots are in use")
    set_pref(buf, species_id, k, item_id, bonus)
    return k


def remove_item(buf: bytearray, species_id: int, item_id: int) -> bool:
    """Drop every slot listing item_id. Returns True if something was removed."""
    hit = False
    for k, (item, _b) in enumerate(slots(buf, species_id)):
        if item == item_id:
            clear_pref(buf, species_id, k)
            hit = True
    return hit


def render(data: bytes, name_fn=None, species_name_fn=None) -> str:
    lines = []
    for sid in range(FIRST_SPECIES, min(FIRST_SPECIES + species_count(data), LAST_SPECIES + 1)):
        p = prefs(data, sid)
        if not p:
            continue
        sp = species_name_fn(sid) if species_name_fn else ""
        items = ", ".join(f"{(name_fn(i) if name_fn else i)}(+{b})" for i, b in p)
        lines.append(f"species {sid:>3} {sp:<16} {items}")
    return "\n".join(lines)
