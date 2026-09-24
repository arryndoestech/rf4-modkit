"""The sidebar tabs besides the Inspector: Objects, Map, Encounters, View, Problems."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import colorchooser, ttk

from rf4s_modkit import gen, map_names, mapground, mobj_types, rf4m, texture

from . import attrs, data, render, ui
from .ui import commit_entry, hint, section


def key_iid(key):
    return f"{key[0]}:{key[1]}"


def iid_key(iid):
    kind, _, v = iid.partition(":")
    return (kind, int(v)) if v.lstrip("-").isdigit() else None


# --------------------------------------------------------------------------- #
class ObjectsTab(ttk.Frame):
    """Everything placed on the map, grouped, filterable; selecting a row selects it on
    the map and scrolls it into view."""

    GROUPS = (("mobj", "Entities"), ("param", "Map parameters"), ("warp", "Warps"),
              ("si", "Search spots"), ("gate", "Encounter points"), ("spawn", "Script NPCs"))

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        r = ttk.Frame(self)
        r.pack(fill="x", padx=4, pady=4)
        ttk.Label(r, text="Filter").pack(side="left")
        self.q = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.q)
        e.pack(side="left", fill="x", expand=True, padx=4)
        self.q.trace_add("write", lambda *_a: self.rebuild())
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True, padx=4)
        self.tree = ttk.Treeview(f, columns=("where",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="object")
        self.tree.heading("where", text="where")
        self.tree.column("#0", width=230, stretch=True)
        self.tree.column("where", width=72, anchor="w", stretch=False)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        self.tree.bind("<Double-Button-1>", lambda _e: ed.show_tab("Inspect"))
        self._open = {"mobj": True, "warp": True, "si": True}
        self._syncing = False
        hint(self, "Double-click opens the Inspector. Script NPCs appear once the 'script NPCs' "
                   "layer is on (View tab); clicking one opens its script line.").pack(anchor="w", padx=4, pady=4)

    def rebuild(self):
        doc = self.ed.doc
        t = self.tree
        for g, _lab in self.GROUPS:
            if t.exists(g):
                self._open[g] = bool(t.item(g, "open"))
        t.delete(*t.get_children())
        if doc is None:
            return
        words = self.q.get().lower().split()

        def ok(text):
            return all(w in text.lower() for w in words)
        rows = {g: [] for g, _l in self.GROUPS}
        for i, o in enumerate(doc.objs):
            tid = o["type_id"] & 0xFFFF
            nm = f"#{i}  {mobj_types.mobj_display_name(tid) or f'type {tid}'}"
            if o["category"] == "mapparam":
                rows["param"].append((("mobj", i), nm, "map-wide"))
            else:
                where = "unplaced" if not (o["pos_x"] or o["pos_y"]) else f"({o['pos_x'] >> 3}, {o['pos_y'] >> 3})"
                rows["mobj"].append((("mobj", i), f"{nm}  [{o['category']}]", where))
        for j, rec in enumerate(doc.map.mapj_records()):
            dest = map_names.describe_destination(rec[5])[0] or data.rooms_by_id().get(rec[5], f"map {rec[5]}")
            rows["warp"].append((("warp", j), f"#{j}  → {dest}", f"({rec[1] >> 3}, {rec[2] >> 3})"))
        if doc.si is not None:
            for i, sp in enumerate(doc.si.spots):
                rows["si"].append((("si", i), f"#{i}  {len(sp.pool.entries)} drop(s)",
                                   f"({sp.tile_x}, {sp.tile_y})"))
        for kind, off, x, y, users in doc.gate_points():
            lab = "gate position" if kind == "gpos" else "monster point"
            rows["gate"].append(((kind, off), f"{lab}  ({len(users)} gate(s))", f"({x >> 3}, {y >> 3})"))
        for i, sp in enumerate(self.ed.view.st.spawns or ()):
            rows["spawn"].append((("spawn", i), f"{sp['name']}  (inst {sp['instance']})",
                                  f"({sp['x'] >> 3}, {sp['y'] >> 3})"))
        for g, lab in self.GROUPS:
            items = [r for r in rows[g] if ok(r[1] + " " + lab)] if words else rows[g]
            if not items:
                continue
            t.insert("", "end", iid=g, text=f"{lab} ({len(items)})", open=self._open.get(g, bool(words)))
            for key, text, where in items:
                t.insert(g, "end", iid=key_iid(key), text=text, values=(where,))
        self.reveal(self.ed.sel)

    def reveal(self, key):
        t = self.tree
        self._syncing = True
        try:
            if key is not None and t.exists(key_iid(key)):
                iid = key_iid(key)
                t.selection_set(iid)
                t.see(iid)
            else:
                t.selection_remove(*t.selection())
        finally:
            ui.later(self, lambda: setattr(self, "_syncing", False))

    def _picked(self, _e=None):
        if self._syncing:
            return
        s = self.tree.selection()
        key = iid_key(s[0]) if s else None
        if key is None:
            return
        if key[0] == "spawn":
            self.ed.open_spawn(key[1])
            return
        self.ed.select(key, center=True)


# --------------------------------------------------------------------------- #
SEASON_TAGS = ("0 spring / none", "1 summer", "2 autumn", "3 winter", "4 house / barn / system")


class MapTab(ui.ScrollFrame):
    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        b = self.body
        # ---- header chunks ----
        p = section(b, "Properties")
        ttk.Label(p, text="Season tag (MSEA)").grid(row=0, column=0, sticky="w")
        self.msea = tk.StringVar()
        cb = ttk.Combobox(p, textvariable=self.msea, values=SEASON_TAGS, width=22)
        cb.grid(row=0, column=1, sticky="w", pady=1)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._commit_msea())
        cb.bind("<Return>", lambda _e: self._commit_msea())
        cb._commit = self._commit_msea
        ui.Tip(cb, "Stored in every shipped map, but nothing in the game reads it.")
        ttk.Label(p, text="Group bits (MGRP)").grid(row=1, column=0, sticky="w")
        self.mgrp = tk.StringVar()
        e = commit_entry(p, self.mgrp, self._commit_mgrp_hex, width=12)
        e.grid(row=1, column=1, sticky="w", pady=1)
        ui.Tip(e, "Required. Bits 0-3 fix the ambience season, bit 4 = no weather, one of bits "
                  "5-25 = the area group (BGM, minimap).")
        sf = ttk.Frame(p)
        sf.grid(row=2, column=0, columnspan=2, sticky="w")
        self.mgrp_bits = {}
        for i, (m, nm) in enumerate(list(rf4m.MGRP_SEASON_BITS.items()) + [(rf4m.MGRP_NO_WEATHER, "no weather")]):
            v = tk.BooleanVar()
            self.mgrp_bits[m] = v
            ttk.Checkbutton(sf, text=nm, variable=v, command=self._commit_mgrp_controls).grid(
                row=0, column=i, sticky="w", padx=(0, 4))
        ttk.Label(p, text="Area group").grid(row=3, column=0, sticky="w")
        self.group = tk.StringVar()
        self.group_choices = ["(none)"] + [f"bit {b}  {rf4m.MGRP_GROUP_NAMES.get(b, 'unnamed')}"
                                           for b in range(5, 26)]
        gc = ttk.Combobox(p, textvariable=self.group, values=self.group_choices, state="readonly", width=26)
        gc.grid(row=3, column=1, sticky="w", pady=1)
        gc.bind("<<ComboboxSelected>>", lambda _e: self._commit_mgrp_controls())
        self.mgrp_note = ttk.Label(p, font=ui.HINT_FONT, foreground=ui.GOOD, wraplength=300, justify="left")
        self.mgrp_note.grid(row=4, column=0, columnspan=2, sticky="w")
        # ---- tints ----
        t = section(b, "Tile tints (MLIG)")
        self.tints = []
        for i, slot in enumerate(rf4m.MLIG_SLOTS):
            ttk.Label(t, text=slot).grid(row=i, column=0, sticky="w")
            dv, tv = tk.BooleanVar(), tk.StringVar()
            ttk.Checkbutton(t, text="default", variable=dv,
                            command=lambda i=i: self._commit_tint_default(i)).grid(row=i, column=1, sticky="w")
            sw = tk.Button(t, width=3, relief="solid", bd=1, command=lambda i=i: self._pick_tint(i))
            sw.grid(row=i, column=2, padx=4, pady=1)
            en = commit_entry(t, tv, lambda i=i: self._commit_tint_text(i), width=12)
            en.grid(row=i, column=3, sticky="w")
            self.tints.append((dv, tv, sw, en))
        self.tint_note = hint(t, "", wrap=300)
        self.tint_note.grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))
        # ---- layers / grid ----
        g = section(b, "Ground layers and grid")
        self.layers_lbl = ttk.Label(g)
        self.layers_lbl.grid(row=0, column=0, sticky="w")
        bb = ttk.Frame(g)
        bb.grid(row=0, column=1, sticky="e")
        ttk.Button(bb, text="+", width=3, command=lambda: self._mtxn(+1)).pack(side="left")
        ttk.Button(bb, text="−", width=3, command=lambda: self._mtxn(-1)).pack(side="left", padx=2)
        hint(g, "Display layers = the MTXN chunk count: 1 draws the ground, 2 adds the overlay set "
                "(only where the map id has one), 0 draws no ground at all. The MTXN value itself "
                "is never read.").grid(row=1, column=0, columnspan=2, sticky="w")
        self.grid_lbl = ttk.Label(g)
        self.grid_lbl.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(g, text="Resize grid…", command=ed.open_resize).grid(row=2, column=1, sticky="e", pady=(6, 0))
        ttk.Button(g, text="Raw chunks…", command=ed.open_chunks).grid(row=3, column=1, sticky="e", pady=(4, 0))
        hint(g, "Raw chunks: a hex editor for anything the other panels do not cover.", wrap=180).grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        g.columnconfigure(0, weight=1)
        # ---- summary ----
        s = section(b, "Summary")
        self.summary = tk.Text(s, height=18, width=40, font=("Consolas", 8), wrap="word", relief="flat")
        self.summary.pack(fill="both", expand=True)
        self.summary.configure(state="disabled")
        self.bind_wheel_tree()

    # ---- refresh -------------------------------------------------------- #
    def refresh(self):
        doc = self.ed.doc
        if doc is None:
            return
        m = doc.map
        ms = m.get_ints("MSEA")
        self.msea.set(SEASON_TAGS[ms[0]] if ms and 0 <= ms[0] < len(SEASON_TAGS) else (str(ms[0]) if ms else ""))
        g = m.mgrp()
        self.mgrp.set("" if g is None else f"0x{g:X}")
        g = g or 0
        for mask, v in self.mgrp_bits.items():
            v.set(bool(g & mask))
        bits = [b for b in range(5, 26) if g >> b & 1]
        self.group.set(self.group_choices[bits[0] - 4] if bits else "(none)")
        self.mgrp_note.config(text=rf4m.mgrp_notes(g) if m.mgrp() is not None else "⚠ no MGRP chunk: the game crashes on load")
        cols = m.mlig_colors()
        for i, (dv, tv, sw, en) in enumerate(self.tints):
            c = cols[i]
            dv.set(c is None)
            shown = c or rf4m.MLIG_DEFAULTS[i]
            tv.set("" if c is None else "%d,%d,%d" % c)
            en.config(state="disabled" if c is None else "normal")
            sw.config(bg="#%02x%02x%02x" % shown)
        t12 = [i for i, o in enumerate(doc.objs) if (o["type_id"] & 0xFFFF) == 12]
        self.tint_note.config(text=("Type-12 tint records override these: entities "
                                    + ", ".join(f"#{i}" for i in t12) + ". Every stock map sets its "
                                    "lighting that way and leaves MLIG at the defaults.") if t12 else
                              "Blank / default = the engine default colour for that time of day.")
        n = len(m.find(b"MTXN"))
        what = {0: "no ground drawn!", 1: "ground only", 2: "ground + overlay"}.get(n, "only 2 are used")
        self.layers_lbl.config(text=f"{n} display layer(s): {what}")
        if doc.grid:
            W, H, _ = doc.grid
            cols_, rows_ = mapground.grid_dims(W, H)
            self.grid_lbl.config(text=f"{W} x {H} tiles · ground atlas {cols_} x {rows_} tiles")
        else:
            self.grid_lbl.config(text="no ATTR grid")
        ui.set_text(self.summary, self.ed.summary_text())

    # ---- commits -------------------------------------------------------- #
    def _commit_msea(self):
        v = data.leading_int(self.msea.get())
        cur = self.ed.doc.map.get_ints("MSEA")
        if v is None or (cur and cur[0] == v):
            return
        self.ed.apply("Set season tag", "props", lambda: self.ed.doc.map.set_ints("MSEA", [v]))

    def _set_mgrp(self, v):
        if v == self.ed.doc.map.mgrp():
            return
        self.ed.apply("Set MGRP", "props", lambda: self.ed.doc.map.set_ints("MGRP", [v & 0xFFFFFFFF], signed=False))

    def _commit_mgrp_hex(self):
        v = ui.to_int(self.mgrp.get())
        if v is not None:
            self._set_mgrp(v)

    def _commit_mgrp_controls(self):
        v = self.ed.doc.map.mgrp() or 0
        for mask, bv in self.mgrp_bits.items():
            v = (v | mask) if bv.get() else (v & ~mask)
        v &= ~(((1 << 26) - 1) & ~0x1F)                  # clear bits 5..25
        g = self.group.get()
        if g.startswith("bit "):
            v |= 1 << int(g.split()[1])
        self._set_mgrp(v)

    def _set_tints(self, cols, label):
        if cols == self.ed.doc.map.mlig_colors():
            return
        self.ed.apply(label, "props", lambda: self.ed.doc.map.set_mlig_colors(cols))

    def _commit_tint_default(self, i):
        cols = self.ed.doc.map.mlig_colors()
        cols[i] = None if self.tints[i][0].get() else rf4m.MLIG_DEFAULTS[i]
        self._set_tints(cols, f"Set {rf4m.MLIG_SLOTS[i]} tint")

    def _commit_tint_text(self, i):
        s = self.tints[i][1].get().strip().replace(";", ",").replace(" ", ",")
        parts = [p for p in s.split(",") if p]
        try:
            rgb = tuple(int(p, 0) for p in parts)
        except ValueError:
            return
        if len(rgb) != 3 or not all(0 <= c <= 255 for c in rgb):
            self.ed.status("A tint is three numbers 0..255: r,g,b")
            return
        cols = self.ed.doc.map.mlig_colors()
        cols[i] = rgb
        self._set_tints(cols, f"Set {rf4m.MLIG_SLOTS[i]} tint")

    def _pick_tint(self, i):
        cols = self.ed.doc.map.mlig_colors()
        cur = cols[i] or rf4m.MLIG_DEFAULTS[i]
        res = colorchooser.askcolor(color="#%02x%02x%02x" % cur, title=f"{rf4m.MLIG_SLOTS[i]} tint")
        if res and res[0]:
            cols[i] = tuple(int(c) for c in res[0])
            self._set_tints(cols, f"Set {rf4m.MLIG_SLOTS[i]} tint")

    def _mtxn(self, delta):
        m = self.ed.doc.map
        idxs = [i for i, c in enumerate(m.chunks) if c.tag == b"MTXN"]
        if delta > 0:
            src = m.chunks[idxs[-1]].payload if idxs else b"\0\0\0\0"
            self.ed.apply("Add display layer", "chunks",
                          lambda: m.add_chunk("MTXN", src, at=(idxs[-1] + 1) if idxs else 0))
        elif idxs:
            self.ed.apply("Remove display layer", "chunks", lambda: m.delete_chunk(idxs[-1]))


# --------------------------------------------------------------------------- #
class EncountersTab(ui.ScrollFrame):
    """The area's Gen*.bin encounter table (a separate file from the map)."""

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        b = self.body
        self.file_lbl = ttk.Label(b, font=ui.HINT_FONT, wraplength=320, justify="left")
        self.file_lbl.pack(anchor="w", padx=4, pady=(4, 0))
        g = section(b, "Gates")
        self.gates = ttk.Treeview(g, columns=("kind", "w", "mon"), show="headings", height=6,
                                  selectmode="browse")
        for c, t, w in (("kind", "gate", 170), ("w", "weight", 50), ("mon", "monsters", 60)):
            self.gates.heading(c, text=t)
            self.gates.column(c, width=w, anchor="w" if c == "kind" else "e", stretch=(c == "kind"))
        self.gates.pack(fill="x")
        self.gates.bind("<<TreeviewSelect>>", self._gate_picked)
        f = ttk.Frame(g)
        f.pack(fill="x", pady=(4, 0))
        ttk.Label(f, text="kind").grid(row=0, column=0, sticky="w")
        self.kind = ui.FilterCombo(f, data.gate_choices(), lambda _t: self._commit_gate(), width=24)
        self.kind.grid(row=0, column=1, columnspan=3, sticky="we")
        self.v = {k: tk.StringVar() for k in ("weight", "cmin", "cmax", "delay")}
        for r, c, lab, k, tip in ((1, 0, "weight", "weight", "Chance of this gate among the pattern's gates."),
                                  (1, 2, "delay", "delay", "Frames between spawns."),
                                  (2, 0, "min", "cmin", "Fewest monsters alive at once."),
                                  (2, 2, "max", "cmax", "Most monsters alive at once.")):
            ttk.Label(f, text=lab).grid(row=r, column=c, sticky="w")
            en = commit_entry(f, self.v[k], self._commit_gate, width=7)
            en.grid(row=r, column=c + 1, sticky="w", pady=1)
            ui.Tip(en, tip)
        gb = ttk.Frame(g)
        gb.pack(fill="x", pady=(4, 0))
        ttk.Button(gb, text="Add (copy)", command=self._add_gate).pack(side="left")
        ttk.Button(gb, text="Remove", command=self._remove_gate).pack(side="left", padx=2)
        self.unshare_btn = ttk.Button(gb, text="Make private", command=self._unshare)
        self.unshare_btn.pack(side="left")
        ui.Tip(self.unshare_btn, "Give this gate its own copies of the blocks it shares with other "
                                 "gates, so edits stop affecting them.")
        self.share_lbl = ttk.Label(g, font=ui.HINT_FONT, foreground="#c60", wraplength=310, justify="left")
        self.share_lbl.pack(anchor="w")
        pf = ttk.Frame(g)
        pf.pack(fill="x", pady=(4, 0))
        self.pts_lbl = ttk.Label(pf, font=ui.HINT_FONT)
        self.pts_lbl.pack(side="left")
        b1 = ttk.Button(pf, text="+ gate", width=7, command=lambda: ed.start_add("gpos"))
        b1.pack(side="right")
        ui.Tip(b1, "Click the map to add a gate position to the selected gate.")
        b2 = ttk.Button(pf, text="+ spawn", width=7, command=lambda: ed.start_add("mpos"))
        b2.pack(side="right", padx=2)
        ui.Tip(b2, "Click the map to add a monster spawn point to the selected gate.")
        r = section(b, "Roster of the selected gate")
        self.roster = ttk.Treeview(r, columns=("mon", "lv", "w"), show="headings", height=6, selectmode="browse")
        for c, t, w in (("mon", "monster", 170), ("lv", "pick wt", 52), ("w", "weights", 80)):
            self.roster.heading(c, text=t)
            self.roster.column(c, width=w, anchor="w" if c != "lv" else "e", stretch=(c == "mon"))
        self.roster.pack(fill="x")
        self.roster.bind("<<TreeviewSelect>>", self._mon_picked)
        mf = ttk.Frame(r)
        mf.pack(fill="x", pady=(4, 0))
        self.mon = ui.FilterCombo(mf, data.monster_choices(), None, width=24)
        self.mon.pack(side="left", fill="x", expand=True)
        ttk.Label(mf, text=" weight").pack(side="left")
        self.lv = tk.StringVar(value="10")
        ttk.Entry(mf, textvariable=self.lv, width=4).pack(side="left")
        mb = ttk.Frame(r)
        mb.pack(fill="x", pady=(2, 0))
        ttk.Button(mb, text="Add monster", command=self._add_mon).pack(side="left")
        ttk.Button(mb, text="Replace", command=self._replace_mon).pack(side="left", padx=2)
        ttk.Button(mb, text="Remove", command=self._remove_mon).pack(side="left")
        hint(b, "Gates (kind 359-390) are picked by weight; the roster lists the monsters a gate "
                "spawns (id 48-254), each with a pick weight (its relative chance; stock uses 5 or 10) and one "
                "weight per monster spawn point. On the map: "
                "orange G = gate positions, pink dots = monster spawn points (the selected gate's are "
                "outlined white). Drag them with the Select tool. Gates often share one roster, so a "
                "monster added to one shows up in all of them until you 'Make private'.").pack(
            anchor="w", padx=6, pady=6)
        self.bind_wheel_tree()

    def _entry(self):
        return self.ed.active_gate

    def refresh(self):
        doc = self.ed.doc
        t = self.gates
        t.delete(*t.get_children())
        if doc is None or doc.gen is None:
            self.file_lbl.config(text="This map has no encounter table (only dungeon and field maps "
                                      "have one).")
            self.roster.delete(*self.roster.get_children())
            self.share_lbl.config(text="")
            self.pts_lbl.config(text="")
            return
        self.file_lbl.config(text=f"{doc.gen_path.name if doc.gen_path else 'Gen*.bin'} · "
                                  f"{sum(len(p) for p in doc.gen.patterns)} gate(s) in "
                                  f"{len(doc.gen.patterns)} pattern(s)")
        for pi, ei, e in doc.gen.all_entries():
            nmon = sum(1 for s in e.spawns if gen.MONSTER_LO <= s.monster_id <= gen.MONSTER_HI)
            t.insert("", "end", iid=f"{pi}:{ei}",
                     values=(f"{e.gate_kind}  {data.actor_name(e.gate_kind)}".strip(), e.weight, nmon))
        gi = self.ed.gate_index
        if gi is not None and t.exists(f"{gi[0]}:{gi[1]}"):
            t.selection_set(f"{gi[0]}:{gi[1]}")
            t.see(f"{gi[0]}:{gi[1]}")
        self._show_gate()

    def _show_gate(self):
        e = self._entry()
        r = self.roster
        keep = r.selection()
        r.delete(*r.get_children())
        if e is None:
            for v in self.v.values():
                v.set("")
            self.kind.var.set("")
            self.share_lbl.config(text="Select a gate.")
            self.pts_lbl.config(text="")
            return
        self.kind.var.set(f"{e.gate_kind}  {data.actor_name(e.gate_kind)}".strip())
        self.v["weight"].set(str(e.weight))
        self.v["cmin"].set(str(e.hdr.count_min))
        self.v["cmax"].set(str(e.hdr.count_max))
        self.v["delay"].set(str(e.hdr.spawn_delay))
        for k, s in enumerate(e.spawns):
            ok = gen.MONSTER_LO <= s.monster_id <= gen.MONSTER_HI
            r.insert("", "end", iid=str(k), values=(f"{s.monster_id}  {data.actor_name(s.monster_id) or '?'}"
                                                    + ("" if ok else "  (not a monster)"),
                                                    s.level, " ".join(map(str, s.weights))))
        if keep and r.exists(keep[0]):
            r.selection_set(keep[0])
        g = self.ed.doc.gen
        shared = [n for n, blk in (("roster", "roster"), ("gate positions", "gate_pos"),
                                   ("monster points", "mon_pos"))
                  if sum(1 for _p, _e, o in g.all_entries() if getattr(o, blk) is getattr(e, blk)) > 1]
        self.share_lbl.config(text=("Shares its " + ", ".join(shared) + " with other gates.") if shared else "")
        self.pts_lbl.config(text=f"{len(e.gate_pos.points)} gate position(s), "
                                 f"{len(e.mon_pos.points)} monster point(s)")

    def _gate_picked(self, _e=None):
        s = self.gates.selection()
        if s:
            pi, ei = (int(x) for x in s[0].split(":"))
            if (pi, ei) != self.ed.gate_index:
                self.ed.set_active_gate((pi, ei))
            self._show_gate()

    def _commit_gate(self):
        e = self._entry()
        if e is None:
            return
        kind = data.leading_int(self.kind.var.get())
        vals = {k: ui.to_int(v.get()) for k, v in self.v.items()}
        if kind is None or None in vals.values():
            return
        cur = (e.gate_kind, e.weight, e.hdr.count_min, e.hdr.count_max, e.hdr.spawn_delay)
        new = (kind & 0xFFFF, vals["weight"] & 0xFFFF, vals["cmin"] & 0xFF, vals["cmax"] & 0xFF,
               vals["delay"] & 0xFFFF)
        if cur == new:
            return
        pi, ei = self.ed.gate_index

        def do():
            g = self.ed.doc.gen
            ent = g.patterns[pi][ei]
            g.set_gate_kind(pi, ei, new[0])
            g.set_weight(pi, ei, new[1])
            g.set_hdr(ent, count_min=new[2], count_max=new[3], spawn_delay=new[4])
        self.ed.apply(f"Edit gate {pi}:{ei}", "gen", do)

    def _add_gate(self):
        gi = self.ed.gate_index
        if gi is None:
            self.ed.status("Select a gate to copy first.")
            return
        pi, ei = gi

        def do():
            g = self.ed.doc.gen
            src = g.patterns[pi][ei]
            g.add_entry(pi, src.gate_kind, src.weight, clone=src, share=False)
        if self.ed.apply("Add gate", "gen", do):
            self.ed.set_active_gate((pi, len(self.ed.doc.gen.patterns[pi]) - 1))

    def _remove_gate(self):
        gi = self.ed.gate_index
        if gi is None:
            return
        pi, ei = gi
        from tkinter import messagebox
        if len(self.ed.doc.gen.patterns[pi]) == 1 and not messagebox.askyesno(
                "Remove gate", "This is the pattern's last gate: the area would spawn nothing. Remove it?"):
            return
        self.ed.set_active_gate(None)
        self.ed.apply("Remove gate", "gen", lambda: self.ed.doc.gen.remove_entry(pi, ei))

    def _unshare(self):
        gi = self.ed.gate_index
        if gi is not None:
            pi, ei = gi
            self.ed.apply("Make gate private", "gen",
                          lambda: self.ed.doc.gen.unshare(self.ed.doc.gen.patterns[pi][ei]))

    def _mon_picked(self, _e=None):
        e = self._entry()
        s = self.roster.selection()
        if e is None or not s:
            return
        sp = e.spawns[int(s[0])]
        self.mon.var.set(f"{sp.monster_id}  {data.actor_name(sp.monster_id)}".strip())
        self.lv.set(str(sp.pick_weight))

    def _mon_values(self):
        mid, lv = data.leading_int(self.mon.var.get()), ui.to_int(self.lv.get())
        if mid is None or lv is None:
            self.ed.status("Pick a monster and a pick weight first.")
            return None
        return mid & 0xFFFF, lv & 0xFFFF

    def _add_mon(self):
        v = self._mon_values()
        gi = self.ed.gate_index
        if v is None or gi is None:
            return
        pi, ei = gi
        self.ed.apply(f"Add monster {v[0]}", "gen",
                      lambda: self.ed.doc.gen.add_spawn(self.ed.doc.gen.patterns[pi][ei], *v))

    def _replace_mon(self):
        v = self._mon_values()
        gi = self.ed.gate_index
        s = self.roster.selection()
        if v is None or gi is None or not s:
            return
        pi, ei = gi
        k = int(s[0])

        def do():
            g = self.ed.doc.gen
            sp = g.patterns[pi][ei].spawns[k]
            g.set_spawn_monster(sp, v[0])
            g.set_spawn_param(sp, v[1])
        self.ed.apply("Edit roster monster", "gen", do)

    def _remove_mon(self):
        gi = self.ed.gate_index
        s = self.roster.selection()
        if gi is None or not s:
            return
        pi, ei = gi
        k = int(s[0])
        self.ed.apply("Remove roster monster", "gen",
                      lambda: self.ed.doc.gen.remove_spawn(self.ed.doc.gen.patterns[pi][ei], k))


