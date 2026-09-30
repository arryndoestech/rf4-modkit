"""Game-data lookups the map editor needs besides the map itself: where the extracted
files are, the map-id table, a map's search-item / encounter sidecar files, item /
monster / character names, MapOre_Rate configs and the NPCs an event script spawns.

Everything is loaded lazily and cached once per process (these tables never change
while the editor runs)."""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import struct

from rf4s_modkit import chestloot, gamepaths, gen, map_names, mobj_types, script, textdb
from rf4s_modkit.refdata import refdata_path

BUNDLE_DIR = gamepaths.bundle_dir()              # the game copy (rf4s_modkit.gamepaths)
EXTRACTED = gamepaths.extracted_dir(BUNDLE_DIR)
ROOMS_CSV_CANDIDATES = [
    pathlib.Path(__file__).resolve().parent.parent / "refdata" / "rf4s_rooms.csv",
]
SEASON_RE = re.compile(r"_(SPRING|SUMMER|AUTUMN|FALL|WINTER)$", re.I)


def map_base(name):
    """'bundleMain/MAP_CITY_02.rf4m' or 'C:\\x\\MAP_CITY_02' -> 'MAP_CITY_02'."""
    bare = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.rf4m$", "", bare, flags=re.I)


# ---- the extracted tree ---------------------------------------------------- #
_EXTRACTED_INDEX = None


def extracted_index():
    """{lower-case basename: [Path, ...]} of every file under EXTRACTED, built once
    (~0.2 s for ~38k files). First hit in sorted walk order wins."""
    global _EXTRACTED_INDEX
    if _EXTRACTED_INDEX is None:
        idx = {}
        if EXTRACTED.is_dir():
            for dirpath, dirnames, filenames in os.walk(EXTRACTED):
                dirnames.sort()
                for fn in sorted(filenames):
                    idx.setdefault(fn.lower(), []).append(pathlib.Path(dirpath) / fn)
        _EXTRACTED_INDEX = idx
    return _EXTRACTED_INDEX


def find_extracted(name):
    """Path of an extracted file by basename (case-insensitive), or None."""
    hits = extracted_index().get(str(name).lower())
    return hits[0] if hits else None


def find_extracted_all(name):
    """Every extracted file with this basename (several bundles can carry one)."""
    return list(extracted_index().get(str(name).lower(), ()))


_READERS = {}


def folder_reader(folder):
    """reader(filename) -> bytes | None: the map's own folder first, then anywhere in the
    extracted tree (a map's textures can ship in another bundle). One reader per folder,
    so the editor's texture caches survive switching between maps of the same folder."""
    d = pathlib.Path(folder)
    if d not in _READERS:
        def read(fn, d=d):
            p = d / fn
            if p.is_file():
                return p.read_bytes()
            hit = find_extracted(fn)
            return hit.read_bytes() if hit is not None else None
        _READERS[d] = read
    return _READERS[d]


# ---- map ids ------------------------------------------------------------- #
_ROOMS = None


