"""The standalone map editor window: a map list beside one MapEditorPanel."""
from __future__ import annotations

import pathlib
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from rf4s_modkit import rf4m

from . import data, render
from .panel import MapEditorPanel


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
        lf = ttk.Frame(left)
        lf.pack(fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        self.listbox = tk.Listbox(lf, yscrollcommand=sb.set, exportselection=False, width=24)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_pick)
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
        words = self.filter_var.get().lower().split()
        self.listbox.delete(0, "end")
        self._listed = [p for p in self._all if all(w in p.stem.lower() for w in words)]
        for p in self._listed:
            self.listbox.insert("end", p.stem)

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Folder of .rf4m maps",
                                    initialdir=str(data.EXTRACTED if data.EXTRACTED.is_dir() else data.REPO))
        if d:
            self._all = sorted(pathlib.Path(d).rglob("*.rf4m"))
            self._refresh_list()

    def _pick_file(self):
        f = filedialog.askopenfilename(title="Open .rf4m", filetypes=[("RF4 map", "*.rf4m")])
        if f:
            self.load(pathlib.Path(f))

    def _on_pick(self, _e):
        s = self.listbox.curselection()
        if s and self._listed[s[0]] != self._current:
            if not self.load(self._listed[s[0]]):
                self._reselect()

    def _reselect(self):
        self.listbox.selection_clear(0, "end")
        if self._current in self._listed:
            i = self._listed.index(self._current)
            self.listbox.selection_set(i)
            self.listbox.see(i)

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
            messagebox.showerror("Load failed", str(e))
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
    root = tk.Tk()
    MapExplorer(root, initial=argv[0] if argv else None)
    root.mainloop()
