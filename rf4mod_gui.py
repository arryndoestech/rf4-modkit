#!/usr/bin/env python3
r"""
rf4mod_gui.py -- a Tkinter explorer for RF4S assets, built on the rf4s_modkit library.

A single window:
  * Left  : a tree of asset entries. Open a Manifest.plist (browse every bundle's
            files, read on demand -- so bundleMain's 4.7 GB never gets slurped),
            a single .mbundle, a folder of extracted/loose files, or one file.
  * Right : a type-aware viewer that adapts to whatever you select --
              .texture        -> decoded image (zoom)
              .png/.jpg/.gif/.bmp/.tif/.webp/.tga/.dds/.ico -> Pillow image (zoom)
              TEXT / rf3mc.*   -> searchable string table
              .minterface/.plist/.mbundle/Manifest -> bplist tree
              .rf4m            -> chunk list + ATTR heatmap + record counts
              .bin (AIBN)      -> opcode disassembly
              .strings         -> key/value table
              .model/.bfskl/.psbData -> NN container structure
              anything else    -> identification + hex preview
  * Buttons: Extract (save raw bytes) and Export (PNG/JSON/disasm where it applies).

Dependencies: Tkinter (stdlib). Pillow enables image views; texture2ddecoder enables
BC7 decode. Everything degrades gracefully without them.

Run:  python rf4mod_gui.py                 # auto-loads <repo>/Bundle/Manifest.plist
      python rf4mod_gui.py <path>          # open a manifest / bundle / folder / file
"""
from __future__ import annotations

