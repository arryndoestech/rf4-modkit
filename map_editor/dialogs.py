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
    """Resize the ATTR grid (the map's size in tiles). Preview is a dry run of
    Rf4mMap.resize_attr_grid listing everything the resize invalidates (ground atlas re-layout,
    tiles to author, objects falling off the grid, seasonal siblings) before anything changes;
    Resize applies it as one undo step -- with the map's objects and warps, and (they live in
    the map's SI / Gen files) its search spots, gate positions and monster spawn points moved
    along when the content shifts."""

    # the value new tiles get: (label, ATTR value); typing any other number works too
    FILLS = (("0x2  wall (blocked)", 0x2), ("0x0  empty (nothing)", 0x0),
             ("0x1  walkable (path)", 0x1))

    def __init__(self, ed):
        self.ed = ed
        W, H, _ = ed.doc.grid
        self.win = win = _toplevel(ed, f"Resize grid — {ed.doc.base}")
        frm = ttk.Frame(win, padding=8)
        frm.pack(fill="x")
        self.v = {}
        fields = (
            ("w", "Width (tiles)", W,
             f"The new width of the map in tiles (now {W}). The collision grid (ATTR) is what the "
             f"game sizes the map by: its world size, camera limits and the ground-texture tile "
             f"grid all follow from it. A map under {rf4m.SMALL_MAP_TILES[0]} tiles wide or "
             f"{rf4m.SMALL_MAP_TILES[1]} tall gets a centred, zoomed-in camera instead of a "
             f"scrolling one."),
            ("h", "Height (tiles)", H, f"The new height of the map in tiles (now {H})."),
            ("ox", "Shift right", 0,
             "Moves the existing map this many tiles to the right inside the new grid, so "
             "new space appears on the LEFT. Negative = cut that many columns off the left. "
             "(Technically: where the old top-left tile lands.)"),
            ("oy", "Shift down", 0,
             "Moves the existing map this many tiles down inside the new grid, so new space "
             "appears at the TOP. Negative = cut that many rows off the top."),
        )
        for col, (key, label, val, tip) in enumerate(fields):
            lab = ttk.Label(frm, text=label)
            lab.grid(row=0, column=col, padx=3, sticky="w")
            self.v[key] = tk.StringVar(value=str(val))
            e = ttk.Entry(frm, textvariable=self.v[key], width=9)
            e.grid(row=1, column=col, padx=3, sticky="w")
            e.bind("<Return>", lambda _e: self.preview())
            for w in (lab, e):
                ui.Tip(w, tip)
        lab = ttk.Label(frm, text="New tiles are")
        lab.grid(row=0, column=4, padx=3, sticky="w")
        self.v["fill"] = tk.StringVar(value=self.FILLS[0][0])
        cb = ttk.Combobox(frm, textvariable=self.v["fill"], values=[f[0] for f in self.FILLS], width=20)
        cb.grid(row=1, column=4, padx=3, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda _e: self.preview())
        cb.bind("<Return>", lambda _e: self.preview())
        fill_tip = ("The collision (ATTR) value every tile the resize ADDS gets -- the new space "
                    "created by a larger width / height or a shift. 0x2 = blocked (solid wall, "
                    "the safe default: nobody walks into unpainted space), 0x0 = empty (no "
                    "collision flags at all), 0x1 = walkable path. Or type any ATTR value "
                    "(hex like 0x2001 or decimal). Paint the real collision afterwards.")
        for w in (lab, cb):
            ui.Tip(w, fill_tip)
        self.shift = tk.BooleanVar(value=True)
        sc = ttk.Checkbutton(frm, text="move objects, warps, search spots and gate positions with the map",
                             variable=self.shift)
        sc.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ui.Tip(sc, "With a shift, keep everything placed on the map on the same terrain: object "
                   "and warp-zone positions, the search spots (SI file) and the gate positions and "
                   "monster spawn points (Gen file) move by the shift. Warp ARRIVAL points are "
                   "positions in the destination map and stay; warps from other maps into this "
                   "one, and event scripts that place NPCs by tile, are not changed.")
        self.summary = ui.hint(win, "", wrap=560)
        self.summary.pack(fill="x", padx=8)
        self.out = tk.Text(win, height=16, width=90, font=ui.MONO, wrap="word")
        self.out.pack(fill="both", expand=True, padx=8, pady=4)
        b = ttk.Frame(win)
        b.pack(fill="x", padx=8, pady=(0, 8))
        pv = ttk.Button(b, text="Preview", command=self.preview)
        pv.pack(side="left")
        ui.Tip(pv, "List what the resize would change and what has to be fixed afterwards "
                   "(ground textures, objects off the map, seasonal copies ...). Changes nothing.")
        rb = ttk.Button(b, text="Resize", command=self.apply)
        rb.pack(side="left", padx=4)
        ui.Tip(rb, "Resize now (one undo step: Ctrl+Z puts everything back).")
        ttk.Button(b, text="Close", command=win.destroy).pack(side="right")
        self.preview()

    def _fill(self):
        text = self.v["fill"].get().strip()
        for label, val in self.FILLS:
            if text == label:
                return val
        return int(text.split()[0], 0)

    def _args(self):
        v = self.v
        return (int(v["w"].get(), 0), int(v["h"].get(), 0),
                dict(fill=self._fill(), origin=(int(v["ox"].get(), 0), int(v["oy"].get(), 0)),
                     shift_entities=self.shift.get(), ground_reader=self.ed.tex_reader,
                     map_name=self.ed.doc.base or None))

    def _sidecar_moves(self, w, h, ox, oy):
        """The search spots / gate positions / monster points of this map at their shifted
        places: [(kind, key, x, y, off_map)] (sub-units). Stored as u16, so a position the
        shift would push below 0 is clamped to 0 (and reported)."""
        d = self.ed.doc
        sx, sy = ox * 8, oy * 8
        out = []
        if not (sx or sy):
            return out
        if d.si is not None:
            for k, sp in enumerate(d.si.spots):
                x, y = sp.x + sx, sp.y + sy
                out.append(("search spot", k, x, y))
        if d.gen is not None:
            for pk, off, x, y, _u in d.gate_points():
                out.append(("gate position" if pk == "gpos" else "monster spawn point", off, x + sx, y + sy))
        return [(kind, key, max(0, x), max(0, y),
                 not (0 <= x >> 3 < w and 0 <= y >> 3 < h)) for kind, key, x, y in out]

    def _show(self, rep, side=()):
        o = self.out
        o.delete("1.0", "end")
        a = rep["atlas"]
        c = rep["cells"]
        (w0, h0), (w1, h1) = rep["old_size"], rep["new_size"]
        self.summary.config(
            text=f"{w0} x {h0} → {w1} x {h1} tiles: {c['kept']} kept, {c['added']} new "
                 f"(filled with 0x{c['fill']:X}), {c['dropped']} cut off"
                 + (f" ({c['dropped_nonzero']} of them had collision)" if c["dropped_nonzero"] else ""))
        o.insert("end", f"ATTR {w0}x{h0} -> {w1}x{h1}   ground tiles {a['old_grid'][0]}x{a['old_grid'][1]} -> "
                        f"{a['new_grid'][0]}x{a['new_grid'][1]}"
                        + ("   (column count changes)" if a["reindexed"] else "") + "\n")
        cam = rep.get("camera", {}).get("new")
        o.insert("end", f"camera: {cam}\n\n" if cam else
                 f"camera: scrolls over the map (at least {rf4m.SMALL_MAP_TILES[0]} x "
                 f"{rf4m.SMALL_MAP_TILES[1]} tiles)\n\n")
        o.insert("end", "Derived artefacts to fix:\n" if rep["todo"] else "Nothing derived needs fixing.\n")
        for t in rep["todo"]:
            o.insert("end", f"  • {t}\n")
        if side:
            moved = len(side)
            off = [s for s in side if s[4]]
            o.insert("end", f"  • {moved} search spot(s) / gate position(s) / monster spawn point(s) "
                            f"move with the map" + (f"; {len(off)} end up off the grid: "
                                                    + ", ".join(f"{k} {key}" for k, key, *_r in off[:6])
                                                    if off else "") + "\n")
        if rep["findings"]:
            o.insert("end", "\nValidation at the new size:\n")
            for f in rep["findings"]:
                o.insert("end", f"  {f}\n")

    def preview(self):
        try:
            w, h, kw = self._args()
            rep = self.ed.doc.map.resize_attr_grid(w, h, dry_run=True, **kw)
            side = self._sidecar_moves(w, h, *kw["origin"]) if kw["shift_entities"] else []
            self._show(rep, side)
        except (ValueError, IndexError, rf4m.Rf4mError) as e:
            self.out.delete("1.0", "end")
            self.out.insert("end", f"error: {e}")

    def apply(self):
        try:
            w, h, kw = self._args()
        except (ValueError, IndexError) as e:
            messagebox.showerror("Resize grid", str(e), parent=self.win)
            return
        d = self.ed.doc
        side = self._sidecar_moves(w, h, *kw["origin"]) if kw["shift_entities"] else []
        rep = {}

        def do():
            rep.update(d.map.resize_attr_grid(w, h, **kw))
            for kind, key, x, y, _off in side:      # the SI / Gen positions, same undo step
                if kind == "search spot":
                    sp = d.si.spots[key]
                    sp.x, sp.y = x & 0xFFFF, y & 0xFFFF
                else:
                    d.gen.set_position(key, x, y)
        aspects = {"attr", "mobj", "mapj", "chunks"}
        if any(k == "search spot" for k, *_r in side):
            aspects.add("si")
        if any(k != "search spot" for k, *_r in side):
            aspects.add("gen")
        if self.ed.apply(f"Resize grid to {w}x{h}", aspects, do):
            self.ed.select(None)
            self.ed.view.background.invalidate()
            self._show(rep, side)
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
    """Searchable emdeb table: the named story / event flags (zone 1, absolute bit ids)."""
    t = mobj_params._emflag_table()
    if not t:
        messagebox.showinfo("Flag reference", "emdeb.bin not found — the named-flag table is unavailable.")
        return None
    win = _toplevel(ed, "Story / event flags (zone 1)", "580x500")
    q = tk.StringVar()
    row = ttk.Frame(win)
    row.pack(fill="x", padx=6, pady=4)
    ttk.Label(row, text="Filter").pack(side="left")
    ent = ttk.Entry(row, textvariable=q)
    ent.pack(side="left", fill="x", expand=True, padx=4)
    info = ui.hint(win, "The named story / event flags (emdeb.bin): zone 1 of the flag array, "
                        "by game bit number -- what the em.bin conditions and GameFlags_ReadField "
                        "look up. Map objects and warps do NOT use these: their flags are zone-2 "
                        "scene bits (game bit 4096 + the number), listed in the map editor's "
                        "Flags… (Inspector). Double-click a row to copy its id.", wrap=560)
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