# --------------------------------------------------------------------------- #
LAYER_DEFAULTS = {"attr": True, "edges": True, "grid": False, "trigger": True, "actor": True,
                  "object": True, "decoration": True, "sprites": False, "labels": False,
                  "mapj": True, "dest": True, "si": True, "gates": True, "spawns": False}
LAYER_GROUPS = {"attr": "bg", "edges": "bg", "grid": "grid", "trigger": "ent", "actor": "ent",
                "object": "ent", "decoration": "ent", "sprites": "ent", "labels": "ent",
                "mapj": "warp", "dest": "dest", "si": "si", "gates": "gate", "spawns": "spawn"}
LAYER_NAMES = {0: "0 ground", 1: "1 overlay"}


class ViewTab(ui.ScrollFrame):
    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        b = self.body
        self.vars = {}
        L = section(b, "Layers")

        def cb(parent, key, text, r, c, color=None):
            v = self.vars.setdefault(key, tk.BooleanVar(value=LAYER_DEFAULTS[key]))
            w = ttk.Checkbutton(parent, text=text, variable=v, command=lambda: ed.set_layer(key, v.get()))
            w.grid(row=r, column=2 * c + 1, sticky="w", padx=(0, 8))
            if color:
                tk.Frame(parent, bg=color, width=10, height=10).grid(row=r, column=2 * c, padx=(0, 3))
        cb(L, "attr", "ATTR fill", 0, 0)
        cb(L, "edges", "cell edges", 0, 1)
        L.columnconfigure(3, weight=1)
        ttk.Label(L, text="Entities", font=ui.HINT_FONT).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        cb(L, "trigger", "forage / triggers", 2, 0, attrs.CAT_COLOR["forage"])
        cb(L, "actor", "actors", 2, 1, attrs.CAT_COLOR["actor"])
        cb(L, "object", "objects", 3, 0, attrs.CAT_COLOR["object"])
        cb(L, "decoration", "decorations", 3, 1, attrs.CAT_COLOR["decoration"])
        cb(L, "sprites", "draw sprites", 4, 0)
        cb(L, "labels", "name labels", 4, 1)
        ttk.Label(L, text="Other", font=ui.HINT_FONT).grid(row=5, column=0, columnspan=4, sticky="w", pady=(4, 0))
        cb(L, "mapj", "warps", 6, 0, render.WARP_COLOR)
        cb(L, "dest", "warp destinations", 6, 1)
        cb(L, "si", "search spots", 7, 0, render.SI_COLOR)
        cb(L, "gates", "encounter points", 7, 1, render.GATE_COLOR)
        cb(L, "spawns", "script NPCs", 8, 0, render.SPAWN_COLOR)
        cb(L, "grid", "tile grid lines", 8, 1)
        hint(L, "Script NPCs are placed by the map's event script (rf3.mc), not the map file; the "
                "first time they are shown the script is scanned.", wrap=300).grid(
            row=9, column=0, columnspan=4, sticky="w", pady=(2, 0))
        # ---- ground display ----
        G = section(b, "Ground texture")
        ttk.Label(G, text="show").grid(row=0, column=0, sticky="w")
        self.ground = tk.StringVar(value="all")
        self.ground_cb = ttk.Combobox(G, textvariable=self.ground, values=["off", "all"], width=12,
                                      state="readonly")
        self.ground_cb.grid(row=0, column=1, sticky="w")
        self.ground_cb.bind("<<ComboboxSelected>>", lambda _e: ed.set_ground_display(self.ground.get()))
        self.scenery = tk.BooleanVar(value=True)
        sc_cb = ttk.Checkbutton(G, text="scenery (the map's over-model)", variable=self.scenery,
                                command=lambda: ed.set_scenery(self.scenery.get()))
        sc_cb.grid(row=3, column=0, columnspan=2, sticky="w")
        ui.Tip(sc_cb, "The pre-rendered billboard cards (statues, railings, rooftops, trees) the "
                      "game draws over the ground, placed where the model's bones put them.")
        ttk.Label(G, text="ATTR opacity").grid(row=1, column=0, sticky="w")
        self.alpha = tk.IntVar(value=180)
        sc = ttk.Scale(G, from_=0, to=255, orient="horizontal", length=150, variable=self.alpha)
        sc.grid(row=1, column=1, sticky="w")
        sc.bind("<ButtonRelease-1>", lambda _e: ed.set_attr_alpha(self.alpha.get()))
        hint(G, "Opacity applies while the texture is shown. Static '_UV' dungeon backdrops are "
                "stretched over the map and do not line up with the tiles.", wrap=300).grid(
            row=2, column=0, columnspan=2, sticky="w")
        # ---- ground files ----
        F = section(b, "Replace the ground art")
        ttk.Label(F, text="layer").grid(row=0, column=0, sticky="w")
        self.glayer = tk.StringVar(value="0 ground")
        self.glayer_cb = ttk.Combobox(F, textvariable=self.glayer, values=["0 ground"], width=10,
                                      state="readonly")
        self.glayer_cb.grid(row=0, column=1, sticky="w")
        ttk.Label(F, text="format").grid(row=0, column=2, sticky="w", padx=(6, 0))
        self.gfmt = tk.StringVar(value="keep")
        ttk.Combobox(F, textvariable=self.gfmt, values=list(texture.ENCODE_FORMATS), width=8,
                     state="readonly").grid(row=0, column=3, sticky="w")
        bb = ttk.Frame(F)
        bb.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Button(bb, text="Export PNG…", command=ed.ground_export).pack(side="left")
        ttk.Button(bb, text="Import PNG…", command=ed.ground_import).pack(side="left", padx=4)
        self.gstatus = ttk.Label(F, font=ui.HINT_FONT, foreground=ui.GOOD, wraplength=300, justify="left")
        self.gstatus.grid(row=2, column=0, columnspan=4, sticky="w")
        hint(F, "Export stitches one layer to a PNG; edit it at exactly that size, then Import "
                "splits it back into .texture tiles (each keeps its size and format) for a loose "
                "override or a repack.", wrap=300).grid(row=3, column=0, columnspan=4, sticky="w")
        self.bind_wheel_tree()

    def layers(self):
        return {k: v.get() for k, v in self.vars.items()}

    def set_available_layers(self, layers):
        vals = ["off", "all"] + [LAYER_NAMES.get(l, str(l)) for l in layers]
        self.ground_cb["values"] = vals
        if self.ground.get() not in vals:
            self.ground.set("all" if layers else "off")
        gv = [LAYER_NAMES.get(l, str(l)) for l in layers] or ["0 ground"]
        self.glayer_cb["values"] = gv
        if self.glayer.get() not in gv:
            self.glayer.set(gv[0])
        self.glayer_cb.config(state="readonly" if len(gv) > 1 else "disabled")


