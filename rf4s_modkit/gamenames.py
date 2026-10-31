"""gamenames.py -- the names the editors show, read from the game's own text files.

Character, item, map and skill names come from the game's text archives, so a mod that
renames something (a file in Bundle/00_mods, or an edited bundleMain copy) shows up in every
picker and listing comment. The file used is the one the game loads (the same Bundle/**
lookup: byte-sorted pre-order walk, earliest copy wins, so 00_mods beats bundleMain), else
the extracted copy of a still-packed install. When neither exists, the lists shipped with
the toolkit (refdata/) are the default.

    table(kind)   {id: name} for kind in KINDS
    name(kind, i) one name, or None
    source(kind)  the game file the names came from, or None for the built-in default
    reload()      forget the cache now
    generation()  a number that changes whenever the names do

A saved name file is picked up by itself: at most twice a second the chosen files' size and
date, and whether a Bundle/00_mods copy exists, are compared with what was loaded, so a save
from the modkit (or any other tool) and a new or removed 00_mods override show on the next read.

Names are always the English (.eng) archives: they double as the words the assembler reads
(actor(Forte), map(...)), which must not change with the display language.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
from collections.abc import Mapping

# kind -> (game file, index of id 0 in that file, built-in default)
FILES = {
    "characters": ("rf3TxtNpc_split2_1.eng", 0),     # row = character id (0 = the player)
    "items": ("rf3TxtItem_split2_1.eng", 0),         # row = item id
    "item_descriptions": ("rf3TxtItem_split2_2.eng", 0),     # row = item id (no built-in default)
    "maps": ("rf3TxtMapName.eng", 1),                # row = map id + 1 (row 0 is a header)
    "skills": ("rf3TxtSkill_split2_1.eng", 0),       # row = skill id (40)
}
KINDS = tuple(FILES)

_BUILTIN_SKILLS = [
    "Short Sword", "Long Sword", "Spear", "Axe/Hammer", "Dual Blades", "Fist",
    "Fire", "Water", "Earth", "Wind", "Light", "Dark", "Love",
    "Farming", "Logging", "Mining", "Fishing", "Cooking", "Forging", "Chemistry",
    "Crafting", "Searching", "Walking", "Sleeping", "Eating", "Defense",
    "Resist Poison", "Resist Seals", "Resist Paralysis", "Resist Sleep",
    "Resist Fatigue", "Resist Cold", "Resist Knockout", "Bathing", "Taming",
    "Throwing", "Leadership", "Bartering", "Dummy", "Dummy 2",
]

_CACHE = {}          # kind -> (table, source path or None)
_FILES = None        # (bundle dir, {file name: path})
_GEN = [0]           # bumped by reload(): Lazy tables rebuild
_STAMP = [None, 0.0] # (what the loaded files looked like, when that was last checked)
CHECK_EVERY = 0.5    # seconds between checks for a changed file


def _builtin(kind):
    from .refdata import refdata_path
    try:
        if kind == "characters":
            d = json.loads(refdata_path("char_names.json").read_text(encoding="utf-8"))
            return {int(k): v for k, v in d.items() if v}
        if kind == "items":
            d = json.loads(refdata_path("rf4s_item_names.json").read_text(encoding="utf-8"))
            return {int(k): v for k, v in d.items() if v}
        if kind == "maps":
            rows = json.loads(refdata_path("map_names.json").read_text(encoding="utf-8"))
            return {i - 1: v.strip() for i, v in enumerate(rows) if i >= 1 and v}
        if kind == "skills":
            return dict(enumerate(_BUILTIN_SKILLS))
    except (OSError, ValueError):
        pass
    return {}


def _first_loose(root, names):
    """{name: path} of the copy the game loads for each name under Bundle/ (the rules of
    mbundle.loose_index -- byte-sorted listings, folders walked where they sort, '.' names
    skipped, earliest wins), stopping as soon as every name is found."""
    left, out = set(names), {}

    def walk(d):
        try:
            ents = sorted(os.scandir(d), key=lambda e: e.name.encode("utf-8", "surrogateescape"))
        except OSError:
            return
        for e in ents:
            if not left:
                return
            if e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=False):
                walk(e.path)
            elif e.name in left:
                out[e.name] = pathlib.Path(e.path)
                left.discard(e.name)
    walk(str(root))
    return out


def _game_files():
    global _FILES
    try:
        from . import gamepaths
        b = gamepaths.find_bundle_dir()
    except Exception:
        b = None
    if _FILES is not None and _FILES[0] == b:
        return _FILES[1]
    if _FILES is not None:                           # another game folder: new names
        _CACHE.clear()
        _GEN[0] += 1
    names = [f for f, _o in FILES.values()]
    found = {}
    if b is not None:
        found = _first_loose(b, names)
        missing = [n for n in names if n not in found]
        if missing:                                  # a packed install: the extracted copy
            try:
                from . import gamepaths
                ex = gamepaths.extracted_dir(b)
                if ex is not None and pathlib.Path(ex).is_dir():
                    found.update(_first_loose(ex, missing))
            except Exception:
                pass
    _FILES = (b, found)
    return found


def _stamp(files):
    """What the name files look like now: each chosen copy's (size, date), and whether a
    Bundle/00_mods copy exists (a new override sorts first)."""
    b = _FILES[0] if _FILES else None
    out = []
    for fn, _o in FILES.values():
        p = files.get(fn)
        try:
            st = p.stat() if p is not None else None
            out.append((str(p), st.st_size, st.st_mtime_ns) if st else None)
        except OSError:
            out.append(None)
        if b is not None:
            out.append((b / "00_mods" / fn).is_file())
    return tuple(out)


def _fresh():
    """Drop the cache when a name file changed (checked at most every CHECK_EVERY s)."""
    global _FILES
    now = time.monotonic()
    if _STAMP[0] is not None and now - _STAMP[1] < CHECK_EVERY:
        return
    _STAMP[1] = now
    files = _game_files()
    st = _stamp(files)
    if _STAMP[0] is not None and st != _STAMP[0]:
        _CACHE.clear()
        _FILES = None                                # resolve the winners again
        _GEN[0] += 1
        st = _stamp(_game_files())
    _STAMP[0] = st


def generation():
    """Changes whenever the names may have (a reload, a saved file, another game folder)."""
    _fresh()
    return _GEN[0]


def _load(kind):
    _fresh()
    files = _game_files()                            # (clears the cache on a folder change)
    if kind in _CACHE:
        return _CACHE[kind]
    fn, first = FILES[kind]
    path = files.get(fn)
    table, src = None, None
    if path is not None:
        try:
            from . import textdb
            arc = textdb.TextArchive.parse(path.read_bytes())
            table = {}
            for row in range(first, len(arc.entries)):
                try:
                    t = arc.text(row).strip()
                except Exception:
                    continue
                if t:
                    table[row - first] = t
            src = path
        except Exception:
            table = None
    if not table:
        table, src = _builtin(kind), None
    _CACHE[kind] = (table, src)
    return _CACHE[kind]


def table(kind):
    """{id: name} of `kind` (see KINDS)."""
    return _load(kind)[0]


def name(kind, i):
    return table(kind).get(i)


def source(kind):
    """The game file the names of `kind` came from, or None (the built-in default)."""
    return _load(kind)[1]


def reload():
    global _FILES
    _CACHE.clear()
    _FILES = None
    _STAMP[0] = None
    _GEN[0] += 1


class Lazy(Mapping):
    """A dict built by `build()` on first read (so importing a module reads no game file).
    reload() rebuilds every Lazy on its next read."""

    def __init__(self, build):
        self._build, self._d, self._gen = build, None, -1

    def _data(self):
        _fresh()
        if self._d is None or self._gen != _GEN[0]:
            try:
                self._d = self._build()
            except Exception:
                self._d = {}
            self._gen = _GEN[0]
        return self._d

    def __getitem__(self, k):
        return self._data()[k]

    def __iter__(self):
        return iter(self._data())

    def __len__(self):
        return len(self._data())
