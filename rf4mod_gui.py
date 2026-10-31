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
import re
import struct
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
# files the toolkit has no viewer for but every Windows install opens (Media Player, the Font
# viewer): the tab offers "Open in default app". ident fmt -> (what, extension it needs)
EXTERNAL_FMTS = {"ogg": ("sound", ".ogg"), "wav": ("sound", ".wav"), "aiff": ("sound", ".aif"),
                 "webm": ("video", ".webm"), "ttf": ("font", ".ttf"), "ttc": ("font", ".ttc")}
EXTERNAL_EXTS = {".ogg": "sound", ".wav": "sound", ".flac": "sound", ".mp3": "sound", ".aif": "sound",
                 ".aiff": "sound", ".webm": "video", ".mp4": "video", ".ttf": "font", ".ttc": "font",
                 ".otf": "font"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".gif", ".bmp", ".tif", ".tiff",
              ".webp", ".tga", ".dds", ".ico"}

from rf4s_modkit import assetcat, gamepaths  # noqa: E402

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
from guiutil import CellEdit, TableSort, Tip, err_text, later, wheel_handler
def _load_actor_names():
    """id -> name: the game's rf3TxtNpc (gamenames), else the built-in list."""
    from rf4s_modkit import gamenames
    tbl = gamenames.table("characters")
    return lambda i: tbl.get(i, "")


def _tk_photo(img, widget=None, bg="#202020"):
    """A Tk PhotoImage of a PIL image, fast: the image is flattened onto the background it is
    shown on (`widget`'s, else `bg`) and handed over opaque. Tk's photo image is slow with
    transparent pixels (it tracks the transparent region): an RGBA portrait atlas with clear
    areas took 1.5 s at half size, the same pixels opaque 0.01 s."""
    if widget is not None:
        try:
            r, g, b = (v >> 8 for v in widget.winfo_rgb(widget.cget("background")))
            bg = (r, g, b)
        except (tk.TclError, AttributeError):
            pass
    if isinstance(bg, str):
        from PIL import ImageColor
        bg = ImageColor.getrgb(bg)
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        base = Image.new("RGB", rgba.size, bg)
        base.paste(rgba, mask=rgba.getchannel("A"))
    else:
        base = img.convert("RGB")
    return ImageTk.PhotoImage(base, master=widget) if widget is not None else ImageTk.PhotoImage(base)


def _load_item_names() -> dict[int, str]:
    """{item id: name}: the game's rf3TxtItem, else the built-in list."""
    from rf4s_modkit import gamenames
    return dict(gamenames.table("items"))


def _item_text(i: int, names: dict) -> str:
    """An item id as the editor shows it: "Minerals (1083)", "(none) (0)"."""
    return f"{names.get(i) or ('(none)' if i == 0 else '?')} ({i})"


def _parse_item(text: str, names: dict) -> int:
    """The item id typed or picked in an item picker: "Name (id)", a bare id, or a name
    (case ignored; must name exactly one item)."""
    s = str(text).strip()
    m = re.search(r"\((\d+)\)\s*$", s)
    if m:
        return int(m.group(1))
    if re.fullmatch(r"(0x[0-9a-fA-F]+|\d+)", s):
        return int(s, 0)
    hits = [i for i, n in names.items() if n and n.lower() == s.lower()]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"{s!r}: no single entry has that name -- pick one from the list or type its number"
                     if hits or s else "a name field is empty")


def _hint_line(lbl):
    """A hint above a row of buttons: its own line, wrapped to the width. (Packed side=left on
    the buttons' row, a long hint took the whole row and pushed the buttons out of sight.)"""
    lbl.config(wraplength=500, justify="left")
    lbl.pack(side="top", fill="x", pady=(0, 2))
    lbl.bind("<Configure>", lambda e: lbl.config(wraplength=max(200, e.width - 8)))
    return lbl


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


# the protagonist's two bodies (rf3NpcParam calls both "Earthmate"); Frey confirmed in game
_PLAYER_MODELS = {"NPC_PLAYER_00": "Lest (player)", "NPC_PLAYER_01": "Frey (player)"}
_MODEL_OWNERS = None


