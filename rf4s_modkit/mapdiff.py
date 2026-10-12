"""
What changed in a map, replayed on another map -- mainly to carry an edit to the other
three seasons of a seasonal map (map_names.season_family: the game loads a different file in
each season, and the four files differ, so copying the whole file would wipe out what makes
each season look like itself).

`diff(base, cur)` records what changed from `base` (the map as the game ships it) to `cur`:
  * objects (MOBJ) and warps (MAPJ): records added, removed and edited, found by aligning
    the two record lists (difflib); an edit keeps the record it replaced;
  * ATTR cells (walkability etc.) that changed, when the grid kept its size;
  * any other chunk that changed (map settings: season, tints, layers ...) -- reported, never
    replayed: those are what differs between seasons.

`apply(changes, target)` replays it on another map: an edited or removed record is found in
`target` by its exact original content (so it only lands where that season has the same
object), added records are appended (up to the game's 40 objects / 10 warps per map), cells
are set when the grid has the same size. Anything
that cannot be matched is skipped and reported, never guessed. Returns a Report.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from . import map_names, mobj_types
from .rf4m import ENGINE_MAX_CHUNKS

KINDS = (("objects", b"MOBJ", 64), ("warps", b"MAPJ", 36))
REPLAYED = {b"MOBJ", b"MAPJ", b"ATTR"}


@dataclass
class Changes:
    edited: dict = field(default_factory=lambda: {k: [] for k, _t, _s in KINDS})    # [(old, new)]
    removed: dict = field(default_factory=lambda: {k: [] for k, _t, _s in KINDS})   # [old]
    added: dict = field(default_factory=lambda: {k: [] for k, _t, _s in KINDS})     # [new]
    cells: dict = field(default_factory=dict)       # {(x, y): value}
    grid: tuple | None = None                       # (w, h) the cells belong to
    grid_resized: bool = False
    other: list = field(default_factory=list)       # chunk tags that changed and are not replayed

    def empty(self):
        return not (any(self.edited.values()) or any(self.removed.values())
                    or any(self.added.values()) or self.cells or self.grid_resized or self.other)

    def summary(self):
        parts = []
        for k, _t, _s in KINDS:
            n = (len(self.edited[k]), len(self.added[k]), len(self.removed[k]))
            if any(n):
                parts.append(f"{k}: {n[0]} changed, {n[1]} added, {n[2]} removed")
        if self.cells:
            parts.append(f"{len(self.cells)} ATTR cell(s)")
        return "; ".join(parts) or "nothing"


@dataclass
class Report:
    done: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def describe(kind, rec):
    """A short readable name for a record (reports)."""
    if kind == "objects":
        tid = rec[0] & 0xFFFF
        nm = mobj_types.mobj_display_name(tid) or mobj_types.mobj_kind(tid)
        return f"{nm} at tile ({rec[14] >> 3}, {rec[15] >> 3})"
    dest = map_names.map_name(rec[5]) or f"map {rec[5]}"
    return f"warp to {dest} at tile ({rec[1] >> 3}, {rec[2] >> 3})"


def _stream(m, tag):
    return [c.payload for c in m.chunks if c.tag == tag]


def _pair(kind, old, new):
    """[(i, j)]: which removed record became which new one inside a replaced block -- the
    closest match (fewest differing fields; objects only of the same type, warps only when
    most fields still match). Pairing by position turned 'delete A, edit the B after it' into
    'edit A, delete B', which then deleted B in another season that has no A."""
    cand = []
    for i, o in enumerate(old):
        for j, n in enumerate(new):
            if kind == "objects" and (o[0] & 0xFFFF) != (n[0] & 0xFFFF):
                continue
            d = sum(1 for x, y in zip(o, n) if x != y)
            if kind != "objects" and d > len(o) // 2:
                continue
            cand.append((d, i, j))
    used_o, used_n, out = set(), set(), []
    for _d, i, j in sorted(cand):
        if i not in used_o and j not in used_n:
            used_o.add(i)
            used_n.add(j)
            out.append((i, j))
    return sorted(out)


def diff(base, cur) -> Changes:
    ch = Changes()
    for kind, tag, stride in KINDS:
        a, b = base.records(tag, stride), cur.records(tag, stride)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            old, new = a[i1:i2], b[j1:j2]
            pairs = _pair(kind, old, new) if op == "replace" else []
            po, pn = {i for i, _j in pairs}, {j for _i, j in pairs}
            ch.edited[kind] += [(old[i], new[j]) for i, j in pairs]
            ch.removed[kind] += [r for i, r in enumerate(old) if i not in po]
            ch.added[kind] += [r for j, r in enumerate(new) if j not in pn]
    ga, gb = base.attr_grid(), cur.attr_grid()
    if ga and gb:
        if (ga[0], ga[1]) != (gb[0], gb[1]):
            ch.grid_resized = True
        else:
            w = ga[0]
            ch.grid = (ga[0], ga[1])
            ch.cells = {(i % w, i // w): (u, v) for i, (u, v) in enumerate(zip(ga[2], gb[2])) if u != v}
    tags = {c.tag for c in base.chunks} | {c.tag for c in cur.chunks}
    ch.other = sorted(t.decode("latin1") for t in tags - REPLAYED if _stream(base, t) != _stream(cur, t))
    return ch


def apply(ch: Changes, target) -> Report:
    rep = Report()
    for kind, tag, stride in KINDS:
        recs = target.records(tag, stride)
        used = set()

        def find(rec):
            for i, r in enumerate(recs):
                if i not in used and tuple(r) == tuple(rec):
                    used.add(i)
                    return i
            return None
        # edits in place first (indices stay valid), then removals from the end, then appends
        for old, new in ch.edited[kind]:
            i = find(old)
            if i is None:
                rep.skipped.append(f"changed {describe(kind, old)}: not the same here")
            else:
                target.set_record(tag, i, new, stride)
                rep.done.append(f"changed {describe(kind, old)}")
        gone = []
        for old in ch.removed[kind]:
            i = find(old)
            if i is None:
                rep.skipped.append(f"removed {describe(kind, old)}: not the same here")
            else:
                gone.append((i, old))
        for i, old in sorted(gone, reverse=True):
            target.delete_record(tag, i, stride)
            rep.done.append(f"removed {describe(kind, old)}")
        cap = ENGINE_MAX_CHUNKS[tag]
        for new in ch.added[kind]:
            if len(target.find(tag)) >= cap:
                # the loader's pointer array for the tag is not bounds-checked
                rep.skipped.append(f"added {describe(kind, new)}: that season already has "
                                   f"{cap} {kind}, the most the game can load")
                continue
            target.add_record(tag, new, stride)
            rep.done.append(f"added {describe(kind, new)}")
    if ch.cells:
        g = target.attr_grid()
        if g and ch.grid and (g[0], g[1]) == ch.grid:
            w, h, cells = g
            differ = 0
            for (x, y), (u, v) in ch.cells.items():
                cur = cells[y * w + x]
                differ += cur != u
                # the bits you cleared go, the bits you set come; the season's own bits stay
                cells[y * w + x] = (cur & ~(u & ~v)) | (v & ~u)
            target.set_attr_grid(w, h, cells)
            rep.done.append(f"{len(ch.cells)} ATTR cell(s)" + (
                f" ({differ} differed here: only the changed bits were applied)" if differ else ""))
        else:
            rep.skipped.append(f"{len(ch.cells)} ATTR cell(s): the grid is a different size here")
    if ch.grid_resized:
        rep.skipped.append("the ATTR grid was resized: resize this map by hand")
    if ch.other:
        rep.skipped.append("map settings (" + ", ".join(ch.other) + "): season-specific, not copied")
    return rep
