"""The editing model: one map plus its two sidecar files, one undo history across all
three, dirty tracking, and change notification.

    doc = MapDocument(rf4m_map, "MAP_FIELD_01")
    with doc.edit("Move entity #3", "mobj"):
        doc.map.set_mobj_record(3, rec)

Every edit runs inside `edit()` (or a `begin()` / `end()` pair for drags). The step
records the bytes of each file that changed, so undo is exact for any edit -- field
tweaks, structural Gen edits, raw chunk rewrites alike -- and an edit that ends where
it started records nothing. Listeners get the set of aspects that changed:

    "attr"  ATTR cells or grid size     "mobj"  entities       "mapj"  warps
    "props" header chunks (MSEA ...)    "chunks" chunk list     "si"    search spots
    "gen"   encounter table
"""
from __future__ import annotations

import struct
from contextlib import contextmanager

from rf4s_modkit import gen, rf4m, search_items

from . import data

UNDO_DEPTH = 100
ALL_ASPECTS = frozenset({"attr", "mobj", "mapj", "props", "chunks", "si", "gen"})
_PART_OF = {"attr": "map", "mobj": "map", "mapj": "map", "props": "map", "chunks": "map",
            "si": "si", "gen": "gen"}


class Step:
    __slots__ = ("label", "before", "after", "aspects")

    def __init__(self, label, before, after, aspects):
        self.label, self.before, self.after, self.aspects = label, before, after, aspects


class Tx:
    """An open edit: the bytes of the touched files when it began."""
    __slots__ = ("label", "aspects", "before")

    def __init__(self, label, aspects, before):
        self.label, self.aspects, self.before = label, aspects, before


