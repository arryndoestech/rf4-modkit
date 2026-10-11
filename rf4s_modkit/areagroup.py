"""areagroup.py -- a map's MGRP value: what the game makes of it, and the conflicts to flag.

The MGRP chunk is one u32 (see rf4m's docstring for the chunk). Map_LoadById stores it as the
map task's work[16] and its low nibble as work[15]; the game reads:

    bits 0..3   fixed season (lowest set bit; clear = follow the calendar): ambience, BGM
                variant, the field maps' escape point, the farm's seasonal blocker sprites
    bit 2       also BGM_SetTargetMode(2) instead of 1 (Scene_ApplyContextualBGM)
    bit 4       no weather: no rain / snow (WeatherTask_Tick), the sound task's indoor flag
    bits 5..25  area group: the LOWEST set bit gives the zone = bit - 5 (0 below 0x20;
                Minimap_BuildForMap RF4S.exe+0x13B3F0 -> the minimap task's byte +52). The
                zone picks the base BGM, the minimap group, the crate loot pool and the
                monster gates. With group bit 6 the minimap reads a room sub-group from the
                lowest of bits 22+ (only MAP_F_ROOM_00 sets them).
    bits 26..31 read ONLY when bits 5..25 are all clear: the zone scan (MGRP & ~0x1F) >> 5
                takes the lowest set bit below 26, so bits 26..30 give zones 21..25 and bit 31
                alone gives 26 (Minimap_BuildForMap, Scene_ApplyContextualBGM
                RF4S.exe+0x19AFB0). Those zones read past the 21-entry area BGM table (zones
                21..25 get sound id 0, zone 26 gets 0xFFFCFFFC: no area music), the monster
                gates use encounter rows 21 / 22 -- the Cluck-Cluck Nest and Demon's Den rows,
                so the spawner loads some unrelated archive -- and the crates the default pool.
                With a group bit 5..25 set they are ignored. No shipped map sets them.
    no area bit (all of 5..31 clear): zone 0, the same as bit 5 (Selphia town).

MONSTER GATES (Encounter_TickMonsterSpawnSlots RF4S.exe+0x1E6240): the game does NOT look a
map's Gen file up by name. For a map id 1..869 it takes the zone (map 44 -> 0, 853..857 -> 21,
861..869 -> 22, whatever MGRP says) and loads archive

    map id - encounter_zones[zone].first_map + encounter_zones[zone].first_archive

(refdata rf4s_exe_tables.json; zones 24..26 read the 3 pairs after the 24-row table, whose
archive half is 0); a zone whose archive is 0 spawns no gates. The map id is the BASE id (a
seasonal variant counts as its base map); the MGRP is the one of the file the game loads (a
seasonal file's own). A room whose area group runs past its zone's run of tables loads
ANOTHER room's table: shipped, MAP_DUNG_I13 / I14 load GenJ01 / GenJ02.bin (Idra Cave) and
MAP_DUNG_N41..N43 load GenO01..O03.bin (Cluck-Cluck Nest) -- I14, N42 and N43 get live gates
from those files. gen_file() names the file the game really loads (exesidecars.archive_name);
the FIELD_100..110 / A0..A3 tables are GenField99_100..110.bin, and GenQ10.bin lies in no
zone's run (never loaded).
"""
from __future__ import annotations

import re

from . import chestloot, exesidecars, map_names

SEASONS = ("spring", "summer", "autumn", "winter")
NO_WEATHER = 0x10
GROUP_BITS = range(5, 26)
_SEASON_SUFFIX = re.compile(r"_(SPRING|SUMMER|AUTUMN|FALL|WINTER)$", re.I)

# what each area-group bit is, and the in-game area of its maps
GROUP_LABELS = {
    5: "Selphia town", 6: "rooms / interiors", 7: "the farm", 8: "fields around Selphia",
    9: "DUNG_A Yokmir Forest", 10: "DUNG_B Water Ruins", 11: "DUNG_C Obsidian Mansion",
    12: "DUNG_D Leon Karnak", 13: "DUNG_E Floating Empire", 14: "DUNG_F World of Fields",
    15: "DUNG_G Yokmir Cave", 16: "DUNG_H Delirium Lava Ruins", 17: "DUNG_I Forest of Beginnings",
    18: "DUNG_J Idra Cave", 19: "DUNG_K Maya Road", 20: "DUNG_L Sechs Territory",
    21: "DUNG_M Rune Prana", 22: "farm-house rooms", 23: "farm-house / barn rooms",
    24: "(unused)", 25: "DUNG_O / DUNG_P",
}