def load_rooms():
    """{MAP_* name: (map id, resource id | None)} for every map (read-only, cached).

    Prefers rf4s_rooms.csv (it also carries the resource id); otherwise the modkit's
    vendored map table (map_names.map_file), which has the same name <-> id pairs."""
    global _ROOMS
    if _ROOMS is not None:
        return _ROOMS
    for p in ROOMS_CSV_CANDIDATES:
        if p.is_file():
            out = {}
            with p.open(encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    try:
                        out[row["name"]] = (int(row["mapId"]), int(row["resourceId"]))
                    except (KeyError, ValueError):
                        pass
            if out:
                _ROOMS = out
                return out
    out = {}
    for mid in range(map_names.map_count() + 1):
        fn = map_names.map_file(mid)
        if fn:
            out[fn] = (mid, None)
    _ROOMS = out
    return out


_ROOMS_BY_ID = None


def rooms_by_id():
    """{map id: MAP_* name}."""
    global _ROOMS_BY_ID
    if _ROOMS_BY_ID is None:
        _ROOMS_BY_ID = {mid: name for name, (mid, _r) in load_rooms().items()}
    return _ROOMS_BY_ID


def map_id(name):
    """Map id of a map name (seasonal variants fall back to their base), or None."""
    rooms = load_rooms()
    base = map_base(name)
    for cand in (base, SEASON_RE.sub("", base)):
        if cand in rooms:
            return rooms[cand][0]
    return None


def base_map_id(name):
    """The id the game keeps for a map name: a seasonal copy's base (ids 4..63 come as base,
    _SUMMER, _AUTUMN, _WINTER, and the game adds the calendar season at load), else the map's
    own id; None when unknown. Warp destinations, the minimap record and the night tint
    default are all looked up by this id."""
    from rf4s_modkit import mapres
    return mapres.base_id(map_id(name))


_MAPS_BY_ID = {}


def load_map_by_id(mid):
    """The .rf4m of map id `mid` from the game folder (an Rf4mMap, cached until the file
    changes), or None when it is not there or unreadable. Validation reads warp destinations
    through this."""
    from rf4s_modkit import rf4m
    name = rooms_by_id().get(mid)
    p = find_extracted(name + ".rf4m") if name else None
    if p is None:
        return None
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if _MAPS_BY_ID.get(mid, (None,))[0] != key:
            _MAPS_BY_ID[mid] = (key, rf4m.Rf4mMap.load(p))
    except Exception:  # noqa: BLE001 - unreadable: no destination checks
        return None
    return _MAPS_BY_ID[mid][1]


SEASON_FOLLOWS = "(season follows the calendar)"


def map_choice(mid):
    """Dropdown label for a map id: '36 - MAP_CITY_03  (Selphia)  (season follows the calendar)'.
    A seasonal family's base id (4, 8 .. 60) is marked: as a warp destination it loads the
    copy of the current season."""
    name = rooms_by_id().get(mid)
    if name is None:
        return f"{mid} - <unknown map>"
    place, _bld = map_names.describe_destination(mid)
    return (f"{mid} - {name}" + (f"  ({place})" if place else "")
            + (f"  {SEASON_FOLLOWS}" if mid in map_names.SEASONAL_MAP_IDS and mid % 4 == 0 else ""))


_WARP_CHOICES = None


def warp_choices():
    """Warp-destination dropdown entries: every map id, except that a seasonal family is
    offered once, by its base id (the game adds the calendar season to ids below 64, so a
    warp must name the base; a seasonal copy's own id loads the wrong file), and the
    MAP_NULL / DUMMY placeholders 0..3 are left out."""
    global _WARP_CHOICES
    if _WARP_CHOICES is None:
        _WARP_CHOICES = [map_choice(i) for i in sorted(rooms_by_id())
                         if i >= 4 and not (i < 64 and i % 4)]
    return _WARP_CHOICES


def leading_int(text):
    """First token of a dropdown entry as an int ('31 - MAP_..', '0x1F', '52  Goblin')."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        return int(t.split()[0], 0)
    except ValueError:
        return None


# ---- sidecar files ------------------------------------------------------- #
# The game never looks a map's search-item (SI_*.bin) or monster-gate (Gen*.bin) file up by
# name: SI comes from a per-map-id table in RF4S.exe, Gen from the map's zone (its MGRP) and
# the zone's run of archives (rf4s_modkit.exesidecars / areagroup, shipped in refdata). These
# helpers apply the same rules, with the room's BASE map id (a seasonal variant shares its
# base's files) and, for Gen, the MGRP of the file the game loads.
def _mgrp_of(name):
    """The MGRP of map file `name` as the game folder has it (map_summaries), or None."""
    want = map_base(name).upper()
    for stem, (mgrp, _ch, _wh) in map_summaries().items():
        if stem.upper() == want:
            return mgrp
    return None


def gen_name_for_map(name, mgrp=None):
    """The Gen*.bin the game loads for map file `name`: its base id's slot in the zone its
    MGRP picks (default: the MGRP of the game folder's copy; without one, the map's own
    table). None when the game spawns no gates there. This can be ANOTHER room's table:
    MAP_DUNG_I14 loads GenJ02.bin, MAP_FIELD_100 GenField99_100.bin."""
    from rf4s_modkit import areagroup
    mid = areagroup.base_map_id(name)
    if mid is None:
        return None
    if mgrp is None:
        mgrp = _mgrp_of(name)
    if mgrp is None and areagroup.gate_zone(mid, None) is not None:
        mgrp = 0                                # maps 44 / 853..857 / 861..869: fixed zone
    if mgrp is None:
        return gen_name_for_id(mid)
    return areagroup.gen_file(mid, mgrp) if areagroup.archive_owner(
        areagroup.gen_archive(mid, mgrp)) is not None else None


def gen_file_for_map(name, mgrp=None):
    fn = gen_name_for_map(name, mgrp)
    return find_extracted(fn) if fn else None


def gen_name_for_id(map_id):
    """The Gen*.bin that is map id `map_id`'s OWN table (its slot in its zone's run of
    archives), or None."""
    from rf4s_modkit import areagroup, exesidecars
    return exesidecars.archive_name(areagroup.own_archive(map_id))


def gen_entry_count(table):
    """Gate entries in a GenTable (None: no table)."""
    return None if table is None else sum(len(p) for p in table.patterns)


_GEN_COUNTS = {}


def gen_entries(fn):
    """Gate entries in the Gen file `fn` found in the game folder (None: absent or
    unreadable); cached per file until it changes."""
    p = find_extracted(fn) if fn else None
    if p is None:
        return None
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _GEN_COUNTS:
        try:
            _GEN_COUNTS[key] = gen_entry_count(gen.GenTable.load(p))
        except Exception:  # noqa: BLE001 - a damaged table: no count
            _GEN_COUNTS[key] = None
    return _GEN_COUNTS[key]


def own_gen_entries(doc):
    """Gate entries in the OWN Gen table of the map open in `doc` (its unsaved edits when the
    editor has that table open), for areagroup.problems; None without one."""
    from rf4s_modkit import areagroup
    own = gen_name_for_id(areagroup.base_map_id(doc.base)) if doc.base else None
    if own is None:
        return None
    if doc.gen is not None and doc.gen_path is not None and doc.gen_path.name.lower() == own.lower():
        return gen_entry_count(doc.gen)
    return gen_entries(own)


def _base_first(hits, owner=None):
    """Map names sorted: the owner's base file first, then the other bases, each followed by
    its seasonal variants."""
    from rf4s_modkit import areagroup
    return sorted(hits, key=lambda n: (areagroup.base_map_id(n) != owner,
                                       SEASON_RE.sub("", map_base(n)),
                                       SEASON_RE.search(map_base(n)) is not None, map_base(n)))


def maps_for_gen(gen_name, candidates):
    """The maps (from `candidates`, map file names) whose monster gates come from `gen_name`
    by the game's rule (gen_name_for_map), the owner's base map first, then its seasonal
    variants, then any other room that loads the same table."""
    from rf4s_modkit import areagroup
    want = map_base(gen_name).rsplit(".", 1)[0].lower() + ".bin"
    mgrps = {stem.upper(): mg for stem, (mg, _ch, _wh) in map_summaries().items()}
    hits = [n for n in candidates
            if (gen_name_for_map(n, mgrps.get(map_base(n).upper())) or "").lower() == want]
    owner = next((m for m in map(areagroup.base_map_id, hits)
                  if (gen_name_for_id(m) or "").lower() == want), None)
    return _base_first(hits, owner)


def si_name_for_map(name):
    """The SI_*.bin the game loads for map file `name` (by its base map id, from the game's
    table: MAP_CITY_05 -> SI_CITY_06.bin, MAP_FIELD_A0 -> SI_FIELD_101.bin), or None when
    the game never rolls search items there (MAP_CITY_06, MAP_DUNG_E45, ...)."""
    from rf4s_modkit import areagroup, exesidecars
    return exesidecars.si_name(areagroup.base_map_id(name))


def si_file_for_map(name):
    fn = si_name_for_map(name)
    return find_extracted(fn) if fn else None


def maps_for_si(si_name, candidates):
    """The maps (from `candidates`) whose search items come from `si_name`."""
    want = map_base(si_name).lower()
    return _base_first([n for n in candidates if (si_name_for_map(n) or "").lower() == want])


def also_used_by(part, fn, name):
    """The OTHER rooms (base map files, this map's own seasonal variants left out -- they
    share on purpose) whose game-loaded side file is `fn`: part 'gen' by the gate rule over
    the game folder's maps, 'si' from the search-item table."""
    from rf4s_modkit import areagroup, exesidecars
    if not fn:
        return []
    me = areagroup.base_map_id(name) if name else None
    if part == "si":
        ids = {areagroup.base_map_id(map_names.map_file(m) or "") for m in exesidecars.si_maps(fn)}
    else:
        ids = {areagroup.base_map_id(n) for n in maps_for_gen(fn, list(map_summaries()))}
    return sorted({map_names.map_file(m) or f"map {m}" for m in ids if m is not None and m != me})


