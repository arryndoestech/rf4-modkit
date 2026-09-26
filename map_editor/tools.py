"""Canvas tools. Each gets press / drag / release / motion events from the editor
(already routed: the canvas only knows the active tool) and edits through the document,
so every gesture is exactly one undo step.

    select  V   click selects, drag moves (Shift = sub-tile precision), warp handles resize,
                double-click or Ctrl+click a warp opens its destination map
    paint   B   paint the ATTR value with a square brush; right-click picks a value,
                Shift+click draws a straight line from the last painted tile
    fill    G   flood-fill the clicked region (or replace the value map-wide)
    rect    R   drag a rectangle and fill it
    pick    I   click a tile to take its value, then return to the previous tool
    add     A   place an entity / search spot / gate position / monster spawn point
    warp    W   drag out a new warp zone
"""
from __future__ import annotations

from rf4s_modkit import search_items

DRAG_THRESHOLD_PX = 4          # the Windows drag threshold: less than this is a click


def _line(a, b):
    """Tiles on the line a -> b (Bresenham), inclusive."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    out = []
    while True:
        out.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return out
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


class Tool:
    name = ""
    label = ""
    key = ""
    cursor = ""
    hint = ""

    def __init__(self, ed):
        self.ed = ed                    # the MapEditorPanel

    @property
    def doc(self):
        return self.ed.doc

    @property
    def view(self):
        return self.ed.view

    def press(self, e): pass
    def drag(self, e): pass
    def release(self, e): pass
    def motion(self, e): pass
    def right_press(self, e): pass
    def cancel(self): self.view.preview_rect(None)
    def activate(self): pass
    def deactivate(self): self.view.preview_rect(None)


# --------------------------------------------------------------------------- #
class SelectTool(Tool):
    name, label, key, cursor = "select", "Select", "v", ""
    hint = ("Click to select, drag to move (hold Shift for sub-tile precision); click the same "
            "spot again to select the next thing under the pointer (a drag moves the selection "
            "instead). Drag a selected warp's handles to resize it. Double-click or Ctrl+click a "
            "warp to open its destination map. Arrow keys nudge the selection by a tile (Shift: 1 sub-unit).")

    def __init__(self, ed):
        super().__init__(ed)
        self._reset()

    def _reset(self):
        self.target = None          # key being dragged
        self.mode = None            # 'move' | handle name
        self.origin = None          # (x, y[, w, h]) of the target when pressed, sub-units
        self.anchor = None          # pointer when pressed: sub-units (move) or edge (resize)
        self.press_xy = None
        self.dragging = False
        self.started = False
        self.cycle = None           # candidates to step through on release (a plain click)

    def press(self, e):
        self._reset()
        self.before_cycle = None    # a new click: forget what the last release stepped from
        self.press_xy = (e.x, e.y)
        ed, doc = self.ed, self.doc
        keys = self.view.keys_at(e)
        # the selected warp's grab handles win over everything
        handle = next((k for k in keys if k[0] == "handle"), None)
        if handle is not None and ed.sel and ed.sel[0] == "warp":
            rec = doc.map.mapj_records()[ed.sel[1]]
            self.target, self.mode = ed.sel, handle[1]
            self.origin = tuple(rec[1:5])
            return
        cands = self.view.pick_candidates(e)
        if ed.sel is not None and ed.sel in cands:
            # pressing on the selection keeps it: a drag moves it, and a plain click (released
            # without moving) steps to the next thing under the pointer -- see release()
            key = ed.sel
            if len(cands) > 1:
                self.cycle = cands
        else:
            key = cands[0] if cands else None
            if key is not None and key[0] == "spawn":
                ed.open_spawn(key[1])
                return
            ed.select(key)
            self._announce(key, cands)
        if key is None:
            return
        self.target, self.mode = key, "move"
        self.origin = ed.position_of(key)
        self.anchor = self.view.subunit_at(e)

    def drag(self, e):
        if self.target is None:
            return
        if not self.dragging:
            if (abs(e.x - self.press_xy[0]) < DRAG_THRESHOLD_PX
                    and abs(e.y - self.press_xy[1]) < DRAG_THRESHOLD_PX):
                return                          # still a click: nothing moves
            self.dragging = True
        if self.mode == "move":
            pos = self._moved_to(e)
        else:
            pos = self._resized_to(e)
        if pos is None or tuple(pos) == tuple(self.ed.position_of(self.target)):
            return
        if not self.started:
            self.doc.begin(self.ed.describe_move(self.target, self.mode), self.ed.aspect_of(self.target))
            self.started = True
        self.ed.set_position(self.target, pos)

    def _moved_to(self, e):
        """Whole-tile moves keep the exact sub-tile offset; Shift places freely."""
        sx, sy = self.view.subunit_at(e)
        ox, oy = self.origin[0], self.origin[1]
        if e.state & 0x0001:                    # Shift
            nx, ny = ox + (sx - self.anchor[0]), oy + (sy - self.anchor[1])
        else:
            nx = ox + ((sx >> 3) - (self.anchor[0] >> 3)) * 8
            ny = oy + ((sy >> 3) - (self.anchor[1] >> 3)) * 8
        W, H, _ = self.doc.grid
        if self.target[0] == "warp":
            ow, oh = self.origin[2], self.origin[3]
            # keep it inside the grid, but never pull an edge warp further out than it was
            nx = max(min(0, ox), min(max(W * 8 - ow, ox), nx))
            ny = max(min(0, oy), min(max(H * 8 - oh, oy), ny))
            return (nx, ny, ow, oh)
        return (max(0, min(W * 8 - 1, nx)), max(0, min(H * 8 - 1, ny)))

    def _resized_to(self, e):
        """Move only the dragged edge(s) onto the tile boundary under the pointer."""
        ex, ey = (v * 8 for v in self.view.edge_at(e))
        ox, oy, ow, oh = self.origin
        W, H, _ = self.doc.grid
        x0, y0, x1, y1 = ox, oy, ox + ow, oy + oh
        m = self.mode
        if "w" in m:
            x0 = max(min(0, ox), min(ex, x1 - 8))
        if "e" in m:
            x1 = min(max(W * 8, ox + ow), max(ex, x0 + 8))
        if "n" in m:
            y0 = max(min(0, oy), min(ey, y1 - 8))
        if "s" in m:
            y1 = min(max(H * 8, oy + oh), max(ey, y0 + 8))
        return (x0, y0, x1 - x0, y1 - y0)

    def release(self, e):
        if self.started:
            self.ed.finish_edit()
        cycle = self.cycle if not self.dragging else None
        self._reset()
        if cycle:                               # a click on the selection: the next one
            ed = self.ed
            i = cycle.index(ed.sel) + 1 if ed.sel in cycle else 0
            key = cycle[i % len(cycle)]
            self.before_cycle = ed.sel          # a double-click may want this one back (double)
            if key[0] == "spawn":
                ed.open_spawn(key[1])
                return
            ed.select(key)
            self._announce(key, cycle)

    def _announce(self, key, cands):
        """Status line when several things are under the pointer."""
        if key is None or len(cands) < 2:
            return
        what = ("warp #%d" % key[1] if key[0] == "warp"
                else (self.view.describe_key(key) or str(key)).split("\n")[0])
        self.ed.status("%d of %d here: %s -- click again for the next"
                       % (cands.index(key) + 1, len(cands), what))

    def cancel(self):
        """Esc during a drag: put the object back."""
        if self.started:
            self.doc.cancel()
        self._reset()

    def right_press(self, e):
        """Context menu for the object under the pointer."""
        cands = self.view.pick_candidates(e, kinds=("mobj", "gpos", "mpos", "si", "warp"))
        key = self.ed.sel if self.ed.sel in cands else (cands[0] if cands else None)
        if key is not None:
            self.ed.select(key)
            self.ed.context_menu(e, key)
        else:
            self.ed.context_menu_empty(e)

    def double(self, e):
        """Tk sends a fast second click here instead of to press(). It opens a warp's
        destination when the double-click is on a warp: the warp that was selected before
        the first click stepped away from it, or the warp the first click selected -- other
        objects overlapping the warp do not matter. Otherwise it is an ordinary click, so
        quick clicks still step through overlapping things."""
        cands = self.view.pick_candidates(e)
        prev, self.before_cycle = getattr(self, "before_cycle", None), None
        for k in (prev, self.ed.sel):
            if k is not None and k[0] == "warp" and k in cands:
                self.ed.select(k)
                self.ed.goto_warp(k[1])
                return "break"
        self.press(e)
        return "break"


# --------------------------------------------------------------------------- #
class PaintTool(Tool):
    name, label, key, cursor = "paint", "Paint", "b", "pencil"
    hint = ("Paint the ATTR value below. Right-click a tile to pick its value; Shift+click "
            "draws a straight line from the last painted tile; [ and ] change the brush.")

    def __init__(self, ed):
        super().__init__(ed)
        self.last = None
        self.stroke = None

    def _stamp(self, t):
        n = self.ed.brush
        r0 = -(n // 2)
        cells = {}
        for dy in range(r0, r0 + n):
            for dx in range(r0, r0 + n):
                cells[(t[0] + dx, t[1] + dy)] = self.ed.paint_value
        return cells

    def _apply(self, tiles):
        cells = {}
        for t in tiles:
            cells.update(self._stamp(t))
        if self.doc.set_cells(cells):
            self.stroke.update(cells)
            self.view.stroke_cells([c for c in cells if self.doc.cell(*c) is not None],
                                   self.ed.paint_value)

    def press(self, e):
        t = self.view.tile_at(e)
        if t is None or self.ed.paint_value is None:
            return
        self.doc.begin(f"Paint 0x{self.ed.paint_value:X}", "attr")
        self.stroke = {}
        start = self.last if (e.state & 0x0001 and self.last) else t
        self._apply(_line(start, t))
        self.last = t

    def drag(self, e):
        if self.stroke is None:
            return
        t = self.view.tile_at(e, clamp=True)
        if t != self.last:
            self._apply(_line(self.last, t))
            self.last = t
        self.motion(e)

    def release(self, e):
        if self.stroke is None:
            return
        self.stroke = None
        self.ed.finish_edit()
        self.view.clear_stroke()

    def cancel(self):
        if self.stroke is not None:
            self.stroke = None
            self.doc.cancel()
            self.view.clear_stroke()

    def right_press(self, e):
        t = self.view.tile_at(e)
        if t is not None:
            self.ed.set_paint_value(self.doc.cell(*t))

    def motion(self, e):
        t = self.view.tile_at(e)
        if t is None:
            self.view.preview_rect(None)
            return
        n = self.ed.brush
        r0 = -(n // 2)
        self.view.preview_rect((t[0] + r0, t[1] + r0, t[0] + r0 + n - 1, t[1] + r0 + n - 1))


class FillTool(Tool):
    name, label, key, cursor = "fill", "Fill", "g", "spraycan"
    hint = ("Click to flood-fill the connected area of the same value. With 'whole map' "
            "ticked, every tile of that value is replaced. Right-click picks a value.")

    def press(self, e):
        t = self.view.tile_at(e)
        v = self.ed.paint_value
        if t is None or v is None:
            return
        W, H, flat = self.doc.grid
        old = flat[t[1] * W + t[0]]
        if old == v:
            return
        if self.ed.fill_global:
            cells = {(k % W, k // W): v for k, c in enumerate(flat) if c == old}
        else:
            cells, todo = {}, [t]
            while todo:
                x, y = todo.pop()
                if (x, y) in cells or not (0 <= x < W and 0 <= y < H) or flat[y * W + x] != old:
                    continue
                cells[(x, y)] = v
                todo += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        with self.doc.edit(f"Fill {len(cells)} tile(s) with 0x{v:X}", "attr"):
            self.doc.set_cells(cells)
        self.ed.status(f"Filled {len(cells)} tile(s) 0x{old:X} -> 0x{v:X}")

    right_press = PaintTool.right_press


class RectTool(Tool):
    name, label, key, cursor = "rect", "Rectangle", "r", "crosshair"
    hint = "Drag a rectangle to fill it with the ATTR value. Right-click picks a value."

    def __init__(self, ed):
        super().__init__(ed)
        self.a = None

    def cancel(self):
        self.a = None
        self.view.preview_rect(None)

    def press(self, e):
        self.a = self.view.tile_at(e)

    def drag(self, e):
        if self.a is not None:
            b = self.view.tile_at(e, clamp=True)
            self.view.preview_rect((*self.a, *b), color="#ffe000", dash=())

    def release(self, e):
        if self.a is None:
            return
        b = self.view.tile_at(e, clamp=True)
        a, self.a = self.a, None
        self.view.preview_rect(None)
        v = self.ed.paint_value
        if v is None:
            return
        cells = {(x, y): v for x in range(min(a[0], b[0]), max(a[0], b[0]) + 1)
                 for y in range(min(a[1], b[1]), max(a[1], b[1]) + 1)}
        with self.doc.edit(f"Fill rectangle with 0x{v:X}", "attr"):
            self.doc.set_cells(cells)

    right_press = PaintTool.right_press


class PickTool(Tool):
    name, label, key, cursor = "pick", "Pick", "i", "target"
    hint = "Click a tile to take its ATTR value; the previous tool comes back."

    def press(self, e):
        t = self.view.tile_at(e)
        if t is not None:
            self.ed.set_paint_value(self.doc.cell(*t))
            self.ed.set_tool(self.ed.prev_paint_tool or "paint")


# --------------------------------------------------------------------------- #
class AddTool(Tool):
    name, label, key, cursor = "add", "Add", "a", "plus"
    hint = "Click a tile to place the chosen kind of object there."

    def press(self, e):
        t = self.view.tile_at(e)
        if t is None:
            return
        ed, doc = self.ed, self.doc
        sx, sy = (t[0] << 3) + 4, (t[1] << 3) + 4          # tile centre in sub-units
        what = ed.add_kind
        if what == "entity":
            tid = ed.add_type
            if tid is None:
                ed.status("Pick an entity type first (Inspector > Add).")
                return
            if 9 <= (tid & 0xFFFF) <= 19:
                sx = sy = 0                  # map parameter records have no position
            with doc.edit(f"Add entity type {tid}", "mobj"):
                i = doc.map.add_mobj_record([tid, -1, -1, -1, -1, -1, 4096, 0,
                                             0, 0, 0, 0, 0, -1, sx, sy])
            ed.select(("mobj", i))
        elif what == "spot":
            with doc.edit("Add search spot", "si"):
                si = doc.ensure_si()
                si.spots.append(search_items.SearchSpot(x=sx, y=sy,
                                                        pool=search_items.DropPool(entries=[])))
            ed.select(("si", len(doc.si.spots) - 1))
        elif what in ("gpos", "mpos"):
            g = ed.active_gate
            if g is None:
                ed.status("Select a gate in the Gates tab first.")
                return
            with doc.edit("Add " + ("gate position" if what == "gpos" else "monster spawn point"), "gen"):
                if what == "gpos":
                    doc.gen.add_gate_position(g, sx, sy)
                else:
                    doc.gen.add_monster_position(g, sx, sy)
            pts = doc.gen.gate_positions_off(g) if what == "gpos" else doc.gen.monster_positions_off(g)
            ed.select((what, pts[-1][0]))


class WarpTool(Tool):
    name, label, key, cursor = "warp", "Warp", "w", "crosshair"
    hint = ("Drag out a rectangle to create a warp zone. It leads back to this map until "
            "you pick a destination in the Inspector.")

    def __init__(self, ed):
        super().__init__(ed)
        self.a = None

    def cancel(self):
        self.a = None
        self.view.preview_rect(None)

    def press(self, e):
        self.a = self.view.tile_at(e)

    def drag(self, e):
        if self.a is not None:
            self.view.preview_rect((*self.a, *self.view.tile_at(e, clamp=True)), color="#ffd040", dash=())

    def release(self, e):
        if self.a is None:
            return
        b = self.view.tile_at(e, clamp=True)
        a, self.a = self.a, None
        self.view.preview_rect(None)
        x0, y0 = min(a[0], b[0]), min(a[1], b[1])
        w, h = abs(a[0] - b[0]) + 1, abs(a[1] - b[1]) + 1
        here = self.ed.this_map_id() or 0
        with self.doc.edit("Add warp", "mapj"):
            j = self.doc.map.add_mapj_record([-1, x0 * 8, y0 * 8, w * 8, h * 8, here,
                                              (x0 + w // 2) * 8 + 4, (y0 + h + 1) * 8 + 4, 0])
        self.ed.select(("warp", j))
        self.ed.status(f"Added warp #{j} ({w}x{h} tiles) -- pick its destination in the Inspector")


TOOLS = (SelectTool, PaintTool, FillTool, RectTool, PickTool, AddTool, WarpTool)
PAINT_TOOLS = ("paint", "fill", "rect", "pick")