import pathlib
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import (  # noqa: E402
    ident, bplist, mbundle, textdb, texture, rf4m, aibn, strings_file, res_container, gen, nlcl,
    search_items, script, mobj_params, asatk, skillcurve, gifts, schedule, map_names,
)

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Standard raster images Pillow can open directly (distinct from the game's own
# BNTX/RES textures, which go through texture.py). `ident` tags these fmt="png"
# or fmt="image"; the extension set is the fallback for formats without a reliable
# magic (e.g. TGA) or that `ident` doesn't sniff.
IMAGE_FMTS = {"png", "jpg", "gif", "bmp", "tiff", "dds", "ico", "webp", "image"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".gif", ".bmp", ".tif", ".tiff",
              ".webp", ".tga", ".dds", ".ico"}

from rf4s_modkit import gamepaths  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
# the game copy's Bundle folder: saved setting, else the nearest Bundle above the toolkit,
# else $RF4S_BUNDLE (rf4s_modkit.gamepaths); main() asks for it when none is found
BUNDLE_DIR = gamepaths.bundle_dir()
# Extraction root: Bundle/extracted/ if present, else a flat Bundle/<bundle>/ layout.
EXTRACTED = gamepaths.extracted_dir(BUNDLE_DIR)
DEFAULT_MANIFEST = BUNDLE_DIR / "Manifest.plist"


def _use_game_paths():
    """Re-derive the path globals here and in the map editor after the game folder changed
    (called before any window or cache exists)."""
    global BUNDLE_DIR, EXTRACTED, DEFAULT_MANIFEST
    BUNDLE_DIR = gamepaths.bundle_dir()
    EXTRACTED = gamepaths.extracted_dir(BUNDLE_DIR)
    DEFAULT_MANIFEST = BUNDLE_DIR / "Manifest.plist"
    md = sys.modules.get("map_editor.data")
    if md is not None:
        md.BUNDLE_DIR, md.EXTRACTED, md._EXTRACTED_INDEX = BUNDLE_DIR, EXTRACTED, None
from rf4s_modkit.refdata import refdata_path as _refdata_path
ACTOR_NAMES_PATH = _refdata_path("rf4s_actor_names.json")   # vendored in modding/refdata/


def _load_actor_names():
    try:
        return gen.load_actor_names(ACTOR_NAMES_PATH)
    except Exception:
        return lambda i: ""


def _load_item_names() -> dict[int, str]:
    """tools/rf4s_item_names.json as {int id: name} (empty dict if absent)."""
    try:
        import json as _json
        raw = _json.loads((ACTOR_NAMES_PATH.parent / "rf4s_item_names.json")
                          .read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}
    except Exception:
        return {}


def _find_extracted(basename: str):
    """Locate a bundle file by basename (for cross-file resolution, e.g. rf3PresentCategory).
    Uses the map editor's cached index of the extracted tree instead of an rglob per call."""
    try:
        import map_editor
        hit = map_editor.find_extracted(basename)
        return hit.read_bytes() if hit else None
    except Exception:
        return None


def _load_char_names() -> dict[int, str]:
    """char_names.json as {int id: name} (vendored modding/refdata/; empty if absent)."""
    try:
        import json as _json
        raw = _json.loads(_refdata_path("char_names.json").read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}
    except Exception:
        return {}

MAX_TABLE_ROWS = 5000  # cap rows shown in big tables (TEXT catalogs are 100k+)


def human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{int(f)} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{int(f)} TB"


def hexdump(data: bytes, limit: int = 4096) -> str:
    out = []
    chunk = data[:limit]
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        hexs = " ".join(f"{b:02x}" for b in row)
        asci = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append(f"{i:08x}  {hexs:<47}  {asci}")
    if len(data) > limit:
        out.append(f"\n... ({len(data) - limit:,} more bytes)")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Entry source abstraction: a flat list of (display_path, group, loader())
# --------------------------------------------------------------------------- #
class Source:
    """A browsable set of named byte blobs (bundle entries, files, ...)."""

    def __init__(self, label: str):
        self.label = label
        self.entries: list[tuple[str, str, object]] = []  # (name, group, loader)

    def add(self, name: str, group: str, loader):
        self.entries.append((name, group, loader))

    def read_named(self, filename):
        """Return bytes for a file by basename (any group), or None. Used to fetch a
        map's sibling ground-texture tiles for the editor's texture layer."""
        base = filename.rsplit("/", 1)[-1].lower()
        if getattr(self, "_byname", None) is None:
            self._byname = {}
            for name, _group, loader in self.entries:
                self._byname.setdefault(name.rsplit("/", 1)[-1].lower(), loader)
        loader = self._byname.get(base)
        if loader is None:
            return None
        try:
            return loader()
        except Exception:
            return None

    @classmethod
    def from_manifest(cls, manifest_path) -> "Source":
        """Every file the manifest lists, grouped by archive. An archive unpacked into
        Bundle/<name>/ is read from that folder (the file the game loads too: loose files
        come before the archives), so a copy whose archives were unpacked and removed
        still shows everything; files not unpacked come from the .mbundle."""
        import os
        man = mbundle.Manifest(manifest_path)
        src = cls(f"Manifest: {pathlib.Path(manifest_path).name}")
        bdir = pathlib.Path(manifest_path).parent
        for bname in man.bundle_names():
            bpath = bdir / bname
            udir = bdir / mbundle.unpack_dir_name(bname)
            loose = set()
            if udir.is_dir():
                for dirpath, _dirs, files in os.walk(udir):
                    rel = os.path.relpath(dirpath, udir)
                    for fn in files:
                        loose.add(fn if rel == "." else os.path.join(rel, fn).replace(os.sep, "/"))
            bundle = mbundle.Bundle(bpath, manifest=man) if bpath.is_file() else None
            for name in man.files(bname):
                rel = name.replace("\\", "/").lstrip("/")
                if rel in loose:
                    fp = udir / rel
                    src.add(name, bname, (lambda f: (lambda: f.read_bytes()))(fp))
                elif bundle is not None:
                    src.add(name, bname, (lambda b, n: (lambda: b.read(n)))(bundle, name))
        return src

    @classmethod
    def from_bundle(cls, bundle_path) -> "Source":
        bpath = pathlib.Path(bundle_path)
        mani = bpath.parent / "Manifest.plist"
        man = mbundle.Manifest(mani) if mani.is_file() else None
        if man is None and bpath.stat().st_size > 256 * 1024 * 1024:
            raise RuntimeError(
                f"{bpath.name} is large and no Manifest.plist sits beside it; "
                f"open the Manifest instead to browse it lazily.")
        bundle = mbundle.Bundle(bpath, manifest=man)
        src = cls(f"Bundle: {bpath.name}")
        for name in bundle.names():
            src.add(name, bpath.name, (lambda n: (lambda: bundle.read(n)))(name))
        return src

    @classmethod
    def from_folder(cls, folder) -> "Source":
        """Every file under `folder`, grouped by its top-level sub-folder; files directly in
        `folder` are ungrouped (listed at the tree root -- the old version put each one in a
        one-file group named after itself). Walks with plain strings (os.walk): the old
        pathlib version spent ~2.5 s in relative_to()/is_file()/parts on the ~38k
        extracted files every time the toolkit started."""
        import os
        folder = pathlib.Path(folder)
        root = str(folder)
        src = cls(f"Folder: {folder.name}")
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            for fn in filenames:
                found.append((f"{rel_dir}/{fn}" if rel_dir else fn, os.path.join(dirpath, fn)))
        # same order the pathlib version produced: part by part (so "numpy/" sorts before
        # "numpy-2.5.3.dist-info/"), case-insensitively on Windows
        found.sort(key=lambda rf: os.path.normcase(rf[1]).split(os.sep))
        for rel, full in found:
            group = rel.split("/", 1)[0] if "/" in rel else ""
            src.add(rel, group, (lambda fp: (lambda: pathlib.Path(fp).read_bytes()))(full))
        return src

    @classmethod
    def from_file(cls, file) -> "Source":
        p = pathlib.Path(file)
        src = cls(f"File: {p.name}")
        src.add(p.name, "", lambda: p.read_bytes())
        return src


# --------------------------------------------------------------------------- #
# Main application
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root: tk.Tk, initial=None):
        self.root = root
        self.source: Source | None = None
        self.cur_name: str | None = None
        self.cur_data: bytes | None = None
        self.cur_image = None          # keep PhotoImage ref alive
        self.zoom = 1.0
        self._pil = None

        root.title("RF4S Modding Toolkit — Asset Explorer")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.geometry("1280x820")

        self._build_toolbar()
        self._build_body()
        self._build_status()

        if initial:
            self.open_path(pathlib.Path(initial))
        elif DEFAULT_MANIFEST.is_file() and any(BUNDLE_DIR.glob("*.mbundle")):
            self.load_source(lambda: Source.from_manifest(DEFAULT_MANIFEST))
        elif EXTRACTED.is_dir():
            self.load_source(lambda: Source.from_folder(EXTRACTED))
        elif DEFAULT_MANIFEST.is_file():
            self.load_source(lambda: Source.from_manifest(DEFAULT_MANIFEST))
        # Warm the lookups the first map view needs (extracted-file index, item names, room
        # table) in the background once the window is up, so the first map click doesn't
        # pay for them (~0.5 s).
        self.root.after(300, self._warm_caches)

    def _warm_caches(self):
        def work():
            try:
                import map_editor
                map_editor.warm_caches()
            except Exception:
                pass
        import threading
        threading.Thread(target=work, daemon=True, name="rf4mod-warmup").start()

    # ---- widgets --------------------------------------------------------- #
    def _build_toolbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="top")
        self._collapse_btn = ttk.Button(bar, text="◀ Files", width=9, command=self.cmd_toggle_files)
        self._collapse_btn.pack(side="left", padx=(2, 6), pady=3)
        ttk.Button(bar, text="Open Manifest…", command=self.cmd_open_manifest).pack(side="left", padx=2, pady=3)
        ttk.Button(bar, text="Open Bundle…", command=self.cmd_open_bundle).pack(side="left", padx=2)
        ttk.Button(bar, text="Game folder…", command=self.cmd_game_folder).pack(side="left", padx=2)
        ttk.Button(bar, text="Open Folder…", command=self.cmd_open_folder).pack(side="left", padx=2)
        ttk.Button(bar, text="Open File…", command=self.cmd_open_file).pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="Map Explorer", command=self.cmd_map_explorer).pack(side="left", padx=2)
        ttk.Button(bar, text="Cutscenes", command=self.cmd_cutscene_editor).pack(side="left", padx=2)
        ttk.Button(bar, text="Extract…", command=self.cmd_extract).pack(side="left", padx=2)
        self.export_btn = ttk.Button(bar, text="Export View…", command=self.cmd_export, state="disabled")
        self.export_btn.pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(bar, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        # Debounced: re-filtering ~38k names on EVERY keystroke made typing stutter; wait
        # until the user pauses (Enter applies immediately).
        self._filter_after = None
        self.filter_var.trace_add("write", lambda *_: self._schedule_filter())
        fe = ttk.Entry(bar, textvariable=self.filter_var, width=28)
        fe.pack(side="left", padx=2)
        fe.bind("<Return>", lambda _e: self._apply_filter_now())
        self.count_lbl = ttk.Label(bar, text="")
        self.count_lbl.pack(side="right", padx=8)

    def _build_body(self):
        from guiutil import Paned
        paned = Paned(self.root, orient="horizontal")   # no live relayout while dragging
        paned.pack(fill="both", expand=True)
        self._paned = paned
        self._left_collapsed = False

        left = ttk.Frame(paned)
        self._left = left
        paned.add(left, weight=0, minsize=160)   # keeps its width; the content gets the rest
        self.tree = ttk.Treeview(left, columns=("size",), show="tree headings")
        self.tree.heading("#0", text="Asset")
        self.tree.heading("size", text="Size")
        self.tree.column("size", width=90, anchor="e", stretch=False)
        vs = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<<TreeviewOpen>>", self._on_group_open)

        self.right = ttk.Frame(paned)
        paned.add(self.right, weight=3, minsize=300)
        # Persistent header + a swappable content frame.
        self.header = ttk.Label(self.right, text="Select an asset", anchor="w",
                                font=("Segoe UI", 10, "bold"))
        self.header.pack(fill="x", padx=6, pady=(6, 2))
        self.content = ttk.Frame(self.right)
        self.content.pack(fill="both", expand=True)

    def _build_status(self):
        self.status = ttk.Label(self.root, text="", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

    def cmd_toggle_files(self):
        """Collapse / restore the left file-select pane (the Asset/Size tree), giving
        the right (preview/editor) pane the full width."""
        if self._left_collapsed:
            self._paned.insert(0, self._left, weight=0, minsize=160)   # restore at the left
            self._collapse_btn.config(text="◀ Files")
            self._left_collapsed = False
        else:
            self._paned.forget(self._left)                # hide the file tree
            self._collapse_btn.config(text="Files ▶")
            self._left_collapsed = True
        deps = []
        deps.append("Pillow:" + ("yes" if HAS_PIL else "no"))
        deps.append("BC7:" + ("yes" if texture.HAS_BC else "no"))
        self.status.config(text="  ·  ".join(deps))

    # ---- source loading -------------------------------------------------- #
    def load_source(self, factory):
        try:
            self.source = factory()
        except Exception as e:
            messagebox.showerror("Open failed", str(e))
            return
        self.root.title(f"RF4S Modding Toolkit — {self.source.label}")
        self._drop_map_view()
        self._refresh_tree()

    def open_path(self, p: pathlib.Path):
        if p.is_dir():
            self.load_source(lambda: Source.from_folder(p))
        elif p.name == "Manifest.plist":
            self.load_source(lambda: Source.from_manifest(p))
        elif p.suffix == ".mbundle":
            self.load_source(lambda: Source.from_bundle(p))
        else:
            self.load_source(lambda: Source.from_file(p))

    def cmd_open_manifest(self):
        f = filedialog.askopenfilename(title="Open Manifest.plist",
                                       initialdir=str(BUNDLE_DIR if BUNDLE_DIR.is_dir() else REPO),
                                       filetypes=[("Manifest", "Manifest.plist *.plist"), ("All", "*.*")])
        if f:
            self.load_source(lambda: Source.from_manifest(f))

    def cmd_game_folder(self):
        """Show / change the game copy every tool uses (takes effect on the next start)."""
        import game_setup
        before = gamepaths.find_bundle_dir()
        if game_setup.run(self.root, current=before) and gamepaths.find_bundle_dir() != before:
            messagebox.showinfo("Game folder", "Saved. Close and start the toolkit again to "
                                "use the new game folder in every tool.", parent=self.root)

    def cmd_open_bundle(self):
        f = filedialog.askopenfilename(title="Open .mbundle",
                                       initialdir=str(BUNDLE_DIR if BUNDLE_DIR.is_dir() else REPO),
                                       filetypes=[("mbundle", "*.mbundle"), ("All", "*.*")])
        if f:
            self.load_source(lambda: Source.from_bundle(f))

    def cmd_open_folder(self):
        d = filedialog.askdirectory(title="Open folder of assets",
                                    initialdir=str(EXTRACTED if EXTRACTED.is_dir() else REPO))
        if d:
            self.load_source(lambda: Source.from_folder(d))

    def cmd_open_file(self):
        f = filedialog.askopenfilename(title="Open a single asset")
        if f:
            self.load_source(lambda: Source.from_file(f))

    # ---- tree ------------------------------------------------------------ #
    GROUP_CAP = 20000     # max leaves shown per group (lazy-loaded on expand)
    FILTER_CAP = 8000     # max matches shown when filtering

    FILTER_DELAY_MS = 180

    def _schedule_filter(self):
        if self._filter_after is not None:
            self.root.after_cancel(self._filter_after)
        self._filter_after = self.root.after(self.FILTER_DELAY_MS, self._apply_filter_now)

    def _apply_filter_now(self):
        if self._filter_after is not None:
            self.root.after_cancel(self._filter_after)
        self._filter_after = None
        self._refresh_tree()

    def _lower_names(self):
        """Lower-cased entry names, computed once per source (the filter compares against
        every name on each refresh)."""
        src = self.source
        if getattr(src, "_lower", None) is None or len(src._lower) != len(src.entries):
            src._lower = [e[0].lower() for e in src.entries]
        return src._lower

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._index = {}            # leaf iid -> entry index
        self._group_indices = {}    # group iid -> [entry indices]
        self._group_loaded = set()
        if not self.source:
            self.count_lbl.config(text="")
            return
        flt = self.filter_var.get().lower()
        n = len(self.source.entries)

        if flt:
            # Flat search across ALL groups, capped.
            groups, shown = {}, 0
            lower = self._lower_names()
            for i, (name, group, _l) in enumerate(self.source.entries):
                if flt not in lower[i]:
                    continue
                parent = ""
                if group:
                    if group not in groups:
                        groups[group] = self.tree.insert("", "end", text=group, open=True)
                    parent = groups[group]
                disp = name[len(group) + 1:] if group and name.startswith(group + "/") else name
                self._index[self.tree.insert(parent, "end", text=disp, values=("",))] = i
                shown += 1
                if shown >= self.FILTER_CAP:
                    break
            self.count_lbl.config(text=f"{shown} match{'es' if shown != 1 else ''}"
                                  + (" (capped)" if shown >= self.FILTER_CAP else ""))
            return

        # No filter: one collapsed node per group (so EVERY group is visible),
        # children loaded lazily on expand. Avoids the old global row cap that
        # only ever filled with the first (alphabetically-first) group.
        from collections import defaultdict
        gmap = defaultdict(list)
        ungrouped = []
        for i, (name, group, _l) in enumerate(self.source.entries):
            (gmap[group] if group else ungrouped).append(i)
        for group in sorted(gmap):
            gid = self.tree.insert("", "end", text=f"{group}  ({len(gmap[group])})", open=False)
            self._group_indices[gid] = gmap[group]
            self.tree.insert(gid, "end", text="…")   # placeholder -> shows expand arrow
        for i in ungrouped:
            self._index[self.tree.insert("", "end", text=self.source.entries[i][0], values=("",))] = i
        self.count_lbl.config(text=f"{n} entries in {len(gmap)} group(s)")

    def _on_group_open(self, _evt):
        gid = self.tree.focus()
        if gid in self._group_loaded or gid not in self._group_indices:
            return
        self._group_loaded.add(gid)
        self.tree.delete(*self.tree.get_children(gid))   # drop placeholder
        idxs = self._group_indices[gid]
        for i in idxs[:self.GROUP_CAP]:
            name, group, _l = self.source.entries[i]
            disp = name[len(group) + 1:] if group and name.startswith(group + "/") else name
            self._index[self.tree.insert(gid, "end", text=disp, values=("",))] = i
        if len(idxs) > self.GROUP_CAP:
            self.tree.insert(gid, "end", text=f"… (+{len(idxs) - self.GROUP_CAP} more — use Filter)")

    def _guard_map_edits(self, action):
        """Ask before discarding unsaved edits in the embedded map editor (the map itself
        or its search-item / encounter sidecars). True = OK to proceed."""
        panel = getattr(self, "_map_panel", None)
        if panel is None:
            return True
        try:
            return panel.confirm_discard(action)
        except tk.TclError:          # panel widgets already gone -- nothing to protect
            return True

    def _on_close(self):
        if self._guard_map_edits("close the toolkit"):
            self.root.destroy()

    def _on_select(self, _evt):
        if getattr(self, "_suppress_select", False):
            return
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid not in self._index:
            return  # a group node
        if iid != getattr(self, "_cur_iid", None) and not self._guard_map_edits("open another file"):
            # stay on the edited map: put the tree highlight back without re-loading it
            prev = getattr(self, "_cur_iid", None)
            self._suppress_select = True
            try:
                if prev is not None and self.tree.exists(prev):
                    self.tree.selection_set(prev); self.tree.see(prev)
                else:
                    self.tree.selection_remove(iid)
            finally:
                self.root.after_idle(lambda: setattr(self, "_suppress_select", False))
            return
        self._cur_iid = iid
        name, group, loader = self.source.entries[self._index[iid]]
        try:
            data = loader()
        except Exception as e:
            messagebox.showerror("Read failed", str(e))
            return
        self.cur_name, self.cur_data = name, data
        self.tree.set(iid, "size", human(len(data)))
        self._show(name, data)

    # ---- viewer dispatch ------------------------------------------------- #
    def _clear_content(self):
        if getattr(self, "_anim_after", None):     # stop a running flipbook animation
            self.root.after_cancel(self._anim_after)
        self._anim_after = None
        self._tex_playing = False
        self._model_playing = False
        self._tex_frames = None
        mv = getattr(self, "_map_view", None)
        for w in self.content.winfo_children():
            if mv is not None and w is mv["nb"]:
                # Kept for the next map (see _view_rf4m) and deliberately left MAPPED here:
                # un-mapping and re-mapping it re-paints every themed widget of the editor
                # (~0.1-0.9 s on Windows) on each map-to-map click. _show hides it once it
                # knows the new view is not a map.
                self._map_view_hide = True
                continue
            w.destroy()
        self._map_panel = None      # not shown: never guard/export a hidden panel
        self.cur_image = None
        self._pil = None
        self.export_btn.config(state="disabled")
        self._export_kind = None

    def _show(self, name: str, data: bytes):
        self._clear_content()
        # The shown bytes ARE the working copy: every editing panel reads/writes
        # self.cur_data, so keep it in sync whatever path called us (file browser,
        # a panel re-rendering after an edit, or a programmatic open).
        self.cur_name, self.cur_data = name, data
        ft = ident.identify(data[:0x4000], filename=name)
        self.header.config(text=f"{name}    —    {ft.fmt}: {ft.desc}    ({human(len(data))})")
        try:
            handler = {
                "texture": self._view_texture,
                "text": self._view_text,
                "bplist": self._view_bplist,
                "rf4m": self._view_rf4m,
                "aibn": self._view_aibn,
                "strings": self._view_strings,
                "res": self._view_res, "model": self._view_res, "bfres": self._view_res,
                "bfsha": self._view_res, "psb": self._view_res, "bntx": self._view_res,
                "gen": self._view_gen,
                "emf": self._view_emf,
                "emdeb": self._view_emf,
                "param": self._view_param,
                "search_items": self._view_search_items,
                "route": self._view_route,
                "route_result": self._view_route_result,
            }.get(ft.fmt)
            # standard raster images (png/jpg/gif/bmp/tiff/webp/dds/ico) -> Pillow viewer
            if ft.fmt in IMAGE_FMTS:
                handler = self._view_image
            # route TEXT / NLCL by magic regardless of extension
            if data[:4] == b"TEXT":
                handler = self._view_textdb
            elif data[:4] == b"NLCL":
                handler = {"gen": self._view_gen,
                           "search_items": self._view_search_items}.get(ft.fmt, self._view_param)
            # filename-family overrides (win over magic: gift/curve carry NLCL magic but need
            # bespoke views; as_atk has no magic and would otherwise fall to hex)
            base = pathlib.Path(name).name.lower()
            if base.startswith("as_atk_"):
                handler = self._view_asatk
            elif base.startswith("rf3presentnpc"):
                handler = self._view_gifts
            elif base.startswith("rf3presentcategory"):
                handler = self._view_gift_categories
            elif base.startswith("rf3monsterpresent"):
                handler = self._view_montame
            elif base.startswith("rf3paramskillexp"):
                handler = self._view_skillcurve
            elif base == "rf3schedule.bin":
                handler = self._view_schedule
            elif base == "rf3npcparam.bin":
                handler = self._view_monster
            elif base == "rf3cropparam.bin":
                handler = self._view_crop
            elif base == "rf3itemstrengthening.bin":
                handler = self._view_strengthening
            elif base == "rf3txtquest_split3_1.bin":
                handler = self._view_quest
            # last-resort image fallback: a known image extension Pillow can open
            # (covers TGA/BMP/ICO and anything `ident` didn't sniff by magic).
            ext = pathlib.Path(name).suffix.lower()
            if handler is None and HAS_PIL and ext in IMAGE_EXTS:
                handler = self._view_image
                self.header.config(text=f"{name}    —    {ext.lstrip('.')}: image "
                                        f"(by extension)    ({human(len(data))})")
            if handler:
                handler(name, data)
            else:
                self._view_hex(name, data)
            self._hide_map_view_if_unused()
        except Exception as e:
            self._clear_content()   # drop any partial widgets the failed handler packed
            self._view_hex(name, data, error=str(e))
            self._hide_map_view_if_unused()

    def _hide_map_view_if_unused(self):
        """After a view is built: hide the kept map editor unless that view used it."""
        mv = getattr(self, "_map_view", None)
        if mv is None or not getattr(self, "_map_view_hide", False):
            return
        self._map_view_hide = False
        try:
            mv["nb"].pack_forget()
            mv["panel"].suspend()           # stop its background texture decode
        except tk.TclError:
            pass

    # ---- per-type views -------------------------------------------------- #
    def _view_texture(self, name, data):
        if not HAS_PIL:
            self._view_hex(name, data, error="Pillow not installed (pip install Pillow)")
            return
        info = texture.parse(data)
        nframes = info.get("frames", 1)
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        head = f"{info['fmt_name']}  {info['width']}x{info['height']}  (code 0x{info['fmt_code']:X})"
        if nframes > 1:
            head += f"   flipbook: {nframes} frames"
        ttk.Label(bar, text=head).pack(side="left", padx=6)
        for z, lbl in ((0.5, "½×"), (1, "1×"), (2, "2×"), (4, "4×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z)).pack(side="left")
        ttk.Button(bar, text="Replace from PNG…",
                   command=lambda: self._replace_texture_png(name)).pack(side="left", padx=(10, 0))
        try:
            if nframes > 1:
                frames = [im.convert("RGBA") for im in texture.decode_frames(data)]
            else:
                img1 = texture.decode_to_image(data)
                frames = [img1.convert("RGBA")] if img1 is not None else []
        except texture.TextureError as e:
            self._view_hex(name, data, error=str(e)); return
        if not frames:
            self._view_hex(name, data, error="unsupported texture format"); return
        self._pil = frames[0]
        self._img_canvas = self._make_image_canvas()
        self._set_zoom(2.0 if max(frames[0].size) <= 64 else 1.0)  # tiny flipbook cells: zoom in
        self._export_kind = "png"
        self.export_btn.config(state="normal")
        if len(frames) > 1:
            # Flipbook controls: prev/next, play/stop (~8 fps default; in-game
            # speed is per-MOBJ-record f9, unknown here), and GIF export.
            self._tex_frames = frames
            self._tex_fi = 0
            fl = ttk.Label(bar, text=f"frame 1/{len(frames)}")

            def show(i):
                self._tex_fi = i % len(self._tex_frames)
                self._pil = self._tex_frames[self._tex_fi]
                fl.config(text=f"frame {self._tex_fi + 1}/{len(self._tex_frames)}")
                self._set_zoom(self.zoom)

            def tick():
                self._anim_after = None
                if getattr(self, "_tex_playing", False):
                    show(self._tex_fi + 1)
                    self._anim_after = self.root.after(120, tick)

            def toggle():
                self._tex_playing = not getattr(self, "_tex_playing", False)
                pb.config(text="Stop" if self._tex_playing else "Play")
                if self._tex_playing and self._anim_after is None:
                    tick()

            ttk.Button(bar, text="◀", width=3, command=lambda: show(self._tex_fi - 1)).pack(side="left", padx=(10, 0))
            fl.pack(side="left", padx=4)
            ttk.Button(bar, text="▶", width=3, command=lambda: show(self._tex_fi + 1)).pack(side="left")
            pb = ttk.Button(bar, text="Play", width=5, command=toggle)
            pb.pack(side="left", padx=4)
            ttk.Button(bar, text="GIF…", width=5,
                       command=lambda: self._export_texture_gif(name)).pack(side="left")
            self._tex_playing = False
            self._anim_after = None

    def _replace_texture_png(self, name):
        """Re-skin the shown .texture from a PNG of the same size, re-encoded in the
        template frame's own format (BC7/BC3/BC1 at the same size, raw kept -- see
        texture.encode_into). For a flipbook only the frame being shown is replaced.
        Updates the working copy (cur_data) like the other editors; Extract writes it."""
        if self.cur_data is None:
            return
        f = filedialog.askopenfilename(title="Replace texture pixels from PNG…",
                                       filetypes=[("PNG image", "*.png"), ("All images", "*.*")])
        if not f:
            return
        frames = getattr(self, "_tex_frames", None)
        frame = getattr(self, "_tex_fi", 0) if frames and len(frames) > 1 else None
        before = len(self.cur_data)
        try:
            blob = texture.encode_into(self.cur_data, f, frame=frame)
        except Exception as e:
            messagebox.showerror("Replace failed", str(e))
            return
        self.cur_data = blob
        self._show(name, blob)
        which = f"frame {frame + 1} " if frame is not None else ""
        size = "same size, bundle patch-able" if len(blob) == before else f"was {before:,}"
        self.status.config(text=f"Replaced {which}pixels from {pathlib.Path(f).name} -> "
                                f"{len(blob):,} bytes ({size}; Extract to save the working copy)")

    def _export_texture_gif(self, name):
        """Save the current flipbook as an animated GIF (120 ms/frame, looped)."""
        frames = getattr(self, "_tex_frames", None)
        if not frames:
            return
        stem = pathlib.Path(name).stem
        f = filedialog.asksaveasfilename(defaultextension=".gif", initialfile=stem + ".gif",
                                         filetypes=[("Animated GIF", "*.gif")])
        if not f:
            return
        frames[0].save(f, save_all=True, append_images=frames[1:], duration=120,
                       loop=0, disposal=2)
        self.status.config(text=f"Exported {len(frames)}-frame GIF -> {f}")

    def _view_image(self, name, data):
        """Standard raster image (PNG/JPEG/GIF/BMP/TIFF/WebP/TGA/DDS/ICO) via Pillow,
        shown in the same zoom/pan canvas the texture viewer uses. Export View -> PNG."""
        if not HAS_PIL:
            self._view_hex(name, data, error="Pillow not installed (pip install Pillow)")
            return
        import io
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as e:  # noqa: BLE001  (Pillow raises many types)
            self._view_hex(name, data, error=f"image decode failed: {e}")
            return
        n_frames = getattr(img, "n_frames", 1)
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        info = f"{img.format or '?'}   {img.width}x{img.height}   {img.mode}"
        if n_frames > 1:
            info += f"   ({n_frames} frames -- showing #1)"
        ttk.Label(bar, text=info).pack(side="left", padx=6)
        for z, lbl in ((0.25, "¼×"), (0.5, "½×"), (1, "1×"), (2, "2×"), (4, "4×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z)).pack(side="left")
        # RGBA so alpha shows over the dark canvas and PNG export keeps transparency.
        self._pil = img.convert("RGBA")
        self._img_canvas = self._make_image_canvas()
        # fit large images to the viewport on open; small ones show 1:1.
        self._set_zoom(self._fit_zoom(img.width, img.height))
        self._export_kind = "png"
        self.export_btn.config(state="normal")

    def _fit_zoom(self, w, h):
        """Pick an initial zoom so a large image fits the content pane (never upscales)."""
        try:
            self.content.update_idletasks()
            cw = max(64, self.content.winfo_width() - 24)
            ch = max(64, self.content.winfo_height() - 48)
        except Exception:  # noqa: BLE001
            return 1.0
        if w <= cw and h <= ch:
            return 1.0
        return max(0.05, min(cw / w, ch / h))

    def _navigate_to_map(self, map_name):
        """Ctrl+click-a-warp handler from the embedded map editor: find {map_name}.rf4m in the
        current source, load it, and re-render (keeping cur_name/cur_data in sync)."""
        if not self.source:
            return
        target = f"{map_name}.rf4m".lower()
        for name, _group, loader in self.source.entries:
            base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if base == target:
                try:
                    data = loader()
                except Exception as e:  # noqa: BLE001
                    self.status.config(text=f"navigate failed: {e}"); return
                self.cur_name, self.cur_data = name, data
                self._show(name, data)
                return
        self.status.config(text=f"{map_name}.rf4m not found in this source")

    def _open_scene_editor(self, bank_index, entry_pc, pc=None):
        """Map-editor NPC-spawn marker click -> open the Cutscene Editor focused on the exact
        EventSpawnNpc line (bank = the map's event bank, scene = entry_pc, statement = pc)."""
        win = tk.Toplevel(self.root)
        win.title(f"Cutscene Editor — event bank {bank_index} @0x{(entry_pc or 0):04x}")
        win.geometry("1200x820")
        import cutscene_editor
        cutscene_editor.CutsceneExplorer(
            win, reader=(self.source.read_named if self.source else None),
            status_fn=lambda s: self.status.config(text=s),
            focus_bank=bank_index, focus_entry=entry_pc, focus_pc=pc)

    def _drop_map_view(self):
        mv = getattr(self, "_map_view", None)
        self._map_view = None
        if mv is not None:
            try:
                mv["panel"].suspend()
                mv["nb"].destroy()
            except tk.TclError:
                pass

    def _map_notebook(self, m, name):
        """The map notebook with its 'Map (edit)' tab. Built ONCE and reused for every map:
        building the editor's ~300 widgets took ~0.3 s per click, and each rebuild left the
        previous panel's texture-decode thread running and threw its texture cache away.
        Now switching maps is set_map() on the same panel (stale decodes are cancelled, and
        revisiting a map reuses its decoded ground). Returns (notebook, panel | None)."""
        mv = getattr(self, "_map_view", None)
        if mv is not None:
            try:
                alive = bool(mv["nb"].winfo_exists())
            except tk.TclError:
                alive = False
            if not alive:
                self._map_view = mv = None
        if mv is not None:
            nb, panel = mv["nb"], mv["panel"]
            for f in mv["extra"]:
                try:
                    nb.forget(f); f.destroy()
                except tk.TclError:
                    pass
            mv["extra"] = []
            self._map_view_hide = False
            panel.tex_reader = self.source.read_named if self.source else None
            panel.set_map(m, name)
            if not nb.winfo_ismapped() or nb.winfo_manager() != "pack":
                nb.pack(fill="both", expand=True)
            nb.select(mv["mapframe"])
            return nb, panel
        nb = ttk.Notebook(self.content); nb.pack(fill="both", expand=True)
        try:
            import map_editor
            mapframe = ttk.Frame(nb); nb.add(mapframe, text="Map (edit)")
            panel = map_editor.MapEditorPanel(
                mapframe, m, name,
                status_fn=lambda s_: self.status.config(text=s_),
                on_change=lambda b: setattr(self, "cur_data", b),
                tex_reader=self.source.read_named if self.source else None,
                on_navigate=self._navigate_to_map,   # Ctrl+click a warp -> open that map
                on_open_scene=self._open_scene_editor)  # click NPC-spawn marker -> its script line
            nb.select(mapframe)              # open the map editor first
        except Exception as e:
            self.status.config(text=f"map editor unavailable: {e}")
            return nb, None                  # not cached: the next map retries the build
        self._map_view = {"nb": nb, "panel": panel, "mapframe": mapframe, "extra": []}
        nb.bind("<<NotebookTabChanged>>", self._on_map_tab_changed, add="+")
        return nb, panel

    def _on_map_tab_changed(self, _e=None):
        """Fill a lazily-built tab (the Hex dump) the first time it is shown."""
        mv = getattr(self, "_map_view", None)
        if mv is None:
            return
        try:
            cur = mv["nb"].nametowidget(mv["nb"].select())
        except (tk.TclError, KeyError):
            return
        fill = mv.get("lazy", {}).pop(str(cur), None)
        if fill is not None:
            fill()

    def _view_rf4m(self, name, data):
        m = rf4m.Rf4mMap.parse(data)
        self._rf4m = m                       # editable map state (Map tab + MOBJ tab edit this)
        self._map_panel = None               # reset: a failed embed must not export a stale panel
        nb, panel = self._map_notebook(m, name)
        self._map_panel = panel
        mv = getattr(self, "_map_view", None)
        before = set(nb.tabs())
        # cutscene/event tab: this map's scenes from rf3.mc tail[mapId]
        try:
            self._build_events_tab(nb, name)
        except Exception as e:
            self.status.config(text=f"events tab unavailable: {e}")
        # summary tab
        txt = self._make_text_tab(nb, "Chunks")
        txt.insert("end", f"{m.summary()}\n\n")
        for c in m.chunks:
            txt.insert("end", f"  {c.tag.decode('latin1'):5} {len(c.payload):>8} B   "
                              f"{rf4m.CHUNK_DESC.get(c.tag,'')}\n")
        grid = m.attr_grid()
        if grid:
            txt.insert("end", f"\nATTR grid: {grid[0]}x{grid[1]}\n")
        mapj = m.mapj_records()
        if mapj:
            txt.insert("end", f"MAPJ records: {len(mapj)}  (first: {mapj[0]})\n")
        txt.config(state="disabled")
        # read-only hex tab (a peer of Chunks); monospace so the offset / hex / ASCII columns
        # line up. Filled only when first opened: dumping a whole map into a Text widget cost
        # ~0.2 s on every map click for a tab most people never look at.
        hx = self._make_text_tab(nb, "Hex", mono=True)

        def fill_hex(hx=hx, data=data):
            hx.config(state="normal")
            hx.delete("1.0", "end")
            hx.insert("end", hexdump(data, limit=len(data)))
            hx.config(state="disabled")
        if mv is not None:
            mv["extra"] = [nb.nametowidget(t) for t in nb.tabs() if t not in before]
            mv.setdefault("lazy", {})[str(hx.master.master)] = fill_hex
        else:
            fill_hex()
        # Export = WYSIWYG map view (current zoom + enabled overlays) when the
        # embedded editor is up; the ATTR-heatmap PNG (set above) stays as the
        # fallback when it isn't.
        if self._map_panel is not None:
            self._export_kind = "map_png"
            self.export_btn.config(state="normal")

    @staticmethod
    def _season_bases(stem):
        """Candidate base map names for a seasonal / tiled .rf4m variant."""
        import re
        outs = []
        up = stem.upper()
        for suf in ("_SPRING", "_SUMMER", "_AUTUMN", "_FALL", "_WINTER"):
            if up.endswith(suf):
                outs.append(stem[: -len(suf)])
        mt = re.match(r"(.+?)_\d{3,4}$", stem)     # strip a trailing tile index (MAP_X_0000)
        if mt:
            outs.append(mt.group(1))
        return outs

    def _events_textarc(self):
        """Lazily load + cache the rf3mc.<locale> dialogue archive for scene previews."""
        if getattr(self, "_ev_textarc_done", False):
            return self._ev_textarc
        self._ev_textarc_done = True
        self._ev_textarc = None
        data = self.source.read_named("rf3mc.eng") if self.source else None
        if data:
            try:
                self._ev_textarc = textdb.TextArchive.parse(data)
            except Exception:
                self._ev_textarc = None
        return self._ev_textarc

    def _build_events_tab(self, nb, name):
        """'Events' tab: the cutscene/event scenes tied to THIS map. rf3.mc's 872 tail
        banks are 1:1 with the 872 rooms, so a map's events live in tail[mapId]. Lists
        those scenes with dialogue previews; opens them in the full Cutscene Editor."""
        import map_editor
        frame = ttk.Frame(nb)
        nb.add(frame, text="Events")
        info = ttk.Label(frame, anchor="w", wraplength=940, justify="left")
        info.pack(fill="x", padx=6, pady=(6, 2))

        stem = pathlib.Path(name).stem
        rooms = map_editor.load_rooms()                # {name: (mapId, resourceId)}
        mid, resolved = None, stem
        for cand in (stem, *self._season_bases(stem)):
            if cand in rooms:
                mid, resolved = rooms[cand][0], cand
                break
        if mid is None:
            info.config(text=f"Couldn't map '{stem}' to a room id (rf4s_rooms.csv). "
                             f"Cutscene events are keyed per-map; this file isn't in the room table.")
            return

        raw = self.source.read_named("rf3.mc") if self.source else None
        if not raw:
            info.config(text=f"{resolved} = mapId {mid}. Its cutscene events live in rf3.mc "
                             f"(bundlePatch1), which isn't in the current source. Open the "
                             f"Manifest (or add rf3.mc) to browse them here.")
            return
        try:
            container = script.Container(raw)
        except Exception as e:
            info.config(text=f"rf3.mc failed to parse: {e}")
            return

        bank_index = container.n_primary + mid
        if not (0 <= bank_index < len(container.banks)):
            info.config(text=f"{resolved}: mapId {mid} has no matching event bank.")
            return
        bank = container.banks[bank_index]
        scenes = script.disassemble_bank(bank)
        ta = self._events_textarc()

        def dlg(i):
            try:
                return ta.text(i) if ta else None
            except Exception:
                return None

        # Build a display row per scene; drop empty (0-stmt) decode artifacts and sort so
        # the real cutscenes (most dialogue, then most statements) surface at the top.
        entries = []                                # (nline, nstmt, entry_pc, ok, preview)
        for sc in scenes:
            nstmt = len(sc.stmts)
            if nstmt == 0:
                continue
            nline = 0
            preview = ""
            for st in sc.stmts.values():
                if st.mnem == "DIALOG":
                    nline += 1
                    if not preview:
                        t = dlg(st.dialog_id)
                        preview = (t.splitlines()[0][:46] if t else f"#{st.dialog_id}")
            entries.append((nline, nstmt, sc.entry_pc, sc.ok, preview))
        entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
        ndlg = sum(e[0] for e in entries)

        info.config(text=f"{resolved}  (mapId {mid})  →  event bank {bank_index}:  "
                         f"{len(entries)} scenes, {ndlg} dialogue lines"
                         + ("  —  double-click a scene to edit it (biggest first)."
                            if entries else "  —  no cutscene events are registered for this map "
                                            "(New scene on this map… mints the first one)."))

        lf = ttk.Frame(frame)
        lf.pack(fill="both", expand=True, padx=6, pady=4)
        sb = ttk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        lb = tk.Listbox(lf, font=("Consolas", 9), yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.config(command=lb.yview)
        row_entry_pc = []
        for nline, nstmt, epc, ok, preview in entries:
            flag = "" if ok else " [partial]"
            lb.insert("end", f"@0x{epc:04x}  {nstmt:>3} stmts  {nline:>2} lines{flag}  {preview}")
            row_entry_pc.append(epc)

        def _editor_window():
            win = tk.Toplevel(self.root)
            win.title(f"Cutscene Editor — {resolved} (event bank {bank_index})")
            win.geometry("1200x820")
            return win

        def open_editor(_e=None):
            sel = lb.curselection()
            entry_pc = row_entry_pc[sel[0]] if sel else None
            win = _editor_window()
            import cutscene_editor
            cutscene_editor.CutsceneExplorer(
                win, reader=(self.source.read_named if self.source else None),
                status_fn=lambda s: self.status.config(text=s),
                focus_bank=bank_index, focus_entry=entry_pc)

        def new_scene():
            """'New scene on this map…': open the Cutscene Editor on this map's event (tail)
            bank and go straight into its New-scene dialog with the map-enter type preselected
            (MapEnterScene, type 7 -- taken from the entry-type catalogue when it names it).
            The scene lands in that editor's in-memory rf3.mc: its Save menu / Install
            write it (this tab keeps listing the shipped file)."""
            import cutscene_editor
            win = _editor_window()
            ex = cutscene_editor.CutsceneExplorer(
                win, reader=(self.source.read_named if self.source else None),
                status_fn=lambda s: self.status.config(text=s),
                focus_bank=bank_index)
            res = ex.open_new_scene_dialog(bank_index,
                                           default_type=cutscene_editor.map_enter_type())
            if res is not None:
                self.status.config(
                    text=f"new scene @0x{res[0]:04x} minted in event bank {bank_index} (in the "
                         f"editor's rf3.mc — use its Save menu or Install; this tab "
                         f"lists the shipped file)")
            return res

        lb.bind("<Double-Button-1>", open_editor)
        btn = ttk.Frame(frame)
        btn.pack(fill="x", padx=6, pady=(0, 6))
        b = ttk.Button(btn, text="Open in Cutscene Editor →", command=open_editor)
        b.pack(side="left")
        nsb = ttk.Button(btn, text="New scene on this map…", command=new_scene)
        nsb.pack(side="left", padx=(6, 0))
        ttk.Label(btn, foreground="#888",
                  text="  New scene… = mint a map-enter scene (MapEnterScene, type 7) in this "
                       "map's event bank via the editor's New-scene dialog").pack(side="left")
        ttk.Label(btn, text="  (no dialogue previews until rf3mc.<locale> is in the source)"
                  if ta is None else "").pack(side="left")
        if not entries:
            b.config(state="disabled")
        self._events_new_scene = new_scene      # headless-test hook (the last built Events tab)

    def _view_textdb(self, name, data):
        arc = textdb.TextArchive.parse(data)
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"{len(arc):,} strings").pack(side="left", padx=6)
        ttk.Label(bar, text="Search:").pack(side="left")
        sv = tk.StringVar()
        ttk.Entry(bar, textvariable=sv, width=30).pack(side="left", padx=2)
        tv = ttk.Treeview(self.content, columns=("idx", "text"), show="headings")
        tv.heading("idx", text="#"); tv.column("idx", width=70, anchor="e", stretch=False)
        tv.heading("text", text="String"); tv.column("text", width=900)
        vs = ttk.Scrollbar(self.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        texts = arc.texts()

        def repop(*_):
            tv.delete(*tv.get_children())
            q = sv.get().lower()
            n = 0
            for i, s in enumerate(texts):
                if q and q not in s.lower():
                    continue
                tv.insert("", "end", values=(i, s.replace("\n", "⏎")))
                n += 1
                if n >= MAX_TABLE_ROWS:
                    tv.insert("", "end", values=("…", f"(showing first {MAX_TABLE_ROWS}; refine search)"))
                    break
        sv.trace_add("write", repop)
        repop()
        self._export_kind = "textjson"; self._export_arc = arc
        self.export_btn.config(state="normal")

    # plain TEXT routed above; this handles `text` fmt files that are NOT TEXT magic
    def _view_text(self, name, data):
        if data[:4] == b"TEXT":
            return self._view_textdb(name, data)
        try:
            s = data.decode("utf-8")
        except UnicodeDecodeError:
            s = data.decode("latin1")
        txt = self._make_text_tab(None, None, mono=True)
        txt.insert("end", s)
        txt.config(state="disabled")

    def _view_bplist(self, name, data):
        root_obj = bplist.loads(data, lazy_data=True)
        tv = ttk.Treeview(self.content, columns=("val",), show="tree headings")
        tv.heading("#0", text="Key / Index"); tv.heading("val", text="Value")
        tv.column("val", width=700)
        vs = ttk.Scrollbar(self.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        self._export_kind = "plistjson"; self._export_data = data
        self.export_btn.config(state="normal")

        # Manifest.plist: render each bundle directly by name with its files listed
        # under it (lazily on expand), instead of the raw bundles[i].{bundleName,files}.
        bundles = root_obj.get("bundles") if isinstance(root_obj, dict) else None
        if isinstance(bundles, list) and bundles and all(
                isinstance(b, dict) and "bundleName" in b for b in bundles):
            self._bplist_files = {}
            for b in bundles:
                files = b.get("files", {})
                nfiles = len(files) if isinstance(files, dict) else 0
                node = tv.insert("", "end", text=str(b.get("bundleName")),
                                 values=(f"{nfiles} files",), open=False)
                if nfiles:
                    self._bplist_files[node] = files
                    tv.insert(node, "end", text="…")     # placeholder -> expand arrow
            tv.bind("<<TreeviewOpen>>", lambda _e: self._bplist_expand_bundle(tv))
            return

        def add(parent, key, val):
            if isinstance(val, dict):
                node = tv.insert(parent, "end", text=f"{key}", values=(f"{{dict: {len(val)}}}",), open=False)
                for k, v in list(val.items())[:2000]:
                    add(node, str(k), v)
            elif isinstance(val, list):
                node = tv.insert(parent, "end", text=f"{key}", values=(f"[list: {len(val)}]",), open=False)
                for i, v in enumerate(val[:2000]):
                    add(node, str(i), v)
            elif isinstance(val, bplist.DataRef):
                tv.insert(parent, "end", text=key, values=(f"<data {val.size} B @0x{val.offset:x}>",))
            else:
                sval = repr(val)
                tv.insert(parent, "end", text=key, values=(sval[:300],))
        add("", "(root)", root_obj)
        for c in tv.get_children():
            tv.item(c, open=True)

    def _bplist_expand_bundle(self, tv):
        nid = tv.focus()
        files = self._bplist_files.pop(nid, None)
        if files is None:
            return
        tv.delete(*tv.get_children(nid))     # drop placeholder
        for fk, fv in files.items():
            if isinstance(fv, dict):
                tv.insert(nid, "end", text=str(fk),
                          values=(f"size {fv.get('size')}  offset {fv.get('offset')}",))
            else:
                tv.insert(nid, "end", text=str(fk), values=(repr(fv)[:200],))

    def _view_aibn(self, name, data):
        toks = aibn.load_tokens(data)
        dis = aibn.disassemble(toks, annotate=True)
        txt = self._make_text_tab(None, None, mono=True)
        c = aibn.stats(toks)
        txt.insert("end", f"# {name}: {len(toks)} tokens, {sum(c.values())} statements"
                          f"  (sub N: / N: labels, if (...) {{ }} blocks, Action(args); trailing # = verified operand meanings;"
                          f" rf4mod ai ops <op> for details; `rf4mod ai asm` rebuilds the file from this text)\n\n")
        txt.insert("end", dis)
        txt.config(state="disabled")
        self._export_kind = "disasm"; self._export_text = dis
        self.export_btn.config(state="normal")

    def _view_emf(self, name, data):
        """em.bin / emdeb.bin -- the Event Manager: the game's trigger rules (what gates
        a marriage, a date, a shop, a sub-event). The exe only runs the VM.

        The decoder/editor for these already lives in the Cutscene editor's **Event Manager**
        window -- entry list, decoded conditions + actions, the rf3.mc scenes that use each
        entry, and byte-safe in-place edits -- so this panel opens that rather than
        duplicating it, and shows the raw container underneath.
        """
        bar = ttk.Frame(self.content); bar.pack(fill="x", pady=3)
        ttk.Button(bar, text="Open Event Manager\u2026", command=self.cmd_event_manager
                   ).pack(side="left", padx=6)
        ttk.Label(bar, text="272 trigger entries: decoded conditions + actions, "
                            "rf3.mc scene cross-refs, in-place editing "
                            "(CLI: rf4mod.py em list / show / set)."
                  ).pack(side="left")
        self._view_hex(name, data)

    def _view_strings(self, name, data):
        try:
            d = strings_file.parse(data.decode("utf-8"))
        except Exception as e:
            self._view_hex(name, data, error=str(e)); return
        tv = ttk.Treeview(self.content, columns=("key", "val"), show="headings")
        tv.heading("key", text="Key"); tv.column("key", width=260)
        tv.heading("val", text="Value"); tv.column("val", width=720)
        vs = ttk.Scrollbar(self.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        for k, v in d.items():
            tv.insert("", "end", values=(k, v.replace("\n", "⏎")))

    def _view_res(self, name, data):
        # A .model / .bntx embeds a Nintendo BNTX texture block (the map's over-model
        # scenery atlases, named MOBJ_<map>_NN). Offer a texture browser alongside the
        # raw container structure. BNTX here is LINEAR BC (no Tegra swizzle), so every
        # texture decodes directly. (Falls back to structure-only without Pillow.)
        if data[:4] == b"PSB\x00" and HAS_PIL and self._view_psb(name, data):
            return
        from rf4s_modkit import model as _model
        is_mesh = _model.is_mesh(data)
        if HAS_PIL and (is_mesh or (data.find(b"BNTX") >= 0 and texture.bntx_list(data))):
            nb = ttk.Notebook(self.content); nb.pack(fill="both", expand=True)
            if is_mesh:
                self._build_model_tab(nb, name, data)
            if data.find(b"BNTX") >= 0 and texture.bntx_list(data):
                self._build_bntx_browser(nb, name, data)
            stxt = self._make_text_tab(nb, "Structure", mono=True)
            stxt.insert("end", res_container.summary(data)); stxt.config(state="disabled")
            nb.select(0)
            return
        txt = self._make_text_tab(None, None, mono=True)
        txt.insert("end", res_container.summary(data))
        if data[:4] == b"RES\x00" and not is_mesh:
            txt.insert("end", "\n\n(a UI screen layout: .model files for menus carry no mesh)")
        txt.config(state="disabled")

    def _view_psb(self, name, data):
        """E-mote portrait (.psbData / .emtbytes): the part atlas on a zoomable canvas
        (Export = PNG) with the PSB summary.  Repaint via `rf4mod psb replace-texture`.
        Returns False (caller falls back to the structure view) if it cannot decode."""
        from rf4s_modkit import psb as _psb
        try:
            ps = _psb.PSB(data)
            texs = ps.textures()
            img = _psb.decode_texture(ps, texs[0]) if texs else None
        except Exception:  # noqa: BLE001
            return False
        if img is None:
            return False
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        t = texs[0]
        ttk.Label(bar, text=f"E-mote atlas '{t['source']}'  {t['type']} {t['width']}x{t['height']}"
                            f"  {len(t['icons'])} parts").pack(side="left", padx=6)
        for z, lbl in ((0.25, "¼×"), (0.5, "½×"), (1, "1×"), (2, "2×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z)).pack(side="left")
        info = tk.Text(self.content, height=9, wrap="word", font=("Consolas", 9))
        info.insert("end", _psb.summary(ps, pathlib.PurePosixPath(name).name)); info.config(state="disabled")
        info.pack(fill="x")
        self._pil = img
        self._img_canvas = self._make_image_canvas()
        self._set_zoom(0.5)
        self._export_kind = "png"
        self.export_btn.config(state="normal")
        return True

    def _build_model_tab(self, nb, name, data):
        """'Model' tab: a textured preview of the meshes (front / back / side / top), the
        shape / material summary, and Export OBJ (geometry + MTL + texture PNGs)."""
        from rf4s_modkit import model as _model
        try:
            m = _model.parse(data)
        except Exception as e:  # noqa: BLE001
            f = ttk.Frame(nb); nb.add(f, text="Model")
            ttk.Label(f, text=f"cannot read the mesh: {e}").pack(anchor="w", padx=6, pady=6)
            return
        frame = ttk.Frame(nb); nb.add(frame, text="Model")
        bar = ttk.Frame(frame); bar.pack(fill="x")
        stem = pathlib.PurePosixPath(name).stem
        view = tk.StringVar(value="top" if stem.upper().startswith("MAP_") else "front")
        ttk.Label(bar, text="view").pack(side="left", padx=(6, 2))
        vc = ttk.Combobox(bar, textvariable=view, values=list(_model.VIEWS), width=7, state="readonly")
        vc.pack(side="left")
        info = ttk.Label(bar, text="")
        info.pack(side="left", padx=8)

        def export():
            d = filedialog.askdirectory(title="Export OBJ + MTL + textures into")
            if not d:
                return
            try:
                written = _model.export_obj(m, d, stem)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Export OBJ", str(e)); return
            self.status.config(text=f"exported {stem}.obj + {len(written) - 1} file(s) to {d}")
        ttk.Button(bar, text="Export OBJ…", command=export).pack(side="right", padx=4)
        body = ttk.Frame(frame); body.pack(fill="both", expand=True)
        txt = tk.Text(body, width=58, font=("Consolas", 9), wrap="none")
        txt.pack(side="left", fill="y")
        lines = [_model.summary(m), "", "materials:"]
        for mt in m.materials:
            ud = _model.user_data_text(mt)
            lines.append(f"  {mt.name}: {', '.join(mt.textures) or '(no texture)'}" + (f"  [{ud}]" if ud else ""))
        txt.insert("end", "\n".join(lines)); txt.config(state="disabled")
        cv = tk.Canvas(body, bg="#202024", highlightthickness=0)
        cv.pack(side="left", fill="both", expand=True)
        state = {"photo": None, "frame": 0.0, "textures": {}}
        anim = self._model_material_anim(name, m)
        if anim is not None:
            # the .bfmat next to the model scrolls its effect layers (ANIM_DUNG_* light shafts
            # and water): play it live at the game's 60 ticks/s, or write one loop as a GIF
            fl = ttk.Label(bar, text="", width=13)
            pb = ttk.Button(bar, text="Play", width=5)
            ttk.Label(bar, text=anim.file_name or f"{name.rsplit('/', 1)[-1].rsplit('.', 1)[0]}.bfmat").pack(side="left", padx=(8, 2))
            pb.pack(side="left")
            fl.pack(side="left", padx=4)
            ttk.Button(bar, text="GIF…", width=5, command=lambda: self._export_model_gif(m, anim, view.get(), stem)
                       ).pack(side="left")
            self._model_playing = False
            tick_ms = 50

            def tick():
                self._anim_after = None
                if not self._model_playing or not cv.winfo_exists():
                    return
                state["frame"] = (state["frame"] + 60 * tick_ms / 1000.0) % max(1, anim.frame_count)
                draw()
                self._anim_after = self.root.after(tick_ms, tick)

            def toggle():
                self._model_playing = not self._model_playing
                pb.config(text="Stop" if self._model_playing else "Play")
                if self._model_playing and getattr(self, "_anim_after", None) is None:
                    tick()
            pb.config(command=toggle)
        else:
            fl = None
        skel_bar = self._model_skel_controls(frame, name, m, state, view, lambda: draw())

        def draw(_e=None):
            from PIL import ImageTk
            if not cv.winfo_exists():
                return                         # another file was opened meanwhile
            size = max(160, min(cv.winfo_width(), cv.winfo_height()) - 8) if cv.winfo_width() > 1 else 480
            try:
                sk = state.get("skel")
                if sk is not None:             # skeletal animation selected: pose + fixed box
                    from rf4s_modkit import skelanim as _sk
                    m.pose = _sk.pose_bones(m, sk, state["sframe"])
                    box = state["boxes"].get(view.get())
                    if box is None:
                        box = state["boxes"][view.get()] = self._skel_box(m, sk, view.get())
                        m.pose = _sk.pose_bones(m, sk, state["sframe"])
                else:
                    m.pose, box = None, None
                im = _model.render(m, view.get(), size, textures=state["textures"], anim=anim,
                                   frame=state["frame"], box=box)
            except Exception as e:  # noqa: BLE001
                info.config(text=f"render failed: {e}"); return
            finally:
                m.pose = None
            if skel_bar is not None:
                skel_bar(state)
            state["photo"] = ImageTk.PhotoImage(im)
            cv.delete("all")
            cv.create_image(4, 4, anchor="nw", image=state["photo"])
            self._pil = im
            self._export_kind = "png"
            self.export_btn.config(state="normal")
            if fl is not None:
                fl.config(text=f"frame {int(state['frame']):3}/{anim.frame_count}")
            info.config(text=f"{sum(len(s.indices) // 3 for s in m.shapes)} triangles · "
                             f"{len(m.bones)} bones · {view.get()} view")
        vc.bind("<<ComboboxSelected>>", draw)
        self.root.after_idle(draw)

    def _model_skel_controls(self, frame, name, m, state, view, redraw):
        """A 'motion' row under the Model tab listing the .bfskl skeletal animations that
        drive this model (skelanim.anim_candidates) with Play / GIF…. Returns a callback that
        refreshes the frame label after each draw, or None when the model has none."""
        from rf4s_modkit import skelanim as _sk
        src = getattr(self, "source", None)
        if src is None or not m.bones:
            return None
        stem = pathlib.PurePosixPath(name).stem
        names = _sk.anim_candidates(stem, [n for n, _g, _l in src.entries])
        if not names:
            return None
        row = ttk.Frame(frame); row.pack(side="bottom", fill="x")
        ttk.Label(row, text="motion").pack(side="left", padx=(6, 2))
        choice = tk.StringVar(value="(bind pose)")
        cb = ttk.Combobox(row, textvariable=choice, values=["(bind pose)"] + names, width=34, state="readonly")
        cb.pack(side="left")
        pb = ttk.Button(row, text="Play", width=5)
        pb.pack(side="left", padx=4)
        lab = ttk.Label(row, text="", width=26)
        lab.pack(side="left")
        state.update(skel=None, sframe=0.0, boxes={}, splaying=False)
        import time as _time

        def select(_e=None):
            state.update(skel=None, sframe=0.0, boxes={})
            n = choice.get()
            if n in names:
                try:
                    a = _sk.parse(src.read_named(n) or b"")
                except Exception as e:  # noqa: BLE001
                    lab.config(text=f"cannot read: {e}"); return
                if not _sk.bound_bones(m, a)[0]:
                    lab.config(text="drives none of this model's bones"); return
                state["skel"] = a
            redraw()

        def tick(last):
            self._skel_after = None
            if not state["splaying"] or not row.winfo_exists() or state["skel"] is None:
                return
            now = _time.monotonic()
            a = state["skel"]
            state["sframe"] = a.wrap(state["sframe"] + 60.0 * (now - last))
            if not a.loops and state["sframe"] >= a.frame_count:
                state["sframe"] = 0.0
            redraw()
            self._skel_after = self.root.after(15, lambda: tick(now))

        def toggle():
            state["splaying"] = not state["splaying"] and state["skel"] is not None
            pb.config(text="Stop" if state["splaying"] else "Play")
            if state["splaying"] and getattr(self, "_skel_after", None) is None:
                tick(_time.monotonic())
        pb.config(command=toggle)

        def gif():
            a = state["skel"]
            if a is None:
                return
            f = filedialog.asksaveasfilename(defaultextension=".gif", initialfile=f"{stem}_{a.name}.gif",
                                             filetypes=[("GIF", "*.gif")])
            if not f:
                return
            from rf4s_modkit import model as _model
            self.root.config(cursor="watch"); self.root.update_idletasks()
            try:
                frames = _model.render_skeletal_animation(m, a, view.get(), 320, step=2)
                _model.save_gif(frames, f, step=2)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Export GIF", str(e)); return
            finally:
                self.root.config(cursor="")
            self.status.config(text=f"wrote {f} ({len(frames)} frames of {a.name})")
        ttk.Button(row, text="GIF…", width=5, command=gif).pack(side="left")
        cb.bind("<<ComboboxSelected>>", select)

        def update(st):
            a = st.get("skel")
            lab.config(text=f"frame {int(st['sframe']):3}/{a.frame_count} {'loop' if a.loops else 'once'}"
                       if a is not None else "")
        return update

    @staticmethod
    def _skel_box(m, anim, view):
        """Union view box of a skeletal animation sampled at 8 frames (keeps playback still)."""
        from rf4s_modkit import model as _model, skelanim as _sk
        proj = _model.VIEWS[view]
        box = None
        n = max(1, anim.frame_count)
        for k in range(8):
            m.pose = _sk.pose_bones(m, anim, n * k / 8.0)
            pts = [proj(p) for sh in m.shapes for p in m.shape_vertices(sh)]
            if pts:
                b = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        m.pose = None
        return box

    def _model_material_anim(self, name, m):
        """The parsed .bfmat beside a .model (same stem) when it animates one of the model's
        materials, else None."""
        from rf4s_modkit import matanim
        src = getattr(self, "source", None)
        if src is None:
            return None
        # same stem first, then the shipped .bfmat whose materials the model carries
        # (SYS_MENU_ANIME_01 -> anim_com01 ...); UV scroll, texture patterns and opacity
        for stem in matanim.companion_stems(name.rsplit("/", 1)[-1].rsplit(".", 1)[0]):
            blob = src.read_named(stem + ".bfmat")
            if not blob:
                continue
            try:
                anim = matanim.parse(blob)
            except Exception:  # noqa: BLE001
                continue
            if matanim.binds(anim, m):
                return anim
        return None

    def _export_model_gif(self, m, anim, view, stem):
        from rf4s_modkit import model as _model
        f = filedialog.asksaveasfilename(defaultextension=".gif", initialfile=stem + ".gif",
                                         filetypes=[("GIF", "*.gif")])
        if not f:
            return
        self.root.config(cursor="watch"); self.root.update_idletasks()
        try:
            frames = _model.render_animation(m, anim, view, 320, step=2)
            _model.save_gif(frames, f, step=2)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Export GIF", str(e)); return
        finally:
            self.root.config(cursor="")
        self.status.config(text=f"wrote {f} ({len(frames)} frames, one {anim.frame_count}-frame loop)")

    def _build_bntx_browser(self, nb, name, data):
        """A 'Textures' tab: list every embedded BNTX texture; click to preview
        (zoom), Export the selected one (toolbar Export), or Export all to a folder."""
        frame = ttk.Frame(nb); nb.add(frame, text="Textures")
        lst = texture.bntx_list(data)
        left = ttk.Frame(frame); left.pack(side="left", fill="y")
        tv = ttk.Treeview(left, columns=("dims", "fmt"), show="tree headings", height=22)
        tv.heading("#0", text="texture"); tv.column("#0", width=190)
        tv.heading("dims", text="w×h"); tv.column("dims", width=84, anchor="e")
        tv.heading("fmt", text="fmt"); tv.column("fmt", width=48, anchor="center")
        vs = ttk.Scrollbar(left, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(side="left", fill="y")
        for t in lst:
            tv.insert("", "end", iid=str(t["index"]), text=t["name"],
                      values=(f"{t['w']}×{t['h']}", t["fmt_name"]))
        right = ttk.Frame(frame); right.pack(side="left", fill="both", expand=True)
        bar = ttk.Frame(right); bar.pack(fill="x")
        self._bntx_lbl = ttk.Label(bar, text=f"{len(lst)} textures — select one")
        self._bntx_lbl.pack(side="left", padx=6)
        for z, lbl in ((0.5, "½×"), (1, "1×"), (2, "2×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z)).pack(side="left")
        ttk.Button(bar, text="Export all…", width=11,
                   command=lambda: self._export_all_bntx(name, data, lst)).pack(side="right", padx=4)
        ttk.Button(bar, text="Replace texture…", width=17,
                   command=lambda: self._replace_bntx_png(name, tv)).pack(side="right", padx=4)
        cvframe = ttk.Frame(right); cvframe.pack(fill="both", expand=True)
        self._img_canvas = self._make_image_canvas(cvframe)

        def on_sel(_evt=None):
            s = tv.selection()
            if not s:
                return
            idx = int(s[0])
            try:
                im = texture.decode_bntx(data, idx)
            except texture.TextureError as e:
                self._bntx_lbl.config(text=str(e)); return
            if im is None:
                self._bntx_lbl.config(text="unsupported format (needs texture2ddecoder)"); return
            self._pil = im.convert("RGBA")
            t = lst[idx]
            self._bntx_lbl.config(text=f"{t['name']}   {t['w']}×{t['h']}   {t['fmt_name']}")
            self._set_zoom(1.0)
            self._export_kind = "png"
            self.export_btn.config(state="normal")

        tv.bind("<<TreeviewSelect>>", on_sel)
        if lst:
            tv.selection_set(str(lst[0]["index"])); on_sel()

    def _replace_bntx_png(self, name, tv):
        """Replace the selected embedded texture of a .model from a PNG of the same size,
        re-encoded IN PLACE in its own block format (texture.bntx_replace: the file size and
        every container field stay as they are). Updates cur_data; Extract writes it."""
        sel = tv.selection()
        if not sel or self.cur_data is None:
            return
        idx = int(sel[0])
        f = filedialog.askopenfilename(title="Replace embedded texture from PNG…",
                                       filetypes=[("PNG image", "*.png"), ("All images", "*.*")])
        if not f:
            return
        try:
            blob = texture.bntx_replace(self.cur_data, idx, f)
        except Exception as e:  # noqa: BLE001 - surface any encode/size problem to the user
            messagebox.showerror("Replace failed", str(e))
            return
        self.cur_data = blob
        self._show(name, blob)
        self.status.config(text=f"Replaced texture {idx} from {pathlib.Path(f).name} in place -> "
                                f"{len(blob):,} bytes, size unchanged (Extract to save the working copy)")

    def _export_all_bntx(self, name, data, lst):
        d = filedialog.askdirectory(title="Export all textures to folder…")
        if not d:
            return
        out = pathlib.Path(d); n = 0
        for t in lst:
            try:
                im = texture.decode_bntx(data, t["index"])
            except Exception:  # noqa: BLE001
                im = None
            if im is None:
                continue
            im.save(str(out / f"{t['name']}.png")); n += 1
        self.status.config(text=f"Exported {n}/{len(lst)} textures -> {d}")

    def _view_gen(self, name, data):
        g = gen.GenTable(data)
        self._gen = g
        nmfn = _load_actor_names()
        roster = g.roster()
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        rtxt = ", ".join(f"{nmfn(i) or i}×{c}" for i, c in roster.most_common()) or "(none)"
        ttk.Label(bar, text=f"Monster encounter table — roster: {rtxt}",
                  wraplength=940).pack(side="left", padx=6)

        top = ttk.Frame(self.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=("id", "nm", "extra"), show="tree headings", height=14)
        tv.heading("#0", text="Gate / Spawn"); tv.column("#0", width=170)
        tv.heading("id", text="id"); tv.column("id", width=60, anchor="e")
        tv.heading("nm", text="name"); tv.column("nm", width=200)
        tv.heading("extra", text="weight / param"); tv.column("extra", width=120, anchor="e")
        vs = ttk.Scrollbar(top, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)
        meta = {}   # iid -> ('gate',pi,ei) | ('spawn',pi,ei,si)

        def fill():
            tv.delete(*tv.get_children()); meta.clear()
            for pi, entries in enumerate(g.patterns):
                for ei, e in enumerate(entries):
                    gid = tv.insert("", "end", text=f"P{pi}.E{ei} gate", open=True,
                                    values=(e.gate_kind, nmfn(e.gate_kind), f"wt {e.weight}"))
                    meta[gid] = ("gate", pi, ei)
                    for si, s in enumerate(e.spawns):
                        sid = tv.insert(gid, "end", text=f"  spawn {si}",
                                        values=(s.monster_id, nmfn(s.monster_id), f"wt {s.param}"))
                        meta[sid] = ("spawn", pi, ei, si)
        fill()

        ed = ttk.LabelFrame(self.content, text="Edit selected (gate: kind+weight · spawn: monster+pick weight)")
        ed.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(ed); row.pack(fill="x", padx=4, pady=4)
        f1l = ttk.Label(row, text="field A"); f1l.pack(side="left")
        v1 = tk.StringVar(); ttk.Entry(row, textvariable=v1, width=8).pack(side="left", padx=(2, 12))
        f2l = ttk.Label(row, text="field B"); f2l.pack(side="left")
        v2 = tk.StringVar(); ttk.Entry(row, textvariable=v2, width=8).pack(side="left", padx=2)
        nmlbl = ttk.Label(row, text=""); nmlbl.pack(side="left", padx=10)
        sel = {"iid": None}

        def on_sel(_e=None):
            s = tv.selection()
            if not s:
                return
            sel["iid"] = s[0]; m = meta.get(s[0])
            if not m:
                return
            if m[0] == "gate":
                e = g.patterns[m[1]][m[2]]
                f1l.config(text="gate kind"); f2l.config(text="weight")
                v1.set(str(e.gate_kind)); v2.set(str(e.weight)); nmlbl.config(text=nmfn(e.gate_kind))
            else:
                sp = g.patterns[m[1]][m[2]].spawns[m[3]]
                f1l.config(text="monster id"); f2l.config(text="pick weight")
                v1.set(str(sp.monster_id)); v2.set(str(sp.param)); nmlbl.config(text=nmfn(sp.monster_id))
        tv.bind("<<TreeviewSelect>>", on_sel)

        def apply_edit():
            m = meta.get(sel["iid"])
            if not m:
                return
            try:
                a, b = int(v1.get(), 0), int(v2.get(), 0)
            except ValueError as e:
                messagebox.showerror("Bad value", str(e)); return
            if m[0] == "gate":
                g.set_gate_kind(m[1], m[2], a); g.set_weight(m[1], m[2], b)
            else:
                sp = g.patterns[m[1]][m[2]].spawns[m[3]]
                g.set_spawn_monster(sp, a); g.set_spawn_pick_weight(sp, b)
            self.cur_data = g.build()
            fill()
            # fill() rebuilt the tree with fresh iids; re-select the same gate/spawn so
            # the edit boxes stay live and a follow-up Apply isn't a silent no-op
            # (matches the MOBJ / param / monster / search-item editors).
            for iid2, mk in meta.items():
                if mk == m:
                    sel["iid"] = iid2
                    tv.selection_set(iid2); tv.see(iid2)
                    break
            self.status.config(text="Applied — use Save table… or Extract… to write")

        def save_tbl():
            blob = g.build(); self.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(self.cur_name).name,
                filetypes=[("Gen table", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob)
                self.status.config(text=f"Saved encounter table → {f}")
        ttk.Button(row, text="Save table…", command=save_tbl).pack(side="right", padx=4)
        ttk.Button(row, text="Apply", command=apply_edit).pack(side="right", padx=4)

    def _view_asatk(self, name, data):
        """as_atk_*.bin attack-move timeline: rendered view + an editable listing that
        assembles back into the working copy (2026-09-19)."""
        s = asatk.summary(data)
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        hw = ", ".join(f"{o}-{c}" for o, c in s["hit_windows"]) or "(none)"
        ttk.Label(bar, text=f"Attack timeline — {s['pairs']} events, "
                            f"frames {s['first_frame']}..{s['last_frame']}, "
                            f"hit-window {hw}, effects {', '.join(str(e) for e in s['effects']) or '(none)'}",
                  wraplength=700).pack(side="left", padx=6)
        nb = ttk.Notebook(self.content); nb.pack(fill="both", expand=True)
        txt = self._make_text_tab(nb, "Timeline", mono=True)
        txt.insert("end", asatk.render(data))
        txt.insert("end", "\n\n" + "-" * 60 + "\nOpcode legend (V=IDA-verified, D=data-inferred):\n")
        for op in sorted(asatk.OPCODES):
            mn, kind, conf, desc = asatk.OPCODES[op]
            txt.insert("end", f"  op{op:<3d} [{conf}] {mn:<10s} {desc}\n")
        txt.config(state="disabled")
        # Edit tab: the canonical listing (raw operands); Apply assembles it into cur_data.
        ef = ttk.Frame(nb); nb.add(ef, text="Edit")
        eb = ttk.Frame(ef); eb.pack(fill="x")
        ttk.Label(eb, text="one event per line: <mnemonic|opN> <operand>  (int, 0x hex, 1.5q, 90deg); "
                           "comments after ';'", font=("Segoe UI", 8), foreground="#666").pack(side="left", padx=6)
        frame = ttk.Frame(ef); frame.pack(fill="both", expand=True)
        vs = ttk.Scrollbar(frame, orient="vertical")
        edit = tk.Text(frame, wrap="none", font=("Consolas", 9), yscrollcommand=vs.set, undo=True)
        vs.config(command=edit.yview); vs.pack(side="right", fill="y")
        edit.pack(side="left", fill="both", expand=True)
        edit.insert("end", asatk.disassemble(data))

        def apply_listing():
            try:
                blob = asatk.assemble(edit.get("1.0", "end"))
            except asatk.AsatkError as ex:
                messagebox.showerror("Assemble failed", str(ex)); return
            warns = asatk.validate(asatk.parse(blob, stop_at_end=False))
            self.cur_data = blob
            self.status.config(text="Timeline assembled (" + (f"{len(warns)} warning(s): {warns[0]}"
                                                               if warns else "no warnings") +
                                    ") — use Extract… / Save to write")
            self._show(self.cur_name, blob)
        ttk.Button(eb, text="Assemble & apply", command=apply_listing).pack(side="right", padx=6)
        self._export_kind = "disasm"; self._export_text = asatk.render(data)
        self.export_btn.config(state="normal")

    def _view_skillcurve(self, name, data):
        """rf3ParamSkillExp*.bin skill XP-per-level curve (read-only decode)."""
        xp = skillcurve.parse(data)
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        arc = next((a for a, f in skillcurve.ARCHIVE_FILE.items()
                    if pathlib.Path(name).stem.lower() == f.lower()), None)
        who = ""
        if arc is not None:
            sks = [s for s, a in skillcurve.FAMILY_ARCHIVE.items() if a == arc]
            who = f"archive {arc}" + (f", skills {sks}" if sks else " (default: weapons/magic/…)")
        ttk.Label(bar, text=f"Skill XP curve — 100 levels, total {sum(xp)}, "
                            f"cap-bracket table[99]={xp[-1] if xp else 0}   {who}",
                  wraplength=940).pack(side="left", padx=6)
        txt = self._make_text_tab(None, None, mono=True)
        txt.insert("end", skillcurve.render(data, upto=100))
        txt.config(state="disabled")

    def _view_strengthening(self, name, data):
        """rf3ItemStrengthening.bin — forge material rows / dish ingredient bonuses / the craft
        status word (GUI twin of `rf4mod str`). Grid of the fields that matter most, a filter
        for the NON-FOOD marker, and the full decoded row for the selection."""
        from rf4s_modkit import strengthening
        t = strengthening.StrengtheningTable(data)
        items = _load_item_names()
        names = {int(k): v for k, v in items.items()}
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"rf3ItemStrengthening: {len(t)} rows x 296 B  (74 s32 per item; "
                            "rows 1108..1149 = level/quality tier rows)").pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)
        only_nz = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="nonzero only", variable=only_nz).pack(side="left", padx=6)
        flagv = tk.StringVar(value="all")
        ttk.Label(bar, text="marker:").pack(side="left")
        ttk.Combobox(bar, textvariable=flagv, values=("all", "nonfood", "food"), width=8,
                     state="readonly").pack(side="left", padx=2)

        def export_csv():
            f = filedialog.asksaveasfilename(defaultextension=".csv",
                initialfile="rf3ItemStrengthening.csv",
                filetypes=[("CSV", "*.csv"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_text(t.to_csv(names), encoding="utf-8")
                self.status.config(text=f"Exported {len(t)} rows → {f}")
        ttk.Button(bar, text="Export CSV…", command=export_csv).pack(side="right", padx=4)

        show = ["difficulty", "atk", "mat", "def", "mdf", "str", "int", "vit", "reach_scale",
                "heal_hp", "heal_rp", "status_word"]
        cols = ["#", "name"] + show + ["procs", "resists", "flags"]
        top = ttk.Frame(self.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=cols, show="headings", height=14)
        widths = {"#": 44, "name": 170, "procs": 120, "resists": 120, "flags": 260, "status_word": 70}
        for c in cols:
            tv.heading(c, text=c); tv.column(c, width=widths.get(c, 52), anchor="w")
        vs = ttk.Scrollbar(top, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)

        def fill(*_):
            tv.delete(*tv.get_children())
            q = sv.get().lower().strip(); shown = 0
            for r in t.rows():
                if flagv.get() == "nonfood" and not r.is_non_food:
                    continue
                if flagv.get() == "food" and (r.is_non_food or r.is_tier_row):
                    continue
                if only_nz.get() and not r.nonzero():
                    continue
                nm = t.label(r.id, names)
                if q and q not in str(r.id) and q not in nm.lower():
                    continue
                procs = ", ".join(f"{n[5:]} {v * 100 // 4096}%" for n, v in r.nonzero("attack_proc"))
                res = ", ".join(f"{n[4:]} {v * 100 // 4096}%" for n, v in r.nonzero("resist"))
                vals = [r.id, nm] + [(("0x%X" % r[c]) if c == "status_word" else r[c]) for c in show]
                vals += [procs, res, "; ".join(r.status_flags())]
                tv.insert("", "end", iid=str(r.id), values=vals); shown += 1
                if shown >= MAX_TABLE_ROWS:
                    break
        sv.trace_add("write", fill); only_nz.trace_add("write", fill); flagv.trace_add("write", fill)
        fill()

        detail = tk.Text(self.content, height=12, wrap="word")
        detail.pack(fill="x", padx=6, pady=4)

        def on_select(*_):
            sel = tv.selection()
            if not sel:
                return
            detail.config(state="normal"); detail.delete("1.0", "end")
            detail.insert("end", t.render(int(sel[0]), names))
            detail.config(state="disabled")
        tv.bind("<<TreeviewSelect>>", on_select)
        detail.insert("end", "Select a row for the full decoded record (readers, units, flags).")
        detail.config(state="disabled")

    def _view_gifts(self, name, data):
        """rf3PresentNpc*.bin NPC gift-preference table (read-only decode, item names)."""
        items = _load_item_names()
        chars = _load_char_names()
        num = int(pathlib.Path(name).stem[13:15]) if pathlib.Path(name).stem[13:15].isdigit() else 0
        name_fn = lambda i: items.get(i, "")
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        who = chars.get(num, "?")
        ttk.Label(bar, text=f"Gift preferences — char {num} {who}  (archive {14850 + num})",
                  ).pack(side="left", padx=6)
        tv = ttk.Treeview(self.content, columns=("aff", "item", "fp"), show="headings", height=20)
        for c, w in (("aff", 130), ("item", 320), ("fp", 90)):
            tv.heading(c, text={"aff": "affinity", "item": "item / target", "fp": "FP / note"}[c])
            tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(self.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        catbytes = _find_extracted("rf3PresentCategory.bin")
        cats = gifts.load_categories(catbytes) if catbytes else None
        for g in gifts.parse(data):
            for aff in gifts.TIERS:              # loved / liked / disliked
                for e in g[aff]:
                    if e.kind == "item":
                        tgt = f"{e.value} {name_fn(e.value)}".strip()
                    elif e.kind == "xref" and cats:
                        ids = gifts.category_items(e.value, cats)
                        preview = ", ".join(name_fn(i) or str(i) for i in ids[:5])
                        tgt = f"[category #{e.value}: {preview}{', …' if len(ids) > 5 else ''}]"
                    elif e.kind == "category" and e.value in gifts.ITEM_RANGE_TABLE:
                        lo, hi, lbl = gifts.ITEM_RANGE_TABLE[e.value]
                        tgt = f"[all {lbl} (ids {lo}..{hi - 1})]"
                    else:
                        tgt = f"[{'category' if e.kind == 'xref' else 'item-range'} #{e.value}]"
                    fp = gifts.entry_fp(e, aff)
                    note = f"{fp:+d}" + ("  signature/hated"
                                         if aff == "disliked" and e.code == gifts.SIGNATURE_DISLIKE_CODE
                                         else "")
                    tv.insert("", "end", values=(aff, tgt, note))
        # ---- edit controls (2026-09-19): tier / FP of an item, signature dislike, remove ----
        ctl = ttk.Frame(self.content); ctl.pack(fill="x", padx=6, pady=3)
        v_item, v_tier, v_fp = tk.StringVar(), tk.StringVar(value="loved"), tk.StringVar()
        ttk.Label(ctl, text="item id").pack(side="left")
        ttk.Entry(ctl, textvariable=v_item, width=7).pack(side="left", padx=2)
        nm_lbl = ttk.Label(ctl, text="", width=22, foreground="steelblue"); nm_lbl.pack(side="left")
        v_item.trace_add("write", lambda *_a: nm_lbl.config(
            text=name_fn(int(v_item.get())) if v_item.get().strip().isdigit() else ""))
        ttk.Label(ctl, text="tier").pack(side="left", padx=(8, 2))
        ttk.Combobox(ctl, textvariable=v_tier, values=("loved", "liked", "disliked", "neutral"),
                     width=9, state="readonly").pack(side="left")
        ttk.Label(ctl, text="FP").pack(side="left", padx=(8, 2))
        ttk.Entry(ctl, textvariable=v_fp, width=5).pack(side="left")

        def _pick(_e=None):
            sel = tv.selection()
            if not sel:
                return
            aff, tgt, note = tv.item(sel[0], "values")
            head = str(tgt).split(" ", 1)[0]
            if head.isdigit():
                v_item.set(head); v_tier.set(aff)
                v_fp.set(str(note).split()[0].lstrip("+"))
        tv.bind("<<TreeviewSelect>>", _pick)

        def _edit(action):
            try:
                iid = int(v_item.get(), 0)
                fp = int(v_fp.get(), 0) if v_fp.get().strip() else None
            except ValueError:
                messagebox.showerror("Bad value", "item id (and FP) must be integers"); return
            t = gifts.GiftTable.parse(self.cur_data)
            try:
                if action == "set":
                    t.set_item(iid, v_tier.get(), fp)
                elif action == "signature":
                    t.set_signature(iid)
                else:
                    t.remove("item", iid)
                blob = t.build()
            except Exception as ex:  # noqa: BLE001 - surface the module's own message
                messagebox.showerror("Edit failed", str(ex)); return
            self.cur_data = blob
            self.status.config(text=f"gift table edited ({action} item {iid}) — Save table… / Extract… to write")
            self._show(self.cur_name, blob)

        def _save():
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                                             initialfile=pathlib.Path(self.cur_name).name,
                                             filetypes=[("gift table", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(self.cur_data); self.status.config(text=f"Saved → {f}")
        for lbl, act in (("Set tier", "set"), ("Signature dislike", "signature"), ("Remove item", "remove")):
            ttk.Button(ctl, text=lbl, command=lambda a=act: _edit(a)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Save table…", command=_save).pack(side="right", padx=2)

    def _view_schedule(self, name, data):
        """rf3Schedule — NPC daily-routine itineraries: one per (NPC, state), time -> spot kind
        -> room (spots resolved through the sibling rf3ScheduleID.bin when it is extracted)."""
        sc = schedule.Schedule.parse(data)
        cells = sc.ordered_cells()
        scheds = [lst for _k, lst in cells]
        sidbytes = _find_extracted("rf3ScheduleID.bin")
        spots = schedule.load_spots(sidbytes) if sidbytes else None
        chars = _load_char_names()
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"NPC daily schedules — {len(scheds)} (NPC, state) routines, "
                            f"{sum(len(s) for s in scheds)} stops. Pick a schedule:"
                  ).pack(side="left", padx=6)
        sv = tk.IntVar(value=0)
        sp = ttk.Spinbox(bar, from_=0, to=max(0, len(scheds) - 1), width=6, textvariable=sv)
        sp.pack(side="left", padx=4)
        who = ttk.Label(bar, text=""); who.pack(side="left", padx=8)
        tv = ttk.Treeview(self.content, columns=("time", "room", "name"), show="headings", height=20)
        for c, w in (("time", 80), ("room", 80), ("name", 360)):
            tv.heading(c, text={"time": "time", "room": "spot kind", "name": "location (rf3ScheduleID)"}[c])
            tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(self.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)

        def fill(*_):
            tv.delete(*tv.get_children())
            try:                       # IntVar.get() raises TclError mid-typing (empty / "1a")
                i = sv.get()
            except tk.TclError:
                return
            if not (0 <= i < len(scheds)):
                return
            (npc, state), _lst = cells[i]
            who.config(text=f"npc {npc} {chars.get(npc, '')}  state {state} "
                            f"({schedule.STATE_NAMES.get(state, '?')})")
            for wp in scheds[i]:
                tv.insert("", "end", values=(schedule.slot_to_time(wp.slot), wp.spot,
                                             schedule.describe_kind(wp.spot, spots, map_names.map_name)
                                             + ("  [random depart]" if wp.flags & 1 else "")))
        sv.trace_add("write", fill); fill()
        # ---- edit controls (2026-09-19): change / add / remove a stop of the shown schedule ----
        ctl = ttk.Frame(self.content); ctl.pack(fill="x", padx=6, pady=3)
        v_time, v_spot, v_rand = tk.StringVar(), tk.StringVar(), tk.BooleanVar()
        ttk.Label(ctl, text="time (HH:MM)").pack(side="left")
        ttk.Entry(ctl, textvariable=v_time, width=7).pack(side="left", padx=2)
        ttk.Label(ctl, text="spot kind").pack(side="left", padx=(8, 2))
        ttk.Entry(ctl, textvariable=v_spot, width=6).pack(side="left")
        ttk.Checkbutton(ctl, text="random depart", variable=v_rand).pack(side="left", padx=6)
        spot_lbl = ttk.Label(ctl, text="", foreground="steelblue"); spot_lbl.pack(side="left", padx=4)
        v_spot.trace_add("write", lambda *_a: spot_lbl.config(
            text=schedule.describe_kind(int(v_spot.get()), spots, map_names.map_name)[:60]
            if v_spot.get().strip().isdigit() else ""))

        def _pick(_e=None):
            sel = tv.selection()
            if not sel:
                return
            t, spot, desc = tv.item(sel[0], "values")
            v_time.set(t); v_spot.set(str(spot)); v_rand.set("[random depart]" in str(desc))
        tv.bind("<<TreeviewSelect>>", _pick)

        def _edit(action):
            try:
                i = sv.get()
                (npc, state), _lst = cells[i]
            except (tk.TclError, IndexError):
                return
            sel = tv.selection()
            idx = tv.index(sel[0]) if sel else None
            try:
                slot = schedule.time_to_slot(v_time.get()) if v_time.get().strip() else None
                spot = int(v_spot.get(), 0) if v_spot.get().strip() else None
                flags = 1 if v_rand.get() else 0
                if action == "apply":
                    if idx is None:
                        messagebox.showinfo("Schedule", "select a stop first"); return
                    sc.set_slice(npc, state, idx, slot=slot, flags=flags, spot=spot)
                elif action == "add":
                    if slot is None or spot is None:
                        messagebox.showinfo("Schedule", "give a time and a spot kind"); return
                    sc.add_slice(npc, state, slot, spot, flags)
                else:
                    if idx is None:
                        messagebox.showinfo("Schedule", "select a stop first"); return
                    sc.remove_slice(npc, state, idx)
                blob = sc.build()
            except Exception as ex:  # noqa: BLE001 - the module explains what is wrong
                messagebox.showerror("Edit failed", str(ex)); return
            self.cur_data = blob
            self.status.config(text=f"schedule edited ({action}, npc {npc} state {state}) — Save… / Extract… to write")
            fill()

        def _save():
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                                             initialfile=pathlib.Path(self.cur_name).name,
                                             filetypes=[("schedule", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(self.cur_data); self.status.config(text=f"Saved → {f}")
        for lbl, act in (("Apply stop", "apply"), ("Add stop", "add"), ("Remove stop", "remove")):
            ttk.Button(ctl, text=lbl, command=lambda a=act: _edit(a)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Save…", command=_save).pack(side="right", padx=2)

    def _view_gift_categories(self, name, data):
        """rf3PresentCategory — the 21 shared gift categories referenced by NPC cross-refs."""
        items = _load_item_names()
        cats = gifts.load_categories(data)
        ttk.Label(self.content, text=f"{len(cats)} shared gift categories (referenced by "
                                     f"NPC gift tables via cross-ref)").pack(fill="x", padx=6, pady=2)
        txt = self._make_text_tab(None, None, mono=True)
        for idx, _grp in enumerate(cats):
            ids = gifts.category_items(idx, cats)
            names = ", ".join(items.get(i, str(i)) for i in ids)
            txt.insert("end", f"cat {idx:>2} ({len(ids)}): {names}\n")
        txt.config(state="disabled")

    def _view_montame(self, name, data):
        """rf3MonsterPresent — per-species monster taming-food preferences (archive 14849)."""
        from rf4s_modkit import montame
        items = _load_item_names()
        chars = _load_char_names()
        ttk.Label(self.content, text=f"Monster taming-food preferences — {montame.species_count(data)} "
                                     f"species (id 48+), each with up to 4 favored items + tame bonus"
                  ).pack(fill="x", padx=6, pady=2)
        tv = ttk.Treeview(self.content, columns=("sp", "who", "items"), show="headings", height=22)
        for c, w in (("sp", 70), ("who", 150), ("items", 640)):
            tv.heading(c, text={"sp": "species", "who": "name", "items": "tame items (+bonus)"}[c])
            tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(self.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        for sid in range(montame.FIRST_SPECIES, montame.FIRST_SPECIES + montame.species_count(data)):
            pr = montame.prefs(data, sid)
            if not pr:
                continue
            txt = ", ".join(f"{items.get(i, i)} (+{b})" for i, b in pr)
            tv.insert("", "end", values=(sid, chars.get(sid, ""), txt))
        # ---- edit controls (2026-09-19): set / remove one of a species' four tame items ----
        ctl = ttk.Frame(self.content); ctl.pack(fill="x", padx=6, pady=3)
        v_sp, v_item, v_bonus = tk.StringVar(), tk.StringVar(), tk.StringVar(value="15")
        for lbl, var, w in (("species", v_sp, 6), ("item id", v_item, 7), ("bonus", v_bonus, 5)):
            ttk.Label(ctl, text=lbl).pack(side="left", padx=(6, 2))
            ttk.Entry(ctl, textvariable=var, width=w).pack(side="left")
        nm_lbl = ttk.Label(ctl, text="", width=22, foreground="steelblue"); nm_lbl.pack(side="left", padx=4)
        v_item.trace_add("write", lambda *_a: nm_lbl.config(
            text=items.get(int(v_item.get()), "") if v_item.get().strip().isdigit() else ""))
        tv.bind("<<TreeviewSelect>>", lambda _e: v_sp.set(tv.item(tv.selection()[0], "values")[0])
                if tv.selection() else None)

        def _edit(remove=False):
            try:
                sp, iid = int(v_sp.get(), 0), int(v_item.get(), 0)
                bonus = int(v_bonus.get(), 0)
            except ValueError:
                messagebox.showerror("Bad value", "species, item id and bonus must be integers"); return
            buf = bytearray(self.cur_data)
            try:
                if remove:
                    if not montame.remove_item(buf, sp, iid):
                        messagebox.showinfo("Taming foods", f"species {sp} does not list item {iid}"); return
                else:
                    montame.set_item(buf, sp, iid, bonus)
            except Exception as ex:  # noqa: BLE001
                messagebox.showerror("Edit failed", str(ex)); return
            blob = bytes(buf)
            self.cur_data = blob
            self.status.config(text=f"taming foods edited (species {sp}, item {iid}) — Save table… / Extract… to write")
            self._show(self.cur_name, blob)

        def _save():
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                                             initialfile=pathlib.Path(self.cur_name).name,
                                             filetypes=[("taming table", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(self.cur_data); self.status.config(text=f"Saved → {f}")
        ttk.Button(ctl, text="Set item", command=lambda: _edit(False)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Remove item", command=lambda: _edit(True)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Save table…", command=_save).pack(side="right", padx=2)

    def _view_route(self, name, data):
        """rf3route.bin — the NPC town-navigation graph (rooms -> nodes -> edges): tree view,
        path queries through rf3RouteResult.bin, JSON export / import (edits land in the
        working copy) and next-hop matrix regeneration (2026-09-19)."""
        from rf4s_modkit import route
        import json as _json
        g = route.RouteGraph.parse(data)
        rooms = [(rid, r) for rid, r in enumerate(g.rooms()) if r.node_count]
        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Navigation graph (TRCS) — {len(g.nodes)} nodes, {len(g.edges)} edges "
                            f"in {len(rooms)} rooms; positions are tiles, edge cost = walk cost",
                  wraplength=700).pack(side="left", padx=6)
        tv = ttk.Treeview(self.content, columns=("kind", "id", "detail"), show="tree headings", height=18)
        tv.heading("#0", text="room / node / edge"); tv.column("#0", width=230)
        for c, w in (("kind", 60), ("id", 60), ("detail", 520)):
            tv.heading(c, text=c); tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(self.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        for rid, r in rooms:
            parent = tv.insert("", "end", text=f"room {rid}  {map_names.map_name(rid)}",
                               values=("room", rid, f"{r.node_count} node(s) from #{r.first_node}"))
            for ni in g.nodes_of_room(rid):
                n = g.nodes[ni]
                nid = tv.insert(parent, "end", text=f"node {ni}",
                                values=("node", ni, f"tile ({n.x},{n.y})  jitter {n.jitter}  "
                                                    f"{n.edge_count} edge(s)"))
                for e in g.edges_of(ni):
                    tgt = g.edge_target(e)
                    tv.insert(nid, "end", text=f"-> node {tgt}",
                              values=("edge", tgt, f"room {e.dest_room} node {e.dest_node}  "
                                                   f"cost {e.cost}{'  (room transition)' if e.cost == 0 else ''}"))
        # ---- path query against the next-hop matrix ----
        ctl = ttk.Frame(self.content); ctl.pack(fill="x", padx=6, pady=3)
        v_src, v_dst = tk.StringVar(), tk.StringVar()
        ttk.Label(ctl, text="path from").pack(side="left")
        ttk.Entry(ctl, textvariable=v_src, width=10).pack(side="left", padx=2)
        ttk.Label(ctl, text="to").pack(side="left")
        ttk.Entry(ctl, textvariable=v_dst, width=10).pack(side="left", padx=2)
        ttk.Label(ctl, text="(node id or room:N[:k])", font=("Segoe UI", 8), foreground="#666").pack(side="left")
        out = ttk.Label(self.content, text="", wraplength=900, justify="left"); out.pack(fill="x", padx=6)

        def _node(text):
            s = text.strip()
            if s.lower().startswith("room:"):
                parts = s.split(":")
                return g.node_index(int(parts[1], 0), int(parts[2], 0) if len(parts) > 2 else 0)
            return int(s, 0)

        def _path():
            res_bytes = _find_extracted("rf3RouteResult.bin")
            if not res_bytes:
                out.config(text="rf3RouteResult.bin is not extracted next to the graph"); return
            try:
                src, dst = _node(v_src.get()), _node(v_dst.get())
                hops, total = route.RouteResult.parse(res_bytes, len(g.nodes)).path(g, src, dst)
            except Exception as ex:  # noqa: BLE001
                out.config(text=f"path: {ex}"); return
            steps = " -> ".join(f"{n}(r{g.nodes[n].room})" + (f"+{c}" if c else "") for n, c in hops)
            out.config(text=f"{len(hops) - 1} hop(s), total cost {total}:  {steps}")
        ttk.Button(ctl, text="Path", command=_path).pack(side="left", padx=4)

        def _export():
            f = filedialog.asksaveasfilename(defaultextension=".json", initialfile="rf3route.json",
                                             filetypes=[("JSON", "*.json")])
            if f:
                pathlib.Path(f).write_text(g.dumps(), encoding="utf-8")
                self.status.config(text=f"graph exported → {f}  (edit, then Import JSON…)")

        def _import():
            f = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
            if not f:
                return
            try:
                blob = route.RouteGraph.from_json(_json.loads(pathlib.Path(f).read_text(encoding="utf-8"))).build()
            except Exception as ex:  # noqa: BLE001
                messagebox.showerror("Import failed", str(ex)); return
            self.cur_data = blob
            self.status.config(text="graph imported — also rebuild the next-hop matrix (button) and save both")
            self._show(self.cur_name, blob)

        def _rebuild():
            f = filedialog.asksaveasfilename(defaultextension=".bin", initialfile="rf3RouteResult.bin",
                                             filetypes=[("route result", "*.bin")])
            if f:
                pathlib.Path(f).write_bytes(route.RouteResult.compute(g).build())
                self.status.config(text=f"next-hop matrix rebuilt from this graph → {f}")

        def _save():
            f = filedialog.asksaveasfilename(defaultextension=".bin", initialfile="rf3route.bin",
                                             filetypes=[("route graph", "*.bin")])
            if f:
                pathlib.Path(f).write_bytes(self.cur_data); self.status.config(text=f"Saved → {f}")
        for lbl, cmd in (("Export JSON…", _export), ("Import JSON…", _import),
                         ("Rebuild next-hop matrix…", _rebuild), ("Save graph…", _save)):
            ttk.Button(ctl, text=lbl, command=cmd).pack(side="right", padx=2)

    def _view_route_result(self, name, data):
        """rf3RouteResult.bin — the derived next-hop matrix; regenerate it from rf3route.bin."""
        from rf4s_modkit import route
        gb = _find_extracted("rf3route.bin")
        ttk.Label(self.content, wraplength=900, justify="left",
                  text="Next-hop matrix hop[dst][src] (nibbles) derived from rf3route.bin; the game walks "
                       "it hop by hop (Nav_BuildPathFromAToB). It is not edited directly: change the graph "
                       "and regenerate this file.").pack(fill="x", padx=6, pady=4)
        if gb:
            g = route.RouteGraph.parse(gb)
            rr = route.RouteResult.parse(data, len(g.nodes))
            same = rr.build() == route.RouteResult.compute(g, rr.rows).build()
            ttk.Label(self.content, text=f"{rr.rows} rows x {rr.stride} B; graph has {len(g.nodes)} nodes; "
                                         f"{'identical to' if same else 'equivalent to'} the matrix "
                                         f"recomputed from rf3route.bin"
                                         f"{'' if same else ' (differences are tie-breaks between equal-cost routes)'}"
                      ).pack(fill="x", padx=6)

            def _rebuild():
                blob = route.RouteResult.compute(g, rr.rows).build()
                self.cur_data = blob
                self.status.config(text="matrix recomputed from rf3route.bin — Extract… to write")
            ttk.Button(self.content, text="Recompute from rf3route.bin", command=_rebuild).pack(padx=6, pady=4)
        else:
            ttk.Label(self.content, text="rf3route.bin is not extracted, so the matrix cannot be checked").pack(padx=6)

    def _view_search_items(self, name, data):
        """SI_*.bin editor — daily ground-pickup spots (see docs/16).

        Two-pane layout: SPOTS (left, position + assigned pool) and POOLS (right,
        first-class pool list + the selected pool's weighted entries). Pools can be
        created/deleted independently and assigned to spots; the on-disk format
        only stores pools referenced by at least one spot, so unassigned pools are
        flagged and dropped on save.

        IDA-verified semantics: max 2 spawns/map/day (deterministic per day, sleep
        rerolls); positions in sub-units (tile = >>3); item id = low 11 bits;
        weight = low byte, summed in a u8 (totals > 255 wrap and skew odds)."""
        try:
            f = search_items.SearchItemFile.parse(data)
        except Exception as e:
            self._view_hex(name, data, error=str(e)); return
        self._si = f
        item_names = _load_item_names()

        # first-class pool list (ordered by first appearance in spots).
        # NOTE: identity comparison throughout — DropPool is a dataclass whose ==
        # compares by value, which would alias two pools with identical entries.
        pools: list = []
        for s in f.spots:
            if not any(p is s.pool for p in pools):
                pools.append(s.pool)
        if not pools:
            pools.append(search_items.DropPool(entries=[search_items.DropEntry(1, 10)]))

        try:
            search_items.parse_nlcl_footer(data)
            footer_txt = "footer: valid (engine ignores it)"
        except Exception:
            footer_txt = "footer: anomalous (harmless, engine ignores it)"

        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Search-item spots — engine rolls daily: 1-in-N chance per "
                            f"spot, max 2 spawns/map/day, sleep rerolls.",
                  wraplength=720).pack(side="left", padx=6)
        ttk.Label(bar, text=footer_txt, foreground="#888").pack(side="right", padx=6)

        paned = ttk.PanedWindow(self.content, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # ------------------------- left: SPOTS ----------------------------- #
        lf = ttk.LabelFrame(paned, text="Spots (position + assigned pool)")
        paned.add(lf, weight=1)
        sp_tv = ttk.Treeview(lf, columns=("x", "y", "tile", "pool"), show="headings", height=10)
        for c, w, a in (("x", 70, "e"), ("y", 70, "e"), ("tile", 90, "center"), ("pool", 80, "center")):
            sp_tv.heading(c, text=c); sp_tv.column(c, width=w, anchor=a)
        sp_tv.pack(fill="both", expand=True, padx=4, pady=2)

        spf = ttk.Frame(lf); spf.pack(fill="x", padx=4, pady=2)
        ttk.Label(spf, text="x:").pack(side="left")
        sx = tk.StringVar(); ttk.Entry(spf, textvariable=sx, width=7).pack(side="left", padx=(2, 8))
        ttk.Label(spf, text="y:").pack(side="left")
        sy = tk.StringVar(); ttk.Entry(spf, textvariable=sy, width=7).pack(side="left", padx=(2, 8))
        ttk.Label(spf, text="pool:").pack(side="left")
        spool = tk.StringVar()
        spool_cb = ttk.Combobox(spf, textvariable=spool, width=9, state="readonly")
        spool_cb.pack(side="left", padx=2)
        sp_tile = ttk.Label(spf, text="", foreground="#888"); sp_tile.pack(side="left", padx=8)

        spb = ttk.Frame(lf); spb.pack(fill="x", padx=4, pady=(0, 4))
        # (buttons wired below, after the helper closures exist)

        # ------------------------- right: POOLS ---------------------------- #
        rf = ttk.LabelFrame(paned, text="Pools (item tables — assign to spots on the left)")
        paned.add(rf, weight=2)
        pl_tv = ttk.Treeview(rf, columns=("entries", "total", "used"), show="tree headings", height=4)
        pl_tv.heading("#0", text="pool"); pl_tv.column("#0", width=80)
        pl_tv.heading("entries", text="entries"); pl_tv.column("entries", width=60, anchor="e")
        pl_tv.heading("total", text="total weight"); pl_tv.column("total", width=140, anchor="e")
        pl_tv.heading("used", text="used by spots"); pl_tv.column("used", width=170)
        pl_tv.pack(fill="x", padx=4, pady=2)

        en_tv = ttk.Treeview(rf, columns=("id", "name", "weight", "pct"), show="headings", height=8)
        for c, w, a in (("id", 60, "e"), ("name", 220, "w"), ("weight", 70, "e"), ("pct", 70, "e")):
            en_tv.heading(c, text={"id": "item id", "pct": "~%"}.get(c, c))
            en_tv.column(c, width=w, anchor=a)
        en_tv.pack(fill="both", expand=True, padx=4, pady=2)

        enf = ttk.Frame(rf); enf.pack(fill="x", padx=4, pady=2)
        ttk.Label(enf, text="item id:").pack(side="left")
        ei = tk.StringVar(); ttk.Entry(enf, textvariable=ei, width=7).pack(side="left", padx=(2, 8))
        ttk.Label(enf, text="weight:").pack(side="left")
        ew = tk.StringVar(); ttk.Entry(enf, textvariable=ew, width=7).pack(side="left", padx=2)
        en_name = ttk.Label(enf, text="", foreground="#888"); en_name.pack(side="left", padx=8)

        enb = ttk.Frame(rf); enb.pack(fill="x", padx=4, pady=(0, 4))

        # ------------------------- shared helpers -------------------------- #
        def pool_no(pool):
            return next((k for k, p in enumerate(pools) if p is pool), -1)

        def used_by(pool):
            return [i for i, s in enumerate(f.spots) if s.pool is pool]

        def sel_spot():
            s = sp_tv.selection()
            return int(s[0]) if s else None

        def sel_pool():
            s = pl_tv.selection()
            return int(s[0]) if s else None

        def sel_entry():
            s = en_tv.selection()
            return int(s[0]) if s else None

        def commit(refill=True):
            # Drop nothing from the editor state, but warn about unsaved pools.
            self.cur_data = f.build()
            orphans = [k for k, p in enumerate(pools) if not used_by(p)]
            note = (f"  (pool(s) {', '.join('#%d' % k for k in orphans)} unassigned — "
                    f"NOT saved until assigned to a spot)" if orphans else "")
            self.status.config(text="Applied — use Save table… or Extract… to write" + note)
            if refill:
                refresh_spots(); refresh_pools(); refresh_entries()

        def refresh_spots():
            keep = sel_spot()
            sp_tv.delete(*sp_tv.get_children())
            for i, s in enumerate(f.spots):
                sp_tv.insert("", "end", iid=str(i), text=str(i),
                             values=(s.x, s.y, f"({s.tile_x},{s.tile_y})", f"#{pool_no(s.pool)}"))
            spool_cb["values"] = [f"#{k}" for k in range(len(pools))]
            if keep is not None and keep < len(f.spots):
                sp_tv.selection_set(str(keep))

        def refresh_pools():
            keep = sel_pool()
            pl_tv.delete(*pl_tv.get_children())
            for k, p in enumerate(pools):
                raw = p.total_weight()
                tot = (f"{raw}  !! wraps to {p.engine_total_weight()}"
                       if raw > 255 else str(raw))
                used = ", ".join(map(str, used_by(p))) or "(unassigned — not saved)"
                pl_tv.insert("", "end", iid=str(k), text=f"pool #{k}",
                             values=(len(p.entries), tot, used))
            if keep is not None and keep < len(pools):
                pl_tv.selection_set(str(keep))
            elif pools:
                pl_tv.selection_set("0")

        def refresh_entries():
            en_tv.delete(*en_tv.get_children())
            k = sel_pool()
            if k is None or k >= len(pools):
                return
            p = pools[k]
            total = p.engine_total_weight()
            for j, e in enumerate(p.entries):
                pct = (100.0 * e.effective_weight / total) if total else 0.0
                en_tv.insert("", "end", iid=str(j),
                             values=(e.effective_item_id,
                                     item_names.get(e.effective_item_id, ""),
                                     e.effective_weight, f"{pct:4.1f}"))

        # ------------------------- selection handlers ---------------------- #
        def on_spot_sel(_e=None):
            i = sel_spot()
            if i is None:
                return
            s = f.spots[i]
            sx.set(str(s.x)); sy.set(str(s.y)); spool.set(f"#{pool_no(s.pool)}")
            sp_tile.config(text=f"tile ({s.tile_x},{s.tile_y})")
        sp_tv.bind("<<TreeviewSelect>>", on_spot_sel)

        def on_pool_sel(_e=None):
            refresh_entries()
        pl_tv.bind("<<TreeviewSelect>>", on_pool_sel)

        def on_entry_sel(_e=None):
            k, j = sel_pool(), sel_entry()
            if k is None or j is None:
                return
            e = pools[k].entries[j]
            ei.set(str(e.effective_item_id)); ew.set(str(e.effective_weight))
            en_name.config(text=item_names.get(e.effective_item_id, ""))
        en_tv.bind("<<TreeviewSelect>>", on_entry_sel)

        # ------------------------- spot actions ---------------------------- #
        def spot_apply():
            i = sel_spot()
            if i is None:
                messagebox.showinfo("Apply", "Select a spot first."); return
            try:
                x, y = int(sx.get(), 0), int(sy.get(), 0)
            except ValueError as e:
                messagebox.showerror("Bad value", str(e)); return
            if not (0 <= x <= 0xFFFF and 0 <= y <= 0xFFFF):
                messagebox.showerror("Bad value", "x/y must be 0..65535 sub-units"); return
            f.spots[i].x, f.spots[i].y = x, y
            pk = spool.get().lstrip("#")
            if pk.isdigit() and int(pk) < len(pools):
                f.spots[i].pool = pools[int(pk)]
            commit()

        def spot_add():
            pool = pools[sel_pool()] if sel_pool() is not None else pools[0]
            if f.spots:
                x, y = f.spots[-1].x + 8, f.spots[-1].y
            else:
                x, y = 64, 64
            f.spots.append(search_items.SearchSpot(x=x, y=y, pool=pool))
            commit()

        def spot_del():
            i = sel_spot()
            if i is None:
                messagebox.showinfo("Delete spot", "Select a spot first."); return
            del f.spots[i]
            commit()

        ttk.Button(spb, text="Apply spot", command=spot_apply).pack(side="left", padx=2)
        ttk.Button(spb, text="+ spot", command=spot_add).pack(side="left", padx=2)
        ttk.Button(spb, text="− spot", command=spot_del).pack(side="left", padx=2)

        # ------------------------- pool / entry actions -------------------- #
        def pool_add():
            pools.append(search_items.DropPool(entries=[search_items.DropEntry(1, 10)]))
            refresh_pools(); pl_tv.selection_set(str(len(pools) - 1))
            self.status.config(text="Pool added — assign it to a spot (it is NOT saved while unassigned)")

        def pool_del():
            k = sel_pool()
            if k is None:
                messagebox.showinfo("Delete pool", "Select a pool first."); return
            users = used_by(pools[k])
            if users:
                messagebox.showerror(
                    "Pool in use",
                    f"Pool #{k} is assigned to spot(s) {users}. Reassign those spots "
                    f"to another pool first.")
                return
            if len(pools) == 1:
                messagebox.showerror("Delete pool", "Cannot delete the last pool."); return
            del pools[k]
            commit()

        def entry_apply():
            k, j = sel_pool(), sel_entry()
            if k is None or j is None:
                messagebox.showinfo("Apply", "Select a pool entry first."); return
            try:
                a, b = int(ei.get(), 0), int(ew.get(), 0)
            except ValueError as e:
                messagebox.showerror("Bad value", str(e)); return
            if not (0 <= a <= 0x7FF):
                messagebox.showerror("Bad value", "item id must be 0..2047 (engine uses 11 bits)"); return
            if not (0 <= b <= 255):
                messagebox.showerror("Bad value", "weight must be 0..255 (engine reads one byte)"); return
            pools[k].entries[j].item_id = a
            pools[k].entries[j].weight = b
            if pools[k].total_weight() > 255:
                messagebox.showwarning(
                    "Weight overflow",
                    f"Pool #{k} total is now {pools[k].total_weight()} — the engine sums "
                    f"weights in a u8, so it wraps to {pools[k].engine_total_weight()} and "
                    f"skews the odds (worst case: only the first entry can drop). "
                    f"Keep the pool total ≤ 255.")
            commit()

        def entry_add():
            k = sel_pool()
            if k is None:
                messagebox.showinfo("Add entry", "Select a pool first."); return
            pools[k].entries.append(search_items.DropEntry(item_id=1, weight=10))
            commit()

        def entry_del():
            k, j = sel_pool(), sel_entry()
            if k is None or j is None:
                messagebox.showinfo("Delete entry", "Select a pool entry first."); return
            if len(pools[k].entries) == 1:
                messagebox.showerror("Delete entry", "A pool needs at least one entry."); return
            del pools[k].entries[j]
            commit()

        ttk.Button(enb, text="Apply entry", command=entry_apply).pack(side="left", padx=2)
        ttk.Button(enb, text="+ entry", command=entry_add).pack(side="left", padx=2)
        ttk.Button(enb, text="− entry", command=entry_del).pack(side="left", padx=2)
        ttk.Separator(enb, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(enb, text="+ pool", command=pool_add).pack(side="left", padx=2)
        ttk.Button(enb, text="− pool", command=pool_del).pack(side="left", padx=2)

        def save_tbl():
            blob = f.build(); self.cur_data = blob
            orphans = [k for k, p in enumerate(pools) if not used_by(p)]
            if orphans:
                if not messagebox.askokcancel(
                        "Unassigned pools",
                        f"Pool(s) {', '.join('#%d' % k for k in orphans)} are not assigned "
                        f"to any spot and will NOT be in the saved file. Save anyway?"):
                    return
            fpath = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(self.cur_name).name,
                filetypes=[("SI table", "*.bin"), ("All", "*.*")])
            if fpath:
                pathlib.Path(fpath).write_bytes(blob)
                self.status.config(text=f"Saved search-item table → {fpath}")
        ttk.Button(enb, text="Save table…", command=save_tbl).pack(side="right", padx=4)

        refresh_spots(); refresh_pools(); refresh_entries()
        if f.spots:
            sp_tv.selection_set("0")

    def _view_quest(self, name, data):
        """rf3TxtQuest_split3_1 — the QUEST/REQUEST database (archive 16342).

        Each of the ~165 requests is just {client_id, category}: the posting NPC and a
        category template id. The concrete objective (monster/item), count, and reward are
        rolled PROCEDURALLY at runtime (Quest_PopulateNpcSlot) — only these two bytes are
        authored. Localized text lives in rf3TxtQuest_split3_2/_3.<locale>. (Story/named
        quests are script-driven in rf3.mc — a different subsystem, not edited here.)
        """
        t = nlcl.NlclTable(data)
        self._param = t
        chars = _load_char_names()

        # category (byte1) = the objective-template selector Quest_LoadDetailStrings switches on.
        # Labels inferred by correlating each category's quests with their English text
        # (rf3TxtQuest_split3_2/_3.eng) — approximate but reflect the actual quest types.
        cat_names = {
            0: "dummy / gift (no objective)", 1: "deliver item (villager request)",
            2: "deliver item (mystery)", 4: "special (Amber / honey)", 5: "deliver food/seafood",
            6: "order milestone (license)", 7: "deliver (share item)", 8: "story / tutorial task",
            9: "do action (cook / forge)", 10: "milestone (achievement)",
            11: "milestone (crop quality)", 12: "milestone (skill level)", 13: "do action / order",
            14: "special (marriage / furniture)", 15: "befriend a monster", 16: "gather (lumber)",
            18: "friendship milestone", 20: "raise skill to 15", 21: "raise skill to 20",
            22: "befriend many monsters", 24: "shipment milestone",
            25: "slay monster (help request)", 26: "deliver (investigate)",
            27: "harvest crop (specific)", 28: "harvest / ship (tutorial)", 29: "ship category",
            30: "deliver (timed)", 31: "herd / hunt monsters", 32: "ship leveled item",
        }

        # Ground-truth labels: the category is a direct index into the per-category
        # detail-format strings in rf4TxtQuestRequestDetailFormat_split2_2.<locale>
        # (archive 16345, the 2nd DB archive QuestMenu_LoadDatabaseArchives loads). The %s
        # slots are filled at runtime with the rolled item/monster/count/reward. Prefer these
        # exact strings; fall back to the hand-written cat_names if the text file isn't present.
        fmt_strings = {}
        try:
            for loc in ("eng", "jpn", "fra", "deu"):
                fbytes = _find_extracted(f"rf4TxtQuestRequestDetailFormat_split2_2.{loc}")
                if fbytes:                 # _find_extracted returns the file BYTES, not a path
                    fa = textdb.TextArchive.parse(fbytes)
                    fmt_strings = {i: fa.text(i).replace("\n", " / ") for i in range(len(fa))}
                    break
        except Exception:
            fmt_strings = {}

        def cat_label(cat):
            s = fmt_strings.get(cat)
            if s and not s.startswith("BLANK"):
                return s
            return cat_names.get(cat, "")

        def cname(cid):
            if cid in (22, 23):
                return "(Anonymous)"
            if cid == 0:
                return "(placeholder / none)"
            return chars.get(cid, "")

        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Quest / Request database (archive 16342) — {t.entry_count} requests."
                            "  Each = posting NPC (client) + category template; the objective,"
                            " count and reward are rolled at runtime.").pack(side="left", padx=6)
        ttk.Label(bar, text="  Search #/client:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=14).pack(side="left", padx=2)

        cols = ("#", "client_id", "client", "category", "type")
        top = ttk.Frame(self.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=cols, show="headings", height=18)
        for c, w in (("#", 45), ("client_id", 65), ("client", 140), ("category", 60), ("type", 340)):
            tv.heading(c, text=c); tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(top, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)

        def fill(*_):
            tv.delete(*tv.get_children())
            q = sv.get().lower().strip()
            for i in range(t.entry_count):
                cid = t.get(i, 0, "u8"); cat = t.get(i, 1, "u8")
                nm = cname(cid); lbl = cat_label(cat)
                if q and q not in str(i) and q not in str(cid) and q not in nm.lower() \
                        and q not in lbl.lower() and q not in str(cat):
                    continue
                tv.insert("", "end", iid=str(i), values=(i, cid, nm, cat, lbl))
        sv.trace_add("write", fill); fill()

        ed = ttk.LabelFrame(self.content, text="Edit selected quest  (client_id + category; save writes the table)")
        ed.pack(fill="x", padx=6, pady=4)
        row = ttk.Frame(ed); row.pack(fill="x", padx=4, pady=4)
        ttk.Label(row, text="client_id:").pack(side="left")
        cid_v = tk.StringVar(); ttk.Entry(row, textvariable=cid_v, width=6).pack(side="left", padx=2)
        cid_name = ttk.Label(row, text="", width=20); cid_name.pack(side="left", padx=(0, 8))
        ttk.Label(row, text="category:").pack(side="left")
        cat_v = tk.StringVar(); ttk.Entry(row, textvariable=cat_v, width=6).pack(side="left", padx=2)
        cat_lbl = ttk.Label(row, text="", width=44); cat_lbl.pack(side="left", padx=(0, 8))
        sel = {"i": None}

        def on_cid(*_):
            try:
                cid_name.config(text=cname(int(cid_v.get(), 0)))
            except Exception:
                cid_name.config(text="")
        cid_v.trace_add("write", on_cid)

        def on_cat(*_):
            try:
                cat_lbl.config(text=cat_label(int(cat_v.get(), 0)))
            except Exception:
                cat_lbl.config(text="")
        cat_v.trace_add("write", on_cat)

        def on_sel(_e=None):
            s = tv.selection()
            if not s:
                return
            i = int(s[0]); sel["i"] = i
            cid_v.set(str(t.get(i, 0, "u8"))); cat_v.set(str(t.get(i, 1, "u8")))
        tv.bind("<<TreeviewSelect>>", on_sel)

        def apply_edit():
            if sel["i"] is None:
                return
            i = sel["i"]
            try:
                t.set(i, 0, int(cid_v.get(), 0), "u8")
                t.set(i, 1, int(cat_v.get(), 0), "u8")
            except (ValueError, nlcl.NlclError) as e:
                messagebox.showerror("Edit failed", str(e)); return
            self.cur_data = t.build()
            fill()
            tv.selection_set(str(i)); tv.see(str(i))
            self.status.config(text=f"Applied quest {i} — Save table… or Extract… to write")

        def save_tbl():
            blob = t.build(); self.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(self.cur_name).name,
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob)
                self.status.config(text=f"Saved quest DB → {f}")
        ttk.Button(row, text="Save table…", command=save_tbl).pack(side="right", padx=4)
        ttk.Button(row, text="Apply", command=apply_edit).pack(side="right", padx=4)

    def _view_param(self, name, data):
        t = nlcl.NlclTable(data)
        self._param = t
        stem = pathlib.Path(name).stem
        sch = t.schema(stem)
        # row-name fn (item names) if the schema asks for it
        namefn = (lambda i: "")
        if sch and sch.get("names") == "item" and ACTOR_NAMES_PATH.parent.joinpath("rf4s_item_names.json").is_file():
            import json as _json
            tbl = _json.loads((ACTOR_NAMES_PATH.parent / "rf4s_item_names.json").read_text(encoding="utf-8"))
            namefn = lambda i: tbl.get(str(i), "")

        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"NLCL {stem}: {t.entry_count} records × {t.record_size} B"
                          + ("  (named fields)" if sch else "  (raw — edit by offset)"),
                  ).pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)

        fields = sch["fields"] if sch else [(f"dw{k}", k * 4, "s32")
                                            for k in range(min(8, t.record_size // 4))]
        cols = ["#"] + [f[0] for f in fields] + (["name"] if sch and sch.get("names") else [])
        top = ttk.Frame(self.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=cols, show="headings", height=16)
        for c in cols:
            tv.heading(c, text=c); tv.column(c, width=70 if c != "name" else 160, anchor="w")
        vs = ttk.Scrollbar(top, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)

        name_field = sch.get("name_field") if sch else None
        name_off_typ = next(((o, ty) for n, o, ty in (sch["fields"] if sch else [])
                             if n == name_field), None)

        def fill(*_):
            tv.delete(*tv.get_children())
            q = sv.get().lower().strip()
            shown = 0
            for i in range(t.entry_count):
                nm = namefn(t.get(i, *name_off_typ) if name_off_typ else i)
                if q and q not in str(i) and q not in nm.lower():
                    continue
                vals = [i] + [t.get(i, off, typ) for _n, off, typ in fields]
                if sch and sch.get("names"):
                    vals.append(nm)
                tv.insert("", "end", iid=str(i), values=vals)
                shown += 1
                if shown >= MAX_TABLE_ROWS:
                    break
        sv.trace_add("write", fill); fill()

        ed = ttk.LabelFrame(self.content, text="Edit selected record")
        ed.pack(fill="x", padx=6, pady=4)
        grid = ttk.Frame(ed); grid.pack(fill="x", padx=4, pady=4)
        evars = []
        for idx, (fn, off, typ) in enumerate(fields):
            cell = ttk.Frame(grid); cell.grid(row=idx // 8, column=idx % 8, padx=2, pady=1)
            ttk.Label(cell, text=f"{fn}", font=("Segoe UI", 7)).pack()
            v = tk.StringVar(); ttk.Entry(cell, textvariable=v, width=9).pack()
            evars.append((v, off, typ, fn))
        # generic offset editor (for raw edits beyond the shown fields)
        gen_row = ttk.Frame(ed); gen_row.pack(fill="x", padx=4, pady=(0, 2))
        ttk.Label(gen_row, text="raw  off:").pack(side="left")
        off_v = tk.StringVar(); ttk.Entry(gen_row, textvariable=off_v, width=5).pack(side="left")
        ttk.Label(gen_row, text="type:").pack(side="left")
        typ_v = tk.StringVar(value="s32"); ttk.Combobox(gen_row, textvariable=typ_v, width=4,
                 values=list(nlcl._FMT.keys())).pack(side="left", padx=2)
        ttk.Label(gen_row, text="=").pack(side="left")
        rawval_v = tk.StringVar(); ttk.Entry(gen_row, textvariable=rawval_v, width=8).pack(side="left", padx=2)
        sel = {"i": None}

        def on_sel(_e=None):
            s = tv.selection()
            if not s:
                return
            i = int(s[0]); sel["i"] = i
            for v, off, typ, _fn in evars:
                v.set(str(t.get(i, off, typ)))
        tv.bind("<<TreeviewSelect>>", on_sel)

        def apply_edit():
            if sel["i"] is None:
                return
            i = sel["i"]
            try:
                for v, off, typ, _fn in evars:
                    t.set(i, off, int(v.get(), 0), typ)
                if off_v.get().strip() and rawval_v.get().strip():
                    t.set(i, int(off_v.get(), 0), int(rawval_v.get(), 0), typ_v.get())
            except (ValueError, nlcl.NlclError) as e:
                messagebox.showerror("Edit failed", str(e)); return
            self.cur_data = t.build()
            fill()
            tv.selection_set(str(i)); tv.see(str(i))
            self.status.config(text=f"Applied record {i} — Save table… or Extract… to write")

        def save_tbl():
            blob = t.build(); self.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(self.cur_name).name,
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob)
                self.status.config(text=f"Saved param table → {f}")

        def export_csv():
            """The table view (every record, schema columns + name column) as CSV."""
            f = filedialog.asksaveasfilename(defaultextension=".csv",
                initialfile=pathlib.Path(self.cur_name).stem + ".csv",
                filetypes=[("CSV", "*.csv"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_text(t.to_csv(stem, namefn), encoding="utf-8")
                self.status.config(text=f"Exported {t.entry_count} records → {f}")
        ttk.Button(gen_row, text="Export CSV…", command=export_csv).pack(side="right", padx=4)
        ttk.Button(gen_row, text="Save table…", command=save_tbl).pack(side="right", padx=4)
        ttk.Button(gen_row, text="Apply", command=apply_edit).pack(side="right", padx=4)

        # ---- add / remove rows (NlclTable.append_record / delete_record: entry_count,
        # byte_size and the NLCL footer are regenerated; whether the ENGINE reads the new row
        # is the schema's IDB-verified "grow" verdict, shown here and by `rf4mod param info`).
        grow_text = t.grow_info(stem)[1]
        ttk.Label(ed, text=grow_text, foreground="#555", wraplength=900).pack(fill="x", padx=6)

        def add_row():
            src = sel["i"]
            try:
                idx = t.append_record(t.record(src) if src is not None else None)
            except nlcl.NlclError as e:
                messagebox.showerror("Add row failed", str(e)); return
            self.cur_data = t.build()
            fill(); tv.selection_set(str(idx)); tv.see(str(idx)); on_sel()
            self.status.config(text=f"Added record {idx} ({'copy of ' + str(src) if src is not None else 'zero row'}); "
                                    f"{t.entry_count} records — Save table… to write")

        def del_row():
            i = sel["i"]
            if i is None:
                return
            if not messagebox.askyesno("Delete row", f"Delete record {i}? Records {i + 1}.. shift down by one "
                                                     f"(the row index is the id in most tables)."):
                return
            try:
                t.delete_record(i)
            except nlcl.NlclError as e:
                messagebox.showerror("Delete row failed", str(e)); return
            sel["i"] = None
            self.cur_data = t.build()
            fill()
            self.status.config(text=f"Deleted record {i}; {t.entry_count} records — Save table… to write")
        ttk.Button(gen_row, text="Delete row", command=del_row).pack(side="right", padx=4)
        ttk.Button(gen_row, text="Add row (copy of selected)", command=add_row).pack(side="right", padx=4)

    def _view_crop(self, name, data):
        """rf3CropParam — crop editor with READABLE season affinity (GUI twin of the
        `rf4mod crop` CLI). The grid decodes each crop's growing season; the editor lets
        you pick which season(s) a crop grows in via checkboxes (writes the +104
        boost/penalty bits) alongside per-field editing (water, growth-rate mults, stages).
        Byte-surgical; Apply updates the in-memory table, Save…/Extract… writes it out."""
        t = nlcl.NlclTable(data)
        self._param = t
        stem = "rf3CropParam"
        namefn = (lambda i: "")
        itemjson = ACTOR_NAMES_PATH.parent / "rf4s_item_names.json"
        if itemjson.is_file():
            import json as _json
            tbl = _json.loads(itemjson.read_text(encoding="utf-8"))
            namefn = lambda i: tbl.get(str(i), "")

        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"rf3CropParam: {t.entry_count} crops × {t.record_size} B  "
                            "(season affinity + growth tuning)").pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)
        only_crops = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="planted crops only", variable=only_crops).pack(side="left", padx=6)

        show_cols = ["stage1", "stage2", "stage3", "regrow", "water", "grow_cap",
                     "gmul_size", "gmul_1", "gmul_2", "gmul_3", "harvest", "seed"]
        cols = ["#"] + show_cols + ["grows", "name"]
        top = ttk.Frame(self.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=cols, show="headings", height=15)
        widths = {"#": 40, "grows": 150, "name": 150}
        for c in cols:
            tv.heading(c, text=c); tv.column(c, width=widths.get(c, 58), anchor="w")
        vs = ttk.Scrollbar(top, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)

        def is_planted(i):
            return bool(any(t.get(i, k, "u8") for k in range(3))
                        or (t.get(i, 104, "u32") & nlcl._CROP_SEASON_MASK))

        def fill(*_):
            tv.delete(*tv.get_children())
            q = sv.get().lower().strip(); shown = 0
            for i in range(t.entry_count):
                if only_crops.get() and not is_planted(i):
                    continue
                nm = namefn(t.get(i, 96, "u32"))
                if q and q not in str(i) and q not in nm.lower():
                    continue
                row = t.row(i, stem)
                grows = "/".join(nlcl.crop_season_decode(row["season"])["grows"])
                vals = [i] + [row[c] for c in show_cols] + [grows, nm]
                tv.insert("", "end", iid=str(i), values=vals); shown += 1
                if shown >= MAX_TABLE_ROWS:
                    break
        sv.trace_add("write", fill); only_crops.trace_add("write", fill); fill()

        ed = ttk.LabelFrame(self.content, text="Edit selected crop")
        ed.pack(fill="x", padx=6, pady=4)
        grid = ttk.Frame(ed); grid.pack(fill="x", padx=4, pady=2)
        ftyp = {n: (o, ty) for n, o, ty in t.schema(stem)["fields"]}
        editable = ["stage1", "stage2", "stage3", "regrow", "water", "grow_cap",
                    "gmul_size", "gmul_1", "gmul_2", "gmul_3", "harvest", "seed"]
        evars = []
        for idx, fn in enumerate(editable):
            cell = ttk.Frame(grid); cell.grid(row=idx // 6, column=idx % 6, padx=2, pady=1)
            ttk.Label(cell, text=fn, font=("Segoe UI", 7)).pack()
            v = tk.StringVar(); ttk.Entry(cell, textvariable=v, width=9).pack()
            evars.append((v, fn))
        srow = ttk.Frame(ed); srow.pack(fill="x", padx=4, pady=(3, 4))
        ttk.Label(srow, text="grows in:").pack(side="left")
        seavars = {}
        for s in nlcl.CROP_SEASONS:
            bv = tk.BooleanVar(); ttk.Checkbutton(srow, text=s, variable=bv).pack(side="left")
            seavars[s] = bv
        allyear = tk.BooleanVar()
        ttk.Checkbutton(srow, text="all-year (no off-season penalty)",
                        variable=allyear).pack(side="left", padx=10)
        sel = {"i": None}

        def on_sel(_e=None):
            s = tv.selection()
            if not s:
                return
            i = int(s[0]); sel["i"] = i
            row = t.row(i, stem)
            for v, fn in evars:
                v.set(str(row[fn]))
            dec = nlcl.crop_season_decode(row["season"])
            grows = set() if dec["grows"] == ["all-season"] else set(dec["grows"])
            for s2, bv in seavars.items():
                bv.set(s2 in grows)
            allyear.set(not grows or not dec["penalized"])
        tv.bind("<<TreeviewSelect>>", on_sel)

        def apply_edit():
            if sel["i"] is None:
                return
            i = sel["i"]
            try:
                for v, fn in evars:
                    off, ty = ftyp[fn]
                    t.set(i, off, int(v.get(), 0), ty)
                chosen = [s for s, bv in seavars.items() if bv.get()]
                old = t.get(i, 104, "u32")
                if chosen:
                    t.set(i, 104, nlcl.crop_season_encode(old, chosen,
                                                          single=not allyear.get()), "u32")
                elif allyear.get():
                    t.set(i, 104, old & ~nlcl._CROP_SEASON_MASK, "u32")   # grow everywhere
            except (ValueError, nlcl.NlclError) as e:
                messagebox.showerror("Edit failed", str(e)); return
            self.cur_data = t.build()
            fill(); tv.selection_set(str(i)); tv.see(str(i))
            self.status.config(text=f"Applied crop {i} — Save…/Extract… to write a loose override")

        def save_tbl():
            blob = t.build(); self.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(self.cur_name).name,
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob)
                self.status.config(text=f"Saved crop table → {f}")
        btns = ttk.Frame(ed); btns.pack(fill="x", padx=4, pady=(0, 3))
        ttk.Button(btns, text="Save table…", command=save_tbl).pack(side="right", padx=4)
        ttk.Button(btns, text="Apply", command=apply_edit).pack(side="right", padx=4)

    def _view_monster(self, name, data):
        """rf3NpcParam — friendly monster/character template editor (archive 14812).

        Resolved roster (name + kind) on the left; the selected monster's full decoded
        sheet (drops with item names, element affinities as %, status resists) on the right,
        with per-field entry boxes for every schema field (stats/drops/elements/resists/AI/
        model). Apply writes into the in-memory table; Save… writes a loose-override .bin.
        Editing is byte-surgical — only the touched record changes."""
        from rf4s_modkit import monster
        t = nlcl.NlclTable(data)
        self._param = t
        stem = "rf3NpcParam"
        sch = t.schema(stem)
        species = monster.load_species()
        items = _load_item_names()

        bar = ttk.Frame(self.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Monster / character templates — {t.entry_count} char_ids × "
                            f"{t.record_size} B   (id: <48 human · 48-199 field · 200-253 boss)"
                  ).pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)

        body = ttk.Frame(self.content); body.pack(fill="both", expand=True)
        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True)
        cols = ("id", "name", "hp", "atk", "def", "kind")
        widths = {"id": 50, "name": 150, "hp": 70, "atk": 55, "def": 55, "kind": 155}
        tv = ttk.Treeview(left, columns=cols, show="headings", height=20)
        for c in cols:
            tv.heading(c, text=c); tv.column(c, width=widths[c], anchor="w")
        vs = ttk.Scrollbar(left, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        sheet = tk.Text(right, wrap="word", width=52, height=15, font=("Consolas", 9))
        sheet.pack(fill="both", expand=True, padx=4, pady=2); sheet.config(state="disabled")
        ed = ttk.LabelFrame(right, text="Edit fields — Apply, then Save…")
        ed.pack(fill="x", padx=4, pady=2)
        grid = ttk.Frame(ed); grid.pack(fill="x", padx=4, pady=2)
        fields = sch["fields"]
        evars = []
        for idx, (fn, off, typ) in enumerate(fields):
            cell = ttk.Frame(grid); cell.grid(row=idx // 6, column=idx % 6, padx=1, pady=1)
            ttk.Label(cell, text=fn, font=("Segoe UI", 7)).pack()
            v = tk.StringVar(); ttk.Entry(cell, textvariable=v, width=8).pack()
            evars.append((v, off, typ))
        sel = {"i": None}

        def render_sheet(cid):
            sheet.config(state="normal"); sheet.delete("1.0", "end")
            sheet.insert("end", monster.render(t, cid, species, items))
            sheet.config(state="disabled")

        def fill(*_):
            tv.delete(*tv.get_children())
            q = sv.get().lower().strip()
            shown = 0
            for i in range(t.entry_count):
                nm = monster.species_name(i, species) or "???"
                if q and q not in str(i) and q not in nm.lower():
                    continue
                row = t.row(i, stem)
                tot = monster.base_totals(row)   # ATK/DEF = flat + STR / VIT/2 (template)
                tv.insert("", "end", iid=str(i),
                          values=(i, nm, row["hp"], tot["atk"], tot["def"], monster.id_semantics(i)))
                shown += 1
                if shown >= MAX_TABLE_ROWS:
                    break
        sv.trace_add("write", fill); fill()

        def on_sel(_e=None):
            s = tv.selection()
            if not s:
                return
            i = int(s[0]); sel["i"] = i
            for v, off, typ in evars:
                v.set(str(t.get(i, off, typ)))
            render_sheet(i)
        tv.bind("<<TreeviewSelect>>", on_sel)

        def apply_edit():
            if sel["i"] is None:
                return
            i = sel["i"]
            try:
                for v, off, typ in evars:
                    t.set(i, off, int(v.get(), 0), typ)
            except (ValueError, nlcl.NlclError) as e:
                messagebox.showerror("Edit failed", str(e)); return
            self.cur_data = t.build()
            fill(); tv.selection_set(str(i)); tv.see(str(i)); render_sheet(i)
            self.status.config(text=f"Applied char {i} — Save… to write a loose override")

        def save_tbl():
            blob = t.build(); self.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin", initialfile="rf3NpcParam.bin",
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob)
                self.status.config(text=f"Saved rf3NpcParam → {f}")

        btns = ttk.Frame(ed); btns.pack(fill="x", padx=4, pady=2)
        ttk.Button(btns, text="Save…", command=save_tbl).pack(side="right", padx=3)
        ttk.Button(btns, text="Apply", command=apply_edit).pack(side="right", padx=3)

    def _view_hex(self, name, data, error: str | None = None):
        txt = self._make_text_tab(None, None, mono=True)
        if error:
            txt.insert("end", f"[viewer note] {error}\n\n")
        txt.insert("end", hexdump(data))
        txt.config(state="disabled")

    # ---- view helpers ---------------------------------------------------- #
    def _make_text_tab(self, nb, title, mono=False):
        parent = self.content if nb is None else ttk.Frame(nb)
        if nb is not None:
            nb.add(parent, text=title)
        frame = ttk.Frame(parent); frame.pack(fill="both", expand=True)
        vs = ttk.Scrollbar(frame, orient="vertical")
        txt = tk.Text(frame, wrap="none", font=("Consolas", 9) if mono else ("Segoe UI", 10),
                      yscrollcommand=vs.set)
        vs.config(command=txt.yview)
        vs.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        return txt

    def _make_image_canvas(self, parent=None):
        parent = parent or self.content
        frame = ttk.Frame(parent); frame.pack(fill="both", expand=True)
        hb = ttk.Scrollbar(frame, orient="horizontal")
        vb = ttk.Scrollbar(frame, orient="vertical")
        canvas = tk.Canvas(frame, bg="#202020", xscrollcommand=hb.set, yscrollcommand=vb.set)
        hb.config(command=canvas.xview); vb.config(command=canvas.yview)
        hb.pack(side="bottom", fill="x"); vb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        return canvas

    def _set_zoom(self, z):
        if self._pil is None:
            return
        self.zoom = z
        w, h = self._pil.size
        # crisp nearest-neighbour when magnifying (see the pixels); smooth LANCZOS
        # when shrinking so downscaled photos/atlases don't alias to noise.
        resample = Image.NEAREST if z >= 1 else Image.LANCZOS
        disp = self._pil.resize((max(1, int(w * z)), max(1, int(h * z))), resample)
        self.cur_image = ImageTk.PhotoImage(disp)
        self._img_canvas.delete("all")
        self._img_canvas.create_image(0, 0, anchor="nw", image=self.cur_image)
        self._img_canvas.config(scrollregion=(0, 0, disp.width, disp.height))

    # ---- extract / export ------------------------------------------------ #
    def cmd_map_explorer(self):
        """Open the standalone map editor in a separate window, seeded with the current map."""
        import map_editor
        seed = None
        if self.cur_name and self.cur_name.lower().endswith(".rf4m"):
            seed = self.cur_name
        map_editor.MapExplorer(tk.Toplevel(self.root), initial=seed)

    def cmd_cutscene_editor(self):
        """Open the cutscene / event-script editor (rf3.mc + rf3mc.<locale>) in a window.
        Reads the script files by basename from the currently-loaded source, so it works
        best with a Manifest open (it can reach both bundlePatch1 and bundleMain)."""
        import cutscene_editor
        reader = self.source.read_named if self.source else None
        win = tk.Toplevel(self.root)
        win.title("RF4S Cutscene Editor")
        win.geometry("1180x780")
        cutscene_editor.CutsceneExplorer(win, reader=reader)
        if reader is None or reader("rf3.mc") is None:
            self.status.config(text="Cutscene editor: open the Manifest (or a bundle with rf3.mc) "
                                    "first, or use 'Open rf3.mc…' in the window.")

    def cmd_event_manager(self):
        """Open the Cutscene editor and pop its Event Manager (em.bin) window straight
        away. Same window the 'Cutscenes' button reaches via 'Event Manager\u2026'; the entry
        browser works without rf3.mc loaded (the 'used by scenes' list is just empty)."""
        import cutscene_editor
        reader = self.source.read_named if self.source else None
        win = tk.Toplevel(self.root)
        win.title("RF4S Cutscene Editor")
        win.geometry("1180x780")
        cutscene_editor.CutsceneExplorer(win, reader=reader).open_event_manager()

    def cmd_extract(self):
        if self.cur_data is None:
            return
        default = pathlib.Path(self.cur_name).name
        f = filedialog.asksaveasfilename(title="Extract raw bytes", initialfile=default)
        if f:
            pathlib.Path(f).write_bytes(self.cur_data)
            self.status.config(text=f"Extracted {len(self.cur_data):,} bytes -> {f}")

    def cmd_export(self):
        kind = getattr(self, "_export_kind", None)
        if not kind:
            return
        stem = pathlib.Path(self.cur_name).stem
        if kind == "map_png":
            # .rf4m: WYSIWYG snapshot of the embedded map editor -- current zoom
            # level + exactly the overlay layers that are toggled on.
            panel = getattr(self, "_map_panel", None)
            img = panel.render_to_image() if panel is not None else None
            if img is None:
                self.status.config(text="Map export needs Pillow + an ATTR grid.")
                return
            f = filedialog.asksaveasfilename(defaultextension=".png", initialfile=stem + ".png",
                                             filetypes=[("PNG", "*.png")])
            if f:
                img.save(f)
                trans = ""
                if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 255:
                    trans = ", with transparency"
                self.status.config(text=f"Exported map view -> {f}  "
                                        f"({img.width}x{img.height} px, {panel.cellpx} px/tile{trans})")
        elif kind == "png":
            f = filedialog.asksaveasfilename(defaultextension=".png", initialfile=stem + ".png",
                                             filetypes=[("PNG", "*.png")])
            if f and self._pil:
                self._pil.save(f); self.status.config(text=f"Exported PNG -> {f}")
        elif kind == "textjson":
            import json
            f = filedialog.asksaveasfilename(defaultextension=".json", initialfile=stem + ".json",
                                             filetypes=[("JSON", "*.json")])
            if f:
                pathlib.Path(f).write_text(
                    json.dumps(self._export_arc.texts(), ensure_ascii=False, indent=1), encoding="utf-8")
                self.status.config(text=f"Exported {len(self._export_arc)} strings -> {f}")
        elif kind == "plistjson":
            import json
            f = filedialog.asksaveasfilename(defaultextension=".json", initialfile=stem + ".json",
                                             filetypes=[("JSON", "*.json")])
            if f:
                obj = bplist.loads(self._export_data)
                pathlib.Path(f).write_text(
                    json.dumps(bplist.to_jsonable(obj), ensure_ascii=False, indent=1), encoding="utf-8")
                self.status.config(text=f"Exported plist JSON -> {f}")
        elif kind == "disasm":
            f = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=stem + ".txt",
                                             filetypes=[("Text", "*.txt")])
            if f:
                pathlib.Path(f).write_text(self._export_text, encoding="utf-8")
                self.status.config(text=f"Exported disassembly -> {f}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    found = gamepaths.find_bundle_dir()
    if not argv and (found is None or (not gamepaths.is_unpacked(found)
                                       and gamepaths.get_setting("unpack_asked") != str(found))):
        # no usable game copy, or one not unpacked yet (asked once per copy): ask for one /
        # offer to copy and unpack it before anything reads the game files
        import game_setup
        if found is not None:
            gamepaths.set_setting("unpack_asked", str(found))
        root.withdraw()
        if game_setup.run(root, current=found) or found is not None:
            _use_game_paths()
        root.deiconify()
    App(root, initial=argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
