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

from guiutil import shortcut_scope
from guiutil import err_text

from rf4s_modkit import (areagroup, flagstate, map_names, mapground, mobj_params, mobj_types, rf4m,
                         search_items)

from . import data, dialogs, render, tools, ui
from . import view as view_mod
from .document import MapDocument
from .inspector import Inspector
from .palette import PaletteTab
from .tabs import (FLAGS_LIVE, FLAGS_NONE, LAYER_GROUPS, EncountersTab, MapTab, MinimapPanel, ObjectsTab,
                   ProblemsTab, ViewTab)
from .view import MapView

TABS = ("View", "Inspect", "Objects", "Palette", "Properties", "Gates", "Problems")
_MOVE_ASPECT = {"mobj": "mobj", "warp": "mapj", "si": "si", "gpos": "gen", "mpos": "gen"}
# The clipboard is the system clipboard: one tagged JSON line, so a copied object survives
# switching maps (the host may rebuild this panel) and pastes into another toolkit window.
CLIP_TAG = "RF4S map object "
MULTI_HINT = ("%d selected -- drag one to move them all, arrows nudge them, Delete deletes them; "
              "Shift+click adds / removes one")
_CLIP_KINDS = ("mobj", "warp", "si", "gpos", "mpos")
_KIND_NAME = {"mobj": "entity", "warp": "warp", "si": "search spot", "gpos": "gate position",
              "mpos": "monster spawn point"}


