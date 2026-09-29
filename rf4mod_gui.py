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
              TEXT / rf3mc.*   -> text editor (every line; checked; Save / Save as…)
              .minterface/.plist/.mbundle/Manifest -> bplist tree
              .rf4m            -> chunk list + ATTR heatmap + record counts
              .bin (AIBN)      -> opcode disassembly
              .strings         -> text editor (keys and values)
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

from rf4s_modkit import assetcat, gamepaths  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
# the game copy's Bundle folder the user chose (rf4s_modkit.gamepaths); main() asks for it
# when none is chosen yet
BUNDLE_DIR = gamepaths.bundle_dir()
# Extraction root: Bundle/extracted/ if present, else a flat Bundle/<bundle>/ layout.
EXTRACTED = gamepaths.extracted_dir(BUNDLE_DIR)
DEFAULT_MANIFEST = BUNDLE_DIR / "Manifest.plist"
GROUP_MAPS_SETTING = "group_maps_by_area"      # settings.json: the file tree's map grouping


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
from guiutil import err_text
def _load_actor_names():
    """id -> name: the game's rf3TxtNpc (gamenames), else the built-in list."""
    from rf4s_modkit import gamenames
    tbl = gamenames.table("characters")
    return lambda i: tbl.get(i, "")


def _load_item_names() -> dict[int, str]:
    """{item id: name}: the game's rf3TxtItem, else the built-in list."""
    from rf4s_modkit import gamenames
    return dict(gamenames.table("items"))


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
    """{character id: name}: the game's rf3TxtNpc, else the built-in list."""
    from rf4s_modkit import gamenames
    return dict(gamenames.table("characters"))

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
        self.sizes: list = []                               # bytes per entry (None = unknown)
        self._cats = None

    def add(self, name: str, group: str, loader, size=None):
        self.entries.append((name, group, loader))
        self.sizes.append(size)
        self._cats = None

    def categories(self):
        """rf4s_modkit.assetcat category key per entry (from the names; nothing is opened)."""
        if self._cats is None or len(self._cats) != len(self.entries):
            self._cats = [assetcat.category_of(e[0]) for e in self.entries]
        return self._cats

    @staticmethod
    def _scan(folder):
        """[(rel path, full path, size)] of every file under `folder`. os.scandir hands out
        the size with the name on Windows, so sizing ~38k files costs nothing extra."""
        import os
        out, stack = [], [(str(folder), "")]
        while stack:
            d, rel = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for de in it:
                    r = f"{rel}/{de.name}" if rel else de.name
                    try:
                        if de.is_dir(follow_symlinks=False):
                            stack.append((de.path, r))
                        elif de.is_file():
                            out.append((r, de.path, de.stat().st_size))
                    except OSError:
                        pass
        return out

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
            loose = {}
            if udir.is_dir():
                loose = {rel: size for rel, _full, size in cls._scan(udir)}
            bundle = mbundle.Bundle(bpath, manifest=man) if bpath.is_file() else None
            for name, info in man.files(bname).items():
                rel = name.replace("\\", "/").lstrip("/")
                if rel in loose:
                    fp = udir / rel
                    src.add(name, bname, (lambda f: (lambda: f.read_bytes()))(fp), loose[rel])
                elif bundle is not None:
                    src.add(name, bname, (lambda b, n: (lambda: b.read(n)))(bundle, name),
                            (info or {}).get("size"))
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
            src.add(name, bpath.name, (lambda n: (lambda: bundle.read(n)))(name), bundle.info(name)[1])
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
        found = cls._scan(root)
        # same order the pathlib version produced: part by part (so "numpy/" sorts before
        # "numpy-2.5.3.dist-info/"), case-insensitively on Windows
        found.sort(key=lambda rf: os.path.normcase(rf[1]).split(os.sep))
        for rel, full, size in found:
            group = rel.split("/", 1)[0] if "/" in rel else ""
            src.add(rel, group, (lambda fp: (lambda: pathlib.Path(fp).read_bytes()))(full), size)
        return src

    @classmethod
    def from_file(cls, file) -> "Source":
        p = pathlib.Path(file)
        src = cls(f"File: {p.name}")
        src.add(p.name, "", lambda: p.read_bytes(), p.stat().st_size)
        return src


# --------------------------------------------------------------------------- #
# Main application
# --------------------------------------------------------------------------- #
class _GenHost:
    """Everything map_editor.tabs.EncountersTab asks of an editor (doc.gen, the selected gate,
    apply, status, start_add), for a Gen file shown on its own: the explorer's Gen view uses
    the map editor's Gates pane with a flat picture of the map instead of the editor.
    Edits change the working copy at once (Save table… writes it)."""

    PICTURE_PX = 440
    PICTURE_PAD = 12                     # the picture column's padx (6 + 6)

    def __init__(self, app, name, g, tab):
        import types
        self.app, self.name = app, name
        self.tab = tab                   # the explorer tab (_Doc) this Gen file is open in
        self.doc = types.SimpleNamespace(gen=g, gen_path=pathlib.Path(name))
        self.gate_index = None
        self.pane = None
        self.map = None                  # the entry name of the map pictured
        self._ground = {}                # map entry name -> (scaled RGB picture, W, H) | None
        self._pending = None             # 'gpos' / 'mpos' while waiting for a click on the map
        self._drag = None
        self._lbl = None

    # ---- what the Gates pane calls -------------------------------------------- #
    @property
    def active_gate(self):
        g = self.doc.gen
        if self.gate_index is None:
            return None
        try:
            return g.patterns[self.gate_index[0]][self.gate_index[1]]
        except IndexError:
            return None

    def set_active_gate(self, idx):
        self.gate_index = tuple(idx) if idx is not None else None
        if self.pane is not None:
            self.pane.refresh()
        self.redraw()

    def apply(self, label, _aspects, fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - report the refusal, keep the view alive
            messagebox.showerror("Not applied", f"{label}:\n{err_text(e)}")
            return False
        self._changed(label)
        return True

    def status(self, msg):
        self.app.status.config(text=msg)

    def start_add(self, kind):
        if self.active_gate is None:
            self.status("Select a gate first.")
            return
        if not self.map:
            self.status("There is no map picture to click: add positions in the map editor.")
            return
        self._pending = kind
        self.status("Click the map picture to place the new %s." % ("gate position" if kind == "gpos"
                                                                    else "monster spawn point"))

    def _changed(self, label):
        self.tab.cur_data = self.doc.gen.build()
        if self.pane is not None:
            self.pane.refresh()
        self.redraw()
        self.status(label + "  — Save table… (or Extract…) writes the file")

    # ---- the map row ------------------------------------------------------------- #
    def build_map_row(self, maps):
        from guiutil import Tip
        from map_editor import data as med
        from rf4s_modkit import map_names as mn
        app = self.app
        row = ttk.Frame(self.tab.content)
        row.pack(fill="x", padx=6, pady=(2, 4))
        self.map = maps[0][0] if maps else None
        if not maps:
            ttk.Label(row, text="No map uses this table (its name matches no map).",
                      foreground="#777").pack(side="left")
        else:
            def place(n):
                mid = med.map_id(n)
                where = mn.describe_destination(mid)[0] if mid is not None else ""
                return med.map_base(n) + (f"  ({where})" if where else "")
            ttk.Label(row, text="Map:").pack(side="left")
            if len(maps) > 1:
                var = tk.StringVar(value=place(maps[0][0]))
                cb = ttk.Combobox(row, textvariable=var, state="readonly", width=46,
                                  values=[place(n) for n, _i in maps])
                cb.pack(side="left", padx=4)
                Tip(cb, "The maps that use this table (seasonal versions share it). The picture "
                        "shows the one picked here.")

                def pick(_e=None):
                    self.map = maps[cb.current()][0]
                    self.redraw()
                cb.bind("<<ComboboxSelected>>", pick)
            else:
                ttk.Label(row, text=place(maps[0][0]), font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)
            ob = ttk.Button(row, text="Open in map editor", command=lambda: app._open_map_encounters(self.map))
            ob.pack(side="left", padx=8)
            Tip(ob, "Open this map in the full map editor, on its Gates tab.")
        sb = ttk.Button(row, text="Save table…", command=self.save)
        sb.pack(side="right")
        Tip(sb, "Write this Gen file (with your edits) to disk.")

    def save(self):
        blob = self.doc.gen.build()
        self.tab.cur_data = blob
        f = filedialog.asksaveasfilename(defaultextension=".bin", initialfile=pathlib.Path(self.name).name,
                                         filetypes=[("Gen table", "*.bin"), ("All", "*.*")])
        if f:
            pathlib.Path(f).write_bytes(blob)
            self.app._mark_saved(self.tab)
            self.status(f"Saved the monster spawns → {f}")

    # ---- the flat map picture ------------------------------------------------------- #
    def _grid(self):
        """(W, H) of the current map's ATTR grid (cached), or None."""
        if not self.map:
            return None
        cache = self.__dict__.setdefault("_grids", {})
        if self.map not in cache:
            try:
                blob = self.app.source.read_named(self.map)
                grid = rf4m.Rf4mMap.parse(blob).attr_grid() if blob else None
                cache[self.map] = (grid[0], grid[1]) if grid else None
            except Exception:  # noqa: BLE001
                cache[self.map] = None
        return cache[self.map]

    def picture_size(self):
        """(width, height) the picture will have: PICTURE_PX on the long side, the map's
        aspect ratio -- known from the ATTR grid before any image is decoded."""
        g = self._grid()
        if not g:
            return None
        W, H = g
        if W >= H:
            return self.PICTURE_PX, max(1, round(self.PICTURE_PX * H / W))
        return max(1, round(self.PICTURE_PX * W / H)), self.PICTURE_PX

    def presize_pane(self, width):
        """Give the Gates pane's scroll area its final width before it is shown, so it is
        laid out once (guiutil.ScrollFrame would otherwise size it on its first <Configure>)."""
        pane = self.pane
        sb = next((c for c in pane.winfo_children() if isinstance(c, ttk.Scrollbar)), None)
        w = max(50, width - (sb.winfo_reqwidth() if sb is not None else 0))
        pane.canvas.configure(width=w)
        pane.canvas.itemconfigure(pane._win, width=w)
        pane._seen_w = w

    def build_picture(self, parent, size=None):
        f = ttk.Frame(parent)
        f.pack(side="left", fill="y", padx=(6, 6))
        self._lbl = tk.Label(f, bd=0, cursor="crosshair")
        if size:                             # the final size now; the picture is drawn into it
            self._blank = tk.PhotoImage(width=size[0], height=size[1])
            self._lbl.config(image=self._blank)
        self._lbl.pack(anchor="n")
        self._lbl.bind("<ButtonPress-1>", self._press)
        self._lbl.bind("<B1-Motion>", self._motion)
        self._lbl.bind("<ButtonRelease-1>", self._release)
        ttk.Label(f, text="\u25c6 gate   \u25cf monster point   (drag to move; the selected gate's are bright)",
                  foreground="#666", font=("Segoe UI", 8)).pack(anchor="w")

    def _picture(self):
        """(scaled picture, pixels per map tile) for the current map, or None."""
        if not self.map:
            return None
        if self.map not in self._ground:
            got = None
            try:
                from map_editor import data as med
                from rf4s_modkit import mapground
                from PIL import Image
                src = self.app.source
                grid, size = self._grid(), self.picture_size()
                comp = mapground.stitch_composite(src.read_named, med.map_base(self.map),
                                                  aspect=grid) if grid else None
                if grid and comp:
                    img = comp[0].convert("RGB").resize(size, Image.BILINEAR)
                    got = (img, size[0] / grid[0])
            except Exception:  # noqa: BLE001 - no picture; the pane still works
                got = None
            self._ground[self.map] = got
        return self._ground[self.map]

    def _points(self):
        """[(kind, rec_off, x, y, mine)] for every gate / monster position in the file."""
        g, active = self.doc.gen, self.active_gate
        out, seen = [], set()
        for _pi, _ei, e in g.all_entries():
            mine = e is active
            for kind, pts in (("mpos", g.monster_positions_off(e)), ("gpos", g.gate_positions_off(e))):
                for off, x, y in pts:
                    if (kind, off) in seen and not mine:
                        continue
                    seen.add((kind, off))
                    out.append((kind, off, x, y, mine))
        out.sort(key=lambda p: (p[4], p[0] == "gpos"))          # the selected gate's on top
        return out

    def redraw(self):
        if self._lbl is None:
            return
        got = self._picture()
        if not got:
            self._lbl.config(image="", text="(no map picture)", width=30, height=10)
            return
        from PIL import ImageDraw, ImageTk
        base, ppt = got
        img = base.copy()
        d = ImageDraw.Draw(img)
        dim = self.active_gate is not None
        for kind, off, x, y, mine in self._points():
            if self._drag and self._drag[1] == off and self._drag[0] == kind:
                x, y = self._drag[2], self._drag[3]
            cx, cy = x / 8 * ppt, y / 8 * ppt
            lit = mine or not dim
            edge = "#ffffff" if (mine and dim) else "#000000"
            if kind == "mpos":
                r = 4 if mine else 3
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill="#e0443a" if lit else "#7a3a36", outline=edge)
            else:
                r = 8 if mine else 6
                d.polygon((cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy),
                          fill="#f0a020" if lit else "#7a5a20", outline=edge)
        self._photo = ImageTk.PhotoImage(img)
        self._lbl.config(image=self._photo, text="")

    def _to_gen(self, ev):
        got = self._picture()
        if not got:
            return None
        ppt = got[1]
        return int(round(ev.x / ppt * 8)), int(round(ev.y / ppt * 8))

    def _press(self, ev):
        got = self._picture()
        if not got:
            return
        pos = self._to_gen(ev)
        if self._pending:                                    # '+ gate' / '+ spawn', then a click
            kind, self._pending = self._pending, None
            e = self.active_gate
            if e is None:
                return
            g = self.doc.gen
            if kind == "gpos":
                self.apply("Add gate position", "gen", lambda: g.add_gate_position(e, *pos))
            else:
                self.apply("Add monster spawn point", "gen", lambda: g.add_monster_position(e, *pos))
            return
        ppt = got[1]
        best = None
        for kind, off, x, y, mine in self._points():
            dd = (x / 8 * ppt - ev.x) ** 2 + (y / 8 * ppt - ev.y) ** 2
            if dd <= 81 and (best is None or (mine, -dd) > (best[4], -best[5])):
                best = (kind, off, x, y, mine, dd)
        if best is not None:
            self._drag = [best[0], best[1], best[2], best[3]]

    def _motion(self, ev):
        if self._drag:
            pos = self._to_gen(ev)
            if pos:
                self._drag[2], self._drag[3] = pos
                self.redraw()

    def _release(self, _ev):
        if not self._drag:
            return
        kind, off, x, y = self._drag
        self._drag = None
        g = self.doc.gen
        self.apply("Move %s" % ("gate position" if kind == "gpos" else "monster spawn point"), "gen",
                   lambda: g.set_position(off, x, y))


class _Doc:
    """One open file = one tab: its working copy (cur_data), the bytes last loaded or saved
    (so the tab knows it has unsaved changes), its own content frame, and the view state its
    viewer keeps (image, zoom, map editor, animation timers ...), so a hidden tab keeps all
    of it untouched. Viewers take `doc = self._doc` when they build and use doc.<name>."""
    VIEW = ("cur_name", "cur_data", "cur_image", "_pil", "_img_canvas",
            "_export_kind", "_export_text", "_export_data", "_export_arc",
            "_anim_after", "_tex_playing", "_tex_frames", "_tex_fi", "_model_playing", "_skel_after",
            "_map_panel", "_map_view", "_map_view_hide", "_rf4m", "_gen", "_gen_host", "_param",
            "_si", "_bplist_files", "_bntx_lbl", "_ev_textarc", "_ev_textarc_done",
            "_events_new_scene", "_text_tab")

    def __init__(self, frame, on_data=None):
        for name in self.VIEW:
            object.__setattr__(self, name, None)
        self.zoom = 1.0
        self.content = frame            # what the viewers build into
        self.frame = frame
        self.key = None                 # (source label, entry name): the same file opens here
        self.saved = None               # the bytes as loaded or last written to a file
        self.header = "Select an asset"
        self.parked = []                # timers that came due while the tab was hidden
        self.on_data = on_data          # called after cur_data changes (the tab's • mark)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name == "cur_data" and self.on_data is not None:
            self.on_data()

    def map_panel(self):
        """This tab's map editor (built the first time it shows a map), or None."""
        mv = self._map_view
        return mv.get("panel") if mv else None

    def is_dirty(self):
        panel = self._map_panel                     # set while the tab shows a map
        if panel is not None:
            try:
                return panel.is_dirty()
            except tk.TclError:
                return False
        data = self.cur_data
        return data is not None and self.saved is not None and data is not self.saved \
            and data != self.saved

    def title(self):
        name = (self.cur_name or "…").replace("\\", "/").rsplit("/", 1)[-1]
        return name + ("  •" if self.is_dirty() else "")

    def on_hide(self):
        panel = self.map_panel()
        if panel is not None:
            try:
                panel.suspend()                 # stop its background ground decodes
            except tk.TclError:
                pass

    def on_show(self):
        panel = self.map_panel()
        if panel is not None:
            try:
                panel.view.request_ground()     # re-queue whatever the suspend dropped
            except tk.TclError:
                pass
        parked, self.parked = self.parked, []
        for fn in parked:
            fn()


BLENDER_HINT = ("With the toolkit's Blender add-on (blender/rf4s_blender.py, installed once) use "
                "File > Import / Export > RF4S model / motions: it sets 60 fps and fits the "
                "timeline for you. Without it: set Output > Frame Rate to 60 BEFORE File > "
                "Import > glTF 2.0.")


