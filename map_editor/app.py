"""The standalone map editor window: a map list beside one MapEditorPanel."""
from __future__ import annotations

import pathlib
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from rf4s_modkit import gamepaths, map_names, rf4m

from . import data, render
from .panel import MapEditorPanel
from guiutil import err_text


GROUP_MAPS_SETTING = "group_maps_by_area"      # settings.json, shared with the explorer


class MapExplorer:
    def __init__(self, root, initial=None):
        from guiutil import Paned
        self.root = root
        root.title("RF4S Map Editor")
        root.geometry("1400x880")
        bar = ttk.Frame(root)
        bar.pack(fill="x")
        ttk.Button(bar, text="Open folder…", command=self._pick_dir).pack(side="left", padx=2, pady=3)
        ttk.Button(bar, text="Open .rf4m…", command=self._pick_file).pack(side="left", padx=2)
        self.status = ttk.Label(bar, text="", anchor="e")
        self.status.pack(side="right", padx=8)
        paned = Paned(root, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned)
        paned.add(left, weight=0, minsize=150)
        ttk.Label(left, text="Maps").pack(anchor="w", padx=4, pady=(4, 0))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_a: self._refresh_list())
        ttk.Entry(left, textvariable=self.filter_var).pack(fill="x", padx=4)
        # one header per in-game area (the same toggle and setting as the explorer's)
        self.group_var = tk.BooleanVar(value=bool(gamepaths.get_setting(GROUP_MAPS_SETTING, True)))
        ttk.Checkbutton(left, text="Group maps by area", variable=self.group_var,
                        command=self._toggle_group).pack(anchor="w", padx=4, pady=(4, 0))
        lf = ttk.Frame(left)
        lf.pack(fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        self.tree = ttk.Treeview(lf, show="tree", selectmode="browse", yscrollcommand=sb.set)
        self.tree.column("#0", width=210)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.config(command=self.tree.yview)
        self.tree.bind("<<TreeviewSelect>>", self._on_pick)
        host = ttk.Frame(paned)
        paned.add(host, weight=5)
        self.panel = MapEditorPanel(host, status_fn=lambda s: self.status.config(text=s),
                                    on_navigate=self.open)
        self._all = sorted(data.EXTRACTED.rglob("*.rf4m")) if data.EXTRACTED.is_dir() else []
        self._listed = []
        self._current = None
        self._refresh_list()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.status.config(text=f"{len(self._all)} maps" + ("" if render.HAS_PIL else "  (no Pillow: no textures)"))
        if initial:
            self.open(initial)

    def _refresh_list(self):
        """List the maps (filtered), under one header per area when grouping is on; a header
        opens by itself while a filter is typed."""
        words = self.filter_var.get().lower().split()
        t = self.tree
        was_open = {t.item(i, "text").split("  (")[0] for i in t.get_children() if t.item(i, "open")}
        t.delete(*t.get_children())
        self._listed = [p for p in self._all if all(w in p.stem.lower() for w in words)]
        self._iid = {}
        if self.group_var.get():
            areas = {}
            for p in self._listed:
                areas.setdefault(map_names.map_area(p.name) or "Other maps", []).append(p)
            for a in sorted(areas, key=str.lower):
                h = t.insert("", "end", text=f"{a}  ({len(areas[a])})",
                             open=bool(words) or a in was_open)
                for p in areas[a]:
                    self._iid[p] = t.insert(h, "end", text=p.stem)
        else:
            for p in self._listed:
                self._iid[p] = t.insert("", "end", text=p.stem)
        self._path = {v: k for k, v in self._iid.items()}
        self._reselect()

    def _toggle_group(self):
        try:
            gamepaths.set_setting(GROUP_MAPS_SETTING, bool(self.group_var.get()))
        except OSError:
            pass                                # a read-only toolkit folder: just don't keep it
        self._refresh_list()

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Folder of .rf4m maps",
                                    initialdir=str(data.EXTRACTED if data.EXTRACTED.is_dir() else data.gamepaths.TOOLKIT))
        if d:
            self._all = sorted(pathlib.Path(d).rglob("*.rf4m"))
            self._refresh_list()

    def _pick_file(self):
        f = filedialog.askopenfilename(title="Open .rf4m", filetypes=[("RF4 map", "*.rf4m")])
        if f:
            self.load(pathlib.Path(f))

    def _on_pick(self, _e):
        if getattr(self, "_reselecting", False):
            return
        s = self.tree.selection()
        p = self._path.get(s[0]) if s else None      # None: an area header
        if p is not None and p != self._current:
            if not self.load(p):
                self._reselect()

    def _reselect(self):
        """Highlight the open map (opening its area) without loading it again."""
        iid = self._iid.get(self._current) if self._current is not None else None
        self._reselecting = True
        try:
            self.tree.selection_set(iid) if iid else self.tree.selection_set(())
            if iid:
                self.tree.see(iid)
        finally:
            self.tree.after_idle(lambda: setattr(self, "_reselecting", False))

    def open(self, arg):
        """Open a map by path or by name (looked up in the extracted tree)."""
        p = pathlib.Path(arg)
        if p.is_file():
            return self.load(p)
        name = p.name                       # 'bundleMain/MAP_X.rf4m' from a host -> 'MAP_X.rf4m'
        hit = data.find_extracted(name if name.lower().endswith(".rf4m") else f"{name}.rf4m")
        if hit is None:
            self.status.config(text=f"{arg}: not found")
            return False
        return self.load(hit)

    def load(self, path):
        path = pathlib.Path(path)
        if not self.panel.confirm_discard(f"open {path.stem}"):
            return False
        try:
            m = rf4m.Rf4mMap.load(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Load failed", err_text(e))
            return False
        self.panel.tex_reader = data.folder_reader(path.parent)
        self.panel.set_map(m, path.stem)
        self._current = path
        self._reselect()
        self.root.title(f"RF4S Map Editor — {path.stem}")
        self.status.config(text=str(path))
        return True

    def _on_close(self):
        if self.panel.confirm_discard("close the editor"):
            self.root.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    import app_icon
    app_icon.prepare()
    root = tk.Tk()
    import guiutil
    guiutil.install_error_logging(root)
    import guiscale
    guiscale.install(root)                  # text size (Options), live
    guiutil.install_combo_keys(root)
    import guitheme
    guitheme.install(root)                  # light / dark (settings.json)
    app_icon.apply(root)
    MapExplorer(root, initial=argv[0] if argv else None)
    root.mainloop()