# ---- names ----------------------------------------------------------------- #
_ITEMS = None


def item_names():
    """{item id: English name}: the game's rf3TxtItem (gamenames), else the built-in list."""
    from rf4s_modkit import gamenames
    return gamenames.table("items")


def item_name(i):
    return item_names().get(i, "")


def chest_loot(rec):
    """What a treasure chest (MOBJ type 44) gives: 'Loot (row N): 3x Recovery Potion', read
    from the game folder's RF4S.exe (rf4s_modkit.chestloot). None for other types."""
    if rec is None or (rec[0] & 0xFFFF) != 44:
        return None
    r = rec[8]
    try:
        slots = chestloot.row(r)
    except chestloot.ChestLootError as e:
        return f"Loot (row {r}): unknown -- {e}"
    if slots is None:
        return f"Loot (row {r}): past the table's {chestloot.ROWS} rows -- no known contents"
    return f"Loot (row {r}): " + chestloot.summary(slots, lambda i: item_name(i) or f"item {i}")


_MAP_SUMMARY = {}


def map_summaries():
    """{MAP_* name: (mgrp, [(entity index, collected flag f13, loot row f8) per chest],
    (grid width, height) or None)} for
    every map in the game folder (the copy the game loads), read once per file change -- all
    872 maps take well under a second."""
    from rf4s_modkit import rf4m
    out = {}
    for low, paths in extracted_index().items():
        if not (low.startswith("map_") and low.endswith(".rf4m")):
            continue
        p = paths[0]
        try:
            st = p.stat()
        except OSError:
            continue
        key = (str(p), st.st_mtime_ns, st.st_size)
        hit = _MAP_SUMMARY.get(str(p))
        if hit is None or hit[0] != key:
            try:
                m = rf4m.Rf4mMap.load(p)
                chests = [(i, r[13], r[8]) for i, r in enumerate(m.mobj_records())
                          if (r[0] & 0xFFFF) == 44]
                g = m.attr_grid()
                hit = (key, (m.mgrp(), chests, (g[0], g[1]) if g else None))
                _MAP_FLAGS[p.stem] = _flag_uses(m.mobj_records(), m.mapj_records())
            except Exception:  # noqa: BLE001 - a damaged map: left out
                hit = (key, (None, [], None))
                _MAP_FLAGS[p.stem] = (set(), [])
            _MAP_SUMMARY[str(p)] = hit
        out[p.stem] = hit[1]
    return out


_MAP_FLAGS = {}         # MAP_* stem -> (zone-2 ids its objects / warps use, one-shot owners)


