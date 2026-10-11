"""The map canvas: draws the background and the overlay groups as tagged layers,
hit-tests the pointer, zooms around the cursor, pans, and reports the hovered tile.

Redraws are incremental: `invalidate("sel")` re-creates only the selection ring, a
moved entity only the entity group, and so on. The background image (texture + ATTR)
is rebuilt only when the grid, zoom or a background setting changes."""
from __future__ import annotations

import sys
import tkinter as tk
import types
from tkinter import ttk

import guiutil
from rf4s_modkit import collisionstamp, mobj_types

from . import attrs, data, render, ui

ZOOMS = (2, 3, 4, 6, 8, 12, 16, 24)      # px per tile; 1 px showed nothing useful
OPEN_ZOOM = 6                              # px per tile a map opens at (Fit / 0 shows it all)
MAX_CANVAS_PX = 8192          # PhotoImage conversion above this gets slow
WHEEL_SETTING = "map_wheel"   # settings.json: "zoom" (default) or "scroll" -- the Options… window
_wheel_mode = None


def wheel_mode() -> str:
    """What the plain mouse wheel does on the map: "zoom" or "scroll" (Ctrl+wheel the other)."""
    global _wheel_mode
    if _wheel_mode is None:
        from rf4s_modkit import gamepaths
        _wheel_mode = "scroll" if gamepaths.get_setting(WHEEL_SETTING) == "scroll" else "zoom"
    return _wheel_mode


def set_wheel_mode(mode: str) -> None:
    """Choose what the wheel does, for every open map, and remember it in settings.json."""
    global _wheel_mode
    from rf4s_modkit import gamepaths
    _wheel_mode = "scroll" if mode == "scroll" else "zoom"
    gamepaths.set_setting(WHEEL_SETTING, _wheel_mode)


class ViewState:
    """What the overlay builders read (see render.overlay)."""

    def __init__(self):
        self.doc = None
        self.cp = 6
        self.layers = {}
        self.sel = None
        self.multi = ()                          # a multi-selection: every selected key
        self.active_gate = None
        self.gate_focus = False                  # outline the active gate's points (panel)
        self.spawns = []
        self.sprites = render.Sprites()
        self.flags = None                        # flagstate.FlagState the objects are shown for


