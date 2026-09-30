"""The Graph tab: the open scene's control flow as blocks and arrows (cfg.build / cfg.layout).

Drag to pan, the wheel zooms at the pointer (Ctrl+wheel scrolls up / down, Shift+wheel
sideways), Fit shows the whole scene. A click on a line selects that statement (the Inspector shows it), a
double click opens it in the Script tab. Green arrows = the branch taken when its guard is
true, red = when it is false, dashed = a CALL (the thin "return" arrow continues after it),
orange = switch / choice / random slots; back edges (loops) run up the right-hand side.
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
TEXT = "#dcdce4"
ADDR = "#8a8a9a"
SEL = "#8a6a10"
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
                                "Scroll to the block of the selected statement.")):
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
                                yscrollcommand=ys.set)
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
        self._key = None
        self._line_items = {}            # canvas text item -> pc
        self._sel_item = None
        self._press_at = None
        self._dragged = False
        self._needs_fit = False
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
            self._mark_selection(see=False)
            return
        new_scene = self._key is None or key[:2] != self._key[:2]
        self._key = key
        if sc is None or bank is None:
            self.blocks, self.back, self.size = {}, set(), (0.0, 0.0)
            self.info.config(text="open a scene on the left")
            self.draw()
            return
        stext = SceneText(app.doc, bank, sc)
        def line(st):
            t = stext.code_line(st)
            return t.split(":", 1)[1].strip() if ":" in t[:6] else t
        self.blocks = cfg.build(sc, line_text=line, choice_text=app.doc.text)
        self.back, w, h = cfg.layout(self.blocks, sc.entry_pc, self._block_size)
        self.size = (w, h)
        n_edges = sum(len(b.edges) for b in self.blocks.values())
        self.info.config(text="%d statements · %d blocks · %d arrows%s" % (
            len(sc.stmts), len(self.blocks), n_edges,
            " · %d loop(s)" % len(self.back) if self.back else ""))
        if new_scene:
            self._needs_fit = True
            self._fit_if_new()
        else:
            self.draw()

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

    # ---- drawing --------------------------------------------------------------- #
    def draw(self):
        c = self.canvas
        c.delete("all")
        self._line_items = {}
        self._sel_item = None
        z = self.zoom
        if not self.blocks:
            c.configure(scrollregion=(0, 0, 1, 1))
            return
        margin = 40 * z
        font = self._font_for(z)
        w, h = self.size
        right = w + 24                                   # the loop lane
        c.configure(scrollregion=(-margin, -margin, (right + 60) * z + margin, h * z + margin))
        entry = next(iter(self.blocks))
        # edges first, blocks over them
        for s, b in self.blocks.items():
            outs = b.edges
            for k, (t, kind, lab) in enumerate(outs):
                tb = self.blocks.get(t)
                if tb is None:
                    continue
                col = EDGE.get(kind, EDGE["jmp"])
                dash = (4, 3) if kind == "call" else ()
                width = 1 if kind == "fall" and lab == "return" else 2
                sx = b.x + b.w * (k + 1) / (len(outs) + 1)
                if (s, t) in self.back or t == s:
                    lane = right + 8 * (len(self.back) % 5)
                    pts = [(b.x + b.w, b.y + b.h - PAD), (lane, b.y + b.h - PAD),
                           (lane, tb.y + PAD), (tb.x + tb.w, tb.y + PAD)]
                    lx, ly = lane + 4, (b.y + b.h + tb.y) / 2
                else:
                    sy, tx, ty = b.y + b.h, tb.x + tb.w / 2, tb.y
                    pts = [(sx, sy), (sx, sy + 14), (tx, ty - 14), (tx, ty)]
                    if tb.layer - b.layer > 1:           # long edge: bend through the gap
                        pts = [(sx, sy), (sx, sy + 14), (tx, ty - 22), (tx, ty)]
                    lx, ly = sx + 4, sy + 8
                flat = [v * z for p in pts for v in p]
                c.create_line(*flat, fill=col, width=width, dash=dash, arrow="last",
                              arrowshape=(8 * z + 2, 9 * z + 2, 3 * z + 1), smooth=True)
                if lab and z >= 0.45:
                    c.create_text(lx * z, ly * z, text=lab, anchor="w", fill=col, font=font)
        show_text = z >= 0.35
        for s, b in self.blocks.items():
            fill = BLOCK_ENTRY if s == entry else (BLOCK_RET if b.returns else BLOCK)
            c.create_rectangle(b.x * z, b.y * z, (b.x + b.w) * z, (b.y + b.h) * z,
                               fill=fill, outline=BORDER, tags=("block", "b%d" % s))
            if not show_text:
                continue
            for i, (pc, txt) in enumerate(b.lines):
                y = (b.y + PAD + i * self.line_h) * z
                if pc is not None:
                    c.create_text((b.x + PAD) * z, y, text="%04x" % pc, anchor="nw", fill=ADDR,
                                  font=font)
                it = c.create_text((b.x + PAD + 5.5 * self.char_w) * z, y, text=txt, anchor="nw",
                                   fill=TEXT if pc is not None else ADDR, font=font)
                if pc is not None:
                    self._line_items[it] = pc
        self._mark_selection(see=False)

    def _mark_selection(self, see=True):
        c = self.canvas
        c.delete("selbox")
        sel = getattr(self.app, "sel", None)
        if not sel or not self.blocks:
            return
        pc = sel[0]
        s = cfg.block_of(self.blocks, pc)
        if s is None:
            return
        b = self.blocks[s]
        z = self.zoom
        idx = next((i for i, (p, _t) in enumerate(b.lines) if p == pc), None)
        if idx is not None and z >= 0.35:
            y = b.y + PAD + idx * self.line_h
            box = c.create_rectangle((b.x + 2) * z, (y - 1) * z, (b.x + b.w - 2) * z,
                                     (y + self.line_h - 1) * z, fill=SEL, outline="", tags="selbox")
            c.tag_raise(box, "b%d" % s)
        else:
            c.create_rectangle(b.x * z - 2, b.y * z - 2, (b.x + b.w) * z + 2, (b.y + b.h) * z + 2,
                               outline=SEL, width=3, tags="selbox")
        if see:
            self._see(b)

    def _see(self, b):
        c = self.canvas
        z = self.zoom
        x0, y0, x1, y1 = (float(v) for v in c.cget("scrollregion").split())
        W, H = c.winfo_width(), c.winfo_height()
        cx, cy = (b.x + b.w / 2) * z, (b.y + b.h / 2) * z
        if x1 - x0 > W:
            c.xview_moveto(max(0.0, (cx - W / 2 - x0) / (x1 - x0)))
        if y1 - y0 > H:
            c.yview_moveto(max(0.0, (cy - H / 3 - y0) / (y1 - y0)))

    # ---- zoom / view ------------------------------------------------------------ #
    def set_zoom(self, z, at=None):
        z = max(0.1, min(3.0, z))
        c = self.canvas
        if at is None:
            at = (c.winfo_width() / 2, c.winfo_height() / 2)
        wx, wy = c.canvasx(at[0]) / self.zoom, c.canvasy(at[1]) / self.zoom
        self.zoom = z
        self.draw()
        x0, y0, x1, y1 = (float(v) for v in c.cget("scrollregion").split())
        if x1 > x0:
            c.xview_moveto(max(0.0, (wx * z - at[0] - x0) / (x1 - x0)))
        if y1 > y0:
            c.yview_moveto(max(0.0, (wy * z - at[1] - y0) / (y1 - y0)))

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
        c.xview_moveto(0.0)
        c.yview_moveto(0.0)

    def _fit_if_new(self):
        if self._needs_fit and self.canvas.winfo_width() > 50:
            self._needs_fit = False
            self.fit()
            if self.zoom < 0.35:                 # too small to read: start at the entry
                self.zoom = 0.6
                self.draw()
                entry = next(iter(self.blocks), None)
                if entry is not None:
                    self._see(self.blocks[entry])

    def show_selection(self):
        self._mark_selection(see=True)

    def mark_selection(self):
        """Highlight the selected statement without scrolling (a click in the graph, or a
        selection made in the Inspector)."""
        self._mark_selection(see=False)

    # ---- mouse ------------------------------------------------------------------ #
    def _press(self, e):
        self.canvas.scan_mark(e.x, e.y)
        self._press_at = (e.x, e.y)
        self._dragged = False

    def _drag(self, e):
        if self._press_at and abs(e.x - self._press_at[0]) + abs(e.y - self._press_at[1]) > 3:
            self._dragged = True
        if self._dragged:
            self.canvas.scan_dragto(e.x, e.y, gain=1)

    def _release(self, e):
        if self._dragged:
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