def _flag_uses(recs, mapj=()):
    """({every zone-2 id the records and warps use}, [(index, type, one-shot flag)])."""
    from rf4s_modkit import mobj_params
    used, owners = set(), []
    for i, r in enumerate(recs):
        tid = r[0] & 0xFFFF
        if mobj_params.reads_flag(tid) and 0 <= r[13] < mobj_params.MOBJ_FLAG_COUNT:
            used.add(r[13])
            if tid == 44 and r[9] & 0xFF:                    # the chest's reveal flag
                used.add(r[13] + ((r[9] & 0xFF) - 256 if r[9] & 0x80 else r[9] & 0xFF))
        fl = mobj_params.one_shot_flag(r)
        if fl is not None:
            owners.append((i, tid, fl))
    for w in mapj:
        if 0 <= w[0] < mobj_params.MOBJ_FLAG_COUNT:
            used.add(w[0])
    return used, owners


def map_flag_uses():
    """{MAP_* stem: (zone-2 ids used, [(index, type, one-shot flag)])} for every map in the
    game folder (read with map_summaries)."""
    stems = set(map_summaries())
    return {k: v for k, v in _MAP_FLAGS.items() if k in stems}


def fresh_flag(recs, mapj, rec, new=False):
    """(new f13, note) for a duplicated / pasted record whose one-shot flag must not be
    shared -- or, `new`, for a record the Add tool creates: the lowest id of the block the
    old flag belongs to (the type's block for a new record, mobj_params.DEFAULT_FLAG_BLOCK)
    that no object or warp uses here (`recs` / `mapj`, unsaved edits included), in this
    map's seasonal copies or on any other map of the game folder. (None, why) when the type
    cannot take just any id (mobj_params.FRESH_FLAG_TYPES), the record has no flag, or the
    block is full. Event scripts are not searched."""
    from rf4s_modkit import mobj_params
    tid = rec[0] & 0xFFFF
    old = rec[13]
    if new:
        block = mobj_params.flag_block(None, tid)
        if block is None:
            return None, "has no flag of its own"
    else:
        if tid not in mobj_params.FRESH_FLAG_TYPES:
            return None, f"keeps its flag {old}"
        if tid == 44 and rec[9] & 0xFF:
            return None, f"keeps its flag {old} (its reveal flag is f13 + f9)"
        if old in (-1, 0):
            return None, "has no flag"
        block = mobj_params.flag_block(old, tid)
        if block is None:
            return None, f"keeps its flag {old} (not in a known flag block)"
    used, _own = _flag_uses(recs, mapj)
    for _stem, (u, _o) in map_flag_uses().items():
        used |= u
    for f in range(block[0], block[1] + 1):
        if f not in used:
            return f, f"got the unused flag {f}"
    return None, f"keeps its flag: every id {block[0]}..{block[1]} is in use"


def sibling_zones(name):
    """Counter of the area-group zones of the other rooms of this map's family (areagroup.
    family_of), from the game folder; this file itself left out."""
    from collections import Counter
    from rf4s_modkit import areagroup
    fam = areagroup.family_of(name)
    me = map_base(name).upper()
    c = Counter()
    if fam is None:
        return c
    for stem, (mgrp, _ch, _wh) in map_summaries().items():
        if stem.upper() != me and mgrp is not None and areagroup.family_of(stem) == fam:
            c[areagroup.zone_of_mgrp(mgrp)] += 1
    return c


def chest_problems(name, recs):
    """[(severity, entity index, message)] for the flag-owning objects in `recs` (this map's
    records, unsaved edits included): a chest with no collected flag, a chest waiting for a
    reveal flag nothing on the map sets (INFO), a one-shot flag (mobj_params.
    ONE_SHOT_FLAG_TYPES) another map of the game folder uses too (seasonal copies of this map
    share theirs on purpose; flags shared within this map are rf4m.validate's), an empty loot
    row, a row past the table."""
    from rf4s_modkit import mobj_params
    out = []
    base = SEASON_RE.sub("", map_base(name)).upper() if name else None
    _used, mine = _flag_uses(recs)
    if mine:
        others = {}
        for stem, (_u, owners) in map_flag_uses().items():
            if base is not None and SEASON_RE.sub("", stem).upper() == base:
                continue
            fam = SEASON_RE.sub("", stem).upper()
            for j, t, flag in owners:             # one entry per map family (seasons share)
                others.setdefault(flag, {}).setdefault(
                    (fam, j), f"{stem} #{j} ({mobj_params.ONE_SHOT_FLAG_TYPES[t]})")
        others = {fl: sorted(v.values()) for fl, v in others.items()}
        for i, t, flag in mine:
            if flag in others:
                what = mobj_params.ONE_SHOT_FLAG_TYPES[t]
                out.append(("WARN", i, f"{what} #{i} shares its one-shot flag {flag} with "
                                       + ", ".join(others[flag][:3])
                                       + (" ..." if len(others[flag]) > 3 else "")
                                       + ": whichever is used first sets it for all of them"))
    for i, r in enumerate(recs):
        if (r[0] & 0xFFFF) != 44:
            continue
        flag, row = r[13], r[8]
        if flag == -1:
            out.append(("WARN", i, f"chest #{i} has no collected flag (f13 = -1): the game never "
                                   f"removes it, so it is back with the same loot on every visit"))
        if row >= chestloot.ROWS:
            out.append(("WARN", i, f"chest #{i}: loot row {row} is past the {chestloot.ROWS}-row "
                                   f"chest table -- the game reads unrelated data as its items"))
        elif row < 0 or not any(item for item, _v in (chestloot.row(row) or [])):
            if not r[10]:
                out.append(("INFO", i, f"chest #{i} gives nothing (loot row {row} is empty)"))
        ev = chest_scene(r, name) if r[10] else None
        if ev is not None and ev[1] is not None and ev[2] is None:
            out.append(("WARN", i, f"chest #{i}: f10 = {r[10]} runs the map's scene keyed {ev[0]}, but "
                                   f"its event bank has no type-2 entry with that key"))
    return out


