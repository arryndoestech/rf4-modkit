"""Secondary windows: grid resize, raw chunk editor, flag reference."""
from __future__ import annotations

import struct
import tkinter as tk
from tkinter import messagebox, ttk

from rf4s_modkit import mobj_params, rf4m

from . import ui


def _toplevel(ed, title, geometry=None):
    win = tk.Toplevel(ed.frame)
    win.title(title)
    win.transient(ed.frame.winfo_toplevel())
    if geometry:
        win.geometry(geometry)
    return win


# --------------------------------------------------------------------------- #
class ResizeDialog:
    """Resize the ATTR grid. Preview is a dry run of Rf4mMap.resize_attr_grid listing
    everything the resize invalidates (ground atlas re-layout, tiles to author, objects
    falling off the grid, seasonal siblings) before anything changes; Resize applies it
    as one undo step."""

    def __init__(self, ed):
        self.ed = ed
        W, H, _ = ed.doc.grid
        self.win = win = _toplevel(ed, f"Resize grid — {ed.doc.base}")
        frm = ttk.Frame(win, padding=8)
        frm.pack(fill="x")
        self.v = {}
        for col, (key, label, val) in enumerate((("w", "width", W), ("h", "height", H),
                                                 ("ox", "origin x", 0), ("oy", "origin y", 0),
                                                 ("fill", "new cells", "0x2"))):
            ttk.Label(frm, text=label).grid(row=0, column=col, padx=3)
            self.v[key] = tk.StringVar(value=str(val))
            e = ttk.Entry(frm, textvariable=self.v[key], width=8)
            e.grid(row=1, column=col, padx=3)
            e.bind("<Return>", lambda _e: self.preview())
        self.shift = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="move entities and warps with the terrain",
                        variable=self.shift).grid(row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))
        ui.hint(win, f"Current grid {W}x{H} tiles. Origin = where the old (0,0) lands (pads left / "
                     f"top). New cells get the fill value (0x2 = solid wall).", wrap=520).pack(fill="x", padx=8)
        self.out = tk.Text(win, height=16, width=86, font=ui.MONO, wrap="word")
        self.out.pack(fill="both", expand=True, padx=8, pady=4)
        b = ttk.Frame(win)
        b.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(b, text="Preview", command=self.preview).pack(side="left")
        ttk.Button(b, text="Resize", command=self.apply).pack(side="left", padx=4)
        ttk.Button(b, text="Close", command=win.destroy).pack(side="right")
        self.preview()

    def _args(self):
        v = self.v
        return (int(v["w"].get(), 0), int(v["h"].get(), 0),
                dict(fill=int(v["fill"].get(), 0), origin=(int(v["ox"].get(), 0), int(v["oy"].get(), 0)),
                     shift_entities=self.shift.get(), ground_reader=self.ed.tex_reader,
                     map_name=self.ed.doc.base or None))

    def _show(self, rep):
        o = self.out
        o.delete("1.0", "end")
        a = rep["atlas"]
        o.insert("end", f"ATTR {rep['old_size'][0]}x{rep['old_size'][1]} -> {rep['new_size'][0]}x"
                        f"{rep['new_size'][1]}   ground tiles {a['old_grid'][0]}x{a['old_grid'][1]} -> "
                        f"{a['new_grid'][0]}x{a['new_grid'][1]}"
                        + ("   (column count changes)" if a["reindexed"] else "") + "\n\n")
        o.insert("end", "Derived artefacts to fix:\n" if rep["todo"] else "Nothing derived needs fixing.\n")
        for t in rep["todo"]:
            o.insert("end", f"  • {t}\n")
        if rep["findings"]:
            o.insert("end", "\nValidation at the new size:\n")
            for f in rep["findings"]:
                o.insert("end", f"  {f}\n")

    def preview(self):
        try:
            w, h, kw = self._args()
            self._show(self.ed.doc.map.resize_attr_grid(w, h, dry_run=True, **kw))
        except (ValueError, rf4m.Rf4mError) as e:
            self.out.delete("1.0", "end")
            self.out.insert("end", f"error: {e}")

    def apply(self):
        try:
            w, h, kw = self._args()
        except ValueError as e:
            messagebox.showerror("Resize grid", str(e), parent=self.win)
            return
        rep = {}

        def do():
            rep.update(self.ed.doc.map.resize_attr_grid(w, h, **kw))
        if self.ed.apply(f"Resize grid to {w}x{h}", {"attr", "mobj", "mapj", "chunks"}, do):
            self.ed.select(None)
            self.ed.view.background.invalidate()
            self._show(rep)
            self.ed.status(f"Resized grid to {w}x{h} — {len(rep['todo'])} derived item(s) listed")