def zone_of_mgrp(mgrp):
    """The zone the game derives from MGRP: lowest set bit of (MGRP >> 5), 0 below 0x20;
    None without an MGRP."""
    if mgrp is None:
        return None
    v = (mgrp & 0xFFFFFFFF) & ~0x1F
    b = v >> 5 if v >= 0x20 else 5
    return next((i for i in range(26) if b >> i & 1), 26)


def season_of(mgrp):
    """'spring'..'winter' for the fixed season the game uses (the lowest bit), or None."""
    v = (mgrp or 0) & 0xF
    return next((SEASONS[i] for i in range(4) if v >> i & 1), None)


def group_bits(mgrp):
    return [b for b in GROUP_BITS if (mgrp or 0) >> b & 1]


# ---- monster gates ---------------------------------------------------------------------- #
def gate_zone(map_id, mgrp):
    """The zone the gate spawner uses for `map_id` (its base id), or None when it spawns no
    gates there at all (map ids outside 1..869)."""
    if map_id is None or not 1 <= map_id <= 869:
        return None
    if map_id == 44:
        return 0
    if 861 <= map_id <= 869:
        return 22
    if 853 <= map_id <= 857:
        return 21
    return zone_of_mgrp(mgrp)


def _zone_rows():
    """The 24 encounter-table rows, then the 3 pairs the game reads past them (zones 24..26)."""
    return ([tuple(r) for r in chestloot.tables()["encounter_zones"]["rows"]]
            + exesidecars.zone_overrun_rows())


def gen_archive(map_id, mgrp):
    """The Gen archive id the game loads for this map, or None (no gates)."""
    z = gate_zone(map_id, mgrp)
    rows = _zone_rows()
    if z is None or z >= len(rows) or not rows[z][1]:
        return None
    first_map, first_arc = rows[z]
    return map_id - first_map + first_arc


def gen_file(map_id, mgrp):
    """The file name of the Gen archive the game loads for this (base) map id with this MGRP,
    or None (no gates, or an archive outside the gate tables' reach)."""
    return exesidecars.archive_name(gen_archive(map_id, mgrp))


def own_archive(map_id):
    """The archive in whose zone run `map_id` owns the slot (its OWN table), or None."""
    if map_id is None:
        return None
    for arc, first, n in gen_ranges():
        if first <= map_id < first + n:
            return arc + map_id - first
    return None


LAST_ZONE_MAPS = 9          # the highest range (maps 861..869) has no next row to end it


def gen_ranges():
    """[(first archive, first map id, count)] of the Gen archives, in archive order: each zone's
    run of tables ends where the next zone's starts."""
    rows = sorted((arc, first) for first, arc in _zone_rows() if arc)
    out = []
    for i, (arc, first) in enumerate(rows):
        n = rows[i + 1][0] - arc if i + 1 < len(rows) else LAST_ZONE_MAPS
        out.append((arc, first, n))
    return out


def archive_owner(archive):
    """The map id whose own table archive `archive` is, or None when it lies outside every
    zone's run of Gen tables (then it is not a monster-gate table at all)."""
    if archive is None:
        return None
    for arc, first, n in gen_ranges():
        if arc <= archive < arc + n:
            return archive - arc + first
    return None


def family_of(name):
    """The room family of a map file: 'MAP_DUNG_B' for MAP_DUNG_B10, 'MAP_FIELD', 'MAP_CITY',
    'MAP_F_ROOM' ... (seasonal copies belong to their base); None for one-offs and the
    DUMMY / NULL placeholders."""
    stem = str(name).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = _SEASON_SUFFIX.sub("", re.sub(r"\.rf4m$", "", stem, flags=re.I))
    m = re.match(r"(MAP_(?:DUNG_[A-Z]+|[A-Z_]+?))_?\d", stem, flags=re.I)
    if not m or re.search(r"DUMMY|NULL", m.group(1), re.I):
        return None
    return m.group(1).upper()


