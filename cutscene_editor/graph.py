"""The Graph tab: the open scene's control flow as blocks and arrows (cfg.build / cfg.layout).

Drag the background to pan, drag a block to move it (Reset layout puts every block back),
the wheel zooms at the pointer (Ctrl+wheel scrolls up / down, Shift+wheel sideways), Fit shows
the whole scene. The selected statement's block shows in gold every block and arrow that can
lead to it (the path from the scene's start, CALLs included). A click on a line selects that statement (the Inspector shows it), a
double click opens it in the Script tab. Green arrows = the branch taken when its guard is
true, red = when it is false, orange = switch / choice / random slots; back edges (loops) run
up the right-hand side of their group. The scene body is drawn on top and every CALLed
subroutine as its own titled group below it; a CALL block carries a "-> sub @xxxx" link that
scrolls to that group (the thin "return" arrow continues after the call).
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from guiutil import Tip

from . import cfg
from .render import SceneText

BG = "#15151b"
BLOCK = "#23232d"
BLOCK_ENTRY = "#2c3a2c"
BLOCK_RET = "#3a2c2c"
BORDER = "#5a5a6a"
GROUP_BORDER = "#34343f"
GROUP_TITLE = "#b0b0c0"
TEXT = "#dcdce4"
ADDR = "#8a8a9a"
SEL = "#8a6a10"
PATH = "#f0c040"                   # the blocks / arrows that lead to the selected block
EDGE = {"yes": "#5ec46e", "no": "#e06464", "jmp": "#9aa0b4", "fall": "#9aa0b4",
        "call": "#86b0ff", "case": "#e0a050"}
FONT = "Consolas"
BASE_PX = 12               # font height in pixels at zoom 1 (world units = pixels at zoom 1)
PAD = 6.0


class GraphTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=2, pady=2)
        for text, cmd, tip in (("Fit", self.fit, "Show the whole scene."),
                               ("100 %", lambda: self.set_zoom(1.0), "Actual size."),
                               ("−", lambda: self.set_zoom(self.zoom / 1.25), "Zoom out (mouse wheel)."),
                               ("+", lambda: self.set_zoom(self.zoom * 1.25), "Zoom in (mouse wheel)."),
                               ("Selection", self.show_selection,
                                "Scroll to the block of the selected statement."),
                               ("Reset layout", self.reset_layout,
                                "Put every block you dragged back where the layout placed it.")):
            b = ttk.Button(bar, text=text, command=cmd, width=len(text) + 2)
            b.pack(side="left", padx=1)
            Tip(b, tip)
        self.info = ttk.Label(bar, text="", font=("Segoe UI", 8), foreground="#888")
        self.info.pack(side="left", padx=8)
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        ys = ttk.Scrollbar(box)
        ys.pack(side="right", fill="y")
        xs = ttk.Scrollbar(box, orient="horizontal")
        xs.pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(box, bg=BG, highlightthickness=0, xscrollcommand=xs.set,
                                yscrollcommand=ys.set, confine=False)
        self.canvas.pack(side="left", fill="both", expand=True)
        ys.config(command=self.canvas.yview)
        xs.config(command=self.canvas.xview)
        c = self.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._double)
        c.bind("<MouseWheel>", self._zoom_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: self._wheel(e, horizontal=True))
        c.bind("<Control-MouseWheel>", self._wheel)
        c.bind("<Configure>", lambda _e: self._fit_if_new())
        self.zoom = 1.0
        self.blocks = {}
        self.back = set()
        self.size = (0.0, 0.0)
        self.groups = []
        self._key = None
        self._link_items = {}            # canvas text item -> subroutine root (a CALL's link)
        self._line_items = {}            # canvas text item -> pc
        self._sel_item = None
        self._press_at = None
        self._dragged = False
        self._drag_block = None          # the block being dragged (its start pc)
        self._drag_last = None
        self._moved = {}                 # (bank pos, scene entry) -> {block start: (dx, dy)}
        self._preds = {}                 # block start -> [(pred start, edge index)] (CALLs too)
        self._edge_geo = {}              # (src, edge index) -> world points of the drawn arrow
        self._base = {}                  # block start -> (x, y) where the layout put it
        self._needs_fit = False
        self._shown_sel = None           # the selection the graph last scrolled to / marked
        self._fonts = {}                 # pixel size -> tkfont.Font
        base = self._font(BASE_PX)
        self.char_w = float(base.measure("0"))
        self.line_h = float(base.metrics("linespace") + 2)

    # ---- data ------------------------------------------------------------------ #
    def render(self, force=False):
        """Rebuild the graph when the scene or its bytes changed (cheap otherwise)."""
        app = self.app
        sc, bank = app.scene, app.bank
        key = (app.bank_pos, sc.entry_pc if sc is not None else None,
               bytes(bank.data) if bank is not None else None, app.doc.locale)
        if not force and key == self._key:
            self._follow_selection()
            return
        new_scene = self._key is None or key[:2] != self._key[:2]
        self._key = key
        if sc is None or bank is None:
            self.blocks, self.back, self.size, self.groups = {}, set(), (0.0, 0.0), []
            self.info.config(text="open a scene on the left")
            self.draw()
            return
        stext = SceneText(app.doc, bank, sc)
        def line(st):
            t = stext.code_line(st)
            return t.split(":", 1)[1].strip() if ":" in t[:6] else t
        self.blocks = cfg.build(sc, line_text=line, choice_text=stext.dlg)
        self.back, w, h, self.groups = cfg.layout(self.blocks, sc.entry_pc, self._block_size)
        self._base = {st_: (b.x, b.y) for st_, b in self.blocks.items()}
        for st_, (dx, dy) in self._moved.get(self._scene_key(), {}).items():
            b = self.blocks.get(st_)
            if b is not None:
                b.x += dx
                b.y += dy
        self.size = self._bounds()[2:]
        self._preds = {st_: [] for st_ in self.blocks}
        for s0, b in self.blocks.items():
            for k, (t, _kind, _lab) in enumerate(b.edges):
                if t in self._preds:
                    self._preds[t].append((s0, k))
        n_subs = sum(1 for g in self.groups if g.callers)
        self.info.config(text="%d statements · %d blocks%s%s" % (
            len(sc.stmts), len(self.blocks),
            " · %d subroutine(s)" % n_subs if n_subs else "",
            " · %d loop(s)" % len(self.back) if self.back else ""))
        if new_scene:
            self._needs_fit = True
            self._fit_if_new()
        else:
            self.draw()
        self._follow_selection()

    def _follow_selection(self):
        """Mark the selected statement; when it changed since the graph last showed one (a
        line picked in the Script tab), also scroll its block into view."""
        sel = getattr(self.app, "sel", None)
        moved = sel is not None and sel != self._shown_sel
        self._shown_sel = sel
        if self._needs_fit:                  # not laid out on screen yet: _fit_if_new follows
            self._shown_sel = None if moved else sel
            return
        self._mark_selection(see=moved)

    def _font(self, px):
        f = self._fonts.get(px)
        if f is None:
            f = self._fonts[px] = tkfont.Font(family=FONT, size=-px)
        return f

    def _font_for(self, z):
        """The largest font whose characters fit the layout's cells at zoom z."""
        px = max(1, int(BASE_PX * z))
        while px > 1 and (self._font(px).measure("0") > self.char_w * z
                          or self._font(px).metrics("linespace") > self.line_h * z):
            px -= 1
        return self._font(px)

    def _block_size(self, b):
        chars = max((len(t) + 6 for _pc, t in b.lines), default=8)
        return (max(90.0, chars * self.char_w + 2 * PAD), len(b.lines) * self.line_h + 2 * PAD)

    def _scene_key(self):
        return (self.app.bank_pos, self.app.scene.entry_pc if self.app.scene is not None else None)

    def _bounds(self):
        """(x0, y0, x1, y1) around every block (world units), 0 at least on the top-left."""
        if not self.blocks:
            return 0.0, 0.0, 0.0, 0.0
        bs = self.blocks.values()
        return (min(0.0, min(b.x for b in bs)), min(0.0, min(b.y for b in bs)),
                max(b.x + b.w for b in bs), max(b.y + b.h for b in bs))

    def _group_box(self, g):
        """A group's frame around its blocks as they are now (the user may have moved some)."""
        bs = [self.blocks[s] for s in g.starts if s in self.blocks]
        if not bs:
            return g.x, g.y, g.x + g.w, g.y + g.h
        return (min(b.x for b in bs), min(b.y for b in bs) - cfg.GROUP_TITLE_H,
                max(b.x + b.w for b in bs), max(b.y + b.h for b in bs))

    def reset_layout(self):
        """Forget the blocks the user dragged in this scene."""
        self._moved.pop(self._scene_key(), None)
        self.render(force=True)

    # ---- drawing --------------------------------------------------------------- #
    def draw(self):
        c = self.canvas
        c.delete("all")
        self._line_items = {}
        self._link_items = {}
        self._sel_item = None
        z = self.zoom
        if not self.blocks:
            c.configure(scrollregion=(0, 0, 1, 1))
            return
        margin = 40 * z
        font = self._font_for(z)
        bx0, by0, bx1, by1 = self._bounds()
        # a window's worth of room on every side: the graph can be put anywhere in view
        mx = max(margin, c.winfo_width() - 40)
        my = max(margin, c.winfo_height() - 40)
        c.configure(scrollregion=(bx0 * z - mx, (by0 - 30) * z - my, (bx1 + 60) * z + mx,
                                  by1 * z + my))
        entry = next(iter(self.blocks))
        owner = {}
        for g in self.groups:
            for st_ in g.starts:
                owner[st_] = g
        # group frames and titles, around the blocks as they are now
        boxes = {}
        for g in self.groups:
            gx0, gy0, gx1, gy1 = boxes[g.root] = self._group_box(g)
            c.create_rectangle((gx0 - 10) * z, (gy0 - 4) * z, (gx1 + 34) * z, (gy1 + 10) * z,
                               outline=GROUP_BORDER, width=1, tags="frame")
            if z >= 0.2:
                c.create_text(gx0 * z, gy0 * z, text=g.title, anchor="nw", fill=GROUP_TITLE,
                              font=font, tags="frame")
        # edges first, blocks over them; a CALL is a link to its subroutine, not an arrow
        self._edge_geo = {}
        labels = []
        for s0, b in self.blocks.items():
            outs = [(k, e) for k, e in enumerate(b.edges) if e[1] != "call"]
            # a fan-out (choices, switch slots, random picks) labels each arrow where it ends,
            # above its target, instead of stacking all the labels under this block
            fan = sum(1 for _k, e in outs if e[2]) > 2
            at_target = {}
            for n, (k, (t, kind, lab)) in enumerate(outs):
                tb = self.blocks.get(t)
                if tb is None:
                    continue
                col = EDGE.get(kind, EDGE["jmp"])
                width = 1 if kind == "fall" and lab == "return" else 2
                pts, lx, ly = self._edge_points(s0, b, t, tb, n, len(outs), owner, boxes)
                self._edge_geo[(s0, k)] = pts
                tags = ("edge", "e%d" % s0, "e%d" % t)
                flat = [v * z for pt in pts for v in pt]
                c.create_line(*flat, fill=col, width=width, arrow="last", tags=tags,
                              arrowshape=(8 * z + 2, 9 * z + 2, 3 * z + 1), smooth=True)
                if not lab or z < 0.45:
                    continue
                if fan and (s0, t) not in self.back and t != s0:
                    at_target.setdefault(t, (col, []))[1].append(lab)
                else:
                    labels.append((lx * z, ly * z, lab, col, "w", tags))
            for t, (col, labs) in at_target.items():
                tb = self.blocks[t]
                # right-aligned so it ends just left of where the arrow comes in
                labels.append(((tb.x + tb.w / 2 - 8) * z, (tb.y - 9) * z, " / ".join(labs), col,
                               "e", ("edge", "e%d" % s0, "e%d" % t)))
        # the branch labels over every arrow, each letter outlined in the background colour
        # so the arrows crossing it don't hide it
        halo = max(1, round(z * 1.5))
        for x, y, lab, col, anchor, tags in labels:
            for dx, dy in ((-halo, 0), (halo, 0), (0, -halo), (0, halo),
                           (-halo, -halo), (halo, halo), (-halo, halo), (halo, -halo)):
                c.create_text(x + dx, y + dy, text=lab, anchor=anchor, fill=BG, font=font, tags=tags)
            c.create_text(x, y, text=lab, anchor=anchor, fill=col, font=font, tags=tags)
        show_text = z >= 0.35
        for s0, b in self.blocks.items():
            fill = BLOCK_ENTRY if s0 == entry else (BLOCK_RET if b.returns else BLOCK)
            tag = "b%d" % s0
            c.create_rectangle(b.x * z, b.y * z, (b.x + b.w) * z, (b.y + b.h) * z,
                               fill=fill, outline=BORDER, tags=("block", tag, "rect%d" % s0))
            if not show_text:
                continue
            for i, (pc, txt) in enumerate(b.lines):
                y = (b.y + PAD + i * self.line_h) * z
                if pc is not None:
                    c.create_text((b.x + PAD) * z, y, text="%04x" % pc, anchor="nw", fill=ADDR,
                                  font=font, tags=tag)
                link = b.link is not None and pc is None and i == len(b.lines) - 1
                it = c.create_text((b.x + PAD + 5.5 * self.char_w) * z, y, text=txt, anchor="nw",
                                   fill=EDGE["call"] if link else (TEXT if pc is not None else ADDR),
                                   font=font, tags=tag)
                if pc is not None:
                    self._line_items[it] = pc
                elif link:
                    self._link_items[it] = b.link
        self._mark_selection(see=False)

    def _edge_points(self, s0, b, t, tb, n, n_out, owner, boxes):
        """World points of the arrow from block b (start s0) to tb (start t), the n-th of
        b's n_out drawn arrows, and where its label goes: (points, label x, label y)."""
        if (s0, t) in self.back or t == s0:
            g = owner.get(s0)
            right = boxes[g.root][2] if g is not None and g.root in boxes else b.x + b.w
            lane = max(right, b.x + b.w, tb.x + tb.w) + 12
            pts = [(b.x + b.w, b.y + b.h - PAD), (lane, b.y + b.h - PAD),
                   (lane, tb.y + PAD), (tb.x + tb.w, tb.y + PAD)]
            return pts, lane + 4, (b.y + b.h + tb.y) / 2
        sx = b.x + b.w * (n + 1) / (n_out + 1)
        sy, tx, ty = b.y + b.h, tb.x + tb.w / 2, tb.y
        bend = 22 if tb.layer - b.layer > 1 else 14      # long edge: bend through the gap
        return [(sx, sy), (sx, sy + 14), (tx, ty - bend), (tx, ty)], sx + 4, sy + 8

    def path_to(self, target):
        """(blocks, edges) that can lead to block `target`: every block with a path to it
        (CALLs included, so a subroutine's callers count) and the drawn arrows between them.
        edges = {(src, edge index)}."""
        anc, stack = set(), [target]
        while stack:
            cur = stack.pop()
            for p_, _k in self._preds.get(cur, ()):
                if p_ not in anc:
                    anc.add(p_)
                    stack.append(p_)
        on = anc | {target}
        edges = {(p_, k) for t in on for p_, k in self._preds.get(t, ()) if p_ in anc}
        return anc, edges

    def _mark_selection(self, see=True):
        c = self.canvas
        c.delete("selbox")
        c.delete("pathhl")
        sel = getattr(self.app, "sel", None)
        if not sel or not self.blocks:
            return
        pc = sel[0]
        s = cfg.block_of(self.blocks, pc)
        if s is None:
            return
        b = self.blocks[s]
        z = self.zoom
        # the way to this block: gold arrows under the blocks, gold frames around them
        anc, edges = self.path_to(s)
        for (p_, k) in edges:
            pts = self._edge_geo.get((p_, k))
            if pts:
                c.create_line(*[v * z for pt in pts for v in pt], fill=PATH, width=3,
                              arrow="last", smooth=True, tags="pathhl",
                              arrowshape=(8 * z + 3, 9 * z + 3, 3 * z + 2))
        if c.find_withtag("pathhl"):
            c.tag_lower("pathhl", "block")
        for a_ in anc | {s}:
            ab = self.blocks[a_]
            c.create_rectangle(ab.x * z - 2, ab.y * z - 2, (ab.x + ab.w) * z + 2,
                               (ab.y + ab.h) * z + 2, outline=PATH,
                               width=3 if a_ == s else 2, tags=("pathhl", "pathbox%d" % a_))
        idx = next((i for i, (p, _t) in enumerate(b.lines) if p == pc), None)
        if idx is not None and z >= 0.35:
            y = b.y + PAD + idx * self.line_h
            box = c.create_rectangle((b.x + 2) * z, (y - 1) * z, (b.x + b.w - 2) * z,
                                     (y + self.line_h - 1) * z, fill=SEL, outline="", tags="selbox")
            c.tag_raise(box, "rect%d" % s)             # over the block, under its text
        else:
            c.create_rectangle(b.x * z - 2, b.y * z - 2, (b.x + b.w) * z + 2, (b.y + b.h) * z + 2,
                               outline=SEL, width=3, tags="selbox")
        if see:
            self._see(b)

    def _view_at(self, left, top):
        """Scroll so the canvas point (left, top) is the view's top-left corner."""
        c = self.canvas
        x0, y0, x1, y1 = (float(v) for v in c.cget("scrollregion").split())
        if x1 > x0:
            c.xview_moveto((left - x0) / (x1 - x0))
        if y1 > y0:
            c.yview_moveto((top - y0) / (y1 - y0))

    def _see(self, b):
        c = self.canvas
        z = self.zoom
        W, H = c.winfo_width(), c.winfo_height()
        cx, cy = (b.x + b.w / 2) * z, (b.y + b.h / 2) * z
        self._view_at(cx - W / 2, cy - H / 3)

    # ---- zoom / view ------------------------------------------------------------ #
    def set_zoom(self, z, at=None):
        z = max(0.1, min(3.0, z))
        c = self.canvas
        if at is None:
            at = (c.winfo_width() / 2, c.winfo_height() / 2)
        wx, wy = c.canvasx(at[0]) / self.zoom, c.canvasy(at[1]) / self.zoom
        self.zoom = z
        self.draw()
        self._view_at(wx * z - at[0], wy * z - at[1])      # the point under the pointer stays

    def fit(self):
        c = self.canvas
        W, H = max(50, c.winfo_width()), max(50, c.winfo_height())
        w, h = self.size
        if not w or not h:
            self.draw()
            return
        z = min(1.0, (W - 60) / (w + 90), (H - 60) / (h + 60))
        self.zoom = max(0.1, z)
        self.draw()
        self._view_at(-30, -30)

    def _fit_if_new(self):
        if self._needs_fit and self.canvas.winfo_width() > 50:
            self._needs_fit = False
            self.fit()
            if self.zoom < 0.35 and self.groups:   # too small to read: fit the scene body
                g = self.groups[0]
                c = self.canvas
                W, H = max(50, c.winfo_width()), max(50, c.winfo_height())
                self.zoom = max(0.35, min(1.0, (W - 60) / (g.w + 90), (H - 60) / (g.h + 60)))
                self.draw()
                self._view_at(-30, -30)
            self._follow_selection()

    def show_group(self, root):
        """Scroll to a subroutine's group (a CALL's link): its title at the top, its first
        block centred (a wide group's root sits in the middle of its first row)."""
        g = next((g for g in self.groups if g.root == root), None)
        if g is None:
            return
        c = self.canvas
        z = self.zoom
        rb = self.blocks.get(root)
        gx0, gy0, _gx1, _gy1 = self._group_box(g)
        cx = (rb.x + rb.w / 2) * z if rb is not None else gx0 * z
        self._view_at(max(gx0 * z - 20, cx - c.winfo_width() / 2), (gy0 - 20) * z)
        self.app.status("%s" % g.title)

    def show_selection(self):
        self._mark_selection(see=True)

    def mark_selection(self):
        """Highlight the selected statement without scrolling (a click in the graph, or a
        selection made in the Inspector)."""
        self._shown_sel = getattr(self.app, "sel", None)
        self._mark_selection(see=False)

    # ---- mouse ------------------------------------------------------------------ #
    def _block_at(self, e):
        """The start of the block under the pointer, or None."""
        c = self.canvas
        wx, wy = c.canvasx(e.x) / self.zoom, c.canvasy(e.y) / self.zoom
        for st_, b in reversed(list(self.blocks.items())):
            if b.x <= wx <= b.x + b.w and b.y <= wy <= b.y + b.h:
                return st_
        return None

    def _press(self, e):
        self.canvas.scan_mark(e.x, e.y)
        self._press_at = (e.x, e.y)
        self._dragged = False
        self._drag_block = self._block_at(e)
        self._drag_last = (e.x, e.y)

    def _drag(self, e):
        if self._press_at and abs(e.x - self._press_at[0]) + abs(e.y - self._press_at[1]) > 3:
            if not self._dragged and self._drag_block is not None:
                # its arrows and the highlights are redrawn when the block is dropped
                self.canvas.delete("e%d" % self._drag_block)
                self.canvas.delete("pathhl")
                self.canvas.delete("selbox")
            self._dragged = True
        if not self._dragged:
            return
        if self._drag_block is None:
            self.canvas.scan_dragto(e.x, e.y, gain=1)
            return
        dx, dy = e.x - self._drag_last[0], e.y - self._drag_last[1]
        self._drag_last = (e.x, e.y)
        self.canvas.move("b%d" % self._drag_block, dx, dy)
        b = self.blocks[self._drag_block]
        b.x += dx / self.zoom
        b.y += dy / self.zoom

    def _drop_block(self):
        """Remember where the dragged block went (for this scene, this session) and redraw."""
        s0 = self._drag_block
        self._drag_block = None
        b = self.blocks[s0]
        bx, by = self._base.get(s0, (b.x, b.y))          # where the layout put it
        self._moved.setdefault(self._scene_key(), {})[s0] = (b.x - bx, b.y - by)
        self.size = self._bounds()[2:]
        self.draw()

    def _release(self, e):
        if self._dragged:
            if self._drag_block is not None:
                self._drop_block()
            return
        self._drag_block = None
        c = self.canvas
        x, y = c.canvasx(e.x), c.canvasy(e.y)
        for it in c.find_overlapping(x - 1, y - 1, x + 1, y + 1):
            if it in self._link_items:
                self.show_group(self._link_items[it])
                return
        pc = self._pc_at(e)
        if pc is not None:
            self.app.select((pc, None))

    def _double(self, e):
        pc = self._pc_at(e)
        if pc is not None:
            self.app.goto(pc)

    def _pc_at(self, e):
        c = self.canvas
        x, y = c.canvasx(e.x), c.canvasy(e.y)
        for it in reversed(c.find_overlapping(x - 1, y - 1, x + 1, y + 1)):
            if it in self._line_items:
                return self._line_items[it]
        # a click beside the text: the line of the block under the pointer
        z = self.zoom
        wx, wy = x / z, y / z
        for b in self.blocks.values():
            if b.x <= wx <= b.x + b.w and b.y <= wy <= b.y + b.h:
                i = int((wy - b.y - PAD) // self.line_h)
                if 0 <= i < len(b.lines):
                    return b.lines[i][0]
                return b.pcs[0]
        return None

    def _wheel(self, e, horizontal=False):
        step = -1 if e.delta > 0 else 1
        (self.canvas.xview_scroll if horizontal else self.canvas.yview_scroll)(step * 3, "units")
        return "break"

    def _zoom_wheel(self, e):
        self.set_zoom(self.zoom * (1.15 if e.delta > 0 else 1 / 1.15), at=(e.x, e.y))
        return "break"