def _model_owner(file_name):
    """Who wears a .model -- 'Frey (player)', 'Clorica', 'Orc / Orc Archer' -- from the character
    templates (refdata/char_models.json: rf3NpcParam +272, resolved the way the game loads it,
    names from the game's text); outfit files (_PAJAMA, _SWIM, _WED, ...) take their base
    model's owners. '' when no character uses it."""
    global _MODEL_OWNERS
    if _MODEL_OWNERS is None:
        import json
        own = {}
        try:
            d = json.loads(_refdata_path("char_models.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        names = _load_char_names()
        for k, v in d.items():
            if k == "_meta" or not isinstance(v, dict) or not v.get("model"):
                continue
            stem = v["model"].upper()
            nm = _PLAYER_MODELS.get(stem) or names.get(int(k)) or v.get("name") or ""
            if nm and nm not in own.setdefault(stem, []):
                own[stem].append(nm)
        for stem, nm in _PLAYER_MODELS.items():
            own[stem] = [nm]
        _MODEL_OWNERS = {s: " / ".join(v[:4]) + (" …" if len(v) > 4 else "") for s, v in own.items()}
    stem = pathlib.PurePosixPath(file_name.replace("\\", "/")).name
    if not stem.lower().endswith(".model"):
        return ""
    parts = stem[:-6].upper().split("_")
    for n in range(len(parts), 0, -1):          # NPC_PLAYER_01_PAJAMA -> NPC_PLAYER_01
        hit = _MODEL_OWNERS.get("_".join(parts[:n]))
        if hit:
            return hit
    return ""

# from this many columns on a table is drawn a window of columns at a time (guiutil.ColumnWindow)
_WIDE_TABLE_COLUMNS = 24


def _table_scrollbars(top, tv, widths=None, freeze=0):
    """Scroll bars for a wide Treeview table: every column keeps its width (wide enough for its
    heading, or widths[col]) instead of being squeezed into the window, a horizontal bar appears
    under the table, and Shift + mouse wheel scrolls sideways. A table of _WIDE_TABLE_COLUMNS or
    more is shown a window of columns at a time (Tk redraws every column, in view or not), with
    its first `freeze` columns kept at the left."""
    import tkinter.font as tkfont
    try:
        f = tkfont.nametofont("TkHeadingFont")
    except tk.TclError:
        f = None
    for c in tv["columns"]:
        text = tv.heading(c, "text") or str(c)
        need = (f.measure(text) if f else 7 * len(text)) + 18
        w = max(need, (widths or {}).get(c, tv.column(c, "width")))
        tv.column(c, width=w, minwidth=40, stretch=False)
    vs = ttk.Scrollbar(top, orient="vertical", command=tv.yview)
    hs = ttk.Scrollbar(top, orient="horizontal", command=tv.xview)
    tv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
    cw = None
    if len(tv["columns"]) >= _WIDE_TABLE_COLUMNS:
        from guiutil import ColumnWindow
        cw = ColumnWindow(tv, hs, freeze)
        hs.configure(command=cw.xview)
        tv.configure(xscrollcommand=lambda *_a: None)   # the window drives the bar, not the table
    top.grid_rowconfigure(0, weight=1)
    top.grid_columnconfigure(0, weight=1)
    tv.grid(row=0, column=0, sticky="nsew")
    vs.grid(row=0, column=1, sticky="ns")
    hs.grid(row=1, column=0, sticky="ew")
    # sideways: a Treeview x unit is 1 pixel, so a notch moves 100 px; rows: 3 per notch
    tv.bind("<Shift-MouseWheel>", wheel_handler(cw.scroll, 1) if cw is not None
            else wheel_handler(lambda n: tv.xview_scroll(n, "units"), 100))
    tv.bind("<MouseWheel>", wheel_handler(lambda n: tv.yview_scroll(n, "units"), 3))
    return vs, hs


def _flag_dialog(parent, title, typ, value, names, on_ok):
    """One tick box per bit of a bit-set field: the named bits first ("Fire  0x01"), then every
    other bit of the field's width as "bit N" (the ones set now are ticked). OK calls
    on_ok(new value)."""
    width = {"u8": 8, "s8": 8, "u16": 16, "s16": 16}.get(typ, 32)
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    body = ttk.Frame(win, padding=8)
    body.pack(fill="both", expand=True)
    boxes = {}
    row = 0
    named = sorted((names or {}).items())
    if named:
        ttk.Label(body, text="Named bits", font=("Segoe UI", 9, "bold")).grid(row=row, column=0, columnspan=4,
                                                                           sticky="w")
        row += 1
        for i, (mask, nm) in enumerate(named):
            var = tk.BooleanVar(value=bool(value & mask))
            boxes[mask] = var
            ttk.Checkbutton(body, text=f"{nm}  ({nlcl.format_flags(mask, typ)})", variable=var).grid(
                row=row + i // 2, column=(i % 2) * 2, columnspan=2, sticky="w", padx=(0, 12))
        row += (len(named) + 1) // 2
    rest = [1 << k for k in range(width) if (1 << k) not in boxes]
    ttk.Label(body, text="Other bits" if named else "Bits", font=("Segoe UI", 9, "bold")).grid(
        row=row, column=0, columnspan=4, sticky="w", pady=(6 if named else 0, 0))
    row += 1
    for i, mask in enumerate(rest):
        var = tk.BooleanVar(value=bool(value & mask))
        boxes[mask] = var
        ttk.Checkbutton(body, text=f"bit {mask.bit_length() - 1}", variable=var).grid(
            row=row + i // 4, column=i % 4, sticky="w", padx=(0, 10))
    row += (len(rest) + 3) // 4
    val_lbl = ttk.Label(body, foreground="#666")
    val_lbl.grid(row=row, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def current():
        return sum(m for m, v in boxes.items() if v.get())

    def show(*_):
        val_lbl.config(text="value " + nlcl.format_flags(current(), typ))
    for v in boxes.values():
        v.trace_add("write", show)
    show()
    bar = ttk.Frame(body)
    bar.grid(row=row + 1, column=0, columnspan=4, sticky="e", pady=(8, 0))

    def ok():
        new = current()
        win.destroy()
        on_ok(new)
    ttk.Button(bar, text="OK", command=ok).pack(side="right")
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=4)
    win.bind("<Escape>", lambda _e: win.destroy())
    win.bind("<Return>", lambda _e: ok())
    win.boxes = boxes                                # (selftest)
    win.ok = ok
    return win


def _fixed_tip(text, typ, bits):
    """Tooltip of a fixed-point field in the table editor: the stored integer and the scale."""
    one = nlcl.fixed_scale(bits)
    if bits == nlcl.ANGLE:
        try:
            return f"stored as {nlcl.parse_value(text, typ, bits)} (65536 = 360°); type degrees such as 90"
        except Exception:
            return "65536 = 360°; type degrees such as 90"
    if bits == nlcl.AMOUNT:
        try:
            return f"stored as {nlcl.parse_value(text, typ, bits)} (4096 = 1); type a number such as 0.5"
        except Exception:
            return "4096 = 1; type a number such as 0.5"
    kind = "whole percent" if bits == nlcl.PERCENT else f"Q{bits}"
    try:
        raw = nlcl.parse_value(text, typ, bits)
        return (f"stored as {raw} ({one} = 100%, {kind}); type a percentage (150 or 150%), or "
                f"0x.. for the stored value")
    except Exception:
        return f"{one} = 100% ({kind}); type a percentage such as 150"

def _max_rows():
    """Rows shown in big tables before 'refine search' (Options: guiutil.list_rows)."""
    import guiutil
    return guiutil.list_rows()


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
        self.paths: dict[str, pathlib.Path] = {}            # loose files that can be saved in place
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
                    src.paths[name] = fp
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
            raise ValueError(
                f"{bpath.name} is too large to open on its own. Put it next to its "
                f"Manifest.plist, or open the game folder.")
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
            src.paths[rel] = pathlib.Path(full)
        return src

    @classmethod
    def from_file(cls, file) -> "Source":
        p = pathlib.Path(file)
        src = cls(f"File: {p.name}")
        src.add(p.name, "", lambda: p.read_bytes(), p.stat().st_size)
        src.paths[p.name] = p
        return src


# --------------------------------------------------------------------------- #
# Main application
# --------------------------------------------------------------------------- #
class _GenHost:
    """Everything map_editor.tabs.EncountersTab asks of an editor (doc.gen, the selected gate,
    apply, status, start_add), for a Gen file shown on its own: the explorer's Gen view uses
    the map editor's Gates pane with a flat picture of the map instead of the editor.
    Edits change the working copy at once (Save / Ctrl+S writes it)."""

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
        self.history = []                # [(label, Gen file before that edit)] for Undo

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

    def _update_gate_focus(self):
        """The Gates list calls this after a pick (the map editor outlines the gate's points
        then). Here set_active_gate already redrew the picture with that gate's points bright."""

    def apply(self, label, _aspects, fn):
        before = self.doc.gen.build()
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - report the refusal, keep the view alive
            self.doc.gen = gen.GenTable(before)
            messagebox.showerror("Not applied", f"{label}:\n{err_text(e)}")
            return False
        if self.doc.gen.build() != before:
            self.history.append((label, before))
        self._changed(label)
        return True

    def undo(self):
        """The toolbar Undo / Ctrl+Z: the Gen file as it was before the last edit."""
        if not self.history:
            return
        label, blob = self.history.pop()
        self.doc.gen = gen.GenTable(blob)
        if self.gate_index is not None:
            pi, ei = self.gate_index
            if pi >= len(self.doc.gen.patterns) or ei >= len(self.doc.gen.patterns[pi]):
                self.gate_index = None
        self._changed(f"Undid: {label}")

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
        self.status(label + "  — Save (Ctrl+S) writes the file")

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

    def before_save(self):
        """Save (toolbar / Ctrl+S) writes the Gen file built from the edits."""
        self.tab.cur_data = self.doc.gen.build()
        return True

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
        self._photo = _tk_photo(img, self._lbl)
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
            "_events_new_scene", "_text_tab", "_manifest_after", "_manifest_filter",
            "_before_save", "_undo", "_can_undo")
    HISTORY = 30                        # working copies kept for Undo (views without their own)

    def __init__(self, frame, on_data=None):
        for name in self.VIEW:
            object.__setattr__(self, name, None)
        self.zoom = 1.0
        self.content = frame            # what the viewers build into
        self.frame = frame
        self.key = None                 # (source label, entry name): the same file opens here
        self.save_path = None           # filesystem path when this tab came from a loose file
        self.saved = None               # the bytes as loaded or last written to a file
        self.header = "Select an asset"
        self.parked = []                # timers that came due while the tab was hidden
        self.on_data = on_data          # called after cur_data changes (the tab's • mark)
        self.history = []               # earlier working copies of this file (Undo)
        self.recording = True           # off while a new file loads or Undo puts one back

    def __setattr__(self, name, value):
        if name == "cur_data":
            prev = self.__dict__.get("cur_data")
            # every change of the working copy is an Undo step -- except in a map tab (its
            # editor keeps its own undo) and while a file loads or Undo restores one
            if (self.__dict__.get("recording", False) and prev is not None and value is not None
                    and value is not prev and self.__dict__.get("_map_panel") is None and value != prev):
                self.history.append(prev)
                del self.history[:-self.HISTORY]
        object.__setattr__(self, name, value)
        if name == "cur_data" and self.on_data is not None:
            self.on_data()

    def load(self, name, data):
        """A file (re)loads into this tab: a different file starts a fresh Undo history."""
        if name != self.cur_name:
            self.history = []
            self.recording = False
            try:
                self.cur_name, self.cur_data = name, data
            finally:
                self.recording = True
        else:
            self.cur_name, self.cur_data = name, data

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
        self._save_btn = ttk.Button(bar, text="Save", command=self.cmd_save)
        self._save_btn.pack(side="left", padx=2, pady=3)
        self._undo_btn = ttk.Button(bar, text="Undo", command=self.cmd_undo, state="disabled")
        self._undo_btn.pack(side="left", padx=2, pady=3)
        ttk.Button(bar, text="Options…", command=self.cmd_options).pack(side="left", padx=2)
        # shown only while something other than the game is listed (see load_source)
        self._back_btn = ttk.Button(bar, text="Back to the game", command=self.cmd_back_to_game)
        from guiutil import Tip
        Tip(self._open_btn, "Look at files that aren't part of the game: one file (a .mbundle opens as "
                            "its files), or every file in a folder (a downloaded mod, "
                            "Bundle\\00_mods, exported files).")
        Tip(self._back_btn, "List the game's files again.")
        Tip(self._save_btn, "Save the file shown (Ctrl+S): a game file goes where the game loads it "
                            "(over its loose copy, or into Bundle\\00_mods when the game only has it "
                            "packed); a file opened from disk is saved over itself. Extract… saves a "
                            "copy anywhere else. To throw your changes away, close the tab.")
        Tip(self._undo_btn, "Undo the last change in the file shown (Ctrl+Z), one step at a time. "
                            "(In a box you are typing in, Ctrl+Z undoes the typing.)")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.extract_btn = ttk.Button(bar, text="Extract…", command=self.cmd_extract, state="disabled")
        self.extract_btn.pack(side="left", padx=2)
        self.export_btn = ttk.Button(bar, text="Export View…", command=self.cmd_export, state="disabled")
        self.export_btn.pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="Cutscenes", command=self.cmd_cutscene_editor).pack(side="left", padx=2)
        # Help (every shortcut) at the very right
        import shortcuts_help
        hb = ttk.Button(bar, text="Help", command=lambda: shortcuts_help.open_help(self.root))
        hb.pack(side="right", padx=(2, 4))
        from guiutil import Tip as _Tip
        _Tip(hb, "Every keyboard shortcut and mouse gesture.")
        self._help_btn = hb
        self.filter_var = tk.StringVar()
        # Debounced: re-filtering ~38k names on EVERY keystroke made typing stutter; wait
        # until the user pauses (Enter applies immediately).
        self._filter_after = None
        self.filter_var.trace_add("write", lambda *_: self._schedule_filter())
        self.cat_var = tk.StringVar(value=self.ALL_CATS)
        # Group maps by area: set in Options… (File list)
        self.group_maps_var = tk.BooleanVar(value=bool(gamepaths.get_setting(GROUP_MAPS_SETTING, True)))

    def _build_body(self):
        from guiutil import Paned, Tip
        paned = Paned(self.root, orient="horizontal")   # no live relayout while dragging
        paned.pack(fill="both", expand=True)
        self._paned = paned
        self._left_collapsed = False

        left = ttk.Frame(paned)
        self._left = left
        paned.add(left, weight=0, minsize=160)   # keeps its width; the content gets the rest
        filters = ttk.Frame(left)
        filters.pack(fill="x", padx=5, pady=(5, 3))
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="Search:").grid(row=0, column=0, sticky="w", padx=(0, 5), pady=2)
        fe = ttk.Entry(filters, textvariable=self.filter_var, width=18)
        fe.grid(row=0, column=1, sticky="ew", pady=2)
        fe.bind("<Return>", lambda _e: self._apply_filter_now())
        ttk.Label(filters, text="Show:").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=2)
        self.cat_cb = ttk.Combobox(filters, textvariable=self.cat_var, state="readonly", width=18,
                                   values=[self.ALL_CATS])
        self.cat_cb.grid(row=1, column=1, sticky="ew", pady=2)
        self.cat_cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_filter_now())
        Tip(self.cat_cb, "Show only one kind of file (textures, voice lines, maps...). Works together "
                         "with Search: Maps + 'city' = every town map.")
        Tip(fe, "Show only files whose name contains this text (Enter applies at once).")
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
        self.root.bind("<Control-W>", lambda _e: self.cmd_close_tab())      # (Caps Lock on)
        self.root.bind("<Control-s>", lambda _e: self.cmd_save())
        self.root.bind("<Control-S>", lambda _e: self.cmd_save())
        self.root.bind("<Control-z>", self._undo_key)
        self.root.bind("<Control-Z>", self._undo_key)
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
            self._game_label = self.source.label        # tabs from this list save into the game
            self._back_btn.pack_forget()
        else:
            self._back_btn.pack(side="left", padx=2, after=self._open_btn)
        self._cur_iid = None
        self._fill_cat_box()                    # this list's categories (keeps the pick if it has it)
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
        else:
            self.status.config(text="No game folder chosen yet: Options… → General → Game folder → Change…")

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
            doc.save_path = p
            self.status.config(text=f"Opened {p} (with {self.source.label})")
        return doc

    def _options_display(self, body):
        """Options -> Appearance -> Display: the text size, applied at once."""
        import guiscale
        from guiutil import Tip
        ttk.Label(body, text="Display", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        row = ttk.Frame(body)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Text size:").pack(side="left")
        self._ui_scale = tk.StringVar(value="%d %%" % guiscale.setting())
        cb = ttk.Combobox(row, textvariable=self._ui_scale, state="readonly", width=7,
                          values=["%d %%" % v for v in guiscale.SCALES])
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda _e: guiscale.set_percent(int(self._ui_scale.get().split()[0])))
        Tip(cb, "Makes every text in the toolkit bigger (lists, editors, menus), in every open "
                "window at once.")

    def _options_rows(self, body):
        """Options -> General: how many rows the big lists show."""
        import guiutil
        from guiutil import Tip
        ttk.Label(body, text="Big lists", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        row2 = ttk.Frame(body)
        row2.pack(anchor="w", pady=(4, 0))
        ttk.Label(row2, text="Rows shown in big lists:").pack(side="left")
        self._list_rows = tk.StringVar(value=str(guiutil.list_rows()))

        def rows_changed(*_a):
            try:
                n = int(self._list_rows.get())
            except ValueError:
                return
            gamepaths.set_setting("list_rows", max(100, min(200000, n)))
        sp = ttk.Spinbox(row2, from_=1000, to=200000, increment=1000, width=8,
                         textvariable=self._list_rows, command=rows_changed)
        sp.pack(side="left", padx=6)
        sp.bind("<FocusOut>", rows_changed)
        sp.bind("<Return>", rows_changed)
        Tip(sp, "Big lists (all 113k dialogue lines, the parameter tables ...) show this many rows, "
                "then 'search to narrow'. More rows take longer to show.")

    def _options_backups(self, body, win):
        """Options -> Backups: keep originals, how many previous versions, the folder, restore."""
        import backup_dialog
        from guiutil import Tip
        ttk.Label(body, text="Backups", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(body, text="With either setting below on, every save of a game file first copies it "
                             "into the backup folder, so a bad save can be undone. Both are off by "
                             "default.\n"
                             "The folder only holds copies: you can delete it, or anything in it, at any "
                             "time to free space (Open shows it). The toolkit makes it again at the next "
                             "save; Restore can then only offer the versions saved since.",
                  foreground="#666", wraplength=380, justify="left").pack(anchor="w", pady=(2, 0))
        self._bk_orig = tk.BooleanVar(value=gamepaths.keep_originals())
        ttk.Checkbutton(body, text="Keep each game file's original (copied the first time it is saved)",
                        variable=self._bk_orig,
                        command=lambda: gamepaths.set_setting("backup_originals", bool(self._bk_orig.get()))
                        ).pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(body)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Previous versions kept per file:").pack(side="left")
        self._bk_prev = tk.StringVar(value=str(gamepaths.keep_previous()))

        def prev_changed(*_a):
            try:
                n = max(0, min(50, int(self._bk_prev.get())))
            except ValueError:
                return
            gamepaths.set_setting("backup_previous", n)
        sp = ttk.Spinbox(row, from_=0, to=50, width=4, textvariable=self._bk_prev, command=prev_changed)
        sp.pack(side="left", padx=6)
        sp.bind("<FocusOut>", prev_changed)
        sp.bind("<Return>", prev_changed)
        Tip(sp, "Every save keeps the file as it was before; the oldest beyond this number are "
                "deleted. 0 = keep none.")
        frow = ttk.Frame(body)
        frow.pack(anchor="w", fill="x", pady=(4, 0))
        self._bk_dir = tk.StringVar(value=str(gamepaths.backup_root() or "(set the game folder first)"))
        ttk.Label(frow, text="Folder:").pack(side="left")
        ttk.Label(frow, textvariable=self._bk_dir, foreground="#666", wraplength=420,
                  justify="left").pack(side="left", padx=6)

        def choose():
            d = filedialog.askdirectory(title="Backup folder", parent=win)
            bd = gamepaths.find_bundle_dir()
            if d and bd is not None:
                try:
                    inside = pathlib.Path(d).resolve().is_relative_to(pathlib.Path(bd).resolve())
                except (OSError, ValueError):
                    inside = False
                if inside:
                    messagebox.showerror("Backup folder", "Pick a folder outside the game's Bundle "
                                         "folder: the game would load the backups.", parent=win)
                    return
            if d:
                gamepaths.set_setting("backup_dir", d)
                self._bk_dir.set(str(gamepaths.backup_root()))

        def default():
            gamepaths.set_setting("backup_dir", None)
            self._bk_dir.set(str(gamepaths.backup_root() or "(set the game folder first)"))
        brow = ttk.Frame(body)
        brow.pack(anchor="w", pady=(4, 0))
        for text, cmd, tip in (("Change…", choose, "Keep the backups in another folder."),
                               ("Default", default, "Back to ModdingBackup next to the game's Bundle folder."),
                               ("Open", backup_dialog.open_folder, "Open the backup folder in Explorer."),
                               ("Restore a previous version…",
                                lambda: backup_dialog.open_restore(win), "Put an original or a "
                                "previous version of a game file back.")):
            b = ttk.Button(brow, text=text, command=cmd)
            b.pack(side="left", padx=(0, 4))
            Tip(b, tip)

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
        win.resizable(False, True)
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        nb = ttk.Notebook(body)
        self._options_nb = nb
        self._options_pages = {}                # page frame path -> tab title
        scrolls = []

        def tab(title):
            # each tab scrolls on its own, so the window fits on a small screen
            sf = ScrollFrame(nb)
            nb.add(sf, text=title)
            f = ttk.Frame(sf.body, padding=12)
            f.pack(fill="both", expand=True)
            scrolls.append((sf, f))
            self._options_pages[str(f)] = title
            return f
        from guiutil import ScrollFrame, Tip
        import guitheme
        # -- General: the game folder, the file list, big lists
        gen = tab("General")
        ttk.Label(gen, text="Game folder", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._game_dir = tk.StringVar()

        def show_game():
            b = gamepaths.find_bundle_dir()        # the game folder: the one holding Bundle and RF4S.exe
            self._game_dir.set(str(b.parent) if b is not None else "(none chosen yet)")
        show_game()
        grow = ttk.Frame(gen)
        grow.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(grow, textvariable=self._game_dir, foreground="#666", wraplength=380,
                  justify="left").pack(side="left")

        def change_game():
            self.cmd_game_folder()
            show_game()
        cg = ttk.Button(gen, text="Change…", command=change_game)
        cg.pack(anchor="w", pady=(4, 0))
        Tip(cg, "Choose the game folder every tool uses, or make a copy. Takes effect after a restart.")
        ttk.Label(gen, text="File list", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        gm = ttk.Checkbutton(gen, text="Group maps by area", variable=self.group_maps_var,
                             command=self.cmd_group_maps)
        gm.pack(anchor="w", pady=(4, 0))
        Tip(gm, "List the .rf4m maps under a header per in-game area (Rune Prana, Selphia: "
                "Town Square, ...), each one opens and closes. Off: one flat list of files.")
        self._options_rows(gen)
        # -- Appearance: light / dark, text size
        app_tab = tab("Appearance")
        ttk.Label(app_tab, text="Theme", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._theme_var = tk.StringVar(value=guitheme.setting())
        row = ttk.Frame(app_tab)
        row.pack(anchor="w", pady=(4, 0))
        for m in guitheme.MODES:
            ttk.Radiobutton(row, text=guitheme.LABELS[m], value=m, variable=self._theme_var,
                            command=lambda: guitheme.set_mode(self._theme_var.get())).pack(side="left", padx=(0, 10))
        self._options_display(app_tab)
        # -- Map editor
        me = tab("Map editor")
        ttk.Label(me, text="Mouse wheel", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._wheel_zooms = tk.BooleanVar(value=map_view.wheel_mode() == "zoom")

        def wheel_changed():
            map_view.set_wheel_mode("zoom" if self._wheel_zooms.get() else "scroll")
        ttk.Checkbutton(me, text="Mouse wheel zooms the map", variable=self._wheel_zooms,
                        command=wheel_changed).pack(anchor="w", pady=(4, 0))
        ttk.Label(me, text="Unticked, the wheel scrolls the map instead. Ctrl+wheel always does "
                           "the other one; Shift+wheel scrolls sideways.",
                  foreground="#666", wraplength=360, justify="left").pack(anchor="w", padx=(20, 0))
        # -- Cutscene Editor
        ce = tab("Cutscene Editor")
        from cutscene_editor.app import CutsceneExplorer
        ttk.Label(ce, text="Adding dialogue lines", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._pad_locales = tk.BooleanVar(value=CutsceneExplorer.pad_locales_setting())

        def pad_changed():
            on = bool(self._pad_locales.get())
            CutsceneExplorer.set_pad_locales_setting(on)
            cur = getattr(self, "_cutscene_ed", None)      # an open editor follows at once
            try:
                if cur is not None and cur[0].winfo_exists():
                    cur[1].pad_locales.set(on)
            except tk.TclError:
                pass
        pl = ttk.Checkbutton(ce, text="Add new lines to every language", variable=self._pad_locales,
                             command=pad_changed)
        pl.pack(anchor="w", pady=(4, 0))
        ttk.Label(ce, text="Each language has its own dialogue file, and a scene shows a line by its "
                           "number. A line you add is also added to the other languages' files "
                           "(in your text, untranslated), so it has the same number everywhere and "
                           "shows in every language. Unticked, only the language you edit gets it: "
                           "players of the other languages would see a wrong line instead.",
                  foreground="#666", wraplength=380, justify="left").pack(anchor="w", padx=(20, 0))
        ttk.Label(ce, text="Variables", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        self._var_editor = tk.BooleanVar(value=CutsceneExplorer.variable_editor_setting())

        def var_editor_changed():
            CutsceneExplorer.set_variable_editor_setting(bool(self._var_editor.get()))
            cur = getattr(self, "_cutscene_ed", None)      # an open editor follows at once
            try:
                if cur is not None and cur[0].winfo_exists():
                    cur[1].apply_variable_editor()
            except tk.TclError:
                pass
        ttk.Checkbutton(ce, text="Variable editor", variable=self._var_editor,
                        command=var_editor_changed).pack(anchor="w", pady=(4, 0))
        ttk.Label(ce, text="Adds a Variables… button to Reference → Flags & variables: rename variables "
                           "and name unused bits as your own. The names go in a separate file the game "
                           "never reads. Off: the list is read-only.",
                  foreground="#666", wraplength=380, justify="left").pack(anchor="w", padx=(20, 0))
        ttk.Label(ce, text="Add-an-instruction list", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        self._list_groups = {}
        for which, text, note in (
                ("most_used", 'Show "Most used"',
                 "A fixed group on top: DIALOG, the choice menu, EVAL and the verified instructions "
                 "the game's own scenes use most (not your own habits)."),
                ("recent", 'Show "Recently used"',
                 "The last 8 instructions you inserted.")):
            var = tk.BooleanVar(value=CutsceneExplorer.list_group_setting(which))
            self._list_groups[which] = var

            def group_changed(which=which, var=var):
                CutsceneExplorer.set_list_group_setting(which, bool(var.get()))
                cur = getattr(self, "_cutscene_ed", None)  # an open editor follows at once
                try:
                    if cur is not None and cur[0].winfo_exists():
                        cur[1].refresh_instruction_list()
                except tk.TclError:
                    pass
            ttk.Checkbutton(ce, text=text, variable=var, command=group_changed).pack(anchor="w", pady=(4, 0))
            ttk.Label(ce, text=note, foreground="#666", wraplength=380,
                      justify="left").pack(anchor="w", padx=(20, 0))
        # -- Advanced: backups (off by default)
        adv = tab("Advanced")
        self._options_backups(adv, win)
        ttk.Label(adv, text="Cutscene Editor", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        self._bank_listing = tk.BooleanVar(value=CutsceneExplorer.bank_listing_setting())

        def listing_changed():
            on = bool(self._bank_listing.get())
            CutsceneExplorer.set_bank_listing_setting(on)
            cur = getattr(self, "_cutscene_ed", None)      # an open editor follows at once
            try:
                if cur is not None and cur[0].winfo_exists():
                    cur[1].show_bank_listing(on)
            except tk.TclError:
                pass
        ttk.Checkbutton(adv, text="Bank listing tab", variable=self._bank_listing,
                        command=listing_changed).pack(anchor="w", pady=(4, 0))
        ttk.Label(adv, text="Adds a tab with the whole open bank as one read-only listing: every "
                            "scene, also those no trigger starts, with the code they share. Find "
                            "searches it; a double click opens that scene at that line.",
                  foreground="#666", wraplength=380, justify="left").pack(anchor="w", padx=(20, 0))
        self._ref_unverified = tk.BooleanVar(value=CutsceneExplorer.reference_unverified_setting())
        self._ref_csv = tk.BooleanVar(value=CutsceneExplorer.reference_csv_setting())

        def reference_changed():
            CutsceneExplorer.set_reference_unverified_setting(bool(self._ref_unverified.get()))
            CutsceneExplorer.set_reference_csv_setting(bool(self._ref_csv.get()))
            cur = getattr(self, "_cutscene_ed", None)      # an open Reference follows at once
            try:
                if cur is not None and cur[0].winfo_exists():
                    cur[1].refresh_reference()
            except tk.TclError:
                pass
        ttk.Checkbutton(adv, text="Show unverified instructions in the Reference", variable=self._ref_unverified,
                        command=reference_changed).pack(anchor="w", pady=(6, 0))
        ttk.Label(adv, text="The Reference window's Functions tab lists every instruction, with a ✓ "
                            "on the ones checked in game; unticked it lists only the checked ones.",
                  foreground="#666", wraplength=380, justify="left").pack(anchor="w", padx=(20, 0))
        ttk.Checkbutton(adv, text="Export CSV buttons in the Reference", variable=self._ref_csv,
                        command=reference_changed).pack(anchor="w", pady=(6, 0))
        ttk.Label(adv, text="Every list in the Reference window gets an Export CSV… button that saves "
                            "the rows the filter lets through, in the list's order.",
                  foreground="#666", wraplength=380, justify="left").pack(anchor="w", padx=(20, 0))
        self._play_scene = tk.BooleanVar(value=CutsceneExplorer.play_scene_setting())

        def play_changed():
            CutsceneExplorer.set_play_scene_setting(bool(self._play_scene.get()))
            cur = getattr(self, "_cutscene_ed", None)      # an open editor follows at once
            try:
                if cur is not None and cur[0].winfo_exists():
                    cur[1].apply_play_scene()
            except tk.TclError:
                pass
        ttk.Checkbutton(adv, text="Play this scene now (Debug menu)", variable=self._play_scene,
                        command=play_changed).pack(anchor="w", pady=(6, 0))
        ttk.Label(adv, text="Starts the open scene in the game the Debugger is attached to, without "
                            "walking to its trigger (Ctrl+Shift+P): scenes of the map you stand "
                            "on only. It runs for real -- flags can be put back afterwards, items, "
                            "money and the party cannot. Use a throwaway save.",
                  foreground="#666", wraplength=380, justify="left").pack(anchor="w", padx=(20, 0))
        # bottom row: the toolkit's version (commit + date, selectable for bug reports) on the
        # left, its text sitting on the same line as the bottom of Close on the right
        foot = ttk.Frame(body)
        foot.pack(side="bottom", fill="x", pady=(12, 0))
        nb.pack(fill="both", expand=True)       # after the footer: a short window shrinks the tabs
        ttk.Button(foot, text="Close", command=win.destroy).pack(side="right")
        import guiutil
        ver = tk.StringVar(value="Modkit version " + guiutil.modkit_version())
        vent = tk.Entry(foot, textvariable=ver, state="readonly", relief="flat", borderwidth=0,
                        foreground="#888888", font=("Segoe UI", 8), width=len(ver.get()) + 2,
                        highlightthickness=0)
        vent.pack(side="left", anchor="s")

        def match_window(_e=None):                 # the window's colour, also after a theme switch
            bg = ttk.Style(win).lookup("TFrame", "background") or win.cget("background")
            vent.configure(readonlybackground=bg)
        match_window()
        vent.bind("<<AppearanceChanged>>", match_window, add="+")   # (guitheme, after a switch)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        # every tab as wide as the widest page and as tall as the tallest, but the window no
        # taller than the screen: the rest scrolls
        pw = max(f.winfo_reqwidth() for _sf, f in scrolls)
        ph = max(f.winfo_reqheight() for _sf, f in scrolls)
        for sf, _f in scrolls:
            sf.canvas.configure(width=pw, height=ph)
            sf.bind_wheel_tree()
        win.update_idletasks()
        top = max(0, self.root.winfo_rooty() + 80)
        room = win.winfo_screenheight() - 80     # (the taskbar and the title bar)
        if top + win.winfo_reqheight() > room:
            top = max(0, min(top, room - win.winfo_reqheight()))
        h = min(win.winfo_reqheight(), room - top)
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        win.geometry(f"{win.winfo_reqwidth()}x{h}+{max(0, x)}+{top}")
        return win

    def cmd_game_folder(self):
        """Show / change the game copy every tool uses (takes effect on the next start)."""
        import game_setup
        before = gamepaths.find_bundle_dir()
        was_unpacked = before is not None and gamepaths.is_unpacked(before)
        if game_setup.run(self.root, current=before) and gamepaths.find_bundle_dir() != before:
            messagebox.showinfo("Game folder", "Saved. Restart the toolkit now: until then some "
                                "tools still use the old game folder.", parent=self.root)
        elif before is not None and not was_unpacked and gamepaths.is_unpacked(before):
            messagebox.showinfo("Game folder", "The game files are unpacked. Close and start "
                                "the toolkit again so every tool reads them.", parent=self.root)

    def cmd_open_folder(self):
        d = filedialog.askdirectory(title="Open a folder of files",
                                    initialdir=str(EXTRACTED if EXTRACTED.is_dir() else gamepaths.TOOLKIT))
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
        cat = assetcat.title(self.source.categories()[i])
        who = _model_owner(self.source.entries[i][0])
        return (f"{cat} · {who}" if who else cat, self._fmt_size(self.source.sizes[i]))

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
        every name on each refresh). A model's text also holds who wears it, so 'frey' finds
        NPC_PLAYER_01.model."""
        src = self.source
        if getattr(src, "_lower", None) is None or len(src._lower) != len(src.entries):
            src._lower = [(e[0] + ("  " + who if (who := _model_owner(e[0])) else "")).lower()
                          for e in src.entries]
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
        ed = getattr(self, "_cutscene_ed", None)       # its window goes with the main one
        try:
            if ed is not None and ed[0].winfo_exists() and not ed[1].confirm_discard("close the toolkit"):
                return
        except tk.TclError:
            pass
        for doc in list(self._docs):
            if not self._save_model_before_close(doc):
                return
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
        doc = self._open_in_tab(key, name, data, mode)
        if doc is not None:
            doc.save_path = self.source.paths.get(name)

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
        self._update_undo_btn()

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
            f"file.\n\nSave it before you {action}?\n(Yes = save, No = discard, "
            "Cancel = stay here)", parent=self.root)
        if ans is None:
            return False
        return self.save_doc(doc) if ans else True

    def _save_model_before_close(self, doc):
        """Save edited .model working copies from loose files when the app exits."""
        if (doc.cur_name or "").lower().endswith(".model") and doc.is_dirty() and doc.save_path:
            return self._write_doc(doc, doc.save_path)
        return True

    def _write_doc(self, doc, path):
        path = pathlib.Path(path)
        try:
            path.write_bytes(doc.cur_data)
        except OSError as e:
            messagebox.showerror("Save failed", f"Could not save {path}:\n{err_text(e)}", parent=self.root)
            return False
        doc.save_path = path
        self._mark_saved(doc)
        self.status.config(text=f"Saved {doc.cur_name} → {path}")
        return True

    # ---- Undo (the toolbar button, Ctrl+Z): the shown tab's last change ---------------------
    def can_undo(self, doc):
        """Something to undo in `doc`: its map editor's history, its view's own (doc._can_undo),
        else the tab's earlier working copies."""
        if doc is self._blank:
            return False
        panel = doc._map_panel
        if panel is not None:
            return bool(getattr(panel.doc, "undo_stack", None)) if panel.doc is not None else False
        if doc._can_undo is not None:
            return bool(doc._can_undo())
        return bool(doc.history)

    def undo_doc(self, doc):
        """Undo the last change in `doc`: a map tab through its editor, a view with its own
        history (keeps the selection) through doc._undo, any other view by putting the previous
        working copy back and showing it again."""
        panel = doc._map_panel
        if panel is not None:
            panel.undo()
        elif doc._undo is not None:
            doc._undo()
        elif doc.history:
            prev = doc.history.pop()
            doc.recording = False
            try:
                self._show(doc.cur_name, prev, doc)
            finally:
                doc.recording = True
            self.status.config(text="Undone")
        else:
            self.status.config(text="Nothing to undo")
        self._update_undo_btn()

    def cmd_undo(self):
        if self._doc is not self._blank:
            self.undo_doc(self._doc)
        return "break"

    def _undo_key(self, e):
        """Ctrl+Z: a text box being typed in undoes its own typing; anywhere else the tab's."""
        if e.widget.winfo_class() in ("Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox"):
            return None
        return self.cmd_undo()

    def _update_undo_btn(self):
        try:
            self._undo_btn.state(["!disabled"] if self.can_undo(self._doc) else ["disabled"])
        except (tk.TclError, AttributeError):
            pass

    def cmd_save(self):
        """Save (the toolbar button, Ctrl+S): the shown tab (save_doc)."""
        if self._doc is not self._blank:
            self.save_doc(self._doc)
        return "break"

    def save_doc(self, doc):
        """Write a tab's working copy where it belongs; True when it was written (or there was
        nothing to write).
          * a map tab: its editor's Save (the map, its search spots and monster gates);
          * one of the game's files: where the game loads it -- over the copy it reads now, else
            Bundle\\00_mods when it only has it packed (gamepaths.game_targets; originals and
            earlier versions kept as set in Options);
          * a file opened from disk: over that file;
          * otherwise (a packed file with no game folder chosen): a Save as dialog, and later
            saves go to the file picked there.
        A viewer that keeps edits outside the working copy (an assembler listing, the Gen view)
        sets doc._before_save, which brings cur_data up to date or returns False to stop."""
        if doc.cur_data is None:
            return True
        panel = doc._map_panel
        if panel is not None:
            try:
                return bool(panel.save_to_game())
            except tk.TclError:
                return False
        if doc._text_tab is not None:           # the text editor saves the same way, plus its notes
            return doc._text_tab.save() is not None
        prep = getattr(doc, "_before_save", None)
        if prep is not None and prep() is False:
            return False
        name = pathlib.PurePosixPath((doc.cur_name or "").replace("\\", "/")).name
        game_label = self.__dict__.get("_game_label")
        if doc.key is not None and game_label is not None and doc.key[0] == game_label and name:
            from rf4s_modkit import gamepaths
            targets = gamepaths.game_targets([name])
            if targets is not None:
                target = targets[name]
                try:
                    backed = gamepaths.write_game_file(target, doc.cur_data)
                except OSError as e:
                    messagebox.showerror("Save failed", f"Could not write {target}:\n{err_text(e)}\n\n"
                                                        "(Is the game running with the file open?)", parent=self.root)
                    return False
                doc.save_path = target
                self._mark_saved(doc)
                bdir = gamepaths.find_bundle_dir()
                shown = target.relative_to(bdir.parent) if bdir and bdir.parent in target.parents else target
                self.status.config(text=f"Saved {name} → {shown}" + (
                    f" (original kept in {gamepaths.BACKUP_DIR})" if backed else "")
                    + " -- the game reads it the next time it loads the file")
                try:                            # a packed patch bundle wins over every loose file
                    from rf4s_modkit import mbundle
                    shadow = mbundle.patch_shadows(bdir).get(name) if bdir is not None else None
                except Exception:  # noqa: BLE001 -- no manifest: nothing to say
                    shadow = None
                if shadow:
                    messagebox.showwarning(
                        "Saved, but the game won't use it",
                        f"Saved {shown}, but the game ignores it while {shadow} (packed) holds {name}: "
                        f"that archive is loaded ahead of the Bundle folder. Unpack it (rf4mod unpack) "
                        f"or move it out of the Bundle folder.", parent=self.root)
                others = targets[None].get(name)
                if others:
                    messagebox.showwarning(
                        "Other copies", f"Saved {shown}. The game ignores these other copies of "
                        f"{name} (they sort later, or differ only in upper / lower case):\n\n"
                        + "\n".join(f"• {o}" for o in others[:8]), parent=self.root)
                return True
        if doc.save_path is not None:
            return self._write_doc(doc, doc.save_path)
        f = filedialog.asksaveasfilename(title="Save", initialfile=name or None, parent=self.root)
        return self._write_doc(doc, f) if f else False

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
        self._update_undo_btn()

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
        doc._before_save = doc._undo = doc._can_undo = None     # the new view sets its own
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
        doc.load(name, data)
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
                "mycf": self._view_mycf,
                "param": self._view_param,
                "search_items": self._view_search_items,
                "route": self._view_route,
                "route_result": self._view_route_result,
                "schedule": self._view_schedule,
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
            elif base == "rf3cropparam.bin":
                handler = self._view_crop
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
            self._view_hex(name, data, error=err_text(e))
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
        ttk.Button(bar, text="Replace…",
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
                                f"{len(blob):,} bytes (was {before:,}); Save (Ctrl+S) puts it in the game")
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
                                f"{len(blob):,} bytes (was {before:,}); Save (Ctrl+S) puts it in the game")
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
                                f"Save (Ctrl+S) puts it in the game")
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
        Updates the working copy (cur_data) like the other editors; Save writes it."""
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
        size = "same size" if len(blob) == before else f"was {before:,}"
        if changes:
            size += "; " + ", ".join("%dx%d -> %dx%d" % (c["old"] + c["new"]) for c in changes)
        self.status.config(text=f"Replaced {which}pixels from {pathlib.Path(f).name} -> "
                                f"{len(blob):,} bytes ({size}; Save (Ctrl+S) puts it in the game)")

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
                key = self._entry_key(name)
                other = next((d for d in self._docs if d.key == key and d is not doc), None)
                if other is not None:              # already open: one tab per file
                    self._select_doc(other)
                    return
                if doc.is_dirty():                 # never replace unsaved edits: a new tab
                    self._open_in_tab(key, name, data, "new")
                    return
                doc.load(name, data)
                doc.key, doc.saved = key, data
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
            focus_bank=focus_bank, focus_entry=focus_entry, focus_pc=focus_pc,
            on_open_map=self._open_map_from_script)
        self._cutscene_ed = (win, ex)
        return ex

    def _open_map_from_script(self, map_file):
        """The Cutscene Editor's Open map: the map in its tab here (selected in the file list),
        this window brought to the front. `map_file` is the game's exact name (MAP_CITY_00)."""
        want = map_file if map_file.lower().endswith(".rf4m") else map_file + ".rf4m"
        ents = self.source.entries if self.source else []
        i = next((k for k, e in enumerate(ents) if pathlib.PurePath(e[0]).name == want), None)
        if i is None:
            self.status.config(text=f"{want} is not in the file list (Back to the game?)")
            return False
        name, _g, loader = ents[i]
        self._reveal_entry(i)
        doc = self._open_in_tab(self._entry_key(name), name, loader())
        panel = getattr(doc, "_map_panel", None) if doc is not None else None
        if panel is not None:
            panel.show_script_layers()          # the script's spawns and trigger boxes
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass
        self.status.config(text=f"{map_file}: opened from the Cutscene Editor")
        return True

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
            info.config(text=f"{stem} is not a known room, so it has no scenes.")
            return

        raw = self.source.read_named("rf3.mc") if self.source else None
        if not raw:
            info.config(text="This map's scenes are in rf3.mc, which isn't in the file list. "
                             "Click Back to the game to see them here.")
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

        info.config(text=f"{resolved}: {len(entries)} scenes, {ndlg} dialogue lines"
                         + (" — double-click one to edit it." if entries
                            else " — no scenes yet (New scene on this map… adds one)."))

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
            lb.insert("end", f"{nline:>2} lines  {preview or '(no dialogue)'}"
                             + (" (partly read)" if flag else ""))
            row_entry_pc.append(epc)

        def open_editor(_e=None):
            sel = lb.curselection()
            entry_pc = row_entry_pc[sel[0]] if sel else None
            self.cutscene_editor(bank_index, entry_pc)

        def new_scene():
            """'New scene on this map…': open the Cutscene Editor on this map's event (tail)
            bank and go straight into its New-scene dialog with the map-enter type preselected
            (MapEnterScene, type 6 -- taken from the entry-type catalogue when it names it).
            The scene lands in that editor's in-memory rf3.mc: its Save menu / Install
            write it (this tab keeps listing the shipped file)."""
            import cutscene_editor
            ex = self.cutscene_editor(bank_index)
            res = ex.open_new_scene_dialog(bank_index,
                                           default_type=cutscene_editor.map_enter_type())
            if res is not None:
                self.status.config(
                    text="New scene added in the Cutscene Editor. Save it there; this list shows "
                         "the saved file.")
            return res

        lb.bind("<Double-Button-1>", open_editor)
        b = ttk.Button(frame, text="Open in Cutscene Editor →", command=open_editor)
        b.pack(fill="x", padx=6, pady=(0, 2))
        nsb = ttk.Button(frame, text="New scene on this map…", command=new_scene)
        nsb.pack(fill="x", padx=6, pady=(0, 2))
        ttk.Label(frame, foreground="#888", justify="left",
                  text="New scene…: a scene that plays when the player enters this map. Only one "
                       "runs per map; the dialog warns if there is one already.").pack(fill="x", padx=6)
        if ta is None:
            ttk.Label(frame, justify="left", text="(no dialogue previews: the dialogue file isn't in "
                                                  "the file list)").pack(fill="x", padx=6)
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
        doc._export_kind = "plistjson"; doc._export_data = data
        self.export_btn.config(state="normal")
        # Manifest.plist: each bundle by name with its files under it, and a filter
        bundles = root_obj.get("bundles") if isinstance(root_obj, dict) else None
        if isinstance(bundles, list) and bundles and all(
                isinstance(b, dict) and "bundleName" in b for b in bundles):
            return self._view_manifest(doc, bundles)
        tv = ttk.Treeview(doc.content, columns=("val",), show="tree headings")
        tv.heading("#0", text="Key / Index"); tv.heading("val", text="Value")
        tv.column("val", width=700)
        vs = ttk.Scrollbar(doc.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)

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

    def _view_manifest(self, doc, bundles):
        """Manifest.plist: one row per bundle, its files under it (filled on expand), Size /
        Offset columns, a filter on the file name and Copy (tab-separated rows)."""
        bar = ttk.Frame(doc.content)
        bar.pack(side="top", fill="x", padx=4, pady=(4, 2))
        ttk.Label(bar, text="Filter:").pack(side="left")
        var = tk.StringVar()
        fe = ttk.Entry(bar, textvariable=var, width=32)
        fe.pack(side="left", padx=4)
        count = ttk.Label(bar, text="")
        count.pack(side="left", padx=6)
        copy_btn = ttk.Button(bar, text="Copy")
        copy_btn.pack(side="right")
        Tip(fe, "Show only files whose name contains this text (any case); Enter applies at once.")
        Tip(copy_btn, "Copy the selected files, or every file shown when none is selected: "
                      "bundle, file, size, offset (tab-separated, pastes into a spreadsheet).")
        tv = ttk.Treeview(doc.content, columns=("size", "offset"), show="tree headings")
        tv.heading("#0", text="Bundle / file")
        tv.heading("size", text="Size"); tv.heading("offset", text="Offset")
        tv.column("#0", width=420)
        tv.column("size", width=110, anchor="e"); tv.column("offset", width=130, anchor="e")
        vs = ttk.Scrollbar(doc.content, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        doc._bplist_files = {}
        rows = {}                                   # tree item -> (bundle, file, size, offset)

        def file_rows(node, bname, files, keep=None):
            for fk, fv in files.items():
                if keep is not None and keep not in str(fk).lower():
                    continue
                size, off = (fv.get("size"), fv.get("offset")) if isinstance(fv, dict) else ("", "")
                iid = tv.insert(node, "end", text=str(fk), values=(size, off))
                rows[iid] = (bname, str(fk), size, off)

        def refill():
            doc._manifest_after = None
            if not tv.winfo_exists():                   # the tab was closed meanwhile
                return
            tv.delete(*tv.get_children())
            rows.clear(); doc._bplist_files = {}
            text = var.get().strip().lower()
            shown = total = 0
            for b in bundles:
                bname = str(b.get("bundleName"))
                files = b.get("files", {})
                files = files if isinstance(files, dict) else {}
                total += len(files)
                if not text:
                    node = tv.insert("", "end", text=bname, values=(f"{len(files)} files", ""))
                    if files:
                        doc._bplist_files[node] = (bname, files)
                        tv.insert(node, "end", text="…")      # placeholder -> expand arrow
                    shown += len(files)
                    continue
                n = sum(text in str(k).lower() for k in files)
                if n:
                    node = tv.insert("", "end", text=bname, values=(f"{n} of {len(files)}", ""),
                                     open=True)
                    file_rows(node, bname, files, text)
                    shown += n
            count.config(text=f"{total:,} files" if not text else f"{shown:,} of {total:,} files")

        def expand(_e=None):
            nid = tv.focus()
            got = doc._bplist_files.pop(nid, None)
            if got is not None:
                tv.delete(*tv.get_children(nid))            # drop the placeholder
                file_rows(nid, *got)

        def schedule(*_):
            if getattr(doc, "_manifest_after", None):
                self.root.after_cancel(doc._manifest_after)
            doc._manifest_after = self.root.after(250, refill)

        def copy():
            sel = [i for i in tv.selection() if i in rows]
            if not sel:                      # bundle rows selected: their files; else all shown
                picked = tv.selection() or tv.get_children()
                for p in picked:
                    got = doc._bplist_files.pop(p, None)
                    if got is not None:                 # not expanded yet: fill it now
                        tv.delete(*tv.get_children(p))
                        file_rows(p, *got)
                sel = [c for p in picked for c in tv.get_children(p) if c in rows]
            if not sel:
                count.config(text="nothing to copy (expand a bundle or filter first)")
                return
            lines = ["bundle\tfile\tsize\toffset"] + ["\t".join(map(str, rows[i])) for i in sel]
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines) + "\n")
            count.config(text=f"copied {len(sel):,} row(s)")

        var.trace_add("write", schedule)
        fe.bind("<Return>", lambda _e: refill())
        copy_btn.config(command=copy)
        tv.bind("<<TreeviewOpen>>", expand)
        tv.bind("<Control-c>", lambda _e: copy())
        doc._manifest_filter = var                  # (tests)
        refill()

    def _save_blob_as(self, doc, blob, what):
        """Ask for a file name and write `blob` (the working copy) there; the tab is then saved."""
        f = filedialog.asksaveasfilename(defaultextension=pathlib.Path(doc.cur_name).suffix or ".bin",
                                         initialfile=pathlib.Path(doc.cur_name).name,
                                         filetypes=[("Game file", "*" + (pathlib.Path(doc.cur_name).suffix or ".bin")),
                                                    ("All", "*.*")])
        if f:
            pathlib.Path(f).write_bytes(blob)
            self._mark_saved(doc)
            self.status.config(text=f"Saved {what} → {f}")
        return f

    def _view_aibn(self, name, data):
        """AI_*.bin monster / NPC AI script: the listing is editable; Assemble rebuilds the file
        from it (the same assembler as `rf4mod ai asm`; every shipped file round-trips)."""
        doc = self._doc
        toks = aibn.load_tokens(data)
        dis = aibn.disassemble(toks, annotate=True)
        bar = ttk.Frame(doc.content); bar.pack(fill="x", pady=2)
        msg = ttk.Label(bar, foreground="#0d5f8f")
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        c = aibn.stats(toks)
        txt.insert("end", f"# {name}: {len(toks)} tokens, {sum(c.values())} statements"
                          f"  (sub N: / N: labels, if (...) {{ }} blocks, Action(args); trailing # = verified operand meanings;"
                          f" rf4mod ai ops <op> for details; Assemble rebuilds the file from this text)\n\n")
        txt.insert("end", dis)
        txt.edit_reset() if hasattr(txt, "edit_reset") else None
        doc._export_kind = "disasm"; doc._export_text = dis
        self.export_btn.config(state="normal")

        def assemble():
            try:
                blob = aibn.build(aibn.assemble(txt.get("1.0", "end-1c")))
            except Exception as e:  # noqa: BLE001 -- the assembler names the bad line
                msg.config(text=f"Not assembled: {err_text(e)}", foreground="#b02020")
                return None
            doc.cur_data = blob
            same = blob == data
            msg.config(text=("Assembled — unchanged from the file" if same else
                             f"Assembled ({len(blob)} bytes) — Save (Ctrl+S) writes it"), foreground="#1d7a3a")
            return blob

        doc._before_save = lambda: assemble() is not None   # Save writes the assembled listing
        b1 = ttk.Button(bar, text="Assemble", command=assemble); b1.pack(side="left", padx=4)
        from guiutil import Tip
        Tip(b1, "Rebuild the AI file from the listing (checks it; errors name the line). The tab "
                "then holds the new file: Save (Ctrl+S) writes it.")
        msg.pack(side="left", padx=8)
        doc._aibn_assemble = assemble             # (selftest)
        doc._aibn_text = txt

    def _view_mycf(self, name, data):
        """rf3.mc (the cutscene / event scripts): selecting it opens the Cutscene Editor (the one
        window, brought forward when it is open already); the tab says so and can reopen it."""
        doc = self._doc
        box = ttk.Frame(doc.content, padding=16)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="rf3.mc — the cutscene and event scripts", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(box, wraplength=640, justify="left", foreground="#666", text=(
            "Every scene, NPC talk and map event of the game. It opens in the Cutscene Editor, "
            "together with the dialogue text and the event rules.")).pack(anchor="w", pady=(6, 10))
        b = ttk.Button(box, text="Open in the Cutscene Editor", command=self.cmd_cutscene_editor)
        b.pack(anchor="w")
        from guiutil import Tip
        Tip(b, "Open the Cutscene Editor window, or bring it to the front.")
        if not getattr(self, "_testing", False):
            self.root.after_idle(self.cmd_cutscene_editor)      # after the list has its selection

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
        ttk.Label(bar, text="The game's event rules (what starts a date, a marriage, a shop …). "
                            "Open the Event Manager to read and edit them.").pack(side="left")
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
        """E-mote portrait (.psbData / .emtbytes), view only. Atlas tab: the PSB summary and the
        part atlas on a zoomable canvas (Export = PNG) with every part outlined -- click one to
        identify it. Parts tab: each part's rectangle, origin and z-order (double-click shows
        it on the atlas). Tree tab: the whole PSB tree, expandable, text repaired for display;
        Export as JSON. Repaint via `rf4mod psb replace-texture`.
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
        t = texs[0]
        icons = {k: v for k, v in (t["icons"] or {}).items() if isinstance(v, dict)}
        st = {"sel": None, "outline": tk.BooleanVar(value=True)}

        def rect(ic):
            x, y = float(ic.get("left", 0)), float(ic.get("top", 0))
            return x, y, x + float(ic.get("width", 0)), y + float(ic.get("height", 0))

        def zorder(ic):
            md = ic.get("metadata")
            return md.get("zorder", "") if isinstance(md, dict) else ""

        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"E-mote atlas '{t['source']}'  {t['type']} {t['width']}x{t['height']}"
                            f"  {len(icons)} parts").pack(side="left", padx=6)
        for z, lbl in ((0.25, "¼×"), (0.5, "½×"), (1, "1×"), (2, "2×")):
            ttk.Button(bar, text=lbl, width=4, command=lambda z=z: zoom(z)).pack(side="left")
        ttk.Checkbutton(bar, text="Outline parts", variable=st["outline"],
                        command=lambda: outlines()).pack(side="left", padx=8)
        part_lbl = ttk.Label(bar, foreground="#555"); part_lbl.pack(side="left", padx=4)

        nb = ttk.Notebook(doc.content); nb.pack(fill="both", expand=True)
        atlas_tab = ttk.Frame(nb); nb.add(atlas_tab, text="Atlas")
        info = tk.Text(atlas_tab, height=9, wrap="word", font=("Consolas", 9))
        info.insert("end", _psb.summary(ps, pathlib.PurePosixPath(name).name)); info.config(state="disabled")
        info.pack(fill="x")
        doc._pil = img
        cv = doc._img_canvas = self._make_image_canvas(parent=atlas_tab, doc=doc)

        def outlines():
            cv.delete("part")
            if not st["outline"].get():
                return
            z = getattr(doc, "zoom", 1) or 1
            for nm, ic in icons.items():
                x0, y0, x1, y1 = rect(ic)
                sel = nm == st["sel"]
                cv.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z, outline="#ffb347" if sel else "#5fb3ff",
                                    width=2 if sel else 1, tags=("part",))

        def zoom(z):
            self._set_zoom(z, doc)
            outlines()

        def select_part(nm, show=False):
            ic = icons.get(nm)
            if ic is None:
                return
            st["sel"] = nm
            x0, y0, x1, y1 = rect(ic)
            part_lbl.config(text=f"part {nm}: {ic.get('width')}×{ic.get('height')} at ({ic.get('left')}, "
                                 f"{ic.get('top')}), origin ({ic.get('originX')}, {ic.get('originY')}), "
                                 f"z-order {zorder(ic)}")
            if pt.exists(nm):
                pt.selection_set(nm); pt.see(nm)
            outlines()
            if show:                                        # scroll the part into view
                z = getattr(doc, "zoom", 1) or 1
                w, h = img.width * z, img.height * z
                cv.xview_moveto(max(0.0, (x0 * z - 40) / max(w, 1)))
                cv.yview_moveto(max(0.0, (y0 * z - 40) / max(h, 1)))

        def pick(e):
            z = getattr(doc, "zoom", 1) or 1
            x, y = cv.canvasx(e.x) / z, cv.canvasy(e.y) / z
            hits = [((r[2] - r[0]) * (r[3] - r[1]), nm) for nm, ic in icons.items()
                    for r in [rect(ic)] if r[0] <= x < r[2] and r[1] <= y < r[3]]
            if hits:
                select_part(min(hits)[1])                   # the smallest part under the pointer
        cv.bind("<Button-1>", pick)

        # ---- parts ------------------------------------------------------------------------
        parts_tab = ttk.Frame(nb); nb.add(parts_tab, text=f"Parts ({len(icons)})")
        pt = ttk.Treeview(parts_tab, columns=("n", "x", "y", "w", "h", "ox", "oy", "z"), show="headings")
        for c, t_, w in (("n", "Part", 80), ("x", "Left", 70), ("y", "Top", 70), ("w", "Width", 70),
                         ("h", "Height", 70), ("ox", "Origin X", 70), ("oy", "Origin Y", 70),
                         ("z", "Z-order", 70)):
            pt.heading(c, text=t_); pt.column(c, width=w, anchor="w")
        _table_scrollbars(parts_tab, pt)
        for nm, ic in icons.items():
            pt.insert("", "end", iid=nm, values=(nm, ic.get("left"), ic.get("top"), ic.get("width"),
                                                 ic.get("height"), ic.get("originX"), ic.get("originY"),
                                                 zorder(ic)))
        ttk.Label(parts_tab, foreground="#555", padding=(4, 2), text=(
            "A part's rectangle on the atlas, the point it is placed by (origin) and its drawing order. "
            "Double-click a part to show it on the atlas.")).grid(row=2, column=0, sticky="w")
        pt.bind("<Double-Button-1>", lambda _e: (nb.select(atlas_tab), select_part(pt.selection()[0], True))
                if pt.selection() else None)

        # ---- tree -------------------------------------------------------------------------
        tree_tab = ttk.Frame(nb); nb.add(tree_tab, text="Tree")
        tbar = ttk.Frame(tree_tab); tbar.pack(fill="x", pady=2)
        ttk.Label(tbar, foreground="#555", text="The whole PSB tree; expand a node to see its contents. "
                                                "Japanese text is shown repaired (the file keeps its bytes)."
                  ).pack(side="left")
        ttk.Button(tbar, text="Export as JSON…", command=lambda: export_json()).pack(side="right")
        tf = ttk.Frame(tree_tab); tf.pack(fill="both", expand=True)
        tt = ttk.Treeview(tf, columns=("v",), show="tree headings")
        tt.heading("#0", text="Key"); tt.heading("v", text="Value")
        tt.column("#0", width=320, stretch=False); tt.column("v", width=560, stretch=False)
        _table_scrollbars(tf, tt)
        pending = {}

        def brief(v):
            if isinstance(v, dict):
                return f"{{{len(v)} keys}}"
            if isinstance(v, list):
                return f"[{len(v)} items]"
            if isinstance(v, _psb.Res):
                return f"<{'extra ' if v.extra else ''}resource {v.index}, {ps.chunk_span(v)[1]:,} bytes>"
            if isinstance(v, str):
                return repr(_psb.repair_text(v))
            return str(v)

        def add(parent, key, v):
            iid = tt.insert(parent, "end", text=_psb.repair_text(str(key)), values=(brief(v),))
            if isinstance(v, (dict, list)) and v:
                pending[iid] = v
                tt.insert(iid, "end", text="…")             # placeholder until opened
            return iid

        def on_open(_e=None):
            iid = tt.focus()
            v = pending.pop(iid, None)
            if v is None:
                return
            tt.delete(*tt.get_children(iid))
            items = list(v.items()) if isinstance(v, dict) else [(f"[{i}]", x) for i, x in enumerate(v)]
            for k, (kk, vv) in enumerate(items):
                if k >= 2000:
                    tt.insert(iid, "end", text="…", values=(f"{len(items) - 2000} more",)); break
                add(iid, kk, vv)
        tt.bind("<<TreeviewOpen>>", on_open)
        for k, v in (ps.root.items() if isinstance(ps.root, dict) else []):
            add("", k, v)

        def export_json():
            f = filedialog.asksaveasfilename(defaultextension=".json",
                                             initialfile=pathlib.PurePosixPath(name).stem + ".json",
                                             filetypes=[("JSON", "*.json")])
            if f:
                _psb.dump_json(ps, f)
                self.status.config(text=f"Exported the PSB tree → {f}")

        zoom(0.5)
        doc._export_kind = "png"
        self.export_btn.config(state="normal")
        doc._psb_view = dict(psb=ps, icons=icons, parts=pt, tree=tt, select=select_part, pick=pick,
                             canvas=cv, state=st, open=on_open, notebook=nb)          # (selftest)
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
        _Tip(gb, "Write a .glb for Blender: the model with its skeleton and textures, plus the motion "
                 "picked below. Bring an edited motion back with Import motion…. " + BLENDER_HINT)
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
            state["photo"] = _tk_photo(im, cv)
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
            self.status.config(text=f"Installed {len(written)} motion(s)"
                                    + (" (originals kept in the backup folder)" if gamepaths.keep_originals() else "")
                                    + " -- restart the game to see them")
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
            messagebox.showerror(
                "Import motion",
                f"{pathlib.Path(f).name} has no animation in it (a model in the same file is fine; "
                f"the export just wrote no animation track). In Blender's glTF export, tick "
                f"Animation and keep the action on the armature (or push it to an NLA track), or "
                f"use File > Export > RF4S motions (.glb) from the toolkit's Blender add-on.")
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
                f"{file_name}? (Yes = install over the game's copy; No = save "
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
                   "motion's file name or saved elsewhere.")

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
                   "or save to a folder.")
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
        BNTX and the .model rebuilt around it. Updates cur_data; Save writes it."""
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
                                f"(Save (Ctrl+S) puts it in the game)")

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
        full editor; Save (Ctrl+S) writes the file."""
        doc = self._doc
        from map_editor import tabs as me_tabs
        g = gen.GenTable(data)
        doc._gen = g
        maps = self._maps_for_gen(name)
        host = _GenHost(self, name, g, doc)
        doc._gen_host = host
        doc._before_save = host.before_save
        doc._undo, doc._can_undo = host.undo, lambda: bool(host.history)
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
        txt.insert("end", "\n\n" + "-" * 60 + "\nEvent legend (V = confirmed, D = inferred from the data):\n")
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
                                    ") — Save (Ctrl+S) to write")
            self._show(doc.cur_name, blob, doc)
        ttk.Button(eb, text="Assemble & apply", command=apply_listing).pack(side="right", padx=6)
        shown = edit.get("1.0", "end")

        def before_save():
            """Save (toolbar / Ctrl+S): an edited listing is assembled first."""
            if edit.get("1.0", "end") == shown:
                return True
            try:
                doc.cur_data = asatk.assemble(edit.get("1.0", "end"))
            except asatk.AsatkError as ex:
                messagebox.showerror("Assemble failed", str(ex))
                return False
            return True
        doc._before_save = before_save
        doc._export_kind = "disasm"; doc._export_text = asatk.render(data)
        self.export_btn.config(state="normal")

    def _view_skillcurve(self, name, data):
        """rf3ParamSkillExp*.bin -- a skill XP curve: how much XP each level needs. A table (one row
        per level; double-click an XP cell to type a new value), a bar chart of the curve (click a
        bar to select that level, or tick Paint and drag to draw the curve), Set / Scale for the
        selected rows or every level, Undo, Revert, and Save as... The header names the skills that use this curve (game names)."""
        doc = self._doc
        from rf4s_modkit import gamenames
        buf = bytearray(data)
        stem = pathlib.Path(name).stem.lower()
        arc = next((a for a, f in skillcurve.ARCHIVE_FILE.items() if f.lower() == stem), None)
        if arc == skillcurve.DEFAULT_ARCHIVE:
            sids = [s for s in range(38) if skillcurve.archive_for_skill(s) == arc]
        else:
            sids = sorted(s for s, x in skillcurve.FAMILY_ARCHIVE.items() if x == arc)
        skill_names = [gamenames.name("skills", s) or f"skill {s}" for s in sids]
        cap99 = set(range(17, 21)) | set(range(26, 33))
        stops_at_99 = bool(sids) and all(s in cap99 for s in sids)
        some_99 = any(s in cap99 for s in sids)

        head = ttk.Frame(doc.content, padding=(6, 4)); head.pack(fill="x")
        ttk.Label(head, text="Skill XP curve", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        used = ", ".join(skill_names) if skill_names else "(no skill found)"
        ttk.Label(head, wraplength=600, justify="left", text=f"Used by: {used}").pack(anchor="w", fill="x")
        if stops_at_99:
            cap_note = "These skills stop at level 99, so the last row is never used."
        elif some_99:
            cap_note = ("The resist skills and crafting skills stop at level 99; the others keep going to "
                        "999, and every level past 99 costs the last row's XP.")
        else:
            cap_note = "These skills go up to level 999: every level past 99 costs the last row's XP."
        ttk.Label(head, wraplength=600, justify="left", foreground="#666", text=(
            "Each row is the XP a skill needs at that level to reach the next one. " + cap_note +
            " Click an XP value and type to change it (with several levels selected, all of them "
            "change), or use Scale.")).pack(anchor="w", fill="x")
        head.bind("<Configure>", lambda e: [w.config(wraplength=max(200, e.width - 16))
                                             for w in head.winfo_children() if isinstance(w, ttk.Label)
                                             and w.cget("wraplength")], add="+")

        # the controls sit at the bottom and are laid out before the table and chart, so a small
        # window shrinks the table / chart and never cuts the buttons off
        foot = ttk.Frame(doc.content, padding=(6, 2, 6, 4)); foot.pack(side="bottom", fill="x")
        body = ttk.Frame(doc.content); body.pack(fill="both", expand=True, padx=6)
        left = ttk.Frame(body); left.pack(side="left", fill="y")
        cols = ("lvl", "xp", "total")
        tv = ttk.Treeview(left, columns=cols, show="headings", height=22, selectmode="extended")
        for c, t_, w in (("lvl", "At level", 150), ("xp", "XP to next level", 120), ("total", "Total XP so far", 120)):
            tv.heading(c, text=t_); tv.column(c, width=w, anchor="e" if c != "lvl" else "w")
        _table_scrollbars(left, tv)
        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        cbar = ttk.Frame(right); cbar.pack(fill="x", pady=(0, 4))
        paintv = tk.BooleanVar(value=False)
        pcb = ttk.Checkbutton(cbar, text="Paint the curve with the mouse", variable=paintv)
        pcb.pack(side="left")
        chart = tk.Canvas(right, height=300, highlightthickness=0,
                          background=ttk.Style(body).lookup("Treeview", "fieldbackground") or "#ffffff")
        chart.pack(fill="both", expand=True)

        bar = ttk.Frame(foot); bar.pack(fill="x")
        bar2 = ttk.Frame(foot); bar2.pack(fill="x", pady=(4, 0))
        pctv = tk.StringVar(value="100")
        ttk.Label(bar, text="Selected levels: scale to").pack(side="left")
        pe = ttk.Entry(bar, textvariable=pctv, width=6); pe.pack(side="left", padx=2)
        ttk.Label(bar, text="%").pack(side="left")
        scb = ttk.Button(bar, text="Scale"); scb.pack(side="left", padx=4)
        allb = ttk.Button(bar2, text="Scale all levels"); allb.pack(side="left")
        from guiutil import Tip
        Tip(pe, "100 = unchanged, 50 = those levels need half the XP (levelling twice as fast), "
                "200 = twice the XP.")
        Tip(pcb, "On: drag across the chart to draw the bars (each level gets the height under the "
                 "mouse). The scale leaves 25% headroom so you can paint above the current top; paint "
                 "again to go higher. Off: clicking a bar selects that level.")
        info = ttk.Label(foot, foreground="#666"); info.pack(fill="x", pady=(4, 0))

        def label(lvl):
            if lvl == skillcurve.REAL_LEVELS - 1 and not stops_at_99:
                return "99 (and every level after)"
            return f"{lvl}  →  {lvl + 1}"

        def refresh(keep=None):
            xp = skillcurve.parse(bytes(buf))
            sel = keep if keep is not None else [int(i) for i in tv.selection()]
            tv.delete(*tv.get_children())
            total = 0
            for lvl, step in enumerate(xp):
                total += step
                tv.insert("", "end", iid=str(lvl), values=(label(lvl), f"{step:,}", f"{total:,}"))
            for i in sel:
                if tv.exists(str(i)):
                    tv.selection_add(str(i))
            info.config(text=f"Total XP from level 0 to 100: {sum(xp):,}   ·   largest step: {max(xp):,} "
                             f"(level {xp.index(max(xp))})")
            draw()

        def draw(*_):
            xp = skillcurve.parse(bytes(buf))
            chart.delete("all")
            w, h = max(chart.winfo_width(), 200), max(chart.winfo_height(), 120)
            pad_l, pad_b, pad_t = PAD_L, PAD_B, PAD_T
            top = chart_top(xp)
            bw = (w - pad_l - 6) / len(xp)
            sel = {int(i) for i in tv.selection()}
            fg = ttk.Style(chart).lookup("TLabel", "foreground") or "#333"
            for lvl, step in enumerate(xp):
                x0 = pad_l + lvl * bw
                y0 = h - pad_b - (h - pad_b - pad_t) * step / top
                chart.create_rectangle(x0, y0, x0 + max(bw - 1, 1), h - pad_b, width=0,
                                       fill="#e0902a" if lvl in sel else "#4a86c8", tags=("bar", f"l{lvl}"))
            chart.create_text(pad_l - 6, pad_t, text=f"{top:,}", anchor="ne", fill=fg, font=("Segoe UI", 8))
            chart.create_text(pad_l - 6, h - pad_b, text="0", anchor="e", fill=fg, font=("Segoe UI", 8))
            for lvl in range(0, len(xp), 10):
                if pad_l + lvl * bw > w - 44:           # keep clear of the "level" label
                    continue
                chart.create_text(pad_l + lvl * bw, h - pad_b + 4, text=str(lvl), anchor="n", fill=fg,
                                  font=("Segoe UI", 8))
            chart.create_text(w - 6, h - 4, text="level", anchor="se", fill=fg, font=("Segoe UI", 8))
            if paintv.get():
                chart.create_text(w - 6, pad_t, text="drag to paint", anchor="ne", fill="#999",
                                  font=("Segoe UI", 8, "italic"))
        chart.bind("<Configure>", draw)

        PAD_L, PAD_B, PAD_T = 50, 22, 10
        paint = dict(top=None, last=None, before=None)     # a stroke keeps its scale fixed

        def chart_top(xp):
            if paint["top"]:
                return paint["top"]
            top = max(xp) or 1
            return int(top * 1.25) + 1 if paintv.get() else top

        def level_at(x):
            n = skillcurve.REAL_LEVELS
            w = max(chart.winfo_width(), 200)
            return int((x - PAD_L) // ((w - PAD_L - 6) / n))

        def xp_at(y):
            h = max(chart.winfo_height(), 120)
            frac = (h - PAD_B - y) / max(h - PAD_B - PAD_T, 1)
            return min(skillcurve.MAX_XP, max(1, int(round(paint["top"] * min(max(frac, 0.0), 1.0)))))

        def paint_to(x, y):
            n = skillcurve.REAL_LEVELS
            l1, v1 = level_at(x), xp_at(y)
            l0, v0 = paint["last"] or (l1, v1)
            lo, hi = sorted((l0, l1))
            for lvl in range(max(lo, 0), min(hi, n - 1) + 1):
                t_ = 0.0 if l1 == l0 else (lvl - l0) / (l1 - l0)      # fill the levels a fast drag skipped
                skillcurve.set_level_xp(buf, lvl, int(round(v0 + (v1 - v0) * t_)))
            paint["last"] = (l1, v1)
            draw()

        def chart_click(e):
            if paintv.get():
                paint["before"] = bytes(buf)
                paint["top"] = chart_top(skillcurve.parse(bytes(buf)))
                paint["last"] = None
                paint_to(e.x, e.y)
                return
            lvl = level_at(e.x)
            if 0 <= lvl < skillcurve.REAL_LEVELS:
                if e.state & 0x4:
                    tv.selection_add(str(lvl))
                else:
                    tv.selection_set(str(lvl))
                tv.see(str(lvl))

        def chart_drag(e):
            if paintv.get() and paint["top"]:
                paint_to(e.x, e.y)

        def chart_release(_e):
            if not paint["top"]:
                return
            before = paint["before"]
            paint.update(top=None, last=None, before=None)
            if before != bytes(buf):
                history.append(before)
                changed("Painted the curve")
            else:
                draw()
        chart.bind("<Button-1>", chart_click)
        chart.bind("<B1-Motion>", chart_drag)
        chart.bind("<ButtonRelease-1>", chart_release)
        paintv.trace_add("write", lambda *_: (chart.config(cursor="pencil" if paintv.get() else ""), draw()))
        tv.bind("<<TreeviewSelect>>", lambda _e: draw(), add="+")

        history = []                                       # file states before each change (Undo)

        def changed(msg):
            doc.cur_data = bytes(buf)
            refresh()
            self.status.config(text=msg + " — Save (Ctrl+S) to write the file")

        def set_levels(levels, value):
            history.append(bytes(buf))
            for lvl in levels:
                skillcurve.set_level_xp(buf, lvl, value)
            changed(f"{len(levels)} level(s) set to {value:,} XP")

        def scale_levels(levels, pct):
            xp = skillcurve.parse(bytes(buf))
            history.append(bytes(buf))
            for lvl in levels:
                skillcurve.set_level_xp(buf, lvl, min(skillcurve.MAX_XP, max(1, int(xp[lvl] * pct / 100 + 0.5))))
            changed(f"{len(levels)} level(s) scaled to {pct:g}%")

        def selected():
            sel = sorted(int(i) for i in tv.selection())
            if not sel:
                self.status.config(text="Select one or more levels first (click, Shift / Ctrl + click)")
            return sel

        def do_scale(levels=None):
            lv = levels if levels is not None else selected()
            if not lv:
                return
            try:
                pct = float(pctv.get().rstrip("%"))
                if pct <= 0:
                    raise ValueError("the percentage must be above 0")
                scale_levels(lv, pct)
            except ValueError as e:
                messagebox.showerror("Skill XP curve", err_text(e))

        def revert():
            if bytes(buf) != data:
                history.append(bytes(buf))
            buf[:] = data
            changed("Back to the file as opened")

        def undo(*_):
            if history:
                buf[:] = history.pop()
                changed("Undone")
        doc._undo, doc._can_undo = undo, lambda: bool(history)   # the toolbar Undo / Ctrl+Z

        scb.config(command=do_scale)
        allb.config(command=lambda: do_scale(list(range(skillcurve.REAL_LEVELS))))
        chart.bind("<Enter>", lambda _e: chart.focus_set() if paintv.get() else None)
        pe.bind("<Return>", lambda _e: do_scale())

        # type in the XP column (several levels selected: all of them get the value)
        cells = CellEdit(tv, {"xp": {
            "get": lambda row: str(skillcurve.parse(bytes(buf))[int(row)]),
            "put": lambda row, text: set_levels(sorted(int(i) for i in cells.targets(row)),
                                                int(text.replace(",", "").strip(), 0))}},
            title="Skill XP curve")
        doc._skill = dict(tree=tv, set=set_levels, scale=scale_levels, revert=revert, used=skill_names,
                          pct_var=pctv, do_scale=do_scale, cells=cells,
                          chart=chart, paint=paintv, undo=undo, history=history, press=chart_click,
                          drag=chart_drag, release=chart_release)
        refresh()

    def _view_gifts(self, name, data):
        """rf3PresentNpc*.bin -- a villager's gift preferences (loved / liked / disliked lists).
        Edited in the table: the tier cell moves an entry (neutral = take it off the lists,
        hated = the signature dislike), the item cell replaces the item, the FP cell sets a
        loved / liked entry's friendship points; the last row adds an item; Delete removes."""
        doc = self._doc
        items = _load_item_names()
        chars = _load_char_names()
        num = int(pathlib.Path(name).stem[13:15]) if pathlib.Path(name).stem[13:15].isdigit() else 0
        name_fn = lambda i: items.get(i, "")
        table = gifts.GiftTable.parse(data)
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        who = chars.get(num, "?")
        ttk.Label(bar, text=f"Gift preferences — {who} ({num})").pack(side="left", padx=6)
        foot = ttk.Frame(doc.content, padding=(6, 2, 6, 4)); foot.pack(side="bottom", fill="x")
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=("aff", "item", "fp"), show="headings", height=20)
        for c, w in (("aff", 170), ("item", 340), ("fp", 110)):
            tv.heading(c, text={"aff": "affinity", "item": "item / target", "fp": "FP / note"}[c])
            tv.column(c, width=w, anchor="w")
        _table_scrollbars(top, tv)
        catbytes = _find_extracted("rf3PresentCategory.bin")
        cats = gifts.load_categories(catbytes) if catbytes else None
        TIER_CHOICES = ["loved", "liked", "disliked", "hated (signature dislike)", "neutral (not listed)"]
        history = []

        def target_text(e):
            if e.kind == "item":
                return f"{e.value} {name_fn(e.value)}".strip()
            if e.kind == "xref" and cats:
                ids = gifts.category_items(e.value, cats)
                preview = ", ".join(name_fn(i) or str(i) for i in ids[:5])
                return f"[category #{e.value}: {preview}{', …' if len(ids) > 5 else ''}]"
            if e.kind == "category" and e.value in gifts.ITEM_RANGE_TABLE:
                lo, hi, lbl = gifts.ITEM_RANGE_TABLE[e.value]
                return f"[all {lbl} (ids {lo}..{hi - 1})]"
            return f"[{'category' if e.kind == 'xref' else 'item-range'} #{e.value}]"

        def entry_of(iid):
            g, tier, k = iid.split(":")
            return int(g), tier, int(k), table.tier(tier, int(g))[int(k)]

        # what the item cell can point at: an item, a gift category of rf3PresentCategory (the
        # game then pays that category entry's own friendship) or an item-id range
        ncat = len(cats) if cats else 21
        special = {target_text(gifts.Entry("xref", n, 0)): ("xref", n) for n in range(ncat)}
        special.update({target_text(gifts.Entry("category", n, 0)): ("category", n)
                        for n in sorted(gifts.ITEM_RANGE_TABLE)})

        def parse_target(text):
            t = text.strip()
            if t in special:
                return special[t]
            m = re.match(r"\[?category #(\d+)", t)
            if m:
                return "xref", int(m.group(1))
            m = re.match(r"\[?(?:item-)?range #(\d+)", t)
            if m:
                return "category", int(m.group(1))
            return "item", _parse_item(t, items)

        def target_name(kind, value):
            return items.get(value, str(value)) if kind == "item" else target_text(gifts.Entry(kind, value, 0))

        def fp_text(tier, e):
            if e.kind == "xref" and tier in gifts.DEFAULT_FP:
                fps = gifts.category_fp(e.value, cats) if cats else []
                return ("/".join(f"{v:+d}" for v in fps) or "?") + "  (the category's own)"
            return f"{gifts.entry_fp(e, tier):+d}"

        def aff_text(tier, e):
            if tier == "disliked" and e.code == gifts.SIGNATURE_DISLIKE_CODE:
                return "hated (signature dislike)"
            return tier

        def fill(select=None):
            tv.delete(*tv.get_children())
            for gi in range(len(table.groups)):
                for tier in gifts.TIERS:              # loved / liked / disliked
                    for k, e in enumerate(table.tier(tier, gi)):
                        tv.insert("", "end", iid=f"{gi}:{tier}:{k}",
                                  values=(aff_text(tier, e), target_text(e), fp_text(tier, e)))
            tv.insert("", "end", iid="new", values=("", "＋ type or pick an item or a category to add it (loved)", ""))
            if select and tv.exists(select):
                tv.selection_set(select); tv.focus(select); tv.see(select)

        def changed(msg, select=None):
            doc.cur_data = table.build()
            fill(select)
            self.status.config(text=msg + " — Save (Ctrl+S) to write")

        def find_iid(kind, value):
            hit = table.find(kind, value)
            return f"{hit[0][0]}:{hit[0][1]}:{hit[0][2]}" if hit else None

        def restore(blob):
            new = gifts.GiftTable.parse(blob)
            table.groups, table.build_date = new.groups, new.build_date

        def edit(fn):
            """Run one change; a refused one (or a list past the game's 255 limit) undoes itself."""
            before = table.build()
            try:
                msg, sel = fn()
                table.build()
            except Exception:
                restore(before)
                raise
            history.append(before)
            changed(msg, sel)

        def put_aff(iid, text):
            g, tier, k, e = entry_of(iid)
            q = text.strip().lower()
            want = next((c for c in TIER_CHOICES if q and c.startswith(q)), None)
            if want is None:
                raise ValueError(f"pick one of: {', '.join(TIER_CHOICES)}")

            def do():
                if want.startswith("neutral"):
                    table.remove(e.kind, e.value, g)
                    return f"{target_text(e)}: neutral (off the lists)", None
                if want.startswith("hated"):
                    if e.kind != "item":
                        raise ValueError("only an item can be the signature dislike")
                    table.set_signature(e.value, g)
                elif want == "disliked":
                    table.add(want, gifts.Entry(e.kind, e.value, gifts.GENERIC_DISLIKE_CODE), g)
                else:                                       # loved / liked: keep a loved / liked FP
                    code = e.code if tier in gifts.DEFAULT_FP else gifts.DEFAULT_FP[want]
                    table.add(want, gifts.Entry(e.kind, e.value, code), g)
                return f"{target_text(e)}: {want}", find_iid(e.kind, e.value)
            edit(do)

        def put_item(iid, text):
            kind, val = parse_target(text)
            gifts.encode_target(kind, val)                      # validates the id / category / range
            if kind == "xref" and not 0 <= val < ncat:
                raise ValueError(f"gift categories are 0..{ncat - 1} (rf3PresentCategory)")
            if iid == "new":
                def add():
                    table.add("loved", gifts.Entry(kind, val, gifts.DEFAULT_FP["loved"]))
                    return f"Added {target_name(kind, val)} (loved)", find_iid(kind, val)
                return edit(add)
            g, tier, k, e = entry_of(iid)

            def do():
                table.remove(kind, val, g)                      # a target sits in one list only
                lst = table.groups[g][tier]
                k2 = next((j for j, x in enumerate(lst) if x is e), None)
                code = e.code
                if tier in gifts.DEFAULT_FP and e.kind == "xref" and kind != "xref":
                    code = gifts.DEFAULT_FP[tier]               # a category entry's own code is unused
                new = gifts.Entry(kind, val, code)
                if k2 is None:
                    lst.append(new)
                else:
                    lst[k2] = new
                return f"{target_text(e)} → {target_name(kind, val)}", find_iid(kind, val)
            edit(do)

        def put_fp(iid, text):
            g, tier, k, e = entry_of(iid)
            fp = int(text.split()[0].lstrip("+"), 0)
            if not -0x8000 <= fp <= 0x7FFF:
                raise ValueError("friendship must be -32768..32767 (the game reads it as signed 16-bit)")

            def do():
                table.groups[g][tier][k] = gifts.Entry(e.kind, e.value, fp & 0xFFFF)
                return f"{target_text(e)}: {fp:+d} FP", iid
            edit(do)

        def remove(*_):
            ents = [entry_of(i) for i in tv.selection() if i != "new"]
            if not ents:
                return

            def do():
                for g, _tier, _k, e in ents:
                    table.remove(e.kind, e.value, g)
                return f"Removed {len(ents)} entr{'y' if len(ents) == 1 else 'ies'}", None
            edit(do)

        def undo(*_):
            if history:
                restore(history.pop())
                changed("Undone")
        doc._undo, doc._can_undo = undo, lambda: bool(history)   # the toolbar Undo / Ctrl+Z

        def revert():
            if table.build() != data:
                history.append(table.build()); restore(data); changed("Back to the file as opened")

        target_choices = lambda: list(special) + [_item_text(i, items) for i in sorted(items)
                                                  if 0 < i <= gifts.MAX_ITEM_ID]

        def target_get(iid):
            if iid == "new":
                return ""
            e = entry_of(iid)[3]
            return _item_text(e.value, items) if e.kind == "item" else target_text(e)
        cells = CellEdit(tv, {
            "aff": {"get": lambda iid: aff_text(entry_of(iid)[1], entry_of(iid)[3]), "put": put_aff,
                    "choices": TIER_CHOICES, "can": lambda iid: iid != "new"},
            "item": {"get": target_get, "put": put_item, "choices": target_choices},
            # a category entry pays the category's own friendship, so its FP cell is not editable
            "fp": {"get": lambda iid: str(gifts.entry_fp(entry_of(iid)[3], entry_of(iid)[1])), "put": put_fp,
                   "can": lambda iid: iid != "new" and entry_of(iid)[1] in gifts.DEFAULT_FP
                   and entry_of(iid)[3].kind != "xref"}})
        tv.bind("<Delete>", remove)

        hint = ttk.Label(foot, foreground="#555", text="Click a cell and type to change it; the item cell also "
                                                       "takes a gift category or an item range (FP: loved / liked "
                                                       "only; a category pays its own; a dislike is always −5, the "
                                                       "signature one −10); "
                                                       "Delete removes the selected rows.")
        _hint_line(hint)
        ttk.Button(foot, text="Remove selected", command=remove).pack(side="right", padx=(2, 12))
        fill()
        doc._gifts = dict(tree=tv, cells=cells, remove=remove, undo=undo, revert=revert,
                          table=lambda: table)                                 # (selftest)

    def _view_schedule(self, name, data):
        """rf3Schedule -- NPC daily routines. Pick an NPC and which kind of day (the game picks
        one routine per NPC each day: a 6-day cycle, a bad-weather variant, festival / married
        days). The table lists the stops (from - until, where); the spots of the selected stop's
        kind (rf3ScheduleID) are listed below it. Edit, add or remove a stop, copy the routine to
        another day, Revert, Save as...
        Day rule: Schedule_GetNpcStateForToday (RF4S.exe+0x229160), state = (day of month - 1) % 6,
        +6 on a rain / snow day while the NPC's map is outdoors, 12..15 festival / married."""
        doc = self._doc
        st = {"sc": schedule.Schedule.parse(data)}
        sidbytes = _find_extracted("rf3ScheduleID.bin")
        spots = schedule.load_spots(sidbytes) if sidbytes else None
        chars = _load_char_names()
        mname = map_names.map_name

        def state_label(s):
            if s < 6:
                return f"Normal day: days {', '.join(str(s + 1 + 6 * k) for k in range(5))}"
            if s < 12:
                d = s - 6
                return f"Rain / snow: days {', '.join(str(d + 1 + 6 * k) for k in range(5))}"
            return {12: "Festival day", 13: "Festival 21 day", 14: "Married (spouse)",
                    15: "Married: date day"}.get(s, f"State {s} (only set by scripts)")

        def kind_short(k):
            if not spots:
                return f"spot kind {k}"
            sp = schedule.kind_spots(k, spots)
            if not sp:
                return f"spot kind {k} (no spots)"
            rooms = []
            for s in sp:
                nm = mname(s.room) or f"room {s.room}"
                if nm not in rooms:
                    rooms.append(nm)
            where = ", ".join(rooms[:3]) + (f" +{len(rooms) - 3} more" if len(rooms) > 3 else "")
            if len(sp) == 1:
                return f"{where} @{sp[0].x},{sp[0].y}"
            return f"one of {len(sp)} spots each day: {where}"

        kind_choices = [f"{k}: {kind_short(k)}" for k in range(schedule.MAX_KIND + 1)]

        def parse_kind(text):
            s = str(text).strip().split(":", 1)[0].strip()
            return int(s, 0)

        # ---- pick the routine: NPC + kind of day --------------------------------------------
        bar = ttk.Frame(doc.content, padding=(6, 4)); bar.pack(fill="x")
        ttk.Label(bar, text="NPC:").pack(side="left")
        npc_v, day_v = tk.StringVar(), tk.StringVar()
        npc_cb = ttk.Combobox(bar, textvariable=npc_v, state="readonly", width=24)
        npc_cb.pack(side="left", padx=(2, 10))
        ttk.Label(bar, text="Day:").pack(side="left")
        day_cb = ttk.Combobox(bar, textvariable=day_v, state="readonly", width=38)
        day_cb.pack(side="left", padx=2)
        count_lbl = ttk.Label(bar, foreground="#666"); count_lbl.pack(side="right")
        hint = ttk.Label(doc.content, foreground="#666", justify="left", padding=(6, 0), text=(
            "Each day the game picks one routine per NPC: normal days repeat every 6 days (day of "
            "the month), on rain / snow days the NPC uses the rain routine while outdoors, and the "
            "festival / married routines replace them for the main villagers. A stop lasts until "
            "the next stop; a spot kind with several spots picks one of them each day."))
        hint.pack(fill="x")
        hint.bind("<Configure>", lambda e: hint.config(wraplength=max(200, e.width - 16)))

        # controls sit at the bottom so a small window never cuts them off
        foot = ttk.Frame(doc.content, padding=(6, 2, 6, 4)); foot.pack(side="bottom", fill="x")
        body = ttk.PanedWindow(doc.content, orient="vertical"); body.pack(fill="both", expand=True, padx=6)
        top = ttk.Frame(body); body.add(top, weight=3)
        tv = ttk.Treeview(top, columns=("time", "where", "kind", "rand"), show="headings", height=14)
        for c, t_, w in (("time", "Time", 120), ("where", "Where", 480), ("kind", "Spot kind", 80),
                         ("rand", "Random departure", 120)):
            tv.heading(c, text=t_); tv.column(c, width=w, anchor="w", stretch=(c == "where"))
        _table_scrollbars(top, tv)
        low = ttk.LabelFrame(body, text="Spots of the selected stop's kind (rf3ScheduleID)")
        body.add(low, weight=1)
        sp_tv = ttk.Treeview(low, columns=("rec", "room", "pos", "facing", "wander", "weight"),
                             show="headings", height=5)
        for c, t_, w in (("rec", "Record", 60), ("room", "Room", 260), ("pos", "x, y", 90),
                         ("facing", "Facing", 60), ("wander", "Wander", 60), ("weight", "Weight", 60)):
            sp_tv.heading(c, text=t_); sp_tv.column(c, width=w, anchor="w")
        _table_scrollbars(low, sp_tv); TableSort(sp_tv)

        row1 = ttk.Frame(foot); row1.pack(fill="x")
        row2 = ttk.Frame(foot); row2.pack(fill="x", pady=(4, 0))
        row3 = ttk.Frame(foot); row3.pack(fill="x", pady=(4, 0))
        _hint_line(ttk.Label(row1, foreground="#555", text="Click a cell and type to change it: the time "
                  "(HH:MM), the place (a spot kind: type its number or part of a room name) or "
                  "random departure (yes / no)."))
        adb = ttk.Button(row2, text="Add stop"); adb.pack(side="left")
        rmb = ttk.Button(row2, text="Remove stop"); rmb.pack(side="left", padx=4)
        ttk.Label(row3, text="Copy this routine to:").pack(side="left")
        copy_v = tk.StringVar()
        copy_cb = ttk.Combobox(row3, textvariable=copy_v, state="readonly", width=38,
                               values=[state_label(s) for s in range(schedule.COLS)])
        copy_cb.pack(side="left", padx=2)
        cpb = ttk.Button(row3, text="Copy"); cpb.pack(side="left", padx=2)
        Tip(adb, "Add a stop after the selected one (15 minutes later, or halfway to the next "
                 "stop), at the same place; then change its time and place in the table.")
        Tip(rmb, "Remove the selected stop (Delete key).")
        Tip(cpb, "Replace (or create) the chosen day's routine of this NPC with a copy of the one "
                 "shown.")

        def npc_list():
            return st["sc"].npcs()

        def npc_text(n):
            return f"{chars.get(n, '') or 'NPC'} ({n})"

        def cur_npc():
            try:
                return int(npc_v.get().rsplit("(", 1)[1].rstrip(")"))
            except (IndexError, ValueError):
                return None

        def cur_state():
            lbl = day_v.get()
            return next((s for s in range(schedule.COLS) if state_label(s) == lbl), None)

        def fill_npcs(keep=None):
            ns = npc_list()
            npc_cb.config(values=[npc_text(n) for n in ns])
            n = keep if keep in ns else (ns[0] if ns else None)
            if n is not None:
                npc_v.set(npc_text(n))
            sc = st["sc"]
            count_lbl.config(text=f"{len(sc.cells)} routines, {sum(len(v) for v in sc.cells.values())} stops")

        def fill_days(keep=None):
            n = cur_npc()
            states = sorted(s for (m, s) in st["sc"].cells if m == n)
            day_cb.config(values=[state_label(s) for s in states])
            s = keep if keep in states else (states[0] if states else None)
            day_v.set(state_label(s) if s is not None else "")
            fill()

        def stops():
            return (st["sc"].get(cur_npc(), cur_state()) if cur_state() is not None else None) or []

        def fill(select=None):
            tv.delete(*tv.get_children())
            sp_tv.delete(*sp_tv.get_children())
            lst = stops()
            for k, wp in enumerate(lst):
                nxt = lst[k + 1].slot if k + 1 < len(lst) else None
                span = schedule.slot_to_time(wp.slot) + (f" – {schedule.slot_to_time(nxt)}" if nxt is not None else "")
                tv.insert("", "end", iid=str(k), values=(span, kind_short(wp.spot), wp.spot,
                                                         "yes" if wp.flags & 1 else "no"))
            if select is not None and tv.exists(str(select)):
                tv.selection_set(str(select)); tv.focus(str(select)); tv.see(str(select))

        def show_spots(k):
            sp_tv.delete(*sp_tv.get_children())
            if not spots:
                sp_tv.insert("", "end", values=("", "rf3ScheduleID.bin is not extracted", "", "", "", ""))
                return
            for r in schedule.kind_records(k):
                if r < len(spots):
                    s = spots[r]
                    sp_tv.insert("", "end", values=(r, f"{mname(s.room) or 'room'} ({s.room})",
                                                    f"{s.x}, {s.y}", f"{s.facing * 360 // 256}°",
                                                    s.wander, s.weight))

        def pick(_e=None):
            sel = tv.selection()
            lst = stops()
            if sel and lst:
                show_spots(lst[int(sel[0])].spot)
        tv.bind("<<TreeviewSelect>>", pick, add="+")
        npc_cb.bind("<<ComboboxSelected>>", lambda _e: fill_days(cur_state()))
        day_cb.bind("<<ComboboxSelected>>", lambda _e: fill())

        def changed(msg, select=None):
            doc.cur_data = st["sc"].build()
            self.status.config(text=msg + " — Save (Ctrl+S) to write the file")
            fill_npcs(cur_npc()); fill_days(cur_state()); fill(select)

        def edit_stop(idx, msg, **kw):
            """Change one stop (slot= / spot= / flags=); a refused change leaves the file as it was."""
            n, s = cur_npc(), cur_state()
            sc = st["sc"]
            before = sc.build()
            try:
                new = sc.set_slice(n, s, idx, **kw)
                sc.build()                          # validates before the view changes
            except Exception:
                st["sc"] = schedule.Schedule.parse(before)
                raise
            changed(f"{npc_text(n)}, {state_label(s)}: {msg}", sc.get(n, s).index(new))

        def put_time(row, text):
            edit_stop(int(row), "time set", slot=schedule.time_to_slot(text.split("–")[0]))

        def put_spot(row, text):
            edit_stop(int(row), "place set", spot=parse_kind(text))

        def put_rand(row, text):
            q = text.strip().lower()
            if q not in ("yes", "no", "y", "n", "1", "0", "true", "false"):
                raise ValueError("random departure: yes or no")
            old = stops()[int(row)]
            on = q in ("yes", "y", "1", "true")
            edit_stop(int(row), "random departure " + ("on" if on else "off"),
                      flags=(old.flags & ~1) | (1 if on else 0))

        def add():
            n, s = cur_npc(), cur_state()
            if n is None or s is None:
                return
            lst = stops()
            sel = tv.selection()
            k = int(sel[0]) if sel else len(lst) - 1
            if lst:
                cur, nxt = lst[k], (lst[k + 1].slot if k + 1 < len(lst) else None)
                slot = cur.slot + max(1, (nxt - cur.slot) // 2) if nxt is not None else cur.slot + 1
                spot = cur.spot
            else:
                slot, spot = schedule.time_to_slot("06:00"), 0
            sc = st["sc"]
            try:
                at = sc.add_slice(n, s, slot, spot, 0)
                sc.build()
            except (ValueError, schedule.ScheduleError) as ex:
                st["sc"] = schedule.Schedule.parse(doc.cur_data)
                messagebox.showerror("Schedule", err_text(ex)); return
            changed(f"{npc_text(n)}, {state_label(s)}: stop added at {schedule.slot_to_time(slot)}", at)

        def remove(*_):
            n, s = cur_npc(), cur_state()
            sel = tv.selection()
            if n is None or s is None or not sel:
                return
            idx = int(sel[0])
            sc = st["sc"]
            sc.remove_slice(n, s, idx)
            changed(f"{npc_text(n)}, {state_label(s)}: stop removed", min(idx, len(sc.get(n, s)) - 1))

        def copy_to():
            n, s = cur_npc(), cur_state()
            dst = next((k for k in range(schedule.COLS) if state_label(k) == copy_v.get()), None)
            if n is None or s is None or dst is None or dst == s:
                self.status.config(text="Pick another day to copy this routine to")
                return
            sc = st["sc"]
            if sc.get(n, dst) is not None and not messagebox.askyesno(
                    "Copy routine", f"Replace {npc_text(n)}'s '{state_label(dst)}' routine?"):
                return
            sc.cells[(n, dst)] = list(sc.get(n, s))
            doc.cur_data = sc.build()
            fill_npcs(n); fill_days(dst)
            self.status.config(text=f"Copied to '{state_label(dst)}' — Save (Ctrl+S) to write the file")

        def revert():
            st["sc"] = schedule.Schedule.parse(data)
            doc.cur_data = data
            fill_npcs(cur_npc()); fill_days(cur_state())
            self.status.config(text="Back to the file as opened")

        spot_spec = {"get": lambda row: kind_choices[stops()[int(row)].spot]
                     if 0 <= stops()[int(row)].spot < len(kind_choices) else str(stops()[int(row)].spot),
                     "put": put_spot, "choices": kind_choices}
        cells = CellEdit(tv, {"time": {"get": lambda row: schedule.slot_to_time(stops()[int(row)].slot),
                                       "put": put_time},
                              "where": spot_spec, "kind": spot_spec,
                              "rand": {"get": lambda row: "yes" if stops()[int(row)].flags & 1 else "no",
                                       "put": put_rand, "choices": ["yes", "no"]}},
                         title="Schedule")
        adb.config(command=add); rmb.config(command=remove); cpb.config(command=copy_to)
        tv.bind("<Delete>", remove)
        fill_npcs(); fill_days()
        doc._sched = dict(npc=npc_v, day=day_v, tree=tv, spots=sp_tv, cells=cells, add=add, remove=remove,
                          copy=copy_to, copy_var=copy_v, revert=revert, fill_days=fill_days,
                          npc_text=npc_text, state_label=state_label, st=st)

    def _view_gift_categories(self, name, data):
        """rf3PresentCategory -- the 21 shared gift categories. A villager's gift list
        (rf3PresentNpcNN) can point at a category instead of single items; when the villager
        LOVES or LIKES the category, gifting one of its items grants that item's own friendship
        value stored HERE (the category entry's code, gifts.py), and a DISLIKED category is -5.
        Left: the categories with a preview and the villagers using them; right: the selected
        category's items (value editable), who uses it, add / remove / set value, Undo, Revert."""
        doc = self._doc
        items = _load_item_names()
        chars = _load_char_names()
        table = gifts.GiftTable.parse(data)
        ncat = len(table.groups)

        # which villagers point at each category, and in which tier
        users = {i: {"loved": [], "liked": [], "disliked": []} for i in range(ncat)}
        for nn in range(1, 28):
            raw = _find_extracted(f"rf3PresentNpc{nn:02d}.bin")
            if not raw:
                continue
            try:
                nt = gifts.GiftTable.parse(raw)
            except gifts.GiftError:
                continue
            who = chars.get(nn, "") or f"NPC {nn}"
            for tier in gifts.TIERS:
                for e in nt.tier(tier):
                    if e.kind == "xref" and e.value in users and who not in users[e.value][tier]:
                        users[e.value][tier].append(who)

        def members(g):
            return table.groups[g].get("disliked") or []           # a category keeps its items in off1

        def fp_of(e):
            return e.code - 0x10000 if e.code >= 0x8000 else e.code

        def default_fp(g):
            codes = [fp_of(e) for e in members(g) if e.kind == "item"]
            return max(set(codes), key=codes.count) if codes else 9

        # ---- layout -----------------------------------------------------------------------
        head = ttk.Frame(doc.content, padding=(6, 4)); head.pack(fill="x")
        ttk.Label(head, text="Gift categories", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        expl = ttk.Label(head, foreground="#555", justify="left", text=(
            "A category is a shared list of items that villagers' gift lists can point to. When a villager "
            "loves or likes a category, giving one of its items grants the friendship points set for that "
            "item here (the villager's own list does not decide it); when they dislike it, the gift is "
            "−5. Each category can hold up to 255 items; only direct items count (the game does not "
            "follow a category inside a category)."))
        expl.pack(fill="x")
        expl.bind("<Configure>", lambda e: expl.config(wraplength=max(200, e.width - 16)))

        foot = ttk.Frame(doc.content, padding=(6, 2, 6, 4)); foot.pack(side="bottom", fill="x")
        # the selected category's title + users span the full width, so both lists below start
        # and end at the same height
        sel_head = ttk.Frame(doc.content, padding=(6, 2)); sel_head.pack(fill="x")
        title = ttk.Label(sel_head, font=("Segoe UI", 10, "bold")); title.pack(anchor="w")
        used_lbl = ttk.Label(sel_head, foreground="#555", justify="left"); used_lbl.pack(fill="x")
        used_lbl.bind("<Configure>", lambda e: used_lbl.config(wraplength=max(200, e.width - 8)))
        body = ttk.PanedWindow(doc.content, orient="horizontal"); body.pack(fill="both", expand=True, padx=6)
        left = ttk.Frame(body); body.add(left, weight=2)
        right = ttk.Frame(body); body.add(right, weight=3)

        ct = ttk.Treeview(left, columns=("n", "items", "preview", "used"), show="headings",
                          selectmode="browse", height=18)
        for c, t_, w in (("n", "#", 36), ("items", "Items", 50), ("preview", "Contains", 260),
                         ("used", "Used by", 260)):
            ct.heading(c, text=t_); ct.column(c, width=w, anchor="w")
        _table_scrollbars(left, ct); TableSort(ct)

        mf = ttk.Frame(right); mf.pack(fill="both", expand=True)
        mt = ttk.Treeview(mf, columns=("item", "id", "fp"), show="headings", selectmode="extended", height=14)
        for c, t_, w in (("item", "Item", 220), ("id", "Id", 60), ("fp", "Friendship when loved / liked", 190)):
            mt.heading(c, text=t_); mt.column(c, width=w, anchor="w")
        _table_scrollbars(mf, mt)

        row2 = ttk.Frame(foot); row2.pack(fill="x")
        _hint_line(ttk.Label(row2, foreground="#555", text="Click an item or friendship cell and type to change "
                  "it (with several items selected, a friendship value goes to all of them); the last "
                  "row adds an item; Remove selected (or Delete) takes items out."))
        rm_b = ttk.Button(row2, text="Remove selected"); rm_b.pack(side="right", padx=(4, 12))
        Tip(rm_b, "Take the selected items out of the category (Delete key).")

        # ---- fill -------------------------------------------------------------------------
        def used_text(g, short=False):
            u = users[g]
            parts = [f"{tier}: {', '.join(u[tier])}" for tier in ("loved", "liked", "disliked") if u[tier]]
            if short:
                n = sum(len(v) for v in u.values())
                if not n:
                    return "(nobody)"
                if u["disliked"] and not (u["loved"] or u["liked"]):
                    return f"disliked by {len(u['disliked'])}"
                return "; ".join(parts)
            return "  ·  ".join(parts) if parts else "No villager's gift list uses this category."

        def fill_cats():
            keep = ct.selection()
            ct.delete(*ct.get_children())
            for g in range(ncat):
                ids = [e.value for e in members(g) if e.kind == "item"]
                prev = ", ".join(items.get(i, str(i)) for i in ids[:4]) + (" …" if len(ids) > 4 else "")
                ct.insert("", "end", iid=str(g), values=(g, len(members(g)), prev, used_text(g, True)))
            ct.selection_set(keep if keep else ("0",))

        def cur():
            s = ct.selection()
            return int(s[0]) if s else 0

        def fill_members(select=()):
            g = cur()
            mt.delete(*mt.get_children())
            for k, e in enumerate(members(g)):
                if e.kind == "item":
                    mt.insert("", "end", iid=str(k), values=(items.get(e.value, "?"), e.value, f"{fp_of(e):+d}"))
                else:                                       # not used by the shipped file
                    mt.insert("", "end", iid=str(k), values=(gifts._fmt(e, items.get), "", "(ignored)"))
            mt.insert("", "end", iid="new", values=("＋ type or pick an item to add it", "", ""))
            for k in select:
                if mt.exists(str(k)):
                    mt.selection_add(str(k)); mt.focus(str(k)); mt.see(str(k))
            title.config(text=f"Category {g} — {len(members(g))} items")
            used_lbl.config(text="Used by  " + used_text(g))

        ct.bind("<<TreeviewSelect>>", lambda _e: fill_members())

        # ---- edits ------------------------------------------------------------------------
        history = []

        def changed(msg, select=()):
            doc.cur_data = table.build()
            fill_cats(); fill_members(select)
            self.status.config(text=msg + " — Save (Ctrl+S) to write the file")

        def snapshot():
            history.append(table.build())

        def restore(blob):
            new = gifts.GiftTable.parse(blob)
            table.groups, table.build_date = new.groups, new.build_date

        def parse_fp(text):
            v = int(str(text).strip().lstrip("+"), 0)
            if not -0x8000 <= v <= 0x7FFF:
                raise ValueError("friendship must be -32768..32767 (the game reads it as signed 16-bit)")
            return v

        def add(g, it, fp=None):
            fp = default_fp(g) if fp is None else fp
            before = table.build()
            try:
                if any(e.kind == "item" and e.value == it for e in members(g)):
                    raise gifts.GiftError(f"{items.get(it, it)} is already in category {g}")
                gifts.encode_target("item", it)
                lst = table.groups[g].get("disliked")
                if lst is None:
                    table.groups[g]["disliked"] = lst = []
                lst.append(gifts.Entry("item", it, fp & 0xFFFF))
                table.build()                               # validates the 255-entry limit
            except (ValueError, gifts.GiftError):
                restore(before)
                raise
            history.append(before)
            changed(f"Added {items.get(it, it)} to category {g} ({fp:+d})", (len(members(g)) - 1,))

        def put_item(iid, text):
            g, it = cur(), _parse_item(text, items)
            if iid == "new":
                return add(g, it)
            k = int(iid)
            lst = members(g)
            if any(e.kind == "item" and e.value == it for j, e in enumerate(lst) if j != k):
                raise gifts.GiftError(f"{items.get(it, it)} is already in category {g}")
            gifts.encode_target("item", it)
            snapshot()
            old = lst[k]
            lst[k] = gifts.Entry("item", it, old.code)
            changed(f"Category {g}: {items.get(old.value, old.value)} → {items.get(it, it)}", (k,))

        def put_fp(iid, text):
            fp = parse_fp(text)
            g = cur()
            lst = members(g)
            sel = [int(k) for k in cells.targets(iid) if k != "new"]
            snapshot()
            for k in sel:
                lst[k] = gifts.Entry(lst[k].kind, lst[k].value, fp & 0xFFFF)
            changed(f"{len(sel)} item(s) set to {fp:+d}", sel)

        def remove(*_):
            sel = [int(k) for k in mt.selection() if k != "new"]
            g = cur()
            if not sel:
                return
            snapshot()
            lst = members(g)
            names = [items.get(lst[k].value, str(lst[k].value)) for k in sel]
            table.groups[g]["disliked"] = [e for k, e in enumerate(lst) if k not in set(sel)]
            changed(f"Removed {', '.join(names[:3])}{' …' if len(names) > 3 else ''} from category {g}")

        def undo(*_):
            if history:
                restore(history.pop())
                changed("Undone")
        doc._undo, doc._can_undo = undo, lambda: bool(history)   # the toolbar Undo / Ctrl+Z

        def revert():
            if table.build() != data:
                snapshot(); restore(data); changed("Back to the file as opened")

        item_choices = lambda: [_item_text(i, items) for i in sorted(items) if 0 < i <= gifts.MAX_ITEM_ID]
        is_item = lambda iid: iid != "new" and members(cur())[int(iid)].kind == "item"
        cells = CellEdit(mt, {
            "item": {"get": lambda iid: "" if iid == "new" else _item_text(members(cur())[int(iid)].value, items),
                     "put": put_item, "choices": item_choices,
                     "can": lambda iid: iid == "new" or is_item(iid)},
            "fp": {"get": lambda iid: str(fp_of(members(cur())[int(iid)])), "put": put_fp,
                   "choices": ["15", "9", "6"], "can": is_item}},
            title="Gift categories")
        mt.bind("<Delete>", remove)
        rm_b.config(command=remove)
        fill_cats(); fill_members()
        # the category list gets half the width once the window is laid out (room for "Used by")
        sash_done = {"d": False}

        def first_layout(e):
            if not sash_done["d"] and e.width > 400:
                sash_done["d"] = True
                later(body, lambda: body.sashpos(0, e.width // 2))
        body.bind("<Configure>", first_layout, add="+")
        doc._gift = dict(cats=ct, members=mt, cells=cells, add=add, remove=remove, undo=undo,
                         revert=revert, users=users, table=lambda: table)      # (selftest)

    def _view_montame(self, name, data):
        """rf3MonsterPresent — per-species monster taming-food preferences (archive 14849): one row
        per species (id 48+) with its four item / bonus slots, edited in the table."""
        doc = self._doc
        from rf4s_modkit import montame
        items = _load_item_names()
        chars = _load_char_names()
        buf = bytearray(data)
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Monster taming-food preferences — {montame.species_count(data)} "
                            f"species (id 48+), each with up to 4 favored items + tame bonus"
                  ).pack(side="left", padx=6, pady=2)
        ttk.Label(bar, text="Search #/name:").pack(side="left", padx=(12, 0))
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)
        only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="only species with tame items", variable=only).pack(side="left", padx=6)
        foot = ttk.Frame(doc.content, padding=(6, 2, 6, 4)); foot.pack(side="bottom", fill="x")
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
        slot_cols = [c for k in range(montame.ENTRIES) for c in (f"item{k + 1}", f"bonus{k + 1}")]
        cols = ["sp", "who"] + slot_cols
        tv = ttk.Treeview(top, columns=cols, show="headings", height=22)
        for c in cols:
            tv.heading(c, text={"sp": "species", "who": "name"}.get(c, c))
            tv.column(c, width={"sp": 60, "who": 140}.get(c, 150 if c.startswith("item") else 55), anchor="w")
        _table_scrollbars(top, tv)
        last = min(montame.FIRST_SPECIES + montame.species_count(data) - 1, montame.LAST_SPECIES)
        history = []

        def fill(*_):
            keep = tv.focus()
            tv.delete(*tv.get_children())
            q = sv.get().lower().strip()
            for sid in range(montame.FIRST_SPECIES, last + 1):
                sl = montame.slots(bytes(buf), sid)
                if only.get() and not any(i for i, _b in sl):
                    continue
                who = chars.get(sid, "")
                if q and q not in str(sid) and q not in who.lower():
                    continue
                vals = [sid, who]
                for item, bonus in sl:
                    vals += [items.get(item, str(item)) if item else "", f"+{bonus}" if item else ""]
                tv.insert("", "end", iid=str(sid), values=vals)
            if keep and tv.exists(keep):
                tv.selection_set(keep); tv.focus(keep); tv.see(keep)
        sv.trace_add("write", fill); only.trace_add("write", fill)

        def changed(msg):
            doc.cur_data = bytes(buf)
            fill()
            self.status.config(text=msg + " — Save (Ctrl+S) to write")

        def put_item(row, k, text):
            sid = int(row)
            it = 0 if not text.strip() else _parse_item(text, items)
            before = bytes(buf)
            if it == 0:
                montame.clear_pref(buf, sid, k)
            else:
                other = montame.find_slot(bytes(buf), sid, it)
                if other is not None and other != k:
                    raise ValueError(f"species {sid} already lists {items.get(it, it)} (slot {other + 1}); "
                                     f"the game only uses the first match")
                bonus = montame.slots(bytes(buf), sid)[k][1] or 15
                montame.set_pref(buf, sid, k, it, bonus)
            if bytes(buf) != before:
                history.append(before)
            changed(f"species {sid}, slot {k + 1}: " + (items.get(it, str(it)) if it else "emptied"))

        def put_bonus(row, k, text):
            sid = int(row)
            item = montame.slots(bytes(buf), sid)[k][0]
            if not item:
                raise ValueError("pick an item for this slot first")
            before = bytes(buf)
            montame.set_pref(buf, sid, k, item, int(text.strip().lstrip("+"), 0))
            if bytes(buf) != before:
                history.append(before)
            changed(f"species {sid}, slot {k + 1}: bonus {text.strip()}")

        def undo(*_):
            if history:
                buf[:] = history.pop()
                changed("Undone")
        doc._undo, doc._can_undo = undo, lambda: bool(history)   # the toolbar Undo / Ctrl+Z

        def revert():
            if bytes(buf) != data:
                history.append(bytes(buf)); buf[:] = data; changed("Back to the file as opened")

        item_choices = lambda: [_item_text(i, items) for i in sorted(items) if 0 < i <= 0x7FF]
        specs = {}
        for k in range(montame.ENTRIES):
            specs[f"item{k + 1}"] = {"get": lambda row, k=k: (_item_text(montame.slots(bytes(buf), int(row))[k][0], items)
                                                              if montame.slots(bytes(buf), int(row))[k][0] else ""),
                                     "put": lambda row, text, k=k: put_item(row, k, text), "choices": item_choices}
            specs[f"bonus{k + 1}"] = {"get": lambda row, k=k: str(montame.slots(bytes(buf), int(row))[k][1]),
                                      "put": lambda row, text, k=k: put_bonus(row, k, text),
                                      "can": lambda row, k=k: bool(montame.slots(bytes(buf), int(row))[k][0])}
        cells = CellEdit(tv, specs, title="Taming foods")

        _hint_line(ttk.Label(foot, foreground="#555", text="Click an item or bonus cell and type to change it; clear "
                  "an item cell (BackSpace, Enter) to empty the slot. The game uses the first slot that "
                  "lists the fed item."))
        fill()
        doc._montame = dict(tree=tv, cells=cells, undo=undo, revert=revert)    # (selftest)

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
        ttk.Label(bar, text=f"NPC walking routes — {len(g.nodes)} points, {len(g.edges)} links "
                            f"in {len(rooms)} rooms (positions in tiles)",
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

        for lbl, cmd in (("Export JSON…", _export), ("Import JSON…", _import),
                         ("Rebuild next-hop matrix…", _rebuild)):
            ttk.Button(ctl, text=lbl, command=cmd).pack(side="right", padx=2)

    def _view_route_result(self, name, data):
        """rf3RouteResult.bin — the derived next-hop matrix; regenerate it from rf3route.bin."""
        doc = self._doc
        from rf4s_modkit import route
        gb = _find_extracted("rf3route.bin")
        ttk.Label(doc.content, wraplength=900, justify="left",
                  text="The ways NPCs walk between route points, worked out from rf3route.bin. Don't "
                       "edit it directly: change rf3route.bin and recompute this file.").pack(fill="x", padx=6, pady=4)
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
        """SI_*.bin editor — daily ground-pickup spots.

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
        except Exception:
            bar = ttk.Frame(doc.content); bar.pack(fill="x")
            ttk.Label(bar, text="footer: anomalous (harmless, engine ignores it)",
                      foreground="#888").pack(side="right", padx=6)

        paned = ttk.PanedWindow(doc.content, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        # ------------------------- left: SPOTS ----------------------------- #
        lf = ttk.LabelFrame(paned, text="Spots")
        paned.add(lf, weight=1)
        sp_tv = ttk.Treeview(lf, columns=("x", "y", "tile", "pool"), show="headings", height=10)
        for c, w, a in (("x", 70, "e"), ("y", 70, "e"), ("tile", 90, "center"), ("pool", 80, "center")):
            sp_tv.heading(c, text=c); sp_tv.column(c, width=w, anchor=a)
        sp_tv.pack(fill="both", expand=True, padx=4, pady=2)

        spb = ttk.Frame(lf); spb.pack(fill="x", padx=4, pady=(0, 4))
        # (buttons wired below, after the helper closures exist)

        # ------------------------- right: POOLS ---------------------------- #
        rf = ttk.LabelFrame(paned, text="Pools")
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
        # The engine keeps 11 bits of item id, so only ids up to 0x7FF can be picked.
        pick_names = {i: n for i, n in item_names.items() if i <= 0x7FF}

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
            self.status.config(text="Applied — Save (Ctrl+S) to write" + note)
            if refill:
                refresh_spots(); refresh_pools(); refresh_entries()

        def refresh_spots():
            keep = sel_spot()
            sp_tv.delete(*sp_tv.get_children())
            for i, s in enumerate(f.spots):
                sp_tv.insert("", "end", iid=str(i), text=str(i),
                             values=(s.x, s.y, f"({s.tile_x},{s.tile_y})", f"#{pool_no(s.pool)}"))
            if keep is not None and keep < len(f.spots):
                sp_tv.selection_set(str(keep)); sp_tv.focus(str(keep))

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
            keep = sel_entry()
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
            if keep is not None and en_tv.exists(str(keep)):
                en_tv.selection_set(str(keep)); en_tv.focus(str(keep))

        pl_tv.bind("<<TreeviewSelect>>", lambda _e: refresh_entries())

        # ------------------------- cells (type in the tables) -------------- #
        def put_xy(row, col, text):
            v = int(text.strip(), 0)
            if not 0 <= v <= 0xFFFF:
                raise ValueError("x / y are 0..65535 sub-units (8 per tile)")
            setattr(f.spots[int(row)], col, v)
            commit()

        def put_pool(row, text):
            pk = text.strip().lstrip("#")
            if not pk.isdigit() or int(pk) >= len(pools):
                raise ValueError(f"pick a pool: #0..#{len(pools) - 1}")
            f.spots[int(row)].pool = pools[int(pk)]
            commit()

        def put_item(row, text):
            a = _parse_item(text, pick_names)
            if not 0 <= a <= 0x7FF:
                raise ValueError("item id must be 0..2047 (engine uses 11 bits)")
            pools[sel_pool()].entries[int(row)].item_id = a
            commit()

        def put_weight(row, text):
            b = int(text.strip(), 0)
            if not 0 <= b <= 255:
                raise ValueError("weight must be 0..255 (engine reads one byte)")
            k = sel_pool()
            pools[k].entries[int(row)].weight = b
            if pools[k].total_weight() > 255:
                messagebox.showwarning(
                    "Weight overflow",
                    f"Pool #{k} total is now {pools[k].total_weight()} — the engine sums "
                    f"weights in a u8, so it wraps to {pools[k].engine_total_weight()} and "
                    f"skews the odds (worst case: only the first entry can drop). "
                    f"Keep the pool total ≤ 255.")
            commit()

        sp_cells = CellEdit(sp_tv, {
            "x": {"get": lambda row: str(f.spots[int(row)].x), "put": lambda row, t_: put_xy(row, "x", t_)},
            "y": {"get": lambda row: str(f.spots[int(row)].y), "put": lambda row, t_: put_xy(row, "y", t_)},
            "pool": {"get": lambda row: f"#{pool_no(f.spots[int(row)].pool)}", "put": put_pool,
                     "choices": lambda: [f"#{k}" for k in range(len(pools))]}}, title="Search items")
        item_spec = {"get": lambda row: _item_text(pools[sel_pool()].entries[int(row)].effective_item_id, item_names),
                     "put": put_item,
                     "choices": lambda: [_item_text(i, pick_names) for i in sorted(set(pick_names) | {0})]}
        en_cells = CellEdit(en_tv, {
            "id": item_spec, "name": item_spec,
            "weight": {"get": lambda row: str(pools[sel_pool()].entries[int(row)].effective_weight),
                       "put": put_weight}}, title="Search items")
        doc._si_cells = (sp_cells, en_cells)                                   # (selftest)

        # ------------------------- spot actions ---------------------------- #
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

        ttk.Button(enb, text="+ entry", command=entry_add).pack(side="left", padx=2)
        ttk.Button(enb, text="− entry", command=entry_del).pack(side="left", padx=2)
        ttk.Separator(enb, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(enb, text="+ pool", command=pool_add).pack(side="left", padx=2)
        ttk.Button(enb, text="− pool", command=pool_del).pack(side="left", padx=2)

        def before_save():
            """Save (toolbar / Ctrl+S): unassigned pools are not part of the file -- ask first."""
            doc.cur_data = f.build()
            orphans = [k for k, p in enumerate(pools) if not used_by(p)]
            return not orphans or messagebox.askokcancel(
                "Unassigned pools",
                f"Pool(s) {', '.join('#%d' % k for k in orphans)} are not assigned "
                f"to any spot and will NOT be in the saved file. Save anyway?")
        doc._before_save = before_save


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
        ttk.Label(bar, text=f"Requests — {t.entry_count}. Each is a villager and a request type; the "
                            "game picks the item or monster, the count and the reward when it posts "
                            "one.").pack(side="left", padx=6)
        ttk.Label(bar, text="  Search #/client:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=14).pack(side="left", padx=2)

        cols = ("#", "client_id", "client", "category", "type")
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=cols, show="headings", height=18)
        heads = {"client_id": "Client id", "client": "Client", "category": "Kind", "type": "Request kind"}
        for c, w in (("#", 45), ("client_id", 65), ("client", 140), ("category", 60), ("type", 340)):
            tv.heading(c, text=heads.get(c, c)); tv.column(c, width=w, anchor="w")
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

        history = []

        def changed(i, msg):
            doc.cur_data = t.build()
            fill()
            if tv.exists(str(i)):
                tv.selection_set(str(i)); tv.focus(str(i)); tv.see(str(i))
            self.status.config(text=msg + " — Save (Ctrl+S) to write")

        def put(row, off, text, names, what):
            i = int(row)
            v = _parse_item(text, names)
            before = t.build()
            t.set(i, off, v, "u8")
            if t.build() != before:
                history.append(before)
            changed(i, f"Request {i}: {what} set")

        client_names = {c: cname(c) for c in range(256) if cname(c)}
        cat_names_all = {c: cat_label(c) for c in range(34) if cat_label(c)}
        cells = CellEdit(tv, {
            "client_id": {"get": lambda row: _item_text(t.get(int(row), 0, "u8"), client_names),
                          "put": lambda row, text: put(row, 0, text, client_names, "client"),
                          "choices": lambda: [_item_text(c, client_names) for c in sorted(client_names)]},
            "category": {"get": lambda row: _item_text(t.get(int(row), 1, "u8"), cat_names_all),
                         "put": lambda row, text: put(row, 1, text, cat_names_all, "type"),
                         "choices": lambda: [_item_text(c, cat_names_all) for c in sorted(cat_names_all)]}},
            title="Requests")
        cells.cols["client"] = cells.cols["client_id"]
        cells.cols["type"] = cells.cols["category"]

        def undo(*_):
            if history:
                t.__dict__.update(nlcl.NlclTable(history.pop()).__dict__)
                keep = tv.focus()
                changed(int(keep) if keep else 0, "Undone")
        doc._undo, doc._can_undo = undo, lambda: bool(history)   # the toolbar Undo / Ctrl+Z

        def revert():
            if t.build() != data:
                history.append(t.build())
                t.__dict__.update(nlcl.NlclTable(data).__dict__)
                keep = tv.focus()
                changed(int(keep) if keep else 0, "Back to the file as opened")

        row = ttk.Frame(doc.content); row.pack(side="bottom", fill="x", padx=6, pady=4, before=top)
        _hint_line(ttk.Label(row, foreground="#555", text="Click the client or the type and type to change it "
                  "(a name, part of one, or the number)."))
        doc._quest = dict(tree=tv, cells=cells, undo=undo, revert=revert)      # (selftest)

    def _view_param(self, name, data):
        """Generic NLCL table view, used by every table without a bespoke editor.

        * ids show names: item / character / room / skill fields and named values (seasons,
          shop line roles ...) from nlcl.REF_FIELDS / VALUE_NAMES, edited with a searchable
          picker; a row-name column after the id when the row index means something
          (nlcl.ROW_NAMES: skills, maps, fish, levels, items);
        * help: hovering a column heading shows that field's note and "About this table..."
          shows the table's notes (both read from the schema comments, nlcl.schema_notes);
        * editing: the form under the table, or double-click a cell to edit it in place; Undo /
          Revert; fixed-point fields as percentages; bit sets with a Flags... tick-box dialog;
          raw offset edits; add / remove rows; unused columns hidden unless asked for."""
        doc = self._doc
        from rf4s_modkit import gamenames
        t = nlcl.NlclTable(data)
        doc._param = t
        stem = pathlib.Path(name).stem
        sch = t.schema(stem)
        fields = sch["fields"] if sch else [(f"dw{k}", k * 4, "s32")
                                            for k in range(min(8, t.record_size // 4))]
        about, notes = nlcl.schema_notes(stem) if sch else ("", {})

        # ---- names ------------------------------------------------------------------------
        name_tables = {}

        def names_of(kind):
            if kind not in name_tables:
                if kind == "item":
                    name_tables[kind] = _load_item_names()
                elif kind in ("char", "skill"):
                    name_tables[kind] = dict(gamenames.table("characters" if kind == "char" else "skills"))
                elif kind == "room":
                    name_tables[kind] = {i: n for i in range(872) for n in [map_names.map_name(i)] if n}
                else:
                    name_tables[kind] = {}
            return name_tables[kind]
        ref = {n: nlcl.ref_kind(stem, n) for n, _o, _t in fields}
        vnames = {n: nlcl.value_names(stem, n) for n, _o, _t in fields}
        pick_f = {n for n, _o, _t in fields if ref[n] or vnames[n]}
        item_f = {n for n in pick_f if ref[n] == "item"}

        def choices(n):
            d = dict(names_of(ref[n])) if ref[n] else {}
            d.update(vnames[n])
            return d

        def cell_text(n, raw_v, typ):
            if n in pick_f:
                if n in item_f and raw_v == 0:
                    return ""                                   # item 0 = an empty slot
                nm = vnames[n].get(raw_v) or (names_of(ref[n]).get(raw_v) if ref[n] else None)
                return nm or (f"#{raw_v}" if ref[n] else str(raw_v))
            bits = nlcl.flag_bits(stem, n)
            if bits is not None:
                # the named bits that are set ("Water Shoes: walk on water"), any others in hex
                named = [bits[m] for m in sorted(bits) if raw_v & m]
                rest = raw_v & ~sum(bits) & ((1 << (8 * nlcl._FMT[typ][1])) - 1)
                if not named:
                    return nlcl.format_flags(raw_v, typ) if raw_v else ""
                return ", ".join(named) + (f", +0x{rest:X}" if rest else "")
            return nlcl.format_value(raw_v, nlcl.fixed_bits(stem, n))

        def edit_text(n, raw_v, typ):
            if n in pick_f:
                return _item_text(raw_v, choices(n))
            return cell_text(n, raw_v, typ)

        def parse_field(n, typ, text):
            if n in pick_f:
                return _parse_item(text, choices(n))
            return nlcl.parse_value(text, typ, nlcl.fixed_bits(stem, n))

        # the row-name column: the row index means something, or the schema names rows by a field
        rk = nlcl.row_kind(stem) if sch else None
        name_field = sch.get("name_field") if sch else None
        name_off_typ = next(((o, ty) for n, o, ty in fields if n == name_field), None)

        def row_name(i):
            if name_off_typ and name_field not in pick_f:
                return names_of("item").get(t.get(i, *name_off_typ), "")
            if strength and i >= strengthening.ITEM_ROWS:
                return strengthening.tier_row_name(i) or "(tier row)"
            if rk in ("item", "room", "skill", "char"):
                return names_of(rk).get(i, "")
            if rk == "fish":
                fi = nlcl.fish_item(i)
                return names_of("item").get(fi, "") if fi is not None else ""
            if rk == "level":
                return f"Lv {i} → {i + 1}"
            if rk == "bracket":
                return f"size bracket {i} · Lv {i + 1}" + (" (smallest)" if i == 0 else "")
            return ""
        name_col = bool(rk) or bool(name_off_typ and name_field not in pick_f)

        # ---- extra columns of particular tables -------------------------------------------
        used = {}
        if stem == "rf3ParamMagic":                 # what fires each row
            from rf4s_modkit import magicnames
            used = magicnames.names_for_game()
        used_col = ["used by"] if stem == "rf3ParamMagic" else []
        pre_cols, pre_vals = [], None
        spots = stem == "rf3ScheduleID"
        if spots:                                   # the spot kind each spot belongs to

            pre_cols = ["spot kind"]

            def pre_vals(i):
                kr = schedule.kind_of_record(i)
                return [f"{kr[0]}  ({kr[1] + 1} of {kr[2]})" if kr else ""]
        strength = stem == "rf3ItemStrengthening"   # forge / dish bonuses: filters + a sheet
        if strength:
            from rf4s_modkit import strengthening
        monsters = stem == "rf3NpcParam"
        if monsters:                                # what the id means + the stats it ends up with
            from rf4s_modkit import monster
            pre_cols = ["kind", "ATK", "DEF", "MAT", "MDF"]

            def pre_vals(i):
                tot = monster.base_totals(t.row(i, stem))
                return [monster.id_semantics(i), tot["atk"], tot["def"], tot["mat"], tot["mdf"]]

        # ---- top bar ----------------------------------------------------------------------
        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"{stem}: {t.entry_count} records × {t.record_size} B"
                            + ("" if sch else "  (no field names — raw dwords, edit by offset)"),
                  ).pack(side="left", padx=6)
        ttk.Label(bar, text="Search:").pack(side="left")
        sv = tk.StringVar(); se = ttk.Entry(bar, textvariable=sv, width=18); se.pack(side="left", padx=2)
        Tip(se, "Matches the row number, the names and every shown value"
                + ("; 'kind 26' lists one spot kind's spots" if spots else "") + ".")
        unused = [n for n, _o, _t in fields if n.startswith("unused") or n == "pad"]
        show_unused = tk.BooleanVar(value=False)
        if unused:
            ttk.Checkbutton(bar, text=f"Show unused columns ({len(unused)})", variable=show_unused,
                            command=lambda: set_display()).pack(side="left", padx=8)
        only_nz, marker = tk.BooleanVar(value=True), tk.StringVar(value="all")
        if strength:
            ttk.Checkbutton(bar, text="nonzero rows only", variable=only_nz,
                            command=lambda: fill()).pack(side="left", padx=6)
            ttk.Label(bar, text="kind:").pack(side="left")
            mk = ttk.Combobox(bar, textvariable=marker, values=("all", "food", "not food"), width=9,
                              state="readonly")
            mk.pack(side="left", padx=2)
            mk.bind("<<ComboboxSelected>>", lambda _e: fill())
            Tip(mk, "food = can go into a dish; not food = the Not food bit of Effects is set "
                    "(spoils a dish). Tier rows count as neither.")
        if about or notes:
            ttk.Button(bar, text="About this table…", command=lambda: show_about()).pack(side="right", padx=4)
        if nlcl.unused_reason(stem):
            _hint_line(ttk.Label(doc.content, foreground="#b02020",
                                 text="Not used by the game: editing this file has no effect. "
                                      + nlcl.unused_reason(stem)))

        cols = (["#"] + (["name"] if name_col else []) + used_col + pre_cols + [f[0] for f in fields])
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=cols, show="headings", height=16)
        widths = {"name": 170, "used by": 300, "spot kind": 110, "kind": 150}
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=widths.get(c, 130 if c in pick_f else 70), anchor="w")
        # wide tables scroll sideways (Shift + wheel too); the row number and name stay put
        _table_scrollbars(top, tv, freeze=1 + bool(name_col))

        def set_display():
            hide = set() if show_unused.get() else set(unused)
            from guiutil import set_shown_columns
            set_shown_columns(tv, [c for c in cols if c not in hide])
        set_display()

        # the info line: column help while hovering a heading, else the row / table hint
        info = ttk.Label(doc.content, foreground="#555", justify="left", padding=(6, 2))
        info.pack(fill="x")
        info.bind("<Configure>", lambda e: info.config(wraplength=max(200, e.width - 16)))
        base_text = {"t": "Click a cell and type to change it (F2 or double-click edits what is there; "
                          "Enter keeps, Tab moves on, Esc cancels). Hover a column heading for what it "
                          "means."}
        if monsters:
            base_text["t"] += (" ATK / DEF / MAT / MDF = the bonus + STR / VIT/2 / INT / VIT/2, before "
                               "level growth. The selected one's sheet is under the table.")
        if strength:
            base_text["t"] += (" Rows 1108-1149 are the level / quality tiers equipment gets. The "
                               "selected row's sheet (its bonuses by use, and what the game does with "
                               "that item id) is under the table.")
        if spots:
            base_text["t"] = ("'spot kind' = the number a schedule stop uses to send an NPC here; a "
                              "kind with several spots picks one of them each day by weight. Type "
                              "'kind 26' in the search box to list one kind's spots.")
        if used_col:
            base_text["t"] = ("'used by' = the player spell, the monsters (their attack timeline) or the "
                              "timeline that fires the row; an empty cell is fired from game code (boss "
                              "scripts, thrown items, traps ...). Select a row for the full list.")
        info.config(text=base_text["t"])
        col_help = {"#": "The row number" + (f" ({rk} id)" if rk in ("item", "room", "skill") else ""),
                    "name": "What the row is (from the game's names; not stored in this file).",
                    "used by": "What fires this row (spell item, monster moves, timelines).",
                    "spot kind": "The schedule spot kind this spot belongs to (fixed in the exe)."}
        for n, _o, typ in fields:
            bits = []
            if notes.get(n):
                bits.append(notes[n])
            if n in pick_f:
                bits.append("Shown by name; the file stores the number.")
            fb = nlcl.fixed_bits(stem, n)
            if fb == nlcl.AMOUNT:
                bits.append("Shown as a number: the file stores it x 4096 (4096 = 1). Type a "
                            "number such as 0.5.")
            elif fb == nlcl.ANGLE:
                bits.append("Shown in degrees: the file stores 65536 for a full turn. Type "
                            "degrees such as 90.")
            elif fb is not None:
                one = nlcl.fixed_scale(fb)
                bits.append(f"Shown as a percentage: the file stores the fraction × {one} ({one} = "
                            f"100%). Type a percentage (150 or 150%); 0x.. sets the stored value.")
            if nlcl.flag_bits(stem, n) is not None:
                bits.append("A set of bits: double-click (or F2) for a tick box per bit.")
            col_help[n] = f"{typ} at +{_o}. " + " ".join(bits) if bits else f"{typ} at +{_o}."
        hover = {"col": None}

        def on_motion(e):
            col = None
            if tv.identify_region(e.x, e.y) == "heading":
                cid = tv.identify_column(e.x)
                try:
                    col = tv["displaycolumns"][int(cid[1:]) - 1]
                except (ValueError, IndexError):
                    col = None
                if col == "#all":
                    col = None
            if col == hover["col"]:
                return
            hover["col"] = col
            info.config(text=f"{col}: {col_help.get(col, '')}" if col else base_text["t"])
        tv.bind("<Motion>", on_motion, add="+")
        tv.bind("<Leave>", lambda _e: (hover.update(col=None), info.config(text=base_text["t"])), add="+")

        def show_about():
            win = tk.Toplevel(doc.content)
            win.title(f"About {stem}")
            win.transient(doc.content.winfo_toplevel())
            txt = tk.Text(win, wrap="word", width=96, height=30, font=("Consolas", 9))
            sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y"); txt.pack(fill="both", expand=True)
            body = (about + "\n\n" if about else "") + "Fields:\n" + "\n".join(
                f"  {n} ({ty} at +{o}): {notes.get(n, '')}" for n, o, ty in fields)
            txt.insert("1.0", "Notes on this table and its fields.\n\n"
                              + re.sub(r"\s*\(?RF4S\.exe\+0x[0-9A-Fa-f]+\)?", "", body))
            txt.config(state="disabled")
            ttk.Button(win, text="Close", command=win.destroy).pack(pady=4)
            return win
        doc._param_about = show_about                                          # (selftest)

        # ---- rows -------------------------------------------------------------------------
        def fill(*_):
            tv.delete(*tv.get_children())
            q = sv.get().lower().strip()
            kq = re.fullmatch(r"kind\s*(\d+)", q) if spots else None
            shown = 0
            for i in range(t.entry_count):
                if strength:
                    eff = t.get(i, 4 * 38, "s32")
                    if only_nz.get() and not any(t.record_dwords(i)):
                        continue
                    if marker.get() == "food" and (eff & strengthening.NON_FOOD or i >= strengthening.ITEM_ROWS):
                        continue
                    if marker.get() == "not food" and not eff & strengthening.NON_FOOD:
                        continue
                vals = [i] + ([row_name(i)] if name_col else []) + ([used.get(i, "")] if used_col else []) \
                    + (pre_vals(i) if pre_cols else []) \
                    + [cell_text(n, t.get(i, off, typ), typ) for n, off, typ in fields]
                if kq:
                    kr = schedule.kind_of_record(i)
                    if not kr or kr[0] != int(kq.group(1)):
                        continue
                elif q and not any(q in str(v).lower() for v in vals):
                    continue
                tv.insert("", "end", iid=str(i), values=vals)
                shown += 1
                if shown >= _max_rows():
                    break
        sv.trace_add("write", fill); fill()

        # ---- history (Undo / Revert) --------------------------------------------------------
        history = []

        def snapshot():
            history.append(t.build())

        def restore(blob):
            t.__dict__.update(nlcl.NlclTable(blob).__dict__)
            doc.cur_data = t.build()
            keep = sel["i"]
            fill()
            if keep is not None and tv.exists(str(keep)):
                tv.selection_set(str(keep)); tv.see(str(keep)); on_sel()

        def undo(*_):
            if history:
                restore(history.pop())
                self.status.config(text="Undone")
        doc._undo, doc._can_undo = undo, lambda: bool(history)   # the toolbar Undo / Ctrl+Z

        def revert():
            if t.build() != data:
                snapshot()
                restore(data)
                self.status.config(text="Back to the file as opened")

        # ---- cell editing (type in the table) ---------------------------------------------
        sel = {"i": None}
        foff = {n: (o, ty) for n, o, ty in fields}

        def open_flags(i, fn, typ):
            off = foff[fn][0]

            def done(new):
                before = t.build()
                t.set(i, off, new, typ)
                if t.build() != before:
                    history.append(before)
                changed(i, f"Record {i}: {fn} set")
            return _flag_dialog(doc.content, f"{stem} #{i} — {fn}", typ, t.get(i, off, typ),
                                nlcl.flag_bits(stem, fn), done)
        doc._param_open_flags = open_flags          # (selftest)

        def put_field(n, row, text):
            i = int(row)
            off, typ = foff[n]
            val = parse_field(n, typ, text)
            lim = (sch or {}).get("limits", {}).get(n)
            if lim and not lim[0] <= val <= lim[1]:
                raise ValueError(f"{n} is {lim[0]}..{lim[1]}: {lim[2]}")
            before = t.build()
            try:
                t.set(i, off, val, typ)
            except (ValueError, nlcl.NlclError):
                t.__dict__.update(nlcl.NlclTable(before).__dict__)
                raise
            if t.build() != before:
                history.append(before)
            changed(i, f"Record {i}: {n} set")

        def cell_spec(n, typ):
            if nlcl.flag_bits(stem, n) is not None:
                return {"action": lambda row, n=n, typ=typ: open_flags(int(row), n, typ)}
            spec = {"get": lambda row, n=n, typ=typ: edit_text(n, t.get(int(row), foff[n][0], typ), typ),
                    "put": lambda row, text, n=n: put_field(n, row, text)}
            if n in pick_f:
                spec["choices"] = lambda n=n: [_item_text(i, choices(n))
                                               for i in sorted(set(choices(n)) | {0})]
            return spec
        cells = CellEdit(tv, {n: cell_spec(n, typ) for n, _o, typ in fields})
        doc._param_cells = cells                                              # (selftest)

        def on_sel(_e=None):
            s = tv.selection()
            if not s:
                return
            i = int(s[0]); sel["i"] = i
            if monsters or strength:
                show_sheet(i)
            if used_col:
                from rf4s_modkit import magicnames
                full = magicnames.full_text(i)
                base_text["t"] = f"#{i} used by: " + ("  ·  ".join(full.splitlines()) if full else
                                                      "no attack timeline fires it (fired from game code, or unused)")
                if hover["col"] is None:
                    info.config(text=base_text["t"])
        tv.bind("<<TreeviewSelect>>", on_sel, add="+")
        doc._param_select = lambda i: (tv.selection_set(str(i)), tv.focus(str(i)), tv.see(str(i)), on_sel())   # (selftest)

        def changed(i, msg):
            doc.cur_data = t.build()
            fill()
            if tv.exists(str(i)):
                tv.selection_set(str(i)); tv.focus(str(i)); tv.see(str(i)); on_sel()
            self.status.config(text=msg + " — Save (Ctrl+S) to write")
        doc._param_tree = tv

        def raw_edit():
            """A value at any byte offset of the selected record (beyond the named fields)."""
            if sel["i"] is None:
                self.status.config(text="Select a record first"); return
            i = sel["i"]
            win = tk.Toplevel(doc.content)
            win.title(f"{stem} #{i} — raw edit")
            win.transient(doc.content.winfo_toplevel())
            f = ttk.Frame(win, padding=8); f.pack(fill="both")
            off_v, typ_v, val_v = tk.StringVar(), tk.StringVar(value="s32"), tk.StringVar()
            ttk.Label(f, text=f"byte offset in the record (0..{t.record_size - 1})").grid(row=0, column=0, sticky="w")
            oe = ttk.Entry(f, textvariable=off_v, width=8); oe.grid(row=0, column=1, sticky="w", padx=4)
            ttk.Label(f, text="type").grid(row=1, column=0, sticky="w")
            ttk.Combobox(f, textvariable=typ_v, width=5, state="readonly",
                         values=list(nlcl._FMT.keys())).grid(row=1, column=1, sticky="w", padx=4)
            ttk.Label(f, text="value").grid(row=2, column=0, sticky="w")
            ttk.Entry(f, textvariable=val_v, width=12).grid(row=2, column=1, sticky="w", padx=4)

            def show_cur(*_):
                try:
                    val_v.set(str(t.get(i, int(off_v.get(), 0), typ_v.get())))
                except (ValueError, nlcl.NlclError, struct.error):
                    pass
            off_v.trace_add("write", show_cur); typ_v.trace_add("write", show_cur)

            def ok(_e=None):
                before = t.build()
                try:
                    t.set(i, int(off_v.get(), 0), int(val_v.get(), 0), typ_v.get())
                except (ValueError, nlcl.NlclError, struct.error) as e:
                    t.__dict__.update(nlcl.NlclTable(before).__dict__)
                    messagebox.showerror("Edit failed", err_text(e), parent=win); return
                if t.build() != before:
                    history.append(before)
                win.destroy()
                changed(i, f"Record {i}: +{off_v.get()} set")
            bb = ttk.Frame(f); bb.grid(row=3, column=0, columnspan=2, sticky="e", pady=(8, 0))
            ttk.Button(bb, text="OK", command=ok).pack(side="right")
            ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=4)
            win.bind("<Return>", ok); win.bind("<Escape>", lambda _e: win.destroy())
            oe.focus_set()
            return win
        doc._param_raw = raw_edit                                             # (selftest)

        def shown_csv():
            """Every record as CSV, the way the table shows it: its columns (unused ones only
            while shown), percentages, names with their ids ("Cheap Cloth (831)"), bit names."""
            import csv as _csv
            import io as _io
            out = _io.StringIO()
            w = _csv.writer(out, lineterminator="\n")
            hide = set() if show_unused.get() else set(unused)
            shown = [c for c in cols if c not in hide]
            w.writerow(shown)
            for i in range(t.entry_count):
                vals = dict(zip(cols, [i] + ([row_name(i)] if name_col else [])
                                + ([used.get(i, "")] if used_col else [])
                                + (pre_vals(i) if pre_cols else [])
                                + [edit_text(n, t.get(i, off, typ), typ) for n, off, typ in fields]))
                w.writerow([vals[c] for c in shown])
            return out.getvalue()
        doc._param_csv = shown_csv                                             # (selftest)

        def export_csv():
            f = filedialog.asksaveasfilename(defaultextension=".csv",
                initialfile=pathlib.Path(doc.cur_name).stem + ".csv",
                filetypes=[("CSV", "*.csv"), ("All", "*.*")])
            if f:
                pathlib.Path(f).write_text(shown_csv(), encoding="utf-8")
                self.status.config(text=f"Exported {t.entry_count} records → {f}")

        # ---- add / remove rows (NlclTable.append_record / delete_record: entry_count,
        # byte_size and the NLCL footer are regenerated; whether the ENGINE reads the new row
        # is the schema's IDB-verified "grow" verdict, shown here and by `rf4mod param info`).
        def add_row():
            src = sel["i"]
            before = t.build()
            try:
                idx = t.append_record(t.record(src) if src is not None else None)
            except nlcl.NlclError as e:
                messagebox.showerror("Add row failed", err_text(e)); return
            history.append(before)
            changed(idx, f"Added record {idx} ({'copy of ' + str(src) if src is not None else 'zero row'}); "
                         f"{t.entry_count} records")

        def del_row():
            i = sel["i"]
            if i is None:
                return
            if not messagebox.askyesno("Delete row", f"Delete record {i}? Records {i + 1}.. shift down by one "
                                                     f"(the row index is the id in most tables)."):
                return
            before = t.build()
            try:
                t.delete_record(i)
            except nlcl.NlclError as e:
                messagebox.showerror("Delete row failed", err_text(e)); return
            history.append(before)
            sel["i"] = None
            changed(min(i, t.entry_count - 1), f"Deleted record {i}; {t.entry_count} records")

        ed = ttk.Frame(doc.content)
        ed.pack(fill="x", padx=6, pady=4)
        btn_row = ttk.Frame(ed); btn_row.pack(fill="x", pady=(2, 2))
        for text_, cmd in (("Add row (copy of selected)", add_row), ("Delete row", del_row)):
            ttk.Button(btn_row, text=text_, command=cmd).pack(side="left", padx=(0, 4))
        rb = ttk.Button(btn_row, text="Raw edit…", command=raw_edit)
        rb.pack(side="left", padx=(12, 4))
        Tip(rb, "Change the value at any byte offset of the selected record (for bytes no column "
                "shows).")
        for text_, cmd in (("Export CSV…", export_csv),):
            ttk.Button(btn_row, text=text_, command=cmd).pack(side="right", padx=4)
        doc._param_undo, doc._param_revert = undo, revert                       # (selftest)
        grow_text = t.grow_info(stem)[1]
        grow_lbl = ttk.Label(ed, text=grow_text, foreground="#555", justify="left")
        grow_lbl.pack(fill="x")
        grow_lbl.bind("<Configure>", lambda e: grow_lbl.config(wraplength=max(200, e.width - 16)))
        # the buttons and the info line are laid out before the table, so a short window
        # shrinks the table and never squeezes the buttons away
        ed.pack_configure(side="bottom", before=top)
        info.pack_configure(side="bottom", before=top)
        if monsters or strength:
            # the selected row's decoded sheet under the table: a character's (monster.render) or
            # a strengthening row's bonuses by use + the item-id behaviour (strengthening.render)
            sheet = tk.Text(doc.content, wrap="word", height=9, font=("Consolas", 9))
            sheet.pack(side="bottom", fill="x", padx=6, pady=(2, 0), before=top)
            sheet.insert("end", "Select a row to see its sheet.")
            sheet.config(state="disabled")
            item_names = _load_item_names()
            species = monster.load_species() if monsters else None

            def show_sheet(i):
                sheet.config(state="normal"); sheet.delete("1.0", "end")
                if monsters:
                    sheet.insert("end", monster.render(t, i, species, item_names))
                else:
                    st = strengthening.StrengtheningTable(t.build())
                    sheet.insert("end", st.render(i, item_names))
                sheet.config(state="disabled")
            doc._param_sheet = sheet                                          # (selftest)

    def _view_crop(self, name, data):
        """rf3CropParam — crop editor with READABLE season affinity (GUI twin of the
        `rf4mod crop` CLI). The grid decodes each crop's growing season; the editor lets
        you pick which season(s) a crop grows in via checkboxes (writes the +104
        boost/penalty bits) alongside per-field editing (stage days, health, growth gains...).
        Hovering a column heading explains the column (nlcl.schema_notes).
        Byte-surgical; edits update the in-memory table, Save (Ctrl+S) writes it out."""
        doc = self._doc
        t = nlcl.NlclTable(data)
        doc._param = t
        stem = "rf3CropParam"
        namefn = (lambda i: "")
        tbl = _load_item_names()
        namefn = lambda i: tbl.get(i, "")

        bar = ttk.Frame(doc.content); bar.pack(fill="x")
        ttk.Label(bar, text=f"Crops — {t.entry_count} (seasons and growth)").pack(side="left", padx=6)
        ttk.Label(bar, text="Search #/name:").pack(side="left")
        sv = tk.StringVar(); ttk.Entry(bar, textvariable=sv, width=16).pack(side="left", padx=2)
        only_crops = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="planted crops only", variable=only_crops).pack(side="left", padx=6)

        ITEM_COLS = ("Harvest item", "Seed item")
        show_cols = ["Stage 1 days", "Stage 2 days", "Stage 3 days", "Stage 4 days", "Regrow days",
                     "Yield", "Health", "Soil quality cost", "Growth speed", "Level gain", "Size gain",
                     "Yield gain",
                     *ITEM_COLS]
        cols = ["#"] + show_cols + ["grows", "name"]
        top = ttk.Frame(doc.content); top.pack(fill="both", expand=True)
        tv = ttk.Treeview(top, columns=cols, show="headings", height=15)
        widths = {"#": 40, "grows": 150, "name": 150}
        heads = {"grows": "Grows in", "name": "Crop"}
        for c in cols:
            tv.heading(c, text=heads.get(c, c)); tv.column(c, width=widths.get(c, 58), anchor="w")
        _table_scrollbars(top, tv)
        _about, col_notes = nlcl.schema_notes(stem)
        col_notes = {**col_notes, "#": "The row number (the crop link a seed item points at).",
                     "grows": "The seasons it grows in (double-click or F2 for the tick boxes).",
                     "name": "What you harvest (the game's item name)."}

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
                grows = "/".join(nlcl.crop_season_decode(row["Seasons"])["grows"])
                vals = [i] + [nlcl.format_value(row[c], nlcl.fixed_bits(stem, c)) for c in show_cols] + [grows, nm]
                tv.insert("", "end", iid=str(i), values=vals); shown += 1
                if shown >= _max_rows():
                    break
        sv.trace_add("write", fill); only_crops.trace_add("write", fill); fill()

        ftyp = {n: (o, ty) for n, o, ty in t.schema(stem)["fields"]}
        history = []

        def changed(i, msg):
            doc.cur_data = t.build()
            fill()
            if tv.exists(str(i)):
                tv.selection_set(str(i)); tv.focus(str(i)); tv.see(str(i))
            self.status.config(text=msg + " — Save (Ctrl+S) writes the file")

        def put(fn, row, text):
            i = int(row)
            off, ty = ftyp[fn]
            val = (_parse_item(text, tbl) if fn in ITEM_COLS
                   else nlcl.parse_value(text, ty, nlcl.fixed_bits(stem, fn)))
            before = t.build()
            t.set(i, off, val, ty)
            if t.build() != before:
                history.append(before)
            changed(i, f"Crop {i}: {fn} set")

        def seasons(row):
            """Which season(s) the crop grows in (the +104 boost / penalty bits)."""
            i = int(row)
            dec = nlcl.crop_season_decode(t.get(i, 104, "u32"))
            grows = set() if dec["grows"] == ["all-season"] else set(dec["grows"])
            win = tk.Toplevel(doc.content)
            win.title(f"Crop {i} — seasons")
            win.transient(doc.content.winfo_toplevel())
            f = ttk.Frame(win, padding=8); f.pack(fill="both")
            ttk.Label(f, text=f"{namefn(t.get(i, 96, 'u32')) or 'Crop ' + str(i)} grows in:").pack(anchor="w")
            bv = {}
            for s2 in nlcl.CROP_SEASONS:
                bv[s2] = tk.BooleanVar(value=s2 in grows)
                ttk.Checkbutton(f, text=s2, variable=bv[s2]).pack(anchor="w")
            allyear = tk.BooleanVar(value=not grows or not dec["penalized"])
            ttk.Checkbutton(f, text="all-year (no off-season penalty)", variable=allyear).pack(anchor="w", pady=(6, 0))

            def ok(_e=None):
                chosen = [s2 for s2, v in bv.items() if v.get()]
                old = t.get(i, 104, "u32")
                if chosen:
                    new = nlcl.crop_season_encode(old, chosen, single=not allyear.get())
                elif allyear.get():
                    new = old & ~nlcl._CROP_SEASON_MASK                  # grow everywhere
                else:
                    new = old
                win.destroy()
                if new != old:
                    history.append(t.build())
                    t.set(i, 104, new, "u32")
                    changed(i, f"Crop {i}: seasons set")
            bb = ttk.Frame(f); bb.pack(fill="x", pady=(8, 0))
            ttk.Button(bb, text="OK", command=ok).pack(side="right")
            ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=4)
            win.bind("<Return>", ok); win.bind("<Escape>", lambda _e: win.destroy())
            return win, bv, allyear, ok

        item_choices = lambda: [_item_text(i, tbl) for i in sorted(set(tbl) | {0})]
        specs = {}
        for fn in show_cols:
            specs[fn] = {"get": (lambda row, fn=fn: _item_text(t.get(int(row), *ftyp[fn]), tbl)) if fn in ITEM_COLS
                         else (lambda row, fn=fn: nlcl.format_value(t.get(int(row), *ftyp[fn]), nlcl.fixed_bits(stem, fn))),
                         "put": lambda row, text, fn=fn: put(fn, row, text)}
            if fn in ITEM_COLS:
                specs[fn]["choices"] = item_choices
        specs["grows"] = {"action": seasons}
        cells = CellEdit(tv, specs)

        def undo(*_):
            if history:
                blob = history.pop()
                t.__dict__.update(nlcl.NlclTable(blob).__dict__)
                keep = tv.focus()
                changed(int(keep) if keep else 0, "Undone")
        doc._undo, doc._can_undo = undo, lambda: bool(history)   # the toolbar Undo / Ctrl+Z

        def revert():
            if t.build() != data:
                history.append(t.build())
                t.__dict__.update(nlcl.NlclTable(data).__dict__)
                keep = tv.focus()
                changed(int(keep) if keep else 0, "Back to the file as opened")

        btns = ttk.Frame(doc.content); btns.pack(side="bottom", fill="x", padx=6, pady=4, before=top)
        hint_text = ("Click a cell and type to change it; the 'Grows in' cell opens the season tick "
                     "boxes (double-click or F2). Hover a column heading for what it means.")
        hint = ttk.Label(btns, foreground="#555", text=hint_text)
        _hint_line(hint)

        def on_motion(e):
            col = None
            if tv.identify_region(e.x, e.y) == "heading":
                try:
                    col = cols[int(tv.identify_column(e.x)[1:]) - 1]
                except (ValueError, IndexError):
                    col = None
            hint.config(text=f"{heads.get(col, col)}: {col_notes[col]}" if col in col_notes else hint_text)
        tv.bind("<Motion>", on_motion, add="+")
        tv.bind("<Leave>", lambda _e: hint.config(text=hint_text), add="+")
        doc._crop = dict(cells=cells, seasons=seasons, undo=undo, revert=revert, tree=tv)   # (selftest)

    def _view_hex(self, name, data, error: str | None = None):
        doc = self._doc
        what = self._external_kind(name, data)
        if what is not None and error is None:
            bar = ttk.Frame(doc.content)
            bar.pack(fill="x", padx=6, pady=(6, 2))
            b = ttk.Button(bar, text="Open in default app",
                           command=lambda: self.open_external(name, data))
            b.pack(side="left")
            Tip(b, "Opens a copy of the file in the program Windows uses for %s files (the game's "
                   "file is not touched). To replace it, edit your own copy and install that." % what)
        txt = self._make_text_tab(None, None, mono=True, doc=doc)
        if error:
            txt.insert("end", f"[viewer note] {error}\n\n")
        txt.insert("end", hexdump(data))
        txt.config(state="disabled")

    @staticmethod
    def _external_kind(name, data):
        """'sound' / 'video' / 'font' for a file Windows has a standard app for, else None."""
        try:
            ft = ident.identify(data[:0x4000], filename=name)
            if ft.fmt in EXTERNAL_FMTS:
                return EXTERNAL_FMTS[ft.fmt][0]
        except Exception:  # noqa: BLE001 -- the extension decides then
            pass
        return EXTERNAL_EXTS.get(pathlib.PurePath(name).suffix.lower())

    def open_external(self, name, data):
        """Write a copy of the file to the temp folder (with the extension its content needs)
        and open it with the default app for that type. Returns the copy's path, or None."""
        import os
        import subprocess
        import tempfile
        base = pathlib.PurePath(name).name
        try:
            fmt = ident.identify(data[:0x4000], filename=name).fmt
        except Exception:  # noqa: BLE001
            fmt = None
        want = EXTERNAL_FMTS.get(fmt, (None, None))[1]
        if want and not base.lower().endswith(want) and not (want == ".aif" and base.lower().endswith(".aiff")):
            base += want                              # e.g. a sound stored without its extension
        d = pathlib.Path(tempfile.gettempdir()) / "rf4s-modkit-open"
        try:
            d.mkdir(parents=True, exist_ok=True)
            out = d / base
            out.write_bytes(bytes(data))
            if hasattr(os, "startfile"):
                os.startfile(str(out))                # noqa: S606 -- the user's own file, their default app
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(out)])
        except OSError as e:
            self.status.config(text=f"Could not open {base}: {err_text(e)}")
            return None
        self.status.config(text=f"Opened a copy of {base} in the default app ({out})")
        return out

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
        doc.cur_image = _tk_photo(disp, doc._img_canvas)
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
            self.status.config(text="rf3.mc isn't in the file list: click Back to the game, or use "
                                    "Open rf3.mc… in the Cutscene Editor.")

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
                self.status.config(text="This map can't be exported as a picture.")
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
    import guiscale
    guiscale.install(root)                  # text size (Options), live
    guiutil.install_combo_keys(root)        # Up / Down step a dropdown's value
    guiutil.install_dialog_parents(root)   # dialogs open over the window in use
    import guitheme
    guitheme.install(root)                  # light / dark (settings.json, Options...)
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
        root.deiconify()
    App(root, initial=argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