CHEST_EVENT_BASE = 1024       # a chest's f10 runs the map's type-2 scene keyed 1024 + f10


def chest_scene(rec, name):
    """(key, bank, scene pc | None) of the scene a chest runs when opened (f10 != 0), else None.
    WorldObject_OnBreakDropLoot (RF4S.exe+0x1662C0) queues game event 27 with 1024 + f10;
    its handler (NpcAi_TickEventMovementOrFinalize +0x1F3070) runs the type-2 entry with that
    key from the map's event (tail) bank."""
    if rec is None or (rec[0] & 0xFFFF) != 44 or not rec[10]:
        return None
    key = CHEST_EVENT_BASE + rec[10]
    mid = map_id(name) if name else None
    cont = rf3mc_container() if mid is not None else None
    bank = cont.banks[cont.n_primary + mid] if cont is not None and 0 <= cont.n_primary + mid < len(cont.banks) else None
    pc = None
    if bank is not None:
        try:
            for r in bank.entry_records(2):
                if any(v == key for _t, v in r.subs):
                    pc = r.event_id
                    break
        except Exception:
            pc = None
    return key, bank, pc


def chest_event(rec, name):
    """'Opening it runs scene key 1025 (@0e18): ModifyPlayerResource(100, add, 3630), ...' for a
    chest with a script event (f10), or that the key has no scene. None without one."""
    hit = chest_scene(rec, name)
    if hit is None:
        return None
    key, bank, pc = hit
    if bank is None:
        return f"Opening it runs the map's scene keyed {key} (f10 = {rec[10]}); rf3.mc not found"
    if pc is None:
        return (f"Opening it runs the map's scene keyed {key} (f10 = {rec[10]}), but this map's "
                f"event bank has no type-2 entry with that key: nothing happens")
    from rf4s_modkit import scriptasm
    steps = []
    try:
        sc = script.disassemble_scene(bank, 2, pc)
        for st in sc.stmts.values():
            if st.op < 0xFFF0:
                args = [scriptasm.operand_text(bank.data, a, st.op, i) for i, a in enumerate(st.args)]
                steps.append(scriptasm.action_line(st.op, args))
            elif st.mnem == "DIALOG":
                steps.append("DIALOG #%d" % st.dialog_id)
        if len(steps) > 6:
            steps = steps[:6] + ["…"]
    except Exception:
        pass
    return (f"Opening it runs scene key {key} (f10 = {rec[10]}, type 2 @{pc:04x} in the map's event "
            f"bank)" + (": " + ", ".join(steps) if steps else ""))


def chest_reveal(rec, recs):
    """For a chest with a reveal offset: 'appears once flag N is set (the room-clear flag of
    #j seal door)' -- which object on the map sets it, or that none does. None otherwise."""
    from rf4s_modkit import mobj_params
    if rec is None or (rec[0] & 0xFFFF) != 44 or not rec[9] & 0xFF:
        return None
    off = (rec[9] & 0xFF) - 256 if rec[9] & 0x80 else rec[9] & 0xFF
    fl = rec[13] + off
    setters = [f"#{j} ({mobj_params.ONE_SHOT_FLAG_TYPES.get(r[0] & 0xFFFF) or mobj_params.param_name(r[0], 13)})"
               for j, r in enumerate(recs) if r[13] == fl and (r[0] & 0xFFFF) != 44]
    who = (("set by " + ", ".join(setters[:3])) if setters
           else "nothing on this map sets it (an event script may)")
    return f"Hidden until flag {fl} (f13 + f9) is set, then it appears: {who}"


def crate_loot(rec, mgrp):
    """What a breakable crate (MOBJ type 53) can give on this map: one item rolled from its
    area group's pool each time the room loads (rf4s_modkit.chestloot). Every item, most
    likely first, items with the same chance grouped so even the 79-item DUNG_M pool fits a
    tooltip -- 'Crate loot (DUNG_B pool, 1 item per visit): 8.6% Antidote Grass · 5.7% each:
    nothing, Grapes, Purple Grass · ...'. None for other types."""
    if rec is None or (rec[0] & 0xFFFF) != 53:
        return None
    if rec[10] == 1:
        return "Crate loot: nothing (f10 = 1 makes it an empty crate)"
    zone = chestloot.zone_of_mgrp(mgrp)
    pools = chestloot.crate_pools(zone)
    what = " / ".join(f"{p['label']} {p['share']:.0%}" if p["share"] < 1 else p["label"]
                      for p in pools)
    try:
        odds = chestloot.crate_odds(zone)
    except chestloot.ChestLootError as e:
        return f"Crate loot ({what} pool): unknown -- {e}"

    def name(i):
        return "nothing" if i == 0 else (item_name(i) or f"item {i}")
    groups = []                                 # [(chance, [names])], most likely first
    for i, p in odds:
        pct = round(p * 100, 1)
        if groups and groups[-1][0] == pct:
            groups[-1][1].append(name(i))
        else:
            groups.append((pct, [name(i)]))
    parts = [f"{pct:g}% " + (names[0] if len(names) == 1 else "each: " + ", ".join(names))
             for pct, names in groups]
    return f"Crate loot ({what} pool, 1 item per visit): " + " · ".join(parts)