# --------------------------------------------------------------------------- #
class ChunkDialog:
    """Raw view of every chunk in stream order, with a hex editor. For what the other
    tabs do not cover; edits that would leave the map unreadable are refused."""

    def __init__(self, ed):
        self.ed = ed
        self.win = win = _toplevel(ed, f"Chunks — {ed.doc.base}", "620x520")
        top = ttk.Frame(win)
        top.pack(fill="both", expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(top, columns=("tag", "size", "what"), show="headings", height=10,
                                 selectmode="browse")
        for c, t, w in (("tag", "tag", 60), ("size", "bytes", 70), ("what", "meaning", 420)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="e" if c == "size" else "w", stretch=(c == "what"))
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._selected())
        self.hex = tk.Text(top, height=12, font=ui.MONO, wrap="char")
        self.hex.pack(fill="both", expand=True, pady=4)
        b = ttk.Frame(top)
        b.pack(fill="x")
        ttk.Button(b, text="Apply hex", command=self.apply).pack(side="left")
        ttk.Button(b, text="Delete chunk", command=self.delete).pack(side="left", padx=4)
        ttk.Label(b, text="new tag").pack(side="left", padx=(12, 2))
        self.tag = tk.StringVar(value="MOBJ")
        ttk.Entry(b, textvariable=self.tag, width=6).pack(side="left")
        ttk.Button(b, text="Add empty chunk", command=self.add).pack(side="left", padx=4)
        ed.doc.subscribe(self._changed)
        self.refresh()

    def _changed(self, _aspects):
        if self.win.winfo_exists():
            self.refresh()

    def refresh(self):
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.ed.doc.map.chunks):
            self.tree.insert("", "end", iid=str(i), values=(c.tag.decode("latin1"), len(c.payload),
                                                            rf4m.CHUNK_DESC.get(c.tag, "")))
        if keep and self.tree.exists(keep[0]):
            self.tree.selection_set(keep[0])
        else:
            self.hex.delete("1.0", "end")

    def _selected(self):
        s = self.tree.selection()
        self.hex.delete("1.0", "end")
        if s:
            self.hex.insert("end", self.ed.doc.map.chunks[int(s[0])].payload.hex(" ", 4))

    def apply(self):
        s = self.tree.selection()
        if not s:
            return
        i = int(s[0])
        try:
            payload = bytes.fromhex("".join(self.hex.get("1.0", "end").split()))
        except ValueError as ex:
            messagebox.showerror("Bad hex", str(ex), parent=self.win)
            return

        def do():
            self.ed.doc.map.set_chunk_payload(i, payload)
            problem = unreadable_reason(self.ed.doc.map)
            if problem:
                raise rf4m.Rf4mError(problem)
        self.ed.apply(f"Edit chunk #{i}", "chunks", do)

    def delete(self):
        s = self.tree.selection()
        if s:
            i = int(s[0])
            self.ed.apply(f"Delete chunk #{i}", "chunks", lambda: self.ed.doc.map.delete_chunk(i))

    def add(self):
        tag = self.tag.get().strip()
        if len(tag) != 4 or not tag.isascii():
            messagebox.showerror("Tag", "A chunk tag is exactly 4 ASCII characters.", parent=self.win)
            return
        self.ed.apply(f"Add {tag} chunk", "chunks", lambda: self.ed.doc.map.add_chunk(tag, b""))


def unreadable_reason(m):
    """Why a map can no longer be displayed / edited, or None. A raw chunk edit can
    truncate ATTR or leave MOBJ / MAPJ records short."""
    a = m.find(b"ATTR")
    if a:
        body = a[0].payload
        if len(body) < 8:
            return "ATTR must start with an 8-byte width/height header."
        w, h = struct.unpack_from("<II", body, 0)
        if w == 0 or h == 0 or len(body) != 8 + 4 * w * h:
            return (f"ATTR payload is {len(body)} bytes but its {w}x{h} header needs "
                    f"{8 + 4 * w * h}. Edit the cells here, and change the size with "
                    f"Map > Resize grid.")
    try:
        m.decode_mobj()
        m.mapj_records()
    except Exception as ex:  # noqa: BLE001 - report instead of breaking the editor
        return f"the map no longer decodes: {ex}"
    return None


# --------------------------------------------------------------------------- #
def flag_reference(ed):
    """Searchable emdeb GameFlag table (absolute bit ids)."""
    t = mobj_params._emflag_table()
    if not t:
        messagebox.showinfo("Flag reference", "emdeb.bin not found — the named-flag table is unavailable.")
        return None
    win = _toplevel(ed, "GameFlag reference", "580x500")
    q = tk.StringVar()
    row = ttk.Frame(win)
    row.pack(fill="x", padx=6, pady=4)
    ttk.Label(row, text="Filter").pack(side="left")
    ent = ttk.Entry(row, textvariable=q)
    ent.pack(side="left", fill="x", expand=True, padx=4)
    info = ui.hint(win, "Absolute GameFlags bit ids -- what GameFlags_ReadField and the em.bin "
                        "conditions look up (0..3016 = these named flags, 4096..6655 = per-map scene "
                        "bits). Other consumers use offsets:\n"
                        "  MOBJ f13 and script ops 443/445 = absolute - 4096\n"
                        "  script op 318 = absolute - 4096 - 1007\n"
                        "Double-click a row to copy its id.", wrap=560)
    info.pack(anchor="w", padx=8)
    lf = ttk.Frame(win)
    lf.pack(fill="both", expand=True, padx=6, pady=4)
    lb = tk.Listbox(lf, font=ui.MONO)
    sb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    rows = [(v.bit_offset, v.name, v.bit_width, v.jp_name or "") for v in t.variables]

    def refill(*_a):
        needle = q.get().strip().lower()
        lb.delete(0, "end")
        for off, name, w, jp in rows:
            if needle and needle not in name.lower() and needle not in jp.lower() and needle != str(off):
                continue
            lb.insert("end", f"{off:5}  {name}{f' [w{w}]' if w > 1 else ''}  {jp}")

    def copy(_e):
        s = lb.curselection()
        if s:
            fid = lb.get(s[0]).split()[0]
            win.clipboard_clear()
            win.clipboard_append(fid)
            info.config(text=f"copied bit id {fid}")
    q.trace_add("write", refill)
    lb.bind("<Double-Button-1>", copy)
    refill()
    ent.focus_set()
    return win