class MapDocument:
    def __init__(self, mapobj, name, *, si_path=None, gen_path=None, load_sidecars=True):
        self.map = mapobj
        self.name = name
        self.base = data.map_base(name)
        self.si = self.si_path = self.gen = self.gen_path = None
        if load_sidecars:
            # the files the GAME loads for this room (by map id and MGRP, not by name)
            self.si_path = si_path or data.si_file_for_map(self.base)
            self.gen_path = gen_path or data.gen_file_for_map(self.base, mapobj.mgrp())
            if self.si_path:
                try:
                    self.si = search_items.SearchItemFile.load(self.si_path)
                except Exception:
                    self.si = None
            if self.gen_path:
                try:
                    self.gen = gen.GenTable.load(self.gen_path)
                except Exception:
                    self.gen = None
        self.undo_stack: list[Step] = []
        self.redo_stack: list[Step] = []
        self._listeners = []
        self._open: Tx | None = None
        self._saved = {p: self._bytes(p) for p in ("map", "si", "gen")}
        self.opened = dict(self._saved)          # the files as opened (saves move _saved on)
        self.grid = None
        self.objs = []
        self.attr_version = 0
        self._derive(ALL_ASPECTS)

    # ---- serialisation --------------------------------------------------- #
    def _bytes(self, part):
        obj = {"map": self.map, "si": self.si, "gen": self.gen}[part]
        return None if obj is None else obj.build()

    def _install(self, part, blob):
        if part == "map":
            self.map = rf4m.Rf4mMap.parse(blob)
        elif part == "si":
            self.si = None if blob is None else search_items.SearchItemFile.parse(blob)
        else:
            self.gen = None if blob is None else gen.GenTable(blob)

    def _derive(self, aspects):
        """Refresh the caches the view reads (grid, decoded entities)."""
        if aspects & {"attr", "chunks"}:
            self.grid = self.map.attr_grid()
            self.attr_version += 1
        if aspects & {"mobj", "chunks"}:
            self.objs = self.map.decode_mobj()

    # ---- listeners ------------------------------------------------------- #
    def subscribe(self, fn):
        self._listeners.append(fn)

    def notify(self, aspects):
        aspects = frozenset(aspects)
        self._derive(aspects)
        for fn in list(self._listeners):
            fn(aspects)

    # ---- transactions ---------------------------------------------------- #
    @staticmethod
    def _aspects(aspects):
        if isinstance(aspects, str):
            aspects = {aspects}
        return frozenset(aspects)

    def begin(self, label, aspects):
        """Open an edit (a drag, a paint stroke). Mutate the files, call notify() for
        live feedback, then end(). Nested begin() calls join the open edit."""
        aspects = self._aspects(aspects)
        if self._open is not None:
            self._open.aspects |= aspects
            for p in {_PART_OF[a] for a in aspects} - set(self._open.before):
                self._open.before[p] = self._bytes(p)
            return self._open
        parts = {_PART_OF[a] for a in aspects}
        self._open = Tx(label, aspects, {p: self._bytes(p) for p in parts})
        return self._open

    def end(self, label=None):
        """Close the open edit. Records one undo step when any file's bytes changed and
        returns it (None when the edit changed nothing)."""
        tx = self._open
        self._open = None
        if tx is None:
            return None
        after = {p: self._bytes(p) for p in tx.before}
        changed = {p for p in tx.before if after[p] != tx.before[p]}
        if not changed:
            return None
        step = Step(label or tx.label, {p: tx.before[p] for p in changed},
                    {p: after[p] for p in changed}, tx.aspects)
        self.undo_stack.append(step)
        del self.undo_stack[:-UNDO_DEPTH]
        self.redo_stack.clear()
        return step

    def cancel(self):
        """Abandon the open edit and put the files back."""
        tx, self._open = self._open, None
        if tx is None:
            return
        for p, blob in tx.before.items():
            self._install(p, blob)
        self.notify(tx.aspects)

    @contextmanager
    def edit(self, label, aspects):
        """One undoable edit. On an exception the files are restored and it re-raises."""
        outer = self._open is not None
        tx = self.begin(label, aspects)
        try:
            yield tx
        except BaseException:
            if not outer:
                self.cancel()
            raise
        if not outer:
            step = self.end()
            if step is not None:
                self.notify(step.aspects)

    @property
    def in_edit(self):
        return self._open is not None

    # ---- undo / redo ------------------------------------------------------ #
    def _apply(self, step, side):
        for p, blob in getattr(step, side).items():
            self._install(p, blob)
        self.notify(step.aspects)

    def undo(self):
        if self._open is not None:
            self.end()
        if not self.undo_stack:
            return None
        step = self.undo_stack.pop()
        self.redo_stack.append(step)
        self._apply(step, "before")
        return step

    def redo(self):
        if not self.redo_stack:
            return None
        step = self.redo_stack.pop()
        self.undo_stack.append(step)
        self._apply(step, "after")
        return step

    # ---- dirty tracking ---------------------------------------------------- #
    PART_LABELS = {"map": "map", "si": "search items", "gen": "monster gates"}

    def dirty_parts(self):
        """Which files differ from their last load / save, as labels: a subset of
        ['map', 'search items', 'monster gates']. Byte comparison, so an undone edit
        does not count."""
        return [self.PART_LABELS[p] for p in ("map", "si", "gen")
                if self._bytes(p) != self._saved[p]]

    def dirty(self, part):
        return self._bytes(part) != self._saved[part]

    def mark_saved(self, part):
        self._saved[part] = self._bytes(part)

    # ---- sidecar creation -------------------------------------------------- #
    def si_block_reason(self):
        """Why this map cannot get search spots (a plain sentence), or None when it can: the
        game loads search items only for map ids that its table (RF4S.exe+0x4DD260) gives an
        SI archive, and a map cannot be given one without patching the game."""
        if self.si is not None:
            return None
        from rf4s_modkit import areagroup
        if areagroup.base_map_id(self.base) is None:
            return (f"{self.base or 'This map'} is not one of the game's map files, so the game "
                    f"never loads search items for it.")
        if data.si_name_for_map(self.base) is None:
            return (f"The game never rolls search items on {self.base}: the game's search-item "
                    f"table has no file for this map, and one cannot be added without patching "
                    f"the game. Only maps that already have an SI file can get search spots.")
        return None

    def ensure_si(self):
        """This map's search-item file, created empty when the game has a slot for it but the
        file is missing. Raises search_items.SearchItemError (with si_block_reason()) on a map
        that never rolls search items."""
        if self.si is None:
            why = self.si_block_reason()
            if why:
                raise search_items.SearchItemError(why)
            self.si = search_items.SearchItemFile()
        return self.si

    # ---- ATTR helpers ------------------------------------------------------ #
    def set_cells(self, cells):
        """Write {(x, y): value} into ATTR in one pass (out-of-grid cells are skipped).
        Updates the cached grid in place. Returns how many cells actually changed."""
        # the LAST ATTR chunk is the one the game keeps (and the one attr_grid() decodes)
        a = self.map.live_chunk(b"ATTR")
        if a is None or self.grid is None:
            raise rf4m.Rf4mError("this map has no ATTR grid")
        w, h, flat = self.grid
        body = bytearray(a.payload)
        n = 0
        for (x, y), v in cells.items():
            if 0 <= x < w and 0 <= y < h:
                v &= 0xFFFFFFFF
                k = y * w + x
                if flat[k] != v:
                    flat[k] = v
                    struct.pack_into("<I", body, 8 + 4 * k, v)
                    n += 1
        if n:
            a.payload = bytes(body)
            self.attr_version += 1
        return n

    def cell(self, x, y):
        if self.grid is None:
            return None
        w, h, flat = self.grid
        return flat[y * w + x] if 0 <= x < w and 0 <= y < h else None

    # ---- search-item and encounter conveniences ---------------------------- #
    def gate_points(self):
        """Every distinct gate / monster position record in the encounter table:
        [(kind, rec_off, x, y, [(pi, ei), ...])], kind 'gpos' or 'mpos'. A position table
        shared by several gates is listed once, with every gate using it."""
        out, where = [], {}
        if self.gen is None:
            return out
        for pi, ei, e in self.gen.all_entries():
            for kind, pts in (("gpos", self.gen.gate_positions_off(e)),
                              ("mpos", self.gen.monster_positions_off(e))):
                for off, x, y in pts:
                    key = (kind, off)
                    if key not in where:
                        where[key] = len(out)
                        out.append((kind, off, x, y, []))
                    out[where[key]][4].append((pi, ei))
        return out

    def locate_point(self, kind, off):
        """(entry, index) of a gate / monster position record by offset, or (None, None)."""
        if self.gen is None:
            return None, None
        for _pi, _ei, e in self.gen.all_entries():
            pts = self.gen.gate_positions_off(e) if kind == "gpos" else self.gen.monster_positions_off(e)
            for i, (o, _x, _y) in enumerate(pts):
                if o == off:
                    return e, i
        return None, None