class App:
    # Each open file is a tab (_Doc) that owns its view state: viewers build into
    # `doc = self._doc` (the shown tab) and keep everything on it, never on the App.
    MAP_TABS_ASK = 10       # more open map tabs than this asks first (each keeps an editor)

    def __init__(self, root: tk.Tk, initial=None):
        self.root = root
        self._blank = _Doc(None, on_data=self._mark_later)   # the empty view while no tab is open
        self._doc = self._blank         # the tab the viewers work on
        self._docs: list[_Doc] = []     # open tabs, in tab order
        self._mark_pending = False
        self.source: Source | None = None

        root.title("RF4S Modding Toolkit — Asset Explorer")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.geometry("1280x820")

        self._build_toolbar()
        self._build_body()
        self._build_status()

        if initial:
            self.open_path(pathlib.Path(initial))
        else:
            self.cmd_back_to_game()
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
        # a plain button (looks like its neighbours) that drops its menu down below itself
        self._open_btn = ttk.Button(bar, text="Open ▾", command=self._post_open_menu)
        self._open_menu = om = tk.Menu(self._open_btn, tearoff=False)
        om.add_command(label="File…", command=self.cmd_open_file)
        om.add_command(label="Folder…", command=self.cmd_open_folder)
        self._open_btn.pack(side="left", padx=2, pady=3)
        ttk.Button(bar, text="Game folder…", command=self.cmd_game_folder).pack(side="left", padx=2)
        ttk.Button(bar, text="Options…", command=self.cmd_options).pack(side="left", padx=2)
        # shown only while something other than the game is listed (see load_source)
        self._back_btn = ttk.Button(bar, text="Back to the game", command=self.cmd_back_to_game)
        from guiutil import Tip
        Tip(self._open_btn, "Look at files that aren't part of the game: one file (a .mbundle opens as "
                            "its files), or every file in a folder (a downloaded mod, "
                            "Bundle\\00_mods, exported files).")
        Tip(self._back_btn, "List the game's files again.")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.extract_btn = ttk.Button(bar, text="Extract…", command=self.cmd_extract, state="disabled")
        self.extract_btn.pack(side="left", padx=2)
        self.export_btn = ttk.Button(bar, text="Export View…", command=self.cmd_export, state="disabled")
        self.export_btn.pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="Cutscenes", command=self.cmd_cutscene_editor).pack(side="left", padx=2)
        # the list filters, kept together at the right end of the toolbar
        flt = ttk.Frame(bar)
        flt.pack(side="right", padx=(0, 4))
        ttk.Separator(bar, orient="vertical").pack(side="right", fill="y", padx=6)
        ttk.Label(flt, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        # Debounced: re-filtering ~38k names on EVERY keystroke made typing stutter; wait
        # until the user pauses (Enter applies immediately).
        self._filter_after = None
        self.filter_var.trace_add("write", lambda *_: self._schedule_filter())
        fe = ttk.Entry(flt, textvariable=self.filter_var, width=28)
        fe.pack(side="left", padx=2)
        fe.bind("<Return>", lambda _e: self._apply_filter_now())
        ttk.Label(flt, text="Show:").pack(side="left", padx=(8, 0))
        self.cat_var = tk.StringVar(value=self.ALL_CATS)
        self.cat_cb = ttk.Combobox(flt, textvariable=self.cat_var, state="readonly", width=26,
                                   values=[self.ALL_CATS])
        self.cat_cb.pack(side="left", padx=2)
        self.cat_cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter_now())
        Tip(self.cat_cb, "Show only one kind of file (textures, voice lines, maps...). Works together "
                         "with the Filter box: Maps + 'city' = every town map.")
        Tip(fe, "Show only files whose name contains this text (Enter applies at once).")
        self.group_maps_var = tk.BooleanVar(value=bool(gamepaths.get_setting(GROUP_MAPS_SETTING, True)))
        gm = ttk.Checkbutton(flt, text="Group maps by area", variable=self.group_maps_var,
                             command=self.cmd_group_maps)
        gm.pack(side="left", padx=(8, 0))
        Tip(gm, "List the .rf4m maps under a header per in-game area (Rune Prana, Selphia: "
                "Town Square, ...), each one opens and closes. Off: one flat list of files.")

    def _build_body(self):
        from guiutil import Paned
        paned = Paned(self.root, orient="horizontal")   # no live relayout while dragging
        paned.pack(fill="both", expand=True)
        self._paned = paned
        self._left_collapsed = False

        left = ttk.Frame(paned)
        self._left = left
        paned.add(left, weight=0, minsize=160)   # keeps its width; the content gets the rest
        self.tree = ttk.Treeview(left, columns=("cat", "size"), show="tree headings")
        self._sort = ("name", False)
        for col, text in (("#0", "Asset"), ("cat", "Category"), ("size", "Size")):
            self.tree.heading(col, text=text, command=lambda c=col: self._sort_by(c))
        self.tree.column("cat", width=120, stretch=False)
        self.tree.column("size", width=80, anchor="e", stretch=False)
        vs = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<<TreeviewOpen>>", self._on_group_open)

        self.tree.configure(selectmode="browse")
        # a click opens the file in a new tab; Up / Down (any key) browse in the current tab
        # a click shows the file in this tab, a double click opens a new one; Up / Down browse
        self.tree.bind("<ButtonPress-1>", lambda _e: setattr(self, "_select_by_key", False), add="+")
        self.tree.bind("<KeyPress>", lambda _e: setattr(self, "_select_by_key", True), add="+")
        self.tree.bind("<Double-Button-1>", self._on_tree_double)

        self.right = ttk.Frame(paned)
        paned.add(self.right, weight=3, minsize=300)
        # the active tab's header, then one tab per open file (the blank view while none is)
        hb = ttk.Frame(self.right)
        hb.pack(fill="x", padx=6, pady=(6, 2))
        self.header = ttk.Label(hb, text="Select an asset", anchor="w",
                                font=("Segoe UI", 10, "bold"))
        self.header.pack(side="left", fill="x", expand=True)
        # the open files' tabs (scrolls: ◀ ▶ / the wheel; ▼ lists them all) over the shown page
        from guiutil import TabBar
        self.tabbar = TabBar(self.right, on_select=self._pick_tab, on_close=self.cmd_close_tab,
                             on_menu=self._on_tab_menu)
        self.tab_area = ttk.Frame(self.right)
        self._tab_menu = tk.Menu(self.tabbar, tearoff=False)
        self._tab_menu.add_command(label="Close", command=lambda: self.cmd_close_tab(self._tab_menu_doc))
        self._tab_menu.add_command(label="Close the other tabs",
                                   command=lambda: self.cmd_close_others(self._tab_menu_doc))
        self.root.bind("<Control-w>", lambda _e: self.cmd_close_tab())
        self.root.bind("<Control-Tab>", lambda _e: self._cycle_tab(1) or "break")
        self.root.bind("<Control-Shift-Tab>", lambda _e: self._cycle_tab(-1) or "break")
        try:
            self.root.bind("<Control-ISO_Left_Tab>", lambda _e: self._cycle_tab(-1) or "break")
        except tk.TclError:                     # no such keysym here
            pass
        self._blank.content = self._blank.frame = ttk.Frame(self.right)   # the blank view
        self._blank.frame.pack(fill="both", expand=True)
        self._poll_id = self.root.after(1000, self._poll_marks)
        # stop the poll with the window (a destroyed Tk must not run it)
        self.tabbar.bind("<Destroy>", lambda e: e.widget is self.tabbar and self._stop_poll(), add="+")

    def _build_status(self):
        sb = ttk.Frame(self.root)
        sb.pack(fill="x", side="bottom")
        # what the file list holds ("38410 entries in 6 group(s)", "12 matches") at the right
        self.count_lbl = ttk.Label(sb, text="", anchor="e", relief="sunken", padding=(8, 0))
        self.count_lbl.pack(side="right")
        self.status = ttk.Label(sb, text="", anchor="w", relief="sunken")
        self.status.pack(side="left", fill="x", expand=True)

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
    def load_source(self, factory, game=False):
        """List a new set of files; game=True for the game copy itself (hides Back to the game).
        Open tabs stay open: each holds its own copy of its file."""
        try:
            self.source = factory()
        except Exception as e:
            messagebox.showerror("Open failed", err_text(e))
            return
        self.root.title(f"RF4S Modding Toolkit — {self.source.label}")
        if game:
            self._back_btn.pack_forget()
        else:
            self._back_btn.pack(side="left", padx=2, after=self._open_btn)
        self._cur_iid = None
        self._refresh_tree()

    def _post_open_menu(self):
        b = self._open_btn
        try:
            self._open_menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            self._open_menu.grab_release()

    def cmd_back_to_game(self):
        """List the game copy's files: the archives through the Manifest, or the unpacked
        folders when the archives were removed."""
        if DEFAULT_MANIFEST.is_file() and any(BUNDLE_DIR.glob("*.mbundle")):
            self.load_source(lambda: Source.from_manifest(DEFAULT_MANIFEST), game=True)
        elif EXTRACTED.is_dir():
            self.load_source(lambda: Source.from_folder(EXTRACTED), game=True)
        elif DEFAULT_MANIFEST.is_file():
            self.load_source(lambda: Source.from_manifest(DEFAULT_MANIFEST), game=True)

    def open_path(self, p: pathlib.Path):
        if p.is_dir():
            self.load_source(lambda: Source.from_folder(p))
        elif p.name == "Manifest.plist":
            self.load_source(lambda: Source.from_manifest(p))
        elif p.suffix == ".mbundle":
            self.load_source(lambda: Source.from_bundle(p))
        elif self.source is not None:
            self.open_file_tab(p)
        else:
            self.load_source(lambda: Source.from_file(p))

    def open_file_tab(self, p: pathlib.Path):
        """One file from disk in a new tab, next to the files listed now: the list (the game
        copy) stays, and the tab reads textures, text and the rest from it as for the game's
        own files. A map opened this way saves back to this file (Ctrl+S)."""
        try:
            data = p.read_bytes()
        except OSError as e:
            messagebox.showerror("Open failed", err_text(e))
            return None
        doc = self._open_in_tab(("file", str(p.resolve())), p.name, data, "new")
        if doc is not None:
            self.status.config(text=f"Opened {p} (with {self.source.label})")
        return doc

    def cmd_options(self):
        """The Options window: toolkit settings, applied as soon as they are ticked and kept
        in settings.json. One window at a time (a second click brings it forward)."""
        win = self.__dict__.get("_options_win")
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_set()
            return win
        from map_editor import view as map_view
        win = self._options_win = tk.Toplevel(self.root)
        win.title("Options")
        win.transient(self.root)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Map editor", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._wheel_zooms = tk.BooleanVar(value=map_view.wheel_mode() == "zoom")

        def wheel_changed():
            map_view.set_wheel_mode("zoom" if self._wheel_zooms.get() else "scroll")
        ttk.Checkbutton(body, text="Mouse wheel zooms the map", variable=self._wheel_zooms,
                        command=wheel_changed).pack(anchor="w", pady=(4, 0))
        ttk.Label(body, text="Unticked, the wheel scrolls the map instead. Ctrl+wheel always does "
                             "the other one; Shift+wheel scrolls sideways.",
                  foreground="#666", wraplength=320, justify="left").pack(anchor="w", padx=(20, 0))
        ttk.Button(body, text="Close", command=win.destroy).pack(anchor="e", pady=(12, 0))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        return win

    def cmd_game_folder(self):
        """Show / change the game copy every tool uses (takes effect on the next start)."""
        import game_setup
        before = gamepaths.find_bundle_dir()
        was_unpacked = before is not None and gamepaths.is_unpacked(before)
        if game_setup.run(self.root, current=before) and gamepaths.find_bundle_dir() != before:
            messagebox.showinfo("Game folder", "Saved. Close and start the toolkit again to "
                                "use the new game folder in every tool.", parent=self.root)
        elif before is not None and not was_unpacked and gamepaths.is_unpacked(before):
            messagebox.showinfo("Game folder", "The game files are unpacked. Close and start "
                                "the toolkit again so every tool reads them.", parent=self.root)

    def cmd_open_folder(self):
        d = filedialog.askdirectory(title="Open a folder of files",
                                    initialdir=str(EXTRACTED if EXTRACTED.is_dir() else REPO))
        if d:
            self.load_source(lambda: Source.from_folder(d))

    def cmd_open_file(self):
        """One file; a .mbundle or a Manifest.plist opens as the list of files inside it."""
        f = filedialog.askopenfilename(title="Open a file")
        if f:
            self.open_path(pathlib.Path(f))

    def cmd_group_maps(self):
        try:
            gamepaths.set_setting(GROUP_MAPS_SETTING, bool(self.group_maps_var.get()))
        except OSError:
            pass                                # a read-only toolkit folder: just don't keep it
        self._sort_by(None)                     # re-list, keeping the open groups

    def _insert_leaves(self, parent, idxs, group="", open_areas=False):
        """Insert entries (already in display order) under `parent`; with Group maps by
        area on, the .rf4m ones go under one header per area, ahead of the other files."""
        def leaf(under, i):
            name = self.source.entries[i][0]
            disp = name[len(group) + 1:] if group and name.startswith(group + "/") else name
            self._index[self.tree.insert(under, "end", text=disp, values=self._row_values(i))] = i
        areas, rest = {}, []
        if self.group_maps_var.get():
            for i in idxs:
                a = map_names.map_area(self.source.entries[i][0])
                (areas.setdefault(a, []) if a is not None else rest).append(i)
        else:
            rest = idxs
        for a in sorted(areas, key=str.lower):
            aid = self.tree.insert(parent, "end", text=f"{a}  ({len(areas[a])})", open=open_areas,
                                   values=("Area", ""))
            for i in areas[a]:
                leaf(aid, i)
        for i in rest:
            leaf(parent, i)

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

    ALL_CATS = "All categories"

    def _cat_filter(self):
        """The category key the Show box picks, or None for all."""
        t = self.cat_var.get() if hasattr(self, "cat_var") else self.ALL_CATS
        for key, title, _d in assetcat.CATEGORIES:
            if t.startswith(title + "  (") or t == title:
                return key
        return None

    def _fill_cat_box(self):
        """'Title  (count)' for the categories this source has, in assetcat order."""
        if not self.source:
            self.cat_cb.configure(values=[self.ALL_CATS])
            return
        from collections import Counter
        n = Counter(self.source.categories())
        vals = [self.ALL_CATS] + ["%s  (%d)" % (title, n[key]) for key, title, _d in assetcat.CATEGORIES
                                  if n.get(key)]
        self.cat_cb.configure(values=vals)
        cur = self._cat_filter()
        self.cat_var.set(next((v for v in vals if cur and v.startswith(assetcat.title(cur) + "  (")),
                              self.ALL_CATS))

    @staticmethod
    def _fmt_size(n):
        if n is None:
            return ""
        for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
            if n >= div:
                return "%.1f %s" % (n / div, unit)
        return "%d B" % n

    def _row_values(self, i):
        return (assetcat.title(self.source.categories()[i]), self._fmt_size(self.source.sizes[i]))

    def _sorted(self, idxs):
        """Entry indices in the order the clicked column header asks for."""
        col, rev = self._sort
        src = self.source
        lower = self._lower_names()
        if col == "cat":
            cats = src.categories()
            key = lambda i: (assetcat.title(cats[i]), lower[i])
        elif col == "size":
            key = lambda i: (src.sizes[i] if src.sizes[i] is not None else -1, lower[i])
        else:
            key = lambda i: lower[i]
        return sorted(idxs, key=key, reverse=rev)

    def _sort_by(self, col):
        """Sort by a column header (again = reverse); col None just re-lists."""
        if col is not None:
            col = {"#0": "name"}.get(col, col)
            cur, rev = self._sort
            self._sort = (col, (not rev) if cur == col else False)
        arrow = " \u25bc" if self._sort[1] else " \u25b2"
        for c, text, key in (("#0", "Asset", "name"), ("cat", "Category", "cat"), ("size", "Size", "size")):
            self.tree.heading(c, text=text + (arrow if key == self._sort[0] else ""))
        # re-list, keeping the groups (and area headers) that were open
        def label(iid):
            return self.tree.item(iid, "text").split("  (")[0]
        was_open = {label(g) for g in self.tree.get_children() if self.tree.item(g, "open")}
        areas_open = {(label(g), label(a)) for g in self.tree.get_children()
                      for a in self.tree.get_children(g) if self.tree.item(a, "open")}
        self._refresh_tree()
        for g in self.tree.get_children():
            if label(g) in was_open:
                self.tree.item(g, open=True)            # a group, or an area header at the top
                if g in self._group_indices:
                    self.tree.focus(g)
                    self._on_group_open(None)
            for a in self.tree.get_children(g):
                if (label(g), label(a)) in areas_open:
                    self.tree.item(a, open=True)

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
        if len(self.cat_cb.cget("values")) <= 1:
            self._fill_cat_box()
        cat = self._cat_filter()
        cats = self.source.categories()
        keep = range(n) if cat is None else [i for i in range(n) if cats[i] == cat]

        if flt:
            # Flat search across ALL groups, capped.
            lower = self._lower_names()
            hits = self._sorted([i for i in keep if flt in lower[i]])[:self.FILTER_CAP]
            shown = len(hits)
            by_group = {}
            for i in hits:
                by_group.setdefault(self.source.entries[i][1], []).append(i)
            for group, idxs in by_group.items():
                parent = self.tree.insert("", "end", text=group, open=True) if group else ""
                self._insert_leaves(parent, idxs, group, open_areas=True)
            self.count_lbl.config(text=f"{shown} match{'es' if shown != 1 else ''}"
                                  + (" (capped)" if shown >= self.FILTER_CAP else ""))
            return

        # No text filter: one collapsed node per group (so EVERY group is visible),
        # children loaded lazily on expand. Avoids the old global row cap that
        # only ever filled with the first (alphabetically-first) group. A category
        # filter narrows the groups the same way (no cap: groups load lazily).
        from collections import defaultdict
        gmap = defaultdict(list)
        ungrouped = []
        for i in keep:
            group = self.source.entries[i][1]
            (gmap[group] if group else ungrouped).append(i)
        for group in sorted(gmap):
            gid = self.tree.insert("", "end", text=f"{group}  ({len(gmap[group])})", open=False)
            self._group_indices[gid] = gmap[group]
            self.tree.insert(gid, "end", text="…")   # placeholder -> shows expand arrow
        self._insert_leaves("", self._sorted(ungrouped))
        shown = sum(len(v) for v in gmap.values()) + len(ungrouped)
        self.count_lbl.config(text=(f"{n} entries in {len(gmap)} group(s)" if cat is None else
                                    f"{shown} {assetcat.title(cat).lower()} in {len(gmap)} group(s)"))

    def _on_group_open(self, _evt):
        gid = self.tree.focus()
        if gid in self._group_loaded or gid not in self._group_indices:
            return
        self._group_loaded.add(gid)
        self.tree.delete(*self.tree.get_children(gid))   # drop placeholder
        idxs = self._sorted(self._group_indices[gid])
        group = self.source.entries[idxs[0]][1] if idxs else ""
        self._insert_leaves(gid, idxs[:self.GROUP_CAP], group)
        if len(idxs) > self.GROUP_CAP:
            self.tree.insert(gid, "end", text=f"… (+{len(idxs) - self.GROUP_CAP} more — use Filter)")

    # ---- tabs ------------------------------------------------------------ #
    def _on_close(self):
        for doc in list(self._docs):
            if not self._confirm_close(doc, "close the toolkit"):
                return
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
        self._cur_iid = iid
        by_key = self.__dict__.get("_select_by_key", False)
        self._select_by_key = False
        self._open_iid(iid, "key" if by_key else "click")

    def _on_tree_double(self, e):
        """A double click opens the file in a new tab. Its first click already showed the file
        in the current tab, so that tab gets back what it showed before."""
        iid = self.tree.identify_row(e.y)
        if iid not in self._index:
            return None                         # a group: let it open / close
        self._double_open(iid)
        return "break"

    def _double_open(self, iid):
        name, _group, loader = self.source.entries[self._index[iid]]
        key = self._entry_key(name)
        last = self.__dict__.get("_last_replace")
        self._last_replace = None
        if last and last["key"] == key and last["doc"] in self._docs and last["doc"].key == key:
            doc, prev = last["doc"], last["prev"]
            self._show(prev["name"], prev["data"], doc)           # the tab's own file again
            doc.key, doc.saved = prev["key"], prev["data"]
            self._retitle(doc)
            try:
                data = loader()
            except Exception as ex:
                messagebox.showerror("Read failed", str(ex))
                return
            self._open_in_tab(key, name, data, "new")
        elif not any(d.key == key for d in self._docs):
            self._open_iid(iid, "new")

    def _pick_tab(self, doc):
        """A tab chosen in the tab bar: shown, and the one clicks and Up / Down fill from now."""
        self._select_doc(doc)
        self._browse_doc = doc

    def _entry_key(self, name):
        return (self.source.label if self.source else "", name)

    def _open_iid(self, iid, mode="new"):
        name, _group, loader = self.source.entries[self._index[iid]]
        key = self._entry_key(name)
        data = None
        if not any(d.key == key for d in self._docs):      # an open tab needn't re-read it
            try:
                data = loader()
            except Exception as e:
                messagebox.showerror("Read failed", err_text(e))
                return
            self.tree.set(iid, "size", human(len(data)))
        self._open_in_tab(key, name, data, mode)

    def _open_in_tab(self, key, name, data, mode="new"):
        """Show a file: in the tab that already has it; else, by `mode` --
          "click" (a click in the file list): in the tab shown now,
          "key"   (Up / Down): in the tab being browsed (the last one a click, a browse step or
                  a tab-bar pick filled), so stepping onto an open file doesn't take its tab,
          "new"   (a double click, or opened from code): in a new tab --
        where a tab with unsaved changes is never replaced (a new tab instead: nothing is
        thrown away). The tab (_Doc), or None when the user declined."""
        doc = next((d for d in self._docs if d.key == key), None)
        if doc is not None:
            self._select_doc(doc)
            if mode != "key":                   # clicked / opened: browse from that tab now
                self._browse_doc = doc
            return doc
        target = None
        if mode in ("click", "key"):
            b = self.__dict__.get("_browse_doc") if mode == "key" else self._doc
            if b not in self._docs and mode == "key":
                b = self._doc
            if b in self._docs and not b.is_dirty():
                target = b
        new_map_editor = target is None or target.map_panel() is None
        if name.lower().endswith(".rf4m") and new_map_editor and not self._ok_to_open_map_tab():
            return None
        # remember what a click replaced: a double click (which starts with that click) puts it back
        self._last_replace = ({"doc": target, "key": key, "prev": {
            "key": target.key, "name": target.cur_name, "data": target.cur_data}}
            if target is not None and mode == "click" else None)
        doc = target or self._new_doc()
        self._browse_doc = doc
        self._select_doc(doc)
        doc.key, doc.saved = key, data
        self._show(name, data)
        self._retitle(doc)
        return doc

    def _ok_to_open_map_tab(self):
        n = sum(1 for d in self._docs if d.map_panel() is not None)
        if n < self.MAP_TABS_ASK or self.__dict__.get("_map_tabs_no_ask"):
            return True
        import guiutil
        ok, stop = guiutil.ask_yes_no_optout(
            self.root, "Open another map",
            f"{n} maps are open in tabs, and each keeps its own map editor (memory and texture "
            "decoding). Open another one anyway?\n\nClosing map tabs you are done with keeps "
            "the toolkit quick.", yes="Open it", optout="Don't warn me again this session")
        if stop:
            self._map_tabs_no_ask = True        # until the toolkit is closed (not saved)
        return ok

    def _new_doc(self):
        frame = ttk.Frame(self.tab_area)
        doc = _Doc(frame, on_data=self._mark_later)
        self._docs.append(doc)
        self.tabbar.add(doc, "…")
        if len(self._docs) == 1:                # the first tab replaces the blank view
            self._blank.frame.pack_forget()
            self.tabbar.pack(fill="x", padx=2)
            self.tab_area.pack(fill="both", expand=True)
        return doc

    def _select_doc(self, doc):
        """Show `doc`'s page and tab, and make it the one the viewers work on."""
        if doc is not self._blank:
            if doc.frame.winfo_manager() != "pack":
                for d in self._docs:
                    if d is not doc and d.frame.winfo_manager():
                        d.frame.pack_forget()
                doc.frame.pack(fill="both", expand=True)
            self.tabbar.select(doc)
        self._activate(doc)

    def _cycle_tab(self, step):
        """Ctrl+Tab / Ctrl+Shift+Tab: the next / previous tab (wraps around)."""
        if len(self._docs) > 1 and self._doc in self._docs:
            i = self._docs.index(self._doc)
            self._select_doc(self._docs[(i + step) % len(self._docs)])

    def _activate(self, doc):
        """Make `doc` the tab the viewers work on (_select_doc shows its page)."""
        old = self._doc
        if doc is old:
            return
        old.header = self.header.cget("text")
        old.on_hide()
        self._doc = doc
        self.header.config(text=doc.header)
        self.extract_btn.config(state="normal" if doc.cur_data is not None else "disabled")
        self.export_btn.config(state="normal" if doc._export_kind else "disabled")
        doc.on_show()

    def _on_tab_menu(self, doc, e):
        self._tab_menu_doc = doc
        self._tab_menu.tk_popup(e.x_root, e.y_root)

    def cmd_close_tab(self, doc=None):
        """Close a tab (the current one by default); asks first when it has unsaved changes."""
        doc = doc or self._doc
        if doc is self._blank or doc not in self._docs:
            return False
        if not self._confirm_close(doc, "close this tab"):
            return False
        self._drop_doc(doc)
        return True

    def cmd_close_others(self, keep):
        for doc in [d for d in self._docs if d is not keep]:
            if not self.cmd_close_tab(doc):
                break
        if keep in self._docs:
            self._select_doc(keep)

    def _confirm_close(self, doc, action):
        """True when `doc` may go: nothing unsaved, or the user saved or discarded it."""
        if not doc.is_dirty():
            return True
        self._select_doc(doc)                   # show what the question is about
        panel = doc._map_panel
        if panel is not None:
            try:
                return panel.confirm_discard(action)
            except tk.TclError:
                return True
        ans = messagebox.askyesnocancel(
            "Unsaved changes", f"{doc.title().rstrip(' •')} has changes that are not saved to a "
            f"file.\n\nSave it before you {action}?\n(Yes = save with Extract…, No = discard, "
            "Cancel = stay here)", parent=self.root)
        if ans is None:
            return False
        return bool(self.cmd_extract()) if ans else True

    def _drop_doc(self, doc):
        for k in ("_anim_after", "_skel_after"):
            t = getattr(doc, k)
            if t:
                try:
                    self.root.after_cancel(t)
                except tk.TclError:
                    pass
        doc.parked = []
        i = self._docs.index(doc)
        self._docs.remove(doc)
        if doc is self._doc:
            nxt = self._docs[min(i, len(self._docs) - 1)] if self._docs else self._blank
            self._activate(nxt)
        else:
            doc.on_hide()
        self.tabbar.remove(doc)
        doc.frame.destroy()
        if not self._docs:                      # back to the blank view
            self.tabbar.pack_forget()
            self.tab_area.pack_forget()
            self._blank.frame.pack(fill="both", expand=True)
        else:
            self._select_doc(self._doc)         # the neighbour activated above: show its page

    def _retitle(self, doc):
        if doc in self._docs:
            try:
                self.tabbar.set_text(doc, doc.title())
            except tk.TclError:
                pass

    def _mark_later(self):
        """A working copy changed: update the tabs' unsaved marks once the change is done."""
        if not self.__dict__.get("_mark_pending", True) and "tabbar" in self.__dict__:
            self._mark_pending = True
            self.root.after_idle(self._refresh_marks)

    def _refresh_marks(self):
        self._mark_pending = False
        for d in self._docs:
            self._retitle(d)

    def _poll_marks(self):
        # saves that don't change the working copy (the map editor's Save) clear the mark here
        self._poll_id = None
        try:
            self._refresh_marks()
            self._poll_id = self.root.after(1000, self._poll_marks)
        except tk.TclError:
            pass

    def _stop_poll(self):
        if self.__dict__.get("_poll_id"):
            try:
                self.root.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None

    def _doc_after(self, ms, fn):
        """root.after for a view's timer (animations): it runs only while its tab is shown;
        one that comes due in a hidden tab waits and runs when that tab is shown again."""
        doc = self._doc

        def run():
            if doc is self._doc:
                fn()
            elif doc in self._docs:
                doc.parked.append(fn)
        return self.root.after(ms, run)

    def _set_doc_data(self, doc, data):
        """A tab-bound editor (the map editor) changed its tab's working copy."""
        doc.cur_data = data                     # (the doc's on_data updates the • mark)

    def _mark_saved(self, doc=None):
        """A tab's working copy (the shown one by default) was just written to a file: the tab
        has no unsaved changes."""
        doc = doc or self._doc
        doc.saved = doc.cur_data
        self._retitle(doc)

    # ---- viewer dispatch ------------------------------------------------- #
    def _clear_content(self, doc=None):
        doc = doc or self._doc
        if getattr(doc, "_anim_after", None):     # stop a running flipbook animation
            self.root.after_cancel(doc._anim_after)
        doc._anim_after = None
        doc._tex_playing = False
        doc._model_playing = False
        doc._tex_frames = None
        mv = getattr(doc, "_map_view", None)
        for w in doc.content.winfo_children():
            if mv is not None and w is mv["nb"]:
                # Kept for the next map (see _view_rf4m) and deliberately left MAPPED here:
                # un-mapping and re-mapping it re-paints every themed widget of the editor
                # (~0.1-0.9 s on Windows) on each map-to-map click. _show hides it once it
                # knows the new view is not a map.
                doc._map_view_hide = True
                continue
            w.destroy()
        doc._map_panel = None      # not shown: never guard/export a hidden panel
        doc.cur_image = None
        doc._pil = None
        if doc is self._doc:
            self.export_btn.config(state="disabled")
        doc._export_kind = None

    def _show(self, name: str, data: bytes, doc=None):
        """Build the viewer for (name, data) in a tab (the shown one by default; another tab
        is brought to the front first: viewers build into the tab being shown)."""
        doc = doc or self._doc
        if doc is not self._doc:
            self._select_doc(doc)
        self._clear_content(doc)
        # The shown bytes ARE the working copy: every editing panel reads/writes
        # doc.cur_data, so keep it in sync whatever path called us (file browser,
        # a panel re-rendering after an edit, or a programmatic open).
        doc.cur_name, doc.cur_data = name, data
        self.extract_btn.config(state="normal")
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
            self._hide_map_view_if_unused(doc)
        except Exception as e:
            self._clear_content(doc)   # drop any partial widgets the failed handler packed
            self._view_hex(name, data, error=str(e))
            self._hide_map_view_if_unused(doc)

    def _hide_map_view_if_unused(self, doc=None):
        """After a view is built: hide the kept map editor unless that view used it."""
        doc = doc or self._doc
        mv = getattr(doc, "_map_view", None)
        if mv is None or not getattr(doc, "_map_view_hide", False):
            return
        doc._map_view_hide = False
        try:
            mv["nb"].pack_forget()
            mv["panel"].suspend()           # stop its background texture decode
        except tk.TclError:
            pass

    # ---- per-type views -------------------------------------------------- #
    def _view_texture(self, name, data):
        doc = self._doc
        if not HAS_PIL:
            self._view_hex(name, data, error="Pillow not installed (pip install Pillow)")
            return
        info = texture.parse(data)
        nframes = info.get("frames", 1)
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        head = f"{info['fmt_name']}  {info['width']}x{info['height']}  (code 0x{info['fmt_code']:X})"
        if nframes > 1:
            head += f"   flipbook: {nframes} frames"
        ttk.Label(bar, text=head).pack(side="left", padx=6)
        for z, lbl in ((0.5, "½×"), (1, "1×"), (2, "2×"), (4, "4×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z, doc)).pack(side="left")
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
        doc._pil = frames[0]
        doc._img_canvas = self._make_image_canvas(doc=doc)
        self._set_zoom(2.0 if max(frames[0].size) <= 64 else 1.0, doc)  # tiny flipbook cells: zoom in
        doc._export_kind = "png"
        self.export_btn.config(state="normal")
        if len(frames) > 1:
            # Flipbook controls: prev/next, play/stop (~8 fps default; in-game
            # speed is per-MOBJ-record f9, unknown here), and GIF export.
            doc._tex_frames = frames
            doc._tex_fi = 0
            fl = ttk.Label(bar, text=f"frame 1/{len(frames)}")

            def show(i):
                doc._tex_fi = i % len(doc._tex_frames)
                doc._pil = doc._tex_frames[doc._tex_fi]
                fl.config(text=f"frame {doc._tex_fi + 1}/{len(doc._tex_frames)}")
                self._set_zoom(doc.zoom, doc)

            def tick():
                doc._anim_after = None
                if getattr(doc, "_tex_playing", False):
                    show(doc._tex_fi + 1)
                    doc._anim_after = self._doc_after(120, tick)

            def toggle():
                doc._tex_playing = not getattr(doc, "_tex_playing", False)
                pb.config(text="Stop" if doc._tex_playing else "Play")
                if doc._tex_playing and doc._anim_after is None:
                    tick()

            ttk.Button(bar, text="◀", width=3, command=lambda: show(doc._tex_fi - 1)).pack(side="left", padx=(10, 0))
            fl.pack(side="left", padx=4)
            ttk.Button(bar, text="▶", width=3, command=lambda: show(doc._tex_fi + 1)).pack(side="left")
            pb = ttk.Button(bar, text="Play", width=5, command=toggle)
            pb.pack(side="left", padx=4)
            ttk.Button(bar, text="GIF…", width=5,
                       command=lambda: self._export_texture_gif(name)).pack(side="left")
            doc._tex_playing = False
            doc._anim_after = None

    def _import_model_obj(self, name, obj_path=None, choose=None):
        """Import OBJ… on a .model tab: pick the OBJ, map its objects onto the model's shapes
        (same-named object preselected, 'keep' for the others) and replace those shapes'
        geometry (modelwrite.import_obj, any vertex / triangle count). The result is the tab's
        working copy (cur_data) like the other editors. `obj_path` / `choose(model, objects)
        -> {shape index: object name}` skip the dialogs (tests)."""
        from rf4s_modkit import model as _model, modelwrite as _mw
        doc = self._doc
        if doc.cur_data is None:
            return False
        f = obj_path or filedialog.askopenfilename(title="Import OBJ (geometry)",
                                                   filetypes=[("Wavefront OBJ", "*.obj"), ("All files", "*.*")])
        if not f:
            return False
        try:
            text = pathlib.Path(f).read_text(encoding="utf-8", errors="replace")
            objs = [o for o in _mw.parse_obj(text) if o.triangles]
            m = _model.parse(doc.cur_data)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import OBJ", err_text(e))
            return False
        if not objs:
            messagebox.showerror("Import OBJ", f"{pathlib.Path(f).name} has no faces.")
            return False
        plan = (choose or self._obj_import_dialog)(m, objs)
        if not plan:
            return False
        blob = doc.cur_data
        try:
            for si, oname in sorted(plan.items()):
                blob = _mw.import_obj(blob, si, text, object_name=oname)
            _model.parse(blob)                     # the result must read back
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import OBJ", f"Nothing was changed:\n{err_text(e)}")
            return False
        if blob == doc.cur_data:
            self.status.config(text=f"{pathlib.Path(f).name}: the geometry is unchanged")
            return True
        before = len(doc.cur_data)
        doc.cur_data = blob
        self._show(name, blob, doc)
        self.status.config(text=f"Imported {len(plan)} shape(s) from {pathlib.Path(f).name} -> "
                                f"{len(blob):,} bytes (was {before:,}); Extract to save the working copy")
        return True

    def _import_model_glb(self, name, glb_path=None, choose=None, bones=None, add=None, new=None):
        """Import from Blender… on a .model tab: read a .glb / .gltf (Export for Blender,
        edited and exported by Blender), put each mesh on the shape of the same name (a dialog
        shows the pairing; `choose(model, meshes, defaults) -> {shape index: mesh name}` skips
        it in tests) and rebuild those shapes with the file's positions, normals, UVs and bone
        weights (meshimport.import_glb). "(remove)" hides a shape (kept in the file as one degenerate
        triangle, so shape numbers do not shift); meshes with no shape can be appended to one
        (`add` = {mesh name: shape index} skips that dialog); a moved rest pose is offered
        (`bones` answers it). The result is the tab's working copy."""
        from rf4s_modkit import model as _model, meshimport as _mi, gltf as _gltf
        REMOVE = "(remove)"
        doc = self._doc
        if doc.cur_data is None:
            return False
        f = glb_path or filedialog.askopenfilename(title="Import from Blender (glTF .glb)",
                                                   filetypes=[("glTF", "*.glb *.gltf"), ("All files", "*.*")])
        if not f:
            return False
        try:
            m = _model.parse(doc.cur_data)
            meshes = _mi.read_meshes(f, m)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import from Blender", err_text(e))
            return False
        if not meshes:
            messagebox.showerror("Import from Blender", f"{pathlib.Path(f).name} has no triangle meshes.")
            return False
        auto, _rest = _mi.match_shapes(m, meshes)
        defaults = {si: me.name for si, me in auto.items()}
        if choose is not None:
            plan = choose(m, meshes, defaults)
        else:
            plan = self._obj_import_dialog(
                m, meshes, title="Import from Blender -- which mesh replaces which shape",
                what="a mesh of the file", named="Export for Blender", defaults=defaults,
                extra=(REMOVE,))
        if not plan:
            return False
        remove = [si for si, v in plan.items() if v == REMOVE]
        plan = {si: v for si, v in plan.items() if v != REMOVE}
        loose = [me for me in meshes if me.name not in plan.values()]
        if add is None and new is None and loose and choose is None:
            add, new = self._glb_add_dialog(m, loose)
        add = {k: v for k, v in (add or {}).items()}
        new = {k: v for k, v in (new or {}).items()}
        try:
            gl = _gltf.read_gltf(f)
            moved, _notes = _mi.rest_pose_changes(m, gl)
            take = bool(moved) and (bones if bones is not None else messagebox.askyesno(
                "Import from Blender",
                f"The file moves the rest pose of {len(moved)} bone(s) ("
                + ", ".join(m.bones[i].name for i in sorted(moved)[:6]) + ("…" if len(moved) > 6 else "")
                + ").\n\nMove them in the model too? The inverse bind matrices and the rigid parts "
                  "follow, so the model looks the same at rest; animations then turn the parts "
                  "about the new pivots.\n\nNo: keep the game's skeleton."))
            if moved:
                blob, rep = _mi.import_glb(doc.cur_data, gl, mapping={si: v for si, v in plan.items()},
                                           remove=remove, bones=take, add=add or None, new=new or None)
            else:
                blob, rep = _mi.import_glb(doc.cur_data, meshes, mapping=plan, remove=remove,
                                           add=add or None, new=new or None)
            _model.parse(blob)                     # the result must read back
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import from Blender", f"Nothing was changed:\n{err_text(e)}")
            return False
        doc._glb_report = rep
        if blob == doc.cur_data:
            self.status.config(text=f"{pathlib.Path(f).name}: the geometry is unchanged")
            return True
        before = len(doc.cur_data)
        doc.cur_data = blob
        self._show(name, blob, doc)
        changed = rep.changed
        if any(r.moved_influences or r.dropped_influences or r.ignored_weights or r.notes for r in changed):
            messagebox.showinfo("Import from Blender", rep.text())
        self.status.config(text=f"Rebuilt {len(changed)} shape(s)"
                                + (f", moved {len(rep.bones_moved)} bone(s)" if rep.bones_moved else "")
                                + f" from {pathlib.Path(f).name} -> "
                                f"{len(blob):,} bytes (was {before:,}); Extract to save the working copy")
        return True

    def _glb_add_dialog(self, m, meshes):
        """({mesh name: shape index} to append to, {mesh name: template shape index} to make new
        shapes of) for meshes of the file that have no shape (new parts made in Blender)."""
        win = tk.Toplevel(self.root)
        win.title("Import from Blender -- new meshes")
        win.transient(self.root)
        ttk.Label(win, text="These meshes have no shape of their name. A new part can be added to an "
                            "existing shape ('add to'), or become a NEW shape ('new like') that copies "
                            "an existing shape's vertex format and material. Either way it keeps its "
                            "own bone weights. A model holds at most 32 shapes.",
                  wraplength=520, justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        grid = ttk.Frame(win)
        grid.pack(fill="both", expand=True, padx=8)
        IGNORE = "(ignore)"
        shapes = [f"add to {sh.index} {sh.name or 'shape%d' % sh.index}" for sh in m.shapes] + \
                 [f"new like {sh.index} {sh.name or 'shape%d' % sh.index}" for sh in m.shapes]
        vars_ = {}
        for r, me in enumerate(meshes):
            ttk.Label(grid, text=f"{me.name}  ({len(me.triangles)} triangles)").grid(row=r, column=0, sticky="w")
            v = tk.StringVar(value=IGNORE)
            ttk.Combobox(grid, textvariable=v, values=[IGNORE] + shapes, state="readonly",
                         width=max(24, min(48, max(map(len, shapes)) + 2))).grid(row=r, column=1, padx=(8, 0), pady=1)
            vars_[me.name] = v
        add, new = {}, {}

        def ok():
            for k, v in vars_.items():
                t = v.get().split()
                if t[0] == "add":
                    add[k] = int(t[2])
                elif t[0] == "new":
                    new[k] = int(t[2])
            win.destroy()
        b = ttk.Frame(win)
        b.pack(fill="x", padx=8, pady=8)
        ttk.Button(b, text="OK", command=ok).pack(side="right")
        ttk.Button(b, text="Skip", command=win.destroy).pack(side="right", padx=4)
        win.grab_set()
        win.wait_window()
        return add, new

    def _edit_model_materials(self, name, changes=None):
        """Materials… on a .model tab: the settings the game reads from each material (texture
        wrap U / V, and DrawOrder / BlendType / CombineType / CombineColor00 where the material
        carries them -- rf4s_modkit.matedit), edited in place into the tab's working copy.
        `changes` ({material index: set_material keyword arguments}) skips the dialog (tests)."""
        from rf4s_modkit import matedit as _me
        doc = self._doc
        if doc.cur_data is None:
            return False
        try:
            mats = _me.materials(doc.cur_data)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Materials", err_text(e))
            return False
        if changes is None:
            changes = self._material_dialog(mats)
        if not changes:
            return False
        blob = doc.cur_data
        try:
            for mi, kw in sorted(changes.items()):
                blob = _me.set_material(blob, mi, **kw)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Materials", f"Nothing was changed:\n{err_text(e)}")
            return False
        if blob == doc.cur_data:
            self.status.config(text="materials unchanged")
            return True
        doc.cur_data = blob
        self._show(name, blob, doc)
        self.status.config(text=f"Changed {len(changes)} material(s) in place (same size); "
                                f"Extract to save the working copy")
        return True

    def _material_dialog(self, mats):
        """{material index: set_material kwargs} of the settings changed in a dialog, or None."""
        from rf4s_modkit import matedit as _me
        win = tk.Toplevel(self.root)
        win.title("Materials -- what the game reads")
        win.transient(self.root)
        ttk.Label(win, text="Texture wrap applies to every material. DrawOrder (pass 0-3, drawn in "
                            "order), BlendType (0 off, 1 alpha, 2 additive, 3 One/One, 4 One/Zero) and "
                            "CombineType (0 texture, 1 texture lit, 2/3 flat CombineColor) can only be "
                            "changed where the material already has them. Models a map places "
                            "always wrap mirrored (the game overrides the file there).",
                  wraplength=620, justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        grid = ttk.Frame(win)
        grid.pack(fill="both", expand=True, padx=8)
        heads = ("material", "texture", "wrap U", "wrap V", "DrawOrder", "BlendType", "CombineType", "CombineColor00")
        for c, h in enumerate(heads):
            ttk.Label(grid, text=h).grid(row=0, column=c, sticky="w", padx=3)
        rows = {}
        for r, mt in enumerate(mats, start=1):
            ttk.Label(grid, text=f"{mt.index} {mt.name}").grid(row=r, column=0, sticky="w", padx=3)
            ttk.Label(grid, text=mt.texture or "-").grid(row=r, column=1, sticky="w", padx=3)
            v = {}
            for c, k in ((2, 0), (3, 1)):
                var = tk.StringVar(value=_me.WRAP_MODES[mt.wrap[k]] if mt.wrap and mt.wrap[k] < 5 else "")
                ttk.Combobox(grid, textvariable=var, values=_me.WRAP_MODES, width=11,
                             state="readonly" if mt.wrap else "disabled").grid(row=r, column=c, padx=3)
                v["wrap_u" if k == 0 else "wrap_v"] = var
            for c, key, kw in ((4, "DrawOrder", "draw_order"), (5, "BlendType", "blend"), (6, "CombineType", "combine")):
                has = key in mt.user
                var = tk.StringVar(value=str(mt.user[key]) if has else "")
                ttk.Combobox(grid, textvariable=var, values=[str(i) for i in range(_me.USER_INTS[key] + 1)],
                             width=4, state="readonly" if has else "disabled").grid(row=r, column=c, padx=3)
                v[kw] = var
            cc = mt.user.get("CombineColor00")
            var = tk.StringVar(value=", ".join(f"{x:g}" for x in cc) if cc else "")
            ttk.Entry(grid, textvariable=var, width=18, state="normal" if cc else "disabled").grid(row=r, column=7, padx=3)
            v["combine_color"] = var
            rows[mt.index] = (mt, v)
        out = {}

        def ok():
            for mi, (mt, v) in rows.items():
                kw = {}
                for key in ("wrap_u", "wrap_v"):
                    k = 0 if key == "wrap_u" else 1
                    if mt.wrap and v[key].get() and v[key].get() != _me.WRAP_MODES[min(4, mt.wrap[k])]:
                        kw[key] = v[key].get()
                for key, kwn in (("DrawOrder", "draw_order"), ("BlendType", "blend"), ("CombineType", "combine")):
                    if key in mt.user and v[kwn].get() != str(mt.user[key]):
                        kw[kwn] = int(v[kwn].get())
                cc = mt.user.get("CombineColor00")
                if cc:
                    try:
                        new = tuple(float(x) for x in v["combine_color"].get().replace(" ", "").split(","))
                    except ValueError:
                        new = ()
                    if len(new) != 3:
                        messagebox.showerror("Materials", f"{mt.name}: CombineColor00 takes r, g, b")
                        return
                    if any(abs(a - b) > 1e-6 for a, b in zip(new, cc)):
                        kw["combine_color"] = new
                if kw:
                    out[mi] = kw
            win.destroy()
        b = ttk.Frame(win)
        b.pack(fill="x", padx=8, pady=8)
        ttk.Button(b, text="Apply", command=ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=win.destroy).pack(side="right", padx=4)
        win.grab_set()
        win.wait_window()
        return out or None

    def _obj_import_dialog(self, m, objs, *, title="Import OBJ -- which object replaces which shape",
                           what="an OBJ object", named="Export OBJ", defaults=None, extra=()):
        """{shape index: object / mesh name} chosen in a small dialog, or None when cancelled.
        `defaults` ({shape index: name}) preselects; else same-named objects are. `extra` adds
        choices after the names (e.g. "(remove)")."""
        names = [o.name for o in objs]
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        ttk.Label(win, text=f"Each shape keeps its geometry unless {what} is chosen for it. "
                            f"Ones named like a shape (as {named} names them) are preselected.",
                  wraplength=520, justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        grid = ttk.Frame(win)
        grid.pack(fill="both", expand=True, padx=8)
        KEEP = "(keep)"
        choice = {}
        for r, sh in enumerate(m.shapes):
            sname = sh.name or f"shape{sh.index}"
            ttk.Label(grid, text=f"{sh.index}  {sname}  ({len(sh.indices) // 3} triangles)").grid(
                row=r, column=0, sticky="w", pady=1)
            if defaults is not None:
                default = defaults.get(sh.index, KEEP)
            else:
                default = sname if sname in names else (names[0] if len(names) == 1 and len(m.shapes) == 1 else KEEP)
            v = tk.StringVar(value=default)
            ttk.Combobox(grid, textvariable=v, values=[KEEP] + names + list(extra), state="readonly",
                         width=max(20, min(48, max(map(len, names)) + 2))).grid(
                row=r, column=1, sticky="w", padx=(8, 0), pady=1)
            choice[sh.index] = v
        out = {}

        def ok():
            out.update({si: v.get() for si, v in choice.items() if v.get() != KEEP})
            win.destroy()
        b = ttk.Frame(win)
        b.pack(fill="x", padx=8, pady=8)
        ttk.Button(b, text="Import", command=ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=win.destroy).pack(side="right", padx=4)
        win.grab_set()
        win.wait_window()
        return out or None

    def _replace_texture_png(self, name):
        """Re-skin the shown .texture from a PNG, re-encoded in the template frame's own
        format (BC7/BC3/BC1 at the same size, raw kept -- see texture.encode_into). A PNG of
        another size is stored at that size after a confirm listing old -> new and what it
        does in game (texture.size_warnings). For a flipbook only the frame being shown is replaced.
        Updates the working copy (cur_data) like the other editors; Extract writes it."""
        doc = self._doc
        if doc.cur_data is None:
            return
        f = filedialog.askopenfilename(title="Replace texture pixels from PNG…",
                                       filetypes=[("PNG image", "*.png"), ("All images", "*.*")])
        if not f:
            return
        frames = getattr(doc, "_tex_frames", None)
        frame = getattr(doc, "_tex_fi", 0) if frames and len(frames) > 1 else None
        before = len(doc.cur_data)
        try:
            # a PNG of another size is stored at that size (texture.encode_into); say what
            # that does in game (texture.size_warnings) and let the user back out
            changes = texture.size_changes(doc.cur_data, f, frame=frame)
            if changes and not messagebox.askyesno(
                    "Change the texture size?",
                    "The PNG has another size than the texture:\n\n"
                    + texture.size_change_text(changes, texture.size_warnings(doc.cur_data, changes, name=name))
                    + "\n\nStore it at the new size?", icon="warning"):
                return
            blob = texture.encode_into(doc.cur_data, f, frame=frame)
        except Exception as e:
            messagebox.showerror("Replace failed", err_text(e))
            return
        doc.cur_data = blob
        self._show(name, blob, doc)
        which = f"frame {frame + 1} " if frame is not None else ""
        size = "same size, bundle patch-able" if len(blob) == before else f"was {before:,}"
        if changes:
            size += "; " + ", ".join("%dx%d -> %dx%d" % (c["old"] + c["new"]) for c in changes)
        self.status.config(text=f"Replaced {which}pixels from {pathlib.Path(f).name} -> "
                                f"{len(blob):,} bytes ({size}; Extract to save the working copy)")

    def _export_texture_gif(self, name):
        """Save the current flipbook as an animated GIF (120 ms/frame, looped)."""
        doc = self._doc
        frames = getattr(doc, "_tex_frames", None)
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
        doc = self._doc
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
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        info = f"{img.format or '?'}   {img.width}x{img.height}   {img.mode}"
        if n_frames > 1:
            info += f"   ({n_frames} frames -- showing #1)"
        ttk.Label(bar, text=info).pack(side="left", padx=6)
        for z, lbl in ((0.25, "¼×"), (0.5, "½×"), (1, "1×"), (2, "2×"), (4, "4×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z, doc)).pack(side="left")
        # RGBA so alpha shows over the dark canvas and PNG export keeps transparency.
        doc._pil = img.convert("RGBA")
        doc._img_canvas = self._make_image_canvas(doc=doc)
        # fit large images to the viewport on open; small ones show 1:1.
        self._set_zoom(self._fit_zoom(img.width, img.height, doc), doc)
        doc._export_kind = "png"
        self.export_btn.config(state="normal")

    def _fit_zoom(self, w, h, doc=None):
        """Pick an initial zoom so a large image fits the content pane (never upscales)."""
        doc = doc or self._doc
        try:
            doc.content.update_idletasks()
            cw = max(64, doc.content.winfo_width() - 24)
            ch = max(64, doc.content.winfo_height() - 48)
        except Exception:  # noqa: BLE001
            return 1.0
        if w <= cw and h <= ch:
            return 1.0
        return max(0.05, min(cw / w, ch / h))

    def _navigate_to_map(self, map_name, doc=None):
        """Ctrl+click-a-warp handler from the embedded map editor: find {map_name}.rf4m in the
        current source, load it, and re-render (keeping cur_name/cur_data in sync)."""
        doc = doc or self._doc
        if not self.source:
            return
        target = f"{map_name}.rf4m".lower()
        for name, _group, loader in self.source.entries:
            base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if base == target:
                try:
                    data = loader()
                except Exception as e:  # noqa: BLE001
                    self.status.config(text=f"navigate failed: {err_text(e)}"); return
                doc.cur_name, doc.cur_data = name, data
                doc.key, doc.saved = self._entry_key(name), data
                self._show(name, data, doc)
                self._retitle(doc)
                return
        self.status.config(text=f"{map_name}.rf4m not found in this source")

    def cutscene_editor(self, focus_bank=None, focus_entry=None, focus_pc=None):
        """The one Cutscene Editor window: brought to the front (and moved to the requested
        bank / scene / statement) when it is already open, so its unsaved edits are never
        split across two copies of rf3.mc; opened otherwise. Returns the CutsceneExplorer."""
        import cutscene_editor
        from guiutil import later
        cur = getattr(self, "_cutscene_ed", None)
        try:
            alive = cur is not None and bool(cur[0].winfo_exists())
        except tk.TclError:
            alive = False
        if alive:
            win, ex = cur
            win.deiconify()
            win.lift()
            win.focus_force()
            if focus_bank is not None:
                ex.show_bank(focus_bank, focus_entry)
                if focus_pc is not None:
                    later(ex.frame, lambda: ex.view.focus_pc(focus_pc))
            return ex
        win = tk.Toplevel(self.root)
        win.title("RF4S Cutscene Editor")
        win.geometry("1200x820")
        ex = cutscene_editor.CutsceneExplorer(
            win, reader=(self.source.read_named if self.source else None),
            status_fn=lambda s: self.status.config(text=s),
            focus_bank=focus_bank, focus_entry=focus_entry, focus_pc=focus_pc)
        self._cutscene_ed = (win, ex)
        return ex

    def _open_scene_editor(self, bank_index, entry_pc, pc=None):
        """Map-editor NPC-spawn marker click -> the Cutscene Editor focused on the exact
        SpawnEventActor line (bank = the map's event bank, scene = entry_pc, statement = pc)."""
        self.cutscene_editor(bank_index, entry_pc, pc)

    def _map_notebook(self, m, name):
        """The map notebook with its 'Map (edit)' tab. Built ONCE and reused for every map:
        building the editor's ~300 widgets took ~0.3 s per click, and each rebuild left the
        previous panel's texture-decode thread running and threw its texture cache away.
        Now switching maps is set_map() on the same panel (stale decodes are cancelled, and
        revisiting a map reuses its decoded ground). Returns (notebook, panel | None)."""
        doc = self._doc
        mv = getattr(doc, "_map_view", None)
        if mv is not None:
            try:
                alive = bool(mv["nb"].winfo_exists())
            except tk.TclError:
                alive = False
            if not alive:
                doc._map_view = mv = None
        if mv is not None:
            nb, panel = mv["nb"], mv["panel"]
            for f in mv["extra"]:
                try:
                    nb.forget(f); f.destroy()
                except tk.TclError:
                    pass
            mv["extra"] = []
            ev = mv.pop("events_tab", None)
            if ev is not None:
                try:
                    ev.destroy()
                except tk.TclError:
                    pass
            doc._map_view_hide = False
            panel.tex_reader = self.source.read_named if self.source else None
            panel.set_map(m, name)
            if not nb.winfo_ismapped() or nb.winfo_manager() != "pack":
                nb.pack(fill="both", expand=True)
            nb.select(mv["mapframe"])
            return nb, panel
        # the editor alone: a notebook whose tab strip is hidden (the Chunks / Hex tabs only
        # come back, with the strip, when the editor cannot be built)
        style = ttk.Style()
        style.layout("MapOnly.TNotebook.Tab", [])
        style.configure("MapOnly.TNotebook", borderwidth=0, tabmargins=0)
        nb = ttk.Notebook(doc.content, style="MapOnly.TNotebook"); nb.pack(fill="both", expand=True)
        try:
            import map_editor
            mapframe = ttk.Frame(nb); nb.add(mapframe, text="Map (edit)")
            panel = map_editor.MapEditorPanel(
                mapframe, m, name,
                status_fn=lambda s_: self.status.config(text=s_),
                on_change=lambda b: self._set_doc_data(doc, b),   # this tab's working copy
                tex_reader=self.source.read_named if self.source else None,
                on_navigate=lambda n: self._navigate_to_map(n, doc),   # Ctrl+click a warp -> that map, here
                on_open_scene=self._open_scene_editor)  # click NPC-spawn marker -> its script line
            nb.select(mapframe)              # open the map editor first
        except Exception as e:
            self.status.config(text=f"map editor unavailable: {err_text(e)}")
            nb.configure(style="TNotebook")  # the Chunks / Hex fallback shows its tabs
            return nb, None                  # not cached: the next map retries the build
        doc._map_view = {"nb": nb, "panel": panel, "mapframe": mapframe, "extra": []}
        return nb, panel

    def _view_rf4m(self, name, data):
        doc = self._doc
        m = rf4m.Rf4mMap.parse(data)
        doc._rf4m = m                       # editable map state (Map tab + MOBJ tab edit this)
        doc._map_panel = None               # reset: a failed embed must not export a stale panel
        nb, panel = self._map_notebook(m, name)
        doc._map_panel = panel
        if panel is not None:               # a map opened from disk saves back to its own file
            key = getattr(doc, "key", None)
            panel.file_path = (pathlib.Path(key[1]) if isinstance(key, tuple) and key
                               and key[0] == "file" else None)
        # cutscene/event tab: this map's scenes from rf3.mc tail[mapId], in the map editor's
        # sidebar next to Gates / Problems
        try:
            self._build_events_tab(panel.nb if panel is not None else nb, name)
        except Exception as e:
            self.status.config(text=f"events tab unavailable: {err_text(e)}")
        if panel is not None:               # the editor alone, no Chunks / Hex tabs
            doc._export_kind = "map_png"
            self.export_btn.config(state="normal")
            return
        # without the editor: a chunk summary and a hex dump
        # summary tab
        txt = self._make_text_tab(nb, "Chunks", doc=doc)
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
        # line up
        hx = self._make_text_tab(nb, "Hex", mono=True, doc=doc)
        hx.insert("end", hexdump(data, limit=len(data)))
        hx.config(state="disabled")

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
        doc = self._doc
        if getattr(doc, "_ev_textarc_done", False):
            return doc._ev_textarc
        doc._ev_textarc_done = True
        doc._ev_textarc = None
        data = self.source.read_named("rf3mc.eng") if self.source else None
        if data:
            try:
                doc._ev_textarc = textdb.TextArchive.parse(data)
            except Exception:
                doc._ev_textarc = None
        return doc._ev_textarc

    def _build_events_tab(self, nb, name):
        """'Events' tab: the cutscene/event scenes tied to THIS map. rf3.mc's 872 tail
        banks are 1:1 with the 872 rooms, so a map's events live in tail[mapId]. Lists
        those scenes with dialogue previews; opens them in the full Cutscene Editor."""
        doc = self._doc
        import map_editor
        frame = ttk.Frame(nb)
        mv = getattr(doc, "_map_view", None)
        if mv is not None and nb is not mv["nb"]:
            nb.insert(mv["panel"].problems, frame, text="Events")    # Problems stays last
            mv["events_tab"] = frame                # replaced when the next map opens
        else:
            nb.add(frame, text="Events")
        info = ttk.Label(frame, anchor="w", justify="left")
        info.pack(fill="x", padx=6, pady=(6, 2))
        # wrap the texts to the sidebar's width, whatever it is
        frame.bind("<Configure>", lambda e: [w.config(wraplength=max(120, e.width - 16))
                                             for w in frame.winfo_children()
                                             if isinstance(w, ttk.Label)], add="+")

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
            info.config(text=f"rf3.mc failed to parse: {err_text(e)}")
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
        hsb = ttk.Scrollbar(lf, orient="horizontal")
        hsb.pack(side="bottom", fill="x")
        lb = tk.Listbox(lf, font=("Consolas", 9), yscrollcommand=sb.set, xscrollcommand=hsb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.config(command=lb.yview)
        hsb.config(command=lb.xview)
        row_entry_pc = []
        for nline, nstmt, epc, ok, preview in entries:
            flag = "" if ok else " [partial]"
            # the dialogue preview first: the sidebar is narrow
            lb.insert("end", f"{nline:>2} lines  {preview or '(no dialogue)'}   "
                             f"@0x{epc:04x}, {nstmt} stmts{flag}")
            row_entry_pc.append(epc)

        def open_editor(_e=None):
            sel = lb.curselection()
            entry_pc = row_entry_pc[sel[0]] if sel else None
            self.cutscene_editor(bank_index, entry_pc)

        def new_scene():
            """'New scene on this map…': open the Cutscene Editor on this map's event (tail)
            bank and go straight into its New-scene dialog with the map-enter type preselected
            (MapEnterScene, type 7 -- taken from the entry-type catalogue when it names it).
            The scene lands in that editor's in-memory rf3.mc: its Save menu / Install
            write it (this tab keeps listing the shipped file)."""
            import cutscene_editor
            ex = self.cutscene_editor(bank_index)
            res = ex.open_new_scene_dialog(bank_index,
                                           default_type=cutscene_editor.map_enter_type())
            if res is not None:
                self.status.config(
                    text=f"new scene @0x{res[0]:04x} minted in event bank {bank_index} (in the "
                         f"editor's rf3.mc — use its Save menu or Install; this tab "
                         f"lists the shipped file)")
            return res

        lb.bind("<Double-Button-1>", open_editor)
        b = ttk.Button(frame, text="Open in Cutscene Editor →", command=open_editor)
        b.pack(fill="x", padx=6, pady=(0, 2))
        nsb = ttk.Button(frame, text="New scene on this map…", command=new_scene)
        nsb.pack(fill="x", padx=6, pady=(0, 2))
        ttk.Label(frame, foreground="#888", justify="left",
                  text="New scene… = mint a map-enter scene (MapEnterScene, type 7) in this "
                       "map's event bank via the editor's New-scene dialog").pack(fill="x", padx=6)
        if ta is None:
            ttk.Label(frame, justify="left", text="(no dialogue previews until rf3mc.<locale> "
                                                  "is in the source)").pack(fill="x", padx=6)
        ttk.Frame(frame, height=4).pack()
        if not entries:
            b.config(state="disabled")
        doc._events_new_scene = new_scene      # headless-test hook (the last built Events tab)

    def _view_textdb(self, name, data):
        """A TEXT archive (rf3Txt* / rf4Txt* / rf3mc.<locale>): the text editor (text_tab.py)."""
        import text_tab
        doc = self._doc
        doc._text_tab = text_tab.TextTab(self, doc, name, data)
        doc._export_kind = "textjson"; doc._export_arc = doc._text_tab.m.arc
        self.export_btn.config(state="normal")

    # plain TEXT routed above; this handles `text` fmt files that are NOT TEXT magic
    def _view_text(self, name, data):
        doc = self._doc
        if data[:4] == b"TEXT":
            return self._view_textdb(name, data)
        try:
            s = data.decode("utf-8")
        except UnicodeDecodeError:
            s = data.decode("latin1")
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        txt.insert("end", s)
        txt.config(state="disabled")

    def _view_bplist(self, name, data):
        doc = self._doc
        root_obj = bplist.loads(data, lazy_data=True)
        tv = ttk.Treeview(doc.content, columns=("val",), show="tree headings")
        tv.heading("#0", text="Key / Index"); tv.heading("val", text="Value")
        tv.column("val", width=700)
        vs = ttk.Scrollbar(doc.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        doc._export_kind = "plistjson"; doc._export_data = data
        self.export_btn.config(state="normal")

        # Manifest.plist: render each bundle directly by name with its files listed
        # under it (lazily on expand), instead of the raw bundles[i].{bundleName,files}.
        bundles = root_obj.get("bundles") if isinstance(root_obj, dict) else None
        if isinstance(bundles, list) and bundles and all(
                isinstance(b, dict) and "bundleName" in b for b in bundles):
            doc._bplist_files = {}
            for b in bundles:
                files = b.get("files", {})
                nfiles = len(files) if isinstance(files, dict) else 0
                node = tv.insert("", "end", text=str(b.get("bundleName")),
                                 values=(f"{nfiles} files",), open=False)
                if nfiles:
                    doc._bplist_files[node] = files
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
        doc = self._doc
        nid = tv.focus()
        files = doc._bplist_files.pop(nid, None)
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
        doc = self._doc
        toks = aibn.load_tokens(data)
        dis = aibn.disassemble(toks, annotate=True)
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        c = aibn.stats(toks)
        txt.insert("end", f"# {name}: {len(toks)} tokens, {sum(c.values())} statements"
                          f"  (sub N: / N: labels, if (...) {{ }} blocks, Action(args); trailing # = verified operand meanings;"
                          f" rf4mod ai ops <op> for details; `rf4mod ai asm` rebuilds the file from this text)\n\n")
        txt.insert("end", dis)
        txt.config(state="disabled")
        doc._export_kind = "disasm"; doc._export_text = dis
        self.export_btn.config(state="normal")

    def _view_emf(self, name, data):
        """em.bin / emdeb.bin -- the Event Manager: the game's trigger rules (what gates
        a marriage, a date, a shop, a sub-event). The exe only runs the VM.

        The decoder/editor for these already lives in the Cutscene editor's **Event Manager**
        window -- entry list, decoded conditions + actions, the rf3.mc scenes that use each
        entry, and byte-safe in-place edits -- so this panel opens that rather than
        duplicating it, and shows the raw container underneath.
        """
        doc = self._doc
        bar = ttk.Frame(doc.content); bar.pack(fill="x", pady=3)
        ttk.Button(bar, text="Open Event Manager\u2026", command=self.cmd_event_manager
                   ).pack(side="left", padx=6)
        ttk.Label(bar, text="272 trigger entries: decoded conditions + actions, "
                            "rf3.mc scene cross-refs, in-place editing "
                            "(CLI: rf4mod.py em list / show / set)."
                  ).pack(side="left")
        self._view_hex(name, data)

    def _view_strings(self, name, data):
        """A .strings file (Localization-<lang>.strings): the text editor (text_tab.py)."""
        import text_tab
        doc = self._doc
        try:
            doc._text_tab = text_tab.TextTab(self, doc, name, data)
        except Exception as e:
            self._view_hex(name, data, error=str(e))

    def _view_res(self, name, data):
        # A .model / .bntx embeds a Nintendo BNTX texture block (the map's over-model
        # scenery atlases, named MOBJ_<map>_NN). Offer a texture browser alongside the
        # raw container structure. BNTX here is LINEAR BC (no Tegra swizzle), so every
        # texture decodes directly. (Falls back to structure-only without Pillow.)
        doc = self._doc
        if data[:4] == b"PSB\x00" and HAS_PIL and self._view_psb(name, data):
            return
        from rf4s_modkit import model as _model
        is_mesh = _model.is_mesh(data)
        if HAS_PIL and (is_mesh or (data.find(b"BNTX") >= 0 and texture.bntx_list(data))):
            nb = ttk.Notebook(doc.content); nb.pack(fill="both", expand=True)
            if is_mesh:
                self._build_model_tab(nb, name, data)
            if data.find(b"BNTX") >= 0 and texture.bntx_list(data):
                self._build_bntx_browser(nb, name, data)
            stxt = self._make_text_tab(nb, "Structure", mono=True, doc=doc)
            stxt.insert("end", res_container.summary(data)); stxt.config(state="disabled")
            nb.select(0)
            return
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        txt.insert("end", res_container.summary(data))
        if data[:4] == b"RES\x00" and not is_mesh:
            txt.insert("end", "\n\n(a UI screen layout: .model files for menus carry no mesh)")
        txt.config(state="disabled")

    def _view_psb(self, name, data):
        """E-mote portrait (.psbData / .emtbytes): the part atlas on a zoomable canvas
        (Export = PNG) with the PSB summary.  Repaint via `rf4mod psb replace-texture`.
        Returns False (caller falls back to the structure view) if it cannot decode."""
        doc = self._doc
        from rf4s_modkit import psb as _psb
        try:
            ps = _psb.PSB(data)
            texs = ps.textures()
            img = _psb.decode_texture(ps, texs[0]) if texs else None
        except Exception:  # noqa: BLE001
            return False
        if img is None:
            return False
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        t = texs[0]
        ttk.Label(bar, text=f"E-mote atlas '{t['source']}'  {t['type']} {t['width']}x{t['height']}"
                            f"  {len(t['icons'])} parts").pack(side="left", padx=6)
        for z, lbl in ((0.25, "¼×"), (0.5, "½×"), (1, "1×"), (2, "2×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z, doc)).pack(side="left")
        info = tk.Text(doc.content, height=9, wrap="word", font=("Consolas", 9))
        info.insert("end", _psb.summary(ps, pathlib.PurePosixPath(name).name)); info.config(state="disabled")
        info.pack(fill="x")
        doc._pil = img
        doc._img_canvas = self._make_image_canvas(doc=doc)
        self._set_zoom(0.5, doc)
        doc._export_kind = "png"
        self.export_btn.config(state="normal")
        return True

    def _build_model_tab(self, nb, name, data):
        """'Model' tab: a textured preview of the meshes (front / back / side / top), the
        shape / material summary, and Export OBJ (geometry + MTL + texture PNGs)."""
        doc = self._doc
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
        # map over-models are flat cards on the ground: top. Everything else opens in the field
        # camera's view (the front, looked down on at ~25 degrees) -- a straight front view
        # shows ground-flat parts edge-on, so some models looked empty
        view = tk.StringVar(value="top" if stem.upper().startswith("MAP_") else "field")
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
                messagebox.showerror("Export OBJ", err_text(e)); return
            self.status.config(text=f"exported {stem}.obj + {len(written) - 1} file(s) to {d}")
        gb = ttk.Button(bar, text="Export for Blender…",
                        command=lambda: self._export_model_glb(m, stem, state.get("skel")))
        gb.pack(side="right", padx=4)
        from guiutil import Tip as _Tip
        _Tip(gb, "Write a .glb that Blender opens with the skeleton ready to pose: the model in "
                 "its rest pose with bones, skin and textures, plus the motion picked in the "
                 "'motion' row as an animation (or none). Animate it in Blender, export a .glb, "
                 "then bring it back with Import motion…. " + BLENDER_HINT)
        bb = ttk.Button(bar, text="Import from Blender…", command=lambda: self._import_model_glb(name))
        bb.pack(side="right", padx=4)
        from guiutil import Tip as _Tip
        _Tip(bb, "Bring meshes edited in Blender back: open the .glb Blender exported (File > "
                 "Export > glTF 2.0, from an Export for Blender file). Each mesh replaces the shape "
                 "of the same name with its positions, normals, UVs AND bone weights (weight "
                 "painting reaches the game; any vertex / triangle count). Meshes you did not "
                 "touch keep their exact bytes. A shape stores a fixed number of bone influences "
                 "per vertex (1 for rigid parts, 2-4 for skinned ones): extra ones are dropped, "
                 "the heaviest kept. The result becomes this tab's working copy.")
        ib = ttk.Button(bar, text="Import OBJ…", command=lambda: self._import_model_obj(name))
        ib.pack(side="right", padx=4)
        from guiutil import Tip as _Tip
        _Tip(ib, "Replace shapes' geometry from an OBJ -- the format Export OBJ writes, edited in "
                 "Blender or any modeller (any vertex / triangle count; positions, normals and UVs "
                 "come from the OBJ, bone weights from the nearest original vertex). Each OBJ "
                 "object replaces the shape of the same name; the dialog lets you change that. "
                 "Materials and textures stay as they are (Replace texture… changes those). "
                 "The result becomes this tab's working copy: save it like any other edit.")
        ttk.Button(bar, text="Export OBJ…", command=export).pack(side="right", padx=4)
        mb = ttk.Button(bar, text="Materials…", command=lambda: self._edit_model_materials(name))
        mb.pack(side="right", padx=4)
        _Tip(mb, "The material settings the game reads: texture wrap (repeat / mirror / clamp …) "
                 "for every material, and draw pass, blend mode and colour combine where the "
                 "material has them. Changed in place (same file size) in this tab's working copy.")
        # the model view on top, the info pane (shapes, materials) under it; the divider moves
        body = ttk.Panedwindow(frame, orient="vertical"); body.pack(fill="both", expand=True)
        cv = tk.Canvas(body, bg="#202024", highlightthickness=0)
        body.add(cv, weight=4)
        infof = ttk.Frame(body)
        txt = tk.Text(infof, height=9, font=("Consolas", 9), wrap="none")
        ys = ttk.Scrollbar(infof, orient="vertical", command=txt.yview)
        xs = ttk.Scrollbar(infof, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        txt.pack(side="left", fill="both", expand=True)
        body.add(infof, weight=1)
        lines = [_model.summary(m), "", "materials:"]
        from rf4s_modkit import matedit as _me
        try:
            wraps = {s.index: s.wrap for s in _me.materials(data)}
        except Exception:  # noqa: BLE001
            wraps = {}
        for mt in m.materials:
            ud = _model.user_data_text(mt)
            w = wraps.get(mt.index)
            wt = (f"  wrap {_me.WRAP_MODES[min(4, w[0])]}/{_me.WRAP_MODES[min(4, w[1])]}") if w else ""
            lines.append(f"  {mt.name}: {', '.join(mt.textures) or '(no texture)'}{wt}" + (f"  [{ud}]" if ud else ""))
        txt.insert("end", "\n".join(lines)); txt.config(state="disabled")
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
            doc._model_playing = False
            tick_ms = 50

            def tick():
                doc._anim_after = None
                if not doc._model_playing or not cv.winfo_exists():
                    return
                state["frame"] = (state["frame"] + 60 * tick_ms / 1000.0) % max(1, anim.frame_count)
                draw()
                doc._anim_after = self._doc_after(tick_ms, tick)

            def toggle():
                doc._model_playing = not doc._model_playing
                pb.config(text="Stop" if doc._model_playing else "Play")
                if doc._model_playing and getattr(doc, "_anim_after", None) is None:
                    tick()
                elif not doc._model_playing:
                    draw()                 # the paused frame at full quality
            pb.config(command=toggle)
        else:
            fl = None
        skel_bar = self._model_skel_controls(frame, name, m, state, view, lambda: draw())

        def draw(_e=None):
            from PIL import ImageTk
            if not cv.winfo_exists():
                return                         # another file was opened meanwhile
            size = max(160, min(cv.winfo_width(), cv.winfo_height()) - 8) if cv.winfo_width() > 1 else 480
            playing = bool(state.get("splaying") or getattr(doc, "_model_playing", False))
            # a playing animation loops over the same frames: keep each rendered frame (up to
            # PLAY_CACHE_FRAMES) and show it again on the next loop instead of re-rendering
            sk = state.get("skel")
            ckey = (id(sk), id(anim), view.get(), size,
                    int(state["sframe"]) if sk is not None else None,
                    int(state["frame"]) if anim is not None else None)
            cache = state.setdefault("fcache", {})
            if playing and ckey in cache:
                state["photo"], im = cache[ckey]
                cv.delete("all")
                cv.create_image(4, 4, anchor="nw", image=state["photo"])
                doc._pil = im
                if skel_bar is not None:
                    skel_bar(state)
                if fl is not None:
                    fl.config(text=f"frame {int(state['frame']):3}/{anim.frame_count}")
                return
            try:
                if sk is not None:             # skeletal animation selected: pose + fixed box
                    from rf4s_modkit import skelanim as _sk
                    m.pose = _sk.pose_bones(m, sk, state["sframe"])
                    box = state["boxes"].get(view.get())
                    if box is None:
                        box = state["boxes"][view.get()] = self._skel_box(m, sk, view.get())
                        m.pose = _sk.pose_bones(m, sk, state["sframe"])
                else:
                    m.pose, box = None, None
                # while a motion / material animation plays, render smaller with the cheap
                # sampler and scale up for display (~3x faster); a still frame stays sharp
                rsize = min(size, self.PLAY_RENDER_PX) if playing else size
                im = _model.render(m, view.get(), rsize, textures=state["textures"], anim=anim,
                                   frame=state["frame"], box=box, fast=playing)
                if rsize < size:
                    k = size / rsize
                    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))),
                                   Image.BILINEAR)
            except Exception as e:  # noqa: BLE001
                info.config(text=f"render failed: {err_text(e)}"); return
            finally:
                m.pose = None
            if skel_bar is not None:
                skel_bar(state)
            state["photo"] = ImageTk.PhotoImage(im)
            if playing:
                if len(cache) >= self.PLAY_CACHE_FRAMES:
                    cache.clear()
                cache[ckey] = (state["photo"], im)
            cv.delete("all")
            cv.create_image(4, 4, anchor="nw", image=state["photo"])
            doc._pil = im
            doc._export_kind = "png"
            self.export_btn.config(state="normal")
            if fl is not None:
                fl.config(text=f"frame {int(state['frame']):3}/{anim.frame_count}")
            info.config(text=f"{sum(len(s.indices) // 3 for s in m.shapes)} triangles · "
                             f"{len(m.bones)} bones · {view.get()} view")
        vc.bind("<<ComboboxSelected>>", draw)

        def resized(_e=None):
            # re-fit the picture when the view is resized (window, or the info-pane divider)
            if state.get("redraw"):
                cv.after_cancel(state["redraw"])
            state["redraw"] = cv.after(150, lambda: (state.update(redraw=None), draw()))
        cv.bind("<Configure>", resized)
        self.root.after_idle(draw)

    def _export_model_glb(self, m, stem, anim=None, path=None):
        """Export for Blender…: the model (rest pose, skeleton, skin, textures) and `anim` as a
        .glb (rf4s_modkit.gltf). `path` skips the dialog (tests). Returns the path or None."""
        from rf4s_modkit import gltf as _gltf
        tag = f"_{anim.name}" if anim is not None else ""
        f = path or filedialog.asksaveasfilename(
            title="Export for Blender (glTF .glb)", defaultextension=".glb",
            initialfile=f"{stem}{tag}.glb", filetypes=[("glTF binary", "*.glb")])
        if not f:
            return None
        try:
            _gltf.export_glb(m, f, anim, stem)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Export for Blender", err_text(e)); return None
        what = f" with the motion {anim.name}" if anim is not None else " (rest pose, no motion)"
        self.status.config(text=f"Exported {pathlib.Path(f).name}{what}. In Blender: File > Import > RF4S "
                                f"model / motions (the add-on in blender/), animate, File > Export > RF4S "
                                f"motions, then Import motion…")
        return f

    def _export_all_motions(self, m, stem, names, src, path=None):
        """Export all motions…: `m` and every motion in `names` (read from `src`) in one .glb,
        one animation each. `path` skips the dialog (tests). Returns (path, exported, skipped)
        or None."""
        from rf4s_modkit import gltf as _gltf, skelanim as _sk
        f = path or filedialog.asksaveasfilename(
            title="Export for Blender -- all motions (glTF .glb)", defaultextension=".glb",
            initialfile=f"{stem}_all_motions.glb", filetypes=[("glTF binary", "*.glb")])
        if not f:
            return None
        anims, skipped = [], []
        self.root.config(cursor="watch"); self.root.update_idletasks()
        try:
            for n in names:
                try:
                    a = _sk.parse(src.read_named(n) or b"")
                except Exception:  # noqa: BLE001
                    skipped.append(n); continue
                if not _sk.bound_bones(m, a)[0]:
                    skipped.append(n); continue
                a.name = pathlib.PurePosixPath(n).stem     # the action name = the file it replaces
                anims.append(a)
            if not anims:
                messagebox.showerror("Export all motions", "None of the motions drive this model's bones.")
                return None
            _gltf.export_glb(m, f, anims, stem)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Export all motions", err_text(e)); return None
        finally:
            self.root.config(cursor="")
        size = pathlib.Path(f).stat().st_size
        self.status.config(text=f"Exported {pathlib.Path(f).name}: {len(anims)} motions ({size / 1e6:.1f} MB)"
                                + (f", skipped {len(skipped)} that drive none of its bones" if skipped else "")
                                + ". In Blender: File > Import > RF4S model / motions (the add-on in "
                                  "blender/), or set Frame Rate 60 before importing as glTF")
        return f, len(anims), skipped

    def _import_all_motions(self, m, names, src, path=None, answer=None):
        """Import all motions…: every animation of a glTF / .glb named like one of `names`
        (motion files of this model) is imported (gltf.import_all_animations); the changed ones
        are offered to install into the game or save to a folder. `path` / `answer` ("install",
        a folder path, or None = cancel) skip the dialogs (tests). Returns [(file name,
        SkelAnimFile)] written, or None."""
        from rf4s_modkit import gltf as _gltf, skelanim as _sk
        f = path or filedialog.askopenfilename(title="Import all motions (glTF / .glb from Blender)",
                                               filetypes=[("glTF", "*.glb *.gltf"), ("All files", "*.*")])
        if not f:
            return None
        templates, stems = {}, {pathlib.PurePosixPath(n).stem: n for n in names}
        self.root.config(cursor="watch")
        try:
            try:
                file_names = {a[1] for a in _gltf.list_animations(f)}
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Import all motions", f"cannot read {pathlib.Path(f).name}:\n{err_text(e)}")
                return None
            for stem_ in file_names & set(stems):
                try:
                    templates[stem_] = _sk.parse(src.read_named(stems[stem_]) or b"")
                except Exception:  # noqa: BLE001
                    pass

            def progress(k, total, nm):
                self.status.config(text=f"Importing motions… {k + 1}/{total} {nm}")
                self.root.update_idletasks()
            res = _gltf.import_all_animations(f, m, templates, progress)
        finally:
            self.root.config(cursor="")
        lines = [f"{len(res['changed'])} changed, {len(res['unchanged'])} unchanged (left alone)"]
        if res["unmatched"]:
            lines.append(f"{len(res['unmatched'])} not named like a motion of this model (ignored): "
                         + ", ".join(res["unmatched"][:6]) + (" …" if len(res["unmatched"]) > 6 else ""))
        if res["failed"]:
            lines.append("failed: " + "; ".join(f"{n}: {e}" for n, e in res["failed"][:4]))
        if res["notes"]:
            lines.insert(0, f"WARNING ({len(res['notes'])} animation(s)): " + next(iter(res["notes"].values()))
                         + " Until then, motions you did not touch show up as changed too.\n")
        summary = "\n".join(lines)
        if not res["changed"]:
            self.status.config(text=f"Import all motions: {lines[0]}")
            messagebox.showinfo("Import all motions", "Nothing to install.\n\n" + summary)
            return None
        chosen = res["changed"]
        if answer is None and not getattr(self, "_testing", False):
            got = self._import_all_dialog(res["changed"], summary)
            if got is None:
                return None
            answer, keep = got
            chosen = [c for c in res["changed"] if c[0] in keep]
        if not answer or not chosen:
            return None
        blobs = {stems[n]: (_sk.build(a), a) for n, a, _d, _t in chosen}
        written = []
        if answer == "install":
            targets = gamepaths.game_targets(list(blobs))
            if targets is None:
                messagebox.showerror("Import all motions", "No game folder is set up."); return None
            for fn, (blob, a) in blobs.items():
                try:
                    gamepaths.write_game_file(targets[fn], blob)
                except OSError as e:
                    messagebox.showerror("Import all motions", f"Could not write {targets[fn]}:\n{err_text(e)}")
                    break
                written.append((fn, a))
            self.status.config(text=f"Installed {len(written)} motion(s) (originals in ModdingBackup) -- "
                                    f"restart the game to see them")
        else:
            d = pathlib.Path(answer)
            d.mkdir(parents=True, exist_ok=True)
            for fn, (blob, a) in blobs.items():
                (d / fn).write_bytes(blob)
                written.append((fn, a))
            self.status.config(text=f"Saved {len(written)} motion(s) to {d}")
        return written

    def _import_all_dialog(self, changed, summary):
        """("install" | folder, {names to write}) or None: the changed motions with a check each."""
        win = tk.Toplevel(self.root)
        win.title("Import all motions")
        win.transient(self.root)
        ttk.Label(win, text=summary, justify="left", wraplength=560).pack(anchor="w", padx=8, pady=(8, 4))
        ttk.Label(win, text="Changed motions (select the ones to write):").pack(anchor="w", padx=8)
        lb = tk.Listbox(win, width=72, height=min(16, len(changed)), selectmode="extended")
        for n, a, deg, trel in changed:
            lb.insert("end", f"{n}   {a.frame_count} frames, up to {deg:.1f}° / {100 * trel:.2f} % moved")
        lb.pack(fill="both", expand=True, padx=8, pady=4)
        lb.selection_set(0, "end")
        out = {}

        def done(kind):
            keep = {changed[i][0] for i in lb.curselection()}
            if kind == "folder":
                d = filedialog.askdirectory(parent=win, title="Save the motions to")
                if not d:
                    return
                kind = d
            out["r"] = (kind, keep)
            win.destroy()
        bar = ttk.Frame(win); bar.pack(fill="x", padx=8, pady=8)
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="Save to folder…", command=lambda: done("folder")).pack(side="right", padx=4)
        ttk.Button(bar, text="Install into game", command=lambda: done("install")).pack(side="right")
        win.grab_set()
        win.wait_window()
        return out.get("r")

    def _import_motion_file(self, m, template, path=None, pick=None):
        """The SkelAnimFile made from a glTF / .glb animation for model `m`, replacing
        `template` (its name, file name and loop flag are kept), or None. `path` / `pick(list)
        -> index` skip the dialogs (tests)."""
        from rf4s_modkit import gltf as _gltf
        f = path or filedialog.askopenfilename(title="Import motion (glTF / .glb from Blender)",
                                               filetypes=[("glTF", "*.glb *.gltf"), ("All files", "*.*")])
        if not f:
            return None
        try:
            anims = _gltf.list_animations(f)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import motion", f"cannot read {pathlib.Path(f).name}:\n{err_text(e)}")
            return None
        if not anims:
            messagebox.showerror("Import motion", f"{pathlib.Path(f).name} has no animation.")
            return None
        k = 0
        if len(anims) > 1:
            want = template.name if template is not None else None
            k = (pick or (lambda a: self._pick_animation(a, want)))(anims)
            if k is None:
                return None
        try:
            new = _gltf.import_animation(f, m, template=template, animation=anims[k][0])
            note = _gltf.frame_rate_note(f, anims[k][0])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import motion", err_text(e))
            return None
        if note and not getattr(self, "_testing", False) and path is None:
            messagebox.showwarning("Import motion", f"{anims[k][1]}: {note}")
        return new

    def _pick_animation(self, anims, want=None):
        """Index into `anims` ([(index, name, seconds, channels)]) chosen in a small list; the
        one named `want` (the motion being replaced) is preselected."""
        win = tk.Toplevel(self.root)
        win.title("Import motion -- which animation?")
        win.transient(self.root)
        lb = tk.Listbox(win, width=60, height=min(12, len(anims)))
        for _i, nm, dur, nch in anims:
            lb.insert("end", f"{nm}   ({dur:.2f} s = {round(dur * 60)} frames, {nch} channels)")
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        first = next((i for i, a in enumerate(anims) if want and a[1] == want), 0)
        lb.selection_set(first)
        lb.see(first)
        out = {}

        def ok(_e=None):
            s = lb.curselection()
            out["k"] = s[0] if s else None
            win.destroy()
        lb.bind("<Double-Button-1>", ok)
        ttk.Button(win, text="Import", command=ok).pack(side="right", padx=8, pady=(0, 8))
        ttk.Button(win, text="Cancel", command=win.destroy).pack(side="right", pady=(0, 8))
        win.grab_set()
        win.wait_window()
        return out.get("k")

    def _install_motion(self, file_name, anim, answer=None):
        """Offer to install an imported motion into the game as `file_name` (backup kept) or
        save it elsewhere. `answer` (True install / False save as / None keep the preview)
        skips the question (tests). Returns the written path or None."""
        from rf4s_modkit import skelanim as _sk
        blob = _sk.build(anim)
        if answer is None and not getattr(self, "_testing", False):
            answer = messagebox.askyesnocancel(
                "Import motion",
                f"The new motion plays in the preview now.\n\nInstall it into your game as "
                f"{file_name}? (Yes = install, the original is kept in ModdingBackup; No = save "
                f"the .bfskl somewhere else; Cancel = only preview it.)")
        if answer is None:
            self.status.config(text=f"Previewing the imported motion (not saved) -- {file_name}")
            return None
        if answer:
            targets = gamepaths.game_targets([file_name])
            if targets is None:
                messagebox.showerror("Import motion", "No game folder is set up."); return None
            try:
                gamepaths.write_game_file(targets[file_name], blob)
            except OSError as e:
                messagebox.showerror("Import motion", f"Could not write {targets[file_name]}:\n{err_text(e)}")
                return None
            self.status.config(text=f"Installed {file_name} ({len(blob):,} bytes) -- restart the game "
                                    f"to see it")
            return targets[file_name]
        f = filedialog.asksaveasfilename(title="Save the motion", initialfile=file_name,
                                         defaultextension=".bfskl", filetypes=[("motion", "*.bfskl")])
        if not f:
            return None
        pathlib.Path(f).write_bytes(blob)
        self.status.config(text=f"Saved {f} ({len(blob):,} bytes)")
        return pathlib.Path(f)

    PLAY_RENDER_PX = 360        # the longer side a model is rendered at while it plays
    PLAY_CACHE_FRAMES = 240     # rendered playback frames kept per model tab (one loop, usually)

    def _model_skel_controls(self, frame, name, m, state, view, redraw):
        """A 'motion' row under the Model tab listing the .bfskl skeletal animations that
        drive this model (skelanim.anim_candidates) with Play / GIF…. Returns a callback that
        refreshes the frame label after each draw, or None when the model has none."""
        doc = self._doc
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
                    lab.config(text=f"cannot read: {err_text(e)}"); return
                if not _sk.bound_bones(m, a)[0]:
                    lab.config(text="drives none of this model's bones"); return
                state["skel"] = a
            redraw()

        def tick(last):
            doc._skel_after = None
            if not state["splaying"] or not row.winfo_exists() or state["skel"] is None:
                return
            now = _time.monotonic()
            a = state["skel"]
            state["sframe"] = a.wrap(state["sframe"] + 60.0 * (now - last))
            if not a.loops and state["sframe"] >= a.frame_count:
                state["sframe"] = 0.0
            redraw()
            doc._skel_after = self._doc_after(15, lambda: tick(now))

        def toggle():
            state["splaying"] = not state["splaying"] and state["skel"] is not None
            pb.config(text="Stop" if state["splaying"] else "Play")
            if state["splaying"] and getattr(doc, "_skel_after", None) is None:
                tick(_time.monotonic())
            elif not state["splaying"]:
                redraw()                   # the paused frame at full quality
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
                messagebox.showerror("Export GIF", err_text(e)); return
            finally:
                self.root.config(cursor="")
            self.status.config(text=f"wrote {f} ({len(frames)} frames of {a.name})")
        ttk.Button(row, text="GIF…", width=5, command=gif).pack(side="left")

        def export_all():
            self._export_all_motions(m, stem, names, src)
        ea_b = ttk.Button(row, text="Export all motions…", command=export_all)
        ea_b.pack(side="left", padx=(8, 0))
        from guiutil import Tip as _Tip
        _Tip(ea_b, f"Write one .glb for Blender with the model and all {len(names)} of its motions, "
                   f"each as its own action named after the motion file (Blender's Action editor / "
                   f"NLA lists them). Bring them back with Import all motions… (only the changed "
                   f"ones), or one with Import motion…. " + BLENDER_HINT)

        def import_motion():
            n = choice.get()
            if n not in names:
                messagebox.showinfo("Import motion", "First pick, in the motion list, the motion the "
                                                     "new animation should replace. The game plays "
                                                     "motions by file name, so a new one always takes "
                                                     "the place of an existing one.")
                return
            try:
                template = _sk.parse(src.read_named(n) or b"")
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Import motion", f"cannot read {n}: {err_text(e)}"); return
            new = self._import_motion_file(m, template)
            if new is None:
                return
            state.update(skel=new, sframe=0.0, boxes={}, fcache={})
            lab.config(text=f"imported: {new.frame_count} frames")
            redraw()
            self._install_motion(n, new)
        im_b = ttk.Button(row, text="Import motion…", command=import_motion)
        im_b.pack(side="left", padx=(8, 0))
        from guiutil import Tip as _Tip
        _Tip(im_b, "Replace the motion picked here with an animation from a glTF / .glb file -- "
                   "made in Blender from Export for Blender… (the bone names must stay the same). "
                   "It is previewed on the model at once, then installed into your game under this "
                   "motion's file name (the original is kept in ModdingBackup) or saved elsewhere.")

        def import_all():
            res = self._import_all_motions(m, names, src)
            cur = choice.get()
            if res and cur in names:            # show the new version of the picked motion
                new = dict((f"{n}.bfskl", a) for n, a in res).get(cur)
                if new is not None:
                    state.update(skel=new, sframe=0.0, boxes={}, fcache={})
                    lab.config(text=f"imported: {new.frame_count} frames")
                    redraw()
        ia_b = ttk.Button(row, text="Import all motions…", command=import_all)
        ia_b.pack(side="left", padx=(4, 0))
        _Tip(ia_b, "Bring back every edited motion from one glTF / .glb (e.g. Export all motions… "
                   "edited in Blender): each animation named like one of this model's motion "
                   "files replaces that file. Only the ones you changed are listed to install "
                   "(untouched ones are left alone); you choose which to install into the game "
                   "(originals kept in ModdingBackup) or save to a folder.")
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
            messagebox.showerror("Export GIF", err_text(e)); return
        finally:
            self.root.config(cursor="")
        self.status.config(text=f"wrote {f} ({len(frames)} frames, one {anim.frame_count}-frame loop)")

    def _build_bntx_browser(self, nb, name, data):
        """A 'Textures' tab: list every embedded BNTX texture; click to preview
        (zoom), Export the selected one (toolbar Export), or Export all to a folder."""
        doc = self._doc
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
        doc._bntx_lbl = ttk.Label(bar, text=f"{len(lst)} textures — select one")
        doc._bntx_lbl.pack(side="left", padx=6)
        for z, lbl in ((0.5, "½×"), (1, "1×"), (2, "2×")):
            ttk.Button(bar, text=lbl, width=4,
                       command=lambda z=z: self._set_zoom(z, doc)).pack(side="left")
        ttk.Button(bar, text="Export all…", width=11,
                   command=lambda: self._export_all_bntx(name, data, lst)).pack(side="right", padx=4)
        ttk.Button(bar, text="Replace texture…", width=17,
                   command=lambda: self._replace_bntx_png(name, tv)).pack(side="right", padx=4)
        cvframe = ttk.Frame(right); cvframe.pack(fill="both", expand=True)
        doc._img_canvas = self._make_image_canvas(cvframe, doc=doc)

        def on_sel(_evt=None):
            s = tv.selection()
            if not s:
                return
            idx = int(s[0])
            try:
                im = texture.decode_bntx(data, idx)
            except texture.TextureError as e:
                doc._bntx_lbl.config(text=err_text(e)); return
            if im is None:
                doc._bntx_lbl.config(text="unsupported format (needs texture2ddecoder)"); return
            doc._pil = im.convert("RGBA")
            t = lst[idx]
            doc._bntx_lbl.config(text=f"{t['name']}   {t['w']}×{t['h']}   {t['fmt_name']}")
            self._set_zoom(1.0, doc)
            doc._export_kind = "png"
            self.export_btn.config(state="normal")

        tv.bind("<<TreeviewSelect>>", on_sel)
        if lst:
            tv.selection_set(str(lst[0]["index"])); on_sel()

    def _replace_bntx_png(self, name, tv):
        """Replace the selected embedded texture of a .model from a PNG, re-encoded in its own
        format (texture.bntx_replace): IN PLACE at the same size (file size and every container
        field unchanged), or -- after a confirm showing old -> new -- at another size, with the
        BNTX and the .model rebuilt around it. Updates cur_data; Extract writes it."""
        doc = self._doc
        sel = tv.selection()
        if not sel or doc.cur_data is None:
            return
        idx = int(sel[0])
        f = filedialog.askopenfilename(title="Replace embedded texture from PNG…",
                                       filetypes=[("PNG image", "*.png"), ("All images", "*.*")])
        if not f:
            return
        before = len(doc.cur_data)
        try:
            # another size is fine for a model (UVs are normalised): the BNTX and the .model
            # are rebuilt around it (texture.bntx_replace); confirm the change first
            t = texture.bntx_info(doc.cur_data)[idx]
            with Image.open(f) as im:
                new_size = im.size
            old_size = (t["width"], t["height"])
            if new_size != old_size:
                msg = (f"Texture {idx} ({t['name']}): {old_size[0]}x{old_size[1]} -> "
                       f"{new_size[0]}x{new_size[1]}\n\nModel UVs are normalised, so the model shows the "
                       f"new image at the new resolution; the .model is rebuilt around the new size."
                       + "".join(f"\n- {w}" for w in texture.bntx_size_warnings(t, new_size))
                       + "\n\nStore it at the new size?")
                if not messagebox.askyesno("Change the texture size?", msg, icon="warning"):
                    return
            blob = texture.bntx_replace(doc.cur_data, idx, f)
        except Exception as e:  # noqa: BLE001 - surface any encode/size problem to the user
            messagebox.showerror("Replace failed", err_text(e))
            return
        doc.cur_data = blob
        self._show(name, blob, doc)
        how = (f"in place -> {len(blob):,} bytes, size unchanged" if len(blob) == before else
               f"{old_size[0]}x{old_size[1]} -> {new_size[0]}x{new_size[1]}, .model rebuilt -> "
               f"{len(blob):,} bytes (was {before:,})")
        self.status.config(text=f"Replaced texture {idx} from {pathlib.Path(f).name} {how} "
                                f"(Extract to save the working copy)")

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
        """A monster generator: the flat picture of its map (gates ◆, monster points ●, drag
        them; '+ gate' / '+ spawn' then click the picture) beside the map editor's own
        Gates pane (gates, weights, counts, rosters). 'Open in map editor' switches to the
        full editor; 'Save table…' writes the file."""
        doc = self._doc
        from map_editor import tabs as me_tabs
        g = gen.GenTable(data)
        doc._gen = g
        maps = self._maps_for_gen(name)
        host = _GenHost(self, name, g, doc)
        doc._gen_host = host
        nmfn = _load_actor_names()
        rtxt = ", ".join(f"{nmfn(i) or i}×{c}" for i, c in g.roster().most_common()) or "(none)"
        ttk.Label(doc.content, text=f"Monster spawns (a monster generator) — roster: {rtxt}",
                  wraplength=940).pack(anchor="w", padx=6)
        host.build_map_row(maps)
        # Lay the view out ONCE: the picture's size comes from the map's ATTR grid (no image
        # needed) and the pane gets the rest of the width up front. Otherwise the Gates
        # pane was drawn at its natural width and re-laid-out ~25 ms later when its scroll area
        # learned the real one -- a visible redraw on every Gen file.
        total_w = doc.content.winfo_width()
        pic = host.picture_size()
        body = ttk.Frame(doc.content)       # built unpacked, shown when complete
        host.build_picture(body, pic)
        pane = me_tabs.EncountersTab(body, host)
        pane.pack(side="left", fill="both", expand=True)
        host.pane = pane
        if total_w > 1:
            host.presize_pane(total_w - ((pic[0] if pic else 0) + host.PICTURE_PAD))
        pane.refresh()
        first = pane.gates.get_children()
        if first:                            # the first gate: its roster shows, its points light up
            pane.gates.selection_set(first[0])
            pane._gate_picked()
        host.redraw()
        body.pack(fill="both", expand=True)

    # ---- Gen files: the map they belong to ------------------------------------------------ #
    def _maps_for_gen(self, gen_name):
        """[(entry name, entry index)] of the maps whose monster generator this Gen file is."""
        from map_editor import data as med
        idx = {}
        for i, (n, _g, _l) in enumerate(self.source.entries if self.source else ()):
            if n.lower().endswith(".rf4m"):
                idx.setdefault(n, i)
        return [(n, idx[n]) for n in med.maps_for_gen(pathlib.Path(gen_name).name, list(idx))]

    def _open_map_encounters(self, map_name):
        """Show a map in the embedded map editor on its Gates tab (and select it in the
        file list), in the map's own tab."""
        if not map_name or not self.source:
            return
        i = next((k for k, e in enumerate(self.source.entries) if e[0] == map_name), None)
        if i is None:
            return
        name, _g, loader = self.source.entries[i]
        self._reveal_entry(i)
        doc = self._open_in_tab(self._entry_key(name), name, loader())
        if doc is None:
            return
        panel = doc._map_panel
        if panel is not None:
            try:
                panel.nb.select(panel.encounters)
            except tk.TclError:
                pass
        self.status.config(text=f"{pathlib.Path(name).name}: Gates tab (its monster generator)")

    def _reveal_entry(self, i):
        """Select entry `i` in the file list without re-opening it (clears a filter that
        hides it; opens its group)."""
        iid = next((k for k, v in self._index.items() if v == i), None)
        if iid is None:
            for gid, idxs in self._group_indices.items():
                if i in idxs:
                    self.tree.item(gid, open=True)
                    self.tree.focus(gid)
                    self._on_group_open(None)
                    iid = next((k for k, v in self._index.items() if v == i), None)
                    break
        if iid is None and (self.filter_var.get() or self._cat_filter()):
            self.filter_var.set("")
            self.cat_var.set(self.ALL_CATS)
            self._apply_filter_now()
            return self._reveal_entry(i)
        if iid is not None:
            self._suppress_select = True
            try:
                self.tree.selection_set(iid)
                self.tree.see(iid)
            finally:
                self.root.after_idle(lambda: setattr(self, "_suppress_select", False))

    def _view_asatk(self, name, data):
        """as_atk_*.bin attack-move timeline: rendered view + an editable listing that
        assembles back into the working copy (2026-09-19)."""
        doc = self._doc
        s = asatk.summary(data)
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        hw = ", ".join(f"{o}-{c}" for o, c in s["hit_windows"]) or "(none)"
        ttk.Label(bar, text=f"Attack timeline — {s['pairs']} events, "
                            f"frames {s['first_frame']}..{s['last_frame']}, "
                            f"hit-window {hw}, effects {', '.join(str(e) for e in s['effects']) or '(none)'}",
                  wraplength=700).pack(side="left", padx=6)
        nb = ttk.Notebook(doc.content); nb.pack(fill="both", expand=True)
        txt = self._make_text_tab(nb, "Timeline", mono=True, doc=doc)
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
            doc.cur_data = blob
            self.status.config(text="Timeline assembled (" + (f"{len(warns)} warning(s): {warns[0]}"
                                                               if warns else "no warnings") +
                                    ") — use Extract… / Save to write")
            self._show(doc.cur_name, blob, doc)
        ttk.Button(eb, text="Assemble & apply", command=apply_listing).pack(side="right", padx=6)
        doc._export_kind = "disasm"; doc._export_text = asatk.render(data)
        self.export_btn.config(state="normal")

    def _view_skillcurve(self, name, data):
        """rf3ParamSkillExp*.bin skill XP-per-level curve (read-only decode)."""
        doc = self._doc
        xp = skillcurve.parse(data)
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        arc = next((a for a, f in skillcurve.ARCHIVE_FILE.items()
                    if pathlib.Path(name).stem.lower() == f.lower()), None)
        who = ""
        if arc is not None:
            sks = [s for s, a in skillcurve.FAMILY_ARCHIVE.items() if a == arc]
            who = f"archive {arc}" + (f", skills {sks}" if sks else " (default: weapons/magic/…)")
        ttk.Label(bar, text=f"Skill XP curve — 100 levels, total {sum(xp)}, "
                            f"cap-bracket table[99]={xp[-1] if xp else 0}   {who}",
                  wraplength=940).pack(side="left", padx=6)
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        txt.insert("end", skillcurve.render(data, upto=100))
        txt.config(state="disabled")

    def _view_strengthening(self, name, data):
        """rf3ItemStrengthening.bin — forge material rows / dish ingredient bonuses / the craft
        status word (GUI twin of `rf4mod str`). Grid of the fields that matter most, a filter
        for the NON-FOOD marker, and the full decoded row for the selection."""
        doc = self._doc
        from rf4s_modkit import strengthening
        t = strengthening.StrengtheningTable(data)
        items = _load_item_names()
        names = {int(k): v for k, v in items.items()}
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
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
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
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

        detail = tk.Text(doc.content, height=12, wrap="word")
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
        doc = self._doc
        items = _load_item_names()
        chars = _load_char_names()
        num = int(pathlib.Path(name).stem[13:15]) if pathlib.Path(name).stem[13:15].isdigit() else 0
        name_fn = lambda i: items.get(i, "")
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        who = chars.get(num, "?")
        ttk.Label(bar, text=f"Gift preferences — char {num} {who}  (archive {14850 + num})",
                  ).pack(side="left", padx=6)
        tv = ttk.Treeview(doc.content, columns=("aff", "item", "fp"), show="headings", height=20)
        for c, w in (("aff", 130), ("item", 320), ("fp", 90)):
            tv.heading(c, text={"aff": "affinity", "item": "item / target", "fp": "FP / note"}[c])
            tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(doc.content, orient="vertical", command=tv.yview)
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
        ctl = ttk.Frame(doc.content); ctl.pack(fill="x", padx=6, pady=3)
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
            t = gifts.GiftTable.parse(doc.cur_data)
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
            doc.cur_data = blob
            self.status.config(text=f"gift table edited ({action} item {iid}) — Save table… / Extract… to write")
            self._show(doc.cur_name, blob, doc)

        def _save():
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                                             initialfile=pathlib.Path(doc.cur_name).name,
                                             filetypes=[("gift table", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(doc.cur_data); self._mark_saved(doc); self.status.config(text=f"Saved → {f}")
        for lbl, act in (("Set tier", "set"), ("Signature dislike", "signature"), ("Remove item", "remove")):
            ttk.Button(ctl, text=lbl, command=lambda a=act: _edit(a)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Save table…", command=_save).pack(side="right", padx=2)

    def _view_schedule(self, name, data):
        """rf3Schedule — NPC daily-routine itineraries: one per (NPC, state), time -> spot kind
        -> room (spots resolved through the sibling rf3ScheduleID.bin when it is extracted)."""
        doc = self._doc
        sc = schedule.Schedule.parse(data)
        cells = sc.ordered_cells()
        scheds = [lst for _k, lst in cells]
        sidbytes = _find_extracted("rf3ScheduleID.bin")
        spots = schedule.load_spots(sidbytes) if sidbytes else None
        chars = _load_char_names()
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"NPC daily schedules — {len(scheds)} (NPC, state) routines, "
                            f"{sum(len(s) for s in scheds)} stops. Pick a schedule:"
                  ).pack(side="left", padx=6)
        sv = tk.IntVar(value=0)
        sp = ttk.Spinbox(bar, from_=0, to=max(0, len(scheds) - 1), width=6, textvariable=sv)
        sp.pack(side="left", padx=4)
        who = ttk.Label(bar, text=""); who.pack(side="left", padx=8)
        tv = ttk.Treeview(doc.content, columns=("time", "room", "name"), show="headings", height=20)
        for c, w in (("time", 80), ("room", 80), ("name", 360)):
            tv.heading(c, text={"time": "time", "room": "spot kind", "name": "location (rf3ScheduleID)"}[c])
            tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(doc.content, orient="vertical", command=tv.yview)
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
        ctl = ttk.Frame(doc.content); ctl.pack(fill="x", padx=6, pady=3)
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
            doc.cur_data = blob
            self.status.config(text=f"schedule edited ({action}, npc {npc} state {state}) — Save… / Extract… to write")
            fill()

        def _save():
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                                             initialfile=pathlib.Path(doc.cur_name).name,
                                             filetypes=[("schedule", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(doc.cur_data); self._mark_saved(doc); self.status.config(text=f"Saved → {f}")
        for lbl, act in (("Apply stop", "apply"), ("Add stop", "add"), ("Remove stop", "remove")):
            ttk.Button(ctl, text=lbl, command=lambda a=act: _edit(a)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Save…", command=_save).pack(side="right", padx=2)

    def _view_gift_categories(self, name, data):
        """rf3PresentCategory — the 21 shared gift categories referenced by NPC cross-refs."""
        doc = self._doc
        items = _load_item_names()
        cats = gifts.load_categories(data)
        ttk.Label(doc.content, text=f"{len(cats)} shared gift categories (referenced by "
                                     f"NPC gift tables via cross-ref)").pack(fill="x", padx=6, pady=2)
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        for idx, _grp in enumerate(cats):
            ids = gifts.category_items(idx, cats)
            names = ", ".join(items.get(i, str(i)) for i in ids)
            txt.insert("end", f"cat {idx:>2} ({len(ids)}): {names}\n")
        txt.config(state="disabled")

    def _view_montame(self, name, data):
        """rf3MonsterPresent — per-species monster taming-food preferences (archive 14849)."""
        doc = self._doc
        from rf4s_modkit import montame
        items = _load_item_names()
        chars = _load_char_names()
        ttk.Label(doc.content, text=f"Monster taming-food preferences — {montame.species_count(data)} "
                                     f"species (id 48+), each with up to 4 favored items + tame bonus"
                  ).pack(fill="x", padx=6, pady=2)
        tv = ttk.Treeview(doc.content, columns=("sp", "who", "items"), show="headings", height=22)
        for c, w in (("sp", 70), ("who", 150), ("items", 640)):
            tv.heading(c, text={"sp": "species", "who": "name", "items": "tame items (+bonus)"}[c])
            tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(doc.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        for sid in range(montame.FIRST_SPECIES, montame.FIRST_SPECIES + montame.species_count(data)):
            pr = montame.prefs(data, sid)
            if not pr:
                continue
            txt = ", ".join(f"{items.get(i, i)} (+{b})" for i, b in pr)
            tv.insert("", "end", values=(sid, chars.get(sid, ""), txt))
        # ---- edit controls (2026-09-19): set / remove one of a species' four tame items ----
        ctl = ttk.Frame(doc.content); ctl.pack(fill="x", padx=6, pady=3)
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
            buf = bytearray(doc.cur_data)
            try:
                if remove:
                    if not montame.remove_item(buf, sp, iid):
                        messagebox.showinfo("Taming foods", f"species {sp} does not list item {iid}"); return
                else:
                    montame.set_item(buf, sp, iid, bonus)
            except Exception as ex:  # noqa: BLE001
                messagebox.showerror("Edit failed", str(ex)); return
            blob = bytes(buf)
            doc.cur_data = blob
            self.status.config(text=f"taming foods edited (species {sp}, item {iid}) — Save table… / Extract… to write")
            self._show(doc.cur_name, blob, doc)

        def _save():
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                                             initialfile=pathlib.Path(doc.cur_name).name,
                                             filetypes=[("taming table", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(doc.cur_data); self._mark_saved(doc); self.status.config(text=f"Saved → {f}")
        ttk.Button(ctl, text="Set item", command=lambda: _edit(False)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Remove item", command=lambda: _edit(True)).pack(side="left", padx=2)
        ttk.Button(ctl, text="Save table…", command=_save).pack(side="right", padx=2)

    def _view_route(self, name, data):
        """rf3route.bin — the NPC town-navigation graph (rooms -> nodes -> edges): tree view,
        path queries through rf3RouteResult.bin, JSON export / import (edits land in the
        working copy) and next-hop matrix regeneration (2026-09-19)."""
        doc = self._doc
        from rf4s_modkit import route
        import json as _json
        g = route.RouteGraph.parse(data)
        rooms = [(rid, r) for rid, r in enumerate(g.rooms()) if r.node_count]
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Navigation graph (TRCS) — {len(g.nodes)} nodes, {len(g.edges)} edges "
                            f"in {len(rooms)} rooms; positions are tiles, edge cost = walk cost",
                  wraplength=700).pack(side="left", padx=6)
        tv = ttk.Treeview(doc.content, columns=("kind", "id", "detail"), show="tree headings", height=18)
        tv.heading("#0", text="room / node / edge"); tv.column("#0", width=230)
        for c, w in (("kind", 60), ("id", 60), ("detail", 520)):
            tv.heading(c, text=c); tv.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(doc.content, orient="vertical", command=tv.yview)
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
        ctl = ttk.Frame(doc.content); ctl.pack(fill="x", padx=6, pady=3)
        v_src, v_dst = tk.StringVar(), tk.StringVar()
        ttk.Label(ctl, text="path from").pack(side="left")
        ttk.Entry(ctl, textvariable=v_src, width=10).pack(side="left", padx=2)
        ttk.Label(ctl, text="to").pack(side="left")
        ttk.Entry(ctl, textvariable=v_dst, width=10).pack(side="left", padx=2)
        ttk.Label(ctl, text="(node id or room:N[:k])", font=("Segoe UI", 8), foreground="#666").pack(side="left")
        out = ttk.Label(doc.content, text="", wraplength=900, justify="left"); out.pack(fill="x", padx=6)

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
            doc.cur_data = blob
            self.status.config(text="graph imported — also rebuild the next-hop matrix (button) and save both")
            self._show(doc.cur_name, blob, doc)

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
                pathlib.Path(f).write_bytes(doc.cur_data); self._mark_saved(doc); self.status.config(text=f"Saved → {f}")
        for lbl, cmd in (("Export JSON…", _export), ("Import JSON…", _import),
                         ("Rebuild next-hop matrix…", _rebuild), ("Save graph…", _save)):
            ttk.Button(ctl, text=lbl, command=cmd).pack(side="right", padx=2)

    def _view_route_result(self, name, data):
        """rf3RouteResult.bin — the derived next-hop matrix; regenerate it from rf3route.bin."""
        doc = self._doc
        from rf4s_modkit import route
        gb = _find_extracted("rf3route.bin")
        ttk.Label(doc.content, wraplength=900, justify="left",
                  text="Next-hop matrix hop[dst][src] (nibbles) derived from rf3route.bin; the game walks "
                       "it hop by hop (Nav_BuildPathFromAToB). It is not edited directly: change the graph "
                       "and regenerate this file.").pack(fill="x", padx=6, pady=4)
        if gb:
            g = route.RouteGraph.parse(gb)
            rr = route.RouteResult.parse(data, len(g.nodes))
            same = rr.build() == route.RouteResult.compute(g, rr.rows).build()
            ttk.Label(doc.content, text=f"{rr.rows} rows x {rr.stride} B; graph has {len(g.nodes)} nodes; "
                                         f"{'identical to' if same else 'equivalent to'} the matrix "
                                         f"recomputed from rf3route.bin"
                                         f"{'' if same else ' (differences are tie-breaks between equal-cost routes)'}"
                      ).pack(fill="x", padx=6)

            def _rebuild():
                blob = route.RouteResult.compute(g, rr.rows).build()
                doc.cur_data = blob
                self.status.config(text="matrix recomputed from rf3route.bin — Extract… to write")
            ttk.Button(doc.content, text="Recompute from rf3route.bin", command=_rebuild).pack(padx=6, pady=4)
        else:
            ttk.Label(doc.content, text="rf3route.bin is not extracted, so the matrix cannot be checked").pack(padx=6)

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
        doc = self._doc
        try:
            f = search_items.SearchItemFile.parse(data)
        except Exception as e:
            self._view_hex(name, data, error=str(e)); return
        doc._si = f
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

        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Search-item spots — engine rolls daily: 1-in-N chance per "
                            f"spot, max 2 spawns/map/day, sleep rerolls.",
                  wraplength=720).pack(side="left", padx=6)
        ttk.Label(bar, text=footer_txt, foreground="#888").pack(side="right", padx=6)

        paned = ttk.PanedWindow(doc.content, orient="horizontal")
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
            doc.cur_data = f.build()
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
            chances, _nothing = p.engine_chances()          # as the game picks (byte sums)
            for j, (e, pct) in enumerate(zip(p.entries, chances)):
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
                messagebox.showerror("Bad value", err_text(e)); return
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
                messagebox.showerror("Bad value", err_text(e)); return
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
            blob = f.build(); doc.cur_data = blob
            orphans = [k for k, p in enumerate(pools) if not used_by(p)]
            if orphans:
                if not messagebox.askokcancel(
                        "Unassigned pools",
                        f"Pool(s) {', '.join('#%d' % k for k in orphans)} are not assigned "
                        f"to any spot and will NOT be in the saved file. Save anyway?"):
                    return
            fpath = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(doc.cur_name).name,
                filetypes=[("SI table", "*.bin"), ("All", "*.*")])
            if fpath:
                pathlib.Path(fpath).write_bytes(blob); self._mark_saved(doc)
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
        doc = self._doc
        t = nlcl.NlclTable(data)
        doc._param = t
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

        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Quest / Request database (archive 16342) — {t.entry_count} requests."
                            "  Each = posting NPC (client) + category template; the objective,"
                            " count and reward are rolled at runtime.").pack(side="left", padx=6)
        ttk.Label(bar, text="  Search #/client:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=14).pack(side="left", padx=2)

        cols = ("#", "client_id", "client", "category", "type")
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
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

        ed = ttk.LabelFrame(doc.content, text="Edit selected quest  (client_id + category; save writes the table)")
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
                messagebox.showerror("Edit failed", err_text(e)); return
            doc.cur_data = t.build()
            fill()
            tv.selection_set(str(i)); tv.see(str(i))
            self.status.config(text=f"Applied quest {i} — Save table… or Extract… to write")

        def save_tbl():
            blob = t.build(); doc.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(doc.cur_name).name,
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob); self._mark_saved(doc)
                self.status.config(text=f"Saved quest DB → {f}")
        ttk.Button(row, text="Save table…", command=save_tbl).pack(side="right", padx=4)
        ttk.Button(row, text="Apply", command=apply_edit).pack(side="right", padx=4)

    def _view_param(self, name, data):
        doc = self._doc
        t = nlcl.NlclTable(data)
        doc._param = t
        stem = pathlib.Path(name).stem
        sch = t.schema(stem)
        # row-name fn (item names) if the schema asks for it
        namefn = (lambda i: "")
        if sch and sch.get("names") == "item":
            tbl = _load_item_names()
            namefn = lambda i: tbl.get(i, "")

        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"NLCL {stem}: {t.entry_count} records × {t.record_size} B"
                          + ("  (named fields)" if sch else "  (raw — edit by offset)"),
                  ).pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)

        fields = sch["fields"] if sch else [(f"dw{k}", k * 4, "s32")
                                            for k in range(min(8, t.record_size // 4))]
        cols = ["#"] + [f[0] for f in fields] + (["name"] if sch and sch.get("names") else [])
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
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

        ed = ttk.LabelFrame(doc.content, text="Edit selected record")
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
                messagebox.showerror("Edit failed", err_text(e)); return
            doc.cur_data = t.build()
            fill()
            tv.selection_set(str(i)); tv.see(str(i))
            self.status.config(text=f"Applied record {i} — Save table… or Extract… to write")

        def save_tbl():
            blob = t.build(); doc.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(doc.cur_name).name,
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob); self._mark_saved(doc)
                self.status.config(text=f"Saved param table → {f}")

        def export_csv():
            """The table view (every record, schema columns + name column) as CSV."""
            f = filedialog.asksaveasfilename(defaultextension=".csv",
                initialfile=pathlib.Path(doc.cur_name).stem + ".csv",
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
                messagebox.showerror("Add row failed", err_text(e)); return
            doc.cur_data = t.build()
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
                messagebox.showerror("Delete row failed", err_text(e)); return
            sel["i"] = None
            doc.cur_data = t.build()
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
        doc = self._doc
        t = nlcl.NlclTable(data)
        doc._param = t
        stem = "rf3CropParam"
        namefn = (lambda i: "")
        tbl = _load_item_names()
        namefn = lambda i: tbl.get(i, "")

        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"rf3CropParam: {t.entry_count} crops × {t.record_size} B  "
                            "(season affinity + growth tuning)").pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)
        only_crops = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="planted crops only", variable=only_crops).pack(side="left", padx=6)

        show_cols = ["stage1", "stage2", "stage3", "regrow", "water", "grow_cap",
                     "gmul_size", "gmul_1", "gmul_2", "gmul_3", "harvest", "seed"]
        cols = ["#"] + show_cols + ["grows", "name"]
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
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

        ed = ttk.LabelFrame(doc.content, text="Edit selected crop")
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
                messagebox.showerror("Edit failed", err_text(e)); return
            doc.cur_data = t.build()
            fill(); tv.selection_set(str(i)); tv.see(str(i))
            self.status.config(text=f"Applied crop {i} — Save…/Extract… to write a loose override")

        def save_tbl():
            blob = t.build(); doc.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin",
                initialfile=pathlib.Path(doc.cur_name).name,
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob); self._mark_saved(doc)
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
        doc = self._doc
        from rf4s_modkit import monster
        t = nlcl.NlclTable(data)
        doc._param = t
        stem = "rf3NpcParam"
        sch = t.schema(stem)
        species = monster.load_species()
        items = _load_item_names()

        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Monster / character templates — {t.entry_count} char_ids × "
                            f"{t.record_size} B   (id: <48 human · 48-199 field · 200-253 boss)"
                  ).pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)

        body = ttk.Frame(doc.content); body.pack(fill="both", expand=True)
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
                messagebox.showerror("Edit failed", err_text(e)); return
            doc.cur_data = t.build()
            fill(); tv.selection_set(str(i)); tv.see(str(i)); render_sheet(i)
            self.status.config(text=f"Applied char {i} — Save… to write a loose override")

        def save_tbl():
            blob = t.build(); doc.cur_data = blob
            f = filedialog.asksaveasfilename(defaultextension=".bin", initialfile="rf3NpcParam.bin",
                filetypes=[("NLCL param", "*.bin"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_bytes(blob); self._mark_saved(doc)
                self.status.config(text=f"Saved rf3NpcParam → {f}")

        btns = ttk.Frame(ed); btns.pack(fill="x", padx=4, pady=2)
        ttk.Button(btns, text="Save…", command=save_tbl).pack(side="right", padx=3)
        ttk.Button(btns, text="Apply", command=apply_edit).pack(side="right", padx=3)

    def _view_hex(self, name, data, error: str | None = None):
        doc = self._doc
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        if error:
            txt.insert("end", f"[viewer note] {error}\n\n")
        txt.insert("end", hexdump(data))
        txt.config(state="disabled")

    # ---- view helpers ---------------------------------------------------- #
    def _make_text_tab(self, nb, title, mono=False, doc=None):
        doc = doc or self._doc
        parent = doc.content if nb is None else ttk.Frame(nb)
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

    def _make_image_canvas(self, parent=None, doc=None):
        doc = doc or self._doc
        parent = parent or doc.content
        frame = ttk.Frame(parent); frame.pack(fill="both", expand=True)
        hb = ttk.Scrollbar(frame, orient="horizontal")
        vb = ttk.Scrollbar(frame, orient="vertical")
        canvas = tk.Canvas(frame, bg="#202020", xscrollcommand=hb.set, yscrollcommand=vb.set)
        hb.config(command=canvas.xview); vb.config(command=canvas.yview)
        hb.pack(side="bottom", fill="x"); vb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        return canvas

    def _set_zoom(self, z, doc=None):
        doc = doc or self._doc
        if doc._pil is None:
            return
        doc.zoom = z
        w, h = doc._pil.size
        # crisp nearest-neighbour when magnifying (see the pixels); smooth LANCZOS
        # when shrinking so downscaled photos/atlases don't alias to noise.
        resample = Image.NEAREST if z >= 1 else Image.LANCZOS
        disp = doc._pil.resize((max(1, int(w * z)), max(1, int(h * z))), resample)
        doc.cur_image = ImageTk.PhotoImage(disp)
        doc._img_canvas.delete("all")
        doc._img_canvas.create_image(0, 0, anchor="nw", image=doc.cur_image)
        doc._img_canvas.config(scrollregion=(0, 0, disp.width, disp.height))

    # ---- extract / export ------------------------------------------------ #
    def cmd_cutscene_editor(self):
        """Open the cutscene / event-script editor (rf3.mc + rf3mc.<locale>) in a window.
        Reads the script files by basename from the currently-loaded source, so it works
        best with a Manifest open (it can reach both bundlePatch1 and bundleMain)."""
        reader = self.source.read_named if self.source else None
        self.cutscene_editor()
        if reader is None or reader("rf3.mc") is None:
            self.status.config(text="Cutscene editor: open the Manifest (or a bundle with rf3.mc) "
                                    "first, or use 'Open rf3.mc…' in the window.")

    def cmd_event_manager(self):
        """Open the Cutscene editor and pop its Event Manager (em.bin) window straight
        away. Same window the 'Cutscenes' button reaches via 'Event Manager\u2026'; the entry
        browser works without rf3.mc loaded (the 'used by scenes' list is just empty)."""
        self.cutscene_editor().open_event_manager()

    def cmd_extract(self):
        """Save the shown file's working copy; True when it was written."""
        doc = self._doc
        if doc.cur_data is None:
            return False
        default = pathlib.Path(doc.cur_name).name
        f = filedialog.asksaveasfilename(title="Extract raw bytes", initialfile=default)
        if not f:
            return False
        pathlib.Path(f).write_bytes(doc.cur_data)
        self.status.config(text=f"Extracted {len(doc.cur_data):,} bytes -> {f}")
        self._mark_saved(doc)
        return True

    def cmd_export(self):
        doc = self._doc
        kind = getattr(doc, "_export_kind", None)
        if not kind:
            return
        stem = pathlib.Path(doc.cur_name).stem
        if kind == "map_png":
            # .rf4m: WYSIWYG snapshot of the embedded map editor -- current zoom
            # level + exactly the overlay layers that are toggled on.
            panel = getattr(doc, "_map_panel", None)
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
            if f and doc._pil:
                doc._pil.save(f); self.status.config(text=f"Exported PNG -> {f}")
        elif kind == "textjson":
            import json
            f = filedialog.asksaveasfilename(defaultextension=".json", initialfile=stem + ".json",
                                             filetypes=[("JSON", "*.json")])
            if f:
                pathlib.Path(f).write_text(
                    json.dumps(doc._export_arc.texts(), ensure_ascii=False, indent=1), encoding="utf-8")
                self.status.config(text=f"Exported {len(doc._export_arc)} strings -> {f}")
        elif kind == "plistjson":
            import json
            f = filedialog.asksaveasfilename(defaultextension=".json", initialfile=stem + ".json",
                                             filetypes=[("JSON", "*.json")])
            if f:
                obj = bplist.loads(doc._export_data)
                pathlib.Path(f).write_text(
                    json.dumps(bplist.to_jsonable(obj), ensure_ascii=False, indent=1), encoding="utf-8")
                self.status.config(text=f"Exported plist JSON -> {f}")
        elif kind == "disasm":
            f = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=stem + ".txt",
                                             filetypes=[("Text", "*.txt")])
            if f:
                pathlib.Path(f).write_text(doc._export_text, encoding="utf-8")
                self.status.config(text=f"Exported disassembly -> {f}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    import app_icon
    app_icon.prepare()
    root = tk.Tk()
    import guiutil
    guiutil.install_error_logging(root)     # toolkit errors -> the console, with traceback
    app_icon.apply(root)
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
            app_icon.apply(root)                # a game copy is known now: its trophy icon
        root.deiconify()
    App(root, initial=argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
