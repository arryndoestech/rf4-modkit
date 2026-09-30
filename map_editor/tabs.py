"""The sidebar tabs besides the Inspector: Objects, Map, Gates (EncountersTab), View, Problems."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from rf4s_modkit import areagroup, gamepaths, gen, map_names, mapground, minimap, mobj_types, rf4m, texture

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
              ("runtime", "Built into the game (read only)"),
              ("si", "Search spots"), ("gate", "Monster gates"), ("spawn", "Script spawns"))

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
        for k in ("<Delete>", "<BackSpace>"):
            self.tree.bind(k, self._delete_key)
        self.tree.bind("<Button-3>", self._menu)
        self._open = {"mobj": True, "warp": True, "runtime": True, "si": True}
        self._syncing = False
        hint(self, "Double-click opens the Inspector; Del or right-click > Delete removes the "
                   "selected object (Ctrl+Z undoes it) -- also objects the map view does not show. "
                   "Script spawns appear once the 'script spawns' layer is on (View tab); clicking one "
                   "opens its script line.").pack(anchor="w", padx=4, pady=4)

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
                where = f"({o['pos_x'] >> 3}, {o['pos_y'] >> 3})"
                rows["mobj"].append((("mobj", i), f"{nm}  [{o['category']}]", where))
        for j, rec in enumerate(doc.map.mapj_records()):
            dest = map_names.describe_destination(rec[5])[0] or data.rooms_by_id().get(rec[5], f"map {rec[5]}")
            rows["warp"].append((("warp", j), f"#{j}  → {dest}", f"({rec[1] >> 3}, {rec[2] >> 3})"))
        for k, (rect, s, _tip) in enumerate(render.runtime_spawns(doc)):
            if s["kind"] == "warp":
                dest = map_names.describe_destination(s["dest"])[0] or data.rooms_by_id().get(
                    s["dest"], f"map {s['dest']}")
                text = f"warp → {dest}  (when {s['when']})"
            else:
                text = f"wall  (when {s['when']})"
            rows["runtime"].append((("runtime", k), text, f"({rect[0]}, {rect[1]})"))
        if doc.si is not None:
            for i, sp in enumerate(doc.si.spots):
                rows["si"].append((("si", i), f"#{i}  {len(sp.pool.entries)} drop(s)",
                                   f"({sp.tile_x}, {sp.tile_y})"))
        for kind, off, x, y, users in doc.gate_points():
            lab = "gate position" if kind == "gpos" else "monster point"
            rows["gate"].append(((kind, off), f"{lab}  ({len(users)} gate(s))", f"({x >> 3}, {y >> 3})"))
        for i, sp in enumerate(self.ed.view.st.spawns or ()):
            what = "object" if sp.get("kind") == "entity" else f"inst {sp['instance']}"
            rows["spawn"].append((("spawn", i), f"{sp['name']}  ({what})",
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

    # the rows that can be deleted: placed objects, warps, search spots and gate / monster
    # points (script NPCs live in the event script, group rows are headings)
    DELETABLE = ("mobj", "warp", "si", "gpos", "mpos")

    def _row_key(self, iid):
        key = iid_key(iid) if iid else None
        return tuple(key) if key is not None and key[0] in self.DELETABLE else None

    def delete_row(self, iid):
        """Delete the object behind a row (one undo step). True when something was deleted."""
        key = self._row_key(iid)
        if key is None:
            return False
        self.ed.delete(key)
        return True

    def _delete_key(self, _e=None):
        s = self.tree.selection()
        if s and not self.delete_row(s[0]):
            self._explain_undeletable(s[0])
        return "break"                  # the map's own Delete binding must not fire as well

    def _explain_undeletable(self, iid):
        key = iid_key(iid)
        if key is not None and key[0] == "runtime":
            messagebox.showinfo("Built into the game", render.HARDCODED_NOTE + "\n\n"
                                "To keep players out of a warp, paint walls (ATTR 0x2) over its "
                                "zone; the room it leads to is an ordinary map you can edit.",
                                parent=self)
        elif key is not None and key[0] == "spawn":
            self.ed.status("Script spawns are placed by the map's event script, not the map file")
        else:
            self.ed.status("Group headings cannot be deleted")

    def _menu(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        key = self._row_key(iid)
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Show on map", state="normal" if key else "disabled",
                      command=lambda: self.ed.select(key, center=True))
        m.add_command(label="Open in Inspector", state="normal" if key else "disabled",
                      command=lambda: (self.ed.select(key, center=True), self.ed.show_tab("Inspect")))
        m.add_separator()
        m.add_command(label="Delete", command=lambda: (self.delete_row(iid)
                                                        or self._explain_undeletable(iid)))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _picked(self, _e=None):
        if self._syncing:
            return
        s = self.tree.selection()
        key = iid_key(s[0]) if s else None
        if key is None:
            return
        if tuple(key) == self.ed.sel:
            return          # reveal()'s own echo (it can arrive after _syncing is cleared):
                            # re-selecting would drop the rest of a multi-selection
        if key[0] == "spawn":
            self.ed.open_spawn(key[1])
            return
        if key[0] == "runtime":                 # the game's own warp / wall: show it, explain
            rs = render.runtime_spawns(self.ed.doc)
            if 0 <= key[1] < len(rs):
                (x0, y0, x1, y1), _s, _tip = rs[key[1]]
                self.ed.view.center_on((x0 + x1) // 2, (y0 + y1) // 2)
            self.ed.status("Built into the game: shown, but it cannot be moved, resized or "
                           "removed here (hover it on the map for details)")
            return
        self.ed.select(key, center=True)


# --------------------------------------------------------------------------- #
SEASON_TAGS = ("0 spring / none", "1 summer", "2 autumn", "3 winter", "4 house / barn / system")


MGRP_SEASON_CHOICES = ("follows the calendar", "always spring", "always summer",
                       "always autumn", "always winter")


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
        # ---- the MGRP value, as the three things it sets (areagroup) ----
        ttk.Label(p, text="Season").grid(row=1, column=0, sticky="w")
        self.season = tk.StringVar()
        sc = ttk.Combobox(p, textvariable=self.season, values=MGRP_SEASON_CHOICES,
                          state="readonly", width=22)
        sc.grid(row=1, column=1, sticky="w", pady=1)
        sc.bind("<<ComboboxSelected>>", lambda _e: self._commit_mgrp_controls())
        ui.Tip(sc, "MGRP bits 0-3. 'Always …' plays that season's ambience and music whatever the "
                   "calendar says (the lowest bit wins if several are set). A seasonal copy of "
                   "a map (_SUMMER …) is loaded by the calendar either way.")
        self.weather = tk.BooleanVar()
        wc = ttk.Checkbutton(p, text="Rain and snow", variable=self.weather,
                             command=self._commit_mgrp_controls)
        wc.grid(row=2, column=1, sticky="w")
        ttk.Label(p, text="Weather").grid(row=2, column=0, sticky="w")
        ui.Tip(wc, "MGRP bit 4 (set = no weather): unticked, the map shows no rain or snow and "
                   "the sound counts it as indoors -- dungeons and rooms.")
        ttk.Label(p, text="Area").grid(row=3, column=0, sticky="w")
        self.group = tk.StringVar()
        self.group_choices = ["(none) -- zone 0"] + [
            f"bit {b} · {areagroup.GROUP_LABELS.get(b, 'unnamed')} (zone {b - 5})" for b in range(5, 26)]
        gc = ttk.Combobox(p, textvariable=self.group, values=self.group_choices, state="readonly", width=34)
        gc.grid(row=3, column=1, sticky="w", pady=1)
        gc.bind("<<ComboboxSelected>>", lambda _e: self._commit_mgrp_controls())
        ui.Tip(gc, "MGRP bits 5-25, the area group: the lowest set bit is the zone, which picks "
                   "the music, the crate loot, the minimap group and the monster-gate table the "
                   "game loads (see the lines below).")
        ttk.Label(p, text="MGRP (raw)").grid(row=4, column=0, sticky="w")
        self.mgrp = tk.StringVar()
        e = ttk.Entry(p, textvariable=self.mgrp, width=12, state="readonly")   # (set it above)
        e.grid(row=4, column=1, sticky="w", pady=1)
        ui.Tip(e, "The whole value as stored (read only: Season, Weather and Area above set it). "
                  "Required: a map without an MGRP chunk crashes the game.")
        self.mgrp_note = ttk.Label(p, font=ui.HINT_FONT, foreground=ui.GOOD, wraplength=300, justify="left")
        self.mgrp_note.grid(row=5, column=0, columnspan=2, sticky="w")
        self.mgrp_warn = ttk.Label(p, font=ui.HINT_FONT, foreground="#b70", wraplength=300, justify="left")
        self.mgrp_warn.grid(row=6, column=0, columnspan=2, sticky="w")
        # ---- the HUD minimap: what the docked picture shows, in words ----
        mm = section(b, "Minimap")
        self.minimap_info = ttk.Label(mm, font=ui.HINT_FONT, wraplength=300, justify="left")
        self.minimap_info.pack(anchor="w")
        self.minimap_note = ttk.Label(mm, font=ui.HINT_FONT, foreground=ui.MUTED, wraplength=300,
                                      justify="left")
        self.minimap_note.pack(anchor="w", pady=(2, 0))
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
            if slot == "night":
                ui.Tip(sw, "With 'default' ticked the game uses 148,214,247 at night, or "
                           "181,214,214 on maps the game's map table marks for it (bit 0x10 of "
                           "the map's entry: indoor rooms, barns, caves and most dungeons); the "
                           "swatch shows the one this map gets.")
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
        self._show_mgrp(g)
        info, note = minimap_details(doc)
        self.minimap_info.config(text=info)
        self.minimap_note.config(text=note)
        cols = m.mlig_colors()
        for i, (dv, tv, sw, en) in enumerate(self.tints):
            c = cols[i]
            dv.set(c is None)
            shown = c or self._tint_defaults()[i]
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

    def _show_mgrp(self, g):
        """Season / weather / area controls, what the game makes of the value, and conflicts."""
        if g is None:
            self.season.set("")
            self.group.set("")
            self.mgrp_note.config(text="")
            self.mgrp_warn.config(text="⚠ no MGRP chunk: the game crashes on load")
            return
        seasons = [areagroup.SEASONS[i] for i in range(4) if g >> i & 1]
        self.season.set(MGRP_SEASON_CHOICES[0] if not seasons else
                        f"always {seasons[0]}" + (" (+ " + ", ".join(seasons[1:]) + ")" if seasons[1:] else ""))
        self.weather.set(not g & areagroup.NO_WEATHER)
        bits = areagroup.group_bits(g)
        self.group.set(self.group_choices[bits[0] - 4] + (f" + bits {', '.join(map(str, bits[1:]))}"
                                                          if bits[1:] else "") if bits else self.group_choices[0])
        doc = self.ed.doc
        eff = areagroup.effects(g, doc.base + ".rf4m" if doc.base else None, data.gen_name_for_id)
        self.mgrp_note.config(text="\n".join(f"{k}: {v}" for k, v in eff))
        probs = areagroup.problems(g, doc.base + ".rf4m" if doc.base else None,
                                   gen_entries=data.own_gen_entries(doc),
                                   gen_name_for=data.gen_name_for_id, gen_entries_for=data.gen_entries,
                                   sibling_zones=data.sibling_zones(doc.base) if doc.base else None)
        self.mgrp_warn.config(text="\n".join(("ⓘ " if sev == "INFO" else "⚠ ") + msg
                                             for sev, msg in probs))

    def _commit_mgrp_controls(self):
        """Apply the Season / Weather / Area controls, each touching only its own bits: an
        unchanged control leaves its bits exactly as stored (several season bits, the
        castle's extra group bits 22 / 23)."""
        v = self.ed.doc.map.mgrp() or 0
        cur = areagroup.season_of(v)
        sel = self.season.get()
        want = next((s for s in areagroup.SEASONS if sel.startswith(f"always {s}")), None)
        if sel in MGRP_SEASON_CHOICES and want != cur or (sel == MGRP_SEASON_CHOICES[0] and v & 0xF):
            v &= ~0xF
            if want is not None:
                v |= 1 << areagroup.SEASONS.index(want)
        v = (v & ~areagroup.NO_WEATHER) if self.weather.get() else (v | areagroup.NO_WEATHER)
        # the area group is the LOWEST set bit of 5..25: swap only that one, so extra group
        # bits (MAP_F_ROOM_00's 22 / 23 next to 6) survive
        old = next((b for b in range(5, 26) if v >> b & 1), None)
        g = self.group.get()
        new = int(g.split()[1]) if g.startswith("bit ") else None
        if new != old:
            if old is not None:
                v &= ~(1 << old)
            if new is not None:
                v |= 1 << new
        self._set_mgrp(v)

    def _tint_defaults(self):
        """The engine's default tints for this map (the night one depends on the map id:
        rf4m.mlig_defaults)."""
        d = self.ed.doc
        return rf4m.mlig_defaults(data.base_map_id(d.base) if d is not None and d.base else None)

    def _set_tints(self, cols, label):
        if cols == self.ed.doc.map.mlig_colors():
            return
        self.ed.apply(label, "props", lambda: self.ed.doc.map.set_mlig_colors(cols))

    def _commit_tint_default(self, i):
        cols = self.ed.doc.map.mlig_colors()
        cols[i] = None if self.tints[i][0].get() else self._tint_defaults()[i]
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
        cur = cols[i] or self._tint_defaults()[i]
        res = colorchooser.askcolor(color="#%02x%02x%02x" % cur, title=f"{rf4m.MLIG_SLOTS[i]} tint")
        if res and res[0]:
            cols[i] = tuple(int(c) for c in res[0])
            self._set_tints(cols, f"Set {rf4m.MLIG_SLOTS[i]} tint")

    def _mtxn(self, delta):
        m = self.ed.doc.map
        idxs = [i for i, c in enumerate(m.chunks) if c.tag == b"MTXN"]
        if delta > 0 and len(idxs) >= 2:
            # the game draws layer 0 (ground) and 1 (overlay) only; a 3rd chunk makes the loader
            # overwrite the pointers after the two layer slots (rf4m.ENGINE_MAX_CHUNKS)
            self.ed.status("Two display layers is the most the game uses (ground + overlay)")
            return
        if delta > 0:
            src = m.chunks[idxs[-1]].payload if idxs else b"\0\0\0\0"
            self.ed.apply("Add display layer", "chunks",
                          lambda: m.add_chunk("MTXN", src, at=(idxs[-1] + 1) if idxs else 0))
        elif idxs:
            self.ed.apply("Remove display layer", "chunks", lambda: m.delete_chunk(idxs[-1]))


# --------------------------------------------------------------------------- #
MINIMAP_HIDDEN_SETTING = "map_minimap_hidden"     # settings.json: the minimap was hidden


def minimap_details(doc):
    """(details, note) text about the open map's HUD minimap for the Properties tab: the sheet,
    blank / maze pictures, fog of war, where an interior's NPC icons go, the other maps on the
    picture, and the save-state picture swaps."""
    # the game reads rf3MapMiniPos by the BASE id (a seasonal copy's own row is never used)
    mid = data.base_map_id(doc.base) if doc is not None and doc.base else None
    rec = minimap.record(mid) if mid is not None else None
    if rec is None:
        return "No minimap record for this map (not one of the game's map ids).", ""
    tex = minimap.texture(mid)
    blank = minimap.is_blank(mid) or minimap.is_composed(mid)
    others = [] if blank else [m for m in minimap.maps_on_sheet(minimap.effective_sheet(mid),
                                                                base_only=True) if m != mid]
    names = [map_names.map_file(m) or str(m) for m in others]
    lines = [f"Sheet {rec['sheet']} (resource {minimap.archive_id(mid)}); drawn: {tex}"]
    if minimap.is_blank(mid):
        lines.append("The HUD shows a blank picture for this map.")
    if minimap.is_composed(mid):
        lines.append("A Sharance Maze floor: the picture is put together at run time from "
                     "the mini_map_rnd_* tiles.")
    lines.append("Fog of war: " + ("a visit uncovers x %d, y %d, %d x %d" % rec["reveal"]
                                   if rec["reveal"] else "none (always fully shown)"))
    if rec["parent_sheet"] is not None:
        lines.append(f"NPCs inside are drawn on sheet {rec['parent_sheet']} "
                     f"({minimap.texture_for_sheet(rec['parent_sheet'])}) at "
                     f"{rec['icon'][0]}, {rec['icon'][1]} (slot {rec['icon_slot']})")
    if names:
        lines.append(f"{len(names)} other map(s) on this picture: " + ", ".join(names[:8])
                     + (" …" if len(names) > 8 else ""))
    var = minimap.variants(mid)
    note = ("Pictures by save state: " + "; ".join(f"{v['texture']} ({v['when']})" for v in var)) if var else ""
    return "\n".join(lines), note


class MinimapPanel(ttk.Frame):
    """The HUD minimap of the open map, docked under the sidebar tabs (shown whatever tab is
    open; Hide / Show minimap, remembered): the picture the game draws for its map id
    (rf4s_modkit.minimap), this map's footprint, the fog-of-war rectangle a visit reveals, the
    part the editor shows now, and the other rooms of the picture. A press or drag moves the
    editor's view there; a click on another room opens that map. The details are in the
    Properties tab."""

    WIDTH = 300                                 # the picture is shown this wide (512 px texture)

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        head = ttk.Frame(self)
        head.pack(fill="x", padx=4, pady=(4, 0))
        self.toggle_btn = ttk.Button(head, width=13, command=self.toggle)
        self.toggle_btn.pack(side="right")          # (packed first: the title never pushes it off)
        self.title = ttk.Label(head, font=("Segoe UI", 9, "bold"))
        self.title.pack(side="left")
        b = self.body = ttk.Frame(self)
        self.pic = tk.Canvas(b, width=self.WIDTH, height=self.WIDTH, highlightthickness=0,
                             bg="#1b1b22", cursor="crosshair")
        self.pic.pack(anchor="center", padx=4, pady=(2, 0))
        self.pic.bind("<ButtonPress-1>", self._press)
        self.pic.bind("<B1-Motion>", self._drag)       # drag: the editor follows the pointer
        self.pic.bind("<ButtonRelease-1>", self._release)
        self.pic.bind("<Motion>", self._hover)
        self.pic.bind("<Leave>", lambda _e: self._hover(None))
        self.hover_lbl = ttk.Label(b, font=ui.HINT_FONT, foreground=ui.GOOD)
        self.hover_lbl.pack(anchor="w", padx=4, pady=(0, 2))
        self._rooms = []                        # [(map name, canvas rect)] of the other rooms
        self._press_xy = self._press_room = None
        self._dragged = False
        self._photo = None
        self._shown = None                      # (map id, texture) the picture was built for
        self._scale = self.WIDTH / 512.0        # canvas px per texture px
        self._view_rect = None
        self._tick_on = False
        self._tick_id = None
        self.pic.bind("<Map>", lambda _e: self._start_tick(), add="+")
        self.bind("<Destroy>", self._stop_tick, add="+")
        try:
            self.hidden = bool(gamepaths.get_setting(MINIMAP_HIDDEN_SETTING, False))
        except Exception:  # noqa: BLE001 - no settings: shown
            self.hidden = False
        self._apply_hidden()

    def _apply_hidden(self):
        if self.hidden:
            self._stop_tick()
            self.body.pack_forget()
            self.toggle_btn.config(text="Show minimap")
        else:
            self.body.pack(fill="x")
            self.toggle_btn.config(text="Hide minimap")

    def toggle(self):
        """Hide / show the picture (the header stays); remembered in settings.json."""
        self.hidden = not self.hidden
        try:
            gamepaths.set_setting(MINIMAP_HIDDEN_SETTING, self.hidden)
        except OSError:
            pass                                # a read-only toolkit folder: just not kept
        self._apply_hidden()
        if not self.hidden:
            self.refresh()

    # ---- data --------------------------------------------------------------------------- #
    def _map_id(self):
        """The id whose minimap record the game uses: the base id (a seasonal copy's own
        rf3MapMiniPos row is never read)."""
        d = self.ed.doc
        return data.base_map_id(d.base) if d is not None and d.base else None

    def _to_canvas(self, mid, x, y):
        """Canvas px of a map position in sub-units (minimap.pos_to_sheet: drawn half-scale
        px, x2 = texture px)."""
        p = minimap.pos_to_sheet(mid, x, y)
        return None if p is None else (p[0] * 2 * self._scale, p[1] * 2 * self._scale)

    def refresh(self):
        c = self.pic
        mid = self._map_id()
        rec = minimap.record(mid) if mid is not None else None
        if rec is None:
            c.delete("all")
            self._photo = self._shown = None
            self._rooms = []
            self.title.config(text="Minimap (none)")
            return
        tex = minimap.texture(mid)
        self.title.config(text="Minimap")        # (the picture's name: Properties)
        if self.hidden:
            return                              # (built when shown again)
        if self._shown != (mid, tex):
            self._shown = (mid, tex)
            c.delete("all")
            self._photo = self._picture(tex)
            if self._photo is not None:
                c.create_image(0, 0, image=self._photo, anchor="nw", tags=("pic",))
            else:
                c.create_text(self.WIDTH // 2, self.WIDTH // 2, fill="#888",
                              text=f"{tex}.texture not found\n(game folder / Pillow)")
        self._draw_overlay(mid, rec)

    def _picture(self, tex):
        reader = self.ed.tex_reader
        if not render.HAS_PIL or reader is None or not tex:
            return None
        try:
            blob = reader(tex + ".texture")
            img = texture.decode_to_image(blob) if blob else None
        except Exception:  # noqa: BLE001 - no picture, the overlay still shows
            img = None
        if img is None:
            return None
        from PIL import ImageTk
        img = img.convert("RGBA")
        self._scale = self.WIDTH / float(img.width)
        img = img.resize((self.WIDTH, max(1, round(img.height * self._scale))))
        self.pic.config(height=img.height)
        return ImageTk.PhotoImage(img)

    def _draw_overlay(self, mid, rec):
        c = self.pic
        c.delete("ov")
        d = self.ed.doc
        if d is None or not d.grid:
            return
        W, H, _ = d.grid
        a, b = self._to_canvas(mid, 0, 0), self._to_canvas(mid, W * 8, H * 8)
        if a and b and (b[0] - a[0]) > 1 and (b[1] - a[1]) > 1:   # (blank / maze: no placement)
            c.create_rectangle(a[0], a[1], b[0], b[1], outline="#e02828", width=2, tags=("ov", "foot"))
        if rec["reveal"]:
            x, y, w, h = rec["reveal"]
            k = 2 * self._scale                 # drawn (half-scale) px, like the origin
            c.create_rectangle(x * k, y * k, (x + w) * k, (y + h) * k, outline="#c020c0",
                               width=2, dash=(4, 3), tags=("ov",))
        self._rooms = self._other_rooms(mid)
        for name, (x0, y0, x1, y1) in self._rooms:
            c.create_rectangle(x0, y0, x1, y1, outline="#8a7650", dash=(2, 3), tags=("ov", "room"))
        c.tag_lower("room")
        c.tag_raise("room", "pic") if c.find_withtag("pic") else None
        self._view_rect = None
        self._draw_view()

    def _other_rooms(self, mid):
        """[(MAP_* name, canvas rect)] of the other maps drawn on this picture (one per
        placement, from the base ids' records -- the ones the game reads; a seasonal family
        opens as the copy of the open map's season)."""
        if minimap.is_blank(mid) or minimap.is_composed(mid):
            return []
        own = data.map_id(self.ed.doc.base)
        season = own - mid if own is not None and 4 <= mid < 64 else 0
        sums = data.map_summaries()
        by_place = {}
        for m in minimap.maps_on_sheet(minimap.effective_sheet(mid), base_only=True):
            r = minimap.raw_record(m)
            name = map_names.map_file(m + season if 4 <= m < 64 else m)
            if not r or not r[7] or not r[8] or not name or m == mid:
                continue                        # no placement, or the open map
            by_place.setdefault(tuple(r[1:9]), []).append((m, name))
        out = []
        for group in by_place.values():
            m, name = group[0]
            wh = (sums.get(name) or (None, None, None))[2]
            if not wh:
                continue
            a, b = self._to_canvas(m, 0, 0), self._to_canvas(m, wh[0] * 8, wh[1] * 8)
            if a and b and b[0] - a[0] > 2 and b[1] - a[1] > 2:
                out.append((name, (a[0], a[1], b[0], b[1])))
        return out

    def room_at(self, x, y):
        """The other room under canvas point (x, y) (the smallest one when they nest), or None."""
        hits = [(r[2] - r[0]) * (r[3] - r[1]) for _n, r in self._rooms]
        best = None
        for (name, r), area in zip(self._rooms, hits):
            if r[0] <= x <= r[2] and r[1] <= y <= r[3] and (best is None or area < best[1]):
                best = (name, area)
        return best[0] if best else None

    def _hover(self, e):
        c = self.pic
        c.delete("hover")
        name = self.room_at(e.x, e.y) if e is not None else None
        if name is None:
            self.hover_lbl.config(text="")
            c.config(cursor="crosshair")
            return
        r = dict(self._rooms)[name]
        c.create_rectangle(*r, outline="#ffcc33", width=2, tags=("hover", "ov"))
        mid = map_names.map_id_for_file(name)
        place = map_names.map_name(mid) if mid is not None else None
        self.hover_lbl.config(text=f"Click to open {name}" + (f" ({place})" if place else ""))
        c.config(cursor="hand2")

    def _press(self, e):
        self._press_xy, self._dragged = (e.x, e.y), False
        self._press_room = self.room_at(e.x, e.y)
        if self._press_room is None:            # on this map / empty space: move the view there
            self._click(e)

    def _drag(self, e):
        if self._press_xy is None:
            return
        if not self._dragged and abs(e.x - self._press_xy[0]) < 4 and abs(e.y - self._press_xy[1]) < 4:
            return                              # still a click
        self._dragged = True
        self._click(e)

    def _release(self, _e):
        name = self._press_room if not self._dragged else None
        self._press_xy = self._press_room = None
        if name:                                # a click on another room: open it
            self.ed.open_map(name)

    def _draw_view(self):
        """The part of the map the editor shows now (cyan)."""
        mid = self._map_id()
        d = self.ed.doc
        if mid is None or d is None or not d.grid or minimap.record(mid) is None:
            return
        v = self.ed.view
        cv = v.canvas
        cp = v.cp
        x0, y0 = cv.canvasx(0) / cp, cv.canvasy(0) / cp
        x1, y1 = x0 + cv.winfo_width() / cp, y0 + cv.winfo_height() / cp
        W, H, _ = d.grid
        rect = (max(0, x0), max(0, y0), min(W, x1), min(H, y1))
        if rect == self._view_rect:
            return
        self._view_rect = rect
        a = self._to_canvas(mid, rect[0] * 8, rect[1] * 8)
        b = self._to_canvas(mid, rect[2] * 8, rect[3] * 8)
        self.pic.delete("view")
        if a and b and (b[0] - a[0]) > 1 and (b[1] - a[1]) > 1:
            self.pic.create_rectangle(a[0], a[1], b[0], b[1], outline="#1060ff", width=2, dash=(3, 3),
                                         tags=("view", "ov"))

    def _start_tick(self):
        if not self._tick_on:
            self._tick_on = True
            self._tick()

    def _tick(self):
        """Follow the editor's scrolling / zoom while the picture is shown."""
        self._tick_id = None
        if not self.pic.winfo_ismapped():
            self._tick_on = False
            return
        try:
            self._draw_view()
        except tk.TclError:
            pass
        self._tick_id = self.after(250, self._tick)

    def _stop_tick(self, e=None):
        """Cancel the pending tick (the panel is going away): a timer left pending when the
        window closes makes Tk drop its command before tkinter deletes it."""
        if e is not None and e.widget is not self:
            return
        tid, self._tick_id = getattr(self, "_tick_id", None), None
        self._tick_on = False
        if tid is not None:
            try:
                self.after_cancel(tid)
            except tk.TclError:
                pass

    def _click(self, e):
        """Centre the editor on the minimap point under the pointer (the inverse of
        pos_to_sheet); a press and every drag step of button 1 come here."""
        mid = self._map_id()
        r = minimap.raw_record(mid) if mid is not None else None
        d = self.ed.doc
        if r is None or d is None or not d.grid or not r[7] or not r[8]:
            return
        drawn_x = e.x / self._scale / 2.0
        drawn_y = e.y / self._scale / 2.0
        sx = (drawn_x - r[1]) * 4096.0 / r[7]
        sy = (drawn_y - r[2]) * 4096.0 / r[8]
        W, H, _ = d.grid
        tx = max(0.0, min(W - 1.0, sx / 8.0))           # (fractional tiles: a smooth drag)
        ty = max(0.0, min(H - 1.0, sy / 8.0))
        self.ed.view.center_on(tx, ty)
        self._view_rect = None
        self._draw_view()


# --------------------------------------------------------------------------- #
class EncountersTab(ui.ScrollFrame):
    """The area's Gen*.bin encounter table (a separate file from the map)."""

    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        b = self.body
        self.file_lbl = ttk.Label(b, font=ui.HINT_FONT, wraplength=320, justify="left")
        self.file_lbl.pack(anchor="w", padx=4, pady=(4, 0))
        # another room loads this Gen file too (areagroup: the game picks it by zone, not name)
        self.shared_file_lbl = ttk.Label(b, font=ui.HINT_FONT, foreground="#c60", wraplength=320,
                                         justify="left")
        self.shared_file_lbl.pack(anchor="w", padx=4)
        self._shared_cache = {}
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
        self.kind = ui.FilterCombo(f, data.gate_choices(), lambda _t: self._commit_gate(), width=30)
        ui.Tip(self.kind, "The gate actor. The two gates of each name differ only in HP; the "
                          "800 HP Void .. Affection Gates (375-382) glide between their "
                          "positions, the others stay put or, with 'teleports' ticked, teleport.")
        self.kind.grid(row=0, column=1, columnspan=3, sticky="we")
        self.v = {k: tk.StringVar() for k in ("weight", "cmin", "cmax", "delay", "level")}
        for r, c, lab, k, tip in (
                (1, 0, "weight", "weight", "Chance of this gate among its pattern's gates: each "
                                           "pattern spawns one gate when you enter the map."),
                (1, 2, "delay", "delay", "Respawn timer base in frames (60 = 1 s): the first wave "
                                         "comes after delay + 0..127 frames (32 less when that is "
                                         "over 32), later waves after (delay + 0..63) / 2 frames, "
                                         "at least 48."),
                (2, 0, "min", "cmin", "Wave size, lower end: the gate's first wave spawns min..max "
                                      "monsters at random; later waves add 1-2 at a time. No wave "
                                      "starts while fewer than min of the gate's 10 slots are "
                                      "free. Hard mode clips it to max."),
                (2, 2, "max", "cmax", "Most of this gate's monsters alive at once (and the largest "
                                      "wave). All the map's gates together hold at most 10 live "
                                      "monsters. Hard mode turns 4 into 3 and anything above 4 "
                                      "into 4."),
                (6, 0, "level", "level", "Gate level (header param_a): the gate is set to this "
                                         "level when it spawns (0 = keep its own), and its "
                                         "monsters that are 16 or more levels below the gate are "
                                         "raised to it. Each Prince 'Stronger Monsters' step "
                                         "scales it: level × (n + 1) + 100 × n. Shipped gates use "
                                         "60-280.")):
            ttk.Label(f, text=lab).grid(row=r, column=c, sticky="w")
            en = commit_entry(f, self.v[k], self._commit_gate, width=7)
            en.grid(row=r, column=c + 1, sticky="w", pady=1)
            ui.Tip(en, tip)
        # the gate's position as numbers -- also one off the map / off screen
        self.gx, self.gy = tk.StringVar(), tk.StringVar()
        for c, lab, var in ((0, "x", self.gx), (2, "y", self.gy)):
            ttk.Label(f, text=lab).grid(row=3, column=c, sticky="w")
            en = commit_entry(f, var, self._commit_gpos, width=7)
            en.grid(row=3, column=c + 1, sticky="w", pady=1)
            ui.Tip(en, "The gate's position in sub-units (8 per tile) -- type to move it, also "
                       "when it is off the map or off screen.")
        pr = ttk.Frame(f)
        pr.grid(row=4, column=0, columnspan=4, sticky="w")
        self._gpos_i = 0                         # which of the gate's positions the fields show
        self.gprev = ttk.Button(pr, text="‹", width=2, command=lambda: self._step_gpos(-1))
        self.gnext = ttk.Button(pr, text="›", width=2, command=lambda: self._step_gpos(1))
        self.gpos_lbl = ttk.Label(pr, font=ui.HINT_FONT)
        self.gprev.pack(side="left")
        self.gnext.pack(side="left")
        self.gpos_lbl.pack(side="left", padx=(4, 0))
        ui.Tip(self.gpos_lbl, "A gate can have several positions; the spawner picks one at random "
                              "when you enter the map. ‹ › step through them.\n"
                              "With 2 or more positions some gates keep moving: kinds 375-382 "
                              "(the 800 HP Void .. Affection Gates), when visible, glide from "
                              "position to position in list order and back to the first, about "
                              "4 s a leg whatever its length (a dashed line with arrows on the "
                              "map). A gate with 'teleports' ticked blinks out and reappears at "
                              "a random one of its positions every 6 s or so (dotted lines) -- "
                              "not kinds 375-382, which then jump to wrong places.")
        self.visible = tk.BooleanVar(value=False)
        vis = ttk.Checkbutton(f, text="visible gate", variable=self.visible, command=self._commit_gate)
        vis.grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.teleport = tk.BooleanVar(value=False)
        tp = ttk.Checkbutton(f, text="teleports", variable=self.teleport, command=self._commit_gate)
        tp.grid(row=5, column=2, columnspan=2, sticky="w", pady=(2, 0))
        self.teleport_cb = tp
        ui.Tip(tp, "Ticked: every 6 s or so the gate blinks out, stays away 1 s and reappears at a "
                   "random one of its positions (it can be the same one) -- the Rune Prana "
                   "gates. Needs 2 or more gate positions. Header flag high byte 1 (0x100).\n"
                   "Greyed out for the gliding kinds (375-382): a gate that glides breaks when it "
                   "also teleports, so pick the same gate with 1000 HP (383-390), as the game "
                   "does. Picking a gliding kind unticks it.")
        self.motion_lbl = ttk.Label(f, font=ui.HINT_FONT, foreground=ui.GOOD, wraplength=300,
                                    justify="left")
        self.motion_lbl.grid(row=8, column=0, columnspan=4, sticky="w")
        self.alt_lbl = ttk.Label(f, font=ui.HINT_FONT, wraplength=300, justify="left")
        self.alt_lbl.grid(row=7, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ui.Tip(self.alt_lbl, "Each monster a gate spawns comes from its roster or its alternate "
                             "roster, by the time of day: the roster 70 % of the time from 5:00 "
                             "to 10:59, 55 % 11:00-16:59, 45 % 17:00-22:59 and 30 % at night, "
                             "the alternate roster otherwise. Every shipped gate uses one block "
                             "for both, so the time of day changes nothing; this tab edits the "
                             "roster.")
        ui.Tip(vis, "Ticked: a gate you can see and break (header flag low byte 0).\n"
                    "Unticked: an invisible spawner -- the game spawns the gate hidden and "
                    "unhittable, and its monsters just appear (low byte 1; 700 of the game's "
                    "1224 gates are like that). A hidden gate never glides.")
        gb = ttk.Frame(g)
        gb.pack(fill="x", pady=(4, 0))
        ttk.Button(gb, text="Add (copy)", command=self._add_gate).pack(side="left")
        nb = ttk.Button(gb, text="New", command=self._new_gate)
        nb.pack(side="left", padx=(2, 0))
        ui.Tip(nb, "Add a gate with its own settings -- also to an empty table: a visible Gate in "
                   "the middle of the map (type x / y or drag it), one monster spawn point there "
                   "and one monster (the one picked in the roster box below, else an Orc), 2-4 "
                   "monsters per wave.")
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
        self.mpts = ttk.Treeview(g, columns=("i", "tile", "r"), show="headings", height=3,
                                 selectmode="browse")
        for c, t, w in (("i", "spawn point", 90), ("tile", "tile", 80), ("r", "radius", 60)):
            self.mpts.heading(c, text=t)
            self.mpts.column(c, width=w, anchor="w" if c != "r" else "e", stretch=(c == "tile"))
        self.mpts.pack(fill="x", pady=(4, 0))
        self.mpts.bind("<<TreeviewSelect>>", self._mpt_picked)
        rf = ttk.Frame(g)
        rf.pack(fill="x", pady=(2, 0))
        ttk.Label(rf, text="radius").pack(side="left")
        self.vrad = tk.StringVar()
        ren = commit_entry(rf, self.vrad, self._commit_radius, width=7)
        ren.pack(side="left", padx=(4, 0))
        ui.Tip(ren, "Scatter radius of the selected spawn point, in sub-units (8 per tile): each "
                    "monster appears at a random angle and distance below this from the point, "
                    "on a walkable tile (up to 63 random samples, then on the point itself). 0 = "
                    "always on the point. Only the low 16 bits are read.")
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
                "an orange G marks a visible gate's positions (over the gate itself when sprites "
                "are on), a gray G a hidden spawner's (the game draws no gate there); pink dots = "
                "monster spawn points (the selected gate's are outlined white; clicking empty map "
                "lets go of the gate). Drag them with the Select tool. Gates often share one roster, so a "
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
            self.file_lbl.config(text="The game spawns no monster gates on this map: with its "
                                      "area group (MGRP, Map tab) it loads no encounter table "
                                      "here -- only dungeon and field rooms have one.")
            self.shared_file_lbl.config(text="")
            self.roster.delete(*self.roster.get_children())
            self.mpts.delete(*self.mpts.get_children())
            self.share_lbl.config(text="")
            self.pts_lbl.config(text="")
            return
        n = sum(len(p) for p in doc.gen.patterns)
        self.file_lbl.config(text=f"{doc.gen_path.name if doc.gen_path else 'Gen*.bin'} · "
                                  f"{n} gate(s) in {len(doc.gen.patterns)} pattern(s)"
                                  + ("" if n else " -- empty: 'New' adds a first gate"))
        self.shared_file_lbl.config(text=self._shared_text(doc))
        for pi, ei, e in doc.gen.all_entries():
            nmon = sum(1 for s in e.spawns if gen.MONSTER_LO <= s.monster_id <= gen.MONSTER_HI)
            t.insert("", "end", iid=f"{pi}:{ei}", values=(data.gate_list_label(e), e.weight, nmon))
        gi = self.ed.gate_index
        if gi is not None and t.exists(f"{gi[0]}:{gi[1]}"):
            t.selection_set(f"{gi[0]}:{gi[1]}")
            t.see(f"{gi[0]}:{gi[1]}")
        self._show_gate()

    def _shared_text(self, doc):
        """'Also used by …' for a Gen file the game loads for other rooms too (cached per file)."""
        base = getattr(doc, "base", None)           # (None: a Gen file open on its own)
        fn = doc.gen_path.name if getattr(doc, "gen_path", None) else None
        if not base or not fn:
            return ""
        key = (fn.lower(), base)
        if key not in self._shared_cache:
            try:
                others = data.also_used_by("gen", fn, base)
                own = data.gen_name_for_id(areagroup.base_map_id(base))
            except Exception:  # noqa: BLE001
                others, own = [], fn
            txt = ""
            if own is None or own.lower() != fn.lower():
                txt = (f"This room has no gate table of its own: with its area group the game "
                       f"loads {fn} here. ")
            if others:
                txt += (f"Also used by: {', '.join(others)} -- the game loads this file for "
                        f"{'that room' if len(others) == 1 else 'those rooms'} too, so edits "
                        f"here change {'its' if len(others) == 1 else 'their'} gates as well.")
            self._shared_cache[key] = txt.strip()
        return self._shared_cache[key]

    def _show_gate(self):
        e = self._entry()
        r = self.roster
        keep = r.selection()
        r.delete(*r.get_children())
        self._show_mpts(e)
        if e is None:
            for v in self.v.values():
                v.set("")
            self.visible.set(False)
            self.teleport.set(False)
            self.teleport_cb.state(["disabled"])
            self.motion_lbl.config(text="")
            self.kind.var.set("")
            self.share_lbl.config(text="Select a gate.")
            self.pts_lbl.config(text="")
            self.alt_lbl.config(text="")
            self._show_gpos(None)
            return
        self.kind.var.set(data.gate_label(e.gate_kind))
        self.v["weight"].set(str(e.weight))
        self.v["cmin"].set(str(e.hdr.count_min))
        self.v["cmax"].set(str(e.hdr.count_max))
        self.v["delay"].set(str(e.hdr.spawn_delay))
        self.v["level"].set(str(e.hdr.param_a))
        self.visible.set(not e.hdr.flag & 0xFF)
        self.teleport.set(bool(e.hdr.flag >> 8))
        # a gliding kind can't teleport: greyed out (left on while a loaded file has it, to untick)
        glides = gen.GLIDE_KIND_LO <= e.gate_kind <= gen.GLIDE_KIND_HI
        self.teleport_cb.state(["disabled"] if glides and not self.teleport.get() else ["!disabled"])
        self.motion_lbl.config(text=gen.gate_motion_text(e))
        if e.roster_alt is e.roster:
            self.alt_lbl.config(text="Alternate roster: the same as the roster.", foreground="")
        else:
            alt = ", ".join(f"{data.actor_name(s.monster_id) or s.monster_id}" for s in e.roster_alt.spawns)
            self.alt_lbl.config(text=f"Alternate roster (differs): {alt or '(empty)'}", foreground="#c60")
        for k, s in enumerate(e.spawns):
            ok = gen.MONSTER_LO <= s.monster_id <= gen.MONSTER_HI
            r.insert("", "end", iid=str(k), values=(f"{s.monster_id}  {data.actor_name(s.monster_id) or '?'}"
                                                    + ("" if ok else "  (not a monster)"),
                                                    s.pick_weight, " ".join(map(str, s.weights))))
        if keep and r.exists(keep[0]):
            r.selection_set(keep[0])
        g = self.ed.doc.gen
        shared = [n for n, blk in (("settings", "hdr"), ("roster", "roster"),
                                   ("gate positions", "gate_pos"), ("monster points", "mon_pos"))
                  if sum(1 for _p, _e, o in g.all_entries() if getattr(o, blk) is getattr(e, blk)) > 1]
        self.share_lbl.config(text=("Shares its " + ", ".join(shared) + " with other gates.") if shared else "")
        self.pts_lbl.config(text=f"{len(e.gate_pos.points)} gate position(s), "
                                 f"{len(e.mon_pos.points)} monster point(s)")
        self._show_gpos(e)

    def _show_mpts(self, e):
        """The selected gate's monster spawn points with their scatter radius."""
        t = self.mpts
        keep = t.selection()
        t.delete(*t.get_children())
        if e is None or self.ed.doc is None or self.ed.doc.gen is None:
            self.vrad.set("")
            return
        for i, (off, x, y) in enumerate(self.ed.doc.gen.monster_positions_off(e)):
            t.insert("", "end", iid=str(off), values=(f"#{i + 1}", f"({x >> 3}, {y >> 3})",
                                                      e.mon_pos.points[i][2] & 0xFFFF))
        sel = getattr(self.ed, "sel", None)
        pick = str(sel[1]) if sel and sel[0] == "mpos" and t.exists(str(sel[1])) else (
            keep[0] if keep and t.exists(keep[0]) else None)
        if pick is None and t.get_children():
            pick = t.get_children()[0]
        if pick is not None:
            t.selection_set(pick)
            self.vrad.set(str(t.set(pick, "r")))
        else:
            self.vrad.set("")

    def _mpt_index(self):
        """(entry, index) of the spawn point selected in the list, or (None, None)."""
        e, s = self._entry(), self.mpts.selection()
        if e is None or not s:
            return None, None
        offs = [off for off, _x, _y in self.ed.doc.gen.monster_positions_off(e)]
        return (e, offs.index(int(s[0]))) if int(s[0]) in offs else (None, None)

    def _mpt_picked(self, _e=None):
        s = self.mpts.selection()
        if not s:
            return
        self.vrad.set(str(self.mpts.set(s[0], "r")))
        k = ("mpos", int(s[0]))
        if hasattr(self.ed, "select") and getattr(self.ed, "sel", None) != k:
            self.ed.select(k)

    def _commit_radius(self):
        e, i = self._mpt_index()
        r = ui.to_int(self.vrad.get())
        if e is None or r is None or not 0 <= r <= 0xFFFF or (e.mon_pos.points[i][2] & 0xFFFF) == r:
            return
        pi, ei = self.ed.gate_index
        self.ed.apply(f"Set spawn point radius {r}", "gen",
                      lambda: self.ed.doc.gen.set_monster_radius(self.ed.doc.gen.patterns[pi][ei], i, r))

    def _gpos_list(self, e=None):
        """[(offset, x, y)] of the gate's positions ([] without a gate)."""
        e = e if e is not None else self._entry()
        doc = self.ed.doc
        if e is None or doc is None or doc.gen is None:
            return []
        return doc.gen.gate_positions_off(e)

    def _show_gpos(self, e):
        """x / y fields for one of the gate's positions: the one picked on the map, else the
        one shown before."""
        pts = self._gpos_list(e)
        sel = getattr(self.ed, "sel", None)
        if sel and sel[0] == "gpos":
            hit = next((k for k, (off, _x, _y) in enumerate(pts) if off == sel[1]), None)
            if hit is not None:
                self._gpos_i = hit
        self._gpos_i = min(self._gpos_i, max(0, len(pts) - 1))
        many = len(pts) > 1
        for w in (self.gprev, self.gnext):
            w.state(["!disabled"] if many else ["disabled"])
        if not pts:
            self.gx.set("")
            self.gy.set("")
            self.gpos_lbl.config(text="")
            return
        _off, x, y = pts[self._gpos_i]
        self.gx.set(str(x))
        self.gy.set(str(y))
        tx, ty = x >> 3, y >> 3
        grid = getattr(self.ed.doc, "grid", None)       # None: a Gen file open without its map
        off_map = grid is not None and not (0 <= tx < grid[0] and 0 <= ty < grid[1])
        self.gpos_lbl.config(text=(f"position {self._gpos_i + 1} of {len(pts)} · " if many else "")
                             + f"tile ({tx}, {ty})" + ("  off the map" if off_map else ""))

    def _gpos_key(self):
        pts = self._gpos_list()
        return ("gpos", pts[self._gpos_i][0]) if pts else None

    def _step_gpos(self, d):
        pts = self._gpos_list()
        if not pts:
            return
        self._gpos_i = (self._gpos_i + d) % len(pts)
        k = self._gpos_key()
        if hasattr(self.ed, "select") and getattr(self.ed, "sel", None) != k:
            self.ed.select(k)                   # also refreshes the fields
        self._show_gpos(self._entry())

    def _commit_gpos(self):
        k = self._gpos_key()
        x, y = ui.to_int(self.gx.get()), ui.to_int(self.gy.get())
        if k is None or x is None or y is None or not (0 <= x <= 0xFFFF and 0 <= y <= 0xFFFF):
            return                              # stored as u16
        cur = self._gpos_list()[self._gpos_i][1:]
        if (x, y) == tuple(cur):
            return
        if hasattr(self.ed, "set_position_edit"):
            self.ed.set_position_edit(k, (x, y))
        else:                                   # the Gen file viewer: the same edit, by hand
            g = self.ed.doc.gen
            self.ed.apply("Move gate position", "gen", lambda: g.set_position(k[1], x, y))

    def _gate_picked(self, _e=None):
        s = self.gates.selection()
        if s:
            pi, ei = (int(x) for x in s[0].split(":"))
            if (pi, ei) != self.ed.gate_index:
                self.ed.set_active_gate((pi, ei))
            self._show_gate()
        self.ed._update_gate_focus()            # the outline follows the list's selection

    def _commit_gate(self):
        e = self._entry()
        if e is None:
            return
        kind = data.leading_int(self.kind.var.get())
        vals = {k: ui.to_int(v.get()) for k, v in self.v.items()}
        if kind is None or None in vals.values():
            return
        # visible = flag low byte 0; hidden keeps its own non-zero low byte (else 1)
        low = e.hdr.flag & 0xFF
        high = (e.hdr.flag & 0xFF00) or gen.TELEPORT_FLAG
        # picking a gliding kind unticks 'teleports' (the two break each other)
        tele = self.teleport.get() and not gen.GLIDE_KIND_LO <= kind <= gen.GLIDE_KIND_HI
        flag = (high if tele else 0) | (0 if self.visible.get() else (low or 1))
        cur = (e.gate_kind, e.weight, e.hdr.count_min, e.hdr.count_max, e.hdr.spawn_delay, e.hdr.flag,
               e.hdr.param_a)
        new = (kind & 0xFFFF, vals["weight"] & 0xFFFF, vals["cmin"] & 0xFF, vals["cmax"] & 0xFF,
               vals["delay"] & 0xFFFF, flag, vals["level"] & 0xFFFF)
        if cur == new:
            return
        pi, ei = self.ed.gate_index

        def do():
            g = self.ed.doc.gen
            ent = g.patterns[pi][ei]
            g.set_gate_kind(pi, ei, new[0])
            g.set_weight(pi, ei, new[1])
            g.set_hdr(ent, count_min=new[2], count_max=new[3], spawn_delay=new[4], flag=new[5],
                      param_a=new[6])
        self.ed.apply(f"Edit gate {pi}:{ei}", "gen", do)

    def _new_gate(self):
        """A gate with fresh blocks (gen.GenTable.new_gate): the first one of an empty table, or
        one more that shares nothing. Pattern 0 (every shipped file has at most one)."""
        doc = self.ed.doc
        if doc is None or doc.gen is None:
            self.ed.status("This map has no encounter table to add a gate to.")
            return
        grid = getattr(doc, "grid", None)
        x, y = ((grid[0] // 2) * 8 + 4, (grid[1] // 2) * 8 + 4) if grid else (64, 64)
        mid = data.leading_int(self.mon.var.get())
        mid = mid if mid is not None and gen.MONSTER_LO <= mid <= gen.MONSTER_HI else gen.MONSTER_LO
        if self.ed.apply("New gate", "gen", lambda: doc.gen.new_gate(x, y, mid)):
            self.ed.set_active_gate((0, len(self.ed.doc.gen.patterns[0]) - 1))
            self.ed.status(f"Added a gate at tile ({x >> 3}, {y >> 3}) with "
                           f"{data.actor_name(mid) or mid} -- move it and its spawn point into place")

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
            g.set_spawn_pick_weight(sp, v[1])
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
                  "object": True, "decoration": True, "sprites": True, "labels": False,
                  "sprite_borders": True, "gate_art": True, "mapj": True, "dest": True, "si": True,
                  "gates": True, "spawns": False, "stamps": True}
LAYER_GROUPS = {"attr": "bg", "edges": "bg", "grid": "grid", "trigger": "ent", "actor": "ent",
                "object": "ent", "decoration": "ent", "sprites": "ent", "labels": "ent",
                "sprite_borders": "ent", "gate_art": "gate", "mapj": "warp", "dest": "dest", "si": "si", "gates": "gate", "spawns": "spawn",
                "stamps": "stamp"}
LAYER_NAMES = {0: "0 ground", 1: "1 overlay"}
VIEW_SETTING = "map_view"      # settings.json key: the View tab's choices, kept across maps and runs
FLAGS_NONE = "(all objects)"
FLAGS_LIVE = "the running game"


class ViewTab(ui.ScrollFrame):
    def __init__(self, parent, ed):
        super().__init__(parent)
        self.ed = ed
        b = self.body
        self.vars = {}
        self.saved = self._load_saved()
        saved_layers = self.saved.get("layers", {})
        L = section(b, "Layers")

        def cb(parent, key, text, r, c, color=None):
            v = self.vars.setdefault(key, tk.BooleanVar(value=bool(saved_layers.get(key, LAYER_DEFAULTS[key]))))
            w = ttk.Checkbutton(parent, text=text, variable=v, command=lambda: ed.set_layer(key, v.get()))
            w.grid(row=r, column=2 * c + 1, sticky="w", padx=(0, 8))
            if color:
                tk.Frame(parent, bg=color, width=10, height=10).grid(row=r, column=2 * c, padx=(0, 3))
            return w
        cb(L, "attr", "ATTR fill", 0, 0)
        cb(L, "edges", "cell edges", 0, 1)
        L.columnconfigure(3, weight=1)
        ttk.Label(L, text="Entities", font=ui.HINT_FONT).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        cb(L, "trigger", "forage / triggers", 2, 0, attrs.CAT_COLOR["forage"])
        cb(L, "actor", "actors", 2, 1, attrs.CAT_COLOR["actor"])
        cb(L, "object", "objects", 3, 0, attrs.CAT_COLOR["object"])
        cb(L, "decoration", "decorations", 3, 1, attrs.CAT_COLOR["decoration"])
        ui.Tip(cb(L, "sprites", "draw sprites", 4, 0),
               "Draw each object's sprite where and as large as the game draws it (the texture's "
               "own quad and crop, scaled by the record's f6), in the game's depth order, right on "
               "the ground. Objects without such a sprite keep their marker.")
        cb(L, "labels", "name labels", 4, 1)
        ui.Tip(cb(L, "sprite_borders", "sprite borders", 5, 0),
               "A red border around every drawn sprite, above the ATTR fill, so each object's "
               "full extent shows even where its art is faint, invisible or covered.")
        ui.Tip(cb(L, "gate_art", "draw gates", 5, 1),
               "Draw each visible monster gate as the game shows it (the swirling orb). "
               "Untick for just the G markers (orange = visible gate, gray = hidden spawner).")
        ttk.Label(L, text="Other", font=ui.HINT_FONT).grid(row=6, column=0, columnspan=4, sticky="w", pady=(4, 0))
        cb(L, "mapj", "warps", 7, 0, render.WARP_COLOR)
        cb(L, "dest", "warp destinations", 7, 1)
        cb(L, "si", "search spots", 8, 0, render.SI_COLOR)
        cb(L, "gates", "monster gates", 8, 1, render.GATE_COLOR)
        cb(L, "spawns", "script spawns", 9, 0, render.SPAWN_COLOR)
        cb(L, "grid", "tile grid lines", 9, 1)
        ui.Tip(cb(L, "stamps", "object collision", 10, 0, render.STAMP_COLOR),
               "Hatched: the tiles the placed objects (trees, rocks, stones ...) stamp into the "
               "ATTR grid when the room loads -- collision the map file does not contain. "
               "Magenta = the object blocks the player there (tree trunks, rocks, the invisible "
               "wall); green = the object makes the tile walkable (the airship gangway lays a "
               "path over walls); grey = marked only, walking unchanged (a tree's canopy ring "
               "carries just the footprint marker 0x8000000). "
               "Shown for the flag state chosen below; Alt over a tile names the object.")
        self.rt_tips = tk.BooleanVar(value=bool(self.saved.get("runtime_tips", False)))
        rt = ttk.Checkbutton(L, text="pop-up info on the game's built-in warps",
                             variable=self.rt_tips, command=lambda: ed.set_runtime_tips(self.rt_tips.get()))
        rt.grid(row=11, column=0, columnspan=4, sticky="w")
        ui.Tip(rt, "The dashed warps and walls the game adds by itself cover big areas, so their "
                   "explanation no longer pops up whenever the mouse passes over them. Off (the "
                   "default): hold Shift over one to see it -- the status line says when the "
                   "pointer is on one. On: it pops up on hover like the objects' tooltips.")
        hint(L, "Script spawns are placed by the map's event script (rf3.mc), not the map file: "
                "NPCs (round) and map objects (square, drawn with their sprite); the "
                "first time they are shown the script is scanned.", wrap=300).grid(
            row=12, column=0, columnspan=4, sticky="w", pady=(2, 0))
        # ---- flag state ----
        S = section(b, "Show objects as in")
        self.flagsrc = tk.StringVar(value=FLAGS_NONE)
        self.flagsrc_cb = ttk.Combobox(S, textvariable=self.flagsrc, width=26, state="readonly",
                                       postcommand=self.refresh_flag_sources)
        self.flagsrc_cb.grid(row=0, column=0, sticky="w")
        self.flagsrc_cb.bind("<<ComboboxSelected>>", lambda _e: ed.set_flag_source(self.flagsrc.get()))
        ui.Tip(self.flagsrc_cb, "Which game flags decide what is shown. Bridges, walls and other "
                                "objects gated by a flag appear or vanish as they would in that "
                                "save or in the game that is running now; hidden ones become a "
                                "dashed outline.")
        bb = ttk.Frame(S)
        bb.grid(row=0, column=1, sticky="w", padx=(4, 0))
        b_re = ttk.Button(bb, text="Reload", width=7, command=lambda: ed.set_flag_source(self.flagsrc.get()))
        b_re.pack(side="left")
        ui.Tip(b_re, "Read the flags again (after saving, or after the game changed map).")
        b_br = ttk.Button(bb, text="File…", width=6, command=ed.browse_flag_save)
        b_br.pack(side="left", padx=(4, 0))
        ui.Tip(b_br, "Pick a slot save (rf4_sNN.sav) from anywhere.")
        self.flagstatus = ttk.Label(S, font=ui.HINT_FONT, wraplength=300, justify="left")
        self.flagstatus.grid(row=1, column=0, columnspan=2, sticky="w")
        hint(S, "Scenery and objects (bridges, walls, trees) follow their flag every frame, so "
                "they appear or vanish in game the moment a script sets it; chests, crates and "
                "other actors check theirs when the room loads.", wrap=300).grid(
            row=2, column=0, columnspan=2, sticky="w")
        # ---- ground display ----
        G = section(b, "Ground texture")
        ttk.Label(G, text="show").grid(row=0, column=0, sticky="w")
        self.ground = tk.StringVar(value=self.saved.get("ground", "all"))
        self.ground_cb = ttk.Combobox(G, textvariable=self.ground, values=["off", "all"], width=12,
                                      state="readonly")
        self.ground_cb.grid(row=0, column=1, sticky="w")
        self.ground_cb.bind("<<ComboboxSelected>>", lambda _e: ed.set_ground_display(self.ground.get()))
        self.scenery = tk.BooleanVar(value=bool(self.saved.get("scenery", True)))
        sc_cb = ttk.Checkbutton(G, text="scenery (the map's over-model)", variable=self.scenery,
                                command=lambda: ed.set_scenery(self.scenery.get()))
        sc_cb.grid(row=3, column=0, columnspan=2, sticky="w")
        ui.Tip(sc_cb, "The pre-rendered billboard cards (statues, railings, rooftops, trees) the "
                      "game draws over the ground, placed where the model's bones put them.")
        om = ttk.Frame(G)
        om.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        b1 = ttk.Button(om, text="Make over-model empty…", command=ed.blank_overmodel)
        b1.pack(side="left")
        ui.Tip(b1, "Replace this map's over-model file with the game's own empty one "
                   "(MAP_FIELD_43.model, which 164 maps already use), so no scenery is drawn over "
                   "the ground. Asks first and lists every map that shares the file -- they all "
                   "change. The original is kept in ModdingBackup.")
        b2 = ttk.Button(om, text="Restore…", command=ed.restore_overmodel)
        b2.pack(side="left", padx=(4, 0))
        ui.Tip(b2, "Put this map's original over-model back (asks first).")
        ttk.Label(G, text="ATTR opacity").grid(row=1, column=0, sticky="w")
        self.alpha = tk.IntVar(value=int(self.saved.get("attr_alpha", 180)))
        sc = ttk.Scale(G, from_=0, to=255, orient="horizontal", length=150, variable=self.alpha)
        sc.grid(row=1, column=1, sticky="w")
        sc.bind("<ButtonRelease-1>", lambda _e: ed.set_attr_alpha(self.alpha.get()))
        ttk.Label(G, text="darken").grid(row=4, column=0, sticky="w")
        self.dim = tk.IntVar(value=int(self.saved.get("ground_dim", 25)))
        dm = ttk.Scale(G, from_=0, to=80, orient="horizontal", length=150, variable=self.dim,
                       command=lambda _v: self.dim.set(int(float(_v))))
        dm.grid(row=4, column=1, sticky="w")
        dm.bind("<ButtonRelease-1>", lambda _e: ed.set_ground_dim(self.dim.get()))
        ui.Tip(dm, lambda: f"Darken the ground texture by {self.dim.get()} % so the objects on it "
                           "stand out (0 = as the game draws it).")
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

    @staticmethod
    def _load_saved():
        d = gamepaths.get_setting(VIEW_SETTING)
        return d if isinstance(d, dict) else {}

    def remember(self):
        """Store the layer toggles and ground display in settings.json, so the next map and
        the next start open the same way."""
        self.saved.update(layers=self.layers(), scenery=self.scenery.get(),
                          runtime_tips=self.rt_tips.get(),
                          attr_alpha=self.alpha.get(), ground=self.ground.get(),
                          ground_dim=self.dim.get())
        try:
            gamepaths.set_setting(VIEW_SETTING, self.saved)
        except OSError:
            pass                                # a read-only toolkit folder: just don't keep them

    def refresh_flag_sources(self):
        vals = [FLAGS_NONE, FLAGS_LIVE] + [p.name for p in data.slot_saves()]
        cur = self.flagsrc.get()
        if cur not in vals:
            vals.append(cur)
        self.flagsrc_cb["values"] = vals

    def set_available_layers(self, layers):
        vals = ["off", "all"] + [LAYER_NAMES.get(l, str(l)) for l in layers]
        self.ground_cb["values"] = vals
        if self.saved.get("ground") in vals:    # the saved choice, where this map has that layer
            self.ground.set(self.saved["ground"])
        elif self.ground.get() not in vals:
            self.ground.set("all" if layers else "off")
        gv = [LAYER_NAMES.get(l, str(l)) for l in layers] or ["0 ground"]
        self.glayer_cb["values"] = gv
        if self.glayer.get() not in gv:
            self.glayer.set(gv[0])
        self.glayer_cb.config(state="readonly" if len(gv) > 1 else "disabled")


# --------------------------------------------------------------------------- #
_REF = (("mobj", re.compile(r"MOBJ #(\d+)")), ("mobj", re.compile(r"^chest #(\d+)")),
        ("warp", re.compile(r"warp #(\d+)")),
        ("si", re.compile(r"search spot #(\d+)")),
        ("gpos", re.compile(r"gate position \(Gen record @0x([0-9a-f]+)\)")),
        ("mpos", re.compile(r"monster spawn point \(Gen record @0x([0-9a-f]+)\)")))


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
        self.tree.tag_configure("INFO", foreground="#667")
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        self.detail = tk.Text(self, height=7, wrap="word", font=ui.HINT_FONT, relief="flat")
        self.detail.pack(fill="x", padx=4, pady=4)
        self.detail.configure(state="disabled")
        self.issues = []
        hint(self, "ERROR = the game crashes, drops data or draws nothing. WARN = it loads, but "
                   "probably not the way you expect. INFO = worth knowing, may well be intended. "
                   "Select an issue to jump to its object.").pack(
            anchor="w", padx=4, pady=(0, 4))

    def run(self):
        self.issues = self.ed.validate()
        t = self.tree
        t.delete(*t.get_children())
        for k, (sev, where, msg) in enumerate(self.issues):
            t.insert("", "end", iid=str(k), text=f"{sev} {where}", values=(msg,), tags=(sev,))
        n_err = sum(1 for s, _w, _m in self.issues if s == "ERROR")
        n_info = sum(1 for s, _w, _m in self.issues if s == "INFO")
        n_iss = len(self.issues) - n_info
        text = ("No problems found." if not n_iss else f"{n_iss} issue(s), {n_err} fatal")
        if n_info:
            text += f" · {n_info} note(s)"
        self.summary.config(text=text,
                            foreground="#c22" if n_err else (ui.GOOD if not n_iss else "#b70"))
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
            if m and where in ("map", "search items", "monster gates"):
                self.ed.select((kind, int(m.group(1), 16 if kind in ("gpos", "mpos") else 10)),
                               center=True)
                return
