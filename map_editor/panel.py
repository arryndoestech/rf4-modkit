"""MapEditorPanel: the embeddable editor (toolbar, canvas, sidebar) and its controller
logic. Hosted by the standalone `MapExplorer` window and by rf4mod_gui's map view.

Host API (kept stable for rf4mod_gui):
    MapEditorPanel(parent, mapobj=None, name="", status_fn=None, on_change=None,
                   tex_reader=None, on_navigate=None, on_open_scene=None)
    .set_map(mapobj, name)      .tex_reader (settable)      .suspend()
    .confirm_discard(action)    .dirty_parts() / .is_dirty()
    .render_to_image(scale=None)  .cellpx  .map  .map_base
`on_change(bytes)` fires with the map's bytes after every edit (and undo) of the map."""
from __future__ import annotations

import copy
import pathlib
import tkinter as tk
from collections import Counter
from tkinter import filedialog, messagebox, ttk

from rf4s_modkit import map_names, mapground, mobj_types, rf4m, search_items

from . import data, dialogs, render, tools, ui
from .document import MapDocument
from .inspector import Inspector
from .tabs import LAYER_GROUPS, EncountersTab, MapTab, ObjectsTab, ProblemsTab, ViewTab
from .view import MapView

TABS = ("Inspect", "Objects", "Map", "Encounters", "View", "Problems")
_MOVE_ASPECT = {"mobj": "mobj", "warp": "mapj", "si": "si", "gpos": "gen", "mpos": "gen"}
_KIND_NAME = {"mobj": "entity", "warp": "warp", "si": "search spot", "gpos": "gate position",
              "mpos": "monster spawn point"}