_ITEM_CHOICES = None


def item_choices():
    global _ITEM_CHOICES
    if _ITEM_CHOICES is None:
        _ITEM_CHOICES = [f"{i}  {n}" for i, n in sorted(item_names().items()) if i < 0x800]
    return _ITEM_CHOICES


_ACTOR_FN = None


def actor_name(i):
    """Monster / gate actor id -> name ('' when unknown)."""
    from rf4s_modkit import gamenames
    return gamenames.name("characters", i) or ""


def monster_choices():
    return [f"{i}  {actor_name(i)}" for i in range(gen.MONSTER_LO, gen.MONSTER_HI + 1) if actor_name(i)]


_GATE_HP = [None, None, {}]            # [bundle dir, (path, mtime), {kind: hp}]


def gate_hp(kind):
    """A gate kind's HP from the game's rf3NpcParam.bin (the copy the game loads), or None.
    The two gates of each name (375..382 and 383..390) differ only in HP."""
    from rf4s_modkit import gamenames, gamepaths, monster, nlcl
    try:
        b = gamepaths.find_bundle_dir()
    except Exception:  # noqa: BLE001
        b = None
    if b is None:
        return None
    if _GATE_HP[0] != b:
        hit = gamenames._first_loose(b, ["rf3NpcParam.bin"]).get("rf3NpcParam.bin")
        if hit is None:
            ex = gamepaths.extracted_dir(b)
            if ex is not None and pathlib.Path(ex).is_dir():
                hit = gamenames._first_loose(ex, ["rf3NpcParam.bin"]).get("rf3NpcParam.bin")
        _GATE_HP[0], _GATE_HP[1], _GATE_HP[2] = b, (hit, None), {}
    path, stamp = _GATE_HP[1]
    if path is None:
        return None
    try:
        now = path.stat().st_mtime_ns
    except OSError:
        return None
    if now != stamp:                        # (re)read: saving rf3NpcParam.bin shows at once
        try:
            t = nlcl.NlclTable.load(path)
            _GATE_HP[2] = {k: t.row(k, monster.STEM)["hp"]
                           for k in range(gen.GATE_KIND_LO, gen.GATE_KIND_HI + 1)}
        except Exception:  # noqa: BLE001
            _GATE_HP[2] = {}
        _GATE_HP[1] = (path, now)
    return _GATE_HP[2].get(kind)


def gate_label(kind):
    """'385  Frozen Gate · 1000 HP' -- '· glides' for the kinds that glide (375..382)."""
    hp = gate_hp(kind)
    out = f"{kind}  {actor_name(kind) or 'gate'}" + (f" · {hp} HP" if hp else "")
    if gen.GLIDE_KIND_LO <= kind <= gen.GLIDE_KIND_HI:
        out += " · glides"
    return out


def gate_choices():
    return [gate_label(i) for i in range(gen.GATE_KIND_LO, gen.GATE_KIND_HI + 1)]


def gate_list_label(e):
    """A gate's row in the Gates list: kind, name, how it moves, hidden."""
    how = gen.gate_motion(e)
    move = ("  · BROKEN (glides + teleports)" if how == {"glide", "teleport"} else
            "  · teleports" if "teleport" in how else "  · glides" if "glide" in how else "")
    return (f"{e.gate_kind}  {actor_name(e.gate_kind)}".strip() + move
            + ("  (hidden)" if e.hdr.flag & 0xFF else ""))


_CHARS = None


def char_name(cid):
    from rf4s_modkit import gamenames
    return gamenames.name("characters", int(cid))


# ---- MapOre_Rate (type-0 ore spawn configs) ------------------------------ #
def ore_configs(reader):
    """MapOre_Rate rows [(kind, deplete, scrap, [(item, weight) x3], rare)], [] if absent."""
    out = []
    try:
        d = reader("MapOre_Rate.bin") if reader else None
        if d and d[:4] == b"NLCL":
            cnt = struct.unpack_from("<I", d, 24)[0]
            for i in range(min(cnt, 64)):
                q = 28 + 32 * i
                kind = struct.unpack_from("<I", d, q)[0]
                dep = struct.unpack_from("<H", d, q + 4)[0]
                scr = struct.unpack_from("<H", d, q + 8)[0]
                iw = [(struct.unpack_from("<H", d, q + 24 + 2 * j)[0],
                       struct.unpack_from("<H", d, q + 12 + 4 * j)[0]) for j in range(3)]
                rare = struct.unpack_from("<H", d, q + 30)[0]
                out.append((kind, dep, scr, iw, rare))
    except Exception:
        return []
    return out


# ---- script-spawned actors (SpawnEventActor* in the map's event bank) -------- #
# ops 153 SpawnEventActor, 154 SpawnEventActorVariant, 155 SpawnEventActorEx: all start with
# (char id, event key, x, y)
SPAWN_OPS = ("SpawnEventActor", "SpawnEventActorVariant", "SpawnEventActorEx")
_RF3MC = {"key": None, "c": None}      # the disk copy, keyed by (path, size, mtime)
_LIVE_SCRIPT = {"fn": None}            # () -> the open cutscene editor's container, or None
_SCRIPT_LISTENERS = []                 # fn() called when the script may have changed


