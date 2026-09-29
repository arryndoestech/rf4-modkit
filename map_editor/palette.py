"""The object palette tab: every placeable MOBJ type as a picture, filterable; a click picks
the type for the Add tool, and the next click on the map places it."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from rf4s_modkit import gamepaths, mobj_types

from . import attrs, render, ui
from .inspector import mobj_choice, mobj_choices
from .tools import new_entity_record
from .ui import hint

try:
    from PIL import Image, ImageTk
except ImportError:                     # the palette falls back to coloured markers
    Image = ImageTk = None

FAVORITES_SETTING = "map_palette_favorites"     # settings.json: the favourite type ids
FAVORITES = "Favorites"

# (label, mobj_types.mobj_kind values shown); Favorites = the types the user starred
GROUPS = (("All", None), (FAVORITES, None), ("Decorations", ("decoration",)), ("Interactive objects", ("object",)),
          ("Actors (NPCs, doors, chests ...)", ("actor",)), ("Forage spawners", ("forage",)),
          ("Map parameters (no picture)", ("mapparam",)))


class PaletteTab(ttk.Frame):
    """A grid of cells, one per type: the sprite the game draws for a freshly added record
    (the Add tool's defaults), else a marker in the type's category colour, with the id and
    name under it. Pictures are made a few at a time while the tab is shown."""

    CELL_W, CELL_H, PIC = 112, 150, 72     # cell size, picture box (px)
    FONT_SIZE = 9                          # the names under the pictures (pt)
    NAME_LINES = 4                         # the name wraps onto up to this many lines
    UNUSED, USED = "#d8d8e0", "#9fe39f"    # name colour; green = already on this map
    BATCH = 6                              # pictures made per idle step

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        self.font = tkfont.Font(family="Segoe UI", size=self.FONT_SIZE)
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(top, text="Find").pack(side="left")
        self.query = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.query, width=14)
        e.pack(side="left", fill="x", expand=True, padx=(4, 6))
        ui.Tip(e, "Filter by type id or name (e.g. 'tree', 'chest', '253').")
        self.group = tk.StringVar(value=GROUPS[0][0])
        cb = ttk.Combobox(top, textvariable=self.group, values=[g[0] for g in GROUPS],
                          state="readonly", width=16)
        cb.pack(side="left")
        self.query.trace_add("write", lambda *_a: self._relayout())
        cb.bind("<<ComboboxSelected>>", lambda _e: self._relayout())
        hint(self, "Click an object to pick it, then click the map to place it (the Add tool, "
                   "A). Right-click: add to / remove from Favorites. Pictures show the object as "
                   "a new one looks; set its fields in the Inspector afterwards.", wrap=340).pack(anchor="w", fill="x", padx=4)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=4, pady=2)
        self.canvas = tk.Canvas(body, bg="#1b1b22", highlightthickness=0, cursor="hand2")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.info = ttk.Label(self, font=ui.HINT_FONT, wraplength=340, justify="left")
        self.info.pack(anchor="w", fill="x", padx=4, pady=(0, 4))
        self.types = [data_tid for data_tid in (_leading(c) for c in mobj_choices())
                      if data_tid is not None]
        self.sprites = render.Sprites()     # its own cache: the map's stays untouched
        self._photos = {}                   # tid -> PhotoImage | None (no picture)
        self._queue = []                    # tids still waiting for a picture
        self._job = None
        self._shown = []                    # tids laid out, in order
        self._cols = 1
        self._hover = None
        self.favorites = self._load_favorites()
        self.canvas.bind("<Button-3>", self._menu)
        self.canvas.bind("<Configure>", lambda _e: self._relayout())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.bind("<Map>", lambda _e: self._pump())

    # ---- the pictures ------------------------------------------------------ #
    def set_reader(self, reader):
        """A new game folder / texture source: every picture is made again."""
        if reader is self.sprites.reader:
            return
        self.sprites.reader = reader
        self.sprites.reset()
        self._photos.clear()
        self._relayout()

    def picture(self, tid):
        """The PIL picture of a new record of type `tid`, fitted into the picture box, or
        None (no sprite: map parameters, the herb pools, actors drawn as models only when
        the model is there). The wood / stone spawns show a Branch / Stone, as on the map."""
        if Image is None or self.sprites.reader is None:
            return None
        rec = new_entity_record(tid)
        o = {"type_id": rec[0], "name": mobj_types.mobj_name(tid), "pos_x": 0, "pos_y": 0,
             "params": rec}
        try:
            im = self.sprites.image(o)
        except Exception:  # noqa: BLE001 - a broken texture: the marker instead
            im = None
        if im is None:
            return None
        bbox = im.getbbox()                 # trim the transparent margin
        if bbox:
            im = im.crop(bbox)
        k = min(self.PIC / max(1, im.width), self.PIC / max(1, im.height), 2.0)
        return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.BILINEAR)

    def _pump(self):
        """Make the next few pictures of the laid-out cells (only while the tab is shown)."""
        self._job = None
        if not self.winfo_ismapped():
            return
        done = 0
        while self._queue and done < self.BATCH:
            tid = self._queue.pop(0)
            if tid in self._photos:
                continue
            pim = self.picture(tid)
            self._photos[tid] = ImageTk.PhotoImage(pim, master=self.canvas) if pim is not None else None
            self._draw_pic(tid)
            done += 1
        if self._queue:
            self._job = ui.later(self, self._pump, 1)

    def make_all(self):
        """Every picture of the laid-out cells right away (tests)."""
        while self._queue:
            tid = self._queue.pop(0)
            if tid not in self._photos:
                pim = self.picture(tid)
                self._photos[tid] = (ImageTk.PhotoImage(pim, master=self.canvas)
                                     if pim is not None else None)
                self._draw_pic(tid)

    # ---- layout -------------------------------------------------------------- #
    # ---- favourites (kept in settings.json across sessions) ------------------ #
    @staticmethod
    def _load_favorites():
        try:
            return {int(t) for t in gamepaths.get_setting(FAVORITES_SETTING, []) or []}
        except Exception:  # noqa: BLE001 - no / unreadable settings: none
            return set()

    def set_favorite(self, tid, on):
        """Star / unstar a type (remembered); the Favorites group follows at once."""
        if on:
            self.favorites.add(tid)
        else:
            self.favorites.discard(tid)
        try:
            gamepaths.set_setting(FAVORITES_SETTING, sorted(self.favorites))
        except OSError:
            pass                                # a read-only toolkit folder: this session only
        self._relayout()
        name = mobj_types.mobj_display_name(tid) or f"type {tid}"
        self.ed.status(f"{tid} {name} {'added to' if on else 'removed from'} the palette's favorites")

    def _menu(self, e):
        tid = self.tid_at(e.x, e.y)
        if tid is None:
            return
        m = tk.Menu(self, tearoff=False)
        if tid in self.favorites:
            m.add_command(label="Remove from favorites", command=lambda: self.set_favorite(tid, False))
        else:
            m.add_command(label="Add to favorites", command=lambda: self.set_favorite(tid, True))
        m.add_command(label="Pick to place", command=lambda: self.pick(tid))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def matches(self, tid):
        if self.group.get() == FAVORITES and tid not in self.favorites:
            return False
        kinds = dict(GROUPS).get(self.group.get())
        if kinds and mobj_types.mobj_kind(tid) not in kinds:
            return False
        q = self.query.get().strip().lower()
        if not q:
            return True
        text = f"{tid} {mobj_types.mobj_display_name(tid) or ''} {mobj_types.mobj_name(tid) or ''} " \
               f"{mobj_types.mobj_note(tid) or ''}".lower()
        return all(w in text for w in q.split())

    def _relayout(self):
        c = self.canvas
        c.delete("all")
        width = max(c.winfo_width(), self.CELL_W)
        self._cols = cols = max(1, width // self.CELL_W)
        self._shown = [t for t in self.types if self.matches(t)]
        on_map = self._on_map()
        for n, tid in enumerate(self._shown):
            x0, y0 = (n % cols) * self.CELL_W, (n // cols) * self.CELL_H
            tag = f"t{tid}"
            c.create_rectangle(x0 + 2, y0 + 2, x0 + self.CELL_W - 2, y0 + self.CELL_H - 2,
                               outline="#33333d", fill="#23232b", tags=(tag, "cell", f"cell{tid}"))
            name = mobj_types.mobj_display_name(tid) or f"type {tid}"
            c.create_text(x0 + self.CELL_W // 2, y0 + self.CELL_H - 4, anchor="s",
                          text=self._fit(f"{tid} {name}"), justify="center",
                          fill=self.USED if tid in on_map else self.UNUSED,
                          font=self.font, tags=(tag, f"name{tid}", "name"))
            self._draw_pic(tid, x0, y0)
            if tid in self.favorites:
                c.create_text(x0 + self.CELL_W - 6, y0 + 4, anchor="ne", text="★", fill="#ffd040",
                              font=self.font, tags=(tag, "star"))
        rows = (len(self._shown) + cols - 1) // cols
        c.configure(scrollregion=(0, 0, cols * self.CELL_W, max(rows * self.CELL_H, 1)))
        self.mark()
        self._queue = [t for t in self._shown if t not in self._photos]
        if self._queue and self._job is None:
            self._job = ui.later(self, self._pump, 1)
        if not self._shown:
            c.create_text(8, 8, anchor="nw", fill="#aaa", width=max(120, width - 16),
                          text="No favorites yet: right-click an object and choose Add to "
                               "favorites." if self.group.get() == FAVORITES and not self.favorites
                          else "No object type matches.")

    def _fit(self, text):
        """`text` word-wrapped onto at most NAME_LINES lines of the cell's width; only what
        still does not fit is cut (with an ellipsis). Hover shows the full name."""
        room = self.CELL_W - 8
        lines, cur = [], ""
        for word in re.sub(r"([-_])(?=\w)", r"\1 ", text).split(" "):
            trial = (cur + word if cur.endswith(("-", "_")) else f"{cur} {word}") if cur else word
            if self.font.measure(trial) <= room or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
        cut = len(lines) > self.NAME_LINES
        lines = lines[:self.NAME_LINES]
        out = []
        for k, line in enumerate(lines):
            last = k == len(lines) - 1
            if self.font.measure(line) > room or (last and cut):
                while line and self.font.measure(line + "…") > room:
                    line = line[:-1]
                line = line.rstrip() + "…"
            out.append(line)
        return "\n".join(out)

    def _cell_xy(self, tid):
        try:
            n = self._shown.index(tid)
        except ValueError:
            return None
        return (n % self._cols) * self.CELL_W, (n // self._cols) * self.CELL_H

    def _draw_pic(self, tid, x0=None, y0=None):
        if x0 is None:
            xy = self._cell_xy(tid)
            if xy is None:
                return
            x0, y0 = xy
        c = self.canvas
        c.delete(f"pic{tid}")
        cx, cy = x0 + self.CELL_W // 2, y0 + 4 + self.PIC // 2
        tags = (f"t{tid}", f"pic{tid}")
        photo = self._photos.get(tid)
        if photo is not None:
            c.create_image(cx, cy, image=photo, tags=tags)
        elif tid in self._photos or Image is None or self.sprites.reader is None:
            # no picture: the map's marker for this kind (map parameters, random forage ...)
            col = attrs.CAT_COLOR.get(mobj_types.mobj_kind(tid), "#888")
            r = self.PIC // 6
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="#000", tags=tags)
            c.create_text(cx, cy, text=str(tid), fill="#000", font=self.font, tags=tags)
        else:
            c.create_text(cx, cy, text="…", fill="#666", tags=tags)

    def _on_map(self):
        doc = getattr(self.ed, "doc", None)
        return {r[0] & 0xFFFF for r in doc.map.mobj_records()} if doc is not None else set()

    def mark(self):
        """Outline the type the Add tool will place."""
        c = self.canvas
        c.itemconfigure("cell", outline="#33333d", width=1)
        tid = getattr(self.ed, "add_type", None)
        if tid is not None:
            c.itemconfigure(f"cell{tid}", outline=render.SEL_COLOR, width=2)

    # ---- events -------------------------------------------------------------- #
    def tid_at(self, x, y):
        """The type under canvas-widget point (x, y), or None."""
        cx, cy = self.canvas.canvasx(x), self.canvas.canvasy(y)
        col, row = int(cx // self.CELL_W), int(cy // self.CELL_H)
        if cx < 0 or col >= self._cols:
            return None
        n = row * self._cols + col
        return self._shown[n] if 0 <= n < len(self._shown) else None

    def pick(self, tid):
        """Make `tid` the Add tool's type and switch to the Add tool (this tab stays open)."""
        ed = self.ed
        ed.inspector.add._pick(mobj_choice(tid))
        ed.set_add_kind("entity")
        ed.set_tool("add", focus=False)
        self.mark()
        name = mobj_types.mobj_display_name(tid) or f"type {tid}"
        ed.status(f"Click the map to place {tid} {name} (Esc: back to Select)")

    def _click(self, e):
        tid = self.tid_at(e.x, e.y)
        if tid is not None:
            self.pick(tid)

    def _motion(self, e):
        self._set_hover(self.tid_at(e.x, e.y))

    def _set_hover(self, tid):
        if tid == self._hover:
            return
        self._hover = tid
        if tid is None:
            self.info.config(text="")
            return
        n = sum(1 for r in self.ed.doc.map.mobj_records() if (r[0] & 0xFFFF) == tid) \
            if getattr(self.ed, "doc", None) is not None else 0
        none = (tid in self._photos and self._photos[tid] is None and tid >= 20
                and mobj_types.mobj_kind(tid) != "actor")
        self.info.config(text=f"{tid}: {mobj_types.mobj_label(tid)}"
                              + (f"  —  {n} on this map" if n else "")
                              + ("  —  the game ships no picture for it (invisible in game)"
                                 if none else ""))

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def refresh(self):
        """The map changed (objects added / removed, another map): names of the types on
        this map go green."""
        c = self.canvas
        on_map = self._on_map()
        c.itemconfigure("name", fill=self.UNUSED)
        for tid in on_map:
            c.itemconfigure(f"name{tid}", fill=self.USED)
        self.mark()


def _leading(text):
    head = text.split(None, 1)[0] if text else ""
    return int(head) if head.lstrip("-").isdigit() else None