# --------------------------------------------------------------------------- #
def scene_flag_reference(ed, focus=None):
    """The zone-2 ("scene") flags -- the numbering of MOBJ f13, warp disable flags and script
    ops 443 / 444 / 445: every id with its known block and everything that sets, clears or
    reads it, on every map and in the event scripts. `focus` = an id to show first."""
    from rf4s_modkit import emflags, flagusers
    from . import data
    win = _toplevel(ed, "Scene flags (zone 2) -- object and warp flags", "820x600")
    top = ttk.Frame(win)
    top.pack(fill="x", padx=6, pady=4)
    ttk.Label(top, text="Find").pack(side="left")
    q = tk.StringVar()
    ent = ttk.Entry(top, textvariable=q, width=24)
    ent.pack(side="left", padx=4)
    ui.Tip(ent, "A flag number, or words from the uses (a map name, 'chest', 'bank 132' ...).")
    unused = tk.BooleanVar(value=False)
    ttk.Checkbutton(top, text="show unused ids too", variable=unused,
                    command=lambda: refill()).pack(side="left", padx=8)
    ttk.Button(top, text="Story / event flags (zone 1)…",
               command=ed.open_story_flags).pack(side="right")
    ui.hint(win, "The game keeps all flags in one bit array. A map object's flag (f13), a warp's "
                 "disable flag and script ops 443 / 444 / 445 all count in ZONE 2: the game adds "
                 "4096 before it tests the bit, so flag 158 is game bit 4254. Zone-2 bits have "
                 "no names in the game data -- what one means is who sets it and who reads it, "
                 "listed below. The named story / event flags (emdeb) are zone 1, a different "
                 "range: their numbers never match an object's flag.", wrap=800).pack(
        anchor="w", padx=8)
    pw = ttk.Panedwindow(win, orient="vertical")
    pw.pack(fill="both", expand=True, padx=6, pady=4)
    upper = ttk.Frame(pw)
    tree = ttk.Treeview(upper, columns=("bit", "known", "uses"), show="headings", selectmode="browse")
    for c, t, w in (("#0", "", 0), ("bit", "flag (game bit)", 120), ("known", "known block", 260),
                    ("uses", "used by", 400)):
        if c != "#0":
            tree.heading(c, text=t)
            tree.column(c, width=w, stretch=(c == "uses"))
    sb = ttk.Scrollbar(upper, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    pw.add(upper, weight=3)
    lower = ttk.Frame(pw)
    detail_title = ttk.Label(lower, font=ui.HINT_FONT)
    detail_title.pack(anchor="w")
    lb = tk.Listbox(lower, font=ui.MONO, height=8)
    lsb = ttk.Scrollbar(lower, orient="vertical", command=lb.yview)
    lb.config(yscrollcommand=lsb.set)
    lsb.pack(side="right", fill="y")
    lb.pack(side="left", fill="both", expand=True)
    pw.add(lower, weight=2)
    status = ui.hint(win, "Scanning every map and the event scripts ...", wrap=800)
    status.pack(anchor="w", padx=8, pady=(0, 6))
    state = {"uses": [], "rel": None}

    def live():
        d = ed.doc
        return (d.base, d.map.mobj_records(), d.map.mapj_records()) if d is not None and d.base else None

    def known(rel):
        hit = emflags.zone2_label(rel)
        if hit is None:
            return ""
        name, _detail, sub = hit
        if sub is not None:
            return f"{name.split(' (')[0]} {sub}"
        return name

    def summary(uses):
        places = []
        for u in uses:
            p = u["owner"] if u["kind"] == "script" else u["map"]
            if p not in places:
                places.append(p)
        head = f"{len(uses)}: " if uses else ""
        return head + ", ".join(places[:4]) + (f" (+{len(places) - 4})" if len(places) > 4 else "")

    def merged():
        """{id: [use]} with the open map's current records in place of its file's."""
        lv = live()
        out = {}
        for rel, uses in (data.flag_index() or {}).items():
            keep = [u for u in uses if lv is None or u.get("map") != lv[0]]
            if keep:
                out[rel] = keep
        if lv is not None:
            for rel, u in flagusers.object_uses(*lv):
                out.setdefault(rel, []).append(u)
        state["merged"] = out
        return out

    def refill(*_a):
        if data.flag_index() is None:
            return
        idx = merged()
        ids = set(idx)
        if unused.get():
            ids |= set(range(flagusers.ZONE2_BITS))
        words = q.get().strip().lower().split()
        tree.delete(*tree.get_children())
        shown = 0
        for rel in sorted(ids):
            uses = idx.get(rel, [])
            text = f"{rel} {flagusers.ZONE2_BASE + rel} {known(rel)} " + " ".join(
                flagusers.describe(u) for u in uses)
            if words and not (len(words) == 1 and words[0].isdigit() and int(words[0]) == rel) \
                    and not all(w in text.lower() for w in words):
                continue
            tree.insert("", "end", iid=str(rel),
                        values=(f"{rel}  ({flagusers.ZONE2_BASE + rel})", known(rel), summary(uses)))
            shown += 1
        status.config(text=f"{shown} flag(s) shown. Double-click a use to go to it.")
        if focus is not None and tree.exists(str(focus)) and state["rel"] is None:
            tree.selection_set(str(focus))
            tree.see(str(focus))

    def show(_e=None):
        s = tree.selection()
        if not s:
            return
        rel = int(s[0])
        state["rel"] = rel
        state["uses"] = state.get("merged", {}).get(rel, [])
        detail_title.config(text=f"Flag {rel} = game bit {flagusers.ZONE2_BASE + rel}"
                                 + (f" -- {known(rel)}" if known(rel) else "")
                                 + ("" if state["uses"] else ": nothing in the shipped game uses it"))
        lb.delete(0, "end")
        for u in state["uses"]:
            lb.insert("end", flagusers.describe(u))

    def go(_e=None):
        s = lb.curselection()
        if not s:
            return
        u = state["uses"][s[0]]
        if u["kind"] == "script":
            status.config(text=f"{u['owner']}: scene entry 0x{u['entry']:04x}, statement 0x{u['pc']:04x} "
                               f"(open it in the cutscene editor to see the script)")
            return
        d = ed.doc
        key = ("mobj" if u["kind"] == "object" else "warp", u["index"])
        if d is not None and u["map"] == d.base:
            ed.select(key, center=True)
        else:
            ed.open_map(u["map"], at=u["at"])

    tree.bind("<<TreeviewSelect>>", show)
    lb.bind("<Double-Button-1>", go)
    q.trace_add("write", refill)
    data.request_flag_index(win, lambda _idx: (refill(), show()))
    ent.focus_set()
    return win