_RF3MC_PATH = {"key": None, "path": None}


def rf3mc_path():
    """The rf3.mc the game loads: the Bundle/** winner (a Bundle/00_mods override, else the
    unpacked bundlePatch1 copy), else the extracted copy (a bundlePatch one first).
    Finding the winner walks the whole Bundle folder (~0.5 s), so it is cached per game
    folder; only a Bundle/00_mods/rf3.mc appearing or going away changes the winner, and
    that is a cheap check on every call (the chest checks call this on each redraw)."""
    try:
        from rf4s_modkit import gamepaths, mbundle
        b = gamepaths.find_bundle_dir()
        key = (str(b), (b / mbundle.MOD_FOLDER / "rf3.mc").is_file()) if b is not None else None
    except Exception:
        b, key = None, None
    if key is not None and key == _RF3MC_PATH["key"]:
        p = _RF3MC_PATH["path"]
        if p is not None and p.is_file():
            return p
    path = None
    try:
        from rf4s_modkit import gamepaths
        t = gamepaths.game_targets(["rf3.mc"])
        if t and t["rf3.mc"].is_file():
            path = t["rf3.mc"]
    except Exception:
        pass
    if path is None:
        hits = find_extracted_all("rf3.mc")
        patch = [h for h in hits if "patch" in str(h).lower()]
        path = (patch or hits)[0] if hits else None
    _RF3MC_PATH.update(key=key, path=path)
    return path


def set_live_script(fn):
    """Show the scripts of an open cutscene editor (fn() -> its Container, or None when it is
    closed) instead of the file on disk, so its edits -- saved or not -- appear on the maps."""
    _LIVE_SCRIPT["fn"] = fn


def on_script_changed(fn):
    """Call fn() whenever script_changed() is signalled (the map editor redraws its spawns)."""
    _SCRIPT_LISTENERS.append(fn)


def script_changed():
    """The scripts changed (an edit, undo or save in the cutscene editor)."""
    for fn in list(_SCRIPT_LISTENERS):
        try:
            if fn() is False:                 # a listener whose widgets are gone unregisters
                _SCRIPT_LISTENERS.remove(fn)
        except Exception:
            _SCRIPT_LISTENERS.remove(fn)


def rf3mc_container(live=True):
    """The rf3.mc event-script container: the open cutscene editor's (set_live_script; not
    with live=False), else the file the game loads, re-read whenever that file changes on
    disk; None if missing."""
    fn = _LIVE_SCRIPT["fn"] if live else None
    if fn is not None:
        try:
            live = fn()
        except Exception:
            live = None
        if live is not None:
            return live
    path = rf3mc_path()
    try:
        st = path.stat() if path is not None else None
    except OSError:
        st = None
    key = (str(path), st.st_size, st.st_mtime_ns) if st is not None else None
    if key != _RF3MC["key"]:
        cont = None
        if path is not None and st is not None:
            try:
                cont = script.Container(path.read_bytes())
            except Exception:
                cont = None
        _RF3MC.update(key=key, c=cont)
    return _RF3MC["c"]


def script_spawns(name, container=None):
    """(bank index | None, [spawn dict]) for the actors this map's EVENT SCRIPT places with
    SpawnEventActor / SpawnEventActorVariant / SpawnEventActorEx: NPCs, monsters such as the Silver
    Wolf in Sechs Territory (MAP_DUNG_L13), and interactibles such as char 269 'Search'. They are not in the
    .rf4m. Coordinates are sub-units (8 per tile), like MOBJ positions."""
    mid = map_id(name)
    cont = (container or rf3mc_container()) if mid is not None else None
    if cont is None:
        return None, []
    bi = cont.n_primary + mid
    if not 0 <= bi < len(cont.banks):
        return None, []
    bank = cont.banks[bi]
    try:
        scenes = script.disassemble_bank(bank)
    except Exception:
        return bi, []
    out = []
    for sc in scenes:
        for pc, st in sc.stmts.items():
            if st.op >= 0xFFF0:
                continue
            mn = script.opcode_mnemonic(st.op)
            if mn == ENTITY_OP:
                ent = _entity_spawn(bank, st)
                if ent is not None:
                    ent.update(entry_pc=sc.entry_pc, pc=pc)
                    out.append(ent)
                continue
            if mn not in SPAWN_OPS:
                continue
            try:
                v = [int(script.arg_repr(bank.data, a), 0) for a in st.args[:4]]
            except (ValueError, TypeError):
                continue                    # computed arguments: position unknown
            if len(v) < 4:
                continue
            cid, inst, x, y = v
            out.append({"kind": "actor", "char_id": cid, "instance": inst,
                        "name": char_name(cid) or f"char#{cid}",
                        "x": x, "y": y, "entry_pc": sc.entry_pc, "pc": pc})
    return bi, out


# op 157 SpawnMapEntity(type, x, y, facing, param, e1..e6) builds the same 16-word record a
# .rf4m MOBJ is (ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable, RF4S.exe+0x213E20):
# w0 = type, w14/w15 = x/y in sub-units, w6 = param*40 (the f6 scale: 100 ~ 1:1),
# w7 = facing*182, w8..w13 = e1..e6, the rest 0; then it calls the map loader's spawners.
ENTITY_OP = "SpawnMapEntity"