def reload_hint(new_file):
    """What to do in the game to see a saved map. Overwriting a file the game already knows
    takes effect the next time the map loads; a NEW loose file (a Bundle/00_mods copy of a
    file the game only had packed) is only found once the game re-indexes its loose files,
    i.e. after a restart."""
    if new_file:
        return "restart the game to see it (a new file: the game looks for new files when it starts)"
    return "leave the map and enter it again to see it"


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
        self.selection = []         # every selected key (sel, the one the forms show, last)
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
        self.file_path = None       # set by the host for a map opened from disk: Save goes there
        self._build()
        self.tex_reader = tex_reader
        self.set_tool("select", focus=False)    # the host keeps its focus (e.g. the file list)
        data.on_script_changed(self._script_changed)
        if mapobj is not None:
            self.set_map(mapobj, name)

    def _script_changed(self):
        """The event scripts changed (cutscene editor edit / undo / save): re-read this map's
        script spawns. False once the panel is gone, which unregisters it."""
        try:
            if not self.frame.winfo_exists():
                return False
        except tk.TclError:
            return False
        self._spawns_for = None
        if self.doc is not None and self.view.st.layers.get("spawns"):
            self._load_spawns(quiet=True)
        return True

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    def _build(self):
        from guiutil import Paned
        self._flag_paths = {}                   # flag-source name -> save file
        self._pointer = None                    # last pointer position (sub-units): Ctrl+V target
        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_toolbar()
        # No live relayout while the sash is dragged (the sidebar is ~150 native
        # widgets); the sidebar keeps its width when the window resizes.
        self._build_limits_bar()
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
        self.palette = PaletteTab(self.nb, self)
        self.maptab = MapTab(self.nb, self)
        # the minimap: docked under the tabs, whatever tab is open
        self.minimap_panel = MinimapPanel(side, self)
        self.minimap_panel.pack(side="bottom", fill="x", before=self.nb)
        self.encounters = EncountersTab(self.nb, self)
        self.viewtab = ViewTab(self.nb, self)
        self.problems = ProblemsTab(self.nb, self)
        for w, t in zip((self.viewtab, self.inspector, self.objects, self.palette, self.maptab,
                         self.encounters, self.problems), TABS):
            self.nb.add(w, text=t)
        self.show_tab("View")                   # the editor opens on the View tab
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._tab_changed())
        self.view.on_zoom = self._update_chrome
        self.view.st.layers = self.viewtab.layers()
        self.view.attr_alpha = self.viewtab.alpha.get()
        self.view.ground_dim = self.viewtab.dim.get()
        self.view.scenery = self.viewtab.scenery.get()
        self.view.runtime_tips = self.viewtab.rt_tips.get()
        self._bind_canvas()
        self._bind_shortcuts()

    def _build_toolbar(self):
        bar = ttk.Frame(self.frame, padding=(2, 2))
        bar.pack(fill="x")
        mb = ttk.Menubutton(bar, text="Save")
        menu = tk.Menu(mb, tearoff=False)
        menu.add_command(label="Save (overwrite the game's files)", accelerator="Ctrl+S",
                         command=self.save_to_game)
        menu.add_separator()
        menu.add_command(label="Save map (.rf4m) as…", command=self.save_map)
        menu.add_command(label="Save search items (SI_*.bin) as…", command=self.save_si)
        menu.add_command(label="Save monster gates (Gen*.bin) as…", command=self.save_gen)
        menu.add_separator()
        menu.add_command(label="Copy changes to the other seasons…", command=self.copy_to_seasons)
        menu.add_separator()
        menu.add_command(label="Export map view as PNG…", command=self.export_png)
        mb["menu"] = menu
        mb.pack(side="left")
        ui.Tip(mb, "Save (Ctrl+S) writes this map's changed files -- the map, its search spots, "
                   "its monster gates -- straight over the ones the game loads from your game folder, "
                   "without asking (with backups on -- Options → Advanced in the main window -- "
                   "the originals are copied to ModdingBackup first). 'Save … as…' writes a copy "
                   "elsewhere instead.\n"
                   "Farm, field and Selphia maps come in four seasons (…_SUMMER, _AUTUMN, "
                   "_WINTER): the game loads the one for the current season. 'Copy changes to "
                   "the other seasons…' carries this map's object / warp / ATTR changes over.")
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
        ui.Tip(fit, lambda: "Fit the map in the window (0). " + (
            "The wheel scrolls up / down, Ctrl+wheel zooms at the pointer"
            if view_mod.wheel_mode() == "scroll" else
            "The wheel zooms at the pointer, Ctrl+wheel scrolls up / down")
            + ", Shift+wheel sideways, middle-drag pans (Options… ▸ Mouse wheel zooms the map).")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="Validate", command=self.run_validation).pack(side="left")
        self.dirty_lbl = ttk.Label(bar, foreground="#c60", font=ui.HINT_FONT)
        self.dirty_lbl.pack(side="right", padx=6)

    # the game's fixed per-map capacities, as "used / cap" along the bottom of the editor
    LIMIT_OK, LIMIT_NEAR, LIMIT_FULL, LIMIT_OVER = "#8a8a96", "#c89a00", "#d06a00", "#e03030"

    def _build_limits_bar(self):
        bar = ttk.Frame(self.frame, padding=(4, 1))
        bar.pack(side="bottom", fill="x")
        lab = ttk.Label(bar, text="Limits:", font=ui.HINT_FONT)
        lab.pack(side="left")
        ui.Tip(lab, "How much of the game's fixed per-map room this map uses. Grey = fine, "
                    "yellow = nearly full, orange = full (nothing more can be added), red = "
                    "past the limit (Validate lists what goes wrong).")
        self.limit_lbls = {}
        self._limit_tips = {}
        for key in ("mobj", "mapj", "forage", "doors", "si"):
            w = ttk.Label(bar, font=ui.HINT_FONT)
            w.pack(side="left", padx=(8, 0))
            ui.Tip(w, lambda k=key: self._limit_tips.get(k, ""))
            self.limit_lbls[key] = w

    def limit_usage(self):
        """[(key, label, used, cap, over_is_error, tip)] for the open map and its SI file
        (search spots only when the game rolls search items here)."""
        d = self.doc
        if d is None:
            return []
        out = d.map.limit_usage()
        if not d.si_block_reason():
            out.append(("si", "Search spots", len(d.si.spots) if d.si else 0,
                        search_items.MAX_SPOTS, True,
                        "Search spots in this map's SI file: the daily roll uses one random "
                        "stream per spot and stream 255 never finishes, so 253 is the most "
                        "that is safe."))
        return out

    def _update_limits(self):
        shown = {}
        for key, label, used, cap, hard, tip in self.limit_usage():
            if used > cap:
                col, state = self.LIMIT_OVER, "past the limit" if hard else "over"
            elif used == cap:
                col, state = self.LIMIT_FULL, "full"
            elif used >= cap * 0.9:
                col, state = self.LIMIT_NEAR, "nearly full"
            else:
                col, state = self.LIMIT_OK, None
            shown[key] = (f"{label} {used}/{cap}", col)
            self._limit_tips[key] = (f"{label}: {used} of {cap}" + (f" -- {state}" if state else "")
                                     + "\n" + tip)
        for key, w in self.limit_lbls.items():
            text, col = shown.get(key, ("", self.LIMIT_OK))
            if key == "si" and key not in shown and self.doc is not None:
                text = "Search spots -"
                self._limit_tips[key] = self.doc.si_block_reason() or ""
            w.config(text=text, foreground=col)

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
            for k in {t.key.lower(), t.key.upper()}:             # (Caps Lock on too)
                c.bind(f"<KeyPress-{k}>", lambda _e, n=name: self.set_tool(n))
        for k in ("Delete", "BackSpace"):
            c.bind(f"<{k}>", lambda _e: self.delete_selection())
        for k in ("a", "A"):
            c.bind(f"<Control-{k}>", lambda _e: self.select_all() or "break")
        c.bind("<Escape>", lambda _e: self.escape())
        # copy / cut / paste objects (canvas only: text fields keep their own Ctrl+C/V)
        for k in ("c", "C"):
            c.bind(f"<Control-{k}>", lambda _e: self.copy_object(self.sel) or "break")
        for k in ("x", "X"):
            c.bind(f"<Control-{k}>", lambda _e: self.copy_object(self.sel, cut=True) or "break")
        for k in ("v", "V"):
            c.bind(f"<Control-{k}>", lambda _e: self.paste_object(self._pointer) or "break")
        c.bind("<Leave>", lambda _e: setattr(self, "_pointer", None), add="+")
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
        # Ctrl shortcuts work wherever the focus is inside the editor, including panel widgets
        # built later (guiutil.shortcut_scope: both letter cases for Caps Lock, Shift tells
        # redo from undo, widgets tagged when they take the focus)
        self._tag = f"MapEd{id(self)}"
        self.retag = shortcut_scope(self.frame, self._tag, [
            ("z", lambda e: self.redo() if e.state & 0x0001 else self.undo()),
            ("y", lambda e: self.redo()),
            ("s", lambda e: self.save_to_game())],
            home=lambda: getattr(getattr(self, "view", None), "canvas", None))  # the map

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
        self.palette.set_reader(reader)

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
        self.selection = []
        self.view.st.multi = ()
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
        fs = self.view.st.flags
        if fs is not None:
            self.viewtab.flagstatus.config(
                text=f"{fs.source}: story step {fs.story()}; "
                     f"{self._count_flag_hidden(fs)} object(s) on this map hidden")
        if self.view.st.layers.get("spawns"):
            self._load_spawns()
        self.inspector.show_selection(None)
        self.inspector.refresh(frozenset({"attr"}))
        self.objects.rebuild()
        self.palette.refresh()
        self.maptab.refresh()
        self.minimap_panel.refresh()
        self.encounters.refresh()
        self.problems.tree.delete(*self.problems.tree.get_children())
        self.problems.summary.config(text="")
        self._update_chrome()
        self.view.request_ground()
        ui.later(self.frame, self.view_open)

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
        return self.save_to_game() if ans else True

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
            messagebox.showerror("Not applied", f"{label}:\n{err_text(e)}")
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
        if "gen" in aspects:                    # gate markers, and the gates drawn as sprites
            groups |= {"gate", "sel", "under"}
        if aspects & {"attr", "chunks"}:
            groups |= set(render.GROUPS)
        if groups:
            v.invalidate(*groups)
        self._validate_selection()
        live = self.doc.in_edit                       # mid-drag: keep it cheap
        self.inspector.refresh(aspects)
        if not live:
            self._schedule("objects", "maptab")
            if aspects & {"mobj", "chunks"}:
                self._schedule("palette")
            if "gen" in aspects:                # (the Map tab's MGRP checks count the gates)
                self._schedule("encounters", "maptab")
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
        if "palette" in names:
            self.palette.refresh()
        if "maptab" in names:
            self.maptab.refresh()
            self.minimap_panel.refresh()
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
        if not self._key_valid(s):
            self.select(None)
        elif len(self.selection) > 1:
            keep = [k for k in self.selection if self._key_valid(k)]
            if keep != self.selection:
                self.select(s, keep=keep)

    def _key_valid(self, s):
        d = self.doc
        kind, k = s
        return ((kind == "mobj" and k < len(d.objs)) or
                (kind == "warp" and k < len(d.map.mapj_records())) or
                (kind == "si" and d.si is not None and k < len(d.si.spots)) or
                (kind in ("gpos", "mpos") and any((pk, off) == s for pk, off, *_r in d.gate_points())))

    def _update_chrome(self):
        parts = self.dirty_parts()
        self.dirty_lbl.config(text=("● unsaved: " + ", ".join(parts)) if parts else "")
        d = self.doc
        self.undo_btn.state(["!disabled"] if d and d.undo_stack else ["disabled"])
        self.redo_btn.state(["!disabled"] if d and d.redo_stack else ["disabled"])
        self.zoom_lbl.config(text=f"{self.view.cp} px")
        self._update_limits()

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

    def set_tool(self, name, focus=True):
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
        if focus:
            self.view.canvas.focus_set()      # so the tool keys work right away
        self.inspector.show_tool(t)
        if name != "select" and self.nb.select() and self.nb.tab(self.nb.select(), "text") in ("Properties", "View"):
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
        # Tk runs a <Double-Button-1> binding INSTEAD of the <ButtonPress-1> one, so for every
        # tool but Select a quick second click must still be a click (placing two objects, or
        # painting, in quick succession used to lose every second one)
        if self.doc is None:
            return None
        if self.tool.name == "select":
            return self.tool.double(e)
        return self._press(e)

    def reveal_layer_for(self, type_id):
        """Switch on the View layer that shows objects of `type_id` when it is off (a newly
        placed object must not be invisible). The layer's name when switched on, else None."""
        kind = mobj_types.mobj_kind(type_id & 0xFFFF)
        if kind == "mapparam":                      # never drawn: nothing to switch on
            return None
        key = "trigger" if kind in ("forage", "trigger") else kind
        var = self.viewtab.vars.get(key)
        if var is None or var.get():
            return None
        var.set(True)
        self.set_layer(key, True)
        return {"trigger": "forage / triggers", "actor": "actors", "object": "objects",
                "decoration": "decorations"}.get(key, key)

    def _right(self, e):
        if self.doc is not None and self.doc.grid:
            self.tool.right_press(e)

    def _motion(self, e):
        if self.doc is not None and self.doc.grid:
            self._pointer = self.view.subunit_at(e)     # where Ctrl+V pastes
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
        if key[0] in _CLIP_KINDS:
            m.add_command(label="Copy  (Ctrl+C)", command=lambda: self.copy_object(key))
            m.add_command(label="Cut  (Ctrl+X)", command=lambda: self.copy_object(key, cut=True))
        if key[0] in ("gpos", "mpos"):
            users = next((u for pk, off, _x, _y, u in self.doc.gate_points() if (pk, off) == key), [])
            if users:
                m.add_command(label="Show its gate", command=lambda: self.show_gate(users[0]))
        m.add_separator()
        if len(self.selection) > 1 and tuple(key) in self.selection:
            m.add_command(label=f"Delete {len(self.selection)} selected",
                          command=self.delete_selection)
        else:
            m.add_command(label="Delete", command=lambda: self.delete(key))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def context_menu_empty(self, e):
        """Right-click on empty map: paste what the clipboard holds, right there."""
        clip = self.clipboard_object()
        if clip is None or self.doc is None:
            return
        m = tk.Menu(self.frame, tearoff=False)
        m.add_command(label=f"Paste {_KIND_NAME[clip['kind']]} here  (Ctrl+V)",
                      command=lambda at=self.view.subunit_at(e): self.paste_object(at))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def view_fit(self):
        self.view.fit()
        self._update_chrome()

    def view_open(self):
        """A map just loaded: the opening zoom (view.OPEN_ZOOM), centred -- or, reached
        through a warp, the zoom the warp was followed at, centred on its arrival point."""
        warp, self._warp_view = self.__dict__.get("_warp_view"), None
        self.view.open_view(*(warp or ()))
        self._update_chrome()

    # ------------------------------------------------------------------ #
    # selection
    # ------------------------------------------------------------------ #
    def select(self, key, center=False, keep=()):
        """Select `key` (None: nothing). `keep`: other keys that stay selected with it (a
        multi-selection; `key` is the one the Inspect tab shows)."""
        if key is not None and key[0] in ("gpos", "mpos"):
            users = next((u for pk, off, _x, _y, u in self.doc.gate_points() if (pk, off) == tuple(key)), [])
            if users and self.gate_index not in users:
                self.set_active_gate(users[0])
            gl = getattr(self.encounters, "gates", None)       # the Gates list shows it picked
            iid = f"{self.gate_index[0]}:{self.gate_index[1]}" if self.gate_index is not None else None
            if gl is not None and iid and gl.exists(iid) and gl.selection() != (iid,):
                gl.selection_set(iid)
                gl.see(iid)
        self.sel = tuple(key) if key is not None else None
        rest = [tuple(k) for k in keep if k is not None and tuple(k) != self.sel]
        self.selection = rest + ([self.sel] if self.sel is not None else [])
        self.view.st.sel = self.sel
        self.view.st.multi = tuple(self.selection) if len(self.selection) > 1 else ()
        self.view.invalidate("sel")
        if len(self.selection) > 1:
            self.status(MULTI_HINT % len(self.selection))
        if key is None:                         # deselecting on the map also lets go of the gate
            gl = getattr(self.encounters, "gates", None)       # picked in the Gates list
            if gl is not None and gl.selection():
                gl.selection_set(())
        self._update_gate_focus()
        if self.sel and self.sel[0] == "gpos":  # the Gates tab's positions list follows
            self.encounters._show_gpos(self.active_gate)
        elif self.sel and self.sel[0] == "mpos":  # ... and its spawn-point list
            ml = getattr(self.encounters, "mpts", None)
            iid = str(self.sel[1])
            if ml is not None and ml.exists(iid) and ml.selection() != (iid,):
                ml.selection_set(iid)
                ml.see(iid)
        self.inspector.show_selection(self.sel)
        self.objects.reveal(self.sel)
        if self.sel is not None:
            cur = self.nb.tab(self.nb.select(), "text") if self.nb.select() else ""
            if cur in ("Properties", "View"):
                self.show_tab("Inspect")
            if center:
                self.center_on(self.sel)

    def add_to_selection(self, key):
        """Shift+click on an unselected object: it joins the selection (and is shown)."""
        if key is not None:
            self.select(key, keep=self.selection)

    def remove_from_selection(self, key):
        """Shift+click on a selected object: it leaves the selection."""
        rest = [k for k in self.selection if k != tuple(key)]
        self.select(rest[-1] if rest else None, keep=rest[:-1])

    def select_many(self, keys, add=False):
        """Select every key in `keys` (a selection box); add=True keeps what was selected."""
        keys = [tuple(k) for k in keys]
        base = [k for k in self.selection if k not in keys] if add else []
        allk = base + keys
        if not allk:
            self.select(None)
            return
        self.select(allk[-1], keep=allk[:-1])

    def select_all(self):
        """Ctrl+A: every object shown on the map."""
        if self.doc is None or not self.doc.grid:
            return
        W, H, _ = self.doc.grid
        self.select_many(self.keys_in_rect(0, 0, W * 8, H * 8))

    def keys_in_rect(self, x0, y0, x1, y1):
        """Keys of the shown objects whose position (a warp: its zone's centre) lies in the
        sub-unit rectangle, in map order."""
        d, L = self.doc, self.view.st.layers
        if d is None:
            return []
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))

        def inside(x, y):
            return x0 <= x <= x1 and y0 <= y <= y1
        out = []
        for i, o in enumerate(d.objs):
            if render.entity_visible(o, L) and inside(o["pos_x"], o["pos_y"]):
                out.append(("mobj", i))
        if L.get("mapj"):
            for j, r in enumerate(d.map.mapj_records()):
                if inside(r[1] + r[3] // 2, r[2] + r[4] // 2):
                    out.append(("warp", j))
        if L.get("si") and d.si is not None:
            for k, sp in enumerate(d.si.spots):
                if inside(sp.x, sp.y):
                    out.append(("si", k))
        if L.get("gates") and d.gen is not None:
            for pk, off, x, y, _u in d.gate_points():
                if inside(x, y):
                    out.append((pk, off))
        return out

    def show_tab(self, title):
        # by title, not position: a host can add tabs (the asset explorer inserts Events)
        tab = next((t for t in self.nb.tabs() if self.nb.tab(t, "text") == title), None)
        if tab is not None:
            self.nb.select(tab)

    def _tab_changed(self):
        self._update_gate_focus()

    def _update_gate_focus(self):
        """The active gate's points are outlined white only while that gate is being worked
        on -- one of its points selected, or the Gates tab open -- and the outlines go as
        soon as the selection or the tab moves on (they used to stay)."""
        sel = self.sel
        on = bool(sel and sel[0] in ("gpos", "mpos"))
        if not on and self.nb.select() and self.nb.tab(self.nb.select(), "text") == "Gates":
            gl = getattr(self.encounters, "gates", None)       # a gate picked in the Gates list
            on = bool(gl is not None and gl.selection())
        if getattr(self.view.st, "gate_focus", None) != on:
            self.view.st.gate_focus = on
            self.view.invalidate("gate")

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
        self.show_tab("Gates")

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
            if (r[0] & 0xFFFF) == 52:           # the knock-back target moves with the vent
                r[8], r[9] = r[8] + pos[0] - r[14], r[9] + pos[1] - r[15]
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
        """Arrow keys: move the selection (every selected object) by (dx, dy) sub-units.
        Entities may go off the grid (shipped maps place trees and seal-door controllers
        there on purpose); search spots and gate points may not go negative."""
        keys = self.selection or ([self.sel] if self.sel else [])
        if not keys or self.doc is None:
            return
        moves = []
        for s in keys:
            p = self.position_of(s)
            if p is None:
                return
            new = (p[0] + dx, p[1] + dy) + tuple(p[2:])
            if min(new[0], new[1]) < 0 and s[0] not in ("warp", "mobj"):
                return                          # one would leave the map: none moves
            moves.append((s, new))
        if len(moves) == 1:
            self.set_position_edit(*moves[0])
            return
        self.move_many(moves)

    def move_many(self, moves):
        """[(key, position)] as one undo step."""
        def do():
            for s, p in moves:
                self.set_position(s, p)
        self.apply(f"Move {len(moves)} objects", {self.aspect_of(s) for s, _p in moves}, do)

    def center_on(self, key):
        if key is None or self.doc is None:
            return
        p = self.position_of(key)
        if p is None:
            return
        x, y = p[0], p[1]
        if key[0] == "warp":
            x, y = x + p[2] // 2, y + p[3] // 2
        if key[0] == "mobj" and mobj_types.is_positionless(self.doc.objs[key[1]]["type_id"]):
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

    def delete_selection(self):
        """Delete: every selected object, as one undo step."""
        keys = list(self.selection) or ([self.sel] if self.sel else [])
        if len(keys) < 2:
            self.delete(keys[0] if keys else None)
            return
        d = self.doc
        pts = []                                # gate / monster points: (entry, index) first
        for kind, k in keys:
            if kind in ("gpos", "mpos"):
                e, i = d.locate_point(kind, k)
                if e is not None:
                    pts.append((kind, e, i))

        def do():
            # highest index first, so the ones still to go keep their numbers
            for kind in ("mobj", "warp", "si"):
                for k in sorted((k for kk, k in keys if kk == kind), reverse=True):
                    if kind == "mobj":
                        d.map.delete_mobj_record(k)
                    elif kind == "warp":
                        d.map.delete_mapj_record(k)
                    else:
                        del d.si.spots[k]
            for kind, e, i in sorted(pts, key=lambda t: -t[2]):
                (d.gen.remove_gate_position if kind == "gpos" else d.gen.remove_monster_position)(e, i)
        label = f"Delete {len(keys)} objects"
        self.select(None)
        if self.apply(label, {self.aspect_of(k) for k in keys}, do):
            self.status(label)

    def room_for(self, kind):
        """None when one more `kind` fits this map, else why not. Each new entity / warp is
        one chunk, and the engine holds only 40 MOBJ / 10 MAPJ chunk pointers per map
        (rf4m.ENGINE_MAX_CHUNKS; more overwrite the next array)."""
        tag = {"mobj": b"MOBJ", "warp": b"MAPJ"}.get(kind)
        if tag is None or self.doc is None:
            return None
        cap = rf4m.ENGINE_MAX_CHUNKS[tag]
        n = sum(1 for ch in self.doc.map.chunks if ch.tag == tag)
        if n >= cap:
            return (f"this map already has {n} {tag.decode()} chunks -- the game holds {cap}; "
                    f"delete one first")
        return None

    def copied_record(self, r, dx=0, dy=0, src=None):
        """(record, notes) for an entity copied onto this map `dx`/`dy` sub-units from where
        it was (src = the map it came from, None = this one): a chest / crate / mushroom pickup
        gets an unused one-shot flag (data.fresh_flag), a knock-back vent's target moves with
        it, a warp point from another map keeps its destination (f10 is relative to the map
        id)."""
        d = self.doc
        r = list(r)
        tid = r[0] & 0xFFFF
        notes = []
        if not mobj_types.is_positionless(tid):
            r[14], r[15] = r[14] + dx, r[15] + dy
        if tid == 52:
            r[8], r[9] = r[8] + dx, r[9] + dy
        if tid == 42 and src and data.map_base(src) != d.base:
            a, b = data.map_id(src), self.this_map_id()
            if a is not None and b is not None:
                dest = a + r[10]
                r[10] = dest - b
                notes.append(f"the warp point still leads to map {dest} (f10 = {r[10]:+d} from here)")
        if mobj_params.one_shot_flag(r) is not None:
            new, why = data.fresh_flag(d.map.mobj_records(), d.map.mapj_records(), r)
            if new is not None:
                r[13] = new
            notes.append(f"the {mobj_params.ONE_SHOT_FLAG_TYPES[tid]} {why}")
        return r, notes

    def shared_flag_note(self, i):
        """' -- WARNING: it shares its one-shot flag N with #j ...' for entity `i`, else ''."""
        recs = self.doc.map.mobj_records()
        fl = mobj_params.one_shot_flag(recs[i])
        if fl is None:
            return ""
        twins = [j for j, r in enumerate(recs) if j != i and mobj_params.one_shot_flag(r) == fl]
        return (f" -- WARNING: it shares its one-shot flag {fl} with "
                + ", ".join(f"#{j}" for j in twins) + " (whichever is used first sets it for "
                "all; see Problems)") if twins else ""

    def duplicate(self, key):
        if key is None or self.doc is None:
            return
        d = self.doc
        kind, k = key
        why = self.room_for(kind)
        if why:
            self.status(f"Can't duplicate: {why}")
            return
        out = {}
        notes = []
        rec = None
        if kind == "mobj":
            rec, notes = self.copied_record(d.map.mobj_records()[k], 8, 8)

        def do():
            if kind == "mobj":
                out["k"] = ("mobj", d.map.add_mobj_record(rec))
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
        label = f"Duplicate {_KIND_NAME[kind]} #{k}"
        if kind in ("mobj", "warp", "si") and self.apply(label, self.aspect_of(key), do):
            self.select(out.get("k"))
            if kind == "mobj":
                self.status(label + "".join(f"; {n}" for n in notes)
                            + self.shared_flag_note(out["k"][1]))

    # ---- clipboard (across maps) ---------------------------------------- #
    def copy_object(self, key, cut=False):
        """Put the entity / warp / search spot `key` on the clipboard (and delete it: cut)."""
        if key is None or self.doc is None:
            return
        kind, k = key
        if kind not in _CLIP_KINDS:
            return
        d = self.doc
        clip = {"kind": kind, "from": d.base}
        if kind in ("gpos", "mpos"):
            e, i = d.locate_point(kind, k)
            if e is None:
                return
            pt = (e.gate_pos if kind == "gpos" else e.mon_pos).points[i]
            clip["x"], clip["y"] = pt[0], pt[1]
            if kind == "mpos":
                clip["extra"] = pt[2]
        elif kind == "mobj":
            clip["record"] = [int(v) for v in d.map.mobj_records()[k]]
        elif kind == "warp":
            clip["record"] = [int(v) for v in d.map.mapj_records()[k]]
        else:
            sp = d.si.spots[k]
            clip["x"], clip["y"] = sp.x, sp.y
            clip["drops"] = [[e.effective_item_id, e.effective_weight] for e in sp.pool.entries]
        import json
        self.frame.clipboard_clear()
        self.frame.clipboard_append(CLIP_TAG + json.dumps(clip))
        what = _KIND_NAME[kind] + (f" #{k}" if kind in ("mobj", "warp", "si") else "")
        if cut:
            self.delete(key)
            self.status(f"Cut {what} -- Ctrl+V pastes it on any map")
        else:
            self.status(f"Copied {what} -- Ctrl+V pastes it on any map (at the pointer)")

    def clipboard_object(self):
        """The map object on the clipboard, or None."""
        import json
        try:
            text = self.frame.clipboard_get()
        except tk.TclError:
            return None
        if not text.startswith(CLIP_TAG):
            return None
        try:
            clip = json.loads(text[len(CLIP_TAG):])
        except ValueError:
            return None
        return clip if isinstance(clip, dict) and clip.get("kind") in _CLIP_KINDS else None

    def paste_object(self, at=None):
        """Add the clipboard's object to this map, centred on `at` (sub-units: the pointer)
        or, without one, where it was on its own map (clamped into this one). Selects it."""
        if self.doc is None or not self.doc.grid:
            return
        clip = self.clipboard_object()
        if clip is None:
            self.status("The clipboard holds no map object (select one and press Ctrl+C)")
            return
        kind = clip["kind"]
        why = self.room_for(kind)
        if why:
            self.status(f"Can't paste: {why}")
            return
        d = self.doc
        gate = None
        if kind in ("gpos", "mpos"):
            # a point belongs to a gate: the one chosen in the Gates tab, or the only one
            if d.gen is None:
                self.status("Can't paste: this map has no encounter table (Gen file)")
                return
            gate = self.active_gate
            if gate is None:
                gates = [e for _pi, _ei, e in d.gen.all_entries()]
                gate = gates[0] if len(gates) == 1 else None
            if gate is None:
                self.status(f"Choose the gate to paste the {_KIND_NAME[kind]} into "
                            f"(Gates tab), then paste again")
                return
        W, H, _ = d.grid
        out = {}
        notes = []

        def clamp(x, y, w=0, h=0):
            return (max(0, min(W * 8 - max(1, w), x)), max(0, min(H * 8 - max(1, h), y)))

        def place(x, y, w=0, h=0, free=False):
            """Top-left for an object of size w x h (sub-units): centred on `at`, keeping
            the object's own sub-tile offset; else its old spot -- clamped into this map,
            unless `free` (an entity that sat off the grid stays where it was)."""
            if at is not None:
                x = (at[0] - w // 2) // 8 * 8 + (x & 7)
                y = (at[1] - h // 2) // 8 * 8 + (y & 7)
            elif free and not (0 <= x >> 3 < W and 0 <= y >> 3 < H):
                return x, y
            return clamp(x, y, w, h)
        rec = None
        if kind == "mobj":
            r0 = clip["record"]
            nx, ny = r0[14], r0[15]
            if not mobj_types.is_positionless(r0[0]):
                nx, ny = place(nx, ny, free=True)
            rec, notes = self.copied_record(r0, nx - r0[14], ny - r0[15], clip.get("from"))

        def do():
            if kind in ("gpos", "mpos"):
                x, y = place(clip["x"], clip["y"])
                if kind == "gpos":
                    d.gen.add_gate_position(gate, x, y)
                    pts = d.gen.gate_positions_off(gate)
                else:
                    d.gen.add_monster_position(gate, x, y, clip.get("extra", 0))
                    pts = d.gen.monster_positions_off(gate)
                out["k"] = (kind, pts[-1][0])
            elif kind == "mobj":
                out["k"] = ("mobj", d.map.add_mobj_record(rec))
            elif kind == "warp":
                r = list(clip["record"])
                r[1], r[2] = place(r[1], r[2], r[3], r[4])
                out["k"] = ("warp", d.map.add_mapj_record(r))
            else:
                x, y = place(clip["x"], clip["y"])
                pool = search_items.DropPool(entries=[search_items.DropEntry(item_id=i, weight=w)
                                                      for i, w in clip["drops"]])
                si = d.ensure_si()
                si.spots.append(search_items.SearchSpot(x=x, y=y, pool=pool))
                out["k"] = ("si", len(si.spots) - 1)
        src = clip.get("from")
        label = f"Paste {_KIND_NAME[kind]}" + (f" from {src}" if src and src != d.base else "")
        if self.apply(label, _MOVE_ASPECT[kind], do):
            self.select(out.get("k"))
            k = out.get("k")
            ref = "(Gen record @0x%x)" % k[1] if k and kind in ("gpos", "mpos") else None
            bad = [m for _s, _w, m in (self._gate_point_issues() if ref else ()) if ref in m]
            self.status(label + (" -- but " + bad[0].split(": ", 1)[-1] if bad else "")
                        + "".join(f"; {n}" for n in notes)
                        + (self.shared_flag_note(k[1]) if kind == "mobj" else ""))

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
        # the destination opens at this map's zoom, centred where the warp arrives
        ax, ay = recs[j][6], recs[j][7]
        self.open_map(name, (ax / 8, ay / 8) if ax or ay else None)

    def open_map(self, name, at=None):
        """Open another map in this editor (after asking about unsaved changes), at the current
        zoom, centred on `at` (tiles) or the map's middle. The host (the asset explorer) may
        swap in its own navigation."""
        if not self.confirm_discard(f"open {name}"):
            return
        self.status(f"→ {name}")
        self._warp_view = (self.view.cp, at)
        nav = self.on_navigate or self._navigate_local

        def go():
            try:
                nav(name)
            except Exception as ex:  # noqa: BLE001 - surface it instead of a silent trace
                self._warp_view = None
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

    def _load_spawns(self, quiet=False):
        if self.doc is None or self._spawns_for is self.doc:
            return
        if not quiet:
            self.status("Scanning this map's event script for NPC spawns…")
            self.frame.update_idletasks()
        bank, spawns = data.script_spawns(self.doc.base)
        self._spawns_for = self.doc
        self._spawn_bank = bank
        self.view.st.spawns = spawns
        # redraw the markers now: the update_idletasks above may already have run the redraw
        # set_map scheduled, while the spawn list was still empty
        self.view.invalidate("spawn")
        if not quiet:
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
        self.viewtab.remember()
        if key == "spawns" and on:
            self._load_spawns()
        g = LAYER_GROUPS[key]
        if g == "bg":
            self.view.invalidate("bg")
        elif key == "sprites":                  # sprites under the ATTR fill: its opacity changes
            self.view.invalidate("bg", g, "sel")
        elif key in ("gates", "gate_art"):      # the gates drawn as sprites go with their markers
            self.view.invalidate(g, "under", "sel")
        else:
            self.view.invalidate(g, "sel")

    def set_ground_display(self, sel):
        self.view.ground_sel = sel
        self.viewtab.remember()
        self.view.invalidate("bg")
        self.view.request_ground()

    # ---- which flags decide the flag-gated objects ------------------------ #
    def set_flag_source(self, choice, path=None):
        """choice = FLAGS_NONE, FLAGS_LIVE or a slot-save file name (path overrides)."""
        vt = self.viewtab
        state, err = None, ""
        try:
            if choice == FLAGS_LIVE:
                state = flagstate.from_running_game()
            elif choice != FLAGS_NONE:
                src = pathlib.Path(path) if path else self._flag_paths.get(choice, data.save_dir() / choice)
                self._flag_paths[choice] = src
                state = flagstate.from_save(src)
        except Exception as e:                  # not running / unreadable file: show all
            err = str(e)
        self.view.st.flags = state
        if state is not None:
            n = self._count_flag_hidden(state)
            vt.flagstatus.config(foreground=ui.GOOD,
                                 text=f"{state.source}: story step {state.story()}; "
                                      f"{n} object(s) on this map hidden")
        else:
            vt.flagstatus.config(foreground="#c44" if err else ui.GOOD,
                                 text=err or "every object shown")
        self.view.invalidate("ent", "sel")

    def browse_flag_save(self):
        path = filedialog.askopenfilename(
            parent=self.frame, title="Slot save to take the flags from",
            initialdir=str(data.save_dir()), filetypes=[("RF4S slot save", "rf4_s*.sav"), ("All files", "*.*")])
        if not path:
            return
        name = pathlib.Path(path).name
        self._flag_paths[name] = pathlib.Path(path)
        self.viewtab.flagsrc.set(name)
        self.set_flag_source(name, path)

    def _count_flag_hidden(self, state):
        d = self.doc
        return sum(flagstate.hidden(o, state) for o in d.objs) if d is not None else 0

    def set_runtime_tips(self, on):
        """The View tab's 'pop-up info on the game's built-in warps' option."""
        self.view.runtime_tips = bool(on)
        self.viewtab.remember()

    def set_scenery(self, on):
        self.view.scenery = bool(on)
        self.viewtab.remember()
        self.view.invalidate("bg")
        self.view.request_ground()

    def set_attr_alpha(self, a):
        self.view.attr_alpha = int(a)
        self.viewtab.remember()
        self.view.invalidate("bg")

    def set_ground_dim(self, pct):
        """Darken the ground texture by `pct` % so the objects on it stand out."""
        self.view.ground_dim = int(pct)
        self.viewtab.dim.set(int(pct))
        self.viewtab.remember()
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

    # ---- the over-model (the scenery cards drawn over the ground) ------------------------ #
    def _overmodel_target(self):
        """(set name, file name, game-folder path) of this map's over-model, or an error text."""
        from rf4s_modkit import gamepaths
        d = self.doc
        setname = mapground.overmodel_for(d.base) if d is not None and d.base else None
        if not setname:
            return "This map has no over-model (nothing is drawn over its ground)."
        name = setname + ".model"
        targets = gamepaths.game_targets([name])
        if targets is None:
            return "No game folder is set up, so there is nothing to change."
        return setname, name, targets[name]

    def blank_overmodel(self):
        """Replace this map's over-model file with the game's own empty placeholder, after a
        confirmation that lists every map sharing the file. True when written."""
        from rf4s_modkit import gamepaths
        got = self._overmodel_target()
        if isinstance(got, str):
            messagebox.showinfo("Empty over-model", got)
            return False
        setname, name, target = got
        reader = self.tex_reader
        cur = reader(name) if reader else None
        if cur is not None and mapground.overmodel_is_blank(cur):
            messagebox.showinfo("Empty over-model", f"{name} is already empty: this map draws no "
                                                     "scenery over its ground.")
            return False
        blank = reader(mapground.BLANK_OVERMODEL + ".model") if reader else None
        if blank is None or not mapground.overmodel_is_blank(blank):
            messagebox.showerror("Empty over-model", f"Could not read the game's empty over-model "
                                                     f"({mapground.BLANK_OVERMODEL}.model).")
            return False
        users = mapground.overmodel_users(setname)
        others = [u for u in users if u != self.doc.base]
        shown = ", ".join(others[:12]) + (f" (+{len(others) - 12} more)" if len(others) > 12 else "")
        bdir = gamepaths.find_bundle_dir()
        where = (str(target.relative_to(bdir.parent)) if bdir and bdir.parent in target.parents
                 else str(target))
        msg = (f"Replace {name} with an empty over-model?\n\n"
               f"The over-model is the pre-rendered scenery the game draws over the ground "
               f"(rooftops, railings, tree tops ...). After this, {self.doc.base} shows only its "
               f"ground and its placed objects. Collision does not change: the over-model is "
               f"drawn only.\n\n"
               + (f"The file is SHARED: {len(others)} other map(s) use it and lose their scenery "
                  f"too: {shown}\n\n" if others else "")
               + f"It is written to {where}. The original is copied to "
               f"{gamepaths.BACKUP_DIR} the first time, and Restore… puts it back.")
        if not messagebox.askyesno("Empty over-model", msg, icon="warning", default="no"):
            self.status("Over-model left unchanged")
            return False
        try:
            gamepaths.write_game_file(target, blank, force_original=True)   # Restore… needs it
        except OSError as e:
            messagebox.showerror("Empty over-model", f"Could not write {target}:\n{err_text(e)}\n\n"
                                                     "(Is the game running with the file open?)")
            return False
        self._overmodel_changed(setname)
        kept = gamepaths.backup_path(target)
        self.status(f"{name} is now empty ({len(users)} map(s) use it)"
                    + (f"; the original is in {gamepaths.BACKUP_DIR}" if kept and kept.is_file() else "")
                    + " -- " + reload_hint(False))
        return True

    def restore_overmodel(self):
        """Put this map's original over-model back -- the ModdingBackup copy, or, for a file the
        game only has packed, remove the Bundle\\00_mods override -- after a confirmation."""
        import shutil
        from rf4s_modkit import gamepaths, mbundle
        got = self._overmodel_target()
        if isinstance(got, str):
            messagebox.showinfo("Restore over-model", got)
            return False
        setname, name, target = got
        backup = gamepaths.backup_path(target)
        users = mapground.overmodel_users(setname)
        if backup is not None and backup.is_file():
            how = f"copy the original back from {gamepaths.BACKUP_DIR}"
        elif target.is_file() and target.parent.name == mbundle.MOD_FOLDER:
            how = (f"delete the override {mbundle.MOD_FOLDER}\\{name}, so the packed original "
                   f"loads again")
            backup = None
        else:
            messagebox.showinfo("Restore over-model", f"No saved original of {name} was found: the "
                                                      "file is the one the game shipped (or it was "
                                                      "changed outside the toolkit).")
            return False
        if not messagebox.askyesno("Restore over-model",
                                   f"Restore {name}? This will {how}.\n\n{len(users)} map(s) use "
                                   f"this over-model and get their scenery back.",
                                   icon="warning", default="no"):
            self.status("Over-model left unchanged")
            return False
        try:
            if backup is not None:
                shutil.copy2(backup, target)
            else:
                target.unlink()
        except OSError as e:
            messagebox.showerror("Restore over-model", f"Could not restore {target}:\n{err_text(e)}")
            return False
        self._overmodel_changed(setname)
        self.status(f"{name} restored -- " + reload_hint(False))
        return True

    def _overmodel_changed(self, setname):
        render._SCENERY.pop(setname, None)            # re-read the file
        data._EXTRACTED_INDEX = None                  # a new Bundle\00_mods file is findable
        self.view.ground.reset()
        self.view.background.invalidate()
        self.view.request_ground()

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
            messagebox.showerror("Ground art", err_text(e))
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
            messagebox.showerror("Ground art", err_text(e))
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

    def open_flag_reference(self, focus=None):
        """The scene-flag (zone 2) reference: the numbering of object and warp flags."""
        self._keep(dialogs.scene_flag_reference(self, focus))

    def open_story_flags(self):
        """The named story / event flags (zone 1, emdeb)."""
        self._keep(dialogs.flag_reference(self))

    def flag_uses_text(self, rel, skip=None, limit=4):
        """'also: ...' lines for zone-2 flag `rel` from every map and the event scripts (the
        open map's current records included), leaving out the use `skip` = (kind, index) on
        this map. Starts the background scan the first time and refreshes the Inspector when
        it is done; '' until then."""
        from rf4s_modkit import flagusers
        if data.flag_index() is None:
            data.request_flag_index(self.frame, lambda _i: self.inspector.show_selection(self.sel))
            return "(looking up who else uses this flag ...)"
        d = self.doc
        live = (d.base, d.map.mobj_records(), d.map.mapj_records()) if d and d.base else None
        uses = [u for u in data.flag_users(rel, live)
                if not (skip and live and u.get("map") == live[0]
                        and (u["kind"], u["index"]) == skip)]
        if not uses:
            return "nothing else in the game uses this flag"
        lines = [flagusers.describe(u) for u in uses[:limit]]
        more = len(uses) - limit
        return "also: " + "\n  ".join(lines) + (f"\n  (+{more} more -- Flags… lists them)" if more > 0 else "")

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
                                    map_name=d.base or None, dest_loader=data.load_map_by_id)
        except Exception as e:  # noqa: BLE001
            issues = [f"ERROR: validation crashed: {e}"]
        for s in issues:
            sev, _, msg = s.partition(": ")
            out.append((sev, "map", msg))
        try:                                    # the MGRP value: season / area-group conflicts
            for sev, msg in areagroup.problems(
                    d.map.mgrp(), d.base + ".rf4m" if d.base else None,
                    gen_entries=data.own_gen_entries(d), gen_name_for=data.gen_name_for_id,
                    gen_entries_for=data.gen_entries,
                    sibling_zones=data.sibling_zones(d.base) if d.base else None):
                out.append((sev, "map", "MGRP: " + msg))
        except Exception as e:  # noqa: BLE001
            out.append(("WARN", "map", f"MGRP check failed: {e}"))
        try:                                    # treasure chests: flags, loot rows
            for sev, _i, msg in data.chest_problems(d.base, d.map.mobj_records()):
                out.append((sev, "map", msg))
        except Exception as e:  # noqa: BLE001
            out.append(("WARN", "map", f"chest check failed: {e}"))
        if d.gen is not None:
            for s in d.gen.validate():
                sev, _, msg = s.partition(": ")
                out.append((sev, "monster gates", msg) if sev in ("ERROR", "INFO")
                           else ("WARN", "monster gates", s))
            out += self._shared_note("gen")
        if d.gen is not None and d.grid:
            out += self._gate_point_issues()
        if d.si is not None:
            for s in d.si.validate():          # spot count, pool size, weights, item ids ...
                sev, _, msg = s.partition(": ")
                out.append((sev if sev in ("ERROR", "WARN") else "WARN", "search items", msg))
            out += self._shared_note("si")
        if d.si is not None and d.grid:
            W, H, _ = d.grid
            for i, sp in enumerate(d.si.spots):
                if not (0 <= sp.tile_x < W and 0 <= sp.tile_y < H):
                    out.append(("WARN", "search items", f"search spot #{i} at tile ({sp.tile_x}, "
                                                        f"{sp.tile_y}) is outside the {W}x{H} grid"))
        return out

    def _shared_file(self, part):
        """(file name, [other rooms]) for this map's SI / Gen file (part 'si' / 'gen'): the
        rooms besides this map and its seasonal variants that the game loads it for too."""
        d = self.doc
        path = d.si_path if part == "si" else d.gen_path
        fn = path.name if path else None
        try:
            return fn, data.also_used_by(part, fn, d.base)
        except Exception:  # noqa: BLE001 - no table: nothing to say
            return fn, []

    def _shared_note(self, part):
        """The INFO line for a side file other rooms load too (their gates / search items change
        with it)."""
        fn, others = self._shared_file(part)
        if not others:
            return []
        what = "monster gates" if part == "gen" else "search items"
        return [("INFO", what, f"{fn} is also used by {', '.join(others[:6])}"
                 + (f" and {len(others) - 6} more" if len(others) > 6 else "")
                 + f": the game loads it for {'that room' if len(others) == 1 else 'those rooms'} "
                   f"too, so edits here change {'its' if len(others) == 1 else 'their'} {what}")]

    def _shared_ok(self, part):
        """Before saving a side file other rooms load too: ask, once per file and session."""
        fn, others = self._shared_file(part)
        if not others:
            return True
        seen = self.__dict__.setdefault("_shared_asked", set())
        if fn in seen:
            return True
        what = "monster gates" if part == "gen" else "search items"
        if not messagebox.askyesno(
                "File shared with other rooms",
                f"{fn} is also used by: {', '.join(others)}.\n\nThe game loads this file for "
                f"{'that room' if len(others) == 1 else 'those rooms'} too, so saving your "
                f"changes changes {'its' if len(others) == 1 else 'their'} {what} as well.\n\n"
                f"Save anyway?"):
            return False
        seen.add(fn)
        return True

    def sidecar_saves_ok(self, parts):
        """The search-item and monster-gate checks before writing those files (save_to_game):
        fatal search-item problems, and files other rooms load too."""
        if "si" in parts and not self._fatal_ok("search items", "Search items have fatal problems",
                                                "The game would hang on this search-item table"):
            return False
        return all(self._shared_ok(p) for p in ("si", "gen") if p in parts)

    # A monster appears at a random spot within its spawn point's radius: the game takes up
    # to 63 random samples for a tile whose ATTR value has bit 0x01 or 0x20 (walkable; off the
    # map counts as blocked), then gives up and uses the point itself (Companion_TickAnimation
    # RF4S.exe+0x1E8A60: the sample counter starts at 1 and stops at 64). Gates are
    # placed as they are -- the game ships 100+ on non-walkable tiles -- so only a gate
    # outside the map is flagged.
    WALKABLE = 0x21

    def _gate_point_issues(self):
        d = self.doc
        W, H, cells = d.grid

        def walkable(tx, ty):
            return 0 <= tx < W and 0 <= ty < H and bool(cells[ty * W + tx] & self.WALKABLE)

        out = []
        for kind, off, x, y, _users in d.gate_points():
            tx, ty = x >> 3, y >> 3
            ref = "(Gen record @0x%x)" % off
            if kind == "gpos":
                if not (0 <= tx < W and 0 <= ty < H):
                    out.append(("WARN", "monster gates", f"gate position {ref} at tile ({tx}, {ty}) is "
                                f"outside the {W}x{H} map -- the gate can never be reached"))
                continue
            e, i = d.locate_point(kind, off)
            r = (e.mon_pos.points[i][2] & 0xFFFF) if e is not None else 0
            if walkable(tx, ty):
                continue
            reach = any(walkable(cx, cy)
                        for cy in range((y - r) >> 3, ((y + r) >> 3) + 1)
                        for cx in range((x - r) >> 3, ((x + r) >> 3) + 1)
                        if (min(max(x, cx * 8), cx * 8 + 7) - x) ** 2
                        + (min(max(y, cy * 8), cy * 8 + 7) - y) ** 2 <= r * r)
            if not reach:
                out.append(("WARN", "monster gates",
                            f"monster spawn point {ref} at tile ({tx}, {ty}): no walkable tile within "
                            f"its radius ({r} sub-units) -- all 63 random samples miss, so every "
                            f"monster appears on the point itself, inside a blocked tile (walkable = "
                            f"ATTR bit 0x01 or 0x20); move "
                            f"it onto open ground or widen the radius"))
        return out

    def stats_line(self):
        d = self.doc
        W, H = (d.grid[0], d.grid[1]) if d.grid else (0, 0)
        params = sum(1 for o in d.objs if o["category"] == "mapparam")
        return (f"{W}×{H} grid · {len(d.objs)} MOBJ records ({params} map parameters) · "
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
            L += ["", f"Monster gates ({d.gen_path.name if d.gen_path else 'Gen'}):", "  " + (roster or "(none)")]
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
            messagebox.showerror("Save failed", err_text(e))
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
            why = d.si_block_reason() if d is not None else None
            messagebox.showinfo("Save search items", "This map has no search spots."
                                + ("\n\n" + why if why else ""))
            return False
        if not (self._fatal_ok("search items", "Search items have fatal problems",
                               "The game would hang on this search-item table")
                and self._shared_ok("si")):
            return False
        p = self._ask_path("Save search items", d.si_path.name if d.si_path else
                           (data.si_name_for_map(d.base) or "SI_MAP.bin"), ".bin", "SI table")
        if not p:
            return False
        try:
            d.si.save(pathlib.Path(p))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save failed", err_text(e))
            return False
        d.mark_saved("si")
        self.status(f"Saved {p}")
        self._update_chrome()
        return True

    def save_gen(self):
        self.flush_edits()
        d = self.doc
        if d is None or d.gen is None:
            messagebox.showinfo("Save monster gates", "This map has no monster gates table (Gen*.bin).")
            return False
        fatal = [m for s, where, m in self.validate() if s == "ERROR" and where == "monster gates"]
        if fatal and not messagebox.askyesno(
                "Monster gates have fatal problems", "The game would crash or hang on this table:\n\n"
                + "\n".join("• " + x for x in fatal[:6]) + ("\n…" if len(fatal) > 6 else "")
                + "\n\nSave anyway?"):
            return False
        if not self._shared_ok("gen"):
            return False
        p = self._ask_path("Save monster gates", d.gen_path.name if d.gen_path else "Gen.bin", ".bin", "Gen table")
        if not p:
            return False
        try:
            d.gen.save(pathlib.Path(p))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save failed", err_text(e))
            return False
        d.mark_saved("gen")
        self.status(f"Saved {p}")
        self._update_chrome()
        return True

    def _fatal_ok(self, where, title, what):
        """True unless validation finds errors that break the game in `where` and the user
        declines to save anyway."""
        fatal = [m for s, w, m in self.validate() if s == "ERROR" and w == where]
        return not fatal or messagebox.askyesno(
            title, what + ":\n\n" + "\n".join("• " + x for x in fatal[:6])
            + ("\n…" if len(fatal) > 6 else "") + "\n\nSave anyway?")

    def save_to_game(self):
        """Save (Ctrl+S): overwrite this map's changed files -- the .rf4m, its search spots, its
        encounters -- where the game loads them from the game folder, without asking; the
        first time, the originals are copied to ModdingBackup. A file the game only has
        inside a packed .mbundle goes to Bundle\\00_mods. Without a game folder it falls back
        to the Save … as… dialogs. True when everything changed was written."""
        from rf4s_modkit import gamepaths
        self.flush_edits()
        d = self.doc
        if d is None:
            return False
        parts = [p for p in ("map", "si", "gen") if d.dirty(p)]
        if not parts:
            self.status("Nothing to save: no unsaved changes")
            return True
        if "map" in parts and not self._fatal_ok("map", "Map has fatal problems",
                                                 "The game's loader would choke on this map"):
            return False
        if "gen" in parts and not self._fatal_ok("monster gates", "Monster gates have fatal problems",
                                                 "The game would crash or hang on this table"):
            return False
        if not self.sidecar_saves_ok(parts):
            return False
        own = None
        if self.file_path is not None and "map" in parts:   # a map opened from disk: its own file
            try:
                pathlib.Path(self.file_path).write_bytes(d._bytes("map"))
            except OSError as e:
                messagebox.showerror("Save", f"Could not write {self.file_path}:\n{err_text(e)}")
                return False
            d.mark_saved("map")
            parts.remove("map")
            own = f"Saved {self.file_path}"
            if not parts:
                self._update_chrome()
                self.status(own)
                return True
        game_map = None
        if "map" in parts:
            # the game asks for a map by id -> g_mapResourceTable -> an EXACT-case file name, so
            # the file must go under that name (a tab named after a renamed copy or a lower-case
            # file would land somewhere the game never reads)
            mid = map_names.map_id_for_file(d.base or "")
            if mid is None:
                messagebox.showerror(
                    "Save", f"“{d.base}” is not one of the game's map names, so the game would "
                            "never load a file saved under it. Use Save map as… in the Save menu "
                            "to write it anywhere, or open the game's map of that name.")
                return False
            game_map = map_names.map_file(mid) + ".rf4m"
        names = {"map": game_map,
                 "si": d.si_path.name if d.si_path else data.si_name_for_map(d.base),
                 "gen": d.gen_path.name if d.gen_path else data.gen_name_for_map(d.base)}
        targets = gamepaths.game_targets([names[p] for p in parts if names[p]])
        if targets is None:
            return self.save_all()
        written, backed, new = [], [], False
        for p in parts:
            name = names[p]
            if not name:
                messagebox.showerror("Save", f"No file name for this map's {d.PART_LABELS[p]}: "
                                             "use Save … as… in the Save menu.")
                return False
            new = new or not targets[name].exists()
            try:
                if gamepaths.write_game_file(targets[name], d._bytes(p)) is not None:
                    backed.append(name)
            except OSError as e:
                messagebox.showerror("Save", f"Could not write {targets[name]}:\n{err_text(e)}\n\n"
                                             "(Is the game running with the file open?)")
                return False
            d.mark_saved(p)
            if p == "si":
                d.si_path = targets[name]
            elif p == "gen":
                d.gen_path = targets[name]
            written.append(targets[name])
        data._EXTRACTED_INDEX = None            # a new Bundle\00_mods file is findable at once
        self._update_chrome()
        bdir = gamepaths.find_bundle_dir()
        shown = [str(t.relative_to(bdir.parent)) if bdir and bdir.parent in t.parents else str(t)
                 for t in written]
        self.status("Saved " + ", ".join(([str(self.file_path)] if own else []) + shown)
                    + (f" (originals kept in {gamepaths.BACKUP_DIR})" if backed else "")
                    + " -- " + reload_hint(new))
        others = {n: v for n, v in targets[None].items()}
        if others:
            messagebox.showwarning(
                "Other copies", "Saved. The game folder also has other copies of these files, "
                "which the game ignores (it loads one file per exact name):\n\n"
                + "\n".join(f"{n} -- the game loads {targets[n]}\n  ignored: "
                            + "\n  ignored: ".join(str(o) for o in v) for n, v in others.items())
                + "\n\nDelete the ignored copies (left over from earlier saves or mods) so they "
                  "do not confuse you or another tool.")
        if "map" in parts:
            self._season_note()
        return True

    SEASON_NOTE_SETTING = "season_note_shown"  # settings.json: the seasonal-map note was shown

    def _season_note(self):
        """Once, ever (remembered in settings.json): a seasonal map (farm, fields, Selphia's
        streets, farmhouse) is four files, and the game loads the one for the current season.
        The Save menu's tooltip keeps saying so afterwards."""
        from rf4s_modkit import gamepaths
        base = (self.doc.base or "").upper()
        fam = map_names.season_family(map_names.map_id_for_file(base))
        if not fam or gamepaths.get_setting(self.SEASON_NOTE_SETTING):
            return
        try:
            gamepaths.set_setting(self.SEASON_NOTE_SETTING, True)
        except OSError:
            pass                                # a read-only toolkit folder: shown again next run
        mine = next((s for s, f in fam if f.upper() == base), "?")
        rest = [f"{f} ({s})" for s, f in fam if f.upper() != base]
        messagebox.showinfo(
            "Saved: a seasonal map",
            f"{base} is this place in {mine}. The game loads a different file in each season:\n\n"
            + "\n".join(rest) + f"\n\nSo the change only shows in {mine}. To see it in another "
            "season, make the same edit in that season's map (or play a save in that season).")

    def copy_to_seasons(self):
        """Carry this map's changes to its other seasons (farm, fields, Selphia's streets,
        farmhouse: four files, one per season). The changes are worked out against the map as
        the game shipped it -- the original in ModdingBackup when the map was saved in place,
        else the map as it was opened -- and replayed on each season (rf4s_modkit.mapdiff):
        an edited or removed object / warp only where that season has the same one, added ones
        everywhere, ATTR cells where the grid is the same size; map settings never. Shows what
        will happen, then writes the seasons over the game's files (originals kept once in
        ModdingBackup). True when something was written."""
        from rf4s_modkit import gamepaths, mapdiff, rf4m as _rf4m
        title = "Copy changes to the other seasons"
        self.flush_edits()
        d = self.doc
        if d is None:
            return False
        fam = map_names.season_family(map_names.map_id_for_file(d.base or ""))
        if not fam:
            messagebox.showinfo(title, f"{d.base} looks the same all year: the game has no other "
                                       "seasons of it.")
            return False
        mine = next((f for _s, f in fam if f.upper() == (d.base or "").upper()), d.base)
        targets = gamepaths.game_targets([f + ".rf4m" for _s, f in fam])
        if targets is None:
            messagebox.showerror(title, "Set the game folder first (Options… → General in the main window).")
            return False
        backup = gamepaths.backup_path(targets[mine + ".rf4m"])
        if backup is not None and backup.is_file():
            base_bytes, origin = backup.read_bytes(), "the original in ModdingBackup"
        else:
            base_bytes, origin = d.opened["map"], "the map as it was when opened"
        ch = mapdiff.diff(_rf4m.Rf4mMap.parse(base_bytes), d.map)
        replayable = ch.cells or any(ch.edited.values()) or any(ch.added.values()) or any(ch.removed.values())
        if not replayable:
            messagebox.showinfo(title, f"Nothing to copy: no object, warp or ATTR changes since {origin}."
                                + (f"\n\n(Changed map settings -- {', '.join(ch.other)} -- are "
                                   "season-specific and never copied.)" if ch.other else ""))
            return False
        plans = []
        for season, f in fam:
            if f.upper() == mine.upper():
                continue
            t = targets[f + ".rf4m"]
            src = t if t.is_file() else data.find_extracted(f + ".rf4m")
            if src is None:
                plans.append((season, f, None, None, None))
                continue
            m = _rf4m.Rf4mMap.load(src)
            plans.append((season, f, t, m, mapdiff.apply(ch, m)))
        lines = [f"Changes to {mine} since {origin}: {ch.summary()}.", ""]
        for season, f, _t, _m, rep in plans:
            if rep is None:
                lines.append(f"{f} ({season}): not found in the game folder")
            else:
                lines.append(f"{f} ({season}): {len(rep.done)} to copy"
                             + (f", {len(rep.skipped)} skipped" if rep.skipped else ""))
        skipped = [f"{f}: {x}" for _s, f, _t, _m, rep in plans if rep for x in rep.skipped]
        if skipped:
            lines += ["", "Skipped (that season differs there, or it is season-specific):"]
            lines += ["  " + x for x in skipped[:12]] + (["  …"] if len(skipped) > 12 else [])
        todo = [p for p in plans if p[4] is not None and p[4].done]
        if not todo:
            messagebox.showinfo(title, "\n".join(lines + ["", "Nothing could be copied."]))
            return False
        known = set(data.rooms_by_id())
        fatal = []                              # each season's validation ERRORs after the copy
        for _season, f, _t, m, _rep in todo:
            try:
                errs = [s[7:] for s in m.validate(known_maps=known, map_name=f,
                                                  dest_loader=data.load_map_by_id)
                        if s.startswith("ERROR: ")]
            except Exception as e:  # noqa: BLE001
                errs = [f"validation crashed: {e}"]
            fatal += [f"{f}: {x}" for x in errs]
        if fatal:
            lines += ["", "After the copy the game would choke on:"]
            lines += ["  • " + x for x in fatal[:8]] + (["  …"] if len(fatal) > 8 else [])
        lines += ["", "Write the other seasons over the game's files" + (" anyway" if fatal else "")
                  + "? (With backups on, the originals are kept in ModdingBackup.) A season open in "
                    "another tab still shows the old map until you reopen it."]
        if not messagebox.askyesno(title, "\n".join(lines), icon="warning" if fatal else "question"):
            return False
        written, new = [], False
        for season, f, t, m, _rep in todo:
            new = new or not t.exists()
            try:
                gamepaths.write_game_file(t, m.build())
            except OSError as e:
                messagebox.showerror(title, f"Could not write {t}:\n{err_text(e)}\n\n(Is the game running "
                                            "with the file open?)")
                return bool(written)
            written.append(f"{f} ({season})")
        data._EXTRACTED_INDEX = None
        self.status("Copied the changes to " + ", ".join(written) + " -- " + reload_hint(new))
        return True

    def save_all(self):
        """Save every changed file, each through its own dialog. False if one was cancelled."""
        self.flush_edits()
        parts = self.dirty_parts()
        if not parts:
            self.status("Nothing to save: no unsaved changes")
            return True
        for label, fn in (("map", self.save_map), ("search items", self.save_si), ("monster gates", self.save_gen)):
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
        ground, top = render.Background().layers(
            d.grid, self.view.colors, st.cp, self.view.ground_image(block=True),
            attr_on=st.layers.get("attr", True), alpha=self.view.attr_alpha,
            edges_on=st.layers.get("edges", True), attr_version=d.attr_version,
            under=bool(st.layers.get("sprites")), dim=self.view.ground_dim)
        # the canvas stacking: ground, sprites, ATTR, the other overlays
        img = ground.copy() if ground is not None else Image.new("RGBA", (W * st.cp, H * st.cp), (0, 0, 0, 0))
        img = render.draw_prims(img, render.overlay("under", st), st.sprites)
        if top is not None:
            img = Image.alpha_composite(img, top)
        prims = [p for g in render.GROUPS if g not in ("sel", "under", "lift") for p in render.overlay(g, st)]
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