class MapView(ttk.Frame):
    def __init__(self, parent, *, on_hover_tile=None):
        super().__init__(parent)
        self.st = ViewState()
        self.colors = {}
        self._colors_for = None                  # doc the colours were assigned for
        self.background = render.Background()
        self.ground = render.GroundLoader(self, self._ground_ready)
        self.ground_sel = "all"                  # display: off / all / '<n> <name>'
        self.scenery = True                      # draw the over-model scenery on the ground
        # the game's built-in warps / walls cover big areas: their tooltip pops up by itself
        # only when this is on; otherwise Shift over one shows it (the status line says so)
        self.runtime_tips = False
        self.attr_alpha = 180
        self.ground_dim = 25                 # % the ground is darkened (the View tab's slider)
        self.on_hover_tile = on_hover_tile       # fn(tile | None)
        self.on_zoom = None                      # fn() after the zoom changed
        self._items = {}                         # canvas item -> selection key
        self._labels = {}                        # group -> [placed label records] (_place_label)
        self._dirty = set()
        self._pending = False
        self._bg_photo = None
        self._attr_photo = None
        self._photos = {}                        # (type_id, size) -> PhotoImage
        self._tip = None
        self._pointer_e = None      # the last pointer position over the canvas (Alt at rest)

        hbar = ttk.Scrollbar(self, orient="horizontal")
        vbar = ttk.Scrollbar(self, orient="vertical")
        self.canvas = tk.Canvas(self, bg="#101014", highlightthickness=0,
                                xscrollcommand=hbar.set, yscrollcommand=lambda *a: self._yscrolled(vbar, a))
        hbar.config(command=self.canvas.xview)
        vbar.config(command=self.canvas.yview)
        self.status = ttk.Label(self, anchor="w", font=("Segoe UI", 8), padding=(4, 1))
        self.status.pack(side="bottom", fill="x")
        hbar.pack(side="bottom", fill="x")
        vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        c = self.canvas
        c.bind("<MouseWheel>", self._wheel)                 # zoom at the pointer (or scroll)
        c.bind("<Configure>", lambda _e: self._update_scrollregion(), add="+")
        # wheel amounts add up, so a trackpad's small steps scroll / zoom smoothly both ways
        self._xwheel = guiutil.wheel_handler(lambda n: c.xview_scroll(n, "units"), 3)
        self._ywheel = guiutil.wheel_handler(lambda n: c.yview_scroll(n, "units"), 3)
        self._zoom_acc = 0.0
        c.bind("<Shift-MouseWheel>", self._xwheel)
        c.bind("<Control-MouseWheel>", self._ctrl_wheel)    # the other one
        c.bind("<ButtonPress-2>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B2-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<Motion>", self._motion, add="+")
        c.bind("<Leave>", lambda _e: (self._set_pointer(None), self.hide_tip(), self._hover(None)),
               add="+")
        # Alt (like the cutscene editor; Ctrl still works) shows the ATTR tooltip, also when
        # pressed with the pointer at rest. "break" keeps a bare Alt from putting the window
        # into menu mode (tk::WinMenuKey), which would eat the next key.
        top = self.winfo_toplevel()
        for seq in ("<KeyPress-Alt_L>", "<KeyPress-Alt_R>"):
            top.bind(seq, lambda _e: self._alt(True), add="+")
        for seq in ("<KeyRelease-Alt_L>", "<KeyRelease-Alt_R>"):
            top.bind(seq, lambda _e: self._alt(False), add="+")

    # ---- document / settings ------------------------------------------- #
    @property
    def doc(self):
        return self.st.doc

    @property
    def cp(self):
        return self.st.cp

    def set_doc(self, doc):
        self.st.doc = doc
        self.st.sel = None
        self.st.active_gate = None
        self.st.spawns = []
        self.st.regions = []
        self.colors = attrs.assign_colors(doc.grid[2]) if doc.grid else {}
        self._colors_for = doc
        self.background.invalidate()
        self.invalidate_all()

    def set_reader(self, reader):
        if reader != self.ground.reader:
            self.ground.reader = reader
            self.ground.reset()
            self.st.sprites.reader = reader
            self.st.sprites.reset()
            self._photos.clear()
            self.background.invalidate()

    def grid_changed(self):
        """ATTR cells changed: give new values a colour and rebuild the background."""
        if self.doc is not None and self.doc.grid:
            attrs.assign_colors(self.doc.grid[2], self.colors)
        self.invalidate("bg")

    # ---- ground ------------------------------------------------------------ #
    def ground_key(self):
        d = self.doc
        if d is None:
            return None
        return (d.base, self.ground_sel, self.scenery, *(d.grid[:2] if d.grid else (0, 0)))

    def request_ground(self):
        d = self.doc
        if d is None or d.grid is None:
            return
        self.ground.request(d.base, self.ground_sel, d.grid[0], d.grid[1], self.scenery)

    def _ground_ready(self, key):
        if key == self.ground_key():
            self.invalidate("bg", "under")      # the held-back sprites appear with the ground

    def ground_pending(self):
        """True while the ground texture this view will show is still being decoded; the
        sprites wait for it, so they never pop up on an empty background."""
        d = self.doc
        if d is None or d.grid is None or not render.HAS_PIL or self.ground.reader is None:
            return False
        if self.ground_sel == "off" and not self.scenery:
            return False
        return not self.ground.has(self.ground_key())

    def ground_image(self, block=False):
        d = self.doc
        if d is None or d.grid is None or not render.HAS_PIL:
            return None
        if self.ground_sel == "off" and not self.scenery:
            return None
        if block:
            return self.ground.get_blocking(d.base, self.ground_sel, d.grid[0], d.grid[1],
                                            self.scenery)
        return self.ground.get(self.ground_key())

    def background_layers(self, block=False):
        """(ground, attr) images; the sprites are drawn between them."""
        d = self.doc
        L = self.st.layers
        return self.background.layers(
            d.grid, self.colors, self.cp, self.ground_image(block), attr_on=L.get("attr", True),
            alpha=self.attr_alpha, edges_on=L.get("edges", True), attr_version=d.attr_version,
            under=bool(L.get("sprites")), dim=self.ground_dim)

    # ---- redraw scheduling -------------------------------------------------- #
    def invalidate(self, *groups):
        groups = groups or ("bg",) + render.GROUPS
        if "ent" in groups:                     # the objects' sprites and their collision
            groups += ("under", "lift", "stamp")
        if "sel" in groups:                     # the selected sprite above the ATTR fill
            groups += ("lift",)
        self._dirty.update(groups)
        if not self._pending:
            self._pending = True
            ui.later(self, self.flush)

    def invalidate_all(self):
        self.invalidate("bg", *render.GROUPS)

    def flush(self):
        """Redraw everything invalidated so far (normally runs on idle)."""
        self._pending = False
        dirty, self._dirty = self._dirty, set()
        if not dirty:
            return
        c = self.canvas
        d = self.doc
        if d is None or d.grid is None:
            c.delete("all")
            self._items.clear()
            c.create_text(20, 20, anchor="nw", fill="#aaa",
                          text="(no map)" if d is None else "(this map has no ATTR grid)")
            return
        W, H, cells = d.grid
        if "bg" in dirty:
            c.delete("bg")
            c.delete("attr")
            ground, top = self.background_layers()
            if ground is not None or top is not None:
                from PIL import ImageTk
                self._bg_photo = ImageTk.PhotoImage(ground) if ground is not None else None
                self._attr_photo = ImageTk.PhotoImage(top) if top is not None else None
                if self._bg_photo is not None:
                    c.create_image(0, 0, anchor="nw", image=self._bg_photo, tags=("bg",))
                if self._attr_photo is not None:
                    c.create_image(0, 0, anchor="nw", image=self._attr_photo, tags=("attr",))
            elif not render.HAS_PIL and self.st.layers.get("attr", True):
                cp = self.cp
                for y in range(H):
                    for x in range(W):
                        rgb = self.colors.get(cells[y * W + x], attrs.ATTR_FLOOR)
                        c.create_rectangle(x * cp, y * cp, x * cp + cp, y * cp + cp,
                                           fill="#%02x%02x%02x" % rgb, width=0, tags=("bg",))
            self._update_scrollregion()
        for g in render.GROUPS:
            if g in dirty:
                self._draw_group(g)
        self._restack()

    def _draw_group(self, g):
        c = self.canvas
        for it in c.find_withtag(g):
            self._items.pop(it, None)
        c.delete(g)
        self._labels[g] = []
        if g in ("under", "lift") and self.ground_pending():
            return                              # drawn when the ground arrives (_ground_ready)
        for p in render.overlay(g, self.st):
            o = p.opt
            tags = (g,)
            if p.kind == "line":
                it = c.create_line(*p.xy, fill=o.get("fill"), width=o.get("width", 1),
                                   dash=o.get("dash", ""), arrow=o.get("arrow", "none"),
                                   arrowshape=(10, 12, 4), tags=tags)
            elif p.kind == "rect":
                it = c.create_rectangle(*p.xy, outline=o.get("outline", ""), fill=o.get("fill", ""),
                                        width=o.get("width", 1), dash=o.get("dash", ""),
                                        stipple=o.get("stipple", ""), tags=tags)
            elif p.kind == "oval":
                it = c.create_oval(*p.xy, outline=o.get("outline", ""), fill=o.get("fill", ""),
                                   width=o.get("width", 1), dash=o.get("dash", ""), tags=tags)
            elif p.kind == "poly":
                it = c.create_polygon(*p.xy, outline=o.get("outline", ""), fill=o.get("fill", ""),
                                      width=o.get("width", 1), tags=tags)
            elif p.kind == "text":
                font = ("Segoe UI", o.get("size", 8)) + (("bold",) if o.get("bold") else ())
                it = c.create_text(*p.xy, text=o["text"], fill=o.get("fill"), font=font,
                                   anchor=o.get("anchor", "center"), tags=tags)
                if o.get("below") or o.get("halo"):
                    self._place_label(it, p, font, tags, g)
            elif p.kind == "sprite":
                ph = self._sprite_photo(o["fn"], o["frame"], p.xy, o["mirror"])
                if ph is None:
                    continue
                it = c.create_image(p.xy[0], p.xy[1], image=ph, anchor="nw", tags=tags)
            else:
                continue
            if p.key is not None:
                self._items[it] = p.key
        if self._labels.get(g):
            self._fit_labels_to_view()

    # the outline: the label drawn again in the halo colour, one pixel off in every direction,
    # under the coloured text (a Tk canvas has no text outline of its own)
    HALO_OFFSETS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))

    def _place_label(self, it, p, font, tags, group):
        """A name label: the first spot of -- above its object, a line or three higher, under
        it, a line or two lower -- that stays on the map and overlaps no label already placed
        (when every one does: the one that overlaps least); shifted in from the left / right
        edges; then outlined. Remembered for _fit_labels_to_view."""
        c, o = self.canvas, p.opt
        d = self.st.doc
        mw = d.grid[0] * self.cp if d is not None and d.grid else None
        up = o.get("anchor", "s")
        box = c.bbox(it)
        if not box:
            return
        h = box[3] - box[1]
        (ax, ay), below = p.xy, o.get("below")
        spots = [((ax, ay - k * h), up) for k in range(4)]
        if below:
            spots += [((below[0], below[1] + k * h), "n") for k in range(3)]
        placed = [bx for recs in self._labels.values() for r in recs for bx in (r["box"],)]

        def put(xy, anchor):
            c.coords(it, *xy)
            c.itemconfigure(it, anchor=anchor)
            bx = c.bbox(it)
            if mw:
                dx = -bx[0] if bx[0] < 0 else (mw - bx[2] if bx[2] > mw else 0)
                if dx and bx[2] - bx[0] <= mw:
                    c.move(it, dx, 0)
                    bx = (bx[0] + dx, bx[1], bx[2] + dx, bx[3])
            return bx

        def overlap(bx):                        # area shared with the labels already placed
            return sum(max(0, min(bx[2], q[2]) - max(bx[0], q[0])) * max(0, min(bx[3], q[3]) - max(bx[1], q[1]))
                       for q in placed)
        chosen, best = None, None
        for xy, anchor in spots:
            bx = put(xy, anchor)
            if bx[1] < 0:                       # off the map's top edge
                continue
            ov = overlap(bx)
            if ov == 0:
                chosen = bx
                break
            if best is None or ov < best[0]:
                best = (ov, xy, anchor)
        if chosen is None:                      # crowded: the spot that overlaps least
            chosen = put(best[1], best[2]) if best else put(below or (ax, ay), "n" if below else up)
        halos = []
        halo = o.get("halo")
        if halo:
            x, y = c.coords(it)
            anchor = c.itemcget(it, "anchor")
            for ox, oy in self.HALO_OFFSETS:
                hid = c.create_text(x + ox, y + oy, text=o["text"], fill=halo, font=font,
                                    anchor=anchor, tags=tags)
                c.tag_lower(hid, it)
                halos.append(hid)
                if p.key is not None:
                    self._items[hid] = p.key
        self._labels.setdefault(group, []).append(
            {"it": it, "halos": halos, "box": chosen, "home": tuple(c.coords(it)),
             "home_anchor": c.itemcget(it, "anchor"), "under": below, "at_home": True})

    # ---- labels at the window's top edge ------------------------------------------ #
    def _yscrolled(self, vbar, args):
        vbar.set(*args)
        self._fit_labels_to_view()              # cheap: a few dozen coordinate checks

    def _fit_labels_to_view(self):
        """A label above its object that the window's top edge cuts off, while the object
        itself is in view, moves under the object; it moves back once there is room."""
        c = self.canvas
        try:
            if not c.winfo_exists():
                return
            top = c.canvasy(0)
        except tk.TclError:
            return
        for recs in self._labels.values():
            for r in recs:
                if r["home_anchor"] != "s" or not r["under"]:
                    continue                    # already under its object (or nowhere to go)
                cut = r["box"][1] < top <= r["under"][1]
                if cut and r["at_home"]:
                    # straight down (keeps the shift in from a side edge)
                    self._shift_label(r, 0, r["under"][1] - r["home"][1], "n")
                    r["at_home"] = False
                elif not cut and not r["at_home"]:
                    cx, cy = c.coords(r["it"])
                    self._shift_label(r, r["home"][0] - cx, r["home"][1] - cy, "s")
                    r["at_home"] = True

    def _shift_label(self, r, dx, dy, anchor):
        c = self.canvas
        for i in [r["it"]] + r["halos"]:
            c.move(i, dx, dy)
            c.itemconfigure(i, anchor=anchor)

    def _sprite_photo(self, fn, frame, rect, mirror):
        x0, y0, x1, y1 = rect
        w, h = x1 - x0, y1 - y0
        if w * h > MAX_CANVAS_PX * MAX_CANVAS_PX // 4:
            return None
        key = ("true", fn, frame, w, h, mirror)
        ph = self._photos.get(key)
        if ph is None:
            im = self.st.sprites.pil(fn, frame, w, h, mirror)
            if im is None:
                return None
            from PIL import ImageTk
            ph = self._photos[key] = ImageTk.PhotoImage(im)
            if len(self._photos) > 512:
                self._photos.pop(next(iter(self._photos)))
        return ph

    def _restack(self):
        c = self.canvas
        for g in render.STACK + ("stroke", "preview"):
            c.tag_raise(g)

    # ---- previews drawn by tools ------------------------------------------- #
    def preview_rect(self, tiles, color="#ffffff", tag="preview", dash=(3, 2)):
        """Outline a tile rectangle (x0, y0, x1, y1 inclusive), or clear it with None."""
        c = self.canvas
        c.delete(tag)
        if tiles is None:
            return
        cp = self.cp
        x0, y0, x1, y1 = tiles
        c.create_rectangle(min(x0, x1) * cp, min(y0, y1) * cp, (max(x0, x1) + 1) * cp,
                           (max(y0, y1) + 1) * cp, outline=color, dash=dash, width=1, tags=(tag,))
        c.tag_raise(tag)

    def stroke_cells(self, cells, value):
        """Draw painted cells straight onto the canvas while a stroke is in progress; the
        background is rebuilt once when the stroke ends."""
        cp = self.cp
        rgb = self.colors.get(value) or attrs.ATTR_PALETTE[len(self.colors) % len(attrs.ATTR_PALETTE)]
        col = "#%02x%02x%02x" % rgb
        for (x, y) in cells:
            self.canvas.create_rectangle(x * cp, y * cp, x * cp + cp, y * cp + cp, fill=col,
                                         outline="", tags=("stroke",))
        self.canvas.tag_raise("stroke")

    def clear_stroke(self):
        self.canvas.delete("stroke")

    # ---- coordinates + hit-testing ----------------------------------------- #
    def canvas_xy(self, e):
        return self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)

    def tile_at(self, e, clamp=False):
        d = self.doc
        if d is None or d.grid is None:
            return None
        x, y = self.canvas_xy(e)
        W, H, _ = d.grid
        tx, ty = int(x // self.cp), int(y // self.cp)
        if clamp:
            return max(0, min(W - 1, tx)), max(0, min(H - 1, ty))
        return (tx, ty) if 0 <= tx < W and 0 <= ty < H else None

    def subunit_at(self, e):
        """Pointer position in sub-units (8 per tile), clamped to the grid."""
        d = self.doc
        x, y = self.canvas_xy(e)
        W, H, _ = d.grid
        return (max(0, min(W * 8 - 1, int(x * 8 / self.cp))),
                max(0, min(H * 8 - 1, int(y * 8 / self.cp))))

    def edge_at(self, e):
        """Nearest tile boundary (0..W, 0..H) under the pointer."""
        d = self.doc
        x, y = self.canvas_xy(e)
        W, H, _ = d.grid
        return (max(0, min(W, round(x / self.cp))), max(0, min(H, round(y / self.cp))))

    def keys_at(self, e, slop=3):
        """Selection keys under the pointer, topmost first."""
        x, y = self.canvas_xy(e)
        out = []
        for it in reversed(self.canvas.find_overlapping(x - slop, y - slop, x + slop, y + slop)):
            k = self._items.get(it)
            if k is not None and k not in out:
                out.append(k)
        return out

    def warps_at(self, e):
        """Indices of the warp zones containing the pointer, smallest zone first."""
        t = self.tile_at(e)
        d = self.doc
        if t is None or not self.st.layers.get("mapj"):
            return []
        found = []
        for j, rec in enumerate(d.map.mapj_records()):
            x0, y0, x1, y1 = rec[1] >> 3, rec[2] >> 3, (rec[1] + rec[3]) >> 3, (rec[2] + rec[4]) >> 3
            if x0 <= t[0] <= max(x1, x0) and y0 <= t[1] <= max(y1, y0):
                found.append(((x1 - x0 + 1) * (y1 - y0 + 1), j))
        return [j for _a, j in sorted(found)]

    def warp_at(self, e):
        """Index of the warp zone containing the pointer (smallest zone wins)."""
        w = self.warps_at(e)
        return w[0] if w else None

    PICKABLE = ("mobj", "gpos", "mpos", "si", "spawn", "region", "warp")

    def pick_candidates(self, e, kinds=PICKABLE):
        """Everything a click here can select, in the order a click picks it: precise hits
        (markers, labels, outlines, sprite borders), then the warp zones under the pointer
        (smallest first), then the insides of sprites -- they lie below the warps
        and the ATTR fill, so they are the weakest hit (topmost sprite first)."""
        x, y = self.canvas_xy(e)
        strong, weak = [], []
        under = set(self.canvas.find_withtag("under"))
        for it in reversed(self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)):
            k = self._items.get(it)
            if k is None or k[0] not in kinds:
                continue
            (weak if it in under else strong).append(k)
        out = []
        warps = [("warp", j) for j in self.warps_at(e)] if "warp" in kinds else []
        for k in strong + warps + weak:
            if k not in out:
                out.append(k)
        return out

    # ---- zoom / scroll ------------------------------------------------------- #
    def max_zoom(self):
        d = self.doc
        if d is None or d.grid is None:
            return ZOOMS[-1]
        W, H, _ = d.grid
        return max(z for z in ZOOMS if z == ZOOMS[0] or max(W, H) * z <= MAX_CANVAS_PX)

    def _region_size(self):
        """(width, height) of the scroll region: the map, but never smaller than the canvas.
        A Tk canvas only pins its content while the region is larger than the window; a
        smaller region can be scrolled anywhere inside it, so a map shorter than the window
        (12 px zoom on most maps) could be dragged away from the top. Padding the region to
        the window keeps the map anchored top-left at every zoom."""
        d = self.doc
        if d is None or d.grid is None:
            return 1, 1
        W, H, _ = d.grid
        c = self.canvas
        return max(1, W * self.cp, c.winfo_width()), max(1, H * self.cp, c.winfo_height())

    def _update_scrollregion(self):
        if self.doc is None or self.doc.grid is None:
            return
        rw, rh = self._region_size()
        if self.canvas.cget("scrollregion") != "0 0 %d %d" % (rw, rh):
            self.canvas.config(scrollregion=(0, 0, rw, rh))

    def set_zoom(self, cp, anchor=None):
        """Zoom to `cp` px per tile, keeping the canvas point under `anchor` (widget x, y)
        fixed; without an anchor the view centre stays put."""
        cp = max(ZOOMS[0], min(self.max_zoom(), int(cp)))
        if cp == self.cp:
            return
        c = self.canvas
        ax, ay = anchor if anchor else (c.winfo_width() / 2, c.winfo_height() / 2)
        mx, my = c.canvasx(ax) / self.cp, c.canvasy(ay) / self.cp        # tile coords
        self.st.cp = cp
        self.invalidate_all()
        self.flush()
        if self.on_zoom:
            self.on_zoom()
        d = self.doc
        if d is not None and d.grid:
            tw, th = self._region_size()
            c.xview_moveto(max(0.0, (mx * cp - ax) / tw))
            c.yview_moveto(max(0.0, (my * cp - ay) / th))

    def zoom_step(self, direction, anchor=None):
        zs = [z for z in ZOOMS if z <= self.max_zoom()]
        if direction > 0:
            nxt = next((z for z in zs if z > self.cp), zs[-1])
        else:
            nxt = next((z for z in reversed(zs) if z < self.cp), zs[0])
        self.set_zoom(nxt, anchor)

    def _after_layout(self, fn):
        """False (and `fn` runs once the canvas has a size, on its first <Configure>) while the
        canvas has not been laid out yet; True when it has."""
        if self.canvas.winfo_width() >= 50 and self.canvas.winfo_height() >= 50:
            return True
        self._layout_wait = fn                  # the latest request wins
        if not getattr(self, "_fit_pending", False):
            self._fit_pending = True

            def later(_e=None):
                if self.canvas.winfo_width() >= 50:
                    self._fit_pending = False
                    self.canvas.unbind("<Configure>", self._fit_bind)
                    self._layout_wait()
            self._fit_bind = self.canvas.bind("<Configure>", later, add="+")
        return False

    def open_view(self, zoom=None, at=None):
        """How a map opens: OPEN_ZOOM px per tile (less when the map is too big for that),
        centred on the map. A warp followed from another map passes the zoom it was viewed
        at and the arrival tile to centre on instead."""
        d = self.doc
        if d is None or d.grid is None or not self._after_layout(lambda: self.open_view(zoom, at)):
            return
        self.set_zoom(min(zoom or OPEN_ZOOM, self.max_zoom()))
        if self.on_zoom:
            self.on_zoom()
        W, H, _ = d.grid
        tx, ty = at if at and 0 <= at[0] < W and 0 <= at[1] < H else (W / 2, H / 2)
        self.center_on(tx, ty)

    def fit(self):
        """Largest zoom at which the whole map is visible. Before the canvas has been laid
        out it has no size yet, so the fit waits for its first <Configure>."""
        d = self.doc
        if d is None or d.grid is None or not self._after_layout(self.fit):
            return
        W, H, _ = d.grid
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        fits = [z for z in ZOOMS if W * z <= cw and H * z <= ch and z <= self.max_zoom()]
        self.set_zoom(fits[-1] if fits else ZOOMS[0])
        if self.on_zoom:
            self.on_zoom()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def center_on(self, tx, ty):
        d = self.doc
        if d is None or d.grid is None:
            return
        c = self.canvas
        cw, ch = c.winfo_width(), c.winfo_height()
        rw, rh = self._region_size()
        c.xview_moveto(max(0.0, (tx * self.cp - cw / 2) / rw))
        c.yview_moveto(max(0.0, (ty * self.cp - ch / 2) / rh))

    def _wheel(self, e):
        if wheel_mode() == "scroll":
            return self._ywheel(e)
        return self._zoom_wheel(e)

    def _ctrl_wheel(self, e):
        """Ctrl+wheel does what the plain wheel doesn't (the Options… window)."""
        if wheel_mode() == "scroll":
            return self._zoom_wheel(e)
        return self._ywheel(e)

    def _zoom_wheel(self, e):
        """One zoom step per mouse notch (delta 120); a trackpad's small deltas add up."""
        self._zoom_acc += e.delta / 120
        while abs(self._zoom_acc) >= 1:
            step = 1 if self._zoom_acc > 0 else -1
            self._zoom_acc -= step
            self.zoom_step(step, (e.x, e.y))
        return "break"

    # ---- hover -------------------------------------------------------------- #
    # Tk's Alt bit: 0x20000 on Windows (Mod1 = 0x0008 is Num Lock there), Mod1 elsewhere
    ALT_MASK = 0x20000 if sys.platform == "win32" else 0x0008

    def _set_pointer(self, e):
        self._pointer_e = None if e is None else types.SimpleNamespace(
            x=e.x, y=e.y, x_root=e.x_root, y_root=e.y_root)

    def _alt(self, down):
        """Alt pressed / released with the pointer over the map: show / drop the ATTR tip."""
        p = self._pointer_e
        try:
            if p is None or self.doc is None or not self.canvas.winfo_ismapped():
                return None
        except tk.TclError:                    # this view's tab was closed: its binding stays
            return None
        self._tip_at(p, self.ALT_MASK if down else 0)
        return "break"

    def _motion(self, e):
        self._set_pointer(e)
        t = self.tile_at(e)
        self._hover(t)
        self._tip_at(e, e.state)

    def _tip_at(self, e, state):
        t = self.tile_at(e)
        if state & (self.ALT_MASK | 0x0004) and t is not None:   # Alt / Ctrl: ATTR inspector
            self.show_tip(e, self.attr_tip(t))
            return
        cands = self.pick_candidates(e)
        k = cands[0] if cands else None          # what a click would select
        if k is not None and k[0] == "warp":
            k = None                             # (warps show their destination on the map)
        text = self.describe_key(k) if k else None
        if not text and t is not None and (self.runtime_tips or state & 0x0001):
            # the game's runtime warps / walls (read-only, drawn dashed; Shift or the View
            # tab's option): under the pointer?
            text = "\n\n".join(self.runtime_tips_at(t)) or None
        if text:
            self.show_tip(e, text)
        else:
            self.hide_tip()

    def runtime_tips_at(self, t):
        """Tooltips of the game's built-in warps / walls covering tile `t` (while the warps
        layer is shown)."""
        if t is None or self.doc is None or not self.st.layers.get("mapj"):
            return []
        return [tip for (x0, y0, x1, y1), _s, tip in render.runtime_spawns(self.doc)
                if x0 <= t[0] < x1 and y0 <= t[1] < y1]

    def attr_tip(self, t):
        """The Alt tooltip: the cell's value and bits, who can walk on it, and the collision
        the placed objects stamp onto it when the room loads (not in the file)."""
        d = self.doc
        v = d.cell(*t)
        lines = [f"tile ({t[0]}, {t[1]})   ATTR = 0x{v:X}", attrs.attr_notes(v),
                 attrs.walk_readout(v)]
        for i, mode, bits in render.stamps_at(d, self.st.flags, t):
            o = d.objs[i]
            nm = mobj_types.mobj_display_name(o["type_id"] & 0xFFFF) or f"type {o['type_id']}"
            what = {"template": f"+0x{bits:X}", "box": "made solid (| 0x2)",
                    "replace": f"set to 0x{bits:X} (replaces the walking bits)"}[mode]
            after = collisionstamp.result(v, mode, bits)
            lines.append(f"stamped by #{i} {nm} at load: {what}  -> 0x{after:X}")
            lines.append("  -> " + attrs.walk_readout(after))
        return "\n".join(lines)

    def _hover(self, t):
        d = self.doc
        if t is None or d is None or d.grid is None:
            self.status.config(text=f"zoom {self.cp} px/tile" if d else "")
        else:
            v = d.cell(*t)
            rt = "" if self.runtime_tips else (
                "      built into the game: hold Shift for details" if self.runtime_tips_at(t) else "")
            self.status.config(text=f"tile ({t[0]}, {t[1]})   ATTR 0x{v:X}  {attrs.attr_notes(v)}"
                                    f"{rt}      zoom {self.cp} px/tile")
        if self.on_hover_tile:
            self.on_hover_tile(t)

    def describe_key(self, k):
        d = self.doc
        kind, i = k
        if kind == "mobj" and i < len(d.objs):
            o = d.objs[i]
            tid = o["type_id"] & 0xFFFF
            head = mobj_types.mobj_display_name(tid) or f"type {tid}"
            text = f"#{i}  {head}\n{o['category']}  tile ({o['pos_x'] >> 3}, {o['pos_y'] >> 3})"
            rec = d.map.mobj_records()[i]
            loot = (data.chest_loot(rec) if tid == 44 else
                    data.crate_loot(rec, d.map.mgrp()) if tid == 53 else None)
            event = data.chest_event(rec, d.base) if tid == 44 else None
            return text + ("\n" + loot if loot else "") + ("\n" + event if event else "")
        if kind == "si" and d.si is not None and i < len(d.si.spots):
            sp = d.si.spots[i]
            return f"search spot #{i}  tile ({sp.tile_x}, {sp.tile_y})  {len(sp.pool.entries)} drop(s)"
        if kind in ("gpos", "mpos"):
            for pk, off, x, y, users in d.gate_points():
                if (pk, off) == k:
                    what = "gate position" if pk == "gpos" else "monster spawn point"
                    return f"{what}  tile ({x >> 3}, {y >> 3})  used by {len(users)} gate(s)"
        regions = getattr(self.st, "regions", None) or []
        if kind == "region" and i < len(regions):
            rg = regions[i]
            when = (f"while {rg['cond_name']} holds" if rg["cond"] >= 0
                    else "every time (no condition)")
            return (f"script area: tiles ({rg['x0'] >> 3}, {rg['y0'] >> 3})-({rg['x1'] >> 3}, "
                    f"{rg['y1'] >> 3})\na script scene runs while the player stands inside, "
                    f"{when} -- click to open it")
        if kind == "spawn" and self.st.spawns and i < len(self.st.spawns):
            sp = self.st.spawns[i]
            more = (f"\nspawned by {sp['copies']} lines of the script (alternatives); click opens "
                    f"the first") if sp.get("copies", 1) > 1 else ""
            if sp.get("kind") == "entity":
                return (f"{sp['name']} (type {sp['type_id'] & 0xFFFF})  tile ({sp['x'] >> 3}, "
                        f"{sp['y'] >> 3})\nplaced by the event script (SpawnMapEntity) once its "
                        f"scene runs -- click to open the line" + more)
            return (f"{sp['name']} (char {sp['char_id']}, instance {sp['instance']})\n"
                    f"placed by the event script -- click to open the line" + more)
        return None

    def show_tip(self, e, text):
        """The hover tooltip beside the pointer: wrapped to the monitor, and flipped to the
        pointer's left / above it where it would run off the monitor (never under it)."""
        if self._tip is None:
            self._tip = tk.Toplevel(self.canvas)
            self._tip.wm_overrideredirect(True)
            self._tip_label = tk.Label(self._tip, justify="left", bg="#222", fg="#eee",
                                       font=("Consolas", 8), bd=1, relief="solid", padx=4, pady=2,
                                       wraplength=guiutil.tip_wraplength(self.canvas, e.x_root,
                                                                         e.y_root, 480))
            self._tip_label.pack()
        if self._tip_label.cget("text") != text:
            self._tip_label.config(text=text)
            self._tip.update_idletasks()
        w, h = self._tip.winfo_reqwidth(), self._tip.winfo_reqheight()
        left, top, right, bottom = guiutil.monitor_rect(self.canvas, e.x_root, e.y_root)
        x, y = e.x_root + 14, e.y_root + 14
        if x + w > right - 4:
            x = e.x_root - 14 - w
        if y + h > bottom - 4:
            y = e.y_root - 14 - h
        self._tip.wm_geometry(f"+{max(left + 4, x)}+{max(top + 4, y)}")

    def hide_tip(self):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