# --------------------------------------------------------------------------- #
_REF = (("mobj", re.compile(r"MOBJ #(\d+)")), ("warp", re.compile(r"warp #(\d+)")),
        ("si", re.compile(r"search spot #(\d+)")))


class ProblemsTab(ttk.Frame):
    """Validation against what the game's loaders do, for the map and both sidecars."""

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=4)
        ttk.Button(top, text="Check now", command=self.run).pack(side="left")
        self.summary = ttk.Label(top, font=ui.HINT_FONT)
        self.summary.pack(side="left", padx=6)
        self.tree = ttk.Treeview(self, columns=("msg",), show="tree", selectmode="browse", height=12)
        self.tree.column("#0", width=70, stretch=False)
        self.tree.column("msg", width=260)
        self.tree.pack(fill="both", expand=True, padx=4)
        self.tree.tag_configure("ERROR", foreground="#c22")
        self.tree.tag_configure("WARN", foreground="#b70")
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        self.detail = tk.Text(self, height=7, wrap="word", font=ui.HINT_FONT, relief="flat")
        self.detail.pack(fill="x", padx=4, pady=4)
        self.detail.configure(state="disabled")
        self.issues = []
        hint(self, "ERROR = the game crashes, drops data or draws nothing. WARN = it loads, but "
                   "probably not the way you expect. Select an issue to jump to its object.").pack(
            anchor="w", padx=4, pady=(0, 4))

    def run(self):
        self.issues = self.ed.validate()
        t = self.tree
        t.delete(*t.get_children())
        for k, (sev, where, msg) in enumerate(self.issues):
            t.insert("", "end", iid=str(k), text=f"{sev} {where}", values=(msg,), tags=(sev,))
        n_err = sum(1 for s, _w, _m in self.issues if s == "ERROR")
        self.summary.config(text=("No problems found." if not self.issues else
                                  f"{len(self.issues)} issue(s), {n_err} fatal"),
                            foreground="#c22" if n_err else (ui.GOOD if not self.issues else "#b70"))
        ui.set_text(self.detail, self.ed.stats_line())
        return self.issues

    def _picked(self, _e=None):
        s = self.tree.selection()
        if not s:
            return
        sev, where, msg = self.issues[int(s[0])]
        ui.set_text(self.detail, f"{sev} ({where}): {msg}")
        for kind, rx in _REF:
            m = rx.search(msg)
            if m and where in ("map", "search items"):
                self.ed.select((kind, int(m.group(1))), center=True)
                return