def base_map_id(name):
    """The map id the game keeps for a map file: a seasonal variant's base (ids < 64 get the
    season added at load), else the file's own id."""
    stem = str(name).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = re.sub(r"\.rf4m$", "", stem, flags=re.I)
    base = _SEASON_SUFFIX.sub("", stem)
    for cand in (base, stem):
        mid = map_names.map_id_for_file(cand)
        if mid is not None:
            return mid
    return None


def fitting_groups(map_id):
    """The area-group bits whose zone makes the gate spawner load this map's OWN table."""
    out = []
    for b in GROUP_BITS:
        arc = gen_archive(map_id, 1 << b)
        if arc is not None and archive_owner(arc) == map_id:
            out.append(b)
    return out


# the game's own maps without an area-group bit (all 872 scanned 2026-09-27): the two airship
# rooms and the travel waiting room are played as they are, the rest are placeholders
SHIPPED_WITHOUT_AREA = ("MAP_ROOM_25", "MAP_ROOM_26", "MAP_TRAVEL_WAITING_ROOM")


def _placeholder(map_name):
    """True for the maps the game itself ships without an area-group bit (placeholders --
    MAP_DUMMY_*, MAP_NULL, MAP_SYSTEM_*, the F_ROOM_DUMMY rooms -- and SHIPPED_WITHOUT_AREA):
    zone 0 is how the game has them, not worth a warning."""
    if map_name is None:
        return False
    stem = _SEASON_SUFFIX.sub("", re.sub(r"\.rf4m$", "", str(map_name).replace("\\", "/")
                                          .rsplit("/", 1)[-1], flags=re.I)).upper()
    return stem in SHIPPED_WITHOUT_AREA or re.search(r"DUMMY|NULL|SYSTEM", stem) is not None


def _entries(n):
    return f"{n} gate entr{'y' if n == 1 else 'ies'}"


def _map_label(mid):
    f = map_names.map_file(mid)
    name = map_names.map_name(mid)
    return f"{f or f'map {mid}'}" + (f" ({name})" if name and name != "???" else "")


def _fix_hint(mid):
    bits = fitting_groups(mid)
    if not bits:
        return ""
    shown = ", ".join(f"bit {b} {GROUP_LABELS.get(b, '')}".rstrip() for b in bits[:3])
    more = f" or {len(bits) - 3} more" if len(bits) > 3 else ""
    return f" To load its own table, set Area to {shown}{more}."


# ---- explanation + conflicts ------------------------------------------------------------ #
def effects(mgrp, map_name=None, gen_name_for=None):
    """[(what, value)] the game derives from this MGRP (for the Map tab). `gen_name_for(map
    id)` names a map's Gen file (the editor passes its own naming)."""
    v = (mgrp or 0) & 0xFFFFFFFF
    zone = zone_of_mgrp(v)
    out = []
    if zone >= 21:
        out.append(("Area", f"zone {zone} from bit {zone + 5}: bits 5-25 are all clear, so the "
                            f"game takes the lowest of bits 26-31"))
    sid = chestloot.area_bgm(zone)
    if sid is not None:
        try:
            from . import soundtable
            out.append(("Music", soundtable.sound_label(sid) or f"sound 0x{sid:X}"))
        except Exception:
            out.append(("Music", f"sound 0x{sid:X}"))
    else:
        bad = exesidecars.area_bgm_overrun(zone)
        if bad is not None:
            out.append(("Music", f"none -- zone {zone} is past the 21-entry area music table "
                                 f"(the game reads sound id 0x{bad:X})"))
    pools = chestloot.crate_pools(zone)
    out.append(("Crate loot", " / ".join(f"{p['label']} {p['share']:.0%}" if p["share"] < 1
                                          else p["label"] for p in pools) + " pool"))
    if map_name is not None:
        mid = base_map_id(map_name)
        arc = gen_archive(mid, v)
        if arc is None:
            out.append(("Monster gates", "none (this area group spawns no gates)"
                        if mid is not None and 1 <= mid <= 869 else "none"))
        else:
            owner = archive_owner(arc)
            fn = exesidecars.archive_name(arc) if owner is not None else None
            if fn is None and gen_name_for and owner is not None:
                fn = gen_name_for(owner)
            own = owner == mid
            out.append(("Monster gates", (fn or f"archive {arc}")
                        + ("" if own else f" -- {_map_label(owner)}'s table, not this map's"
                           if owner is not None else " -- not a monster-gate table")))
    out.append(("Minimap", f"group {zone}"))
    return out