class MapEditorPanel:
    def __init__(self, parent, mapobj=None, name="", status_fn=None, on_change=None,
                 tex_reader=None, on_navigate=None, on_open_scene=None):
        self.parent = parent
        self.status_fn = status_fn or (lambda s: None)
        self.on_change = on_change
        self.on_navigate = on_navigate
        self.on_open_scene = on_open_scene
        self.doc = None
        self.sel = None
        self.gate_index = None
        self.paint_value = 0x1
        self.brush = 1
        self.fill_global = False
        self.add_kind = "entity"
        self.add_type = 28
        self.prev_paint_tool = None
        self._spawns_for = None
        self._spawn_bank = None
        self._pending = set()
        self._dialogs = []
        self._build()
        self.tex_reader = tex_reader
        self.set_tool("select")
        if mapobj is not None:
            self.set_map(mapobj, name)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    def _build(self):
        from guiutil import Paned
        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_toolbar()
        # No live relayout while the sash is dragged (the sidebar is ~150 native
        # widgets); the sidebar keeps its width when the window resizes.
        paned = Paned(self.frame, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.view = MapView(paned, on_hover_tile=self._hover)
        paned.add(self.view, weight=4, minsize=240)
        side = ttk.Frame(paned, width=380)
        side.pack_propagate(False)            # a fixed start width, not the content's
        paned.add(side, weight=0, minsize=300, width=380)
        self.nb = ttk.Notebook(side)
        self.nb.pack(fill="both", expand=True)
        self.inspector = Inspector(self.nb, self)
        self.objects = ObjectsTab(self.nb, self)
        self.maptab = MapTab(self.nb, self)
        self.encounters = EncountersTab(self.nb, self)
        self.viewtab = ViewTab(self.nb, self)
        self.problems = ProblemsTab(self.nb, self)
        for w, t in zip((self.inspector, self.objects, self.maptab, self.encounters, self.viewtab,
                         self.problems), TABS):
            self.nb.add(w, text=t)
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._tab_changed())
        self.view.on_zoom = self._update_chrome
        self.view.st.layers = self.viewtab.layers()
        self.view.attr_alpha = self.viewtab.alpha.get()
        self._bind_canvas()
        self._bind_shortcuts()

    def _build_toolbar(self):
        bar = ttk.Frame(self.frame, padding=(2, 2))
        bar.pack(fill="x")
        mb = ttk.Menubutton(bar, text="Save")
        menu = tk.Menu(mb, tearoff=False)
        menu.add_command(label="Save all changed files…", accelerator="Ctrl+S", command=self.save_all)
        menu.add_separator()
        menu.add_command(label="Save map (.rf4m)…", command=self.save_map)
        menu.add_command(label="Save search items (SI_*.bin)…", command=self.save_si)
        menu.add_command(label="Save encounters (Gen*.bin)…", command=self.save_gen)
        menu.add_separator()
        menu.add_command(label="Export map view as PNG…", command=self.export_png)
        mb["menu"] = menu
        mb.pack(side="left")
        self.undo_btn = ttk.Button(bar, text="↶", width=3, command=self.undo)
        self.undo_btn.pack(side="left", padx=(6, 0))
        ui.Tip(self.undo_btn, lambda: self._undo_tip("undo"))
        self.redo_btn = ttk.Button(bar, text="↷", width=3, command=self.redo)
        self.redo_btn.pack(side="left")
        ui.Tip(self.redo_btn, lambda: self._undo_tip("redo"))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.tool_var = tk.StringVar(value="select")
        self.tools = {}
        for cls in tools.TOOLS:
            t = cls(self)
            self.tools[t.name] = t
            b = ttk.Radiobutton(bar, text=t.label, value=t.name, variable=self.tool_var,
                                style="Toolbutton", command=lambda n=t.name: self.set_tool(n))
            b.pack(side="left", padx=1)
            ui.Tip(b, f"{t.label}  ({t.key.upper()})\n{t.hint}")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="−", width=2, command=lambda: self.view.zoom_step(-1)).pack(side="left")
        self.zoom_lbl = ttk.Label(bar, width=6, anchor="center")
        self.zoom_lbl.pack(side="left")
        ttk.Button(bar, text="+", width=2, command=lambda: self.view.zoom_step(1)).pack(side="left")
        fit = ttk.Button(bar, text="Fit", width=4, command=self.view_fit)
        fit.pack(side="left", padx=(2, 0))
        ui.Tip(fit, "Fit the map in the window (0). Ctrl+wheel zooms at the pointer, middle-drag pans.")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="Validate", command=self.run_validation).pack(side="left")
        self.dirty_lbl = ttk.Label(bar, foreground="#c60", font=ui.HINT_FONT)
        self.dirty_lbl.pack(side="right", padx=6)

    def _bind_canvas(self):
        c = self.view.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<Control-ButtonPress-1>", self._ctrl_press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._double)
        c.bind("<ButtonPress-3>", self._right)
        c.bind("<Motion>", self._motion, add="+")

    def _bind_shortcuts(self):
        c = self.view.canvas
        for name, t in self.tools.items():
            c.bind(f"<KeyPress-{t.key}>", lambda _e, n=name: self.set_tool(n))
        for k in ("Delete", "BackSpace"):
            c.bind(f"<{k}>", lambda _e: self.delete(self.sel))
        c.bind("<Escape>", lambda _e: self.escape())
        for k, d in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
            c.bind(f"<{k}>", lambda _e, d=d: self.nudge(d[0] * 8, d[1] * 8))
            c.bind(f"<Shift-{k}>", lambda _e, d=d: self.nudge(*d))
        for k in ("plus", "equal", "KP_Add"):
            c.bind(f"<{k}>", lambda _e: self.view.zoom_step(1))
        for k in ("minus", "KP_Subtract"):
            c.bind(f"<{k}>", lambda _e: self.view.zoom_step(-1))
        c.bind("<Key-0>", lambda _e: self.view_fit())
        c.bind("<bracketleft>", lambda _e: self.set_brush(max(1, self.brush - 1 if self.brush <= 3 else self.brush - 2)))
        c.bind("<bracketright>", lambda _e: self.set_brush(min(9, self.brush + 1 if self.brush < 3 else self.brush + 2)))
        # Ctrl shortcuts work wherever the focus is inside the editor
        tag = f"MapEd{id(self)}"
        self._tag = tag
        self.frame.bind_class(tag, "<Control-z>", lambda _e: (self.undo(), "break")[1])
        self.frame.bind_class(tag, "<Control-y>", lambda _e: (self.redo(), "break")[1])
        self.frame.bind_class(tag, "<Control-Z>", lambda _e: (self.redo(), "break")[1])
        self.frame.bind_class(tag, "<Control-s>", lambda _e: (self.save_all(), "break")[1])

        def add_tag(w):
            tags = w.bindtags()
            if tag not in tags:
                w.bindtags((tags[0], tag) + tags[1:])
            for ch in w.winfo_children():
                add_tag(ch)
        add_tag(self.frame)

    # ------------------------------------------------------------------ #
    # host API
    # ------------------------------------------------------------------ #
    @property
    def tex_reader(self):
        return self._reader

    @tex_reader.setter
    def tex_reader(self, reader):
        self._reader = reader
        self.view.set_reader(reader)

    @property
    def map(self):
        return self.doc.map if self.doc else None

    @property
    def map_base(self):
        return self.doc.base if self.doc else ""

    @property
    def cellpx(self):
        return self.view.cp

    def set_map(self, mapobj, name):
        """Load a map (and its SI / Gen sidecars). Undo history starts fresh."""
        self.flush_edits()
        for w in self._dialogs:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._dialogs = []
        self.view.ground.suspend()
        self.doc = MapDocument(mapobj, name)
        self.doc.subscribe(self._changed)
        self.sel = None
        self.gate_index = None
        self._spawns_for = None
        self.view.set_doc(self.doc)
        if self.doc.grid:
            common = [v for v, _n in Counter(self.doc.grid[2]).most_common() if v]
            self.paint_value = common[0] if common else 0x1
        self.inspector.paint.sync(self.paint_value, self.view.colors)
        layers = []
        if render.HAS_PIL and self.tex_reader and self.doc.base:
            try:
                layers = mapground.available_layers(self.tex_reader, self.doc.base)
            except Exception:
                layers = []
        self.viewtab.set_available_layers(layers)
        self.view.ground_sel = self.viewtab.ground.get()
        if self.view.st.layers.get("spawns"):
            self._load_spawns()
        self.inspector.show_selection(None)
        self.inspector.refresh(frozenset({"attr"}))
        self.objects.rebuild()
        self.maptab.refresh()
        self.encounters.refresh()
        self.problems.tree.delete(*self.problems.tree.get_children())
        self.problems.summary.config(text="")
        self._update_chrome()
        self.view.request_ground()
        ui.later(self.frame, self.view_fit)

    def suspend(self):
        """The host is hiding the editor: stop background ground decodes."""
        self.view.ground.suspend()

    def dirty_parts(self):
        return self.doc.dirty_parts() if self.doc else []

    def is_dirty(self):
        return bool(self.dirty_parts())

    def confirm_discard(self, action="continue"):
        """Ask before throwing edits away. Yes = save each changed file (through its own
        Save dialog), No = discard, Cancel = stay. True when it is OK to proceed."""
        self.flush_edits()
        parts = self.dirty_parts()
        if not parts:
            return True
        ans = messagebox.askyesnocancel(
            "Unsaved changes",
            f"Unsaved changes to this map's {', '.join(parts)}.\n\n"
            f"Save before you {action}?\n(Yes = save, No = discard, Cancel = stay here)")
        if ans is None:
            return False
        return self.save_all() if ans else True

    # ------------------------------------------------------------------ #
    # document changes
    # ------------------------------------------------------------------ #
    def apply(self, label, aspects, fn):
        """Run `fn` as one undoable edit. A failure restores the files and is reported.
        Returns True when it ran (whether or not anything changed)."""
        if self.doc is None:
            return False
        try:
            with self.doc.edit(label, aspects):
                fn()
        except Exception as e:  # noqa: BLE001 - report the refusal, keep the editor alive
            messagebox.showerror("Not applied", f"{label}:\n{e}")
            return False
        return True

    def finish_edit(self):
        """Close a drag / stroke edit opened with doc.begin()."""
        step = self.doc.end()
        if step is not None:
            self.doc.notify(step.aspects)
            self.status(f"{step.label}")

    def _changed(self, aspects):
        v = self.view
        if "attr" in aspects or "chunks" in aspects:
            v.grid_changed()
        groups = set()
        if aspects & {"mobj", "chunks"}:
            groups |= {"ent", "sel"}
        if aspects & {"mapj", "chunks"}:
            groups |= {"warp", "dest", "sel"}
        if "si" in aspects:
            groups |= {"si", "sel"}
        if "gen" in aspects:
            groups |= {"gate", "sel"}
        if aspects & {"attr", "chunks"}:
            groups |= set(render.GROUPS)
        if groups:
            v.invalidate(*groups)
        self._validate_selection()
        live = self.doc.in_edit                       # mid-drag: keep it cheap
        self.inspector.refresh(aspects)
        if not live:
            self._schedule("objects", "maptab")
            if "gen" in aspects:
                self._schedule("encounters")
            if aspects & {"attr", "mobj", "mapj", "props", "chunks"} and self.on_change:
                try:
                    self.on_change(self.doc.map.build())
                except Exception:
                    pass
            self._update_chrome()

    def _schedule(self, *names):
        if not self._pending:
            ui.later(self.frame, self._run_pending)
        self._pending.update(names)

    def _run_pending(self):
        names, self._pending = self._pending, set()
        if self.doc is None:
            return
        if "objects" in names:
            self.objects.rebuild()
        if "maptab" in names:
            self.maptab.refresh()
        if "encounters" in names:
            self.encounters.refresh()

    def _validate_selection(self):
        d = self.doc
        g = self.gate_index
        if g is not None and (d.gen is None or g[0] >= len(d.gen.patterns) or g[1] >= len(d.gen.patterns[g[0]])):
            self.gate_index = None
            self.view.st.active_gate = None
        else:
            self.view.st.active_gate = self.active_gate
        s = self.sel
        if s is None:
            return
        kind, k = s
        ok = ((kind == "mobj" and k < len(d.objs)) or
              (kind == "warp" and k < len(d.map.mapj_records())) or
              (kind == "si" and d.si is not None and k < len(d.si.spots)) or
              (kind in ("gpos", "mpos") and any((pk, off) == s for pk, off, *_r in d.gate_points())))
        if not ok:
            self.select(None)

    def _update_chrome(self):
        parts = self.dirty_parts()
        self.dirty_lbl.config(text=("● unsaved: " + ", ".join(parts)) if parts else "")
        d = self.doc
        self.undo_btn.state(["!disabled"] if d and d.undo_stack else ["disabled"])
        self.redo_btn.state(["!disabled"] if d and d.redo_stack else ["disabled"])
        self.zoom_lbl.config(text=f"{self.view.cp} px")

    def _undo_tip(self, which):
        d = self.doc
        st = (d.undo_stack if which == "undo" else d.redo_stack) if d else []
        key = "Ctrl+Z" if which == "undo" else "Ctrl+Y"
        return f"{which.capitalize()}: {st[-1].label}  ({key})" if st else f"Nothing to {which}"

    def flush_edits(self):
        """Commit a half-typed field before anything changes what the forms show."""
        try:
            w = self.frame.focus_get()
        except (KeyError, tk.TclError):
            w = None
        fn = getattr(w, "_commit", None)
        if fn is not None and self.doc is not None:
            fn()

    def undo(self):
        self.flush_edits()
        if self.doc is None:
            return
        step = self.doc.undo()
        self.status(f"Undid: {step.label}" if step else "Nothing to undo")
        self._update_chrome()

    def redo(self):
        self.flush_edits()
        if self.doc is None:
            return
        step = self.doc.redo()
        self.status(f"Redid: {step.label}" if step else "Nothing to redo")
        self._update_chrome()

    def status(self, msg):
        self.status_fn(msg)

    # ------------------------------------------------------------------ #
    # tools + canvas events
    # ------------------------------------------------------------------ #
    @property
    def tool(self):
        return self.tools[self.tool_var.get()]

    def set_tool(self, name):
        self.flush_edits()
        old = self.tools.get(getattr(self, "_tool_name", None))
        if old is not None:
            old.deactivate()
            if old.name in tools.PAINT_TOOLS and old.name != "pick":
                self.prev_paint_tool = old.name
        self._tool_name = name
        self.tool_var.set(name)
        t = self.tools[name]
        t.activate()
        self.view.canvas.config(cursor=t.cursor)
        self.view.canvas.focus_set()          # so the tool keys work right away
        self.inspector.show_tool(t)
        if name != "select" and self.nb.select() and self.nb.tab(self.nb.select(), "text") in ("Map", "View"):
            self.show_tab("Inspect")

    def start_add(self, kind):
        self.set_add_kind(kind)
        self.set_tool("add")
        self.show_tab("Inspect")

    def set_add_kind(self, kind):
        self.add_kind = kind
        self.inspector.add.sync()

    def set_paint_value(self, v):
        if v is None:
            return
        self.paint_value = v & 0xFFFFFFFF
        self.inspector.paint.sync(self.paint_value, self.view.colors)

    def set_brush(self, n):
        self.brush = n
        self.inspector.paint.vbrush.set(str(n))
        self.status(f"Brush {n}x{n}")

    def _press(self, e):
        self.flush_edits()
        self.view.canvas.focus_set()
        self.view.hide_tip()
        if self.doc is not None and self.doc.grid:
            self.tool.press(e)

    def _ctrl_press(self, e):
        self.view.canvas.focus_set()
        j = self.view.warp_at(e) if self.doc else None
        if j is not None:
            self.goto_warp(j)
            return "break"
        return self._press(e)

    def _drag(self, e):
        if self.doc is not None and self.doc.grid:
            self.tool.drag(e)

    def _release(self, e):
        if self.doc is not None and self.doc.grid:
            self.tool.release(e)
            self._update_chrome()

    def _double(self, e):
        if self.doc is not None and self.tool.name == "select":
            return self.tool.double(e)

    def _right(self, e):
        if self.doc is not None and self.doc.grid:
            self.tool.right_press(e)

    def _motion(self, e):
        if self.doc is not None and self.doc.grid:
            self.tool.motion(e)

    def _hover(self, t):
        self.inspector.hover(t)

    def escape(self):
        """Esc: abandon a drag / stroke in progress, otherwise clear the selection."""
        if self.doc is not None and self.doc.in_edit:
            self.tool.cancel()
            self.status("Cancelled")
        else:
            self.tool.cancel()
            self.select(None)

    def context_menu(self, e, key):
        m = tk.Menu(self.frame, tearoff=False)
        if key[0] == "warp":
            m.add_command(label="Open destination map", command=lambda: self.goto_warp(key[1]))
            m.add_separator()
        m.add_command(label="Center view here", command=lambda: self.center_on(key))
        if key[0] in ("mobj", "warp", "si"):
            m.add_command(label="Duplicate", command=lambda: self.duplicate(key))
        if key[0] in ("gpos", "mpos"):
            users = next((u for pk, off, _x, _y, u in self.doc.gate_points() if (pk, off) == key), [])
            if users:
                m.add_command(label="Show its gate", command=lambda: self.show_gate(users[0]))
        m.add_separator()
        m.add_command(label="Delete", command=lambda: self.delete(key))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def view_fit(self):
        self.view.fit()
        self._update_chrome()

    # ------------------------------------------------------------------ #
    # selection
    # ------------------------------------------------------------------ #
    def select(self, key, center=False):
        if key is not None and key[0] in ("gpos", "mpos"):
            users = next((u for pk, off, _x, _y, u in self.doc.gate_points() if (pk, off) == tuple(key)), [])
            if users and self.gate_index not in users:
                self.set_active_gate(users[0])
        self.sel = tuple(key) if key is not None else None
        self.view.st.sel = self.sel
        self.view.invalidate("sel")
        self.inspector.show_selection(self.sel)
        self.objects.reveal(self.sel)
        if self.sel is not None:
            cur = self.nb.tab(self.nb.select(), "text") if self.nb.select() else ""
            if cur in ("Map", "View"):
                self.show_tab("Inspect")
            if center:
                self.center_on(self.sel)

    def show_tab(self, title):
        self.nb.select(TABS.index(title))

    def _tab_changed(self):
        pass

    @property
    def active_gate(self):
        g, d = self.gate_index, self.doc
        if g is None or d is None or d.gen is None:
            return None
        try:
            return d.gen.patterns[g[0]][g[1]]
        except IndexError:
            return None

    def set_active_gate(self, idx):
        self.gate_index = tuple(idx) if idx is not None else None
        self.view.st.active_gate = self.active_gate
        self.view.invalidate("gate")
        self.encounters.refresh()
        self.inspector.add.sync()

    def show_gate(self, idx):
        self.set_active_gate(idx)
        self.show_tab("Encounters")

    # ---- positions (shared by dragging, nudging and the forms) ---------- #
    def aspect_of(self, key):
        return _MOVE_ASPECT[key[0]]

    def describe_move(self, key, mode="move"):
        what = _KIND_NAME[key[0]]
        num = f" #{key[1]}" if key[0] in ("mobj", "warp", "si") else ""
        return f"{'Move' if mode == 'move' else 'Resize'} {what}{num}"

    def position_of(self, key):
        d = self.doc
        kind, k = key
        if kind == "mobj":
            r = d.map.mobj_records()[k]
            return (r[14], r[15])
        if kind == "warp":
            return tuple(d.map.mapj_records()[k][1:5])
        if kind == "si":
            sp = d.si.spots[k]
            return (sp.x, sp.y)
        for pk, off, x, y, _u in d.gate_points():
            if (pk, off) == tuple(key):
                return (x, y)
        return None

    def set_position(self, key, pos):
        """Move `key` to `pos` inside an open edit (live feedback)."""
        d = self.doc
        kind, k = key
        if kind == "mobj":
            r = list(d.map.mobj_records()[k])
            r[14], r[15] = pos
            d.map.set_mobj_record(k, r)
        elif kind == "warp":
            r = list(d.map.mapj_records()[k])
            r[1:5] = pos
            d.map.set_mapj_record(k, r)
        elif kind == "si":
            sp = d.si.spots[k]
            sp.x, sp.y = pos[0] & 0xFFFF, pos[1] & 0xFFFF
        else:
            d.gen.set_position(k, pos[0], pos[1])
        d.notify({self.aspect_of(key)})

    def set_position_edit(self, key, pos):
        self.apply(self.describe_move(key), self.aspect_of(key), lambda: self.set_position(key, pos))

    def nudge(self, dx, dy):
        s = self.sel
        if s is None or self.doc is None:
            return
        p = self.position_of(s)
        if p is None:
            return
        new = (p[0] + dx, p[1] + dy) + tuple(p[2:])
        if min(new[0], new[1]) < 0 and s[0] != "warp":
            return
        self.set_position_edit(s, new)

    def center_on(self, key):
        if key is None or self.doc is None:
            return
        p = self.position_of(key)
        if p is None:
            return
        x, y = p[0], p[1]
        if key[0] == "warp":
            x, y = x + p[2] // 2, y + p[3] // 2
        if key[0] == "mobj" and not (x or y):
            return
        self.view.center_on(x >> 3, y >> 3)

    # ---- delete / duplicate --------------------------------------------- #
    def delete(self, key):
        if key is None or self.doc is None:
            return
        d = self.doc
        kind, k = key
        label = f"Delete {_KIND_NAME[kind]}" + (f" #{k}" if kind in ("mobj", "warp", "si") else "")

        def do():
            if kind == "mobj":
                d.map.delete_mobj_record(k)
            elif kind == "warp":
                d.map.delete_mapj_record(k)
            elif kind == "si":
                del d.si.spots[k]
            else:
                e, i = d.locate_point(kind, k)
                if e is None:
                    return
                (d.gen.remove_gate_position if kind == "gpos" else d.gen.remove_monster_position)(e, i)
        self.select(None)
        if self.apply(label, self.aspect_of(key), do):
            self.status(label)

    def duplicate(self, key):
        if key is None or self.doc is None:
            return
        d = self.doc
        kind, k = key
        out = {}

        def do():
            if kind == "mobj":
                r = list(d.map.mobj_records()[k])
                if r[14] or r[15]:
                    r[14] += 8
                    r[15] += 8
                out["k"] = ("mobj", d.map.add_mobj_record(r))
            elif kind == "warp":
                r = list(d.map.mapj_records()[k])
                r[1] += 8
                r[2] += 8
                out["k"] = ("warp", d.map.add_mapj_record(r))
            elif kind == "si":
                sp = d.si.spots[k]
                pool = search_items.DropPool(entries=[search_items.DropEntry(item_id=e.effective_item_id,
                                                                             weight=e.effective_weight)
                                                      for e in sp.pool.entries])
                d.si.spots.append(search_items.SearchSpot(x=sp.x + 8, y=sp.y + 8, pool=pool))
                out["k"] = ("si", len(d.si.spots) - 1)
        if kind in ("mobj", "warp", "si") and self.apply(f"Duplicate {_KIND_NAME[kind]} #{k}",
                                                         self.aspect_of(key), do):
            self.select(out.get("k"))

    # ---- navigation ------------------------------------------------------- #
    def this_map_id(self):
        return data.map_id(self.doc.base) if self.doc else None

    def goto_warp(self, j):
        recs = self.doc.map.mapj_records()
        if j >= len(recs):
            return
        dest = recs[j][5]
        name = data.rooms_by_id().get(dest)
        if not name:
            self.status(f"warp → map id {dest}: no known .rf4m for it")
            return
        if not self.confirm_discard(f"open {name}"):
            return
        self.status(f"→ {name}")
        nav = self.on_navigate or self._navigate_local

        def go():
            try:
                nav(name)
            except Exception as ex:  # noqa: BLE001 - surface it instead of a silent trace
                self.status(f"opening {name} failed: {ex}")
        # the host may rebuild this panel: never do that inside our own click handler
        ui.later(self.frame, go)

    def _navigate_local(self, name):
        hit = data.find_extracted(f"{name}.rf4m")
        if hit is None:
            self.status(f"{name}.rf4m not found under {data.EXTRACTED}")
            return
        self.tex_reader = data.folder_reader(hit.parent)
        self.set_map(rf4m.Rf4mMap.load(hit), name)

    def _load_spawns(self):
        if self.doc is None or self._spawns_for is self.doc:
            return
        self.status("Scanning this map's event script for NPC spawns…")
        self.frame.update_idletasks()
        bank, spawns = data.script_spawns(self.doc.base)
        self._spawns_for = self.doc
        self._spawn_bank = bank
        self.view.st.spawns = spawns
        self.status(f"{len(spawns)} script-placed NPC(s) on this map" if bank is not None
                    else "No event script found for this map")
        self._schedule("objects")

    def open_spawn(self, i):
        sp = (self.view.st.spawns or [])[i] if i < len(self.view.st.spawns or []) else None
        if sp is None:
            return
        if self.on_open_scene is None or self._spawn_bank is None:
            self.status(f"{sp['name']}: no cutscene editor available here")
            return
        bi, epc, pc = self._spawn_bank, sp["entry_pc"], sp["pc"]
        self.status(f"{sp['name']} (instance {sp['instance']}) → event bank {bi}, line @0x{pc:04x}")
        ui.later(self.frame, lambda: self.on_open_scene(bi, epc, pc))

    # ------------------------------------------------------------------ #
    # view settings
    # ------------------------------------------------------------------ #
    def set_layer(self, key, on):
        self.view.st.layers[key] = on
        if key == "spawns" and on:
            self._load_spawns()
        g = LAYER_GROUPS[key]
        if g == "bg":
            self.view.invalidate("bg")
        else:
            self.view.invalidate(g, "sel")

    def set_ground_display(self, sel):
        self.view.ground_sel = sel
        self.view.invalidate("bg")
        self.view.request_ground()

    def set_scenery(self, on):
        self.view.scenery = bool(on)
        self.view.invalidate("bg")
        self.view.request_ground()

    def set_attr_alpha(self, a):
        self.view.attr_alpha = int(a)
        self.view.invalidate("bg")

    # ---- ground art export / import --------------------------------------- #
    def ground_layer_choice(self):
        """(layer, note) for the export/import picker, or (None, reason)."""
        if not (render.HAS_PIL and self.tex_reader and self.doc):
            return None, "no map or no texture source"
        try:
            layers = mapground.available_layers(self.tex_reader, self.doc.base)
        except Exception as e:
            return None, f"cannot list layers: {e}"
        if not layers:
            return None, "this map ships no ground atlas"
        sel = (self.viewtab.glayer.get() or "").strip()
        if sel[:1].isdigit():
            n = int(sel.split()[0])
            if n in layers:
                return n, ""
            return None, f"this map has no layer {n} (it has {', '.join(map(str, layers))})"
        return layers[0], f"layer {layers[0]}"

    def ground_info(self, layer):
        g = self.doc.grid
        aspect = (g[0], g[1]) if g else None
        lay = mapground.tile_layout(self.tex_reader, self.doc.base, layer, aspect)
        if lay is None:
            raise ValueError(f"layer {layer} has no atlas")
        lay["aspect"] = aspect
        return lay

    def ground_export_to(self, path, layer):
        lay = self.ground_info(layer)
        res = mapground.stitch(self.tex_reader, self.doc.base, layer, aspect=lay["aspect"])
        if not res:
            raise ValueError(f"layer {layer} produced no image")
        res[0].save(path)
        lay["image_size"] = res[0].size
        return lay

    def ground_import_from(self, png_path, outdir, layer, fmt="keep"):
        from PIL import Image
        lay = self.ground_info(layer)
        tiles = mapground.unstitch(self.tex_reader, self.doc.base, Image.open(png_path), layer,
                                   aspect=lay["aspect"], fmt=None if fmt == "keep" else fmt)
        out = pathlib.Path(outdir)
        out.mkdir(parents=True, exist_ok=True)
        for name, blob in tiles:
            (out / name).write_bytes(blob)
        return [n for n, _b in tiles]

    def ground_export(self):
        layer, note = self.ground_layer_choice()
        if layer is None:
            messagebox.showinfo("Ground art", f"Cannot export: {note}.")
            return
        try:
            lay = self.ground_info(layer)
            path = filedialog.asksaveasfilename(title=f"Export ground layer {layer}", defaultextension=".png",
                                                initialfile=f"{lay['set']}_L{layer}.png",
                                                filetypes=[("PNG image", "*.png")])
            if not path:
                return
            lay = self.ground_export_to(path, layer)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Ground art", str(e))
            return
        self.viewtab.gstatus.config(text=f"Exported set {lay['set']} layer {layer}: {len(lay['tiles'])} tiles "
                                         f"({lay['cols']}x{lay['rows']}), image {lay['image_size'][0]}x"
                                         f"{lay['image_size'][1]}. Edit it at exactly this size.")

    def ground_import(self):
        layer, note = self.ground_layer_choice()
        if layer is None:
            messagebox.showinfo("Ground art", f"Cannot import: {note}.")
            return
        png = filedialog.askopenfilename(title="Edited ground PNG", filetypes=[("PNG image", "*.png")])
        if not png:
            return
        outdir = filedialog.askdirectory(title="Write the .texture files into")
        if not outdir:
            return
        try:
            names = self.ground_import_from(png, outdir, layer, self.viewtab.gfmt.get())
        except Exception as e:  # noqa: BLE001 - unstitch names the size it wanted
            messagebox.showerror("Ground art", str(e))
            return
        self.viewtab.gstatus.config(text=f"Wrote {len(names)} .texture files to {outdir}: install them "
                                         f"as loose overrides (rf4mod install) or repack.")

    # ---- dialogs ------------------------------------------------------------ #
    def _keep(self, win):
        if win is not None:
            self._dialogs.append(win)

    def open_resize(self):
        if self.doc is None or self.doc.grid is None:
            messagebox.showinfo("Resize grid", "This map has no ATTR grid.")
            return None
        dlg = dialogs.ResizeDialog(self)
        self._keep(dlg.win)
        return dlg

    def open_chunks(self):
        if self.doc is None:
            return None
        dlg = dialogs.ChunkDialog(self)
        self._keep(dlg.win)
        return dlg

    def open_flag_reference(self):
        self._keep(dialogs.flag_reference(self))

    # ------------------------------------------------------------------ #
    # validation + summaries
    # ------------------------------------------------------------------ #
    def run_validation(self):
        self.flush_edits()
        self.show_tab("Problems")
        return self.problems.run()

    def validate(self):
        """[(severity, file, message)] for the map and both sidecars."""
        d = self.doc
        if d is None:
            return []
        out = []
        try:
            issues = d.map.validate(known_maps=set(data.rooms_by_id()), ground_reader=self.tex_reader,
                                    map_name=d.base or None)
        except Exception as e:  # noqa: BLE001
            issues = [f"ERROR: validation crashed: {e}"]
        for s in issues:
            sev, _, msg = s.partition(": ")
            out.append((sev, "map", msg))
        if d.gen is not None:
            for s in d.gen.validate():
                sev, _, msg = s.partition(": ")
                out.append(("ERROR", "encounters", msg) if sev == "ERROR" else ("WARN", "encounters", s))
        if d.si is not None and d.grid:
            W, H, _ = d.grid
            for i, sp in enumerate(d.si.spots):
                total = sum(e.effective_weight for e in sp.pool.entries)
                if not sp.pool.entries:
                    out.append(("WARN", "search items", f"search spot #{i} has an empty drop pool"))
                elif total > 255:
                    out.append(("WARN", "search items", f"search spot #{i}: drop weights sum to {total}, "
                                                        f"which the game keeps in one byte ({total & 0xFF})"))
                if not (0 <= sp.tile_x < W and 0 <= sp.tile_y < H):
                    out.append(("WARN", "search items", f"search spot #{i} at tile ({sp.tile_x}, "
                                                        f"{sp.tile_y}) is outside the {W}x{H} grid"))
        return out

    def stats_line(self):
        d = self.doc
        W, H = (d.grid[0], d.grid[1]) if d.grid else (0, 0)
        params = sum(1 for o in d.objs if o["category"] == "mapparam")
        unplaced = sum(1 for o in d.objs if o["category"] != "mapparam" and not (o["pos_x"] or o["pos_y"]))
        return (f"{W}×{H} grid · {len(d.objs)} MOBJ records ({params} map parameters, {unplaced} unplaced) · "
                f"{len(d.map.mapj_records())} warps · {len(d.map.find(b'MTXN'))} display layer(s) · "
                f"{len(d.si.spots) if d.si else 0} search spots · "
                f"{sum(len(p) for p in d.gen.patterns) if d.gen else 0} gates")

    def summary_text(self):
        d = self.doc
        m = d.map
        L = [d.name, ""]
        mid = data.map_id(d.base)
        rid = data.load_rooms().get(d.base, (None, None))[1]
        if mid is not None:
            L.append(f"map id     {mid}" + (f"   resource id {rid}" if rid is not None else ""))
            place = map_names.describe_destination(mid)[0]
            if place:
                L.append(f"in game    {place}")
        ts = mapground.texture_set_for(d.base) if d.base else None
        if ts:
            L.append(f"ground     {ts[0]}" + ("  (static backdrop, not tile-aligned)" if ts[1] else
                                              "  (remapped)" if ts[0] != d.base else ""))
        om = mapground.overmodel_for(d.base) if d.base else None
        if om:
            L.append(f"overmodel  {om}")
        L.append("chunks     " + m.summary())
        L.append("")
        L.append(self.stats_line())
        named = Counter(mobj_types.mobj_display_name(o["type_id"] & 0xFFFF) or f"type {o['type_id'] & 0xFFFF}"
                        for o in d.objs)
        if named:
            L += ["", "Placed types:"] + [f"  {c:>3} × {n}" for n, c in named.most_common()]
        if d.gen is not None:
            roster = ", ".join(f"{data.actor_name(i) or i}" for i, _n in d.gen.roster().most_common())
            L += ["", f"Encounters ({d.gen_path.name if d.gen_path else 'Gen'}):", "  " + (roster or "(none)")]
        if d.si is not None:
            L += ["", f"Search spots ({d.si_path.name if d.si_path else 'new'}): {len(d.si.spots)}"]
            for i, sp in enumerate(d.si.spots[:12]):
                drops = ", ".join(f"{data.item_name(e.effective_item_id) or e.effective_item_id}"
                                  f"({e.effective_weight})" for e in sp.pool.entries[:4])
                L.append(f"  [{i}] ({sp.tile_x},{sp.tile_y}) {drops}"
                         + (f", +{len(sp.pool.entries) - 4}" if len(sp.pool.entries) > 4 else ""))
        return "\n".join(L)

    # ------------------------------------------------------------------ #
    # saving + export
    # ------------------------------------------------------------------ #
    def _ask_path(self, title, initial, ext, kind):
        return filedialog.asksaveasfilename(title=title, defaultextension=ext, initialfile=initial,
                                            filetypes=[(kind, "*" + ext), ("All files", "*.*")])

    def save_map(self):
        """Save the .rf4m through a Save dialog; asks first when the loader would choke on
        it. True when written."""
        self.flush_edits()
        d = self.doc
        if d is None:
            return False
        fatal = [m for s, where, m in self.validate() if s == "ERROR" and where == "map"]
        if fatal and not messagebox.askyesno(
                "Map has fatal problems", "The game's loader would choke on this map:\n\n"
                + "\n".join("• " + x for x in fatal[:6]) + ("\n…" if len(fatal) > 6 else "")
                + "\n\nSave anyway?"):
            return False
        p = self._ask_path("Save map", f"{d.base or 'map'}.rf4m", ".rf4m", "RF4 map")
        if not p:
            return False
        try:
            d.map.save(p)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save failed", str(e))
            return False
        d.mark_saved("map")
        self.status(f"Saved {p}")
        self._update_chrome()
        return True

    def save_si(self):
        """Save the search spots to a loose SI_*.bin chosen in a dialog (never silently over
        the game's extracted file). True when written."""
        self.flush_edits()
        d = self.doc
        if d is None or d.si is None:
            messagebox.showinfo("Save search items", "This map has no search spots.")
            return False
        p = self._ask_path("Save search items", d.si_path.name if d.si_path else
                           (data.si_name_for_map(d.base) or "SI_MAP.bin"), ".bin", "SI table")
        if not p:
            return False
        try:
            d.si.save(pathlib.Path(p))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save failed", str(e))
            return False
        d.mark_saved("si")
        self.status(f"Saved {p}")
        self._update_chrome()
        return True

    def save_gen(self):
        self.flush_edits()
        d = self.doc
        if d is None or d.gen is None:
            messagebox.showinfo("Save encounters", "This map has no encounter table.")
            return False
        fatal = [m for s, where, m in self.validate() if s == "ERROR" and where == "encounters"]
        if fatal and not messagebox.askyesno(
                "Encounters have fatal problems", "The game would crash or hang on this table:\n\n"
                + "\n".join("• " + x for x in fatal[:6]) + ("\n…" if len(fatal) > 6 else "")
                + "\n\nSave anyway?"):
            return False
        p = self._ask_path("Save encounters", d.gen_path.name if d.gen_path else "Gen.bin", ".bin", "Gen table")
        if not p:
            return False
        try:
            d.gen.save(pathlib.Path(p))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save failed", str(e))
            return False
        d.mark_saved("gen")
        self.status(f"Saved {p}")
        self._update_chrome()
        return True

    def save_all(self):
        """Save every changed file, each through its own dialog. False if one was cancelled."""
        self.flush_edits()
        parts = self.dirty_parts()
        if not parts:
            self.status("Nothing to save: no unsaved changes")
            return True
        for label, fn in (("map", self.save_map), ("search items", self.save_si), ("encounters", self.save_gen)):
            if label in parts and not fn():
                return False
        return True

    def render_to_image(self, scale=None):
        """WYSIWYG PIL image of the map view at the current zoom (or `scale` px per tile) with
        exactly the enabled layers, minus the selection. RGBA; transparent where no base
        layer is drawn, so it composites over other renders."""
        d = self.doc
        if d is None or d.grid is None or not render.HAS_PIL:
            return None
        from PIL import Image
        st = copy.copy(self.view.st)
        st.cp = scale or self.view.cp
        st.sel = None
        W, H, _ = d.grid
        bg = render.Background().image(d.grid, self.view.colors, st.cp, self.view.ground_image(block=True),
                                       attr_on=st.layers.get("attr", True), alpha=self.view.attr_alpha,
                                       edges_on=st.layers.get("edges", True), attr_version=d.attr_version)
        img = bg.copy() if bg is not None else Image.new("RGBA", (W * st.cp, H * st.cp), (0, 0, 0, 0))
        prims = [p for g in render.GROUPS if g != "sel" for p in render.overlay(g, st)]
        return render.draw_prims(img, prims, st.sprites)

    def export_png(self):
        img = self.render_to_image()
        if img is None:
            messagebox.showinfo("Export", "Pillow and a map with an ATTR grid are needed.")
            return
        p = self._ask_path("Export map view", f"{self.map_base or 'map'}.png", ".png", "PNG image")
        if p:
            img.save(p)
            self.status(f"Exported {p} ({img.width}x{img.height})")
