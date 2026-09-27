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

from rf4s_modkit import chestloot, gamepaths, gen, map_names, script, textdb
from rf4s_modkit.refdata import refdata_path

REPO = pathlib.Path(__file__).resolve().parent.parent.parent.parent
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
def gen_name_for_map(name):
    """MAP_DUNG_X## -> GenX##.bin ; MAP_FIELD_## -> GenField##.bin (seasonal variants share
    their base map's table), or None for maps without a monster generator."""
    m = re.search(r"DUNG_([A-Z]+)(\d+)", str(name)) or re.search(r"(FIELD)_?(\d+)", str(name))
    if not m:
        return None
    area, num = m.group(1), int(m.group(2))
    return f"GenField{num:02d}.bin" if area == "FIELD" else f"Gen{area}{num:02d}.bin"


def gen_file_for_map(name):
    fn = gen_name_for_map(name)
    return find_extracted(fn) if fn else None


def gen_name_for_id(map_id):
    """GenX##.bin of a map id (by its MAP_* file), or None."""
    f = map_names.map_file(map_id) if map_id is not None else None
    return gen_name_for_map(f) if f else None


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


def maps_for_gen(gen_name, map_names):
    """The maps (from `map_names`) whose monster generator is `gen_name`, the base map first,
    then its seasonal variants."""
    want = map_base(gen_name).rsplit(".", 1)[0].lower() + ".bin"
    hits = [n for n in map_names if (gen_name_for_map(map_base(n)) or "").lower() == want]
    return sorted(hits, key=lambda n: (SEASON_RE.search(map_base(n)) is not None, map_base(n)))


def si_name_for_map(name):
    """SI_<rest>.bin for MAP_<rest> (seasonal variants share one file), or None."""
    base = SEASON_RE.sub("", map_base(name))
    m = re.match(r"^MAP_(.+)$", base, re.I)
    return f"SI_{m.group(1)}.bin" if m else None


def si_file_for_map(name):
    fn = si_name_for_map(name)
    return find_extracted(fn) if fn else None


# ---- names ----------------------------------------------------------------- #
_ITEMS = None


def item_names():
    """{item id: English name}: rf3TxtItem from the extracted tree, with the vendored
    rf4s_item_names.json filling any gaps."""
    global _ITEMS
    if _ITEMS is not None:
        return _ITEMS
    out = {}
    try:
        d = json.loads(refdata_path("rf4s_item_names.json").read_text(encoding="utf-8"))
        out.update({int(k): v for k, v in d.items() if v})
    except Exception:
        pass
    hit = find_extracted("rf3TxtItem_split2_1.eng")
    if hit is not None:
        try:
            arc = textdb.TextArchive.load(hit)
            out.update({i: e.decode("utf-8", "replace") for i, e in enumerate(arc.entries) if e})
        except Exception:
            pass
    _ITEMS = out
    return out


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
            out.append(("INFO", i, f"chest #{i} gives nothing (loot row {row} is empty)"))
    return out


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
    global _ACTOR_FN
    if _ACTOR_FN is None:
        p = refdata_path("rf4s_actor_names.json")
        try:
            _ACTOR_FN = gen.load_actor_names(p) if p.is_file() else (lambda _i: "")
        except Exception:
            _ACTOR_FN = lambda _i: ""
    return _ACTOR_FN(i) or ""


def monster_choices():
    return [f"{i}  {actor_name(i)}" for i in range(gen.MONSTER_LO, gen.MONSTER_HI + 1) if actor_name(i)]


def gate_choices():
    return [f"{i}  {actor_name(i) or 'gate'}" for i in range(gen.GATE_KIND_LO, gen.GATE_KIND_HI + 1)]


_CHARS = None


def char_name(cid):
    global _CHARS
    if _CHARS is None:
        try:
            _CHARS = json.loads(refdata_path("char_names.json").read_text(encoding="utf-8"))
        except Exception:
            _CHARS = {}
    return _CHARS.get(str(cid))


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


# ---- script-spawned actors (EventSpawnNpc* in the map's event bank) -------- #
# ops 153 EventSpawnNpc, 154 EventSpawnNpcVariant, 155 EventSpawnNpcEx: all start with
# (char id, event key, x, y)
SPAWN_OPS = ("EventSpawnNpc", "EventSpawnNpcVariant", "EventSpawnNpcEx")
_RF3MC = {"c": False}          # False = not tried yet; None = tried and missing


def rf3mc_container():
    """The rf3.mc event-script container (a bundlePatch copy wins), or None."""
    if _RF3MC["c"] is not False:
        return _RF3MC["c"]
    cont = None
    try:
        hits = find_extracted_all("rf3.mc")
        patch = [h for h in hits if "patch" in str(h).lower()]
        path = (patch or hits)[0] if hits else None
        if path is not None:
            cont = script.Container(path.read_bytes())
    except Exception:
        cont = None
    _RF3MC["c"] = cont
    return cont


def script_spawns(name):
    """(bank index | None, [spawn dict]) for the actors this map's EVENT SCRIPT places with
    EventSpawnNpc / EventSpawnNpcVariant / EventSpawnNpcEx: NPCs, monsters such as the Silver
    Wolf in Sechs Territory (MAP_DUNG_L13), and interactibles such as char 269 'Search'. They are not in the
    .rf4m. Coordinates are sub-units (8 per tile), like MOBJ positions."""
    mid = map_id(name)
    cont = rf3mc_container() if mid is not None else None
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
            if st.op >= 0xFFF0 or script.opcode_mnemonic(st.op) not in SPAWN_OPS:
                continue
            try:
                v = [int(script.arg_repr(bank.data, a), 0) for a in st.args[:4]]
            except (ValueError, TypeError):
                continue                    # computed arguments: position unknown
            if len(v) < 4:
                continue
            cid, inst, x, y = v
            out.append({"char_id": cid, "instance": inst,
                        "name": char_name(cid) or f"char#{cid}",
                        "x": x, "y": y, "entry_pc": sc.entry_pc, "pc": pc})
    return bi, out


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