def _area_bits(zone):
    """Music / crate pool / minimap of a zone, for comparing two zones."""
    sid = chestloot.area_bgm(zone)
    try:
        from . import soundtable
        music = (soundtable.sound_label(sid) or f"sound 0x{sid:X}") if sid is not None else None
    except Exception:
        music = f"sound 0x{sid:X}" if sid is not None else None
    pools = " / ".join(p["label"] for p in chestloot.crate_pools(zone))
    return music, pools


def family_note(mgrp, map_name, sibling_zones):
    """('INFO', message) when this map's area group differs from the one every other room of
    its family uses (`sibling_zones` = Counter of the siblings' zones, this map excluded), or
    None. Only families whose rooms all agree are compared -- the shipped dungeons, fields,
    farm, rooms each use one group."""
    fam = family_of(map_name) if map_name else None
    zs = {z for z, n in (sibling_zones or {}).items() if n > 0}
    if fam is None or mgrp is None or len(zs) != 1:
        return None
    zone, usual = zone_of_mgrp(mgrp), next(iter(zs))
    if zone == usual:
        return None
    (m1, c1), (m0, c0) = _area_bits(zone), _area_bits(usual)
    diffs = []
    if m1 != m0:
        diffs.append(f"music {m1} instead of {m0}")
    if c1 != c0:
        diffs.append(f"crates roll the {c1} pool instead of {c0}")
    diffs.append(f"minimap group {zone} instead of {usual}")
    return ("INFO", f"the other {fam} rooms use area group bit {usual + 5} "
                    f"({GROUP_LABELS.get(usual + 5, '?')}); with bit {zone + 5} this room has "
                    + ", ".join(diffs))