def _entity_spawn(bank, st):
    """The map object a SpawnMapEntity statement places, as a spawn dict with a decoded
    MOBJ entry under "obj", or None when its type or position is computed."""
    try:
        v = [int(script.arg_repr(bank.data, a), 0) for a in st.args[:11]]
    except (ValueError, TypeError):
        return None
    if len(v) < 3:
        return None
    v += [0] * (11 - len(v))
    t, x, y, facing, param = v[:5]
    rec = [t, 0, 0, 0, 0, 0, param * 40, (facing * 182) & 0xFFFFFFFF] + v[5:11] + [x, y]
    rec[7] = rec[7] - (1 << 32) if rec[7] >= 1 << 31 else rec[7]
    tid = t & 0xFFFF
    obj = {"type_id": t, "category": mobj_types.mobj_kind(tid), "name": mobj_types.mobj_name(tid),
           "archive_id": mobj_types.mobj_archive_id(tid), "scale": rec[6] / 4096.0,
           "orientation_deg": (rec[7] % 65536) * 360.0 / 65536.0,
           "pos_x": x, "pos_y": y, "params": rec}
    return {"kind": "entity", "type_id": t, "instance": None,
            "name": mobj_types.mobj_display_name(tid) or f"MOBJ {tid}", "x": x, "y": y, "obj": obj}


# ---- slot saves (for the "show objects as in" flag source) -------------------- #
def save_dir():
    """The game's save folder: Rune Factory 4 Special under %APPDATA%."""
    base = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData" / "Roaming")
    return pathlib.Path(base) / "Rune Factory 4 Special"


def slot_saves():
    """rf4_sNN.sav files in the save folder, by slot number."""
    d = save_dir()
    if not d.is_dir():
        return []
    return sorted((p for p in d.glob("rf4_s[0-9][0-9].sav") if p.is_file()), key=lambda p: p.name)


# ---- zone-2 ("scene") flags: who uses each one --------------------------------- #
# The placed objects and warps of every map are re-read each time (0.3 s); the event-script
# uses take ~5 s to find, so they are cached in the toolkit's cache/ folder, keyed by the
# rf3.mc file they came from.
_FLAGS = {"idx": None, "thread": None, "result": None}


def _script_flag_uses():
    from rf4s_modkit import flagusers
    path = rf3mc_path()
    if path is None:
        return []
    st = path.stat()
    key = f"{path}|{st.st_size}|{st.st_mtime_ns}"
    cache = gamepaths.TOOLKIT / "cache" / "flag_script_uses.json"
    try:
        got = json.loads(cache.read_text(encoding="utf-8"))
        if got.get("key") == key:
            return [(rel, u) for rel, u in got["uses"]]
    except (OSError, ValueError, KeyError):
        pass
    cont = rf3mc_container(live=False)       # the cache is keyed by the file on disk
    if cont is None:
        return []
    uses = flagusers.script_uses(cont, map_file_for=lambda mid: rooms_by_id().get(mid))
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "uses": uses}), encoding="utf-8")
    except OSError:
        pass                                    # a read-only toolkit folder: scan next time
    return uses


def _build_flag_index():
    from rf4s_modkit import flagusers, rf4m
    uses = []
    for n, paths in extracted_index().items():
        if n.startswith("map_") and n.endswith(".rf4m"):
            try:
                m = rf4m.Rf4mMap.load(paths[0])
            except Exception:  # noqa: BLE001 - an unreadable map: skipped
                continue
            uses += flagusers.object_uses(paths[0].stem, m.mobj_records(), m.mapj_records())
    uses += _script_flag_uses()
    return flagusers.index(uses)


def flag_index():
    """{zone-2 id: [use]} over every map and the event scripts, or None while not built yet
    (see request_flag_index)."""
    return _FLAGS["idx"]


def request_flag_index(widget, done=None):
    """Build the flag index in the background (once); `done(index)` runs on the Tk thread
    when it is ready -- at once if it already is."""
    if _FLAGS["idx"] is not None:
        if done:
            done(_FLAGS["idx"])
        return
    waiters = _FLAGS.setdefault("waiters", [])
    if done:
        waiters.append(done)
    if _FLAGS["thread"] is None:
        import threading

        def work():
            try:
                _FLAGS["result"] = _build_flag_index()
            except Exception:  # noqa: BLE001 - nothing to show rather than a crash
                _FLAGS["result"] = {}
        _FLAGS["thread"] = threading.Thread(target=work, daemon=True)
        _FLAGS["thread"].start()

    def poll():
        if _FLAGS["result"] is None:
            try:
                widget.after(150, poll)
            except Exception:  # noqa: BLE001 - the widget is gone
                pass
            return
        _FLAGS["idx"] = _FLAGS["result"]
        for fn in _FLAGS.pop("waiters", []):
            try:
                fn(_FLAGS["idx"])
            except Exception:  # noqa: BLE001
                pass
    try:
        widget.after(150, poll)
    except Exception:  # noqa: BLE001
        pass


def flag_users(rel, live=None):
    """[use] of zone-2 id `rel` over every map and script. `live` = (map name, MOBJ records,
    MAPJ records) of the map being edited: its current records replace the file's."""
    from rf4s_modkit import flagusers
    idx = _FLAGS["idx"] or {}
    out = [u for u in idx.get(rel, ()) if live is None or u.get("map") != live[0]]
    if live is not None:
        out += [u for r, u in flagusers.object_uses(*live) if r == rel]
    return out