def problems(mgrp, map_name=None, gen_entries=None, gen_name_for=None, gen_entries_for=None,
             sibling_zones=None):
    """[(severity, message)] for this MGRP. `gen_entries` = the number of gate entries in this
    map's OWN Gen table (the one in its zone's run; None: none); `gen_name_for(map id)` names a
    map's own table; `gen_entries_for(file name)` =
    the entry count of another Gen file (None: absent); `sibling_zones` = the zones of the
    other rooms of this map's family (see family_note). Severity 'WARN' (loads, but not as
    probably meant) or 'INFO'; nothing here stops the game from loading."""
    out = []
    if map_name is not None and base_map_id(map_name) is None:
        out.append(("WARN", f"{re.sub(r'[.]rf4m$', '', str(map_name), flags=re.I)} is not one of "
                            f"the game's map files: the game never loads it, so a copy saved "
                            f"to the game folder has no effect in game"))
    if mgrp is None:
        return out
    note = family_note(mgrp, map_name, sibling_zones)
    if note:
        out.append(note)
    v = mgrp & 0xFFFFFFFF
    seasons = [SEASONS[i] for i in range(4) if v >> i & 1]
    if len(seasons) > 1:
        out.append(("WARN", f"several fixed-season bits ({'+'.join(seasons)}): the game uses "
                            f"only {seasons[0]} (the lowest)"))
    if map_name is not None and seasons:
        m = _SEASON_SUFFIX.search(re.sub(r"\.rf4m$", "", str(map_name), flags=re.I))
        if m:
            file_season = {"FALL": "autumn"}.get(m.group(1).upper(), m.group(1).lower())
            if seasons[0] != file_season:
                out.append(("WARN", f"the {file_season} file fixes the season to {seasons[0]}: "
                                    f"in {file_season} the game loads this file but plays "
                                    f"{seasons[0]} ambience and music"))
    groups = group_bits(v)
    extra = groups[1:]
    if extra and not (groups[0] == 6 and all(b >= 22 for b in extra)):
        out.append(("WARN", f"several area-group bits ({', '.join(map(str, groups))}): the game "
                            f"uses only bit {groups[0]} ({GROUP_LABELS.get(groups[0], '?')})"))
    zone = zone_of_mgrp(v)
    if v >> 26 and groups:
        out.append(("WARN", f"bits 26-31 set (0x{v & 0xFC000000:X}): ignored while an area-group "
                            f"bit 5-25 is set (bit {groups[0]} wins)"))
    elif v >> 26:
        gates = {21: "the Cluck-Cluck Nest row", 22: "the Demon's Den row"}.get(zone)
        out.append(("WARN", f"no area-group bit 5-25, so the game takes bit {zone + 5} "
                            f"(bits 26-31 = 0x{v & 0xFC000000:X}) as the area: zone {zone}, past "
                            f"the end of the area tables -- no area music, the default crate "
                            f"pool, minimap group {zone}, and "
                            + (f"the monster gates come from {gates} of the encounter table, "
                               f"i.e. some unrelated file" if gates else "no monster gates")
                            + ". Pick an Area (bits 5-25) instead"))
    elif not v & ~0x1F and not _placeholder(map_name):
        out.append(("WARN", "no area-group bit: the game treats the map as zone 0 (Selphia "
                            "town): town music, minimap group 0, the default crate pool and no "
                            "monster gates. Pick an Area if the map belongs somewhere else"))
    if map_name is None:
        return out
    mid = base_map_id(map_name)
    if mid is None or not 1 <= mid <= 869:
        return out
    arc = gen_archive(mid, v)
    own_fn = gen_name_for(mid) if gen_name_for else None
    if arc is None:
        if gen_entries:
            out.append(("WARN", f"this area group (zone {zone_of_mgrp(v)}) spawns no monster "
                                f"gates: the {_entries(gen_entries)} in {own_fn or 'this map’s Gen file'} "
                                f"never {'appears' if gen_entries == 1 else 'appear'}.{_fix_hint(mid)}"))
        return out
    owner = archive_owner(arc)
    if owner == mid:
        return out
    if owner is None:
        # the sum lands outside every zone's run of Gen tables: the spawner loads a file that
        # is not an encounter table at all
        out.append(("WARN", f"with this area group (zone {gate_zone(mid, v)}) the gate spawner "
                            f"loads archive {arc}"
                            + (f" ({exesidecars.archive_name(arc)})" if exesidecars.archive_name(arc) else "")
                            + f", which is not a monster-gate table.{_fix_hint(mid)}"))
        return out
    other_fn = exesidecars.archive_name(arc) or (gen_name_for(owner) if gen_name_for else None)
    other_n = gen_entries_for(other_fn) if (gen_entries_for and other_fn) else None
    if not gen_entries and other_n:
        # shipped: MAP_DUNG_I14 -> GenJ02, N42 / N43 -> GenO02 / O03 (the map editor opens
        # that file for this room, so editing it here changes both rooms)
        out.append(("INFO", f"this room has no gates of its own: with this area group (zone "
                            f"{gate_zone(mid, v)}) the game loads {other_fn}, the table of "
                            f"{_map_label(owner)}, and its {_entries(other_n)} spawn"
                            f"{'s' if other_n == 1 else ''} here too -- the Gates tab shows that "
                            f"file, and edits to it change both rooms"))
    if gen_entries:
        # (only when this map's own table has gates: a few shipped rooms point past their
        # area's tables, harmlessly, because they have none)
        msg = (f"wrong monster gates: with this area group the game loads "
               f"{other_fn or f'archive {arc}'}, the table of {_map_label(owner)}, instead of "
               f"{own_fn or 'this map’s own Gen file'}. The {_entries(gen_entries)} in {own_fn or 'it'} "
               f"never {'appears' if gen_entries == 1 else 'appear'}")
        if other_n:
            msg += f"; that room's {_entries(other_n)} spawn{'s' if other_n == 1 else ''} here instead"
        out.append(("WARN", msg + "." + _fix_hint(mid)))
    return out
